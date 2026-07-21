# -*- coding: utf-8 -*-
"""
Actividad 4.8.4 - SVM no lineal aproximado con Nystroem RBF
===========================================================

Wrapper para ejecutar el entrenador SVM con una configuracion no lineal
aproximada:

    SimpleImputer -> StandardScaler -> Nystroem(RBF) -> LinearSVC

Ejecucion desde la raiz del repositorio:

    python src/actividad_4/SVM/4_8_4_train_nystroem_rbf_svm.py
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
TRAINER = SCRIPT_PATH.with_name("4_8_3_train_linear_svm.py")
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) >= 4 else Path.cwd()
CONFIG = REPO_ROOT / "config" / "a4_8_svm.yaml::nystroem_rbf_svm"


if __name__ == "__main__":
    if len(sys.argv) > 1:
        config = sys.argv[1] if "::" in sys.argv[1] else str(Path(sys.argv[1]).resolve())
    else:
        config = str(CONFIG)
    sys.argv = [str(TRAINER), config]
    runpy.run_path(str(TRAINER), run_name="__main__")
