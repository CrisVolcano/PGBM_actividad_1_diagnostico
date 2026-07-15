from __future__ import annotations

from pathlib import Path
import runpy
import sys


# =============================================================================
# PGBM - Reporte de exportacion GEE para caso Panama
# =============================================================================
# Este script conserva la metodologia del modulo general:
#   src/actividad_3/a3_auditorias_nuevas_fuentes/
#   04_generate_gee_export_report_sinac_src10_2021.py
#
# La adaptacion del caso Panama fija rutas, patron CSV y metadatos de fuente
# para MIAMBIENTE - Cultivos Mapa Panama, SRC15, 2021.
# =============================================================================


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
GENERAL_SCRIPT = (
    PROJECT_DIR
    / "src"
    / "actividad_3"
    / "a3_auditorias_nuevas_fuentes"
    / "04_generate_gee_export_report_sinac_src10_2021.py"
)


def main() -> None:
    if not GENERAL_SCRIPT.exists():
        raise FileNotFoundError(f"No existe el script metodologico base: {GENERAL_SCRIPT}")

    default_args = [
        "--js",
        str(
            PROJECT_DIR
            / "scripts"
            / "gee"
            / "a3_auditorias_nuevas_fuentes"
            / "s2_sr_monthly_s2cloudless_export_mapa_forestal_panama_src15_2021.js"
        ),
        "--raw-dir",
        str(
            PROJECT_DIR
            / "data"
            / "processed"
            / "a3_auditorias_nuevas_fuentes"
            / "caso_panama"
            / "gee_exports"
        ),
        "--csv-pattern",
        "pgbm_s2sr_monthly_s2cloudless_mapa_forestal_panama_src15_2021*.csv",
        "--output",
        str(
            PROJECT_DIR
            / "outputs"
            / "reports"
            / "a3_auditorias_nuevas_fuentes"
            / "caso_panama"
            / "gee_input"
            / "gee_export_report_mapa_forestal_panama_src15_2021.md"
        ),
        "--source-name",
        "MIAMBIENTE - Cultivos Mapa Panamá",
        "--source-id",
        "15",
        "--source-code",
        "SRC15",
        "--country-code",
        "PAN",
        "--year-ref",
        "2021",
    ]

    # Permite sobrescribir manualmente cualquier argumento si se invoca el
    # wrapper con parametros propios.
    if len(sys.argv) == 1:
        sys.argv.extend(default_args)

    runpy.run_path(str(GENERAL_SCRIPT), run_name="__main__")


if __name__ == "__main__":
    main()
