# -*- coding: utf-8 -*-
"""
Actividad 4.7 — Modelado tabular piloto con validación espacial
================================================================

Esta etapa entrena un modelo Random Forest base, pero separa explícitamente:

1. Puntos opcionalmente excluidos por cercanía al borde de cuadrantes.
2. Conjunto de desarrollo: usado para entrenamiento + validación interna.
3. Validación interna mediante GroupKFold / StratifiedGroupKFold.
4. Validación independiente: grupos/cuadrantes retenidos fuera de GridSearchCV.

La validación independiente no se usa para buscar hiperparámetros. El modelo se
selecciona con GridSearchCV usando únicamente el conjunto de desarrollo. Las
métricas OOF de la validación interna se reportan como diagnóstico del ajuste y
no sustituyen la evaluación del conjunto independiente.

Entrada principal:
    - Dataset tabular preparado en A4.6.
    - selected_feature_columns.txt generado en A4.6.
    - GPKG A4/A4.4 para calcular distancia a borde de cuadrantes, si se activa
      spatial_filter.exclude_near_quadrant_border.

Salida principal:
    - particiones espaciales documentadas;
    - resultados de GridSearchCV;
    - métricas y matrices de confusión de entrenamiento;
    - métricas y matrices de confusión de validación cruzada interna;
    - métricas y matrices de confusión de validación independiente;
    - importancia de variables;
    - modelo RF seleccionado.

Ejecución desde la raíz del repositorio:
    python src/actividad_4/4_7_train_rf_gridsearch_spatial_validation_balanced.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import GridSearchCV, GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder

try:
    from sklearn.model_selection import StratifiedGroupKFold
except ImportError:  # pragma: no cover
    StratifiedGroupKFold = None

LOGGER = logging.getLogger("a4_7_rf_spatial_validation")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_7_train_rf_gridsearch_spatial_validation_balanced.yaml"


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    """Renderiza una tabla Markdown sin depender del paquete opcional tabulate."""

    def format_cell(value: Any) -> str:
        try:
            is_missing = bool(pd.isna(value))
        except (TypeError, ValueError):
            is_missing = False
        if is_missing:
            return ""
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.6f}"
        return str(value).replace("|", r"\|").replace("\r\n", "<br>").replace("\n", "<br>")

    if df.empty:
        return "_Sin datos._"

    headers = [format_cell(column) for column in df.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in df.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(format_cell(value) for value in row) + " |")
    return "\n".join(lines)


def confusion_matrix_for_report(confusion_long: pd.DataFrame) -> pd.DataFrame:
    """Convierte la matriz larga de salida en una matriz legible para el reporte."""
    if confusion_long.empty:
        return pd.DataFrame()

    required = {
        "true_class",
        "true_class_label",
        "predicted_class",
        "predicted_class_label",
        "n",
    }
    missing = sorted(required - set(confusion_long.columns))
    if missing:
        raise ValueError(f"Faltan campos para construir la matriz de confusión: {missing}")

    def class_display(class_id: Any, class_label: Any) -> str:
        label_missing = pd.isna(class_label) or not str(class_label).strip()
        return str(class_id) if label_missing else f"{class_id} - {class_label}"

    work = confusion_long.copy()
    work["clase_real"] = [
        class_display(class_id, class_label)
        for class_id, class_label in zip(work["true_class"], work["true_class_label"])
    ]
    work["clase_predicha"] = [
        class_display(class_id, class_label)
        for class_id, class_label in zip(
            work["predicted_class"],
            work["predicted_class_label"],
        )
    ]

    class_order = list(dict.fromkeys(work["clase_real"].tolist() + work["clase_predicha"].tolist()))
    matrix = work.pivot_table(
        index="clase_real",
        columns="clase_predicha",
        values="n",
        aggfunc="sum",
        fill_value=0,
    )
    matrix = matrix.reindex(index=class_order, columns=class_order, fill_value=0)
    matrix = matrix.astype(int).reset_index()
    matrix.columns.name = None
    matrix = matrix.rename(columns={"clase_real": "real \\ predicha"})
    return matrix


def best_gridsearch_train_validation_metrics(search: GridSearchCV) -> pd.DataFrame:
    """Resume train y validación CV del mejor conjunto de hiperparámetros."""
    best_result = pd.DataFrame(search.cv_results_).iloc[int(search.best_index_)]
    scorers = list(search.scorer_) if isinstance(search.scorer_, dict) else ["score"]
    rows: list[dict[str, Any]] = []
    for metric in scorers:
        validation_suffix = metric if metric != "score" else "score"
        row = {
            "metric": metric,
            "mean_train_cv": best_result.get(f"mean_train_{validation_suffix}"),
            "std_train_cv": best_result.get(f"std_train_{validation_suffix}"),
            "mean_validation_cv": best_result.get(f"mean_test_{validation_suffix}"),
            "std_validation_cv": best_result.get(f"std_test_{validation_suffix}"),
            "rank_validation": best_result.get(f"rank_test_{validation_suffix}"),
        }
        rows.append(row)
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class PartitionData:
    dataframe_all: pd.DataFrame
    dataframe_modelable: pd.DataFrame
    dataframe_development: pd.DataFrame
    dataframe_independent: pd.DataFrame
    split_assignments: pd.DataFrame
    cv_splits: list[tuple[np.ndarray, np.ndarray]]


def configure_logger(output_dir: Path) -> None:
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "a4_7_train_rf_gridsearch_spatial_validation.log"

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


def ensure_dirs(output_dir: Path) -> None:
    for name in ["tables", "reports", "models", "logs"]:
        (output_dir / name).mkdir(parents=True, exist_ok=True)


def read_modeling_dataset(config: dict[str, Any]) -> pd.DataFrame:
    paths = config["paths"]
    parquet_path = resolve_path(paths["modeling_dataset_parquet"])
    csv_path = resolve_path(paths["modeling_dataset_csv"])

    if parquet_path.exists():
        try:
            LOGGER.info("Leyendo dataset Parquet: %s", parquet_path)
            return pd.read_parquet(parquet_path)
        except Exception as error:
            LOGGER.warning(
                "No se pudo leer Parquet; se intentará CSV. Parquet=%s | error=%s",
                parquet_path,
                error,
            )

    if csv_path.exists():
        LOGGER.info("Leyendo dataset CSV: %s", csv_path)
        return pd.read_csv(csv_path, encoding="utf-8-sig")

    raise FileNotFoundError(
        "No se encontró dataset de modelado. Revisar paths.modeling_dataset_parquet "
        f"y paths.modeling_dataset_csv. Parquet={parquet_path}; CSV={csv_path}"
    )


def read_feature_columns(config: dict[str, Any], dataframe: pd.DataFrame) -> list[str]:
    feature_txt = resolve_path(config["paths"]["feature_columns_txt"])
    non_predictor_fields = set(map(str, config["fields"].get("non_predictor_fields", [])))

    if feature_txt.exists():
        features = [line.strip() for line in feature_txt.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        LOGGER.warning("No existe selected_feature_columns.txt; se inferirán predictores por exclusión.")
        features = [col for col in dataframe.columns if col not in non_predictor_fields]

    missing = [col for col in features if col not in dataframe.columns]
    if missing:
        raise ValueError(f"Hay predictores en selected_feature_columns.txt que no existen en el dataset: {missing[:20]}")

    forbidden = [col for col in features if col in non_predictor_fields]
    if forbidden:
        raise ValueError(f"Columnas no predictoras aparecen como predictores: {forbidden}")

    if not features:
        raise ValueError("No hay columnas predictoras para entrenar.")

    LOGGER.info("Predictores seleccionados: %s", f"{len(features):,}")
    return features


def validate_homologated_target(config: dict[str, Any], dataframe: pd.DataFrame) -> None:
    """Fail closed if training is configured with an original, non-homologated class."""
    fields = config.get("fields", {})
    target = str(fields["target"])
    allowed = {str(value) for value in fields.get("homologated_target_fields", [])}
    target_columns_path = resolve_path(config["paths"]["target_columns_txt"])

    if target not in allowed:
        raise ValueError(
            f"El target '{target}' no está declarado en fields.homologated_target_fields. "
            "Se rechaza el entrenamiento con clases de origen no homologadas."
        )
    if target not in dataframe.columns:
        raise ValueError(f"El dataset no contiene el target homologado configurado: {target}")
    if not target_columns_path.exists():
        raise FileNotFoundError(
            "No existe target_columns.txt de A4.6; no se puede verificar la procedencia "
            f"del objetivo homologado: {target_columns_path}"
        )
    prepared_targets = {
        line.strip()
        for line in target_columns_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    if target not in prepared_targets:
        raise ValueError(
            f"El target homologado '{target}' no fue declarado por A4.6. "
            f"Objetivos preparados: {sorted(prepared_targets)}"
        )
    build_target_label_mapping(dataframe, config)
    LOGGER.info("Objetivo homologado verificado: %s", target)


def build_target_label_mapping(
    dataframe: pd.DataFrame,
    config: dict[str, Any],
) -> dict[str, str]:
    """Return and validate the code-to-label catalog for the homologated target."""
    fields = config.get("fields", {})
    target = str(fields["target"])
    label_field = fields.get("target_label")
    if not label_field:
        return {}
    label_field = str(label_field)
    if label_field not in dataframe.columns:
        raise ValueError(f"El dataset no contiene el label homologado configurado: {label_field}")

    catalog = dataframe[[target, label_field]].dropna().copy()
    catalog[target] = catalog[target].astype(str).str.strip()
    catalog[label_field] = catalog[label_field].astype(str).str.strip()
    ambiguous = catalog.groupby(target)[label_field].nunique()
    ambiguous = ambiguous[ambiguous > 1]
    if not ambiguous.empty:
        raise ValueError(
            "El catálogo del objetivo homologado no es determinista; códigos con más de un label: "
            f"{ambiguous.index.astype(str).tolist()[:20]}"
        )
    mapping = (
        catalog.drop_duplicates(subset=[target])
        .set_index(target)[label_field]
        .astype(str)
        .to_dict()
    )
    target_classes = set(dataframe[target].dropna().astype(str).str.strip())
    missing_labels = sorted(target_classes - set(mapping))
    if missing_labels:
        raise ValueError(f"Clases homologadas sin label en {label_field}: {missing_labels}")
    return mapping


def add_target_labels(
    dataframe: pd.DataFrame,
    target: str,
    label_field: str | None,
    class_labels: dict[str, str],
) -> pd.DataFrame:
    """Place the homologated class label immediately after its target ID."""
    result = dataframe.copy()
    if not label_field or target not in result.columns:
        return result

    mapped = result[target].map(
        lambda value: class_labels.get(str(value).strip()) if pd.notna(value) else pd.NA
    )
    if label_field in result.columns:
        existing = result.pop(label_field)
        mapped = existing.where(existing.notna(), mapped)
    result.insert(result.columns.get_loc(target) + 1, label_field, mapped)
    return result


def joined_class_labels(classes: list[str], class_labels: dict[str, str]) -> str:
    """Return pipe-separated labels in the same order as pipe-separated class IDs."""
    return "|".join(class_labels.get(str(class_id), "") for class_id in classes)


def apply_row_filters(dataframe: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    target = config["fields"]["target"]
    row_filter = config.get("row_filter", {})
    data = dataframe.copy()

    if target not in data.columns:
        raise ValueError(f"El dataset no contiene el target configurado: {target}")

    if bool(row_filter.get("required_non_null_target", True)):
        before = len(data)
        data = data[data[target].notna()].copy()
        LOGGER.info("Filtro target no nulo: %s -> %s filas", f"{before:,}", f"{len(data):,}")

    if bool(row_filter.get("use_action_filter", False)):
        action_field = row_filter.get("action_field")
        allowed_values = row_filter.get("allowed_action_values") or []
        if action_field not in data.columns:
            raise ValueError(f"No existe action_field para filtrar: {action_field}")
        before = len(data)
        data = data[data[action_field].isin(allowed_values)].copy()
        LOGGER.info(
            "Filtro xy_accion aplicado en %s: %s -> %s filas",
            action_field,
            f"{before:,}",
            f"{len(data):,}",
        )

    if data.empty:
        raise ValueError("El dataset quedó vacío después de aplicar filtros.")

    return data.reset_index(drop=True)


def _estimate_metric_crs(gdf: Any, configured_metric_crs: str | int | None) -> Any:
    if configured_metric_crs and str(configured_metric_crs).lower() != "auto":
        return configured_metric_crs
    try:
        return gdf.estimate_utm_crs()
    except Exception:
        LOGGER.warning("No se pudo estimar CRS métrico; se usará EPSG:3857 como respaldo.")
        return "EPSG:3857"


def apply_border_filter(
    dataframe: pd.DataFrame,
    config: dict[str, Any],
    output_dir: Path,
) -> pd.DataFrame:
    """Mark and optionally remove points closer than threshold to their quadrant boundary."""
    spatial_cfg = config.get("spatial_filter", {})
    if not bool(spatial_cfg.get("exclude_near_quadrant_border", False)):
        data = dataframe.copy()
        data["distance_to_quadrant_border_m"] = np.nan
        data["border_excluded"] = False
        pd.DataFrame(
            [
                {
                    "enabled": False,
                    "method": "not_applied",
                    "threshold_m": np.nan,
                    "n_input": len(data),
                    "n_excluded": 0,
                    "pct_excluded": 0.0,
                    "n_kept": len(data),
                }
            ]
        ).to_csv(
            output_dir / "tables" / "border_filter_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )
        LOGGER.info(
            "Filtro de borde desactivado por configuración: "
            "spatial_filter.exclude_near_quadrant_border=false"
        )
        return data

    try:
        import geopandas as gpd
    except ImportError as error:  # pragma: no cover
        raise ImportError(
            "spatial_filter.exclude_near_quadrant_border=true requiere geopandas. "
            "Instalar geopandas o desactivar el filtro espacial."
        ) from error

    key = config["fields"]["key"]
    group_field = config["fields"]["group"]
    threshold_m = float(spatial_cfg.get("border_distance_m", 1000))
    if threshold_m <= 0:
        raise ValueError("spatial_filter.border_distance_m debe ser mayor que 0 cuando el filtro está activo.")
    method = str(spatial_cfg.get("method", "own_quadrant_boundary"))
    if method != "own_quadrant_boundary":
        raise ValueError(
            "Por ahora solo está implementado spatial_filter.method='own_quadrant_boundary'. "
            "Es un filtro conservador: excluye puntos a menos del umbral del borde de su cuadrante."
        )

    a4_4_gpkg = resolve_path(config["paths"].get("a4_4_gpkg", config["paths"].get("modeling_gpkg", "")))
    a4_gpkg = resolve_path(config["paths"].get("a4_gpkg", ""))
    points_layer = config.get("layers", {}).get("points_layer", "pilot_xy_point")
    quadrants_layer = config.get("layers", {}).get("quadrants_layer", "pilot_quadrant")

    if not a4_4_gpkg.exists():
        raise FileNotFoundError(f"No existe GPKG A4.4 para leer puntos: {a4_4_gpkg}")
    if not a4_gpkg.exists():
        raise FileNotFoundError(f"No existe GPKG A4 para leer cuadrantes: {a4_gpkg}")

    LOGGER.info("Filtro espacial: leyendo puntos %s desde %s", points_layer, a4_4_gpkg)
    points = gpd.read_file(a4_4_gpkg, layer=points_layer)
    LOGGER.info("Filtro espacial: leyendo cuadrantes %s desde %s", quadrants_layer, a4_gpkg)
    quadrants = gpd.read_file(a4_gpkg, layer=quadrants_layer)

    for field, label in [(key, points_layer), (group_field, quadrants_layer)]:
        if field not in (points.columns if label == points_layer else quadrants.columns):
            raise ValueError(f"No existe campo '{field}' en {label}.")

    if points.crs is None:
        raise ValueError(f"La capa {points_layer} no tiene CRS definido.")
    if quadrants.crs is None:
        raise ValueError(f"La capa {quadrants_layer} no tiene CRS definido.")

    points = points[[key, points.geometry.name]].copy()
    points[key] = points[key].astype(str).str.strip()
    data = dataframe.copy()
    data[key] = data[key].astype(str).str.strip()
    data[group_field] = data[group_field].astype(str).str.strip()

    points = points.merge(data[[key, group_field]], on=key, how="inner", validate="one_to_one")
    if len(points) != len(data):
        raise ValueError(
            f"No se pudo empatar todo el dataset con geometrías: dataset={len(data):,}, geometrías={len(points):,}."
        )

    metric_crs = _estimate_metric_crs(points, spatial_cfg.get("metric_crs", "auto"))
    LOGGER.info("Filtro espacial: reproyectando a CRS métrico %s", metric_crs)
    points_m = points.to_crs(metric_crs)
    quadrants_m = quadrants[[group_field, quadrants.geometry.name]].copy().to_crs(metric_crs)
    quadrants_m[group_field] = quadrants_m[group_field].astype(str).str.strip()

    # Si hay más de una geometría por cuadrante, se disuelve para tener una geometría única por grupo.
    quadrants_m = quadrants_m.dissolve(by=group_field, as_index=False)
    quadrants_m["quadrant_boundary"] = quadrants_m.geometry.boundary
    boundary_lookup = dict(zip(quadrants_m[group_field], quadrants_m["quadrant_boundary"]))

    missing_quadrants = sorted(set(points_m[group_field]) - set(boundary_lookup))
    if missing_quadrants:
        raise ValueError(f"Hay puntos con cuadrantes que no existen en {quadrants_layer}: {missing_quadrants[:10]}")

    LOGGER.info("Calculando distancia al borde de cuadrante con umbral %.1f m", threshold_m)
    distances = []
    # 102k puntos es pequeño para esta operación piloto; se privilegia claridad.
    for geom, group_id in zip(points_m.geometry, points_m[group_field]):
        distances.append(float(geom.distance(boundary_lookup[group_id])))

    distance_table = pd.DataFrame({key: points_m[key].to_numpy(), "distance_to_quadrant_border_m": distances})
    data = data.merge(distance_table, on=key, how="left", validate="one_to_one")
    data["border_excluded"] = data["distance_to_quadrant_border_m"] < threshold_m

    removed = data[data["border_excluded"]].copy()
    kept = data[~data["border_excluded"]].copy()
    removed_path = output_dir / "tables" / "border_excluded_points.csv"
    summary_path = output_dir / "tables" / "border_filter_summary.csv"
    removed[[key, group_field, "distance_to_quadrant_border_m"]].to_csv(removed_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {
                "enabled": True,
                "method": method,
                "threshold_m": threshold_m,
                "n_input": len(data),
                "n_excluded": len(removed),
                "pct_excluded": len(removed) / len(data) if len(data) else np.nan,
                "n_kept": len(kept),
            }
        ]
    ).to_csv(summary_path, index=False, encoding="utf-8-sig")

    LOGGER.info(
        "Filtro borde de cuadrante: entrada=%s | excluidos=%s | conservados=%s",
        f"{len(data):,}",
        f"{len(removed):,}",
        f"{len(kept):,}",
    )
    return data.reset_index(drop=True)


def make_group_splitter(method: str, n_splits: int, shuffle: bool, random_state: int | None):
    method = method.lower()
    if method == "stratified_group_kfold":
        if StratifiedGroupKFold is None:
            raise ImportError("La versión instalada de scikit-learn no tiene StratifiedGroupKFold.")
        return StratifiedGroupKFold(n_splits=n_splits, shuffle=shuffle, random_state=random_state)
    if method == "group_kfold":
        if shuffle:
            LOGGER.warning("GroupKFold no usa shuffle en versiones antiguas de scikit-learn; se ignorará shuffle.")
        return GroupKFold(n_splits=n_splits)
    raise ValueError(f"Método de partición no soportado: {method}")


def _class_distribution_error(y_all: np.ndarray, y_holdout: np.ndarray) -> float:
    """L1 difference between global and holdout class proportions."""
    classes = sorted(set(y_all))
    all_counts = pd.Series(y_all).value_counts(normalize=True)
    hold_counts = pd.Series(y_holdout).value_counts(normalize=True)
    error = 0.0
    for cls in classes:
        error += abs(float(all_counts.get(cls, 0.0)) - float(hold_counts.get(cls, 0.0)))
    return error


def build_quadrant_class_profile(data: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """Build a quadrant-by-class profile used to document the spatial split design."""
    group_field = config["fields"]["group"]
    target = config["fields"]["target"]
    label_field = config.get("fields", {}).get("target_label")
    class_labels = build_target_label_mapping(data, config)

    base = data[[group_field, target]].copy()
    base[group_field] = base[group_field].astype(str).str.strip()
    base[target] = base[target].astype(str).str.strip()

    counts = (
        base.groupby([group_field, target], dropna=False)
        .size()
        .reset_index(name="n_points")
    )
    total = base.groupby(group_field).size().rename("n_points_quadrant").reset_index()
    counts = counts.merge(total, on=group_field, how="left", validate="many_to_one")
    counts["pct_points_quadrant"] = counts["n_points"] / counts["n_points_quadrant"]
    counts = add_target_labels(counts, target, label_field, class_labels)
    return counts.sort_values([group_field, target]).reset_index(drop=True)


def _candidate_holdout_metrics(
    data: pd.DataFrame,
    mask: pd.Series,
    config: dict[str, Any],
    candidate_id: str,
    class_labels: dict[str, str],
    seed: int | None = None,
    fold_id: int | None = None,
) -> dict[str, Any]:
    group_field = config["fields"]["group"]
    target = config["fields"]["target"]
    iv_cfg = config.get("independent_validation", {})

    y_all = data[target].astype(str).str.strip().to_numpy()
    y_ind = data.loc[mask, target].astype(str).str.strip().to_numpy()
    y_dev = data.loc[~mask, target].astype(str).str.strip().to_numpy()

    all_classes = set(y_all)
    ind_classes = set(y_ind)
    dev_classes = set(y_dev)
    missing_ind = sorted(all_classes - ind_classes)
    missing_dev = sorted(all_classes - dev_classes)

    n_rows = int(mask.sum())
    n_total = int(len(data))
    pct_rows = float(n_rows / n_total) if n_total else np.nan

    all_groups = set(data[group_field].astype(str).str.strip())
    ind_groups = set(data.loc[mask, group_field].astype(str).str.strip())
    n_groups = len(ind_groups)
    n_total_groups = len(all_groups)
    pct_groups = float(n_groups / n_total_groups) if n_total_groups else np.nan

    target_fraction = float(iv_cfg.get("holdout_fraction", 1.0 / float(iv_cfg.get("n_candidate_splits", 5))))
    distribution_error = _class_distribution_error(y_all, y_ind) if n_rows else np.inf
    row_fraction_error = abs(pct_rows - target_fraction) if np.isfinite(pct_rows) else np.inf
    group_fraction_error = abs(pct_groups - target_fraction) if np.isfinite(pct_groups) else np.inf

    # Criterio automático simple: semejanza de la distribución de clases y
    # cercanía a la fracción de filas solicitada. No se asignan pesos distintos
    # a clases, regiones, predictores ni cuadrantes.
    score = distribution_error + row_fraction_error

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
        "selection_score": float(score),
        "valid_for_modeling": bool(n_rows > 0 and len(y_dev) > 0 and not missing_dev),
        "holdout_group_ids": "|".join(sorted(ind_groups)),
        "selected": False,
    }


def select_independent_holdout(
    data: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.Series, pd.DataFrame]:
    """Select whole quadrants for independent validation.

    The selection unit is always fields.group, i.e. id_cuadrante.  The default
    strategy generates StratifiedGroupKFold candidate holdouts and selects, among
    the valid candidates, the one with the smallest class-distribution error plus
    row-fraction error. A candidate is valid when every class present in its
    holdout also exists in development. No geographic label is introduced.
    """
    group_field = config["fields"]["group"]
    target = config["fields"]["target"]
    iv_cfg = config.get("independent_validation", {})

    if iv_cfg.get("optimization"):
        LOGGER.warning(
            "independent_validation.optimization está presente, pero sus pesos "
            "ya no se usan. La selección aplica únicamente distribution_error + "
            "row_fraction_error."
        )

    if not bool(iv_cfg.get("enabled", True)):
        LOGGER.warning("independent_validation.enabled=false; no habrá validación independiente.")
        return pd.Series(False, index=data.index), pd.DataFrame()

    data = data.copy()
    data[group_field] = data[group_field].astype(str).str.strip()
    data[target] = data[target].astype(str).str.strip()
    class_labels = build_target_label_mapping(data, config)
    groups = data[group_field].to_numpy()
    y = data[target].to_numpy()

    explicit_groups = [str(value).strip() for value in iv_cfg.get("explicit_group_ids", []) if str(value).strip()]
    if explicit_groups:
        mask = pd.Series(data[group_field].isin(explicit_groups), index=data.index)
        if not mask.any():
            raise ValueError("independent_validation.explicit_group_ids no seleccionó ningún cuadrante.")
        metrics = _candidate_holdout_metrics(
            data,
            mask,
            config,
            candidate_id="explicit",
            class_labels=class_labels,
            seed=None,
            fold_id=None,
        )
        metrics["selected"] = True
        LOGGER.info("Validación independiente por cuadrantes explícitos: %s", explicit_groups)
        return mask, pd.DataFrame([metrics])

    method = str(iv_cfg.get("method", "stratified_group_holdout")).lower()
    n_candidate_splits = int(iv_cfg.get("n_candidate_splits", 5))
    selected_candidate_id = iv_cfg.get("selected_candidate_id", None)
    random_state = int(iv_cfg.get("random_state", 42))
    shuffle = bool(iv_cfg.get("shuffle", True))
    n_random_repeats = int(iv_cfg.get("n_random_repeats", 1))

    if method not in ["optimized_stratified_group_holdout", "stratified_group_holdout", "group_holdout"]:
        raise ValueError(f"independent_validation.method no soportado: {method}")

    splitter_method = "stratified_group_kfold" if method in ["optimized_stratified_group_holdout", "stratified_group_holdout"] else "group_kfold"
    X_dummy = np.zeros((len(data), 1), dtype=np.int8)
    candidates: list[dict[str, Any]] = []
    masks_by_candidate: dict[str, pd.Series] = {}

    seed_values = [random_state] if method != "optimized_stratified_group_holdout" else list(range(random_state, random_state + n_random_repeats))

    for seed in seed_values:
        splitter = make_group_splitter(splitter_method, n_candidate_splits, shuffle=shuffle, random_state=seed)
        for fold_id, (_, holdout_idx) in enumerate(splitter.split(X_dummy, y, groups=groups)):
            holdout_groups = set(groups[holdout_idx])
            mask = pd.Series(data[group_field].isin(holdout_groups), index=data.index)
            candidate_id = f"seed_{seed}_fold_{fold_id}"
            metrics = _candidate_holdout_metrics(
                data,
                mask,
                config,
                candidate_id=candidate_id,
                class_labels=class_labels,
                seed=seed,
                fold_id=fold_id,
            )
            candidates.append(metrics)
            masks_by_candidate[candidate_id] = mask

    candidates_df = pd.DataFrame(candidates)
    if candidates_df.empty:
        raise ValueError("No se pudieron generar candidatos de validación independiente.")

    if selected_candidate_id is None:
        eligible = candidates_df[candidates_df["valid_for_modeling"].astype(bool)].copy()
        if eligible.empty:
            raise ValueError(
                "Ningún candidato de holdout es válido: en todos aparece al menos "
                "una clase que no existe en el conjunto de desarrollo."
            )
        order = eligible.sort_values(
            ["selection_score", "class_distribution_error", "row_fraction_error", "candidate_id"],
            ascending=[True, True, True, True],
        )
        selected_candidate_id = str(order.iloc[0]["candidate_id"])
    else:
        selected_candidate_id = str(selected_candidate_id)
        if selected_candidate_id not in masks_by_candidate:
            raise ValueError(
                f"selected_candidate_id='{selected_candidate_id}' no existe entre los candidatos generados."
            )

    candidates_df.loc[candidates_df["candidate_id"].astype(str) == selected_candidate_id, "selected"] = True
    mask = masks_by_candidate[selected_candidate_id]

    LOGGER.info(
        "Validación independiente seleccionada: candidate=%s | filas=%s | cuadrantes=%s | clases=%s",
        selected_candidate_id,
        f"{int(mask.sum()):,}",
        f"{data.loc[mask, group_field].nunique():,}",
        f"{data.loc[mask, target].nunique():,}",
    )

    return mask, candidates_df


def build_cv_splits(
    development: pd.DataFrame,
    config: dict[str, Any],
) -> list[tuple[np.ndarray, np.ndarray]]:
    group_field = config["fields"]["group"]
    target = config["fields"]["target"]
    cv_cfg = config.get("inner_cv", {})
    method = str(cv_cfg.get("method", "stratified_group_kfold"))
    n_splits = int(cv_cfg.get("n_splits", 5))
    shuffle = bool(cv_cfg.get("shuffle", True))
    random_state = cv_cfg.get("random_state", 42)

    n_groups = development[group_field].nunique()
    if n_groups < n_splits:
        raise ValueError(f"No hay suficientes grupos para CV: grupos={n_groups}, n_splits={n_splits}")

    splitter = make_group_splitter(method, n_splits, shuffle=shuffle, random_state=random_state)
    y = development[target].astype(str).str.strip().to_numpy()
    groups = development[group_field].astype(str).str.strip().to_numpy()
    X_dummy = np.zeros((len(development), 1), dtype=np.int8)
    splits = list(splitter.split(X_dummy, y, groups=groups))

    # Controles mínimos de validez. No se exige que todas las clases globales
    # aparezcan en cada fold, porque su distribución espacial puede impedirlo.
    # Sí se exige que una clase observada en validación haya sido vista durante
    # el entrenamiento de ese fold.
    for fold_id, (train_idx, val_idx) in enumerate(splits, start=1):
        train_groups = set(groups[train_idx])
        val_groups = set(groups[val_idx])
        overlap = train_groups & val_groups
        if overlap:
            raise ValueError(f"Leakage espacial en fold {fold_id}: grupos compartidos {sorted(overlap)[:10]}")

        train_classes = set(y[train_idx])
        validation_classes = set(y[val_idx])
        unseen_validation_classes = sorted(validation_classes - train_classes)
        if unseen_validation_classes:
            raise ValueError(
                f"Fold {fold_id} inválido: contiene clases en validación ausentes "
                f"del entrenamiento: {unseen_validation_classes}. Reducir n_splits, "
                "cambiar la semilla o revisar la representación por cuadrante."
            )

    LOGGER.info("CV interna preparada: method=%s | folds=%s | grupos_desarrollo=%s", method, n_splits, n_groups)
    return splits


def prepare_partitions(dataframe: pd.DataFrame, config: dict[str, Any], output_dir: Path) -> PartitionData:
    key = config["fields"]["key"]
    group_field = config["fields"]["group"]
    target = config["fields"]["target"]
    label_field = config.get("fields", {}).get("target_label")
    class_labels = build_target_label_mapping(dataframe, config)

    data_with_border = apply_border_filter(dataframe, config, output_dir=output_dir)
    modelable = data_with_border[~data_with_border["border_excluded"]].copy().reset_index(drop=True)
    if modelable.empty:
        raise ValueError("No quedan puntos modelables después del filtro de borde.")

    quadrant_profile = build_quadrant_class_profile(modelable, config)
    quadrant_profile.to_csv(output_dir / "tables" / "quadrant_class_profile.csv", index=False, encoding="utf-8-sig")

    independent_mask, independent_candidates = select_independent_holdout(modelable, config)
    independent = modelable[independent_mask].copy().reset_index(drop=True)
    development = modelable[~independent_mask].copy().reset_index(drop=True)

    if bool(config.get("independent_validation", {}).get("enabled", True)) and independent.empty:
        raise ValueError("La validación independiente quedó vacía.")
    if development.empty:
        raise ValueError("El conjunto de desarrollo quedó vacío.")

    dev_groups = set(development[group_field].astype(str))
    ind_groups = set(independent[group_field].astype(str))
    overlap = dev_groups & ind_groups
    if overlap:
        raise ValueError(f"Leakage entre desarrollo y validación independiente: {sorted(overlap)[:10]}")

    # Verificar que toda clase de validación independiente exista en desarrollo para poder predecirla con un clasificador supervisado.
    dev_classes = set(development[target].astype(str))
    ind_classes = set(independent[target].astype(str))
    unseen = ind_classes - dev_classes
    if unseen:
        raise ValueError(
            "La validación independiente contiene clases ausentes del desarrollo. "
            f"Clases sin entrenamiento: {sorted(unseen)}"
        )

    cv_splits = build_cv_splits(development, config)

    # Asignación global por punto: incluye excluidos por borde, desarrollo y validación independiente.
    base_cols = [key, group_field, target]
    if label_field:
        base_cols.append(str(label_field))
    assignments = data_with_border[base_cols + ["distance_to_quadrant_border_m", "border_excluded"]].copy()
    assignments["split_role"] = "development_cv"
    assignments.loc[assignments["border_excluded"], "split_role"] = "excluded_border"

    independent_keys = set(independent[key].astype(str))
    assignments.loc[assignments[key].astype(str).isin(independent_keys), "split_role"] = "independent_validation"
    assignments["cv_validation_fold_id"] = pd.NA

    dev_key_by_pos = development[key].astype(str).reset_index(drop=True)
    cv_assignment_rows = []
    for fold_id, (train_idx, val_idx) in enumerate(cv_splits, start=1):
        train_keys = set(dev_key_by_pos.iloc[train_idx])
        val_keys = set(dev_key_by_pos.iloc[val_idx])
        assignments.loc[assignments[key].astype(str).isin(val_keys), "cv_validation_fold_id"] = fold_id

        train_part = development.iloc[train_idx][base_cols].copy()
        train_part["fold_id"] = fold_id
        train_part["cv_role"] = "cv_train"
        val_part = development.iloc[val_idx][base_cols].copy()
        val_part["fold_id"] = fold_id
        val_part["cv_role"] = "cv_validation"
        cv_assignment_rows.extend([train_part, val_part])

        if train_keys & val_keys:
            raise ValueError(f"Leakage interno en fold {fold_id}: un punto aparece en train y validation.")

    cv_assignments = pd.concat(cv_assignment_rows, ignore_index=True) if cv_assignment_rows else pd.DataFrame()
    cv_assignments = add_target_labels(cv_assignments, target, label_field, class_labels)
    cv_assignments.to_csv(output_dir / "tables" / "cv_fold_assignments.csv", index=False, encoding="utf-8-sig")

    if not independent_candidates.empty:
        independent_candidates.to_csv(output_dir / "tables" / "independent_validation_candidates.csv", index=False, encoding="utf-8-sig")
        selected_groups = independent_candidates.loc[independent_candidates["selected"].astype(bool)].copy()
        selected_groups.to_csv(output_dir / "tables" / "selected_independent_quadrants.csv", index=False, encoding="utf-8-sig")

    assignments = add_target_labels(assignments, target, label_field, class_labels)
    assignments.to_csv(output_dir / "tables" / "split_assignments.csv", index=False, encoding="utf-8-sig")

    LOGGER.info(
        "Particiones: excluidos_borde=%s | desarrollo=%s | validacion_independiente=%s",
        f"{int((assignments['split_role'] == 'excluded_border').sum()):,}",
        f"{len(development):,}",
        f"{len(independent):,}",
    )

    return PartitionData(
        dataframe_all=data_with_border,
        dataframe_modelable=modelable,
        dataframe_development=development,
        dataframe_independent=independent,
        split_assignments=assignments,
        cv_splits=cv_splits,
    )


def prepare_xy(
    dataframe: pd.DataFrame,
    feature_columns: list[str],
    target: str,
    encoder: LabelEncoder | None = None,
) -> tuple[pd.DataFrame, np.ndarray, LabelEncoder]:
    X = dataframe[feature_columns].copy()
    for col in feature_columns:
        X[col] = pd.to_numeric(X[col], errors="coerce")

    y_raw = dataframe[target].astype(str).str.strip().to_numpy()
    if encoder is None:
        encoder = LabelEncoder()
        y = encoder.fit_transform(y_raw)
    else:
        y = encoder.transform(y_raw)
    return X, y, encoder


def build_pipeline(config: dict[str, Any]) -> Pipeline:
    model_cfg = config.get("model", {})
    rf = RandomForestClassifier(
        random_state=int(model_cfg.get("random_state", 42)),
        n_jobs=int(model_cfg.get("n_jobs", -1)),
        class_weight=model_cfg.get("class_weight", "balanced_subsample"),
        oob_score=bool(model_cfg.get("oob_score", False)),
    )
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy=model_cfg.get("imputer_strategy", "median"))),
            ("clf", rf),
        ]
    )


def normalize_param_grid(config: dict[str, Any]) -> dict[str, list[Any]]:
    grid = config.get("grid_search", {}).get("param_grid", {})
    if not isinstance(grid, dict) or not grid:
        raise ValueError("grid_search.param_grid debe ser un diccionario no vacío.")
    normalized: dict[str, list[Any]] = {}
    for key, value in grid.items():
        if not isinstance(value, list):
            value = [value]
        normalized[key] = value
    return normalized


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


def run_grid_search(
    development: pd.DataFrame,
    feature_columns: list[str],
    cv_splits: list[tuple[np.ndarray, np.ndarray]],
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[GridSearchCV, LabelEncoder, pd.DataFrame, np.ndarray, np.ndarray]:
    target = config["fields"]["target"]
    group_field = config["fields"]["group"]
    X_dev, y_dev, encoder = prepare_xy(development, feature_columns, target=target, encoder=None)
    groups_dev = development[group_field].astype(str).str.strip().to_numpy()

    pipeline = build_pipeline(config)
    param_grid = normalize_param_grid(config)
    gs_cfg = config.get("grid_search", {})
    scoring = gs_cfg.get("scoring", {
        "accuracy": "accuracy",
        "balanced_accuracy": "balanced_accuracy",
        "f1_macro": "f1_macro",
    })
    refit = gs_cfg.get("refit", "f1_macro")

    LOGGER.info("Iniciando GridSearchCV: combinaciones=%s", np.prod([len(v) for v in param_grid.values()]))
    search = GridSearchCV(
        estimator=pipeline,
        param_grid=param_grid,
        scoring=scoring,
        refit=refit,
        cv=cv_splits,
        n_jobs=int(gs_cfg.get("n_jobs", -1)),
        verbose=int(gs_cfg.get("verbose", 1)),
        return_train_score=bool(gs_cfg.get("return_train_score", True)),
        error_score=gs_cfg.get("error_score", "raise"),
    )
    search.fit(X_dev, y_dev, groups=groups_dev)

    results = pd.DataFrame(search.cv_results_)
    results_path = output_dir / "tables" / "gridsearch_results.csv"
    results.to_csv(results_path, index=False, encoding="utf-8-sig")

    best_params_path = output_dir / "tables" / "best_params.json"
    best_params_path.write_text(json.dumps(search.best_params_, indent=2, ensure_ascii=False), encoding="utf-8")

    LOGGER.info("GridSearchCV finalizado. Best score=%s | best_params=%s", search.best_score_, search.best_params_)
    return search, encoder, X_dev, y_dev, groups_dev


def evaluate_best_model_cv(
    search: GridSearchCV,
    development: pd.DataFrame,
    X_dev: pd.DataFrame,
    y_dev: np.ndarray,
    encoder: LabelEncoder,
    cv_splits: list[tuple[np.ndarray, np.ndarray]],
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    key = config["fields"]["key"]
    group_field = config["fields"]["group"]
    best_estimator = search.best_estimator_
    class_labels = build_target_label_mapping(development, config)

    predictions = np.full(shape=len(y_dev), fill_value=-1, dtype=int)
    fold_rows = []
    pred_rows = []

    for fold_id, (train_idx, val_idx) in enumerate(cv_splits, start=1):
        estimator = clone(best_estimator)
        estimator.fit(X_dev.iloc[train_idx], y_dev[train_idx])
        val_pred = estimator.predict(X_dev.iloc[val_idx])
        predictions[val_idx] = val_pred
        fold_rows.append(metric_row(y_dev[val_idx], val_pred, label=f"cv_fold_{fold_id}"))
        for local_idx, pred in zip(val_idx, val_pred):
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

    fold_metrics = pd.DataFrame(fold_rows)
    # Estos resultados OOF describen el comportamiento interno de la
    # configuración elegida. Como los hiperparámetros se escogieron usando los
    # mismos folds, se reportan como diagnóstico de tuning, no como una segunda
    # evaluación independiente.
    overall_cv = pd.DataFrame([metric_row(y_dev, predictions, label="cv_oof_tuning_diagnostic")])
    class_metrics = classification_report_df(
        y_dev,
        predictions,
        encoder,
        evaluation="cv_oof_tuning_diagnostic",
        class_labels=class_labels,
    )
    confusion = confusion_matrix_df(
        y_dev,
        predictions,
        encoder,
        evaluation="cv_oof_tuning_diagnostic",
        class_labels=class_labels,
    )
    fold_predictions = pd.DataFrame(pred_rows)

    fold_metrics.to_csv(output_dir / "tables" / "cv_fold_metrics.csv", index=False, encoding="utf-8-sig")
    overall_cv.to_csv(output_dir / "tables" / "cv_overall_metrics.csv", index=False, encoding="utf-8-sig")
    class_metrics.to_csv(output_dir / "tables" / "cv_class_metrics.csv", index=False, encoding="utf-8-sig")
    confusion.to_csv(output_dir / "tables" / "cv_confusion_matrix.csv", index=False, encoding="utf-8-sig")
    fold_predictions.to_csv(output_dir / "tables" / "cv_fold_predictions.csv", index=False, encoding="utf-8-sig")

    return overall_cv, fold_metrics, class_metrics, confusion


def evaluate_independent(
    search: GridSearchCV,
    development: pd.DataFrame,
    independent: pd.DataFrame,
    feature_columns: list[str],
    encoder: LabelEncoder,
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    target = config["fields"]["target"]
    key = config["fields"]["key"]
    group_field = config["fields"]["group"]

    # Reentrena el mejor modelo en todo el conjunto de desarrollo.
    X_dev, y_dev, _ = prepare_xy(development, feature_columns, target=target, encoder=encoder)
    estimator = clone(search.best_estimator_)
    estimator.fit(X_dev, y_dev)

    X_ind, y_ind, _ = prepare_xy(independent, feature_columns, target=target, encoder=encoder)
    class_labels = build_target_label_mapping(
        pd.concat([development, independent], ignore_index=True),
        config,
    )

    # Desempeño aparente del modelo ya ajustado sobre el mismo desarrollo.
    # Se reporta como diagnóstico de sobreajuste, no como validación independiente.
    y_dev_pred = estimator.predict(X_dev)
    training_metrics = pd.DataFrame(
        [metric_row(y_dev, y_dev_pred, label="training_development_resubstitution")]
    )
    training_class_metrics = classification_report_df(
        y_dev,
        y_dev_pred,
        encoder,
        evaluation="training_development_resubstitution",
        class_labels=class_labels,
    )
    training_confusion = confusion_matrix_df(
        y_dev,
        y_dev_pred,
        encoder,
        evaluation="training_development_resubstitution",
        class_labels=class_labels,
    )

    y_pred = estimator.predict(X_ind)
    y_true_classes = encoder.inverse_transform(y_ind).astype(str)
    y_pred_classes = encoder.inverse_transform(y_pred).astype(str)

    metrics = pd.DataFrame([metric_row(y_ind, y_pred, label="independent_validation")])
    class_metrics = classification_report_df(
        y_ind,
        y_pred,
        encoder,
        evaluation="independent_validation",
        class_labels=class_labels,
    )
    confusion = confusion_matrix_df(
        y_ind,
        y_pred,
        encoder,
        evaluation="independent_validation",
        class_labels=class_labels,
    )

    predictions = pd.DataFrame(
        {
            key: independent[key].to_numpy(),
            group_field: independent[group_field].to_numpy(),
            "split_role": "independent_validation",
            "y_true": y_true_classes,
            "y_true_label": [class_labels.get(value) for value in y_true_classes],
            "y_pred": y_pred_classes,
            "y_pred_label": [class_labels.get(value) for value in y_pred_classes],
        }
    )

    training_metrics.to_csv(output_dir / "tables" / "training_metrics.csv", index=False, encoding="utf-8-sig")
    training_class_metrics.to_csv(
        output_dir / "tables" / "training_class_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    training_confusion.to_csv(
        output_dir / "tables" / "training_confusion_matrix.csv",
        index=False,
        encoding="utf-8-sig",
    )
    metrics.to_csv(output_dir / "tables" / "independent_metrics.csv", index=False, encoding="utf-8-sig")
    class_metrics.to_csv(output_dir / "tables" / "independent_class_metrics.csv", index=False, encoding="utf-8-sig")
    confusion.to_csv(output_dir / "tables" / "independent_confusion_matrix.csv", index=False, encoding="utf-8-sig")
    predictions.to_csv(output_dir / "tables" / "independent_predictions.csv", index=False, encoding="utf-8-sig")

    model_path = output_dir / config["outputs"].get("model_development_path", "models/rf_best_development.joblib")
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": estimator,
            "label_encoder": encoder,
            "feature_columns": feature_columns,
            "target": target,
            "target_label": config.get("fields", {}).get("target_label"),
            "target_is_homologated": True,
            "trained_on": "development_only",
            "best_params": search.best_params_,
            "classes": encoder.classes_.tolist(),
            "class_labels": class_labels,
        },
        model_path,
    )
    LOGGER.info("Modelo seleccionado entrenado en desarrollo guardado: %s", model_path)

    if bool(config.get("outputs", {}).get("train_final_model_on_modelable_after_independent_eval", False)):
        all_modelable = pd.concat([development, independent], ignore_index=True)
        X_all, y_all, _ = prepare_xy(all_modelable, feature_columns, target=target, encoder=encoder)
        final_estimator = clone(search.best_estimator_)
        final_estimator.fit(X_all, y_all)
        final_path = output_dir / config["outputs"].get("model_all_modelable_path", "models/rf_best_all_modelable.joblib")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": final_estimator,
                "label_encoder": encoder,
                "feature_columns": feature_columns,
                "target": target,
                "target_label": config.get("fields", {}).get("target_label"),
                "target_is_homologated": True,
                "trained_on": "all_modelable_after_independent_evaluation",
                "best_params": search.best_params_,
                "classes": encoder.classes_.tolist(),
                "class_labels": class_labels,
            },
            final_path,
        )
        LOGGER.info("Modelo final entrenado en todo lo modelable guardado: %s", final_path)

    return (
        training_metrics,
        training_class_metrics,
        training_confusion,
        metrics,
        class_metrics,
        confusion,
    )


def write_feature_importance(search: GridSearchCV, feature_columns: list[str], output_dir: Path) -> None:
    best = search.best_estimator_
    clf = best.named_steps.get("clf")
    if not hasattr(clf, "feature_importances_"):
        LOGGER.warning("El estimador seleccionado no expone feature_importances_.")
        return
    importance = pd.DataFrame(
        {
            "feature": feature_columns,
            "importance": clf.feature_importances_,
        }
    ).sort_values("importance", ascending=False)
    importance.to_csv(output_dir / "tables" / "feature_importance.csv", index=False, encoding="utf-8-sig")


def write_balance_tables(partitions: PartitionData, config: dict[str, Any], output_dir: Path) -> None:
    group_field = config["fields"]["group"]
    target = config["fields"]["target"]
    label_field = config.get("fields", {}).get("target_label")
    class_labels = build_target_label_mapping(partitions.dataframe_all, config)

    split_balance = (
        partitions.split_assignments.groupby(["split_role", target], dropna=False)
        .agg(n_points=(target, "size"), n_groups=(group_field, "nunique"))
        .reset_index()
        .sort_values(["split_role", target])
    )
    split_balance = add_target_labels(split_balance, target, label_field, class_labels)
    split_balance.to_csv(output_dir / "tables" / "split_class_balance.csv", index=False, encoding="utf-8-sig")

    dev = partitions.dataframe_development.copy().reset_index(drop=True)
    rows = []
    for fold_id, (train_idx, val_idx) in enumerate(partitions.cv_splits, start=1):
        for role, idx in [("cv_train", train_idx), ("cv_validation", val_idx)]:
            part = dev.iloc[idx]
            grouped = part.groupby(target).agg(n_points=(target, "size"), n_groups=(group_field, "nunique")).reset_index()
            grouped.insert(0, "fold_id", fold_id)
            grouped.insert(1, "cv_role", role)
            rows.append(grouped)
    fold_balance = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    fold_balance = add_target_labels(fold_balance, target, label_field, class_labels)
    fold_balance.to_csv(output_dir / "tables" / "cv_fold_class_balance.csv", index=False, encoding="utf-8-sig")


def write_report(
    config: dict[str, Any],
    output_dir: Path,
    feature_columns: list[str],
    partitions: PartitionData,
    search: GridSearchCV,
    cv_overall: pd.DataFrame,
    cv_fold_metrics: pd.DataFrame,
    cv_class_metrics: pd.DataFrame,
    cv_confusion: pd.DataFrame,
    training_metrics: pd.DataFrame,
    training_class_metrics: pd.DataFrame,
    training_confusion: pd.DataFrame,
    independent_metrics: pd.DataFrame,
    independent_class_metrics: pd.DataFrame,
    independent_confusion: pd.DataFrame,
) -> None:
    target = config["fields"]["target"]
    target_label = config.get("fields", {}).get("target_label")
    group_field = config["fields"]["group"]
    spatial_cfg = config.get("spatial_filter", {})
    border_filter_enabled = bool(spatial_cfg.get("exclude_near_quadrant_border", False))
    border_threshold_display = (
        f"{spatial_cfg.get('border_distance_m', 'NA')} m"
        if border_filter_enabled
        else "no aplicado"
    )
    class_labels = build_target_label_mapping(partitions.dataframe_all, config)
    label_column = str(target_label or "class_label")
    class_catalog = pd.DataFrame(
        [{target: class_id, label_column: label} for class_id, label in sorted(class_labels.items())]
    )
    class_catalog.to_csv(
        output_dir / "tables" / "class_catalog.csv",
        index=False,
        encoding="utf-8-sig",
    )

    report_path = output_dir / config["outputs"].get("report_md", "reports/a4_7_rf_gridsearch_report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    n_excluded = int((partitions.split_assignments["split_role"] == "excluded_border").sum())
    n_dev = len(partitions.dataframe_development)
    n_ind = len(partitions.dataframe_independent)
    grid_train_validation = best_gridsearch_train_validation_metrics(search)
    grid_train_validation.to_csv(
        output_dir / "tables" / "best_gridsearch_train_validation_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    training_confusion_report = confusion_matrix_for_report(training_confusion)
    cv_confusion_report = confusion_matrix_for_report(cv_confusion)
    independent_confusion_report = confusion_matrix_for_report(independent_confusion)

    lines = [
        "# Actividad 4.7 — Modelo piloto RF con validación espacial y GridSearch",
        "",
        "## Diseño de validación",
        "",
        "La validación independiente se separa antes de GridSearchCV y no participa en la búsqueda de hiperparámetros.",
        "La unidad espacial de partición es el cuadrante (`id_cuadrante`), no la zona.",
        "La validación interna se usa para ajustar y seleccionar la configuración mediante GroupKFold/StratifiedGroupKFold por cuadrante.",
        "No se exige que todas las clases aparezcan en cada fold; solamente que toda clase observada en validación exista en el entrenamiento correspondiente.",
        "La selección automática del holdout usa un criterio simple: distribución de clases y fracción de filas, siempre con cuadrantes completos.",
        "",
        "## Configuración principal",
        "",
        f"- Target: `{target}`",
        f"- Label del target: `{target_label}`",
        f"- Grupo espacial / unidad de partición: `{group_field}`",
        f"- Predictores usados: **{len(feature_columns):,}**",
        f"- Filtro de borde activo: **{border_filter_enabled}**",
        f"- Umbral borde: **{border_threshold_display}**",
        "",
        "## Particiones",
        "",
        "| partición | filas | cuadrantes | clases |",
        "|:--|--:|--:|--:|",
        f"| excluidos por borde | {n_excluded:,} | {partitions.split_assignments.loc[partitions.split_assignments['split_role']=='excluded_border', group_field].nunique():,} | {partitions.split_assignments.loc[partitions.split_assignments['split_role']=='excluded_border', target].nunique():,} |",
        f"| desarrollo train/validación CV | {n_dev:,} | {partitions.dataframe_development[group_field].nunique():,} | {partitions.dataframe_development[target].nunique():,} |",
        f"| validación independiente | {n_ind:,} | {partitions.dataframe_independent[group_field].nunique():,} | {partitions.dataframe_independent[target].nunique():,} |",
        "",
        "## Catálogo de clases homologadas",
        "",
        dataframe_to_markdown(class_catalog),
        "",
        "## GridSearchCV",
        "",
        f"- Mejor score interno: `{search.best_score_}`",
        f"- Mejores hiperparámetros: `{json.dumps(search.best_params_, ensure_ascii=False)}`",
        "",
        "### Comparación train–validación del mejor resultado",
        "",
        dataframe_to_markdown(grid_train_validation),
        "",
        "## Desempeño sobre entrenamiento/desarrollo",
        "",
        "Estas métricas se calculan sobre los mismos datos usados para ajustar el modelo. Son un diagnóstico de sobreajuste y no sustituyen la validación OOF ni la independiente.",
        "",
        "### Métricas generales de entrenamiento",
        "",
        dataframe_to_markdown(training_metrics),
        "",
        "### Métricas de entrenamiento por clase",
        "",
        dataframe_to_markdown(training_class_metrics),
        "",
        "### Matriz de confusión de entrenamiento",
        "",
        "Filas: clase real. Columnas: clase predicha.",
        "",
        dataframe_to_markdown(training_confusion_report),
        "",
        "## Validación cruzada interna para ajuste sobre desarrollo",
        "",
        "Los hiperparámetros se seleccionan usando estos mismos folds. Por ello, las métricas OOF siguientes son un diagnóstico interno del tuning y no sustituyen la validación independiente.",
        "",
        "### Métricas generales OOF de diagnóstico",
        "",
        dataframe_to_markdown(cv_overall),
        "",
        "### Métricas de validación por fold",
        "",
        dataframe_to_markdown(cv_fold_metrics),
        "",
        "### Métricas OOF de diagnóstico por clase",
        "",
        dataframe_to_markdown(cv_class_metrics),
        "",
        "### Matriz de confusión OOF de diagnóstico",
        "",
        "Filas: clase real. Columnas: clase predicha.",
        "",
        dataframe_to_markdown(cv_confusion_report),
        "",
        "## Validación independiente",
        "",
        "### Métricas generales independientes",
        "",
        dataframe_to_markdown(independent_metrics),
        "",
        "### Métricas independientes por clase",
        "",
        dataframe_to_markdown(independent_class_metrics),
        "",
        "### Matriz de confusión independiente",
        "",
        "Filas: clase real. Columnas: clase predicha.",
        "",
        dataframe_to_markdown(independent_confusion_report),
        "",
        "## Nota metodológica",
        "",
        "El modelo usa las clases homologadas. La validación independiente permanece fuera de GridSearchCV y del ajuste del modelo de desarrollo; por ello constituye la estimación principal de generalización espacial dentro del diseño por cuadrantes. El filtro de borde es opcional y no se incorpora ningún criterio adicional de autocorrelación ni etiquetas regionales.",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Reporte escrito: %s", report_path)


def main() -> None:
    config = read_yaml(DEFAULT_CONFIG)
    output_dir = resolve_path(config["paths"]["output_dir"])
    ensure_dirs(output_dir)
    configure_logger(output_dir)
    LOGGER.info("YAML de configuración: %s", DEFAULT_CONFIG)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)

        raw = read_modeling_dataset(config)
        validate_homologated_target(config, raw)
        features = read_feature_columns(config, raw)
        filtered = apply_row_filters(raw, config)
        partitions = prepare_partitions(filtered, config, output_dir)
        write_balance_tables(partitions, config, output_dir)

        search, encoder, X_dev, y_dev, _groups_dev = run_grid_search(
            development=partitions.dataframe_development,
            feature_columns=features,
            cv_splits=partitions.cv_splits,
            config=config,
            output_dir=output_dir,
        )
        cv_overall, fold_metrics, cv_class_metrics, cv_confusion = evaluate_best_model_cv(
            search=search,
            development=partitions.dataframe_development,
            X_dev=X_dev,
            y_dev=y_dev,
            encoder=encoder,
            cv_splits=partitions.cv_splits,
            config=config,
            output_dir=output_dir,
        )
        (
            training_metrics,
            training_class_metrics,
            training_confusion,
            independent_metrics,
            independent_class_metrics,
            independent_confusion,
        ) = evaluate_independent(
            search=search,
            development=partitions.dataframe_development,
            independent=partitions.dataframe_independent,
            feature_columns=features,
            encoder=encoder,
            config=config,
            output_dir=output_dir,
        )
        write_feature_importance(search, features, output_dir)
        write_report(
            config=config,
            output_dir=output_dir,
            feature_columns=features,
            partitions=partitions,
            search=search,
            cv_overall=cv_overall,
            cv_fold_metrics=fold_metrics,
            cv_class_metrics=cv_class_metrics,
            cv_confusion=cv_confusion,
            training_metrics=training_metrics,
            training_class_metrics=training_class_metrics,
            training_confusion=training_confusion,
            independent_metrics=independent_metrics,
            independent_class_metrics=independent_class_metrics,
            independent_confusion=independent_confusion,
        )

    LOGGER.info("Actividad 4.7 finalizada correctamente.")


if __name__ == "__main__":
    main()