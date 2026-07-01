# -*- coding: utf-8 -*-
"""
Muestreo espacial reproducible para el consenso SINAC de bosque deciduo 2021-2023.

Flujo principal:
1. Lee configuración desde YAML.
2. Inspecciona y valida un GeoPackage vectorial.
3. Filtra la clase objetivo en `clase_objetivo`.
4. Repara geometrías, elimina geometrías vacías/no poligonales y aplica área mínima.
5. Reproyecta a un CRS métrico para cálculos de área y distancia.
6. Genera un punto interior por polígono mediante `representative_point()`.
7. Aplica escenarios de separación mínima entre puntos con un filtro greedy reproducible.
8. Exporta capas SIG, tablas CSV, log y reporte Markdown.

Ejecución desde la raíz del repositorio:

    python src/actividad_3/run_bosque_deciduo_sampling.py \
        --config config/bosque_deciduo_sampling.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------
# GDAL/PROJ en Conda/Windows antes de importar GeoPandas/Pyogrio.
# ---------------------------------------------------------------------

def configure_conda_geodata_paths() -> None:
    candidates = {
        "GDAL_DATA": [
            Path(sys.prefix) / "Library" / "share" / "gdal",
            Path(sys.prefix) / "share" / "gdal",
        ],
        "PROJ_LIB": [
            Path(sys.prefix) / "Library" / "share" / "proj",
            Path(sys.prefix) / "share" / "proj",
        ],
    }
    for env_name, paths in candidates.items():
        if os.environ.get(env_name):
            continue
        for path in paths:
            if path.exists():
                os.environ[env_name] = str(path)
                break


configure_conda_geodata_paths()

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import yaml
from pyproj import CRS

try:
    from scipy.spatial import cKDTree
except ImportError:  # pragma: no cover - dependencia opcional
    cKDTree = None


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "bosque_deciduo_sampling.yaml"
LOGGER = logging.getLogger("bosque_deciduo_sampling_sinac")


# ---------------------------------------------------------------------
# Utilidades generales
# ---------------------------------------------------------------------

def configure_logger(log_path: Path | None = None) -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    LOGGER.addHandler(console)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        file_handler.setFormatter(formatter)
        LOGGER.addHandler(file_handler)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el YAML de configuración: {path}")
    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("El YAML no contiene una estructura tipo diccionario.")
    return config


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_text(value: Any) -> str:
    """Normalización robusta para comparar etiquetas temáticas."""
    if pd.isna(value):
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = " ".join(text.split())
    return text


def require_fields(frame: pd.DataFrame, fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in frame.columns]
    if missing:
        raise ValueError(
            f"Faltan campos obligatorios en {label}: {missing}\n"
            f"Campos disponibles: {list(frame.columns)}"
        )


def validate_processing_crs(crs_value: str) -> CRS:
    crs = CRS.from_user_input(crs_value)
    if not crs.is_projected:
        raise ValueError(f"El CRS de procesamiento debe ser proyectado: {crs_value}")
    units = {axis.unit_name.lower() for axis in crs.axis_info if axis.unit_name}
    if not ({"metre", "meter"} & units):
        raise ValueError(
            "El CRS de procesamiento debe usar metros. "
            f"CRS recibido: {crs_value}; unidades: {sorted(units)}"
        )
    return crs


def get_layer(path: Path, configured_layer: str | None) -> str:
    layers = pyogrio.list_layers(path)
    layer_names = layers[:, 0].tolist()

    if configured_layer:
        if configured_layer not in layer_names:
            raise ValueError(
                f"La capa configurada no existe: {configured_layer}. "
                f"Capas disponibles: {layer_names}"
            )
        return configured_layer

    if len(layer_names) == 1:
        return layer_names[0]

    raise ValueError(
        "El GeoPackage tiene más de una capa. Indique inputs.source.layer en el YAML. "
        f"Capas disponibles: {layer_names}"
    )


# ---------------------------------------------------------------------
# Lectura, inspección y preparación geométrica
# ---------------------------------------------------------------------

def inspect_source(path: Path, layer: str) -> dict[str, Any]:
    info = pyogrio.read_info(path, layer=layer)
    crs = CRS.from_user_input(info["crs"]) if info.get("crs") else None
    inspection = {
        "path": str(path),
        "layer": layer,
        "driver": info.get("driver"),
        "features": int(info.get("features", 0)),
        "geometry_type": info.get("geometry_type"),
        "crs": str(info.get("crs")),
        "crs_name": crs.name if crs else None,
        "is_projected": bool(crs.is_projected) if crs else None,
        "fields": list(info.get("fields", [])),
        "dtypes": [str(value) for value in info.get("dtypes", [])],
        "fid_column": info.get("fid_column"),
        "total_bounds": [float(value) for value in info.get("total_bounds", [])],
    }
    return inspection


def read_source(config: dict[str, Any], source_path: Path, layer: str) -> gpd.GeoDataFrame:
    source_cfg = config["inputs"]["source"]
    fields_cfg = source_cfg["fields"]

    required_fields = [fields_cfg["class_field"]]
    source_id_field = fields_cfg.get("source_id_field")
    if source_id_field:
        required_fields.append(source_id_field)

    keep_fields = source_cfg.get("keep_fields", [])
    requested_columns = list(dict.fromkeys(required_fields + keep_fields))

    LOGGER.info("Leyendo fuente: %s | layer=%s", source_path, layer)
    LOGGER.info("Columnas solicitadas: %s", requested_columns)

    gdf = pyogrio.read_dataframe(
        source_path,
        layer=layer,
        columns=requested_columns,
    )

    if gdf.empty:
        raise ValueError(f"La capa está vacía: {source_path} | {layer}")
    if gdf.crs is None:
        raise ValueError(f"La capa no tiene CRS definido: {source_path} | {layer}")

    require_fields(gdf, required_fields, "GeoPackage de consenso SINAC")

    LOGGER.info("Fuente leída | objetos=%s | CRS=%s", f"{len(gdf):,}", gdf.crs)
    return gdf


def repair_geometries(gdf: gpd.GeoDataFrame, label: str) -> tuple[gpd.GeoDataFrame, dict[str, int]]:
    output = gdf.copy()
    stats: dict[str, int] = {
        "input_features": int(len(output)),
        "dropped_null_empty_before": 0,
        "invalid_before": 0,
        "dropped_null_empty_after": 0,
        "invalid_after": 0,
        "dropped_non_polygonal": 0,
        "output_features": 0,
    }

    null_or_empty = output.geometry.isna() | output.geometry.is_empty
    stats["dropped_null_empty_before"] = int(null_or_empty.sum())
    if null_or_empty.any():
        LOGGER.warning(
            "%s | eliminando geometrías nulas/vacías iniciales: %s",
            label,
            f"{stats['dropped_null_empty_before']:,}",
        )
        output = output.loc[~null_or_empty].copy()

    invalid = ~output.geometry.is_valid
    stats["invalid_before"] = int(invalid.sum())
    if invalid.any():
        LOGGER.info("%s | corrigiendo geometrías inválidas: %s", label, f"{stats['invalid_before']:,}")
        try:
            output.loc[invalid, "geometry"] = output.loc[invalid].geometry.make_valid()
        except (AttributeError, NotImplementedError):
            output.loc[invalid, "geometry"] = output.loc[invalid].geometry.buffer(0)

    null_or_empty = output.geometry.isna() | output.geometry.is_empty
    stats["dropped_null_empty_after"] = int(null_or_empty.sum())
    if null_or_empty.any():
        LOGGER.warning(
            "%s | eliminando geometrías vacías después de reparar: %s",
            label,
            f"{stats['dropped_null_empty_after']:,}",
        )
        output = output.loc[~null_or_empty].copy()

    unresolved = ~output.geometry.is_valid
    stats["invalid_after"] = int(unresolved.sum())
    if unresolved.any():
        LOGGER.warning(
            "%s | eliminando geometrías inválidas no resueltas: %s",
            label,
            f"{stats['invalid_after']:,}",
        )
        output = output.loc[~unresolved].copy()

    polygonal = output.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    stats["dropped_non_polygonal"] = int((~polygonal).sum())
    if (~polygonal).any():
        LOGGER.warning(
            "%s | eliminando geometrías no poligonales: %s",
            label,
            f"{stats['dropped_non_polygonal']:,}",
        )
        output = output.loc[polygonal].copy()

    stats["output_features"] = int(len(output))
    return output.reset_index(drop=True), stats


def reproject(gdf: gpd.GeoDataFrame, target_crs: str, label: str) -> gpd.GeoDataFrame:
    if str(gdf.crs) == target_crs:
        LOGGER.info("%s ya está en %s", label, target_crs)
        return gdf.copy()
    LOGGER.info("Reproyectando %s a %s", label, target_crs)
    return gdf.to_crs(target_crs)


def filter_target_class(gdf: gpd.GeoDataFrame, config: dict[str, Any]) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    fields_cfg = config["inputs"]["source"]["fields"]
    class_field = fields_cfg["class_field"]
    target_value = config["sampling"]["target_class_value"]
    target_norm = normalize_text(target_value)

    values = gdf[class_field].map(normalize_text)
    selected = values == target_norm

    distribution = (
        gdf[class_field]
        .fillna("<NULL>")
        .astype(str)
        .value_counts(dropna=False)
        .rename_axis("class_value")
        .reset_index(name="n_features")
    )
    distribution["selected_as_target"] = distribution["class_value"].map(
        lambda value: int(normalize_text(value) == target_norm)
    )

    LOGGER.info(
        "Filtro temático | campo=%s | valor objetivo=%s | seleccionados=%s/%s",
        class_field,
        target_value,
        f"{int(selected.sum()):,}",
        f"{len(gdf):,}",
    )

    output = gdf.loc[selected].copy()
    if output.empty:
        raise ValueError(
            f"El filtro {class_field} = {target_value!r} no devolvió registros. "
            "Revise mayúsculas, acentos o el valor configurado."
        )
    return output.reset_index(drop=True), distribution


def prepare_polygons(gdf: gpd.GeoDataFrame, config: dict[str, Any], processing_crs: str) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    fields_cfg = config["inputs"]["source"]["fields"]
    source_id_field = fields_cfg.get("source_id_field")
    area_field = fields_cfg.get("area_field")
    class_field = fields_cfg["class_field"]

    output = reproject(gdf, processing_crs, "polígonos de bosque deciduo")

    if source_id_field and source_id_field in output.columns:
        output = output.rename(columns={source_id_field: "source_polygon_id"})
        id_origin = f"campo:{source_id_field}"
    else:
        output["source_polygon_id"] = np.arange(1, len(output) + 1, dtype=np.int64)
        id_origin = "generado_desde_orden_lectura"

    if class_field != "clase_objetivo":
        output = output.rename(columns={class_field: "clase_objetivo"})

    output["source_id_origin"] = id_origin
    output["source_area_ha"] = output.geometry.area / 10_000.0

    if area_field and area_field in output.columns:
        output["source_area_attr_ha"] = pd.to_numeric(output[area_field], errors="coerce")
    else:
        output["source_area_attr_ha"] = np.nan

    output["area_difference_abs_ha"] = (
        output["source_area_attr_ha"] - output["source_area_ha"]
    ).abs()

    minimum_area_ha = float(config.get("geometry", {}).get("minimum_area_ha", 0.0))
    before_area = len(output)
    if minimum_area_ha > 0:
        output = output.loc[output["source_area_ha"] >= minimum_area_ha].copy()
        LOGGER.info(
            "Filtro por área mínima %.6f ha | descartados=%s | remanentes=%s",
            minimum_area_ha,
            f"{before_area - len(output):,}",
            f"{len(output):,}",
        )

    if output.empty:
        raise ValueError("No quedaron polígonos después de aplicar el área mínima.")

    output["processed_polygon_id"] = np.arange(1, len(output) + 1, dtype=np.int64)
    output["source_name"] = config["project"]["source_name"]
    output["base_year"] = str(config["project"].get("base_year", "2021-2023"))

    summary = pd.DataFrame(
        [
            {
                "n_input_target_polygons": int(before_area),
                "n_processed_polygons": int(len(output)),
                "n_dropped_by_minimum_area": int(before_area - len(output)),
                "minimum_area_ha": minimum_area_ha,
                "total_area_ha": float(output["source_area_ha"].sum()),
                "mean_area_ha": float(output["source_area_ha"].mean()),
                "median_area_ha": float(output["source_area_ha"].median()),
                "min_area_ha": float(output["source_area_ha"].min()),
                "max_area_ha": float(output["source_area_ha"].max()),
                "source_id_origin": id_origin,
            }
        ]
    )

    first_fields = [
        "processed_polygon_id",
        "source_polygon_id",
        "source_id_origin",
        "clase_objetivo",
        "source_area_ha",
        "source_area_attr_ha",
        "area_difference_abs_ha",
        "source_name",
        "base_year",
    ]

    extra_fields = [
        field
        for field in output.columns
        if field not in first_fields and field != "geometry"
    ]

    return output[first_fields + extra_fields + ["geometry"]].reset_index(drop=True), summary


# ---------------------------------------------------------------------
# Generación y selección de puntos
# ---------------------------------------------------------------------

def create_candidate_points(polygons: gpd.GeoDataFrame, config: dict[str, Any]) -> gpd.GeoDataFrame:
    method = config.get("sampling", {}).get("representative_point_method", "point_on_surface")
    if method not in {"point_on_surface", "representative_point"}:
        raise ValueError("Solo se admite representative_point_method: point_on_surface/representative_point")

    LOGGER.info("Generando un punto interior por polígono procesado")
    attrs = polygons.drop(columns="geometry").copy()
    points = gpd.GeoDataFrame(
        attrs,
        geometry=polygons.geometry.representative_point(),
        crs=polygons.crs,
    )

    valid = ~(points.geometry.isna() | points.geometry.is_empty)
    if (~valid).any():
        LOGGER.warning("Candidatos con geometría vacía descartados: %s", f"{int((~valid).sum()):,}")
        points = points.loc[valid].copy()

    points["candidate_id"] = np.arange(1, len(points) + 1, dtype=np.int64)
    prefix = config.get("outputs", {}).get("point_id_prefix", "SINAC_BD")
    points["point_id"] = points["candidate_id"].map(lambda value: f"{prefix}_{int(value):07d}")
    points["extraction_method"] = "representative_point_per_polygon"

    first_fields = [
        "candidate_id",
        "point_id",
        "processed_polygon_id",
        "source_polygon_id",
        "clase_objetivo",
        "source_area_ha",
        "source_name",
        "base_year",
        "extraction_method",
    ]

    extra_fields = [field for field in points.columns if field not in first_fields and field != "geometry"]
    LOGGER.info("Puntos candidatos generados: %s", f"{len(points):,}")
    return points[first_fields + extra_fields + ["geometry"]].reset_index(drop=True)


def order_candidates(points: gpd.GeoDataFrame, selection_order: list[str]) -> gpd.GeoDataFrame:
    output = points.copy()
    source_numeric = pd.to_numeric(output["source_polygon_id"], errors="coerce")
    if source_numeric.notna().all():
        output["_source_sort"] = source_numeric.astype(float)
    else:
        output["_source_sort"] = output["source_polygon_id"].astype("string").fillna("")

    sort_fields: list[str] = []
    ascending: list[bool] = []

    for rule in selection_order:
        if rule == "area_desc":
            sort_fields.append("source_area_ha")
            ascending.append(False)
        elif rule == "area_asc":
            sort_fields.append("source_area_ha")
            ascending.append(True)
        elif rule in {"source_id_asc", "objectid_asc"}:
            sort_fields.append("_source_sort")
            ascending.append(True)
        elif rule in {"source_id_desc", "objectid_desc"}:
            sort_fields.append("_source_sort")
            ascending.append(False)
        elif rule == "candidate_id_asc":
            sort_fields.append("candidate_id")
            ascending.append(True)
        else:
            raise ValueError(f"Regla de orden no reconocida: {rule}")

    if "candidate_id" not in sort_fields:
        sort_fields.append("candidate_id")
        ascending.append(True)

    output = output.sort_values(sort_fields, ascending=ascending, kind="mergesort")
    return output.drop(columns="_source_sort").reset_index(drop=True)


def thin_points_by_distance(
    points: gpd.GeoDataFrame,
    distance_m: float,
    selection_order: list[str],
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    if distance_m <= 0:
        raise ValueError("La distancia mínima debe ser mayor que cero.")

    ordered = order_candidates(points, selection_order).reset_index(drop=True)
    ordered["ordered_row_id"] = np.arange(len(ordered), dtype=np.int64)

    cell_size = float(distance_m)
    distance_sq = cell_size * cell_size
    spatial_cells: dict[tuple[int, int], list[int]] = {}
    accepted_coords: list[tuple[float, float]] = []
    accepted_candidate_ids: list[int] = []
    accepted_ordered_row_ids: list[int] = []
    audit_rows: list[dict[str, Any]] = []

    for selection_order_id, row in enumerate(ordered.itertuples(index=False), start=1):
        candidate_id = int(row.candidate_id)
        x = float(row.geometry.x)
        y = float(row.geometry.y)
        cell_x = math.floor(x / cell_size)
        cell_y = math.floor(y / cell_size)
        blocker_candidate_id: int | None = None
        blocker_distance_m: float | None = None

        for dx in (-1, 0, 1):
            if blocker_candidate_id is not None:
                break
            for dy in (-1, 0, 1):
                neighbor_key = (cell_x + dx, cell_y + dy)
                for accepted_index in spatial_cells.get(neighbor_key, []):
                    accepted_x, accepted_y = accepted_coords[accepted_index]
                    delta_x = x - accepted_x
                    delta_y = y - accepted_y
                    candidate_distance_sq = delta_x * delta_x + delta_y * delta_y
                    if candidate_distance_sq < distance_sq:
                        blocker_candidate_id = accepted_candidate_ids[accepted_index]
                        blocker_distance_m = math.sqrt(candidate_distance_sq)
                        break
                if blocker_candidate_id is not None:
                    break

        selected = blocker_candidate_id is None
        if selected:
            accepted_index = len(accepted_coords)
            accepted_coords.append((x, y))
            accepted_candidate_ids.append(candidate_id)
            accepted_ordered_row_ids.append(int(row.ordered_row_id))
            spatial_cells.setdefault((cell_x, cell_y), []).append(accepted_index)
            selection_reason = "selected_distance"
        else:
            selection_reason = "within_minimum_distance"

        audit_rows.append(
            {
                "distance_m": int(distance_m),
                "candidate_id": candidate_id,
                "point_id": row.point_id,
                "source_polygon_id": row.source_polygon_id,
                "selection_order": selection_order_id,
                "selected": int(selected),
                "blocker_candidate_id": blocker_candidate_id,
                "blocker_distance_m": blocker_distance_m,
                "selection_reason": selection_reason,
            }
        )

    selected_points = ordered.loc[ordered["ordered_row_id"].isin(accepted_ordered_row_ids)].copy()
    selected_points = selected_points.drop(columns="ordered_row_id")
    selected_points["distance_scenario_m"] = int(distance_m)
    selected_points["selection_status"] = "selected_distance"
    selected_points["nearest_neighbor_m"] = calculate_nearest_neighbor_distance(selected_points)

    audit = pd.DataFrame(audit_rows)
    return selected_points.reset_index(drop=True), audit


def calculate_nearest_neighbor_distance(points: gpd.GeoDataFrame) -> pd.Series:
    n_points = len(points)
    if n_points == 0:
        return pd.Series(dtype="float64")
    if n_points == 1:
        return pd.Series([np.nan], index=points.index, dtype="float64")
    if cKDTree is None:
        LOGGER.warning("SciPy no está disponible. nearest_neighbor_m se dejará vacío.")
        return pd.Series(np.nan, index=points.index, dtype="float64")

    coords = np.column_stack((points.geometry.x.to_numpy(), points.geometry.y.to_numpy()))
    tree = cKDTree(coords)
    distances, _ = tree.query(coords, k=2)
    return pd.Series(distances[:, 1], index=points.index, dtype="float64")


# ---------------------------------------------------------------------
# Resúmenes, reporte y exportación
# ---------------------------------------------------------------------

def summarize_scenarios(selected_layers: dict[int, gpd.GeoDataFrame], n_candidates: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for distance_m, gdf in selected_layers.items():
        nn = gdf["nearest_neighbor_m"] if "nearest_neighbor_m" in gdf.columns else pd.Series(dtype="float64")
        rows.append(
            {
                "distance_m": int(distance_m),
                "n_candidates": int(n_candidates),
                "n_selected": int(len(gdf)),
                "n_rejected": int(n_candidates - len(gdf)),
                "pct_selected": float(100.0 * len(gdf) / n_candidates) if n_candidates else 0.0,
                "total_source_area_ha_selected": float(gdf["source_area_ha"].sum()) if len(gdf) else 0.0,
                "mean_nearest_neighbor_m": float(nn.mean()) if len(nn.dropna()) else np.nan,
                "min_nearest_neighbor_m": float(nn.min()) if len(nn.dropna()) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("distance_m").reset_index(drop=True)


def summarize_processed_polygons(polygons: gpd.GeoDataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "n_processed_polygons": int(len(polygons)),
                "total_area_ha": float(polygons["source_area_ha"].sum()),
                "mean_area_ha": float(polygons["source_area_ha"].mean()),
                "median_area_ha": float(polygons["source_area_ha"].median()),
                "min_area_ha": float(polygons["source_area_ha"].min()),
                "p05_area_ha": float(polygons["source_area_ha"].quantile(0.05)),
                "p25_area_ha": float(polygons["source_area_ha"].quantile(0.25)),
                "p75_area_ha": float(polygons["source_area_ha"].quantile(0.75)),
                "p95_area_ha": float(polygons["source_area_ha"].quantile(0.95)),
                "max_area_ha": float(polygons["source_area_ha"].max()),
                "n_source_polygons_unique": int(polygons["source_polygon_id"].nunique(dropna=True)),
            }
        ]
    )


def build_candidate_selection_matrix(candidate_points: gpd.GeoDataFrame, selection_audit: pd.DataFrame) -> pd.DataFrame:
    base_fields = [
        "candidate_id",
        "point_id",
        "source_polygon_id",
        "clase_objetivo",
        "source_area_ha",
        "source_name",
        "base_year",
    ]
    matrix = candidate_points[base_fields].copy()
    pivot = selection_audit.pivot_table(
        index="candidate_id",
        columns="distance_m",
        values="selected",
        aggfunc="max",
        fill_value=0,
    )
    pivot.columns = [f"selected_d{int(distance):04d}" for distance in pivot.columns]
    pivot = pivot.reset_index()
    matrix = matrix.merge(pivot, on="candidate_id", how="left", validate="one_to_one")
    for column in [col for col in matrix.columns if col.startswith("selected_d")]:
        matrix[column] = matrix[column].fillna(0).astype(int)
    return matrix


def make_run_metadata(
    config: dict[str, Any],
    config_path: Path,
    inspection: dict[str, Any],
    processing_crs: str,
    output_crs: str,
) -> pd.DataFrame:
    metadata = {
        "project_name": config["project"]["name"],
        "source_name": config["project"]["source_name"],
        "base_year": str(config["project"].get("base_year", "2021-2023")),
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "source_path": inspection["path"],
        "source_layer": inspection["layer"],
        "source_features": inspection["features"],
        "source_crs": inspection["crs"],
        "processing_crs": processing_crs,
        "output_crs": output_crs,
        "target_class_field": config["inputs"]["source"]["fields"]["class_field"],
        "target_class_value": config["sampling"]["target_class_value"],
        "thinning_distances_m": ",".join(str(v) for v in config["sampling"].get("thinning_distances_m", [])),
        "configuration_json": json.dumps(config, ensure_ascii=False),
    }
    return pd.DataFrame({"key": list(metadata.keys()), "value": [str(v) for v in metadata.values()]})


def write_spatial_layer(gdf: gpd.GeoDataFrame, gpkg_path: Path, layer_name: str, output_crs: str) -> None:
    output = gdf.copy()
    if output.crs is None:
        raise ValueError(f"La capa {layer_name} no tiene CRS.")
    output = output.to_crs(output_crs)
    LOGGER.info("Exportando capa: %s | objetos=%s", layer_name, f"{len(output):,}")
    output.to_file(gpkg_path, layer=layer_name, driver="GPKG", index=False)


def register_attribute_table(connection: sqlite3.Connection, table_name: str) -> None:
    last_change = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%fZ")
    connection.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (table_name,))
    connection.execute(
        """
        INSERT INTO gpkg_contents
        (table_name, data_type, identifier, description, last_change)
        VALUES (?, 'attributes', ?, '', ?)
        """,
        (table_name, table_name, last_change),
    )


def write_nonspatial_table(dataframe: pd.DataFrame, gpkg_path: Path, table_name: str) -> None:
    LOGGER.info("Exportando tabla GeoPackage: %s | filas=%s", table_name, f"{len(dataframe):,}")
    table = dataframe.astype(object).where(pd.notna(dataframe), None)
    with sqlite3.connect(gpkg_path) as connection:
        table.to_sql(table_name, connection, if_exists="replace", index=False)
        register_attribute_table(connection, table_name)
        connection.commit()


def export_csv_tables(output_tables_dir: Path, tables: dict[str, pd.DataFrame]) -> None:
    ensure_directory(output_tables_dir)
    for filename, dataframe in tables.items():
        path = output_tables_dir / f"{filename}.csv"
        LOGGER.info("Exportando CSV: %s", path)
        dataframe.to_csv(path, index=False, encoding="utf-8-sig")


def write_report(
    report_path: Path,
    inspection: dict[str, Any],
    geometry_stats: dict[str, int],
    class_distribution: pd.DataFrame,
    polygon_summary: pd.DataFrame,
    scenario_summary: pd.DataFrame,
    run_metadata: pd.DataFrame,
) -> None:
    ensure_directory(report_path.parent)
    meta = dict(zip(run_metadata["key"], run_metadata["value"]))
    poly = polygon_summary.iloc[0].to_dict()

    scenario_md = scenario_summary.to_markdown(index=False)
    class_md = class_distribution.to_markdown(index=False)

    content = f"""# Reporte de muestreo SINAC - bosque deciduo 2021-2023

## Identificación del proceso

- Proyecto: {meta.get('project_name')}
- Fuente: {meta.get('source_name')}
- Año base: {meta.get('base_year')}
- Fecha de ejecución UTC: {meta.get('run_utc')}
- Capa de entrada: `{inspection['layer']}`
- CRS de entrada: `{inspection['crs']}` ({inspection.get('crs_name')})
- CRS de procesamiento: `{meta.get('processing_crs')}`
- CRS de salida: `{meta.get('output_crs')}`

## Inspección de entrada

- Objetos reportados por la capa: {inspection['features']:,}
- Tipo geométrico reportado: {inspection['geometry_type']}
- Campos disponibles: {', '.join(inspection['fields'])}
- Bounds de entrada: {inspection['total_bounds']}

## Filtro temático

Campo de clase: `{meta.get('target_class_field')}`  
Valor objetivo: `{meta.get('target_class_value')}`

{class_md}

## Control geométrico

- Geometrías de entrada al control: {geometry_stats['input_features']:,}
- Geometrías nulas/vacías descartadas antes de reparar: {geometry_stats['dropped_null_empty_before']:,}
- Geometrías inválidas detectadas antes de reparar: {geometry_stats['invalid_before']:,}
- Geometrías nulas/vacías descartadas después de reparar: {geometry_stats['dropped_null_empty_after']:,}
- Geometrías inválidas no resueltas descartadas: {geometry_stats['invalid_after']:,}
- Geometrías no poligonales descartadas: {geometry_stats['dropped_non_polygonal']:,}
- Geometrías válidas después del control: {geometry_stats['output_features']:,}

## Resumen de polígonos procesados

- Polígonos procesados: {int(poly['n_processed_polygons']):,}
- Área total procesada: {float(poly['total_area_ha']):,.2f} ha
- Área media: {float(poly['mean_area_ha']):,.4f} ha
- Área mediana: {float(poly['median_area_ha']):,.4f} ha
- Área mínima: {float(poly['min_area_ha']):,.8f} ha
- Área máxima: {float(poly['max_area_ha']):,.2f} ha

## Escenarios de separación mínima

{scenario_md}

## Criterio metodológico

El flujo genera un punto interior por polígono mediante `representative_point()`. Posteriormente aplica una selección greedy reproducible con separación mínima global por escenario. La prioridad de selección se controla desde el YAML mediante `sampling.selection_order`; por defecto se priorizan polígonos de mayor área y luego el identificador de fuente.

## Advertencias metodológicas

- El filtro temático se realiza de forma robusta ante mayúsculas, espacios y acentos, pero conserva el valor original en la salida.
- El CRS de procesamiento debe ser métrico. Para Costa Rica se recomienda `EPSG:8908` cuando la fuente ya está en CR-SIRGAS / CRTM05.
- Los escenarios de distancia mínima no sustituyen una validación temática independiente; solamente controlan densidad y autocorrelación espacial aproximada.
- La existencia de muchos polígonos pequeños puede reflejar una fuente derivada de raster o intersecciones. El parámetro `geometry.minimum_area_ha` permite controlar fragmentos residuales.
"""
    report_path.write_text(content, encoding="utf-8")
    LOGGER.info("Reporte Markdown exportado: %s", report_path)


# ---------------------------------------------------------------------
# Ejecución principal
# ---------------------------------------------------------------------

def run(config_path: Path) -> None:
    config_path = config_path.resolve()
    config = load_yaml(config_path)

    source_path = resolve_repo_path(config["inputs"]["source"]["path"])
    if not source_path.exists():
        raise FileNotFoundError(f"No existe el GeoPackage de entrada: {source_path}")

    outputs_cfg = config["outputs"]
    geodata_dir = resolve_repo_path(outputs_cfg.get("geodata_dir", "outputs/geodata"))
    tables_dir = resolve_repo_path(outputs_cfg.get("tables_dir", "outputs/tables"))
    reports_dir = resolve_repo_path(outputs_cfg.get("reports_dir", "outputs/reports"))
    logs_dir = resolve_repo_path(outputs_cfg.get("logs_dir", "logs"))

    for directory in [geodata_dir, tables_dir, reports_dir, logs_dir]:
        ensure_directory(directory)

    log_path = logs_dir / outputs_cfg.get("log_name", "bosque_deciduo_sampling_sinac.log")
    configure_logger(log_path)

    gpkg_path = geodata_dir / outputs_cfg.get("gpkg_name", "bosque_deciduo_sampling_sinac.gpkg")
    if gpkg_path.exists():
        LOGGER.info("Eliminando GeoPackage previo: %s", gpkg_path)
        gpkg_path.unlink()

    crs_cfg = config.get("crs", {})
    processing_crs = crs_cfg.get("processing_crs")
    output_crs = crs_cfg.get("output_crs", "EPSG:4326")
    if not processing_crs:
        raise ValueError("El YAML debe incluir crs.processing_crs")
    validate_processing_crs(processing_crs)
    CRS.from_user_input(output_crs)

    layer = get_layer(source_path, config["inputs"]["source"].get("layer"))
    inspection = inspect_source(source_path, layer)
    LOGGER.info("Inspección inicial: %s", json.dumps(inspection, ensure_ascii=False))

    raw = read_source(config, source_path, layer)
    target, class_distribution = filter_target_class(raw, config)

    if config.get("geometry", {}).get("repair_invalid", True):
        target, geometry_stats = repair_geometries(target, "consenso SINAC bosque deciduo")
    else:
        geometry_stats = {
            "input_features": int(len(target)),
            "dropped_null_empty_before": 0,
            "invalid_before": int((~target.geometry.is_valid).sum()),
            "dropped_null_empty_after": 0,
            "invalid_after": 0,
            "dropped_non_polygonal": 0,
            "output_features": int(len(target)),
        }

    polygons, area_filter_summary = prepare_polygons(target, config, processing_crs)
    candidate_points = create_candidate_points(polygons, config)

    distances = [int(value) for value in config["sampling"].get("thinning_distances_m", [])]
    if not distances:
        raise ValueError("Debe indicar al menos una distancia en sampling.thinning_distances_m")

    selection_order = config["sampling"].get("selection_order", ["area_desc", "source_id_asc"])
    selected_layers: dict[int, gpd.GeoDataFrame] = {}
    audit_parts: list[pd.DataFrame] = []

    for distance_m in distances:
        LOGGER.info("Aplicando escenario de separación mínima: %s m", f"{distance_m:,}")
        selected, audit = thin_points_by_distance(candidate_points, distance_m, selection_order)
        selected_layers[distance_m] = selected
        audit_parts.append(audit)
        LOGGER.info(
            "Escenario %s m | seleccionados=%s | rechazados=%s",
            f"{distance_m:,}",
            f"{len(selected):,}",
            f"{len(candidate_points) - len(selected):,}",
        )

    selection_audit = pd.concat(audit_parts, ignore_index=True)
    scenario_summary = summarize_scenarios(selected_layers, len(candidate_points))
    processed_polygon_summary = summarize_processed_polygons(polygons)
    candidate_selection_matrix = build_candidate_selection_matrix(candidate_points, selection_audit)
    run_metadata = make_run_metadata(config, config_path, inspection, processing_crs, output_crs)

    layer_names = outputs_cfg.get("layers", {})
    write_spatial_layer(
        polygons,
        gpkg_path,
        layer_names.get("processed_polygons", "bosque_deciduo_sinac_poligonos_procesados"),
        output_crs,
    )
    write_spatial_layer(
        candidate_points,
        gpkg_path,
        layer_names.get("candidate_points", "bosque_deciduo_sinac_puntos_candidatos"),
        output_crs,
    )

    selected_prefix = layer_names.get("selected_prefix", "bosque_deciduo_sinac_puntos_d")
    for distance_m, selected in selected_layers.items():
        write_spatial_layer(selected, gpkg_path, f"{selected_prefix}{distance_m:04d}", output_crs)

    nonspatial_tables = {
        layer_names.get("class_distribution", "bosque_deciduo_sinac_distribucion_clases"): class_distribution,
        layer_names.get("area_filter_summary", "bosque_deciduo_sinac_resumen_filtro_area"): area_filter_summary,
        layer_names.get("processed_polygon_summary", "bosque_deciduo_sinac_resumen_poligonos"): processed_polygon_summary,
        layer_names.get("scenario_summary", "bosque_deciduo_sinac_resumen_escenarios"): scenario_summary,
        layer_names.get("selection_audit", "bosque_deciduo_sinac_auditoria_seleccion"): selection_audit,
        layer_names.get("candidate_selection_matrix", "bosque_deciduo_sinac_matriz_candidatos"): candidate_selection_matrix,
        layer_names.get("run_metadata", "bosque_deciduo_sinac_run_metadata"): run_metadata,
    }
    for table_name, dataframe in nonspatial_tables.items():
        write_nonspatial_table(dataframe, gpkg_path, table_name)

    if outputs_cfg.get("export_csv", True):
        export_csv_tables(
            tables_dir,
            {
                "bosque_deciduo_sinac_distribucion_clases": class_distribution,
                "bosque_deciduo_sinac_resumen_filtro_area": area_filter_summary,
                "bosque_deciduo_sinac_resumen_poligonos": processed_polygon_summary,
                "bosque_deciduo_sinac_resumen_escenarios": scenario_summary,
                "bosque_deciduo_sinac_auditoria_seleccion": selection_audit,
                "bosque_deciduo_sinac_matriz_candidatos": candidate_selection_matrix,
                "bosque_deciduo_sinac_run_metadata": run_metadata,
            },
        )

    report_path = reports_dir / outputs_cfg.get(
        "report_name",
        "bosque_deciduo_sampling_sinac_reporte.md",
    )
    write_report(
        report_path,
        inspection,
        geometry_stats,
        class_distribution,
        processed_polygon_summary,
        scenario_summary,
        run_metadata,
    )

    LOGGER.info("Proceso finalizado correctamente.")
    LOGGER.info("GeoPackage: %s", gpkg_path)
    LOGGER.info("Tablas CSV: %s", tables_dir)
    LOGGER.info("Reporte: %s", report_path)
    LOGGER.info("Log: %s", log_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Muestreo espacial para consenso SINAC de bosque deciduo 2021-2023."
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"Ruta al YAML. Por defecto: {DEFAULT_CONFIG}",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(Path(args.config))
