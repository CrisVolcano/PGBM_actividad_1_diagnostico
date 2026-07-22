# -*- coding: utf-8 -*-
"""
Actividad 4.9.3 - Hiperparametrizacion XGBoost
==============================================

Ejecuta una busqueda GridSearchCV sobre XGBoost usando los folds espaciales ya
creados. La validacion independiente permanece fuera de la seleccion de
hiperparametros y se evalua solo al final.

Ejecucion desde la raiz del repositorio:

    python src/actividad_4/XGBoost/4_9_3_train_xgboost_gridsearch.py
"""

from __future__ import annotations

import importlib.util
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
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier


LOGGER = logging.getLogger("a4_9_3_train_xgboost_gridsearch")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) >= 4 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_9_xgboost.yaml"
CONFIG_SECTION = "gridsearch"
BASE_SCRIPT = SCRIPT_PATH.with_name("4_9_2_train_xgboost_base_model.py")


def load_base_helpers() -> Any:
    spec = importlib.util.spec_from_file_location("a4_9_2_train_xgboost_base_model", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"No se pudieron cargar helpers desde {BASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load_base_helpers()


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
            output_dir / "logs" / "a4_9_3_train_xgboost_gridsearch.log",
            mode="w",
            encoding="utf-8",
        ),
    ):
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)


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


def xgboost_base_params(config: dict[str, Any], n_classes: int) -> dict[str, Any]:
    model_cfg = config.get("model", {}) or {}
    excluded = {"algorithm", "implementation"}
    params = {key: value for key, value in model_cfg.items() if key not in excluded}
    params["num_class"] = int(n_classes)
    return params


def build_pipeline(config: dict[str, Any], n_classes: int) -> Pipeline:
    params = xgboost_base_params(config, n_classes)
    classifier = XGBClassifier(**params)
    return Pipeline(steps=[("clf", classifier)])


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
) -> tuple[GridSearchCV, Any, pd.DataFrame, np.ndarray]:
    target = str(config["fields"]["target"])
    x_dev, y_dev, encoder = base.prepare_xy(development, feature_columns, target, encoder=None)
    pipeline = build_pipeline(config, n_classes=len(encoder.classes_))
    param_grid = normalize_param_grid(config)
    gs_cfg = config.get("grid_search", {}) or {}
    scoring = gs_cfg.get(
        "scoring",
        {"accuracy": "accuracy", "balanced_accuracy": "balanced_accuracy", "f1_macro": "f1_macro"},
    )

    combinations = int(np.prod([len(values) for values in param_grid.values()]))
    internal_fits = combinations * len(cv_splits)
    LOGGER.info(
        "Iniciando GridSearchCV XGBoost: combinaciones=%s | folds=%s | entrenamientos_internos=%s",
        f"{combinations:,}",
        f"{len(cv_splits):,}",
        f"{internal_fits:,}",
    )
    search = GridSearchCV(
        estimator=pipeline,
        param_grid=param_grid,
        scoring=scoring,
        refit=gs_cfg.get("refit", "f1_macro"),
        cv=cv_splits,
        n_jobs=int(gs_cfg.get("n_jobs", 1)),
        verbose=int(gs_cfg.get("verbose", 1)),
        return_train_score=bool(gs_cfg.get("return_train_score", True)),
        error_score=gs_cfg.get("error_score", "raise"),
    )
    search.fit(x_dev, y_dev)

    outputs = config.get("outputs", {}) or {}
    pd.DataFrame(search.cv_results_).to_csv(
        output_dir / outputs.get("gridsearch_results_csv", "tables/xgboost_gridsearch_results.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    (output_dir / outputs.get("best_params_json", "tables/xgboost_best_params.json")).write_text(
        json.dumps(search.best_params_, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    LOGGER.info("GridSearchCV XGBoost finalizado. Best score=%s | best_params=%s", search.best_score_, search.best_params_)
    return search, encoder, x_dev, y_dev


def evaluate_training(
    search: GridSearchCV,
    development: pd.DataFrame,
    x_dev: pd.DataFrame,
    y_dev: np.ndarray,
    encoder: Any,
    class_labels: dict[str, str],
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    y_pred = search.best_estimator_.predict(x_dev)
    metrics = pd.DataFrame([base.metric_row(y_dev, y_pred, "training_development_resubstitution")])
    class_metrics = base.classification_report_df(y_dev, y_pred, encoder, "training_development_resubstitution", class_labels)
    confusion = base.confusion_matrix_df(y_dev, y_pred, encoder, "training_development_resubstitution", class_labels)
    base.write_metric_outputs(output_dir, config, metrics, class_metrics, confusion, "training")
    return metrics, class_metrics, confusion


def evaluate_best_model_cv(
    search: GridSearchCV,
    development: pd.DataFrame,
    x_dev: pd.DataFrame,
    y_dev: np.ndarray,
    encoder: Any,
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
            "Reentrenando mejor XGBoost para OOF fold %s/%s: train=%s | validacion=%s",
            fold_id,
            len(cv_splits),
            f"{len(train_idx):,}",
            f"{len(validation_idx):,}",
        )
        estimator = clone(search.best_estimator_)
        estimator.fit(x_dev.iloc[train_idx], y_dev[train_idx])
        fold_pred = estimator.predict(x_dev.iloc[validation_idx])
        predictions[validation_idx] = fold_pred
        fold_rows.append(base.metric_row(y_dev[validation_idx], fold_pred, f"cv_fold_{fold_id}"))

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

    overall = pd.DataFrame([base.metric_row(y_dev, predictions, "cv_oof_best_gridsearch_diagnostic")])
    fold_metrics = pd.DataFrame(fold_rows)
    class_metrics = base.classification_report_df(y_dev, predictions, encoder, "cv_oof_best_gridsearch_diagnostic", class_labels)
    confusion = base.confusion_matrix_df(y_dev, predictions, encoder, "cv_oof_best_gridsearch_diagnostic", class_labels)
    fold_predictions = pd.DataFrame(pred_rows)

    outputs = config.get("outputs", {}) or {}
    overall.to_csv(output_dir / outputs.get("cv_overall_metrics_csv", "tables/xgboost_cv_overall_metrics.csv"), index=False, encoding="utf-8-sig")
    fold_metrics.to_csv(output_dir / outputs.get("cv_fold_metrics_csv", "tables/xgboost_cv_fold_metrics.csv"), index=False, encoding="utf-8-sig")
    class_metrics.to_csv(output_dir / outputs.get("cv_class_metrics_csv", "tables/xgboost_cv_class_metrics.csv"), index=False, encoding="utf-8-sig")
    confusion.to_csv(output_dir / outputs.get("cv_confusion_csv", "tables/xgboost_cv_confusion_matrix.csv"), index=False, encoding="utf-8-sig")
    fold_predictions.to_csv(output_dir / outputs.get("cv_fold_predictions_csv", "tables/xgboost_cv_fold_predictions.csv"), index=False, encoding="utf-8-sig")
    return overall, fold_metrics, class_metrics, confusion


def evaluate_independent(
    search: GridSearchCV,
    independent: pd.DataFrame,
    feature_columns: list[str],
    encoder: Any,
    class_labels: dict[str, str],
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    key = str(config["fields"]["key"])
    group_field = str(config["fields"]["group"])
    target = str(config["fields"]["target"])
    x_ind, y_ind, _ = base.prepare_xy(independent, feature_columns, target, encoder)
    y_pred = search.best_estimator_.predict(x_ind)

    metrics = pd.DataFrame([base.metric_row(y_ind, y_pred, "independent_validation")])
    class_metrics = base.classification_report_df(y_ind, y_pred, encoder, "independent_validation", class_labels)
    confusion = base.confusion_matrix_df(y_ind, y_pred, encoder, "independent_validation", class_labels)
    base.write_metric_outputs(output_dir, config, metrics, class_metrics, confusion, "independent")

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


def write_feature_importance(search: GridSearchCV, feature_columns: list[str], output_dir: Path, config: dict[str, Any]) -> None:
    outputs = config.get("outputs", {}) or {}
    classifier = search.best_estimator_.named_steps["clf"]
    importances = getattr(classifier, "feature_importances_", None)
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
    search: GridSearchCV,
    encoder: Any,
    feature_columns: list[str],
    class_catalog: pd.DataFrame,
    output_dir: Path,
    config: dict[str, Any],
) -> None:
    outputs = config.get("outputs", {}) or {}
    joblib.dump(search.best_estimator_, output_dir / outputs.get("model_development_path", "models/xgboost_best_development.joblib"))
    joblib.dump(encoder, output_dir / outputs.get("label_encoder_path", "models/xgboost_label_encoder.joblib"))
    (output_dir / outputs.get("feature_columns_path", "models/xgboost_feature_columns.txt")).write_text(
        "\n".join(feature_columns) + "\n",
        encoding="utf-8",
    )
    class_catalog.to_csv(output_dir / outputs.get("class_catalog_csv", "tables/xgboost_class_catalog.csv"), index=False, encoding="utf-8-sig")


def write_report(
    development_path: Path,
    independent_path: Path,
    feature_columns: list[str],
    search: GridSearchCV,
    best_grid_metrics: pd.DataFrame,
    training_metrics: pd.DataFrame,
    cv_overall: pd.DataFrame,
    cv_fold_metrics: pd.DataFrame,
    independent_metrics: pd.DataFrame,
    output_dir: Path,
    config: dict[str, Any],
) -> None:
    outputs = config.get("outputs", {}) or {}
    report_path = output_dir / outputs.get("report_md", "reports/a4_9_3_train_xgboost_gridsearch_report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    target = str(config["fields"]["target"])
    param_grid = normalize_param_grid(config)
    combinations = int(np.prod([len(values) for values in param_grid.values()]))

    lines = [
        "# Actividad 4.9.3 - Hiperparametrizacion XGBoost",
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
        "## GridSearchCV",
        "",
        f"- Combinaciones evaluadas: **{combinations:,}**",
        f"- Folds espaciales: **{len(search.cv):,}**",
        f"- Entrenamientos internos: **{combinations * len(search.cv):,}**",
        f"- Mejor score interno: `{search.best_score_}`",
        f"- Mejores hiperparametros: `{json.dumps(search.best_params_, ensure_ascii=False)}`",
        "",
        "### Train vs validacion CV del mejor resultado",
        "",
        base.dataframe_to_markdown(best_grid_metrics),
        "",
        "## Desempeno sobre desarrollo",
        "",
        base.dataframe_to_markdown(training_metrics),
        "",
        "## Diagnostico OOF interno",
        "",
        base.dataframe_to_markdown(cv_overall),
        "",
        "### Metricas por fold",
        "",
        base.dataframe_to_markdown(cv_fold_metrics),
        "",
        "## Validacion independiente",
        "",
        base.dataframe_to_markdown(independent_metrics),
        "",
        "## Nota metodologica",
        "",
        "La busqueda se realiza solo sobre desarrollo mediante folds espaciales "
        "agrupados por `id_cuadrante`. La validacion independiente queda fuera "
        "de GridSearchCV y se usa una unica vez al final.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Reporte escrito: %s", report_path)


def run_training(config: dict[str, Any]) -> None:
    output_dir = resolve_path(config["paths"]["output_dir"])
    configure_logger(output_dir)

    development, development_path, _ = base.read_partitioned_dataset(
        config,
        "development_dataset_parquet",
        "development_dataset_csv",
        "desarrollo XGBoost",
    )
    independent, independent_path, _ = base.read_partitioned_dataset(
        config,
        "independent_dataset_parquet",
        "independent_dataset_csv",
        "validacion independiente XGBoost",
    )
    development = base.normalize_core_fields(development, config)
    independent = base.normalize_core_fields(independent, config)
    feature_columns = base.read_text_list(resolve_path(config["paths"]["selected_features_txt"]), "selected_features_txt")
    base.validate_inputs(development, independent, feature_columns, config)
    cv_splits = base.read_cv_splits(development, config)

    search, encoder, x_dev, y_dev = run_grid_search(development, feature_columns, cv_splits, config, output_dir)
    class_labels = base.build_target_label_mapping(pd.concat([development, independent], ignore_index=True), config)
    class_catalog = base.build_class_catalog(pd.concat([development, independent], ignore_index=True), config)

    best_grid_metrics = best_gridsearch_train_validation_metrics(search)
    outputs = config.get("outputs", {}) or {}
    best_grid_metrics.to_csv(
        output_dir / outputs.get("best_gridsearch_train_validation_metrics_csv", "tables/xgboost_best_gridsearch_train_validation_metrics.csv"),
        index=False,
        encoding="utf-8-sig",
    )

    training_metrics, _, _ = evaluate_training(search, development, x_dev, y_dev, encoder, class_labels, config, output_dir)
    cv_overall, cv_fold_metrics, _, _ = evaluate_best_model_cv(
        search,
        development,
        x_dev,
        y_dev,
        encoder,
        class_labels,
        cv_splits,
        config,
        output_dir,
    )
    independent_metrics, _, _ = evaluate_independent(search, independent, feature_columns, encoder, class_labels, config, output_dir)
    write_feature_importance(search, feature_columns, output_dir, config)
    save_artifacts(search, encoder, feature_columns, class_catalog, output_dir, config)
    write_report(
        development_path=development_path,
        independent_path=independent_path,
        feature_columns=feature_columns,
        search=search,
        best_grid_metrics=best_grid_metrics,
        training_metrics=training_metrics,
        cv_overall=cv_overall,
        cv_fold_metrics=cv_fold_metrics,
        independent_metrics=independent_metrics,
        output_dir=output_dir,
        config=config,
    )
    LOGGER.info(
        "A4.9.3 finalizado: best_cv_score=%.6f | training_f1_macro=%.6f | oof_f1_macro=%.6f | independent_f1_macro=%.6f",
        float(search.best_score_),
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
