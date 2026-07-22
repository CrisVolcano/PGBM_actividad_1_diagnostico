# -*- coding: utf-8 -*-
"""Wrapper GPU para hiperparametrizar XGBoost con `device='cuda'`."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) >= 4 else Path.cwd()
CPU_SCRIPT = REPO_ROOT / "src" / "actividad_4" / "XGBoost" / "4_9_3_train_xgboost_gridsearch.py"
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_9_xgboost_gpu.yaml"
CONFIG_SECTION = "gridsearch"


def load_cpu_module():
    spec = importlib.util.spec_from_file_location("a4_9_3_train_xgboost_gridsearch", CPU_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"No se pudo cargar {CPU_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_cpu_module()
    config_arg = sys.argv[1] if len(sys.argv) > 1 else f"{DEFAULT_CONFIG}::{CONFIG_SECTION}"
    config_path, config_section = module.split_config_arg(config_arg, CONFIG_SECTION)
    config = module.select_config_section(module.read_yaml(config_path), config_section)
    module.run_training(config)


if __name__ == "__main__":
    main()
