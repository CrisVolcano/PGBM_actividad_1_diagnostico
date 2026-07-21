#!/usr/bin/env python3
"""Prepara datos tabulares y particiones espaciales congeladas para la DNN.

La etapa no entrena modelos y no ajusta imputadores ni escaladores. Reutiliza las
asignaciones producidas por el RF para que ambos algoritmos se comparen sobre las
mismas filas, los mismos folds y el mismo holdout independiente.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from sklearn.preprocessing import LabelEncoder


LOGGER = logging.getLogger("a4_8_prepare_dnn")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_8_prepare_dnn_spatial_data.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    path = resolve_path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe el YAML de configuración: {path}")
    with path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError(f"El YAML no contiene un diccionario: {path}")
    return config


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.expanduser().resolve()
    return (REPO_ROOT / path).expanduser().resolve()


def configure_logger(output_dir: Path) -> None:
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    handlers.append(
        logging.FileHandler(output_dir / "logs" / "prepare_dnn_data.log", encoding="utf-8")
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def read_modeling_dataset(config: dict[str, Any]) -> tuple[pd.DataFrame, Path]:
    paths = config["paths"]
    parquet_path = resolve_path(paths["modeling_dataset_parquet"])
    csv_path = resolve_path(paths["modeling_dataset_csv"])
    if parquet_path.exists():
        try:
            LOGGER.info("Leyendo dataset Parquet: %s", parquet_path)
            return pd.read_parquet(parquet_path), parquet_path
        except (ImportError, ModuleNotFoundError, ValueError) as exc:
            LOGGER.warning("No se pudo leer Parquet (%s); se intentará CSV.", exc)
    if csv_path.exists():
        LOGGER.info("Leyendo dataset CSV: %s", csv_path)
        return pd.read_csv(csv_path, low_memory=False), csv_path
    raise FileNotFoundError(
        "No se encontró el dataset de modelado. "
        f"Parquet={parquet_path}; CSV={csv_path}"
    )


def read_feature_columns(config: dict[str, Any], dataframe: pd.DataFrame) -> list[str]:
    feature_path = resolve_path(config["paths"]["feature_columns_txt"])
    if not feature_path.exists():
        raise FileNotFoundError(
            "La preparación DNN exige la misma lista de predictores del RF: "
            f"{feature_path}"
        )
    features = [
        value.strip()
        for value in feature_path.read_text(encoding="utf-8").splitlines()
        if value.strip()
    ]
    if not features:
        raise ValueError("La lista de predictores está vacía.")
    if len(features) != len(set(features)):
        raise ValueError("La lista de predictores contiene columnas duplicadas.")
    missing = [feature for feature in features if feature not in dataframe.columns]
    if missing:
        raise ValueError(f"Predictores ausentes del dataset: {missing[:20]}")
    forbidden = set(config.get("fields", {}).get("non_predictor_fields", []))
    invalid = [feature for feature in features if feature in forbidden]
    if invalid:
        raise ValueError(f"Campos no predictores presentes en X: {invalid}")
    return features


def normalize_identifier(series: pd.Series, name: str) -> pd.Series:
    if series.isna().any():
        raise ValueError(f"El campo {name} contiene valores nulos.")
    return series.astype(str).str.strip()


def check_unique(series: pd.Series, name: str) -> None:
    duplicated = series[series.duplicated(keep=False)]
    if not duplicated.empty:
        examples = duplicated.astype(str).drop_duplicates().head(10).tolist()
        raise ValueError(f"{name} no es único. Ejemplos duplicados: {examples}")


def load_and_join_assignments(
    dataframe: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    key = config["fields"]["key"]
    group = config["fields"]["group"]
    target = config["fields"]["target"]
    label = config["fields"].get("target_label")
    assignments_path = resolve_path(config["paths"]["rf_split_assignments_csv"])
    if not assignments_path.exists():
        raise FileNotFoundError(
            "No existe split_assignments.csv del RF. Debe ejecutarse primero el RF: "
            f"{assignments_path}"
        )

    assignments = pd.read_csv(assignments_path, low_memory=False)
    required_assignment_columns = {
        key,
        group,
        "split_role",
        "cv_validation_fold_id",
    }
    missing = required_assignment_columns - set(assignments.columns)
    if missing:
        raise ValueError(f"Faltan columnas en split_assignments.csv: {sorted(missing)}")
    required_data_columns = {key, group, target}
    if label:
        required_data_columns.add(str(label))
    missing = required_data_columns - set(dataframe.columns)
    if missing:
        raise ValueError(f"Faltan columnas en el dataset: {sorted(missing)}")

    data = dataframe.copy()
    data[key] = normalize_identifier(data[key], key)
    assignments[key] = normalize_identifier(assignments[key], key)
    check_unique(data[key], f"dataset.{key}")
    check_unique(assignments[key], f"split_assignments.{key}")

    assignments_for_join = assignments.copy()
    assignments_for_join = assignments_for_join.rename(
        columns={group: "__assignment_group", target: "__assignment_target"}
    )
    assignment_columns = [
        key,
        "__assignment_group",
        "__assignment_target",
        "split_role",
        "cv_validation_fold_id",
        "border_excluded",
        "distance_to_quadrant_border_m",
    ]
    assignment_columns = [
        column for column in assignment_columns if column in assignments_for_join.columns
    ]
    joined = assignments_for_join[assignment_columns].merge(
        data,
        on=key,
        how="left",
        validate="one_to_one",
        indicator=True,
        sort=False,
    )
    missing_keys = joined.loc[joined["_merge"] != "both", key].head(10).tolist()
    if missing_keys:
        raise ValueError(
            "Hay claves de split_assignments ausentes del dataset. "
            f"Ejemplos: {missing_keys}"
        )
    joined = joined.drop(columns="_merge")

    if "__assignment_group" in joined.columns:
        assignment_group = normalize_identifier(joined["__assignment_group"], group)
        dataset_group = normalize_identifier(joined[group], group)
        mismatch = ~assignment_group.eq(dataset_group)
        if mismatch.any():
            examples = joined.loc[mismatch, key].head(10).tolist()
            raise ValueError(
                "El cuadrante del dataset no coincide con split_assignments. "
                f"Claves: {examples}"
            )
        joined = joined.drop(columns="__assignment_group")
    if "__assignment_target" in joined.columns:
        assignment_target = joined["__assignment_target"].astype(str).str.strip()
        dataset_target = joined[target].astype(str).str.strip()
        mismatch = ~assignment_target.eq(dataset_target)
        if mismatch.any():
            examples = joined.loc[mismatch, key].head(10).tolist()
            raise ValueError(
                "El target del dataset no coincide con split_assignments. "
                f"Claves: {examples}"
            )
        joined = joined.drop(columns="__assignment_target")

    allowed_roles = {"development_cv", "independent_validation", "excluded_border"}
    unknown_roles = set(joined["split_role"].dropna().astype(str)) - allowed_roles
    if unknown_roles:
        raise ValueError(f"Roles no reconocidos en split_assignments: {sorted(unknown_roles)}")
    return joined, assignments, assignments_path


def numeric_feature_matrix(dataframe: pd.DataFrame, features: list[str]) -> np.ndarray:
    numeric = dataframe[features].apply(pd.to_numeric, errors="coerce")
    numeric = numeric.replace([np.inf, -np.inf], np.nan)
    all_missing = [feature for feature in features if numeric[feature].isna().all()]
    if all_missing:
        raise ValueError(f"Predictores completamente nulos: {all_missing}")
    return numeric.to_numpy(dtype=np.float32, copy=True)


def save_array(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, array, allow_pickle=False)


def build_class_catalog(
    modelable: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[np.ndarray, LabelEncoder, list[dict[str, Any]]]:
    target = config["fields"]["target"]
    label_field = config["fields"].get("target_label")
    raw_target = modelable[target].astype(str).str.strip()
    if raw_target.eq("").any() or modelable[target].isna().any():
        raise ValueError("El target contiene valores nulos o vacíos en filas modelables.")
    encoder = LabelEncoder()
    y = encoder.fit_transform(raw_target).astype(np.int64, copy=False)

    labels_by_class: dict[str, str] = {}
    if label_field and label_field in modelable.columns:
        pairs = modelable[[target, label_field]].dropna().copy()
        pairs[target] = pairs[target].astype(str).str.strip()
        pairs[label_field] = pairs[label_field].astype(str).str.strip()
        conflicting = pairs.groupby(target)[label_field].nunique()
        conflicting = conflicting[conflicting > 1]
        if not conflicting.empty:
            raise ValueError(
                "Una clase posee más de un label: "
                f"{conflicting.index.astype(str).tolist()}"
            )
        labels_by_class = pairs.drop_duplicates(target).set_index(target)[label_field].to_dict()

    catalog = [
        {
            "encoded_class": int(index),
            "original_class": str(original),
            "class_label": labels_by_class.get(str(original), str(original)),
        }
        for index, original in enumerate(encoder.classes_)
    ]
    return y, encoder, catalog


def build_spatial_indices(
    modelable: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[dict[str, np.ndarray], list[int]]:
    group = config["fields"]["group"]
    roles = modelable["split_role"].astype(str)
    development_idx = np.flatnonzero(roles.eq("development_cv").to_numpy()).astype(np.int64)
    independent_idx = np.flatnonzero(roles.eq("independent_validation").to_numpy()).astype(np.int64)
    if development_idx.size == 0 or independent_idx.size == 0:
        raise ValueError("Desarrollo o validación independiente quedaron vacíos.")

    dev_groups = set(modelable.iloc[development_idx][group].astype(str))
    ind_groups = set(modelable.iloc[independent_idx][group].astype(str))
    overlap = dev_groups & ind_groups
    if overlap:
        raise ValueError(
            "Leakage entre desarrollo y validación independiente. "
            f"Cuadrantes: {sorted(overlap)[:10]}"
        )

    fold_values = pd.to_numeric(
        modelable.iloc[development_idx]["cv_validation_fold_id"], errors="coerce"
    )
    if fold_values.isna().any():
        raise ValueError("Hay filas de desarrollo sin cv_validation_fold_id.")
    if not np.allclose(fold_values.to_numpy(), np.round(fold_values.to_numpy())):
        raise ValueError("cv_validation_fold_id contiene valores no enteros.")
    fold_ids = sorted(fold_values.astype(int).unique().tolist())
    expected = config.get("preparation", {}).get("expected_cv_folds")
    if expected is not None and len(fold_ids) != int(expected):
        raise ValueError(
            f"Se esperaban {expected} folds, pero split_assignments contiene {len(fold_ids)}."
        )

    arrays: dict[str, np.ndarray] = {
        "development_indices": development_idx,
        "independent_indices": independent_idx,
    }
    dev_fold_ids = fold_values.astype(int).to_numpy()
    for fold_id in fold_ids:
        val_idx = development_idx[dev_fold_ids == fold_id]
        train_idx = development_idx[dev_fold_ids != fold_id]
        train_groups = set(modelable.iloc[train_idx][group].astype(str))
        val_groups = set(modelable.iloc[val_idx][group].astype(str))
        overlap = train_groups & val_groups
        if overlap:
            raise ValueError(
                f"Leakage espacial en fold {fold_id}: {sorted(overlap)[:10]}"
            )
        if train_idx.size == 0 or val_idx.size == 0:
            raise ValueError(f"Fold {fold_id} vacío en entrenamiento o validación.")
        arrays[f"fold_{fold_id}_train"] = train_idx.astype(np.int64, copy=False)
        arrays[f"fold_{fold_id}_validation"] = val_idx.astype(np.int64, copy=False)
    return arrays, fold_ids


def write_report(
    output_dir: Path,
    modelable: pd.DataFrame,
    features: list[str],
    catalog: list[dict[str, Any]],
    fold_ids: list[int],
    config: dict[str, Any],
) -> None:
    group = config["fields"]["group"]
    roles = modelable["split_role"].astype(str)
    lines = [
        "# A4.8 — Preparación de datos para DNN PyTorch",
        "",
        "Los datos y las particiones se reutilizaron desde `split_assignments.csv` del RF.",
        "No se ajustaron imputadores, escaladores ni modelos en esta etapa.",
        "",
        "| componente | valor |",
        "|:--|--:|",
        f"| filas modelables | {len(modelable):,} |",
        f"| predictores | {len(features):,} |",
        f"| clases | {len(catalog):,} |",
        f"| folds | {len(fold_ids):,} |",
        f"| filas desarrollo | {int(roles.eq('development_cv').sum()):,} |",
        f"| cuadrantes desarrollo | {modelable.loc[roles.eq('development_cv'), group].nunique():,} |",
        f"| filas validación independiente | {int(roles.eq('independent_validation').sum()):,} |",
        f"| cuadrantes validación independiente | {modelable.loc[roles.eq('independent_validation'), group].nunique():,} |",
        "",
        "## Principio de preprocesamiento",
        "",
        "La imputación y estandarización deberán ajustarse dentro de cada fold usando solamente su entrenamiento.",
    ]
    report_path = output_dir / "reports" / "a4_8_prepare_dnn_spatial_data_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    config_path = args.config.resolve()
    config = read_yaml(config_path)
    output_dir = resolve_path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_logger(output_dir)

    dataframe, dataset_path = read_modeling_dataset(config)
    features = read_feature_columns(config, dataframe)
    joined, assignments, assignments_path = load_and_join_assignments(dataframe, config)
    modelable = joined[
        joined["split_role"].astype(str).isin(["development_cv", "independent_validation"])
    ].copy()
    modelable = modelable.reset_index(drop=True)
    if modelable.empty:
        raise ValueError("No hay filas modelables en split_assignments.csv.")

    target = config["fields"]["target"]
    development_classes = set(
        modelable.loc[modelable["split_role"].eq("development_cv"), target]
        .astype(str)
        .str.strip()
    )
    independent_classes = set(
        modelable.loc[modelable["split_role"].eq("independent_validation"), target]
        .astype(str)
        .str.strip()
    )
    unseen = independent_classes - development_classes
    if unseen:
        raise ValueError(
            "La validación independiente contiene clases ausentes del desarrollo: "
            f"{sorted(unseen)}"
        )

    X = numeric_feature_matrix(modelable, features)
    y, _encoder, catalog = build_class_catalog(modelable, config)
    index_arrays, fold_ids = build_spatial_indices(modelable, config)

    arrays_dir = output_dir / "arrays"
    tables_dir = output_dir / "tables"
    metadata_dir = output_dir / "metadata"
    arrays_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    key = config["fields"]["key"]
    group = config["fields"]["group"]
    label = config["fields"].get("target_label")
    save_array(arrays_dir / "X_raw_float32.npy", X)
    save_array(arrays_dir / "y_encoded.npy", y)
    save_array(arrays_dir / "groups.npy", modelable[group].astype(str).to_numpy(dtype=str))
    save_array(arrays_dir / "row_keys.npy", modelable[key].astype(str).to_numpy(dtype=str))
    np.savez_compressed(arrays_dir / "spatial_indices.npz", **index_arrays)

    sample_columns = [key, group, target]
    if label and label in modelable.columns:
        sample_columns.append(str(label))
    sample_columns += ["split_role", "cv_validation_fold_id"]
    sample_index = modelable[sample_columns].copy()
    sample_index.insert(0, "prepared_row_index", np.arange(len(sample_index), dtype=np.int64))
    sample_index.insert(4 if label else 3, "encoded_class", y)
    sample_index.to_csv(tables_dir / "sample_index.csv", index=False, encoding="utf-8-sig")

    (metadata_dir / "feature_columns.txt").write_text("\n".join(features) + "\n", encoding="utf-8")
    (metadata_dir / "class_mapping.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "config_path": str(config_path),
        "source_dataset": str(dataset_path),
        "source_dataset_size_bytes": dataset_path.stat().st_size,
        "source_split_assignments": str(assignments_path),
        "split_assignments_sha256": sha256_file(assignments_path),
        "feature_columns_sha256": sha256_text(features),
        "n_rows": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "n_classes": int(len(catalog)),
        "fold_ids": fold_ids,
        "n_development": int(index_arrays["development_indices"].size),
        "n_independent": int(index_arrays["independent_indices"].size),
        "n_excluded_border": int(
            assignments["split_role"].astype(str).eq("excluded_border").sum()
        ),
        "x_dtype": str(X.dtype),
        "y_dtype": str(y.dtype),
        "contains_nan_predictors": bool(np.isnan(X).any()),
        "fields": {
            "key": key,
            "group": group,
            "target": target,
            "target_label": label,
        },
    }
    (metadata_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_report(output_dir, modelable, features, catalog, fold_ids, config)

    LOGGER.info(
        "Preparación finalizada: X=%s | clases=%s | folds=%s | salida=%s",
        X.shape,
        len(catalog),
        fold_ids,
        output_dir,
    )


if __name__ == "__main__":
    main()
