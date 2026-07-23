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

    def format_cell(value: Any) -> str:
        try:
            if bool(pd.isna(value)):
                return ""
        except (TypeError, ValueError):
            pass
        if isinstance(value, float):
            return f"{value:.6f}"
        return str(value).replace("|", r"\|").replace("\n", "<br>")

    headers = [format_cell(column) for column in display.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in display.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(format_cell(value) for value in row) + " |")
    return "\n".join(lines)


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


def actual_configuration(model_cfg: dict[str, Any], best_params: dict[str, Any]) -> str:
    """Describe la configuración efectiva usando la salida de GridSearchCV."""
    c_value = best_params.get("clf__C")
    class_weight = best_params.get("clf__class_weight")
    if "kernel__gamma" in best_params or "kernel__n_components" in best_params:
        gamma = best_params.get("kernel__gamma")
        n_components = best_params.get("kernel__n_components")
        return (
            f"Nystroem(RBF, gamma={gamma}, n_components={n_components}) + "
            f"LinearSVC(C={c_value}, class_weight={class_weight})"
        )
    if c_value is not None:
        return f"LinearSVC(C={c_value}, class_weight={class_weight})"
    return str(model_cfg.get("configuration", "Configuración no descrita"))


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def load_model_results(
    config: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, dict[str, pd.DataFrame]], pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    detail_tables: dict[str, dict[str, pd.DataFrame]] = {}
    skipped_rows: list[dict[str, Any]] = []

    for model_cfg in config.get("models", []):
        result_dir = resolve_path(model_cfg["result_dir"])
        required_paths = {
            "best_params_json": result_dir / model_cfg["best_params_json"],
            "cv_overall_metrics_csv": result_dir / model_cfg["cv_overall_metrics_csv"],
            "independent_metrics_csv": result_dir / model_cfg["independent_metrics_csv"],
            "independent_class_metrics_csv": result_dir
            / model_cfg["independent_class_metrics_csv"],
            "independent_confusion_csv": result_dir
            / model_cfg["independent_confusion_csv"],
            "model_path": result_dir / model_cfg["model_path"],
        }
        missing_paths = [path for path in required_paths.values() if not path.exists()]
        if missing_paths:
            skipped_rows.append(
                {
                    "model_id": model_cfg["model_id"],
                    "model_name": model_cfg["model_name"],
                    "result_dir": relative_path(result_dir),
                    "missing_file_count": len(missing_paths),
                    "missing_files": "; ".join(relative_path(path) for path in missing_paths),
                }
            )
            continue

        best_params = read_json(required_paths["best_params_json"])
        cv_metrics = read_csv(
            required_paths["cv_overall_metrics_csv"],
            f"cv metrics {model_cfg['model_id']}",
        )
        independent_metrics = read_csv(
            required_paths["independent_metrics_csv"],
            f"independent metrics {model_cfg['model_id']}",
        )
        class_metrics = read_csv(
            required_paths["independent_class_metrics_csv"],
            f"class metrics {model_cfg['model_id']}",
        )
        confusion = read_csv(
            required_paths["independent_confusion_csv"],
            f"confusion {model_cfg['model_id']}",
        )

        cv = metric_record(cv_metrics)
        independent = metric_record(independent_metrics)
        rows.append(
            {
                "model_id": model_cfg["model_id"],
                "model_name": model_cfg["model_name"],
                "configuration": actual_configuration(model_cfg, best_params),
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
                "model_path": relative_path(required_paths["model_path"]),
                "result_dir": relative_path(result_dir),
            }
        )
        detail_tables[model_cfg["model_id"]] = {
            "class_metrics": class_metrics,
            "confusion": confusion,
        }

    if not rows:
        missing_summary = "\n".join(
            f"- {row['model_id']}: {row['missing_files']}" for row in skipped_rows
        )
        raise FileNotFoundError(
            "No se encontró ninguna ejecución SVM completa configurada para el informe.\n"
            + missing_summary
        )

    comparison = pd.DataFrame(rows).sort_values("ind_f1_macro", ascending=False).reset_index(drop=True)
    comparison.insert(0, "rank_ind_f1_macro", range(1, len(comparison) + 1))
    skipped = pd.DataFrame(skipped_rows)
    return comparison, detail_tables, skipped


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

    best_id = rec.get("best_model_id")
    best = by_id.loc[best_id] if best_id in by_id.index else by_id.iloc[0]

    cost_id = rec.get("cost_benefit_model_id")
    if cost_id in by_id.index:
        cost_benefit = by_id.loc[cost_id]
    else:
        candidates = by_id[by_id["recommendation_role"] == "costo_beneficio"]
        cost_benefit = candidates.iloc[0] if not candidates.empty else best

    linear_id = rec.get("linear_baseline_model_id")
    if linear_id in by_id.index:
        linear = by_id.loc[linear_id]
    else:
        candidates = by_id[by_id["recommendation_role"] == "lineal_base"]
        linear = candidates.iloc[0] if not candidates.empty else best

    return best, cost_benefit, linear


def build_report(config: dict[str, Any]) -> Path:
    output_dir = resolve_path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = config.get("outputs", {}) or {}

    target_distribution = read_csv(
        resolve_path(config["paths"]["target_distribution_csv"]),
        "target_distribution_csv",
    )
    split_summary = read_csv(resolve_path(config["paths"]["split_summary_csv"]), "split_summary_csv")
    comparison, detail_tables, skipped_models = load_model_results(config)

    best_row, cost_benefit_row, linear_row = selected_rows(comparison, config)
    recommended_classes = detail_tables[str(best_row.name)]["class_metrics"]
    recommended_confusion = detail_tables[str(best_row.name)]["confusion"]
    weak_classes = weak_class_table(recommended_classes)
    strong_classes = strong_class_table(recommended_classes)
    confusions = top_confusions(recommended_confusion, recommended_classes)

    comparison.to_csv(output_dir / outputs.get("model_comparison_csv", "a4_8_svm_model_comparison.csv"), index=False, encoding="utf-8-sig")
    skipped_models.to_csv(
        output_dir / outputs.get("skipped_models_csv", "a4_8_svm_skipped_models.csv"),
        index=False,
        encoding="utf-8-sig",
    )
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

    same_cost_benefit_model = str(cost_benefit_row.name) == str(best_row.name)
    if same_cost_benefit_model:
        cost_benefit_explanation = (
            "Con las ejecuciones completas disponibles, esta alternativa coincide con el modelo "
            "recomendado por desempeño."
        )
    else:
        cost_benefit_explanation = (
            "Esta alternativa se conserva como referencia de costo/beneficio entre las "
            "ejecuciones completas disponibles."
        )

    interpretation_lines = [
        "- La comparación y la recomendación consideran únicamente ejecuciones con todos los archivos requeridos.",
        "- La validación independiente se mantuvo separada de la selección de hiperparámetros, por lo que sus métricas son la principal evidencia de generalización espacial.",
    ]
    if not skipped_models.empty:
        skipped_ids = ", ".join(skipped_models["model_id"].astype(str))
        interpretation_lines.append(
            f"- Se omitieron configuraciones sin salida completa: `{skipped_ids}`; no se imputaron ni supusieron métricas."
        )

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
        "## Configuraciones omitidas por no tener salida completa",
        "",
        dataframe_to_markdown(skipped_models),
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
        cost_benefit_explanation,
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
        *interpretation_lines,
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
