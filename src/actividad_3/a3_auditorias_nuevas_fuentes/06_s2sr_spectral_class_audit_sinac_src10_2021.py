from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import sqlite3
import traceback
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd


# =============================================================================
# PGBM - Auditoría espectral por clase para nueva fuente puntual
# Caso: SINAC SRC10 2021
# =============================================================================
#
# Propósito:
#   Evaluar de forma preliminar la coherencia espectral de los registros SINAC
#   usando los resúmenes anuales Sentinel-2 SR generados en el paso de unión
#   espectral.
#
# Este script está adaptado a:
#   SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica
#   source_id / id_fuente = 10
#   país = CRI
#   año = 2021
#
# Entrada esperada:
#   data/processed/a3_auditorias_nuevas_fuentes/s2sr_join/sinac_src10_2021_s2sr_join_outputs.gpkg
#
# Capas de entrada esperadas:
#   - sinac_src10_records_s2sr_annual
#   - sinac_src10_extract_units_s2sr_annual
#
# Salida principal:
#   data/processed/a3_auditorias_nuevas_fuentes/spectral_class_audit/s2sr_spectral_class_audit_sinac_src10_2021_outputs.gpkg
#
# Notas metodológicas:
#   - Las alertas son exploratorias; no equivalen a validación temática final.
#   - Las reglas usan NDVI/NDRE anual mediano, disponibilidad anual y rareza
#     estadística por clase.
#   - El bosque maduro y el bosque secundario usan la misma regla espectral.
#   - El bosque secundario deciduo mantiene una regla más conservadora por
#     estacionalidad.
#   - Humedal palustre se trata como clase mixta agua-vegetación.
# =============================================================================


# =============================================================================
# CONFIGURACIÓN GENERAL
# =============================================================================

SOURCE_NAME = "SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica"
SOURCE_CODE = "SRC10"
SOURCE_ID_EXPECTED = 10
COUNTRY_CODE_EXPECTED = "CRI"
YEAR_REF_EXPECTED = 2021

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]

DEFAULT_INPUT_CANDIDATES = [
    Path("data/processed/a3_auditorias_nuevas_fuentes/s2sr_join/sinac_src10_2021_s2sr_join_outputs.gpkg"),
]

INPUT_LAYER_ORIGINAL_ANNUAL = "sinac_src10_records_s2sr_annual"
INPUT_LAYER_UNITS_ANNUAL = "sinac_src10_extract_units_s2sr_annual"

OUTPUT_DIR_REL = Path("data/processed/a3_auditorias_nuevas_fuentes/spectral_class_audit")
TABLES_DIR_REL = Path("outputs/tables/a3_auditorias_nuevas_fuentes/spectral_class_audit")
REPORTS_DIR_REL = Path("outputs/reports/a3_auditorias_nuevas_fuentes/spectral_class_audit")

OUTPUT_GPKG_NAME = "s2sr_spectral_class_audit_sinac_src10_2021_outputs.gpkg"
REPORT_MD_NAME = "s2sr_spectral_class_audit_sinac_src10_2021_report.md"

LAYER_AUDIT_ORIGINAL = "sinac_src10_audit_original_records_s2sr_annual"
LAYER_AUDIT_UNITS = "sinac_src10_audit_extract_units_s2sr_annual"
LAYER_PRIORITY_ORIGINAL = "sinac_src10_priority_original_records_s2sr"
LAYER_PRIORITY_UNITS = "sinac_src10_priority_extract_units_s2sr"
LAYER_XY_GROUP_AUDIT = "sinac_src10_xy_group_spectral_audit"

TABLE_AUDIT_SUMMARY = "audit_summary"
TABLE_ALERT_DISTRIBUTION_ORIGINAL = "alert_distribution_original_records"
TABLE_ALERT_DISTRIBUTION_UNITS = "alert_distribution_extract_units"
TABLE_CLASS_AUDIT_ORIGINAL = "class_spectral_audit_original_records"
TABLE_CLASS_AUDIT_UNITS = "class_spectral_audit_extract_units"
TABLE_RARE_RECORDS = "rare_spectral_records"
TABLE_LOW_AVAILABILITY = "low_satellite_availability_records"
TABLE_CLASS_RULES = "sinac_class_rules_reference"
TABLE_RULE_PARAMETERS = "audit_rule_parameters"
TABLE_EXTRACT_THEME_CONTEXT = "extract_unit_thematic_context"
TABLE_XY_GROUP_AUDIT = "xy_group_spectral_audit"

AUDIT_SUMMARY_CSV_NAME = "audit_summary.csv"
ALERT_DISTRIBUTION_ORIGINAL_CSV_NAME = "alert_distribution_original_records.csv"
ALERT_DISTRIBUTION_UNITS_CSV_NAME = "alert_distribution_extract_units.csv"
CLASS_AUDIT_ORIGINAL_CSV_NAME = "class_spectral_audit_original_records.csv"
CLASS_AUDIT_UNITS_CSV_NAME = "class_spectral_audit_extract_units.csv"
PRIORITY_ORIGINAL_CSV_NAME = "priority_original_records_s2sr.csv"
PRIORITY_UNITS_CSV_NAME = "priority_extract_units_s2sr.csv"
RARE_RECORDS_CSV_NAME = "rare_spectral_records.csv"
LOW_AVAILABILITY_CSV_NAME = "low_satellite_availability_records.csv"
CLASS_RULES_CSV_NAME = "sinac_class_rules_reference.csv"
RULE_PARAMETERS_CSV_NAME = "audit_rule_parameters.csv"
EXTRACT_THEME_CONTEXT_CSV_NAME = "extract_unit_thematic_context.csv"
XY_GROUP_AUDIT_CSV_NAME = "xy_group_spectral_audit.csv"


# =============================================================================
# PARÁMETROS DE AUDITORÍA
# =============================================================================

MIN_VALID_MONTHS = 4
MIN_TOTAL_OBS = 4
CLOUD_PROB_HIGH = 60.0

MIN_GROUP_SIZE_FOR_RARENESS = 20
IQR_FACTOR = 1.5

HIGH_GAP_PCT = 25.0
HIGH_RARE_PCT = 15.0
HIGH_ALERT_PCT = 25.0


# =============================================================================
# REGLAS TEMÁTICO-ESPECTRALES SINAC
# =============================================================================

# Las reglas se implementan explícitamente en evaluate_class_rule(). Esta tabla
# sirve para documentar el criterio dentro del GPKG, CSV y reporte.
SINAC_CLASS_RULES = [
    {
        "class_code": 1,
        "class_name": "Bosque maduro",
        "expected_signal_group": "vegetacion_forestal_esperada",
        "medium_rule": "NDVI < 0.40 o NDRE < 0.10",
        "high_rule": "NDVI < 0.30 o NDRE < 0.06",
        "note": "Misma regla que bosque secundario para evitar falsa precisión en esta versión piloto.",
    },
    {
        "class_code": 2,
        "class_name": "Bosque secundario",
        "expected_signal_group": "vegetacion_forestal_esperada",
        "medium_rule": "NDVI < 0.40 o NDRE < 0.10",
        "high_rule": "NDVI < 0.30 o NDRE < 0.06",
        "note": "Misma regla que bosque maduro.",
    },
    {
        "class_code": 4,
        "class_name": "Bosque secundario deciduo",
        "expected_signal_group": "vegetacion_forestal_estacional",
        "medium_rule": "NDVI < 0.30 o NDRE < 0.07",
        "high_rule": "NDVI < 0.22 o NDRE < 0.04",
        "note": "Regla conservadora por estacionalidad del bosque deciduo en trópico seco.",
    },
    {
        "class_code": 6,
        "class_name": "Manglar",
        "expected_signal_group": "vegetacion_humeda_mixta",
        "medium_rule": "NDVI < 0.40 o NDRE < 0.08",
        "high_rule": "NDVI < 0.30 o NDRE < 0.05",
        "note": "Tolera mezcla con agua/borde, pero prioriza señales vegetales muy bajas.",
    },
    {
        "class_code": 8,
        "class_name": "Pastos",
        "expected_signal_group": "vegetacion_herbacea_estacional",
        "medium_rule": "NDVI < 0.25 o NDVI > 0.70 o NDVI > 0.65 y NDRE > 0.18",
        "high_rule": "NDVI < 0.18",
        "note": "Regla conservadora por variabilidad estacional y manejo ganadero.",
    },
    {
        "class_code": 9,
        "class_name": "Cultivos",
        "expected_signal_group": "vegetacion_agricola_variable",
        "medium_rule": "NDVI < 0.15 o NDVI > 0.85 o NDRE < 0.02",
        "high_rule": "No aplica por umbral fijo; alta si conflicto temático + rareza/extremo.",
        "note": "Clase variable por ciclos agrícolas, suelo preparado, cosecha y barbecho.",
    },
    {
        "class_code": 10,
        "class_name": "Agua",
        "expected_signal_group": "agua_baja_vegetacion",
        "medium_rule": "NDVI > 0.20 o NDRE > 0.04",
        "high_rule": "NDVI > 0.35 o NDRE > 0.08",
        "note": "Señal vegetal alta sugiere borde, humedal, manglar, mezcla o error temático.",
    },
    {
        "class_code": 11,
        "class_name": "Humedal Palustre",
        "expected_signal_group": "humedal_mixto",
        "medium_rule": "NDVI < 0.05 o NDVI > 0.75 o NDRE > 0.20",
        "high_rule": "No aplica por umbral fijo; alta si conflicto temático + extremo/rareza.",
        "note": "Clase mixta agua-vegetación; se detectan extremos, no una señal única esperada.",
    },
    {
        "class_code": 16,
        "class_name": "Edificaciones",
        "expected_signal_group": "no_vegetacion_esperada",
        "medium_rule": "NDVI > 0.40 o NDRE > 0.12",
        "high_rule": "NDVI > 0.55 o NDVI > 0.50 y NDRE > 0.12",
        "note": "Puede haber mezcla a 20 m con árboles, jardines o bordes urbanos.",
    },
]

CLASS_RULES_BY_CODE = {int(row["class_code"]): row for row in SINAC_CLASS_RULES}


# =============================================================================
# RUTAS
# =============================================================================

def resolve_path(path_value: str | Path | None, base_dir: Path = PROJECT_DIR) -> Path | None:
    if path_value is None:
        return None
    path = Path(path_value)
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def resolve_default_input() -> Path:
    candidates: list[Path] = []

    for rel_path in DEFAULT_INPUT_CANDIDATES:
        candidates.append((PROJECT_DIR / rel_path).resolve())
        candidates.append((Path.cwd() / rel_path).resolve())

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate

    checked = "\n".join(f" - {p}" for p in candidates)
    raise FileNotFoundError(
        "No se encontró el GeoPackage de entrada. Rutas revisadas:\n" + checked
    )


def fmt_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_DIR)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


# =============================================================================
# UTILIDADES
# =============================================================================

def crear_carpetas(output_dir: Path, tables_dir: Path, reports_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    return df


def available_cols(df: pd.DataFrame, cols: list[str]) -> list[str]:
    return [c for c in cols if c in df.columns]


def to_numeric_safe(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def as_int_flag(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool).astype("int8")


def pct(n: float | int, d: float | int) -> float:
    n = 0 if pd.isna(n) else float(n)
    d = 0 if pd.isna(d) else float(d)
    return 0.0 if d == 0 else round(n / d * 100.0, 3)


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


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


def drop_geometry_for_csv(df: gpd.GeoDataFrame | pd.DataFrame) -> pd.DataFrame:
    if isinstance(df, gpd.GeoDataFrame):
        return pd.DataFrame(df.drop(columns=[df.geometry.name], errors="ignore"))
    return pd.DataFrame(df)


def write_table_to_gpkg(df: pd.DataFrame, gpkg_path: Path, table_name: str) -> None:
    table = clean_for_gpkg(df)
    with sqlite3.connect(gpkg_path) as conn:
        table.to_sql(table_name, conn, if_exists="replace", index=False)


# =============================================================================
# NORMALIZACIÓN DE CAMPOS SINAC
# =============================================================================

def first_existing(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def ensure_sinac_standard_fields(df: pd.DataFrame) -> pd.DataFrame:
    out = clean_columns(df)

    country_col = first_existing(out, ["Pais_es", "country", "audit_country"])
    country_code_col = first_existing(out, ["Pais_cod3", "country_code", "audit_country_code"])
    source_col = first_existing(out, ["Fuente", "source", "audit_source"])
    source_id_col = first_existing(out, ["id_fuente", "source_id", "audit_source_id"])
    year_col = first_existing(out, ["Año", "year_ref", "s2_year_ref", "s2_year_extraction", "audit_year"])

    class_code_col = first_existing(out, ["Clase", "class_code", "audit_class_code"])
    class_group_col = first_existing(out, ["GranClase", "class_group_code", "audit_class_group_code"])
    class_name_col = first_existing(out, ["nombre_clase", "class_name", "audit_class_name"])
    class_group_name_col = first_existing(out, ["nombre_gran_clase", "class_group_name", "audit_class_group_name"])

    out["audit_country"] = out[country_col] if country_col else pd.NA
    out["audit_country_code"] = out[country_code_col] if country_code_col else pd.NA
    out["audit_source"] = out[source_col] if source_col else pd.NA
    out["audit_source_id"] = out[source_id_col] if source_id_col else pd.NA
    out["audit_year"] = out[year_col] if year_col else pd.NA

    out["audit_class_code"] = out[class_code_col] if class_code_col else pd.NA
    out["audit_class_group_code"] = out[class_group_col] if class_group_col else pd.NA
    out["audit_class_name"] = out[class_name_col] if class_name_col else pd.NA
    out["audit_class_group_name"] = out[class_group_name_col] if class_group_name_col else pd.NA

    numeric_cols = [
        "audit_source_id",
        "audit_year",
        "audit_class_code",
        "audit_class_group_code",
        "s2_n_month_rows",
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
        "n_records_extract_unit",
    ]

    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    for col in [
        "extract_id",
        "audit_country",
        "audit_country_code",
        "audit_source",
        "audit_class_name",
        "audit_class_group_name",
    ]:
        if col in out.columns:
            out[col] = out[col].astype("string")

    out["expected_signal_group"] = out["audit_class_code"].map(
        lambda x: CLASS_RULES_BY_CODE.get(int(x), {}).get("expected_signal_group", "sin_regla")
        if pd.notna(x)
        else "sin_regla"
    )

    return out


# =============================================================================
# CONTEXTO TEMÁTICO POR EXTRACT_ID
# =============================================================================

def compute_extract_theme_context(original_records: gpd.GeoDataFrame) -> pd.DataFrame:
    base = ensure_sinac_standard_fields(original_records)

    if "extract_id" not in base.columns:
        raise ValueError("La capa original anual no contiene extract_id.")

    context = (
        base.groupby("extract_id", dropna=False)
        .agg(
            n_records_same_extract_id=("extract_id", "size"),
            n_unique_class_code_extract_unit=("audit_class_code", "nunique"),
            n_unique_class_group_code_extract_unit=("audit_class_group_code", "nunique"),
            class_codes_extract_unit=(
                "audit_class_code",
                lambda s: ";".join(
                    sorted({str(int(v)) for v in pd.to_numeric(s, errors="coerce").dropna()})
                ),
            ),
            class_names_extract_unit=(
                "audit_class_name",
                lambda s: ";".join(sorted({str(v) for v in s.dropna().astype(str)})),
            ),
            class_group_codes_extract_unit=(
                "audit_class_group_code",
                lambda s: ";".join(
                    sorted({str(int(v)) for v in pd.to_numeric(s, errors="coerce").dropna()})
                ),
            ),
            class_group_names_extract_unit=(
                "audit_class_group_name",
                lambda s: ";".join(sorted({str(v) for v in s.dropna().astype(str)})),
            ),
        )
        .reset_index()
    )

    context["flag_context_multiple_records_extract_unit"] = (
        context["n_records_same_extract_id"] > 1
    ).astype("int8")

    context["flag_context_multiple_class_code"] = (
        context["n_unique_class_code_extract_unit"] > 1
    ).astype("int8")

    context["flag_context_multiple_class_group_code"] = (
        context["n_unique_class_group_code_extract_unit"] > 1
    ).astype("int8")

    context["flag_context_thematic_conflict"] = (
        (context["flag_context_multiple_class_code"] == 1)
        | (context["flag_context_multiple_class_group_code"] == 1)
    ).astype("int8")

    return context


def merge_theme_context(df: gpd.GeoDataFrame, context: pd.DataFrame) -> gpd.GeoDataFrame:
    out = df.copy()

    context_cols = [c for c in context.columns if c != "extract_id"]
    out = out.drop(columns=[c for c in context_cols if c in out.columns], errors="ignore")

    out["extract_id"] = out["extract_id"].astype("string")
    context = context.copy()
    context["extract_id"] = context["extract_id"].astype("string")

    merged = out.merge(context, on="extract_id", how="left")
    return gpd.GeoDataFrame(merged, geometry=df.geometry.name, crs=df.crs)


# =============================================================================
# REGLAS POR CLASE
# =============================================================================

def is_number(value: Any) -> bool:
    try:
        return pd.notna(float(value))
    except Exception:
        return False


def evaluate_class_rule(row: pd.Series) -> tuple[str, str]:
    """
    Return class-rule severity and reason.

    severity values:
      - none
      - medium
      - high
    """
    code_raw = row.get("audit_class_code", np.nan)
    if pd.isna(code_raw):
        return "none", "Sin código de clase para regla espectral"

    code = int(code_raw)
    ndvi = row.get("s2yr_ndvi_median", np.nan)
    ndre = row.get("s2yr_ndre_median", np.nan)

    ndvi_ok = is_number(ndvi)
    ndre_ok = is_number(ndre)

    if not ndvi_ok and not ndre_ok:
        return "none", "Sin NDVI/NDRE anual disponible"

    ndvi_v = float(ndvi) if ndvi_ok else np.nan
    ndre_v = float(ndre) if ndre_ok else np.nan

    def lt(value: float, threshold: float) -> bool:
        return pd.notna(value) and value < threshold

    def gt(value: float, threshold: float) -> bool:
        return pd.notna(value) and value > threshold

    # Bosque maduro y bosque secundario: misma regla.
    if code in [1, 2]:
        if lt(ndvi_v, 0.30) or lt(ndre_v, 0.06):
            return "high", "Bosque maduro/secundario con NDVI < 0.30 o NDRE < 0.06"
        if lt(ndvi_v, 0.40) or lt(ndre_v, 0.10):
            return "medium", "Bosque maduro/secundario con NDVI < 0.40 o NDRE < 0.10"
        return "none", "Señal compatible con bosque maduro/secundario"

    # Bosque secundario deciduo: regla conservadora por estacionalidad.
    if code == 4:
        if lt(ndvi_v, 0.22) or lt(ndre_v, 0.04):
            return "high", "Bosque secundario deciduo con NDVI < 0.22 o NDRE < 0.04"
        if lt(ndvi_v, 0.30) or lt(ndre_v, 0.07):
            return "medium", "Bosque secundario deciduo con NDVI < 0.30 o NDRE < 0.07"
        return "none", "Señal compatible con bosque secundario deciduo"

    # Manglar.
    if code == 6:
        if lt(ndvi_v, 0.30) or lt(ndre_v, 0.05):
            return "high", "Manglar con NDVI < 0.30 o NDRE < 0.05"
        if lt(ndvi_v, 0.40) or lt(ndre_v, 0.08):
            return "medium", "Manglar con NDVI < 0.40 o NDRE < 0.08"
        return "none", "Señal compatible con manglar"

    # Pastos.
    if code == 8:
        if lt(ndvi_v, 0.18):
            return "high", "Pastos con NDVI < 0.18"
        if lt(ndvi_v, 0.25):
            return "medium", "Pastos con NDVI < 0.25"
        if gt(ndvi_v, 0.70):
            return "medium", "Pastos con NDVI > 0.70"
        if gt(ndvi_v, 0.65) and gt(ndre_v, 0.18):
            return "medium", "Pastos con NDVI > 0.65 y NDRE > 0.18"
        return "none", "Señal compatible con pastos"

    # Cultivos: clase agrícola variable, sin alerta alta por umbral fijo.
    if code == 9:
        if lt(ndvi_v, 0.15):
            return "medium", "Cultivos con NDVI < 0.15"
        if gt(ndvi_v, 0.85):
            return "medium", "Cultivos con NDVI > 0.85"
        if lt(ndre_v, 0.02):
            return "medium", "Cultivos con NDRE < 0.02"
        return "none", "Señal compatible con cultivos o variabilidad agrícola esperada"

    # Agua.
    if code == 10:
        if gt(ndvi_v, 0.35) or gt(ndre_v, 0.08):
            return "high", "Agua con NDVI > 0.35 o NDRE > 0.08"
        if gt(ndvi_v, 0.20) or gt(ndre_v, 0.04):
            return "medium", "Agua con NDVI > 0.20 o NDRE > 0.04"
        return "none", "Señal compatible con agua"

    # Humedal palustre: clase mixta, solo extremos como alerta media.
    if code == 11:
        if lt(ndvi_v, 0.05):
            return "medium", "Humedal palustre con NDVI < 0.05"
        if gt(ndvi_v, 0.75):
            return "medium", "Humedal palustre con NDVI > 0.75"
        if gt(ndre_v, 0.20):
            return "medium", "Humedal palustre con NDRE > 0.20"
        return "none", "Señal compatible con humedal palustre mixto"

    # Edificaciones.
    if code == 16:
        if gt(ndvi_v, 0.55):
            return "high", "Edificaciones con NDVI > 0.55"
        if gt(ndvi_v, 0.50) and gt(ndre_v, 0.12):
            return "high", "Edificaciones con NDVI > 0.50 y NDRE > 0.12"
        if gt(ndvi_v, 0.40) or gt(ndre_v, 0.12):
            return "medium", "Edificaciones con NDVI > 0.40 o NDRE > 0.12"
        return "none", "Señal compatible con edificaciones o mezcla urbana esperada"

    return "none", "Clase SINAC sin regla espectral específica"


# =============================================================================
# RAREZA ESTADÍSTICA POR CLASE
# =============================================================================

def add_rare_flags_by_class_year(audit: pd.DataFrame) -> pd.DataFrame:
    out = audit.copy()

    out["flag_ndvi_rare_by_class_year"] = False
    out["flag_ndre_rare_by_class_year"] = False
    out["ndvi_class_iqr_low"] = np.nan
    out["ndvi_class_iqr_high"] = np.nan
    out["ndre_class_iqr_low"] = np.nan
    out["ndre_class_iqr_high"] = np.nan

    group_cols = available_cols(
        out,
        ["audit_country_code", "audit_year", "audit_class_code"],
    )

    if len(group_cols) < 3:
        return out

    for _, group in out.groupby(group_cols, dropna=False):
        if len(group) < MIN_GROUP_SIZE_FOR_RARENESS:
            continue

        for metric, flag_col, low_col, high_col in [
            (
                "s2yr_ndvi_median",
                "flag_ndvi_rare_by_class_year",
                "ndvi_class_iqr_low",
                "ndvi_class_iqr_high",
            ),
            (
                "s2yr_ndre_median",
                "flag_ndre_rare_by_class_year",
                "ndre_class_iqr_low",
                "ndre_class_iqr_high",
            ),
        ]:
            if metric not in out.columns:
                continue

            values = pd.to_numeric(group[metric], errors="coerce").dropna()
            if len(values) < MIN_GROUP_SIZE_FOR_RARENESS:
                continue

            q1 = values.quantile(0.25)
            q3 = values.quantile(0.75)
            iqr = q3 - q1

            if pd.isna(iqr) or iqr == 0:
                continue

            low = q1 - IQR_FACTOR * iqr
            high = q3 + IQR_FACTOR * iqr

            idx = group.index[
                out.loc[group.index, metric].notna()
                & (
                    (out.loc[group.index, metric] < low)
                    | (out.loc[group.index, metric] > high)
                )
            ]

            out.loc[group.index, low_col] = low
            out.loc[group.index, high_col] = high
            out.loc[idx, flag_col] = True

    return out


# =============================================================================
# AUDITORÍA ESPECTRAL
# =============================================================================

def build_spectral_audit(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    audit = ensure_sinac_standard_fields(gdf)

    # Asegurar columnas mínimas aunque falten en alguna versión del GPKG.
    for col in [
        "s2yr_months_obs",
        "s2yr_obs_total",
        "s2yr_obs_mean",
        "s2yr_cloudprob_median",
        "s2yr_ndvi_median",
        "s2yr_ndvi8a_median",
        "s2yr_ndre_median",
        "flag_context_thematic_conflict",
        "flag_context_multiple_records_extract_unit",
        "flag_context_multiple_class_code",
        "flag_context_multiple_class_group_code",
    ]:
        if col not in audit.columns:
            audit[col] = np.nan

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

    # Reglas por clase.
    rule_results = audit.apply(evaluate_class_rule, axis=1, result_type="expand")
    rule_results.columns = ["class_rule_alert_level", "class_rule_reason"]
    audit["class_rule_alert_level"] = rule_results["class_rule_alert_level"]
    audit["class_rule_reason"] = rule_results["class_rule_reason"]

    audit["flag_class_rule_high"] = audit["class_rule_alert_level"].eq("high")
    audit["flag_class_rule_medium"] = audit["class_rule_alert_level"].eq("medium")
    audit["flag_class_rule_triggered"] = audit["class_rule_alert_level"].isin(["high", "medium"])

    # Rareza estadística.
    audit = add_rare_flags_by_class_year(audit)

    audit["flag_rare_spectral_value"] = (
        audit["flag_ndvi_rare_by_class_year"]
        | audit["flag_ndre_rare_by_class_year"]
    )

    # Banderas contextuales.
    for col in [
        "flag_context_thematic_conflict",
        "flag_context_multiple_records_extract_unit",
        "flag_context_multiple_class_code",
        "flag_context_multiple_class_group_code",
    ]:
        audit[col] = pd.to_numeric(audit[col], errors="coerce").fillna(0) > 0

    audit["flag_conflict_and_rare"] = (
        audit["flag_context_thematic_conflict"]
        & audit["flag_rare_spectral_value"]
    )

    audit["flag_conflict_and_class_rule"] = (
        audit["flag_context_thematic_conflict"]
        & audit["flag_class_rule_triggered"]
    )

    flag_cols = [
        "flag_no_spectral_data",
        "flag_low_months_obs",
        "flag_low_total_obs",
        "flag_high_cloudprob",
        "flag_class_rule_high",
        "flag_class_rule_medium",
        "flag_rare_spectral_value",
        "flag_context_thematic_conflict",
        "flag_context_multiple_records_extract_unit",
        "flag_context_multiple_class_code",
        "flag_context_multiple_class_group_code",
        "flag_conflict_and_rare",
        "flag_conflict_and_class_rule",
    ]

    for col in flag_cols:
        audit[col] = as_int_flag(audit[col])

    audit["spectral_alert_count"] = audit[flag_cols].sum(axis=1).astype("int16")

    audit["spectral_alert_level"] = np.select(
        [
            audit["flag_no_spectral_data"] == 1,
            audit["flag_class_rule_high"] == 1,
            audit["flag_conflict_and_rare"] == 1,
            audit["flag_conflict_and_class_rule"] == 1,
            audit["spectral_alert_count"] >= 4,
            audit["flag_class_rule_medium"] == 1,
            audit["flag_rare_spectral_value"] == 1,
            audit["spectral_alert_count"].between(2, 3),
            audit["spectral_alert_count"] == 1,
        ],
        [
            "alta_sin_datos",
            "alta",
            "alta",
            "alta",
            "alta",
            "media",
            "media",
            "media",
            "baja",
        ],
        default="sin_alerta",
    )

    audit["recommended_action"] = np.select(
        [
            audit["spectral_alert_level"].eq("alta_sin_datos"),
            audit["spectral_alert_level"].eq("alta"),
            audit["spectral_alert_level"].eq("media"),
            audit["spectral_alert_level"].eq("baja"),
        ],
        [
            "Revisar disponibilidad satelital o excluir de análisis espectral",
            "Priorizar revisión temática y espectral",
            "Revisar en control de calidad temático/espectral",
            "Revisar si pertenece a clase o fuente prioritaria",
        ],
        default="Sin alerta preliminar",
    )

    audit["main_alert_reason"] = audit.apply(main_alert_reason, axis=1)

    audit["flag_spectral_class_review"] = (
        audit["spectral_alert_level"] != "sin_alerta"
    ).astype("int8")

    audit["flag_spectral_priority"] = audit["spectral_alert_level"].isin(
        ["alta_sin_datos", "alta", "media"]
    ).astype("int8")

    audit["audit_scope"] = "Auditoría espectral preliminar SINAC SRC10 2021"
    audit["audit_interpretation"] = (
        "Alerta exploratoria; no constituye validación temática definitiva"
    )

    return gpd.GeoDataFrame(audit, geometry=gdf.geometry.name, crs=gdf.crs)


def main_alert_reason(row: pd.Series) -> str:
    if row.get("flag_no_spectral_data", 0) == 1:
        return "sin_datos_espectrales"
    if row.get("flag_class_rule_high", 0) == 1:
        return "regla_clase_alta: " + str(row.get("class_rule_reason", ""))
    if row.get("flag_conflict_and_rare", 0) == 1:
        return "conflicto_tematico_y_rareza_espectral"
    if row.get("flag_conflict_and_class_rule", 0) == 1:
        return "conflicto_tematico_y_regla_clase"
    if row.get("flag_class_rule_medium", 0) == 1:
        return "regla_clase_media: " + str(row.get("class_rule_reason", ""))
    if row.get("flag_rare_spectral_value", 0) == 1:
        return "rareza_espectral_por_clase_anio"
    if row.get("flag_low_months_obs", 0) == 1:
        return "baja_cantidad_meses_observados"
    if row.get("flag_low_total_obs", 0) == 1:
        return "bajo_total_observaciones_limpias"
    if row.get("flag_high_cloudprob", 0) == 1:
        return "alta_probabilidad_mediana_nube"
    if row.get("flag_context_thematic_conflict", 0) == 1:
        return "conflicto_tematico_contextual"
    if row.get("flag_context_multiple_records_extract_unit", 0) == 1:
        return "multiples_registros_misma_unidad_extraccion"
    return "sin_alerta"


# =============================================================================
# RESÚMENES
# =============================================================================

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


def make_xy_group_spectral_audit(audit: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Aggregate spectral alerts by xy_group_id when the field is available."""
    if "xy_group_id" not in audit.columns:
        return gpd.GeoDataFrame(
            columns=[
                "xy_group_id",
                "n_records",
                "n_extract_ids",
                "n_priority_records",
                "pct_priority_records",
                "max_spectral_alert_level",
            ],
            geometry=[],
            crs=audit.crs,
        )

    tmp = audit.copy()
    tmp["alert_rank"] = tmp["spectral_alert_level"].map(
        {
            "sin_alerta": 0,
            "baja": 1,
            "media": 2,
            "alta": 3,
            "alta_sin_datos": 4,
        }
    ).fillna(0)

    rows = (
        tmp.groupby("xy_group_id", dropna=False)
        .agg(
            lon=("Longitud", "first") if "Longitud" in tmp.columns else ("geometry", lambda s: pd.NA),
            lat=("Latitud", "first") if "Latitud" in tmp.columns else ("geometry", lambda s: pd.NA),
            country=("audit_country", first_existing_value),
            country_code=("audit_country_code", first_existing_value),
            source=("audit_source", first_existing_value),
            source_id=("audit_source_id", first_existing_value),
            n_records=("xy_group_id", "size"),
            n_extract_ids=("extract_id", lambda s: s.nunique(dropna=True)),
            n_classes=("audit_class_code", lambda s: s.nunique(dropna=True)),
            n_class_groups=("audit_class_group_code", lambda s: s.nunique(dropna=True)),
            n_priority_records=("flag_spectral_priority", "sum"),
            n_no_spectral_data=("flag_no_spectral_data", "sum"),
            n_rare_spectral_records=("flag_rare_spectral_value", "sum"),
            n_thematic_conflict_records=("flag_context_thematic_conflict", "sum"),
            max_alert_rank=("alert_rank", "max"),
            median_ndvi=("s2yr_ndvi_median", "median"),
            median_ndre=("s2yr_ndre_median", "median"),
            median_months_obs=("s2yr_months_obs", "median"),
        )
        .reset_index()
    )

    rank_to_level = {
        0: "sin_alerta",
        1: "baja",
        2: "media",
        3: "alta",
        4: "alta_sin_datos",
    }
    rows["max_spectral_alert_level"] = rows["max_alert_rank"].map(rank_to_level).fillna("sin_alerta")
    rows["pct_priority_records"] = (
        rows["n_priority_records"] / rows["n_records"] * 100
    ).round(3)
    rows["has_multiple_classes"] = (rows["n_classes"] > 1).astype("int8")
    rows["has_multiple_class_groups"] = (rows["n_class_groups"] > 1).astype("int8")

    if "geometry" in tmp.columns:
        geom = tmp.groupby("xy_group_id", dropna=False).geometry.first().reset_index()
        rows = rows.merge(geom, on="xy_group_id", how="left")
        return gpd.GeoDataFrame(rows, geometry="geometry", crs=audit.crs)

    return gpd.GeoDataFrame(rows, geometry=[], crs=audit.crs)


def first_existing_value(series: pd.Series) -> object:
    vals = series.dropna()
    if vals.empty:
        return pd.NA
    return vals.iloc[0]


def make_class_spectral_audit(audit: pd.DataFrame) -> pd.DataFrame:
    group_cols = available_cols(
        audit,
        [
            "audit_country_code",
            "audit_country",
            "audit_year",
            "audit_class_group_code",
            "audit_class_group_name",
            "audit_class_code",
            "audit_class_name",
            "expected_signal_group",
        ],
    )

    out = (
        audit.groupby(group_cols, dropna=False)
        .agg(
            n_records=("extract_id", "size"),
            n_extract_id=("extract_id", "nunique"),
            s2yr_months_obs_median=("s2yr_months_obs", "median"),
            s2yr_obs_total_median=("s2yr_obs_total", "median"),
            s2yr_cloudprob_median=("s2yr_cloudprob_median", "median"),
            s2yr_ndvi_median=("s2yr_ndvi_median", "median"),
            s2yr_ndre_median=("s2yr_ndre_median", "median"),
            n_no_spectral_data=("flag_no_spectral_data", "sum"),
            n_low_months_obs=("flag_low_months_obs", "sum"),
            n_low_total_obs=("flag_low_total_obs", "sum"),
            n_high_cloudprob=("flag_high_cloudprob", "sum"),
            n_class_rule_high=("flag_class_rule_high", "sum"),
            n_class_rule_medium=("flag_class_rule_medium", "sum"),
            n_rare_spectral_value=("flag_rare_spectral_value", "sum"),
            n_context_thematic_conflict=("flag_context_thematic_conflict", "sum"),
            n_spectral_class_review=("flag_spectral_class_review", "sum"),
            n_spectral_priority=("flag_spectral_priority", "sum"),
            n_alert_high=(
                "spectral_alert_level",
                lambda s: int(s.isin(["alta", "alta_sin_datos"]).sum()),
            ),
            n_alert_medium=(
                "spectral_alert_level",
                lambda s: int((s == "media").sum()),
            ),
            n_alert_low=(
                "spectral_alert_level",
                lambda s: int((s == "baja").sum()),
            ),
            n_alert_none=(
                "spectral_alert_level",
                lambda s: int((s == "sin_alerta").sum()),
            ),
        )
        .reset_index()
    )

    out["pct_no_spectral_data"] = (out["n_no_spectral_data"] / out["n_records"] * 100).round(3)
    out["pct_low_months_obs"] = (out["n_low_months_obs"] / out["n_records"] * 100).round(3)
    out["pct_class_rule_high"] = (out["n_class_rule_high"] / out["n_records"] * 100).round(3)
    out["pct_class_rule_medium"] = (out["n_class_rule_medium"] / out["n_records"] * 100).round(3)
    out["pct_rare_spectral_value"] = (out["n_rare_spectral_value"] / out["n_records"] * 100).round(3)
    out["pct_spectral_class_review"] = (out["n_spectral_class_review"] / out["n_records"] * 100).round(3)
    out["pct_spectral_priority"] = (out["n_spectral_priority"] / out["n_records"] * 100).round(3)
    out["pct_alert_medium_high"] = (
        (out["n_alert_high"] + out["n_alert_medium"]) / out["n_records"] * 100
    ).round(3)

    out["class_priority_level"] = np.select(
        [
            out["pct_no_spectral_data"] >= HIGH_GAP_PCT,
            out["pct_class_rule_high"] >= HIGH_ALERT_PCT,
            out["pct_rare_spectral_value"] >= HIGH_RARE_PCT,
            out["pct_alert_medium_high"] >= HIGH_ALERT_PCT,
            out["pct_spectral_class_review"] >= HIGH_ALERT_PCT,
        ],
        [
            "alta_vacios_satelitales",
            "alta_reglas_clase",
            "alta_valores_espectrales_raros",
            "alta_alertas",
            "media_revision",
        ],
        default="baja_sin_prioridad",
    )

    return out.sort_values(
        [
            "pct_spectral_priority",
            "pct_spectral_class_review",
            "pct_rare_spectral_value",
            "pct_no_spectral_data",
            "n_records",
        ],
        ascending=[False, False, False, False, False],
    )


def make_audit_summary(
    input_gpkg: Path,
    output_gpkg: Path,
    audit_original: gpd.GeoDataFrame,
    audit_units: gpd.GeoDataFrame,
    priority_original: gpd.GeoDataFrame,
    priority_units: gpd.GeoDataFrame,
    rare_records: gpd.GeoDataFrame,
    low_availability: gpd.GeoDataFrame,
    class_audit_original: pd.DataFrame,
    class_audit_units: pd.DataFrame,
) -> pd.DataFrame:
    n_original = len(audit_original)
    n_units = len(audit_units)

    return pd.DataFrame(
        [
            {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source_name": SOURCE_NAME,
                "source_code": SOURCE_CODE,
                "source_id_expected": SOURCE_ID_EXPECTED,
                "country_code_expected": COUNTRY_CODE_EXPECTED,
                "year_ref_expected": YEAR_REF_EXPECTED,
                "input_gpkg": str(input_gpkg),
                "input_layer_original_annual": INPUT_LAYER_ORIGINAL_ANNUAL,
                "input_layer_units_annual": INPUT_LAYER_UNITS_ANNUAL,
                "output_gpkg": str(output_gpkg),
                "n_original_records": int(n_original),
                "n_extract_units": int(n_units),
                "n_priority_original_records": int(len(priority_original)),
                "pct_priority_original_records": pct(len(priority_original), n_original),
                "n_priority_extract_units": int(len(priority_units)),
                "pct_priority_extract_units": pct(len(priority_units), n_units),
                "n_rare_spectral_records": int(len(rare_records)),
                "pct_rare_spectral_records": pct(len(rare_records), n_original),
                "n_low_availability_records": int(len(low_availability)),
                "pct_low_availability_records": pct(len(low_availability), n_original),
                "n_class_audit_original_rows": int(len(class_audit_original)),
                "n_class_audit_units_rows": int(len(class_audit_units)),
                "min_valid_months": MIN_VALID_MONTHS,
                "min_total_obs": MIN_TOTAL_OBS,
                "cloud_prob_high": CLOUD_PROB_HIGH,
                "min_group_size_for_rareness": MIN_GROUP_SIZE_FOR_RARENESS,
                "iqr_factor": IQR_FACTOR,
            }
        ]
    )


def make_rule_parameters_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"parameter": "MIN_VALID_MONTHS", "value": MIN_VALID_MONTHS},
            {"parameter": "MIN_TOTAL_OBS", "value": MIN_TOTAL_OBS},
            {"parameter": "CLOUD_PROB_HIGH", "value": CLOUD_PROB_HIGH},
            {"parameter": "MIN_GROUP_SIZE_FOR_RARENESS", "value": MIN_GROUP_SIZE_FOR_RARENESS},
            {"parameter": "IQR_FACTOR", "value": IQR_FACTOR},
            {"parameter": "HIGH_GAP_PCT", "value": HIGH_GAP_PCT},
            {"parameter": "HIGH_RARE_PCT", "value": HIGH_RARE_PCT},
            {"parameter": "HIGH_ALERT_PCT", "value": HIGH_ALERT_PCT},
        ]
    )


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
# SALIDAS
# =============================================================================

def guardar_csvs(
    tables_dir: Path,
    audit_summary: pd.DataFrame,
    alert_original: pd.DataFrame,
    alert_units: pd.DataFrame,
    class_audit_original: pd.DataFrame,
    class_audit_units: pd.DataFrame,
    priority_original: gpd.GeoDataFrame,
    priority_units: gpd.GeoDataFrame,
    rare_records: gpd.GeoDataFrame,
    low_availability: gpd.GeoDataFrame,
    class_rules: pd.DataFrame,
    rule_parameters: pd.DataFrame,
    extract_theme_context: pd.DataFrame,
    xy_group_audit: gpd.GeoDataFrame,
) -> None:
    audit_summary.to_csv(tables_dir / AUDIT_SUMMARY_CSV_NAME, index=False, encoding="utf-8-sig")
    alert_original.to_csv(tables_dir / ALERT_DISTRIBUTION_ORIGINAL_CSV_NAME, index=False, encoding="utf-8-sig")
    alert_units.to_csv(tables_dir / ALERT_DISTRIBUTION_UNITS_CSV_NAME, index=False, encoding="utf-8-sig")
    class_audit_original.to_csv(tables_dir / CLASS_AUDIT_ORIGINAL_CSV_NAME, index=False, encoding="utf-8-sig")
    class_audit_units.to_csv(tables_dir / CLASS_AUDIT_UNITS_CSV_NAME, index=False, encoding="utf-8-sig")
    drop_geometry_for_csv(priority_original).to_csv(tables_dir / PRIORITY_ORIGINAL_CSV_NAME, index=False, encoding="utf-8-sig")
    drop_geometry_for_csv(priority_units).to_csv(tables_dir / PRIORITY_UNITS_CSV_NAME, index=False, encoding="utf-8-sig")
    drop_geometry_for_csv(rare_records).to_csv(tables_dir / RARE_RECORDS_CSV_NAME, index=False, encoding="utf-8-sig")
    drop_geometry_for_csv(low_availability).to_csv(tables_dir / LOW_AVAILABILITY_CSV_NAME, index=False, encoding="utf-8-sig")
    class_rules.to_csv(tables_dir / CLASS_RULES_CSV_NAME, index=False, encoding="utf-8-sig")
    rule_parameters.to_csv(tables_dir / RULE_PARAMETERS_CSV_NAME, index=False, encoding="utf-8-sig")
    extract_theme_context.to_csv(tables_dir / EXTRACT_THEME_CONTEXT_CSV_NAME, index=False, encoding="utf-8-sig")
    drop_geometry_for_csv(xy_group_audit).to_csv(tables_dir / XY_GROUP_AUDIT_CSV_NAME, index=False, encoding="utf-8-sig")


def guardar_gpkg(
    output_gpkg: Path,
    audit_original: gpd.GeoDataFrame,
    audit_units: gpd.GeoDataFrame,
    priority_original: gpd.GeoDataFrame,
    priority_units: gpd.GeoDataFrame,
    audit_summary: pd.DataFrame,
    alert_original: pd.DataFrame,
    alert_units: pd.DataFrame,
    class_audit_original: pd.DataFrame,
    class_audit_units: pd.DataFrame,
    rare_records: gpd.GeoDataFrame,
    low_availability: gpd.GeoDataFrame,
    class_rules: pd.DataFrame,
    rule_parameters: pd.DataFrame,
    extract_theme_context: pd.DataFrame,
    xy_group_audit: gpd.GeoDataFrame,
) -> None:
    if output_gpkg.exists():
        output_gpkg.unlink()

    clean_for_gpkg(audit_original).to_file(
        output_gpkg,
        layer=LAYER_AUDIT_ORIGINAL,
        driver="GPKG",
    )

    clean_for_gpkg(audit_units).to_file(
        output_gpkg,
        layer=LAYER_AUDIT_UNITS,
        driver="GPKG",
    )

    clean_for_gpkg(priority_original).to_file(
        output_gpkg,
        layer=LAYER_PRIORITY_ORIGINAL,
        driver="GPKG",
    )

    clean_for_gpkg(priority_units).to_file(
        output_gpkg,
        layer=LAYER_PRIORITY_UNITS,
        driver="GPKG",
    )

    if len(xy_group_audit) > 0:
        clean_for_gpkg(xy_group_audit).to_file(
            output_gpkg,
            layer=LAYER_XY_GROUP_AUDIT,
            driver="GPKG",
        )

    write_table_to_gpkg(audit_summary, output_gpkg, TABLE_AUDIT_SUMMARY)
    write_table_to_gpkg(alert_original, output_gpkg, TABLE_ALERT_DISTRIBUTION_ORIGINAL)
    write_table_to_gpkg(alert_units, output_gpkg, TABLE_ALERT_DISTRIBUTION_UNITS)
    write_table_to_gpkg(class_audit_original, output_gpkg, TABLE_CLASS_AUDIT_ORIGINAL)
    write_table_to_gpkg(class_audit_units, output_gpkg, TABLE_CLASS_AUDIT_UNITS)
    write_table_to_gpkg(drop_geometry_for_csv(rare_records), output_gpkg, TABLE_RARE_RECORDS)
    write_table_to_gpkg(drop_geometry_for_csv(low_availability), output_gpkg, TABLE_LOW_AVAILABILITY)
    write_table_to_gpkg(class_rules, output_gpkg, TABLE_CLASS_RULES)
    write_table_to_gpkg(rule_parameters, output_gpkg, TABLE_RULE_PARAMETERS)
    write_table_to_gpkg(extract_theme_context, output_gpkg, TABLE_EXTRACT_THEME_CONTEXT)
    write_table_to_gpkg(drop_geometry_for_csv(xy_group_audit), output_gpkg, TABLE_XY_GROUP_AUDIT)


def generar_reporte_markdown(
    report_path: Path,
    input_gpkg: Path,
    output_gpkg: Path,
    tables_dir: Path,
    audit_summary: pd.DataFrame,
    alert_original: pd.DataFrame,
    alert_units: pd.DataFrame,
    class_audit_original: pd.DataFrame,
    class_audit_units: pd.DataFrame,
    xy_group_audit: gpd.GeoDataFrame,
    class_rules: pd.DataFrame,
    rule_parameters: pd.DataFrame,
) -> None:
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    top_original = class_audit_original.head(30).copy()
    top_units = class_audit_units.head(30).copy()
    top_xy = drop_geometry_for_csv(
        xy_group_audit.sort_values(
            ["n_priority_records", "max_alert_rank", "n_records"],
            ascending=[False, False, False],
        ).head(30)
    ) if len(xy_group_audit) else pd.DataFrame()

    content = "\n".join(
        [
            "# Auditoría espectral preliminar por clase - SINAC SRC10 2021",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## Propósito",
            "",
            "Este reporte resume la auditoría espectral preliminar aplicada a los registros SINAC SRC10 2021 con valores anuales Sentinel-2 SR.",
            "",
            "La auditoría identifica vacíos satelitales, baja disponibilidad, valores espectrales raros y señales potencialmente inconsistentes con la clase temática.",
            "",
            "Los resultados son alertas exploratorias y no constituyen validación temática definitiva.",
            "",
            "## Entradas principales",
            "",
            "| Insumo | Ruta / valor |",
            "|---|---|",
            f"| GeoPackage de entrada | `{fmt_path(input_gpkg)}` |",
            f"| Capa registros originales anual | `{INPUT_LAYER_ORIGINAL_ANNUAL}` |",
            f"| Capa unidades sin duplicados anual | `{INPUT_LAYER_UNITS_ANNUAL}` |",
            "",
            "## Salidas principales",
            "",
            "| Producto | Ruta |",
            "|---|---|",
            f"| GeoPackage de auditoría | `{fmt_path(output_gpkg)}` |",
            f"| Tablas CSV | `{fmt_path(tables_dir)}` |",
            f"| Reporte Markdown | `{fmt_path(report_path)}` |",
            "",
            "## Resumen general",
            "",
            dataframe_to_markdown(audit_summary),
            "",
            "## Distribución de alertas - registros originales",
            "",
            dataframe_to_markdown(alert_original),
            "",
            "## Distribución de alertas - unidades únicas de extracción",
            "",
            dataframe_to_markdown(alert_units),
            "",
            "## Principales clases priorizadas - registros originales",
            "",
            dataframe_to_markdown(top_original),
            "",
            "## Principales clases priorizadas - unidades únicas de extracción",
            "",
            dataframe_to_markdown(top_units),
            "",
            "## Principales grupos XY priorizados",
            "",
            dataframe_to_markdown(top_xy),
            "",
            "## Reglas temático-espectrales por clase",
            "",
            dataframe_to_markdown(class_rules),
            "",
            "## Parámetros usados",
            "",
            dataframe_to_markdown(rule_parameters),
            "",
            "## Interpretación de banderas principales",
            "",
            "| Campo | Interpretación |",
            "|---|---|",
            "| flag_no_spectral_data | No hay evidencia espectral útil o no hay meses observados. |",
            "| flag_low_months_obs | La unidad tiene menos meses válidos que el umbral mínimo. |",
            "| flag_low_total_obs | El total anual de observaciones limpias es bajo. |",
            "| flag_high_cloudprob | La probabilidad mediana anual de nube es alta. |",
            "| flag_class_rule_high | La clase activa una regla espectral fuerte. |",
            "| flag_class_rule_medium | La clase activa una regla espectral moderada. |",
            "| flag_rare_spectral_value | NDVI o NDRE es raro respecto a su clase, país y año. |",
            "| flag_context_thematic_conflict | Hay más de una clase o gran clase asociada al mismo extract_id. |",
            "| spectral_alert_count | Número total de banderas activadas. |",
            "| spectral_alert_level | Nivel sintético de prioridad de revisión. |",
            "| main_alert_reason | Razón principal de la alerta. |",
            "| recommended_action | Acción sugerida para revisión posterior. |",
            "| xy_group_id | Grupo espacial estable generado para nuevas fuentes. |",
            "",
            "## Nota metodológica",
            "",
            "El bosque maduro y el bosque secundario usan la misma regla de coherencia espectral. El bosque secundario deciduo conserva una regla más conservadora por estacionalidad. Manglar y humedal palustre se tratan como clases mixtas con cautela por mezcla agua-vegetación y borde a 20 m.",
            "",
            "La rareza espectral se calcula por país, año y clase usando IQR cuando el grupo tiene tamaño suficiente.",
            "",
        ]
    )

    report_path.write_text(content, encoding="utf-8")


# =============================================================================
# CLI / MAIN
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ejecuta una auditoría espectral preliminar por clase para "
            "SINAC SRC10 2021 usando el GPKG unido con Sentinel-2 SR."
        )
    )

    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Ruta al GeoPackage de entrada sinac_src10_2021_s2sr_join_outputs.gpkg.",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(OUTPUT_DIR_REL),
        help="Carpeta de salida para el GeoPackage de auditoría.",
    )

    parser.add_argument(
        "--tables-dir",
        type=str,
        default=str(TABLES_DIR_REL),
        help="Carpeta de salida para tablas CSV.",
    )

    parser.add_argument(
        "--reports-dir",
        type=str,
        default=str(REPORTS_DIR_REL),
        help="Carpeta de salida para reporte Markdown.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_gpkg = resolve_path(args.input) if args.input else resolve_default_input()
    output_dir = resolve_path(args.output_dir)
    tables_dir = resolve_path(args.tables_dir)
    reports_dir = resolve_path(args.reports_dir)

    assert output_dir is not None
    assert tables_dir is not None
    assert reports_dir is not None

    output_gpkg = output_dir / OUTPUT_GPKG_NAME
    report_md = reports_dir / REPORT_MD_NAME

    crear_carpetas(output_dir, tables_dir, reports_dir)

    print("============================================================")
    print("PGBM - Auditoría espectral por clase - SINAC SRC10 2021")
    print("============================================================")
    print("Input GPKG:", input_gpkg)
    print("Output GPKG:", output_gpkg)
    print("Tables dir:", tables_dir)
    print("Reports dir:", reports_dir)
    print("============================================================")

    print("\nCargando capas de entrada...")
    original_annual = cargar_capa(input_gpkg, INPUT_LAYER_ORIGINAL_ANNUAL)
    units_annual = cargar_capa(input_gpkg, INPUT_LAYER_UNITS_ANNUAL)

    print("Registros originales anual:", len(original_annual))
    print("Unidades extract_id anual:", len(units_annual))

    print("\nCalculando contexto temático por extract_id...")
    extract_theme_context = compute_extract_theme_context(original_annual)

    original_annual_ctx = merge_theme_context(original_annual, extract_theme_context)
    units_annual_ctx = merge_theme_context(units_annual, extract_theme_context)

    print("Unidades con conflicto temático contextual:", int(extract_theme_context["flag_context_thematic_conflict"].sum()))
    print("Unidades con múltiples registros:", int(extract_theme_context["flag_context_multiple_records_extract_unit"].sum()))

    print("\nConstruyendo auditoría por registro original...")
    audit_original = build_spectral_audit(original_annual_ctx)

    print("Construyendo auditoría por unidad única de extracción...")
    audit_units = build_spectral_audit(units_annual_ctx)

    print("\nConstruyendo capas de prioridad...")
    priority_original = audit_original[audit_original["flag_spectral_priority"] == 1].copy()
    priority_units = audit_units[audit_units["flag_spectral_priority"] == 1].copy()

    rare_records = audit_original[audit_original["flag_rare_spectral_value"] == 1].copy()
    low_availability = audit_original[
        (audit_original["flag_no_spectral_data"] == 1)
        | (audit_original["flag_low_months_obs"] == 1)
        | (audit_original["flag_low_total_obs"] == 1)
    ].copy()

    print("Registros prioritarios:", len(priority_original))
    print("Unidades prioritarias:", len(priority_units))
    print("Registros con rareza espectral:", len(rare_records))
    print("Registros con baja disponibilidad:", len(low_availability))

    print("\nConstruyendo resúmenes...")
    alert_original = make_alert_distribution(audit_original)
    alert_units = make_alert_distribution(audit_units)
    class_audit_original = make_class_spectral_audit(audit_original)
    class_audit_units = make_class_spectral_audit(audit_units)
    xy_group_audit = make_xy_group_spectral_audit(audit_original)
    print("Grupos XY auditados:", len(xy_group_audit))
    class_rules = pd.DataFrame(SINAC_CLASS_RULES)
    rule_parameters = make_rule_parameters_table()

    audit_summary = make_audit_summary(
        input_gpkg=input_gpkg,
        output_gpkg=output_gpkg,
        audit_original=audit_original,
        audit_units=audit_units,
        priority_original=priority_original,
        priority_units=priority_units,
        rare_records=rare_records,
        low_availability=low_availability,
        class_audit_original=class_audit_original,
        class_audit_units=class_audit_units,
    )

    print("\nGuardando CSV...")
    guardar_csvs(
        tables_dir=tables_dir,
        audit_summary=audit_summary,
        alert_original=alert_original,
        alert_units=alert_units,
        class_audit_original=class_audit_original,
        class_audit_units=class_audit_units,
        priority_original=priority_original,
        priority_units=priority_units,
        rare_records=rare_records,
        low_availability=low_availability,
        class_rules=class_rules,
        rule_parameters=rule_parameters,
        extract_theme_context=extract_theme_context,
        xy_group_audit=xy_group_audit,
    )

    print("Guardando GeoPackage...")
    guardar_gpkg(
        output_gpkg=output_gpkg,
        audit_original=audit_original,
        audit_units=audit_units,
        priority_original=priority_original,
        priority_units=priority_units,
        audit_summary=audit_summary,
        alert_original=alert_original,
        alert_units=alert_units,
        class_audit_original=class_audit_original,
        class_audit_units=class_audit_units,
        rare_records=rare_records,
        low_availability=low_availability,
        class_rules=class_rules,
        rule_parameters=rule_parameters,
        extract_theme_context=extract_theme_context,
        xy_group_audit=xy_group_audit,
    )

    print("Generando reporte Markdown...")
    generar_reporte_markdown(
        report_path=report_md,
        input_gpkg=input_gpkg,
        output_gpkg=output_gpkg,
        tables_dir=tables_dir,
        audit_summary=audit_summary,
        alert_original=alert_original,
        alert_units=alert_units,
        class_audit_original=class_audit_original,
        class_audit_units=class_audit_units,
        xy_group_audit=xy_group_audit,
        class_rules=class_rules,
        rule_parameters=rule_parameters,
    )

    print("\n============================================================")
    print("AUDITORÍA FINALIZADA")
    print("============================================================")
    print("Registros originales auditados:", len(audit_original))
    print("Unidades únicas auditadas:", len(audit_units))
    print("Registros prioritarios:", len(priority_original))
    print("Unidades prioritarias:", len(priority_units))
    print("Grupos XY auditados:", len(xy_group_audit))
    print("Registros con rareza espectral:", len(rare_records))
    print("Registros con baja disponibilidad:", len(low_availability))
    print("Salida GPKG:", output_gpkg)
    print("Tablas:", tables_dir)
    print("Reporte:", report_md)
    print("============================================================")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
