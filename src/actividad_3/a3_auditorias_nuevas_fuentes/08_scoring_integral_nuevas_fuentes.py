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
import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]
DEFAULT_CONFIG_RELATIVE = "config/a3_auditorias_nuevas_fuentes/config_sinac_malla_entrenamientos_2021.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def resolve_config_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    for base in [Path.cwd(), SCRIPT_DIR, PROJECT_DIR]:
        candidate = (base / path).resolve()
        if candidate.exists():
            return candidate
    return (PROJECT_DIR / path).resolve()


def project_root(config: dict[str, Any], config_path: Path) -> Path:
    root = config.get("paths", {}).get("project_root")
    if root:
        path = Path(root)
        return path.resolve() if path.is_absolute() else (config_path.parent / path).resolve()
    return config_path.parent.resolve()


def resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def md_table(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


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


def pct(n: float, d: float) -> float:
    return 0.0 if d == 0 else round(float(n) / float(d) * 100, 3)


def map_score(value: object, mapping: dict[str, Any], default: float = 70.0) -> float:
    if pd.isna(value):
        return default
    return float(mapping.get(str(value), default))


def classify_representativity(n: int, moderate: int, sufficient: int) -> str:
    if n >= sufficient:
        return "suficiente"
    if n >= moderate:
        return "moderado"
    if n >= 30:
        return "bajo"
    return "critico"


def read_inputs(config: dict[str, Any], root: Path) -> dict[str, Any]:
    xy_cfg = config["xy_groups"]
    spec_cfg = config["spectral_class_audit"]
    score_cfg = config["quality_scoring"]

    xy_gpkg = resolve_path(xy_cfg["output_gpkg"], root)
    xy_records = gpd.read_file(xy_gpkg, layer=xy_cfg["output_layers"]["records"])
    xy_groups = pd.read_csv(resolve_path(xy_cfg["tables_dir"], root) / "xy_groups.csv", encoding="utf-8-sig")
    xy_year = pd.read_csv(resolve_path(xy_cfg["tables_dir"], root) / "xy_year_groups.csv", encoding="utf-8-sig")
    xy_class = pd.read_csv(resolve_path(xy_cfg["tables_dir"], root) / "xy_class_groups.csv", encoding="utf-8-sig")
    field_quality = pd.read_csv(resolve_path(xy_cfg["tables_dir"], root) / "field_quality.csv", encoding="utf-8-sig")

    spec_tables = resolve_path(spec_cfg["tables_dir"], root)
    xy_spectral = pd.read_csv(spec_tables / "xy_group_spectral_audit.csv", encoding="utf-8-sig")
    class_spectral = pd.read_csv(spec_tables / "class_spectral_audit_original_records.csv", encoding="utf-8-sig")
    audit_summary = pd.read_csv(spec_tables / "audit_summary.csv", encoding="utf-8-sig")

    out_gpkg = resolve_path(score_cfg["output_gpkg"], root)
    tables_dir = resolve_path(score_cfg["tables_dir"], root)
    report_md = resolve_path(score_cfg["report_md"], root)

    return {
        "xy_records": xy_records,
        "xy_groups": xy_groups,
        "xy_year": xy_year,
        "xy_class": xy_class,
        "field_quality": field_quality,
        "xy_spectral": xy_spectral,
        "class_spectral": class_spectral,
        "audit_summary": audit_summary,
        "out_gpkg": out_gpkg,
        "tables_dir": tables_dir,
        "report_md": report_md,
    }


def structural_audit(records: gpd.GeoDataFrame, fields: dict[str, str]) -> dict[str, pd.DataFrame]:
    schema = pd.DataFrame(
        [
            {"field_name": col, "dtype": str(records[col].dtype), "non_null": int(records[col].notna().sum())}
            for col in records.columns
        ]
    )
    rows = []
    for logical, field in fields.items():
        present = field in records.columns
        row = {"logical_field": logical, "field": field, "present": present}
        if present:
            non_null = records.loc[records[field].notna(), field]
            empty = int((non_null.astype("string").str.strip() == "").sum())
            row.update(
                {
                    "nulls": int(records[field].isna().sum()),
                    "empty_strings": empty,
                    "unique_values": int(records[field].nunique(dropna=True)),
                }
            )
        rows.append(row)
    field_quality = pd.DataFrame(rows)

    id_field = fields["id"]
    duplicates = (
        records.groupby(id_field, dropna=False)
        .size()
        .reset_index(name="records")
        .query("records > 1")
        if id_field in records.columns
        else pd.DataFrame()
    )
    return {"schema": schema, "field_quality": field_quality, "duplicate_ids": duplicates}


def spatial_audit(records: gpd.GeoDataFrame, xy_groups: pd.DataFrame, fields: dict[str, str]) -> dict[str, pd.DataFrame]:
    lon = fields["longitude"]
    lat = fields["latitude"]
    coord = records[[lon, lat]].apply(pd.to_numeric, errors="coerce")
    quality = pd.DataFrame(
        [
            {
                "records": len(records),
                "crs": str(records.crs),
                "null_lon": int(coord[lon].isna().sum()),
                "null_lat": int(coord[lat].isna().sum()),
                "out_of_global_range": int(((coord[lon] < -180) | (coord[lon] > 180) | (coord[lat] < -90) | (coord[lat] > 90)).sum()),
                "xy_groups": int(len(xy_groups)),
                "xy_with_multiple_records": int((xy_groups["records"] > 1).sum()) if "records" in xy_groups else 0,
                "xy_with_thematic_conflict": int(xy_groups.get("has_thematic_conflict", pd.Series(dtype=int)).sum()),
            }
        ]
    )
    bbox = pd.DataFrame(
        [
            {
                "lon_min": float(coord[lon].min()),
                "lon_max": float(coord[lon].max()),
                "lat_min": float(coord[lat].min()),
                "lat_max": float(coord[lat].max()),
                "crs": str(records.crs),
            }
        ]
    )
    return {"spatial_quality": quality, "bbox": bbox}


def temporal_audit(records: pd.DataFrame, fields: dict[str, str], target_year: int) -> dict[str, pd.DataFrame]:
    year_field = fields["year"]
    years = pd.to_numeric(records[year_field], errors="coerce")
    quality = pd.DataFrame(
        [
            {
                "records": len(records),
                "target_year": target_year,
                "null_or_invalid_year": int(years.isna().sum()),
                "year_min": int(years.min()) if years.notna().any() else pd.NA,
                "year_max": int(years.max()) if years.notna().any() else pd.NA,
                "records_target_year": int((years == target_year).sum()),
                "pct_target_year": pct(int((years == target_year).sum()), len(records)),
            }
        ]
    )
    distribution = years.value_counts(dropna=False).reset_index()
    distribution.columns = ["year", "records"]
    distribution["percentage"] = (distribution["records"] / len(records) * 100).round(3)
    return {"temporal_quality": quality, "year_distribution": distribution.sort_values("year")}


def thematic_semantic_audit(records: pd.DataFrame, fields: dict[str, str], score_cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    cls = fields["class_code"]
    group = fields["class_group_code"]
    cls_name = fields["class_name"]
    group_name = fields["class_group_name"]

    class_dist = (
        records.groupby([group, group_name, cls, cls_name], dropna=False)
        .size()
        .reset_index(name="records")
        .sort_values("records", ascending=False)
    )
    total = len(records)
    class_dist["percentage"] = (class_dist["records"] / total * 100).round(3)
    class_dist["representativity_state"] = class_dist["records"].map(
        lambda n: classify_representativity(
            int(n),
            int(score_cfg["min_records_moderate_class"]),
            int(score_cfg["min_records_sufficient_class"]),
        )
    )

    hierarchy = (
        records.groupby([cls, cls_name], dropna=False)
        .agg(n_class_groups=(group, lambda s: s.nunique(dropna=True)), class_groups=(group, lambda s: " | ".join(map(str, sorted(s.dropna().unique())))))
        .reset_index()
    )
    hierarchy["hierarchy_consistent"] = (hierarchy["n_class_groups"] <= 1).astype("int8")

    residual_words = [w.casefold() for w in score_cfg.get("semantic_keywords", {}).get("residual", [])]
    semantic = class_dist.copy()
    text = (
        semantic[cls_name].astype("string").fillna("")
        + " "
        + semantic[group_name].astype("string").fillna("")
    ).str.casefold()
    semantic["flag_semantic_residual"] = [
        int(any(word in value for word in residual_words)) for value in text
    ]
    semantic["semantic_clarity_state"] = np.where(
        semantic["flag_semantic_residual"].eq(1),
        "residual_o_ambigua",
        "clara",
    )
    return {"class_distribution": class_dist, "hierarchy": hierarchy, "semantic": semantic}


def build_master(
    records: gpd.GeoDataFrame,
    xy_groups: pd.DataFrame,
    xy_spectral: pd.DataFrame,
    class_dist: pd.DataFrame,
    semantic: pd.DataFrame,
    fields: dict[str, str],
    score_cfg: dict[str, Any],
) -> gpd.GeoDataFrame:
    xy_col = fields["xy_group_id"]
    target_year = int(score_cfg["target_year"])

    base = (
        records.groupby(xy_col, dropna=False)
        .agg(
            lon=(fields["longitude"], "first"),
            lat=(fields["latitude"], "first"),
            country=(fields["country"], "first"),
            country_code=(fields["country_code"], "first"),
            source=(fields["source"], "first"),
            source_id=(fields["source_id"], "first"),
            year_min=(fields["year"], "min"),
            year_max=(fields["year"], "max"),
            n_records=(xy_col, "size"),
            n_classes=(fields["class_code"], lambda s: s.nunique(dropna=True)),
            n_class_groups=(fields["class_group_code"], lambda s: s.nunique(dropna=True)),
            class_code=(fields["class_code"], "first"),
            class_group_code=(fields["class_group_code"], "first"),
            class_name=(fields["class_name"], "first"),
            class_group_name=(fields["class_group_name"], "first"),
            geometry=("geometry", "first"),
        )
        .reset_index()
    )
    master = gpd.GeoDataFrame(base, geometry="geometry", crs=records.crs)

    xy_keep = xy_groups[[c for c in ["xy_group_id", "has_thematic_conflict", "has_temporal_repetition"] if c in xy_groups.columns]].copy()
    master = master.merge(xy_keep, on="xy_group_id", how="left")

    spec_cols = [
        "xy_group_id",
        "max_spectral_alert_level",
        "pct_priority_records",
        "n_priority_records",
        "n_no_spectral_data",
        "n_rare_spectral_records",
        "median_ndvi",
        "median_ndre",
        "median_months_obs",
    ]
    master = master.merge(xy_spectral[[c for c in spec_cols if c in xy_spectral.columns]], on="xy_group_id", how="left")

    rep = class_dist[[fields["class_code"], "records", "representativity_state"]].rename(
        columns={fields["class_code"]: "class_code", "records": "class_records_total"}
    )
    master = master.merge(rep, on="class_code", how="left")

    sem = semantic[[fields["class_code"], "flag_semantic_residual", "semantic_clarity_state"]].rename(
        columns={fields["class_code"]: "class_code"}
    )
    master = master.merge(sem, on="class_code", how="left")

    master["score_temporal"] = np.where(
        (pd.to_numeric(master["year_min"], errors="coerce") == target_year)
        & (pd.to_numeric(master["year_max"], errors="coerce") == target_year),
        100.0,
        70.0,
    )
    conflict = pd.to_numeric(master.get("has_thematic_conflict", 0), errors="coerce").fillna(0).gt(0)
    duplicates = pd.to_numeric(master["n_records"], errors="coerce").fillna(0).gt(1)
    master["estado_xy_subset"] = np.select(
        [conflict, duplicates],
        ["conflicto_tematico_subset", "redundancia_misma_fuente_misma_clase_subset"],
        default="xy_unico_en_subset",
    )
    master["score_espacial"] = np.select([conflict, duplicates], [0.0, 70.0], default=100.0)

    master["score_consistencia_clase"] = np.where(master["n_classes"].eq(1) & master["n_class_groups"].eq(1), 100.0, 0.0)
    rep_scores = score_cfg["representativity_scores"]
    master["score_representatividad"] = master["representativity_state"].map(lambda x: map_score(x, rep_scores, 65))
    master["score_claridad_semantica"] = np.where(master["flag_semantic_residual"].fillna(0).astype(int).eq(1), 60.0, 100.0)
    master["score_nivel_leyenda"] = np.where(master["class_code"].notna() & master["class_group_code"].notna(), 100.0, 60.0)
    master["score_tematico"] = (
        0.4 * master["score_consistencia_clase"]
        + 0.3 * master["score_representatividad"]
        + 0.2 * master["score_claridad_semantica"]
        + 0.1 * master["score_nivel_leyenda"]
    )

    spec_scores = score_cfg["spectral_scores"]
    master["score_espectral"] = master["max_spectral_alert_level"].map(lambda x: map_score(x, spec_scores, 70))
    master["score_confiabilidad"] = np.where(
        master["score_espectral"].lt(60) | conflict,
        float(score_cfg["confidence_neutral_score"]),
        90.0,
    )
    master["score_fuente"] = float(score_cfg["source_base_score"])

    w = score_cfg["weights_xy"]
    master["score_aptitud_raw"] = (
        w["temporal"] * master["score_temporal"]
        + w["spatial"] * master["score_espacial"]
        + w["thematic"] * master["score_tematico"]
        + w["spectral"] * master["score_espectral"]
        + w["confidence"] * master["score_confiabilidad"]
        + w["representativity"] * master["score_representatividad"]
        + w["source"] * master["score_fuente"]
    )
    master["score_cap"] = 100.0
    caps = score_cfg["caps"]
    master.loc[master["max_spectral_alert_level"].isin(["alta"]), "score_cap"] = np.minimum(
        master.loc[master["max_spectral_alert_level"].isin(["alta"]), "score_cap"],
        float(caps["spectral_alert_high"]),
    )
    master.loc[master["max_spectral_alert_level"].isin(["alta_sin_datos"]), "score_cap"] = np.minimum(
        master.loc[master["max_spectral_alert_level"].isin(["alta_sin_datos"]), "score_cap"],
        float(caps["spectral_no_data"]),
    )
    master.loc[master["flag_semantic_residual"].fillna(0).astype(int).eq(1), "score_cap"] = np.minimum(
        master.loc[master["flag_semantic_residual"].fillna(0).astype(int).eq(1), "score_cap"],
        float(caps["semantic_residual"]),
    )
    master["score_aptitud_total"] = np.minimum(master["score_aptitud_raw"], master["score_cap"]).round(3)

    th = score_cfg["state_thresholds"]
    master["categoria_aptitud"] = np.select(
        [
            master["score_aptitud_total"].ge(float(th["training_high"])),
            master["score_aptitud_total"].ge(float(th["training_conditioned"])),
            master["score_aptitud_total"].ge(float(th["contextual"])),
        ],
        ["entrenamiento_alta", "entrenamiento_condicionado", "referencia_contextual"],
        default="revision_o_apoyo",
    )
    master["score_method_note"] = (
        "Adaptado del scoring original: temporal, espacial, tematico, espectral, "
        "confiabilidad, representatividad y fuente; unidad=xy_group_id."
    )
    return master


def save_outputs(
    data: dict[str, Any],
    audits: dict[str, pd.DataFrame],
    master: gpd.GeoDataFrame,
    config_path: Path,
    score_cfg: dict[str, Any],
) -> None:
    out_gpkg = data["out_gpkg"]
    tables_dir = data["tables_dir"]
    report_md = data["report_md"]
    out_gpkg.parent.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    report_md.parent.mkdir(parents=True, exist_ok=True)

    if out_gpkg.exists():
        out_gpkg.unlink()

    clean_for_gpkg(master).to_file(out_gpkg, layer="xy_group_quality_scoring", driver="GPKG")

    for name, df in audits.items():
        df.to_csv(tables_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
        write_table_gpkg(df, out_gpkg, name)

    drop_geom = pd.DataFrame(master.drop(columns=[master.geometry.name], errors="ignore"))
    drop_geom.to_csv(tables_dir / "xy_group_scoring_master.csv", index=False, encoding="utf-8-sig")

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
    score_summary = (
        master[score_cols]
        .agg(["count", "min", "mean", "median", "max"])
        .round(3)
        .reset_index()
        .rename(columns={"index": "statistic"})
    )
    score_summary.to_csv(tables_dir / "score_component_summary.csv", index=False, encoding="utf-8-sig")
    write_table_gpkg(score_summary, out_gpkg, "score_component_summary")

    category = (
        master.groupby("categoria_aptitud", dropna=False)
        .agg(n_xy_groups=("xy_group_id", "count"), score_mean=("score_aptitud_total", "mean"))
        .reset_index()
    )
    category["pct_xy_groups"] = (category["n_xy_groups"] / len(master) * 100).round(3)
    category["score_mean"] = category["score_mean"].round(3)
    category.to_csv(tables_dir / "aptitude_category_summary.csv", index=False, encoding="utf-8-sig")
    write_table_gpkg(category, out_gpkg, "aptitude_category_summary")

    weights = pd.DataFrame([{"criterion": k, "weight": v} for k, v in score_cfg["weights_xy"].items()])
    weights.to_csv(tables_dir / "scoring_weights.csv", index=False, encoding="utf-8-sig")
    write_table_gpkg(weights, out_gpkg, "scoring_weights")

    report = "\n".join(
        [
            "# Auditorías integradas y scoring multicriterio - nuevas fuentes",
            "",
            f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}",
            "",
            "## Alcance",
            "",
            "Este módulo adapta metodológicamente el cierre del flujo original a la fuente configurada.",
            "La unidad de decisión es `xy_group_id` y el score total combina criterios temporal, espacial, temático/semántico, espectral, confiabilidad, representatividad y fuente.",
            "",
            "## Configuración",
            "",
            f"- YAML: `{config_path}`",
            f"- GeoPackage de salida: `{out_gpkg}`",
            f"- Tablas: `{tables_dir}`",
            "",
            "## Categorías de aptitud",
            "",
            md_table(category),
            "",
            "## Resumen de componentes del score",
            "",
            md_table(score_summary),
            "",
            "## Pesos usados",
            "",
            md_table(weights),
            "",
            "## Auditorías generadas",
            "",
            "- Estructural/tabular: esquema, campos configurados, duplicados de ID.",
            "- Espacial: CRS, bbox, calidad de coordenadas, duplicados y conflictos XY.",
            "- Temporal: calidad del año y cobertura del año objetivo.",
            "- Temática: distribución Clase/GranClase, representatividad y jerarquía clase-gran clase.",
            "- Semántica: clases residuales o ambiguas por palabras clave.",
            "- Espectral: alertas Sentinel-2 agregadas por `xy_group_id`.",
            "- Scoring: score multicriterio total por `xy_group_id`.",
            "",
        ]
    )
    report_md.write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auditorías integradas y scoring para nuevas fuentes.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_RELATIVE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = resolve_config_path(args.config)
    config = load_yaml(config_path)
    root = project_root(config, config_path)
    data = read_inputs(config, root)
    fields = config["fields"]
    score_cfg = config["quality_scoring"]

    print("============================================================")
    print("PGBM - Auditorías integradas y scoring - nuevas fuentes")
    print("============================================================")
    print("Config:", config_path)
    print("Salida GPKG:", data["out_gpkg"])

    records = data["xy_records"]
    structural = structural_audit(records, fields)
    spatial = spatial_audit(records, data["xy_groups"], fields)
    temporal = temporal_audit(records, fields, int(score_cfg["target_year"]))
    thematic = thematic_semantic_audit(records, fields, score_cfg)
    master = build_master(
        records,
        data["xy_groups"],
        data["xy_spectral"],
        thematic["class_distribution"],
        thematic["semantic"],
        fields,
        score_cfg,
    )

    audits = {}
    audits.update({f"structural_{k}": v for k, v in structural.items()})
    audits.update({f"spatial_{k}": v for k, v in spatial.items()})
    audits.update({f"temporal_{k}": v for k, v in temporal.items()})
    audits.update({f"thematic_{k}": v for k, v in thematic.items()})

    save_outputs(data, audits, master, config_path, score_cfg)

    print("Done.")
    print(f"Grupos XY con scoring: {len(master):,}")
    print(f"Score promedio: {master['score_aptitud_total'].mean():.3f}")
    print(f"Tablas: {data['tables_dir']}")
    print(f"Reporte: {data['report_md']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
