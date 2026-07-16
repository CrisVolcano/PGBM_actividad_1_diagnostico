from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import sys
import traceback
from typing import Any

import geopandas as gpd
import pandas as pd
import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
DEFAULT_CONFIG = PROJECT_DIR / "config/a3_auditorias_nuevas_fuentes/caso_panama_v2/config_mapa_forestal_panama_2021_a1.yaml"


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


def normalize(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        out[col] = out[col].astype("string").str.strip()
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Homologa clases Panamá a niveles A1.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = load_yaml(config_path)
    root = project_root(config, config_path)
    cfg = config["homologation_a1"]

    input_gpkg = resolve_path(cfg["input_gpkg"], root)
    input_layer = str(cfg["input_layer"])
    hom_csv = resolve_path(cfg["homologation_csv"], root)
    output_gpkg = resolve_path(cfg["output_gpkg"], root)
    output_layer = str(cfg["output_layer"])
    tables_dir = resolve_path(cfg["tables_dir"], root)
    report_md = resolve_path(cfg["report_md"], root)

    records = gpd.read_file(input_gpkg, layer=input_layer)
    hom = pd.read_csv(hom_csv, encoding="utf-8-sig", dtype="string")
    if "class_value" not in records.columns and "Clase" in records.columns:
        records["class_value"] = records["Clase"]
    if "class_name" not in records.columns and "nombre_clase" in records.columns:
        records["class_name"] = records["nombre_clase"]
    keys = ["class_value", "class_name"]
    missing_records = [c for c in keys if c not in records.columns]
    missing_hom = [c for c in keys if c not in hom.columns]
    if missing_records or missing_hom:
        raise ValueError(f"Faltan claves. GPKG={missing_records}; homologación={missing_hom}")

    records = normalize(records, keys)
    hom = normalize(hom, keys)
    if hom.duplicated(keys).any():
        raise ValueError("La homologación Panamá tiene claves duplicadas.")

    keep = keys + [
        "nivel_0_codigo",
        "nivel_0_homologado",
        "nivel_1_codigo",
        "nivel_1_homologado",
        "nivel_2_codigo",
        "nivel_2_homologado",
        "tipo_equivalencia",
        "confianza",
        "requiere_revision",
        "nota",
    ]
    hom = hom[keep].rename(
        columns={
            "nivel_0_codigo": "id_nivel_0",
            "nivel_0_homologado": "nivel_0",
            "nivel_1_codigo": "id_nivel_1",
            "nivel_1_homologado": "nivel_1",
            "nivel_2_codigo": "id_nivel_2",
            "nivel_2_homologado": "nivel_2",
            "tipo_equivalencia": "homologacion_tipo_equivalencia",
            "confianza": "homologacion_confianza",
            "requiere_revision": "homologacion_requiere_revision",
            "nota": "homologacion_nota",
        }
    )
    out = records.merge(hom, on=keys, how="left", validate="many_to_one")
    out["homologacion_encontrada"] = out["nivel_2"].notna().astype("int8")
    out["homologacion_requiere_revision"] = pd.to_numeric(
        out["homologacion_requiere_revision"], errors="coerce"
    ).fillna(1).astype("int8")
    unmatched = out.loc[out["homologacion_encontrada"].eq(0), keys].drop_duplicates().sort_values(keys)
    tables_dir.mkdir(parents=True, exist_ok=True)
    unmatched.to_csv(tables_dir / "clases_no_homologadas.csv", index=False, encoding="utf-8-sig")
    if bool(cfg.get("fail_on_unmatched", True)) and not unmatched.empty:
        raise ValueError(f"Hay clases sin homologación. Revise {tables_dir / 'clases_no_homologadas.csv'}")

    out["class_value_original"] = out["class_value"]
    out["class_name_original"] = out["class_name"]
    out["Clase"] = out["id_nivel_2"]
    out["GranClase"] = out["id_nivel_1"]
    out["nombre_clase"] = out["nivel_2"]
    out["nombre_gran_clase"] = out["nivel_1"]

    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    if output_gpkg.exists():
        output_gpkg.unlink()
    out.to_file(output_gpkg, layer=output_layer, driver="GPKG")

    summary = pd.DataFrame(
        [
            {
                "records": len(out),
                "source_classes": int(records[keys].drop_duplicates().shape[0]),
                "homologated_classes": int(out.loc[out["homologacion_encontrada"].eq(1), keys].drop_duplicates().shape[0]),
                "unmatched_classes": int(unmatched.shape[0]),
                "records_requiring_review": int(out["homologacion_requiere_revision"].sum()),
            }
        ]
    )
    summary.to_csv(tables_dir / "homologacion_summary.csv", index=False, encoding="utf-8-sig")
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_md.write_text(
        "\n".join(
            [
                "# Homologación temática A1 - caso Panamá v2",
                "",
                f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}",
                "",
                summary.to_markdown(index=False),
            ]
        ),
        encoding="utf-8",
    )
    print("Homologación A1 Panamá completada.")
    print("Salida GPKG:", output_gpkg)
    print("Tablas:", tables_dir)
    print("Reporte:", report_md)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        raise
