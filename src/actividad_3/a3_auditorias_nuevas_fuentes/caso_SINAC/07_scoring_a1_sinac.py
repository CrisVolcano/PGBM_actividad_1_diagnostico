from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import sqlite3
import sys
import traceback
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.actividad_3.a3_auditorias_nuevas_fuentes.a1_scoring_package import (
    build_a1_like_auxiliary_layers,
    write_a1_like_auxiliary_layers,
)

DEFAULT_CONFIG = PROJECT_DIR / "config/a3_auditorias_nuevas_fuentes/caso_SINAC/config_sinac_src10_2021.yaml"
A1_OUTPUT = PROJECT_DIR / "data/processed/scoring_aptitud/10_scoring_aptitud_outputs.gpkg"
A1_LAYER = "xy_group_aptitude_master"


SINAC_EXTRA_COLUMNS = [
    "id_nivel_0",
    "nivel_0",
    "id_nivel_1",
    "nivel_1",
    "id_nivel_2",
    "nivel_2",
    "Clase",
    "GranClase",
    "nombre_clase",
    "nombre_gran_clase",
]


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def project_root(config: dict[str, Any], config_path: Path) -> Path:
    value = config.get("paths", {}).get("project_root")
    if not value:
        return config_path.parent
    path = Path(value)
    return path.resolve() if path.is_absolute() else (config_path.parent / path).resolve()


def resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def a1_columns() -> list[str]:
    with sqlite3.connect(A1_OUTPUT) as conn:
        rows = conn.execute(f"PRAGMA table_info({A1_LAYER})").fetchall()
    return [row[1] for row in rows if row[1] not in {"fid", "geom"}]


def read_inputs(config: dict[str, Any], root: Path) -> dict[str, Any]:
    xy_cfg = config["xy_groups"]
    spec_cfg = config["spectral_class_audit"]
    score_cfg = config["quality_scoring_a1"]
    xy_gpkg = resolve_path(xy_cfg["output_gpkg"], root)
    spec_tables = resolve_path(spec_cfg["tables_dir"], root)
    return {
        "records": gpd.read_file(xy_gpkg, layer=xy_cfg["output_layers"]["records"]),
        "xy_groups": pd.read_csv(resolve_path(xy_cfg["tables_dir"], root) / "xy_groups.csv", encoding="utf-8-sig"),
        "xy_spectral": pd.read_csv(spec_tables / "xy_group_spectral_audit.csv", encoding="utf-8-sig"),
        "out_gpkg": resolve_path(score_cfg["output_gpkg"], root),
        "out_layer": str(score_cfg.get("output_layer", A1_LAYER)),
        "tables_dir": resolve_path(score_cfg["tables_dir"], root),
        "report_md": resolve_path(score_cfg["report_md"], root),
        "spectral_file": str(resolve_path(spec_cfg["output_gpkg"], root)),
        "spectral_layer": "xy_group_spectral_audit",
    }


def first_value(series: pd.Series) -> object:
    values = series.dropna()
    return values.iloc[0] if len(values) else ""


def concat_values(series: pd.Series) -> str:
    values = sorted({str(v) for v in series.dropna() if str(v).strip()})
    return " | ".join(values)


def map_score(value: object, mapping: dict[str, Any], default: float = 70.0) -> float:
    if pd.isna(value):
        return default
    text = str(value)
    return float(mapping.get(text, mapping.get(text.lower(), default)))


def classify_count(n: int) -> str:
    if n >= 500:
        return "suficiente"
    if n >= 100:
        return "moderado"
    if n >= 30:
        return "bajo"
    return "critico"


def usage_fields(score: pd.Series) -> tuple[str, str, str, str, str]:
    value = float(score)
    if value >= 85:
        return (
            "datos_para_entrenamiento",
            "entrenamiento",
            "Datos con alta aptitud multicriterio dentro del flujo A3 compatible con A1.",
            "Usar como núcleo de entrenamiento, aplicando balance por país, clase y fuente.",
            "score_aptitud_total >= 85",
        )
    if value >= 70:
        return (
            "datos_para_validacion",
            "validación",
            "Datos con aptitud buena pero no máxima; pueden tener alguna condición menor o menor fortaleza relativa.",
            "Usar preferentemente para validación estratificada o como complemento controlado del entrenamiento.",
            "70 <= score_aptitud_total < 85",
        )
    if value >= 55:
        return (
            "referencia_contextual_revision",
            "referencia contextual",
            "Datos con limitaciones que requieren revisión experta antes de cualquier uso supervisado.",
            "Mantener como referencia contextual o cola de revisión experta.",
            "55 <= score_aptitud_total < 70",
        )
    return (
        "mascara_exclusion",
        "máscaras",
        "Datos no aptos para uso directo dentro de la preselección automática.",
        "Usar como máscara de exclusión, control de calidad o lista de descarte.",
        "score_aptitud_total < 55",
    )


def build_master(
    records: gpd.GeoDataFrame,
    xy_groups: pd.DataFrame,
    xy_spectral: pd.DataFrame,
    score_cfg: dict[str, Any],
) -> gpd.GeoDataFrame:
    target_year = int(score_cfg["target_year"])
    rec = records.copy()
    xy = "xy_group_id"

    base = (
        rec.groupby(xy, dropna=False)
        .agg(
            lon=("Longitud", "first"),
            lat=("Latitud", "first"),
            pais_grupo=("Pais_es", "first"),
            n_registros=(xy, "size"),
            n_anios=("Año", "nunique"),
            anio_min=("Año", "min"),
            anio_max=("Año", "max"),
            pais_dominante=("Pais_es", first_value),
            id_fuente_dominante=("id_fuente", first_value),
            fuente_dominante=("Fuente", first_value),
            nivel_0_dominante=("nivel_0", first_value),
            nivel_1_dominante=("nivel_1", first_value),
            nivel_2_dominante=("nivel_2", first_value),
            valores_nivel_0=("nivel_0", concat_values),
            valores_nivel_1=("nivel_1", concat_values),
            valores_nivel_2=("nivel_2", concat_values),
            n_nivel0=("id_nivel_0", lambda s: s.nunique(dropna=True)),
            n_nivel1=("id_nivel_1", lambda s: s.nunique(dropna=True)),
            n_nivel2=("id_nivel_2", lambda s: s.nunique(dropna=True)),
            id_nivel_0=("id_nivel_0", first_value),
            nivel_0=("nivel_0", first_value),
            id_nivel_1=("id_nivel_1", first_value),
            nivel_1=("nivel_1", first_value),
            id_nivel_2=("id_nivel_2", first_value),
            nivel_2=("nivel_2", first_value),
            Clase=("Clase", first_value),
            GranClase=("GranClase", first_value),
            nombre_clase=("nombre_clase", first_value),
            nombre_gran_clase=("nombre_gran_clase", first_value),
            geometry=("geometry", "first"),
        )
        .reset_index()
    )
    master = gpd.GeoDataFrame(base, geometry="geometry", crs=records.crs)

    xy_keep = xy_groups[[c for c in ["xy_group_id", "has_thematic_conflict", "has_temporal_repetition"] if c in xy_groups.columns]].copy()
    master = master.merge(xy_keep, on="xy_group_id", how="left")
    master["has_thematic_conflict"] = pd.to_numeric(master.get("has_thematic_conflict", 0), errors="coerce").fillna(0).astype(int)
    master["has_temporal_repetition"] = pd.to_numeric(master.get("has_temporal_repetition", 0), errors="coerce").fillna(0).astype(int)

    master["tipo_grupo_original"] = np.where(master["has_thematic_conflict"].eq(1), "conflicto_tematico", "sin_conflicto")
    master["n_registros_original"] = master["n_registros"]
    master["n_registros_subset"] = master["n_registros"]
    master["distancia_minima_2020"] = (pd.to_numeric(master["anio_min"], errors="coerce") - target_year).abs().astype(int)
    master["incluye_2020"] = (
        (pd.to_numeric(master["anio_min"], errors="coerce") <= target_year)
        & (pd.to_numeric(master["anio_max"], errors="coerce") >= target_year)
    ).astype(int)
    master["score_temporal"] = np.where(master["incluye_2020"].eq(1), 100.0, 70.0)
    master["tipo_fuente_dominante"] = "nueva_fuente"
    master["detalle_tipo_fuente_dominante"] = "SINAC SRC10 2021"

    source_score = float(score_cfg["source_base_score"])
    master["n_fuentes"] = 1
    master["ids_fuente_presentes"] = master["id_fuente_dominante"].astype(str)
    master["fuentes_presentes"] = master["fuente_dominante"].astype(str)
    master["tipos_fuente_presentes"] = "nueva_fuente"
    master["score_directitud_fuente_promedio"] = source_score
    master["score_trazabilidad_fuente_promedio"] = source_score
    master["score_temporal_metadata_fuente_promedio"] = 100.0
    master["score_fuente_promedio"] = source_score
    master["score_fuente_minimo"] = source_score
    master["score_fuente_maximo"] = source_score
    master["n_fuentes_anio_inconsistente"] = 0
    master["n_fuentes_pais_inconsistente"] = 0

    # SINAC no trae conf_integrada observada. Se conserva el esquema A1 sin NULL.
    master["conf_integrada_promedio_observada"] = 0.0
    master["n_conf_integrada_observada"] = 0
    master["pct_conf_integrada_observada"] = 0.0
    master["flag_confianza_imputada"] = 1

    conflict = master["has_thematic_conflict"].eq(1)
    duplicated = pd.to_numeric(master["n_registros"], errors="coerce").fillna(0).gt(1)
    master["estado_xy_subset"] = np.select(
        [conflict, duplicated],
        ["conflicto_tematico_subset", "redundancia_misma_fuente_misma_clase_subset"],
        default="xy_unico_en_subset",
    )

    class_counts = (
        rec.groupby(["Pais_es", "nivel_1"], dropna=False)
        .size()
        .reset_index(name="n_registros_pais_clase")
        .rename(columns={"Pais_es": "pais_grupo", "nivel_1": "nivel_1_dominante"})
    )
    class_counts["estado_pais_clase"] = class_counts["n_registros_pais_clase"].map(lambda n: classify_count(int(n)))
    master = master.merge(class_counts, on=["pais_grupo", "nivel_1_dominante"], how="left")
    master["estado_pais_clase"] = master["estado_pais_clase"].fillna("sin_matriz")
    master["n_registros_pais_clase"] = pd.to_numeric(master["n_registros_pais_clase"], errors="coerce").fillna(0).astype(int)

    spec = xy_spectral.copy()
    master = master.merge(spec, on="xy_group_id", how="left", validate="one_to_one")
    spectral_defaults = {
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
        "s2yr_months_obs_median": 0.0,
        "s2yr_obs_total_median": 0.0,
        "s2yr_obs_mean_median": 0.0,
        "s2yr_cloudprob_median": 0.0,
        "s2yr_ndvi_mean": 0.0,
        "s2yr_ndvi_median": 0.0,
        "s2yr_ndvi8a_mean": 0.0,
        "s2yr_ndvi8a_median": 0.0,
        "s2yr_ndre_mean": 0.0,
        "s2yr_ndre_median": 0.0,
        "spectral_alert_level_max": "sin_alerta",
        "score_espectral": 70.0,
    }
    for col, default in spectral_defaults.items():
        if col not in master.columns:
            master[col] = default
        master[col] = master[col].fillna(default)

    master["tipo_conflicto"] = np.where(conflict, "conflicto_tematico_xy", "")
    master["severidad_conflicto"] = np.where(conflict, "alta", "")
    master["score_prioridad_revision"] = np.where(conflict, 100.0, 0.0)
    master["flag_conflicto_activo"] = conflict.astype(int)

    master["score_espacial"] = np.select([conflict, duplicated], [0.0, 70.0], default=100.0)
    master["score_consistencia_clase"] = np.select(
        [
            master["flag_conflicto_activo"].eq(1),
            (master["n_nivel1"] <= 1) & (master["n_nivel2"] <= 1),
            (master["n_nivel1"] <= 1) & (master["n_nivel2"] > 1),
            master["n_nivel1"] > 1,
        ],
        [0.0, 100.0, 75.0, 40.0],
        default=60.0,
    )
    master["score_viabilidad_clase"] = master["estado_pais_clase"].map(
        lambda x: map_score(x, score_cfg["class_viability_scores"], 70)
        if "class_viability_scores" in score_cfg
        else map_score(x, {"suficiente": 100, "moderado": 80, "bajo": 55, "critico": 25, "sin_matriz": 70}, 70)
    )
    residual_words = [w.casefold() for w in score_cfg.get("semantic_keywords", {}).get("residual", ["otras", "otra"])]
    master["flag_clase_residual"] = master["nivel_1_dominante"].astype(str).str.casefold().map(
        lambda value: int(any(word in value for word in residual_words))
    )
    master["score_claridad_semantica"] = np.where(master["flag_clase_residual"].eq(1), 60.0, 100.0)
    master["score_nivel_leyenda"] = np.select(
        [
            master["n_nivel2"].eq(1) & master["score_viabilidad_clase"].ge(70),
            master["n_nivel1"].eq(1),
        ],
        [100.0, 80.0],
        default=40.0,
    )
    master["score_tematico"] = (
        0.4 * master["score_consistencia_clase"]
        + 0.3 * master["score_viabilidad_clase"]
        + 0.2 * master["score_claridad_semantica"]
        + 0.1 * master["score_nivel_leyenda"]
    ).round(3)

    formula = score_cfg["confidence_formula"]
    master["score_confiabilidad_base"] = (
        float(formula["source"]) * master["score_fuente_promedio"]
        + float(formula["semantic_clarity"]) * master["score_claridad_semantica"]
        + float(formula["class_consistency"]) * master["score_consistencia_clase"]
        + float(formula["spatial"]) * master["score_espacial"]
    ).clip(0, 100).round(3)
    master["origen_score_confiabilidad"] = str(score_cfg["confidence_method"])
    master["conf_integrada_promedio"] = master["score_confiabilidad_base"]
    master["incluye_2018_2022"] = 1
    master["score_confiabilidad"] = master["score_confiabilidad_base"]
    master["score_representatividad"] = master["estado_pais_clase"].map(lambda x: map_score(x, score_cfg["representativity_scores"], 70))
    master["score_fuente"] = master["score_fuente_promedio"]

    w = score_cfg["weights_xy"]
    master["score_aptitud_raw"] = (
        float(w["temporal"]) * master["score_temporal"]
        + float(w["spatial"]) * master["score_espacial"]
        + float(w["thematic"]) * master["score_tematico"]
        + float(w["spectral"]) * master["score_espectral"]
        + float(w["confidence"]) * master["score_confiabilidad"]
        + float(w["representativity"]) * master["score_representatividad"]
        + float(w["source"]) * master["score_fuente"]
    ).round(3)
    master["score_cap"] = 100.0
    master["cap_reason"] = ""
    caps = score_cfg["caps"]
    high = master["spectral_alert_level_max"].astype(str).str.lower().eq("alta")
    no_data = master["spectral_alert_level_max"].astype(str).str.lower().eq("alta_sin_datos")
    residual = master["flag_clase_residual"].eq(1)
    master.loc[high, ["score_cap", "cap_reason"]] = [float(caps["spectral_alert_high"]), "alerta_espectral_alta"]
    master.loc[no_data, ["score_cap", "cap_reason"]] = [float(caps["spectral_no_data"]), "sin_datos_espectrales"]
    master.loc[residual & master["score_cap"].gt(float(caps["semantic_residual"])), ["score_cap", "cap_reason"]] = [
        float(caps["semantic_residual"]),
        "clase_residual",
    ]
    master["score_aptitud_total"] = np.minimum(master["score_aptitud_raw"], master["score_cap"]).round(3)

    usage = master["score_aptitud_total"].map(usage_fields)
    master["categoria_aptitud_preliminar"] = [u[0] for u in usage]
    master["categoria_uso_actividad_1_8"] = [u[1] for u in usage]
    master["definicion_categoria_aptitud"] = [u[2] for u in usage]
    master["accion_recomendada"] = [u[3] for u in usage]
    master["razon_categoria_aptitud"] = [u[4] for u in usage]

    return master


def usage_fields(score: float) -> tuple[str, str, str, str, str]:
    if score >= 85:
        return (
            "datos_para_entrenamiento",
            "entrenamiento",
            "Datos con alta aptitud multicriterio dentro del flujo A3 compatible con A1.",
            "Usar como núcleo de entrenamiento, aplicando balance por país, clase y fuente.",
            "score_aptitud_total >= 85",
        )
    if score >= 70:
        return (
            "datos_para_validacion",
            "validación",
            "Datos con aptitud buena pero no máxima; pueden tener alguna condición menor o menor fortaleza relativa.",
            "Usar preferentemente para validación estratificada o como complemento controlado del entrenamiento.",
            "70 <= score_aptitud_total < 85",
        )
    if score >= 55:
        return (
            "referencia_contextual_revision",
            "referencia contextual",
            "Datos con limitaciones que requieren revisión experta antes de cualquier uso supervisado.",
            "Mantener como referencia contextual o cola de revisión experta.",
            "55 <= score_aptitud_total < 70",
        )
    return (
        "mascara_exclusion",
        "máscaras",
        "Datos no aptos para uso directo dentro de la preselección automática.",
        "Usar como máscara de exclusión, control de calidad o lista de descarte.",
        "score_aptitud_total < 55",
    )


def clean_for_gpkg(df: pd.DataFrame | gpd.GeoDataFrame) -> pd.DataFrame | gpd.GeoDataFrame:
    out = df.copy()
    geom = out.geometry.name if isinstance(out, gpd.GeoDataFrame) else None
    for col in out.columns:
        if col == geom:
            continue
        dtype = str(out[col].dtype)
        if dtype.startswith("Int") or dtype.startswith("UInt") or dtype == "boolean":
            out[col] = out[col].astype("float").where(out[col].notna(), None)
        elif dtype == "string":
            out[col] = out[col].astype(object)
    return out


def assert_no_null_columns(master: gpd.GeoDataFrame) -> None:
    tabular = pd.DataFrame(master.drop(columns=[master.geometry.name], errors="ignore"))
    nulls = tabular.isna().sum()
    bad = nulls[nulls.gt(0)]
    if not bad.empty:
        raise ValueError(f"La salida final contiene NULL en columnas tabulares: {bad.to_dict()}")


def write_table_gpkg(df: pd.DataFrame, gpkg: Path, name: str) -> None:
    with sqlite3.connect(gpkg) as conn:
        clean_for_gpkg(df).to_sql(name, conn, if_exists="replace", index=False)


def save_outputs(master: gpd.GeoDataFrame, data: dict[str, Any], config_path: Path, score_cfg: dict[str, Any]) -> None:
    out_gpkg = data["out_gpkg"]
    tables_dir = data["tables_dir"]
    report_md = data["report_md"]
    out_layer = A1_LAYER
    out_gpkg.parent.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    report_md.parent.mkdir(parents=True, exist_ok=True)
    assert_no_null_columns(master)
    if out_gpkg.exists():
        out_gpkg.unlink()
    clean_for_gpkg(master).to_file(out_gpkg, layer=out_layer, driver="GPKG")
    pd.DataFrame(master.drop(columns=[master.geometry.name], errors="ignore")).to_csv(
        tables_dir / "xy_group_aptitude_master.csv",
        index=False,
        encoding="utf-8-sig",
    )
    score_cols = [
        "score_temporal",
        "score_espacial",
        "score_tematico",
        "score_espectral",
        "score_confiabilidad",
        "score_representatividad",
        "score_fuente",
        "score_aptitud_raw",
        "score_aptitud_total",
    ]
    score_summary = master[score_cols].agg(["count", "min", "mean", "median", "max"]).round(3).reset_index().rename(columns={"index": "statistic"})
    category = master.groupby("categoria_aptitud_preliminar", dropna=False).agg(
        n_xy_groups=("xy_group_id", "count"),
        score_mean=("score_aptitud_total", "mean"),
    ).reset_index()
    category["pct_xy_groups"] = (category["n_xy_groups"] / len(master) * 100).round(3)
    category["score_mean"] = category["score_mean"].round(3)
    for name, df in {"score_component_summary": score_summary, "aptitude_category_summary": category}.items():
        df.to_csv(tables_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
        write_table_gpkg(df, out_gpkg, name)
    auxiliary_layers = build_a1_like_auxiliary_layers(
        master=master,
        config_path=config_path,
        score_cfg=score_cfg,
        spectral_file=data["spectral_file"],
        spectral_layer=data["spectral_layer"],
    )
    write_a1_like_auxiliary_layers(out_gpkg, auxiliary_layers, tables_dir)
    report_md.write_text(
        "\n".join(
            [
                "# Scoring A1 - caso SINAC",
                "",
                f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}",
                f"- YAML: `{config_path}`",
                f"- GeoPackage: `{out_gpkg}`",
                f"- Capa: `{out_layer}`",
                "",
                "La salida replica el esquema de columnas de A1 y agrega únicamente columnas originales SINAC para trazabilidad temática.",
                "",
                category.to_markdown(index=False),
            ]
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scoring A1 para caso SINAC con esquema compatible A1.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = load_yaml(config_path)
    root = project_root(config, config_path)
    data = read_inputs(config, root)
    score_cfg = config["quality_scoring_a1"]
    print("============================================================")
    print("PGBM - Scoring A1 compatible - caso SINAC")
    print("============================================================")
    master = build_master(data["records"], data["xy_groups"], data["xy_spectral"], score_cfg)
    cols = a1_columns() + SINAC_EXTRA_COLUMNS + ["geometry"]
    missing = [c for c in cols if c not in master.columns]
    if missing:
        raise ValueError(f"Faltan columnas para salida A1: {missing}")
    master = master[cols]
    save_outputs(master, data, config_path, score_cfg)
    print("Done.")
    print(f"Grupos XY con scoring: {len(master):,}")
    print(f"Score promedio: {master['score_aptitud_total'].mean():.3f}")
    print(f"Salida GPKG: {data['out_gpkg']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
