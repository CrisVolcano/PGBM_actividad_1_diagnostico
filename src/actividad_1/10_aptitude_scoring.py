
from __future__ import annotations

"""
Módulo 10 - Scoring multicriterio de aptitud y preparación de categorías de uso.

Este script integra la auditoría temática/espacial previa con la auditoría
espectral anual de Sentinel-2 SR generada por el Módulo 09.

La unidad principal de decisión es `xy_group_id`.

Decisiones metodológicas principales:
- El componente espectral se lee desde `audit_extract_units_s2sr_annual`.
- Esa capa está sin duplicados por `extract_id`; esto evita contar dos veces
  la misma señal espectral, pero no elimina observaciones de años distintos.
- El score final combina criterios temporal, espacial, temático, espectral,
  confiabilidad, representatividad y fuente.
- Las categorías de salida se nombran directamente con la lógica de uso para
  la Actividad 1.8: entrenamiento, validación, prueba, apoyo interpretativo,
  máscaras y referencia contextual.
- Si existen salidas antiguas o incompatibles, el pipeline se recalcula
  automáticamente y sobrescribe los resultados.
"""


# NOTA: aún debo revisar todo el pydocstring. 

import argparse
import re
import sqlite3
import traceback
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml


# =============================================================================
# PGBM - Etapa 1.7 / Módulo 10
# Scoring multicriterio de aptitud preliminar
# =============================================================================
#
# Corrección principal de esta versión:
#   - El componente espectral NO se une por source_rowid.
#   - El componente espectral se lee desde el Módulo 09, capa SIN duplicados:
#
#       data/processed/s2_sr_spectral_class_audit/
#       └─ s2sr_spectral_class_audit_outputs.gpkg
#          layer = audit_extract_units_s2sr_annual
#
#   - La capa espectral se agrega por xy_group_id.
#   - El scoring final trabaja en la unidad principal del flujo: xy_group_id.
#
# Esto evita el error anterior donde se leía audit_original_records_s2sr_annual
# y se intentaba hacer join por source_rowid, produciendo muchos registros
# sin unión espectral.
# =============================================================================


ROOT = Path(__file__).resolve().parents[1]

CONFIG = ROOT / "config" / "scoring_aptitud.yaml"
DEFAULT_SOURCE_CATALOG = ROOT / "config" / "source_catalog.csv"

DB = ROOT / "data" / "interim" / "05_thematic_audit.sqlite"
SCORING_DB = ROOT / "data" / "interim" / "10_scoring_aptitud.sqlite"

OUT = ROOT / "outputs" / "tables"
REP = ROOT / "outputs" / "reports"
LOG = ROOT / "logs"

PROCESSED_SCORING = ROOT / "data" / "processed" / "scoring_aptitud"
SCORING_GPKG = PROCESSED_SCORING / "10_scoring_aptitud_outputs.gpkg"

SPECTRAL_AUDIT_GPKG = (
    ROOT
    / "data"
    / "processed"
    / "s2_sr_spectral_class_audit"
    / "s2sr_spectral_class_audit_outputs.gpkg"
)

# Capa correcta para el scoring: sin duplicados por extract_id.
SPECTRAL_AUDIT_LAYER = "audit_extract_units_s2sr_annual"

STRICT_SPECTRAL_COVERAGE_DEFAULT = True

# -----------------------------------------------------------------------------
# Control de ejecución
# -----------------------------------------------------------------------------
# TRUE/FALSE de control:
#   False = si las salidas principales ya existen, NO recalcula el pipeline pesado;
#           solo lee los CSV existentes y regenera el Markdown completo.
#   True  = recalcula todo y sobrescribe las salidas.
#
# También puede cambiarse desde la terminal con:
#   --recreate-outputs true
#   --recreate-outputs false
RECREATE_OUTPUTS_DEFAULT = True
CLEAN_OUTPUTS_BEFORE_RECREATE_DEFAULT = True

MASTER_CSV = OUT / "10_xy_group_aptitude_master.csv"
SOURCE_RANKING_CSV = OUT / "10_source_aptitude_ranking.csv"
RECORD_FLAGS_CSV = OUT / "10_record_aptitude_flags.csv"
GAP_PRIORITY_CSV = OUT / "10_gap_priority_country_class.csv"
REVIEW_CASES_CSV = OUT / "10_review_priority_cases.csv"
SCENARIOS_CSV = OUT / "10_selection_scenarios_summary.csv"
AUDIT_SUMMARY_CSV = OUT / "10_scoring_audit_summary.csv"
REPORT_MD = REP / "10_scoring_multicriterio_aptitud.md"

# Versión de trazabilidad del componente de confiabilidad. Se guarda en la
# auditoría para impedir que resultados antiguos, sin distinción entre valores
# observados e imputados, se reutilicen como si fueran actuales.
CONFIDENCE_PIPELINE_VERSION = "2.0-observed-vs-imputed"
DEFAULT_CONFIDENCE_NEUTRAL_SCORE = 70.0

# El score de fuente se calcula antes del score XY desde un catálogo documental
# y nunca se sustituye silenciosamente por un valor neutral.
SOURCE_PIPELINE_VERSION = "1.0-documented-catalog-unique-source-per-xy"


# =============================================================================
# UTILIDADES GENERALES
# =============================================================================

def mkdirs() -> None:
    for p in [OUT, REP, LOG, SCORING_DB.parent, PROCESSED_SCORING]:
        p.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    mkdirs()
    with open(LOG / "auditoria.log", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def load_cfg(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def q(x: str) -> str:
    return '"' + x.replace('"', '""') + '"'


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    )


def cols(conn: sqlite3.Connection, table: str) -> list[str]:
    return pd.read_sql_query(f"PRAGMA table_info({q(table)})", conn)["name"].tolist()


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    return df


def mode(s: pd.Series) -> str:
    vals = [str(x) for x in s.dropna().tolist() if str(x).strip()]
    return Counter(vals).most_common(1)[0][0] if vals else ""


def map_score(x: Any, mapping: dict[str, Any], default: float = 70.0) -> float:
    if pd.isna(x):
        return default

    sx = str(x)

    if sx in mapping:
        return float(mapping[sx])

    for k, v in mapping.items():
        if str(k).lower() == sx.lower():
            return float(v)

    return default


def confidence_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    section = cfg.get("confidence", {}) or {}
    neutral = float(section.get("neutral_score", DEFAULT_CONFIDENCE_NEUTRAL_SCORE))
    if not 0 <= neutral <= 100:
        raise ValueError(
            f"confidence.neutral_score debe estar entre 0 y 100; recibido={neutral}"
        )

    input_scale = str(section.get("input_scale", "auto")).strip().lower()
    aliases = {
        "auto": "auto",
        "0_1": "0_1",
        "0-1": "0_1",
        "01": "0_1",
        "0_100": "0_100",
        "0-100": "0_100",
        "0100": "0_100",
    }
    if input_scale not in aliases:
        raise ValueError(
            "confidence.input_scale debe ser auto, 0_1 o 0_100; "
            f"recibido={input_scale!r}"
        )

    max_imputed_xy_pct = float(section.get("max_imputed_xy_pct", 100.0))
    if not 0 <= max_imputed_xy_pct <= 100:
        raise ValueError(
            "confidence.max_imputed_xy_pct debe estar entre 0 y 100; "
            f"recibido={max_imputed_xy_pct}"
        )

    return {
        "neutral_score": neutral,
        "input_scale": aliases[input_scale],
        "max_imputed_xy_pct": max_imputed_xy_pct,
    }


def prepare_confidence_records(
    records: pd.DataFrame,
    cfg: dict[str, Any],
    *,
    allow_missing: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Normaliza conf_integrada y conserva trazabilidad observada/imputada."""
    rec = records.copy()
    settings = confidence_settings(cfg)

    if "conf_integrada" not in rec.columns:
        if not allow_missing:
            raise ValueError(
                "thematic_base no contiene conf_integrada. Ejecute primero "
                "thematic_audit.py; la ejecución se detiene para evitar que "
                "todos los grupos reciban 70 silenciosamente."
            )
        rec["conf_integrada"] = np.nan

    raw = rec["conf_integrada"]
    raw_non_empty = raw.notna() & raw.astype("string").str.strip().ne("")
    numeric = pd.to_numeric(raw, errors="coerce")
    invalid = raw_non_empty & numeric.isna()

    if invalid.any():
        examples = raw.loc[invalid].astype(str).drop_duplicates().head(10).tolist()
        raise ValueError(
            f"conf_integrada contiene {int(invalid.sum())} valores no numéricos. "
            f"Ejemplos: {examples}"
        )

    observed = numeric.dropna()
    n_observed = int(observed.size)

    if n_observed == 0 and not allow_missing:
        raise ValueError(
            "No existe ningún valor observado de conf_integrada en la ventana. "
            "La ejecución se detiene para evitar imputar 70 a todos los grupos. "
            "Use --allow-missing-confidence solo si la ausencia es intencional."
        )

    detected_scale = "sin_datos"
    normalized = numeric.astype(float)

    if n_observed:
        min_value = float(observed.min())
        max_value = float(observed.max())
        requested_scale = settings["input_scale"]

        if min_value < 0 or max_value > 100:
            raise ValueError(
                "conf_integrada está fuera del rango permitido: "
                f"min={min_value}, max={max_value}. Se acepta 0-1 o 0-100."
            )

        if requested_scale == "auto":
            detected_scale = "0_1" if max_value <= 1.0 + 1e-9 else "0_100"
        else:
            detected_scale = requested_scale

        if detected_scale == "0_1":
            if max_value > 1.0 + 1e-9:
                raise ValueError(
                    "confidence.input_scale=0_1, pero conf_integrada contiene "
                    f"valores mayores que 1 (max={max_value})."
                )
            normalized = numeric * 100.0
        else:
            if max_value > 100:
                raise ValueError(
                    "confidence.input_scale=0_100, pero existen valores mayores "
                    f"que 100 (max={max_value})."
                )
            normalized = numeric.astype(float)

    normalized = normalized.clip(0, 100)
    rec["conf_integrada_score_observado"] = normalized
    rec["conf_integrada_observada"] = normalized.notna().astype("int8")

    meta = {
        "confidence_pipeline_version": CONFIDENCE_PIPELINE_VERSION,
        "confidence_input_scale_config": settings["input_scale"],
        "confidence_scale_detected": detected_scale,
        "confidence_neutral_score": settings["neutral_score"],
        "n_records_confidence_observed": n_observed,
        "n_records_confidence_missing": int(len(rec) - n_observed),
        "pct_records_confidence_observed": round(
            100.0 * n_observed / len(rec) if len(rec) else 0.0,
            6,
        ),
        "n_confidence_distinct_observed": int(normalized.dropna().nunique()),
        "confidence_observed_min": (
            round(float(normalized.dropna().min()), 6) if n_observed else np.nan
        ),
        "confidence_observed_max": (
            round(float(normalized.dropna().max()), 6) if n_observed else np.nan
        ),
    }

    print(
        "Confiabilidad observada:",
        f"registros={n_observed:,}/{len(rec):,};",
        f"cobertura={meta['pct_records_confidence_observed']:.3f}%;",
        f"escala={detected_scale};",
        f"valores_distintos={meta['n_confidence_distinct_observed']}",
    )

    return rec, meta


def validate_confidence_master(
    master: pd.DataFrame,
    cfg: dict[str, Any],
    *,
    allow_missing: bool,
) -> dict[str, Any]:
    required = [
        "n_conf_integrada_observada",
        "pct_conf_integrada_observada",
        "conf_integrada_promedio_observada",
        "score_confiabilidad_base",
        "flag_confianza_imputada",
        "origen_score_confiabilidad",
    ]
    missing = [c for c in required if c not in master.columns]
    if missing:
        raise ValueError(
            f"Faltan columnas de trazabilidad de confiabilidad en master: {missing}"
        )

    base_score = pd.to_numeric(master["score_confiabilidad_base"], errors="coerce")
    if base_score.isna().any():
        n = int(base_score.isna().sum())
        raise ValueError(
            f"Hay {n} grupos XY sin score_confiabilidad_base después de la unión. "
            "Esto indica grupos sin registros asociados o una agregación incompleta."
        )

    imputed = pd.to_numeric(
        master["flag_confianza_imputada"], errors="coerce"
    ).fillna(1).eq(1)
    n_total = int(len(master))
    n_imputed = int(imputed.sum())
    n_observed = n_total - n_imputed

    pct_imputed = 100.0 * n_imputed / n_total if n_total else 0.0
    settings = confidence_settings(cfg)

    if n_observed == 0 and not allow_missing:
        raise ValueError(
            "Todos los grupos XY quedaron con confiabilidad neutral imputada. "
            "La ejecución se detiene para evitar publicar un score constante como "
            "si fuera confiabilidad observada."
        )

    if (
        pct_imputed > settings["max_imputed_xy_pct"]
        and not allow_missing
    ):
        raise ValueError(
            "La imputación de confiabilidad supera el máximo permitido: "
            f"{pct_imputed:.3f}% > "
            f"{settings['max_imputed_xy_pct']:.3f}%. "
            "Ajuste confidence.max_imputed_xy_pct solo si este nivel de ausencia "
            "es metodológicamente aceptable."
        )

    return {
        "n_xy_confidence_observed": n_observed,
        "n_xy_confidence_imputed": n_imputed,
        "pct_xy_confidence_observed": round(
            100.0 * n_observed / n_total if n_total else 0.0, 6
        ),
        "pct_xy_confidence_imputed": round(pct_imputed, 6),
        "max_imputed_xy_pct_allowed": settings["max_imputed_xy_pct"],
    }


def _normalize_text_key(value: Any) -> str:
    """Normaliza texto para controles de correspondencia, no para reemplazar el original."""
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*[-–—]\s*", "-", text)
    return text


def _normalize_source_id(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except (TypeError, ValueError):
        pass
    return text


def _parse_allowed_years(value: Any) -> set[int]:
    if pd.isna(value):
        return set()
    years: set[int] = set()
    for token in re.split(r"[|,;\s]+", str(value).strip()):
        if not token:
            continue
        try:
            years.add(int(float(token)))
        except ValueError as exc:
            raise ValueError(
                f"Año inválido en source_catalog.csv: {token!r} dentro de {value!r}"
            ) from exc
    return years


def source_quality_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    section = cfg.get("source_quality", {}) or {}
    catalog_value = section.get("catalog_file", "config/source_catalog.csv")
    catalog_path = Path(str(catalog_value))
    if not catalog_path.is_absolute():
        catalog_path = ROOT / catalog_path

    weights = {
        "directness": 0.50,
        "traceability": 0.25,
        "temporal_metadata": 0.25,
        **(section.get("weights", {}) or {}),
    }
    weights = {k: float(v) for k, v in weights.items()}
    required_weight_keys = {"directness", "traceability", "temporal_metadata"}
    missing = sorted(required_weight_keys - set(weights))
    if missing:
        raise ValueError(f"Faltan pesos de source_quality: {missing}")
    total = sum(weights[k] for k in required_weight_keys)
    if not np.isclose(total, 1.0, atol=1e-9):
        raise ValueError(
            "Los pesos de source_quality deben sumar 1.0; "
            f"recibido={total:.12f}"
        )
    if any(weights[k] < 0 for k in required_weight_keys):
        raise ValueError("Los pesos de source_quality no pueden ser negativos.")

    return {
        "catalog_path": catalog_path,
        "weights": weights,
        "fail_on_type_mismatch": bool(section.get("fail_on_type_mismatch", True)),
        "fail_on_uncatalogued_source": bool(
            section.get("fail_on_uncatalogued_source", True)
        ),
        "min_distinct_xy_scores": int(section.get("min_distinct_xy_scores", 2)),
    }


def load_source_catalog(cfg: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    settings = source_quality_settings(cfg)
    path: Path = settings["catalog_path"]
    if not path.exists():
        raise FileNotFoundError(
            f"No existe el catálogo de fuentes requerido: {path}. "
            "Copie source_catalog.csv dentro de config/."
        )

    catalog = pd.read_csv(path, dtype="string", encoding="utf-8-sig")
    catalog = clean_columns(catalog)
    required = [
        "id_fuente",
        "fuente_reporte",
        "medio_obtencion",
        "tipo_documentado",
        "restriccion_uso",
        "anios_documentados",
        "anios_permitidos",
        "pais_documentado",
        "observaciones",
        "clase_trazabilidad",
        "score_directitud",
        "score_trazabilidad",
    ]
    missing = [c for c in required if c not in catalog.columns]
    if missing:
        raise ValueError(f"source_catalog.csv no contiene columnas requeridas: {missing}")

    catalog["id_fuente"] = catalog["id_fuente"].map(_normalize_source_id)
    if catalog["id_fuente"].eq("").any():
        raise ValueError("source_catalog.csv contiene id_fuente vacío.")
    duplicated = catalog[catalog["id_fuente"].duplicated(keep=False)]
    if not duplicated.empty:
        raise ValueError(
            "source_catalog.csv contiene id_fuente duplicados: "
            + ", ".join(sorted(duplicated["id_fuente"].unique().tolist()))
        )

    for col in ["score_directitud", "score_trazabilidad"]:
        catalog[col] = pd.to_numeric(catalog[col], errors="coerce")
        if catalog[col].isna().any():
            bad = catalog.loc[catalog[col].isna(), "id_fuente"].tolist()
            raise ValueError(f"{col} no numérico para id_fuente={bad}")
        if (~catalog[col].between(0, 100)).any():
            bad = catalog.loc[~catalog[col].between(0, 100), ["id_fuente", col]]
            raise ValueError(f"{col} fuera de 0-100: {bad.to_dict('records')}")

    catalog["_allowed_years"] = catalog["anios_permitidos"].map(_parse_allowed_years)
    if catalog["_allowed_years"].map(len).eq(0).any():
        bad = catalog.loc[catalog["_allowed_years"].map(len).eq(0), "id_fuente"].tolist()
        raise ValueError(f"Fuentes sin años documentados utilizables: {bad}")

    catalog["_fuente_key"] = catalog["fuente_reporte"].map(_normalize_text_key)
    catalog["_tipo_key"] = catalog["tipo_documentado"].map(_normalize_text_key)
    catalog["_pais_key"] = catalog["pais_documentado"].map(_normalize_text_key)

    meta = {
        "source_pipeline_version": SOURCE_PIPELINE_VERSION,
        "source_catalog_file": str(path.resolve()),
        "source_catalog_rows": int(len(catalog)),
        "source_catalog_unique_ids": int(catalog["id_fuente"].nunique()),
        "source_weight_directness": settings["weights"]["directness"],
        "source_weight_traceability": settings["weights"]["traceability"],
        "source_weight_temporal_metadata": settings["weights"]["temporal_metadata"],
    }
    return catalog, meta


def prepare_source_records(
    records: pd.DataFrame,
    cfg: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Une el catálogo y calcula un score previo por fuente sin circularidad."""
    required = [
        "id_fuente",
        "fuente",
        "tipo_fuente",
        "detalle_tipo_fuente",
        "id_origen",
        "anio",
        "pais",
    ]
    missing = [c for c in required if c not in records.columns]
    if missing:
        raise ValueError(
            "thematic_base no conserva todos los campos de fuente requeridos: "
            f"{missing}. Ejecute thematic_audit.py con la versión corregida."
        )

    settings = source_quality_settings(cfg)
    catalog, catalog_meta = load_source_catalog(cfg)
    rec = records.copy()
    rec["id_fuente"] = rec["id_fuente"].map(_normalize_source_id)
    if rec["id_fuente"].eq("").any():
        raise ValueError(
            f"Hay {int(rec['id_fuente'].eq('').sum())} registros sin id_fuente."
        )

    observed_ids = set(rec["id_fuente"].unique())
    catalog_ids = set(catalog["id_fuente"].unique())
    uncatalogued = sorted(observed_ids - catalog_ids)
    if uncatalogued and settings["fail_on_uncatalogued_source"]:
        raise ValueError(
            "Hay id_fuente sin documentar en source_catalog.csv: "
            + ", ".join(uncatalogued)
        )

    merge_cols = [
        "id_fuente",
        "fuente_reporte",
        "medio_obtencion",
        "tipo_documentado",
        "restriccion_uso",
        "anios_documentados",
        "anios_permitidos",
        "pais_documentado",
        "observaciones",
        "clase_trazabilidad",
        "score_directitud",
        "score_trazabilidad",
        "_allowed_years",
        "_fuente_key",
        "_tipo_key",
        "_pais_key",
    ]
    rec = rec.merge(
        catalog[merge_cols],
        on="id_fuente",
        how="left",
        validate="many_to_one",
    )

    if rec["score_directitud"].isna().any():
        missing_ids = sorted(rec.loc[rec["score_directitud"].isna(), "id_fuente"].unique())
        raise ValueError(f"Registros sin score de catálogo para id_fuente={missing_ids}")

    rec["_fuente_registro_key"] = rec["fuente"].map(_normalize_text_key)
    rec["_tipo_registro_key"] = rec["tipo_fuente"].map(_normalize_text_key)
    rec["_pais_registro_key"] = rec["pais"].map(_normalize_text_key)
    rec["flag_nombre_fuente_inconsistente"] = (
        rec["_fuente_registro_key"].ne(rec["_fuente_key"])
    ).astype("int8")
    rec["flag_tipo_fuente_inconsistente"] = (
        rec["_tipo_registro_key"].ne(rec["_tipo_key"])
    ).astype("int8")
    rec["flag_pais_fuente_inconsistente"] = (
        rec["_pais_registro_key"].ne(rec["_pais_key"])
    ).astype("int8")

    n_type_mismatch = int(rec["flag_tipo_fuente_inconsistente"].sum())
    if n_type_mismatch and settings["fail_on_type_mismatch"]:
        examples = (
            rec.loc[
                rec["flag_tipo_fuente_inconsistente"].eq(1),
                ["id_fuente", "tipo_fuente", "tipo_documentado"],
            ]
            .drop_duplicates()
            .head(20)
            .to_dict("records")
        )
        raise ValueError(
            f"Hay {n_type_mismatch:,} registros cuyo Tipo no coincide con el catálogo. "
            f"Ejemplos: {examples}"
        )

    rec["anio"] = pd.to_numeric(rec["anio"], errors="coerce").astype("Int64")
    rec["flag_anio_fuente_informado"] = rec["anio"].notna().astype("int8")
    rec["flag_anio_fuente_consistente"] = [
        int(pd.notna(year) and int(year) in allowed)
        for year, allowed in zip(rec["anio"], rec["_allowed_years"])
    ]

    temporal = (
        rec.groupby("id_fuente", dropna=False)
        .agg(
            n_registros_fuente=("source_rowid", "count"),
            n_anio_informado=("flag_anio_fuente_informado", "sum"),
            n_anio_consistente=("flag_anio_fuente_consistente", "sum"),
            n_nombre_inconsistente=("flag_nombre_fuente_inconsistente", "sum"),
            n_tipo_inconsistente=("flag_tipo_fuente_inconsistente", "sum"),
            n_pais_inconsistente=("flag_pais_fuente_inconsistente", "sum"),
        )
        .reset_index()
    )
    temporal["pct_anio_informado"] = (
        100.0 * temporal["n_anio_informado"] / temporal["n_registros_fuente"]
    ).round(6)
    temporal["pct_anio_consistente"] = np.where(
        temporal["n_anio_informado"].gt(0),
        100.0 * temporal["n_anio_consistente"] / temporal["n_anio_informado"],
        0.0,
    ).round(6)
    temporal["score_consistencia_temporal_fuente"] = (
        0.5 * temporal["pct_anio_informado"]
        + 0.5 * temporal["pct_anio_consistente"]
    ).round(3)

    source_profile = catalog.merge(temporal, on="id_fuente", how="inner", validate="one_to_one")
    w = settings["weights"]
    source_profile["score_fuente_base"] = (
        w["directness"] * source_profile["score_directitud"]
        + w["traceability"] * source_profile["score_trazabilidad"]
        + w["temporal_metadata"]
        * source_profile["score_consistencia_temporal_fuente"]
    ).round(3)
    source_profile["flag_fuente_anio_inconsistente"] = (
        source_profile["pct_anio_informado"].lt(100)
        | source_profile["pct_anio_consistente"].lt(100)
    ).astype("int8")
    source_profile["flag_fuente_pais_inconsistente"] = (
        source_profile["n_pais_inconsistente"].gt(0)
    ).astype("int8")

    profile_cols = [
        "id_fuente",
        "score_consistencia_temporal_fuente",
        "pct_anio_informado",
        "pct_anio_consistente",
        "score_fuente_base",
        "flag_fuente_anio_inconsistente",
        "flag_fuente_pais_inconsistente",
    ]
    rec = rec.merge(
        source_profile[profile_cols],
        on="id_fuente",
        how="left",
        validate="many_to_one",
    )
    if rec["score_fuente_base"].isna().any():
        raise ValueError("La unión del score de fuente dejó registros sin score_fuente_base.")

    meta = {
        **catalog_meta,
        "n_source_ids_observed": int(len(observed_ids)),
        "n_source_ids_uncatalogued": int(len(uncatalogued)),
        "source_ids_uncatalogued": "|".join(uncatalogued),
        "n_source_records_name_mismatch": int(rec["flag_nombre_fuente_inconsistente"].sum()),
        "n_source_records_type_mismatch": n_type_mismatch,
        "n_source_records_country_mismatch": int(rec["flag_pais_fuente_inconsistente"].sum()),
        "n_source_records_year_missing": int(rec["flag_anio_fuente_informado"].eq(0).sum()),
        "n_source_records_year_inconsistent": int((
            rec["flag_anio_fuente_informado"].eq(1)
            & rec["flag_anio_fuente_consistente"].eq(0)
        ).sum()),
        "n_source_scores_distinct": int(source_profile["score_fuente_base"].nunique()),
        "source_score_min": round(float(source_profile["score_fuente_base"].min()), 3),
        "source_score_max": round(float(source_profile["score_fuente_base"].max()), 3),
    }

    print(
        "Score de fuente previo:",
        f"fuentes={len(source_profile):,};",
        f"scores_distintos={meta['n_source_scores_distinct']:,};",
        f"rango={meta['source_score_min']}-{meta['source_score_max']};",
        f"años_inconsistentes={meta['n_source_records_year_inconsistent']:,}",
    )
    return rec, source_profile, meta


def validate_source_master(master: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    required = [
        "n_fuentes",
        "ids_fuente_presentes",
        "fuentes_presentes",
        "score_fuente_promedio",
        "score_fuente_minimo",
        "score_fuente_maximo",
    ]
    missing = [c for c in required if c not in master.columns]
    if missing:
        raise ValueError(f"Faltan columnas del componente fuente en master: {missing}")

    score = pd.to_numeric(master["score_fuente_promedio"], errors="coerce")
    if score.isna().any():
        raise ValueError(
            f"Hay {int(score.isna().sum())} grupos XY sin score_fuente_promedio."
        )
    if (~score.between(0, 100)).any():
        raise ValueError("score_fuente_promedio contiene valores fuera de 0-100.")

    settings = source_quality_settings(cfg)
    n_active_sources = int(
        master["ids_fuente_presentes"]
        .astype(str)
        .str.split("|")
        .explode()
        .replace("", np.nan)
        .dropna()
        .nunique()
    )
    n_distinct_scores = int(score.round(6).nunique())
    if (
        n_active_sources > 1
        and n_distinct_scores < settings["min_distinct_xy_scores"]
    ):
        raise ValueError(
            "El score de fuente volvió a quedar constante o casi constante: "
            f"fuentes_activas={n_active_sources}, scores_xy_distintos={n_distinct_scores}."
        )

    return {
        "n_xy_source_scored": int(score.notna().sum()),
        "pct_xy_source_scored": round(100.0 * score.notna().mean(), 6),
        "n_xy_source_scores_distinct": n_distinct_scores,
        "xy_source_score_min": round(float(score.min()), 3),
        "xy_source_score_max": round(float(score.max()), 3),
        "n_active_source_ids_in_xy": n_active_sources,
    }


def sev_order(x: Any) -> int:
    return {
        "sin_alerta": 0,
        "baja": 1,
        "media": 2,
        "alta": 3,
        "alta_sin_datos": 4,
    }.get(str(x).lower(), 0)


def sev_name(v: Any) -> str:
    try:
        iv = int(v)
    except Exception:
        iv = 0

    return {
        0: "sin_alerta",
        1: "baja",
        2: "media",
        3: "alta",
        4: "alta_sin_datos",
    }.get(iv, "sin_alerta")


def md(df: pd.DataFrame, n: int | None = None) -> str:
    d = df.head(n).copy() if n else df.copy()

    try:
        return d.to_markdown(index=False)
    except Exception:
        return "```text\n" + d.to_string(index=False) + "\n```"


def normalize_xy_join_fields(
    df: pd.DataFrame,
    lon_col: str = "lon",
    lat_col: str = "lat",
    ndigits: int = 7,
) -> pd.DataFrame:
    out = df.copy()
    out["_lon_join"] = pd.to_numeric(out[lon_col], errors="coerce").round(ndigits)
    out["_lat_join"] = pd.to_numeric(out[lat_col], errors="coerce").round(ndigits)
    return out


def existing(df: pd.DataFrame, names: list[str]) -> list[str]:
    return [c for c in names if c in df.columns]


def str_to_bool(value: Any) -> bool:
    """Parsea valores tipo true/false para controlar si se recalculan salidas."""
    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"true", "1", "yes", "y", "si", "sí"}:
        return True

    if text in {"false", "0", "no", "n"}:
        return False

    raise argparse.ArgumentTypeError(
        "Valor inválido. Use true o false."
    )


def usage_category_definitions() -> pd.DataFrame:
    """Define las categorías finales de salida y su homologación para Actividad 1.8."""
    return pd.DataFrame(
        [
            {
                "categoria_aptitud_preliminar": "datos_para_entrenamiento",
                "categoria_uso_actividad_1_8": "entrenamiento",
                "definición": "Datos con alta aptitud multicriterio, sin alertas severas ni conflictos que obliguen a revisión.",
                "uso_recomendado": "Usar como núcleo de entrenamiento, aplicando balance por país, clase y fuente.",
            },
            {
                "categoria_aptitud_preliminar": "datos_para_validacion",
                "categoria_uso_actividad_1_8": "validación",
                "definición": "Datos con aptitud buena pero no máxima; pueden tener alguna condición menor o menor fortaleza relativa.",
                "uso_recomendado": "Usar preferentemente para validación estratificada o como complemento controlado del entrenamiento.",
            },
            {
                "categoria_aptitud_preliminar": "datos_para_prueba",
                "categoria_uso_actividad_1_8": "prueba",
                "definición": "Datos útiles para evaluación o contraste, pero no recomendados como núcleo de entrenamiento.",
                "uso_recomendado": "Usar como conjunto de prueba o contraste, manteniendo independencia respecto al entrenamiento.",
            },
            {
                "categoria_aptitud_preliminar": "apoyo_interpretativo_espectral",
                "categoria_uso_actividad_1_8": "apoyo interpretativo",
                "definición": "Datos con alerta espectral fuerte o ausencia de datos espectrales que impide su uso directo como etiqueta supervisada.",
                "uso_recomendado": "Usar para revisión visual, interpretación o priorización; no usar directamente como entrenamiento, validación o prueba.",
            },
            {
                "categoria_aptitud_preliminar": "referencia_contextual_revision",
                "categoria_uso_actividad_1_8": "referencia contextual",
                "definición": "Datos con conflictos temáticos o espaciales que requieren revisión experta antes de cualquier uso supervisado.",
                "uso_recomendado": "Mantener como referencia contextual o cola de revisión experta.",
            },
            {
                "categoria_aptitud_preliminar": "referencia_contextual_temporal",
                "categoria_uso_actividad_1_8": "referencia contextual",
                "definición": "Datos cuya interpretación depende de trayectoria temporal o posible cambio real.",
                "uso_recomendado": "Usar como referencia contextual temporal o para análisis de cambio; revisar antes de etiquetar.",
            },
            {
                "categoria_aptitud_preliminar": "mascara_exclusion",
                "categoria_uso_actividad_1_8": "máscaras",
                "definición": "Datos no aptos para uso directo o sin registros representados válidos dentro de la ventana.",
                "uso_recomendado": "Usar como máscara de exclusión, control de calidad o lista de descarte.",
            },
        ]
    )


def usage_category_map() -> dict[str, str]:
    defs = usage_category_definitions()
    return dict(zip(defs["categoria_aptitud_preliminar"], defs["categoria_uso_actividad_1_8"]))


def usage_definition_map() -> dict[str, str]:
    defs = usage_category_definitions()
    return dict(zip(defs["categoria_aptitud_preliminar"], defs["definición"]))


def usage_action_map() -> dict[str, str]:
    defs = usage_category_definitions()
    return dict(zip(defs["categoria_aptitud_preliminar"], defs["uso_recomendado"]))


def source_usage_definitions() -> pd.DataFrame:
    """Define categorías de uso para fuentes completas."""
    return pd.DataFrame(
        [
            {
                "categoria_aptitud_fuente": "fuente_para_entrenamiento",
                "categoria_uso_fuente_actividad_1_8": "entrenamiento",
                "definición": "Fuente con alta aptitud agregada, buena compatibilidad con el pipeline y baja proporción de conflictos o alertas.",
                "uso_recomendado": "Priorizar para entrenamiento; si el volumen lo permite, derivar subconjuntos de validación/prueba estratificados.",
            },
            {
                "categoria_aptitud_fuente": "fuente_para_validacion_o_prueba",
                "categoria_uso_fuente_actividad_1_8": "validación / prueba",
                "definición": "Fuente útil pero condicionada por alguna debilidad espectral, temática, espacial o de representatividad.",
                "uso_recomendado": "Usar para validación o prueba; usar en entrenamiento solo si cubre vacíos específicos.",
            },
            {
                "categoria_aptitud_fuente": "fuente_de_apoyo_interpretativo",
                "categoria_uso_fuente_actividad_1_8": "apoyo interpretativo",
                "definición": "Fuente útil para interpretación o contraste, pero no suficientemente robusta como etiqueta núcleo.",
                "uso_recomendado": "Usar como apoyo interpretativo, revisión visual o priorización.",
            },
            {
                "categoria_aptitud_fuente": "fuente_de_referencia_contextual",
                "categoria_uso_fuente_actividad_1_8": "referencia contextual",
                "definición": "Fuente que requiere revisión o que sirve principalmente como referencia secundaria.",
                "uso_recomendado": "Mantener como referencia contextual hasta revisión adicional.",
            },
            {
                "categoria_aptitud_fuente": "fuente_para_mascara_o_exclusion",
                "categoria_uso_fuente_actividad_1_8": "máscaras",
                "definición": "Fuente no apta para uso directo como etiqueta.",
                "uso_recomendado": "Usar solo como máscara, exclusión o referencia auxiliar.",
            },
        ]
    )


def source_usage_map() -> dict[str, str]:
    defs = source_usage_definitions()
    return dict(zip(defs["categoria_aptitud_fuente"], defs["categoria_uso_fuente_actividad_1_8"]))


# =============================================================================
# LECTURA DE INSUMOS BASE
# =============================================================================

def read_base(conn: sqlite3.Connection, cfg: dict[str, Any]) -> pd.DataFrame:
    start = int(cfg["scoring"]["window_start"])
    end = int(cfg["scoring"]["window_end"])

    required = [
        "source_rowid",
        "lon",
        "lat",
        "anio",
        "pais",
        "id_fuente",
        "fuente",
        "tipo_fuente",
        "detalle_tipo_fuente",
        "id_origen",
        "nivel_0",
        "nivel_1",
        "nivel_2",
        "conf_integrada",
    ]

    available = cols(conn, "thematic_base")
    missing = [c for c in required if c not in available]

    if missing:
        raise ValueError(f"thematic_base no contiene columnas requeridas: {missing}")

    optional = [
        c
        for c in ["conf_ndvi", "conf_cobertura", "conf_altura"]
        if c in available
    ]

    selected = required + optional

    sql = (
        f"SELECT {', '.join(q(c) for c in selected)} "
        f"FROM thematic_base "
        f"WHERE anio BETWEEN {start} AND {end}"
    )

    df = pd.read_sql_query(sql, conn)

    if df.empty:
        raise ValueError(f"No hay registros dentro de {start}-{end}")

    df = clean_columns(df)
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int64")

    return df


def read_xy(conn: sqlite3.Connection, cfg: dict[str, Any]) -> pd.DataFrame:
    subset = cfg["scoring"].get(
        "subset_name",
        f"ventana_{cfg['scoring']['window_start']}_{cfg['scoring']['window_end']}",
    )

    df = pd.read_sql_query(
        "SELECT * FROM xy_subset_agg WHERE subset=?",
        conn,
        params=(subset,),
    )

    if df.empty:
        raise ValueError(
            f"xy_subset_agg no contiene registros para {subset}. "
            "Ejecuta antes el módulo 5B."
        )

    df = clean_columns(df)

    if "xy_group_id" not in df.columns:
        raise ValueError("xy_subset_agg no contiene xy_group_id.")

    return df


def attach_xy_group_id(records: pd.DataFrame, xy: pd.DataFrame) -> pd.DataFrame:
    """
    Asocia cada registro de thematic_base a xy_group_id.

    IMPORTANTE:
    No se usa join por coordenadas redondeadas. `xy_subset_agg` fue construido
    desde `grupos_xy` + `thematic_base` con igualdad exacta de lon/lat, por lo
    que aquí debe conservarse la misma llave exacta. Redondear puede colapsar
    dos grupos XY muy próximos en una sola llave y dejar el segundo grupo sin
    atributos temáticos agregados.
    """
    rec = records.copy()
    xy_keep_cols = ["xy_group_id", "lon", "lat"]

    if "n_registros_subset" in xy.columns:
        xy_keep_cols.append("n_registros_subset")

    xy_keep = xy[xy_keep_cols].drop_duplicates().copy()

    for col in ["lon", "lat"]:
        rec[col] = pd.to_numeric(rec[col], errors="coerce")
        xy_keep[col] = pd.to_numeric(xy_keep[col], errors="coerce")

    # Debe existir una correspondencia 1:1 entre coordenada exacta y xy_group_id.
    coord_to_xy = (
        xy_keep
        .groupby(["lon", "lat"], dropna=False)["xy_group_id"]
        .nunique(dropna=True)
        .reset_index(name="n_xy_group_id")
    )
    duplicated_coords = coord_to_xy[coord_to_xy["n_xy_group_id"].gt(1)]

    if not duplicated_coords.empty:
        sample = duplicated_coords.head(10).to_dict("records")
        raise ValueError(
            "xy_subset_agg contiene coordenadas exactas asociadas a más de un "
            f"xy_group_id. Ejemplos: {sample}"
        )

    out = rec.merge(
        xy_keep[["xy_group_id", "lon", "lat"]].drop_duplicates(["lon", "lat"]),
        on=["lon", "lat"],
        how="left",
    )

    missing = int(out["xy_group_id"].isna().sum())

    if missing:
        sample = (
            out.loc[out["xy_group_id"].isna(), ["source_rowid", "lon", "lat"]]
            .head(10)
            .to_dict("records")
        )
        raise ValueError(
            f"{missing:,} registros no pudieron asociarse a xy_group_id "
            "mediante lon/lat exactos. Esto indica una inconsistencia entre "
            f"thematic_base y xy_subset_agg. Ejemplos: {sample}"
        )

    out["xy_group_id"] = out["xy_group_id"].astype("string")

    # Control crítico: la cantidad de registros asignados por grupo debe
    # coincidir con n_registros_subset calculado en el Módulo 5B.
    if "n_registros_subset" in xy_keep.columns:
        expected = (
            xy_keep[["xy_group_id", "n_registros_subset"]]
            .drop_duplicates("xy_group_id")
            .assign(n_registros_subset=lambda d: pd.to_numeric(d["n_registros_subset"], errors="coerce"))
            .set_index("xy_group_id")
        )
        observed = out.groupby("xy_group_id", dropna=False).size().rename("n_registros_asignados")
        audit = expected.join(observed, how="left")
        audit["n_registros_asignados"] = audit["n_registros_asignados"].fillna(0).astype(int)
        bad = audit[audit["n_registros_asignados"].ne(audit["n_registros_subset"])]

        if not bad.empty:
            sample = bad.head(10).reset_index().to_dict("records")
            raise ValueError(
                "Inconsistencia al asignar registros a xy_group_id: "
                "n_registros_asignados no coincide con n_registros_subset. "
                f"Grupos afectados: {len(bad):,}. Ejemplos: {sample}"
            )

    return out


# =============================================================================
# LECTURA Y AGREGACIÓN DEL COMPONENTE ESPECTRAL
# =============================================================================

def read_spectral_units() -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Lee la auditoría espectral SIN duplicados por extract_id generada por el Módulo 09.

    Capa esperada:
      audit_extract_units_s2sr_annual

    Esta es la capa correcta para el scoring por xy_group_id, porque no
    sobrepondera registros originales repetidos que comparten la misma señal
    espectral.
    """
    meta = {
        "spectral_file": str(SPECTRAL_AUDIT_GPKG),
        "spectral_layer": SPECTRAL_AUDIT_LAYER,
        "spectral_status": "not_found",
        "spectral_join_key": "xy_group_id",
    }

    if not SPECTRAL_AUDIT_GPKG.exists():
        raise FileNotFoundError(f"No existe el GPKG espectral del Módulo 09: {SPECTRAL_AUDIT_GPKG}")

    try:
        gdf = gpd.read_file(SPECTRAL_AUDIT_GPKG, layer=SPECTRAL_AUDIT_LAYER)
    except Exception as exc:
        raise RuntimeError(
            f"No se pudo leer la capa {SPECTRAL_AUDIT_LAYER} desde {SPECTRAL_AUDIT_GPKG}: {exc}"
        ) from exc

    df = pd.DataFrame(gdf.drop(columns=[gdf.geometry.name], errors="ignore"))
    df = clean_columns(df)

    if df.empty:
        raise ValueError(f"La capa espectral {SPECTRAL_AUDIT_LAYER} está vacía.")

    required = ["xy_group_id", "extract_id"]
    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(
            f"La capa {SPECTRAL_AUDIT_LAYER} no contiene columnas requeridas: {missing}"
        )

    df["xy_group_id"] = df["xy_group_id"].astype("string")
    df["extract_id"] = df["extract_id"].astype("string")

    meta["spectral_status"] = "loaded_gpkg_module_09_units"
    meta["n_spectral_units_loaded"] = int(len(df))
    meta["n_spectral_xy_loaded"] = int(df["xy_group_id"].nunique(dropna=True))

    return df, meta


def prepare_spectral_units(spec: pd.DataFrame) -> pd.DataFrame:
    spec = spec.copy()

    defaults = {
        "spectral_alert_level": "sin_alerta",
        "spectral_alert_count": 0,
        "flag_low_months_obs": 0,
        "flag_low_total_obs": 0,
        "flag_low_availability": 0,
        "flag_no_spectral_data": 0,
        "flag_spectral_class_review": 0,
        "s2yr_months_obs": np.nan,
        "s2yr_obs_total": np.nan,
        "s2yr_obs_mean": np.nan,
        "s2yr_cloudprob_median": np.nan,
        "s2yr_ndvi_mean": np.nan,
        "s2yr_ndvi_median": np.nan,
        "s2yr_ndvi8a_mean": np.nan,
        "s2yr_ndvi8a_median": np.nan,
        "s2yr_ndre_mean": np.nan,
        "s2yr_ndre_median": np.nan,
    }

    for col, default in defaults.items():
        if col not in spec.columns:
            spec[col] = default

    numeric_cols = [
        "spectral_alert_count",
        "flag_low_months_obs",
        "flag_low_total_obs",
        "flag_low_availability",
        "flag_no_spectral_data",
        "flag_spectral_class_review",
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

    for col in numeric_cols:
        spec[col] = pd.to_numeric(spec[col], errors="coerce")

    # Si flag_low_availability no venía creado, se deriva desde las dos banderas base.
    spec["flag_low_availability"] = np.where(
        (
            spec["flag_low_availability"].fillna(0).astype(int).eq(1)
            | spec["flag_low_months_obs"].fillna(0).astype(int).eq(1)
            | spec["flag_low_total_obs"].fillna(0).astype(int).eq(1)
        ),
        1,
        0,
    )

    spec["spectral_alert_level"] = spec["spectral_alert_level"].fillna("sin_alerta").astype(str)

    spec["spectral_severity_order"] = (
        spec["spectral_alert_level"]
        .map(sev_order)
        .fillna(0)
        .astype(int)
    )

    return spec


def make_spectral_by_xy(spec: pd.DataFrame) -> pd.DataFrame:
    """
    Resume la auditoría espectral sin duplicados por extract_id a la unidad de
    decisión del scoring: xy_group_id.
    """
    spec = prepare_spectral_units(spec)

    out = (
        spec
        .groupby("xy_group_id", dropna=False)
        .agg(
            n_extract_units_spectral=("extract_id", "nunique"),
            n_spectral_rows=("extract_id", "size"),
            spectral_severity_order_max=("spectral_severity_order", "max"),
            spectral_alert_count_sum=("spectral_alert_count", "sum"),
            pct_extract_units_sin_alerta=(
                "spectral_alert_level",
                lambda x: 100 * x.astype(str).str.lower().eq("sin_alerta").mean(),
            ),
            pct_extract_units_alerta_baja=(
                "spectral_alert_level",
                lambda x: 100 * x.astype(str).str.lower().eq("baja").mean(),
            ),
            pct_extract_units_alerta_media=(
                "spectral_alert_level",
                lambda x: 100 * x.astype(str).str.lower().eq("media").mean(),
            ),
            pct_extract_units_alerta_alta=(
                "spectral_alert_level",
                lambda x: 100 * x.astype(str).str.lower().isin(["alta", "alta_sin_datos"]).mean(),
            ),
            pct_extract_units_baja_disponibilidad=(
                "flag_low_availability",
                lambda x: 100 * pd.to_numeric(x, errors="coerce").fillna(0).astype(int).eq(1).mean(),
            ),
            pct_extract_units_sin_datos=(
                "flag_no_spectral_data",
                lambda x: 100 * pd.to_numeric(x, errors="coerce").fillna(0).astype(int).eq(1).mean(),
            ),
            pct_extract_units_revision_espectral=(
                "flag_spectral_class_review",
                lambda x: 100 * pd.to_numeric(x, errors="coerce").fillna(0).astype(int).eq(1).mean(),
            ),
            s2yr_months_obs_median=("s2yr_months_obs", "median"),
            s2yr_obs_total_median=("s2yr_obs_total", "median"),
            s2yr_obs_mean_median=("s2yr_obs_mean", "median"),
            s2yr_cloudprob_median=("s2yr_cloudprob_median", "median"),
            s2yr_ndvi_mean=("s2yr_ndvi_mean", "median"),
            s2yr_ndvi_median=("s2yr_ndvi_median", "median"),
            s2yr_ndvi8a_mean=("s2yr_ndvi8a_mean", "median"),
            s2yr_ndvi8a_median=("s2yr_ndvi8a_median", "median"),
            s2yr_ndre_mean=("s2yr_ndre_mean", "median"),
            s2yr_ndre_median=("s2yr_ndre_median", "median"),
        )
        .reset_index()
    )

    out["spectral_alert_level_max"] = out["spectral_severity_order_max"].map(sev_name)

    # Score espectral agregado por xy_group_id.
    # Parte de 100 y penaliza alertas fuertes, baja disponibilidad, revisión y ausencia de datos.
    out["score_espectral"] = (
        100
        - 0.60 * out["pct_extract_units_alerta_alta"]
        - 0.35 * out["pct_extract_units_alerta_media"]
        - 0.30 * out["pct_extract_units_baja_disponibilidad"]
        - 0.50 * out["pct_extract_units_sin_datos"]
        - 0.20 * out["pct_extract_units_revision_espectral"]
    ).clip(0, 100).round(3)

    return out


def validate_spectral_coverage(
    master_xy: pd.DataFrame,
    spectral_by_xy: pd.DataFrame,
    allow_missing: bool = False,
) -> dict[str, Any]:
    master_ids = set(master_xy["xy_group_id"].dropna().astype(str))
    spec_ids = set(spectral_by_xy["xy_group_id"].dropna().astype(str))

    missing = sorted(master_ids - spec_ids)
    extra = sorted(spec_ids - master_ids)

    coverage = 100 * (len(master_ids) - len(missing)) / len(master_ids) if master_ids else 0.0

    audit = {
        "n_xy_groups_master": int(len(master_ids)),
        "n_xy_groups_spectral": int(len(spec_ids)),
        "n_xy_groups_missing_spectral": int(len(missing)),
        "n_xy_groups_extra_spectral": int(len(extra)),
        "spectral_xy_coverage_pct": round(float(coverage), 3),
    }

    if missing and not allow_missing:
        sample = ", ".join(missing[:10])
        raise ValueError(
            "Hay xy_group_id del scoring sin componente espectral. "
            f"Faltantes: {len(missing):,}. Cobertura: {coverage:.3f}%. "
            f"Ejemplos: {sample}. "
            "Revise que el Módulo 09 se haya generado con extract_units_s2sr_annual "
            "y que la capa audit_extract_units_s2sr_annual conserve xy_group_id."
        )

    return audit


# =============================================================================
# SCORING DE REGISTROS Y AGREGACIÓN XY
# =============================================================================

def availability(v: Any) -> float:
    if pd.isna(v):
        return 70.0

    v = float(v)

    if v >= 8:
        return 100.0
    if v >= 6:
        return 85.0
    if v >= 4:
        return 65.0
    if v >= 2:
        return 40.0
    if v >= 1:
        return 20.0

    return 0.0


def add_record_scores(records: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """
    Score a nivel de registro. En esta versión el componente espectral fuerte
    entra después por xy_group_id, no por source_rowid.
    """
    df = records.copy()

    temp = {str(k): v for k, v in cfg["temporal_scores"].items()}

    df["score_temporal_registro"] = (
        df["anio"]
        .astype(int)
        .astype(str)
        .map(temp)
        .fillna(0)
        .astype(float)
    )

    df["estado_registro_scoring"] = "registro_apto_preliminar"

    return df


def aggregate_records_to_xy(records: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    rec = records.copy()

    temp = {str(k): v for k, v in cfg["temporal_scores"].items()}

    rec["score_temporal_record"] = (
        rec["anio"]
        .astype(int)
        .astype(str)
        .map(temp)
        .fillna(0)
        .astype(float)
    )

    required_conf_cols = [
        "conf_integrada_score_observado",
        "conf_integrada_observada",
    ]
    missing_conf_cols = [c for c in required_conf_cols if c not in rec.columns]
    if missing_conf_cols:
        raise ValueError(
            "Los registros no fueron preparados mediante prepare_confidence_records. "
            f"Faltan: {missing_conf_cols}"
        )

    def concat(s: pd.Series) -> str:
        return "|".join(
            sorted(
                {
                    str(x)
                    for x in s.dropna().tolist()
                    if str(x).strip()
                }
            )
        )

    target = int(cfg["scoring"]["target_year"])

    g = (
        rec.groupby("xy_group_id")
        .agg(
            n_registros=("source_rowid", "count"),
            n_fuentes_registros=("id_fuente", "nunique"),
            n_anios=("anio", "nunique"),
            anio_min=("anio", "min"),
            anio_max=("anio", "max"),
            distancia_minima_2020=(
                "anio",
                lambda s: int(
                    np.min(
                        np.abs(
                            pd.to_numeric(s, errors="coerce") - target
                        )
                    )
                ),
            ),
            incluye_2020=(
                "anio",
                lambda s: int((pd.to_numeric(s, errors="coerce") == target).any()),
            ),
            score_temporal=("score_temporal_record", "max"),
            pais_dominante=("pais", mode),
            id_fuente_dominante=("id_fuente", mode),
            fuente_dominante=("fuente", mode),
            tipo_fuente_dominante=("tipo_fuente", mode),
            detalle_tipo_fuente_dominante=("detalle_tipo_fuente", mode),
            nivel_0_dominante=("nivel_0", mode),
            nivel_1_dominante=("nivel_1", mode),
            nivel_2_dominante=("nivel_2", mode),
            valores_nivel_0=("nivel_0", concat),
            valores_nivel_1=("nivel_1", concat),
            valores_nivel_2=("nivel_2", concat),
            n_nivel0=("nivel_0", "nunique"),
            n_nivel1=("nivel_1", "nunique"),
            n_nivel2=("nivel_2", "nunique"),
            conf_integrada_promedio_observada=(
                "conf_integrada_score_observado",
                "mean",
            ),
            n_conf_integrada_observada=(
                "conf_integrada_score_observado",
                "count",
            ),
        )
        .reset_index()
    )

    required_source_cols = [
        "id_fuente",
        "fuente",
        "tipo_fuente",
        "score_directitud",
        "score_trazabilidad",
        "score_consistencia_temporal_fuente",
        "score_fuente_base",
        "flag_fuente_anio_inconsistente",
        "flag_fuente_pais_inconsistente",
    ]
    missing_source_cols = [c for c in required_source_cols if c not in rec.columns]
    if missing_source_cols:
        raise ValueError(
            "Los registros no fueron preparados mediante prepare_source_records. "
            f"Faltan: {missing_source_cols}"
        )

    source_units = rec[
        ["xy_group_id"] + required_source_cols
    ].drop_duplicates(["xy_group_id", "id_fuente"]).copy()

    source_consistency = (
        source_units.groupby(["xy_group_id", "id_fuente"], dropna=False)
        .agg(n_score_fuente=("score_fuente_base", "nunique"))
        .reset_index()
    )
    bad_source_units = source_consistency[source_consistency["n_score_fuente"].ne(1)]
    if not bad_source_units.empty:
        raise ValueError(
            "Un mismo xy_group_id + id_fuente tiene más de un score_fuente_base. "
            f"Ejemplos: {bad_source_units.head(10).to_dict('records')}"
        )

    source_xy = (
        source_units.groupby("xy_group_id", dropna=False)
        .agg(
            n_fuentes=("id_fuente", "nunique"),
            ids_fuente_presentes=("id_fuente", concat),
            fuentes_presentes=("fuente", concat),
            tipos_fuente_presentes=("tipo_fuente", concat),
            score_directitud_fuente_promedio=("score_directitud", "mean"),
            score_trazabilidad_fuente_promedio=("score_trazabilidad", "mean"),
            score_temporal_metadata_fuente_promedio=(
                "score_consistencia_temporal_fuente",
                "mean",
            ),
            score_fuente_promedio=("score_fuente_base", "mean"),
            score_fuente_minimo=("score_fuente_base", "min"),
            score_fuente_maximo=("score_fuente_base", "max"),
            n_fuentes_anio_inconsistente=(
                "flag_fuente_anio_inconsistente",
                "sum",
            ),
            n_fuentes_pais_inconsistente=(
                "flag_fuente_pais_inconsistente",
                "sum",
            ),
        )
        .reset_index()
    )
    for col in [
        "score_directitud_fuente_promedio",
        "score_trazabilidad_fuente_promedio",
        "score_temporal_metadata_fuente_promedio",
        "score_fuente_promedio",
        "score_fuente_minimo",
        "score_fuente_maximo",
    ]:
        source_xy[col] = pd.to_numeric(source_xy[col], errors="coerce").round(3)

    g = g.merge(source_xy, on="xy_group_id", how="left", validate="one_to_one")
    if not g["n_fuentes"].equals(g["n_fuentes_registros"]):
        bad = g.loc[
            g["n_fuentes"].ne(g["n_fuentes_registros"]),
            ["xy_group_id", "n_fuentes", "n_fuentes_registros"],
        ]
        raise ValueError(
            "La agregación de fuentes únicas no coincide con los registros. "
            f"Ejemplos: {bad.head(10).to_dict('records')}"
        )
    g = g.drop(columns=["n_fuentes_registros"])

    settings = confidence_settings(cfg)
    g["pct_conf_integrada_observada"] = (
        100.0 * g["n_conf_integrada_observada"] / g["n_registros"]
    ).round(6)
    g["flag_confianza_imputada"] = g["n_conf_integrada_observada"].eq(0).astype(int)
    g["score_confiabilidad_base"] = (
        pd.to_numeric(g["conf_integrada_promedio_observada"], errors="coerce")
        .fillna(settings["neutral_score"])
        .clip(0, 100)
    )
    g["origen_score_confiabilidad"] = np.where(
        g["flag_confianza_imputada"].eq(1),
        "neutral_imputado",
        "observado",
    )
    # Alias compatible, pero conserva NaN cuando no hubo dato observado.
    g["conf_integrada_promedio"] = g["conf_integrada_promedio_observada"]
    g["incluye_2018_2022"] = 1

    return g


def add_country_class(master: pd.DataFrame, records: pd.DataFrame) -> pd.DataFrame:
    counts = (
        records.groupby(["pais", "nivel_1"])
        .agg(n_registros_pais_clase=("source_rowid", "count"))
        .reset_index()
    )

    counts["estado_pais_clase"] = pd.cut(
        counts["n_registros_pais_clase"],
        [-1, 29, 99, 499, np.inf],
        labels=["critico", "bajo", "moderado", "suficiente"],
    ).astype(str)

    counts = counts.rename(
        columns={
            "pais": "pais_grupo",
            "nivel_1": "nivel_1_dominante",
        }
    )

    out = master.merge(
        counts,
        on=["pais_grupo", "nivel_1_dominante"],
        how="left",
    )

    out["estado_pais_clase"] = out["estado_pais_clase"].fillna("sin_matriz")

    return out


def merge_conflicts(master: pd.DataFrame) -> pd.DataFrame:
    out = master.copy()

    path = OUT / "05c_conflict_taxonomy_details.csv"

    if path.exists():
        c = pd.read_csv(path)

        keep = [
            x
            for x in [
                "xy_group_id",
                "tipo_conflicto",
                "severidad_conflicto",
                "score_prioridad_revision",
            ]
            if x in c
        ]

        if keep:
            c = c[keep].copy()

            if "score_prioridad_revision" in c:
                c = c.sort_values("score_prioridad_revision", ascending=False)

            out = out.merge(
                c.drop_duplicates("xy_group_id"),
                on="xy_group_id",
                how="left",
            )

    for col in ["tipo_conflicto", "severidad_conflicto"]:
        out[col] = out[col].fillna("") if col in out else ""

    out["score_prioridad_revision"] = pd.to_numeric(
        out.get("score_prioridad_revision", 0),
        errors="coerce",
    ).fillna(0)

    return out


def compute_scores(master: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    df = master.copy()

    df["score_espacial"] = df["estado_xy_subset"].map(
        lambda x: map_score(x, cfg["spatial_scores"], 70)
    )

    df["flag_conflicto_activo"] = (
        df["estado_xy_subset"]
        .astype(str)
        .eq("conflicto_tematico_subset")
        .astype(int)
    )

    df["score_consistencia_clase"] = np.select(
        [
            df["flag_conflicto_activo"].eq(1),
            (df["n_nivel1"] <= 1) & (df["n_nivel2"] <= 1),
            (df["n_nivel1"] <= 1) & (df["n_nivel2"] > 1),
            df["n_nivel1"] > 1,
        ],
        [0, 100, 75, 40],
        default=60,
    )

    df["score_viabilidad_clase"] = df["estado_pais_clase"].map(
        lambda x: map_score(x, cfg["class_viability_scores"], 70)
    )

    residual = cfg.get("semantic_keywords", {}).get("residual", ["otras", "otra"])

    df["flag_clase_residual"] = (
        df["nivel_1_dominante"]
        .map(lambda x: any(k in str(x).lower() for k in residual))
        .astype(int)
    )

    df["score_claridad_semantica"] = np.where(
        df["flag_clase_residual"].eq(1),
        60,
        100,
    )

    df["score_nivel_leyenda"] = np.select(
        [
            df["n_nivel2"].eq(1) & df["score_viabilidad_clase"].ge(70),
            df["n_nivel1"].eq(1),
        ],
        [100, 80],
        default=40,
    )

    df["score_tematico"] = (
        0.4 * df["score_consistencia_clase"]
        + 0.3 * df["score_viabilidad_clase"]
        + 0.2 * df["score_claridad_semantica"]
        + 0.1 * df["score_nivel_leyenda"]
    ).round(3)

    if "score_confiabilidad_base" not in df.columns:
        raise ValueError(
            "Falta score_confiabilidad_base. La confiabilidad debe prepararse y "
            "auditarse antes de calcular el score multicriterio."
        )

    confidence_score = pd.to_numeric(
        df["score_confiabilidad_base"],
        errors="coerce",
    )
    if confidence_score.isna().any():
        raise ValueError(
            f"Hay {int(confidence_score.isna().sum())} grupos sin score de "
            "confiabilidad después de la preparación."
        )

    df["score_confiabilidad"] = confidence_score.clip(0, 100)

    df["score_representatividad"] = df["estado_pais_clase"].map(
        lambda x: map_score(x, cfg["representativity_scores"], 70)
    )

    if "score_fuente_promedio" not in df.columns:
        raise ValueError(
            "Falta score_fuente_promedio. El componente fuente debe calcularse "
            "desde source_catalog.csv antes del score multicriterio."
        )
    source_score = pd.to_numeric(df["score_fuente_promedio"], errors="coerce")
    if source_score.isna().any():
        raise ValueError(
            f"Hay {int(source_score.isna().sum())} grupos sin score de fuente."
        )
    df["score_fuente"] = source_score.clip(0, 100)

    # score_espectral viene de audit_extract_units_s2sr_annual agregado por xy_group_id.
    if "score_espectral" not in df.columns:
        raise ValueError("Falta score_espectral. El componente espectral no fue unido al master.")

    w = cfg["weights_xy"]

    df["score_aptitud_raw"] = (
        w["temporal"] * df["score_temporal"]
        + w["spatial"] * df["score_espacial"]
        + w["thematic"] * df["score_tematico"]
        + w["spectral"] * df["score_espectral"]
        + w["confidence"] * df["score_confiabilidad"]
        + w["representativity"] * df["score_representatividad"]
        + w["source"] * df["score_fuente"]
    ).round(3)

    caps = cfg.get("caps", {})

    df["score_cap"] = 100.0
    df["cap_reason"] = ""

    def cap(mask: pd.Series, value: float, reason: str) -> None:
        idx = mask & (df["score_cap"] > value)
        df.loc[idx, "score_cap"] = value
        df.loc[idx, "cap_reason"] = reason

    level = df["spectral_alert_level_max"].astype(str).str.lower()

    cap(
        level.eq("alta"),
        float(caps.get("spectral_alert_high", 70)),
        "alerta_espectral_alta",
    )

    cap(
        level.eq("alta_sin_datos"),
        float(caps.get("spectral_no_data", 60)),
        "sin_datos_espectrales",
    )

    cap(
        df["flag_clase_residual"].eq(1),
        float(caps.get("residual_class", 75)),
        "clase_residual",
    )

    pais_grupo = df["pais_grupo"].astype(str).str.lower()
    cap(
        pais_grupo.eq("multipais_o_inconsistente"),
        float(caps.get("multipais_inconsistent", 40)),
        "multipais_o_inconsistente",
    )

    df["score_aptitud_total"] = np.minimum(
        df["score_aptitud_raw"],
        df["score_cap"],
    ).round(3)

    return df


def assign_states(master: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """
    Asigna categorías finales de aptitud con nombres orientados al uso.

    En esta versión ya no se producen etiquetas como `entrenamiento_alta_prioridad`.
    Las categorías se asignan directamente en `categoria_aptitud_preliminar` y
    se homologan a la Actividad 1.8 en `categoria_uso_actividad_1_8`.
    """
    out = master.copy()

    th = cfg["state_thresholds"]

    level = out["spectral_alert_level_max"].astype(str).str.lower()
    conflict = out["tipo_conflicto"].astype(str).str.lower()
    sev = out["severidad_conflicto"].astype(str).str.lower()

    conditions = [
        out["flag_conflicto_activo"].eq(1)
        & conflict.str.contains("posible_cambio_temporal", na=False),

        out["flag_conflicto_activo"].eq(1)
        & (
            conflict.str.contains(
                "bosque_vs_no_bosque|conflicto_mismo_anio|residual_otras",
                regex=True,
                na=False,
            )
            | sev.isin(["alta", "muy_alta"])
        ),

        level.isin(["alta", "alta_sin_datos"]),

        out["score_aptitud_total"].ge(float(th["training_high"])),

        out["score_aptitud_total"].ge(float(th["training_conditioned"])),

        out["score_aptitud_total"].ge(float(th["contextual"])),
    ]

    choices = [
        "referencia_contextual_temporal",
        "referencia_contextual_revision",
        "apoyo_interpretativo_espectral",
        "datos_para_entrenamiento",
        "datos_para_validacion",
        "datos_para_prueba",
    ]

    out["categoria_aptitud_preliminar"] = np.select(
        conditions,
        choices,
        default="mascara_exclusion",
    )

    out["categoria_uso_actividad_1_8"] = (
        out["categoria_aptitud_preliminar"].map(usage_category_map()).fillna("sin_definicion")
    )

    out["definicion_categoria_aptitud"] = (
        out["categoria_aptitud_preliminar"].map(usage_definition_map()).fillna("")
    )

    out["accion_recomendada"] = (
        out["categoria_aptitud_preliminar"].map(usage_action_map()).fillna("revision_general")
    )

    out["razon_categoria_aptitud"] = out.apply(
        lambda r: (
            f"score:{r['score_aptitud_total']}; "
            f"tipo_xy:{r['estado_xy_subset']}; "
            f"alerta:{r['spectral_alert_level_max']}; "
            f"conflicto:{r.get('tipo_conflicto', '')}; "
            f"cap:{r.get('cap_reason', '')}"
        ),
        axis=1,
    )

    return out


def source_ranking(
    master: pd.DataFrame,
    cfg: dict[str, Any],
    source_profile: pd.DataFrame,
) -> pd.DataFrame:
    master = master.copy()

    master = master[
        master["fuente_dominante"].notna()
        & pd.to_numeric(master["n_registros"], errors="coerce").fillna(0).gt(0)
    ].copy()

    rows = []

    for id_fuente, g in master.groupby("id_fuente_dominante", dropna=False):
        fuente = mode(g["fuente_dominante"])
        def pct_mask(mask: pd.Series) -> float:
            return round(float(mask.mean() * 100), 3) if len(mask) else 0

        rows.append(
            {
                "id_fuente": _normalize_source_id(id_fuente),
                "fuente": fuente,
                "n_grupos_xy": len(g),
                "n_registros_representados": int(g["n_registros"].sum()),
                "score_temporal_fuente": round(g["score_temporal"].mean(), 3),
                "score_tematico_fuente": round(g["score_tematico"].mean(), 3),
                "score_espacial_fuente": round(g["score_espacial"].mean(), 3),
                "score_espectral_fuente": round(g["score_espectral"].mean(), 3),
                "score_representatividad_fuente": round(g["score_representatividad"].mean(), 3),
                "pct_conflicto_activo": pct_mask(g["flag_conflicto_activo"].eq(1)),
                "pct_alerta_espectral_alta": pct_mask(
                    g["spectral_alert_level_max"]
                    .astype(str)
                    .str.lower()
                    .isin(["alta", "alta_sin_datos"])
                ),
                "pct_no_uso_directo": pct_mask(
                    ~g["categoria_uso_actividad_1_8"].astype(str).isin(["entrenamiento", "validación", "prueba"])
                ),
                "pct_entrenamiento": pct_mask(g["categoria_uso_actividad_1_8"].astype(str).eq("entrenamiento")),
                "pct_validacion": pct_mask(g["categoria_uso_actividad_1_8"].astype(str).eq("validación")),
                "pct_prueba": pct_mask(g["categoria_uso_actividad_1_8"].astype(str).eq("prueba")),
            }
        )

    out = pd.DataFrame(rows)

    if out.empty:
        return out

    profile_keep = [
        "id_fuente",
        "fuente_reporte",
        "tipo_documentado",
        "medio_obtencion",
        "anios_documentados",
        "pais_documentado",
        "score_directitud",
        "score_trazabilidad",
        "score_consistencia_temporal_fuente",
        "score_fuente_base",
        "pct_anio_informado",
        "pct_anio_consistente",
        "n_nombre_inconsistente",
        "n_tipo_inconsistente",
        "n_pais_inconsistente",
        "flag_fuente_anio_inconsistente",
        "flag_fuente_pais_inconsistente",
    ]
    out["id_fuente"] = out["id_fuente"].map(_normalize_source_id)
    out = source_profile[profile_keep].merge(
        out,
        on="id_fuente",
        how="left",
        validate="one_to_one",
    )
    out["fuente"] = out["fuente"].fillna(out["fuente_reporte"])
    out["score_trazabilidad_documental"] = out["score_trazabilidad"]

    out["score_compatibilidad_pipeline"] = np.select(
        [
            out["pct_conflicto_activo"].le(1)
            & out["pct_alerta_espectral_alta"].le(5),

            out["pct_conflicto_activo"].le(5)
            & out["pct_alerta_espectral_alta"].le(15),
        ],
        [85, 70],
        default=50,
    )

    w = cfg["weights_source"]

    out["score_desempeno_fuente"] = (
        w["traceability"] * out["score_trazabilidad_documental"]
        + w["temporal"] * out["score_temporal_fuente"]
        + w["thematic"] * out["score_tematico_fuente"]
        + w["spatial"] * out["score_espacial_fuente"]
        + w["representativity"] * out["score_representatividad_fuente"]
        + w["spectral"] * out["score_espectral_fuente"]
        + w["pipeline_compatibility"] * out["score_compatibilidad_pipeline"]
    ).round(3)

    # Alias compatible: este ranking es posterior y NO alimenta score_fuente XY.
    out["score_aptitud_fuente"] = out["score_desempeno_fuente"]

    out["categoria_aptitud_fuente"] = pd.cut(
        out["score_desempeno_fuente"],
        [-np.inf, 40, 55, 70, 85, np.inf],
        labels=[
            "fuente_para_mascara_o_exclusion",
            "fuente_de_referencia_contextual",
            "fuente_de_apoyo_interpretativo",
            "fuente_para_validacion_o_prueba",
            "fuente_para_entrenamiento",
        ],
    ).astype(str)

    out["categoria_uso_fuente_actividad_1_8"] = (
        out["categoria_aptitud_fuente"].map(source_usage_map()).fillna("sin_definicion")
    )

    return out.sort_values("score_aptitud_fuente", ascending=False)


def gap_priority(records: pd.DataFrame) -> pd.DataFrame:
    df = (
        records.groupby(["pais", "nivel_1"])
        .agg(
            n_registros_2018_2022=("source_rowid", "count"),
            n_fuentes=("fuente", "nunique"),
        )
        .reset_index()
        .rename(columns={"nivel_1": "clase"})
    )

    df["nivel"] = "Nivel_1"

    df["estado_pais_clase"] = pd.cut(
        df["n_registros_2018_2022"],
        [-1, 29, 99, 499, np.inf],
        labels=["critico", "bajo", "moderado", "suficiente"],
    ).astype(str)

    df["score_necesidad_complementacion"] = (
        df["estado_pais_clase"]
        .map(
            {
                "critico": 90,
                "bajo": 70,
                "moderado": 40,
                "suficiente": 10,
            }
        )
        .fillna(50)
    )

    return df.sort_values(
        ["score_necesidad_complementacion", "pais", "clase"],
        ascending=[False, True, True],
    )


def scenarios(master: pd.DataFrame) -> pd.DataFrame:
    df = master

    data = {
        "datos_para_entrenamiento": df[df["categoria_uso_actividad_1_8"].astype(str).eq("entrenamiento")],
        "datos_para_validacion": df[df["categoria_uso_actividad_1_8"].astype(str).eq("validación")],
        "datos_para_prueba": df[df["categoria_uso_actividad_1_8"].astype(str).eq("prueba")],
        "ventana_conservadora": df[
            df["flag_conflicto_activo"].eq(0)
            & ~df["spectral_alert_level_max"].astype(str).str.lower().isin(["alta", "alta_sin_datos"])
        ],
        "nivel1_regional": df[
            df["flag_conflicto_activo"].eq(0)
            & df["n_nivel1"].le(1)
            & df["score_tematico"].ge(70)
        ],
        "apoyo_o_referencia": df[
            df["categoria_uso_actividad_1_8"].astype(str).isin(["apoyo interpretativo", "referencia contextual"])
        ],
        "mascaras": df[df["categoria_uso_actividad_1_8"].astype(str).eq("máscaras")],
    }

    return pd.DataFrame(
        [
            {
                "escenario": k,
                "n_grupos_xy": len(v),
                "n_registros_representados": int(v["n_registros"].sum()) if len(v) else 0,
                "n_fuentes": int(v["fuente_dominante"].nunique()) if len(v) else 0,
                "score_promedio": round(float(v["score_aptitud_total"].mean()), 3) if len(v) else 0,
            }
            for k, v in data.items()
        ]
    )


# =============================================================================
# REPORTES Y EXPORTACIÓN
# =============================================================================

def output_csv_paths() -> list[Path]:
    return [
        MASTER_CSV,
        SOURCE_RANKING_CSV,
        RECORD_FLAGS_CSV,
        GAP_PRIORITY_CSV,
        REVIEW_CASES_CSV,
        SCENARIOS_CSV,
        AUDIT_SUMMARY_CSV,
    ]


def output_all_paths() -> list[Path]:
    return output_csv_paths() + [SCORING_GPKG]


def outputs_exist() -> bool:
    return all(path.exists() for path in output_all_paths())


def missing_output_paths() -> list[Path]:
    return [path for path in output_all_paths() if not path.exists()]


def clean_previous_outputs() -> None:
    """Elimina salidas controladas por el Módulo 10 antes de recrear resultados."""
    for path in output_all_paths() + [REPORT_MD]:
        if path.exists():
            path.unlink()


def validate_existing_outputs(master: pd.DataFrame, audit: dict[str, Any]) -> tuple[bool, list[str]]:
    """Verifica si las salidas existentes corresponden a la versión actual."""
    problems: list[str] = []

    spectral_layer = str(audit.get("spectral_layer", ""))
    spectral_join_key = str(audit.get("spectral_join_key", ""))

    coverage = pd.to_numeric(pd.Series([audit.get("spectral_xy_coverage_pct", np.nan)]), errors="coerce").iloc[0]
    missing = pd.to_numeric(pd.Series([audit.get("n_xy_groups_missing_spectral", np.nan)]), errors="coerce").iloc[0]

    if spectral_layer != SPECTRAL_AUDIT_LAYER:
        problems.append(f"spectral_layer={spectral_layer!r}; esperado={SPECTRAL_AUDIT_LAYER!r}")

    if spectral_join_key != "xy_group_id":
        problems.append(f"spectral_join_key={spectral_join_key!r}; esperado='xy_group_id'")

    if pd.isna(coverage) or float(coverage) < 99.999:
        problems.append(f"spectral_xy_coverage_pct={coverage}; esperado=100")

    if pd.isna(missing) or int(missing) != 0:
        problems.append(f"n_xy_groups_missing_spectral={missing}; esperado=0")

    if "categoria_aptitud_preliminar" not in master.columns:
        problems.append("falta columna nueva categoria_aptitud_preliminar")

    if "categoria_uso_actividad_1_8" not in master.columns:
        problems.append("falta columna nueva categoria_uso_actividad_1_8")

    if "estado_funcional_preliminar" in master.columns:
        problems.append("salida antigua contiene estado_funcional_preliminar; se requiere renombrado directo")

    confidence_version = str(audit.get("confidence_pipeline_version", ""))
    if confidence_version != CONFIDENCE_PIPELINE_VERSION:
        problems.append(
            f"confidence_pipeline_version={confidence_version!r}; "
            f"esperado={CONFIDENCE_PIPELINE_VERSION!r}"
        )

    source_version = str(audit.get("source_pipeline_version", ""))
    if source_version != SOURCE_PIPELINE_VERSION:
        problems.append(
            f"source_pipeline_version={source_version!r}; "
            f"esperado={SOURCE_PIPELINE_VERSION!r}"
        )

    source_columns = [
        "id_fuente_dominante",
        "ids_fuente_presentes",
        "fuentes_presentes",
        "score_fuente_promedio",
        "score_fuente_minimo",
        "score_fuente_maximo",
        "score_fuente",
    ]
    for col in source_columns:
        if col not in master.columns:
            problems.append(f"falta columna de trazabilidad de fuente: {col}")

    confidence_columns = [
        "n_conf_integrada_observada",
        "pct_conf_integrada_observada",
        "conf_integrada_promedio_observada",
        "score_confiabilidad_base",
        "flag_confianza_imputada",
        "origen_score_confiabilidad",
    ]
    for col in confidence_columns:
        if col not in master.columns:
            problems.append(f"falta columna de trazabilidad de confiabilidad: {col}")

    valid_categories = set(usage_category_definitions()["categoria_aptitud_preliminar"])
    if "categoria_aptitud_preliminar" in master.columns:
        found = set(master["categoria_aptitud_preliminar"].dropna().astype(str).unique())
        unknown = sorted(found - valid_categories)
        if unknown:
            problems.append(f"categorías de aptitud no reconocidas: {unknown[:10]}")

    return len(problems) == 0, problems


def read_existing_outputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """
    Lee salidas existentes para evitar repetir el proceso pesado.

    Se usa cuando ya existen los CSV principales del Módulo 10. Permite
    regenerar el Markdown sin volver a leer GPKG grandes ni recalcular scores.
    """
    master = pd.read_csv(MASTER_CSV, encoding="utf-8-sig", low_memory=False)
    ranking = pd.read_csv(SOURCE_RANKING_CSV, encoding="utf-8-sig", low_memory=False)
    gap = pd.read_csv(GAP_PRIORITY_CSV, encoding="utf-8-sig", low_memory=False)
    review = pd.read_csv(REVIEW_CASES_CSV, encoding="utf-8-sig", low_memory=False)
    scen = pd.read_csv(SCENARIOS_CSV, encoding="utf-8-sig", low_memory=False)
    audit_df = pd.read_csv(AUDIT_SUMMARY_CSV, encoding="utf-8-sig", low_memory=False)

    audit = audit_df.iloc[0].to_dict() if len(audit_df) else {}

    return master, ranking, gap, review, scen, audit



def dataframe_to_point_gdf(
    df: pd.DataFrame,
    lon_col: str = "lon",
    lat_col: str = "lat",
    crs: str = "EPSG:4326",
) -> gpd.GeoDataFrame:
    """
    Convierte un DataFrame con lon/lat a GeoDataFrame de puntos.

    Si no existen lon/lat, devuelve GeoDataFrame sin geometría útil y permite
    que la salida se escriba como tabla cuando sea necesario.
    """
    out = df.copy()

    if lon_col not in out.columns or lat_col not in out.columns:
        return gpd.GeoDataFrame(out)

    lon = pd.to_numeric(out[lon_col], errors="coerce")
    lat = pd.to_numeric(out[lat_col], errors="coerce")

    geom = gpd.points_from_xy(lon, lat)

    gdf = gpd.GeoDataFrame(out, geometry=geom, crs=crs)

    # Evita geometrías inválidas generadas a partir de coordenadas nulas.
    invalid = lon.isna() | lat.isna()
    if invalid.any():
        gdf.loc[invalid, "geometry"] = None

    return gdf


def prepare_gpkg_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza tipos problemáticos antes de escribir a GeoPackage.

    GeoPackage/GDAL puede fallar con columnas object que mezclan listas,
    diccionarios o tipos pandas extendidos. Esta función mantiene números como
    números y convierte objetos complejos a texto.
    """
    out = df.copy()

    for col in out.columns:
        if str(out[col].dtype) in {"Int64", "Float64", "boolean"}:
            out[col] = out[col].astype("float64" if "Float" in str(out[col].dtype) else "object")

        if out[col].dtype == "object":
            out[col] = out[col].map(
                lambda x: "" if pd.isna(x) else str(x)
            )

    return out


def write_gpkg_outputs(
    master: pd.DataFrame,
    ranking: pd.DataFrame,
    gap: pd.DataFrame,
    review: pd.DataFrame,
    scen: pd.DataFrame,
    audit: dict[str, Any],
    records: pd.DataFrame | None = None,
) -> None:
    """
    Escribe las salidas principales del Módulo 10 en un GeoPackage.

    Capas espaciales:
    - xy_group_aptitude_master
    - review_priority_cases
    - record_aptitude_flags, si se proporciona records con lon/lat

    Capas tabulares:
    - source_aptitude_ranking
    - gap_priority_country_class
    - selection_scenarios_summary
    - scoring_audit_summary
    - category_definitions
    - source_category_definitions
    """
    PROCESSED_SCORING.mkdir(parents=True, exist_ok=True)

    if SCORING_GPKG.exists():
        SCORING_GPKG.unlink()

    master_gdf = dataframe_to_point_gdf(
        prepare_gpkg_table(master),
        lon_col="lon",
        lat_col="lat",
    )
    master_gdf.to_file(
        SCORING_GPKG,
        layer="xy_group_aptitude_master",
        driver="GPKG",
    )

    review_gdf = dataframe_to_point_gdf(
        prepare_gpkg_table(review),
        lon_col="lon",
        lat_col="lat",
    )
    review_gdf.to_file(
        SCORING_GPKG,
        layer="review_priority_cases",
        driver="GPKG",
    )

    if records is not None and not records.empty:
        records_gdf = dataframe_to_point_gdf(
            prepare_gpkg_table(records),
            lon_col="lon",
            lat_col="lat",
        )
        records_gdf.to_file(
            SCORING_GPKG,
            layer="record_aptitude_flags",
            driver="GPKG",
        )

    table_layers = [
        ("source_aptitude_ranking", ranking),
        ("gap_priority_country_class", gap),
        ("selection_scenarios_summary", scen),
        ("scoring_audit_summary", pd.DataFrame([audit])),
        ("category_definitions", usage_category_definitions()),
        ("source_category_definitions", source_usage_definitions()),
    ]

    for layer, df in table_layers:
        gpd.GeoDataFrame(
            prepare_gpkg_table(df),
            geometry=[None] * len(df),
            crs="EPSG:4326",
        ).to_file(
            SCORING_GPKG,
            layer=layer,
            driver="GPKG",
        )


def write_gpkg_outputs_from_csv() -> None:
    """
    Regenera el GeoPackage desde los CSV existentes sin repetir el pipeline pesado.
    """
    master, ranking, gap, review, scen, audit = read_existing_outputs()

    records = None
    if RECORD_FLAGS_CSV.exists():
        records = pd.read_csv(RECORD_FLAGS_CSV, encoding="utf-8-sig", low_memory=False)

    write_gpkg_outputs(
        master=master,
        ranking=ranking,
        gap=gap,
        review=review,
        scen=scen,
        audit=audit,
        records=records,
    )


def write_sqlite_outputs_from_csv() -> None:
    """
    Crea o actualiza el SQLite final usando CSV ya existentes.

    Esto es liviano comparado con repetir el pipeline completo y permite usar
    --write-sqlite aunque se esté reutilizando la ejecución previa.
    """
    master, ranking, gap, review, scen, audit = read_existing_outputs()
    records = pd.read_csv(RECORD_FLAGS_CSV, encoding="utf-8-sig", low_memory=False)

    with sqlite3.connect(SCORING_DB) as out:
        master.to_sql("xy_group_aptitude_master", out, if_exists="replace", index=False)
        ranking.to_sql("source_aptitude_ranking", out, if_exists="replace", index=False)
        records.to_sql("record_aptitude_flags", out, if_exists="replace", index=False)
        gap.to_sql("gap_priority_country_class", out, if_exists="replace", index=False)
        review.to_sql("review_priority_cases", out, if_exists="replace", index=False)
        scen.to_sql("selection_scenarios_summary", out, if_exists="replace", index=False)
        pd.DataFrame([audit]).to_sql("scoring_audit_summary", out, if_exists="replace", index=False)


def safe_mean(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns:
        return np.nan
    return float(pd.to_numeric(df[col], errors="coerce").mean())


def score_distribution_table(master: pd.DataFrame) -> pd.DataFrame:
    if "score_aptitud_total" not in master.columns:
        return pd.DataFrame()

    score = pd.to_numeric(master["score_aptitud_total"], errors="coerce")

    bins = [-np.inf, 40, 55, 70, 85, np.inf]
    labels = ["<=40", "40-55", "55-70", "70-85", ">85"]

    out = (
        pd.DataFrame({"rango_score": pd.cut(score, bins=bins, labels=labels)})
        .value_counts("rango_score", dropna=False)
        .reset_index(name="n_grupos")
    )

    out["pct_grupos"] = (out["n_grupos"] / out["n_grupos"].sum() * 100).round(3)

    return out


def confidence_summary_table(
    master: pd.DataFrame,
    audit: dict[str, Any],
) -> pd.DataFrame:
    """Tabla explícita para no confundir valores observados con imputados."""
    imputed = (
        pd.to_numeric(master.get("flag_confianza_imputada", pd.Series(dtype=float)), errors="coerce")
        .fillna(1)
        .eq(1)
    )
    observed_scores = pd.to_numeric(
        master.loc[~imputed, "score_confiabilidad"]
        if "score_confiabilidad" in master.columns and len(imputed) == len(master)
        else pd.Series(dtype=float),
        errors="coerce",
    )

    rows = [
        {"indicador": "Versión del control", "valor": audit.get("confidence_pipeline_version", "")},
        {"indicador": "Escala configurada", "valor": audit.get("confidence_input_scale_config", "")},
        {"indicador": "Escala detectada", "valor": audit.get("confidence_scale_detected", "")},
        {"indicador": "Valor neutral", "valor": audit.get("confidence_neutral_score", "")},
        {"indicador": "Registros con confianza observada", "valor": audit.get("n_records_confidence_observed", 0)},
        {"indicador": "% registros con confianza observada", "valor": audit.get("pct_records_confidence_observed", 0)},
        {"indicador": "Grupos XY con confianza observada", "valor": audit.get("n_xy_confidence_observed", 0)},
        {"indicador": "Grupos XY con confianza imputada", "valor": audit.get("n_xy_confidence_imputed", 0)},
        {"indicador": "% grupos XY con confianza imputada", "valor": audit.get("pct_xy_confidence_imputed", 0)},
        {"indicador": "Máximo de imputación permitido (%)", "valor": audit.get("max_imputed_xy_pct_allowed", 100)},
        {"indicador": "Valores observados distintos", "valor": audit.get("n_confidence_distinct_observed", 0)},
        {"indicador": "Media de confiabilidad observada", "valor": round(float(observed_scores.mean()), 3) if len(observed_scores) else ""},
    ]
    return pd.DataFrame(rows)


def source_summary_table(
    master: pd.DataFrame,
    audit: dict[str, Any],
) -> pd.DataFrame:
    """Resume el origen y los controles del score de fuente previo al score XY."""
    source_score = pd.to_numeric(
        master.get("score_fuente", pd.Series(dtype=float)),
        errors="coerce",
    )
    rows = [
        {"indicador": "Versión del control", "valor": audit.get("source_pipeline_version", "")},
        {"indicador": "Catálogo utilizado", "valor": audit.get("source_catalog_file", "")},
        {"indicador": "Fuentes documentadas en catálogo", "valor": audit.get("source_catalog_unique_ids", 0)},
        {"indicador": "Fuentes observadas en la ventana", "valor": audit.get("n_source_ids_observed", 0)},
        {"indicador": "Fuentes no catalogadas", "valor": audit.get("n_source_ids_uncatalogued", 0)},
        {"indicador": "Peso de directitud", "valor": audit.get("source_weight_directness", "")},
        {"indicador": "Peso de trazabilidad", "valor": audit.get("source_weight_traceability", "")},
        {"indicador": "Peso de metadatos temporales", "valor": audit.get("source_weight_temporal_metadata", "")},
        {"indicador": "Registros con nombre de fuente inconsistente", "valor": audit.get("n_source_records_name_mismatch", 0)},
        {"indicador": "Registros con tipo de fuente inconsistente", "valor": audit.get("n_source_records_type_mismatch", 0)},
        {"indicador": "Registros con país distinto al documentado", "valor": audit.get("n_source_records_country_mismatch", 0)},
        {"indicador": "Registros con año ausente", "valor": audit.get("n_source_records_year_missing", 0)},
        {"indicador": "Registros con año fuera de lo documentado", "valor": audit.get("n_source_records_year_inconsistent", 0)},
        {"indicador": "Scores de fuente distintos por XY", "valor": audit.get("n_xy_source_scores_distinct", 0)},
        {"indicador": "Score de fuente mínimo por XY", "valor": round(float(source_score.min()), 3) if len(source_score) else ""},
        {"indicador": "Score de fuente máximo por XY", "valor": round(float(source_score.max()), 3) if len(source_score) else ""},
    ]
    return pd.DataFrame(rows)


def criteria_overall_table(master: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    weights = cfg.get("weights_xy", {})

    rows = [
        ("Temporal", "score_temporal", weights.get("temporal", "")),
        ("Espacial", "score_espacial", weights.get("spatial", "")),
        ("Temático", "score_tematico", weights.get("thematic", "")),
        ("Espectral", "score_espectral", weights.get("spectral", "")),
        ("Confiabilidad", "score_confiabilidad", weights.get("confidence", "")),
        ("Representatividad", "score_representatividad", weights.get("representativity", "")),
        ("Fuente", "score_fuente", weights.get("source", "")),
        ("Score raw", "score_aptitud_raw", ""),
        ("Score total", "score_aptitud_total", ""),
    ]

    data = []

    for criterio, campo, peso in rows:
        if campo not in master.columns:
            continue

        s = pd.to_numeric(master[campo], errors="coerce")

        row = {
            "criterio": criterio,
            "campo": campo,
            "peso_configurado": peso,
            "media": round(float(s.mean()), 3),
            "mediana": round(float(s.median()), 3),
            "min": round(float(s.min()), 3),
            "max": round(float(s.max()), 3),
            "n_validos_score": int(s.notna().sum()),
            "n_observados_origen": "",
            "n_imputados_neutral": "",
        }

        if criterio == "Confiabilidad" and "flag_confianza_imputada" in master.columns:
            imputed = pd.to_numeric(
                master["flag_confianza_imputada"], errors="coerce"
            ).fillna(1).eq(1)
            row["n_observados_origen"] = int((~imputed).sum())
            row["n_imputados_neutral"] = int(imputed.sum())

        data.append(row)

    return pd.DataFrame(data)


def criteria_description_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "criterio": "Temporal",
                "campo_score": "score_temporal",
                "valores_o_campos_usados": "anio; target_year; temporal_scores",
                "qué_evalúa": "Cercanía temporal respecto al año objetivo 2020.",
                "cómo_se_interpreta": "Valores altos indican registros más próximos al año de referencia. 2020 recibe el máximo; años vecinos reciben menor puntaje.",
            },
            {
                "criterio": "Espacial",
                "campo_score": "score_espacial",
                "valores_o_campos_usados": "estado_xy_subset; spatial_scores",
                "qué_evalúa": "Consistencia espacial del grupo XY dentro del subset.",
                "cómo_se_interpreta": "Valores altos indican grupos espacialmente limpios. Valores bajos indican conflicto espacial/temático o condición menos apta.",
            },
            {
                "criterio": "Temático",
                "campo_score": "score_tematico",
                "valores_o_campos_usados": "n_nivel1; n_nivel2; estado_pais_clase; flag_clase_residual; score_nivel_leyenda",
                "qué_evalúa": "Consistencia de clase, viabilidad país-clase, claridad semántica y nivel de leyenda.",
                "cómo_se_interpreta": "Valores altos indican clases consistentes, no residuales, con buena representación y leyenda suficientemente clara.",
            },
            {
                "criterio": "Espectral",
                "campo_score": "score_espectral",
                "valores_o_campos_usados": "audit_extract_units_s2sr_annual; spectral_alert_level_max; pct_extract_units_*; s2yr_*",
                "qué_evalúa": "Coherencia espectral Sentinel-2 SR agregada por xy_group_id.",
                "cómo_se_interpreta": "Valores altos indican señal espectral coherente. Valores bajos indican alertas, baja disponibilidad, ausencia de datos o necesidad de revisión.",
            },
            {
                "criterio": "Confiabilidad",
                "campo_score": "score_confiabilidad",
                "valores_o_campos_usados": "conf_integrada observada; promedio por XY; valor neutral solo en grupos sin observación",
                "qué_evalúa": "Confianza documental o temática integrada en los registros originales.",
                "cómo_se_interpreta": "El reporte distingue valores observados de valores neutrales imputados. La ejecución falla si todos los grupos quedan imputados, salvo autorización explícita.",
            },
            {
                "criterio": "Representatividad",
                "campo_score": "score_representatividad",
                "valores_o_campos_usados": "estado_pais_clase; representativity_scores",
                "qué_evalúa": "Suficiencia de registros por país y clase.",
                "cómo_se_interpreta": "Valores altos indican combinaciones país-clase bien representadas. Valores bajos indican vacíos o clases escasas.",
            },
            {
                "criterio": "Fuente",
                "campo_score": "score_fuente",
                "valores_o_campos_usados": "id_fuente; Tipo; catálogo documental; medio de obtención; consistencia entre Año y años documentados; promedio de fuentes únicas por XY",
                "qué_evalúa": "Directitud del dato, trazabilidad de obtención y calidad temporal de los metadatos de la fuente.",
                "cómo_se_interpreta": "Se calcula antes de la clasificación final. Cada fuente cuenta una sola vez dentro de cada grupo XY; no se pondera por filas repetidas ni reutiliza scores temáticos, espaciales, espectrales o de confiabilidad.",
            },
        ]
    )


def weights_table(cfg: dict[str, Any]) -> pd.DataFrame:
    weights = cfg.get("weights_xy", {})

    return pd.DataFrame(
        [
            {"criterio": "Temporal", "clave_config": "temporal", "peso": weights.get("temporal", "")},
            {"criterio": "Espacial", "clave_config": "spatial", "peso": weights.get("spatial", "")},
            {"criterio": "Temático", "clave_config": "thematic", "peso": weights.get("thematic", "")},
            {"criterio": "Espectral", "clave_config": "spectral", "peso": weights.get("spectral", "")},
            {"criterio": "Confiabilidad", "clave_config": "confidence", "peso": weights.get("confidence", "")},
            {"criterio": "Representatividad", "clave_config": "representativity", "peso": weights.get("representativity", "")},
            {"criterio": "Fuente", "clave_config": "source", "peso": weights.get("source", "")},
        ]
    )


def caps_table(cfg: dict[str, Any]) -> pd.DataFrame:
    caps_cfg = cfg.get("caps", {})

    return pd.DataFrame(
        [
            {
                "regla": "Alerta espectral alta",
                "condición": "spectral_alert_level_max == alta",
                "tope_aplicado": caps_cfg.get("spectral_alert_high", ""),
                "cap_reason": "alerta_espectral_alta",
            },
            {
                "regla": "Sin datos espectrales",
                "condición": "spectral_alert_level_max == alta_sin_datos",
                "tope_aplicado": caps_cfg.get("spectral_no_data", ""),
                "cap_reason": "sin_datos_espectrales",
            },
            {
                "regla": "Clase residual",
                "condición": "flag_clase_residual == 1",
                "tope_aplicado": caps_cfg.get("residual_class", ""),
                "cap_reason": "clase_residual",
            },
            {
                "regla": "Pais multiple o inconsistente",
                "condición": "pais_grupo == multipais_o_inconsistente",
                "tope_aplicado": caps_cfg.get("multipais_inconsistent", ""),
                "cap_reason": "multipais_o_inconsistente",
            },
        ]
    )


def cap_summary_table(master: pd.DataFrame) -> pd.DataFrame:
    if "cap_reason" not in master.columns:
        return pd.DataFrame()

    out = (
        master.assign(cap_reason_clean=master["cap_reason"].replace("", "sin_tope"))
        .groupby("cap_reason_clean")
        .agg(
            n_grupos=("xy_group_id", "count"),
            score_promedio=("score_aptitud_total", "mean"),
            score_raw_promedio=("score_aptitud_raw", "mean"),
        )
        .reset_index()
        .sort_values("n_grupos", ascending=False)
    )

    for col in ["score_promedio", "score_raw_promedio"]:
        out[col] = out[col].round(3)

    out["pct_grupos"] = (out["n_grupos"] / out["n_grupos"].sum() * 100).round(3)

    return out


def spectral_summary_table(master: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "n_extract_units_spectral",
        "pct_extract_units_sin_alerta",
        "pct_extract_units_alerta_baja",
        "pct_extract_units_alerta_media",
        "pct_extract_units_alerta_alta",
        "pct_extract_units_baja_disponibilidad",
        "pct_extract_units_sin_datos",
        "pct_extract_units_revision_espectral",
        "s2yr_months_obs_median",
        "s2yr_obs_total_median",
        "s2yr_cloudprob_median",
        "s2yr_ndvi_median",
        "s2yr_ndre_median",
        "score_espectral",
    ]

    rows = []

    for col in fields:
        if col not in master.columns:
            continue

        s = pd.to_numeric(master[col], errors="coerce")
        rows.append(
            {
                "campo": col,
                "media": round(float(s.mean()), 3),
                "mediana": round(float(s.median()), 3),
                "min": round(float(s.min()), 3),
                "max": round(float(s.max()), 3),
                "n_validos": int(s.notna().sum()),
            }
        )

    return pd.DataFrame(rows)


def state_by_criteria_table(master: pd.DataFrame) -> pd.DataFrame:
    score_cols = existing(
        master,
        [
            "score_aptitud_total",
            "score_aptitud_raw",
            "score_temporal",
            "score_espacial",
            "score_tematico",
            "score_espectral",
            "score_confiabilidad",
            "score_representatividad",
            "score_fuente",
        ],
    )

    agg = {
        "n_grupos": ("xy_group_id", "count"),
        "n_registros": ("n_registros", "sum"),
    }

    for col in score_cols:
        agg[f"{col}_promedio"] = (col, "mean")

    group_cols = ["categoria_aptitud_preliminar", "categoria_uso_actividad_1_8"]

    out = (
        master.groupby(group_cols)
        .agg(**agg)
        .reset_index()
        .sort_values("n_grupos", ascending=False)
    )

    for col in out.columns:
        if col.endswith("_promedio"):
            out[col] = out[col].round(3)

    return out


def state_spectral_alert_table(master: pd.DataFrame) -> pd.DataFrame:
    """
    Resume el cruce entre la categoría final de aptitud y la alerta espectral.

    Esta función usa los nombres nuevos:
    - categoria_aptitud_preliminar
    - categoria_uso_actividad_1_8

    No usa `estado_funcional_preliminar`, que pertenecía a versiones anteriores.
    """
    if "spectral_alert_level_max" not in master.columns:
        return pd.DataFrame()

    required = [
        "categoria_aptitud_preliminar",
        "categoria_uso_actividad_1_8",
        "spectral_alert_level_max",
    ]

    missing = [c for c in required if c not in master.columns]

    if missing:
        raise ValueError(
            "Faltan columnas requeridas para el cruce categoría-alerta espectral: "
            f"{missing}"
        )

    out = (
        master.groupby(
            [
                "categoria_aptitud_preliminar",
                "categoria_uso_actividad_1_8",
                "spectral_alert_level_max",
            ],
            dropna=False,
        )
        .agg(
            n_grupos=("xy_group_id", "count"),
            score_promedio=("score_aptitud_total", "mean"),
        )
        .reset_index()
        .sort_values(
            ["categoria_aptitud_preliminar", "categoria_uso_actividad_1_8", "n_grupos"],
            ascending=[True, True, False],
        )
    )

    out["score_promedio"] = out["score_promedio"].round(3)

    return out


def write_report(
    master: pd.DataFrame,
    ranking: pd.DataFrame,
    gap: pd.DataFrame,
    review: pd.DataFrame,
    scen: pd.DataFrame,
    audit: dict[str, Any],
    cfg: dict[str, Any],
) -> None:
    """
    Escribe el reporte Markdown del Módulo 10.

    Incluye:
    - resumen de auditoría,
    - definición de criterios del score,
    - categorías finales de aptitud,
    - homologación hacia Actividad 1.8,
    - resumen general por categoría,
    - resumen específico por país,
    - resumen país-clase,
    - resumen país-fuente,
    - resumen espectral por país,
    - ranking de fuentes,
    - vacíos país-clase,
    - casos de revisión / apoyo / máscaras.
    """
    REP.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # Tablas generales ya existentes
    # -------------------------------------------------------------------------
    state = state_by_criteria_table(master)
    criteria_overall = criteria_overall_table(master, cfg)
    confidence_summary = confidence_summary_table(master, audit)
    source_summary = source_summary_table(master, audit)
    score_dist = score_distribution_table(master)
    cap_summary = cap_summary_table(master)
    spectral_summary = spectral_summary_table(master)
    state_alert = state_spectral_alert_table(master)

    score_formula_df = pd.DataFrame(
        [
            {
                "score": "score_aptitud_raw",
                "formula": (
                    "w_temporal*score_temporal + "
                    "w_spatial*score_espacial + "
                    "w_thematic*score_tematico + "
                    "w_spectral*score_espectral + "
                    "w_confidence*score_confiabilidad + "
                    "w_representativity*score_representatividad + "
                    "w_source*score_fuente"
                ),
            },
            {
                "score": "score_aptitud_total",
                "formula": "min(score_aptitud_raw, score_cap)",
            },
        ]
    )

    # -------------------------------------------------------------------------
    # Helper local para detectar columna país
    # -------------------------------------------------------------------------
    def _country_col(df: pd.DataFrame) -> str | None:
        for col in ["pais_grupo", "pais_dominante", "pais"]:
            if col in df.columns:
                return col
        return None

    country_col = _country_col(master)

    # -------------------------------------------------------------------------
    # Resumen por país
    # -------------------------------------------------------------------------
    if country_col:
        country_summary = (
            master.groupby(country_col, dropna=False)
            .agg(
                n_grupos_xy=("xy_group_id", "count"),
                n_registros=("n_registros", "sum"),
                n_fuentes=("fuente_dominante", "nunique"),
                n_clases_nivel_1=("nivel_1_dominante", "nunique"),
                n_clases_nivel_2=("nivel_2_dominante", "nunique"),
                score_total_promedio=("score_aptitud_total", "mean"),
                score_temporal_promedio=("score_temporal", "mean"),
                score_espacial_promedio=("score_espacial", "mean"),
                score_tematico_promedio=("score_tematico", "mean"),
                score_espectral_promedio=("score_espectral", "mean"),
                score_confiabilidad_promedio=("score_confiabilidad", "mean"),
                score_representatividad_promedio=("score_representatividad", "mean"),
                pct_conflicto_activo=(
                    "flag_conflicto_activo",
                    lambda s: 100 * pd.to_numeric(s, errors="coerce").fillna(0).eq(1).mean(),
                ),
                pct_alerta_espectral_alta=(
                    "spectral_alert_level_max",
                    lambda s: 100
                    * s.astype(str)
                    .str.lower()
                    .isin(["alta", "alta_sin_datos"])
                    .mean(),
                ),
            )
            .reset_index()
            .rename(columns={country_col: "pais"})
            .sort_values("n_grupos_xy", ascending=False)
        )

        for col in country_summary.columns:
            if col.startswith("score_") or col.startswith("pct_"):
                country_summary[col] = pd.to_numeric(
                    country_summary[col],
                    errors="coerce",
                ).round(3)

        # Uso Actividad 1.8 por país
        if "categoria_uso_actividad_1_8" in master.columns:
            country_use = (
                master.groupby(["pais_grupo" if "pais_grupo" in master.columns else country_col, "categoria_uso_actividad_1_8"], dropna=False)
                .agg(
                    n_grupos_xy=("xy_group_id", "count"),
                    n_registros=("n_registros", "sum"),
                    score_promedio=("score_aptitud_total", "mean"),
                )
                .reset_index()
                .rename(columns={("pais_grupo" if "pais_grupo" in master.columns else country_col): "pais"})
                .sort_values(["pais", "n_grupos_xy"], ascending=[True, False])
            )

            country_use["score_promedio"] = pd.to_numeric(
                country_use["score_promedio"],
                errors="coerce",
            ).round(3)

            total_country = (
                country_use.groupby("pais")["n_grupos_xy"]
                .sum()
                .reset_index()
                .rename(columns={"n_grupos_xy": "total_pais"})
            )

            country_use = country_use.merge(total_country, on="pais", how="left")
            country_use["pct_grupos_pais"] = (
                country_use["n_grupos_xy"] / country_use["total_pais"] * 100
            ).round(3)

        else:
            country_use = pd.DataFrame()

        # Categoría final por país
        if "categoria_aptitud_preliminar" in master.columns:
            country_category = (
                master.groupby(["pais_grupo" if "pais_grupo" in master.columns else country_col, "categoria_aptitud_preliminar"], dropna=False)
                .agg(
                    n_grupos_xy=("xy_group_id", "count"),
                    n_registros=("n_registros", "sum"),
                    score_promedio=("score_aptitud_total", "mean"),
                )
                .reset_index()
                .rename(columns={("pais_grupo" if "pais_grupo" in master.columns else country_col): "pais"})
                .sort_values(["pais", "n_grupos_xy"], ascending=[True, False])
            )

            country_category["score_promedio"] = pd.to_numeric(
                country_category["score_promedio"],
                errors="coerce",
            ).round(3)

        else:
            country_category = pd.DataFrame()

        # Resumen espectral por país
        country_spectral_cols = [
            c
            for c in [
                "n_extract_units_spectral",
                "pct_extract_units_sin_alerta",
                "pct_extract_units_alerta_baja",
                "pct_extract_units_alerta_media",
                "pct_extract_units_alerta_alta",
                "pct_extract_units_baja_disponibilidad",
                "pct_extract_units_sin_datos",
                "pct_extract_units_revision_espectral",
                "s2yr_months_obs_median",
                "s2yr_obs_total_median",
                "s2yr_cloudprob_median",
                "s2yr_ndvi_median",
                "s2yr_ndre_median",
                "score_espectral",
            ]
            if c in master.columns
        ]

        if country_spectral_cols:
            agg_spectral = {
                "n_grupos_xy": ("xy_group_id", "count"),
            }

            for col in country_spectral_cols:
                agg_spectral[f"{col}_promedio"] = (col, "mean")

            country_spectral = (
                master.groupby(country_col, dropna=False)
                .agg(**agg_spectral)
                .reset_index()
                .rename(columns={country_col: "pais"})
                .sort_values("n_grupos_xy", ascending=False)
            )

            for col in country_spectral.columns:
                if col != "pais":
                    country_spectral[col] = pd.to_numeric(
                        country_spectral[col],
                        errors="coerce",
                    ).round(3)

        else:
            country_spectral = pd.DataFrame()

        # Resumen país-fuente
        country_source = (
            master[
                master["fuente_dominante"].notna()
                & pd.to_numeric(master["n_registros"], errors="coerce").fillna(0).gt(0)
            ]
            .groupby([country_col, "fuente_dominante"], dropna=False)
            .agg(
                n_grupos_xy=("xy_group_id", "count"),
                n_registros=("n_registros", "sum"),
                n_clases_nivel_1=("nivel_1_dominante", "nunique"),
                score_total_promedio=("score_aptitud_total", "mean"),
                score_espectral_promedio=("score_espectral", "mean"),
                pct_alerta_espectral_alta=(
                    "spectral_alert_level_max",
                    lambda s: 100
                    * s.astype(str)
                    .str.lower()
                    .isin(["alta", "alta_sin_datos"])
                    .mean(),
                ),
            )
            .reset_index()
            .rename(columns={country_col: "pais"})
            .sort_values(["pais", "n_grupos_xy"], ascending=[True, False])
        )

        for col in [
            "score_total_promedio",
            "score_espectral_promedio",
            "pct_alerta_espectral_alta",
        ]:
            country_source[col] = pd.to_numeric(
                country_source[col],
                errors="coerce",
            ).round(3)

    else:
        country_summary = pd.DataFrame()
        country_use = pd.DataFrame()
        country_category = pd.DataFrame()
        country_spectral = pd.DataFrame()
        country_source = pd.DataFrame()

    # -------------------------------------------------------------------------
    # Resumen de vacíos país-clase
    # -------------------------------------------------------------------------
    if not gap.empty and {"pais", "estado_pais_clase"}.issubset(gap.columns):
        country_gap_summary = (
            gap.groupby(["pais", "estado_pais_clase"], dropna=False)
            .agg(
                n_clases=("clase", "count"),
                n_registros_total=("n_registros_2018_2022", "sum"),
                score_necesidad_promedio=("score_necesidad_complementacion", "mean"),
                score_necesidad_max=("score_necesidad_complementacion", "max"),
            )
            .reset_index()
            .sort_values(["pais", "score_necesidad_max"], ascending=[True, False])
        )

        for col in ["score_necesidad_promedio", "score_necesidad_max"]:
            country_gap_summary[col] = pd.to_numeric(
                country_gap_summary[col],
                errors="coerce",
            ).round(3)

    else:
        country_gap_summary = pd.DataFrame()

    # -------------------------------------------------------------------------
    # Líneas del reporte
    # -------------------------------------------------------------------------
    lines = [
        "# Scoring multicriterio de aptitud preliminar",
        "",
        "Ventana 2018-2022. Score temporal: 2020=100; 2019/2021=90; 2018/2022=85.",
        "",
        "## Resumen de auditoría",
        "",
        md(pd.DataFrame([audit])),
        "",
        "## Ubicación de salidas",
        "",
        f"CSV principales: `{OUT}`",
        "",
        f"GeoPackage principal: `{SCORING_GPKG}`",
        "",
        "## Interpretación general del resultado",
        "",
        "Este módulo no clasifica los grupos XY usando un único criterio. La aptitud final se calcula mediante un score multicriterio que combina evidencia temporal, espacial, temática, espectral, de confiabilidad, representatividad y fuente.",
        "",
        "Las categorías de salida ya están nombradas directamente según su uso previsto en la Actividad 1.8. No se trata de una equivalencia posterior con nombres antiguos: el campo `categoria_aptitud_preliminar` es la categoría final del Módulo 10 y `categoria_uso_actividad_1_8` homologa esa categoría hacia entrenamiento, validación, prueba, apoyo interpretativo, máscaras o referencia contextual.",
        "",
        "El componente espectral es importante, pero no decide por sí solo. Funciona como una dimensión adicional de calidad y, cuando presenta alertas fuertes, puede activar categorías de apoyo interpretativo o aplicar topes al score final.",
        "",
        "El componente de fuente se calcula antes de las categorías finales mediante un catálogo documental. Evalúa directitud, trazabilidad y consistencia temporal, y cada fuente cuenta una sola vez dentro de cada grupo XY.",
        "",
        "## Fórmula del score",
        "",
        md(score_formula_df),
        "",
        "## Criterios usados en el score multicriterio",
        "",
        md(criteria_description_table()),
        "",
        "## Definición de categorías finales de aptitud y uso Actividad 1.8",
        "",
        md(usage_category_definitions()),
        "",
        "## Definición de categorías de fuente",
        "",
        md(source_usage_definitions()),
        "",
        "## Pesos configurados para el score por grupo XY",
        "",
        md(weights_table(cfg)),
        "",
        "## Auditoría del componente de confiabilidad",
        "",
        "Esta tabla separa la confianza realmente observada de los grupos que recibieron el valor neutral por ausencia de información.",
        "",
        md(confidence_summary),
        "",
        "## Auditoría del componente de fuente",
        "",
        "El score de fuente no usa oficialidad institucional, restricción de uso, confiabilidad integrada ni el resultado posterior de entrenamiento/validación. Tampoco se pondera por el número de filas repetidas de una fuente multitemporal.",
        "",
        md(source_summary),
        "",
        "## Resumen estadístico por criterio",
        "",
        md(criteria_overall),
        "",
        "## Distribución del score total",
        "",
        md(score_dist),
        "",
        "## Categorías finales y promedios por criterio",
        "",
        md(state),
        "",
        "## Reglas de tope aplicadas al score",
        "",
        md(caps_table(cfg)),
        "",
        "## Resumen de topes aplicados",
        "",
        md(cap_summary),
        "",
        "## Resumen del componente espectral",
        "",
        md(spectral_summary),
        "",
        "## Cruce entre categoría final y alerta espectral",
        "",
        md(state_alert),
    ]

    # -------------------------------------------------------------------------
    # Sección país
    # -------------------------------------------------------------------------
    if country_col:
        lines.extend(
            [
                "",
                "## Resumen por país",
                "",
                "Esta sección resume el comportamiento del score y de las categorías finales por país. Permite identificar países con mayor volumen de datos aptos, países dominados por categorías de apoyo/revisión y diferencias entre criterios.",
                "",
                "### Síntesis general por país",
                "",
                md(country_summary),
                "",
                "### Uso homologado Actividad 1.8 por país",
                "",
                md(country_use),
                "",
                "### Categorías finales de aptitud por país",
                "",
                md(country_category),
                "",
                "### Componente espectral por país",
                "",
                md(country_spectral),
                "",
                "### Principales fuentes por país",
                "",
                md(country_source.head(80)),
            ]
        )

    # -------------------------------------------------------------------------
    # Vacíos país-clase
    # -------------------------------------------------------------------------
    lines.extend(
        [
            "",
            "## Resumen de vacíos país-clase",
            "",
            "Esta sección resume las combinaciones país-clase con menor disponibilidad. Es útil para orientar complementación de datos, revisión dirigida o estrategias de balance antes del entrenamiento.",
            "",
            md(country_gap_summary),
            "",
            "## Nota sobre duplicados espectrales",
            "",
            "El componente espectral se integró desde `audit_extract_units_s2sr_annual`, es decir, desde la capa sin duplicados por `extract_id`.",
            "",
            "Esto no elimina observaciones de años diferentes. Un mismo punto en 2020 y 2021 se conserva como dos unidades temporales distintas si tiene `extract_id` diferente. La eliminación de duplicados solo evita contar dos veces la misma unidad de extracción espectral.",
            "",
            "La capa completa `audit_original_records_s2sr_annual` se conserva para trazabilidad de registros originales, pero no se usa como insumo principal del score espectral agregado.",
            "",
            "## Escenarios",
            "",
            md(scen),
            "",
            "## Ranking de fuentes",
            "",
            md(ranking.head(30)),
            "",
            "## Vacíos país-clase",
            "",
            md(gap.head(40)),
            "",
            "## Revisión, apoyo interpretativo y máscaras",
            "",
            md(review.head(40)),
        ]
    )

    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def export_outputs(
    records: pd.DataFrame,
    master: pd.DataFrame,
    ranking: pd.DataFrame,
    gap: pd.DataFrame,
    review: pd.DataFrame,
    scen: pd.DataFrame,
    audit: dict[str, Any],
    write_sqlite: bool,
) -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    master.to_csv(
        MASTER_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    ranking.to_csv(
        SOURCE_RANKING_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    record_flag_cols = [
        "source_rowid",
        "xy_group_id",
        "lon",
        "lat",
        "anio",
        "pais",
        "id_fuente",
        "fuente",
        "tipo_fuente",
        "detalle_tipo_fuente",
        "id_origen",
        "score_directitud",
        "score_trazabilidad",
        "score_consistencia_temporal_fuente",
        "score_fuente_base",
        "flag_anio_fuente_informado",
        "flag_anio_fuente_consistente",
        "flag_nombre_fuente_inconsistente",
        "flag_tipo_fuente_inconsistente",
        "flag_pais_fuente_inconsistente",
        "nivel_0",
        "nivel_1",
        "nivel_2",
        "conf_integrada",
        "conf_integrada_score_observado",
        "conf_integrada_observada",
        "score_temporal_registro",
        "estado_registro_scoring",
    ]

    records[
        [c for c in record_flag_cols if c in records.columns]
    ].to_csv(
        RECORD_FLAGS_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    gap.to_csv(
        GAP_PRIORITY_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    review.to_csv(
        REVIEW_CASES_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    scen.to_csv(
        SCENARIOS_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    pd.DataFrame([audit]).to_csv(
        AUDIT_SUMMARY_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    write_gpkg_outputs(
        master=master,
        ranking=ranking,
        gap=gap,
        review=review,
        scen=scen,
        audit=audit,
        records=records[[c for c in record_flag_cols if c in records.columns]],
    )

    if write_sqlite:
        with sqlite3.connect(SCORING_DB) as out:
            master.to_sql(
                "xy_group_aptitude_master",
                out,
                if_exists="replace",
                index=False,
            )

            ranking.to_sql(
                "source_aptitude_ranking",
                out,
                if_exists="replace",
                index=False,
            )

            records[
                [c for c in record_flag_cols if c in records.columns]
            ].to_sql(
                "record_aptitude_flags",
                out,
                if_exists="replace",
                index=False,
            )

            gap.to_sql(
                "gap_priority_country_class",
                out,
                if_exists="replace",
                index=False,
            )

            review.to_sql(
                "review_priority_cases",
                out,
                if_exists="replace",
                index=False,
            )

            scen.to_sql(
                "selection_scenarios_summary",
                out,
                if_exists="replace",
                index=False,
            )

            pd.DataFrame([audit]).to_sql(
                "scoring_audit_summary",
                out,
                if_exists="replace",
                index=False,
            )


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--write-sqlite", action="store_true")
    parser.add_argument(
        "--recreate-outputs",
        type=str_to_bool,
        default=RECREATE_OUTPUTS_DEFAULT,
        metavar="true|false",
        help=(
            "True = recalcula todo y sobrescribe salidas. "
            "False = si las salidas ya existen, las reutiliza y solo regenera el Markdown. "
            f"Default: {RECREATE_OUTPUTS_DEFAULT}."
        ),
    )
    parser.add_argument(
        "--allow-missing-spectral",
        action="store_true",
        help=(
            "Permite continuar aunque existan xy_group_id sin componente espectral. "
            "Por defecto el proceso falla si falta cobertura espectral."
        ),
    )
    parser.add_argument(
        "--allow-missing-confidence",
        action="store_true",
        help=(
            "Permite continuar sin ninguna confianza observada e imputar el valor "
            "neutral. Por defecto la ejecución falla para evitar un 70 constante "
            "publicado como si fuera información observada."
        ),
    )
    args = parser.parse_args()

    mkdirs()

    cfg = load_cfg(Path(args.config))

    # -------------------------------------------------------------------------
    # Modo rápido: si ya existen resultados y no se pide reprocesar, no se
    # repite el proceso pesado. Solo se reconstruye el Markdown mejorado.
    # -------------------------------------------------------------------------
    if all(path.exists() for path in output_csv_paths()) and not SCORING_GPKG.exists() and not args.recreate_outputs:
        print("CSV existentes detectados, pero falta el GeoPackage del Módulo 10.")
        print("Validando CSV y regenerando únicamente el GPKG y el Markdown...")

        master, ranking, gap, review, scen, audit = read_existing_outputs()
        outputs_are_valid, output_problems = validate_existing_outputs(master, audit)

        if outputs_are_valid:
            write_gpkg_outputs_from_csv()
            write_report(
                master=master,
                ranking=ranking,
                gap=gap,
                review=review,
                scen=scen,
                audit=audit,
                cfg=cfg,
            )
            print("GeoPackage generado:", SCORING_GPKG)
            print("Reporte regenerado:", REPORT_MD)
            return

        print("Los CSV existentes son antiguos o incompatibles. Se ejecutará el pipeline completo.")
        for problem in output_problems:
            print(" -", problem)

        if CLEAN_OUTPUTS_BEFORE_RECREATE_DEFAULT:
            print("Eliminando salidas antiguas del Módulo 10...")
            clean_previous_outputs()

    if outputs_exist() and not args.recreate_outputs:
        print("Salidas existentes detectadas. Validando si corresponden a la versión actual...")

        master, ranking, gap, review, scen, audit = read_existing_outputs()
        outputs_are_valid, output_problems = validate_existing_outputs(master, audit)

        if outputs_are_valid:
            print("Las salidas existentes son compatibles. No se recalcula el pipeline completo.")
            print("Se regenerará únicamente el reporte Markdown con los CSV existentes.")
            print("Para recalcular todo manualmente, ejecutar con --recreate-outputs true.")

            write_report(
                master=master,
                ranking=ranking,
                gap=gap,
                review=review,
                scen=scen,
                audit=audit,
                cfg=cfg,
            )

            if args.write_sqlite:
                print("Actualizando SQLite desde CSV existentes...")
                write_sqlite_outputs_from_csv()

            log(
                "Módulo 10 reutilizó salidas existentes compatibles y regeneró reporte. "
                f"Reporte={REPORT_MD}"
            )

            print("Reporte regenerado:", REPORT_MD)
            return

        print("Las salidas existentes son antiguas o incompatibles con la versión actual.")
        print("Se ejecutará el pipeline completo automáticamente.")
        print("Problemas detectados:")
        for problem in output_problems:
            print(" -", problem)

        if CLEAN_OUTPUTS_BEFORE_RECREATE_DEFAULT:
            print("Eliminando salidas antiguas del Módulo 10...")
            clean_previous_outputs()

    elif args.recreate_outputs and CLEAN_OUTPUTS_BEFORE_RECREATE_DEFAULT:
        print("--recreate-outputs true activo. Eliminando salidas previas del Módulo 10...")
        clean_previous_outputs()

    missing = missing_output_paths()
    if missing:
        print("No se encontraron todas las salidas previas. Se ejecutará el pipeline completo.")
        print("Salidas faltantes:")
        for path in missing:
            print(" -", path)

    if not DB.exists():
        raise FileNotFoundError(f"No existe {DB}")

    conn = sqlite3.connect(DB)

    try:
        if not table_exists(conn, "thematic_base") or not table_exists(conn, "xy_subset_agg"):
            raise ValueError(
                "La base 05_thematic_audit.sqlite debe contener thematic_base y xy_subset_agg."
            )

        print("Leyendo registros 2018-2022...")
        base = read_base(conn, cfg)

        print("Leyendo grupos XY...")
        xy = read_xy(conn, cfg)

        print("Asociando registros a xy_group_id...")
        records = attach_xy_group_id(base, xy)
        records = add_record_scores(records, cfg)

        print("Validando catálogo y calculando score previo de fuente...")
        records, source_profile, source_meta = prepare_source_records(records, cfg)

        print("Validando y normalizando confiabilidad...")
        records, confidence_meta = prepare_confidence_records(
            records,
            cfg,
            allow_missing=args.allow_missing_confidence,
        )

        print("Agregando registros por xy_group_id...")
        group = aggregate_records_to_xy(records, cfg)

        xy_cols = [
            c
            for c in [
                "xy_group_id",
                "lon",
                "lat",
                "pais_grupo",
                "estado_xy_subset",
                "tipo_grupo_original",
                "n_registros_original",
                "n_registros_subset",
            ]
            if c in xy.columns
        ]

        master_xy = xy[xy_cols].drop_duplicates("xy_group_id").copy()
        master_xy["xy_group_id"] = master_xy["xy_group_id"].astype("string")

        print("Leyendo componente espectral del Módulo 09 sin duplicados...")
        spec_units, spectral_meta = read_spectral_units()

        print("Agregando componente espectral por xy_group_id...")
        spectral_by_xy = make_spectral_by_xy(spec_units)

        print("Validando cobertura espectral...")
        coverage_audit = validate_spectral_coverage(
            master_xy=master_xy,
            spectral_by_xy=spectral_by_xy,
            allow_missing=args.allow_missing_spectral,
        )

        print(
            "Cobertura espectral por xy_group_id:",
            f"{coverage_audit['spectral_xy_coverage_pct']}%",
        )

        master = (
            master_xy
            .merge(group, on="xy_group_id", how="left")
            .merge(spectral_by_xy, on="xy_group_id", how="left")
        )

        if args.allow_missing_spectral:
            spectral_fill_defaults = {
                "n_extract_units_spectral": 0,
                "n_spectral_rows": 0,
                "spectral_severity_order_max": 0,
                "spectral_alert_count_sum": 0,
                "pct_extract_units_sin_alerta": 100.0,
                "pct_extract_units_alerta_baja": 0.0,
                "pct_extract_units_alerta_media": 0.0,
                "pct_extract_units_alerta_alta": 0.0,
                "pct_extract_units_baja_disponibilidad": 0.0,
                "pct_extract_units_sin_datos": 0.0,
                "pct_extract_units_revision_espectral": 0.0,
                "score_espectral": 70.0,
                "spectral_alert_level_max": "sin_alerta",
            }

            for col, default in spectral_fill_defaults.items():
                if col not in master.columns:
                    master[col] = default
                else:
                    master[col] = master[col].fillna(default)

        confidence_xy_meta = validate_confidence_master(
            master,
            cfg,
            allow_missing=args.allow_missing_confidence,
        )
        source_xy_meta = validate_source_master(master, cfg)

        master = add_country_class(master, records)
        master = merge_conflicts(master)
        master = assign_states(compute_scores(master, cfg), cfg)

        ranking = source_ranking(master, cfg, source_profile)
        gap = gap_priority(records)

        review = master[
            master["categoria_uso_actividad_1_8"].isin(
                [
                    "apoyo interpretativo",
                    "referencia contextual",
                    "máscaras",
                ]
            )
        ].copy()

        scen = scenarios(master)

        audit = {
            "target_year": cfg["scoring"]["target_year"],
            "window_start": cfg["scoring"]["window_start"],
            "window_end": cfg["scoring"]["window_end"],
            "n_registros_ventana": int(len(records)),
            "n_grupos_xy_ventana": int(master["xy_group_id"].nunique()),
            "n_fuentes": int(records["fuente"].nunique()),
            "n_paises": int(records["pais"].nunique()),
            **confidence_meta,
            **confidence_xy_meta,
            **source_meta,
            **source_xy_meta,
            "spectral_file": spectral_meta.get("spectral_file", ""),
            "spectral_layer": spectral_meta.get("spectral_layer", ""),
            "spectral_status": spectral_meta.get("spectral_status", ""),
            "spectral_join_key": "xy_group_id",
            "n_spectral_units_loaded": spectral_meta.get("n_spectral_units_loaded", 0),
            "n_spectral_xy_loaded": spectral_meta.get("n_spectral_xy_loaded", 0),
            "n_xy_groups_joined_spectral": int(
                master["n_extract_units_spectral"].notna().sum()
            ),
            "n_xy_groups_missing_spectral": coverage_audit["n_xy_groups_missing_spectral"],
            "spectral_xy_coverage_pct": coverage_audit["spectral_xy_coverage_pct"],
            "deduplication_rule": (
                "Se usa audit_extract_units_s2sr_annual: una fila por extract_id. "
                "No elimina años distintos; elimina repeticiones exactas de la misma unidad de extracción espectral."
            ),
        }

        print("Exportando salidas...")
        export_outputs(
            records=records,
            master=master,
            ranking=ranking,
            gap=gap,
            review=review,
            scen=scen,
            audit=audit,
            write_sqlite=args.write_sqlite,
        )

        write_report(
            master=master,
            ranking=ranking,
            gap=gap,
            review=review,
            scen=scen,
            audit=audit,
            cfg=cfg,
        )

        log(
            "Etapa 1.7 ejecutada correctamente. "
            f"Registros={len(records)}; "
            f"grupos={master['xy_group_id'].nunique()}; "
            f"spectral_status={spectral_meta.get('spectral_status', '')}; "
            f"spectral_layer={spectral_meta.get('spectral_layer', '')}; "
            f"spectral_xy_coverage_pct={coverage_audit['spectral_xy_coverage_pct']}"
        )

        print("Etapa 1.7 ejecutada correctamente.")
        print(f"Registros ventana: {len(records):,}")
        print(f"Grupos XY: {master['xy_group_id'].nunique():,}")
        print(f"Insumo espectral: {spectral_meta.get('spectral_status', '')}")
        print(f"Capa espectral: {spectral_meta.get('spectral_layer', '')}")
        print("Join espectral: xy_group_id")
        print(f"Cobertura espectral XY: {coverage_audit['spectral_xy_coverage_pct']}%")
        print("Salidas CSV:", OUT)
        print("Salida GPKG:", SCORING_GPKG)
        print("Reporte:", REPORT_MD)

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("Error durante la ejecución de la Etapa 1.7 / Módulo 10.")
        traceback.print_exc()
        raise
