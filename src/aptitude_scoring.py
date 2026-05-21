
from __future__ import annotations

import argparse
import sqlite3
import traceback
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

DB = ROOT / "data" / "interim" / "05_thematic_audit.sqlite"
SCORING_DB = ROOT / "data" / "interim" / "10_scoring_aptitud.sqlite"

OUT = ROOT / "outputs" / "tables"
REP = ROOT / "outputs" / "reports"
LOG = ROOT / "logs"

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


# =============================================================================
# UTILIDADES GENERALES
# =============================================================================

def mkdirs() -> None:
    for p in [OUT, REP, LOG, SCORING_DB.parent]:
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
        "fuente",
        "nivel_0",
        "nivel_1",
        "nivel_2",
    ]

    available = cols(conn, "thematic_base")
    missing = [c for c in required if c not in available]

    if missing:
        raise ValueError(f"thematic_base no contiene columnas requeridas: {missing}")

    optional = [
        c
        for c in ["conf_integrada", "conf_ndvi", "conf_cobertura", "conf_altura"]
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
    Asocia cada registro de thematic_base a xy_group_id usando lon/lat redondeados.
    Esto evita fallos por diferencias pequeñas de precisión.
    """
    rec = normalize_xy_join_fields(records, "lon", "lat")
    xyj = normalize_xy_join_fields(xy, "lon", "lat")

    xy_keep = (
        xyj[["xy_group_id", "_lon_join", "_lat_join"]]
        .drop_duplicates(["_lon_join", "_lat_join"])
        .copy()
    )

    out = rec.merge(xy_keep, on=["_lon_join", "_lat_join"], how="left")
    out = out.drop(columns=["_lon_join", "_lat_join"], errors="ignore")

    missing = int(out["xy_group_id"].isna().sum())

    if missing:
        raise ValueError(
            f"{missing:,} registros no pudieron asociarse a xy_group_id "
            "mediante lon/lat. Revise precisión de coordenadas entre thematic_base y xy_subset_agg."
        )

    out["xy_group_id"] = out["xy_group_id"].astype("string")

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

    if "conf_integrada" in rec.columns:
        conf = pd.to_numeric(rec["conf_integrada"], errors="coerce")

        rec["conf_integrada_score"] = (
            conf * 100
            if len(conf.dropna()) and conf.dropna().quantile(0.95) <= 1.5
            else conf
        )

        rec["conf_integrada_score"] = rec["conf_integrada_score"].clip(0, 100)

    else:
        rec["conf_integrada_score"] = 70.0

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
            n_fuentes=("fuente", "nunique"),
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
            fuente_dominante=("fuente", mode),
            nivel_0_dominante=("nivel_0", mode),
            nivel_1_dominante=("nivel_1", mode),
            nivel_2_dominante=("nivel_2", mode),
            valores_nivel_0=("nivel_0", concat),
            valores_nivel_1=("nivel_1", concat),
            valores_nivel_2=("nivel_2", concat),
            n_nivel0=("nivel_0", "nunique"),
            n_nivel1=("nivel_1", "nunique"),
            n_nivel2=("nivel_2", "nunique"),
            conf_integrada_promedio=("conf_integrada_score", "mean"),
        )
        .reset_index()
    )

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

    df["score_confiabilidad"] = (
        pd.to_numeric(df.get("conf_integrada_promedio", 70), errors="coerce")
        .fillna(70)
        .clip(0, 100)
    )

    df["score_representatividad"] = df["estado_pais_clase"].map(
        lambda x: map_score(x, cfg["representativity_scores"], 70)
    )

    df["score_fuente"] = 70.0

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

    df["score_aptitud_total"] = np.minimum(
        df["score_aptitud_raw"],
        df["score_cap"],
    ).round(3)

    return df


def assign_states(master: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
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
        "revision_temporal",
        "revision_prioritaria",
        "revision_espectral",
        "entrenamiento_alta_prioridad",
        "entrenamiento_condicionado",
        "apoyo_contextual",
    ]

    out["estado_funcional_preliminar"] = np.select(
        conditions,
        choices,
        default="exclusion_controlada",
    )

    out["razon_estado"] = out.apply(
        lambda r: (
            f"score:{r['score_aptitud_total']}; "
            f"tipo_xy:{r['estado_xy_subset']}; "
            f"alerta:{r['spectral_alert_level_max']}; "
            f"conflicto:{r.get('tipo_conflicto', '')}; "
            f"cap:{r.get('cap_reason', '')}"
        ),
        axis=1,
    )

    action = {
        "entrenamiento_alta_prioridad": "candidato_para_entrenamiento_con_balance",
        "entrenamiento_condicionado": "usar_con_restricciones_y_balance",
        "apoyo_contextual": "usar_como_apoyo_no_como_etiqueta_nucleo",
        "revision_prioritaria": "enviar_a_revision_experta_o_fotointerpretacion",
        "revision_espectral": "revisar_evidencia_s2_y_clase",
        "revision_temporal": "evaluar_trayectoria_temporal_y_cambio_potencial",
        "exclusion_controlada": "excluir_de_entrenamiento_directo_documentando_causa",
    }

    out["accion_recomendada"] = (
        out["estado_funcional_preliminar"]
        .map(action)
        .fillna("revision_general")
    )

    return out


def source_ranking(master: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    rows = []

    for fuente, g in master.groupby("fuente_dominante", dropna=False):
        def pct_mask(mask: pd.Series) -> float:
            return round(float(mask.mean() * 100), 3) if len(mask) else 0

        rows.append(
            {
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
                "pct_revision": pct_mask(
                    g["estado_funcional_preliminar"]
                    .astype(str)
                    .str.startswith("revision")
                ),
            }
        )

    out = pd.DataFrame(rows)

    if out.empty:
        return out

    out["score_trazabilidad_documental"] = 70.0

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

    out["score_aptitud_fuente"] = (
        w["traceability"] * out["score_trazabilidad_documental"]
        + w["temporal"] * out["score_temporal_fuente"]
        + w["thematic"] * out["score_tematico_fuente"]
        + w["spatial"] * out["score_espacial_fuente"]
        + w["representativity"] * out["score_representatividad_fuente"]
        + w["spectral"] * out["score_espectral_fuente"]
        + w["pipeline_compatibility"] * out["score_compatibilidad_pipeline"]
    ).round(3)

    out["categoria_aptitud_fuente"] = pd.cut(
        out["score_aptitud_fuente"],
        [-np.inf, 40, 55, 70, 85, np.inf],
        labels=[
            "fuente_no_apta_directa",
            "fuente_para_revision",
            "fuente_de_apoyo",
            "fuente_apta_condicionada",
            "fuente_prioritaria",
        ],
    ).astype(str)

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
        "estricto_2020": df[
            df["incluye_2020"].eq(1)
            & df["flag_conflicto_activo"].eq(0)
            & ~df["spectral_alert_level_max"]
            .astype(str)
            .str.lower()
            .isin(["media", "alta", "alta_sin_datos"])
        ],

        "ventana_conservadora": df[
            df["flag_conflicto_activo"].eq(0)
            & ~df["spectral_alert_level_max"]
            .astype(str)
            .str.lower()
            .isin(["alta", "alta_sin_datos"])
        ],

        "nivel1_regional": df[
            df["flag_conflicto_activo"].eq(0)
            & df["n_nivel1"].le(1)
            & df["score_tematico"].ge(70)
        ],

        "revision_prioritaria": df[
            df["estado_funcional_preliminar"]
            .astype(str)
            .str.startswith("revision")
        ],
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

def write_report(
    master: pd.DataFrame,
    ranking: pd.DataFrame,
    gap: pd.DataFrame,
    review: pd.DataFrame,
    scen: pd.DataFrame,
    audit: dict[str, Any],
) -> None:
    REP.mkdir(parents=True, exist_ok=True)

    state = (
        master.groupby("estado_funcional_preliminar")
        .agg(
            n_grupos=("xy_group_id", "count"),
            n_registros=("n_registros", "sum"),
            score_promedio=("score_aptitud_total", "mean"),
        )
        .reset_index()
        .sort_values("n_grupos", ascending=False)
    )

    state["score_promedio"] = state["score_promedio"].round(3)

    lines = [
        "# Scoring multicriterio de aptitud preliminar",
        "",
        "Ventana 2018-2022. Score temporal: 2020=100; 2019/2021=90; 2018/2022=85.",
        "",
        "## Resumen de auditoría",
        "",
        md(pd.DataFrame([audit])),
        "",
        "## Nota sobre duplicados espectrales",
        "",
        "El componente espectral se integró desde `audit_extract_units_s2sr_annual`, es decir, desde la capa sin duplicados por `extract_id`.",
        "",
        "Esto no elimina observaciones de años diferentes. Un mismo punto en 2020 y 2021 se conserva como dos unidades temporales distintas si tiene `extract_id` diferente. La eliminación de duplicados solo evita contar dos veces la misma unidad de extracción espectral.",
        "",
        "La capa completa `audit_original_records_s2sr_annual` se conserva para trazabilidad de registros originales, pero no se usa como insumo principal del score espectral agregado.",
        "",
        "## Estados funcionales",
        "",
        md(state),
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
        "## Revisión prioritaria",
        "",
        md(review.head(40)),
    ]

    (REP / "10_scoring_multicriterio_aptitud.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


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
        OUT / "10_xy_group_aptitude_master.csv",
        index=False,
        encoding="utf-8-sig",
    )

    ranking.to_csv(
        OUT / "10_source_aptitude_ranking.csv",
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
        "fuente",
        "nivel_0",
        "nivel_1",
        "nivel_2",
        "score_temporal_registro",
        "estado_registro_scoring",
    ]

    records[
        [c for c in record_flag_cols if c in records.columns]
    ].to_csv(
        OUT / "10_record_aptitude_flags.csv",
        index=False,
        encoding="utf-8-sig",
    )

    gap.to_csv(
        OUT / "10_gap_priority_country_class.csv",
        index=False,
        encoding="utf-8-sig",
    )

    review.to_csv(
        OUT / "10_review_priority_cases.csv",
        index=False,
        encoding="utf-8-sig",
    )

    scen.to_csv(
        OUT / "10_selection_scenarios_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    pd.DataFrame([audit]).to_csv(
        OUT / "10_scoring_audit_summary.csv",
        index=False,
        encoding="utf-8-sig",
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
        "--allow-missing-spectral",
        action="store_true",
        help=(
            "Permite continuar aunque existan xy_group_id sin componente espectral. "
            "Por defecto el proceso falla si falta cobertura espectral."
        ),
    )
    args = parser.parse_args()

    mkdirs()

    cfg = load_cfg(Path(args.config))

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
            # Solo si el usuario lo permite explícitamente.
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

        master = add_country_class(master, records)
        master = merge_conflicts(master)
        master = assign_states(compute_scores(master, cfg), cfg)

        ranking = source_ranking(master, cfg)
        gap = gap_priority(records)

        review = master[
            master["estado_funcional_preliminar"].isin(
                [
                    "revision_prioritaria",
                    "revision_espectral",
                    "revision_temporal",
                    "exclusion_controlada",
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

        write_report(master, ranking, gap, review, scen, audit)

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
        print(f"Join espectral: xy_group_id")
        print(f"Cobertura espectral XY: {coverage_audit['spectral_xy_coverage_pct']}%")
        print("Salidas:", OUT)
        print("Reporte:", REP / "10_scoring_multicriterio_aptitud.md")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("Error durante la ejecución de la Etapa 1.7 / Módulo 10.")
        traceback.print_exc()
        raise
