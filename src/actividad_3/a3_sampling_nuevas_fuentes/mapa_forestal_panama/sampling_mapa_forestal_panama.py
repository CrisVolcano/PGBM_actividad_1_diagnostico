#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Muestreo reproducible sobre el raster recortado del mapa forestal de Panama.

El flujo replica la logica general de sampling.py para fuentes raster:
1. Lee un GeoTIFF tematico y su VAT lateral.
2. Genera una malla de puntos candidatos en CRS metrico.
3. Muestrea el valor del raster y lo homologa con Classvalue/Class_name.
4. Protege representacion minima por clase.
5. Aplica escenarios de separacion minima global.
6. Exporta GeoPackage, CSV, reporte Markdown y log.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapefile
import yaml
from pyproj import CRS
from shapely.geometry import box

try:
    from scipy.spatial import cKDTree
except ImportError:  # pragma: no cover
    cKDTree = None


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[4]
DEFAULT_CONFIG = REPO_ROOT / "config" / "mapa_forestal_panama_sampling.yaml"
LOGGER = logging.getLogger("mapa_forestal_panama_sampling")


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
        raise FileNotFoundError(f"No existe el YAML: {path}")
    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("El YAML no contiene una estructura valida.")
    return config


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


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


def read_cpg(path: Path | None) -> str:
    if path is None or not path.exists():
        return "utf-8"
    value = path.read_text(encoding="ascii", errors="ignore").strip()
    return value or "utf-8"


def read_vat_table(config: dict[str, Any]) -> pd.DataFrame:
    raster_cfg = config["inputs"]["raster"]
    dbf_path = resolve_repo_path(raster_cfg["vat_dbf"])
    cpg_value = raster_cfg.get("vat_cpg")
    cpg_path = resolve_repo_path(cpg_value) if cpg_value else None
    if not dbf_path.exists():
        raise FileNotFoundError(f"No existe la tabla VAT: {dbf_path}")

    encoding = read_cpg(cpg_path)
    reader = shapefile.Reader(dbf=str(dbf_path), encoding=encoding)
    field_names = [field[0] for field in reader.fields[1:]]
    rows = [dict(zip(field_names, record)) for record in reader.records()]
    vat = pd.DataFrame(rows)
    if vat.empty:
        raise ValueError(f"La tabla VAT esta vacia: {dbf_path}")

    fields = raster_cfg["fields"]
    required = [
        fields["raster_value"],
        fields["class_value"],
        fields["class_name"],
    ]
    missing = [field for field in required if field not in vat.columns]
    if missing:
        raise ValueError(f"Faltan campos en VAT: {missing}; disponibles: {list(vat.columns)}")

    vat = vat.rename(
        columns={
            fields["raster_value"]: "raster_value",
            fields["class_value"]: "class_value",
            fields["class_name"]: "class_name",
            fields.get("class_name_en", "Name_Eng"): "class_name_en",
            fields.get("red", "Red"): "red",
            fields.get("green", "Green"): "green",
            fields.get("blue", "Blue"): "blue",
            "Count": "pixel_count",
        }
    )
    vat["raster_value"] = pd.to_numeric(vat["raster_value"], errors="coerce").astype("Int64")
    vat["class_value"] = pd.to_numeric(vat["class_value"], errors="coerce").astype("Int64")
    vat["class_name"] = vat["class_name"].astype("string").str.strip()
    if "class_name_en" in vat.columns:
        vat["class_name_en"] = vat["class_name_en"].astype("string").str.strip()
    else:
        vat["class_name_en"] = pd.NA
    for color in ["red", "green", "blue"]:
        if color in vat.columns:
            vat[color] = pd.to_numeric(vat[color], errors="coerce").astype("Int64")
        else:
            vat[color] = pd.NA
    if "pixel_count" in vat.columns:
        vat["pixel_count"] = pd.to_numeric(vat["pixel_count"], errors="coerce").fillna(0)
    else:
        vat["pixel_count"] = 0

    return vat[
        [
            "raster_value",
            "class_value",
            "class_name",
            "class_name_en",
            "red",
            "green",
            "blue",
            "pixel_count",
        ]
    ].copy()


def inspect_raster(raster_path: Path, band: int, processing_crs: str) -> dict[str, Any]:
    with rasterio.open(raster_path) as src:
        if src.count < band:
            raise ValueError(f"El raster no tiene la banda solicitada: {band}")
        if src.crs is None:
            raise ValueError(f"El raster no tiene CRS: {raster_path}")
        if CRS.from_user_input(src.crs) != CRS.from_user_input(processing_crs):
            LOGGER.warning(
                "El CRS del raster (%s) difiere del CRS de procesamiento (%s). "
                "Se usara el CRS del raster para la malla.",
                src.crs,
                processing_crs,
            )
        dtype = np.dtype(src.dtypes[band - 1])
        if not np.issubdtype(dtype, np.integer):
            raise ValueError(f"El raster tematico debe ser entero; tipo encontrado: {dtype}")
        return {
            "path": str(raster_path),
            "crs": str(src.crs),
            "width": int(src.width),
            "height": int(src.height),
            "bounds": [float(v) for v in src.bounds],
            "resolution_x": float(abs(src.transform.a)),
            "resolution_y": float(abs(src.transform.e)),
            "dtype": str(dtype),
            "band_count": int(src.count),
            "nodata": src.nodata,
        }


def build_class_catalog(vat: pd.DataFrame, pixel_area_ha: float) -> pd.DataFrame:
    catalog = vat.copy()
    catalog["raster_area_ha"] = catalog["pixel_count"] * pixel_area_ha
    catalog["stratum_id"] = (
        catalog["class_value"].astype("string")
        + " | "
        + catalog["class_name"].fillna("SIN_CLASE").astype("string")
    )
    return catalog.sort_values("raster_value").reset_index(drop=True)


def create_raster_footprint(raster_path: Path) -> gpd.GeoDataFrame:
    with rasterio.open(raster_path) as src:
        geom = box(*src.bounds)
        return gpd.GeoDataFrame(
            {"footprint_id": [1], "source_raster": [raster_path.name]},
            geometry=[geom],
            crs=src.crs,
        )


def create_candidate_points(
    raster_path: Path,
    vat: pd.DataFrame,
    config: dict[str, Any],
) -> gpd.GeoDataFrame:
    raster_cfg = config["inputs"]["raster"]
    band = int(raster_cfg.get("band", 1))
    nodata_cfg = raster_cfg.get("nodata")
    spacing = float(config["sampling"]["candidate_spacing_m"])
    if spacing <= 0:
        raise ValueError("sampling.candidate_spacing_m debe ser mayor que cero.")

    value_lookup = vat.set_index("raster_value")
    with rasterio.open(raster_path) as src:
        nodata = src.nodata if nodata_cfg is None else nodata_cfg
        minx, miny, maxx, maxy = src.bounds
        xs = np.arange(minx + spacing / 2.0, maxx, spacing)
        ys = np.arange(miny + spacing / 2.0, maxy, spacing)
        if len(xs) == 0 or len(ys) == 0:
            raise ValueError("La malla no produjo candidatos. Revise candidate_spacing_m.")
        mesh_x, mesh_y = np.meshgrid(xs, ys)
        coordinates = list(zip(mesh_x.ravel(), mesh_y.ravel()))
        sampled = [value[0] for value in src.sample(coordinates, indexes=band)]
        crs = src.crs

    candidates = pd.DataFrame(
        {
            "x": mesh_x.ravel(),
            "y": mesh_y.ravel(),
            "raster_value": sampled,
        }
    )
    candidates["raster_value"] = pd.to_numeric(candidates["raster_value"], errors="coerce")
    valid = candidates["raster_value"].notna()
    if nodata is not None:
        valid &= candidates["raster_value"] != float(nodata)
    candidates = candidates.loc[valid].copy()
    candidates["raster_value"] = candidates["raster_value"].astype(int)
    candidates = candidates.loc[candidates["raster_value"].isin(value_lookup.index)].copy()
    if candidates.empty:
        raise ValueError("No quedaron candidatos validos despues de muestrear el raster.")

    attrs = value_lookup.loc[candidates["raster_value"]].reset_index(drop=True)
    candidates = pd.concat([candidates.reset_index(drop=True), attrs.reset_index(drop=True)], axis=1)
    candidates["candidate_id"] = np.arange(1, len(candidates) + 1, dtype=np.int64)
    prefix = config["outputs"].get("point_id_prefix", "PAN_FCL")
    candidates["point_id"] = candidates["candidate_id"].map(lambda value: f"{prefix}_{int(value):07d}")
    candidates["source_name"] = config["project"]["source_name"]
    candidates["base_year"] = int(config["project"]["base_year"])
    candidates["country"] = config["project"].get("country", "Panama")
    candidates["candidate_spacing_m"] = spacing
    candidates["extraction_method"] = "regular_grid_sample_valid_raster_pixels"
    candidates["stratum_id"] = (
        candidates["class_value"].astype("string")
        + " | "
        + candidates["class_name"].fillna("SIN_CLASE").astype("string")
    )
    candidates["class_area_ha"] = candidates["pixel_count"].astype(float) * 0.01

    gdf = gpd.GeoDataFrame(
        candidates.drop(columns=["x", "y"]),
        geometry=gpd.points_from_xy(candidates["x"], candidates["y"]),
        crs=crs,
    )

    first_fields = [
        "candidate_id",
        "point_id",
        "raster_value",
        "class_value",
        "class_name",
        "class_name_en",
        "stratum_id",
        "pixel_count",
        "class_area_ha",
        "red",
        "green",
        "blue",
        "source_name",
        "base_year",
        "country",
        "candidate_spacing_m",
        "extraction_method",
        "geometry",
    ]
    LOGGER.info(
        "Puntos candidatos generados: %s | clases=%s",
        f"{len(gdf):,}",
        f"{gdf['stratum_id'].nunique():,}",
    )
    return gdf[first_fields].reset_index(drop=True)


def order_candidates(points: gpd.GeoDataFrame, selection_order: list[str]) -> gpd.GeoDataFrame:
    output = points.copy()
    sort_fields: list[str] = []
    ascending: list[bool] = []
    for rule in selection_order:
        if rule == "class_area_desc":
            sort_fields.append("class_area_ha")
            ascending.append(False)
        elif rule == "class_area_asc":
            sort_fields.append("class_area_ha")
            ascending.append(True)
        elif rule == "raster_value_asc":
            sort_fields.append("raster_value")
            ascending.append(True)
        elif rule == "raster_value_desc":
            sort_fields.append("raster_value")
            ascending.append(False)
        elif rule == "candidate_id_asc":
            sort_fields.append("candidate_id")
            ascending.append(True)
        elif rule == "candidate_id_desc":
            sort_fields.append("candidate_id")
            ascending.append(False)
        else:
            raise ValueError(f"Regla de orden no reconocida: {rule}")
    if "candidate_id" not in sort_fields:
        sort_fields.append("candidate_id")
        ascending.append(True)
    return output.sort_values(sort_fields, ascending=ascending, kind="mergesort").reset_index(drop=True)


def select_protected_candidates(
    points: gpd.GeoDataFrame,
    config: dict[str, Any],
    selection_order: list[str],
) -> pd.DataFrame:
    representation_cfg = config.get("sampling", {}).get("class_representation", {})
    if not representation_cfg.get("enabled", False):
        return pd.DataFrame(
            columns=[
                "candidate_id",
                "protected",
                "protection_reason",
                "protection_class_field",
                "protection_class_value",
            ]
        )
    class_field = representation_cfg.get("class_field", "stratum_id")
    if class_field not in points.columns:
        raise ValueError(f"El campo de representacion por clase no existe: {class_field}")
    minimum_points = int(representation_cfg.get("minimum_points_per_class", 1))
    if minimum_points < 0:
        raise ValueError("minimum_points_per_class no puede ser negativo.")

    priority_cfg = representation_cfg.get("priority_classes", {})
    priority_enabled = bool(priority_cfg.get("enabled", False))
    priority_field = priority_cfg.get("field", class_field)
    priority_values = {str(value) for value in priority_cfg.get("values", [])}
    priority_minimum = int(priority_cfg.get("minimum_points_per_class", minimum_points))
    if priority_enabled and priority_field not in points.columns:
        raise ValueError(f"El campo de clases prioritarias no existe: {priority_field}")

    rows: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    ordered = order_candidates(points, selection_order)
    for class_value, group in ordered.groupby(class_field, dropna=False, sort=False):
        n_to_protect = minimum_points
        reason = "minimum_class_representation"
        if priority_enabled and priority_values:
            group_values = {str(value) for value in group[priority_field].dropna().unique().tolist()}
            if group_values & priority_values:
                n_to_protect = max(n_to_protect, priority_minimum)
                reason = "priority_class_representation"
        for candidate_id in group.head(n_to_protect)["candidate_id"].tolist():
            candidate_id = int(candidate_id)
            if candidate_id in selected_ids:
                continue
            selected_ids.add(candidate_id)
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "protected": 1,
                    "protection_reason": reason,
                    "protection_class_field": class_field,
                    "protection_class_value": str(class_value),
                }
            )
    protected = pd.DataFrame(rows)
    LOGGER.info("Candidatos protegidos por clase: %s", f"{len(protected):,}")
    return protected


def thin_points_by_distance(
    points: gpd.GeoDataFrame,
    distance_m: float,
    selection_order: list[str],
    protected_candidates: pd.DataFrame,
    keep_protected_points_even_if_close: bool,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    if distance_m <= 0:
        raise ValueError("La distancia minima debe ser mayor que cero.")
    if protected_candidates.empty:
        protected_lookup: dict[int, dict[str, Any]] = {}
    else:
        protected_lookup = {
            int(row.candidate_id): row._asdict()
            for row in protected_candidates.itertuples(index=False)
        }

    ordered = order_candidates(points, selection_order).reset_index(drop=True)
    ordered["ordered_row_id"] = np.arange(len(ordered), dtype=np.int64)
    ordered["_is_protected"] = ordered["candidate_id"].map(lambda value: int(int(value) in protected_lookup))
    ordered = ordered.sort_values(
        ["_is_protected", "candidate_id"],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)

    cell_size = float(distance_m)
    distance_sq = cell_size * cell_size
    spatial_cells: dict[tuple[int, int], list[int]] = {}
    accepted_coords: list[tuple[float, float]] = []
    accepted_candidate_ids: list[int] = []
    accepted_ordered_row_ids: list[int] = []
    accepted_reasons: dict[int, str] = {}
    audit_rows: list[dict[str, Any]] = []

    for selection_order_id, row in enumerate(ordered.itertuples(index=False), start=1):
        candidate_id = int(row.candidate_id)
        protected_info = protected_lookup.get(candidate_id)
        is_protected = protected_info is not None
        x = float(row.geometry.x)
        y = float(row.geometry.y)
        cell_x = math.floor(x / cell_size)
        cell_y = math.floor(y / cell_size)
        blocker_candidate_id: int | None = None
        blocker_distance_m: float | None = None

        if not (is_protected and keep_protected_points_even_if_close):
            for dx in (-1, 0, 1):
                if blocker_candidate_id is not None:
                    break
                for dy in (-1, 0, 1):
                    for accepted_index in spatial_cells.get((cell_x + dx, cell_y + dy), []):
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
            selection_reason = (
                protected_info.get("protection_reason", "minimum_class_representation")
                if is_protected
                else "selected_distance"
            )
            accepted_reasons[candidate_id] = selection_reason
        else:
            selection_reason = "within_minimum_distance"

        audit_rows.append(
            {
                "distance_m": int(distance_m),
                "candidate_id": candidate_id,
                "point_id": row.point_id,
                "raster_value": row.raster_value,
                "class_value": row.class_value,
                "class_name": row.class_name,
                "selection_order": selection_order_id,
                "selected": int(selected),
                "protected": int(is_protected),
                "protection_reason": protected_info.get("protection_reason") if protected_info else None,
                "protection_class_field": protected_info.get("protection_class_field") if protected_info else None,
                "protection_class_value": protected_info.get("protection_class_value") if protected_info else None,
                "blocker_candidate_id": blocker_candidate_id,
                "blocker_distance_m": blocker_distance_m,
                "selection_reason": selection_reason,
            }
        )

    selected_points = ordered.loc[ordered["ordered_row_id"].isin(accepted_ordered_row_ids)].copy()
    selected_points = selected_points.drop(columns=["ordered_row_id", "_is_protected"], errors="ignore")
    selected_points["distance_scenario_m"] = int(distance_m)
    selected_points["selection_status"] = selected_points["candidate_id"].map(
        lambda value: accepted_reasons.get(int(value), "selected")
    )
    selected_points["protected"] = selected_points["candidate_id"].map(lambda value: int(int(value) in protected_lookup))
    selected_points["nearest_neighbor_m"] = calculate_nearest_neighbor_distance(selected_points)
    return selected_points.reset_index(drop=True), pd.DataFrame(audit_rows)


def calculate_nearest_neighbor_distance(points: gpd.GeoDataFrame) -> pd.Series:
    if len(points) == 0:
        return pd.Series(dtype="float64")
    if len(points) == 1:
        return pd.Series([np.nan], index=points.index, dtype="float64")
    if cKDTree is None:
        LOGGER.warning("SciPy no esta disponible. nearest_neighbor_m se dejara vacio.")
        return pd.Series(np.nan, index=points.index, dtype="float64")
    coordinates = np.column_stack((points.geometry.x.to_numpy(), points.geometry.y.to_numpy()))
    tree = cKDTree(coordinates)
    distances, _ = tree.query(coordinates, k=2)
    return pd.Series(distances[:, 1], index=points.index, dtype="float64")


def summarize_candidates(points: gpd.GeoDataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "n_candidates": int(len(points)),
                "n_classes": int(points["stratum_id"].nunique()),
                "candidate_spacing_m": float(points["candidate_spacing_m"].iloc[0]),
                "min_x": float(points.geometry.x.min()),
                "min_y": float(points.geometry.y.min()),
                "max_x": float(points.geometry.x.max()),
                "max_y": float(points.geometry.y.max()),
            }
        ]
    )


def summarize_distances(selected_layers: dict[int, gpd.GeoDataFrame], n_candidates: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for distance_m, points in selected_layers.items():
        nearest = points["nearest_neighbor_m"]
        rows.append(
            {
                "distance_m": int(distance_m),
                "n_candidates": int(n_candidates),
                "n_selected": int(len(points)),
                "n_rejected": int(n_candidates - len(points)),
                "pct_selected": float(100.0 * len(points) / n_candidates) if n_candidates else 0.0,
                "n_classes": int(points["stratum_id"].nunique()),
                "min_nearest_neighbor_m": float(nearest.min()) if nearest.notna().any() else np.nan,
                "median_nearest_neighbor_m": float(nearest.median()) if nearest.notna().any() else np.nan,
                "mean_nearest_neighbor_m": float(nearest.mean()) if nearest.notna().any() else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("distance_m").reset_index(drop=True)


def summarize_by_class(selected_layers: dict[int, gpd.GeoDataFrame]) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    group_fields = ["raster_value", "class_value", "class_name", "class_name_en", "stratum_id"]
    for distance_m, points in selected_layers.items():
        summary = (
            points.groupby(group_fields, dropna=False)
            .agg(
                n_points=("candidate_id", "size"),
                n_protected=("protected", "sum"),
                class_area_ha=("class_area_ha", "first"),
            )
            .reset_index()
        )
        summary.insert(0, "distance_m", int(distance_m))
        pieces.append(summary)
    if not pieces:
        return pd.DataFrame()
    return pd.concat(pieces, ignore_index=True)


def summarize_class_representation(
    candidate_points: gpd.GeoDataFrame,
    selection_audit: pd.DataFrame,
    class_field: str,
) -> pd.DataFrame:
    if class_field not in candidate_points.columns:
        class_field = "stratum_id"
    base = (
        candidate_points.groupby(class_field, dropna=False)
        .agg(
            n_candidates=("candidate_id", "size"),
            class_area_ha=("class_area_ha", "first"),
        )
        .reset_index()
        .rename(columns={class_field: "class_value_text"})
    )
    audit = selection_audit.merge(
        candidate_points[["candidate_id", class_field]],
        on="candidate_id",
        how="left",
        validate="many_to_one",
    )
    summary = (
        audit.groupby(["distance_m", class_field], dropna=False)
        .agg(
            n_selected=("selected", "sum"),
            n_protected=("protected", "sum"),
            n_selected_protected=(
                "selection_reason",
                lambda values: int(
                    values.isin(["minimum_class_representation", "priority_class_representation"]).sum()
                ),
            ),
        )
        .reset_index()
        .rename(columns={class_field: "class_value_text"})
    )
    output = summary.merge(base, on="class_value_text", how="left", validate="many_to_one")
    output.insert(1, "class_field", class_field)
    output["missing_after_selection"] = (output["n_selected"] == 0).astype(int)
    return output.sort_values(["distance_m", "missing_after_selection", "class_value_text"]).reset_index(drop=True)


def make_run_metadata(
    config: dict[str, Any],
    config_path: Path,
    raster_path: Path,
    raster_info: dict[str, Any],
    processing_crs: str,
    output_crs: str,
) -> pd.DataFrame:
    metadata = {
        "project_name": config["project"]["name"],
        "source_name": config["project"]["source_name"],
        "base_year": config["project"]["base_year"],
        "country": config["project"].get("country", "Panama"),
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "raster_path": str(raster_path),
        "raster_crs": raster_info["crs"],
        "raster_width": raster_info["width"],
        "raster_height": raster_info["height"],
        "raster_resolution_x": raster_info["resolution_x"],
        "raster_resolution_y": raster_info["resolution_y"],
        "processing_crs": processing_crs,
        "output_crs": output_crs,
        "candidate_spacing_m": config["sampling"]["candidate_spacing_m"],
        "thinning_distances_m": ",".join(str(v) for v in config["sampling"]["thinning_distances_m"]),
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
    run_metadata: pd.DataFrame,
    class_catalog: pd.DataFrame,
    candidate_summary: pd.DataFrame,
    distance_summary: pd.DataFrame,
) -> None:
    ensure_directory(report_path.parent)
    meta = dict(zip(run_metadata["key"], run_metadata["value"]))
    cand = candidate_summary.iloc[0].to_dict()
    content = f"""# Reporte de sampling - mapa forestal Panama

## Identificacion

- Proyecto: {meta.get('project_name')}
- Fuente: {meta.get('source_name')}
- Pais: {meta.get('country')}
- Anio base: {meta.get('base_year')}
- Fecha de ejecucion UTC: {meta.get('run_utc')}
- Raster: `{meta.get('raster_path')}`
- CRS raster: `{meta.get('raster_crs')}`
- CRS salida: `{meta.get('output_crs')}`

## Candidatos

- Candidatos validos: {int(cand['n_candidates']):,}
- Clases representadas: {int(cand['n_classes']):,}
- Espaciamiento de malla: {float(cand['candidate_spacing_m']):,.0f} m

## Escenarios de separacion minima

{distance_summary.to_markdown(index=False)}

## Catalogo de clases

{class_catalog[['raster_value', 'class_value', 'class_name', 'class_name_en', 'pixel_count', 'raster_area_ha']].to_markdown(index=False)}

## Criterio metodologico

El flujo genera una malla regular de candidatos sobre el GeoTIFF recortado y conserva solo los puntos cuyo valor raster es valido y esta documentado en la VAT. Cada valor se homologa con `Classvalue` y `Class_name`. Luego se aplica seleccion greedy reproducible por escenarios de distancia minima, con proteccion opcional de representacion minima por clase.
"""
    report_path.write_text(content, encoding="utf-8")
    LOGGER.info("Reporte Markdown exportado: %s", report_path)


def run(config_path: Path) -> None:
    config_path = config_path.resolve()
    config = load_yaml(config_path)

    outputs_cfg = config["outputs"]
    geodata_dir = resolve_repo_path(outputs_cfg["geodata_dir"])
    tables_dir = resolve_repo_path(outputs_cfg["tables_dir"])
    reports_dir = resolve_repo_path(outputs_cfg["reports_dir"])
    logs_dir = resolve_repo_path(outputs_cfg["logs_dir"])
    for directory in [geodata_dir, tables_dir, reports_dir, logs_dir]:
        ensure_directory(directory)

    log_path = logs_dir / outputs_cfg.get("log_name", "mapa_forestal_panama_sampling.log")
    configure_logger(log_path)

    gpkg_path = geodata_dir / outputs_cfg["gpkg_name"]
    if gpkg_path.exists():
        LOGGER.info("Eliminando GeoPackage previo: %s", gpkg_path)
        gpkg_path.unlink()

    raster_cfg = config["inputs"]["raster"]
    raster_path = resolve_repo_path(raster_cfg["path"])
    if not raster_path.exists():
        raise FileNotFoundError(f"No existe el raster: {raster_path}")

    processing_crs = config["crs"]["processing_crs"]
    output_crs = config["crs"].get("output_crs", "EPSG:4326")
    validate_processing_crs(processing_crs)
    CRS.from_user_input(output_crs)

    raster_info = inspect_raster(raster_path, int(raster_cfg.get("band", 1)), processing_crs)
    vat = read_vat_table(config)
    pixel_area_ha = raster_info["resolution_x"] * raster_info["resolution_y"] / 10_000.0
    class_catalog = build_class_catalog(vat, pixel_area_ha)
    footprint = create_raster_footprint(raster_path)
    candidate_points = create_candidate_points(raster_path, vat, config)

    distances = [int(value) for value in config["sampling"]["thinning_distances_m"]]
    if not distances:
        raise ValueError("Debe indicar al menos una distancia en sampling.thinning_distances_m.")
    selection_order = config["sampling"].get("selection_order", ["class_area_desc", "candidate_id_asc"])

    class_rep_cfg = config.get("sampling", {}).get("class_representation", {})
    protected_candidates = select_protected_candidates(candidate_points, config, selection_order)
    keep_protected = bool(class_rep_cfg.get("keep_protected_points_even_if_close", True))

    selected_layers: dict[int, gpd.GeoDataFrame] = {}
    audit_pieces: list[pd.DataFrame] = []
    for distance_m in distances:
        LOGGER.info("Aplicando separacion minima global: %s m", f"{distance_m:,}")
        selected, audit = thin_points_by_distance(
            candidate_points,
            distance_m=distance_m,
            selection_order=selection_order,
            protected_candidates=protected_candidates,
            keep_protected_points_even_if_close=keep_protected,
        )
        selected_layers[distance_m] = selected
        audit_pieces.append(audit)
        LOGGER.info(
            "Escenario %s m | seleccionados=%s | rechazados=%s",
            f"{distance_m:,}",
            f"{len(selected):,}",
            f"{len(candidate_points) - len(selected):,}",
        )

    selection_audit = pd.concat(audit_pieces, ignore_index=True)
    candidate_summary = summarize_candidates(candidate_points)
    distance_summary = summarize_distances(selected_layers, len(candidate_points))
    class_summary = summarize_by_class(selected_layers)
    class_representation_summary = summarize_class_representation(
        candidate_points,
        selection_audit,
        class_field=class_rep_cfg.get("class_field", "stratum_id"),
    )
    run_metadata = make_run_metadata(
        config,
        config_path,
        raster_path,
        raster_info,
        processing_crs,
        output_crs,
    )

    layer_names = outputs_cfg["layers"]
    write_spatial_layer(footprint, gpkg_path, layer_names["raster_footprint"], output_crs)
    write_spatial_layer(candidate_points, gpkg_path, layer_names["candidate_points"], output_crs)
    selected_prefix = layer_names.get("selected_prefix", "mapa_forestal_panama_puntos_d")
    for distance_m, selected in selected_layers.items():
        write_spatial_layer(selected, gpkg_path, f"{selected_prefix}{distance_m:04d}", output_crs)

    tables = {
        layer_names["class_catalog"]: class_catalog,
        layer_names["candidate_summary"]: candidate_summary,
        layer_names["distance_summary"]: distance_summary,
        layer_names["class_summary"]: class_summary,
        layer_names["class_representation_summary"]: class_representation_summary,
        layer_names["selection_audit"]: selection_audit,
        layer_names["run_metadata"]: run_metadata,
    }
    for table_name, dataframe in tables.items():
        write_nonspatial_table(dataframe, gpkg_path, table_name)

    if outputs_cfg.get("export_csv", True):
        export_csv_tables(tables_dir, tables)

    report_path = reports_dir / outputs_cfg.get("report_name", "mapa_forestal_panama_sampling_reporte.md")
    write_report(report_path, run_metadata, class_catalog, candidate_summary, distance_summary)

    LOGGER.info("Proceso finalizado correctamente.")
    LOGGER.info("GeoPackage: %s", gpkg_path)
    LOGGER.info("Tablas CSV: %s", tables_dir)
    LOGGER.info("Reporte: %s", report_path)
    LOGGER.info("Log: %s", log_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sampling raster para el mapa forestal de Panama recortado."
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"Ruta al YAML. Por defecto: {DEFAULT_CONFIG}",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(Path(arguments.config))
