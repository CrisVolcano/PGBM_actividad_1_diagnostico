from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import argparse
import csv
import sqlite3
import traceback
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

try:
    import fiona
except Exception:  # pragma: no cover
    fiona = None


# =============================================================================
# PGBM - Join SINAC SRC10 2021 records with Sentinel-2 SR monthly values
# =============================================================================
#
# Propósito:
#   Unir los registros originales/elegibles de la nueva fuente SINAC SRC10 2021
#   con los valores espectro-temporales mensuales Sentinel-2 SR exportados desde
#   Google Earth Engine.
#
# Condiciones del piloto:
#   - Fuente: SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica
#   - source_id / id_fuente: 10
#   - Año de referencia: 2021
#   - País: CRI / Costa Rica
#   - Unidad de extracción: Longitud + Latitud + Año
#   - Llave de unión: extract_id
#
# Este código no asume grupos_xy, Nivel_1 ni Nivel_2. Conserva los campos
# temáticos propios del piloto: Clase, GranClase, nombre_clase y
# nombre_gran_clase, además de los equivalentes genéricos si existen:
# class_code, class_group_code, class_name y class_group_name.
#
# Salida principal:
#   data/processed/a3_auditorias_nuevas_fuentes/s2sr_join/sinac_src10_2021_s2sr_join_outputs.gpkg
#
# Capas GPKG:
#   - sinac_src10_records_s2sr_full
#   - sinac_src10_records_s2sr_reduced
#   - sinac_src10_records_s2sr_annual
#   - sinac_src10_extract_units_s2sr_annual
#
# Tablas de control:
#   - validation_summary
#   - input_files_inventory
#   - missing_extract_id_in_gee
#   - extra_extract_id_in_gee
#   - duplicate_gee_extract_id_month
#   - monthly_clean_obs_summary
#   - thematic_extract_units_summary
#
# Uso recomendado desde la carpeta del piloto:
#   python3 src/actividad_3/a3_auditorias_nuevas_fuentes/05_join_s2sr_to_sinac_src10_2021_records.py
#
# Uso con rutas explícitas:
#   python3 src/actividad_3/a3_auditorias_nuevas_fuentes/05_join_s2sr_to_sinac_src10_2021_records.py \
#     --reference-gpkg data/processed/a3_auditorias_nuevas_fuentes/gee_input/puntos_sinac_src10_2021_con_extract_id.gpkg \
#     --gee-export-dir data/processed/a3_auditorias_nuevas_fuentes/gee_exports
# =============================================================================


# -----------------------------------------------------------------------------
# Defaults relative to the pilot folder
# -----------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]

DEFAULT_REFERENCE_GPKG = Path(
    "data/processed/a3_auditorias_nuevas_fuentes/gee_input/puntos_sinac_src10_2021_con_extract_id.gpkg"
)
DEFAULT_REFERENCE_LAYER = None

DEFAULT_GEE_EXPORT_DIR = Path("data/processed/a3_auditorias_nuevas_fuentes/gee_exports")
DEFAULT_GEE_EXPORT_PREFIX = "pgbm_s2sr_monthly_s2cloudless_sinac_src10_2021"

DEFAULT_OUTPUT_GPKG = Path(
    "data/processed/a3_auditorias_nuevas_fuentes/s2sr_join/sinac_src10_2021_s2sr_join_outputs.gpkg"
)
DEFAULT_TABLES_DIR = Path("outputs/tables/a3_auditorias_nuevas_fuentes/s2sr_join")
DEFAULT_REPORTS_DIR = Path("outputs/reports/a3_auditorias_nuevas_fuentes/s2sr_join")
DEFAULT_REPORT_NAME = "join_s2sr_to_sinac_src10_2021_records_report.md"

SOURCE_NAME = "SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica"
SOURCE_ID = "10"
SOURCE_CODE = "SRC10"
COUNTRY_CODE = "CRI"
YEAR_REF = "2021"

ID_COL = "extract_id"
MONTH_COL = "month"
CHUNKSIZE = 250_000

SPECTRAL_VALUE_COLS = [
    "B2",
    "B3",
    "B4",
    "B5",
    "B6",
    "B7",
    "B8",
    "B8A",
    "B11",
    "B12",
    "NDVI",
    "NDVI8A",
    "NDRE",
    "n_obs_clean",
    "cloud_prob_median",
]

INDEX_COLS = ["NDVI", "NDVI8A", "NDRE"]

METADATA_COLS = [
    "year_ref",
    "year_extraction",
    "batch_id",
]

LAYER_FULL = "sinac_src10_records_s2sr_full"
LAYER_REDUCED = "sinac_src10_records_s2sr_reduced"
LAYER_ANNUAL = "sinac_src10_records_s2sr_annual"
LAYER_UNITS_ANNUAL = "sinac_src10_extract_units_s2sr_annual"

TABLE_VALIDATION = "validation_summary"
TABLE_INPUT_FILES = "input_files_inventory"
TABLE_MISSING = "missing_extract_id_in_gee"
TABLE_EXTRA = "extra_extract_id_in_gee"
TABLE_DUPLICATES = "duplicate_gee_extract_id_month"
TABLE_MONTHLY_OBS = "monthly_clean_obs_summary"
TABLE_THEMATIC = "thematic_extract_units_summary"


@dataclass(frozen=True)
class Settings:
    reference_gpkg: Path
    reference_layer: str | None
    gee_export_dir: Path
    gee_export_prefix: str
    output_gpkg: Path
    tables_dir: Path
    reports_dir: Path
    report_md: Path
    allow_missing: bool


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

def resolve_path(path_value: str | Path) -> Path:
    """Resolve absolute paths or pilot-folder-relative paths."""
    path = Path(path_value)
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_DIR / path).resolve()


def fmt_path(path: Path) -> str:
    """Return path relative to the pilot folder when possible."""
    try:
        return str(path.resolve().relative_to(PROJECT_DIR)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove BOM and surrounding whitespace from column names."""
    out = df.copy()
    out.columns = [str(c).replace("\ufeff", "").strip() for c in out.columns]
    return out


def read_csv_header(path: Path) -> list[str]:
    """Read only a CSV header using common encodings."""
    for encoding in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            with open(path, "r", encoding=encoding, newline="") as file:
                reader = csv.reader(file)
                return [str(c).replace("\ufeff", "").strip() for c in next(reader, [])]
        except UnicodeDecodeError:
            continue
        except StopIteration:
            return []
        except Exception:
            return []
    return []


def format_bool(value: bool) -> str:
    return "true" if bool(value) else "false"


def dataframe_a_markdown(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


def s2_base_name(name: str) -> str:
    mapping = {
        "B2": "b02",
        "B3": "b03",
        "B4": "b04",
        "B5": "b05",
        "B6": "b06",
        "B7": "b07",
        "B8": "b08",
        "B8A": "b8a",
        "B11": "b11",
        "B12": "b12",
        "NDVI": "ndvi",
        "NDVI8A": "ndvi8a",
        "NDRE": "ndre",
        "n_obs_clean": "obs",
        "cloud_prob_median": "cloudprob",
    }
    return mapping.get(name, str(name).lower())


def s2_monthly_col(month: int, value_col: str) -> str:
    return f"s2_{int(month):02d}_{s2_base_name(value_col)}"


def s2yr_col(value_col: str, metric: str) -> str:
    return f"s2yr_{s2_base_name(value_col)}_{metric}"


def clean_for_gpkg(df: pd.DataFrame | gpd.GeoDataFrame) -> pd.DataFrame | gpd.GeoDataFrame:
    """Convert pandas extension dtypes to GeoPackage-safe dtypes."""
    out = df.copy()

    geometry_name = None
    if isinstance(out, gpd.GeoDataFrame):
        geometry_name = out.geometry.name

    for col in out.columns:
        if col == geometry_name:
            continue

        dtype = str(out[col].dtype)

        if dtype.startswith("Int") or dtype.startswith("UInt"):
            out[col] = out[col].astype("float").where(out[col].notna(), None)
        elif dtype == "string":
            out[col] = out[col].astype(object)
        elif dtype == "boolean":
            out[col] = out[col].astype("float").where(out[col].notna(), None)

    return out


def write_table_to_gpkg(df: pd.DataFrame, gpkg_path: Path, table_name: str) -> None:
    table = clean_for_gpkg(df)
    with sqlite3.connect(gpkg_path) as conn:
        table.to_sql(table_name, conn, if_exists="replace", index=False)


def select_gdf_columns(gdf: gpd.GeoDataFrame, columns: list[str]) -> gpd.GeoDataFrame:
    geom_col = gdf.geometry.name
    selected = []

    for col in columns:
        if col in gdf.columns and col not in selected:
            selected.append(col)

    if geom_col not in selected:
        selected.append(geom_col)

    return gdf[selected].copy()


def make_dirs(settings: Settings) -> None:
    settings.output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    settings.tables_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------------------------
# Input loading
# -----------------------------------------------------------------------------

def list_gpkg_layers(gpkg_path: Path) -> list[str]:
    if fiona is None:
        return []
    try:
        return list(fiona.listlayers(gpkg_path))
    except Exception:
        return []


def resolve_reference_layer(gpkg_path: Path, requested_layer: str | None) -> str | None:
    if requested_layer:
        return requested_layer

    layers = list_gpkg_layers(gpkg_path)

    if len(layers) == 1:
        return layers[0]

    candidates = [
        "puntos_sinac_src10_2021_con_extract_id",
        "preparacion_datos_sinac_auditoria_espectral",
        "sinac_src10_2021_con_extract_id",
    ]

    for candidate in candidates:
        if candidate in layers:
            return candidate

    if layers:
        raise ValueError(
            "El GPKG tiene múltiples capas y no se indicó --reference-layer. "
            f"Capas disponibles: {layers}"
        )

    return None


def load_reference_gpkg(settings: Settings) -> tuple[gpd.GeoDataFrame, str | None]:
    if not settings.reference_gpkg.exists():
        raise FileNotFoundError(
            f"No existe el GPKG de referencia: {settings.reference_gpkg}"
        )

    layer = resolve_reference_layer(settings.reference_gpkg, settings.reference_layer)

    if layer:
        gdf = gpd.read_file(settings.reference_gpkg, layer=layer)
    else:
        gdf = gpd.read_file(settings.reference_gpkg)

    gdf = clean_columns(gdf)

    if ID_COL not in gdf.columns:
        raise ValueError(
            f"El GPKG de referencia no contiene la columna requerida `{ID_COL}`. "
            "Este módulo debe ejecutarse sobre el GPKG ya preparado por el paso 06B."
        )

    if "original_record_row_id" not in gdf.columns:
        gdf.insert(0, "original_record_row_id", np.arange(1, len(gdf) + 1))

    gdf[ID_COL] = gdf[ID_COL].astype("string")

    return gdf, layer


def list_gee_exports(settings: Settings) -> tuple[list[Path], pd.DataFrame]:
    if not settings.gee_export_dir.exists():
        raise FileNotFoundError(
            f"No existe la carpeta de exports GEE: {settings.gee_export_dir}"
        )

    all_csv = sorted(settings.gee_export_dir.glob("*.csv"))
    csv_files = [p for p in all_csv if p.name.startswith(settings.gee_export_prefix)]

    if not csv_files:
        raise FileNotFoundError(
            "No se encontraron CSV de GEE con prefijo "
            f"`{settings.gee_export_prefix}` en {settings.gee_export_dir}"
        )

    rows = []
    for path in all_csv:
        header = read_csv_header(path)
        selected = path.name.startswith(settings.gee_export_prefix)
        rows.append(
            {
                "source_csv": path.name,
                "path": str(path),
                "size_mb": round(path.stat().st_size / (1024 * 1024), 3),
                "selected_for_processing": selected,
                "n_columns_header": len(header),
                "has_extract_id": ID_COL in header,
                "has_month": MONTH_COL in header,
                "has_n_obs_clean": "n_obs_clean" in header,
            }
        )

    inventory = pd.DataFrame(rows)
    return csv_files, inventory


def read_monthly_exports(csv_files: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    print("\nLeyendo CSV mensuales de GEE...")
    print(f"Archivos seleccionados: {len(csv_files):,}")

    for i, csv_path in enumerate(csv_files, start=1):
        header = read_csv_header(csv_path)

        if not header:
            print(f"[{i}/{len(csv_files)}] SKIP sin encabezado: {csv_path.name}")
            continue

        missing_required = [c for c in [ID_COL, MONTH_COL] if c not in header]
        if missing_required:
            print(
                f"[{i}/{len(csv_files)}] SKIP inválido: {csv_path.name}; "
                f"faltan {missing_required}"
            )
            continue

        usecols = [
            c
            for c in [ID_COL, MONTH_COL] + SPECTRAL_VALUE_COLS + METADATA_COLS
            if c in header
        ]

        print(f"[{i}/{len(csv_files)}] Leyendo: {csv_path.name} cols={len(usecols)}")

        for chunk in pd.read_csv(
            csv_path,
            encoding="utf-8-sig",
            usecols=usecols,
            chunksize=CHUNKSIZE,
            low_memory=False,
        ):
            chunk = clean_columns(chunk)
            chunk["source_csv"] = csv_path.name

            chunk[ID_COL] = chunk[ID_COL].astype("string")
            chunk[MONTH_COL] = pd.to_numeric(chunk[MONTH_COL], errors="coerce").astype("Int64")

            for col in SPECTRAL_VALUE_COLS:
                if col in chunk.columns:
                    chunk[col] = pd.to_numeric(chunk[col], errors="coerce")

            for col in ["year_ref", "year_extraction"]:
                if col in chunk.columns:
                    chunk[col] = pd.to_numeric(chunk[col], errors="coerce").astype("Int64")

            frames.append(chunk)

    if not frames:
        raise ValueError("No se pudo leer ningún CSV mensual válido de GEE.")

    monthly = pd.concat(frames, ignore_index=True)
    monthly = clean_columns(monthly)

    print(f"Filas mensuales leídas: {len(monthly):,}")
    print(f"Extract ID únicos en GEE: {monthly[ID_COL].nunique(dropna=True):,}")

    return monthly


# -----------------------------------------------------------------------------
# Monthly normalization and wide table
# -----------------------------------------------------------------------------

def normalize_monthly(monthly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    monthly = monthly.copy()

    monthly = monthly.dropna(subset=[ID_COL, MONTH_COL])
    monthly[ID_COL] = monthly[ID_COL].astype("string")
    monthly[MONTH_COL] = pd.to_numeric(monthly[MONTH_COL], errors="coerce").astype("Int64")
    monthly = monthly[monthly[MONTH_COL].between(1, 12)].copy()

    # Convert -9999 to NaN for spectral values and cloud probability.
    # n_obs_clean remains numeric because 0 is meaningful.
    for col in SPECTRAL_VALUE_COLS:
        if col in monthly.columns and col != "n_obs_clean":
            monthly[col] = pd.to_numeric(monthly[col], errors="coerce").replace(-9999, np.nan)

    if "n_obs_clean" in monthly.columns:
        monthly["n_obs_clean"] = pd.to_numeric(monthly["n_obs_clean"], errors="coerce").fillna(0)

    duplicate_mask = monthly.duplicated(subset=[ID_COL, MONTH_COL], keep=False)
    duplicates = monthly.loc[duplicate_mask].copy()

    if len(duplicates) > 0:
        print(
            "Advertencia: hay filas duplicadas por extract_id + month en GEE:",
            f"{len(duplicates):,}",
        )
        monthly = (
            monthly.sort_values([ID_COL, MONTH_COL, "source_csv"], na_position="last")
            .drop_duplicates(subset=[ID_COL, MONTH_COL], keep="first")
        )

    print(f"Filas mensuales únicas extract_id+month: {len(monthly):,}")
    return monthly, duplicates


def build_wide_table(monthly: pd.DataFrame) -> pd.DataFrame:
    value_cols = [col for col in SPECTRAL_VALUE_COLS if col in monthly.columns]

    if not value_cols:
        raise ValueError("No se encontraron columnas espectrales en los CSV GEE.")

    print("\nConstruyendo tabla wide mensual por extract_id...")

    wide_parts: list[pd.DataFrame] = []

    for value_col in value_cols:
        pivot = monthly.pivot_table(
            index=ID_COL,
            columns=MONTH_COL,
            values=value_col,
            aggfunc="first",
        )
        pivot.columns = [s2_monthly_col(int(month), value_col) for month in pivot.columns]
        wide_parts.append(pivot)

    wide = pd.concat(wide_parts, axis=1).reset_index()

    group = monthly.groupby(ID_COL, dropna=False)
    annual = group.size().reset_index(name="s2_n_month_rows")

    if "n_obs_clean" in monthly.columns:
        obs_summary = (
            group["n_obs_clean"]
            .agg(
                s2yr_obs_total="sum",
                s2yr_obs_mean="mean",
                s2yr_obs_median="median",
                s2yr_months_obs=lambda s: int((pd.to_numeric(s, errors="coerce").fillna(0) > 0).sum()),
                s2yr_months_zero_obs=lambda s: int((pd.to_numeric(s, errors="coerce").fillna(0) == 0).sum()),
            )
            .reset_index()
        )
        annual = annual.merge(obs_summary, on=ID_COL, how="left")

    if "cloud_prob_median" in monthly.columns:
        cloud = (
            group["cloud_prob_median"]
            .agg(s2yr_cloudprob_median="median", s2yr_cloudprob_mean="mean")
            .reset_index()
        )
        annual = annual.merge(cloud, on=ID_COL, how="left")

    for col in INDEX_COLS:
        if col in monthly.columns:
            tmp = (
                group[col]
                .agg(
                    **{
                        s2yr_col(col, "mean"): "mean",
                        s2yr_col(col, "median"): "median",
                        s2yr_col(col, "min"): "min",
                        s2yr_col(col, "max"): "max",
                    }
                )
                .reset_index()
            )
            annual = annual.merge(tmp, on=ID_COL, how="left")

    for col in ["year_ref", "year_extraction"]:
        if col in monthly.columns:
            tmp = group[col].first().reset_index(name=f"s2_{col}")
            annual = annual.merge(tmp, on=ID_COL, how="left")

    wide = wide.merge(annual, on=ID_COL, how="left")

    n_s2_cols = len([c for c in wide.columns if c.startswith("s2_") or c.startswith("s2yr_")])
    print(f"Tabla wide extract_id: {len(wide):,}")
    print(f"Columnas agregadas s2_/s2yr_: {n_s2_cols:,}")

    return wide


# -----------------------------------------------------------------------------
# Summaries
# -----------------------------------------------------------------------------

def build_monthly_obs_summary(monthly: pd.DataFrame) -> pd.DataFrame:
    if "n_obs_clean" not in monthly.columns:
        return pd.DataFrame()

    tmp = monthly.copy()
    tmp["n_obs_clean"] = pd.to_numeric(tmp["n_obs_clean"], errors="coerce").fillna(0)

    out = (
        tmp.groupby(MONTH_COL, dropna=False)
        .agg(
            rows=(ID_COL, "size"),
            extract_ids=(ID_COL, "nunique"),
            rows_zero_clean_obs=("n_obs_clean", lambda s: int((s == 0).sum())),
            median_clean_obs=("n_obs_clean", "median"),
            max_clean_obs=("n_obs_clean", "max"),
        )
        .reset_index()
        .sort_values(MONTH_COL)
    )
    out["pct_zero_clean_obs"] = (out["rows_zero_clean_obs"] / out["rows"] * 100).round(4)
    return out


def build_thematic_summary(original: gpd.GeoDataFrame) -> pd.DataFrame:
    cols_options = [
        ["class_group_code", "class_group_name", "class_code", "class_name"],
        ["GranClase", "nombre_gran_clase", "Clase", "nombre_clase"],
    ]

    for cols in cols_options:
        if all(col in original.columns for col in cols):
            return (
                original[[ID_COL] + cols]
                .drop_duplicates()
                .groupby(cols, dropna=False)
                .size()
                .reset_index(name="extract_units_or_records")
                .sort_values("extract_units_or_records", ascending=False)
            )

    return pd.DataFrame()


# -----------------------------------------------------------------------------
# Join and derived layers
# -----------------------------------------------------------------------------

def check_no_column_collision(original: gpd.GeoDataFrame, wide: pd.DataFrame) -> None:
    original_cols = set(original.columns)
    wide_cols = set(wide.columns) - {ID_COL}
    overlap = sorted(original_cols.intersection(wide_cols))

    if overlap:
        raise ValueError(
            "Hay columnas espectrales que ya existen en el GPKG original. "
            "Para no alterar columnas originales, revise: "
            f"{overlap[:50]}"
        )


def join_original_with_spectral(
    original: gpd.GeoDataFrame,
    wide: pd.DataFrame,
    settings: Settings,
    reference_layer: str | None,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    print("\nUniendo registros originales con valores espectrales...")

    check_no_column_collision(original, wide)

    original_ids = set(original[ID_COL].dropna().astype(str))
    gee_ids = set(wide[ID_COL].dropna().astype(str))

    missing_ids = sorted(original_ids - gee_ids)
    extra_ids = sorted(gee_ids - original_ids)

    missing_df = pd.DataFrame({ID_COL: missing_ids})
    extra_df = pd.DataFrame({ID_COL: extra_ids})

    if missing_ids:
        print("Extract ID del original sin valores GEE:", len(missing_ids))
        if not settings.allow_missing:
            raise ValueError(
                "Hay extract_id del GPKG original que no aparecen en los CSV GEE. "
                f"Faltantes: {len(missing_ids):,}. "
                "Ejecute con --allow-missing si desea continuar."
            )

    original_rows = len(original)

    original = original.copy()
    wide = wide.copy()
    original[ID_COL] = original[ID_COL].astype("string")
    wide[ID_COL] = wide[ID_COL].astype("string")

    full = original.merge(wide, on=ID_COL, how="left")

    if len(full) != original_rows:
        raise ValueError(
            "El número de filas cambió después del merge. "
            f"Original={original_rows:,}, Output={len(full):,}"
        )

    validation = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_name": SOURCE_NAME,
        "source_code": SOURCE_CODE,
        "source_id_expected": SOURCE_ID,
        "country_code_expected": COUNTRY_CODE,
        "year_ref_expected": YEAR_REF,
        "reference_gpkg": str(settings.reference_gpkg),
        "reference_layer": reference_layer or "No identificado",
        "gee_export_dir": str(settings.gee_export_dir),
        "gee_export_prefix": settings.gee_export_prefix,
        "output_gpkg": str(settings.output_gpkg),
        "original_rows": int(original_rows),
        "output_rows": int(len(full)),
        "row_count_matches": format_bool(original_rows == len(full)),
        "original_unique_extract_id": int(len(original_ids)),
        "gee_unique_extract_id": int(len(gee_ids)),
        "n_missing_extract_id_in_gee": int(len(missing_ids)),
        "n_extra_extract_id_in_gee": int(len(extra_ids)),
        "all_original_extract_id_have_spectral": format_bool(len(missing_ids) == 0),
        "allow_missing": format_bool(settings.allow_missing),
    }

    print(f"Filas salida {LAYER_FULL}: {len(full):,}")
    return full, missing_df, extra_df, validation


def original_core_columns() -> list[str]:
    """Core columns for reduced and annual layers in the SINAC SRC10 pilot."""
    return [
        "original_record_row_id",
        ID_COL,
        "id_registro",
        "id_muestra_original",
        "Id",
        "id",
        "xy_group_id",
        "xy_year_group_id",
        "xy_class_group_id",
        "Longitud",
        "Latitud",
        "lon",
        "lat",
        "lon_out",
        "lat_out",
        "Pais_es",
        "Pais_cod3",
        "country",
        "country_code",
        "Fuente",
        "id_fuente",
        "source",
        "source_id",
        "Año",
        "year_ref",
        "Clase",
        "GranClase",
        "nombre_clase",
        "nombre_gran_clase",
        "class_code",
        "class_group_code",
        "class_name",
        "class_group_name",
        "n_records_extract_unit",
        "n_unique_class_code_extract_unit",
        "n_unique_class_group_code_extract_unit",
        "n_unique_class_name_extract_unit",
        "n_unique_class_group_name_extract_unit",
        "has_thematic_conflict",
        "batch_id",
    ]


def reduced_monthly_index_columns(df: pd.DataFrame) -> list[str]:
    cols = []
    for month in range(1, 13):
        for index_name in INDEX_COLS:
            col = s2_monthly_col(month, index_name)
            if col in df.columns:
                cols.append(col)
    return cols


def monthly_obs_columns(df: pd.DataFrame) -> list[str]:
    cols = []
    for month in range(1, 13):
        col = s2_monthly_col(month, "n_obs_clean")
        if col in df.columns:
            cols.append(col)
    return cols


def annual_s2_columns(df: pd.DataFrame) -> list[str]:
    wanted = [
        "s2_n_month_rows",
        "s2_year_ref",
        "s2_year_extraction",
        "s2yr_months_obs",
        "s2yr_months_zero_obs",
        "s2yr_obs_total",
        "s2yr_obs_mean",
        "s2yr_obs_median",
        "s2yr_cloudprob_median",
        "s2yr_cloudprob_mean",
        "s2yr_ndvi_mean",
        "s2yr_ndvi_median",
        "s2yr_ndvi_min",
        "s2yr_ndvi_max",
        "s2yr_ndvi8a_mean",
        "s2yr_ndvi8a_median",
        "s2yr_ndvi8a_min",
        "s2yr_ndvi8a_max",
        "s2yr_ndre_mean",
        "s2yr_ndre_median",
        "s2yr_ndre_min",
        "s2yr_ndre_max",
    ]
    return [col for col in wanted if col in df.columns]


def build_reduced_layer(full: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    cols = original_core_columns()
    cols += reduced_monthly_index_columns(full)
    cols += monthly_obs_columns(full)
    cols += annual_s2_columns(full)

    reduced = select_gdf_columns(full, cols)
    print(f"Capa {LAYER_REDUCED}: {len(reduced):,}")
    print(f"Columnas reduced: {len(reduced.columns):,}")
    return reduced


def build_annual_layer(full: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    cols = original_core_columns()
    cols += annual_s2_columns(full)

    annual = select_gdf_columns(full, cols)
    print(f"Capa {LAYER_ANNUAL}: {len(annual):,}")
    print(f"Columnas annual: {len(annual.columns):,}")
    return annual


def build_extract_units_annual(original: gpd.GeoDataFrame, wide: pd.DataFrame) -> gpd.GeoDataFrame:
    print("\nConstruyendo capa anual sin duplicados por extract_id...")

    geom_col = original.geometry.name

    keep_cols = [col for col in original_core_columns() if col in original.columns]
    if geom_col not in keep_cols:
        keep_cols.append(geom_col)

    base_units = original[keep_cols].drop_duplicates(subset=[ID_COL], keep="first").copy()

    annual_cols = [ID_COL] + annual_s2_columns(wide)
    annual_cols = [col for col in annual_cols if col in wide.columns]
    annual_wide = wide[annual_cols].copy()

    base_units[ID_COL] = base_units[ID_COL].astype("string")
    annual_wide[ID_COL] = annual_wide[ID_COL].astype("string")

    units = base_units.merge(annual_wide, on=ID_COL, how="left")
    units_gdf = gpd.GeoDataFrame(units, geometry=geom_col, crs=original.crs)

    print(f"Capa {LAYER_UNITS_ANNUAL}: {len(units_gdf):,}")
    print(f"Columnas extract_units annual: {len(units_gdf.columns):,}")
    return units_gdf


# -----------------------------------------------------------------------------
# Outputs and report
# -----------------------------------------------------------------------------

def save_control_tables_csv(
    settings: Settings,
    validation: dict[str, Any],
    input_inventory: pd.DataFrame,
    missing_df: pd.DataFrame,
    extra_df: pd.DataFrame,
    duplicates_df: pd.DataFrame,
    monthly_summary: pd.DataFrame,
    thematic_summary: pd.DataFrame,
) -> None:
    settings.tables_dir.mkdir(parents=True, exist_ok=True)

    outputs = {
        "validation_summary.csv": pd.DataFrame([validation]),
        "input_files_inventory.csv": input_inventory,
        "missing_extract_id_in_gee.csv": missing_df,
        "extra_extract_id_in_gee.csv": extra_df,
        "duplicate_gee_extract_id_month.csv": duplicates_df,
        "monthly_clean_obs_summary.csv": monthly_summary,
        "thematic_extract_units_summary.csv": thematic_summary,
    }

    print("\nGuardando tablas CSV de control...")
    for name, df in outputs.items():
        path = settings.tables_dir / name
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(" -", path)


def save_outputs_gpkg(
    settings: Settings,
    full: gpd.GeoDataFrame,
    reduced: gpd.GeoDataFrame,
    annual: gpd.GeoDataFrame,
    units_annual: gpd.GeoDataFrame,
    validation: dict[str, Any],
    input_inventory: pd.DataFrame,
    missing_df: pd.DataFrame,
    extra_df: pd.DataFrame,
    duplicates_df: pd.DataFrame,
    monthly_summary: pd.DataFrame,
    thematic_summary: pd.DataFrame,
) -> None:
    print("\nGuardando salidas en GPKG único...")

    if settings.output_gpkg.exists():
        settings.output_gpkg.unlink()

    print("Escribiendo capa completa:", LAYER_FULL)
    clean_for_gpkg(full).to_file(settings.output_gpkg, layer=LAYER_FULL, driver="GPKG")

    print("Escribiendo capa reducida:", LAYER_REDUCED)
    clean_for_gpkg(reduced).to_file(settings.output_gpkg, layer=LAYER_REDUCED, driver="GPKG")

    print("Escribiendo capa anual:", LAYER_ANNUAL)
    clean_for_gpkg(annual).to_file(settings.output_gpkg, layer=LAYER_ANNUAL, driver="GPKG")

    print("Escribiendo capa anual sin duplicados:", LAYER_UNITS_ANNUAL)
    clean_for_gpkg(units_annual).to_file(settings.output_gpkg, layer=LAYER_UNITS_ANNUAL, driver="GPKG")

    write_table_to_gpkg(pd.DataFrame([validation]), settings.output_gpkg, TABLE_VALIDATION)
    write_table_to_gpkg(input_inventory, settings.output_gpkg, TABLE_INPUT_FILES)
    write_table_to_gpkg(missing_df, settings.output_gpkg, TABLE_MISSING)
    write_table_to_gpkg(extra_df, settings.output_gpkg, TABLE_EXTRA)
    write_table_to_gpkg(duplicates_df, settings.output_gpkg, TABLE_DUPLICATES)
    write_table_to_gpkg(monthly_summary, settings.output_gpkg, TABLE_MONTHLY_OBS)
    write_table_to_gpkg(thematic_summary, settings.output_gpkg, TABLE_THEMATIC)

    print("GPKG final:", settings.output_gpkg)


def generate_report(
    settings: Settings,
    validation: dict[str, Any],
    full: gpd.GeoDataFrame,
    reduced: gpd.GeoDataFrame,
    annual: gpd.GeoDataFrame,
    units_annual: gpd.GeoDataFrame,
    input_inventory: pd.DataFrame,
    missing_df: pd.DataFrame,
    extra_df: pd.DataFrame,
    duplicates_df: pd.DataFrame,
    monthly_summary: pd.DataFrame,
    thematic_summary: pd.DataFrame,
) -> None:
    settings.reports_dir.mkdir(parents=True, exist_ok=True)

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    resumen_df = pd.DataFrame(
        [
            {"indicador": "Filas originales", "valor": validation.get("original_rows")},
            {"indicador": "Filas capa completa", "valor": validation.get("full_layer_rows")},
            {"indicador": "Filas capa reducida", "valor": validation.get("reduced_layer_rows")},
            {"indicador": "Filas capa anual", "valor": validation.get("annual_layer_rows")},
            {"indicador": "Filas capa anual sin duplicados", "valor": validation.get("extract_units_annual_rows")},
            {"indicador": "Extract ID únicos originales", "valor": validation.get("original_unique_extract_id")},
            {"indicador": "Extract ID únicos en GEE", "valor": validation.get("gee_unique_extract_id")},
            {"indicador": "Extract ID faltantes en GEE", "valor": validation.get("n_missing_extract_id_in_gee")},
            {"indicador": "Extract ID extra en GEE", "valor": validation.get("n_extra_extract_id_in_gee")},
            {"indicador": "Duplicados GEE por extract_id + mes", "valor": validation.get("duplicate_gee_extract_id_month_rows")},
            {"indicador": "CSV seleccionados para procesamiento", "valor": validation.get("input_csv_files_selected")},
        ]
    )

    capas_df = pd.DataFrame(
        [
            {
                "capa_tabla": LAYER_FULL,
                "tipo": "capa espacial",
                "unidad": "registro original",
                "filas": len(full),
                "descripcion": "Columnas originales + bandas/índices mensuales + métricas anuales.",
            },
            {
                "capa_tabla": LAYER_REDUCED,
                "tipo": "capa espacial",
                "unidad": "registro original",
                "filas": len(reduced),
                "descripcion": "Capa práctica para revisión: campos clave + índices mensuales + observaciones + resumen anual.",
            },
            {
                "capa_tabla": LAYER_ANNUAL,
                "tipo": "capa espacial",
                "unidad": "registro original",
                "filas": len(annual),
                "descripcion": "Resumen anual por registro original.",
            },
            {
                "capa_tabla": LAYER_UNITS_ANNUAL,
                "tipo": "capa espacial",
                "unidad": "extract_id único",
                "filas": len(units_annual),
                "descripcion": "Resumen anual sin duplicados por unidad espectral extraída en GEE.",
            },
            {"capa_tabla": TABLE_VALIDATION, "tipo": "tabla", "unidad": "control", "filas": 1, "descripcion": "Resumen de validación."},
            {"capa_tabla": TABLE_INPUT_FILES, "tipo": "tabla", "unidad": "archivo CSV", "filas": len(input_inventory), "descripcion": "Inventario de CSV."},
            {"capa_tabla": TABLE_MISSING, "tipo": "tabla", "unidad": "extract_id", "filas": len(missing_df), "descripcion": "Extract ID faltantes en GEE."},
            {"capa_tabla": TABLE_EXTRA, "tipo": "tabla", "unidad": "extract_id", "filas": len(extra_df), "descripcion": "Extract ID extra en GEE."},
            {"capa_tabla": TABLE_DUPLICATES, "tipo": "tabla", "unidad": "extract_id + mes", "filas": len(duplicates_df), "descripcion": "Duplicados en CSV GEE."},
            {"capa_tabla": TABLE_MONTHLY_OBS, "tipo": "tabla", "unidad": "mes", "filas": len(monthly_summary), "descripcion": "Control mensual de observaciones limpias."},
            {"capa_tabla": TABLE_THEMATIC, "tipo": "tabla", "unidad": "clase", "filas": len(thematic_summary), "descripcion": "Resumen temático de unidades/registros."},
        ]
    )

    contenido = "\n".join(
        [
            "# Unión de registros SINAC SRC10 2021 con valores espectrales Sentinel-2 SR",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## 1. Propósito",
            "",
            "Este módulo une los registros originales/elegibles de la fuente SINAC SRC10 2021 con los valores espectro-temporales mensuales exportados desde Google Earth Engine.",
            "",
            "La llave de unión es `extract_id`, que representa la unidad única de extracción definida como `Longitud + Latitud + Año`.",
            "",
            "## 2. Entradas principales",
            "",
            "| Insumo | Ruta / valor |",
            "|---|---|",
            f"| GPKG de registros con `extract_id` | `{fmt_path(settings.reference_gpkg)}` |",
            f"| Capa de referencia | `{validation.get('reference_layer')}` |",
            f"| Carpeta de CSV GEE | `{fmt_path(settings.gee_export_dir)}` |",
            f"| Prefijo de CSV procesados | `{settings.gee_export_prefix}` |",
            "",
            "## 3. Salidas principales",
            "",
            "| Producto | Ruta |",
            "|---|---|",
            f"| GeoPackage final | `{fmt_path(settings.output_gpkg)}` |",
            f"| Tablas de control CSV | `{fmt_path(settings.tables_dir)}` |",
            f"| Reporte Markdown | `{fmt_path(settings.report_md)}` |",
            "",
            "## 4. Capas y tablas generadas",
            "",
            dataframe_a_markdown(capas_df),
            "",
            "## 5. Resumen de validación",
            "",
            dataframe_a_markdown(resumen_df),
            "",
            "## 6. Control mensual de observaciones limpias",
            "",
            dataframe_a_markdown(monthly_summary) if not monthly_summary.empty else "No se generó tabla mensual.",
            "",
            "## 7. Resumen temático",
            "",
            dataframe_a_markdown(thematic_summary) if not thematic_summary.empty else "No se generó resumen temático.",
            "",
            "## 8. Nota metodológica",
            "",
            "Los CSV de GEE llegan en formato largo, con una fila por `extract_id` y mes. Este módulo transforma los datos a formato ancho para unirlos con los registros originales.",
            "",
            "Los valores `-9999` exportados desde GEE se interpretan como ausencia de dato válido y se convierten a nulos antes de calcular métricas anuales. El campo `n_obs_clean` conserva el valor cero porque indica explícitamente meses sin observaciones limpias.",
            "",
            "La capa completa conserva todos los registros originales, incluyendo casos en que varios registros comparten un mismo `extract_id`. La capa de unidades anuales elimina duplicados por `extract_id` para análisis espectral sin sobreponderar puntos repetidos.",
            "",
        ]
    )

    settings.report_md.write_text(contenido, encoding="utf-8")
    print("\nReporte Markdown guardado en:")
    print(" -", settings.report_md)


# -----------------------------------------------------------------------------
# CLI and main
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Une registros SINAC SRC10 2021 con valores espectrales mensuales/anuales "
            "de Sentinel-2 SR exportados desde Google Earth Engine."
        )
    )

    parser.add_argument(
        "--reference-gpkg",
        type=str,
        default=str(DEFAULT_REFERENCE_GPKG),
        help="Ruta al GPKG con registros SINAC SRC10 2021 y extract_id.",
    )
    parser.add_argument(
        "--reference-layer",
        type=str,
        default=DEFAULT_REFERENCE_LAYER,
        help="Capa del GPKG de referencia. Si se omite, se intenta detectar automáticamente.",
    )
    parser.add_argument(
        "--gee-export-dir",
        type=str,
        default=str(DEFAULT_GEE_EXPORT_DIR),
        help="Carpeta con CSV exportados desde GEE.",
    )
    parser.add_argument(
        "--gee-export-prefix",
        type=str,
        default=DEFAULT_GEE_EXPORT_PREFIX,
        help="Prefijo de los CSV GEE a procesar.",
    )
    parser.add_argument(
        "--output-gpkg",
        type=str,
        default=str(DEFAULT_OUTPUT_GPKG),
        help="GeoPackage de salida.",
    )
    parser.add_argument(
        "--tables-dir",
        type=str,
        default=str(DEFAULT_TABLES_DIR),
        help="Carpeta para tablas CSV de control.",
    )
    parser.add_argument(
        "--reports-dir",
        type=str,
        default=str(DEFAULT_REPORTS_DIR),
        help="Carpeta para reporte Markdown.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Permite continuar aunque algunos extract_id originales no aparezcan en GEE.",
    )

    return parser.parse_args()


def build_settings(args: argparse.Namespace) -> Settings:
    reports_dir = resolve_path(args.reports_dir)
    return Settings(
        reference_gpkg=resolve_path(args.reference_gpkg),
        reference_layer=args.reference_layer,
        gee_export_dir=resolve_path(args.gee_export_dir),
        gee_export_prefix=args.gee_export_prefix,
        output_gpkg=resolve_path(args.output_gpkg),
        tables_dir=resolve_path(args.tables_dir),
        reports_dir=reports_dir,
        report_md=reports_dir / DEFAULT_REPORT_NAME,
        allow_missing=bool(args.allow_missing),
    )


def main() -> None:
    args = parse_args()
    settings = build_settings(args)

    make_dirs(settings)

    print("============================================================")
    print("PGBM - SINAC SRC10 2021 + Sentinel-2 SR")
    print("============================================================")
    print("Project dir:", PROJECT_DIR)
    print("GPKG referencia:", settings.reference_gpkg)
    print("Layer referencia:", settings.reference_layer or "auto")
    print("CSV GEE dir:", settings.gee_export_dir)
    print("CSV prefix:", settings.gee_export_prefix)
    print("Output GPKG:", settings.output_gpkg)
    print("Tables dir:", settings.tables_dir)
    print("Reports dir:", settings.reports_dir)
    print("============================================================")

    original, reference_layer = load_reference_gpkg(settings)
    print(f"\nFilas originales/elegibles: {len(original):,}")
    print(f"Extract ID únicos originales: {original[ID_COL].nunique(dropna=True):,}")
    print("CRS original:", original.crs)
    print("Layer usada:", reference_layer or "No identificado")

    csv_files, input_inventory = list_gee_exports(settings)
    monthly_raw = read_monthly_exports(csv_files)
    monthly, duplicates_df = normalize_monthly(monthly_raw)
    wide = build_wide_table(monthly)

    monthly_summary = build_monthly_obs_summary(monthly)
    thematic_summary = build_thematic_summary(original)

    full, missing_df, extra_df, validation = join_original_with_spectral(
        original=original,
        wide=wide,
        settings=settings,
        reference_layer=reference_layer,
    )

    reduced = build_reduced_layer(full)
    annual = build_annual_layer(full)
    units_annual = build_extract_units_annual(original=original, wide=wide)

    validation["full_layer_rows"] = int(len(full))
    validation["reduced_layer_rows"] = int(len(reduced))
    validation["annual_layer_rows"] = int(len(annual))
    validation["extract_units_annual_rows"] = int(len(units_annual))
    validation["duplicate_gee_extract_id_month_rows"] = int(len(duplicates_df))
    validation["input_csv_files_selected"] = int(len(csv_files))
    validation["input_csv_files_total"] = int(len(input_inventory))
    validation["layer_full"] = LAYER_FULL
    validation["layer_reduced"] = LAYER_REDUCED
    validation["layer_annual"] = LAYER_ANNUAL
    validation["layer_extract_units_annual"] = LAYER_UNITS_ANNUAL
    validation["tables_dir"] = str(settings.tables_dir)
    validation["reports_dir"] = str(settings.reports_dir)
    validation["report_markdown"] = str(settings.report_md)

    save_outputs_gpkg(
        settings=settings,
        full=full,
        reduced=reduced,
        annual=annual,
        units_annual=units_annual,
        validation=validation,
        input_inventory=input_inventory,
        missing_df=missing_df,
        extra_df=extra_df,
        duplicates_df=duplicates_df,
        monthly_summary=monthly_summary,
        thematic_summary=thematic_summary,
    )

    save_control_tables_csv(
        settings=settings,
        validation=validation,
        input_inventory=input_inventory,
        missing_df=missing_df,
        extra_df=extra_df,
        duplicates_df=duplicates_df,
        monthly_summary=monthly_summary,
        thematic_summary=thematic_summary,
    )

    generate_report(
        settings=settings,
        validation=validation,
        full=full,
        reduced=reduced,
        annual=annual,
        units_annual=units_annual,
        input_inventory=input_inventory,
        missing_df=missing_df,
        extra_df=extra_df,
        duplicates_df=duplicates_df,
        monthly_summary=monthly_summary,
        thematic_summary=thematic_summary,
    )

    print("\n============================================================")
    print("PROCESO FINALIZADO")
    print("============================================================")
    print("Filas originales:", validation["original_rows"])
    print("Filas capa completa:", validation["full_layer_rows"])
    print("Filas capa reducida:", validation["reduced_layer_rows"])
    print("Filas capa anual:", validation["annual_layer_rows"])
    print("Filas capa anual sin duplicados:", validation["extract_units_annual_rows"])
    print("Filas coinciden:", validation["row_count_matches"])
    print("Extract ID originales:", validation["original_unique_extract_id"])
    print("Extract ID GEE:", validation["gee_unique_extract_id"])
    print("Faltantes en GEE:", validation["n_missing_extract_id_in_gee"])
    print("Extras en GEE:", validation["n_extra_extract_id_in_gee"])
    print("Duplicados GEE extract_id+month:", validation["duplicate_gee_extract_id_month_rows"])
    print("Todos los originales tienen espectral:", validation["all_original_extract_id_have_spectral"])
    print("Salida GPKG:", settings.output_gpkg)
    print("Tablas:", settings.tables_dir)
    print("Reporte:", settings.report_md)
    print("============================================================")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
