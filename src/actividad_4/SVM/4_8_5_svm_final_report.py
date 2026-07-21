# -*- coding: utf-8 -*-
"""
Actividad 4.8.5 - Informe final SVM
===================================

Consolida los resultados ya generados del flujo SVM. No entrena modelos ni
recalcula particiones.

Ejecucion desde la raiz del repositorio:

    python src/actividad_4/SVM/4_8_5_svm_final_report.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) >= 4 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_8_svm.yaml"
CONFIG_SECTION = "final_report"


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


def select_config_section(config: dict[str, Any], section: str) -> dict[str, Any]:
    if section in config:
        selected = config[section]
        if not isinstance(selected, dict):
            raise ValueError(f"La seccion {section} debe contener un diccionario.")
        return selected
    return config


def dataframe_to_markdown(dataframe: pd.DataFrame, max_rows: int | None = None) -> str:
    if dataframe.empty:
        return "_Sin datos._"
    display = dataframe.copy()
    if max_rows is not None and len(display) > max_rows:
        display = display.head(max_rows).copy()
    return display.to_markdown(index=False)


def read_csv(path: Path, label: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"No existe {label}: {path}")
    return pd.read_csv(path, encoding="utf-8-sig")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def metric_record(metrics: pd.DataFrame) -> dict[str, Any]:
    if metrics.empty:
        raise ValueError("Tabla de metricas vacia.")
    row = metrics.iloc[0].to_dict()
    return {
        "n_rows": int(row.get("n_rows", 0)),
        "accuracy": float(row.get("accuracy", float("nan"))),
        "balanced_accuracy": float(row.get("balanced_accuracy", float("nan"))),
        "f1_macro": float(row.get("f1_macro", float("nan"))),
        "f1_weighted": float(row.get("f1_weighted", float("nan"))),
        "kappa": float(row.get("kappa", float("nan"))),
    }


def load_model_results(config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, dict[str, pd.DataFrame]]]:
    rows: list[dict[str, Any]] = []
    detail_tables: dict[str, dict[str, pd.DataFrame]] = {}

    for model_cfg in config.get("models", []):
        result_dir = resolve_path(model_cfg["result_dir"])
        best_params = read_json(result_dir / model_cfg["best_params_json"])
        cv_metrics = read_csv(result_dir / model_cfg["cv_overall_metrics_csv"], f"cv metrics {model_cfg['model_id']}")
        independent_metrics = read_csv(
            result_dir / model_cfg["independent_metrics_csv"],
            f"independent metrics {model_cfg['model_id']}",
        )
        class_metrics = read_csv(
            result_dir / model_cfg["independent_class_metrics_csv"],
            f"class metrics {model_cfg['model_id']}",
        )
        confusion = read_csv(
            result_dir / model_cfg["independent_confusion_csv"],
            f"confusion {model_cfg['model_id']}",
        )

        cv = metric_record(cv_metrics)
        independent = metric_record(independent_metrics)
        rows.append(
            {
                "model_id": model_cfg["model_id"],
                "model_name": model_cfg["model_name"],
                "configuration": model_cfg["configuration"],
                "recommendation_role": model_cfg.get("recommendation_role", ""),
                "best_params": json.dumps(best_params, ensure_ascii=False),
                "cv_accuracy": cv["accuracy"],
                "cv_balanced_accuracy": cv["balanced_accuracy"],
                "cv_f1_macro": cv["f1_macro"],
                "cv_f1_weighted": cv["f1_weighted"],
                "cv_kappa": cv["kappa"],
                "ind_accuracy": independent["accuracy"],
                "ind_balanced_accuracy": independent["balanced_accuracy"],
                "ind_f1_macro": independent["f1_macro"],
                "ind_f1_weighted": independent["f1_weighted"],
                "ind_kappa": independent["kappa"],
                "model_path": str((result_dir / model_cfg["model_path"]).relative_to(REPO_ROOT)),
                "result_dir": str(result_dir.relative_to(REPO_ROOT)),
            }
        )
        detail_tables[model_cfg["model_id"]] = {
            "class_metrics": class_metrics,
            "confusion": confusion,
        }

    comparison = pd.DataFrame(rows).sort_values("ind_f1_macro", ascending=False).reset_index(drop=True)
    comparison.insert(0, "rank_ind_f1_macro", range(1, len(comparison) + 1))
    return comparison, detail_tables


def top_confusions(confusion: pd.DataFrame, class_metrics: pd.DataFrame, max_rows: int = 12) -> pd.DataFrame:
    required = {"true_class", "predicted_class", "n"}
    if not required.issubset(confusion.columns):
        return pd.DataFrame()
    output = confusion.copy()
    output = output[output["true_class"].astype(str) != output["predicted_class"].astype(str)].copy()
    output = output[output["n"] > 0].sort_values("n", ascending=False)
    keep = [
        column
        for column in [
            "true_class",
            "true_class_label",
            "predicted_class",
            "predicted_class_label",
            "n",
        ]
        if column in output.columns
    ]
    return output[keep].head(max_rows).reset_index(drop=True)


def weak_class_table(class_metrics: pd.DataFrame, max_f1: float = 0.30) -> pd.DataFrame:
    if "f1-score" not in class_metrics.columns:
        return pd.DataFrame()
    output = class_metrics.copy()
    output = output[pd.to_numeric(output["class_id"], errors="coerce").notna()].copy()
    output["f1-score"] = pd.to_numeric(output["f1-score"], errors="coerce")
    output = output[output["f1-score"] <= max_f1].sort_values("f1-score")
    keep = [column for column in ["class_id", "class_label", "precision", "recall", "f1-score", "support"] if column in output]
    return output[keep].reset_index(drop=True)


def strong_class_table(class_metrics: pd.DataFrame, min_f1: float = 0.75) -> pd.DataFrame:
    if "f1-score" not in class_metrics.columns:
        return pd.DataFrame()
    output = class_metrics.copy()
    output = output[pd.to_numeric(output["class_id"], errors="coerce").notna()].copy()
    output["f1-score"] = pd.to_numeric(output["f1-score"], errors="coerce")
    output = output[output["f1-score"] >= min_f1].sort_values("f1-score", ascending=False)
    keep = [column for column in ["class_id", "class_label", "precision", "recall", "f1-score", "support"] if column in output]
    return output[keep].reset_index(drop=True)


def selected_rows(comparison: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.Series, pd.Series, pd.Series]:
    rec = config["recommendation"]
    by_id = comparison.set_index("model_id")
    return (
        by_id.loc[rec["best_model_id"]],
        by_id.loc[rec["cost_benefit_model_id"]],
        by_id.loc[rec["linear_baseline_model_id"]],
    )


def build_report(config: dict[str, Any]) -> Path:
    output_dir = resolve_path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = config.get("outputs", {}) or {}

    target_distribution = read_csv(
        resolve_path(config["paths"]["target_distribution_csv"]),
        "target_distribution_csv",
    )
    split_summary = read_csv(resolve_path(config["paths"]["split_summary_csv"]), "split_summary_csv")
    comparison, detail_tables = load_model_results(config)

    best_row, cost_benefit_row, linear_row = selected_rows(comparison, config)
    recommended_classes = detail_tables[str(best_row.name)]["class_metrics"]
    recommended_confusion = detail_tables[str(best_row.name)]["confusion"]
    weak_classes = weak_class_table(recommended_classes)
    strong_classes = strong_class_table(recommended_classes)
    confusions = top_confusions(recommended_confusion, recommended_classes)

    comparison.to_csv(output_dir / outputs.get("model_comparison_csv", "a4_8_svm_model_comparison.csv"), index=False, encoding="utf-8-sig")
    recommended_classes.to_csv(
        output_dir / outputs.get("recommended_class_metrics_csv", "a4_8_svm_recommended_class_metrics.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    confusions.to_csv(
        output_dir / outputs.get("recommended_top_confusions_csv", "a4_8_svm_recommended_top_confusions.csv"),
        index=False,
        encoding="utf-8-sig",
    )

    comparison_report = comparison[
        [
            "rank_ind_f1_macro",
            "model_name",
            "configuration",
            "cv_f1_macro",
            "ind_accuracy",
            "ind_balanced_accuracy",
            "ind_f1_macro",
            "ind_f1_weighted",
            "ind_kappa",
        ]
    ].copy()

    target_field = str(config["fields"]["target"])
    target_table = target_distribution[target_distribution["target_field"].astype(str) == target_field].copy()
    target_table = target_table[["class_id", "n_points", "pct_points", "n_groups"]].sort_values("n_points", ascending=False)

    report_path = output_dir / outputs.get("final_report_md", "a4_8_svm_final_report.md")
    lines = [
        "# Informe final SVM - Actividad 4.8",
        "",
        f"**Fecha:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Objetivo",
        "",
        "Consolidar los resultados del flujo SVM para `id_1_propuesta`, sin comparacion formal contra RF. "
        "El entrenamiento y la seleccion de hiperparametros usaron validacion cruzada espacial dentro del conjunto de desarrollo; "
        "la validacion independiente permanecio fuera de GridSearchCV.",
        "",
        "## Datos y particiones",
        "",
        "Distribucion del objetivo en el dataset preparado:",
        "",
        dataframe_to_markdown(target_table),
        "",
        "Particiones espaciales:",
        "",
        dataframe_to_markdown(split_summary),
        "",
        "## Modelos evaluados",
        "",
        dataframe_to_markdown(comparison_report),
        "",
        "## Modelo recomendado por desempeno",
        "",
        f"- Modelo: **{best_row['model_name']}**",
        f"- Configuracion: `{best_row['configuration']}`",
        f"- Mejor conjunto de parametros: `{best_row['best_params']}`",
        f"- Modelo guardado: `{best_row['model_path']}`",
        "",
        "Metricas independientes del modelo recomendado:",
        "",
        "| accuracy | balanced_accuracy | f1_macro | f1_weighted | kappa |",
        "|--:|--:|--:|--:|--:|",
        f"| {best_row['ind_accuracy']:.6f} | {best_row['ind_balanced_accuracy']:.6f} | {best_row['ind_f1_macro']:.6f} | {best_row['ind_f1_weighted']:.6f} | {best_row['ind_kappa']:.6f} |",
        "",
        "## Alternativa costo/beneficio",
        "",
        f"- Modelo: **{cost_benefit_row['model_name']}**",
        f"- Configuracion: `{cost_benefit_row['configuration']}`",
        f"- Modelo guardado: `{cost_benefit_row['model_path']}`",
        "",
        "Esta alternativa fue menos costosa porque uso 300 componentes Nystroem en lugar de 600, con una perdida pequena de `f1_macro` independiente.",
        "",
        "## Linea base lineal",
        "",
        f"- Modelo: **{linear_row['model_name']}**",
        f"- Configuracion: `{linear_row['configuration']}`",
        f"- `f1_macro` independiente: `{linear_row['ind_f1_macro']:.6f}`",
        "",
        "La linea base lineal queda como referencia parsimoniosa, pero no como el mejor SVM observado.",
        "",
        "## Desempeno por clase del modelo recomendado",
        "",
        dataframe_to_markdown(recommended_classes[["class_id", "class_label", "precision", "recall", "f1-score", "support"]]),
        "",
        "## Clases fuertes",
        "",
        dataframe_to_markdown(strong_classes),
        "",
        "## Clases debiles",
        "",
        dataframe_to_markdown(weak_classes),
        "",
        "## Confusiones principales",
        "",
        dataframe_to_markdown(confusions),
        "",
        "## Lectura metodologica",
        "",
        "- El salto principal de desempeno ocurrio al pasar del SVM lineal al SVM no lineal aproximado con Nystroem RBF.",
        "- El refinamiento de 300 a 600 componentes mejoro el desempeno independiente, pero con mayor costo computacional.",
        "- `class_weight=balanced` no fue seleccionado en las mejores configuraciones observadas.",
        "- Las clases `plantaciones forestales` y `otras tierras` siguen siendo los puntos mas debiles del flujo SVM.",
        "- La validacion independiente se mantuvo separada de la seleccion de hiperparametros, por lo que sus metricas son la principal evidencia de generalizacion espacial.",
        "",
        "## Recomendacion final",
        "",
        "Para reportar el mejor desempeno SVM observado, usar:",
        "",
        "```text",
        str(best_row["configuration"]),
        "```",
        "",
        "Para una opcion con mejor balance entre costo y desempeno, usar:",
        "",
        "```text",
        str(cost_benefit_row["configuration"]),
        "```",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> None:
    config_path = resolve_path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG
    config = select_config_section(read_yaml(config_path), CONFIG_SECTION)
    report_path = build_report(config)
    print(f"Informe final SVM escrito: {report_path}")


if __name__ == "__main__":
    main()
