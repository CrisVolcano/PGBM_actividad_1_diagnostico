# -*- coding: utf-8 -*-
"""
Actividad 4.9.2 - Entrenamiento base XGBoost
============================================

Entrena un XGBoost multiclase con parametros fijos definidos en el YAML. Esta
etapa no hace hiperparametrizacion: sirve como modelo base y como verificacion
de que el flujo completo funciona sobre los splits espaciales existentes.

Ejecucion desde la raiz del repositorio:

    python src/actividad_4/XGBoost/4_9_2_train_xgboost_base_model.py
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
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
)
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier


LOGGER = logging.getLogger("a4_9_2_train_xgboost_base_model")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) >= 4 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_9_xgboost.yaml"
CONFIG_SECTION = "base_model"


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
            output_dir / "logs" / "a4_9_2_train_xgboost_base_model.log",
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
    key = str(fields["key"])
    group = str(fields["group"])
    target = str(fields["target"])
    label = fields.get("target_label")
    required = [key, group, target]
    if label:
        required.append(str(label))
    required.extend(feature_columns)

    for name, dataframe in [("development", development), ("independent_validation", independent)]:
        missing = sorted(set(required) - set(dataframe.columns))
        if missing:
            raise ValueError(f"Faltan columnas en {name}: {missing}")
        duplicated = int(dataframe[key].duplicated().sum())
        if duplicated:
            raise ValueError(f"{name} tiene {duplicated:,} llaves duplicadas.")
        if dataframe[target].isna().any():
            raise ValueError(f"{name} contiene nulos en el target {target}.")

    key_overlap = sorted(set(development[key]) & set(independent[key]))
    if key_overlap:
        raise ValueError(f"Hay llaves repetidas entre desarrollo e independiente: {key_overlap[:10]}")

    group_overlap = sorted(set(development[group]) & set(independent[group]))
    if group_overlap:
        raise ValueError(f"Leakage espacial desarrollo/independiente: {group_overlap[:10]}")

    unseen = sorted(set(independent[target]) - set(development[target]))
    if unseen:
        raise ValueError(f"Validacion independiente contiene clases no vistas en desarrollo: {unseen}")


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


def xgboost_params(config: dict[str, Any], n_classes: int) -> dict[str, Any]:
    model_cfg = config.get("model", {}) or {}
    excluded = {"algorithm", "implementation"}
    params = {key: value for key, value in model_cfg.items() if key not in excluded}
    params["num_class"] = int(n_classes)
    return params


def build_model(config: dict[str, Any], n_classes: int) -> XGBClassifier:
    return XGBClassifier(**xgboost_params(config, n_classes))


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


def dataframe_to_markdown(dataframe: pd.DataFrame, max_rows: int = 20) -> str:
    if dataframe.empty:
        return "_Sin datos._"
    return dataframe.head(max_rows).to_markdown(index=False)


def write_metric_outputs(
    output_dir: Path,
    config: dict[str, Any],
    metrics: pd.DataFrame,
    class_metrics: pd.DataFrame,
    confusion: pd.DataFrame,
    prefix: str,
) -> None:
    outputs = config.get("outputs", {}) or {}
    metrics.to_csv(output_dir / outputs.get(f"{prefix}_metrics_csv", f"tables/xgboost_{prefix}_metrics.csv"), index=False, encoding="utf-8-sig")
    class_metrics.to_csv(
        output_dir / outputs.get(f"{prefix}_class_metrics_csv", f"tables/xgboost_{prefix}_class_metrics.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    confusion.to_csv(
        output_dir / outputs.get(f"{prefix}_confusion_csv", f"tables/xgboost_{prefix}_confusion_matrix.csv"),
        index=False,
        encoding="utf-8-sig",
    )


def evaluate_training(
    model: XGBClassifier,
    development: pd.DataFrame,
    x_dev: pd.DataFrame,
    y_dev: np.ndarray,
    encoder: LabelEncoder,
    class_labels: dict[str, str],
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    y_pred = model.predict(x_dev)
    metrics = pd.DataFrame([metric_row(y_dev, y_pred, "training_development_resubstitution")])
    class_metrics = classification_report_df(y_dev, y_pred, encoder, "training_development_resubstitution", class_labels)
    confusion = confusion_matrix_df(y_dev, y_pred, encoder, "training_development_resubstitution", class_labels)
    write_metric_outputs(output_dir, config, metrics, class_metrics, confusion, "training")
    return metrics, class_metrics, confusion


def evaluate_cv(
    base_model: XGBClassifier,
    development: pd.DataFrame,
    x_dev: pd.DataFrame,
    y_dev: np.ndarray,
    encoder: LabelEncoder,
    class_labels: dict[str, str],
    cv_splits: list[tuple[np.ndarray, np.ndarray]],
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    key = str(config["fields"]["key"])
    group_field = str(config["fields"]["group"])
    predictions = np.full(shape=len(y_dev), fill_value=-1, dtype=int)
    fold_rows: list[dict[str, Any]] = []
    pred_rows: list[dict[str, Any]] = []

    for fold_id, (train_idx, validation_idx) in enumerate(cv_splits, start=1):
        LOGGER.info(
            "Entrenando fold CV base XGBoost %s/%s: train=%s | validacion=%s",
            fold_id,
            len(cv_splits),
            f"{len(train_idx):,}",
            f"{len(validation_idx):,}",
        )
        estimator = clone(base_model)
        estimator.fit(x_dev.iloc[train_idx], y_dev[train_idx])
        fold_pred = estimator.predict(x_dev.iloc[validation_idx])
        predictions[validation_idx] = fold_pred
        fold_rows.append(metric_row(y_dev[validation_idx], fold_pred, f"cv_fold_{fold_id}"))

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

    overall = pd.DataFrame([metric_row(y_dev, predictions, "cv_oof_base_model_diagnostic")])
    fold_metrics = pd.DataFrame(fold_rows)
    class_metrics = classification_report_df(y_dev, predictions, encoder, "cv_oof_base_model_diagnostic", class_labels)
    confusion = confusion_matrix_df(y_dev, predictions, encoder, "cv_oof_base_model_diagnostic", class_labels)
    fold_predictions = pd.DataFrame(pred_rows)

    outputs = config.get("outputs", {}) or {}
    overall.to_csv(output_dir / outputs.get("cv_overall_metrics_csv", "tables/xgboost_cv_overall_metrics.csv"), index=False, encoding="utf-8-sig")
    fold_metrics.to_csv(output_dir / outputs.get("cv_fold_metrics_csv", "tables/xgboost_cv_fold_metrics.csv"), index=False, encoding="utf-8-sig")
    class_metrics.to_csv(output_dir / outputs.get("cv_class_metrics_csv", "tables/xgboost_cv_class_metrics.csv"), index=False, encoding="utf-8-sig")
    confusion.to_csv(output_dir / outputs.get("cv_confusion_csv", "tables/xgboost_cv_confusion_matrix.csv"), index=False, encoding="utf-8-sig")
    fold_predictions.to_csv(output_dir / outputs.get("cv_fold_predictions_csv", "tables/xgboost_cv_fold_predictions.csv"), index=False, encoding="utf-8-sig")
    return overall, fold_metrics, class_metrics, confusion


def evaluate_independent(
    model: XGBClassifier,
    independent: pd.DataFrame,
    feature_columns: list[str],
    encoder: LabelEncoder,
    class_labels: dict[str, str],
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    key = str(config["fields"]["key"])
    group_field = str(config["fields"]["group"])
    target = str(config["fields"]["target"])
    x_ind, y_ind, _ = prepare_xy(independent, feature_columns, target, encoder)
    y_pred = model.predict(x_ind)

    metrics = pd.DataFrame([metric_row(y_ind, y_pred, "independent_validation")])
    class_metrics = classification_report_df(y_ind, y_pred, encoder, "independent_validation", class_labels)
    confusion = confusion_matrix_df(y_ind, y_pred, encoder, "independent_validation", class_labels)
    write_metric_outputs(output_dir, config, metrics, class_metrics, confusion, "independent")

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
    outputs = config.get("outputs", {}) or {}
    pd.DataFrame(pred_rows).to_csv(
        output_dir / outputs.get("independent_predictions_csv", "tables/xgboost_independent_predictions.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    return metrics, class_metrics, confusion


def write_feature_importance(model: XGBClassifier, feature_columns: list[str], output_dir: Path, config: dict[str, Any]) -> None:
    outputs = config.get("outputs", {}) or {}
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        LOGGER.warning("El modelo no expone feature_importances_.")
        return
    table = pd.DataFrame(
        {
            "feature": feature_columns,
            "importance": np.asarray(importances, dtype=float),
        }
    ).sort_values("importance", ascending=False)
    table["rank"] = np.arange(1, len(table) + 1)
    table.to_csv(output_dir / outputs.get("feature_importance_csv", "tables/xgboost_feature_importance.csv"), index=False, encoding="utf-8-sig")


def save_artifacts(
    model: XGBClassifier,
    encoder: LabelEncoder,
    feature_columns: list[str],
    class_catalog: pd.DataFrame,
    output_dir: Path,
    config: dict[str, Any],
) -> None:
    outputs = config.get("outputs", {}) or {}
    joblib.dump(model, output_dir / outputs.get("model_development_path", "models/xgboost_base_development.joblib"))
    joblib.dump(encoder, output_dir / outputs.get("label_encoder_path", "models/xgboost_label_encoder.joblib"))
    (output_dir / outputs.get("feature_columns_path", "models/xgboost_feature_columns.txt")).write_text(
        "\n".join(feature_columns) + "\n",
        encoding="utf-8",
    )
    class_catalog.to_csv(output_dir / outputs.get("class_catalog_csv", "tables/xgboost_class_catalog.csv"), index=False, encoding="utf-8-sig")


def build_class_catalog(dataframe: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    target = str(config["fields"]["target"])
    label_field = config.get("fields", {}).get("target_label")
    class_labels = build_target_label_mapping(dataframe, config)
    label_name = str(label_field or "class_label")
    return pd.DataFrame(
        [{target: class_id, label_name: label} for class_id, label in sorted(class_labels.items())]
    )


def write_report(
    development_path: Path,
    independent_path: Path,
    feature_columns: list[str],
    model_params: dict[str, Any],
    training_metrics: pd.DataFrame,
    cv_overall: pd.DataFrame,
    cv_fold_metrics: pd.DataFrame,
    independent_metrics: pd.DataFrame,
    output_dir: Path,
    config: dict[str, Any],
) -> None:
    outputs = config.get("outputs", {}) or {}
    report_path = output_dir / outputs.get("report_md", "reports/a4_9_2_train_xgboost_base_model_report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    target = str(config["fields"]["target"])

    lines = [
        "# Actividad 4.9.2 - Entrenamiento base XGBoost",
        "",
        f"**Fecha:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Insumos",
        "",
        f"- Desarrollo: `{relative_path(development_path)}`",
        f"- Validacion independiente: `{relative_path(independent_path)}`",
        f"- Target: `{target}`",
        f"- Predictores: **{len(feature_columns):,}**",
        "",
        "## Modelo",
        "",
        "`XGBClassifier` multiclase con `objective='multi:softprob'`, `tree_method='hist'` y manejo nativo de valores faltantes.",
        "",
        "### Parametros",
        "",
        f"`{json.dumps(model_params, ensure_ascii=False)}`",
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
        "Este es un modelo base, no hiperparametrizado. Las metricas OOF provienen "
        "de los folds espaciales existentes por `id_cuadrante`. La validacion "
        "independiente no participa en el ajuste del modelo.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Reporte escrito: %s", report_path)


def run_training(config: dict[str, Any]) -> None:
    output_dir = resolve_path(config["paths"]["output_dir"])
    configure_logger(output_dir)

    development, development_path, _ = read_partitioned_dataset(
        config,
        "development_dataset_parquet",
        "development_dataset_csv",
        "desarrollo XGBoost",
    )
    independent, independent_path, _ = read_partitioned_dataset(
        config,
        "independent_dataset_parquet",
        "independent_dataset_csv",
        "validacion independiente XGBoost",
    )
    development = normalize_core_fields(development, config)
    independent = normalize_core_fields(independent, config)
    feature_columns = read_text_list(resolve_path(config["paths"]["selected_features_txt"]), "selected_features_txt")
    validate_inputs(development, independent, feature_columns, config)
    cv_splits = read_cv_splits(development, config)

    target = str(config["fields"]["target"])
    x_dev, y_dev, encoder = prepare_xy(development, feature_columns, target, encoder=None)
    class_labels = build_target_label_mapping(pd.concat([development, independent], ignore_index=True), config)
    class_catalog = build_class_catalog(pd.concat([development, independent], ignore_index=True), config)
    model = build_model(config, n_classes=len(encoder.classes_))
    model_params = xgboost_params(config, n_classes=len(encoder.classes_))

    LOGGER.info(
        "Entrenando XGBoost base sobre desarrollo: filas=%s | predictores=%s | clases=%s",
        f"{len(development):,}",
        f"{len(feature_columns):,}",
        f"{len(encoder.classes_):,}",
    )
    model.fit(x_dev, y_dev)

    training_metrics, _, _ = evaluate_training(model, development, x_dev, y_dev, encoder, class_labels, config, output_dir)
    cv_overall, cv_fold_metrics, _, _ = evaluate_cv(
        model,
        development,
        x_dev,
        y_dev,
        encoder,
        class_labels,
        cv_splits,
        config,
        output_dir,
    )
    independent_metrics, _, _ = evaluate_independent(model, independent, feature_columns, encoder, class_labels, config, output_dir)
    write_feature_importance(model, feature_columns, output_dir, config)
    save_artifacts(model, encoder, feature_columns, class_catalog, output_dir, config)
    write_report(
        development_path=development_path,
        independent_path=independent_path,
        feature_columns=feature_columns,
        model_params=model_params,
        training_metrics=training_metrics,
        cv_overall=cv_overall,
        cv_fold_metrics=cv_fold_metrics,
        independent_metrics=independent_metrics,
        output_dir=output_dir,
        config=config,
    )
    LOGGER.info(
        "A4.9.2 finalizado: training_f1_macro=%.6f | cv_f1_macro=%.6f | independent_f1_macro=%.6f",
        float(training_metrics.loc[0, "f1_macro"]),
        float(cv_overall.loc[0, "f1_macro"]),
        float(independent_metrics.loc[0, "f1_macro"]),
    )


def main() -> None:
    config_path, config_section = split_config_arg(sys.argv[1], CONFIG_SECTION) if len(sys.argv) > 1 else (DEFAULT_CONFIG, CONFIG_SECTION)
    config = select_config_section(read_yaml(config_path), config_section)
    run_training(config)


if __name__ == "__main__":
    main()
