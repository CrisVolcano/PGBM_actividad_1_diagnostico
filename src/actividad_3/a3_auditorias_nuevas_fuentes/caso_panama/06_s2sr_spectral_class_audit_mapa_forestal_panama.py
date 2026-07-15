from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]
BASE_SCRIPT = (
    PROJECT_DIR
    / "src/actividad_3/a3_auditorias_nuevas_fuentes/06_s2sr_spectral_class_audit_sinac_src10_2021.py"
)
CONFIG_DEFAULT = (
    PROJECT_DIR
    / "config/a3_auditorias_nuevas_fuentes/caso_panama/config_mapa_forestal_panama_2021.yaml"
)

PANAMA_CLASS_RULES = [
    {
        "class_code": 1,
        "class_name": "Broadleaf Evergreen Mature Forest",
        "expected_signal_group": "vegetacion_forestal_esperada",
        "medium_rule": "NDVI < 0.40 o NDRE < 0.10",
        "high_rule": "NDVI < 0.30 o NDRE < 0.06",
        "note": "Bosque maduro: se espera vegetacion persistente con senal fotosintetica alta.",
    },
    {
        "class_code": 2,
        "class_name": "Broadleaf Evergreen Secondary Forest",
        "expected_signal_group": "vegetacion_forestal_esperada",
        "medium_rule": "NDVI < 0.40 o NDRE < 0.10",
        "high_rule": "NDVI < 0.30 o NDRE < 0.06",
        "note": "Bosque secundario: misma regla piloto que bosque maduro.",
    },
    {
        "class_code": 3,
        "class_name": "Mangrove Forest",
        "expected_signal_group": "vegetacion_humeda_mixta",
        "medium_rule": "NDVI < 0.40 o NDRE < 0.08",
        "high_rule": "NDVI < 0.30 o NDRE < 0.05",
        "note": "Manglar: tolera mezcla agua-vegetacion y borde a 20 m.",
    },
    {
        "class_code": 7,
        "class_name": "Coniferous Plantation",
        "expected_signal_group": "vegetacion_forestal_esperada",
        "medium_rule": "NDVI < 0.40 o NDRE < 0.10",
        "high_rule": "NDVI < 0.30 o NDRE < 0.06",
        "note": "Plantacion forestal: se evalua como vegetacion arborea esperada.",
    },
    {
        "class_code": 8,
        "class_name": "Broadleaf Plantation",
        "expected_signal_group": "vegetacion_forestal_esperada",
        "medium_rule": "NDVI < 0.40 o NDRE < 0.10",
        "high_rule": "NDVI < 0.30 o NDRE < 0.06",
        "note": "Plantacion latifoliada: se evalua como vegetacion arborea esperada.",
    },
    {
        "class_code": 9,
        "class_name": "Shrubs",
        "expected_signal_group": "vegetacion_natural_baja",
        "medium_rule": "NDVI < 0.20 o NDRE < 0.03 o NDVI > 0.85",
        "high_rule": "NDVI < 0.10",
        "note": "Arbustos: clase natural baja, potencialmente heterogenea.",
    },
    {
        "class_code": 10,
        "class_name": "Herbaceous Vegetation",
        "expected_signal_group": "vegetacion_herbacea_estacional",
        "medium_rule": "NDVI < 0.18 o NDVI > 0.82",
        "high_rule": "NDVI < 0.08",
        "note": "Vegetacion herbacea: umbrales conservadores por estacionalidad.",
    },
    {
        "class_code": 11,
        "class_name": "Low Flooded Vegetation",
        "expected_signal_group": "vegetacion_humeda_mixta",
        "medium_rule": "NDVI < 0.05 o NDVI > 0.80 o NDRE > 0.20",
        "high_rule": "No aplica por umbral fijo",
        "note": "Vegetacion inundable: clase mixta agua-vegetacion.",
    },
    {
        "class_code": 12,
        "class_name": "Rocks And Natural Bare Soil",
        "expected_signal_group": "no_vegetacion_esperada",
        "medium_rule": "NDVI > 0.30 o NDRE > 0.08",
        "high_rule": "NDVI > 0.45 o NDRE > 0.12",
        "note": "Suelo desnudo natural: senal vegetal alta sugiere mezcla o cambio.",
    },
    {
        "class_code": 13,
        "class_name": "Beaches And Sand",
        "expected_signal_group": "no_vegetacion_esperada",
        "medium_rule": "NDVI > 0.30 o NDRE > 0.08",
        "high_rule": "NDVI > 0.45 o NDRE > 0.12",
        "note": "Playas y arena: senal vegetal alta sugiere borde o inconsistencia.",
    },
    {
        "class_code": 14,
        "class_name": "Coffee",
        "expected_signal_group": "vegetacion_agricola_variable",
        "medium_rule": "NDVI < 0.15 o NDVI > 0.90 o NDRE < 0.01",
        "high_rule": "NDVI < 0.05",
        "note": "Cultivo permanente: regla conservadora por manejo y sombra.",
    },
    {
        "class_code": 15,
        "class_name": "Citrus",
        "expected_signal_group": "vegetacion_agricola_variable",
        "medium_rule": "NDVI < 0.15 o NDVI > 0.90 o NDRE < 0.01",
        "high_rule": "NDVI < 0.05",
        "note": "Cultivo permanente: regla conservadora.",
    },
    {
        "class_code": 16,
        "class_name": "Oil Palm",
        "expected_signal_group": "vegetacion_agricola_variable",
        "medium_rule": "NDVI < 0.20 o NDRE < 0.03",
        "high_rule": "NDVI < 0.10",
        "note": "Palma aceitera: se espera senal vegetal persistente.",
    },
    {
        "class_code": 18,
        "class_name": "Other Permanent Crop",
        "expected_signal_group": "vegetacion_agricola_variable",
        "medium_rule": "NDVI < 0.15 o NDVI > 0.90 o NDRE < 0.01",
        "high_rule": "NDVI < 0.05",
        "note": "Cultivo permanente variable.",
    },
    {
        "class_code": 19,
        "class_name": "Rice",
        "expected_signal_group": "vegetacion_agricola_estacional",
        "medium_rule": "NDVI < 0.10 o NDVI > 0.90",
        "high_rule": "No aplica por umbral fijo",
        "note": "Arroz: alta variabilidad por inundacion, crecimiento y cosecha.",
    },
    {
        "class_code": 20,
        "class_name": "Sugar Cane",
        "expected_signal_group": "vegetacion_agricola_estacional",
        "medium_rule": "NDVI < 0.10 o NDVI > 0.90",
        "high_rule": "No aplica por umbral fijo",
        "note": "Cana de azucar: variabilidad por ciclo y cosecha.",
    },
    {
        "class_code": 23,
        "class_name": "Pineapple",
        "expected_signal_group": "vegetacion_agricola_variable",
        "medium_rule": "NDVI < 0.10 o NDVI > 0.90",
        "high_rule": "No aplica por umbral fijo",
        "note": "Pina: cobertura agricola variable y estructura baja.",
    },
    {
        "class_code": 24,
        "class_name": "Other Annual Crop",
        "expected_signal_group": "vegetacion_agricola_estacional",
        "medium_rule": "NDVI < 0.10 o NDVI > 0.90",
        "high_rule": "No aplica por umbral fijo",
        "note": "Cultivo anual: clase dependiente del calendario agricola.",
    },
    {
        "class_code": 25,
        "class_name": "Heterogeneous Agricultural Area",
        "expected_signal_group": "vegetacion_agricola_variable",
        "medium_rule": "NDVI < 0.10 o NDVI > 0.90",
        "high_rule": "No aplica por umbral fijo",
        "note": "Mosaico agricola heterogeneo.",
    },
    {
        "class_code": 26,
        "class_name": "Pasture",
        "expected_signal_group": "vegetacion_herbacea_estacional",
        "medium_rule": "NDVI < 0.25 o NDVI > 0.75",
        "high_rule": "NDVI < 0.18",
        "note": "Pasto: regla conservadora por manejo ganadero y estacionalidad.",
    },
    {
        "class_code": 27,
        "class_name": "Water",
        "expected_signal_group": "agua_baja_vegetacion",
        "medium_rule": "NDVI > 0.20 o NDRE > 0.04",
        "high_rule": "NDVI > 0.35 o NDRE > 0.08",
        "note": "Agua: senal vegetal alta sugiere borde, humedal o mezcla.",
    },
    {
        "class_code": 28,
        "class_name": "Populated Area",
        "expected_signal_group": "no_vegetacion_urbana",
        "medium_rule": "NDVI > 0.40 o NDRE > 0.12",
        "high_rule": "NDVI > 0.55 o NDVI > 0.50 y NDRE > 0.12",
        "note": "Urbano: puede haber mezcla con arbolado, jardines o bordes.",
    },
    {
        "class_code": 29,
        "class_name": "Infrastructure",
        "expected_signal_group": "no_vegetacion_urbana",
        "medium_rule": "NDVI > 0.40 o NDRE > 0.12",
        "high_rule": "NDVI > 0.55 o NDVI > 0.50 y NDRE > 0.12",
        "note": "Infraestructura: puede mezclar vegetacion de borde.",
    },
    {
        "class_code": 31,
        "class_name": "Aquaculture Pond",
        "expected_signal_group": "agua_baja_vegetacion",
        "medium_rule": "NDVI > 0.20 o NDRE > 0.04",
        "high_rule": "NDVI > 0.35 o NDRE > 0.08",
        "note": "Estanque acuicola: senal vegetal alta sugiere borde o vegetacion flotante.",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ejecuta el paso 06 de auditoria espectral para el mapa forestal de Panama."
    )
    parser.add_argument("--config", default=str(CONFIG_DEFAULT), help="Ruta al YAML del caso Panama.")
    return parser.parse_args()


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_DIR / path).resolve()


def load_base_module():
    spec = importlib.util.spec_from_file_location("s2sr_spectral_class_audit_base", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar el script base: {BASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def is_number(value: Any) -> bool:
    try:
        return pd.notna(float(value))
    except Exception:
        return False


def evaluate_panama_class_rule(row: pd.Series) -> tuple[str, str]:
    code_raw = row.get("audit_class_code", np.nan)
    if pd.isna(code_raw):
        return "none", "Sin codigo de clase para regla espectral"

    code = int(code_raw)
    ndvi = row.get("s2yr_ndvi_median", np.nan)
    ndre = row.get("s2yr_ndre_median", np.nan)

    ndvi_ok = is_number(ndvi)
    ndre_ok = is_number(ndre)
    if not ndvi_ok and not ndre_ok:
        return "none", "Sin NDVI/NDRE anual disponible"

    ndvi_v = float(ndvi) if ndvi_ok else np.nan
    ndre_v = float(ndre) if ndre_ok else np.nan

    def lt(value: float, threshold: float) -> bool:
        return pd.notna(value) and value < threshold

    def gt(value: float, threshold: float) -> bool:
        return pd.notna(value) and value > threshold

    if code in {1, 2, 7, 8}:
        if lt(ndvi_v, 0.30) or lt(ndre_v, 0.06):
            return "high", "Bosque/plantacion forestal con NDVI < 0.30 o NDRE < 0.06"
        if lt(ndvi_v, 0.40) or lt(ndre_v, 0.10):
            return "medium", "Bosque/plantacion forestal con NDVI < 0.40 o NDRE < 0.10"
        return "none", "Senal compatible con bosque o plantacion forestal"

    if code == 3:
        if lt(ndvi_v, 0.30) or lt(ndre_v, 0.05):
            return "high", "Manglar con NDVI < 0.30 o NDRE < 0.05"
        if lt(ndvi_v, 0.40) or lt(ndre_v, 0.08):
            return "medium", "Manglar con NDVI < 0.40 o NDRE < 0.08"
        return "none", "Senal compatible con manglar"

    if code == 9:
        if lt(ndvi_v, 0.10):
            return "high", "Arbustos con NDVI < 0.10"
        if lt(ndvi_v, 0.20) or lt(ndre_v, 0.03) or gt(ndvi_v, 0.85):
            return "medium", "Arbustos con senal baja o excepcionalmente alta"
        return "none", "Senal compatible con arbustos"

    if code == 10:
        if lt(ndvi_v, 0.08):
            return "high", "Vegetacion herbacea con NDVI < 0.08"
        if lt(ndvi_v, 0.18) or gt(ndvi_v, 0.82):
            return "medium", "Vegetacion herbacea con NDVI bajo o muy alto"
        return "none", "Senal compatible con vegetacion herbacea"

    if code == 11:
        if lt(ndvi_v, 0.05) or gt(ndvi_v, 0.80) or gt(ndre_v, 0.20):
            return "medium", "Vegetacion inundable con senal extrema para clase mixta"
        return "none", "Senal compatible con vegetacion inundable mixta"

    if code in {12, 13}:
        if gt(ndvi_v, 0.45) or gt(ndre_v, 0.12):
            return "high", "Suelo desnudo/playa con NDVI > 0.45 o NDRE > 0.12"
        if gt(ndvi_v, 0.30) or gt(ndre_v, 0.08):
            return "medium", "Suelo desnudo/playa con NDVI > 0.30 o NDRE > 0.08"
        return "none", "Senal compatible con suelo desnudo, arena o playa"

    if code in {14, 15, 18}:
        if lt(ndvi_v, 0.05):
            return "high", "Cultivo permanente con NDVI < 0.05"
        if lt(ndvi_v, 0.15) or gt(ndvi_v, 0.90) or lt(ndre_v, 0.01):
            return "medium", "Cultivo permanente con senal extrema o muy baja"
        return "none", "Senal compatible con cultivo permanente"

    if code == 16:
        if lt(ndvi_v, 0.10):
            return "high", "Palma aceitera con NDVI < 0.10"
        if lt(ndvi_v, 0.20) or lt(ndre_v, 0.03):
            return "medium", "Palma aceitera con senal vegetal baja"
        return "none", "Senal compatible con palma aceitera"

    if code in {19, 20, 23, 24, 25}:
        if lt(ndvi_v, 0.10) or gt(ndvi_v, 0.90):
            return "medium", "Cultivo anual/mosaico agricola con NDVI extremo"
        return "none", "Senal compatible con variabilidad agricola estacional"

    if code == 26:
        if lt(ndvi_v, 0.18):
            return "high", "Pasto con NDVI < 0.18"
        if lt(ndvi_v, 0.25) or gt(ndvi_v, 0.75):
            return "medium", "Pasto con NDVI bajo o muy alto"
        return "none", "Senal compatible con pasto"

    if code in {27, 31}:
        if gt(ndvi_v, 0.35) or gt(ndre_v, 0.08):
            return "high", "Agua/acuicultura con NDVI > 0.35 o NDRE > 0.08"
        if gt(ndvi_v, 0.20) or gt(ndre_v, 0.04):
            return "medium", "Agua/acuicultura con NDVI > 0.20 o NDRE > 0.04"
        return "none", "Senal compatible con agua o estanque acuicola"

    if code in {28, 29}:
        if gt(ndvi_v, 0.55) or (gt(ndvi_v, 0.50) and gt(ndre_v, 0.12)):
            return "high", "Urbano/infraestructura con senal vegetal alta"
        if gt(ndvi_v, 0.40) or gt(ndre_v, 0.12):
            return "medium", "Urbano/infraestructura con senal vegetal moderada"
        return "none", "Senal compatible con urbano o infraestructura"

    return "none", "Clase del mapa forestal Panama sin regla espectral especifica"


def configure_module(module: Any, cfg: dict[str, Any]) -> tuple[Path, Path, Path]:
    source = cfg["source"]
    audit_cfg = cfg["spectral_class_audit"]
    layers = audit_cfg["layers"]

    module.SOURCE_NAME = source["fuente_reporte"]
    module.SOURCE_CODE = "SRC15"
    module.SOURCE_ID_EXPECTED = int(source["id_fuente"])
    module.COUNTRY_CODE_EXPECTED = source["pais_cod3"]
    module.YEAR_REF_EXPECTED = int(source["anio"])

    module.INPUT_LAYER_ORIGINAL_ANNUAL = layers["original_annual"]
    module.INPUT_LAYER_UNITS_ANNUAL = layers["extract_units_annual"]
    module.OUTPUT_GPKG_NAME = audit_cfg["output_gpkg_name"]
    module.REPORT_MD_NAME = audit_cfg["report_name"]

    module.LAYER_AUDIT_ORIGINAL = layers["audit_original"]
    module.LAYER_AUDIT_UNITS = layers["audit_units"]
    module.LAYER_PRIORITY_ORIGINAL = layers["priority_original"]
    module.LAYER_PRIORITY_UNITS = layers["priority_units"]
    module.LAYER_XY_GROUP_AUDIT = layers["xy_group_audit"]

    module.TABLE_CLASS_RULES = "mapa_forestal_panama_class_rules_reference"
    module.CLASS_RULES_CSV_NAME = "mapa_forestal_panama_class_rules_reference.csv"

    module.SINAC_CLASS_RULES = PANAMA_CLASS_RULES
    module.CLASS_RULES_BY_CODE = {int(row["class_code"]): row for row in PANAMA_CLASS_RULES}
    module.evaluate_class_rule = evaluate_panama_class_rule

    input_gpkg = resolve_path(audit_cfg["input_gpkg"])
    output_dir = resolve_path(audit_cfg["output_dir"])
    tables_dir = resolve_path(audit_cfg["tables_dir"])
    reports_dir = resolve_path(audit_cfg["reports_dir"])
    return input_gpkg, output_dir, tables_dir, reports_dir


def main() -> None:
    args = parse_args()
    config_path = resolve_path(args.config)
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    module = load_base_module()
    input_gpkg, output_dir, tables_dir, reports_dir = configure_module(module, cfg)

    sys.argv = [
        str(BASE_SCRIPT),
        "--input",
        str(input_gpkg),
        "--output-dir",
        str(output_dir),
        "--tables-dir",
        str(tables_dir),
        "--reports-dir",
        str(reports_dir),
    ]
    module.main()


if __name__ == "__main__":
    main()
