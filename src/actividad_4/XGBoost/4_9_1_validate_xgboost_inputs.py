# -*- coding: utf-8 -*-
"""
Actividad 4.9.1 - Validacion de insumos para XGBoost
====================================================

Diagnostica si los datos tabulares y los splits espaciales existentes estan
listos para entrenar un modelo XGBoost multiclase. No entrena modelos ni cambia
las particiones: solo valida disponibilidad, consistencia, leakage espacial,
balance de clases, folds CV y calidad basica de predictores.

Ejecucion desde la raiz del repositorio:

    python src/actividad_4/XGBoost/4_9_1_validate_xgboost_inputs.py
"""

from __future__ import annotations

import importlib.metadata
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


LOGGER = logging.getLogger("a4_9_1_validate_xgboost_inputs")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) >= 4 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_9_xgboost.yaml"
CONFIG_SECTION = "validate_inputs"


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
            output_dir / "logs" / "a4_9_1_validate_xgboost_inputs.log",
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


def package_version(package_name: str) -> str:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


def add_issue(
    issues: list[dict[str, Any]],
    severity: str,
    check: str,
    message: str,
    n_affected: int | float | None = None,
) -> None:
    issues.append(
        {
            "severity": severity,
            "check": check,
            "message": message,
            "n_affected": n_affected,
        }
    )


def class_balance(dataframe: pd.DataFrame, role: str, config: dict[str, Any]) -> pd.DataFrame:
    target = str(config["fields"]["target"])
    label = config["fields"].get("target_label")
    group = str(config["fields"]["group"])
    columns = [target]
    if label and str(label) in dataframe.columns:
        columns.append(str(label))
    summary = (
        dataframe.groupby(columns, dropna=False)
        .agg(n_points=(target, "size"), n_groups=(group, "nunique"))
        .reset_index()
        .sort_values(target)
    )
    summary.insert(0, "split_role", role)
    summary["pct_points_split"] = summary["n_points"] / len(dataframe) if len(dataframe) else np.nan
    return summary


def build_input_inventory(
    development: pd.DataFrame,
    independent: pd.DataFrame,
    feature_columns: list[str],
    config: dict[str, Any],
    paths_used: dict[str, Path],
    formats_used: dict[str, str],
) -> pd.DataFrame:
    fields = config["fields"]
    version = package_version("xgboost")
    return pd.DataFrame(
        [
            {
                "item": "development_dataset",
                "path": str(paths_used["development_dataset"]),
                "format": formats_used["development_dataset"],
                "n_rows": len(development),
                "n_columns": development.shape[1],
                "n_groups": development[str(fields["group"])].nunique(),
                "n_classes": development[str(fields["target"])].nunique(),
            },
            {
                "item": "independent_validation_dataset",
                "path": str(paths_used["independent_dataset"]),
                "format": formats_used["independent_dataset"],
                "n_rows": len(independent),
                "n_columns": independent.shape[1],
                "n_groups": independent[str(fields["group"])].nunique(),
                "n_classes": independent[str(fields["target"])].nunique(),
            },
            {
                "item": "selected_features",
                "path": str(paths_used["selected_features"]),
                "format": "txt",
                "n_rows": len(feature_columns),
                "n_columns": np.nan,
                "n_groups": np.nan,
                "n_classes": np.nan,
            },
            {
                "item": "xgboost_dependency",
                "path": "",
                "format": version,
                "n_rows": np.nan,
                "n_columns": np.nan,
                "n_groups": np.nan,
                "n_classes": np.nan,
            },
        ]
    )


def validate_dataset_consistency(
    development: pd.DataFrame,
    independent: pd.DataFrame,
    feature_columns: list[str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    fields = config["fields"]
    validation_cfg = config.get("validation", {}) or {}
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
            add_issue(issues, "critical", f"{name}_required_columns", f"Faltan columnas: {missing}", len(missing))
        duplicates = int(dataframe[key].duplicated().sum()) if key in dataframe.columns else 0
        if duplicates:
            add_issue(issues, "critical", f"{name}_duplicate_keys", "Hay llaves duplicadas.", duplicates)
        null_target = int(dataframe[target].isna().sum()) if target in dataframe.columns else 0
        if null_target:
            add_issue(issues, "critical", f"{name}_null_target", f"Hay nulos en {target}.", null_target)

    if key in development.columns and key in independent.columns:
        key_overlap = len(set(development[key]) & set(independent[key]))
        if key_overlap:
            add_issue(issues, "critical", "development_independent_key_overlap", "Hay puntos repetidos entre desarrollo e independiente.", key_overlap)

    if group in development.columns and group in independent.columns:
        group_overlap = len(set(development[group]) & set(independent[group]))
        if group_overlap:
            add_issue(issues, "critical", "development_independent_group_overlap", "Hay cuadrantes compartidos entre desarrollo e independiente.", group_overlap)

    if target in development.columns and target in independent.columns:
        unseen_classes = sorted(set(independent[target]) - set(development[target]))
        if unseen_classes:
            add_issue(
                issues,
                "critical",
                "unseen_independent_classes",
                f"Validacion independiente contiene clases ausentes en desarrollo: {unseen_classes}",
                len(unseen_classes),
            )

    if package_version("xgboost") == "not_installed":
        add_issue(issues, "warning", "xgboost_dependency", "El paquete xgboost no esta instalado en el ambiente actual.", None)

    warn_null = float(validation_cfg.get("warn_feature_null_pct", 0.05))
    warn_non_numeric = float(validation_cfg.get("warn_feature_non_numeric_pct", 0.0))
    for feature in feature_columns:
        if feature not in development.columns:
            continue
        null_pct = float(development[feature].isna().mean())
        if null_pct > warn_null:
            add_issue(issues, "warning", "feature_null_pct", f"{feature} supera el umbral de nulos en desarrollo.", null_pct)
        if not pd.api.types.is_numeric_dtype(development[feature]):
            converted = pd.to_numeric(development[feature], errors="coerce")
            non_numeric_pct = float(converted.isna().mean() - development[feature].isna().mean())
            if non_numeric_pct > warn_non_numeric:
                add_issue(issues, "warning", "feature_non_numeric_pct", f"{feature} tiene valores no numericos.", non_numeric_pct)

    return issues


def feature_quality_summary(
    development: pd.DataFrame,
    independent: pd.DataFrame,
    feature_columns: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for feature in feature_columns:
        dev_exists = feature in development.columns
        ind_exists = feature in independent.columns
        dev = development[feature] if dev_exists else pd.Series(dtype=float)
        ind = independent[feature] if ind_exists else pd.Series(dtype=float)
        dev_numeric = bool(pd.api.types.is_numeric_dtype(dev)) if dev_exists else False
        ind_numeric = bool(pd.api.types.is_numeric_dtype(ind)) if ind_exists else False
        rows.append(
            {
                "feature": feature,
                "exists_development": dev_exists,
                "exists_independent": ind_exists,
                "development_dtype": str(dev.dtype) if dev_exists else "",
                "independent_dtype": str(ind.dtype) if ind_exists else "",
                "development_is_numeric": dev_numeric,
                "independent_is_numeric": ind_numeric,
                "development_null_pct": float(dev.isna().mean()) if dev_exists else np.nan,
                "independent_null_pct": float(ind.isna().mean()) if ind_exists else np.nan,
                "development_n_unique": int(dev.nunique(dropna=True)) if dev_exists else 0,
                "independent_n_unique": int(ind.nunique(dropna=True)) if ind_exists else 0,
            }
        )
    return pd.DataFrame(rows).sort_values(["development_null_pct", "feature"], ascending=[False, True])


def validate_cv_assignments(
    development: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    paths = config["paths"]
    key = str(config["fields"]["key"])
    group = str(config["fields"]["group"])
    target = str(config["fields"]["target"])
    assignments_path = resolve_path(paths["cv_fold_assignments_csv"])
    if not assignments_path.exists():
        add_issue(issues, "critical", "cv_assignments_missing", f"No existe {assignments_path}", None)
        return pd.DataFrame(), issues

    assignments = pd.read_csv(assignments_path, encoding=str(config.get("read", {}).get("csv_encoding", "utf-8-sig")), low_memory=False)
    for field in [key, group, target, "fold_id", "cv_role"]:
        if field not in assignments.columns:
            add_issue(issues, "critical", "cv_assignments_required_columns", f"Falta {field} en asignaciones CV.", None)
            return pd.DataFrame(), issues

    dev_keys = set(development[key].astype(str))
    assignments[key] = assignments[key].astype(str)
    assignments[group] = assignments[group].astype(str)
    assignments[target] = assignments[target].astype(str)

    validation_rows = assignments[assignments["cv_role"].astype(str) == "cv_validation"].copy()
    validation_key_counts = validation_rows[key].value_counts()
    duplicated_validation_keys = int((validation_key_counts > 1).sum())
    unassigned_keys = len(dev_keys - set(validation_rows[key]))
    extra_keys = len(set(validation_rows[key]) - dev_keys)

    if duplicated_validation_keys:
        add_issue(issues, "critical", "cv_duplicate_validation_keys", "Hay puntos asignados a validacion en mas de un fold.", duplicated_validation_keys)
    if unassigned_keys:
        add_issue(issues, "critical", "cv_unassigned_development_keys", "Hay puntos de desarrollo sin fold de validacion.", unassigned_keys)
    if extra_keys:
        add_issue(issues, "critical", "cv_extra_validation_keys", "Hay llaves CV que no estan en desarrollo.", extra_keys)

    rows: list[dict[str, Any]] = []
    for fold_id in sorted(assignments["fold_id"].dropna().unique()):
        fold = assignments[assignments["fold_id"] == fold_id]
        train = fold[fold["cv_role"].astype(str) == "cv_train"]
        validation = fold[fold["cv_role"].astype(str) == "cv_validation"]
        train_groups = set(train[group])
        validation_groups = set(validation[group])
        group_overlap = len(train_groups & validation_groups)
        unseen_classes = sorted(set(validation[target]) - set(train[target]))
        rows.append(
            {
                "fold_id": fold_id,
                "n_train": len(train),
                "n_validation": len(validation),
                "n_train_groups": len(train_groups),
                "n_validation_groups": len(validation_groups),
                "n_train_classes": train[target].nunique(),
                "n_validation_classes": validation[target].nunique(),
                "group_overlap": group_overlap,
                "unseen_validation_classes": "|".join(unseen_classes),
            }
        )
        if group_overlap:
            add_issue(issues, "critical", "cv_group_leakage", f"Fold {fold_id} comparte cuadrantes entre train y validacion.", group_overlap)
        if unseen_classes:
            add_issue(issues, "critical", "cv_unseen_validation_classes", f"Fold {fold_id} tiene clases no vistas en train: {unseen_classes}", len(unseen_classes))

    return pd.DataFrame(rows), issues


def should_fail(issues: list[dict[str, Any]], config: dict[str, Any]) -> bool:
    validation_cfg = config.get("validation", {}) or {}
    critical = [issue for issue in issues if issue["severity"] == "critical"]
    if not critical:
        return False
    checks_to_flags = {
        "development_required_columns": "fail_on_missing_required_fields",
        "independent_validation_required_columns": "fail_on_missing_required_fields",
        "development_duplicate_keys": "fail_on_duplicate_keys",
        "independent_validation_duplicate_keys": "fail_on_duplicate_keys",
        "development_independent_key_overlap": "fail_on_key_overlap",
        "development_independent_group_overlap": "fail_on_group_leakage",
        "unseen_independent_classes": "fail_on_unseen_independent_classes",
        "cv_group_leakage": "fail_on_cv_group_leakage",
        "cv_unseen_validation_classes": "fail_on_unseen_cv_validation_classes",
        "cv_unassigned_development_keys": "fail_on_unassigned_development_keys",
    }
    for issue in critical:
        flag = checks_to_flags.get(str(issue["check"]), "fail_on_missing_required_fields")
        if bool(validation_cfg.get(flag, True)):
            return True
    return False


def dataframe_to_markdown(dataframe: pd.DataFrame, max_rows: int = 20) -> str:
    if dataframe.empty:
        return "_Sin registros._"
    return dataframe.head(max_rows).to_markdown(index=False)


def write_report(
    output_dir: Path,
    config: dict[str, Any],
    inventory: pd.DataFrame,
    balance: pd.DataFrame,
    cv_summary: pd.DataFrame,
    feature_quality: pd.DataFrame,
    issues: pd.DataFrame,
) -> None:
    outputs = config.get("outputs", {}) or {}
    report_path = output_dir / outputs.get("report_md", "reports/a4_9_1_validate_xgboost_inputs_report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    critical_count = int((issues["severity"] == "critical").sum()) if not issues.empty else 0
    warning_count = int((issues["severity"] == "warning").sum()) if not issues.empty else 0
    max_null = float(feature_quality["development_null_pct"].max()) if not feature_quality.empty else np.nan
    n_non_numeric = int((~feature_quality["development_is_numeric"]).sum()) if not feature_quality.empty else 0

    lines = [
        "# Actividad 4.9.1 - Validacion de insumos para XGBoost",
        "",
        f"**Fecha:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Resultado general",
        "",
        f"- Incidencias criticas: **{critical_count:,}**",
        f"- Advertencias: **{warning_count:,}**",
        f"- Predictores evaluados: **{len(feature_quality):,}**",
        f"- Mayor porcentaje de nulos en desarrollo: **{max_null:.6f}**",
        f"- Predictores no numericos en desarrollo: **{n_non_numeric:,}**",
        "",
        "## Inventario de insumos",
        "",
        dataframe_to_markdown(inventory),
        "",
        "## Balance de clases",
        "",
        dataframe_to_markdown(balance, max_rows=30),
        "",
        "## Resumen CV espacial",
        "",
        dataframe_to_markdown(cv_summary),
        "",
        "## Predictores con mas nulos en desarrollo",
        "",
        dataframe_to_markdown(
            feature_quality[
                [
                    "feature",
                    "development_dtype",
                    "development_is_numeric",
                    "development_null_pct",
                    "independent_null_pct",
                    "development_n_unique",
                ]
            ],
            max_rows=20,
        ),
        "",
        "## Incidencias",
        "",
        dataframe_to_markdown(issues, max_rows=50),
        "",
        "## Nota metodologica",
        "",
        "Esta etapa reutiliza las particiones espaciales creadas previamente: "
        "desarrollo para entrenamiento y CV interna, y validacion independiente "
        "por cuadrantes completos. No es Leave-One-Out; es una validacion "
        "agrupada espacialmente por `id_cuadrante`.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Reporte escrito: %s", report_path)


def run_validation(config: dict[str, Any]) -> None:
    output_dir = resolve_path(config["paths"]["output_dir"])
    configure_logger(output_dir)
    outputs = config.get("outputs", {}) or {}

    development, development_path, development_format = read_partitioned_dataset(
        config,
        "development_dataset_parquet",
        "development_dataset_csv",
        "desarrollo XGBoost",
    )
    independent, independent_path, independent_format = read_partitioned_dataset(
        config,
        "independent_dataset_parquet",
        "independent_dataset_csv",
        "validacion independiente XGBoost",
    )
    development = normalize_core_fields(development, config)
    independent = normalize_core_fields(independent, config)

    feature_path = resolve_path(config["paths"]["selected_features_txt"])
    feature_columns = read_text_list(feature_path, "selected_features_txt")
    paths_used = {
        "development_dataset": development_path,
        "independent_dataset": independent_path,
        "selected_features": feature_path,
    }
    formats_used = {
        "development_dataset": development_format,
        "independent_dataset": independent_format,
    }

    issues = validate_dataset_consistency(development, independent, feature_columns, config)
    cv_summary, cv_issues = validate_cv_assignments(development, config)
    issues.extend(cv_issues)

    inventory = build_input_inventory(development, independent, feature_columns, config, paths_used, formats_used)
    balance = pd.concat(
        [
            class_balance(development, "development_cv", config),
            class_balance(independent, "independent_validation", config),
        ],
        ignore_index=True,
    )
    feature_quality = feature_quality_summary(development, independent, feature_columns)
    issues_df = pd.DataFrame(issues, columns=["severity", "check", "message", "n_affected"])

    inventory.to_csv(output_dir / outputs.get("input_inventory_csv", "tables/xgboost_input_inventory.csv"), index=False, encoding="utf-8-sig")
    balance.to_csv(output_dir / outputs.get("class_balance_csv", "tables/xgboost_class_balance.csv"), index=False, encoding="utf-8-sig")
    cv_summary.to_csv(output_dir / outputs.get("cv_fold_summary_csv", "tables/xgboost_cv_fold_summary.csv"), index=False, encoding="utf-8-sig")
    feature_quality.to_csv(output_dir / outputs.get("feature_quality_csv", "tables/xgboost_feature_quality_summary.csv"), index=False, encoding="utf-8-sig")
    issues_df.to_csv(output_dir / outputs.get("validation_issues_csv", "tables/xgboost_validation_issues.csv"), index=False, encoding="utf-8-sig")
    write_report(output_dir, config, inventory, balance, cv_summary, feature_quality, issues_df)

    n_critical = int((issues_df["severity"] == "critical").sum()) if not issues_df.empty else 0
    n_warning = int((issues_df["severity"] == "warning").sum()) if not issues_df.empty else 0
    LOGGER.info(
        "A4.9.1 finalizado: desarrollo=%s | independiente=%s | predictores=%s | criticas=%s | advertencias=%s",
        f"{len(development):,}",
        f"{len(independent):,}",
        f"{len(feature_columns):,}",
        f"{n_critical:,}",
        f"{n_warning:,}",
    )

    if should_fail(issues, config):
        raise ValueError("La validacion XGBoost encontro incidencias criticas. Revisar el reporte.")


def main() -> None:
    config_path, config_section = split_config_arg(sys.argv[1], CONFIG_SECTION) if len(sys.argv) > 1 else (DEFAULT_CONFIG, CONFIG_SECTION)
    config = select_config_section(read_yaml(config_path), config_section)
    run_validation(config)


if __name__ == "__main__":
    main()
