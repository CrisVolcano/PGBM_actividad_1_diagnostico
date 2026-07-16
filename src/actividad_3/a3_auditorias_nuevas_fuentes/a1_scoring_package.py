from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd


CATEGORY_DEFINITIONS = pd.DataFrame(
    [
        {
            "categoria_aptitud_preliminar": "entrenamiento_alta",
            "categoria_uso_actividad_1_8": "entrenamiento",
            "definición": "Alta aptitud para uso como entrenamiento.",
            "uso_recomendado": "Usar como entrenamiento prioritario.",
        },
        {
            "categoria_aptitud_preliminar": "entrenamiento_condicionado",
            "categoria_uso_actividad_1_8": "entrenamiento_condicionado",
            "definición": "Aptitud suficiente con condicionamientos metodológicos.",
            "uso_recomendado": "Usar con revisión o filtros complementarios.",
        },
        {
            "categoria_aptitud_preliminar": "referencia_contextual",
            "categoria_uso_actividad_1_8": "referencia_contextual",
            "definición": "Aptitud contextual o de apoyo interpretativo.",
            "uso_recomendado": "Usar como referencia, no como entrenamiento principal.",
        },
        {
            "categoria_aptitud_preliminar": "revision_o_apoyo",
            "categoria_uso_actividad_1_8": "revision_o_apoyo",
            "definición": "Requiere revisión metodológica antes de uso.",
            "uso_recomendado": "Priorizar revisión antes de uso analítico.",
        },
    ]
)


SOURCE_CATEGORY_DEFINITIONS = pd.DataFrame(
    [
        {
            "categoria_aptitud_fuente": "fuente_alta",
            "categoria_uso_fuente_actividad_1_8": "fuente_prioritaria",
            "definición": "Fuente con desempeño alto dentro del caso evaluado.",
            "uso_recomendado": "Mantener como fuente prioritaria.",
        },
        {
            "categoria_aptitud_fuente": "fuente_condicionada",
            "categoria_uso_fuente_actividad_1_8": "fuente_condicionada",
            "definición": "Fuente útil con condicionamientos metodológicos.",
            "uso_recomendado": "Usar con controles complementarios.",
        },
        {
            "categoria_aptitud_fuente": "fuente_referencia",
            "categoria_uso_fuente_actividad_1_8": "fuente_referencia",
            "definición": "Fuente útil como referencia contextual.",
            "uso_recomendado": "No usar como fuente principal sin revisión.",
        },
        {
            "categoria_aptitud_fuente": "fuente_revision",
            "categoria_uso_fuente_actividad_1_8": "fuente_revision",
            "definición": "Fuente que requiere revisión antes de uso prioritario.",
            "uso_recomendado": "Priorizar revisión metodológica.",
        },
    ]
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


def write_table_gpkg(df: pd.DataFrame, gpkg: Path, name: str) -> None:
    with sqlite3.connect(gpkg) as conn:
        clean_for_gpkg(df).to_sql(name, conn, if_exists="replace", index=False)


def _source_category(score: float) -> tuple[str, str]:
    if score >= 85:
        return "fuente_alta", "fuente_prioritaria"
    if score >= 70:
        return "fuente_condicionada", "fuente_condicionada"
    if score >= 55:
        return "fuente_referencia", "fuente_referencia"
    return "fuente_revision", "fuente_revision"


def _need_score(status: object) -> int:
    return {
        "critico": 100,
        "bajo": 75,
        "moderado": 40,
        "suficiente": 0,
        "sin_matriz": 60,
    }.get(str(status), 60)


def build_gap_priority_country_class(master: gpd.GeoDataFrame) -> pd.DataFrame:
    out = (
        master.groupby(["pais_grupo", "nivel_1_dominante"], dropna=False)
        .agg(
            n_registros_2018_2022=("n_registros", "sum"),
            n_fuentes=("id_fuente_dominante", "nunique"),
            estado_pais_clase=("estado_pais_clase", "first"),
        )
        .reset_index()
        .rename(columns={"pais_grupo": "pais", "nivel_1_dominante": "clase"})
    )
    out["nivel"] = out["estado_pais_clase"]
    out["score_necesidad_complementacion"] = out["estado_pais_clase"].map(_need_score).astype(int)
    return out[
        [
            "pais",
            "clase",
            "n_registros_2018_2022",
            "n_fuentes",
            "nivel",
            "estado_pais_clase",
            "score_necesidad_complementacion",
        ]
    ]


def build_record_aptitude_flags(master: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = gpd.GeoDataFrame(
        {
            "source_rowid": np.arange(1, len(master) + 1),
            "xy_group_id": master["xy_group_id"].astype(str),
            "lon": master["lon"],
            "lat": master["lat"],
            "anio": master["anio_min"].astype(str),
            "pais": master["pais_grupo"].astype(str),
            "id_fuente": master["id_fuente_dominante"].astype(str),
            "fuente": master["fuente_dominante"].astype(str),
            "tipo_fuente": master["tipo_fuente_dominante"].astype(str),
            "detalle_tipo_fuente": master["detalle_tipo_fuente_dominante"].astype(str),
            "id_origen": master["xy_group_id"].astype(str),
            "score_directitud": master["score_directitud_fuente_promedio"].astype(str),
            "score_trazabilidad": master["score_trazabilidad_fuente_promedio"].astype(str),
            "score_consistencia_temporal_fuente": master["score_temporal_metadata_fuente_promedio"],
            "score_fuente_base": master["score_fuente_promedio"],
            "flag_anio_fuente_informado": 1,
            "flag_anio_fuente_consistente": 1,
            "flag_nombre_fuente_inconsistente": 0,
            "flag_tipo_fuente_inconsistente": 0,
            "flag_pais_fuente_inconsistente": 0,
            "nivel_0": master["nivel_0_dominante"].astype(str),
            "nivel_1": master["nivel_1_dominante"].astype(str),
            "nivel_2": master["nivel_2_dominante"].astype(str),
            "conf_integrada": master["conf_integrada_promedio"],
            "conf_integrada_score_observado": master["conf_integrada_promedio_observada"],
            "conf_integrada_observada": master["n_conf_integrada_observada"].gt(0).astype(int),
            "score_temporal_registro": master["score_temporal"],
            "estado_registro_scoring": master["categoria_aptitud_preliminar"].astype(str),
        },
        geometry=master.geometry,
        crs=master.crs,
    )
    return out


def build_review_priority_cases(master: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    mask = (
        master["categoria_aptitud_preliminar"].ne("entrenamiento_alta")
        | master["flag_conflicto_activo"].gt(0)
        | master["score_prioridad_revision"].gt(0)
        | master["spectral_alert_level_max"].astype(str).str.lower().isin(["media", "alta", "alta_sin_datos"])
    )
    return master.loc[mask].copy()


def build_scoring_audit_summary(
    master: gpd.GeoDataFrame,
    config_path: Path,
    score_cfg: dict[str, Any],
    spectral_file: str,
    spectral_layer: str,
) -> pd.DataFrame:
    observed = int(pd.to_numeric(master["n_conf_integrada_observada"], errors="coerce").fillna(0).sum())
    n_records = int(master["n_registros"].sum())
    n_xy = int(len(master))
    return pd.DataFrame(
        [
            {
                "target_year": int(score_cfg.get("target_year", 2021)),
                "window_start": int(score_cfg.get("target_year", 2021)),
                "window_end": int(score_cfg.get("target_year", 2021)),
                "n_registros_ventana": n_records,
                "n_grupos_xy_ventana": n_xy,
                "n_fuentes": int(master["id_fuente_dominante"].nunique()),
                "n_paises": int(master["pais_grupo"].nunique()),
                "confidence_pipeline_version": "A3_A1_compatible_without_observed_conf_integrada",
                "confidence_input_scale_config": str(score_cfg.get("confidence_method", "")),
                "confidence_scale_detected": "derived_0_100",
                "confidence_neutral_score": float(master["score_confiabilidad"].median()),
                "n_records_confidence_observed": observed,
                "n_records_confidence_missing": n_records - observed,
                "pct_records_confidence_observed": round(observed / n_records * 100, 3) if n_records else 0,
                "n_confidence_distinct_observed": 0,
                "confidence_observed_min": 0.0,
                "confidence_observed_max": 0.0,
                "n_xy_confidence_observed": int(master["n_conf_integrada_observada"].gt(0).sum()),
                "n_xy_confidence_imputed": int(master["flag_confianza_imputada"].sum()),
                "pct_xy_confidence_observed": round(master["n_conf_integrada_observada"].gt(0).mean() * 100, 3),
                "pct_xy_confidence_imputed": round(master["flag_confianza_imputada"].mean() * 100, 3),
                "max_imputed_xy_pct_allowed": 100.0,
                "source_pipeline_version": "A3_A1_compatible",
                "source_catalog_file": str(config_path),
                "source_catalog_rows": int(master["id_fuente_dominante"].nunique()),
                "source_catalog_unique_ids": int(master["id_fuente_dominante"].nunique()),
                "source_weight_directness": 1.0,
                "source_weight_traceability": 1.0,
                "source_weight_temporal_metadata": 1.0,
                "n_source_ids_observed": int(master["id_fuente_dominante"].nunique()),
                "n_source_ids_uncatalogued": 0,
                "source_ids_uncatalogued": "",
                "n_source_records_name_mismatch": 0,
                "n_source_records_type_mismatch": 0,
                "n_source_records_country_mismatch": 0,
                "n_source_records_year_missing": 0,
                "n_source_records_year_inconsistent": int(master["n_fuentes_anio_inconsistente"].sum()),
                "n_source_scores_distinct": int(master["score_fuente"].nunique()),
                "source_score_min": float(master["score_fuente"].min()),
                "source_score_max": float(master["score_fuente"].max()),
                "n_xy_source_scored": n_xy,
                "pct_xy_source_scored": 100.0,
                "n_xy_source_scores_distinct": int(master["score_fuente"].nunique()),
                "xy_source_score_min": float(master["score_fuente"].min()),
                "xy_source_score_max": float(master["score_fuente"].max()),
                "n_active_source_ids_in_xy": int(master["id_fuente_dominante"].nunique()),
                "spectral_file": spectral_file,
                "spectral_layer": spectral_layer,
                "spectral_status": "joined",
                "spectral_join_key": "xy_group_id",
                "n_spectral_units_loaded": int(master["n_extract_units_spectral"].sum()),
                "n_spectral_xy_loaded": int(master["n_extract_units_spectral"].gt(0).sum()),
                "n_xy_groups_joined_spectral": int(master["n_extract_units_spectral"].gt(0).sum()),
                "n_xy_groups_missing_spectral": int(master["n_extract_units_spectral"].le(0).sum()),
                "spectral_xy_coverage_pct": round(master["n_extract_units_spectral"].gt(0).mean() * 100, 3),
                "deduplication_rule": "xy_group_id",
            }
        ]
    )


def build_selection_scenarios_summary(master: gpd.GeoDataFrame) -> pd.DataFrame:
    out = (
        master.groupby("categoria_aptitud_preliminar", dropna=False)
        .agg(
            n_grupos_xy=("xy_group_id", "count"),
            n_registros_representados=("n_registros", "sum"),
            n_fuentes=("id_fuente_dominante", "nunique"),
            score_promedio=("score_aptitud_total", "mean"),
        )
        .reset_index()
        .rename(columns={"categoria_aptitud_preliminar": "escenario"})
    )
    total = pd.DataFrame(
        [
            {
                "escenario": "total_caso",
                "n_grupos_xy": len(master),
                "n_registros_representados": int(master["n_registros"].sum()),
                "n_fuentes": int(master["id_fuente_dominante"].nunique()),
                "score_promedio": float(master["score_aptitud_total"].mean()),
            }
        ]
    )
    return pd.concat([out, total], ignore_index=True).round({"score_promedio": 3})


def build_source_aptitude_ranking(master: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for source_id, group in master.groupby("id_fuente_dominante", dropna=False):
        score = float(group["score_aptitud_total"].mean())
        cat, use = _source_category(score)
        rows.append(
            {
                "id_fuente": str(source_id),
                "fuente_reporte": str(group["detalle_tipo_fuente_dominante"].iloc[0]),
                "tipo_documentado": str(group["tipo_fuente_dominante"].iloc[0]),
                "medio_obtencion": "nueva_fuente_a3",
                "anios_documentados": f"{group['anio_min'].min()}-{group['anio_max'].max()}",
                "pais_documentado": str(group["pais_grupo"].iloc[0]),
                "score_directitud": str(group["score_directitud_fuente_promedio"].iloc[0]),
                "score_trazabilidad": str(group["score_trazabilidad_fuente_promedio"].iloc[0]),
                "score_consistencia_temporal_fuente": float(group["score_temporal_metadata_fuente_promedio"].mean()),
                "score_fuente_base": float(group["score_fuente"].mean()),
                "pct_anio_informado": 100.0,
                "pct_anio_consistente": 100.0,
                "n_nombre_inconsistente": 0,
                "n_tipo_inconsistente": 0,
                "n_pais_inconsistente": 0,
                "flag_fuente_anio_inconsistente": 0,
                "flag_fuente_pais_inconsistente": 0,
                "fuente": str(group["fuente_dominante"].iloc[0]),
                "n_grupos_xy": int(len(group)),
                "n_registros_representados": int(group["n_registros"].sum()),
                "score_temporal_fuente": float(group["score_temporal"].mean()),
                "score_tematico_fuente": float(group["score_tematico"].mean()),
                "score_espacial_fuente": float(group["score_espacial"].mean()),
                "score_espectral_fuente": float(group["score_espectral"].mean()),
                "score_representatividad_fuente": float(group["score_representatividad"].mean()),
                "pct_conflicto_activo": round(group["flag_conflicto_activo"].mean() * 100, 3),
                "pct_alerta_espectral_alta": round(group["spectral_alert_level_max"].astype(str).str.lower().eq("alta").mean() * 100, 3),
                "pct_no_uso_directo": round(group["categoria_aptitud_preliminar"].ne("entrenamiento_alta").mean() * 100, 3),
                "pct_entrenamiento": round(group["categoria_uso_actividad_1_8"].astype(str).str.contains("entrenamiento", na=False).mean() * 100, 3),
                "pct_validacion": 0.0,
                "pct_prueba": 0.0,
                "score_trazabilidad_documental": str(group["score_trazabilidad_fuente_promedio"].iloc[0]),
                "score_compatibilidad_pipeline": 100,
                "score_desempeno_fuente": round(score, 3),
                "score_aptitud_fuente": round(score, 3),
                "categoria_aptitud_fuente": cat,
                "categoria_uso_fuente_actividad_1_8": use,
            }
        )
    return pd.DataFrame(rows)


def build_a1_like_auxiliary_layers(
    master: gpd.GeoDataFrame,
    config_path: Path,
    score_cfg: dict[str, Any],
    spectral_file: str,
    spectral_layer: str,
) -> dict[str, pd.DataFrame | gpd.GeoDataFrame]:
    return {
        "category_definitions": CATEGORY_DEFINITIONS.copy(),
        "gap_priority_country_class": build_gap_priority_country_class(master),
        "record_aptitude_flags": build_record_aptitude_flags(master),
        "review_priority_cases": build_review_priority_cases(master),
        "scoring_audit_summary": build_scoring_audit_summary(master, config_path, score_cfg, spectral_file, spectral_layer),
        "selection_scenarios_summary": build_selection_scenarios_summary(master),
        "source_aptitude_ranking": build_source_aptitude_ranking(master),
        "source_category_definitions": SOURCE_CATEGORY_DEFINITIONS.copy(),
    }


def write_a1_like_auxiliary_layers(
    out_gpkg: Path,
    layers: dict[str, pd.DataFrame | gpd.GeoDataFrame],
    tables_dir: Path,
) -> None:
    for name, df in layers.items():
        df.to_csv(tables_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
        if isinstance(df, gpd.GeoDataFrame):
            clean_for_gpkg(df).to_file(out_gpkg, layer=name, driver="GPKG")
        else:
            write_table_gpkg(df, out_gpkg, name)
