from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
BASE_SCRIPT = PROJECT_DIR / "src/actividad_3/a3_auditorias_nuevas_fuentes/02_xy_groups_nuevas_fuentes.py"
CONFIG = PROJECT_DIR / "config/a3_auditorias_nuevas_fuentes/caso_SINAC/config_sinac_src10_2021.yaml"


def main() -> None:
    subprocess.run([sys.executable, str(BASE_SCRIPT), "--config", str(CONFIG)], check=True)


if __name__ == "__main__":
    main()
