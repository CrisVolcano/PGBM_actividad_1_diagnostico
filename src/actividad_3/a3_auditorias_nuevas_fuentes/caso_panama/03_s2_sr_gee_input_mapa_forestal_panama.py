from __future__ import annotations

from pathlib import Path
import runpy
import sys


# =============================================================================
# PGBM - Preparacion GEE Sentinel-2 SR para caso Panama
# =============================================================================
# Este script conserva la metodologia del modulo general:
#   src/actividad_3/a3_auditorias_nuevas_fuentes/
#   03_s2_sr_gee_input_nuevas_fuentes_caso_SINAC.py
#
# La adaptacion del caso Panama vive en el YAML:
#   config/a3_auditorias_nuevas_fuentes/caso_panama/
#   config_mapa_forestal_panama_2021.yaml
# =============================================================================


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
GENERAL_SCRIPT = (
    PROJECT_DIR
    / "src"
    / "actividad_3"
    / "a3_auditorias_nuevas_fuentes"
    / "03_s2_sr_gee_input_nuevas_fuentes_caso_SINAC.py"
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

    if "--config" not in sys.argv:
        sys.argv.extend(["--config", str(DEFAULT_CONFIG)])

    runpy.run_path(str(GENERAL_SCRIPT), run_name="__main__")


if __name__ == "__main__":
    main()
