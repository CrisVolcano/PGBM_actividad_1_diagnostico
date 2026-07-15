from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
BASE_SCRIPT = PROJECT_DIR / "src/actividad_3/a3_auditorias_nuevas_fuentes/08_scoring_integral_nuevas_fuentes.py"
CONFIG = PROJECT_DIR / "config/a3_auditorias_nuevas_fuentes/caso_panama/config_mapa_forestal_panama_2021.yaml"


def main() -> None:
    cmd = [sys.executable, str(BASE_SCRIPT), "--config", str(CONFIG)]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
