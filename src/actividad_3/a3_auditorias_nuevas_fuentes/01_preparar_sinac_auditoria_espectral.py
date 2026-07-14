from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import sys
import traceback

import geopandas as gpd
import pandas as pd

try:
    import fiona
except Exception:  # pragma: no cover
    fiona = None


# =============================================================================
# Preparación de datos SINAC para auditoría espectral
# =============================================================================
# Este script normaliza una fuente puntual para dejarla lista para el flujo de
# auditoría espectral. El caso base corresponde a:
# SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica.
#
# Operaciones principales:
# 1. Lee un GeoPackage de puntos.
# 2. Valida geometría puntual.
# 3. Reproyecta siempre a EPSG:4326.
# 4. Crea Longitud y Latitud con 6 decimales.
# 5. Agrega metadatos de fuente, país y año.
# 6. Conserva los campos temáticos Clase/GranClase/nombres.
# 7. Marca registros con nulos temáticos para revisión.
# 8. Exporta un GeoPackage normalizado.
# =============================================================================


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]

DEFAULT_INPUT_GPKG = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "a3_auditorias_nuevas_fuentes"
    / "raw"
    / "muestras_guanacaste_zonas_cuadrantes.gpkg"
)
DEFAULT_OUTPUT_GPKG = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "a3_auditorias_nuevas_fuentes"
    / "preparacion"
    / "preparacion_datos_sinac_auditoria_espectral.gpkg"
)
DEFAULT_OUTPUT_LAYER = "preparacion_datos_sinac_auditoria_espectral"

FUENTE = "SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica"
ID_FUENTE = 10
PAIS_ES = "Costa Rica"
PAIS_COD3 = "CRI"
ANIO = 2021

OUTPUT_CRS = "EPSG:4326"
COORD_DECIMALS = 6

THEMATIC_COLUMNS = ["Clase", "GranClase", "nombre_clase", "nombre_gran_clase"]
OPTIONAL_ORIGINAL_ID = "id_muestra_original"

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
    "geometry",
]


def listar_capas(gpkg_path: Path) -> list[str]:
    """Return GeoPackage layers."""
    if fiona is None:
        return []
    return list(fiona.listlayers(gpkg_path))


def resolver_capa(gpkg_path: Path, layer: str | None) -> str | None:
    """Resolve input layer. If layer is not provided and there is one layer, use it."""
    if layer:
        return layer

    layers = listar_capas(gpkg_path)
    if len(layers) == 1:
        return layers[0]

    if len(layers) > 1:
        raise ValueError(
            "El GeoPackage tiene varias capas. Indique una con --input-layer. "
            f"Capas disponibles: {layers}"
        )

    return None


def validar_entrada(gdf: gpd.GeoDataFrame) -> None:
    """Validate required geometry and thematic fields."""
    if gdf.empty:
        raise ValueError("La capa de entrada no contiene registros.")

    if gdf.crs is None:
        raise ValueError(
            "La capa de entrada no tiene CRS definido. Asigne el CRS correcto antes de continuar."
        )

    missing = [col for col in THEMATIC_COLUMNS if col not in gdf.columns]
    if missing:
        raise ValueError(
            "Faltan columnas temáticas requeridas en la fuente: "
            f"{missing}. Columnas disponibles: {list(gdf.columns)}"
        )

    if "geometry" not in gdf.columns:
        raise ValueError("La capa de entrada no tiene columna geometry.")

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


def crear_id_registro(n: int, id_fuente: int) -> list[str]:
    """Create stable internal unique IDs for this prepared source."""
    return [f"SRC{id_fuente:02d}_{i:07d}" for i in range(1, n + 1)]


def normalizar_sinac(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Normalize the input GeoDataFrame to the minimum audit-ready schema."""
    validar_entrada(gdf)

    gdf_out = gdf.copy()

    if gdf_out.crs.to_string() != OUTPUT_CRS:
        gdf_out = gdf_out.to_crs(OUTPUT_CRS)

    gdf_out["id_registro"] = crear_id_registro(len(gdf_out), ID_FUENTE)

    if OPTIONAL_ORIGINAL_ID not in gdf_out.columns:
        gdf_out[OPTIONAL_ORIGINAL_ID] = pd.NA

    gdf_out["Fuente"] = FUENTE
    gdf_out["id_fuente"] = ID_FUENTE
    gdf_out["Pais_es"] = PAIS_ES
    gdf_out["Pais_cod3"] = PAIS_COD3
    gdf_out["Año"] = ANIO

    gdf_out["Longitud"] = gdf_out.geometry.x.round(COORD_DECIMALS)
    gdf_out["Latitud"] = gdf_out.geometry.y.round(COORD_DECIMALS)

    # Preserve thematic fields while using nullable dtypes where appropriate.
    for col in ["Clase", "GranClase"]:
        gdf_out[col] = pd.to_numeric(gdf_out[col], errors="coerce").astype("Int64")

    for col in ["nombre_clase", "nombre_gran_clase"]:
        gdf_out[col] = gdf_out[col].astype("string")

    has_null_theme = gdf_out[THEMATIC_COLUMNS].isna().any(axis=1)
    gdf_out["revision_nulos_tematicos"] = has_null_theme.astype(int)
    gdf_out["motivo_revision"] = ""
    gdf_out.loc[has_null_theme, "motivo_revision"] = "nulos_en_campos_tematicos"

    # Keep only the normalized schema. id_zona/id_cuadrante are intentionally dropped.
    missing_output = [col for col in OUTPUT_COLUMNS if col not in gdf_out.columns]
    if missing_output:
        raise RuntimeError(f"Faltan columnas de salida inesperadamente: {missing_output}")

    gdf_out = gdf_out[OUTPUT_COLUMNS].copy()
    gdf_out = gpd.GeoDataFrame(gdf_out, geometry="geometry", crs=OUTPUT_CRS)

    # Final uniqueness check for the generated ID.
    if gdf_out["id_registro"].isna().any():
        raise RuntimeError("id_registro contiene nulos.")

    if gdf_out["id_registro"].duplicated().any():
        raise RuntimeError("id_registro contiene duplicados.")

    return gdf_out


def exportar_gpkg(gdf: gpd.GeoDataFrame, output_gpkg: Path, output_layer: str) -> None:
    """Export normalized GeoPackage, overwriting during development."""
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)

    if output_gpkg.exists():
        output_gpkg.unlink()

    gdf.to_file(output_gpkg, layer=output_layer, driver="GPKG")


def imprimir_resumen(gdf_in: gpd.GeoDataFrame, gdf_out: gpd.GeoDataFrame, output_gpkg: Path, output_layer: str) -> None:
    """Print a compact execution summary."""
    print("============================================================")
    print("Preparación de datos SINAC para auditoría espectral")
    print("============================================================")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Registros entrada: {len(gdf_in):,}")
    print(f"CRS entrada: {gdf_in.crs}")
    print(f"Registros salida: {len(gdf_out):,}")
    print(f"CRS salida: {gdf_out.crs}")
    print(f"Fuente: {FUENTE}")
    print(f"id_fuente: {ID_FUENTE}")
    print(f"Año: {ANIO}")
    print(f"País: {PAIS_ES} ({PAIS_COD3})")
    print(f"Decimales Longitud/Latitud: {COORD_DECIMALS}")
    print(f"Registros con nulos temáticos: {int(gdf_out['revision_nulos_tematicos'].sum()):,}")
    print(f"Salida: {output_gpkg}")
    print(f"Capa: {output_layer}")
    print("Done.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normaliza puntos SINAC 2021 para auditoría espectral."
    )
    parser.add_argument(
        "--input-gpkg",
        type=Path,
        default=DEFAULT_INPUT_GPKG,
        help=f"GeoPackage de entrada. Por defecto: {DEFAULT_INPUT_GPKG}",
    )
    parser.add_argument(
        "--input-layer",
        type=str,
        default=None,
        help="Capa de entrada. Si se omite y el GPKG tiene una sola capa, se usa esa.",
    )
    parser.add_argument(
        "--output-gpkg",
        type=Path,
        default=DEFAULT_OUTPUT_GPKG,
        help=f"GeoPackage de salida. Por defecto: {DEFAULT_OUTPUT_GPKG}",
    )
    parser.add_argument(
        "--output-layer",
        type=str,
        default=DEFAULT_OUTPUT_LAYER,
        help=f"Capa de salida. Por defecto: {DEFAULT_OUTPUT_LAYER}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input_gpkg.exists():
        raise FileNotFoundError(f"No existe el GeoPackage de entrada: {args.input_gpkg}")

    input_layer = resolver_capa(args.input_gpkg, args.input_layer)

    if input_layer:
        gdf_in = gpd.read_file(args.input_gpkg, layer=input_layer)
    else:
        gdf_in = gpd.read_file(args.input_gpkg)

    gdf_out = normalizar_sinac(gdf_in)
    exportar_gpkg(gdf_out, args.output_gpkg, args.output_layer)
    imprimir_resumen(gdf_in, gdf_out, args.output_gpkg, args.output_layer)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        raise
