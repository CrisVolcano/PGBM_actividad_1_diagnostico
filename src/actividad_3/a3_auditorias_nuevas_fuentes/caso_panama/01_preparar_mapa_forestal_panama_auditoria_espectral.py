from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import sys
import traceback
from typing import Any

import geopandas as gpd
import pandas as pd
import yaml

try:
    import fiona
except Exception:  # pragma: no cover
    fiona = None


# =============================================================================
# Preparacion de datos Panama para auditoria espectral
# =============================================================================
# Este script adapta el primer paso metodologico de a3_auditorias_nuevas_fuentes:
# normalizar una fuente puntual para dejarla lista para auditoria espectral.
#
# Caso Panama:
#   Fuente: MIAMBIENTE - Cultivos Mapa Panama
#   id_fuente: 15
#   Entrada: puntos seleccionados del sampling del mapa forestal Panama 2021
#
# Operaciones principales:
# 1. Lee una capa puntual del GeoPackage de sampling.
# 2. Valida geometria puntual y campos raster/clase.
# 3. Reproyecta a EPSG:4326.
# 4. Crea Longitud y Latitud con precision configurable.
# 5. Agrega metadatos de fuente, pais y anio.
# 6. Mapea class_value/class_name a Clase/nombre_clase.
# 7. Deriva GranClase/nombre_gran_clase desde reglas del YAML.
# 8. Marca nulos tematicos y clases sin grupo para revision.
# 9. Exporta un GeoPackage normalizado.
# =============================================================================


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
DEFAULT_CONFIG_RELATIVE = (
    "config/a3_auditorias_nuevas_fuentes/caso_panama/"
    "config_mapa_forestal_panama_2021.yaml"
)

OUTPUT_COLUMNS = [
    "id_registro",
    "id_muestra_original",
    "Fuente",
    "id_fuente",
    "Pais_es",
    "Pais_cod3",
    "Año",
    "Longitud",
    "Latitud",
    "Clase",
    "GranClase",
    "nombre_clase",
    "nombre_gran_clase",
    "revision_nulos_tematicos",
    "motivo_revision",
    "candidate_id",
    "raster_value",
    "class_name_en",
    "stratum_id",
    "distance_scenario_m",
    "selection_status",
    "protected",
    "nearest_neighbor_m",
    "geometry",
]

THEMATIC_COLUMNS = ["Clase", "GranClase", "nombre_clase", "nombre_gran_clase"]


def cargar_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el YAML requerido: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"El YAML no contiene un diccionario valido: {path}")
    return data


def resolver_config_path(config_arg: str | Path) -> Path:
    path = Path(config_arg)
    if path.is_absolute():
        return path.resolve()

    cwd_path = (Path.cwd() / path).resolve()
    if cwd_path.exists():
        return cwd_path

    project_path = (PROJECT_DIR / path).resolve()
    if project_path.exists():
        return project_path

    return (SCRIPT_DIR / path).resolve()


def resolver_project_root(config: dict[str, Any], config_path: Path) -> Path:
    paths_cfg = config.get("paths", {})
    if isinstance(paths_cfg, dict) and paths_cfg.get("project_root"):
        root = Path(paths_cfg["project_root"])
        return root.resolve() if root.is_absolute() else (config_path.parent / root).resolve()
    return PROJECT_DIR


def resolver_ruta(path_value: str | Path, base_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def listar_capas(gpkg_path: Path) -> list[str]:
    if fiona is None:
        return []
    return list(fiona.listlayers(gpkg_path))


def resolver_capa(gpkg_path: Path, layer: str | None) -> str | None:
    if layer:
        return layer

    layers = listar_capas(gpkg_path)
    if len(layers) == 1:
        return layers[0]

    if len(layers) > 1:
        raise ValueError(
            "El GeoPackage tiene varias capas. Indique input_layer en el YAML. "
            f"Capas disponibles: {layers}"
        )

    return None


def crear_id_registro(n: int, id_fuente: int) -> list[str]:
    return [f"SRC{id_fuente:02d}_{i:07d}" for i in range(1, n + 1)]


def validar_entrada(gdf: gpd.GeoDataFrame, required_fields: list[str]) -> None:
    if gdf.empty:
        raise ValueError("La capa de entrada no contiene registros.")

    if gdf.crs is None:
        raise ValueError("La capa de entrada no tiene CRS definido.")

    missing = [field for field in required_fields if field not in gdf.columns]
    if missing:
        raise ValueError(
            f"Faltan campos requeridos: {missing}. "
            f"Columnas disponibles: {list(gdf.columns)}"
        )

    null_geom = int(gdf.geometry.isna().sum())
    empty_geom = int(gdf.geometry.is_empty.sum())
    if null_geom or empty_geom:
        raise ValueError(
            "La capa contiene geometrías nulas o vacías. "
            f"Nulas: {null_geom:,}. Vacías: {empty_geom:,}."
        )

    geom_types = set(gdf.geometry.geom_type.dropna().unique())
    allowed = {"Point"}
    if not geom_types.issubset(allowed):
        raise ValueError(
            "La capa debe contener solamente geometrías Point. "
            f"Tipos encontrados: {sorted(geom_types)}"
        )


def construir_lookup_gran_clase(class_groups: list[dict[str, Any]]) -> dict[int, tuple[int, str]]:
    lookup: dict[int, tuple[int, str]] = {}
    for group in class_groups:
        code = int(group["code"])
        name = str(group["name"]).strip()
        for value in group.get("class_values", []):
            class_value = int(value)
            if class_value in lookup:
                previous = lookup[class_value]
                raise ValueError(
                    f"La clase {class_value} aparece en mas de una GranClase: "
                    f"{previous[0]} y {code}"
                )
            lookup[class_value] = (code, name)
    return lookup


def validar_config(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    prep = config.get("preparation", {})
    source = config.get("source", {})
    fields = prep.get("fields", {})

    required_sections = {
        "preparation": prep,
        "source": source,
        "preparation.fields": fields,
    }
    for label, section in required_sections.items():
        if not isinstance(section, dict):
            raise ValueError(f"La seccion {label} no es valida.")

    required_field_keys = ["original_id", "class_code", "class_name"]
    missing_field_keys = [key for key in required_field_keys if not fields.get(key)]
    if missing_field_keys:
        raise ValueError(f"Faltan llaves requeridas en preparation.fields: {missing_field_keys}")

    class_groups = prep.get("class_groups", [])
    if not isinstance(class_groups, list) or not class_groups:
        raise ValueError("Debe configurar preparation.class_groups.")

    return {
        "input_gpkg": resolver_ruta(prep["input_gpkg"], project_root),
        "input_layer": prep.get("input_layer"),
        "output_gpkg": resolver_ruta(prep["output_gpkg"], project_root),
        "output_layer": str(prep.get("output_layer", "preparacion_mapa_forestal_panama_2021")),
        "output_crs": str(prep.get("output_crs", "EPSG:4326")),
        "coordinate_precision": int(prep.get("coordinate_precision", 6)),
        "overwrite": bool(prep.get("overwrite", True)),
        "source": {
            "id_fuente": int(source["id_fuente"]),
            "fuente_reporte": str(source["fuente_reporte"]),
            "pais_es": str(source.get("pais_es", "Panamá")),
            "pais_cod3": str(source.get("pais_cod3", "PAN")),
            "anio": int(source.get("anio", 2021)),
        },
        "fields": {key: str(value) for key, value in fields.items() if value is not None},
        "class_group_lookup": construir_lookup_gran_clase(class_groups),
    }


def normalizar_panama(gdf: gpd.GeoDataFrame, cfg: dict[str, Any]) -> gpd.GeoDataFrame:
    fields = cfg["fields"]
    required = [
        fields["original_id"],
        fields["class_code"],
        fields["class_name"],
    ]
    optional_fields = [
        fields.get(key)
        for key in [
            "candidate_id",
            "class_name_en",
            "raster_value",
            "stratum_id",
            "distance_scenario_m",
            "selection_status",
            "protected",
            "nearest_neighbor_m",
        ]
        if fields.get(key)
    ]
    validar_entrada(gdf, required + optional_fields)

    gdf_out = gdf.copy()
    if gdf_out.crs.to_string() != cfg["output_crs"]:
        gdf_out = gdf_out.to_crs(cfg["output_crs"])

    source = cfg["source"]
    decimals = cfg["coordinate_precision"]
    class_group_lookup = cfg["class_group_lookup"]

    gdf_out["id_registro"] = crear_id_registro(len(gdf_out), source["id_fuente"])
    gdf_out["id_muestra_original"] = gdf_out[fields["original_id"]].astype("string")
    gdf_out["Fuente"] = source["fuente_reporte"]
    gdf_out["id_fuente"] = source["id_fuente"]
    gdf_out["Pais_es"] = source["pais_es"]
    gdf_out["Pais_cod3"] = source["pais_cod3"]
    gdf_out["Año"] = source["anio"]
    gdf_out["Longitud"] = gdf_out.geometry.x.round(decimals)
    gdf_out["Latitud"] = gdf_out.geometry.y.round(decimals)

    gdf_out["Clase"] = pd.to_numeric(gdf_out[fields["class_code"]], errors="coerce").astype("Int64")
    gdf_out["nombre_clase"] = gdf_out[fields["class_name"]].astype("string").str.strip()

    group_codes: list[int | pd.NA] = []
    group_names: list[str | pd.NA] = []
    for class_value in gdf_out["Clase"].tolist():
        if pd.isna(class_value):
            group_codes.append(pd.NA)
            group_names.append(pd.NA)
            continue
        group = class_group_lookup.get(int(class_value))
        if group is None:
            group_codes.append(pd.NA)
            group_names.append(pd.NA)
        else:
            group_codes.append(group[0])
            group_names.append(group[1])

    gdf_out["GranClase"] = pd.Series(group_codes, index=gdf_out.index).astype("Int64")
    gdf_out["nombre_gran_clase"] = pd.Series(group_names, index=gdf_out.index).astype("string")

    passthrough_defaults = {
        "candidate_id": pd.NA,
        "raster_value": pd.NA,
        "class_name_en": pd.NA,
        "stratum_id": pd.NA,
        "distance_scenario_m": pd.NA,
        "selection_status": pd.NA,
        "protected": pd.NA,
        "nearest_neighbor_m": pd.NA,
    }
    for output_col, default_value in passthrough_defaults.items():
        source_field = fields.get(output_col)
        if source_field and source_field in gdf_out.columns:
            gdf_out[output_col] = gdf_out[source_field]
        else:
            gdf_out[output_col] = default_value

    for col in ["candidate_id", "raster_value", "distance_scenario_m", "protected"]:
        gdf_out[col] = pd.to_numeric(gdf_out[col], errors="coerce").astype("Int64")
    gdf_out["nearest_neighbor_m"] = pd.to_numeric(gdf_out["nearest_neighbor_m"], errors="coerce")
    for col in ["class_name_en", "stratum_id", "selection_status"]:
        gdf_out[col] = gdf_out[col].astype("string")

    has_null_theme = gdf_out[THEMATIC_COLUMNS].isna().any(axis=1)
    missing_group = gdf_out["GranClase"].isna() & gdf_out["Clase"].notna()
    gdf_out["revision_nulos_tematicos"] = (has_null_theme | missing_group).astype(int)
    gdf_out["motivo_revision"] = ""
    gdf_out.loc[has_null_theme, "motivo_revision"] = "nulos_en_campos_tematicos"
    gdf_out.loc[missing_group, "motivo_revision"] = "clase_sin_gran_clase_configurada"

    missing_output = [col for col in OUTPUT_COLUMNS if col not in gdf_out.columns]
    if missing_output:
        raise RuntimeError(f"Faltan columnas de salida inesperadamente: {missing_output}")

    gdf_out = gdf_out[OUTPUT_COLUMNS].copy()
    gdf_out = gpd.GeoDataFrame(gdf_out, geometry="geometry", crs=cfg["output_crs"])

    if gdf_out["id_registro"].isna().any():
        raise RuntimeError("id_registro contiene nulos.")
    if gdf_out["id_registro"].duplicated().any():
        raise RuntimeError("id_registro contiene duplicados.")

    return gdf_out


def exportar_gpkg(gdf: gpd.GeoDataFrame, output_gpkg: Path, output_layer: str, overwrite: bool) -> None:
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    if output_gpkg.exists() and overwrite:
        output_gpkg.unlink()
    gdf.to_file(output_gpkg, layer=output_layer, driver="GPKG")


def imprimir_resumen(
    gdf_in: gpd.GeoDataFrame,
    gdf_out: gpd.GeoDataFrame,
    cfg: dict[str, Any],
) -> None:
    print("============================================================")
    print("Preparacion de datos Panama para auditoria espectral")
    print("============================================================")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Registros entrada: {len(gdf_in):,}")
    print(f"CRS entrada: {gdf_in.crs}")
    print(f"Registros salida: {len(gdf_out):,}")
    print(f"CRS salida: {gdf_out.crs}")
    print(f"Fuente: {cfg['source']['fuente_reporte']}")
    print(f"id_fuente: {cfg['source']['id_fuente']}")
    print(f"Año: {cfg['source']['anio']}")
    print(f"Pais: {cfg['source']['pais_es']} ({cfg['source']['pais_cod3']})")
    print(f"Clases: {gdf_out['Clase'].nunique(dropna=True):,}")
    print(f"GranClases: {gdf_out['GranClase'].nunique(dropna=True):,}")
    print(f"Registros con revision: {int(gdf_out['revision_nulos_tematicos'].sum()):,}")
    print(f"Salida: {cfg['output_gpkg']}")
    print(f"Capa: {cfg['output_layer']}")
    print("Done.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normaliza puntos del mapa forestal Panama 2021 para auditoria espectral."
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_RELATIVE,
        help=f"YAML de configuracion. Por defecto: {DEFAULT_CONFIG_RELATIVE}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = resolver_config_path(args.config)
    config = cargar_yaml(config_path)
    project_root = resolver_project_root(config, config_path)
    cfg = validar_config(config, project_root)

    if not cfg["input_gpkg"].exists():
        raise FileNotFoundError(f"No existe el GeoPackage de entrada: {cfg['input_gpkg']}")

    input_layer = resolver_capa(cfg["input_gpkg"], cfg["input_layer"])
    if input_layer:
        gdf_in = gpd.read_file(cfg["input_gpkg"], layer=input_layer)
    else:
        gdf_in = gpd.read_file(cfg["input_gpkg"])

    gdf_out = normalizar_panama(gdf_in, cfg)
    exportar_gpkg(gdf_out, cfg["output_gpkg"], cfg["output_layer"], cfg["overwrite"])
    imprimir_resumen(gdf_in, gdf_out, cfg)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        raise
