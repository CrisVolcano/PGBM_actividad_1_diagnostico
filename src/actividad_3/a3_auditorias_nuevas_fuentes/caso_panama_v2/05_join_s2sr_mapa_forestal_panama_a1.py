from __future__ import annotations

from pathlib import Path
import argparse
import importlib.util
import sys
from typing import Any

import yaml


# =============================================================================
# PGBM - Join Panama SRC15 2021 records with Sentinel-2 SR monthly values
# =============================================================================
# Este script conserva la metodologia del modulo general de union S2SR.
#
# La adaptacion del caso Panama se realiza por YAML y por constantes de salida:
# fuente SRC15, rutas caso_panama_v2 y nombres de capas del mapa forestal Panama.
# =============================================================================


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
DEFAULT_CONFIG = (
    PROJECT_DIR
    / "config"
    / "a3_auditorias_nuevas_fuentes"
    / "caso_panama_v2"
    / "config_mapa_forestal_panama_2021_a1.yaml"
)
GENERAL_SCRIPT_CANDIDATES = sorted(
    (
        PROJECT_DIR
        / "src"
        / "actividad_3"
        / "a3_auditorias_nuevas_fuentes"
    ).glob("05_join_s2sr_to_*_records.py")
)
GENERAL_SCRIPT = GENERAL_SCRIPT_CANDIDATES[0] if GENERAL_SCRIPT_CANDIDATES else Path()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el YAML: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"El YAML no contiene un diccionario valido: {path}")
    return data


def resolve_project_root(config: dict[str, Any], config_path: Path) -> Path:
    paths_cfg = config.get("paths", {})
    if isinstance(paths_cfg, dict) and paths_cfg.get("project_root"):
        root = Path(paths_cfg["project_root"])
        return root.resolve() if root.is_absolute() else (config_path.parent / root).resolve()
    return PROJECT_DIR


def resolve_path(path_value: str | Path, project_root: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def load_base_module():
    if not GENERAL_SCRIPT.exists():
        raise FileNotFoundError(f"No existe el script metodologico base: {GENERAL_SCRIPT}")
    spec = importlib.util.spec_from_file_location("join_s2sr_base", GENERAL_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar el script base: {GENERAL_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Une registros Panama SRC15 2021 con export Sentinel-2 SR mensual."
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"YAML del caso Panama. Por defecto: {DEFAULT_CONFIG}",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Permite continuar aunque algunos extract_id no aparezcan en GEE.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = load_yaml(config_path)
    project_root = resolve_project_root(config, config_path)
    join_cfg = config.get("s2sr_join", {})
    if not isinstance(join_cfg, dict) or not join_cfg:
        raise ValueError("El YAML debe incluir la seccion s2sr_join.")

    layers = join_cfg.get("layers", {})
    if not isinstance(layers, dict):
        layers = {}

    module = load_base_module()

    module.SOURCE_NAME = config["source"]["fuente_reporte"]
    module.SOURCE_ID = str(config["source"]["id_fuente"])
    module.SOURCE_CODE = f"SRC{int(config['source']['id_fuente']):02d}"
    module.COUNTRY_CODE = str(config["source"].get("pais_cod3", "PAN"))
    module.YEAR_REF = str(config["source"].get("anio", 2021))

    module.LAYER_FULL = str(layers.get("full", "mapa_forestal_panama_src15_records_s2sr_full"))
    module.LAYER_REDUCED = str(layers.get("reduced", "mapa_forestal_panama_src15_records_s2sr_reduced"))
    module.LAYER_ANNUAL = str(layers.get("annual", "mapa_forestal_panama_src15_records_s2sr_annual"))
    module.LAYER_UNITS_ANNUAL = str(
        layers.get("extract_units_annual", "mapa_forestal_panama_src15_extract_units_s2sr_annual")
    )
    module.DEFAULT_REPORT_NAME = str(
        join_cfg.get("report_name", "join_s2sr_to_mapa_forestal_panama_src15_2021_records_report.md")
    )

    argv = [
        str(GENERAL_SCRIPT),
        "--reference-gpkg",
        str(resolve_path(join_cfg["input_gpkg"], project_root)),
        "--reference-layer",
        str(join_cfg["input_layer"]),
        "--gee-export-dir",
        str(resolve_path(join_cfg["gee_export_dir"], project_root)),
        "--gee-export-prefix",
        str(join_cfg["gee_export_prefix"]),
        "--output-gpkg",
        str(resolve_path(join_cfg["output_gpkg"], project_root)),
        "--tables-dir",
        str(resolve_path(join_cfg["tables_dir"], project_root)),
        "--reports-dir",
        str(resolve_path(join_cfg["reports_dir"], project_root)),
    ]
    if args.allow_missing:
        argv.append("--allow-missing")

    old_argv = sys.argv
    try:
        sys.argv = argv
        module.main()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    main()
