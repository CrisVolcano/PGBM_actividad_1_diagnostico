# -*- coding: utf-8 -*-
"""
Actividad 4.8.6 - Importancia por permutacion para SVM
======================================================

Calcula importancia de predictores originales sobre validacion independiente
para un modelo SVM ya entrenado. La practica principal apunta al SVM Nystroem
RBF refinado, cuyos coeficientes internos no son interpretables directamente en
el espacio original de predictores.

Ejecucion desde la raiz del repositorio:

    python src/actividad_4/SVM/4_8_6_svm_permutation_importance.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
import yaml
from sklearn.inspection import permutation_importance
from sklearn.metrics import f1_score, make_scorer


LOGGER = logging.getLogger("a4_8_6_svm_permutation_importance")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) >= 4 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_8_svm.yaml"
CONFIG_SECTION = "permutation_importance"


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el YAML de configuracion: {path}")
    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("El YAML debe contener un diccionario en la raiz.")
    return config


def split_config_arg(raw_arg: str | Path, default_section: str) -> tuple[Path, str]:
    raw_text = str(raw_arg)
    if "::" in raw_text:
        path_text, section = raw_text.split("::", 1)
        return resolve_path(path_text), section
    return resolve_path(raw_text), default_section


def select_config_section(config: dict[str, Any], section: str) -> dict[str, Any]:
    if section in config:
        selected = config[section]
        if not isinstance(selected, dict):
            raise ValueError(f"La seccion {section} debe contener un diccionario.")
        return selected
    return config


def ensure_dirs(output_dir: Path) -> None:
    for dirname in ["logs", "tables", "reports"]:
        (output_dir / dirname).mkdir(parents=True, exist_ok=True)


def configure_logger(output_dir: Path) -> None:
    ensure_dirs(output_dir)
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for handler in (
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            output_dir / "logs" / "a4_8_6_svm_permutation_importance.log",
            mode="w",
            encoding="utf-8",
        ),
    ):
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)


def read_text_list(path: Path, label: str) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"No existe {label}: {path}")
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def read_independent_dataset(config: dict[str, Any]) -> tuple[pd.DataFrame, Path, str]:
    paths = config["paths"]
    prefer_parquet = bool(config.get("read", {}).get("prefer_parquet", True))
    parquet_path = resolve_path(paths["independent_dataset_parquet"])
    csv_path = resolve_path(paths["independent_dataset_csv"])
    csv_encoding = str(config.get("read", {}).get("csv_encoding", "utf-8-sig"))

    if prefer_parquet and parquet_path.exists():
        LOGGER.info("Leyendo validacion independiente Parquet: %s", parquet_path)
        return pd.read_parquet(parquet_path), parquet_path, "parquet"
    if csv_path.exists():
        LOGGER.info("Leyendo validacion independiente CSV: %s", csv_path)
        return pd.read_csv(csv_path, encoding=csv_encoding, low_memory=False), csv_path, "csv"
    if parquet_path.exists():
        LOGGER.info("Leyendo validacion independiente Parquet: %s", parquet_path)
        return pd.read_parquet(parquet_path), parquet_path, "parquet"
    raise FileNotFoundError(f"No existe validacion independiente: {parquet_path} ni {csv_path}")


def prepare_xy(
    dataframe: pd.DataFrame,
    feature_columns: list[str],
    target: str,
    encoder: Any,
) -> tuple[pd.DataFrame, np.ndarray]:
    missing = sorted(set(feature_columns + [target]) - set(dataframe.columns))
    if missing:
        raise ValueError(f"Faltan columnas para permutacion SVM: {missing}")
    x = dataframe[feature_columns].copy()
    for column in feature_columns:
        x[column] = pd.to_numeric(x[column], errors="coerce")
    y_raw = dataframe[target].astype(str).str.strip()
    unseen = sorted(set(y_raw) - set(str(value) for value in encoder.classes_))
    if unseen:
        raise ValueError(f"Validacion independiente contiene clases no vistas por el encoder: {unseen}")
    return x, encoder.transform(y_raw)


def feature_family(feature: str) -> str:
    text = feature.lower()
    if "worldclim" in text or "wolrdclim" in text:
        return "WorldClim / bioclimaticas"
    if "glcm" in text and "sar" in text:
        return "Texturas GLCM SAR"
    if "glcm" in text:
        return "Texturas GLCM opticas"
    if "dem" in text:
        return "DEM / topografia"
    if text.startswith("mos_sar") or text.startswith("pred_a_sar") or "_sar_" in text:
        return "SAR"
    if "s2" in text or "msi" in text:
        return "Sentinel-2 / MSI espectral"
    return "Otros"


def score_f1_macro(model: Any, x: pd.DataFrame, y: np.ndarray) -> float:
    return float(f1_score(y, model.predict(x), average="macro", zero_division=0))


def compute_group_permutation_importance(
    model: Any,
    x: pd.DataFrame,
    y: np.ndarray,
    feature_columns: list[str],
    baseline_score: float,
    n_repeats: int,
    random_state: int,
) -> pd.DataFrame:
    groups: dict[str, list[str]] = {}
    for feature in feature_columns:
        groups.setdefault(feature_family(feature), []).append(feature)

    rng = np.random.default_rng(random_state)
    rows: list[dict[str, Any]] = []
    for group_name, columns in sorted(groups.items()):
        scores = []
        for repeat in range(1, n_repeats + 1):
            permuted = x.copy()
            shuffled_index = rng.permutation(len(permuted))
            permuted.loc[:, columns] = permuted.iloc[shuffled_index][columns].to_numpy()
            score = score_f1_macro(model, permuted, y)
            rows.append(
                {
                    "group": group_name,
                    "n_features": len(columns),
                    "repeat": repeat,
                    "baseline_score": baseline_score,
                    "permuted_score": score,
                    "importance": baseline_score - score,
                }
            )
            scores.append(score)
        LOGGER.info(
            "Grupo permutado: %s | features=%s | importancia_media=%.6f",
            group_name,
            len(columns),
            baseline_score - float(np.mean(scores)),
        )

    repeats = pd.DataFrame(rows)
    summary = (
        repeats.groupby(["group", "n_features"], dropna=False)
        .agg(
            baseline_score=("baseline_score", "first"),
            mean_permuted_score=("permuted_score", "mean"),
            std_permuted_score=("permuted_score", "std"),
            mean_importance=("importance", "mean"),
            std_importance=("importance", "std"),
        )
        .reset_index()
        .sort_values("mean_importance", ascending=False)
    )
    summary["rank"] = np.arange(1, len(summary) + 1)
    return summary


def write_report(
    config: dict[str, Any],
    output_dir: Path,
    dataset_path: Path,
    dataset_format: str,
    feature_importance: pd.DataFrame,
    group_importance: pd.DataFrame | None,
    metadata: dict[str, Any],
) -> None:
    outputs = config.get("outputs", {}) or {}
    report_path = output_dir / outputs.get("report_md", "reports/a4_8_6_svm_permutation_importance_report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Actividad 4.8.6 - Importancia por permutacion SVM",
        "",
        f"**Fecha:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Insumos",
        "",
        f"- Validacion independiente: `{relative_path(dataset_path)}` ({dataset_format})",
        f"- Modelo: `{relative_path(resolve_path(config['paths']['model_path']))}`",
        f"- Predictores evaluados: **{metadata['n_features']:,}**",
        f"- Filas evaluadas: **{metadata['n_rows']:,}**",
        "",
        "## Configuracion",
        "",
        f"- Metrica: `{metadata['scoring']}`",
        f"- Score baseline: `{metadata['baseline_score']:.6f}`",
        f"- Repeticiones por predictor: **{metadata['n_repeats']}**",
        f"- Semilla: `{metadata['random_state']}`",
        "",
        "## Top 20 predictores",
        "",
        feature_importance.head(20).to_markdown(index=False),
        "",
    ]
    if group_importance is not None and not group_importance.empty:
        lines.extend(
            [
                "## Importancia por familia",
                "",
                group_importance.to_markdown(index=False),
                "",
            ]
        )
    lines.extend(
        [
            "## Nota metodologica",
            "",
            "La importancia se calcula como la caida de `f1_macro` al permutar cada "
            "predictor original sobre la validacion independiente. No se reentrena "
            "el modelo; se evalua la sensibilidad del pipeline ya entrenado.",
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Reporte escrito: %s", report_path)


def run(config: dict[str, Any]) -> None:
    output_dir = resolve_path(config["paths"]["output_dir"])
    configure_logger(output_dir)

    feature_columns = read_text_list(resolve_path(config["paths"]["selected_features_txt"]), "selected_features_txt")
    dataframe, dataset_path, dataset_format = read_independent_dataset(config)
    model = joblib.load(resolve_path(config["paths"]["model_path"]))
    encoder = joblib.load(resolve_path(config["paths"]["label_encoder_path"]))

    target = str(config["fields"]["target"])
    x, y = prepare_xy(dataframe, feature_columns, target, encoder)
    perm_cfg = config.get("permutation", {}) or {}
    scoring = str(perm_cfg.get("scoring", "f1_macro"))
    if scoring != "f1_macro":
        raise ValueError("Por ahora solo se soporta permutation.scoring: f1_macro.")
    n_repeats = int(perm_cfg.get("n_repeats", 5))
    random_state = int(perm_cfg.get("random_state", 42))
    n_jobs = int(perm_cfg.get("n_jobs", 1))

    baseline_score = score_f1_macro(model, x, y)
    LOGGER.info(
        "Calculando importancia por permutacion SVM: filas=%s | features=%s | repeats=%s | baseline_f1_macro=%.6f",
        f"{len(x):,}",
        f"{len(feature_columns):,}",
        n_repeats,
        baseline_score,
    )
    result = permutation_importance(
        model,
        x,
        y,
        scoring=make_scorer(f1_score, average="macro", zero_division=0),
        n_repeats=n_repeats,
        random_state=random_state,
        n_jobs=n_jobs,
    )

    feature_importance = pd.DataFrame(
        {
            "feature": feature_columns,
            "feature_family": [feature_family(feature) for feature in feature_columns],
            "baseline_score": baseline_score,
            "mean_importance": result.importances_mean,
            "std_importance": result.importances_std,
            "mean_permuted_score": baseline_score - result.importances_mean,
        }
    ).sort_values("mean_importance", ascending=False)
    feature_importance["rank"] = np.arange(1, len(feature_importance) + 1)

    group_importance = None
    if bool(perm_cfg.get("compute_group_importance", True)):
        group_importance = compute_group_permutation_importance(
            model,
            x,
            y,
            feature_columns,
            baseline_score,
            n_repeats,
            random_state,
        )

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scoring": scoring,
        "baseline_score": baseline_score,
        "n_rows": int(len(x)),
        "n_features": int(len(feature_columns)),
        "n_repeats": n_repeats,
        "random_state": random_state,
        "n_jobs": n_jobs,
        "sklearn_runtime_version": sklearn.__version__,
        "model_path": relative_path(resolve_path(config["paths"]["model_path"])),
        "label_encoder_path": relative_path(resolve_path(config["paths"]["label_encoder_path"])),
        "independent_dataset_path": relative_path(dataset_path),
    }

    outputs = config.get("outputs", {}) or {}
    feature_importance.to_csv(
        output_dir / outputs.get("feature_importance_csv", "tables/svm_permutation_feature_importance.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    if group_importance is not None:
        group_importance.to_csv(
            output_dir / outputs.get("group_importance_csv", "tables/svm_permutation_group_importance.csv"),
            index=False,
            encoding="utf-8-sig",
        )
    (output_dir / outputs.get("metadata_json", "tables/svm_permutation_importance_metadata.json")).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_report(config, output_dir, dataset_path, dataset_format, feature_importance, group_importance, metadata)
    LOGGER.info("A4.8.6 finalizado.")


def main() -> None:
    raw_arg = sys.argv[1] if len(sys.argv) > 1 else f"{DEFAULT_CONFIG}::{CONFIG_SECTION}"
    config_path, section = split_config_arg(raw_arg, CONFIG_SECTION)
    config = select_config_section(read_yaml(config_path), section)
    run(config)


if __name__ == "__main__":
    main()
