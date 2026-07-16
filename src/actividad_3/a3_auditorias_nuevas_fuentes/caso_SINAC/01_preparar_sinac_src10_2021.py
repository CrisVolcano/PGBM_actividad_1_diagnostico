from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
BASE_SCRIPT = PROJECT_DIR / "src/actividad_3/a3_auditorias_nuevas_fuentes/01_preparar_sinac_auditoria_espectral.py"
CONFIG = PROJECT_DIR / "config/a3_auditorias_nuevas_fuentes/caso_SINAC/config_sinac_src10_2021.yaml"


def resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def main() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    root_value = Path(config.get("paths", {}).get("project_root", "../../.."))
    root = root_value if root_value.is_absolute() else (CONFIG.parent / root_value).resolve()
    cfg = config["preparation"]
    cmd = [
        sys.executable,
        str(BASE_SCRIPT),
        "--input-gpkg",
        str(resolve_path(cfg["input_gpkg"], root)),
        "--output-gpkg",
        str(resolve_path(cfg["output_gpkg"], root)),
        "--output-layer",
        str(cfg["output_layer"]),
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
