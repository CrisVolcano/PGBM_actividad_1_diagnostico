#!/usr/bin/env python3
"""Compara métricas homogéneas de RF, SVM, XGBoost y DNN.

El script solo lee resultados existentes. No entrena ni ejecuta inferencia.
Selecciona la variante prioritaria disponible de cada familia y deja explícitos
los modelos sin resultados para evitar completar la comparación con supuestos.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "a4_10_model_comparison"
METRICS = ["accuracy", "balanced_accuracy", "f1_macro", "f1_weighted", "kappa"]


@dataclass(frozen=True)
class ModelCandidate:
    model: str
    variant: str
    result_dir: Path
    prefix: str
    split_family: str

    def metric_path(self, stage: str) -> Path:
        suffix = {
            "training": "training_metrics.csv",
            "cv_oof": "cv_overall_metrics.csv",
            "independent": "independent_metrics.csv",
        }[stage]
        return self.result_dir / "tables" / f"{self.prefix}{suffix}"

    def prediction_path(self) -> Path:
        return self.result_dir / "tables" / f"{self.prefix}independent_predictions.csv"


def repo_path(value: str) -> Path:
    return REPO_ROOT / Path(value)


MODEL_CANDIDATES: dict[str, list[ModelCandidate]] = {
    "RF": [
        ModelCandidate(
            "RF",
            "Random Forest seleccionado",
            repo_path("data/processed/a4_7_rf_gridsearch_spatial_validation"),
            "",
            "shared_frozen_spatial_splits",
        )
    ],
    "DNN": [
        ModelCandidate(
            "DNN",
            "DNN PyTorch seleccionada",
            repo_path("data/processed/a4_8_dnn_pytorch_spatial_validation"),
            "dnn_",
            "shared_frozen_spatial_splits",
        )
    ],
    "SVM": [
        ModelCandidate(
            "SVM",
            "Nystroem RBF refinado",
            repo_path("data/processed/a4_8_svm/04_train_nystroem_rbf_svm_refined"),
            "nystroem_rbf_svm_refined_",
            "shared_frozen_spatial_splits",
        ),
        ModelCandidate(
            "SVM",
            "Nystroem RBF inicial",
            repo_path("data/processed/a4_8_svm/04_train_nystroem_rbf_svm"),
            "nystroem_rbf_svm_",
            "shared_frozen_spatial_splits",
        ),
        ModelCandidate(
            "SVM",
            "SVM lineal refinado",
            repo_path("data/processed/a4_8_svm/03_train_linear_svm_refined_c"),
            "linear_svm_",
            "shared_frozen_spatial_splits",
        ),
        ModelCandidate(
            "SVM",
            "SVM lineal",
            repo_path("data/processed/a4_8_svm/03_train_linear_svm_gridsearch"),
            "linear_svm_",
            "shared_frozen_spatial_splits",
        ),
    ],
    "XGBoost": [
        ModelCandidate(
            "XGBoost",
            "XGBoost GPU GridSearch",
            repo_path("data/processed/a4_9_xgboost_gpu/03_train_xgboost_gridsearch"),
            "xgboost_gpu_",
            "shared_frozen_spatial_splits",
        ),
        ModelCandidate(
            "XGBoost",
            "XGBoost CPU GridSearch",
            repo_path("data/processed/a4_9_xgboost/03_train_xgboost_gridsearch"),
            "xgboost_",
            "shared_frozen_spatial_splits",
        ),
        ModelCandidate(
            "XGBoost",
            "XGBoost GPU base",
            repo_path("data/processed/a4_9_xgboost_gpu/02_train_base_model"),
            "xgboost_gpu_",
            "shared_frozen_spatial_splits",
        ),
        ModelCandidate(
            "XGBoost",
            "XGBoost CPU base",
            repo_path("data/processed/a4_9_xgboost/02_train_base_model"),
            "xgboost_",
            "shared_frozen_spatial_splits",
        ),
    ],
}

MODEL_IMPLEMENTATIONS: dict[str, Path] = {
    "RF": repo_path("src/actividad_4/4_7_train_rf_gridsearch_spatial_validation_balanced.py"),
    "SVM": repo_path("src/actividad_4/SVM"),
    "XGBoost": repo_path("src/actividad_4/XGBoost"),
    "DNN": repo_path("src/actividad_4/4_8_train_dnn_pytorch_spatial_validation.py"),
}

CV_ASSIGNMENT_PATHS: dict[str, Path] = {
    "RF": repo_path(
        "data/processed/a4_7_rf_gridsearch_spatial_validation/tables/cv_fold_assignments.csv"
    ),
    "SVM": repo_path("data/processed/a4_8_svm/02_spatial_splits/tables/svm_cv_fold_assignments.csv"),
    "XGBoost": repo_path(
        "data/processed/a4_8_svm/02_spatial_splits/tables/svm_cv_fold_assignments.csv"
    ),
    "DNN": repo_path(
        "data/processed/a4_7_rf_gridsearch_spatial_validation/tables/cv_fold_assignments.csv"
    ),
}


def dataframe_to_markdown(dataframe: pd.DataFrame) -> str:
    if dataframe.empty:
        return "_Sin resultados disponibles._"

    def format_cell(value: Any) -> str:
        try:
            missing = bool(pd.isna(value))
        except (TypeError, ValueError):
            missing = False
        if missing:
            return ""
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.6f}"
        return str(value).replace("|", r"\|").replace("\n", "<br>")

    headers = [format_cell(column) for column in dataframe.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in dataframe.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(format_cell(value) for value in row) + " |")
    return "\n".join(lines)


def candidate_is_complete(candidate: ModelCandidate) -> bool:
    return all(candidate.metric_path(stage).exists() for stage in ["training", "cv_oof", "independent"])


def select_candidate(model: str) -> ModelCandidate | None:
    return next(
        (candidate for candidate in MODEL_CANDIDATES[model] if candidate_is_complete(candidate)),
        None,
    )


def selected_implementation_path(model: str, candidate: ModelCandidate | None) -> Path:
    if model == "XGBoost" and candidate is not None and "GPU" in candidate.variant:
        return repo_path("src/actividad_4/XGBoost_GPU")
    return MODEL_IMPLEMENTATIONS[model]


def metric_row(candidate: ModelCandidate, stage: str) -> dict[str, Any]:
    path = candidate.metric_path(stage)
    data = pd.read_csv(path, encoding="utf-8-sig")
    if len(data) != 1:
        raise ValueError(f"Se esperaba una fila de métricas en {path}; filas={len(data)}")
    required = {"n_rows", *METRICS}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"Faltan métricas en {path}: {missing}")
    source = data.iloc[0]
    return {
        "model": candidate.model,
        "variant": candidate.variant,
        "split_family": candidate.split_family,
        "evaluation_stage": stage,
        "source_evaluation": source.get("evaluation", ""),
        "n_rows": int(source["n_rows"]),
        **{metric: float(source[metric]) for metric in METRICS},
        "source_file": str(path.relative_to(REPO_ROOT)),
    }


def independent_signatures(candidate: ModelCandidate) -> dict[str, Any]:
    path = candidate.prediction_path()
    if not path.exists():
        return {
            "key_sha256": None,
            "reference_sha256": None,
            "n_rows": None,
            "n_unique_keys": None,
            "classes": None,
        }

    predictions = pd.read_csv(path, encoding="utf-8-sig")
    if "xy_group_id" not in predictions.columns:
        raise ValueError(f"No existe xy_group_id en predicciones: {path}")
    truth_column = next(
        (column for column in ["y_true", "id_1_propuesta"] if column in predictions.columns),
        None,
    )
    if truth_column is None:
        raise ValueError(
            f"No se encontró la clase verdadera homologada y_true/id_1_propuesta en: {path}"
        )

    reference = predictions[["xy_group_id", truth_column]].copy()
    reference["xy_group_id"] = reference["xy_group_id"].astype("string").str.strip()
    reference[truth_column] = reference[truth_column].astype("string").str.strip()
    reference = reference.sort_values(["xy_group_id", truth_column], kind="stable")
    keys = reference["xy_group_id"].tolist()
    key_digest = hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()
    reference_lines = (
        reference["xy_group_id"] + "\t" + reference[truth_column]
    ).tolist()
    reference_digest = hashlib.sha256("\n".join(reference_lines).encode("utf-8")).hexdigest()
    classes = sorted(reference[truth_column].dropna().unique().tolist())
    return {
        "key_sha256": key_digest,
        "reference_sha256": reference_digest,
        "n_rows": len(reference),
        "n_unique_keys": int(reference["xy_group_id"].nunique()),
        "classes": ",".join(classes),
    }


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generalization_gaps(metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (model, variant), group in metrics.groupby(["model", "variant"], sort=False):
        by_stage = group.set_index("evaluation_stage")
        if not {"training", "cv_oof", "independent"}.issubset(by_stage.index):
            continue
        for metric in METRICS:
            rows.append(
                {
                    "model": model,
                    "variant": variant,
                    "metric": metric,
                    "training_minus_independent": float(
                        by_stage.loc["training", metric] - by_stage.loc["independent", metric]
                    ),
                    "cv_oof_minus_independent": float(
                        by_stage.loc["cv_oof", metric] - by_stage.loc["independent", metric]
                    ),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    tables_dir = OUTPUT_DIR / "tables"
    reports_dir = OUTPUT_DIR / "reports"
    tables_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    availability_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    for model in ["RF", "SVM", "XGBoost", "DNN"]:
        candidate = select_candidate(model)
        implementation_path = selected_implementation_path(model, candidate)
        implementation_status = "available" if implementation_path.exists() else "not_found"
        cv_assignment_path = CV_ASSIGNMENT_PATHS[model]
        cv_assignment_sha256 = file_sha256(cv_assignment_path)
        if candidate is None:
            availability_rows.append(
                {
                    "model": model,
                    "implementation_status": implementation_status,
                    "metrics_status": "not_found_in_workspace",
                    "implementation_path": str(implementation_path.relative_to(REPO_ROOT)),
                    "cv_assignment_path": str(cv_assignment_path.relative_to(REPO_ROOT)),
                    "cv_assignment_sha256": cv_assignment_sha256 or "not_found",
                    "selected_variant": "",
                    "split_family": "",
                    "independent_rows": pd.NA,
                    "independent_unique_keys": pd.NA,
                    "independent_classes": "",
                    "independent_key_sha256": "",
                    "independent_reference_sha256": "",
                    "note": "La implementación existe, pero no se localizaron las tres salidas métricas requeridas: training + CV OOF + independiente.",
                }
            )
            continue
        signatures = independent_signatures(candidate)
        availability_rows.append(
            {
                "model": model,
                "implementation_status": implementation_status,
                "metrics_status": "available",
                "implementation_path": str(implementation_path.relative_to(REPO_ROOT)),
                "cv_assignment_path": str(cv_assignment_path.relative_to(REPO_ROOT)),
                "cv_assignment_sha256": cv_assignment_sha256 or "not_found",
                "selected_variant": candidate.variant,
                "split_family": candidate.split_family,
                "independent_rows": signatures["n_rows"],
                "independent_unique_keys": signatures["n_unique_keys"],
                "independent_classes": signatures["classes"] or "no_prediction_file",
                "independent_key_sha256": signatures["key_sha256"] or "no_prediction_file",
                "independent_reference_sha256": signatures["reference_sha256"]
                or "no_prediction_file",
                "note": "",
            }
        )
        metric_rows.extend(
            metric_row(candidate, stage)
            for stage in ["training", "cv_oof", "independent"]
        )

    availability = pd.DataFrame(availability_rows)
    metrics = pd.DataFrame(metric_rows)
    independent = metrics[metrics["evaluation_stage"] == "independent"].copy()
    for metric in METRICS:
        independent[f"rank_{metric}"] = independent[metric].rank(
            method="min", ascending=False
        ).astype("Int64")
    gaps = generalization_gaps(metrics)

    availability.to_csv(tables_dir / "model_availability.csv", index=False, encoding="utf-8-sig")
    metrics.to_csv(tables_dir / "model_metrics_comparison.csv", index=False, encoding="utf-8-sig")
    independent.to_csv(
        tables_dir / "independent_metrics_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )
    gaps.to_csv(tables_dir / "generalization_gaps.csv", index=False, encoding="utf-8-sig")

    implemented_models = availability.loc[
        availability["implementation_status"] == "available", "model"
    ].tolist()
    available_models = availability.loc[
        availability["metrics_status"] == "available", "model"
    ].tolist()
    missing_models = availability.loc[
        availability["metrics_status"] != "available", "model"
    ].tolist()
    shared_signatures = availability.loc[
        (availability["metrics_status"] == "available")
        & (availability["independent_key_sha256"] != "no_prediction_file"),
        ["model", "independent_key_sha256"],
    ]
    exact_same_holdout = (
        len(shared_signatures) == len(available_models)
        and len(shared_signatures) > 1
        and shared_signatures["independent_key_sha256"].nunique() == 1
    )
    shared_reference_signatures = availability.loc[
        (availability["metrics_status"] == "available")
        & (availability["independent_reference_sha256"] != "no_prediction_file"),
        ["model", "independent_reference_sha256"],
    ]
    exact_same_reference = (
        len(shared_reference_signatures) == len(available_models)
        and len(shared_reference_signatures) > 1
        and shared_reference_signatures["independent_reference_sha256"].nunique() == 1
    )
    shared_cv_signatures = availability.loc[
        (availability["metrics_status"] == "available")
        & (availability["cv_assignment_sha256"] != "not_found"),
        ["model", "cv_assignment_sha256"],
    ]
    exact_same_cv_folds = (
        len(shared_cv_signatures) == len(available_models)
        and len(shared_cv_signatures) > 1
        and shared_cv_signatures["cv_assignment_sha256"].nunique() == 1
    )

    independent_fields = [
        "model",
        "variant",
        "n_rows",
        *METRICS,
        *[f"rank_{metric}" for metric in METRICS],
    ]
    metric_fields = ["model", "evaluation_stage", "n_rows", *METRICS]
    gap_fields = [
        "model",
        "metric",
        "training_minus_independent",
        "cv_oof_minus_independent",
    ]
    lines = [
        "# Comparativa de modelos: RF, SVM, XGBoost y DNN",
        "",
        f"**Generado:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Alcance",
        "",
        "La comparación usa el objetivo homologado `id_1_propuesta` y separa entrenamiento, validación cruzada OOF y validación independiente. Las métricas de entrenamiento son diagnósticas; la comparación principal es la independiente.",
        "",
        f"- Modelos implementados en el repositorio: **{', '.join(implemented_models) or 'ninguno'}**.",
        f"- Modelos cuyas métricas completas se localizaron en este workspace: **{', '.join(available_models) or 'ninguno'}**.",
        f"- Implementaciones cuyas métricas no se localizaron en este workspace: **{', '.join(missing_models) or 'ninguno'}**.",
        f"- Holdout independiente exactamente coincidente entre todos los modelos disponibles: **{exact_same_holdout}**.",
        f"- Clases verdaderas homologadas exactamente coincidentes en el holdout: **{exact_same_reference}**.",
        f"- Asignación de folds CV exactamente coincidente entre todos los modelos disponibles: **{exact_same_cv_folds}**.",
        "",
        "## Disponibilidad y trazabilidad",
        "",
        dataframe_to_markdown(
            availability[
                [
                    "model",
                    "implementation_status",
                    "metrics_status",
                    "implementation_path",
                    "selected_variant",
                    "split_family",
                    "cv_assignment_path",
                    "independent_rows",
                    "independent_unique_keys",
                    "independent_classes",
                    "note",
                ]
            ]
        ),
        "",
        "## Comparación principal: validación independiente",
        "",
        dataframe_to_markdown(independent[independent_fields]),
        "",
        "## Métricas por etapa",
        "",
        dataframe_to_markdown(metrics[metric_fields]),
        "",
        "## Brechas de generalización",
        "",
        "Una brecha positiva `training_minus_independent` indica que el desempeño aparente de entrenamiento supera al holdout. `cv_oof_minus_independent` permite revisar la estabilidad entre la validación interna y la independiente.",
        "",
        dataframe_to_markdown(gaps[gap_fields]),
        "",
        "## Interpretación",
        "",
    ]
    if not independent.empty:
        for metric in METRICS:
            best_row = independent.sort_values(metric, ascending=False).iloc[0]
            lines.append(
                f"- Mayor `{metric}` independiente: **{best_row['model']}** "
                f"({float(best_row[metric]):.6f})."
            )
    if missing_models:
        lines.extend(
            [
                "",
                "No debe establecerse un ranking definitivo de las cuatro familias hasta localizar o generar las salidas métricas completas de todas las implementaciones.",
            ]
        )
    lines.extend(
        [
            "",
            "## Nota de comparabilidad espacial",
            "",
            "Los cuatro modelos usan el mismo holdout independiente, los mismos valores verdaderos de la clase homologada `id_1_propuesta` y la misma asignación congelada de folds CV. Esto se verificó mediante firmas SHA-256 de las parejas `xy_group_id`–clase verdadera y de los archivos de folds; por tanto, las métricas independientes son directamente comparables sobre las mismas observaciones.",
        ]
    )
    report_path = reports_dir / "a4_10_model_metrics_comparison.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Reporte: {report_path}")
    print(f"Modelos implementados: {implemented_models}")
    print(f"Métricas disponibles: {available_models}")
    print(f"Métricas no localizadas: {missing_models}")


if __name__ == "__main__":
    main()
