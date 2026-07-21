# -*- coding: utf-8 -*-
"""
Actividad 4.8.3 - Entrenamiento SVM lineal
==========================================

Entrena un SVM lineal multiclase usando las particiones espaciales creadas en
A4.8.2. El pipeline incluye imputacion y escalamiento dentro de GridSearchCV
para evitar fuga de informacion.

Ejecucion desde la raiz del repositorio:

    python src/actividad_4/SVM/4_8_3_train_linear_svm.py
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
import yaml
from sklearn.base import clone
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
)
from sklearn.kernel_approximation import Nystroem
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.svm import LinearSVC


LOGGER = logging.getLogger("a4_8_3_train_linear_svm")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) >= 4 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_8_svm.yaml"
CONFIG_SECTION = "linear_svm_gridsearch"


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


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
    for dirname in ["logs", "tables", "reports", "models"]:
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
            output_dir / "logs" / "a4_8_3_train_linear_svm.log",
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


def read_partitioned_dataset(
    config: dict[str, Any],
    parquet_key: str,
    csv_key: str,
    label: str,
) -> tuple[pd.DataFrame, Path, str]:
    paths = config["paths"]
    prefer_parquet = bool(config.get("read", {}).get("prefer_parquet", True))
    parquet_path = resolve_path(paths[parquet_key])
    csv_path = resolve_path(paths[csv_key])
    csv_encoding = str(config.get("read", {}).get("csv_encoding", "utf-8-sig"))

    if prefer_parquet and parquet_path.exists():
        LOGGER.info("Leyendo %s Parquet: %s", label, parquet_path)
        return pd.read_parquet(parquet_path), parquet_path, "parquet"
    if csv_path.exists():
        LOGGER.info("Leyendo %s CSV: %s", label, csv_path)
        return pd.read_csv(csv_path, encoding=csv_encoding, low_memory=False), csv_path, "csv"
    if parquet_path.exists():
        LOGGER.info("Leyendo %s Parquet: %s", label, parquet_path)
        return pd.read_parquet(parquet_path), parquet_path, "parquet"
    raise FileNotFoundError(f"No existe {label}: {parquet_path} ni {csv_path}")


def normalize_core_fields(dataframe: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    fields = config["fields"]
    output = dataframe.copy()
    for field in [fields["key"], fields["group"], fields["target"]]:
        output[str(field)] = output[str(field)].astype(str).str.strip()
    label = fields.get("target_label")
    if label and str(label) in output.columns:
        output[str(label)] = output[str(label)].astype(str).str.strip()
    return output.reset_index(drop=True)


def validate_inputs(development: pd.DataFrame, independent: pd.DataFrame, feature_columns: list[str], config: dict[str, Any]) -> None:
    fields = config["fields"]
    required = [str(fields["key"]), str(fields["group"]), str(fields["target"])]
    label = fields.get("target_label")
    if label:
        required.append(str(label))
    required.extend(feature_columns)

    for name, dataframe in [("development", development), ("independent", independent)]:
        missing = sorted(set(required) - set(dataframe.columns))
        if missing:
            raise ValueError(f"Faltan columnas en {name}: {missing}")
        duplicated = int(dataframe[str(fields["key"])].duplicated().sum())
        if duplicated:
            raise ValueError(f"{name} tiene {duplicated:,} llaves duplicadas.")
        if dataframe[str(fields["target"])].isna().any():
            raise ValueError(f"{name} contiene nulos en el target {fields['target']}.")

    dev_classes = set(development[str(fields["target"])].astype(str))
    independent_classes = set(independent[str(fields["target"])].astype(str))
    unseen = sorted(independent_classes - dev_classes)
    if unseen:
        raise ValueError(f"Validacion independiente contiene clases no vistas en desarrollo: {unseen}")

    dev_groups = set(development[str(fields["group"])].astype(str))
    independent_groups = set(independent[str(fields["group"])].astype(str))
    overlap = sorted(dev_groups & independent_groups)
    if overlap:
        raise ValueError(f"Leakage espacial desarrollo/independiente: {overlap[:10]}")


def read_cv_splits(development: pd.DataFrame, config: dict[str, Any]) -> list[tuple[np.ndarray, np.ndarray]]:
    key = str(config["fields"]["key"])
    cv_path = resolve_path(config["paths"]["cv_fold_assignments_csv"])
    if not cv_path.exists():
        raise FileNotFoundError(f"No existe cv_fold_assignments_csv: {cv_path}")
    cv_assignments = pd.read_csv(cv_path, encoding=str(config.get("read", {}).get("csv_encoding", "utf-8-sig")))
    for field in [key, "fold_id", "cv_role"]:
        if field not in cv_assignments.columns:
            raise ValueError(f"cv_fold_assignments no contiene {field}.")

    key_to_position = {value: pos for pos, value in enumerate(development[key].astype(str))}
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    for fold_id in sorted(cv_assignments["fold_id"].dropna().unique()):
        fold = cv_assignments[cv_assignments["fold_id"] == fold_id].copy()
        train_keys = fold.loc[fold["cv_role"] == "cv_train", key].astype(str)
        validation_keys = fold.loc[fold["cv_role"] == "cv_validation", key].astype(str)
        train_idx = np.array([key_to_position[value] for value in train_keys if value in key_to_position], dtype=int)
        validation_idx = np.array([key_to_position[value] for value in validation_keys if value in key_to_position], dtype=int)
        if len(train_idx) == 0 or len(validation_idx) == 0:
            raise ValueError(f"Fold {fold_id} quedo vacio al reconstruir indices.")
        if set(train_idx) & set(validation_idx):
            raise ValueError(f"Leakage interno en fold {fold_id}: indices repetidos en train y validation.")
        splits.append((train_idx, validation_idx))

    if not splits:
        raise ValueError("No se reconstruyo ningun fold CV.")
    LOGGER.info("Folds CV reconstruidos desde asignaciones: %s", len(splits))
    return splits


def build_target_label_mapping(dataframe: pd.DataFrame, config: dict[str, Any]) -> dict[str, str]:
    target = str(config["fields"]["target"])
    label_field = config.get("fields", {}).get("target_label")
    if not label_field or str(label_field) not in dataframe.columns:
        return {}
    label = str(label_field)
    mapping: dict[str, str] = {}
    pairs = dataframe[[target, label]].dropna().drop_duplicates()
    for class_id, group in pairs.groupby(target, dropna=False):
        labels = sorted(str(value) for value in group[label].dropna().unique())
        if labels:
            mapping[str(class_id)] = labels[0]
    return mapping


def prepare_xy(
    dataframe: pd.DataFrame,
    feature_columns: list[str],
    target: str,
    encoder: LabelEncoder | None = None,
) -> tuple[pd.DataFrame, np.ndarray, LabelEncoder]:
    x = dataframe[feature_columns].copy()
    for column in feature_columns:
        x[column] = pd.to_numeric(x[column], errors="coerce")

    y_raw = dataframe[target].astype(str).str.strip().to_numpy()
    if encoder is None:
        encoder = LabelEncoder()
        y = encoder.fit_transform(y_raw)
    else:
        y = encoder.transform(y_raw)
    return x, y, encoder


def build_pipeline(config: dict[str, Any]) -> Pipeline:
    model_cfg = config.get("model", {}) or {}
    kernel_cfg = model_cfg.get("kernel_approximation", {}) or {}
    classifier = LinearSVC(
        random_state=int(model_cfg.get("random_state", 42)),
        max_iter=int(model_cfg.get("max_iter", 20000)),
        tol=float(model_cfg.get("tol", 0.0001)),
        dual=bool(model_cfg.get("dual", False)),
        loss=str(model_cfg.get("loss", "squared_hinge")),
        multi_class=str(model_cfg.get("multi_class", "ovr")),
        fit_intercept=bool(model_cfg.get("fit_intercept", True)),
    )
    steps: list[tuple[str, Any]] = [
        ("imputer", SimpleImputer(strategy=str(model_cfg.get("imputer_strategy", "median")))),
        ("scaler", StandardScaler()),
    ]
    if bool(kernel_cfg.get("enabled", False)):
        method = str(kernel_cfg.get("method", "nystroem")).lower()
        if method != "nystroem":
            raise ValueError(f"kernel_approximation.method no soportado: {method}")
        steps.append(
            (
                "kernel",
                Nystroem(
                    kernel=str(kernel_cfg.get("kernel", "rbf")),
                    gamma=float(kernel_cfg.get("gamma", 0.01)),
                    n_components=int(kernel_cfg.get("n_components", 300)),
                    random_state=int(model_cfg.get("random_state", 42)),
                ),
            )
        )
    steps.append(("clf", classifier))
    return Pipeline(steps=steps)


def normalize_param_grid(config: dict[str, Any]) -> dict[str, list[Any]]:
    grid = config.get("grid_search", {}).get("param_grid", {})
    if not isinstance(grid, dict) or not grid:
        raise ValueError("grid_search.param_grid debe ser un diccionario no vacio.")
    normalized: dict[str, list[Any]] = {}
    for key, value in grid.items():
        if not isinstance(value, list):
            value = [value]
        normalized[key] = value
    return normalized


def metric_row(y_true: np.ndarray, y_pred: np.ndarray, label: str) -> dict[str, Any]:
    return {
        "evaluation": label,
        "n_rows": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "f1_weighted": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
        "kappa": float(cohen_kappa_score(y_true, y_pred)),
    }


def classification_report_df(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    encoder: LabelEncoder,
    evaluation: str,
    class_labels: dict[str, str],
) -> pd.DataFrame:
    labels = np.arange(len(encoder.classes_))
    report = classification_report(
        y_true,
        y_pred,
        labels=labels,
        target_names=encoder.classes_.astype(str),
        output_dict=True,
        zero_division=0,
    )
    rows = []
    for label, values in report.items():
        if not isinstance(values, dict):
            continue
        row = {
            "evaluation": evaluation,
            "class_id": label,
            "class_label": class_labels.get(str(label)),
        }
        row.update(values)
        rows.append(row)
    return pd.DataFrame(rows)


def confusion_matrix_df(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    encoder: LabelEncoder,
    evaluation: str,
    class_labels: dict[str, str],
) -> pd.DataFrame:
    labels = np.arange(len(encoder.classes_))
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    rows = []
    for i, true_label in enumerate(encoder.classes_):
        for j, pred_label in enumerate(encoder.classes_):
            rows.append(
                {
                    "evaluation": evaluation,
                    "true_class": true_label,
                    "true_class_label": class_labels.get(str(true_label)),
                    "predicted_class": pred_label,
                    "predicted_class_label": class_labels.get(str(pred_label)),
                    "n": int(matrix[i, j]),
                }
            )
    return pd.DataFrame(rows)


def dataframe_to_markdown(dataframe: pd.DataFrame) -> str:
    if dataframe.empty:
        return "_Sin datos._"
    return dataframe.to_markdown(index=False)


def best_gridsearch_train_validation_metrics(search: GridSearchCV) -> pd.DataFrame:
    results = pd.DataFrame(search.cv_results_)
    best = results.iloc[int(search.best_index_)]
    rows = []
    scoring = search.scorer_ if isinstance(search.scorer_, dict) else {"score": search.scorer_}
    for metric in scoring:
        suffix = metric if metric != "score" else "score"
        rows.append(
            {
                "metric": metric,
                "mean_train_cv": best.get(f"mean_train_{suffix}"),
                "std_train_cv": best.get(f"std_train_{suffix}"),
                "mean_validation_cv": best.get(f"mean_test_{suffix}"),
                "std_validation_cv": best.get(f"std_test_{suffix}"),
                "rank_validation": best.get(f"rank_test_{suffix}"),
            }
        )
    return pd.DataFrame(rows)


def run_grid_search(
    development: pd.DataFrame,
    feature_columns: list[str],
    cv_splits: list[tuple[np.ndarray, np.ndarray]],
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[GridSearchCV, LabelEncoder, pd.DataFrame, np.ndarray]:
    target = str(config["fields"]["target"])
    x_dev, y_dev, encoder = prepare_xy(development, feature_columns, target=target, encoder=None)
    pipeline = build_pipeline(config)
    param_grid = normalize_param_grid(config)
    gs_cfg = config.get("grid_search", {}) or {}
    scoring = gs_cfg.get(
        "scoring",
        {"accuracy": "accuracy", "balanced_accuracy": "balanced_accuracy", "f1_macro": "f1_macro"},
    )

    combinations = int(np.prod([len(values) for values in param_grid.values()]))
    LOGGER.info("Iniciando GridSearchCV SVM lineal: combinaciones=%s | folds=%s", combinations, len(cv_splits))
    search = GridSearchCV(
        estimator=pipeline,
        param_grid=param_grid,
        scoring=scoring,
        refit=gs_cfg.get("refit", "f1_macro"),
        cv=cv_splits,
        n_jobs=int(gs_cfg.get("n_jobs", -1)),
        verbose=int(gs_cfg.get("verbose", 1)),
        return_train_score=bool(gs_cfg.get("return_train_score", True)),
        error_score=gs_cfg.get("error_score", "raise"),
    )
    search.fit(x_dev, y_dev)

    outputs = config.get("outputs", {}) or {}
    pd.DataFrame(search.cv_results_).to_csv(
        output_dir / outputs.get("gridsearch_results_csv", "tables/linear_svm_gridsearch_results.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    (output_dir / outputs.get("best_params_json", "tables/linear_svm_best_params.json")).write_text(
        json.dumps(search.best_params_, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    LOGGER.info("GridSearchCV SVM finalizado. Best score=%s | best_params=%s", search.best_score_, search.best_params_)
    return search, encoder, x_dev, y_dev


def evaluate_training(
    search: GridSearchCV,
    development: pd.DataFrame,
    x_dev: pd.DataFrame,
    y_dev: np.ndarray,
    encoder: LabelEncoder,
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    class_labels = build_target_label_mapping(development, config)
    y_pred = search.best_estimator_.predict(x_dev)
    metrics = pd.DataFrame([metric_row(y_dev, y_pred, label="training_development_resubstitution")])
    class_metrics = classification_report_df(y_dev, y_pred, encoder, "training_development_resubstitution", class_labels)
    confusion = confusion_matrix_df(y_dev, y_pred, encoder, "training_development_resubstitution", class_labels)

    outputs = config.get("outputs", {}) or {}
    metrics.to_csv(output_dir / outputs.get("training_metrics_csv", "tables/linear_svm_training_metrics.csv"), index=False, encoding="utf-8-sig")
    class_metrics.to_csv(output_dir / outputs.get("training_class_metrics_csv", "tables/linear_svm_training_class_metrics.csv"), index=False, encoding="utf-8-sig")
    confusion.to_csv(output_dir / outputs.get("training_confusion_csv", "tables/linear_svm_training_confusion_matrix.csv"), index=False, encoding="utf-8-sig")
    return metrics, class_metrics, confusion


def evaluate_best_model_cv(
    search: GridSearchCV,
    development: pd.DataFrame,
    x_dev: pd.DataFrame,
    y_dev: np.ndarray,
    encoder: LabelEncoder,
    cv_splits: list[tuple[np.ndarray, np.ndarray]],
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    key = str(config["fields"]["key"])
    group_field = str(config["fields"]["group"])
    class_labels = build_target_label_mapping(development, config)
    predictions = np.full(shape=len(y_dev), fill_value=-1, dtype=int)
    fold_rows = []
    pred_rows = []

    for fold_id, (train_idx, validation_idx) in enumerate(cv_splits, start=1):
        estimator = clone(search.best_estimator_)
        estimator.fit(x_dev.iloc[train_idx], y_dev[train_idx])
        fold_pred = estimator.predict(x_dev.iloc[validation_idx])
        predictions[validation_idx] = fold_pred
        fold_rows.append(metric_row(y_dev[validation_idx], fold_pred, label=f"cv_fold_{fold_id}"))

        for local_idx, pred in zip(validation_idx, fold_pred):
            y_true_class = str(encoder.inverse_transform([y_dev[local_idx]])[0])
            y_pred_class = str(encoder.inverse_transform([pred])[0])
            pred_rows.append(
                {
                    key: development.iloc[local_idx][key],
                    group_field: development.iloc[local_idx][group_field],
                    "fold_id": fold_id,
                    "split_role": "cv_validation",
                    "y_true": y_true_class,
                    "y_true_label": class_labels.get(y_true_class),
                    "y_pred": y_pred_class,
                    "y_pred_label": class_labels.get(y_pred_class),
                }
            )

    if np.any(predictions < 0):
        raise ValueError("No se generaron predicciones CV para todos los puntos de desarrollo.")

    overall_cv = pd.DataFrame([metric_row(y_dev, predictions, label="cv_oof_tuning_diagnostic")])
    fold_metrics = pd.DataFrame(fold_rows)
    class_metrics = classification_report_df(y_dev, predictions, encoder, "cv_oof_tuning_diagnostic", class_labels)
    confusion = confusion_matrix_df(y_dev, predictions, encoder, "cv_oof_tuning_diagnostic", class_labels)
    fold_predictions = pd.DataFrame(pred_rows)

    outputs = config.get("outputs", {}) or {}
    overall_cv.to_csv(output_dir / outputs.get("cv_overall_metrics_csv", "tables/linear_svm_cv_overall_metrics.csv"), index=False, encoding="utf-8-sig")
    fold_metrics.to_csv(output_dir / outputs.get("cv_fold_metrics_csv", "tables/linear_svm_cv_fold_metrics.csv"), index=False, encoding="utf-8-sig")
    class_metrics.to_csv(output_dir / outputs.get("cv_class_metrics_csv", "tables/linear_svm_cv_class_metrics.csv"), index=False, encoding="utf-8-sig")
    confusion.to_csv(output_dir / outputs.get("cv_confusion_csv", "tables/linear_svm_cv_confusion_matrix.csv"), index=False, encoding="utf-8-sig")
    fold_predictions.to_csv(output_dir / outputs.get("cv_fold_predictions_csv", "tables/linear_svm_cv_fold_predictions.csv"), index=False, encoding="utf-8-sig")
    return overall_cv, fold_metrics, class_metrics, confusion


def evaluate_independent(
    search: GridSearchCV,
    independent: pd.DataFrame,
    feature_columns: list[str],
    encoder: LabelEncoder,
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    key = str(config["fields"]["key"])
    group_field = str(config["fields"]["group"])
    target = str(config["fields"]["target"])
    class_labels = build_target_label_mapping(independent, config)
    x_ind, y_ind, _ = prepare_xy(independent, feature_columns, target=target, encoder=encoder)
    y_pred = search.best_estimator_.predict(x_ind)

    metrics = pd.DataFrame([metric_row(y_ind, y_pred, label="independent_validation")])
    class_metrics = classification_report_df(y_ind, y_pred, encoder, "independent_validation", class_labels)
    confusion = confusion_matrix_df(y_ind, y_pred, encoder, "independent_validation", class_labels)

    pred_rows = []
    for row_idx, pred in enumerate(y_pred):
        y_true_class = str(encoder.inverse_transform([y_ind[row_idx]])[0])
        y_pred_class = str(encoder.inverse_transform([pred])[0])
        pred_rows.append(
            {
                key: independent.iloc[row_idx][key],
                group_field: independent.iloc[row_idx][group_field],
                "split_role": "independent_validation",
                "y_true": y_true_class,
                "y_true_label": class_labels.get(y_true_class),
                "y_pred": y_pred_class,
                "y_pred_label": class_labels.get(y_pred_class),
            }
        )
    predictions = pd.DataFrame(pred_rows)

    outputs = config.get("outputs", {}) or {}
    metrics.to_csv(output_dir / outputs.get("independent_metrics_csv", "tables/linear_svm_independent_metrics.csv"), index=False, encoding="utf-8-sig")
    class_metrics.to_csv(output_dir / outputs.get("independent_class_metrics_csv", "tables/linear_svm_independent_class_metrics.csv"), index=False, encoding="utf-8-sig")
    confusion.to_csv(output_dir / outputs.get("independent_confusion_csv", "tables/linear_svm_independent_confusion_matrix.csv"), index=False, encoding="utf-8-sig")
    predictions.to_csv(output_dir / outputs.get("independent_predictions_csv", "tables/linear_svm_independent_predictions.csv"), index=False, encoding="utf-8-sig")
    return metrics, class_metrics, confusion


def write_feature_coefficients(
    search: GridSearchCV,
    feature_columns: list[str],
    encoder: LabelEncoder,
    output_dir: Path,
    config: dict[str, Any],
) -> None:
    clf = search.best_estimator_.named_steps["clf"]
    coef = getattr(clf, "coef_", None)
    if coef is None:
        LOGGER.warning("El estimador no expone coeficientes.")
        return
    coef = np.asarray(coef)
    has_kernel_step = "kernel" in search.best_estimator_.named_steps
    n_coefficients = int(coef.shape[1]) if coef.ndim == 2 else int(coef.shape[0])
    if has_kernel_step or n_coefficients != len(feature_columns):
        coefficient_names = [f"component_{idx:04d}" for idx in range(n_coefficients)]
        coefficient_space = "kernel_approximation_component"
    else:
        coefficient_names = feature_columns
        coefficient_space = "original_feature"

    rows = []
    for class_idx, class_id in enumerate(encoder.classes_):
        class_coef = coef[class_idx] if coef.ndim == 2 else coef
        for feature, value in zip(coefficient_names, class_coef):
            rows.append(
                {
                    "class_id": str(class_id),
                    "coefficient_space": coefficient_space,
                    "feature": feature,
                    "coefficient": float(value),
                    "abs_coefficient": float(abs(value)),
                }
            )
    coefficients = pd.DataFrame(rows)
    summary = (
        coefficients.groupby("feature", dropna=False)
        .agg(mean_abs_coefficient=("abs_coefficient", "mean"), max_abs_coefficient=("abs_coefficient", "max"))
        .reset_index()
        .sort_values("mean_abs_coefficient", ascending=False)
    )
    output = coefficients.merge(summary, on="feature", how="left", validate="many_to_one")
    outputs = config.get("outputs", {}) or {}
    output.to_csv(output_dir / outputs.get("feature_coefficients_csv", "tables/linear_svm_feature_coefficients.csv"), index=False, encoding="utf-8-sig")


def pipeline_description(config: dict[str, Any], best_params: dict[str, Any] | None = None) -> str:
    model_cfg = config.get("model", {}) or {}
    kernel_cfg = model_cfg.get("kernel_approximation", {}) or {}
    best_params = best_params or {}
    parts = ["SimpleImputer(strategy='median')", "StandardScaler"]
    if bool(kernel_cfg.get("enabled", False)):
        parts.append(
            "Nystroem("
            f"kernel='{kernel_cfg.get('kernel', 'rbf')}', "
            f"gamma={best_params.get('kernel__gamma', kernel_cfg.get('gamma', 'grid'))}, "
            f"n_components={best_params.get('kernel__n_components', kernel_cfg.get('n_components', 'grid'))}"
            ")"
        )
    parts.append("LinearSVC")
    return " -> ".join(parts)


def save_artifacts(
    search: GridSearchCV,
    encoder: LabelEncoder,
    feature_columns: list[str],
    output_dir: Path,
    config: dict[str, Any],
) -> None:
    outputs = config.get("outputs", {}) or {}
    joblib.dump(search.best_estimator_, output_dir / outputs.get("model_development_path", "models/linear_svm_best_development.joblib"))
    joblib.dump(encoder, output_dir / outputs.get("label_encoder_path", "models/linear_svm_label_encoder.joblib"))
    (output_dir / outputs.get("feature_columns_path", "models/linear_svm_feature_columns.txt")).write_text(
        "\n".join(feature_columns) + "\n",
        encoding="utf-8",
    )


def write_class_catalog(dataframe: pd.DataFrame, output_dir: Path, config: dict[str, Any]) -> None:
    target = str(config["fields"]["target"])
    label_field = config.get("fields", {}).get("target_label")
    class_labels = build_target_label_mapping(dataframe, config)
    catalog = pd.DataFrame(
        [{target: class_id, str(label_field or "class_label"): label} for class_id, label in sorted(class_labels.items())]
    )
    outputs = config.get("outputs", {}) or {}
    catalog.to_csv(output_dir / outputs.get("class_catalog_csv", "tables/linear_svm_class_catalog.csv"), index=False, encoding="utf-8-sig")


def build_report(
    development_path: Path,
    independent_path: Path,
    feature_columns: list[str],
    search: GridSearchCV,
    training_metrics: pd.DataFrame,
    grid_train_validation: pd.DataFrame,
    cv_overall: pd.DataFrame,
    cv_fold_metrics: pd.DataFrame,
    independent_metrics: pd.DataFrame,
    output_dir: Path,
    config: dict[str, Any],
) -> None:
    outputs = config.get("outputs", {}) or {}
    report_path = output_dir / outputs.get("report_md", "reports/a4_8_3_train_linear_svm_report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    target = str(config["fields"]["target"])
    algorithm = str(config.get("model", {}).get("algorithm", "linear_svm"))
    report_title = str(outputs.get("report_title", f"Actividad 4.8.3 - Entrenamiento {algorithm}"))

    lines = [
        f"# {report_title}",
        "",
        f"**Fecha:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Insumos",
        "",
        f"- Desarrollo: `{development_path.relative_to(REPO_ROOT)}`",
        f"- Validacion independiente: `{independent_path.relative_to(REPO_ROOT)}`",
        f"- Target: `{target}`",
        f"- Predictores: **{len(feature_columns):,}**",
        "",
        "## Pipeline",
        "",
        f"`{pipeline_description(config, search.best_params_)}`",
        "",
        "## GridSearchCV",
        "",
        f"- Mejor score interno: `{search.best_score_}`",
        f"- Mejores hiperparametros: `{json.dumps(search.best_params_, ensure_ascii=False)}`",
        "",
        "### Train vs validacion CV del mejor resultado",
        "",
        dataframe_to_markdown(grid_train_validation),
        "",
        "## Desempeno sobre desarrollo",
        "",
        dataframe_to_markdown(training_metrics),
        "",
        "## Diagnostico OOF interno",
        "",
        dataframe_to_markdown(cv_overall),
        "",
        "### Metricas por fold",
        "",
        dataframe_to_markdown(cv_fold_metrics),
        "",
        "## Validacion independiente",
        "",
        dataframe_to_markdown(independent_metrics),
        "",
        "## Nota metodologica",
        "",
        "La validacion independiente no participa en GridSearchCV. Las metricas OOF "
        "son diagnosticas porque los hiperparametros se eligieron usando esos mismos folds.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Reporte SVM lineal escrito: %s", report_path)


def main() -> None:
    config_path, config_section = split_config_arg(sys.argv[1], CONFIG_SECTION) if len(sys.argv) > 1 else (DEFAULT_CONFIG, CONFIG_SECTION)
    config = select_config_section(read_yaml(config_path), config_section)
    output_dir = resolve_path(config["paths"]["output_dir"])
    configure_logger(output_dir)
    LOGGER.info("YAML de configuracion: %s | seccion=%s", config_path, config_section)

    development, development_path, _ = read_partitioned_dataset(
        config,
        "development_dataset_parquet",
        "development_dataset_csv",
        "desarrollo SVM",
    )
    independent, independent_path, _ = read_partitioned_dataset(
        config,
        "independent_dataset_parquet",
        "independent_dataset_csv",
        "validacion independiente SVM",
    )
    development = normalize_core_fields(development, config)
    independent = normalize_core_fields(independent, config)
    feature_columns = read_text_list(resolve_path(config["paths"]["selected_features_txt"]), "selected_features_txt")
    validate_inputs(development, independent, feature_columns, config)
    cv_splits = read_cv_splits(development, config)

    search, encoder, x_dev, y_dev = run_grid_search(development, feature_columns, cv_splits, config, output_dir)
    grid_train_validation = best_gridsearch_train_validation_metrics(search)
    grid_train_validation.to_csv(
        output_dir / "tables" / "linear_svm_best_gridsearch_train_validation_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )

    training_metrics, _, _ = evaluate_training(search, development, x_dev, y_dev, encoder, config, output_dir)
    cv_overall, cv_fold_metrics, _, _ = evaluate_best_model_cv(
        search,
        development,
        x_dev,
        y_dev,
        encoder,
        cv_splits,
        config,
        output_dir,
    )
    independent_metrics, _, _ = evaluate_independent(search, independent, feature_columns, encoder, config, output_dir)
    write_feature_coefficients(search, feature_columns, encoder, output_dir, config)
    save_artifacts(search, encoder, feature_columns, output_dir, config)
    write_class_catalog(pd.concat([development, independent], ignore_index=True), output_dir, config)
    build_report(
        development_path=development_path,
        independent_path=independent_path,
        feature_columns=feature_columns,
        search=search,
        training_metrics=training_metrics,
        grid_train_validation=grid_train_validation,
        cv_overall=cv_overall,
        cv_fold_metrics=cv_fold_metrics,
        independent_metrics=independent_metrics,
        output_dir=output_dir,
        config=config,
    )
    LOGGER.info(
        "A4.8.3 finalizado: desarrollo=%s | independiente=%s | best_score=%s",
        f"{len(development):,}",
        f"{len(independent):,}",
        search.best_score_,
    )


if __name__ == "__main__":
    main()
