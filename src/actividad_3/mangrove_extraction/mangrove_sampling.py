# -*- coding: utf-8 -*-
"""
mangrove_sampling.py

Flujo exclusivo para extraer puntos candidatos desde la fuente de manglar:

    Global Mangrove Watch 2020
    INTERSECT
    ESA WorldCover 2020 clase 95
    con parches menores a 0.5 ha eliminados

Este script NO genera la fuente de manglar.
Este script NO extrae predictores espectrales.
Este script solo genera puntos candidatos y escenarios de separación mínima.

Metodología:
1. Lee AOI regional.
2. Lee fuente vectorial de manglar consenso.
3. Repara geometrías si se solicita.
4. Reproyecta a CRS métrico.
5. Recorta la fuente de manglar con el AOI.
6. Genera un punto interior por fragmento recortado.
7. Protege representación mínima por clase.
8. Aplica escenarios de separación mínima.
9. Exporta capas espaciales, auditorías y resúmenes.

"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ------------------------------------------------------------------
# GDAL/PROJ en Conda Windows
# ------------------------------------------------------------------

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
import yaml
from pyproj import CRS

try:
    from scipy.spatial import cKDTree
except ImportError:
    cKDTree = None


# ------------------------------------------------------------------
# Rutas base
# ------------------------------------------------------------------

def find_repo_root(start_path: Path | None = None) -> Path:
    if start_path is None:
        start_path = Path(__file__).resolve()

    current = start_path.parent if start_path.is_file() else start_path.resolve()
    candidates = [current] + list(current.parents)

    for candidate in candidates:
        if (candidate / "data").exists():
            return candidate

    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate

    raise RuntimeError(
        "No se pudo detectar la raíz del repositorio. "
        "Debe existir una carpeta data/ o .git."
    )


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = find_repo_root(SCRIPT_PATH)
DEFAULT_CONFIG = REPO_ROOT / "config" / "mangrove_sampling.yaml"

LOGGER = logging.getLogger("mangrove_sampling")


# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

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

        file_handler = logging.FileHandler(
            log_path,
            mode="w",
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        LOGGER.addHandler(file_handler)


# ------------------------------------------------------------------
# Configuración
# ------------------------------------------------------------------

def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el YAML: {path}")

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("El YAML no contiene una estructura válida.")

    return config


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)

    if path.is_absolute():
        return path

    return (REPO_ROOT / path).resolve()


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def get_layer_name(
    layer_names: dict[str, str],
    key: str,
    default: str,
) -> str:
    return layer_names.get(key, default)


def get_source_prefix(config: dict[str, Any]) -> str:
    return str(
        config.get("project", {}).get("source_prefix", "MANGROVE")
    ).strip()


# ------------------------------------------------------------------
# Lectura y validación
# ------------------------------------------------------------------

def read_vector(
    path: Path,
    layer: str | None = None,
) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo vectorial: {path}")

    LOGGER.info(
        "Leyendo: %s%s",
        path,
        f" | layer={layer}" if layer else "",
    )

    if layer:
        gdf = gpd.read_file(path, layer=layer)
    else:
        gdf = gpd.read_file(path)

    if gdf.empty:
        raise ValueError(f"La capa está vacía: {path}")

    if gdf.crs is None:
        raise ValueError(f"La capa no tiene CRS definido: {path}")

    LOGGER.info(
        "Capa leída | objetos=%s | CRS=%s",
        f"{len(gdf):,}",
        gdf.crs,
    )

    return gdf


def require_fields(
    dataframe: pd.DataFrame,
    fields: list[str],
    label: str,
) -> None:
    fields = [
        field
        for field in fields
        if field is not None
    ]

    missing = [
        field
        for field in fields
        if field not in dataframe.columns
    ]

    if missing:
        raise ValueError(
            f"Faltan campos obligatorios en {label}: {missing}\n"
            f"Campos disponibles: {list(dataframe.columns)}"
        )


def validate_processing_crs(crs_value: str) -> CRS:
    crs = CRS.from_user_input(crs_value)

    if not crs.is_projected:
        raise ValueError(
            f"El CRS de procesamiento debe ser proyectado: {crs_value}"
        )

    units = {
        axis.unit_name.lower()
        for axis in crs.axis_info
        if axis.unit_name
    }

    if "metre" not in units and "meter" not in units:
        raise ValueError(
            "El CRS de procesamiento debe utilizar metros. "
            f"CRS recibido: {crs_value}; unidades: {sorted(units)}"
        )

    return crs


# ------------------------------------------------------------------
# Geometrías
# ------------------------------------------------------------------

def repair_geometries(
    gdf: gpd.GeoDataFrame,
    label: str,
) -> gpd.GeoDataFrame:
    output = gdf.copy()

    null_or_empty = output.geometry.isna() | output.geometry.is_empty

    if null_or_empty.any():
        LOGGER.warning(
            "%s | eliminando geometrías nulas/vacías: %s",
            label,
            f"{int(null_or_empty.sum()):,}",
        )
        output = output.loc[~null_or_empty].copy()

    invalid = ~output.geometry.is_valid
    n_invalid = int(invalid.sum())

    if n_invalid:
        LOGGER.info(
            "%s | corrigiendo geometrías inválidas: %s",
            label,
            f"{n_invalid:,}",
        )

        try:
            output.loc[invalid, "geometry"] = (
                output.loc[invalid].geometry.make_valid()
            )
        except (AttributeError, NotImplementedError):
            output.loc[invalid, "geometry"] = (
                output.loc[invalid].geometry.buffer(0)
            )

    null_or_empty = output.geometry.isna() | output.geometry.is_empty

    if null_or_empty.any():
        LOGGER.warning(
            "%s | eliminando geometrías vacías después de reparar: %s",
            label,
            f"{int(null_or_empty.sum()):,}",
        )
        output = output.loc[~null_or_empty].copy()

    unresolved = ~output.geometry.is_valid

    if unresolved.any():
        LOGGER.warning(
            "%s | geometrías inválidas no resueltas y eliminadas: %s",
            label,
            f"{int(unresolved.sum()):,}",
        )
        output = output.loc[~unresolved].copy()

    return output.reset_index(drop=True)


def reproject(
    gdf: gpd.GeoDataFrame,
    target_crs: str,
    label: str,
) -> gpd.GeoDataFrame:
    LOGGER.info("Reproyectando %s a %s", label, target_crs)
    return gdf.to_crs(target_crs)


# ------------------------------------------------------------------
# AOI
# ------------------------------------------------------------------

def prepare_aoi_units(
    aoi: gpd.GeoDataFrame,
    config: dict[str, Any],
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    aoi_cfg = config["inputs"]["aoi"]
    fields = aoi_cfg.get("fields", {})

    unit_id_field = fields.get("unit_id")
    unit_name_field = fields.get("unit_name")

    output = aoi.copy()

    filter_cfg = config.get("aoi", {}).get("filter", {})

    if filter_cfg.get("enabled", False):
        filter_field = filter_cfg.get("field")
        filter_values = {
            str(value).strip()
            for value in filter_cfg.get("values", [])
        }

        if not filter_field:
            raise ValueError(
                "aoi.filter.enabled=true requiere aoi.filter.field."
            )

        require_fields(output, [filter_field], "AOI")

        values = (
            output[filter_field]
            .astype("string")
            .str.strip()
        )

        output = output.loc[
            values.isin(filter_values)
        ].copy()

        LOGGER.info(
            "AOI filtrado por %s | objetos=%s",
            filter_field,
            f"{len(output):,}",
        )

    exclude_cfg = config.get("aoi", {}).get("exclude", {})

    if exclude_cfg.get("enabled", False):
        exclude_field = exclude_cfg.get("field")
        exclude_values = {
            str(value).strip().upper()
            for value in exclude_cfg.get("values", [])
        }

        if not exclude_field:
            raise ValueError(
                "aoi.exclude.enabled=true requiere aoi.exclude.field."
            )

        require_fields(output, [exclude_field], "AOI")

        values = (
            output[exclude_field]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper()
        )

        before = len(output)
        output = output.loc[
            ~values.isin(exclude_values)
        ].copy()

        LOGGER.info(
            "AOI exclusiones por %s | eliminados=%s",
            exclude_field,
            f"{before - len(output):,}",
        )

    if output.empty:
        raise ValueError("El AOI quedó vacío después de filtros/exclusiones.")

    if unit_id_field and unit_id_field in output.columns:
        output["aoi_unit_id"] = (
            output[unit_id_field]
            .astype("string")
            .str.strip()
        )
    else:
        output["aoi_unit_id"] = [
            f"AOI_{idx:03d}"
            for idx in range(1, len(output) + 1)
        ]

    if unit_name_field and unit_name_field in output.columns:
        output["aoi_unit_name"] = (
            output[unit_name_field]
            .astype("string")
            .str.strip()
        )
    else:
        output["aoi_unit_name"] = output["aoi_unit_id"]

    LOGGER.info("Disolviendo AOI por unidad")

    output = output.dissolve(
        by=["aoi_unit_id", "aoi_unit_name"],
        as_index=False,
        dropna=False,
    )

    output["aoi_area_ha"] = output.geometry.area / 10_000.0

    output = output[
        [
            "aoi_unit_id",
            "aoi_unit_name",
            "aoi_area_ha",
            "geometry",
        ]
    ].copy()

    try:
        union_geometry = output.geometry.union_all()
    except AttributeError:
        union_geometry = output.geometry.unary_union

    aoi_union = gpd.GeoDataFrame(
        {
            "aoi_id": [1],
            "aoi_name": ["mangrove_sampling_aoi"],
        },
        geometry=[union_geometry],
        crs=output.crs,
    )

    aoi_union["aoi_area_ha"] = aoi_union.geometry.area / 10_000.0

    LOGGER.info(
        "AOI preparado | unidades=%s | área total=%.2f ha",
        f"{len(output):,}",
        float(aoi_union["aoi_area_ha"].iloc[0]),
    )

    return output.reset_index(drop=True), aoi_union


# ------------------------------------------------------------------
# Fuente manglar
# ------------------------------------------------------------------

def build_source_uid(
    source_objectid: Any,
    class_id: Any,
    class_label: Any,
    geometry: Any,
    source_prefix: str,
) -> str:
    object_text = "" if pd.isna(source_objectid) else str(source_objectid).strip()
    class_text = "" if pd.isna(class_id) else str(class_id).strip()
    label_text = "" if pd.isna(class_label) else str(class_label).strip()

    geometry_bytes = (
        b""
        if geometry is None or geometry.is_empty
        else geometry.wkb
    )

    digest = hashlib.sha1()
    digest.update(object_text.encode("utf-8"))
    digest.update(b"|")
    digest.update(class_text.encode("utf-8"))
    digest.update(b"|")
    digest.update(label_text.encode("utf-8"))
    digest.update(b"|")
    digest.update(geometry_bytes)

    return f"{source_prefix}_{digest.hexdigest()[:20]}"


def normalize_mangrove_source(
    source: gpd.GeoDataFrame,
    config: dict[str, Any],
) -> gpd.GeoDataFrame:
    source_cfg = config["inputs"]["mangrove_source"]
    fields = source_cfg["fields"]

    object_id_field = fields.get("object_id")
    class_id_field = fields.get("class_id")
    class_label_field = fields.get("class_label")
    confidence_field = fields.get("confidence")
    source_area_field = fields.get("source_area_ha")
    extra_fields = fields.get("extra_fields", []) or []

    require_fields(
        source,
        [class_id_field, class_label_field],
        "fuente de manglar",
    )

    optional_fields = [
        field
        for field in [
            object_id_field,
            confidence_field,
            source_area_field,
        ]
        if field is not None
    ]

    require_fields(source, optional_fields, "fuente de manglar")

    existing_extra_fields = [
        field
        for field in extra_fields
        if field in source.columns
    ]

    missing_extra = sorted(set(extra_fields) - set(existing_extra_fields))

    if missing_extra:
        LOGGER.warning(
            "Campos extra no encontrados y omitidos: %s",
            missing_extra,
        )

    output = source.copy()
    source_prefix = get_source_prefix(config)

    if object_id_field:
        output = output.rename(
            columns={
                object_id_field: "source_objectid",
            }
        )
        source_id_origin = f"campo:{object_id_field}"
    else:
        output["source_objectid"] = np.arange(
            1,
            len(output) + 1,
            dtype=np.int64,
        )
        source_id_origin = "generado_desde_orden_lectura"

    output = output.rename(
        columns={
            class_id_field: "class_id",
            class_label_field: "class_label",
        }
    )

    output["class_id"] = (
        output["class_id"]
        .astype("string")
        .str.strip()
    )

    output["class_label"] = (
        output["class_label"]
        .astype("string")
        .str.strip()
    )

    output["source_id_origin"] = source_id_origin
    output["source_type"] = "mangrove_consensus_vector"
    output["source_domain"] = "VEGETATION"
    output["class_group"] = "MANGROVE"
    output["stratum_id"] = (
        output["class_id"]
        .fillna("SIN_CLASE")
        .astype(str)
        .str.strip()
        + " | "
        + output["class_label"]
        .fillna("SIN_ETIQUETA")
        .astype(str)
        .str.strip()
    )

    if confidence_field:
        output["confidence"] = (
            output[confidence_field]
            .astype("string")
            .str.strip()
        )
    else:
        output["confidence"] = "high_consensus"

    if source_area_field:
        output["source_area_ha_input"] = pd.to_numeric(
            output[source_area_field],
            errors="coerce",
        )
    else:
        output["source_area_ha_input"] = np.nan

    output["source_area_ha"] = output.geometry.area / 10_000.0

    output["source_uid"] = [
        build_source_uid(
            source_objectid=source_objectid,
            class_id=class_id,
            class_label=class_label,
            geometry=geometry,
            source_prefix=source_prefix,
        )
        for source_objectid, class_id, class_label, geometry in zip(
            output["source_objectid"],
            output["class_id"],
            output["class_label"],
            output.geometry,
        )
    ]

    keep_fields = [
        "source_objectid",
        "source_uid",
        "source_id_origin",
        "source_type",
        "source_domain",
        "class_group",
        "class_id",
        "class_label",
        "stratum_id",
        "confidence",
        "source_area_ha_input",
        "source_area_ha",
    ]

    keep_fields.extend(existing_extra_fields)
    keep_fields.append("geometry")

    LOGGER.info(
        "Fuente manglar normalizada | polígonos=%s | clases=%s | confianza=%s",
        f"{len(output):,}",
        f"{output['stratum_id'].nunique(dropna=True):,}",
        f"{output['confidence'].nunique(dropna=True):,}",
    )

    return output[keep_fields].copy()


def clip_mangrove_source_to_aoi(
    source: gpd.GeoDataFrame,
    aoi_units: gpd.GeoDataFrame,
    aoi_union: gpd.GeoDataFrame,
    minimum_fragment_area_ha: float,
) -> gpd.GeoDataFrame:
    LOGGER.info("Seleccionando polígonos de manglar que intersectan el AOI")

    union_geometry = aoi_union.geometry.iloc[0]

    subset = source.loc[
        source.geometry.intersects(union_geometry)
    ].copy()

    LOGGER.info(
        "Polígonos candidatos antes de intersección: %s",
        f"{len(subset):,}",
    )

    if subset.empty:
        raise ValueError("La fuente de manglar no intersecta el AOI.")

    LOGGER.info("Intersectando fuente de manglar con unidades AOI")

    output = gpd.overlay(
        subset,
        aoi_units[
            [
                "aoi_unit_id",
                "aoi_unit_name",
                "geometry",
            ]
        ],
        how="intersection",
        keep_geom_type=False,
    )

    polygon_mask = output.geometry.geom_type.isin(
        [
            "Polygon",
            "MultiPolygon",
        ]
    )

    dropped = int((~polygon_mask).sum())

    if dropped:
        LOGGER.info(
            "Geometrías no poligonales descartadas después del clip: %s",
            f"{dropped:,}",
        )
        output = output.loc[polygon_mask].copy()

    output = output.loc[
        ~(
            output.geometry.isna()
            | output.geometry.is_empty
        )
    ].copy()

    if output.empty:
        raise ValueError("La intersección manglar × AOI no produjo polígonos.")

    output["clip_id"] = np.arange(
        1,
        len(output) + 1,
        dtype=np.int64,
    )

    output["clipped_area_ha"] = output.geometry.area / 10_000.0

    if minimum_fragment_area_ha > 0:
        before = len(output)

        output = output.loc[
            output["clipped_area_ha"] >= minimum_fragment_area_ha
        ].copy()

        LOGGER.info(
            "Fragmentos eliminados por área mínima %.4f ha: %s",
            minimum_fragment_area_ha,
            f"{before - len(output):,}",
        )

    keep_fields = [
        "clip_id",
        "source_objectid",
        "source_uid",
        "source_id_origin",
        "source_type",
        "source_domain",
        "class_group",
        "class_id",
        "class_label",
        "stratum_id",
        "confidence",
        "source_area_ha_input",
        "source_area_ha",
        "aoi_unit_id",
        "aoi_unit_name",
        "clipped_area_ha",
    ]

    extra_fields = [
        column
        for column in output.columns
        if column not in keep_fields + ["geometry"]
        and column not in ["index_right"]
    ]

    keep_fields.extend(extra_fields)
    keep_fields.append("geometry")

    LOGGER.info(
        "Fuente manglar recortada | fragmentos=%s | polígonos fuente=%s | área=%.2f ha",
        f"{len(output):,}",
        f"{output['source_uid'].nunique():,}",
        float(output["clipped_area_ha"].sum()),
    )

    return output[keep_fields].reset_index(drop=True)


# ------------------------------------------------------------------
# Puntos candidatos
# ------------------------------------------------------------------

def create_candidate_points(
    clipped: gpd.GeoDataFrame,
    config: dict[str, Any],
) -> gpd.GeoDataFrame:
    method = config["sampling"].get(
        "representative_point_method",
        "point_on_surface",
    )

    if method != "point_on_surface":
        raise ValueError(
            "Este flujo de manglar actualmente solo admite "
            "representative_point_method: point_on_surface."
        )

    LOGGER.info("Generando un punto interior por fragmento de manglar")

    output = clipped.drop(columns="geometry").copy()

    output = gpd.GeoDataFrame(
        output,
        geometry=clipped.geometry.representative_point(),
        crs=clipped.crs,
    )

    valid = ~(
        output.geometry.isna()
        | output.geometry.is_empty
    )

    output = output.loc[valid].copy()

    output["candidate_id"] = np.arange(
        1,
        len(output) + 1,
        dtype=np.int64,
    )

    source_prefix = get_source_prefix(config)

    output["point_id"] = output["candidate_id"].map(
        lambda value: f"{source_prefix}_{value:07d}"
    )

    output["source_name"] = config["project"]["source_name"]
    output["base_year"] = int(config["project"]["base_year"])
    output["extraction_method"] = "point_on_surface_per_clipped_mangrove_fragment"

    first_fields = [
        "candidate_id",
        "point_id",
        "clip_id",
        "source_objectid",
        "source_uid",
        "source_id_origin",
        "source_type",
        "source_domain",
        "class_group",
        "class_id",
        "class_label",
        "stratum_id",
        "confidence",
        "aoi_unit_id",
        "aoi_unit_name",
        "source_area_ha_input",
        "source_area_ha",
        "clipped_area_ha",
        "source_name",
        "base_year",
        "extraction_method",
    ]

    other_fields = [
        column
        for column in output.columns
        if column not in first_fields + ["geometry"]
    ]

    first_fields.extend(other_fields)
    first_fields.append("geometry")

    LOGGER.info(
        "Puntos candidatos generados: %s",
        f"{len(output):,}",
    )

    return output[first_fields].reset_index(drop=True)


# ------------------------------------------------------------------
# Protección por clase y orden
# ------------------------------------------------------------------

def order_candidates(
    points: gpd.GeoDataFrame,
    selection_order: list[str],
) -> gpd.GeoDataFrame:
    output = points.copy()

    source_numeric = pd.to_numeric(
        output["source_objectid"],
        errors="coerce",
    )

    if source_numeric.notna().all():
        output["_source_sort"] = source_numeric
    else:
        output["_source_sort"] = (
            output["source_objectid"]
            .astype("string")
            .fillna("")
        )

    sort_fields: list[str] = []
    ascending: list[bool] = []

    for rule in selection_order:
        if rule == "area_desc":
            sort_fields.append("clipped_area_ha")
            ascending.append(False)

        elif rule == "area_asc":
            sort_fields.append("clipped_area_ha")
            ascending.append(True)

        elif rule == "objectid_asc":
            sort_fields.append("_source_sort")
            ascending.append(True)

        elif rule == "objectid_desc":
            sort_fields.append("_source_sort")
            ascending.append(False)

        else:
            raise ValueError(f"Regla de orden no reconocida: {rule}")

    if "candidate_id" not in sort_fields:
        sort_fields.append("candidate_id")
        ascending.append(True)

    output = output.sort_values(
        sort_fields,
        ascending=ascending,
        kind="mergesort",
    )

    return output.drop(columns="_source_sort").reset_index(drop=True)


def select_protected_candidates(
    points: gpd.GeoDataFrame,
    config: dict[str, Any],
    selection_order: list[str],
) -> pd.DataFrame:
    representation_cfg = (
        config.get("sampling", {})
        .get("class_representation", {})
    )

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
        raise ValueError(
            f"El campo de representación por clase no existe: {class_field}"
        )

    minimum_points = int(
        representation_cfg.get("minimum_points_per_class", 1)
    )

    if minimum_points < 0:
        raise ValueError("minimum_points_per_class no puede ser negativo.")

    priority_cfg = representation_cfg.get("priority_classes", {})
    priority_enabled = bool(priority_cfg.get("enabled", False))
    priority_field = priority_cfg.get("field", class_field)
    priority_values = {
        str(value)
        for value in priority_cfg.get("values", [])
    }
    priority_minimum = int(
        priority_cfg.get("minimum_points_per_class", minimum_points)
    )

    if priority_enabled and priority_field not in points.columns:
        raise ValueError(
            f"El campo de clases prioritarias no existe: {priority_field}"
        )

    ordered = order_candidates(points, selection_order)

    rows: list[dict[str, Any]] = []
    already_selected: set[int] = set()

    for class_value, group in ordered.groupby(
        class_field,
        dropna=False,
        sort=False,
    ):
        class_value_text = str(class_value)
        n_to_protect = minimum_points
        reason = "minimum_class_representation"

        if priority_enabled and priority_values:
            group_priority_values = {
                str(value)
                for value in group[priority_field]
                .dropna()
                .unique()
                .tolist()
            }

            if group_priority_values & priority_values:
                n_to_protect = max(
                    n_to_protect,
                    priority_minimum,
                )
                reason = "priority_class_representation"

        if n_to_protect <= 0:
            continue

        selected_group = group.head(n_to_protect)

        for candidate_id in selected_group["candidate_id"].tolist():
            candidate_id = int(candidate_id)

            if candidate_id in already_selected:
                continue

            already_selected.add(candidate_id)

            rows.append(
                {
                    "candidate_id": candidate_id,
                    "protected": 1,
                    "protection_reason": reason,
                    "protection_class_field": class_field,
                    "protection_class_value": class_value_text,
                }
            )

    protected = pd.DataFrame(rows)

    LOGGER.info(
        "Representación mínima por clase | protegidos=%s | campo=%s",
        f"{len(protected):,}",
        class_field,
    )

    return protected


# ------------------------------------------------------------------
# Thinning por distancia
# ------------------------------------------------------------------

def thin_points_by_distance(
    points: gpd.GeoDataFrame,
    distance_m: float,
    selection_order: list[str],
    protected_candidates: pd.DataFrame | None = None,
    keep_protected_points_even_if_close: bool = True,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    if distance_m <= 0:
        raise ValueError("La distancia mínima debe ser mayor que cero.")

    protected_candidates = (
        protected_candidates.copy()
        if protected_candidates is not None
        else pd.DataFrame()
    )

    if protected_candidates.empty:
        protected_lookup: dict[int, dict[str, Any]] = {}
    else:
        protected_lookup = {
            int(row.candidate_id): row._asdict()
            for row in protected_candidates.itertuples(index=False)
        }

    ordered = order_candidates(
        points,
        selection_order,
    ).reset_index(drop=True)

    ordered["ordered_row_id"] = np.arange(
        len(ordered),
        dtype=np.int64,
    )

    ordered["_is_protected"] = ordered["candidate_id"].map(
        lambda value: int(int(value) in protected_lookup)
    )

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

    for selection_order_id, row in enumerate(
        ordered.itertuples(index=False),
        start=1,
    ):
        candidate_id = int(row.candidate_id)
        protected_info = protected_lookup.get(candidate_id)
        is_protected = protected_info is not None

        x = float(row.geometry.x)
        y = float(row.geometry.y)

        cell_x = math.floor(x / cell_size)
        cell_y = math.floor(y / cell_size)

        blocker_candidate_id: int | None = None
        blocker_distance_m: float | None = None

        if not (
            is_protected
            and keep_protected_points_even_if_close
        ):
            for dx in (-1, 0, 1):
                if blocker_candidate_id is not None:
                    break

                for dy in (-1, 0, 1):
                    neighbor_key = (
                        cell_x + dx,
                        cell_y + dy,
                    )

                    for accepted_index in spatial_cells.get(
                        neighbor_key,
                        [],
                    ):
                        accepted_x, accepted_y = accepted_coords[accepted_index]

                        delta_x = x - accepted_x
                        delta_y = y - accepted_y

                        candidate_distance_sq = (
                            delta_x * delta_x
                            + delta_y * delta_y
                        )

                        if candidate_distance_sq < distance_sq:
                            blocker_candidate_id = accepted_candidate_ids[
                                accepted_index
                            ]
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

            if is_protected:
                selection_reason = protected_info.get(
                    "protection_reason",
                    "minimum_class_representation",
                )
            else:
                selection_reason = "selected_distance"

            accepted_reasons[candidate_id] = selection_reason

            spatial_cells.setdefault(
                (cell_x, cell_y),
                [],
            ).append(accepted_index)

        else:
            selection_reason = "within_minimum_distance"

        audit_rows.append(
            {
                "distance_m": int(distance_m),
                "candidate_id": candidate_id,
                "point_id": row.point_id,
                "selection_order": selection_order_id,
                "selected": int(selected),
                "protected": int(is_protected),
                "protection_reason": (
                    protected_info.get("protection_reason")
                    if protected_info
                    else None
                ),
                "protection_class_field": (
                    protected_info.get("protection_class_field")
                    if protected_info
                    else None
                ),
                "protection_class_value": (
                    protected_info.get("protection_class_value")
                    if protected_info
                    else None
                ),
                "blocker_candidate_id": blocker_candidate_id,
                "blocker_distance_m": blocker_distance_m,
                "selection_reason": selection_reason,
            }
        )

    selected_points = ordered.loc[
        ordered["ordered_row_id"].isin(accepted_ordered_row_ids)
    ].copy()

    selected_points = selected_points.drop(
        columns=[
            "ordered_row_id",
            "_is_protected",
        ],
        errors="ignore",
    )

    selected_points["distance_scenario_m"] = int(distance_m)

    selected_points["selection_status"] = selected_points["candidate_id"].map(
        lambda value: accepted_reasons.get(
            int(value),
            "selected",
        )
    )

    selected_points["protected"] = selected_points["candidate_id"].map(
        lambda value: int(int(value) in protected_lookup)
    )

    selected_points["nearest_neighbor_m"] = calculate_nearest_neighbor_distance(
        selected_points
    )

    audit = pd.DataFrame(audit_rows)

    return selected_points.reset_index(drop=True), audit


def calculate_nearest_neighbor_distance(
    points: gpd.GeoDataFrame,
) -> pd.Series:
    n_points = len(points)

    if n_points == 0:
        return pd.Series(dtype="float64")

    if n_points == 1:
        return pd.Series(
            [np.nan],
            index=points.index,
            dtype="float64",
        )

    if cKDTree is None:
        LOGGER.warning(
            "SciPy no está disponible. nearest_neighbor_m se dejará vacío."
        )
        return pd.Series(
            np.nan,
            index=points.index,
            dtype="float64",
        )

    coordinates = np.column_stack(
        (
            points.geometry.x.to_numpy(),
            points.geometry.y.to_numpy(),
        )
    )

    tree = cKDTree(coordinates)

    distances, _ = tree.query(
        coordinates,
        k=2,
    )

    return pd.Series(
        distances[:, 1],
        index=points.index,
        dtype="float64",
    )


# ------------------------------------------------------------------
# Resúmenes
# ------------------------------------------------------------------

def build_field_audit(dataframe: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "source_objectid",
        "source_uid",
        "source_type",
        "source_domain",
        "class_group",
        "class_id",
        "class_label",
        "stratum_id",
        "confidence",
        "source_area_ha_input",
        "source_area_ha",
        "clipped_area_ha",
        "aoi_unit_id",
        "aoi_unit_name",
    ]

    total = len(dataframe)
    rows: list[dict[str, Any]] = []

    for field in fields:
        if field not in dataframe.columns:
            continue

        null_count = int(dataframe[field].isna().sum())

        rows.append(
            {
                "field": field,
                "n_total": total,
                "n_null": null_count,
                "pct_null": (
                    100.0 * null_count / total
                    if total
                    else 0.0
                ),
                "n_unique": int(dataframe[field].nunique(dropna=True)),
            }
        )

    return pd.DataFrame(rows)


def build_class_catalog(
    dataframe: pd.DataFrame,
    area_field: str,
    polygon_id_field: str,
) -> pd.DataFrame:
    group_fields = [
        "class_group",
        "class_id",
        "class_label",
        "stratum_id",
        "confidence",
    ]

    catalog = (
        dataframe.groupby(
            group_fields,
            dropna=False,
        )
        .agg(
            n_polygons=(polygon_id_field, "nunique"),
            area_ha=(area_field, "sum"),
        )
        .reset_index()
    )

    return catalog.sort_values(
        [
            "class_group",
            "class_id",
            "class_label",
        ],
        na_position="last",
    ).reset_index(drop=True)


def summarize_distances(
    selected_layers: dict[int, gpd.GeoDataFrame],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for distance_m, points in selected_layers.items():
        nearest = points["nearest_neighbor_m"]

        rows.append(
            {
                "distance_m": distance_m,
                "n_points": len(points),
                "n_aoi_units": points["aoi_unit_id"].nunique(),
                "n_classes": points["stratum_id"].nunique(),
                "n_source_patches": points["source_uid"].nunique(),
                "n_clipped_fragments": points["clip_id"].nunique(),
                "represented_area_ha": float(points["clipped_area_ha"].sum()),
                "min_nearest_neighbor_m": (
                    float(nearest.min())
                    if nearest.notna().any()
                    else np.nan
                ),
                "median_nearest_neighbor_m": (
                    float(nearest.median())
                    if nearest.notna().any()
                    else np.nan
                ),
                "mean_nearest_neighbor_m": (
                    float(nearest.mean())
                    if nearest.notna().any()
                    else np.nan
                ),
            }
        )

    return pd.DataFrame(rows).sort_values(
        "distance_m"
    ).reset_index(drop=True)


def summarize_by_aoi_unit(
    selected_layers: dict[int, gpd.GeoDataFrame],
) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []

    for distance_m, points in selected_layers.items():
        summary = (
            points.groupby(
                [
                    "aoi_unit_id",
                    "aoi_unit_name",
                ],
                dropna=False,
            )
            .agg(
                n_points=("candidate_id", "size"),
                n_classes=("stratum_id", "nunique"),
                n_source_patches=("source_uid", "nunique"),
                n_clipped_fragments=("clip_id", "nunique"),
                represented_area_ha=("clipped_area_ha", "sum"),
            )
            .reset_index()
        )

        summary.insert(0, "distance_m", distance_m)
        pieces.append(summary)

    if not pieces:
        return pd.DataFrame()

    return pd.concat(
        pieces,
        ignore_index=True,
    )


def summarize_by_class(
    selected_layers: dict[int, gpd.GeoDataFrame],
) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []

    group_fields = [
        "class_group",
        "class_id",
        "class_label",
        "stratum_id",
        "confidence",
    ]

    for distance_m, points in selected_layers.items():
        summary = (
            points.groupby(
                group_fields,
                dropna=False,
            )
            .agg(
                n_points=("candidate_id", "size"),
                n_aoi_units=("aoi_unit_id", "nunique"),
                n_source_patches=("source_uid", "nunique"),
                n_clipped_fragments=("clip_id", "nunique"),
                represented_area_ha=("clipped_area_ha", "sum"),
            )
            .reset_index()
        )

        summary.insert(0, "distance_m", distance_m)
        pieces.append(summary)

    if not pieces:
        return pd.DataFrame()

    return pd.concat(
        pieces,
        ignore_index=True,
    )


def build_source_patch_summary(
    candidate_points: gpd.GeoDataFrame,
    selection_audit: pd.DataFrame,
) -> pd.DataFrame:
    base_fields = [
        "candidate_id",
        "point_id",
        "clip_id",
        "source_objectid",
        "source_uid",
        "aoi_unit_id",
        "aoi_unit_name",
        "class_id",
        "class_label",
        "stratum_id",
        "confidence",
        "clipped_area_ha",
    ]

    summary = candidate_points[base_fields].copy()

    selected = selection_audit.pivot_table(
        index="candidate_id",
        columns="distance_m",
        values="selected",
        aggfunc="max",
        fill_value=0,
    )

    selected.columns = [
        f"selected_d{int(distance):04d}"
        for distance in selected.columns
    ]

    selected = selected.reset_index()

    summary = summary.merge(
        selected,
        on="candidate_id",
        how="left",
        validate="one_to_one",
    )

    selected_columns = [
        column
        for column in summary.columns
        if column.startswith("selected_d")
    ]

    for column in selected_columns:
        summary[column] = (
            summary[column]
            .fillna(0)
            .astype(int)
        )

    return summary


def summarize_class_representation(
    candidate_points: gpd.GeoDataFrame,
    selection_audit: pd.DataFrame,
    class_field: str = "stratum_id",
) -> pd.DataFrame:
    if class_field not in candidate_points.columns:
        class_field = "stratum_id"

    base = (
        candidate_points.groupby(
            class_field,
            dropna=False,
        )
        .agg(
            n_candidates=("candidate_id", "size"),
            n_aoi_units=("aoi_unit_id", "nunique"),
            represented_candidate_area_ha=("clipped_area_ha", "sum"),
        )
        .reset_index()
        .rename(columns={class_field: "class_value"})
    )

    base.insert(0, "class_field", class_field)

    audit = selection_audit.merge(
        candidate_points[
            [
                "candidate_id",
                class_field,
            ]
        ],
        on="candidate_id",
        how="left",
        validate="many_to_one",
    )

    summary = (
        audit.groupby(
            [
                "distance_m",
                class_field,
            ],
            dropna=False,
        )
        .agg(
            n_selected=("selected", "sum"),
            n_protected=("protected", "sum"),
            n_selected_protected=(
                "selection_reason",
                lambda values: int(
                    values.isin(
                        [
                            "minimum_class_representation",
                            "priority_class_representation",
                        ]
                    ).sum()
                ),
            ),
        )
        .reset_index()
        .rename(columns={class_field: "class_value"})
    )

    output = summary.merge(
        base,
        on="class_value",
        how="left",
        validate="many_to_one",
    )

    output["missing_after_selection"] = (
        output["n_selected"] == 0
    ).astype(int)

    return output[
        [
            "distance_m",
            "class_field",
            "class_value",
            "n_candidates",
            "n_selected",
            "n_protected",
            "n_selected_protected",
            "missing_after_selection",
            "n_aoi_units",
            "represented_candidate_area_ha",
        ]
    ].sort_values(
        [
            "distance_m",
            "missing_after_selection",
            "class_value",
        ],
        ascending=[
            True,
            False,
            True,
        ],
    ).reset_index(drop=True)


def make_run_metadata(
    config: dict[str, Any],
    config_path: Path,
    aoi_path: Path,
    source_path: Path,
    processing_crs: str,
    output_crs: str,
) -> pd.DataFrame:
    metadata = {
        "project_name": config["project"]["name"],
        "source_name": config["project"]["source_name"],
        "source_prefix": get_source_prefix(config),
        "base_year": config["project"]["base_year"],
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "aoi_path": str(aoi_path),
        "source_path": str(source_path),
        "processing_crs": processing_crs,
        "output_crs": output_crs,
        "minimum_fragment_area_ha": config["geometry"].get(
            "minimum_fragment_area_ha",
            0.0,
        ),
        "thinning_distances_m": ",".join(
            str(value)
            for value in config["sampling"]["thinning_distances_m"]
        ),
        "configuration_json": json.dumps(
            config,
            ensure_ascii=False,
        ),
    }

    return pd.DataFrame(
        {
            "key": list(metadata.keys()),
            "value": [
                str(value)
                for value in metadata.values()
            ],
        }
    )


# ------------------------------------------------------------------
# Exportación
# ------------------------------------------------------------------

def write_spatial_layer(
    gdf: gpd.GeoDataFrame,
    gpkg_path: Path,
    layer_name: str,
    output_crs: str,
) -> None:
    output = gdf.copy()

    if output.crs is None:
        raise ValueError(f"La capa {layer_name} no tiene CRS.")

    output = output.to_crs(output_crs)

    LOGGER.info(
        "Exportando capa: %s | objetos=%s | CRS=%s",
        layer_name,
        f"{len(output):,}",
        output.crs,
    )

    output.to_file(
        gpkg_path,
        layer=layer_name,
        driver="GPKG",
        index=False,
    )


def register_attribute_table(
    connection: sqlite3.Connection,
    table_name: str,
) -> None:
    last_change = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%fZ"
    )

    connection.execute(
        """
        DELETE FROM gpkg_contents
        WHERE table_name = ?
        """,
        (table_name,),
    )

    connection.execute(
        """
        INSERT INTO gpkg_contents
        (
            table_name,
            data_type,
            identifier,
            description,
            last_change
        )
        VALUES
        (
            ?,
            'attributes',
            ?,
            '',
            ?
        )
        """,
        (
            table_name,
            table_name,
            last_change,
        ),
    )


def write_nonspatial_table(
    dataframe: pd.DataFrame,
    gpkg_path: Path,
    table_name: str,
) -> None:
    LOGGER.info(
        "Exportando tabla: %s | filas=%s",
        table_name,
        f"{len(dataframe):,}",
    )

    table = dataframe.copy()

    table = table.astype(object).where(
        pd.notna(table),
        None,
    )

    with sqlite3.connect(gpkg_path) as connection:
        table.to_sql(
            table_name,
            connection,
            if_exists="replace",
            index=False,
        )

        register_attribute_table(
            connection,
            table_name,
        )

        connection.commit()


def export_csv_tables(
    output_root: Path,
    tables: dict[str, pd.DataFrame],
) -> None:
    for filename, dataframe in tables.items():
        path = output_root / f"{filename}.csv"

        LOGGER.info("Exportando CSV: %s", path)

        dataframe.to_csv(
            path,
            index=False,
            encoding="utf-8-sig",
        )


# ------------------------------------------------------------------
# Ejecución
# ------------------------------------------------------------------

def run(config_path: Path) -> None:
    config_path = config_path.resolve()
    config = load_yaml(config_path)

    output_root = resolve_repo_path(
        config["outputs"]["root"]
    )

    ensure_directory(output_root)

    log_path = output_root / config["outputs"].get(
        "log_name",
        "mangrove_sampling.log",
    )

    configure_logger(log_path)

    gpkg_path = output_root / config["outputs"]["gpkg_name"]

    if gpkg_path.exists():
        LOGGER.info("Eliminando salida previa: %s", gpkg_path)
        gpkg_path.unlink()

    crs_cfg = config.get("crs", {})

    processing_crs = crs_cfg.get("processing_crs")

    if not processing_crs:
        raise ValueError("El YAML debe incluir crs.processing_crs.")

    output_crs = crs_cfg.get("output_crs", "EPSG:4326")

    validate_processing_crs(processing_crs)
    CRS.from_user_input(output_crs)

    aoi_cfg = config["inputs"]["aoi"]
    source_cfg = config["inputs"]["mangrove_source"]

    aoi_path = resolve_repo_path(aoi_cfg["path"])
    source_path = resolve_repo_path(source_cfg["path"])

    aoi = read_vector(
        aoi_path,
        aoi_cfg.get("layer"),
    )

    source = read_vector(
        source_path,
        source_cfg.get("layer"),
    )

    if config["geometry"].get("repair_invalid", True):
        aoi = repair_geometries(aoi, "AOI")
        source = repair_geometries(source, "fuente manglar")

    aoi = reproject(
        aoi,
        processing_crs,
        "AOI",
    )

    source = reproject(
        source,
        processing_crs,
        "fuente manglar",
    )

    aoi_units, aoi_union = prepare_aoi_units(
        aoi,
        config,
    )

    source = normalize_mangrove_source(
        source,
        config,
    )

    source_clipped = clip_mangrove_source_to_aoi(
        source=source,
        aoi_units=aoi_units,
        aoi_union=aoi_union,
        minimum_fragment_area_ha=float(
            config["geometry"].get(
                "minimum_fragment_area_ha",
                0.0,
            )
        ),
    )

    field_audit = build_field_audit(source_clipped)

    class_catalog = build_class_catalog(
        source_clipped,
        area_field="clipped_area_ha",
        polygon_id_field="clip_id",
    )

    candidate_points = create_candidate_points(
        source_clipped,
        config,
    )

    distances = [
        int(value)
        for value in config["sampling"]["thinning_distances_m"]
    ]

    selection_order = config["sampling"].get(
        "selection_order",
        [
            "area_desc",
            "objectid_asc",
        ],
    )

    class_rep_cfg = config.get("sampling", {}).get(
        "class_representation",
        {},
    )

    protected_candidates = select_protected_candidates(
        candidate_points,
        config,
        selection_order,
    )

    keep_protected = bool(
        class_rep_cfg.get(
            "keep_protected_points_even_if_close",
            True,
        )
    )

    selected_layers: dict[int, gpd.GeoDataFrame] = {}
    audit_pieces: list[pd.DataFrame] = []

    for distance_m in distances:
        LOGGER.info(
            "Aplicando separación mínima global: %s m",
            f"{distance_m:,}",
        )

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

    selection_audit = pd.concat(
        audit_pieces,
        ignore_index=True,
    )

    distance_summary = summarize_distances(selected_layers)
    aoi_summary = summarize_by_aoi_unit(selected_layers)
    class_summary = summarize_by_class(selected_layers)

    source_patch_summary = build_source_patch_summary(
        candidate_points,
        selection_audit,
    )

    class_representation_summary = summarize_class_representation(
        candidate_points,
        selection_audit,
        class_field=class_rep_cfg.get(
            "class_field",
            "stratum_id",
        ),
    )

    run_metadata = make_run_metadata(
        config=config,
        config_path=config_path,
        aoi_path=aoi_path,
        source_path=source_path,
        processing_crs=processing_crs,
        output_crs=output_crs,
    )

    layer_names = config["outputs"]["layers"]

    write_spatial_layer(
        aoi_units,
        gpkg_path,
        get_layer_name(layer_names, "aoi_units", "aoi_units"),
        output_crs,
    )

    write_spatial_layer(
        aoi_union,
        gpkg_path,
        get_layer_name(layer_names, "aoi_union", "aoi_union"),
        output_crs,
    )

    write_spatial_layer(
        source_clipped,
        gpkg_path,
        get_layer_name(layer_names, "source_clipped", "mangrove_source_clipped"),
        output_crs,
    )

    write_spatial_layer(
        candidate_points,
        gpkg_path,
        get_layer_name(layer_names, "candidate_points", "mangrove_candidate_points"),
        output_crs,
    )

    prefix = get_layer_name(
        layer_names,
        "thinned_prefix",
        "mangrove_points_d",
    )

    for distance_m, selected in selected_layers.items():
        layer_name = f"{prefix}{distance_m:04d}"

        write_spatial_layer(
            selected,
            gpkg_path,
            layer_name,
            output_crs,
        )

    nonspatial_tables = {
        get_layer_name(layer_names, "field_audit", "field_audit"): field_audit,
        get_layer_name(layer_names, "class_catalog", "class_catalog"): class_catalog,
        get_layer_name(layer_names, "distance_summary", "distance_summary"): distance_summary,
        get_layer_name(layer_names, "aoi_summary", "aoi_summary"): aoi_summary,
        get_layer_name(layer_names, "class_summary", "class_summary"): class_summary,
        get_layer_name(layer_names, "source_patch_summary", "source_patch_summary"): source_patch_summary,
        get_layer_name(layer_names, "class_representation_summary", "class_representation_summary"): class_representation_summary,
        get_layer_name(layer_names, "selection_audit", "selection_audit"): selection_audit,
        get_layer_name(layer_names, "run_metadata", "run_metadata"): run_metadata,
    }

    for table_name, dataframe in nonspatial_tables.items():
        write_nonspatial_table(
            dataframe,
            gpkg_path,
            table_name,
        )

    if config["outputs"].get("export_csv", True):
        export_csv_tables(
            output_root,
            {
                "field_audit": field_audit,
                "class_catalog": class_catalog,
                "distance_summary": distance_summary,
                "aoi_summary": aoi_summary,
                "class_summary": class_summary,
                "source_patch_summary": source_patch_summary,
                "class_representation_summary": class_representation_summary,
                "selection_audit": selection_audit,
                "run_metadata": run_metadata,
            },
        )

    LOGGER.info("Proceso finalizado correctamente.")
    LOGGER.info("GeoPackage: %s", gpkg_path)
    LOGGER.info("Log: %s", log_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extracción de puntos candidatos desde fuente de manglar consenso."
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