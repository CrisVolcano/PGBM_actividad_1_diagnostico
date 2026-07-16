from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import importlib.util
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
CONFIG = PROJECT_DIR / "config/a3_auditorias_nuevas_fuentes/caso_panama_v2/config_mapa_forestal_panama_2021_a1.yaml"
A1_SPECTRAL_SCRIPT = PROJECT_DIR / "src/actividad_1/09_s2sr_spectral_class_audit.py"


def load_a1_spectral_module() -> Any:
    spec = importlib.util.spec_from_file_location("a1_spectral_audit", A1_SPECTRAL_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"No se pudo cargar {A1_SPECTRAL_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def prep_for_a1_audit(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = gdf.copy()
    out["audit_country"] = out.get("Pais_es", out.get("country", ""))
    out["audit_source"] = out.get("Fuente", out.get("source", ""))
    out["audit_year"] = out.get("Año", out.get("year_ref", 2021))
    level_1_source = "id_nivel_1" if "id_nivel_1" in out.columns else "GranClase"
    level_2_source = "id_nivel_2" if "id_nivel_2" in out.columns else "Clase"
    out["level_1_code"] = pd.to_numeric(out[level_1_source], errors="coerce")
    out["level_2_code"] = pd.to_numeric(out[level_2_source], errors="coerce")
    n_group = out["n_unique_class_group_code_extract_unit"] if "n_unique_class_group_code_extract_unit" in out.columns else pd.Series(1, index=out.index)
    n_class = out["n_unique_class_code_extract_unit"] if "n_unique_class_code_extract_unit" in out.columns else pd.Series(1, index=out.index)
    n_records = out["n_records_extract_unit"] if "n_records_extract_unit" in out.columns else pd.Series(1, index=out.index)
    out["n_nivel1"] = pd.to_numeric(n_group, errors="coerce").fillna(1)
    out["n_nivel2"] = pd.to_numeric(n_class, errors="coerce").fillna(1)
    out["n_registros"] = pd.to_numeric(n_records, errors="coerce").fillna(1)
    out["n_paises"] = 1
    out["n_fuentes"] = 1
    conflict = out["has_thematic_conflict"] if "has_thematic_conflict" in out.columns else pd.Series(0, index=out.index)
    out["tipo_grupo_xy"] = np.where(
        pd.to_numeric(conflict, errors="coerce").fillna(0).gt(0),
        "conflicto_tematico_subset",
        "xy_unico_en_subset",
    )
    return out


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
    numeric = [c for c in defaults if c != "spectral_alert_level"]
    for col in numeric:
        spec[col] = pd.to_numeric(spec[col], errors="coerce")
    spec["flag_low_availability"] = np.where(
        spec["flag_low_availability"].fillna(0).astype(int).eq(1)
        | spec["flag_low_months_obs"].fillna(0).astype(int).eq(1)
        | spec["flag_low_total_obs"].fillna(0).astype(int).eq(1),
        1,
        0,
    )
    order = {"sin_alerta": 0, "baja": 1, "media": 2, "alta": 3, "alta_sin_datos": 4}
    spec["spectral_alert_level"] = spec["spectral_alert_level"].fillna("sin_alerta").astype(str)
    spec["spectral_severity_order"] = spec["spectral_alert_level"].map(order).fillna(0).astype(int)
    return spec


def make_spectral_by_xy(spec: pd.DataFrame) -> pd.DataFrame:
    spec = prepare_spectral_units(spec)
    out = (
        spec.groupby("xy_group_id", dropna=False)
        .agg(
            n_extract_units_spectral=("extract_id", "nunique"),
            n_spectral_rows=("extract_id", "size"),
            spectral_severity_order_max=("spectral_severity_order", "max"),
            spectral_alert_count_sum=("spectral_alert_count", "sum"),
            pct_extract_units_sin_alerta=("spectral_alert_level", lambda x: 100 * x.astype(str).str.lower().eq("sin_alerta").mean()),
            pct_extract_units_alerta_baja=("spectral_alert_level", lambda x: 100 * x.astype(str).str.lower().eq("baja").mean()),
            pct_extract_units_alerta_media=("spectral_alert_level", lambda x: 100 * x.astype(str).str.lower().eq("media").mean()),
            pct_extract_units_alerta_alta=("spectral_alert_level", lambda x: 100 * x.astype(str).str.lower().isin(["alta", "alta_sin_datos"]).mean()),
            pct_extract_units_baja_disponibilidad=("flag_low_availability", lambda x: 100 * pd.to_numeric(x, errors="coerce").fillna(0).astype(int).eq(1).mean()),
            pct_extract_units_sin_datos=("flag_no_spectral_data", lambda x: 100 * pd.to_numeric(x, errors="coerce").fillna(0).astype(int).eq(1).mean()),
            pct_extract_units_revision_espectral=("flag_spectral_class_review", lambda x: 100 * pd.to_numeric(x, errors="coerce").fillna(0).astype(int).eq(1).mean()),
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
    names = {0: "sin_alerta", 1: "baja", 2: "media", 3: "alta", 4: "alta_sin_datos"}
    out["spectral_alert_level_max"] = out["spectral_severity_order_max"].map(names).fillna("sin_alerta")
    out["score_espectral"] = (
        100
        - 0.60 * out["pct_extract_units_alerta_alta"]
        - 0.35 * out["pct_extract_units_alerta_media"]
        - 0.30 * out["pct_extract_units_baja_disponibilidad"]
        - 0.50 * out["pct_extract_units_sin_datos"]
        - 0.20 * out["pct_extract_units_revision_espectral"]
    ).clip(0, 100).round(3)
    return out


def alert_distribution(audit: pd.DataFrame) -> pd.DataFrame:
    out = audit["spectral_alert_level"].value_counts(dropna=False).reset_index()
    out.columns = ["spectral_alert_level", "n"]
    out["pct"] = (out["n"] / len(audit) * 100).round(3)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auditoría espectral Panamá v2 con metodología A1.")
    parser.add_argument("--config", default=str(CONFIG))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = load_yaml(config_path)
    root = project_root(config, config_path)
    cfg = config["spectral_class_audit"]
    a1 = load_a1_spectral_module()

    input_gpkg = resolve_path(cfg["input_gpkg"], root)
    original_layer = cfg["input_layers"]["original_annual"]
    units_layer = cfg["input_layers"]["extract_units_annual"]
    output_gpkg = resolve_path(cfg["output_gpkg"], root)
    tables_dir = resolve_path(cfg["tables_dir"], root)
    reports_dir = resolve_path(cfg["reports_dir"], root)
    report_md = resolve_path(cfg["report_md"], root)

    print("============================================================")
    print("PGBM - Auditoría espectral A1 - caso Panamá v2")
    print("============================================================")
    print("Input GPKG:", input_gpkg)
    print("Output GPKG:", output_gpkg)

    original = prep_for_a1_audit(gpd.read_file(input_gpkg, layer=original_layer))
    units = prep_for_a1_audit(gpd.read_file(input_gpkg, layer=units_layer))

    audit_original = a1.build_spectral_audit(original)
    audit_units = a1.build_spectral_audit(units)
    spectral_xy = make_spectral_by_xy(audit_units)
    dist_original = alert_distribution(audit_original)
    dist_units = alert_distribution(audit_units)

    tables_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    if output_gpkg.exists():
        output_gpkg.unlink()

    audit_original.to_csv(tables_dir / "audit_original_records_s2sr_annual.csv", index=False, encoding="utf-8-sig")
    audit_units.to_csv(tables_dir / "audit_extract_units_s2sr_annual.csv", index=False, encoding="utf-8-sig")
    spectral_xy.to_csv(tables_dir / "xy_group_spectral_audit.csv", index=False, encoding="utf-8-sig")
    dist_original.to_csv(tables_dir / "alert_distribution_original_records.csv", index=False, encoding="utf-8-sig")
    dist_units.to_csv(tables_dir / "alert_distribution_extract_units.csv", index=False, encoding="utf-8-sig")

    clean_for_gpkg(audit_original).to_file(output_gpkg, layer="audit_original_records_s2sr_annual", driver="GPKG")
    clean_for_gpkg(audit_units).to_file(output_gpkg, layer="audit_extract_units_s2sr_annual", driver="GPKG")
    spectral_xy_gdf = gpd.GeoDataFrame(
        spectral_xy.merge(units[["xy_group_id", "geometry"]].drop_duplicates("xy_group_id"), on="xy_group_id", how="left"),
        geometry="geometry",
        crs=units.crs,
    )
    clean_for_gpkg(spectral_xy_gdf).to_file(
        output_gpkg,
        layer="xy_group_spectral_audit",
        driver="GPKG",
    )
    write_table_gpkg(dist_original, output_gpkg, "alert_distribution_original_records")
    write_table_gpkg(dist_units, output_gpkg, "alert_distribution_extract_units")

    summary = pd.DataFrame(
        [
            {
                "n_original_records": len(audit_original),
                "n_extract_units": len(audit_units),
                "n_xy_groups": int(spectral_xy["xy_group_id"].nunique()),
                "method": "A1_general_spectral_audit",
            }
        ]
    )
    summary.to_csv(tables_dir / "audit_summary.csv", index=False, encoding="utf-8-sig")
    write_table_gpkg(summary, output_gpkg, "audit_summary")

    report = "\n".join(
        [
            "# Auditoría espectral A1 - caso Panamá v2",
            "",
            f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}",
            "",
            "Esta etapa aplica la metodología general de A1: disponibilidad S2, nube, señal esperada por nivel 0 homologado, rareza por país-año-clase y agregación por `xy_group_id`.",
            "",
            dist_units.to_markdown(index=False),
        ]
    )
    report_md.write_text(report, encoding="utf-8")

    print("Done.")
    print("Registros originales auditados:", len(audit_original))
    print("Unidades auditadas:", len(audit_units))
    print("Grupos XY auditados:", len(spectral_xy))
    print("Tablas:", tables_dir)
    print("Reporte:", report_md)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
