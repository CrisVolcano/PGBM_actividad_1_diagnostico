from __future__ import annotations

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


# =============================================================================
# PGBM - Join original records with Sentinel-2 SR monthly spectral values
# =============================================================================
#
# Purpose:
#   Preserve every original record from:
#
#     data/processed/s2_sr_gee_input/puntos_s2_sr_2018_2022.gpkg
#
#   and append monthly/yearly spectral values extracted from GEE.
#
# Main rules:
#   1. Original column names are NOT renamed.
#   2. New Sentinel-2 columns use short names:
#        s2_01_ndvi, s2_01_b02, s2yr_ndvi_mean, etc.
#   3. Outputs are written to a single GeoPackage.
#   4. Control tables are also exported to outputs/tables.
#   5. A concise Markdown report is exported to outputs/reports.
#   6. No JSON outputs.
#   7. No Parquet outputs.
#
# Main output:
#   data/processed/s2_sr_original_records_with_spectral/
#   └─ puntos_s2_sr_2018_2022_s2sr_join_outputs.gpkg
#
# GPKG layers:
#   - original_records_s2sr_full
#   - original_records_s2sr_reduced
#   - original_records_s2sr_annual
#   - extract_units_s2sr_annual
#
# GPKG control tables:
#   - validation_summary
#   - input_files_inventory
#   - missing_extract_id_in_gee
#   - extra_extract_id_in_gee
#   - duplicate_gee_extract_id_month
#
# CSV control tables:
#   outputs/tables/s2_sr_original_records_with_spectral/
#
# Markdown report:
#   outputs/reports/s2_sr_original_records_with_spectral/
#
# Run:
#   python src/08_join_s2sr_to_original_records.py
# =============================================================================


# -----------------------------------------------------------------------------
# Input/output configuration
# -----------------------------------------------------------------------------

GEE_EXPORT_PREFIX = "pgbm_s2sr_monthly_s2cloudless_"

REFERENCE_GPKG_REL = Path(
    "data/processed/s2_sr_gee_input/puntos_s2_sr_2018_2022.gpkg"
)
REFERENCE_LAYER = "puntos_s2_sr_2018_2022"

GEE_EXPORT_DIR_REL = Path("data/raw/PGBM_S2SR_monthly_s2cloudless")

OUTPUT_DIR_REL = Path("data/processed/s2_sr_original_records_with_spectral")
OUTPUT_GPKG_NAME = "puntos_s2_sr_2018_2022_s2sr_join_outputs.gpkg"

TABLES_DIR_REL = Path("outputs/tables/s2_sr_original_records_with_spectral")
REPORTS_DIR_REL = Path("outputs/reports/s2_sr_original_records_with_spectral")
REPORT_MD_NAME = "08_s2sr_original_records_join_report.md"

LAYER_FULL = "original_records_s2sr_full"
LAYER_REDUCED = "original_records_s2sr_reduced"
LAYER_ANNUAL = "original_records_s2sr_annual"
LAYER_UNITS_ANNUAL = "extract_units_s2sr_annual"

TABLE_VALIDATION = "validation_summary"
TABLE_INPUT_FILES = "input_files_inventory"
TABLE_MISSING = "missing_extract_id_in_gee"
TABLE_EXTRA = "extra_extract_id_in_gee"
TABLE_DUPLICATES = "duplicate_gee_extract_id_month"

VALIDATION_SUMMARY_CSV_NAME = "validation_summary.csv"
INPUT_FILES_INVENTORY_CSV_NAME = "input_files_inventory.csv"
MISSING_EXTRACT_ID_CSV_NAME = "missing_extract_id_in_gee.csv"
EXTRA_EXTRACT_ID_CSV_NAME = "extra_extract_id_in_gee.csv"
DUPLICATE_GEE_ROWS_CSV_NAME = "duplicate_gee_extract_id_month.csv"

CHUNKSIZE = 250_000

ID_COL = "extract_id"
MONTH_COL = "month"

SPECTRAL_VALUE_COLS = [
    "B1",
    "B2",
    "B3",
    "B4",
    "B5",
    "B6",
    "B7",
    "B8",
    "B8A",
    "B9",
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
    "source_csv",
]


# -----------------------------------------------------------------------------
# Project paths
# -----------------------------------------------------------------------------

def find_project_root() -> Path:
    starts = [Path(__file__).resolve().parent, Path.cwd().resolve()]
    visited: set[Path] = set()

    for start in starts:
        for path in [start, *start.parents]:
            if path in visited:
                continue

            visited.add(path)

            if (path / ".git").exists() or (path / "config" / "config.yaml").exists():
                return path

    raise FileNotFoundError(
        "No se pudo localizar la raíz del proyecto. "
        "Ejecute el script desde el repositorio o guárdelo dentro de src/."
    )


PROJECT_ROOT = find_project_root()

REFERENCE_GPKG = PROJECT_ROOT / REFERENCE_GPKG_REL
GEE_EXPORT_DIR = PROJECT_ROOT / GEE_EXPORT_DIR_REL

OUTPUT_DIR = PROJECT_ROOT / OUTPUT_DIR_REL
OUTPUT_GPKG = OUTPUT_DIR / OUTPUT_GPKG_NAME

TABLES_DIR = PROJECT_ROOT / TABLES_DIR_REL
REPORTS_DIR = PROJECT_ROOT / REPORTS_DIR_REL
REPORT_MD = REPORTS_DIR / REPORT_MD_NAME

VALIDATION_SUMMARY_CSV = TABLES_DIR / VALIDATION_SUMMARY_CSV_NAME
INPUT_FILES_INVENTORY_CSV = TABLES_DIR / INPUT_FILES_INVENTORY_CSV_NAME
MISSING_EXTRACT_ID_CSV = TABLES_DIR / MISSING_EXTRACT_ID_CSV_NAME
EXTRA_EXTRACT_ID_CSV = TABLES_DIR / EXTRA_EXTRACT_ID_CSV_NAME
DUPLICATE_GEE_ROWS_CSV = TABLES_DIR / DUPLICATE_GEE_ROWS_CSV_NAME


# -----------------------------------------------------------------------------
# Generic utilities
# -----------------------------------------------------------------------------

def crear_carpetas() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    return df


def read_csv_header(path: Path) -> list[str]:
    encodings = ["utf-8-sig", "utf-8", "latin-1"]

    for encoding in encodings:
        try:
            with open(path, "r", encoding=encoding, newline="") as file:
                reader = csv.reader(file)
                return [
                    str(c).replace("\ufeff", "").strip()
                    for c in next(reader, [])
                ]
        except UnicodeDecodeError:
            continue
        except Exception:
            return []

    return []


def format_bool(value: bool) -> str:
    return "true" if bool(value) else "false"


def fmt_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def dataframe_a_markdown(df: pd.DataFrame) -> str:
    """Convierte un DataFrame a Markdown de forma segura."""
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


def s2_base_name(name: str) -> str:
    """
    Convert original GEE variable names to short lowercase suffixes.
    """
    mapping = {
        "B1": "b01",
        "B2": "b02",
        "B3": "b03",
        "B4": "b04",
        "B5": "b05",
        "B6": "b06",
        "B7": "b07",
        "B8": "b08",
        "B8A": "b8a",
        "B9": "b09",
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


def is_monthly_s2_col(col: str) -> bool:
    return (
        col.startswith("s2_")
        and len(col) > 6
        and col[3:5].isdigit()
        and col[5] == "_"
    )


def clean_for_gpkg(df: pd.DataFrame | gpd.GeoDataFrame) -> pd.DataFrame | gpd.GeoDataFrame:
    """
    Convert pandas extension dtypes to types that write safely to GeoPackage.
    """
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


def remove_previous_optional_csvs() -> None:
    for path in [
        MISSING_EXTRACT_ID_CSV,
        EXTRA_EXTRACT_ID_CSV,
        DUPLICATE_GEE_ROWS_CSV,
    ]:
        if path.exists():
            path.unlink()


def select_gdf_columns(
    gdf: gpd.GeoDataFrame,
    columns: list[str],
) -> gpd.GeoDataFrame:
    """
    Select existing columns and preserve geometry.
    """
    geom_col = gdf.geometry.name

    selected = []
    for col in columns:
        if col in gdf.columns and col not in selected:
            selected.append(col)

    if geom_col not in selected:
        selected.append(geom_col)

    return gdf[selected].copy()


# -----------------------------------------------------------------------------
# Input loading
# -----------------------------------------------------------------------------

def listar_exports_gee() -> tuple[list[Path], pd.DataFrame]:
    if not GEE_EXPORT_DIR.exists():
        raise FileNotFoundError(f"No existe la carpeta de exports GEE: {GEE_EXPORT_DIR}")

    all_csv = sorted(GEE_EXPORT_DIR.glob("*.csv"))

    csv_files = [
        p for p in all_csv
        if p.name.startswith(GEE_EXPORT_PREFIX)
    ]

    if not csv_files:
        raise FileNotFoundError(
            "No se encontraron CSV de GEE con prefijo "
            f"{GEE_EXPORT_PREFIX} en {GEE_EXPORT_DIR}"
        )

    rows = []
    for p in all_csv:
        selected = p.name.startswith(GEE_EXPORT_PREFIX)
        header = read_csv_header(p)

        rows.append(
            {
                "source_csv": p.name,
                "path": str(p),
                "size_mb": round(p.stat().st_size / (1024 * 1024), 3),
                "selected_for_processing": selected,
                "n_columns_header": len(header),
                "has_extract_id": ID_COL in header,
                "has_month": MONTH_COL in header,
            }
        )

    inventory = pd.DataFrame(rows)

    return csv_files, inventory


def cargar_original_gpkg() -> gpd.GeoDataFrame:
    if not REFERENCE_GPKG.exists():
        raise FileNotFoundError(f"No existe el GPKG de referencia: {REFERENCE_GPKG}")

    gdf = gpd.read_file(REFERENCE_GPKG, layer=REFERENCE_LAYER)
    gdf = clean_columns(gdf)

    if ID_COL not in gdf.columns:
        raise ValueError(
            f"El GPKG de referencia no contiene la columna requerida: {ID_COL}"
        )

    # No renombramos columnas originales.
    # Solo agregamos un ID técnico para preservar orden/fila original.
    if "original_record_row_id" not in gdf.columns:
        gdf.insert(0, "original_record_row_id", np.arange(1, len(gdf) + 1))

    gdf[ID_COL] = gdf[ID_COL].astype("string")

    return gdf


def leer_exports_mensuales(csv_files: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    print("\nLeyendo CSV mensuales de GEE...")
    print(f"Total archivos candidatos: {len(csv_files):,}")

    for i, csv_path in enumerate(csv_files, start=1):
        header = read_csv_header(csv_path)

        if not header:
            print(f"[{i}/{len(csv_files)}] SKIP sin encabezado: {csv_path.name}")
            continue

        required = [ID_COL, MONTH_COL]
        missing_required = [c for c in required if c not in header]

        if missing_required:
            print(
                f"[{i}/{len(csv_files)}] SKIP no mensual o inválido: {csv_path.name} "
                f"faltan {missing_required}"
            )
            continue

        usecols = [
            c
            for c in [ID_COL, MONTH_COL] + SPECTRAL_VALUE_COLS + METADATA_COLS
            if c in header
        ]

        print(
            f"[{i}/{len(csv_files)}] Leyendo: {csv_path.name} "
            f"cols={len(usecols)}"
        )

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
            chunk[MONTH_COL] = pd.to_numeric(
                chunk[MONTH_COL],
                errors="coerce",
            ).astype("Int64")

            for col in SPECTRAL_VALUE_COLS:
                if col in chunk.columns:
                    chunk[col] = pd.to_numeric(chunk[col], errors="coerce")

            for col in ["year_ref", "year_extraction"]:
                if col in chunk.columns:
                    chunk[col] = pd.to_numeric(
                        chunk[col],
                        errors="coerce",
                    ).astype("Int64")

            frames.append(chunk)

    if not frames:
        raise ValueError("No se pudo leer ningún CSV mensual válido de GEE.")

    monthly = pd.concat(frames, ignore_index=True)
    monthly = clean_columns(monthly)

    print(f"Filas mensuales leídas: {len(monthly):,}")
    print(f"Extract ID únicos en GEE mensual: {monthly[ID_COL].nunique(dropna=True):,}")

    return monthly


# -----------------------------------------------------------------------------
# Monthly normalization and wide table
# -----------------------------------------------------------------------------

def normalizar_monthly(monthly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    monthly = monthly.copy()

    monthly = monthly.dropna(subset=[ID_COL, MONTH_COL])
    monthly[ID_COL] = monthly[ID_COL].astype("string")
    monthly[MONTH_COL] = pd.to_numeric(
        monthly[MONTH_COL],
        errors="coerce",
    ).astype("Int64")

    # Convertimos -9999 a NaN en variables espectrales.
    # Los CSV raw quedan intactos en data/raw.
    for col in SPECTRAL_VALUE_COLS:
        if col in monthly.columns and col != "n_obs_clean":
            monthly[col] = (
                pd.to_numeric(monthly[col], errors="coerce")
                .replace(-9999, np.nan)
            )

    if "n_obs_clean" in monthly.columns:
        monthly["n_obs_clean"] = (
            pd.to_numeric(monthly["n_obs_clean"], errors="coerce")
            .fillna(0)
        )

    monthly = monthly[
        monthly[MONTH_COL].between(1, 12)
    ].copy()

    duplicate_mask = monthly.duplicated(subset=[ID_COL, MONTH_COL], keep=False)
    duplicates = monthly.loc[duplicate_mask].copy()

    if len(duplicates) > 0:
        print(
            "Advertencia: hay filas duplicadas por extract_id + month en exports GEE:",
            f"{len(duplicates):,}",
        )

        monthly = (
            monthly.sort_values([ID_COL, MONTH_COL, "source_csv"], na_position="last")
            .drop_duplicates(subset=[ID_COL, MONTH_COL], keep="first")
        )

    print(f"Filas mensuales únicas extract_id+month: {len(monthly):,}")

    return monthly, duplicates


def construir_tabla_wide(monthly: pd.DataFrame) -> pd.DataFrame:
    value_cols = [c for c in SPECTRAL_VALUE_COLS if c in monthly.columns]

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

        pivot.columns = [
            s2_monthly_col(int(month), value_col)
            for month in pivot.columns
            if pd.notna(month)
        ]

        wide_parts.append(pivot)

    wide = pd.concat(wide_parts, axis=1).reset_index()

    group = monthly.groupby(ID_COL, dropna=False)

    annual = group.size().reset_index(name="s2_n_month_rows")

    if "n_obs_clean" in monthly.columns:
        obs_summary = (
            group["n_obs_clean"]
            .agg(
                s2yr_obs_total="sum",
                s2yr_months_obs=lambda s: int(
                    (pd.to_numeric(s, errors="coerce").fillna(0) > 0).sum()
                ),
                s2yr_obs_mean="mean",
            )
            .reset_index()
        )
        annual = annual.merge(obs_summary, on=ID_COL, how="left")

    if "cloud_prob_median" in monthly.columns:
        cloud = (
            group["cloud_prob_median"]
            .agg(s2yr_cloudprob_median="median")
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

    n_s2_cols = len(
        [
            c for c in wide.columns
            if c.startswith("s2_") or c.startswith("s2yr_")
        ]
    )

    print(f"Tabla wide extract_id: {len(wide):,}")
    print(f"Columnas agregadas s2_/s2yr_: {n_s2_cols:,}")

    return wide


# -----------------------------------------------------------------------------
# Join and derived layers
# -----------------------------------------------------------------------------

def check_no_original_column_collision(
    original: gpd.GeoDataFrame,
    wide: pd.DataFrame,
) -> None:
    """
    Ensure the spectral wide table does not overwrite original columns.
    """
    original_cols = set(original.columns)
    wide_cols = set(wide.columns) - {ID_COL}

    overlap = sorted(original_cols.intersection(wide_cols))

    if overlap:
        raise ValueError(
            "Hay columnas de la tabla espectral que ya existen en el GPKG original. "
            "Para no alterar columnas originales, revise estos nombres: "
            f"{overlap[:50]}"
        )


def unir_original_con_espectral(
    original: gpd.GeoDataFrame,
    wide: pd.DataFrame,
    allow_missing: bool = False,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    print("\nUniendo registros originales con valores espectrales...")

    check_no_original_column_collision(original, wide)

    original_ids = set(original[ID_COL].dropna().astype(str))
    gee_ids = set(wide[ID_COL].dropna().astype(str))

    missing_ids = sorted(original_ids - gee_ids)
    extra_ids = sorted(gee_ids - original_ids)

    missing_df = pd.DataFrame({ID_COL: missing_ids})
    extra_df = pd.DataFrame({ID_COL: extra_ids})

    if missing_ids:
        print("Extract ID del original sin valores GEE:", len(missing_ids))

        if not allow_missing:
            raise ValueError(
                "Hay extract_id del GPKG original que no aparecen en los CSV GEE. "
                f"Faltantes: {len(missing_ids):,}. "
                "Ejecute con --allow-missing si desea continuar."
            )

    original_rows = len(original)

    original[ID_COL] = original[ID_COL].astype("string")
    wide[ID_COL] = wide[ID_COL].astype("string")

    out = original.merge(wide, on=ID_COL, how="left")

    output_rows = len(out)

    if original_rows != output_rows:
        raise ValueError(
            "El número de filas cambió después del merge. "
            f"Original={original_rows:,}, Output={output_rows:,}"
        )

    validation = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reference_gpkg": str(REFERENCE_GPKG),
        "reference_layer": REFERENCE_LAYER,
        "gee_export_dir": str(GEE_EXPORT_DIR),
        "output_gpkg": str(OUTPUT_GPKG),
        "original_rows": int(original_rows),
        "output_rows": int(output_rows),
        "row_count_matches": format_bool(original_rows == output_rows),
        "original_unique_extract_id": int(len(original_ids)),
        "gee_unique_extract_id": int(len(gee_ids)),
        "n_missing_extract_id_in_gee": int(len(missing_ids)),
        "n_extra_extract_id_in_gee": int(len(extra_ids)),
        "all_original_extract_id_have_spectral": format_bool(len(missing_ids) == 0),
        "allow_missing": format_bool(allow_missing),
    }

    print(f"Filas salida original_records_s2sr_full: {len(out):,}")

    return out, missing_df, extra_df, validation


def original_core_columns() -> list[str]:
    """
    Columns considered useful for practical review and annual summaries.

    Excludes temporal range fields such as anio_min, anio_max and n_anios.
    Keeps the year of the actual record, if available.
    """
    return [
        "original_record_row_id",
        ID_COL,
        "xy_group_id",
        "Id",
        "id",
        "Longitud",
        "Latitud",
        "lon",
        "lat",
        "Pais_es",
        "country",
        "Fuente",
        "source",
        "Año",
        "year_ref",
        "Nivel_0",
        "Nivel_1",
        "Nivel_2",
        "level_1",
        "level_2",
        "Tipo",
        "Admin1name",
        "tipo_grupo_xy",
        "n_records_extract_unit",
        "n_registros",
        "n_paises",
        "n_fuentes",
        "n_nivel1",
        "n_nivel2",
    ]


def reduced_monthly_index_columns(df: pd.DataFrame) -> list[str]:
    cols = []
    for month in range(1, 13):
        for index_name in ["NDVI", "NDVI8A", "NDRE"]:
            col = s2_monthly_col(month, index_name)
            if col in df.columns:
                cols.append(col)
    return cols


def annual_s2_columns(df: pd.DataFrame) -> list[str]:
    wanted = [
        "s2_n_month_rows",
        "s2_year_ref",
        "s2_year_extraction",
        "s2yr_months_obs",
        "s2yr_obs_total",
        "s2yr_obs_mean",
        "s2yr_cloudprob_median",
        "s2yr_ndvi_mean",
        "s2yr_ndvi_median",
        "s2yr_ndvi8a_mean",
        "s2yr_ndvi8a_median",
        "s2yr_ndre_mean",
        "s2yr_ndre_median",
    ]
    return [c for c in wanted if c in df.columns]


def construir_capa_reduced(full: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Practical monthly review layer:
    - original key fields
    - monthly indices only
    - no monthly obs
    - no monthly cloud probability
    - no min/max year range fields
    """
    cols = original_core_columns()
    cols += reduced_monthly_index_columns(full)

    reduced = select_gdf_columns(full, cols)

    print(f"Capa {LAYER_REDUCED}: {len(reduced):,}")
    print(f"Columnas reduced: {len(reduced.columns):,}")

    return reduced


def construir_capa_annual(full: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Annual summary layer at original-record level:
    - original key fields
    - annual obs metrics
    - cloud probability median
    - mean/median of indices
    - no min/max/amplitude
    """
    cols = original_core_columns()
    cols += annual_s2_columns(full)

    annual = select_gdf_columns(full, cols)

    print(f"Capa {LAYER_ANNUAL}: {len(annual):,}")
    print(f"Columnas annual: {len(annual.columns):,}")

    return annual


def construir_extract_units_annual(
    original: gpd.GeoDataFrame,
    wide: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """
    Build a non-duplicated annual layer with one row per extract_id.

    This represents the unit actually extracted in GEE.
    """
    print("\nConstruyendo capa anual sin duplicados por extract_id...")

    geom_col = original.geometry.name

    keep_cols = original_core_columns() + [geom_col]
    keep_cols = [c for c in keep_cols if c in original.columns]

    base_units = (
        original[keep_cols]
        .drop_duplicates(subset=[ID_COL], keep="first")
        .copy()
    )

    annual_cols = [ID_COL] + annual_s2_columns(wide)
    annual_cols = [c for c in annual_cols if c in wide.columns]

    annual_wide = wide[annual_cols].copy()

    base_units[ID_COL] = base_units[ID_COL].astype("string")
    annual_wide[ID_COL] = annual_wide[ID_COL].astype("string")

    units = base_units.merge(annual_wide, on=ID_COL, how="left")

    units_gdf = gpd.GeoDataFrame(
        units,
        geometry=geom_col,
        crs=original.crs,
    )

    print(f"Capa {LAYER_UNITS_ANNUAL}: {len(units_gdf):,}")
    print(f"Columnas extract_units annual: {len(units_gdf.columns):,}")

    return units_gdf


# -----------------------------------------------------------------------------
# Reports and outputs
# -----------------------------------------------------------------------------

def guardar_tablas_outputs(
    validation: dict[str, Any],
    input_inventory: pd.DataFrame,
    missing_df: pd.DataFrame,
    extra_df: pd.DataFrame,
    duplicates_df: pd.DataFrame,
) -> None:
    """
    Save official pipeline control tables in:
      outputs/tables/s2_sr_original_records_with_spectral/
    """
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    validation_df = pd.DataFrame([validation])

    validation_df.to_csv(
        VALIDATION_SUMMARY_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    input_inventory.to_csv(
        INPUT_FILES_INVENTORY_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    # Always write these tables, even if empty, so each run has predictable outputs.
    missing_df.to_csv(
        MISSING_EXTRACT_ID_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    extra_df.to_csv(
        EXTRA_EXTRACT_ID_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    duplicates_df.to_csv(
        DUPLICATE_GEE_ROWS_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    print("\nTablas de control guardadas en:")
    print(" -", VALIDATION_SUMMARY_CSV)
    print(" -", INPUT_FILES_INVENTORY_CSV)
    print(" -", MISSING_EXTRACT_ID_CSV)
    print(" -", EXTRA_EXTRACT_ID_CSV)
    print(" -", DUPLICATE_GEE_ROWS_CSV)


def generar_reporte_markdown(
    validation: dict[str, Any],
    full: gpd.GeoDataFrame,
    reduced: gpd.GeoDataFrame,
    annual: gpd.GeoDataFrame,
    units_annual: gpd.GeoDataFrame,
    input_inventory: pd.DataFrame,
    missing_df: pd.DataFrame,
    extra_df: pd.DataFrame,
    duplicates_df: pd.DataFrame,
) -> None:
    """
    Genera reporte Markdown sintético del Módulo 08.

    El reporte documenta las entradas, salidas, conteos principales y
    consideraciones metodológicas del cruce entre registros originales y
    valores espectrales Sentinel-2 SR exportados desde GEE.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

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
                "descripcion": "Versión completa con columnas originales, variables mensuales y resúmenes anuales.",
            },
            {
                "capa_tabla": LAYER_REDUCED,
                "tipo": "capa espacial",
                "unidad": "registro original",
                "filas": len(reduced),
                "descripcion": "Versión práctica con columnas clave e índices mensuales.",
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
                "descripcion": "Resumen anual sin duplicados, equivalente a las unidades extraídas en GEE.",
            },
            {
                "capa_tabla": TABLE_VALIDATION,
                "tipo": "tabla",
                "unidad": "control",
                "filas": 1,
                "descripcion": "Resumen de validación de conteos.",
            },
            {
                "capa_tabla": TABLE_INPUT_FILES,
                "tipo": "tabla",
                "unidad": "archivo CSV",
                "filas": len(input_inventory),
                "descripcion": "Inventario de archivos CSV encontrados y procesados.",
            },
            {
                "capa_tabla": TABLE_MISSING,
                "tipo": "tabla",
                "unidad": "extract_id",
                "filas": len(missing_df),
                "descripcion": "Extract ID presentes en el GPKG original pero ausentes en GEE.",
            },
            {
                "capa_tabla": TABLE_EXTRA,
                "tipo": "tabla",
                "unidad": "extract_id",
                "filas": len(extra_df),
                "descripcion": "Extract ID presentes en GEE pero ausentes en el GPKG original.",
            },
            {
                "capa_tabla": TABLE_DUPLICATES,
                "tipo": "tabla",
                "unidad": "extract_id + mes",
                "filas": len(duplicates_df),
                "descripcion": "Duplicados detectados en los CSV de GEE.",
            },
        ]
    )

    columnas_df = pd.DataFrame(
        [
            {
                "grupo": "Columnas mensuales completas",
                "patron": "s2_MM_variable",
                "ejemplos": "s2_01_b02, s2_01_ndvi, s2_12_cloudprob",
                "incluido_en": LAYER_FULL,
            },
            {
                "grupo": "Índices mensuales",
                "patron": "s2_MM_ndvi / s2_MM_ndvi8a / s2_MM_ndre",
                "ejemplos": "s2_01_ndvi, s2_06_ndre, s2_12_ndvi8a",
                "incluido_en": f"{LAYER_FULL}, {LAYER_REDUCED}",
            },
            {
                "grupo": "Resumen anual de observaciones",
                "patron": "s2yr_obs_*",
                "ejemplos": "s2yr_obs_total, s2yr_obs_mean, s2yr_months_obs",
                "incluido_en": f"{LAYER_FULL}, {LAYER_ANNUAL}, {LAYER_UNITS_ANNUAL}",
            },
            {
                "grupo": "Resumen anual de índices",
                "patron": "s2yr_indice_metrica",
                "ejemplos": "s2yr_ndvi_mean, s2yr_ndvi_median, s2yr_ndre_mean",
                "incluido_en": f"{LAYER_FULL}, {LAYER_ANNUAL}, {LAYER_UNITS_ANNUAL}",
            },
        ]
    )

    contenido = "\n".join(
        [
            "# Unión de registros originales con valores espectrales Sentinel-2 SR",
            "",
            "## Módulo 08",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## Propósito",
            "",
            "Este módulo une los registros originales elegibles con los valores espectrales mensuales de Sentinel-2 SR exportados desde Google Earth Engine.",
            "",
            "La unión se realiza mediante el campo `extract_id`, que representa la unidad única de extracción espectral.",
            "",
            "## Entradas principales",
            "",
            "| Insumo | Ruta / valor |",
            "|---|---|",
            f"| GPKG de registros originales | `{fmt_path(REFERENCE_GPKG)}` |",
            f"| Capa de registros originales | `{REFERENCE_LAYER}` |",
            f"| Carpeta de CSV GEE | `{fmt_path(GEE_EXPORT_DIR)}` |",
            f"| Prefijo de CSV procesados | `{GEE_EXPORT_PREFIX}` |",
            "",
            "## Salidas principales",
            "",
            "| Producto | Ruta |",
            "|---|---|",
            f"| GeoPackage final | `{fmt_path(OUTPUT_GPKG)}` |",
            f"| Tablas de control | `{fmt_path(TABLES_DIR)}` |",
            f"| Reporte Markdown | `{fmt_path(REPORT_MD)}` |",
            "",
            "## Capas y tablas generadas",
            "",
            dataframe_a_markdown(capas_df),
            "",
            "## Resumen de validación",
            "",
            dataframe_a_markdown(resumen_df),
            "",
            "## Grupos de columnas Sentinel-2",
            "",
            dataframe_a_markdown(columnas_df),
            "",
            "## Interpretación de las capas",
            "",
            f"- `{LAYER_FULL}` conserva toda la trazabilidad: columnas originales, variables mensuales, bandas, índices, observaciones y resúmenes anuales.",
            f"- `{LAYER_REDUCED}` es una versión práctica para QGIS: mantiene columnas clave e índices mensuales, pero excluye bandas, observaciones mensuales y probabilidad mensual de nube.",
            f"- `{LAYER_ANNUAL}` resume cada registro original con métricas anuales de observaciones, nube e índices.",
            f"- `{LAYER_UNITS_ANNUAL}` elimina duplicados por `extract_id` y representa directamente las unidades espectrales extraídas en GEE.",
            "",
            "## Nota metodológica",
            "",
            "Los CSV de GEE están en formato largo, con una fila por `extract_id` y mes. Este módulo transforma esa información a formato ancho.",
            "",
            "Los valores `-9999` exportados desde GEE se interpretan como ausencia de dato válido y se convierten a valores nulos para el cálculo de métricas anuales.",
            "",
            "La capa de registros originales conserva duplicados porque corresponden a registros reales del flujo de datos. La capa sin duplicados se incluye para análisis espectral sin sobreponderar unidades repetidas.",
            "",
            "Este módulo no modifica los datos originales de entrada. Todas las salidas se generan como productos derivados.",
            "",
        ]
    )

    REPORT_MD.write_text(contenido, encoding="utf-8")

    print("\nReporte Markdown guardado en:")
    print(" -", REPORT_MD)


def guardar_salidas_gpkg(
    full: gpd.GeoDataFrame,
    reduced: gpd.GeoDataFrame,
    annual: gpd.GeoDataFrame,
    units_annual: gpd.GeoDataFrame,
    validation: dict[str, Any],
    input_inventory: pd.DataFrame,
    missing_df: pd.DataFrame,
    extra_df: pd.DataFrame,
    duplicates_df: pd.DataFrame,
) -> None:
    print("\nGuardando salidas en GPKG único...")

    if OUTPUT_GPKG.exists():
        OUTPUT_GPKG.unlink()

    print("Escribiendo capa completa:", LAYER_FULL)
    clean_for_gpkg(full).to_file(
        OUTPUT_GPKG,
        layer=LAYER_FULL,
        driver="GPKG",
    )

    print("Escribiendo capa reducida:", LAYER_REDUCED)
    clean_for_gpkg(reduced).to_file(
        OUTPUT_GPKG,
        layer=LAYER_REDUCED,
        driver="GPKG",
    )

    print("Escribiendo capa anual:", LAYER_ANNUAL)
    clean_for_gpkg(annual).to_file(
        OUTPUT_GPKG,
        layer=LAYER_ANNUAL,
        driver="GPKG",
    )

    print("Escribiendo capa anual sin duplicados:", LAYER_UNITS_ANNUAL)
    clean_for_gpkg(units_annual).to_file(
        OUTPUT_GPKG,
        layer=LAYER_UNITS_ANNUAL,
        driver="GPKG",
    )

    validation_df = pd.DataFrame([validation])

    write_table_to_gpkg(validation_df, OUTPUT_GPKG, TABLE_VALIDATION)
    write_table_to_gpkg(input_inventory, OUTPUT_GPKG, TABLE_INPUT_FILES)
    write_table_to_gpkg(missing_df, OUTPUT_GPKG, TABLE_MISSING)
    write_table_to_gpkg(extra_df, OUTPUT_GPKG, TABLE_EXTRA)
    write_table_to_gpkg(duplicates_df, OUTPUT_GPKG, TABLE_DUPLICATES)

    print("GPKG final:", OUTPUT_GPKG)

    guardar_tablas_outputs(
        validation=validation,
        input_inventory=input_inventory,
        missing_df=missing_df,
        extra_df=extra_df,
        duplicates_df=duplicates_df,
    )

    generar_reporte_markdown(
        validation=validation,
        full=full,
        reduced=reduced,
        annual=annual,
        units_annual=units_annual,
        input_inventory=input_inventory,
        missing_df=missing_df,
        extra_df=extra_df,
        duplicates_df=duplicates_df,
    )


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Une registros originales con valores espectrales mensuales/anuales de GEE "
            "y guarda salidas relevantes en GPKG + outputs/tables + outputs/reports."
        )
    )

    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Permite continuar aunque algunos extract_id originales no aparezcan en GEE.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    crear_carpetas()
    remove_previous_optional_csvs()

    print("============================================================")
    print("PGBM - Registros originales + valores espectrales Sentinel-2 SR")
    print("============================================================")
    print("Project root:", PROJECT_ROOT)
    print("GPKG original:", REFERENCE_GPKG)
    print("Layer original:", REFERENCE_LAYER)
    print("CSV GEE dir:", GEE_EXPORT_DIR)
    print("Output GPKG:", OUTPUT_GPKG)
    print("Tables dir:", TABLES_DIR)
    print("Reports dir:", REPORTS_DIR)
    print("============================================================")

    original = cargar_original_gpkg()
    print(f"\nFilas originales: {len(original):,}")
    print(f"Extract ID únicos originales: {original[ID_COL].nunique(dropna=True):,}")

    csv_files, input_inventory = listar_exports_gee()

    monthly = leer_exports_mensuales(csv_files)
    monthly, duplicates_df = normalizar_monthly(monthly)

    wide = construir_tabla_wide(monthly)

    full, missing_df, extra_df, validation = unir_original_con_espectral(
        original=original,
        wide=wide,
        allow_missing=args.allow_missing,
    )

    reduced = construir_capa_reduced(full)
    annual = construir_capa_annual(full)
    units_annual = construir_extract_units_annual(
        original=original,
        wide=wide,
    )

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
    validation["tables_dir"] = str(TABLES_DIR)
    validation["reports_dir"] = str(REPORTS_DIR)
    validation["report_markdown"] = str(REPORT_MD)

    guardar_salidas_gpkg(
        full=full,
        reduced=reduced,
        annual=annual,
        units_annual=units_annual,
        validation=validation,
        input_inventory=input_inventory,
        missing_df=missing_df,
        extra_df=extra_df,
        duplicates_df=duplicates_df,
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
    print("Salida GPKG:", OUTPUT_GPKG)
    print("Tablas:", TABLES_DIR)
    print("Reporte:", REPORT_MD)
    print("============================================================")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise