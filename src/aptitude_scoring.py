#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Etapa 1.7 - Scoring multicriterio de aptitud preliminar.
Trabaja únicamente con la ventana 2018-2022.
Score temporal: 2020=100; 2019/2021=90; 2018/2022=85.
Unidad principal: xy_group_id.
"""

from __future__ import annotations

import argparse
import sqlite3
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "scoring_aptitud.yaml"
DB = ROOT / "data" / "interim" / "05_thematic_audit.sqlite"
OUT = ROOT / "outputs" / "tables"
REP = ROOT / "outputs" / "reports"
LOG = ROOT / "logs"
SCORING_DB = ROOT / "data" / "interim" / "10_scoring_aptitud.sqlite"


def mkdirs():
    for p in [OUT, REP, LOG, SCORING_DB.parent]:
        p.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    mkdirs()
    with open(LOG / "auditoria.log", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def load_cfg(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def q(x: str) -> str:
    return '"' + x.replace('"', '""') + '"'


def table_exists(conn, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def cols(conn, table: str) -> list[str]:
    return pd.read_sql_query(f"PRAGMA table_info({q(table)})", conn)["name"].tolist()


def mode(s: pd.Series) -> str:
    vals = [str(x) for x in s.dropna().tolist() if str(x).strip()]
    return Counter(vals).most_common(1)[0][0] if vals else ""


def map_score(x: Any, mapping: dict[str, Any], default=70.0) -> float:
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
    return {"sin_alerta": 0, "baja": 1, "media": 2, "alta": 3, "alta_sin_datos": 4}.get(str(x).lower(), 0)


def sev_name(v: int) -> str:
    return {0: "sin_alerta", 1: "baja", 2: "media", 3: "alta", 4: "alta_sin_datos"}.get(int(v), "sin_alerta")


def md(df: pd.DataFrame, n: int | None = None) -> str:
    d = df.head(n).copy() if n else df.copy()
    try:
        return d.to_markdown(index=False)
    except Exception:
        return "```text\n" + d.to_string(index=False) + "\n```"


def read_base(conn, cfg):
    start, end = int(cfg["scoring"]["window_start"]), int(cfg["scoring"]["window_end"])
    required = ["source_rowid", "lon", "lat", "anio", "pais", "fuente", "nivel_0", "nivel_1", "nivel_2"]
    available = cols(conn, "thematic_base")
    missing = [c for c in required if c not in available]
    if missing:
        raise ValueError(f"thematic_base no contiene columnas requeridas: {missing}")
    optional = [c for c in ["conf_integrada", "conf_ndvi", "conf_cobertura", "conf_altura"] if c in available]
    sql = f"SELECT {', '.join(q(c) for c in required+optional)} FROM thematic_base WHERE anio BETWEEN {start} AND {end}"
    df = pd.read_sql_query(sql, conn)
    if df.empty:
        raise ValueError(f"No hay registros dentro de {start}-{end}")
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int64")
    return df


def read_xy(conn, cfg):
    subset = cfg["scoring"].get("subset_name", f"ventana_{cfg['scoring']['window_start']}_{cfg['scoring']['window_end']}")
    df = pd.read_sql_query("SELECT * FROM xy_subset_agg WHERE subset=?", conn, params=(subset,))
    if df.empty:
        raise ValueError(f"xy_subset_agg no contiene registros para {subset}. Ejecuta antes el módulo 5B.")
    return df


def find_spectral_file() -> Path | None:
    patterns = [
        "09*_spectral*records*.csv", "09*_spectral*class*audit*.csv", "09*.csv",
        "08*s2*join*.csv", "*spectral*class*.csv", "*s2sr*join*.csv"
    ]
    for pat in patterns:
        found = sorted(OUT.glob(pat))
        if found:
            return found[0]
    return None


def choose(columns: list[str], candidates: list[str]) -> str | None:
    low = {c.lower(): c for c in columns}
    for c in candidates:
        if c.lower() in low:
            return low[c.lower()]
    return None


def read_spectral():
    path = find_spectral_file()
    meta = {"spectral_file": str(path) if path else "", "spectral_status": "not_found", "join_key": ""}
    if path is None:
        return pd.DataFrame(), meta
    header = pd.read_csv(path, nrows=0)
    columns = list(header.columns)
    c_source = choose(columns, ["source_rowid", "original_source_rowid", "rowid", "fid", "id", "Id"])
    c_lon = choose(columns, ["lon", "Longitud", "longitude", "x"])
    c_lat = choose(columns, ["lat", "Latitud", "latitude", "y"])
    c_year = choose(columns, ["anio", "Año", "year"])
    c_alert = choose(columns, ["spectral_alert_level", "nivel_alerta", "nivel_alerta_espectral", "alert_level", "alerta_espectral"])
    c_count = choose(columns, ["spectral_alert_count", "n_alertas", "alert_count"])
    c_low = choose(columns, ["flag_low_availability", "flag_baja_disponibilidad", "low_availability", "baja_disponibilidad"])
    c_nodata = choose(columns, ["flag_no_spectral_data", "flag_sin_datos", "no_spectral_data", "sin_datos_s2"])
    c_months = choose(columns, ["n_valid_months", "valid_months", "meses_validos", "n_meses_validos"])
    usecols = [c for c in [c_source, c_lon, c_lat, c_year, c_alert, c_count, c_low, c_nodata, c_months] if c]
    if not usecols:
        meta["spectral_status"] = "unusable_no_known_columns"
        return pd.DataFrame(), meta
    df = pd.read_csv(path, usecols=list(dict.fromkeys(usecols)))
    rename = {}
    for old, new in [(c_source, "source_rowid"), (c_lon, "lon"), (c_lat, "lat"), (c_year, "anio"),
                     (c_alert, "spectral_alert_level"), (c_count, "spectral_alert_count"),
                     (c_low, "flag_low_availability"), (c_nodata, "flag_no_spectral_data"),
                     (c_months, "n_valid_months")]:
        if old:
            rename[old] = new
    df = df.rename(columns=rename)
    if "spectral_alert_level" not in df:
        df["spectral_alert_level"] = "sin_alerta"
    if "spectral_alert_count" not in df:
        df["spectral_alert_count"] = 0
    if "flag_low_availability" not in df:
        df["flag_low_availability"] = 0
    if "flag_no_spectral_data" not in df:
        df["flag_no_spectral_data"] = np.where(df["spectral_alert_level"].astype(str).str.lower().eq("alta_sin_datos"), 1, 0)
    df["spectral_severity_order"] = df["spectral_alert_level"].map(sev_order)
    if "source_rowid" in df:
        meta["join_key"] = "source_rowid"
        meta["spectral_status"] = "loaded_source_rowid"
    elif {"lon", "lat", "anio"}.issubset(df.columns):
        meta["join_key"] = "lon_lat_anio"
        meta["spectral_status"] = "loaded_lon_lat_anio"
    return df, meta


def join_spectral(base, spec, meta):
    df = base.copy()
    if spec.empty or not meta.get("join_key"):
        df["spectral_alert_level"] = "sin_alerta"
        df["spectral_alert_count"] = 0
        df["flag_low_availability"] = 0
        df["flag_no_spectral_data"] = 0
        df["spectral_severity_order"] = 0
        df["spectral_join_status"] = "sin_insumo_espectral"
        return df
    if meta["join_key"] == "source_rowid":
        spec = spec.sort_values("spectral_severity_order", ascending=False).drop_duplicates("source_rowid")
        df = df.merge(spec, on="source_rowid", how="left")
        df["spectral_join_status"] = np.where(df["spectral_alert_level"].notna(), "joined_source_rowid", "missing_spectral")
    else:
        spec = spec.sort_values("spectral_severity_order", ascending=False).drop_duplicates(["lon", "lat", "anio"])
        df = df.merge(spec, on=["lon", "lat", "anio"], how="left")
        df["spectral_join_status"] = np.where(df["spectral_alert_level"].notna(), "joined_lon_lat_anio", "missing_spectral")
    for col, default in {"spectral_alert_level": "sin_alerta", "spectral_alert_count": 0, "flag_low_availability": 0,
                         "flag_no_spectral_data": 0, "spectral_severity_order": 0}.items():
        df[col] = df[col].fillna(default) if col in df else default
    return df


def availability(v):
    if pd.isna(v): return 70.0
    v = float(v)
    if v >= 8: return 100.0
    if v >= 6: return 85.0
    if v >= 4: return 65.0
    if v >= 2: return 40.0
    if v >= 1: return 20.0
    return 0.0


def add_record_scores(records, cfg):
    df = records.copy()
    temp = {str(k): v for k, v in cfg["temporal_scores"].items()}
    df["score_temporal_registro"] = df["anio"].astype(int).astype(str).map(temp).fillna(0).astype(float)
    df["score_coherencia_s2_registro"] = df["spectral_alert_level"].map(lambda x: map_score(x, cfg["spectral_scores"], 70))
    df["score_disponibilidad_s2_registro"] = df["n_valid_months"].map(availability) if "n_valid_months" in df else np.where(df["flag_no_spectral_data"].fillna(0).astype(int).eq(1), 0, 70)
    df["score_espectral_registro"] = (0.45 * df["score_disponibilidad_s2_registro"] + 0.55 * df["score_coherencia_s2_registro"]).round(3)
    df["estado_registro_scoring"] = np.select(
        [df["flag_no_spectral_data"].fillna(0).astype(int).eq(1),
         df["spectral_alert_level"].astype(str).str.lower().eq("alta"),
         df["spectral_alert_level"].astype(str).str.lower().eq("media"),
         df["flag_low_availability"].fillna(0).astype(int).eq(1)],
        ["revision_espectral_sin_datos", "revision_espectral_alta", "revision_espectral_media", "apto_condicionado_baja_disponibilidad"],
        default="registro_apto_preliminar")
    return df


def aggregate(records, xy, cfg):
    rec = records.merge(xy[["xy_group_id", "lon", "lat"]].drop_duplicates(), on=["lon", "lat"], how="left")
    missing = int(rec["xy_group_id"].isna().sum())
    if missing:
        raise ValueError(f"{missing} registros no pudieron asociarse a xy_group_id.")
    temp = {str(k): v for k, v in cfg["temporal_scores"].items()}
    rec["score_temporal_record"] = rec["anio"].astype(int).astype(str).map(temp).fillna(0).astype(float)
    if "conf_integrada" in rec:
        conf = pd.to_numeric(rec["conf_integrada"], errors="coerce")
        rec["conf_integrada_score"] = conf * 100 if len(conf.dropna()) and conf.dropna().quantile(.95) <= 1.5 else conf
        rec["conf_integrada_score"] = rec["conf_integrada_score"].clip(0, 100)
    else:
        rec["conf_integrada_score"] = 70.0
    def concat(s):
        return "|".join(sorted({str(x) for x in s.dropna().tolist() if str(x).strip()}))
    target = int(cfg["scoring"]["target_year"])
    g = rec.groupby("xy_group_id").agg(
        n_registros=("source_rowid", "count"), n_fuentes=("fuente", "nunique"), n_anios=("anio", "nunique"),
        anio_min=("anio", "min"), anio_max=("anio", "max"),
        distancia_minima_2020=("anio", lambda s: int(np.min(np.abs(pd.to_numeric(s, errors="coerce") - target)))),
        incluye_2020=("anio", lambda s: int((pd.to_numeric(s, errors="coerce") == target).any())),
        score_temporal=("score_temporal_record", "max"),
        pais_dominante=("pais", mode), fuente_dominante=("fuente", mode),
        nivel_0_dominante=("nivel_0", mode), nivel_1_dominante=("nivel_1", mode), nivel_2_dominante=("nivel_2", mode),
        valores_nivel_0=("nivel_0", concat), valores_nivel_1=("nivel_1", concat), valores_nivel_2=("nivel_2", concat),
        n_nivel0=("nivel_0", "nunique"), n_nivel1=("nivel_1", "nunique"), n_nivel2=("nivel_2", "nunique"),
        conf_integrada_promedio=("conf_integrada_score", "mean")
    ).reset_index()
    g["incluye_2018_2022"] = 1
    s = rec.groupby("xy_group_id").agg(
        spectral_severity_order_max=("spectral_severity_order", "max"),
        spectral_alert_count_sum=("spectral_alert_count", "sum"),
        pct_extract_units_sin_alerta=("spectral_alert_level", lambda x: 100 * x.astype(str).str.lower().eq("sin_alerta").mean()),
        pct_extract_units_alerta_alta=("spectral_alert_level", lambda x: 100 * x.astype(str).str.lower().isin(["alta", "alta_sin_datos"]).mean()),
        pct_extract_units_baja_disponibilidad=("flag_low_availability", lambda x: 100 * pd.to_numeric(x, errors="coerce").fillna(0).astype(int).eq(1).mean()),
        score_espectral=("score_espectral_registro", "mean")
    ).reset_index()
    s["spectral_alert_level_max"] = s["spectral_severity_order_max"].map(sev_name)
    return g, s


def add_country_class(master, records):
    counts = records.groupby(["pais", "nivel_1"]).agg(n_registros_pais_clase=("source_rowid", "count")).reset_index()
    counts["estado_pais_clase"] = pd.cut(counts["n_registros_pais_clase"], [-1, 29, 99, 499, np.inf], labels=["critico", "bajo", "moderado", "suficiente"]).astype(str)
    counts = counts.rename(columns={"pais": "pais_grupo", "nivel_1": "nivel_1_dominante"})
    out = master.merge(counts, on=["pais_grupo", "nivel_1_dominante"], how="left")
    out["estado_pais_clase"] = out["estado_pais_clase"].fillna("sin_matriz")
    return out


def merge_conflicts(master):
    out = master.copy()
    path = OUT / "05c_conflict_taxonomy_details.csv"
    if path.exists():
        c = pd.read_csv(path)
        keep = [x for x in ["xy_group_id", "tipo_conflicto", "severidad_conflicto", "score_prioridad_revision"] if x in c]
        if keep:
            c = c[keep].copy()
            if "score_prioridad_revision" in c:
                c = c.sort_values("score_prioridad_revision", ascending=False)
            out = out.merge(c.drop_duplicates("xy_group_id"), on="xy_group_id", how="left")
    for col in ["tipo_conflicto", "severidad_conflicto"]:
        out[col] = out[col].fillna("") if col in out else ""
    out["score_prioridad_revision"] = pd.to_numeric(out.get("score_prioridad_revision", 0), errors="coerce").fillna(0)
    return out


def compute_scores(master, cfg):
    df = master.copy()
    df["score_espacial"] = df["estado_xy_subset"].map(lambda x: map_score(x, cfg["spatial_scores"], 70))
    df["flag_conflicto_activo"] = df["estado_xy_subset"].astype(str).eq("conflicto_tematico_subset").astype(int)
    df["score_consistencia_clase"] = np.select(
        [df["flag_conflicto_activo"].eq(1), (df["n_nivel1"] <= 1) & (df["n_nivel2"] <= 1), (df["n_nivel1"] <= 1) & (df["n_nivel2"] > 1), df["n_nivel1"] > 1],
        [0, 100, 75, 40], default=60)
    df["score_viabilidad_clase"] = df["estado_pais_clase"].map(lambda x: map_score(x, cfg["class_viability_scores"], 70))
    residual = cfg.get("semantic_keywords", {}).get("residual", ["otras", "otra"])
    df["flag_clase_residual"] = df["nivel_1_dominante"].map(lambda x: any(k in str(x).lower() for k in residual)).astype(int)
    df["score_claridad_semantica"] = np.where(df["flag_clase_residual"].eq(1), 60, 100)
    df["score_nivel_leyenda"] = np.select([df["n_nivel2"].eq(1) & df["score_viabilidad_clase"].ge(70), df["n_nivel1"].eq(1)], [100, 80], default=40)
    df["score_tematico"] = (0.4 * df["score_consistencia_clase"] + 0.3 * df["score_viabilidad_clase"] + 0.2 * df["score_claridad_semantica"] + 0.1 * df["score_nivel_leyenda"]).round(3)
    df["score_confiabilidad"] = pd.to_numeric(df.get("conf_integrada_promedio", 70), errors="coerce").fillna(70).clip(0, 100)
    df["score_representatividad"] = df["estado_pais_clase"].map(lambda x: map_score(x, cfg["representativity_scores"], 70))
    df["score_fuente"] = 70.0
    w = cfg["weights_xy"]
    df["score_aptitud_raw"] = (w["temporal"]*df["score_temporal"] + w["spatial"]*df["score_espacial"] + w["thematic"]*df["score_tematico"] + w["spectral"]*df["score_espectral"] + w["confidence"]*df["score_confiabilidad"] + w["representativity"]*df["score_representatividad"] + w["source"]*df["score_fuente"]).round(3)
    caps = cfg.get("caps", {})
    df["score_cap"] = 100.0
    df["cap_reason"] = ""
    def cap(mask, value, reason):
        idx = mask & (df["score_cap"] > value)
        df.loc[idx, "score_cap"] = value
        df.loc[idx, "cap_reason"] = reason
    level = df["spectral_alert_level_max"].astype(str).str.lower()
    cap(level.eq("alta"), float(caps.get("spectral_alert_high", 70)), "alerta_espectral_alta")
    cap(level.eq("alta_sin_datos"), float(caps.get("spectral_no_data", 60)), "sin_datos_espectrales")
    cap(df["flag_clase_residual"].eq(1), float(caps.get("residual_class", 75)), "clase_residual")
    df["score_aptitud_total"] = np.minimum(df["score_aptitud_raw"], df["score_cap"]).round(3)
    return df


def assign_states(df, cfg):
    out = df.copy()
    th = cfg["state_thresholds"]
    level = out["spectral_alert_level_max"].astype(str).str.lower()
    conflict = out["tipo_conflicto"].astype(str).str.lower()
    sev = out["severidad_conflicto"].astype(str).str.lower()
    conditions = [
        out["flag_conflicto_activo"].eq(1) & conflict.str.contains("posible_cambio_temporal", na=False),
        out["flag_conflicto_activo"].eq(1) & (conflict.str.contains("bosque_vs_no_bosque|conflicto_mismo_anio|residual_otras", regex=True, na=False) | sev.isin(["alta", "muy_alta"])),
        level.isin(["alta", "alta_sin_datos"]),
        out["score_aptitud_total"].ge(float(th["training_high"])),
        out["score_aptitud_total"].ge(float(th["training_conditioned"])),
        out["score_aptitud_total"].ge(float(th["contextual"])),
    ]
    choices = ["revision_temporal", "revision_prioritaria", "revision_espectral", "entrenamiento_alta_prioridad", "entrenamiento_condicionado", "apoyo_contextual"]
    out["estado_funcional_preliminar"] = np.select(conditions, choices, default="exclusion_controlada")
    out["razon_estado"] = out.apply(lambda r: f"score:{r['score_aptitud_total']}; tipo_xy:{r['estado_xy_subset']}; alerta:{r['spectral_alert_level_max']}; conflicto:{r.get('tipo_conflicto','')}; cap:{r.get('cap_reason','')}", axis=1)
    action = {"entrenamiento_alta_prioridad": "candidato_para_entrenamiento_con_balance", "entrenamiento_condicionado": "usar_con_restricciones_y_balance", "apoyo_contextual": "usar_como_apoyo_no_como_etiqueta_nucleo", "revision_prioritaria": "enviar_a_revision_experta_o_fotointerpretacion", "revision_espectral": "revisar_evidencia_s2_y_clase", "revision_temporal": "evaluar_trayectoria_temporal_y_cambio_potencial", "exclusion_controlada": "excluir_de_entrenamiento_directo_documentando_causa"}
    out["accion_recomendada"] = out["estado_funcional_preliminar"].map(action).fillna("revision_general")
    return out


def source_ranking(master, cfg):
    rows = []
    for fuente, g in master.groupby("fuente_dominante", dropna=False):
        pct = lambda mask: round(float(mask.mean()*100), 3) if len(mask) else 0
        rows.append({"fuente": fuente, "n_grupos_xy": len(g), "n_registros_representados": int(g["n_registros"].sum()), "score_temporal_fuente": round(g["score_temporal"].mean(), 3), "score_tematico_fuente": round(g["score_tematico"].mean(), 3), "score_espacial_fuente": round(g["score_espacial"].mean(), 3), "score_espectral_fuente": round(g["score_espectral"].mean(), 3), "score_representatividad_fuente": round(g["score_representatividad"].mean(), 3), "pct_conflicto_activo": pct(g["flag_conflicto_activo"].eq(1)), "pct_alerta_espectral_alta": pct(g["spectral_alert_level_max"].astype(str).str.lower().isin(["alta", "alta_sin_datos"])), "pct_revision": pct(g["estado_funcional_preliminar"].astype(str).str.startswith("revision"))})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["score_trazabilidad_documental"] = 70.0
    out["score_compatibilidad_pipeline"] = np.select([out["pct_conflicto_activo"].le(1) & out["pct_alerta_espectral_alta"].le(5), out["pct_conflicto_activo"].le(5) & out["pct_alerta_espectral_alta"].le(15)], [85, 70], default=50)
    w = cfg["weights_source"]
    out["score_aptitud_fuente"] = (w["traceability"]*out["score_trazabilidad_documental"] + w["temporal"]*out["score_temporal_fuente"] + w["thematic"]*out["score_tematico_fuente"] + w["spatial"]*out["score_espacial_fuente"] + w["representativity"]*out["score_representatividad_fuente"] + w["spectral"]*out["score_espectral_fuente"] + w["pipeline_compatibility"]*out["score_compatibilidad_pipeline"]).round(3)
    out["categoria_aptitud_fuente"] = pd.cut(out["score_aptitud_fuente"], [-np.inf, 40, 55, 70, 85, np.inf], labels=["fuente_no_apta_directa", "fuente_para_revision", "fuente_de_apoyo", "fuente_apta_condicionada", "fuente_prioritaria"]).astype(str)
    return out.sort_values("score_aptitud_fuente", ascending=False)


def gap_priority(records):
    df = records.groupby(["pais", "nivel_1"]).agg(n_registros_2018_2022=("source_rowid", "count"), n_fuentes=("fuente", "nunique")).reset_index().rename(columns={"nivel_1": "clase"})
    df["nivel"] = "Nivel_1"
    df["estado_pais_clase"] = pd.cut(df["n_registros_2018_2022"], [-1, 29, 99, 499, np.inf], labels=["critico", "bajo", "moderado", "suficiente"]).astype(str)
    df["score_necesidad_complementacion"] = df["estado_pais_clase"].map({"critico": 90, "bajo": 70, "moderado": 40, "suficiente": 10}).fillna(50)
    return df.sort_values(["score_necesidad_complementacion", "pais", "clase"], ascending=[False, True, True])


def scenarios(master):
    df = master
    data = {"estricto_2020": df[df["incluye_2020"].eq(1) & df["flag_conflicto_activo"].eq(0) & ~df["spectral_alert_level_max"].astype(str).str.lower().isin(["media", "alta", "alta_sin_datos"])], "ventana_conservadora": df[df["flag_conflicto_activo"].eq(0) & ~df["spectral_alert_level_max"].astype(str).str.lower().isin(["alta", "alta_sin_datos"])], "nivel1_regional": df[df["flag_conflicto_activo"].eq(0) & df["n_nivel1"].le(1) & df["score_tematico"].ge(70)], "revision_prioritaria": df[df["estado_funcional_preliminar"].astype(str).str.startswith("revision")]}
    return pd.DataFrame([{"escenario": k, "n_grupos_xy": len(v), "n_registros_representados": int(v["n_registros"].sum()) if len(v) else 0, "n_fuentes": int(v["fuente_dominante"].nunique()) if len(v) else 0, "score_promedio": round(float(v["score_aptitud_total"].mean()), 3) if len(v) else 0} for k, v in data.items()])


def write_report(master, ranking, gap, review, scen, audit):
    REP.mkdir(parents=True, exist_ok=True)
    state = master.groupby("estado_funcional_preliminar").agg(n_grupos=("xy_group_id", "count"), n_registros=("n_registros", "sum"), score_promedio=("score_aptitud_total", "mean")).reset_index().sort_values("n_grupos", ascending=False)
    state["score_promedio"] = state["score_promedio"].round(3)
    lines = ["# Scoring multicriterio de aptitud preliminar", "", "Ventana 2018-2022. Score temporal: 2020=100; 2019/2021=90; 2018/2022=85.", "", "## Resumen de auditoría", "", md(pd.DataFrame([audit])), "", "## Estados funcionales", "", md(state), "", "## Escenarios", "", md(scen), "", "## Ranking de fuentes", "", md(ranking.head(30)), "", "## Vacíos país-clase", "", md(gap.head(40)), "", "## Revisión prioritaria", "", md(review.head(40))]
    (REP / "10_scoring_multicriterio_aptitud.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--write-sqlite", action="store_true")
    args = parser.parse_args()
    mkdirs()
    cfg = load_cfg(Path(args.config))
    if not DB.exists():
        raise FileNotFoundError(f"No existe {DB}")
    conn = sqlite3.connect(DB)
    try:
        if not table_exists(conn, "thematic_base") or not table_exists(conn, "xy_subset_agg"):
            raise ValueError("La base 05_thematic_audit.sqlite debe contener thematic_base y xy_subset_agg.")
        print("Leyendo registros 2018-2022...")
        base = read_base(conn, cfg)
        print("Leyendo grupos XY...")
        xy = read_xy(conn, cfg)
        print("Integrando datos espectrales...")
        spec, meta = read_spectral()
        records = add_record_scores(join_spectral(base, spec, meta), cfg)
        print("Agregando por xy_group_id...")
        group, spectral = aggregate(records, xy, cfg)
        xy_cols = [c for c in ["xy_group_id", "lon", "lat", "pais_grupo", "estado_xy_subset", "tipo_grupo_original", "n_registros_original", "n_registros_subset"] if c in xy.columns]
        master = xy[xy_cols].drop_duplicates("xy_group_id").merge(group, on="xy_group_id", how="left").merge(spectral, on="xy_group_id", how="left")
        master = add_country_class(master, records)
        master = merge_conflicts(master)
        master = assign_states(compute_scores(master, cfg), cfg)
        ranking = source_ranking(master, cfg)
        gap = gap_priority(records)
        review = master[master["estado_funcional_preliminar"].isin(["revision_prioritaria", "revision_espectral", "revision_temporal", "exclusion_controlada"])].copy()
        scen = scenarios(master)
        audit = {"target_year": cfg["scoring"]["target_year"], "window_start": cfg["scoring"]["window_start"], "window_end": cfg["scoring"]["window_end"], "n_registros_ventana": int(len(records)), "n_grupos_xy_ventana": int(master["xy_group_id"].nunique()), "n_fuentes": int(records["fuente"].nunique()), "n_paises": int(records["pais"].nunique()), "spectral_file": meta.get("spectral_file", ""), "spectral_status": meta.get("spectral_status", ""), "spectral_join_key": meta.get("join_key", "")}
        print("Exportando salidas...")
        master.to_csv(OUT / "10_xy_group_aptitude_master.csv", index=False, encoding="utf-8-sig")
        ranking.to_csv(OUT / "10_source_aptitude_ranking.csv", index=False, encoding="utf-8-sig")
        records[[c for c in ["source_rowid", "lon", "lat", "anio", "pais", "fuente", "nivel_0", "nivel_1", "nivel_2", "spectral_alert_level", "score_temporal_registro", "score_espectral_registro", "estado_registro_scoring", "spectral_join_status"] if c in records.columns]].to_csv(OUT / "10_record_aptitude_flags.csv", index=False, encoding="utf-8-sig")
        gap.to_csv(OUT / "10_gap_priority_country_class.csv", index=False, encoding="utf-8-sig")
        review.to_csv(OUT / "10_review_priority_cases.csv", index=False, encoding="utf-8-sig")
        scen.to_csv(OUT / "10_selection_scenarios_summary.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame([audit]).to_csv(OUT / "10_scoring_audit_summary.csv", index=False, encoding="utf-8-sig")
        write_report(master, ranking, gap, review, scen, audit)
        if args.write_sqlite:
            with sqlite3.connect(SCORING_DB) as out:
                master.to_sql("xy_group_aptitude_master", out, if_exists="replace", index=False)
                ranking.to_sql("source_aptitude_ranking", out, if_exists="replace", index=False)
                gap.to_sql("gap_priority_country_class", out, if_exists="replace", index=False)
                review.to_sql("review_priority_cases", out, if_exists="replace", index=False)
                scen.to_sql("selection_scenarios_summary", out, if_exists="replace", index=False)
        log(f"Etapa 1.7 ejecutada correctamente. Registros={len(records)}; grupos={master['xy_group_id'].nunique()}")
        print("Etapa 1.7 ejecutada correctamente.")
        print(f"Registros ventana: {len(records):,}")
        print(f"Grupos XY: {master['xy_group_id'].nunique():,}")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("Error durante la ejecución de la Etapa 1.7.")
        traceback.print_exc()
        raise
