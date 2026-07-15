from __future__ import annotations

from pathlib import Path
import runpy
import sys


# =============================================================================
# PGBM - Grupos XY para caso Panama
# =============================================================================
# Este script conserva la metodologia del modulo general:
#   src/actividad_3/a3_auditorias_nuevas_fuentes/02_xy_groups_nuevas_fuentes.py
#
# La adaptacion del caso Panama vive en el YAML:
#   config/a3_auditorias_nuevas_fuentes/caso_panama/
#   config_mapa_forestal_panama_2021.yaml
#
# Se genera un archivo nuevo para mantener la serie de codigos del caso Panama
# separada del caso SINAC original, sin duplicar la implementacion metodologica.
# =============================================================================


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
GENERAL_SCRIPT = (
    PROJECT_DIR
    / "src"
    / "actividad_3"
    / "a3_auditorias_nuevas_fuentes"
    / "02_xy_groups_nuevas_fuentes.py"
)
DEFAULT_CONFIG = (
    PROJECT_DIR
    / "config"
    / "a3_auditorias_nuevas_fuentes"
    / "caso_panama"
    / "config_mapa_forestal_panama_2021.yaml"
)


def main() -> None:
    if not GENERAL_SCRIPT.exists():
        raise FileNotFoundError(f"No existe el script metodologico base: {GENERAL_SCRIPT}")
    if not DEFAULT_CONFIG.exists():
        raise FileNotFoundError(f"No existe el YAML del caso Panama: {DEFAULT_CONFIG}")

    # Si el usuario no pasa --config, se inyecta el YAML del caso Panama.
    if "--config" not in sys.argv:
        sys.argv.extend(["--config", str(DEFAULT_CONFIG)])

    runpy.run_path(str(GENERAL_SCRIPT), run_name="__main__")


if __name__ == "__main__":
    main()
