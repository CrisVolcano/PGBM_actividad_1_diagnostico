from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import re
import traceback
from typing import Any

import geopandas as gpd
import pandas as pd
import yaml


# =============================================================================
# Prepare Sentinel-2 SR GEE input for normalized new point sources
# =============================================================================
# Purpose:
#   Prepare independent point datasets from new sources for Sentinel-2 Surface
#   Reflectance extraction in Google Earth Engine.
#
# Key difference from Module 06:
#   This script does NOT depend on the original grupos_xy SQLite table.
#   It creates extraction units directly from:
#
#       Longitud + Latitud + Año
#
# Expected command from the repository root:
#
#   python3 src/actividad_3/a3_auditorias_nuevas_fuentes/03_s2_sr_gee_input_nuevas_fuentes_caso_SINAC.py
#
# Optional:
#
#   python3 src/actividad_3/a3_auditorias_nuevas_fuentes/03_s2_sr_gee_input_nuevas_fuentes_caso_SINAC.py \
#       --batch-size 50000
# =============================================================================


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]
DEFAULT_CONFIG_RELATIVE = "config/a3_auditorias_nuevas_fuentes/config_sinac_malla_entrenamientos_2021.yaml"


def cargar_yaml(path: Path) -> dict[str, Any]:
    """Load YAML config."""
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo YAML requerido: {path}")

    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if data is None:
        return {}

    if not isinstance(data, dict):
        raise ValueError(f"El YAML no contiene un diccionario válido: {path}")

    return data


def resolver_config_path(config_arg: str | Path) -> Path:
    """Resolve config path from current working directory or script folder."""
    path = Path(config_arg)
    if path.is_absolute():
        return path.resolve()

    cwd_path = (Path.cwd() / path).resolve()
    if cwd_path.exists():
        return cwd_path

    script_path = (SCRIPT_DIR / path).resolve()
    if script_path.exists():
        return script_path

    return (PROJECT_DIR / path).resolve()


def resolver_project_root(config: dict[str, Any], config_path: Path) -> Path:
    """
    Resolve the base folder for input and output paths.

    Priority:
    1. paths.project_root in YAML.
    2. Folder containing the YAML file.
    """
    paths_cfg = config.get("paths", {})
    if isinstance(paths_cfg, dict):
        project_root_value = paths_cfg.get("project_root")
        if project_root_value:
            root = Path(project_root_value)
            return root.resolve() if root.is_absolute() else (config_path.parent / root).resolve()

    return config_path.parent.resolve()


def resolver_ruta(path_value: str | Path, base_dir: Path) -> Path:
    """Resolve absolute or YAML-folder-relative path."""
    path = Path(path_value)
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def limpiar_nombre_archivo(value: object) -> str:
    """Create safe filename fragments."""
    if pd.isna(value):
        return "NA"

    text = str(value).strip()
    text = text.replace(" ", "_")
    text = re.sub(r"[^A-Za-z0-9_\-]+", "", text)
    text = re.sub(r"_+", "_", text).strip("_")

    return text[:80] if text else "NA"


def crear_carpetas(base_dir: Path, tables_dir: Path) -> dict[str, Path]:
    """Create output directory structure."""
    dirs = {
        "base": base_dir,
        "batches": base_dir / "batches",
        "tables": tables_dir,
        "reports": PROJECT_DIR / "outputs" / "reports" / "a3_auditorias_nuevas_fuentes" / "gee_input",
        "logs": PROJECT_DIR / "logs" / "a3_auditorias_nuevas_fuentes",
    }

    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)

    return dirs


def registrar_log(log_dir: Path, mensaje: str) -> None:
    """Append execution messages to log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = log_dir / "auditoria_espectral_nuevas_fuentes.log"

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"[{fecha}] {mensaje}\n")


def obtener_cfg(config: dict[str, Any], section: str, key: str, default: Any = None) -> Any:
    """Small helper to read nested config values."""
    value = config.get(section, {})
    if not isinstance(value, dict):
        return default
    return value.get(key, default)


def validar_config(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Validate YAML config and return normalized settings."""
    input_data = config.get("input_data", {})
    fields = config.get("fields", {})
    settings = config.get("settings", {})
    outputs = config.get("outputs", {})
    temporal = config.get("temporal", {})
    xy_groups = config.get("xy_groups", {})

    if not isinstance(input_data, dict):
        raise ValueError("La sección input_data del YAML no es válida.")
    if not isinstance(fields, dict):
        raise ValueError("La sección fields del YAML no es válida.")
    if not isinstance(settings, dict):
        settings = {}
    if not isinstance(outputs, dict):
        outputs = {}
    if not isinstance(temporal, dict):
        temporal = {}
    if not isinstance(xy_groups, dict):
        xy_groups = {}

    gpkg_file = input_data.get("gpkg_file")
    gpkg_layer = input_data.get("gpkg_layer")

    if not gpkg_file:
        raise ValueError("Debe definirse input_data.gpkg_file en el YAML.")
    if not gpkg_layer:
        raise ValueError("Debe definirse input_data.gpkg_layer en el YAML.")

    required_field_keys = [
        "source",
        "source_id",
        "year",
        "country",
        "country_code",
        "longitude",
        "latitude",
        "class_code",
        "class_group_code",
        "class_name",
        "class_group_name",
    ]
    optional_field_keys = [
        "id",
        "original_id",
        "xy_group_id",
        "xy_year_group_id",
        "xy_class_group_id",
    ]

    missing_field_keys = [key for key in required_field_keys if not fields.get(key)]
    if missing_field_keys:
        raise ValueError(
            "Faltan nombres de campos requeridos en fields: "
            f"{missing_field_keys}"
        )

    output_base_dir = outputs.get(
        "base_dir",
        ".",
    )

    xy_layers = xy_groups.get("output_layers", {})
    if not isinstance(xy_layers, dict):
        xy_layers = {}

    use_xy_for_input = bool(xy_groups.get("use_for_gee_input", False))
    xy_input_gpkg = xy_groups.get("output_gpkg")
    xy_input_layer = xy_layers.get("records")

    normalized_fields = {key: str(fields[key]) for key in required_field_keys}
    for key in optional_field_keys:
        if fields.get(key):
            normalized_fields[key] = str(fields[key])

    norm = {
        "input_gpkg": resolver_ruta(gpkg_file, project_root),
        "input_layer": str(gpkg_layer),
        "fields": normalized_fields,
        "expected_crs": str(settings.get("expected_crs", "EPSG:4326")),
        "coordinate_precision": int(settings.get("coordinate_precision", 6)),
        "extract_id_prefix": str(settings.get("extract_id_prefix", "S2SR_llenado_SRC10")),
        "batch_size": int(settings.get("batch_size", 50000)),
        "year_min": temporal.get("year_min"),
        "year_max": temporal.get("year_max"),
        "output_base_dir": resolver_ruta(output_base_dir, project_root),
        "output_tables_dir": resolver_ruta(
            outputs.get("tables_dir", "outputs/tables/a3_auditorias_nuevas_fuentes/gee_input"),
            project_root,
        ),
        "eligible_gpkg": str(outputs.get("eligible_gpkg", "puntos_con_extract_id.gpkg")),
        "eligible_layer": str(outputs.get("eligible_layer", "puntos_con_extract_id")),
        "units_csv": str(outputs.get("units_csv", "s2_sr_extract_units.csv")),
        "overwrite": bool(outputs.get("overwrite", True)),
    }

    if use_xy_for_input:
        if not xy_input_gpkg or not xy_input_layer:
            raise ValueError(
                "xy_groups.use_for_gee_input=true requiere "
                "xy_groups.output_gpkg y xy_groups.output_layers.records."
            )
        norm["input_gpkg"] = resolver_ruta(xy_input_gpkg, project_root)
        norm["input_layer"] = str(xy_input_layer)
        norm["requires_xy_groups"] = True
    else:
        norm["requires_xy_groups"] = False

    return norm


def validar_campos(gdf: gpd.GeoDataFrame, fields: dict[str, str]) -> None:
    """Validate required physical fields in GeoDataFrame."""
    optional_keys = {"id", "original_id", "xy_group_id", "xy_year_group_id", "xy_class_group_id"}
    required_columns = [
        field for key, field in fields.items()
        if key not in optional_keys
    ]
    missing = [field for field in required_columns if field not in gdf.columns]

    if missing:
        available = sorted([str(col) for col in gdf.columns])
        raise ValueError(
            "Faltan campos requeridos en el GeoPackage de entrada: "
            f"{missing}\n\nCampos disponibles:\n{available}"
        )


def preparar_geometria_y_coord(
    gdf: gpd.GeoDataFrame,
    expected_crs: str,
    lon_field: str,
    lat_field: str,
    decimals: int,
) -> gpd.GeoDataFrame:
    """
    Validate point geometry, reproject to expected CRS and derive lon/lat.

    Longitud and Latitud are recalculated from geometry to avoid stale coordinate
    values inherited from previous processing.
    """
    if gdf.empty:
        raise ValueError("El GeoPackage de entrada no contiene registros.")

    if gdf.geometry.name not in gdf.columns:
        raise ValueError("El GeoPackage no contiene una columna geometry válida.")

    if gdf.geometry.isna().any():
        n_null = int(gdf.geometry.isna().sum())
        raise ValueError(f"Existen geometrías nulas: {n_null:,}")

    if gdf.geometry.is_empty.any():
        n_empty = int(gdf.geometry.is_empty.sum())
        raise ValueError(f"Existen geometrías vacías: {n_empty:,}")

    geom_types = set(gdf.geometry.geom_type.dropna().unique())
    if geom_types != {"Point"}:
        raise ValueError(
            "Este módulo solo acepta geometrías puntuales simples. "
            f"Tipos detectados: {sorted(geom_types)}"
        )

    if gdf.crs is None:
        raise ValueError(
            "El GeoPackage no tiene CRS definido. "
            "Asigne el CRS correcto antes de ejecutar este módulo."
        )

    if str(gdf.crs).upper() != expected_crs.upper():
        gdf = gdf.to_crs(expected_crs)

    gdf = gdf.copy()
    gdf[lon_field] = gdf.geometry.x.round(decimals)
    gdf[lat_field] = gdf.geometry.y.round(decimals)

    return gdf


def normalizar_coord(series: pd.Series, decimals: int) -> pd.Series:
    """Convert coordinate column to numeric and round consistently."""
    return pd.to_numeric(series, errors="coerce").round(decimals)


def filtrar_por_anio(
    gdf: gpd.GeoDataFrame,
    year_field: str,
    year_min: Any,
    year_max: Any,
) -> gpd.GeoDataFrame:
    """Convert year to numeric and apply optional year range filter."""
    gdf = gdf.copy()
    gdf[year_field] = pd.to_numeric(gdf[year_field], errors="coerce")

    if gdf[year_field].isna().any():
        n = int(gdf[year_field].isna().sum())
        raise ValueError(f"Existen registros con Año nulo o no numérico: {n:,}")

    if year_min is not None:
        year_min = int(year_min)
        gdf = gdf[gdf[year_field] >= year_min].copy()

    if year_max is not None:
        year_max = int(year_max)
        gdf = gdf[gdf[year_field] <= year_max].copy()

    return gdf


def construir_unidades_extraccion(
    gdf: gpd.GeoDataFrame,
    fields: dict[str, str],
    extract_id_prefix: str,
    decimals: int,
) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """
    Build unique extraction units and join extract_id back to all records.

    Extraction unit:
        Longitud + Latitud + Año
    """
    lon_field = fields["longitude"]
    lat_field = fields["latitude"]
    year_field = fields["year"]

    gdf = gdf.copy()
    gdf["_lon_join"] = normalizar_coord(gdf[lon_field], decimals)
    gdf["_lat_join"] = normalizar_coord(gdf[lat_field], decimals)

    required_keys = ["_lon_join", "_lat_join", year_field]

    agg_fields = [
        fields["country"],
        fields["country_code"],
        fields["source"],
        fields["source_id"],
        fields["class_code"],
        fields["class_group_code"],
        fields["class_name"],
        fields["class_group_name"],
    ]
    optional_agg_fields = [
        fields.get("id"),
        fields.get("original_id"),
        fields.get("xy_group_id"),
        fields.get("xy_year_group_id"),
        fields.get("xy_class_group_id"),
    ]
    agg_fields.extend(
        [
            field
            for field in optional_agg_fields
            if field and field in gdf.columns and field not in agg_fields
        ]
    )

    grouped = gdf.groupby(required_keys, dropna=False)

    units = grouped.size().reset_index(name="n_records_extract_unit")

    first_values = grouped[agg_fields].first().reset_index()
    units = units.merge(first_values, on=required_keys, how="left")

    class_code = fields["class_code"]
    class_group_code = fields["class_group_code"]
    class_name = fields["class_name"]
    class_group_name = fields["class_group_name"]

    for field, suffix in [
        (class_code, "class_code"),
        (class_group_code, "class_group_code"),
        (class_name, "class_name"),
        (class_group_name, "class_group_name"),
    ]:
        nunique = (
            grouped[field]
            .nunique(dropna=True)
            .reset_index(name=f"n_unique_{suffix}_extract_unit")
        )
        units = units.merge(nunique, on=required_keys, how="left")

    units["has_thematic_conflict"] = (
        (units["n_unique_class_code_extract_unit"] > 1)
        | (units["n_unique_class_group_code_extract_unit"] > 1)
        | (units["n_unique_class_name_extract_unit"] > 1)
        | (units["n_unique_class_group_name_extract_unit"] > 1)
    ).astype(int)

    sort_cols = [
        fields["country_code"],
        fields["year"],
        fields["source_id"],
        "_lon_join",
        "_lat_join",
    ]
    sort_cols = [col for col in sort_cols if col in units.columns]
    units = units.sort_values(sort_cols, na_position="last").reset_index(drop=True)

    units.insert(
        0,
        "extract_id",
        [f"{extract_id_prefix}_{i:09d}" for i in range(1, len(units) + 1)],
    )

    units = units.rename(
        columns={
            "_lon_join": "lon",
            "_lat_join": "lat",
            fields["year"]: "year_ref",
            fields["country"]: "country",
            fields["country_code"]: "country_code",
            fields["source"]: "source",
            fields["source_id"]: "source_id",
            fields["class_code"]: "class_code",
            fields["class_group_code"]: "class_group_code",
            fields["class_name"]: "class_name",
            fields["class_group_name"]: "class_group_name",
        }
    )

    optional_renames = {
        fields.get("id"): "source_record_id",
        fields.get("original_id"): "original_source_record_id",
        fields.get("xy_group_id"): "xy_group_id",
        fields.get("xy_year_group_id"): "xy_year_group_id",
        fields.get("xy_class_group_id"): "xy_class_group_id",
    }
    optional_renames = {
        source: target
        for source, target in optional_renames.items()
        if source and source in units.columns and source != target
    }
    if optional_renames:
        units = units.rename(columns=optional_renames)

    extract_lookup = units[
        ["extract_id", "lon", "lat", "year_ref", "n_records_extract_unit"]
    ].rename(
        columns={
            "lon": "_lon_join",
            "lat": "_lat_join",
            "year_ref": year_field,
        }
    )

    for col in ["extract_id", "n_records_extract_unit"]:
        if col in gdf.columns:
            gdf = gdf.drop(columns=[col])

    gdf = gdf.merge(extract_lookup, on=["_lon_join", "_lat_join", year_field], how="left")

    missing_extract_id = int(gdf["extract_id"].isna().sum())
    if missing_extract_id:
        raise ValueError(
            "Algunos registros no recibieron extract_id: "
            f"{missing_extract_id:,}"
        )

    return units, gdf


def generar_tabla_conflictos(
    gdf: gpd.GeoDataFrame,
    fields: dict[str, str],
    decimals: int,
) -> pd.DataFrame:
    """Detect extraction units with more than one thematic value."""
    lon_field = fields["longitude"]
    lat_field = fields["latitude"]
    year_field = fields["year"]
    class_code = fields["class_code"]
    class_group_code = fields["class_group_code"]
    class_name = fields["class_name"]
    class_group_name = fields["class_group_name"]

    df = gdf.copy()
    df["_lon_join"] = normalizar_coord(df[lon_field], decimals)
    df["_lat_join"] = normalizar_coord(df[lat_field], decimals)

    key_cols = ["_lon_join", "_lat_join", year_field]

    rows = []
    for key, group in df.groupby(key_cols, dropna=False):
        n_class = group[class_code].nunique(dropna=True)
        n_group = group[class_group_code].nunique(dropna=True)
        n_class_name = group[class_name].nunique(dropna=True)
        n_group_name = group[class_group_name].nunique(dropna=True)

        if max(n_class, n_group, n_class_name, n_group_name) <= 1:
            continue

        lon, lat, year = key
        rows.append(
            {
                "lon": lon,
                "lat": lat,
                "year_ref": year,
                "records": len(group),
                "n_unique_class_code": n_class,
                "n_unique_class_group_code": n_group,
                "n_unique_class_name": n_class_name,
                "n_unique_class_group_name": n_group_name,
                "class_codes": " | ".join(map(str, sorted(group[class_code].dropna().unique()))),
                "class_group_codes": " | ".join(map(str, sorted(group[class_group_code].dropna().unique()))),
                "class_names": " | ".join(map(str, sorted(group[class_name].dropna().unique()))),
                "class_group_names": " | ".join(map(str, sorted(group[class_group_name].dropna().unique()))),
            }
        )

    return pd.DataFrame(rows)


def exportar_tabla_conteo(df: pd.DataFrame, field: str, output_csv: Path) -> None:
    """Export frequency table."""
    if field not in df.columns:
        pd.DataFrame(
            [{"warning": f"Campo no encontrado: {field}"}]
        ).to_csv(output_csv, index=False, encoding="utf-8-sig")
        return

    table = (
        df.groupby(field, dropna=False)
        .size()
        .reset_index(name="records")
        .sort_values("records", ascending=False)
    )

    total = int(table["records"].sum())
    table["percentage"] = (table["records"] / total * 100).round(4) if total else 0

    table.to_csv(output_csv, index=False, encoding="utf-8-sig")


def exportar_batches(
    units: pd.DataFrame,
    batch_size: int,
    batches_dir: Path,
    tables_dir: Path,
) -> pd.DataFrame:
    """Export GEE CSV batches grouped by country_code + year_ref + source_id."""
    if batch_size <= 0:
        raise ValueError("batch_size debe ser mayor que 0.")

    batches_dir.mkdir(parents=True, exist_ok=True)

    for old_csv in batches_dir.glob("*.csv"):
        old_csv.unlink()

    if units.empty:
        batch_index = pd.DataFrame(
            columns=["batch_id", "country_code", "year_ref", "source_id", "records", "batch_csv"]
        )
        batch_index.to_csv(tables_dir / "s2_sr_gee_batch_index.csv", index=False, encoding="utf-8-sig")
        return batch_index

    batch_records = []
    group_fields = ["country_code", "year_ref", "source_id"]

    for (country_code, year_ref, source_id), df_group in units.groupby(group_fields, dropna=False):
        df_group = df_group.sort_values("extract_id").reset_index(drop=True)

        n_batches = (len(df_group) + batch_size - 1) // batch_size

        for batch_idx in range(n_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(df_group))
            df_batch = df_group.iloc[start:end].copy()

            country_name = limpiar_nombre_archivo(country_code)
            year_name = limpiar_nombre_archivo(year_ref)
            source_name = limpiar_nombre_archivo(f"SRC{source_id}")

            batch_name = (
                f"s2sr_units_{country_name}_{year_name}_{source_name}_"
                f"batch_{batch_idx + 1:03d}"
            )
            batch_csv = batches_dir / f"{batch_name}.csv"

            df_batch["batch_id"] = batch_name
            df_batch.to_csv(batch_csv, index=False, encoding="utf-8-sig")

            batch_records.append(
                {
                    "batch_id": batch_name,
                    "country_code": country_code,
                    "year_ref": year_ref,
                    "source_id": source_id,
                    "records": len(df_batch),
                    "batch_csv": str(batch_csv),
                }
            )

    batch_index = pd.DataFrame(batch_records)
    batch_index.to_csv(
        tables_dir / "s2_sr_gee_batch_index.csv",
        index=False,
        encoding="utf-8-sig",
    )

    return batch_index


def exportar_gpkg(gdf: gpd.GeoDataFrame, output_gpkg: Path, layer: str, overwrite: bool) -> None:
    """Export GeoPackage with original eligible records and extract_id."""
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)

    export_gdf = gdf.drop(columns=[c for c in ["_lon_join", "_lat_join"] if c in gdf.columns])

    if output_gpkg.exists() and overwrite:
        output_gpkg.unlink()

    export_gdf.to_file(output_gpkg, layer=layer, driver="GPKG")


def generar_reporte(
    report_path: Path,
    config_path: Path,
    input_gpkg: Path,
    input_layer: str,
    output_gpkg: Path,
    output_layer: str,
    units_csv: Path,
    batch_index: pd.DataFrame,
    total_input: int,
    total_eligible: int,
    total_units: int,
    total_conflicts: int,
    batch_size: int,
    expected_crs: str,
    coordinate_precision: int,
) -> None:
    """Write Markdown report."""
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    contenido = "\n".join(
        [
            "# Preparación de insumos para GEE - nueva fuente puntual",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## Propósito",
            "",
            (
                "Este módulo prepara una fuente puntual normalizada e independiente "
                "para extracción Sentinel-2 Surface Reflectance en Google Earth Engine."
            ),
            "",
            "## Configuración usada",
            "",
            f"- Configuración YAML: `{config_path}`",
            f"- GeoPackage de entrada: `{input_gpkg}`",
            f"- Capa de entrada: `{input_layer}`",
            f"- CRS de trabajo: `{expected_crs}`",
            f"- Decimales de coordenadas: `{coordinate_precision}`",
            "",
            "## Unidad de extracción",
            "",
            "```text",
            "Longitud + Latitud + Año",
            "```",
            "",
            (
                "Si el GeoPackage de entrada proviene del modulo de grupos XY, "
                "las columnas `xy_group_id`, `xy_year_group_id` y "
                "`xy_class_group_id` se conservan en registros elegibles y "
                "unidades de extraccion."
            ),
            "",
            "## Resumen",
            "",
            "| Métrica | Valor |",
            "|---|---:|",
            f"| Registros de entrada | {total_input:,} |",
            f"| Registros elegibles | {total_eligible:,} |",
            f"| Unidades únicas Longitud-Latitud-Año | {total_units:,} |",
            f"| Extracciones redundantes evitadas | {total_eligible - total_units:,} |",
            f"| Unidades con posible conflicto temático | {total_conflicts:,} |",
            f"| Batch size | {batch_size:,} |",
            f"| Batches generados | {len(batch_index):,} |",
            "",
            "## Salidas principales",
            "",
            f"- GeoPackage con registros elegibles y `extract_id`: `{output_gpkg}`",
            f"- Capa: `{output_layer}`",
            f"- CSV de unidades únicas para GEE: `{units_csv}`",
            f"- Índice de batches: `{batch_index}`",
            "",
        ]
    )

    report_path.write_text(contenido, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Prepara una nueva fuente puntual normalizada para extracción "
            "Sentinel-2 SR en GEE."
        )
    )

    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_RELATIVE,
        help=(
            "Ruta al YAML de configuración. "
            f"Por defecto: {DEFAULT_CONFIG_RELATIVE}"
        ),
    )

    parser.add_argument(
        "--input-gpkg",
        default=None,
        help="Sobrescribe input_data.gpkg_file del YAML.",
    )

    parser.add_argument(
        "--input-layer",
        default=None,
        help="Sobrescribe input_data.gpkg_layer del YAML.",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Sobrescribe settings.batch_size del YAML.",
    )

    parser.add_argument(
        "--output-dir",
        default=None,
        help="Sobrescribe outputs.base_dir del YAML.",
    )

    parser.add_argument(
        "--skip-gpkg",
        action="store_true",
        help="No exporta el GeoPackage con registros elegibles y extract_id.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config_path = resolver_config_path(args.config)
    config = cargar_yaml(config_path)
    project_root = resolver_project_root(config, config_path)

    norm_cfg = validar_config(config, project_root)

    if args.input_gpkg:
        norm_cfg["input_gpkg"] = resolver_ruta(args.input_gpkg, project_root)
    if args.input_layer:
        norm_cfg["input_layer"] = str(args.input_layer)
    if args.batch_size is not None:
        norm_cfg["batch_size"] = int(args.batch_size)
    if args.output_dir:
        norm_cfg["output_base_dir"] = resolver_ruta(args.output_dir, project_root)

    dirs = crear_carpetas(norm_cfg["output_base_dir"], norm_cfg["output_tables_dir"])

    registrar_log(dirs["logs"], "Inicio de preparación de nueva fuente puntual para GEE.")

    fields = norm_cfg["fields"]

    print("============================================================")
    print("PGBM - Preparación GEE Sentinel-2 SR para nueva fuente puntual")
    print("============================================================")
    print(f"Project root: {project_root}")
    print(f"Config: {config_path}")
    print(f"GeoPackage entrada: {norm_cfg['input_gpkg']}")
    print(f"Capa entrada: {norm_cfg['input_layer']}")
    print(f"Requiere etapa XY previa: {norm_cfg['requires_xy_groups']}")
    print(f"Salida base: {norm_cfg['output_base_dir']}")
    print(f"CRS esperado: {norm_cfg['expected_crs']}")
    print(f"Decimales coordenadas: {norm_cfg['coordinate_precision']}")
    print(f"Prefijo extract_id: {norm_cfg['extract_id_prefix']}")
    print(f"Batch size: {norm_cfg['batch_size']:,}")

    if not norm_cfg["input_gpkg"].exists():
        if norm_cfg["requires_xy_groups"]:
            raise FileNotFoundError(
                f"No existe el GeoPackage de entrada con grupos XY: {norm_cfg['input_gpkg']}. "
                "Ejecute primero src/actividad_3/a3_auditorias_nuevas_fuentes/02_xy_groups_nuevas_fuentes.py."
            )
        raise FileNotFoundError(f"No existe el GeoPackage de entrada: {norm_cfg['input_gpkg']}")

    print("\nLeyendo GeoPackage normalizado...")
    gdf = gpd.read_file(norm_cfg["input_gpkg"], layer=norm_cfg["input_layer"])
    total_input = len(gdf)
    print(f"Registros de entrada: {total_input:,}")
    print(f"CRS entrada: {gdf.crs}")

    validar_campos(gdf, fields)

    print("\nValidando geometría, CRS y coordenadas...")
    gdf = preparar_geometria_y_coord(
        gdf=gdf,
        expected_crs=norm_cfg["expected_crs"],
        lon_field=fields["longitude"],
        lat_field=fields["latitude"],
        decimals=norm_cfg["coordinate_precision"],
    )

    print("\nFiltrando por año, si aplica...")
    gdf = filtrar_por_anio(
        gdf=gdf,
        year_field=fields["year"],
        year_min=norm_cfg["year_min"],
        year_max=norm_cfg["year_max"],
    )
    total_eligible = len(gdf)
    print(f"Registros elegibles: {total_eligible:,}")

    print("\nConstruyendo unidades únicas Longitud-Latitud-Año...")
    units, gdf_with_extract_id = construir_unidades_extraccion(
        gdf=gdf,
        fields=fields,
        extract_id_prefix=norm_cfg["extract_id_prefix"],
        decimals=norm_cfg["coordinate_precision"],
    )
    print(f"Unidades únicas para GEE: {len(units):,}")
    print(f"Extracciones redundantes evitadas: {total_eligible - len(units):,}")

    print("\nDetectando conflictos por coordenada/año/clase...")
    conflicts = generar_tabla_conflictos(
        gdf=gdf,
        fields=fields,
        decimals=norm_cfg["coordinate_precision"],
    )
    print(f"Unidades con posible conflicto temático: {len(conflicts):,}")

    print("\nExportando CSV de unidades para GEE...")
    units_csv = dirs["base"] / norm_cfg["units_csv"]
    units.to_csv(units_csv, index=False, encoding="utf-8-sig")
    print(f"CSV unidades: {units_csv}")

    print("\nExportando batches para GEE...")
    batch_index = exportar_batches(
        units=units,
        batch_size=norm_cfg["batch_size"],
        batches_dir=dirs["batches"],
        tables_dir=dirs["tables"],
    )
    print(f"Batches generados: {len(batch_index):,}")

    print("\nExportando tablas resumen...")
    summary = pd.DataFrame(
        [
            {
                "input_gpkg": str(norm_cfg["input_gpkg"]),
                "input_layer": norm_cfg["input_layer"],
                "total_input_records": total_input,
                "eligible_records": total_eligible,
                "extract_units_lon_lat_year": len(units),
                "redundant_extractions_avoided": total_eligible - len(units),
                "thematic_conflict_units": len(conflicts),
                "batch_size": norm_cfg["batch_size"],
                "n_batches": len(batch_index),
                "output_base_dir": str(dirs["base"]),
                "units_csv": str(units_csv),
            }
        ]
    )
    summary.to_csv(dirs["tables"] / "s2_sr_nueva_fuente_summary.csv", index=False, encoding="utf-8-sig")

    exportar_tabla_conteo(gdf_with_extract_id, fields["country"], dirs["tables"] / "records_by_country.csv")
    exportar_tabla_conteo(gdf_with_extract_id, fields["country_code"], dirs["tables"] / "records_by_country_code.csv")
    exportar_tabla_conteo(gdf_with_extract_id, fields["year"], dirs["tables"] / "records_by_year.csv")
    exportar_tabla_conteo(gdf_with_extract_id, fields["source"], dirs["tables"] / "records_by_source.csv")
    exportar_tabla_conteo(gdf_with_extract_id, fields["source_id"], dirs["tables"] / "records_by_source_id.csv")
    exportar_tabla_conteo(gdf_with_extract_id, fields["class_code"], dirs["tables"] / "records_by_class_code.csv")
    exportar_tabla_conteo(gdf_with_extract_id, fields["class_group_code"], dirs["tables"] / "records_by_class_group_code.csv")
    exportar_tabla_conteo(gdf_with_extract_id, fields["class_name"], dirs["tables"] / "records_by_class_name.csv")
    exportar_tabla_conteo(gdf_with_extract_id, fields["class_group_name"], dirs["tables"] / "records_by_class_group_name.csv")

    conflicts.to_csv(dirs["tables"] / "possible_thematic_conflicts_by_lon_lat_year.csv", index=False, encoding="utf-8-sig")

    output_gpkg = dirs["base"] / norm_cfg["eligible_gpkg"]
    output_layer = norm_cfg["eligible_layer"]

    if not args.skip_gpkg:
        print("\nExportando GeoPackage con registros elegibles y extract_id...")
        exportar_gpkg(
            gdf=gdf_with_extract_id,
            output_gpkg=output_gpkg,
            layer=output_layer,
            overwrite=norm_cfg["overwrite"],
        )
        print(f"GeoPackage exportado: {output_gpkg}")
    else:
        print("\nSe omitió la exportación del GeoPackage por --skip-gpkg.")

    print("\nGenerando reporte Markdown...")
    report_path = dirs["reports"] / "s2_sr_gee_input_nueva_fuente.md"
    generar_reporte(
        report_path=report_path,
        config_path=config_path,
        input_gpkg=norm_cfg["input_gpkg"],
        input_layer=norm_cfg["input_layer"],
        output_gpkg=output_gpkg,
        output_layer=output_layer,
        units_csv=units_csv,
        batch_index=batch_index,
        total_input=total_input,
        total_eligible=total_eligible,
        total_units=len(units),
        total_conflicts=len(conflicts),
        batch_size=norm_cfg["batch_size"],
        expected_crs=norm_cfg["expected_crs"],
        coordinate_precision=norm_cfg["coordinate_precision"],
    )

    registrar_log(
        dirs["logs"],
        "Preparación de nueva fuente puntual ejecutada correctamente. "
        f"Registros elegibles: {total_eligible}. "
        f"Unidades GEE: {len(units)}. "
        f"Batches: {len(batch_index)}. "
        f"Conflictos: {len(conflicts)}."
    )

    print("\nDone.")
    print(f"Registros elegibles: {total_eligible:,}")
    print(f"Unidades únicas Longitud-Latitud-Año: {len(units):,}")
    print(f"Extracciones redundantes evitadas: {total_eligible - len(units):,}")
    print(f"Unidades con posible conflicto temático: {len(conflicts):,}")
    print(f"CSV unidades GEE: {units_csv}")
    print(f"GeoPackage registros con extract_id: {output_gpkg}")
    print(f"Reporte: {report_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            config_path = resolver_config_path(parse_args().config)
            config = cargar_yaml(config_path)
            project_root = resolver_project_root(config, config_path)
            norm_cfg = validar_config(config, project_root)
            dirs = crear_carpetas(norm_cfg["output_base_dir"], norm_cfg["output_tables_dir"])
            registrar_log(
                dirs["logs"],
                "Error durante la preparación de nueva fuente puntual. "
                f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            pass

        traceback.print_exc()
        raise
