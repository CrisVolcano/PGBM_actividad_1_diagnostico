# -*- coding: utf-8 -*-
"""
Actividad 4.6 — Preparación del dataset tabular de modelado
============================================================

Esta etapa toma la base normalizada de A4.4 y prepara un dataset tabular
limpio para modelado piloto. No entrena modelos, no genera mapas y no crea
cubos raster. Su función es dejar documentado qué columnas son contexto,
qué columnas son objetivos y qué columnas son predictores.

Entrada principal:
    - GeoPackage A4.4 con:
        pilot_model_matrix
        predictor_source
        predictor_band

Salidas principales:
    - tables/modeling_dataset.parquet  (si hay motor parquet disponible)
    - tables/modeling_dataset.csv      (opcional)
    - tables/feature_catalog.csv
    - tables/target_distribution.csv
    - tables/class_by_quadrant.csv
    - tables/split_readiness_by_target.csv
    - reports/a4_6_modeling_dataset_report.md

Ejecución desde la raíz del repositorio:
    python src/actividad_4/4_6_prepare_modeling_dataset.py
"""

from __future__ import annotations

import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

LOGGER = logging.getLogger("a4_6_modeling_dataset")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_6_prepare_modeling_dataset.yaml"


def configure_logger(output_dir: Path) -> None:
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "a4_6_prepare_modeling_dataset.log"

    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    LOGGER.addHandler(console)

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el YAML de configuración: {path}")
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError("El YAML debe contener un diccionario en la raíz.")
    return data


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def read_sql_table(connection: sqlite3.Connection, table_name: str) -> pd.DataFrame:
    if not table_exists(connection, table_name):
        raise ValueError(f"No existe la tabla '{table_name}' en la base A4.4.")
    return pd.read_sql_query(f'SELECT * FROM "{table_name}"', connection)


def attach_homologated_targets(
    matrix: pd.DataFrame,
    modeling_gpkg: Path,
    config: dict[str, Any],
) -> pd.DataFrame:
    """Garantiza objetivos homologados; las clases originales quedan para auditoría."""
    hom_cfg = config.get("homologation", {}) or {}
    if not bool(hom_cfg.get("enabled", True)):
        return matrix

    key = str(config.get("fields", {}).get("key", "xy_group_id"))
    source_gpkg = resolve_path(config["paths"]["homologation_gpkg"])
    source_table = str(config["inputs"].get("homologation_final_table", "xy_homologacion_final"))
    target_fields = [str(field) for field in as_list(hom_cfg.get("target_fields"))]
    label_fields = [str(field) for field in as_list(hom_cfg.get("label_fields"))]
    selected_fields = [key] + target_fields + label_fields

    if not target_fields:
        raise ValueError("homologation.target_fields debe declarar al menos un objetivo homologado.")
    if label_fields and len(label_fields) != len(target_fields):
        raise ValueError(
            "homologation.label_fields debe declarar una etiqueta por cada target homologado."
        )

    configured_targets = {
        str(field) for field in as_list(config.get("fields", {}).get("targets"))
    }
    primary_target = str(config.get("fields", {}).get("primary_target", ""))
    allowed_targets = set(target_fields)
    invalid_targets = sorted(configured_targets - allowed_targets)
    if primary_target and primary_target not in allowed_targets:
        invalid_targets.append(primary_target)
    if invalid_targets:
        raise ValueError(
            "A4.6 solo puede preparar objetivos homologados. Objetivos no permitidos: "
            f"{sorted(set(invalid_targets))}; permitidos: {sorted(allowed_targets)}"
        )

    matrix_homologation_fields = target_fields + label_fields
    present_fields = [field for field in matrix_homologation_fields if field in matrix.columns]
    missing_matrix_fields = [
        field for field in matrix_homologation_fields if field not in matrix.columns
    ]
    if present_fields and missing_matrix_fields:
        raise ValueError(
            "La matriz contiene una homologación parcial: "
            f"presentes={present_fields}, faltantes={missing_matrix_fields}."
        )

    if not missing_matrix_fields:
        null_counts = matrix[matrix_homologation_fields].isna().sum()
        incomplete = {
            field: int(count)
            for field, count in null_counts.items()
            if int(count) > 0
        }
        if incomplete and bool(hom_cfg.get("require_complete", True)):
            raise ValueError(f"Hay campos sin homologación final: {incomplete}")

        for target_field, label_field in zip(target_fields, label_fields):
            mapping = matrix[[target_field, label_field]].dropna().drop_duplicates()
            ambiguous_ids = mapping.groupby(target_field)[label_field].nunique()
            ambiguous_ids = ambiguous_ids[ambiguous_ids > 1]
            if not ambiguous_ids.empty:
                raise ValueError(
                    f"{target_field} tiene IDs asociados a más de una etiqueta en "
                    f"{label_field}: {ambiguous_ids.index.astype(str).tolist()[:5]}"
                )

        LOGGER.info(
            "Homologación unificada ya presente en pilot_model_matrix: %s",
            matrix_homologation_fields,
        )
        return matrix

    if bool(hom_cfg.get("require_in_model_matrix", False)):
        raise ValueError(
            "pilot_model_matrix no contiene la homologación unificada requerida: "
            f"{missing_matrix_fields}. Vuelva a ejecutar A4.1 y A4.4 actualizados."
        )

    if not source_gpkg.exists():
        raise FileNotFoundError(f"No existe la base con clases homologadas: {source_gpkg}")

    quoted_fields = ", ".join(f'h."{field}"' for field in selected_fields)
    with sqlite3.connect(source_gpkg) as connection:
        if not table_exists(connection, source_table):
            raise ValueError(f"No existe la tabla de homologación final '{source_table}'.")
        available = {
            row[1]
            for row in connection.execute(f'PRAGMA table_info("{source_table}")').fetchall()
        }
        missing = [field for field in selected_fields if field not in available]
        if missing:
            raise ValueError(f"Faltan campos en {source_table}: {missing}")

        connection.execute("ATTACH DATABASE ? AS modeling", (str(modeling_gpkg),))
        try:
            query = f'''
                SELECT {quoted_fields}
                FROM "{source_table}" AS h
                INNER JOIN modeling."{config['inputs'].get('model_matrix_table', 'pilot_model_matrix')}" AS m
                    ON h."{key}" = m."{key}"
            '''
            homologation = pd.read_sql_query(query, connection)
        finally:
            connection.execute("DETACH DATABASE modeling")

    validate_unique_key(homologation, key, source_table)
    if len(homologation) != len(matrix):
        matrix_keys = set(matrix[key].astype(str).str.strip())
        homologated_keys = set(homologation[key].astype(str).str.strip())
        missing_keys = sorted(matrix_keys - homologated_keys)
        extra_keys = sorted(homologated_keys - matrix_keys)
        raise ValueError(
            "La homologación final no coincide 1:1 con el universo de modelado: "
            f"matriz={len(matrix):,}, homologados={len(homologation):,}, "
            f"faltan={len(missing_keys):,}, sobran={len(extra_keys):,}. "
            f"Ejemplos faltantes: {missing_keys[:5]}; ejemplos sobrantes: {extra_keys[:5]}"
        )

    null_counts = homologation[target_fields].isna().sum()
    incomplete = {field: int(count) for field, count in null_counts.items() if int(count) > 0}
    if incomplete and bool(hom_cfg.get("require_complete", True)):
        raise ValueError(f"Hay objetivos sin homologación final: {incomplete}")

    output = matrix.copy()
    output[key] = output[key].astype(str).str.strip()
    homologation[key] = homologation[key].astype(str).str.strip()
    output = output.merge(homologation, on=key, how="left", validate="one_to_one")
    LOGGER.info(
        "Homologación final incorporada: tabla=%s | filas=%s | objetivos=%s",
        source_table,
        f"{len(output):,}",
        target_fields,
    )
    return output


def validate_unique_key(dataframe: pd.DataFrame, key: str, label: str) -> None:
    if key not in dataframe.columns:
        raise ValueError(f"{label} no contiene la llave requerida: {key}")
    duplicated = int(dataframe[key].astype(str).duplicated().sum())
    if duplicated:
        raise ValueError(f"{label} tiene {duplicated:,} filas duplicadas para {key}.")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def first_existing_column(dataframe: pd.DataFrame, candidates: list[str], label: str) -> str:
    for candidate in candidates:
        if candidate in dataframe.columns:
            return candidate
    raise ValueError(
        f"No se encontró ninguna columna válida para {label}. "
        f"Candidatas: {candidates}. Columnas disponibles: {list(dataframe.columns)}"
    )


def normalize_string_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def build_feature_catalog(
    predictor_source: pd.DataFrame,
    predictor_band: pd.DataFrame,
    matrix_columns: set[str],
    config: dict[str, Any],
) -> pd.DataFrame:
    feature_cfg = config.get("features", {})
    feature_column_candidates = as_list(feature_cfg.get("feature_column_fields")) or [
        "band_column",
        "band_output",
        "predictor_band_id",
    ]
    feature_column_field = first_existing_column(
        predictor_band,
        feature_column_candidates,
        label="columna física de predictor en pilot_model_matrix",
    )

    required_band_fields = ["predictor_id"]
    missing_required = [field for field in required_band_fields if field not in predictor_band.columns]
    if missing_required:
        raise ValueError(f"Faltan columnas en predictor_band: {missing_required}")

    catalog = predictor_band.copy()
    catalog["predictor_id"] = normalize_string_series(catalog["predictor_id"])
    catalog["feature_column"] = normalize_string_series(catalog[feature_column_field])

    if "predictor_table" not in catalog.columns:
        catalog["predictor_table"] = ""
    if "predictor_band_id" not in catalog.columns:
        catalog["predictor_band_id"] = catalog["predictor_id"] + "::" + catalog["feature_column"]
    if "band_order" not in catalog.columns:
        catalog["band_order"] = catalog.groupby("predictor_id").cumcount() + 1

    if "predictor_id" in predictor_source.columns:
        source_cols = [
            col
            for col in [
                "predictor_id",
                "asset",
                "project",
                "type",
                "period",
                "resolution_m",
                "scale_m",
                "rescale",
                "description",
            ]
            if col in predictor_source.columns
        ]
        source = predictor_source[source_cols].drop_duplicates(subset=["predictor_id"]).copy()
        source["predictor_id"] = normalize_string_series(source["predictor_id"])
        catalog = catalog.merge(source, on="predictor_id", how="left", suffixes=("", "_source"))

    include_predictor_ids = set(map(str, as_list(feature_cfg.get("include_predictor_ids"))))
    exclude_predictor_ids = set(map(str, as_list(feature_cfg.get("exclude_predictor_ids"))))
    exclude_feature_columns = set(map(str, as_list(feature_cfg.get("exclude_feature_columns"))))
    exclude_regexes = [re.compile(pattern) for pattern in as_list(feature_cfg.get("exclude_feature_regex"))]

    catalog["exists_in_matrix"] = catalog["feature_column"].isin(matrix_columns)
    catalog["use_in_model"] = True
    catalog["exclusion_reason"] = ""

    if include_predictor_ids:
        mask = ~catalog["predictor_id"].isin(include_predictor_ids)
        catalog.loc[mask, "use_in_model"] = False
        catalog.loc[mask, "exclusion_reason"] = "predictor_not_in_include_list"

    if exclude_predictor_ids:
        mask = catalog["predictor_id"].isin(exclude_predictor_ids)
        catalog.loc[mask, "use_in_model"] = False
        catalog.loc[mask, "exclusion_reason"] = "predictor_excluded_by_config"

    if exclude_feature_columns:
        mask = catalog["feature_column"].isin(exclude_feature_columns)
        catalog.loc[mask, "use_in_model"] = False
        catalog.loc[mask, "exclusion_reason"] = "feature_excluded_by_config"

    for regex in exclude_regexes:
        mask = catalog["feature_column"].apply(lambda value: bool(regex.search(str(value))))
        catalog.loc[mask, "use_in_model"] = False
        catalog.loc[mask, "exclusion_reason"] = "feature_regex_excluded_by_config"

    missing_mask = ~catalog["exists_in_matrix"]
    catalog.loc[missing_mask, "use_in_model"] = False
    catalog.loc[missing_mask, "exclusion_reason"] = "missing_in_model_matrix"

    duplicated_feature_columns = catalog["feature_column"].duplicated(keep=False)
    if duplicated_feature_columns.any():
        duplicates = sorted(catalog.loc[duplicated_feature_columns, "feature_column"].unique())
        if bool(config.get("quality", {}).get("fail_on_duplicate_feature_columns", True)):
            raise ValueError(f"Columnas predictoras duplicadas en predictor_band: {duplicates[:20]}")
        catalog.loc[duplicated_feature_columns, "use_in_model"] = False
        catalog.loc[duplicated_feature_columns, "exclusion_reason"] = "duplicated_feature_column"

    if bool(config.get("quality", {}).get("fail_on_missing_feature_columns", True)):
        missing_features = sorted(catalog.loc[missing_mask, "feature_column"].unique())
        if missing_features:
            raise ValueError(
                "Hay columnas predictoras en predictor_band que no existen en pilot_model_matrix: "
                + ", ".join(missing_features[:20])
            )

    return catalog


def attach_feature_quality(
    matrix: pd.DataFrame,
    feature_catalog: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    quality_cfg = config.get("quality", {})
    max_pct_null = float(quality_cfg.get("max_pct_null_to_use", 1.0))
    drop_constant = bool(quality_cfg.get("drop_constant_features", True))

    rows: list[dict[str, Any]] = []
    usable_features = feature_catalog.loc[feature_catalog["use_in_model"], "feature_column"].tolist()

    for feature in usable_features:
        series = pd.to_numeric(matrix[feature], errors="coerce")
        n_rows = int(len(series))
        n_null = int(series.isna().sum())
        pct_null = float(n_null / n_rows) if n_rows else 1.0
        n_unique = int(series.nunique(dropna=True))
        rows.append(
            {
                "feature_column": feature,
                "n_rows": n_rows,
                "n_null": n_null,
                "pct_null": pct_null,
                "n_unique": n_unique,
                "is_constant": n_unique <= 1,
            }
        )

    quality = pd.DataFrame(rows)
    if quality.empty:
        feature_catalog["n_null"] = pd.NA
        feature_catalog["pct_null"] = pd.NA
        feature_catalog["n_unique"] = pd.NA
        feature_catalog["is_constant"] = pd.NA
        return feature_catalog

    output = feature_catalog.merge(quality, on="feature_column", how="left")

    high_null_mask = output["use_in_model"] & (output["pct_null"].fillna(0) > max_pct_null)
    output.loc[high_null_mask, "use_in_model"] = False
    output.loc[high_null_mask, "exclusion_reason"] = "high_null_fraction"

    if drop_constant:
        constant_mask = output["use_in_model"] & output["is_constant"].fillna(False)
        output.loc[constant_mask, "use_in_model"] = False
        output.loc[constant_mask, "exclusion_reason"] = "constant_feature"

    return output


def build_modeling_dataset(
    matrix: pd.DataFrame,
    feature_catalog: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, list[str], list[str], list[str]]:
    fields = config.get("fields", {})
    key = fields.get("key", "xy_group_id")
    group = fields.get("group", "id_cuadrante")
    targets = as_list(fields.get("targets")) or ["id_0", "id_1", "id_2"]
    context_fields = as_list(fields.get("context_fields"))

    mandatory_context = [key, group]
    for field in mandatory_context:
        if field not in context_fields:
            context_fields.insert(0 if field == key else len(context_fields), field)

    missing_context = [field for field in context_fields if field not in matrix.columns]
    if missing_context:
        raise ValueError(f"Faltan campos de contexto en pilot_model_matrix: {missing_context}")

    missing_targets = [field for field in targets if field not in matrix.columns]
    if missing_targets:
        raise ValueError(f"Faltan campos objetivo en pilot_model_matrix: {missing_targets}")

    selected_features = feature_catalog.loc[feature_catalog["use_in_model"], "feature_column"].tolist()
    selected_features = [feature for feature in selected_features if feature in matrix.columns]
    if not selected_features:
        raise ValueError("No quedó ninguna columna predictora seleccionada para modelado.")

    required_non_null_targets = as_list(config.get("row_filter", {}).get("required_non_null_targets"))
    dataset = matrix.copy()
    if required_non_null_targets:
        missing_required_targets = [field for field in required_non_null_targets if field not in dataset.columns]
        if missing_required_targets:
            raise ValueError(f"required_non_null_targets contiene campos inexistentes: {missing_required_targets}")
        before = len(dataset)
        dataset = dataset.dropna(subset=required_non_null_targets).copy()
        LOGGER.info(
            "Filtro por objetivos no nulos: filas iniciales=%s | finales=%s | removidas=%s",
            f"{before:,}",
            f"{len(dataset):,}",
            f"{before - len(dataset):,}",
        )

    action_filter = config.get("row_filter", {}).get("action_filter", {}) or {}
    action_field = action_filter.get("field")
    allowed_values = action_filter.get("allowed_values")
    if action_field and allowed_values is not None:
        if action_field not in dataset.columns:
            raise ValueError(f"El campo de filtro por acción no existe: {action_field}")
        allowed_set = set(map(str, as_list(allowed_values)))
        before = len(dataset)
        dataset = dataset[dataset[action_field].astype(str).isin(allowed_set)].copy()
        LOGGER.info(
            "Filtro por acción: campo=%s | filas iniciales=%s | finales=%s | removidas=%s",
            action_field,
            f"{before:,}",
            f"{len(dataset):,}",
            f"{before - len(dataset):,}",
        )

    output_columns = []
    for field in context_fields + targets + selected_features:
        if field not in output_columns:
            output_columns.append(field)
    dataset = dataset[output_columns].copy()

    # Forzar predictores a numéricos; los objetivos y contexto se conservan.
    for feature in selected_features:
        dataset[feature] = pd.to_numeric(dataset[feature], errors="coerce")

    validate_unique_key(dataset, key, "modeling_dataset")
    return dataset, context_fields, targets, selected_features


def summarize_targets(dataset: pd.DataFrame, targets: list[str], group_field: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    distribution_rows: list[dict[str, Any]] = []
    by_group_rows: list[dict[str, Any]] = []

    for target in targets:
        if target not in dataset.columns:
            continue
        total = len(dataset)
        grouped = dataset.groupby(target, dropna=False).agg(
            n_points=(target, "size"),
            n_groups=(group_field, "nunique"),
        ).reset_index()
        grouped["target_field"] = target
        grouped = grouped.rename(columns={target: "class_id"})
        grouped["pct_points"] = grouped["n_points"] / total if total else 0
        distribution_rows.extend(grouped[["target_field", "class_id", "n_points", "pct_points", "n_groups"]].to_dict("records"))

        class_group = dataset.groupby([target, group_field], dropna=False).size().reset_index(name="n_points")
        class_group["target_field"] = target
        class_group = class_group.rename(columns={target: "class_id", group_field: "group_id"})
        by_group_rows.extend(class_group[["target_field", "class_id", "group_id", "n_points"]].to_dict("records"))

    target_distribution = pd.DataFrame(distribution_rows)
    class_by_group = pd.DataFrame(by_group_rows)
    if not target_distribution.empty:
        target_distribution = target_distribution.sort_values(["target_field", "n_points"], ascending=[True, False])
    if not class_by_group.empty:
        class_by_group = class_by_group.sort_values(["target_field", "class_id", "group_id"])

    action_cols = [
        col
        for col in ["categoria_aptitud_preliminar", "categoria_uso_actividad_1_8", "accion_recomendada"]
        if col in dataset.columns
    ]
    action_rows: list[pd.DataFrame] = []
    for col in action_cols:
        temp = dataset.groupby(col, dropna=False).size().reset_index(name="n_points")
        temp["field"] = col
        temp = temp.rename(columns={col: "value"})
        action_rows.append(temp[["field", "value", "n_points"]])
    action_distribution = pd.concat(action_rows, ignore_index=True) if action_rows else pd.DataFrame(columns=["field", "value", "n_points"])

    return target_distribution, class_by_group, action_distribution


def build_split_readiness(target_distribution: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    split_cfg = config.get("split_readiness", {})
    requested_splits = int(split_cfg.get("requested_group_kfold_splits", 5))
    min_points = int(split_cfg.get("min_points_per_class", 30))

    if target_distribution.empty:
        return pd.DataFrame(
            columns=[
                "target_field",
                "class_id",
                "n_points",
                "n_groups",
                "requested_group_kfold_splits",
                "status",
                "severity",
                "message",
            ]
        )

    rows: list[dict[str, Any]] = []
    for row in target_distribution.to_dict("records"):
        status = "ok"
        severity = "ok"
        messages: list[str] = []
        if int(row["n_points"]) < min_points:
            status = "risk_few_points"
            severity = "warning"
            messages.append(f"menos de {min_points} puntos")
        if int(row["n_groups"]) < requested_splits:
            status = "risk_group_kfold"
            severity = "warning"
            messages.append(f"{int(row['n_groups'])} grupos < {requested_splits} folds")
        if not messages:
            messages.append("soporte suficiente para revisión inicial")
        rows.append(
            {
                "target_field": row["target_field"],
                "class_id": row["class_id"],
                "n_points": int(row["n_points"]),
                "n_groups": int(row["n_groups"]),
                "requested_group_kfold_splits": requested_splits,
                "status": status,
                "severity": severity,
                "message": "; ".join(messages),
            }
        )
    return pd.DataFrame(rows).sort_values(["severity", "target_field", "n_points"], ascending=[False, True, True])


def build_schema(dataset: pd.DataFrame, context_fields: list[str], targets: list[str], features: list[str], key: str, group: str) -> pd.DataFrame:
    roles: dict[str, str] = {}
    for col in context_fields:
        roles[col] = "context"
    for col in targets:
        roles[col] = "target"
    for col in features:
        roles[col] = "feature"
    roles[key] = "key"
    roles[group] = "group"

    rows = []
    for order, col in enumerate(dataset.columns, start=1):
        rows.append(
            {
                "column_order": order,
                "column_name": col,
                "role": roles.get(col, "other"),
                "dtype": str(dataset[col].dtype),
                "n_null": int(dataset[col].isna().sum()),
                "n_unique": int(dataset[col].nunique(dropna=True)),
            }
        )
    return pd.DataFrame(rows)


def safe_write_parquet(dataframe: pd.DataFrame, path: Path) -> bool:
    try:
        dataframe.to_parquet(path, index=False)
        return True
    except Exception as error:  # pragma: no cover - depends on optional engines
        LOGGER.warning("No se pudo escribir Parquet en %s: %s", path, error)
        return False


def dataframe_to_markdown(dataframe: pd.DataFrame) -> str:
    """Renderiza una tabla Markdown sin depender del paquete opcional tabulate."""

    def format_cell(value: Any) -> str:
        try:
            is_missing = bool(pd.isna(value))
        except (TypeError, ValueError):
            is_missing = False
        if is_missing:
            return ""
        return str(value).replace("|", r"\|").replace("\r\n", "<br>").replace("\n", "<br>")

    headers = [format_cell(column) for column in dataframe.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in dataframe.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(format_cell(value) for value in row) + " |")
    return "\n".join(lines)


def write_report(
    config: dict[str, Any],
    output_dir: Path,
    dataset: pd.DataFrame,
    feature_catalog: pd.DataFrame,
    target_distribution: pd.DataFrame,
    split_readiness: pd.DataFrame,
    parquet_written: bool,
) -> Path:
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "a4_6_modeling_dataset_report.md"

    n_features_all = len(feature_catalog)
    n_features_used = int(feature_catalog["use_in_model"].sum()) if "use_in_model" in feature_catalog.columns else 0
    n_excluded = n_features_all - n_features_used
    primary_target = config.get("fields", {}).get("primary_target", "id_1_propuesta")
    target_summary = ""
    if not target_distribution.empty:
        primary_dist = target_distribution[target_distribution["target_field"] == primary_target].copy()
        if not primary_dist.empty:
            target_summary = dataframe_to_markdown(primary_dist.head(20))
        else:
            target_summary = dataframe_to_markdown(target_distribution.head(20))

    warning_table = ""
    if not split_readiness.empty:
        warnings = split_readiness[split_readiness["severity"] != "ok"].copy()
        if not warnings.empty:
            warning_table = dataframe_to_markdown(warnings)

    content = f"""# Actividad 4.6 — Preparación del dataset tabular de modelado

**Fecha:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

## Insumos

- Base A4.4: `{config['paths']['modeling_gpkg']}`
- Tabla matriz: `{config['inputs']['model_matrix_table']}`
- Tabla catálogo de predictores: `{config['inputs']['predictor_source_table']}`
- Tabla catálogo de bandas: `{config['inputs']['predictor_band_table']}`

## Dataset preparado

| elemento | valor |
|:--|--:|
| filas | {len(dataset):,} |
| columnas totales | {len(dataset.columns):,} |
| predictores catalogados | {n_features_all:,} |
| predictores usados | {n_features_used:,} |
| predictores excluidos | {n_excluded:,} |
| Parquet escrito | {parquet_written} |

## Objetivo principal configurado

`{primary_target}`

## Distribución del objetivo principal

{target_summary if target_summary else '_Sin distribución disponible._'}

## Advertencias de preparación para validación espacial

{warning_table if warning_table else '_No se detectaron advertencias con las reglas configuradas._'}

## Nota metodológica

Esta etapa no crea particiones finales de entrenamiento/validación. Solo prepara el
insumo tabular y diagnostica la viabilidad preliminar de una partición espacial por
cuadrantes. Los objetivos usados son las clases homologadas incorporadas en A4.4;
las particiones definitivas se generan en la etapa de modelado.
"""
    report_path.write_text(content, encoding="utf-8")
    return report_path


def run(config: dict[str, Any]) -> None:
    output_dir = resolve_path(config["paths"]["output_dir"])
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    configure_logger(output_dir)

    modeling_gpkg = resolve_path(config["paths"]["modeling_gpkg"])
    if not modeling_gpkg.exists():
        raise FileNotFoundError(f"No existe la base A4.4: {modeling_gpkg}")

    LOGGER.info("Base A4.4: %s", modeling_gpkg)
    with sqlite3.connect(modeling_gpkg) as connection:
        matrix = read_sql_table(connection, config["inputs"].get("model_matrix_table", "pilot_model_matrix"))
        predictor_source = read_sql_table(connection, config["inputs"].get("predictor_source_table", "predictor_source"))
        predictor_band = read_sql_table(connection, config["inputs"].get("predictor_band_table", "predictor_band"))

    matrix = attach_homologated_targets(matrix, modeling_gpkg, config)

    key = config.get("fields", {}).get("key", "xy_group_id")
    group = config.get("fields", {}).get("group", "id_cuadrante")
    validate_unique_key(matrix, key, "pilot_model_matrix")
    LOGGER.info("Matriz leída: filas=%s | columnas=%s", f"{len(matrix):,}", f"{len(matrix.columns):,}")

    feature_catalog = build_feature_catalog(
        predictor_source=predictor_source,
        predictor_band=predictor_band,
        matrix_columns=set(matrix.columns),
        config=config,
    )
    feature_catalog = attach_feature_quality(matrix, feature_catalog, config)

    dataset, context_fields, targets, selected_features = build_modeling_dataset(
        matrix=matrix,
        feature_catalog=feature_catalog,
        config=config,
    )

    target_distribution, class_by_group, action_distribution = summarize_targets(dataset, targets, group)
    split_readiness = build_split_readiness(target_distribution, config)
    schema = build_schema(dataset, context_fields, targets, selected_features, key, group)

    # Tablas de control
    feature_catalog.to_csv(tables_dir / "feature_catalog.csv", index=False, encoding="utf-8-sig")
    target_distribution.to_csv(tables_dir / "target_distribution.csv", index=False, encoding="utf-8-sig")
    class_by_group.to_csv(tables_dir / "class_by_quadrant.csv", index=False, encoding="utf-8-sig")
    split_readiness.to_csv(tables_dir / "split_readiness_by_target.csv", index=False, encoding="utf-8-sig")
    action_distribution.to_csv(tables_dir / "action_distribution.csv", index=False, encoding="utf-8-sig")
    schema.to_csv(tables_dir / "modeling_dataset_schema.csv", index=False, encoding="utf-8-sig")

    # Dataset de modelado
    outputs = config.get("outputs", {})
    parquet_written = False
    if bool(outputs.get("write_parquet", True)):
        parquet_path = output_dir / outputs.get("modeling_dataset_parquet", "tables/modeling_dataset.parquet")
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_written = safe_write_parquet(dataset, parquet_path)
        if parquet_written:
            LOGGER.info("Dataset Parquet escrito: %s", parquet_path)

    if bool(outputs.get("write_csv", True)):
        csv_path = output_dir / outputs.get("modeling_dataset_csv", "tables/modeling_dataset.csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_csv(csv_path, index=False, encoding="utf-8-sig")
        LOGGER.info("Dataset CSV escrito: %s", csv_path)

    # Listas simples útiles para scripts de entrenamiento posteriores
    (tables_dir / "selected_feature_columns.txt").write_text("\n".join(selected_features) + "\n", encoding="utf-8")
    (tables_dir / "target_columns.txt").write_text("\n".join(targets) + "\n", encoding="utf-8")
    (tables_dir / "context_columns.txt").write_text("\n".join(context_fields) + "\n", encoding="utf-8")

    report_path = write_report(
        config=config,
        output_dir=output_dir,
        dataset=dataset,
        feature_catalog=feature_catalog,
        target_distribution=target_distribution,
        split_readiness=split_readiness,
        parquet_written=parquet_written,
    )
    LOGGER.info("Reporte escrito: %s", report_path)
    LOGGER.info(
        "A4.6 finalizado: filas=%s | features=%s | advertencias_split=%s",
        f"{len(dataset):,}",
        f"{len(selected_features):,}",
        f"{(int((split_readiness.get('severity', pd.Series(dtype=str)) == 'warning').sum()) if not split_readiness.empty else 0):,}",
    )


def main() -> None:
    config = read_yaml(DEFAULT_CONFIG)
    run(config)


if __name__ == "__main__":
    main()
