# -*- coding: utf-8 -*-
"""
Actividad 4.8.2 - Particiones espaciales para SVM
=================================================

Esta etapa toma el dataset preparado en A4.8.1 y crea particiones espaciales
independientes para el flujo SVM:

1. Holdout independiente con cuadrantes completos.
2. Folds internos de validacion cruzada dentro del conjunto de desarrollo.

No entrena modelos, no imputa, no escala y no calcula metricas predictivas.

Todo es totalmente compatiblecon el flujo desarrollado para Random Forest en A4.7.2, pero con la diferencia de que SVM requiere que las particiones sean por cuadrantes completos, para evitar fuga espacial.

Ejecucion desde la raiz del repositorio:

    python src/actividad_4/SVM/4_8_2_create_svm_spatial_splits.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from sklearn.model_selection import GroupKFold

try:
    from sklearn.model_selection import StratifiedGroupKFold
except ImportError:  # pragma: no cover - depende de la version de sklearn
    StratifiedGroupKFold = None


LOGGER = logging.getLogger("a4_8_2_create_svm_spatial_splits")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) >= 4 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_8_svm.yaml"
CONFIG_SECTION = "spatial_splits"


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


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


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
            output_dir / "logs" / "a4_8_2_create_svm_spatial_splits.log",
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


def read_dataset(config: dict[str, Any]) -> tuple[pd.DataFrame, Path, str]:
    paths = config["paths"]
    prefer_parquet = bool(config.get("read", {}).get("prefer_parquet", True))
    parquet_path = resolve_path(paths["prepared_dataset_parquet"])
    csv_path = resolve_path(paths["prepared_dataset_csv"])
    csv_encoding = str(config.get("read", {}).get("csv_encoding", "utf-8-sig"))

    if prefer_parquet and parquet_path.exists():
        LOGGER.info("Leyendo dataset SVM preparado Parquet: %s", parquet_path)
        return pd.read_parquet(parquet_path), parquet_path, "parquet"

    if csv_path.exists():
        LOGGER.info("Leyendo dataset SVM preparado CSV: %s", csv_path)
        return pd.read_csv(csv_path, encoding=csv_encoding, low_memory=False), csv_path, "csv"

    if parquet_path.exists():
        LOGGER.info("Leyendo dataset SVM preparado Parquet: %s", parquet_path)
        return pd.read_parquet(parquet_path), parquet_path, "parquet"

    raise FileNotFoundError(f"No existe dataset preparado A4.8.1: {parquet_path} ni {csv_path}")


def validate_inputs(dataframe: pd.DataFrame, config: dict[str, Any]) -> None:
    fields = config["fields"]
    required = [str(fields["key"]), str(fields["group"]), str(fields["target"])]
    label = fields.get("target_label")
    if label:
        required.append(str(label))

    missing = sorted(set(required) - set(dataframe.columns))
    if missing and bool(config.get("validation", {}).get("fail_on_missing_required_fields", True)):
        raise ValueError(f"Faltan campos requeridos para splits SVM: {missing}")
    if missing:
        LOGGER.warning("Faltan campos requeridos para splits SVM: %s", missing)

    key = str(fields["key"])
    duplicated = int(dataframe[key].astype(str).duplicated().sum())
    if duplicated and bool(config.get("validation", {}).get("fail_on_duplicate_keys", True)):
        raise ValueError(f"El campo {key} tiene {duplicated:,} llaves duplicadas.")

    if dataframe[str(fields["group"])].isna().any():
        raise ValueError(f"El campo de grupo {fields['group']} contiene nulos.")
    if dataframe[str(fields["target"])].isna().any():
        raise ValueError(f"El target {fields['target']} contiene nulos.")


def normalize_split_fields(dataframe: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    fields = config["fields"]
    output = dataframe.copy()
    for field in [fields["key"], fields["group"], fields["target"]]:
        output[str(field)] = output[str(field)].astype(str).str.strip()
    label = fields.get("target_label")
    if label and str(label) in output.columns:
        output[str(label)] = output[str(label)].astype(str).str.strip()
    return output.reset_index(drop=True)


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


def joined_class_labels(class_ids: list[str], class_labels: dict[str, str]) -> str:
    return "|".join(class_labels.get(str(class_id), "") for class_id in class_ids)


def add_target_labels(
    dataframe: pd.DataFrame,
    target: str,
    label_field: str | None,
    class_labels: dict[str, str],
) -> pd.DataFrame:
    if dataframe.empty or not class_labels or target not in dataframe.columns:
        return dataframe
    output = dataframe.copy()
    output[str(label_field or "class_label")] = output[target].astype(str).map(class_labels)
    return output


def dataframe_to_markdown(dataframe: pd.DataFrame, max_rows: int | None = None) -> str:
    if dataframe.empty:
        return "_Sin datos._"
    display = dataframe.copy()
    if max_rows is not None and len(display) > max_rows:
        display = display.head(max_rows).copy()
    return display.to_markdown(index=False)


def make_group_splitter(method: str, n_splits: int, shuffle: bool, random_state: int | None):
    method = method.lower()
    if method == "stratified_group_kfold":
        if StratifiedGroupKFold is None:
            raise ImportError("La version instalada de scikit-learn no tiene StratifiedGroupKFold.")
        return StratifiedGroupKFold(n_splits=n_splits, shuffle=shuffle, random_state=random_state)
    if method == "group_kfold":
        if shuffle:
            LOGGER.warning("GroupKFold no usa shuffle en versiones antiguas de scikit-learn; se ignorara shuffle.")
        return GroupKFold(n_splits=n_splits)
    raise ValueError(f"Metodo de particion no soportado: {method}")


def class_distribution_error(y_all: np.ndarray, y_holdout: np.ndarray) -> float:
    classes = sorted(set(y_all))
    all_counts = pd.Series(y_all).value_counts(normalize=True)
    hold_counts = pd.Series(y_holdout).value_counts(normalize=True)
    error = 0.0
    for class_id in classes:
        error += abs(float(all_counts.get(class_id, 0.0)) - float(hold_counts.get(class_id, 0.0)))
    return error


def build_quadrant_class_profile(dataframe: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    group_field = str(config["fields"]["group"])
    target = str(config["fields"]["target"])
    label_field = config.get("fields", {}).get("target_label")
    class_labels = build_target_label_mapping(dataframe, config)

    counts = (
        dataframe.groupby([group_field, target], dropna=False)
        .size()
        .reset_index(name="n_points")
    )
    total = dataframe.groupby(group_field).size().rename("n_points_quadrant").reset_index()
    counts = counts.merge(total, on=group_field, how="left", validate="many_to_one")
    counts["pct_points_quadrant"] = counts["n_points"] / counts["n_points_quadrant"]
    counts = add_target_labels(counts, target, str(label_field) if label_field else None, class_labels)
    return counts.sort_values([group_field, target]).reset_index(drop=True)


def candidate_holdout_metrics(
    dataframe: pd.DataFrame,
    mask: pd.Series,
    config: dict[str, Any],
    candidate_id: str,
    class_labels: dict[str, str],
    seed: int | None = None,
    fold_id: int | None = None,
) -> dict[str, Any]:
    group_field = str(config["fields"]["group"])
    target = str(config["fields"]["target"])
    iv_cfg = config.get("independent_validation", {}) or {}

    y_all = dataframe[target].to_numpy()
    y_ind = dataframe.loc[mask, target].to_numpy()
    y_dev = dataframe.loc[~mask, target].to_numpy()

    all_classes = set(y_all)
    ind_classes = set(y_ind)
    dev_classes = set(y_dev)
    missing_ind = sorted(all_classes - ind_classes)
    missing_dev = sorted(ind_classes - dev_classes)

    n_rows = int(mask.sum())
    n_total = int(len(dataframe))
    pct_rows = float(n_rows / n_total) if n_total else np.nan
    all_groups = set(dataframe[group_field])
    ind_groups = set(dataframe.loc[mask, group_field])
    n_groups = int(len(ind_groups))
    pct_groups = float(n_groups / len(all_groups)) if all_groups else np.nan

    target_fraction = float(iv_cfg.get("holdout_fraction", 1.0 / float(iv_cfg.get("n_candidate_splits", 5))))
    distribution_error = class_distribution_error(y_all, y_ind) if n_rows else np.inf
    row_fraction_error = abs(pct_rows - target_fraction) if np.isfinite(pct_rows) else np.inf
    group_fraction_error = abs(pct_groups - target_fraction) if np.isfinite(pct_groups) else np.inf
    selection_score = distribution_error + row_fraction_error

    return {
        "candidate_id": candidate_id,
        "seed": seed,
        "candidate_fold": fold_id,
        "n_rows": n_rows,
        "pct_rows": pct_rows,
        "n_groups": n_groups,
        "pct_groups": pct_groups,
        "n_classes": int(len(ind_classes)),
        "n_development_classes": int(len(dev_classes)),
        "n_missing_independent_classes": int(len(missing_ind)),
        "n_missing_development_classes": int(len(missing_dev)),
        "missing_independent_classes": "|".join(missing_ind),
        "missing_independent_class_labels": joined_class_labels(missing_ind, class_labels),
        "missing_development_classes": "|".join(missing_dev),
        "missing_development_class_labels": joined_class_labels(missing_dev, class_labels),
        "class_distribution_error": float(distribution_error),
        "row_fraction_error": float(row_fraction_error),
        "group_fraction_error": float(group_fraction_error),
        "selection_score": float(selection_score),
        "valid_for_modeling": bool(n_rows > 0 and len(y_dev) > 0 and not missing_dev),
        "holdout_group_ids": "|".join(sorted(ind_groups)),
        "selected": False,
    }


def select_independent_holdout(
    dataframe: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.Series, pd.DataFrame]:
    group_field = str(config["fields"]["group"])
    target = str(config["fields"]["target"])
    iv_cfg = config.get("independent_validation", {}) or {}

    if not bool(iv_cfg.get("enabled", True)):
        LOGGER.warning("independent_validation.enabled=false; no habra validacion independiente.")
        return pd.Series(False, index=dataframe.index), pd.DataFrame()

    class_labels = build_target_label_mapping(dataframe, config)
    explicit_groups = [str(value).strip() for value in as_list(iv_cfg.get("explicit_group_ids")) if str(value).strip()]
    if explicit_groups:
        mask = pd.Series(dataframe[group_field].isin(explicit_groups), index=dataframe.index)
        if not mask.any():
            raise ValueError("independent_validation.explicit_group_ids no selecciono ningun cuadrante.")
        metrics = candidate_holdout_metrics(
            dataframe,
            mask,
            config,
            candidate_id="explicit",
            class_labels=class_labels,
        )
        metrics["selected"] = True
        LOGGER.info("Validacion independiente por cuadrantes explicitos: %s", explicit_groups)
        return mask, pd.DataFrame([metrics])

    method = str(iv_cfg.get("method", "stratified_group_holdout")).lower()
    if method not in ["stratified_group_holdout", "group_holdout"]:
        raise ValueError(f"independent_validation.method no soportado: {method}")

    splitter_method = "stratified_group_kfold" if method == "stratified_group_holdout" else "group_kfold"
    n_candidate_splits = int(iv_cfg.get("n_candidate_splits", 5))
    selected_candidate_id = iv_cfg.get("selected_candidate_id")
    random_state = int(iv_cfg.get("random_state", 42))
    shuffle = bool(iv_cfg.get("shuffle", True))

    y = dataframe[target].to_numpy()
    groups = dataframe[group_field].to_numpy()
    x_dummy = np.zeros((len(dataframe), 1), dtype=np.int8)
    splitter = make_group_splitter(splitter_method, n_candidate_splits, shuffle=shuffle, random_state=random_state)

    candidates: list[dict[str, Any]] = []
    masks_by_candidate: dict[str, pd.Series] = {}
    for fold_id, (_, holdout_idx) in enumerate(splitter.split(x_dummy, y, groups=groups)):
        holdout_groups = set(groups[holdout_idx])
        mask = pd.Series(dataframe[group_field].isin(holdout_groups), index=dataframe.index)
        candidate_id = f"seed_{random_state}_fold_{fold_id}"
        metrics = candidate_holdout_metrics(
            dataframe,
            mask,
            config,
            candidate_id=candidate_id,
            class_labels=class_labels,
            seed=random_state,
            fold_id=fold_id,
        )
        candidates.append(metrics)
        masks_by_candidate[candidate_id] = mask

    candidates_df = pd.DataFrame(candidates)
    if candidates_df.empty:
        raise ValueError("No se pudieron generar candidatos de validacion independiente.")

    if selected_candidate_id is None:
        eligible = candidates_df[candidates_df["valid_for_modeling"].astype(bool)].copy()
        if eligible.empty:
            raise ValueError("Ningun candidato de holdout es valido para modelado.")
        selected_candidate_id = str(
            eligible.sort_values(
                ["selection_score", "class_distribution_error", "row_fraction_error", "candidate_id"],
                ascending=[True, True, True, True],
            ).iloc[0]["candidate_id"]
        )
    else:
        selected_candidate_id = str(selected_candidate_id)
        if selected_candidate_id not in masks_by_candidate:
            raise ValueError(
                f"selected_candidate_id='{selected_candidate_id}' no existe entre los candidatos generados."
            )

    candidates_df.loc[candidates_df["candidate_id"].astype(str) == selected_candidate_id, "selected"] = True
    mask = masks_by_candidate[selected_candidate_id]
    LOGGER.info(
        "Holdout independiente seleccionado: %s | filas=%s | cuadrantes=%s",
        selected_candidate_id,
        f"{int(mask.sum()):,}",
        f"{dataframe.loc[mask, group_field].nunique():,}",
    )
    return mask, candidates_df


def build_cv_splits(development: pd.DataFrame, config: dict[str, Any]) -> list[tuple[np.ndarray, np.ndarray]]:
    group_field = str(config["fields"]["group"])
    target = str(config["fields"]["target"])
    cv_cfg = config.get("inner_cv", {}) or {}
    method = str(cv_cfg.get("method", "stratified_group_kfold"))
    n_splits = int(cv_cfg.get("n_splits", 3))
    shuffle = bool(cv_cfg.get("shuffle", True))
    random_state = cv_cfg.get("random_state", 42)
    random_state = int(random_state) if random_state is not None else None

    n_groups = development[group_field].nunique()
    if n_groups < n_splits:
        raise ValueError(f"No hay suficientes grupos para CV: grupos={n_groups}, n_splits={n_splits}")

    splitter = make_group_splitter(method, n_splits, shuffle=shuffle, random_state=random_state)
    y = development[target].to_numpy()
    groups = development[group_field].to_numpy()
    x_dummy = np.zeros((len(development), 1), dtype=np.int8)
    splits = list(splitter.split(x_dummy, y, groups=groups))

    for fold_id, (train_idx, validation_idx) in enumerate(splits, start=1):
        train_groups = set(groups[train_idx])
        validation_groups = set(groups[validation_idx])
        overlap = train_groups & validation_groups
        if overlap and bool(config.get("validation", {}).get("fail_on_group_leakage", True)):
            raise ValueError(f"Leakage espacial en fold {fold_id}: grupos compartidos {sorted(overlap)[:10]}")

        train_classes = set(y[train_idx])
        validation_classes = set(y[validation_idx])
        unseen_validation_classes = sorted(validation_classes - train_classes)
        if unseen_validation_classes and bool(config.get("validation", {}).get("fail_on_unseen_validation_classes", True)):
            raise ValueError(
                f"Fold {fold_id} invalido: contiene clases en validacion ausentes "
                f"del entrenamiento: {unseen_validation_classes}."
            )

    LOGGER.info("CV interna SVM preparada: method=%s | folds=%s | grupos_desarrollo=%s", method, n_splits, n_groups)
    return splits


def build_split_outputs(
    dataframe: pd.DataFrame,
    independent_mask: pd.Series,
    cv_splits: list[tuple[np.ndarray, np.ndarray]],
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    key = str(config["fields"]["key"])
    group_field = str(config["fields"]["group"])
    target = str(config["fields"]["target"])
    label_field = config.get("fields", {}).get("target_label")
    class_labels = build_target_label_mapping(dataframe, config)

    independent = dataframe[independent_mask].copy().reset_index(drop=True)
    development = dataframe[~independent_mask].copy().reset_index(drop=True)

    dev_groups = set(development[group_field])
    ind_groups = set(independent[group_field])
    overlap = dev_groups & ind_groups
    if overlap and bool(config.get("validation", {}).get("fail_on_group_leakage", True)):
        raise ValueError(f"Leakage entre desarrollo y validacion independiente: {sorted(overlap)[:10]}")

    unseen = sorted(set(independent[target]) - set(development[target]))
    if unseen and bool(config.get("validation", {}).get("fail_on_unseen_validation_classes", True)):
        raise ValueError(f"Validacion independiente contiene clases ausentes del desarrollo: {unseen}")

    base_cols = [key, group_field, target]
    if label_field and str(label_field) in dataframe.columns:
        base_cols.append(str(label_field))

    assignments = dataframe[base_cols].copy()
    assignments["split_role"] = "development_cv"
    assignments.loc[independent_mask, "split_role"] = "independent_validation"
    assignments["cv_validation_fold_id"] = pd.NA

    dev_key_by_pos = development[key].reset_index(drop=True)
    cv_assignment_rows: list[pd.DataFrame] = []
    for fold_id, (train_idx, validation_idx) in enumerate(cv_splits, start=1):
        train_keys = set(dev_key_by_pos.iloc[train_idx])
        validation_keys = set(dev_key_by_pos.iloc[validation_idx])
        if train_keys & validation_keys:
            raise ValueError(f"Leakage interno en fold {fold_id}: un punto aparece en train y validation.")

        assignments.loc[assignments[key].isin(validation_keys), "cv_validation_fold_id"] = fold_id

        train_part = development.iloc[train_idx][base_cols].copy()
        train_part["fold_id"] = fold_id
        train_part["cv_role"] = "cv_train"
        validation_part = development.iloc[validation_idx][base_cols].copy()
        validation_part["fold_id"] = fold_id
        validation_part["cv_role"] = "cv_validation"
        cv_assignment_rows.extend([train_part, validation_part])

    cv_assignments = pd.concat(cv_assignment_rows, ignore_index=True) if cv_assignment_rows else pd.DataFrame()
    cv_assignments = add_target_labels(cv_assignments, target, str(label_field) if label_field else None, class_labels)
    assignments = add_target_labels(assignments, target, str(label_field) if label_field else None, class_labels)

    group_assignments = (
        assignments.groupby([group_field, "split_role"], dropna=False)
        .agg(
            n_points=(key, "size"),
            n_classes=(target, "nunique"),
            cv_validation_fold_ids=("cv_validation_fold_id", lambda values: "|".join(sorted({str(v) for v in values.dropna()}))),
        )
        .reset_index()
        .sort_values(["split_role", group_field])
    )

    split_summary = (
        assignments.groupby("split_role", dropna=False)
        .agg(
            n_points=(key, "size"),
            n_groups=(group_field, "nunique"),
            n_classes=(target, "nunique"),
        )
        .reset_index()
        .sort_values("split_role")
    )
    split_summary["pct_points"] = split_summary["n_points"] / len(assignments)

    split_class_balance = (
        assignments.groupby(["split_role", target], dropna=False)
        .agg(n_points=(key, "size"), n_groups=(group_field, "nunique"))
        .reset_index()
        .sort_values(["split_role", target])
    )
    split_class_balance = add_target_labels(split_class_balance, target, str(label_field) if label_field else None, class_labels)

    fold_balance_rows: list[pd.DataFrame] = []
    fold_ids = sorted(cv_assignments["fold_id"].dropna().unique()) if not cv_assignments.empty else []
    for fold_id in fold_ids:
        subset = cv_assignments[cv_assignments["fold_id"] == fold_id]
        grouped = (
            subset.groupby(["fold_id", "cv_role", target], dropna=False)
            .agg(n_points=(key, "size"), n_groups=(group_field, "nunique"))
            .reset_index()
            .sort_values(["fold_id", "cv_role", target])
        )
        fold_balance_rows.append(grouped)
    cv_fold_class_balance = pd.concat(fold_balance_rows, ignore_index=True) if fold_balance_rows else pd.DataFrame()
    cv_fold_class_balance = add_target_labels(
        cv_fold_class_balance,
        target,
        str(label_field) if label_field else None,
        class_labels,
    )

    return assignments, cv_assignments, group_assignments, split_summary, split_class_balance, cv_fold_class_balance


def write_outputs(
    dataframe: pd.DataFrame,
    development: pd.DataFrame,
    independent: pd.DataFrame,
    assignments: pd.DataFrame,
    cv_assignments: pd.DataFrame,
    group_assignments: pd.DataFrame,
    independent_candidates: pd.DataFrame,
    quadrant_profile: pd.DataFrame,
    split_summary: pd.DataFrame,
    split_class_balance: pd.DataFrame,
    cv_fold_class_balance: pd.DataFrame,
    output_dir: Path,
    config: dict[str, Any],
) -> None:
    outputs = config.get("outputs", {}) or {}

    if bool(outputs.get("write_partitioned_parquet", True)):
        development.to_parquet(output_dir / outputs.get("development_dataset_parquet", "tables/svm_development_dataset.parquet"), index=False)
        independent.to_parquet(
            output_dir / outputs.get("independent_dataset_parquet", "tables/svm_independent_validation_dataset.parquet"),
            index=False,
        )
    if bool(outputs.get("write_partitioned_csv", False)):
        development.to_csv(
            output_dir / outputs.get("development_dataset_csv", "tables/svm_development_dataset.csv"),
            index=False,
            encoding="utf-8-sig",
        )
        independent.to_csv(
            output_dir / outputs.get("independent_dataset_csv", "tables/svm_independent_validation_dataset.csv"),
            index=False,
            encoding="utf-8-sig",
        )

    assignments.to_csv(output_dir / outputs.get("split_assignments_csv", "tables/svm_split_assignments.csv"), index=False, encoding="utf-8-sig")
    cv_assignments.to_csv(
        output_dir / outputs.get("cv_fold_assignments_csv", "tables/svm_cv_fold_assignments.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    group_assignments.to_csv(
        output_dir / outputs.get("group_split_assignments_csv", "tables/svm_group_split_assignments.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    if not independent_candidates.empty:
        independent_candidates.to_csv(
            output_dir / outputs.get("independent_candidates_csv", "tables/svm_independent_validation_candidates.csv"),
            index=False,
            encoding="utf-8-sig",
        )
        independent_candidates[independent_candidates["selected"].astype(bool)].to_csv(
            output_dir / outputs.get("selected_independent_quadrants_csv", "tables/svm_selected_independent_quadrants.csv"),
            index=False,
            encoding="utf-8-sig",
        )
    quadrant_profile.to_csv(
        output_dir / outputs.get("quadrant_class_profile_csv", "tables/svm_quadrant_class_profile.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    split_summary.to_csv(output_dir / outputs.get("split_summary_csv", "tables/svm_split_summary.csv"), index=False, encoding="utf-8-sig")
    split_class_balance.to_csv(
        output_dir / outputs.get("split_class_balance_csv", "tables/svm_split_class_balance.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    cv_fold_class_balance.to_csv(
        output_dir / outputs.get("cv_fold_class_balance_csv", "tables/svm_cv_fold_class_balance.csv"),
        index=False,
        encoding="utf-8-sig",
    )

    target = str(config["fields"]["target"])
    label_field = config.get("fields", {}).get("target_label")
    class_labels = build_target_label_mapping(dataframe, config)
    class_catalog = pd.DataFrame(
        [{target: class_id, str(label_field or "class_label"): label} for class_id, label in sorted(class_labels.items())]
    )
    class_catalog.to_csv(output_dir / outputs.get("class_catalog_csv", "tables/svm_class_catalog.csv"), index=False, encoding="utf-8-sig")


def build_report(
    input_path: Path,
    input_kind: str,
    feature_count: int,
    dataframe: pd.DataFrame,
    development: pd.DataFrame,
    independent: pd.DataFrame,
    independent_candidates: pd.DataFrame,
    split_summary: pd.DataFrame,
    cv_fold_class_balance: pd.DataFrame,
    output_dir: Path,
    config: dict[str, Any],
) -> None:
    outputs = config.get("outputs", {}) or {}
    report_path = output_dir / outputs.get("report_md", "reports/a4_8_2_create_svm_spatial_splits_report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    target = str(config["fields"]["target"])
    group_field = str(config["fields"]["group"])
    selected_candidate = "_No aplica_"
    selected_groups = "_No aplica_"
    if not independent_candidates.empty:
        selected = independent_candidates[independent_candidates["selected"].astype(bool)]
        if not selected.empty:
            selected_candidate = f"`{selected.iloc[0]['candidate_id']}`"
            selected_groups = f"`{selected.iloc[0]['holdout_group_ids']}`"

    lines = [
        "# Actividad 4.8.2 - Particiones espaciales para SVM",
        "",
        f"**Fecha:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Insumo",
        "",
        f"- Dataset leido: `{input_path.relative_to(REPO_ROOT)}`",
        f"- Formato usado: `{input_kind}`",
        f"- Predictores SVM registrados: **{feature_count:,}**",
        "",
        "## Diseno de validacion",
        "",
        f"- Target: `{target}`",
        f"- Unidad espacial de particion: `{group_field}`",
        "- La validacion independiente se separa antes del entrenamiento y no participa en ajuste de hiperparametros.",
        "- La validacion cruzada interna usa cuadrantes completos dentro del conjunto de desarrollo.",
        "- Una clase puede no aparecer en todos los folds, pero cualquier clase observada en validacion debe existir en el entrenamiento correspondiente.",
        "",
        "## Particiones",
        "",
        dataframe_to_markdown(split_summary),
        "",
        "## Holdout independiente seleccionado",
        "",
        f"- Candidato seleccionado: {selected_candidate}",
        f"- Cuadrantes holdout: {selected_groups}",
        f"- Filas desarrollo: **{len(development):,}**",
        f"- Filas validacion independiente: **{len(independent):,}**",
        f"- Cuadrantes desarrollo: **{development[group_field].nunique():,}**",
        f"- Cuadrantes validacion independiente: **{independent[group_field].nunique():,}**",
        f"- Clases totales: **{dataframe[target].nunique():,}**",
        "",
        "## Balance por fold CV",
        "",
        dataframe_to_markdown(cv_fold_class_balance, max_rows=40),
        "",
        "## Nota metodologica",
        "",
        "Esta etapa solo congela el diseno de particiones. El escalamiento, la imputacion "
        "y el entrenamiento SVM deben ocurrir despues, usando estos cortes para evitar "
        "fuga espacial entre entrenamiento, validacion interna y validacion independiente.",
        "",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Reporte de particiones SVM escrito: %s", report_path)


def main() -> None:
    config_path = resolve_path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG
    config = select_config_section(read_yaml(config_path), CONFIG_SECTION)
    output_dir = resolve_path(config["paths"]["output_dir"])
    configure_logger(output_dir)
    LOGGER.info("YAML de configuracion: %s | seccion=%s", config_path, CONFIG_SECTION)

    dataframe, input_path, input_kind = read_dataset(config)
    validate_inputs(dataframe, config)
    dataframe = normalize_split_fields(dataframe, config)

    feature_columns = read_text_list(resolve_path(config["paths"]["selected_features_txt"]), "selected_features_txt")
    missing_features = sorted(set(feature_columns) - set(dataframe.columns))
    if missing_features:
        raise ValueError(f"Predictores SVM ausentes en el dataset preparado: {missing_features}")

    quadrant_profile = build_quadrant_class_profile(dataframe, config)
    independent_mask, independent_candidates = select_independent_holdout(dataframe, config)
    independent = dataframe[independent_mask].copy().reset_index(drop=True)
    development = dataframe[~independent_mask].copy().reset_index(drop=True)
    if independent.empty and bool(config.get("independent_validation", {}).get("enabled", True)):
        raise ValueError("La validacion independiente quedo vacia.")
    if development.empty:
        raise ValueError("El conjunto de desarrollo quedo vacio.")

    cv_splits = build_cv_splits(development, config)
    (
        assignments,
        cv_assignments,
        group_assignments,
        split_summary,
        split_class_balance,
        cv_fold_class_balance,
    ) = build_split_outputs(dataframe, independent_mask, cv_splits, config)

    write_outputs(
        dataframe=dataframe,
        development=development,
        independent=independent,
        assignments=assignments,
        cv_assignments=cv_assignments,
        group_assignments=group_assignments,
        independent_candidates=independent_candidates,
        quadrant_profile=quadrant_profile,
        split_summary=split_summary,
        split_class_balance=split_class_balance,
        cv_fold_class_balance=cv_fold_class_balance,
        output_dir=output_dir,
        config=config,
    )
    build_report(
        input_path=input_path,
        input_kind=input_kind,
        feature_count=len(feature_columns),
        dataframe=dataframe,
        development=development,
        independent=independent,
        independent_candidates=independent_candidates,
        split_summary=split_summary,
        cv_fold_class_balance=cv_fold_class_balance,
        output_dir=output_dir,
        config=config,
    )
    LOGGER.info(
        "A4.8.2 finalizado: filas=%s | desarrollo=%s | independiente=%s | folds=%s",
        f"{len(dataframe):,}",
        f"{len(development):,}",
        f"{len(independent):,}",
        f"{len(cv_splits):,}",
    )


if __name__ == "__main__":
    main()
