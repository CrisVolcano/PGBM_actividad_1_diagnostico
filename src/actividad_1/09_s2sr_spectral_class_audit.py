from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
import traceback
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd


# =============================================================================
# PGBM - Módulo 09
# Auditoría espectral por clase a partir de Sentinel-2 SR
# =============================================================================
#
# Propósito:
#   Evaluar de forma preliminar qué tan coherente parece cada registro/punto
#   desde el punto de vista espectral, según su clase temática y su señal
#   Sentinel-2 SR anual.
#
# Entrada principal:
#   data/processed/s2_sr_original_records_with_spectral/
#   └─ puntos_s2_sr_2018_2022_s2sr_join_outputs.gpkg
#
# Capas de entrada:
#   - original_records_s2sr_annual
#   - extract_units_s2sr_annual
#
# Salidas:
#   data/processed/s2_sr_spectral_class_audit/
#   └─ s2sr_spectral_class_audit_outputs.gpkg
#
#   outputs/tables/s2_sr_spectral_class_audit/
#   outputs/reports/s2_sr_spectral_class_audit/
#
# Nota:
#   Esta auditoría genera alertas exploratorias.
#   No constituye validación temática definitiva.
# =============================================================================


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

INPUT_GPKG_REL = Path(
    "data/processed/s2_sr_original_records_with_spectral/"
    "puntos_s2_sr_2018_2022_s2sr_join_outputs.gpkg"
)

INPUT_LAYER_ORIGINAL_ANNUAL = "original_records_s2sr_annual"
INPUT_LAYER_UNITS_ANNUAL = "extract_units_s2sr_annual"

OUTPUT_DIR_REL = Path("data/processed/s2_sr_spectral_class_audit")
TABLES_DIR_REL = Path("outputs/tables/s2_sr_spectral_class_audit")
REPORTS_DIR_REL = Path("outputs/reports/s2_sr_spectral_class_audit")

OUTPUT_GPKG_NAME = "s2sr_spectral_class_audit_outputs.gpkg"
REPORT_MD_NAME = "09_s2sr_spectral_class_audit_report.md"

LAYER_AUDIT_ORIGINAL = "audit_original_records_s2sr_annual"
LAYER_AUDIT_UNITS = "audit_extract_units_s2sr_annual"
LAYER_PRIORITY_ORIGINAL = "priority_original_records_s2sr"

TABLE_AUDIT_SUMMARY = "audit_summary"
TABLE_ALERT_DISTRIBUTION = "alert_distribution"
TABLE_CLASS_COUNTRY_YEAR = "class_country_year_spectral_audit"
TABLE_CLASS_COUNTRY = "class_country_spectral_audit"
TABLE_RARE_RECORDS = "rare_spectral_records"
TABLE_LOW_AVAILABILITY = "low_satellite_availability_records"

AUDIT_SUMMARY_CSV_NAME = "09_audit_summary.csv"
ALERT_DISTRIBUTION_CSV_NAME = "09_alert_distribution.csv"
CLASS_COUNTRY_YEAR_CSV_NAME = "09_class_country_year_spectral_audit.csv"
CLASS_COUNTRY_CSV_NAME = "09_class_country_spectral_audit.csv"
PRIORITY_RECORDS_CSV_NAME = "09_priority_original_records_s2sr.csv"
RARE_RECORDS_CSV_NAME = "09_rare_spectral_records.csv"
LOW_AVAILABILITY_CSV_NAME = "09_low_satellite_availability_records.csv"


# -----------------------------------------------------------------------------
# Parámetros de auditoría
# -----------------------------------------------------------------------------

MIN_VALID_MONTHS = 4
MIN_TOTAL_OBS = 4
CLOUD_PROB_HIGH = 60

NDVI_LOW_FOR_VEGETATION = 0.35
NDRE_LOW_FOR_VEGETATION = 0.08
NDVI_HIGH_FOR_NON_VEGETATION = 0.55

MIN_GROUP_SIZE_FOR_RARENESS = 20
IQR_FACTOR = 1.5

HIGH_GAP_PCT = 25.0
HIGH_RARE_PCT = 15.0
HIGH_ALERT_PCT = 25.0


# =============================================================================
# REFERENCIA HOMOLOGADA DE CLASES
# =============================================================================

CLASS_REFERENCE_LEVEL1 = {
    11: {"level_0_code": 10, "level_0_name": "Artificializado y otra tierras", "level_1_name_ref": "Urbano"},
    12: {"level_0_code": 10, "level_0_name": "Artificializado y otra tierras", "level_1_name_ref": "Otras tierras"},
    21: {"level_0_code": 20, "level_0_name": "Tierras húmedas y agua", "level_1_name_ref": "Cuerpos de Agua"},
    22: {"level_0_code": 20, "level_0_name": "Tierras húmedas y agua", "level_1_name_ref": "Humedales"},
    31: {"level_0_code": 30, "level_0_name": "Tierras de Cultivo y Pastos", "level_1_name_ref": "Cultivos intensivos No-Arbóreos"},
    32: {"level_0_code": 30, "level_0_name": "Tierras de Cultivo y Pastos", "level_1_name_ref": "Cultivos Arbóreos"},
    33: {"level_0_code": 30, "level_0_name": "Tierras de Cultivo y Pastos", "level_1_name_ref": "Cultivos extensivos, Pastizales y matorrales"},
    41: {"level_0_code": 40, "level_0_name": "Tierras Forestales", "level_1_name_ref": "Bosque latifoliado y mixto"},
    42: {"level_0_code": 40, "level_0_name": "Tierras Forestales", "level_1_name_ref": "Bosque de coníferas"},
    43: {"level_0_code": 40, "level_0_name": "Tierras Forestales", "level_1_name_ref": "Manglares"},
    44: {"level_0_code": 40, "level_0_name": "Tierras Forestales", "level_1_name_ref": "Otros arbóreo en tierras no agrícola"},
    91: {"level_0_code": 90, "level_0_name": "Otras", "level_1_name_ref": "Otras"},
}

CLASS_REFERENCE_LEVEL2 = {
    110: "Urbano",
    111: "Urbano continuo",
    112: "Urbano discontinuo",
    121: "Otros artificializado",
    122: "Suelo desnudo, arena, rocoso, lava, otros",
    210: "Cuerpos de Agua",
    211: "Cuerpos de agua natural",
    212: "Cuerpos de agua artificial",
    220: "Humedales",
    311: "Palma aceitera",
    312: "Bananeras",
    313: "Caña de azúcar",
    314: "Piña",
    315: "Otros cultivos intensivos no arbóreos",
    321: "Café",
    322: "Cacao",
    323: "Frutales",
    324: "Hule",
    325: "Otros sistemas agroforestales o silvopastoriles",
    331: "Granos básicos y hortalizas y otros",
    332: "Pastizales naturales y cultivados",
    333: "Matorrales (barbecho o en descanso)",
    410: "Bosque latifoliado y mixto",
    411: "Latifoliado maduro húmedo",
    412: "Latifoliado secundario húmedo",
    413: "Bosque Mixto (Lat-Coniferas)",
    414: "Bosque seco o deciduo",
    420: "Bosque de coníferas",
    421: "Coníferas denso",
    422: "Coníferas ralo",
    423: "Sabanas de pino",
    430: "Manglares",
    431: "Manglar alto",
    432: "Manglar bajo",
    441: "Masa arbórea ribereña",
    442: "Plantaciones forestales",
    443: "Árboles fuera de bosque y otras áreas naturales",
    444: "Regeneración forestal",
    445: "Bosque de Palmas",
    910: "Otras",
}


# =============================================================================
# RUTAS
# =============================================================================

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

INPUT_GPKG = PROJECT_ROOT / INPUT_GPKG_REL

OUTPUT_DIR = PROJECT_ROOT / OUTPUT_DIR_REL
TABLES_DIR = PROJECT_ROOT / TABLES_DIR_REL
REPORTS_DIR = PROJECT_ROOT / REPORTS_DIR_REL

OUTPUT_GPKG = OUTPUT_DIR / OUTPUT_GPKG_NAME
REPORT_MD = REPORTS_DIR / REPORT_MD_NAME

AUDIT_SUMMARY_CSV = TABLES_DIR / AUDIT_SUMMARY_CSV_NAME
ALERT_DISTRIBUTION_CSV = TABLES_DIR / ALERT_DISTRIBUTION_CSV_NAME
CLASS_COUNTRY_YEAR_CSV = TABLES_DIR / CLASS_COUNTRY_YEAR_CSV_NAME
CLASS_COUNTRY_CSV = TABLES_DIR / CLASS_COUNTRY_CSV_NAME
PRIORITY_RECORDS_CSV = TABLES_DIR / PRIORITY_RECORDS_CSV_NAME
RARE_RECORDS_CSV = TABLES_DIR / RARE_RECORDS_CSV_NAME
LOW_AVAILABILITY_CSV = TABLES_DIR / LOW_AVAILABILITY_CSV_NAME


# =============================================================================
# UTILIDADES
# =============================================================================

def crear_carpetas() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    return df


def available_cols(df: pd.DataFrame, cols: list[str]) -> list[str]:
    return [c for c in cols if c in df.columns]


def dataframe_a_markdown(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


def fmt_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def pct(n: float | int, d: float | int) -> float:
    n = 0 if pd.isna(n) else float(n)
    d = 0 if pd.isna(d) else float(d)
    return 0.0 if d == 0 else round(n / d * 100, 3)


def extract_first_code(value: Any) -> float:
    if pd.isna(value):
        return np.nan

    text = str(value).strip()
    digits = ""

    for char in text:
        if char.isdigit():
            digits += char
        else:
            break

    if digits:
        return float(digits)

    return np.nan


def to_int_flag(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool).astype("int8")


def clean_for_gpkg(df: pd.DataFrame | gpd.GeoDataFrame) -> pd.DataFrame | gpd.GeoDataFrame:
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


def drop_geometry_for_csv(gdf: gpd.GeoDataFrame | pd.DataFrame) -> pd.DataFrame:
    if isinstance(gdf, gpd.GeoDataFrame):
        return pd.DataFrame(gdf.drop(columns=[gdf.geometry.name], errors="ignore"))
    return pd.DataFrame(gdf)


# =============================================================================
# NORMALIZACIÓN DE CAMPOS
# =============================================================================

def ensure_standard_fields(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df)

    # Campos de país/fuente/año con nombres estandarizados para la auditoría.
    if "audit_country" not in df.columns:
        if "Pais_es" in df.columns:
            df["audit_country"] = df["Pais_es"]
        elif "country" in df.columns:
            df["audit_country"] = df["country"]
        else:
            df["audit_country"] = pd.NA

    if "audit_source" not in df.columns:
        if "Fuente" in df.columns:
            df["audit_source"] = df["Fuente"]
        elif "source" in df.columns:
            df["audit_source"] = df["source"]
        else:
            df["audit_source"] = pd.NA

    if "audit_year" not in df.columns:
        if "Año" in df.columns:
            df["audit_year"] = df["Año"]
        elif "year_ref" in df.columns:
            df["audit_year"] = df["year_ref"]
        elif "s2_year_ref" in df.columns:
            df["audit_year"] = df["s2_year_ref"]
        elif "s2_year_extraction" in df.columns:
            df["audit_year"] = df["s2_year_extraction"]
        else:
            df["audit_year"] = pd.NA

    # Códigos de clase.
    if "level_1_code" not in df.columns:
        if "Nivel_1" in df.columns:
            df["level_1_code"] = df["Nivel_1"].apply(extract_first_code)
        elif "level_1" in df.columns:
            df["level_1_code"] = df["level_1"].apply(extract_first_code)
        else:
            df["level_1_code"] = np.nan

    if "level_2_code" not in df.columns:
        if "Nivel_2" in df.columns:
            df["level_2_code"] = df["Nivel_2"].apply(extract_first_code)
        elif "level_2" in df.columns:
            df["level_2_code"] = df["level_2"].apply(extract_first_code)
        else:
            df["level_2_code"] = np.nan

    df["level_1_code"] = pd.to_numeric(df["level_1_code"], errors="coerce")
    df["level_2_code"] = pd.to_numeric(df["level_2_code"], errors="coerce")

    df["level_0_code"] = df["level_1_code"].map(
        lambda x: CLASS_REFERENCE_LEVEL1.get(int(x), {}).get("level_0_code", np.nan)
        if pd.notna(x) else np.nan
    )

    df["level_0_name"] = df["level_1_code"].map(
        lambda x: CLASS_REFERENCE_LEVEL1.get(int(x), {}).get("level_0_name", "")
        if pd.notna(x) else ""
    )

    df["level_1_name_ref"] = df["level_1_code"].map(
        lambda x: CLASS_REFERENCE_LEVEL1.get(int(x), {}).get("level_1_name_ref", "")
        if pd.notna(x) else ""
    )

    df["level_2_name_ref"] = df["level_2_code"].map(
        lambda x: CLASS_REFERENCE_LEVEL2.get(int(x), "")
        if pd.notna(x) else ""
    )

    # Variables espectrales principales.
    numeric_cols = [
        "audit_year",
        "level_0_code",
        "level_1_code",
        "level_2_code",
        "s2_n_month_rows",
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
        "n_nivel1",
        "n_nivel2",
        "n_records_extract_unit",
        "n_registros",
        "n_paises",
        "n_fuentes",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["audit_country", "audit_source", "extract_id", "xy_group_id"]:
        if col in df.columns:
            df[col] = df[col].astype("string")

    return df


def expected_signal_group_from_level0(level_0_code: Any) -> str:
    if pd.isna(level_0_code):
        return "sin_regla"

    code = int(level_0_code)

    if code == 10:
        return "no_vegetacion_esperada"

    if code == 20:
        return "agua_humedal"

    if code in [30, 40]:
        return "vegetacion_esperada"

    return "sin_regla"


# =============================================================================
# CARGA DE DATOS
# =============================================================================

def cargar_capa(gpkg_path: Path, layer: str) -> gpd.GeoDataFrame:
    if not gpkg_path.exists():
        raise FileNotFoundError(f"No existe el GeoPackage de entrada: {gpkg_path}")

    gdf = gpd.read_file(gpkg_path, layer=layer)
    gdf = clean_columns(gdf)

    if "extract_id" not in gdf.columns:
        raise ValueError(f"La capa {layer} no contiene extract_id.")

    return gdf


# =============================================================================
# AUDITORÍA PUNTO / REGISTRO
# =============================================================================

def add_rare_flags_by_class_country_year(audit: pd.DataFrame) -> pd.DataFrame:
    audit = audit.copy()

    audit["flag_ndvi_rare_by_class_country_year"] = False
    audit["flag_ndre_rare_by_class_country_year"] = False

    group_cols = available_cols(
        audit,
        ["audit_country", "audit_year", "level_2_code"],
    )

    if len(group_cols) < 3:
        group_cols = available_cols(
            audit,
            ["audit_country", "audit_year", "level_1_code"],
        )

    if len(group_cols) < 3:
        return audit

    for _, group in audit.groupby(group_cols, dropna=False):
        if len(group) < MIN_GROUP_SIZE_FOR_RARENESS:
            continue

        for metric, flag_col in [
            ("s2yr_ndvi_median", "flag_ndvi_rare_by_class_country_year"),
            ("s2yr_ndre_median", "flag_ndre_rare_by_class_country_year"),
        ]:
            if metric not in audit.columns:
                continue

            vals = pd.to_numeric(group[metric], errors="coerce").dropna()

            if len(vals) < MIN_GROUP_SIZE_FOR_RARENESS:
                continue

            q1 = vals.quantile(0.25)
            q3 = vals.quantile(0.75)
            iqr = q3 - q1

            if pd.isna(iqr) or iqr == 0:
                continue

            low = q1 - IQR_FACTOR * iqr
            high = q3 + IQR_FACTOR * iqr

            idx = group.index[
                audit.loc[group.index, metric].notna()
                & (
                    (audit.loc[group.index, metric] < low)
                    | (audit.loc[group.index, metric] > high)
                )
            ]

            audit.loc[idx, flag_col] = True

    return audit


def build_spectral_audit(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    audit = ensure_standard_fields(gdf)

    # Asegurar columnas mínimas.
    for col in [
        "s2yr_months_obs",
        "s2yr_obs_total",
        "s2yr_obs_mean",
        "s2yr_cloudprob_median",
        "s2yr_ndvi_median",
        "s2yr_ndre_median",
    ]:
        if col not in audit.columns:
            audit[col] = np.nan

    audit["expected_signal_group"] = audit["level_0_code"].map(
        expected_signal_group_from_level0
    )

    months_obs = pd.to_numeric(audit["s2yr_months_obs"], errors="coerce").fillna(0)
    total_obs = pd.to_numeric(audit["s2yr_obs_total"], errors="coerce").fillna(0)
    cloud = pd.to_numeric(audit["s2yr_cloudprob_median"], errors="coerce")
    ndvi = pd.to_numeric(audit["s2yr_ndvi_median"], errors="coerce")
    ndre = pd.to_numeric(audit["s2yr_ndre_median"], errors="coerce")

    audit["flag_no_spectral_data"] = (
        (months_obs <= 0)
        | ((ndvi.isna()) & (ndre.isna()))
    )

    audit["flag_low_months_obs"] = (
        (months_obs > 0)
        & (months_obs < MIN_VALID_MONTHS)
    )

    audit["flag_low_total_obs"] = total_obs < MIN_TOTAL_OBS

    audit["flag_high_cloudprob"] = (
        cloud.notna()
        & (cloud >= CLOUD_PROB_HIGH)
    )

    audit["flag_vegetation_low_ndvi"] = (
        (audit["expected_signal_group"] == "vegetacion_esperada")
        & ndvi.notna()
        & (ndvi < NDVI_LOW_FOR_VEGETATION)
    )

    audit["flag_vegetation_low_ndre"] = (
        (audit["expected_signal_group"] == "vegetacion_esperada")
        & ndre.notna()
        & (ndre < NDRE_LOW_FOR_VEGETATION)
    )

    audit["flag_nonvegetation_high_ndvi"] = (
        (audit["expected_signal_group"] == "no_vegetacion_esperada")
        & ndvi.notna()
        & (ndvi > NDVI_HIGH_FOR_NON_VEGETATION)
    )

    if "tipo_grupo_xy" in audit.columns:
        audit["flag_prior_xy_conflict"] = (
            audit["tipo_grupo_xy"]
            .astype(str)
            .str.lower()
            .str.contains("conflicto", na=False)
        )
    else:
        audit["flag_prior_xy_conflict"] = False

    if "n_nivel1" in audit.columns:
        audit["flag_multiple_level1_xy"] = (
            pd.to_numeric(audit["n_nivel1"], errors="coerce").fillna(0) > 1
        )
    else:
        audit["flag_multiple_level1_xy"] = False

    if "n_nivel2" in audit.columns:
        audit["flag_multiple_level2_xy"] = (
            pd.to_numeric(audit["n_nivel2"], errors="coerce").fillna(0) > 1
        )
    else:
        audit["flag_multiple_level2_xy"] = False

    audit = add_rare_flags_by_class_country_year(audit)

    audit["flag_rare_spectral_value"] = (
        audit["flag_ndvi_rare_by_class_country_year"]
        | audit["flag_ndre_rare_by_class_country_year"]
    )

    flag_cols = [
        "flag_no_spectral_data",
        "flag_low_months_obs",
        "flag_low_total_obs",
        "flag_high_cloudprob",
        "flag_vegetation_low_ndvi",
        "flag_vegetation_low_ndre",
        "flag_nonvegetation_high_ndvi",
        "flag_ndvi_rare_by_class_country_year",
        "flag_ndre_rare_by_class_country_year",
        "flag_rare_spectral_value",
        "flag_prior_xy_conflict",
        "flag_multiple_level1_xy",
        "flag_multiple_level2_xy",
    ]

    for col in flag_cols:
        audit[col] = to_int_flag(audit[col])

    audit["spectral_alert_count"] = audit[flag_cols].sum(axis=1).astype("int16")

    audit["spectral_alert_level"] = np.select(
        [
            audit["flag_no_spectral_data"] == 1,
            audit["spectral_alert_count"] >= 4,
            audit["spectral_alert_count"].between(2, 3),
            audit["spectral_alert_count"] == 1,
        ],
        [
            "alta_sin_datos",
            "alta",
            "media",
            "baja",
        ],
        default="sin_alerta",
    )

    audit["recommended_action"] = np.select(
        [
            audit["flag_no_spectral_data"] == 1,
            audit["spectral_alert_level"].isin(["alta", "media"]),
            audit["spectral_alert_level"].eq("baja"),
        ],
        [
            "Revisar disponibilidad satelital o excluir de análisis espectral",
            "Priorizar revisión temática/metodológica posterior",
            "Revisar si pertenece a clase o fuente prioritaria",
        ],
        default="Sin alerta preliminar",
    )

    audit["flag_spectral_class_review"] = (
        audit["spectral_alert_count"] > 0
    ).astype("int8")

    audit["audit_scope"] = "Módulo 09 - auditoría espectral preliminar por clase"
    audit["audit_interpretation"] = (
        "Alerta exploratoria; no constituye validación temática definitiva"
    )

    return audit


# =============================================================================
# RESÚMENES AGREGADOS
# =============================================================================

def make_class_country_year_audit(audit: pd.DataFrame) -> pd.DataFrame:
    group_cols = available_cols(
        audit,
        [
            "audit_country",
            "audit_year",
            "level_0_code",
            "level_0_name",
            "level_1_code",
            "level_1_name_ref",
            "level_2_code",
            "level_2_name_ref",
        ],
    )

    agg_dict = {
        "n_records": ("extract_id", "size"),
        "n_extract_id": ("extract_id", "nunique"),
        "n_sources": ("audit_source", "nunique"),
        "s2yr_months_obs_median": ("s2yr_months_obs", "median"),
        "s2yr_obs_total_median": ("s2yr_obs_total", "median"),
        "s2yr_cloudprob_median": ("s2yr_cloudprob_median", "median"),
        "s2yr_ndvi_median": ("s2yr_ndvi_median", "median"),
        "s2yr_ndre_median": ("s2yr_ndre_median", "median"),
        "n_no_spectral_data": ("flag_no_spectral_data", "sum"),
        "n_low_months_obs": ("flag_low_months_obs", "sum"),
        "n_high_cloudprob": ("flag_high_cloudprob", "sum"),
        "n_vegetation_low_ndvi": ("flag_vegetation_low_ndvi", "sum"),
        "n_vegetation_low_ndre": ("flag_vegetation_low_ndre", "sum"),
        "n_nonvegetation_high_ndvi": ("flag_nonvegetation_high_ndvi", "sum"),
        "n_rare_spectral_value": ("flag_rare_spectral_value", "sum"),
        "n_prior_xy_conflict": ("flag_prior_xy_conflict", "sum"),
        "n_spectral_class_review": ("flag_spectral_class_review", "sum"),
        "n_alert_high": (
            "spectral_alert_level",
            lambda s: int(s.isin(["alta", "alta_sin_datos"]).sum()),
        ),
        "n_alert_medium": (
            "spectral_alert_level",
            lambda s: int((s == "media").sum()),
        ),
        "n_alert_low": (
            "spectral_alert_level",
            lambda s: int((s == "baja").sum()),
        ),
    }

    out = (
        audit
        .groupby(group_cols, dropna=False)
        .agg(**agg_dict)
        .reset_index()
    )

    out["pct_no_spectral_data"] = (
        out["n_no_spectral_data"] / out["n_records"] * 100
    ).round(3)

    out["pct_low_months_obs"] = (
        out["n_low_months_obs"] / out["n_records"] * 100
    ).round(3)

    out["pct_rare_spectral_value"] = (
        out["n_rare_spectral_value"] / out["n_records"] * 100
    ).round(3)

    out["pct_spectral_class_review"] = (
        out["n_spectral_class_review"] / out["n_records"] * 100
    ).round(3)

    out["pct_alert_medium_high"] = (
        (out["n_alert_high"] + out["n_alert_medium"]) / out["n_records"] * 100
    ).round(3)

    out["class_priority_level"] = np.select(
        [
            out["pct_no_spectral_data"] >= HIGH_GAP_PCT,
            out["pct_rare_spectral_value"] >= HIGH_RARE_PCT,
            out["pct_alert_medium_high"] >= HIGH_ALERT_PCT,
            out["pct_spectral_class_review"] >= HIGH_ALERT_PCT,
        ],
        [
            "alta_vacios_satelitales",
            "alta_valores_espectrales_raros",
            "alta_alertas",
            "media_revision",
        ],
        default="baja_sin_prioridad",
    )

    return out.sort_values(
        [
            "pct_spectral_class_review",
            "pct_rare_spectral_value",
            "pct_no_spectral_data",
            "n_records",
        ],
        ascending=[False, False, False, False],
    )


def make_class_country_audit(class_country_year: pd.DataFrame) -> pd.DataFrame:
    group_cols = available_cols(
        class_country_year,
        [
            "audit_country",
            "level_0_code",
            "level_0_name",
            "level_1_code",
            "level_1_name_ref",
            "level_2_code",
            "level_2_name_ref",
        ],
    )

    out = (
        class_country_year
        .groupby(group_cols, dropna=False)
        .agg(
            n_records=("n_records", "sum"),
            n_extract_id=("n_extract_id", "sum"),
            n_years=("audit_year", "nunique"),
            n_no_spectral_data=("n_no_spectral_data", "sum"),
            n_low_months_obs=("n_low_months_obs", "sum"),
            n_high_cloudprob=("n_high_cloudprob", "sum"),
            n_rare_spectral_value=("n_rare_spectral_value", "sum"),
            n_spectral_class_review=("n_spectral_class_review", "sum"),
            s2yr_months_obs_median=("s2yr_months_obs_median", "median"),
            s2yr_ndvi_median=("s2yr_ndvi_median", "median"),
            s2yr_ndre_median=("s2yr_ndre_median", "median"),
            pct_no_spectral_data=("pct_no_spectral_data", "median"),
            pct_low_months_obs=("pct_low_months_obs", "median"),
            pct_rare_spectral_value=("pct_rare_spectral_value", "median"),
            pct_spectral_class_review=("pct_spectral_class_review", "median"),
            pct_alert_medium_high=("pct_alert_medium_high", "median"),
        )
        .reset_index()
    )

    out["class_priority_level"] = np.select(
        [
            out["pct_no_spectral_data"] >= HIGH_GAP_PCT,
            out["pct_rare_spectral_value"] >= HIGH_RARE_PCT,
            out["pct_alert_medium_high"] >= HIGH_ALERT_PCT,
            out["pct_spectral_class_review"] >= HIGH_ALERT_PCT,
        ],
        [
            "alta_vacios_satelitales",
            "alta_valores_espectrales_raros",
            "alta_alertas",
            "media_revision",
        ],
        default="baja_sin_prioridad",
    )

    return out.sort_values(
        [
            "pct_spectral_class_review",
            "pct_rare_spectral_value",
            "pct_no_spectral_data",
            "n_records",
        ],
        ascending=[False, False, False, False],
    )


def make_alert_distribution(audit: pd.DataFrame) -> pd.DataFrame:
    out = (
        audit["spectral_alert_level"]
        .fillna("sin_dato")
        .value_counts(dropna=False)
        .reset_index()
    )

    out.columns = ["spectral_alert_level", "n"]
    out["pct"] = (out["n"] / out["n"].sum() * 100).round(3)

    return out


def make_audit_summary(
    audit_original: gpd.GeoDataFrame,
    audit_units: gpd.GeoDataFrame,
    class_country_year: pd.DataFrame,
    class_country: pd.DataFrame,
    priority_records: gpd.GeoDataFrame,
    rare_records: gpd.GeoDataFrame,
    low_availability: gpd.GeoDataFrame,
) -> pd.DataFrame:
    n_original = len(audit_original)
    n_units = len(audit_units)

    return pd.DataFrame(
        [
            {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "input_gpkg": str(INPUT_GPKG),
                "input_layer_original_annual": INPUT_LAYER_ORIGINAL_ANNUAL,
                "input_layer_units_annual": INPUT_LAYER_UNITS_ANNUAL,
                "output_gpkg": str(OUTPUT_GPKG),
                "n_original_records": int(n_original),
                "n_extract_units": int(n_units),
                "n_priority_original_records": int(len(priority_records)),
                "pct_priority_original_records": pct(len(priority_records), n_original),
                "n_rare_spectral_records": int(len(rare_records)),
                "pct_rare_spectral_records": pct(len(rare_records), n_original),
                "n_low_availability_records": int(len(low_availability)),
                "pct_low_availability_records": pct(len(low_availability), n_original),
                "n_class_country_year_rows": int(len(class_country_year)),
                "n_class_country_rows": int(len(class_country)),
                "min_valid_months": MIN_VALID_MONTHS,
                "min_total_obs": MIN_TOTAL_OBS,
                "cloud_prob_high": CLOUD_PROB_HIGH,
                "ndvi_low_for_vegetation": NDVI_LOW_FOR_VEGETATION,
                "ndre_low_for_vegetation": NDRE_LOW_FOR_VEGETATION,
                "ndvi_high_for_nonvegetation": NDVI_HIGH_FOR_NON_VEGETATION,
                "min_group_size_for_rareness": MIN_GROUP_SIZE_FOR_RARENESS,
                "iqr_factor": IQR_FACTOR,
            }
        ]
    )


# =============================================================================
# SALIDAS
# =============================================================================

def guardar_tablas_csv(
    audit_summary: pd.DataFrame,
    alert_distribution: pd.DataFrame,
    class_country_year: pd.DataFrame,
    class_country: pd.DataFrame,
    priority_records: gpd.GeoDataFrame,
    rare_records: gpd.GeoDataFrame,
    low_availability: gpd.GeoDataFrame,
) -> None:
    audit_summary.to_csv(AUDIT_SUMMARY_CSV, index=False, encoding="utf-8-sig")
    alert_distribution.to_csv(ALERT_DISTRIBUTION_CSV, index=False, encoding="utf-8-sig")
    class_country_year.to_csv(CLASS_COUNTRY_YEAR_CSV, index=False, encoding="utf-8-sig")
    class_country.to_csv(CLASS_COUNTRY_CSV, index=False, encoding="utf-8-sig")

    drop_geometry_for_csv(priority_records).to_csv(
        PRIORITY_RECORDS_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    drop_geometry_for_csv(rare_records).to_csv(
        RARE_RECORDS_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    drop_geometry_for_csv(low_availability).to_csv(
        LOW_AVAILABILITY_CSV,
        index=False,
        encoding="utf-8-sig",
    )


def guardar_gpkg(
    audit_original: gpd.GeoDataFrame,
    audit_units: gpd.GeoDataFrame,
    priority_records: gpd.GeoDataFrame,
    audit_summary: pd.DataFrame,
    alert_distribution: pd.DataFrame,
    class_country_year: pd.DataFrame,
    class_country: pd.DataFrame,
    rare_records: gpd.GeoDataFrame,
    low_availability: gpd.GeoDataFrame,
) -> None:
    if OUTPUT_GPKG.exists():
        OUTPUT_GPKG.unlink()

    clean_for_gpkg(audit_original).to_file(
        OUTPUT_GPKG,
        layer=LAYER_AUDIT_ORIGINAL,
        driver="GPKG",
    )

    clean_for_gpkg(audit_units).to_file(
        OUTPUT_GPKG,
        layer=LAYER_AUDIT_UNITS,
        driver="GPKG",
    )

    clean_for_gpkg(priority_records).to_file(
        OUTPUT_GPKG,
        layer=LAYER_PRIORITY_ORIGINAL,
        driver="GPKG",
    )

    write_table_to_gpkg(audit_summary, OUTPUT_GPKG, TABLE_AUDIT_SUMMARY)
    write_table_to_gpkg(alert_distribution, OUTPUT_GPKG, TABLE_ALERT_DISTRIBUTION)
    write_table_to_gpkg(class_country_year, OUTPUT_GPKG, TABLE_CLASS_COUNTRY_YEAR)
    write_table_to_gpkg(class_country, OUTPUT_GPKG, TABLE_CLASS_COUNTRY)
    write_table_to_gpkg(drop_geometry_for_csv(rare_records), OUTPUT_GPKG, TABLE_RARE_RECORDS)
    write_table_to_gpkg(drop_geometry_for_csv(low_availability), OUTPUT_GPKG, TABLE_LOW_AVAILABILITY)


def generar_reporte_markdown(
    audit_summary: pd.DataFrame,
    alert_distribution: pd.DataFrame,
    class_country_year: pd.DataFrame,
    class_country: pd.DataFrame,
) -> None:
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    top_class_year = class_country_year.head(30).copy()
    top_class = class_country.head(30).copy()

    contenido = "\n".join(
        [
            "# Auditoría espectral preliminar por clase",
            "",
            "## Módulo 09",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## Propósito",
            "",
            "Este módulo evalúa de forma preliminar la coherencia espectral de los registros originales y unidades de extracción Sentinel-2 SR según su clase temática.",
            "",
            "La auditoría identifica vacíos satelitales, baja disponibilidad, valores espectrales potencialmente raros y señales que podrían ser inconsistentes con el grupo temático esperado.",
            "",
            "Los resultados son alertas exploratorias y no constituyen validación temática definitiva.",
            "",
            "## Entradas principales",
            "",
            "| Insumo | Ruta / valor |",
            "|---|---|",
            f"| GeoPackage de entrada | `{fmt_path(INPUT_GPKG)}` |",
            f"| Capa registros originales anual | `{INPUT_LAYER_ORIGINAL_ANNUAL}` |",
            f"| Capa unidades sin duplicados anual | `{INPUT_LAYER_UNITS_ANNUAL}` |",
            "",
            "## Salidas principales",
            "",
            "| Producto | Ruta |",
            "|---|---|",
            f"| GeoPackage de auditoría | `{fmt_path(OUTPUT_GPKG)}` |",
            f"| Tablas de auditoría | `{fmt_path(TABLES_DIR)}` |",
            f"| Reporte Markdown | `{fmt_path(REPORT_MD)}` |",
            "",
            "## Resumen general",
            "",
            dataframe_a_markdown(audit_summary),
            "",
            "## Distribución de niveles de alerta",
            "",
            dataframe_a_markdown(alert_distribution),
            "",
            "## Principales combinaciones clase-país-año priorizadas",
            "",
            dataframe_a_markdown(top_class_year),
            "",
            "## Principales combinaciones clase-país priorizadas",
            "",
            dataframe_a_markdown(top_class),
            "",
            "## Interpretación de alertas",
            "",
            "| Campo | Interpretación |",
            "|---|---|",
            "| flag_no_spectral_data | No hay evidencia espectral útil o no hay meses con observación limpia. |",
            "| flag_low_months_obs | El punto tiene menos meses válidos que el umbral definido. |",
            "| flag_low_total_obs | El total anual de observaciones limpias es bajo. |",
            "| flag_high_cloudprob | La probabilidad mediana anual de nube es alta. |",
            "| flag_vegetation_low_ndvi | Clase con vegetación esperada, pero NDVI anual mediano bajo. |",
            "| flag_vegetation_low_ndre | Clase con vegetación esperada, pero NDRE anual mediano bajo. |",
            "| flag_nonvegetation_high_ndvi | Clase con no vegetación esperada, pero NDVI anual mediano alto. |",
            "| flag_rare_spectral_value | Valor NDVI/NDRE raro respecto a su clase, país y año. |",
            "| spectral_alert_count | Número total de alertas acumuladas. |",
            "| spectral_alert_level | Nivel sintético de prioridad de revisión. |",
            "| recommended_action | Acción recomendada para revisión posterior. |",
            "",
            "## Parámetros usados",
            "",
            "| Parámetro | Valor |",
            "|---|---:|",
            f"| MIN_VALID_MONTHS | {MIN_VALID_MONTHS} |",
            f"| MIN_TOTAL_OBS | {MIN_TOTAL_OBS} |",
            f"| CLOUD_PROB_HIGH | {CLOUD_PROB_HIGH} |",
            f"| NDVI_LOW_FOR_VEGETATION | {NDVI_LOW_FOR_VEGETATION} |",
            f"| NDRE_LOW_FOR_VEGETATION | {NDRE_LOW_FOR_VEGETATION} |",
            f"| NDVI_HIGH_FOR_NON_VEGETATION | {NDVI_HIGH_FOR_NON_VEGETATION} |",
            f"| MIN_GROUP_SIZE_FOR_RARENESS | {MIN_GROUP_SIZE_FOR_RARENESS} |",
            f"| IQR_FACTOR | {IQR_FACTOR} |",
            "",
            "## Nota metodológica",
            "",
            "Esta auditoría utiliza los valores anuales derivados del Módulo 08. No reprocesa los CSV mensuales de GEE.",
            "",
            "Los registros originales se conservan con sus duplicados porque corresponden al flujo original de datos. La capa `audit_extract_units_s2sr_annual` permite revisar las mismas alertas sin duplicación por `extract_id`.",
            "",
            "Las alertas deben interpretarse como criterios de priorización para revisión temática o metodológica posterior.",
            "",
        ]
    )

    REPORT_MD.write_text(contenido, encoding="utf-8")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    crear_carpetas()

    print("============================================================")
    print("PGBM - Módulo 09 - Auditoría espectral por clase")
    print("============================================================")
    print("Project root:", PROJECT_ROOT)
    print("Input GPKG:", INPUT_GPKG)
    print("Output GPKG:", OUTPUT_GPKG)
    print("Tables dir:", TABLES_DIR)
    print("Reports dir:", REPORTS_DIR)
    print("============================================================")

    print("\nCargando capas de entrada...")
    original_annual = cargar_capa(INPUT_GPKG, INPUT_LAYER_ORIGINAL_ANNUAL)
    units_annual = cargar_capa(INPUT_GPKG, INPUT_LAYER_UNITS_ANNUAL)

    print("Registros originales anual:", len(original_annual))
    print("Unidades extract_id anual:", len(units_annual))

    print("\nConstruyendo auditoría por registro original...")
    audit_original = build_spectral_audit(original_annual)

    print("Construyendo auditoría sin duplicados por extract_id...")
    audit_units = build_spectral_audit(units_annual)

    print("\nConstruyendo capas/tablas de prioridad...")
    priority_records = audit_original[
        audit_original["flag_spectral_class_review"] == 1
    ].copy()

    rare_records = audit_original[
        audit_original["flag_rare_spectral_value"] == 1
    ].copy()

    low_availability = audit_original[
        (audit_original["flag_no_spectral_data"] == 1)
        | (audit_original["flag_low_months_obs"] == 1)
        | (audit_original["flag_low_total_obs"] == 1)
    ].copy()

    print("Priority records:", len(priority_records))
    print("Rare spectral records:", len(rare_records))
    print("Low availability records:", len(low_availability))

    print("\nConstruyendo resúmenes agregados...")
    class_country_year = make_class_country_year_audit(audit_original)
    class_country = make_class_country_audit(class_country_year)
    alert_distribution = make_alert_distribution(audit_original)

    audit_summary = make_audit_summary(
        audit_original=audit_original,
        audit_units=audit_units,
        class_country_year=class_country_year,
        class_country=class_country,
        priority_records=priority_records,
        rare_records=rare_records,
        low_availability=low_availability,
    )

    print("\nGuardando tablas CSV...")
    guardar_tablas_csv(
        audit_summary=audit_summary,
        alert_distribution=alert_distribution,
        class_country_year=class_country_year,
        class_country=class_country,
        priority_records=priority_records,
        rare_records=rare_records,
        low_availability=low_availability,
    )

    print("Guardando GPKG...")
    guardar_gpkg(
        audit_original=audit_original,
        audit_units=audit_units,
        priority_records=priority_records,
        audit_summary=audit_summary,
        alert_distribution=alert_distribution,
        class_country_year=class_country_year,
        class_country=class_country,
        rare_records=rare_records,
        low_availability=low_availability,
    )

    print("Generando reporte Markdown...")
    generar_reporte_markdown(
        audit_summary=audit_summary,
        alert_distribution=alert_distribution,
        class_country_year=class_country_year,
        class_country=class_country,
    )

    print("\n============================================================")
    print("MÓDULO 09 FINALIZADO")
    print("============================================================")
    print("Registros originales auditados:", len(audit_original))
    print("Unidades sin duplicados auditadas:", len(audit_units))
    print("Registros priorizados:", len(priority_records))
    print("Registros con rareza espectral:", len(rare_records))
    print("Registros con baja disponibilidad:", len(low_availability))
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