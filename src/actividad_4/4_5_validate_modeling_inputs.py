# -*- coding: utf-8 -*-
"""
Actividad 5.0 — Validación previa al modelado
=============================================

Valida la base preparada en A4.4 antes de iniciar entrenamiento de modelos.

Entrada principal:
    - GeoPackage A4.4 con:
        pilot_xy_point
        xy_pilot_quadrant
        xy_score
        xy_accion
        predictor_source
        predictor_band
        xy_pred_<predictor_id>
        pilot_model_matrix

Salida:
    - Reporte Markdown de validación.
    - CSVs de integridad, faltantes, distribución de clases y preparación para
      validación espacial por cuadrantes.

Ejecución desde la raíz del repositorio:
    python src/actividad_5/a5_0_validate_modeling_inputs.py

El script no recibe argumentos obligatorios. Por defecto lee:
    config/a5_0_validate_modeling_inputs.yaml
"""

from __future__ import annotations

import logging
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import yaml

LOGGER = logging.getLogger("a5_0_pre_model_validation")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_5_validate_modeling_inputs.yaml"


@dataclass
class Issue:
    severity: str
    check: str
    table: str
    field: str
    message: str
    n_affected: int | None = None


def configure_logger(output_dir: Path) -> None:
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "a4_5_validate_modeling_inputs.log"

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


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def connect_readonly(sqlite_path: Path) -> sqlite3.Connection:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"No existe la base de datos: {sqlite_path}")
    return sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True)


def list_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()
    return {str(row[0]) for row in rows}


def table_columns(connection: sqlite3.Connection, table_name: str) -> list[str]:
    rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return [str(row[1]) for row in rows]


def read_table(
    connection: sqlite3.Connection,
    table_name: str,
    fields: list[str] | None = None,
) -> pd.DataFrame:
    if fields:
        available = table_columns(connection, table_name)
        missing = [field for field in fields if field not in available]
        if missing:
            raise ValueError(f"Faltan campos en {table_name}: {missing}")
        columns = ", ".join(f'"{field}"' for field in fields)
    else:
        columns = "*"
    return pd.read_sql_query(f'SELECT {columns} FROM "{table_name}"', connection)


def normalize_key_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def add_issue(
    issues: list[Issue],
    severity: str,
    check: str,
    table: str,
    field: str,
    message: str,
    n_affected: int | None = None,
) -> None:
    issues.append(
        Issue(
            severity=severity,
            check=check,
            table=table,
            field=field,
            message=message,
            n_affected=n_affected,
        )
    )


def validate_unique_key(
    dataframe: pd.DataFrame,
    key: str,
    table_name: str,
    issues: list[Issue],
) -> None:
    if key not in dataframe.columns:
        add_issue(
            issues,
            "critical",
            "key_exists",
            table_name,
            key,
            f"No existe el campo llave {key}.",
        )
        return
    nulls = int(dataframe[key].isna().sum())
    if nulls:
        add_issue(
            issues,
            "critical",
            "key_not_null",
            table_name,
            key,
            f"La llave {key} tiene valores nulos.",
            nulls,
        )
    duplicates = int(dataframe.duplicated(subset=[key]).sum())
    if duplicates:
        add_issue(
            issues,
            "critical",
            "key_unique",
            table_name,
            key,
            f"La llave {key} tiene duplicados.",
            duplicates,
        )


def compare_universe(
    observed_keys: set[str],
    expected_keys: set[str],
    table_name: str,
    key: str,
    issues: list[Issue],
    severity: str = "critical",
) -> dict[str, Any]:
    missing = expected_keys - observed_keys
    extra = observed_keys - expected_keys
    if missing:
        add_issue(
            issues,
            severity,
            "missing_keys",
            table_name,
            key,
            "La tabla no contiene todo el universo esperado de puntos.",
            len(missing),
        )
    if extra:
        add_issue(
            issues,
            severity,
            "extra_keys",
            table_name,
            key,
            "La tabla contiene llaves que no existen en pilot_xy_point.",
            len(extra),
        )
    return {
        "table": table_name,
        "expected_keys": len(expected_keys),
        "observed_keys": len(observed_keys),
        "missing_keys": len(missing),
        "extra_keys": len(extra),
        "exact_universe": len(missing) == 0 and len(extra) == 0,
    }


def safe_sql_table_name(text: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_]+", "_", str(text).strip().lower())
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe:
        raise ValueError(f"No se puede construir nombre seguro de tabla para: {text!r}")
    if safe[0].isdigit():
        safe = f"p_{safe}"
    return safe


def load_pilot_points(
    gpkg_path: Path,
    layer_name: str,
    key: str,
    issues: list[Issue],
) -> tuple[gpd.GeoDataFrame, set[str], dict[str, Any]]:
    LOGGER.info("Leyendo capa espacial: %s", layer_name)
    gdf = gpd.read_file(gpkg_path, layer=layer_name)
    validate_unique_key(gdf, key, layer_name, issues)
    gdf[key] = normalize_key_series(gdf[key])

    geometry_null = int(gdf.geometry.isna().sum())
    geometry_empty = int(gdf.geometry.is_empty.sum()) if len(gdf) else 0
    if geometry_null or geometry_empty:
        add_issue(
            issues,
            "critical",
            "geometry_valid",
            layer_name,
            "geometry",
            "Hay geometrías nulas o vacías en pilot_xy_point.",
            geometry_null + geometry_empty,
        )

    geometry_types = sorted(gdf.geometry.geom_type.dropna().unique().tolist())
    if any(gtype not in {"Point", "MultiPoint"} for gtype in geometry_types):
        add_issue(
            issues,
            "warning",
            "geometry_type",
            layer_name,
            "geometry",
            f"Se encontraron tipos de geometría no puntuales: {geometry_types}.",
        )

    summary = {
        "table": layer_name,
        "n_rows": len(gdf),
        "n_columns": len(gdf.columns),
        "geometry_types": ",".join(geometry_types),
        "crs": str(gdf.crs) if gdf.crs else "",
        "n_geometry_null_or_empty": geometry_null + geometry_empty,
    }
    return gdf, set(gdf[key]), summary


def validate_base_tables(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    base_keys: set[str],
    issues: list[Issue],
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    key = config["fields"]["key"]
    inputs = config["inputs"]
    tables = {
        "xy_pilot_quadrant": inputs["assignment_table"],
        "xy_score": inputs["score_table"],
        "xy_accion": inputs["action_table"],
    }
    table_summaries: list[dict[str, Any]] = []
    loaded: dict[str, pd.DataFrame] = {}
    existing = list_tables(connection)

    for label, table_name in tables.items():
        if table_name not in existing:
            add_issue(
                issues,
                "critical",
                "table_exists",
                table_name,
                "",
                f"No existe la tabla requerida {table_name}.",
            )
            continue
        df = read_table(connection, table_name)
        if key in df.columns:
            df[key] = normalize_key_series(df[key])
        validate_unique_key(df, key, table_name, issues)
        observed = set(df[key]) if key in df.columns else set()
        universe = compare_universe(observed, base_keys, table_name, key, issues)
        table_summaries.append(
            {
                "table": table_name,
                "logical_role": label,
                "n_rows": len(df),
                "n_columns": len(df.columns),
                **universe,
            }
        )
        loaded[label] = df
    return loaded, table_summaries


def validate_catalogs(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    issues: list[Issue],
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    catalog_cfg = config.get("catalogs", {})
    source_table = catalog_cfg.get("predictor_source_table", "predictor_source")
    band_table_name = catalog_cfg.get("predictor_band_table", "predictor_band")
    existing = list_tables(connection)
    summaries: list[dict[str, Any]] = []

    for table_name in [source_table, band_table_name]:
        if table_name not in existing:
            raise ValueError(f"No existe la tabla requerida: {table_name}")

    predictor_source = read_table(connection, source_table)
    predictor_band = read_table(connection, band_table_name)

    required_source = ["predictor_id"]
    required_band = ["predictor_id"]
    for field in required_source:
        if field not in predictor_source.columns:
            add_issue(issues, "critical", "catalog_field", source_table, field, "Falta campo en predictor_source.")
    for field in required_band:
        if field not in predictor_band.columns:
            add_issue(issues, "critical", "catalog_field", band_table_name, field, "Falta campo en predictor_band.")

    if "predictor_id" in predictor_source.columns:
        predictor_source["predictor_id"] = predictor_source["predictor_id"].astype(str).str.strip()
        validate_unique_key(predictor_source, "predictor_id", source_table, issues)
    if "predictor_id" in predictor_band.columns:
        predictor_band["predictor_id"] = predictor_band["predictor_id"].astype(str).str.strip()

    if "predictor_table" not in predictor_source.columns:
        predictor_source["predictor_table"] = predictor_source["predictor_id"].apply(
            lambda value: f"xy_pred_{safe_sql_table_name(value)}"
        )
        add_issue(
            issues,
            "warning",
            "catalog_field",
            source_table,
            "predictor_table",
            "No existía predictor_table; se infirió como xy_pred_<predictor_id>.",
        )
    if "predictor_table" not in predictor_band.columns:
        predictor_band = predictor_band.merge(
            predictor_source[["predictor_id", "predictor_table"]],
            on="predictor_id",
            how="left",
            validate="many_to_one",
        )
    if "band_column" not in predictor_band.columns:
        fallback_field = "band_output" if "band_output" in predictor_band.columns else None
        if fallback_field is None:
            add_issue(
                issues,
                "critical",
                "catalog_field",
                band_table_name,
                "band_column",
                "No existe band_column ni band_output para identificar columnas de predictores.",
            )
            predictor_band["band_column"] = ""
        else:
            predictor_band["band_column"] = predictor_band[fallback_field].astype(str).str.strip()
            add_issue(
                issues,
                "warning",
                "catalog_field",
                band_table_name,
                "band_column",
                f"No existía band_column; se usó {fallback_field}.",
            )

    if "predictor_band_id" not in predictor_band.columns:
        predictor_band["predictor_band_id"] = (
            predictor_band["predictor_id"].astype(str) + "::" + predictor_band["band_column"].astype(str)
        )

    validate_unique_key(predictor_band, "predictor_band_id", band_table_name, issues)

    source_ids = set(predictor_source["predictor_id"].astype(str)) if "predictor_id" in predictor_source else set()
    band_ids = set(predictor_band["predictor_id"].astype(str)) if "predictor_id" in predictor_band else set()
    missing_in_source = band_ids - source_ids
    if missing_in_source:
        add_issue(
            issues,
            "critical",
            "catalog_fk",
            band_table_name,
            "predictor_id",
            "Hay predictor_id en predictor_band que no existen en predictor_source.",
            len(missing_in_source),
        )

    summaries.append({"table": source_table, "n_rows": len(predictor_source), "n_columns": len(predictor_source.columns)})
    summaries.append({"table": band_table_name, "n_rows": len(predictor_band), "n_columns": len(predictor_band.columns)})
    return predictor_source, predictor_band, summaries


def validate_predictor_tables(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    predictor_source: pd.DataFrame,
    predictor_band: pd.DataFrame,
    base_keys: set[str],
    issues: list[Issue],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    key = config["fields"]["key"]
    existing = list_tables(connection)
    predictor_summaries: list[dict[str, Any]] = []
    missingness_rows: list[dict[str, Any]] = []
    max_null_pct_warning = float(config.get("thresholds", {}).get("max_predictor_null_pct_warning", 5.0))
    max_null_pct_critical = float(config.get("thresholds", {}).get("max_predictor_null_pct_critical", 30.0))

    for _, source_row in predictor_source.sort_values("predictor_id").iterrows():
        predictor_id = str(source_row["predictor_id"])
        predictor_table = str(source_row["predictor_table"])
        if predictor_table not in existing:
            add_issue(
                issues,
                "critical",
                "predictor_table_exists",
                predictor_table,
                "",
                f"No existe la tabla física para el predictor {predictor_id}.",
            )
            continue

        columns = table_columns(connection, predictor_table)
        if key not in columns:
            add_issue(
                issues,
                "critical",
                "predictor_key_exists",
                predictor_table,
                key,
                "La tabla de predictor no tiene xy_group_id.",
            )
            continue

        band_rows = predictor_band[predictor_band["predictor_id"].astype(str) == predictor_id].copy()
        expected_band_columns = band_rows["band_column"].astype(str).tolist()
        missing_columns = [column for column in expected_band_columns if column not in columns]
        if missing_columns:
            add_issue(
                issues,
                "critical",
                "predictor_band_columns",
                predictor_table,
                "band_column",
                f"Faltan columnas de bandas esperadas: {missing_columns[:10]}",
                len(missing_columns),
            )

        read_fields = [key] + [column for column in expected_band_columns if column in columns]
        df = read_table(connection, predictor_table, read_fields)
        df[key] = normalize_key_series(df[key])
        validate_unique_key(df, key, predictor_table, issues)
        observed = set(df[key])
        universe = compare_universe(observed, base_keys, predictor_table, key, issues)

        predictor_summaries.append(
            {
                "predictor_id": predictor_id,
                "predictor_table": predictor_table,
                "n_rows": len(df),
                "n_band_columns_expected": len(expected_band_columns),
                "n_band_columns_found": len(read_fields) - 1,
                **universe,
            }
        )

        for column in expected_band_columns:
            if column not in df.columns:
                continue
            numeric = pd.to_numeric(df[column], errors="coerce")
            n_total = len(numeric)
            n_null = int(numeric.isna().sum())
            n_non_null = int(n_total - n_null)
            pct_null = float((n_null / n_total) * 100.0) if n_total else 0.0
            n_unique = int(numeric.nunique(dropna=True))
            std = float(numeric.std(skipna=True)) if n_non_null > 1 else None
            minimum = float(numeric.min(skipna=True)) if n_non_null else None
            maximum = float(numeric.max(skipna=True)) if n_non_null else None

            severity = "ok"
            if pct_null >= max_null_pct_critical:
                severity = "critical"
                add_issue(
                    issues,
                    "critical",
                    "predictor_missingness",
                    predictor_table,
                    column,
                    f"La banda tiene {pct_null:.2f}% de valores nulos.",
                    n_null,
                )
            elif pct_null >= max_null_pct_warning:
                severity = "warning"
                add_issue(
                    issues,
                    "warning",
                    "predictor_missingness",
                    predictor_table,
                    column,
                    f"La banda tiene {pct_null:.2f}% de valores nulos.",
                    n_null,
                )

            if n_unique <= 1:
                add_issue(
                    issues,
                    "warning",
                    "predictor_variance",
                    predictor_table,
                    column,
                    "La banda tiene cero o casi cero variabilidad.",
                    n_unique,
                )

            missingness_rows.append(
                {
                    "predictor_id": predictor_id,
                    "predictor_table": predictor_table,
                    "band_column": column,
                    "n_total": n_total,
                    "n_non_null": n_non_null,
                    "n_null": n_null,
                    "pct_null": round(pct_null, 6),
                    "n_unique": n_unique,
                    "min": minimum,
                    "max": maximum,
                    "std": std,
                    "severity": severity,
                }
            )

        LOGGER.info(
            "Validado predictor: %s | tabla=%s | filas=%s | bandas=%s",
            predictor_id,
            predictor_table,
            f"{len(df):,}",
            len(expected_band_columns),
        )

    return pd.DataFrame(predictor_summaries), pd.DataFrame(missingness_rows)


def read_model_matrix(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    gpkg_path: Path,
) -> pd.DataFrame | None:
    outputs = config.get("outputs", {})
    matrix_table = outputs.get("model_matrix_table", "pilot_model_matrix")
    existing = list_tables(connection)
    if matrix_table in existing:
        LOGGER.info("Leyendo matriz de modelado desde GPKG: %s", matrix_table)
        return read_table(connection, matrix_table)

    matrix_csv_value = outputs.get("model_matrix_csv")
    if matrix_csv_value:
        matrix_csv = resolve_path(matrix_csv_value)
        if not matrix_csv.exists() and not Path(matrix_csv_value).is_absolute():
            # Si se configuró solo el nombre del CSV, buscar dentro de output_dir.
            matrix_csv = resolve_path(config["paths"]["output_dir"]) / matrix_csv_value
        if matrix_csv.exists():
            LOGGER.info("Leyendo matriz de modelado desde CSV: %s", matrix_csv)
            return pd.read_csv(matrix_csv, encoding="utf-8-sig")

    LOGGER.warning("No se encontró pilot_model_matrix ni CSV de matriz de modelado.")
    return None


def validate_model_matrix(
    matrix: pd.DataFrame | None,
    config: dict[str, Any],
    predictor_band: pd.DataFrame,
    base_keys: set[str],
    issues: list[Issue],
) -> pd.DataFrame:
    key = config["fields"]["key"]
    if matrix is None:
        add_issue(
            issues,
            "critical",
            "model_matrix_exists",
            "pilot_model_matrix",
            "",
            "No existe la matriz derivada de modelado.",
        )
        return pd.DataFrame()

    if key in matrix.columns:
        matrix[key] = normalize_key_series(matrix[key])
    validate_unique_key(matrix, key, "pilot_model_matrix", issues)
    observed = set(matrix[key]) if key in matrix.columns else set()
    universe = compare_universe(observed, base_keys, "pilot_model_matrix", key, issues)

    required_context_fields = list(config.get("fields", {}).get("model_context_fields", []))
    missing_context = [field for field in required_context_fields if field not in matrix.columns]
    if missing_context:
        add_issue(
            issues,
            "warning",
            "model_matrix_context_fields",
            "pilot_model_matrix",
            "",
            f"Faltan campos de contexto esperados: {missing_context}",
            len(missing_context),
        )

    expected_predictor_columns = sorted(set(predictor_band["band_column"].astype(str)))
    missing_predictor_columns = [field for field in expected_predictor_columns if field not in matrix.columns]
    if missing_predictor_columns:
        add_issue(
            issues,
            "critical",
            "model_matrix_predictor_columns",
            "pilot_model_matrix",
            "",
            f"Faltan columnas predictoras esperadas: {missing_predictor_columns[:10]}",
            len(missing_predictor_columns),
        )

    duplicate_columns = matrix.columns[matrix.columns.duplicated()].tolist()
    if duplicate_columns:
        add_issue(
            issues,
            "critical",
            "model_matrix_duplicate_columns",
            "pilot_model_matrix",
            "",
            f"La matriz tiene columnas duplicadas: {duplicate_columns[:10]}",
            len(duplicate_columns),
        )

    return pd.DataFrame(
        [
            {
                "table": "pilot_model_matrix",
                "n_rows": len(matrix),
                "n_columns": len(matrix.columns),
                "n_expected_predictor_columns": len(expected_predictor_columns),
                "n_missing_predictor_columns": len(missing_predictor_columns),
                **universe,
            }
        ]
    )


def summarize_action_distribution(
    base_tables: dict[str, pd.DataFrame],
    config: dict[str, Any],
) -> pd.DataFrame:
    action_df = base_tables.get("xy_accion")
    if action_df is None or action_df.empty:
        return pd.DataFrame()
    fields = [
        field
        for field in config.get("fields", {}).get("action_distribution_fields", [])
        if field in action_df.columns
    ]
    rows: list[pd.DataFrame] = []
    for field in fields:
        counts = (
            action_df[field]
            .fillna("<NULL>")
            .astype(str)
            .value_counts(dropna=False)
            .rename_axis("category")
            .reset_index(name="n_points")
        )
        counts.insert(0, "field", field)
        counts["pct_points"] = (counts["n_points"] / len(action_df) * 100).round(6)
        rows.append(counts)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def summarize_class_readiness(
    matrix: pd.DataFrame | None,
    config: dict[str, Any],
    issues: list[Issue],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if matrix is None or matrix.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    key = config["fields"]["key"]
    group_field = config["fields"].get("quadrant", "id_cuadrante")
    target_fields = config.get("model_readiness", {}).get("target_fields", ["id_0", "id_1", "id_2"])
    min_points = int(config.get("thresholds", {}).get("min_points_per_class", 30))
    min_quadrants = int(config.get("thresholds", {}).get("min_quadrants_per_class", 2))
    requested_splits = int(config.get("model_readiness", {}).get("group_kfold_n_splits", 5))

    class_rows: list[dict[str, Any]] = []
    class_quad_rows: list[dict[str, Any]] = []
    readiness_rows: list[dict[str, Any]] = []

    for target in target_fields:
        if target not in matrix.columns:
            add_issue(
                issues,
                "warning",
                "target_field_exists",
                "pilot_model_matrix",
                target,
                f"No existe el campo objetivo {target} en la matriz.",
            )
            continue
        if group_field not in matrix.columns:
            add_issue(
                issues,
                "critical",
                "group_field_exists",
                "pilot_model_matrix",
                group_field,
                f"No existe el campo de grupo espacial {group_field} en la matriz.",
            )
            continue

        work = matrix[[key, target, group_field]].copy()
        work[target] = work[target].fillna("<NULL>").astype(str)
        work[group_field] = work[group_field].fillna("<NULL>").astype(str)

        by_class = (
            work.groupby(target, dropna=False)
            .agg(n_points=(key, "count"), n_quadrants=(group_field, "nunique"))
            .reset_index()
            .rename(columns={target: "class_id"})
        )
        by_class.insert(0, "target_field", target)
        by_class["pct_points"] = (by_class["n_points"] / len(work) * 100).round(6)
        class_rows.extend(by_class.to_dict("records"))

        by_class_quad = (
            work.groupby([target, group_field], dropna=False)
            .agg(n_points=(key, "count"))
            .reset_index()
            .rename(columns={target: "class_id", group_field: "id_cuadrante"})
        )
        by_class_quad.insert(0, "target_field", target)
        class_quad_rows.extend(by_class_quad.to_dict("records"))

        for _, row in by_class.iterrows():
            class_id = str(row["class_id"])
            n_points = int(row["n_points"])
            n_quadrants = int(row["n_quadrants"])
            if class_id == "<NULL>":
                status = "critical_null_class"
                severity = "critical"
                message = f"{target} tiene puntos sin clase asignada."
            elif n_points < min_points:
                status = "risk_few_points"
                severity = "warning"
                message = f"{target}={class_id} tiene menos de {min_points} puntos."
            elif n_quadrants < min_quadrants:
                status = "impossible_spatial_validation"
                severity = "critical"
                message = f"{target}={class_id} aparece en menos de {min_quadrants} cuadrantes."
            elif n_quadrants < requested_splits:
                status = "risk_group_kfold"
                severity = "warning"
                message = (
                    f"{target}={class_id} aparece en {n_quadrants} cuadrantes; "
                    f"es menor que n_splits={requested_splits}."
                )
            else:
                status = "ok"
                severity = "ok"
                message = ""

            readiness_rows.append(
                {
                    "target_field": target,
                    "class_id": class_id,
                    "n_points": n_points,
                    "n_quadrants": n_quadrants,
                    "requested_group_kfold_splits": requested_splits,
                    "status": status,
                    "severity": severity,
                    "message": message,
                }
            )
            if severity in {"critical", "warning"}:
                add_issue(
                    issues,
                    severity,
                    "class_group_readiness",
                    "pilot_model_matrix",
                    target,
                    message,
                    n_quadrants if "quadrantes" in message or "cuadrantes" in message else n_points,
                )

    return (
        pd.DataFrame(class_rows),
        pd.DataFrame(class_quad_rows),
        pd.DataFrame(readiness_rows),
    )


def write_csv(dataframe: pd.DataFrame, path: Path) -> None:
    ensure_dir(path.parent)
    dataframe.to_csv(path, index=False, encoding="utf-8-sig")


def issues_to_dataframe(issues: list[Issue]) -> pd.DataFrame:
    return pd.DataFrame([issue.__dict__ for issue in issues])


def build_markdown_report(
    output_path: Path,
    config: dict[str, Any],
    issues_df: pd.DataFrame,
    table_integrity: pd.DataFrame,
    predictor_summary: pd.DataFrame,
    missingness: pd.DataFrame,
    class_distribution: pd.DataFrame,
    group_readiness: pd.DataFrame,
    matrix_validation: pd.DataFrame,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    n_critical = int((issues_df["severity"] == "critical").sum()) if not issues_df.empty else 0
    n_warning = int((issues_df["severity"] == "warning").sum()) if not issues_df.empty else 0
    status = "FAIL" if n_critical else ("WARN" if n_warning else "PASS")

    lines: list[str] = []
    lines.append("# Actividad 5.0 — Validación previa al modelado")
    lines.append("")
    lines.append(f"**Fecha:** {now}")
    lines.append(f"**Estado general:** `{status}`")
    lines.append(f"**Críticos:** {n_critical}")
    lines.append(f"**Advertencias:** {n_warning}")
    lines.append("")
    lines.append("## Insumos")
    lines.append("")
    lines.append(f"- Base A4.4: `{config['paths']['modeling_gpkg']}`")
    lines.append(f"- Carpeta de salida: `{config['paths']['output_dir']}`")
    lines.append("")

    lines.append("## Resumen de integridad")
    lines.append("")
    if table_integrity.empty:
        lines.append("No se generó resumen de integridad.")
    else:
        cols = [col for col in ["table", "n_rows", "n_columns", "missing_keys", "extra_keys", "exact_universe"] if col in table_integrity.columns]
        lines.append(table_integrity[cols].to_markdown(index=False))
    lines.append("")

    lines.append("## Predictores")
    lines.append("")
    if predictor_summary.empty:
        lines.append("No se validaron tablas de predictores.")
    else:
        lines.append(f"Tablas de predictores validadas: **{len(predictor_summary):,}**")
        lines.append("")
        cols = [
            "predictor_id",
            "predictor_table",
            "n_rows",
            "n_band_columns_expected",
            "n_band_columns_found",
            "missing_keys",
            "extra_keys",
        ]
        cols = [col for col in cols if col in predictor_summary.columns]
        lines.append(predictor_summary[cols].to_markdown(index=False))
    lines.append("")

    lines.append("## Faltantes en bandas predictoras")
    lines.append("")
    if missingness.empty:
        lines.append("No se generó reporte de faltantes.")
    else:
        worst = missingness.sort_values("pct_null", ascending=False).head(20)
        cols = ["predictor_id", "band_column", "n_null", "pct_null", "n_unique", "severity"]
        lines.append(worst[cols].to_markdown(index=False))
    lines.append("")

    lines.append("## Preparación de clases para validación espacial")
    lines.append("")
    if group_readiness.empty:
        lines.append("No se generó diagnóstico de clases por cuadrante.")
    else:
        problem = group_readiness[group_readiness["severity"].isin(["critical", "warning"])].copy()
        if problem.empty:
            lines.append("Todas las clases cumplen los umbrales configurados para puntos y cuadrantes.")
        else:
            lines.append(problem.to_markdown(index=False))
    lines.append("")

    lines.append("## Matriz de modelado")
    lines.append("")
    if matrix_validation.empty:
        lines.append("No se pudo validar la matriz de modelado.")
    else:
        lines.append(matrix_validation.to_markdown(index=False))
    lines.append("")

    lines.append("## Incidencias")
    lines.append("")
    if issues_df.empty:
        lines.append("No se detectaron incidencias.")
    else:
        cols = ["severity", "check", "table", "field", "message", "n_affected"]
        lines.append(issues_df[cols].to_markdown(index=False))
    lines.append("")

    ensure_dir(output_path.parent)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def run_validation(config: dict[str, Any]) -> None:
    output_dir = resolve_path(config["paths"]["output_dir"])
    ensure_dir(output_dir)
    configure_logger(output_dir)

    issues: list[Issue] = []
    gpkg_path = resolve_path(config["paths"]["modeling_gpkg"])
    key = config["fields"]["key"]
    pilot_points_layer = config["inputs"]["pilot_points_layer"]

    LOGGER.info("Base A4.4 para validar: %s", gpkg_path)

    pilot_gdf, base_keys, pilot_summary = load_pilot_points(
        gpkg_path=gpkg_path,
        layer_name=pilot_points_layer,
        key=key,
        issues=issues,
    )

    with connect_readonly(gpkg_path) as connection:
        table_integrity_rows: list[dict[str, Any]] = [pilot_summary]

        base_tables, base_summaries = validate_base_tables(connection, config, base_keys, issues)
        table_integrity_rows.extend(base_summaries)

        predictor_source, predictor_band, catalog_summaries = validate_catalogs(connection, config, issues)
        table_integrity_rows.extend(catalog_summaries)

        predictor_summary, missingness = validate_predictor_tables(
            connection=connection,
            config=config,
            predictor_source=predictor_source,
            predictor_band=predictor_band,
            base_keys=base_keys,
            issues=issues,
        )

        matrix = read_model_matrix(connection, config, gpkg_path)
        matrix_validation = validate_model_matrix(
            matrix=matrix,
            config=config,
            predictor_band=predictor_band,
            base_keys=base_keys,
            issues=issues,
        )

        action_distribution = summarize_action_distribution(base_tables, config)
        class_distribution, class_by_quadrant, group_readiness = summarize_class_readiness(
            matrix=matrix,
            config=config,
            issues=issues,
        )

    table_integrity = pd.DataFrame(table_integrity_rows)
    issues_df = issues_to_dataframe(issues)

    reports_dir = output_dir / "reports"
    tables_dir = output_dir / "tables"
    ensure_dir(reports_dir)
    ensure_dir(tables_dir)

    write_csv(table_integrity, tables_dir / "table_integrity.csv")
    write_csv(predictor_summary, tables_dir / "predictor_table_summary.csv")
    write_csv(missingness, tables_dir / "predictor_band_missingness.csv")
    write_csv(matrix_validation, tables_dir / "model_matrix_validation.csv")
    write_csv(action_distribution, tables_dir / "action_distribution.csv")
    write_csv(class_distribution, tables_dir / "class_distribution.csv")
    write_csv(class_by_quadrant, tables_dir / "class_by_quadrant.csv")
    write_csv(group_readiness, tables_dir / "group_cv_readiness.csv")
    write_csv(issues_df, tables_dir / "validation_issues.csv")

    report_path = reports_dir / "a5_0_validation_report.md"
    build_markdown_report(
        output_path=report_path,
        config=config,
        issues_df=issues_df,
        table_integrity=table_integrity,
        predictor_summary=predictor_summary,
        missingness=missingness,
        class_distribution=class_distribution,
        group_readiness=group_readiness,
        matrix_validation=matrix_validation,
    )

    n_critical = int((issues_df["severity"] == "critical").sum()) if not issues_df.empty else 0
    n_warning = int((issues_df["severity"] == "warning").sum()) if not issues_df.empty else 0
    LOGGER.info("Reporte escrito: %s", report_path)
    LOGGER.info("CSV de validación escritos en: %s", tables_dir)
    LOGGER.info("Resultado: críticos=%s | advertencias=%s", n_critical, n_warning)

    if n_critical and bool(config.get("validation", {}).get("fail_on_critical", True)):
        raise SystemExit(
            f"Validación fallida: {n_critical} incidencia(s) crítica(s). "
            f"Revisar {report_path}"
        )


def main() -> None:
    config = read_yaml(DEFAULT_CONFIG)
    run_validation(config)


if __name__ == "__main__":
    main()