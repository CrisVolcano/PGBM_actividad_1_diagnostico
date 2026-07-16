from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
BASE_SCRIPT = PROJECT_DIR / "src/actividad_3/a3_auditorias_nuevas_fuentes/05_join_s2sr_to_sinac_src10_2021_records.py"
CONFIG = PROJECT_DIR / "config/a3_auditorias_nuevas_fuentes/caso_SINAC/config_sinac_src10_2021.yaml"


def resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def main() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    root_value = Path(config.get("paths", {}).get("project_root", "../../.."))
    root = root_value if root_value.is_absolute() else (CONFIG.parent / root_value).resolve()
    cfg = config["s2sr_join"]
    cmd = [
        sys.executable,
        str(BASE_SCRIPT),
        "--reference-gpkg",
        str(resolve_path(cfg["input_gpkg"], root)),
        "--reference-layer",
        str(cfg["input_layer"]),
        "--gee-export-dir",
        str(resolve_path(cfg["gee_export_dir"], root)),
        "--gee-export-prefix",
        str(cfg["gee_export_prefix"]),
        "--output-gpkg",
        str(resolve_path(cfg["output_gpkg"], root)),
        "--tables-dir",
        str(resolve_path(cfg["tables_dir"], root)),
        "--reports-dir",
        str(resolve_path(Path(cfg["report_md"]).parent, root)),
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
