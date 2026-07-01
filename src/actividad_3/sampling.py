# -*- coding: utf-8 -*-
"""
Pipeline único para extraer puntos desde una fuente temática vectorial o raster.

La configuración incluida mantiene el caso INEGI Serie VII, pero el flujo queda preparado
para recibir otras fuentes temáticas con campos de clase definidos en el YAML.

Flujo:
1. Lee la capa de estados de México.
2. Selecciona Campeche (04), Chiapas (07), Quintana Roo (23) y Tabasco (27).
3. Excluye islas cuando así se indique en el YAML.
4. Reproyecta temporalmente a un CRS métrico.
5. Convierte la fuente temática a puntos candidatos normalizados.
6. En fuentes vectoriales, genera un punto interior por fragmento recortado.
7. En fuentes raster, extrae valores de clase sobre una malla de candidatos.
8. Protege una representación mínima por clase, si se activa en el YAML.
9. Aplica varios escenarios de separación mínima global.
10. Audita y exporta el conjunto usado en el muestreo, en EPSG:4326.

Ejecución desde la raíz del repositorio:

    python src/actividad_3/run_inegi_sampling.py

También puede indicarse otro YAML:

    python src/actividad_3/run_inegi_sampling.py --config config/inegi_sampling.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ------------------------------------------------------------------
# Ayuda a localizar GDAL/PROJ dentro de un entorno Conda en Windows.
# Debe ejecutarse antes de importar GeoPandas/Pyogrio.
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

try:
    import rasterio
except ImportError:
    rasterio = None


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "inegi_sampling.yaml"

LOGGER = logging.getLogger("inegi_sampling")

# ------------------------------------------------------------------
# Reglas temáticas mínimas para interpretar CLAVE/DESCRIPCIO
# ------------------------------------------------------------------

AGRICULTURE_KEYS = {
    "TA", "TS", "TP", "TAS", "TAP", "TSP",
    "RA", "RS", "RP", "RAS", "RAP", "RSP",
    "HA", "HS", "HP", "HAS", "HAP", "HSP",
}

PRODUCTIVE_SYSTEM_KEYS = {
    "ACUI",  # Acuícola
    "PC",    # Pastizal cultivado
    "BC",    # Bosque cultivado
}

OTHER_FEATURE_KEYS = {
    "H2O",   # Agua
    "AH",    # Urbano construido
    "ADV",   # Área desprovista de vegetación
    "DV",    # Sin vegetación aparente
}

INDUCED_VEGETATION_KEYS = {
    "PI",    # Pastizal inducido
    "VSI",   # Sabanoide
    "VPI",   # Palmar inducido
    "BI",    # Bosque inducido
}

SECONDARY_PREFIXES = {
    "VSA/": "Arbórea",
    "VSa/": "Arbustiva",
    "VSh/": "Herbácea",
}

VEGETATION_DESCRIPTION_TERMS = (
    "BOSQUE",
    "SELVA",
    "MATORRAL",
    "PASTIZAL",
    "VEGETACIÓN",
    "VEGETACION",
    "SABANA",
    "SABANOIDE",
    "CHAPARRAL",
    "MANGLAR",
    "POPAL",
    "TULAR",
    "PALMAR",
    "PRADERA",
    "MEZQUITAL",
)



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
# Configuración y rutas
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


def get_thematic_source_config(config: dict[str, Any]) -> dict[str, Any]:
    """
    Devuelve la configuración de la fuente temática.

    Se mantiene compatibilidad con el YAML anterior, donde la fuente estaba en
    inputs.land_cover. La versión nueva usa inputs.thematic_source con
    source_type: vector | raster.
    """
    inputs = config.get("inputs", {})

    if "thematic_source" in inputs:
        source_cfg = inputs["thematic_source"].copy()
        source_type = str(source_cfg.get("source_type", "vector")).lower()
        source_cfg["source_type"] = source_type
        return source_cfg

    if "land_cover" not in inputs:
        raise ValueError(
            "El YAML debe incluir inputs.thematic_source o inputs.land_cover."
        )

    legacy = inputs["land_cover"]
    fields = legacy.get("fields", {})

    return {
        "source_type": "vector",
        "vector": {
            "path": legacy["path"],
            "layer": legacy.get("layer"),
            "fields": {
                "object_id": fields.get("object_id"),
                "class_id": fields.get("class_id", fields.get("key")),
                "class_label": fields.get(
                    "class_label",
                    fields.get("description"),
                ),
            },
        },
    }


def get_vector_source_config(config: dict[str, Any]) -> dict[str, Any]:
    source_cfg = get_thematic_source_config(config)

    if source_cfg.get("source_type") != "vector":
        raise ValueError(
            "La fuente temática configurada no es vectorial."
        )

    if "vector" not in source_cfg:
        raise ValueError(
            "La fuente temática vectorial debe incluir thematic_source.vector."
        )

    return source_cfg["vector"]


def get_raster_source_config(config: dict[str, Any]) -> dict[str, Any]:
    source_cfg = get_thematic_source_config(config)

    if source_cfg.get("source_type") != "raster":
        raise ValueError(
            "La fuente temática configurada no es raster."
        )

    if "raster" not in source_cfg:
        raise ValueError(
            "La fuente temática raster debe incluir thematic_source.raster."
        )

    return source_cfg["raster"]


def get_source_type(config: dict[str, Any]) -> str:
    return get_thematic_source_config(config).get("source_type", "vector")


def get_layer_name(
    layer_names: dict[str, str],
    key: str,
    default: str,
) -> str:
    return layer_names.get(key, default)


def load_optional_class_table(
    table_path: str | Path | None,
    class_id_field: str,
    class_label_field: str,
) -> dict[str, str]:
    if not table_path:
        return {}

    path = resolve_repo_path(table_path)
    if not path.exists():
        raise FileNotFoundError(
            f"No existe la tabla de clases raster: {path}"
        )

    if path.suffix.lower() in {".xlsx", ".xls"}:
        table = pd.read_excel(path)
    else:
        table = pd.read_csv(path)

    require_fields(
        table,
        [class_id_field, class_label_field],
        "tabla de clases raster",
    )

    class_ids = (
        table[class_id_field]
        .astype("string")
        .str.strip()
    )
    labels = (
        table[class_label_field]
        .astype("string")
        .str.strip()
    )

    return dict(zip(class_ids, labels))


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
    gdf: gpd.GeoDataFrame,
    fields: list[str],
    label: str,
) -> None:
    missing = [field for field in fields if field not in gdf.columns]

    if missing:
        raise ValueError(
            f"Faltan campos obligatorios en {label}: {missing}\n"
            f"Campos disponibles: {list(gdf.columns)}"
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
# Área de interés
# ------------------------------------------------------------------

def prepare_aoi(
    states: gpd.GeoDataFrame,
    config: dict[str, Any],
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    state_cfg = config["inputs"]["states"]
    field_cfg = state_cfg["fields"]

    code_field = field_cfg["state_code"]
    name_field = field_cfg["state_name"]
    feature_field = field_cfg["geographic_feature"]

    state_codes = [
        str(value).strip().zfill(2)
        for value in config["aoi"]["state_codes"]
    ]

    output = states.copy()
    output[code_field] = (
        output[code_field]
        .astype("string")
        .str.strip()
        .str.zfill(2)
    )

    output = output.loc[
        output[code_field].isin(state_codes)
    ].copy()

    if output.empty:
        raise ValueError(
            "El filtro de estados no devolvió geometrías. "
            f"Códigos solicitados: {state_codes}"
        )

    found_codes = set(
        output[code_field]
        .dropna()
        .astype(str)
        .str.zfill(2)
        .unique()
        .tolist()
    )
    missing_codes = sorted(set(state_codes) - found_codes)

    if missing_codes:
        raise ValueError(
            "No se encontraron todos los estados solicitados. "
            f"Códigos faltantes: {missing_codes}"
        )

    exclusion_cfg = config["aoi"].get(
        "exclude_geographic_features",
        {},
    )

    if exclusion_cfg.get("enabled", False):
        excluded_values = {
            str(value).strip().upper()
            for value in exclusion_cfg.get("values", [])
        }

        feature_normalized = (
            output[feature_field]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper()
        )

        excluded_mask = feature_normalized.isin(excluded_values)
        LOGGER.info(
            "Objetos excluidos por %s: %s",
            feature_field,
            f"{int(excluded_mask.sum()):,}",
        )
        output = output.loc[~excluded_mask].copy()

    if output.empty:
        raise ValueError(
            "No quedaron geometrías estatales después de aplicar "
            "las exclusiones."
        )

    remaining_codes = set(
        output[code_field]
        .dropna()
        .astype(str)
        .str.zfill(2)
        .unique()
        .tolist()
    )
    missing_after_exclusion = sorted(
        set(state_codes) - remaining_codes
    )

    if missing_after_exclusion:
        raise ValueError(
            "Uno o más estados quedaron sin geometría después de "
            "aplicar las exclusiones. "
            f"Códigos: {missing_after_exclusion}"
        )

    LOGGER.info("Disolviendo geometrías por estado")
    output = output.dissolve(
        by=[code_field, name_field],
        as_index=False,
        dropna=False,
    )

    output = output.rename(
        columns={
            code_field: "num_edo",
            name_field: "entidad",
        }
    )

    output["num_edo"] = (
        output["num_edo"]
        .astype("string")
        .str.strip()
        .str.zfill(2)
    )
    output["entidad"] = (
        output["entidad"]
        .astype("string")
        .str.strip()
        .str.upper()
    )
    output["aoi_area_ha"] = output.geometry.area / 10_000.0

    output = output[
        ["num_edo", "entidad", "aoi_area_ha", "geometry"]
    ].copy()

    aoi_name = "_".join(
        output.sort_values("num_edo")["entidad"]
        .astype(str)
        .str.replace(" ", "_", regex=False)
        .tolist()
    )

    try:
        union_geometry = output.geometry.union_all()
    except AttributeError:
        union_geometry = output.geometry.unary_union

    aoi_union = gpd.GeoDataFrame(
        {
            "aoi_id": [1],
            "aoi_name": [aoi_name],
        },
        geometry=[union_geometry],
        crs=output.crs,
    )
    aoi_union["aoi_area_ha"] = (
        aoi_union.geometry.area / 10_000.0
    )

    LOGGER.info(
        "AOI preparado | estados=%s | área total=%.2f ha",
        len(output),
        float(aoi_union["aoi_area_ha"].iloc[0]),
    )

    return output.reset_index(drop=True), aoi_union


# ------------------------------------------------------------------
# Continuo nacional Serie VII
# ------------------------------------------------------------------

def classify_domain(
    key: Any,
    description: Any,
) -> str:
    if pd.isna(key):
        return "SIN_CLAVE"

    clean_key = str(key).strip()
    clean_description = (
        ""
        if pd.isna(description)
        else str(description).strip().upper()
    )

    if clean_key in AGRICULTURE_KEYS:
        return "AGRICULTURA"

    if clean_key in PRODUCTIVE_SYSTEM_KEYS:
        return "SISTEMA_PRODUCTIVO"

    if clean_key in OTHER_FEATURE_KEYS:
        return "OTRO_RASGO"

    if any(
        clean_key.startswith(prefix)
        for prefix in SECONDARY_PREFIXES
    ):
        return "VEGETACION"

    if any(
        term in clean_description
        for term in VEGETATION_DESCRIPTION_TERMS
    ):
        return "VEGETACION"

    return "POR_REVISAR"


def derive_key_attributes(
    key: Any,
    domain: str,
) -> tuple[Any, Any, Any]:
    if pd.isna(key):
        return pd.NA, pd.NA, pd.NA

    clean_key = str(key).strip()

    for prefix, phase in SECONDARY_PREFIXES.items():
        if clean_key.startswith(prefix):
            return (
                clean_key[len(prefix):],
                "Secundaria",
                phase,
            )

    if domain == "VEGETACION":
        if clean_key in INDUCED_VEGETATION_KEYS:
            return clean_key, "Inducida", pd.NA

        return (
            clean_key,
            "Sin prefijo secundario",
            pd.NA,
        )

    return clean_key, pd.NA, pd.NA


def derive_class_type(
    description: Any,
) -> Any:
    if pd.isna(description):
        return pd.NA

    clean_description = str(description).strip()

    pattern = (
        r"^VEGETACI[ÓO]N SECUNDARIA "
        r"(ARB[ÓO]REA|ARBUSTIVA|HERB[ÁA]CEA) DE "
    )

    return re.sub(
        pattern,
        "",
        clean_description,
        flags=re.IGNORECASE,
    ).strip()


def build_source_uid(
    key: Any,
    description: Any,
    geometry: Any,
) -> str:
    key_text = "" if pd.isna(key) else str(key).strip()
    description_text = (
        ""
        if pd.isna(description)
        else str(description).strip()
    )

    geometry_bytes = (
        b""
        if geometry is None or geometry.is_empty
        else geometry.wkb
    )

    digest = hashlib.sha1()
    digest.update(key_text.encode("utf-8"))
    digest.update(b"|")
    digest.update(description_text.encode("utf-8"))
    digest.update(b"|")
    digest.update(geometry_bytes)

    return f"INEGI_{digest.hexdigest()[:20]}"


def normalize_land_cover_fields(
    land_cover: gpd.GeoDataFrame,
    config: dict[str, Any],
) -> gpd.GeoDataFrame:
    vector_cfg = get_vector_source_config(config)
    fields = vector_cfg["fields"]

    object_id_field = fields.get("object_id")
    key_field = fields.get("class_id", fields.get("key"))
    description_field = fields.get(
        "class_label",
        fields.get("description"),
    )

    if key_field is None or description_field is None:
        raise ValueError(
            "La fuente vectorial debe indicar fields.class_id y "
            "fields.class_label."
        )

    require_fields(
        land_cover,
        [key_field, description_field],
        "fuente temática vectorial",
    )

    output = land_cover.copy()

    if object_id_field:
        require_fields(
            output,
            [object_id_field],
            "fuente temática vectorial",
        )
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
            key_field: "clave",
            description_field: "descripcion",
        }
    )

    output["clave"] = (
        output["clave"]
        .astype("string")
        .str.strip()
    )
    output["descripcion"] = (
        output["descripcion"]
        .astype("string")
        .str.strip()
    )

    output["class_id"] = output["clave"]
    output["class_label"] = output["descripcion"]
    output["source_type"] = "vector"

    output["source_uid"] = [
        build_source_uid(
            key,
            description,
            geometry,
        )
        for key, description, geometry in zip(
            output["clave"],
            output["descripcion"],
            output.geometry,
        )
    ]
    output["source_id_origin"] = source_id_origin

    output["dominio_inegi"] = [
        classify_domain(key, description)
        for key, description in zip(
            output["clave"],
            output["descripcion"],
        )
    ]

    derived = [
        derive_key_attributes(key, domain)
        for key, domain in zip(
            output["clave"],
            output["dominio_inegi"],
        )
    ]

    output["clave_base"] = [
        values[0]
        for values in derived
    ]
    output["estado_vegetacion"] = [
        values[1]
        for values in derived
    ]
    output["fase_vegetacion"] = [
        values[2]
        for values in derived
    ]
    output["tipo_clase"] = output["descripcion"].map(
        derive_class_type
    )

    output["stratum_id"] = (
        output["clave"]
        .fillna("SIN_CLAVE")
        .astype(str)
        .str.strip()
        + " | "
        + output["descripcion"]
        .fillna("SIN_DESCRIPCION")
        .astype(str)
        .str.strip()
    )

    output["source_area_ha"] = (
        output.geometry.area / 10_000.0
    )

    unknown_count = int(
        (output["dominio_inegi"] == "POR_REVISAR").sum()
    )
    if unknown_count:
        LOGGER.warning(
            "Clases marcadas como POR_REVISAR: %s polígonos",
            f"{unknown_count:,}",
        )

    keep_fields = [
        "source_objectid",
        "source_uid",
        "source_id_origin",
        "source_type",
        "clave",
        "descripcion",
        "class_id",
        "class_label",
        "dominio_inegi",
        "clave_base",
        "tipo_clase",
        "estado_vegetacion",
        "fase_vegetacion",
        "stratum_id",
        "source_area_ha",
        "geometry",
    ]

    LOGGER.info(
        "Fuente vectorial normalizada | polígonos=%s | "
        "clases=%s | dominios=%s",
        f"{len(output):,}",
        f"{output['clave'].nunique(dropna=True):,}",
        f"{output['dominio_inegi'].nunique(dropna=True):,}",
    )

    return output[keep_fields].copy()

def build_field_audit(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    fields = [
        "source_objectid",
        "source_uid",
        "clave",
        "descripcion",
        "dominio_inegi",
        "clave_base",
        "tipo_clase",
        "estado_vegetacion",
        "fase_vegetacion",
        "stratum_id",
    ]

    total = len(dataframe)
    rows: list[dict[str, Any]] = []

    for field in fields:
        if field not in dataframe.columns:
            continue

        null_count = int(
            dataframe[field].isna().sum()
        )

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
                "n_unique": int(
                    dataframe[field].nunique(
                        dropna=True
                    )
                ),
            }
        )

    return pd.DataFrame(rows)


def build_class_catalog(
    dataframe: pd.DataFrame,
    area_field: str,
    polygon_id_field: str,
) -> pd.DataFrame:
    group_fields = [
        "clave",
        "descripcion",
        "dominio_inegi",
        "clave_base",
        "tipo_clase",
        "estado_vegetacion",
        "fase_vegetacion",
        "stratum_id",
    ]

    catalog = (
        dataframe.groupby(
            group_fields,
            dropna=False,
        )
        .agg(
            n_polygons=(
                polygon_id_field,
                "nunique",
            ),
            area_ha=(
                area_field,
                "sum",
            ),
        )
        .reset_index()
    )

    return catalog.sort_values(
        [
            "dominio_inegi",
            "clave",
            "descripcion",
        ],
        na_position="last",
    ).reset_index(drop=True)


def clip_land_cover_to_states(
    land_cover: gpd.GeoDataFrame,
    aoi_states: gpd.GeoDataFrame,
    aoi_union: gpd.GeoDataFrame,
    minimum_area_ha: float,
) -> gpd.GeoDataFrame:
    LOGGER.info(
        "Seleccionando polígonos de la Serie VII que "
        "intersectan el AOI"
    )

    union_geometry = aoi_union.geometry.iloc[0]
    subset = land_cover.loc[
        land_cover.geometry.intersects(
            union_geometry
        )
    ].copy()

    LOGGER.info(
        "Polígonos candidatos antes de la intersección: %s",
        f"{len(subset):,}",
    )

    LOGGER.info(
        "Intersectando Serie VII con los estados seleccionados"
    )

    output = gpd.overlay(
        subset,
        aoi_states[
            ["num_edo", "entidad", "geometry"]
        ],
        how="intersection",
        keep_geom_type=False,
    )

    polygon_mask = output.geometry.geom_type.isin(
        ["Polygon", "MultiPolygon"]
    )
    dropped = int((~polygon_mask).sum())

    if dropped:
        LOGGER.info(
            "Geometrías no poligonales descartadas después "
            "de la intersección: %s",
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
        raise ValueError(
            "La intersección Serie VII × estados no produjo "
            "polígonos."
        )

    output["clip_id"] = np.arange(
        1,
        len(output) + 1,
        dtype=np.int64,
    )
    output["clipped_area_ha"] = (
        output.geometry.area / 10_000.0
    )

    if minimum_area_ha > 0:
        before = len(output)
        output = output.loc[
            output["clipped_area_ha"]
            >= minimum_area_ha
        ].copy()

        LOGGER.info(
            "Fragmentos eliminados por área mínima "
            "%.4f ha: %s",
            minimum_area_ha,
            f"{before - len(output):,}",
        )

    keep_fields = [
        "clip_id",
        "source_objectid",
        "source_uid",
        "source_id_origin",
        "source_type",
        "num_edo",
        "entidad",
        "clave",
        "descripcion",
        "class_id",
        "class_label",
        "dominio_inegi",
        "clave_base",
        "tipo_clase",
        "estado_vegetacion",
        "fase_vegetacion",
        "stratum_id",
        "source_area_ha",
        "clipped_area_ha",
        "geometry",
    ]

    LOGGER.info(
        "Serie VII recortada | fragmentos=%s | "
        "polígonos fuente=%s | estratos=%s",
        f"{len(output):,}",
        f"{output['source_objectid'].nunique():,}",
        f"{output['stratum_id'].nunique():,}",
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
            "Actualmente solo se admite "
            "representative_point_method: point_on_surface"
        )

    LOGGER.info(
        "Generando un punto interior por fragmento de polígono"
    )

    output = clipped.drop(
        columns="geometry"
    ).copy()

    output = gpd.GeoDataFrame(
        output,
        geometry=(
            clipped.geometry.representative_point()
        ),
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
    output["point_id"] = output["candidate_id"].map(
        lambda value: f"INEGI_{value:07d}"
    )
    output["source_name"] = (
        config["project"]["source_name"]
    )
    output["base_year"] = int(
        config["project"]["base_year"]
    )
    output["extraction_method"] = (
        "point_on_surface_per_clipped_polygon"
    )

    first_fields = [
        "candidate_id",
        "point_id",
        "clip_id",
        "source_objectid",
        "source_uid",
        "source_id_origin",
        "source_type",
        "num_edo",
        "entidad",
        "clave",
        "descripcion",
        "class_id",
        "class_label",
        "dominio_inegi",
        "clave_base",
        "tipo_clase",
        "estado_vegetacion",
        "fase_vegetacion",
        "stratum_id",
        "source_area_ha",
        "clipped_area_ha",
        "source_name",
        "base_year",
        "extraction_method",
        "geometry",
    ]

    LOGGER.info(
        "Puntos candidatos generados: %s",
        f"{len(output):,}",
    )

    return output[
        first_fields
    ].reset_index(drop=True)


def create_raster_candidate_points(
    aoi_states: gpd.GeoDataFrame,
    aoi_union: gpd.GeoDataFrame,
    config: dict[str, Any],
    processing_crs: str,
) -> gpd.GeoDataFrame:
    """
    Genera puntos candidatos desde un raster temático mediante una malla simple.

    Esta opción mantiene la metodología genérica: el valor del píxel se convierte
    en class_id y, si existe una tabla externa, se añade class_label.
    """
    if rasterio is None:
        raise ImportError(
            "Para usar source_type: raster se requiere instalar rasterio."
        )

    raster_cfg = get_raster_source_config(config)
    raster_path = resolve_repo_path(raster_cfg["path"])
    band = int(raster_cfg.get("band", 1))
    nodata_cfg = raster_cfg.get("nodata")

    sampling_cfg = config.get("sampling", {})
    raster_sampling_cfg = sampling_cfg.get("raster_sampling", {})
    candidate_spacing_m = float(
        raster_sampling_cfg.get("candidate_spacing_m", 500)
    )

    if candidate_spacing_m <= 0:
        raise ValueError(
            "sampling.raster_sampling.candidate_spacing_m debe ser mayor que cero."
        )

    class_fields = raster_cfg.get("fields", {})
    class_id_field = class_fields.get("class_id", "value")
    class_label_field = class_fields.get("class_label", "label")
    class_lookup = load_optional_class_table(
        raster_cfg.get("class_table"),
        class_id_field=class_id_field,
        class_label_field=class_label_field,
    )

    LOGGER.info(
        "Generando candidatos raster | raster=%s | espaciamiento=%.2f m",
        raster_path,
        candidate_spacing_m,
    )

    if not raster_path.exists():
        raise FileNotFoundError(
            f"No existe el raster temático: {raster_path}"
        )

    union_geometry = aoi_union.geometry.iloc[0]
    minx, miny, maxx, maxy = union_geometry.bounds

    xs = np.arange(
        minx + candidate_spacing_m / 2.0,
        maxx,
        candidate_spacing_m,
    )
    ys = np.arange(
        miny + candidate_spacing_m / 2.0,
        maxy,
        candidate_spacing_m,
    )

    if len(xs) == 0 or len(ys) == 0:
        raise ValueError(
            "La malla raster no generó candidatos. Revise AOI y candidate_spacing_m."
        )

    mesh_x, mesh_y = np.meshgrid(xs, ys)
    grid = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(
            mesh_x.ravel(),
            mesh_y.ravel(),
        ),
        crs=processing_crs,
    )

    grid = grid.loc[
        grid.geometry.within(union_geometry)
    ].copy()

    if grid.empty:
        raise ValueError(
            "La malla raster no produjo puntos dentro del AOI."
        )

    # Asigna estado antes de muestrear el raster para mantener resúmenes por país/estado.
    grid = gpd.sjoin(
        grid,
        aoi_states[["num_edo", "entidad", "geometry"]],
        how="inner",
        predicate="within",
    ).drop(columns=["index_right"])

    if grid.empty:
        raise ValueError(
            "No se pudieron asignar estados a los candidatos raster."
        )

    with rasterio.open(raster_path) as dataset:
        raster_crs = dataset.crs
        if raster_crs is None:
            raise ValueError(
                f"El raster no tiene CRS definido: {raster_path}"
            )

        sample_points = grid.to_crs(raster_crs)
        coordinates = [
            (geom.x, geom.y)
            for geom in sample_points.geometry
        ]
        values = [
            value[0]
            for value in dataset.sample(
                coordinates,
                indexes=band,
            )
        ]

        nodata = dataset.nodata if nodata_cfg is None else nodata_cfg

    output = grid.copy()
    output["raster_value"] = values

    valid = pd.notna(output["raster_value"])
    if nodata is not None:
        valid &= output["raster_value"] != nodata

    output = output.loc[valid].copy()

    if output.empty:
        raise ValueError(
            "No quedaron candidatos raster después de excluir nodata."
        )

    output["candidate_id"] = np.arange(
        1,
        len(output) + 1,
        dtype=np.int64,
    )
    output["point_id"] = output["candidate_id"].map(
        lambda value: f"SRC_{value:07d}"
    )
    output["clip_id"] = output["candidate_id"]
    output["source_objectid"] = output["candidate_id"]
    output["source_id_origin"] = "raster_grid_candidate"
    output["source_type"] = "raster"
    output["clave"] = (
        output["raster_value"]
        .astype("string")
        .str.strip()
    )
    output["class_id"] = output["clave"]
    output["descripcion"] = output["class_id"].map(
        class_lookup
    )
    output["descripcion"] = output["descripcion"].fillna(
        "Clase " + output["class_id"].astype(str)
    )
    output["class_label"] = output["descripcion"]

    output["source_uid"] = [
        build_source_uid(
            key,
            description,
            geometry,
        )
        for key, description, geometry in zip(
            output["clave"],
            output["descripcion"],
            output.geometry,
        )
    ]

    output["dominio_inegi"] = [
        classify_domain(key, description)
        for key, description in zip(
            output["clave"],
            output["descripcion"],
        )
    ]
    derived = [
        derive_key_attributes(key, domain)
        for key, domain in zip(
            output["clave"],
            output["dominio_inegi"],
        )
    ]
    output["clave_base"] = [values[0] for values in derived]
    output["estado_vegetacion"] = [values[1] for values in derived]
    output["fase_vegetacion"] = [values[2] for values in derived]
    output["tipo_clase"] = output["descripcion"].map(
        derive_class_type
    )
    output["stratum_id"] = (
        output["clave"]
        .fillna("SIN_CLAVE")
        .astype(str)
        .str.strip()
        + " | "
        + output["descripcion"]
        .fillna("SIN_DESCRIPCION")
        .astype(str)
        .str.strip()
    )

    support_area_ha = (candidate_spacing_m * candidate_spacing_m) / 10_000.0
    output["source_area_ha"] = support_area_ha
    output["clipped_area_ha"] = support_area_ha
    output["source_name"] = config["project"]["source_name"]
    output["base_year"] = int(config["project"]["base_year"])
    output["extraction_method"] = "raster_grid_value"

    first_fields = [
        "candidate_id",
        "point_id",
        "clip_id",
        "source_objectid",
        "source_uid",
        "source_id_origin",
        "source_type",
        "num_edo",
        "entidad",
        "clave",
        "descripcion",
        "class_id",
        "class_label",
        "dominio_inegi",
        "clave_base",
        "tipo_clase",
        "estado_vegetacion",
        "fase_vegetacion",
        "stratum_id",
        "source_area_ha",
        "clipped_area_ha",
        "source_name",
        "base_year",
        "extraction_method",
        "geometry",
    ]

    LOGGER.info(
        "Candidatos raster generados: %s | clases=%s",
        f"{len(output):,}",
        f"{output['stratum_id'].nunique(dropna=True):,}",
    )

    return output[first_fields].reset_index(drop=True)


# ------------------------------------------------------------------
# Filtrado por distancia
# ------------------------------------------------------------------

def get_candidate_sort_frame(
    points: gpd.GeoDataFrame,
    selection_order: list[str],
) -> gpd.GeoDataFrame:
    """Orden estable de candidatos; se reutiliza para selección y protección."""
    return order_candidates(
        points,
        selection_order,
    )


def select_protected_candidates(
    points: gpd.GeoDataFrame,
    config: dict[str, Any],
    selection_order: list[str],
) -> pd.DataFrame:
    """
    Selecciona candidatos protegidos para asegurar representación mínima por clase.

    La regla es simple: para cada valor de class_field se protegen los primeros N
    candidatos según selection_order. Las clases prioritarias pueden tener un N mayor.
    """
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
        raise ValueError(
            "minimum_points_per_class no puede ser negativo."
        )

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

    ordered = get_candidate_sort_frame(
        points,
        selection_order,
    )

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
            sort_fields.append(
                "clipped_area_ha"
            )
            ascending.append(False)

        elif rule == "area_asc":
            sort_fields.append(
                "clipped_area_ha"
            )
            ascending.append(True)

        elif rule == "objectid_asc":
            sort_fields.append(
                "_source_sort"
            )
            ascending.append(True)

        elif rule == "objectid_desc":
            sort_fields.append(
                "_source_sort"
            )
            ascending.append(False)

        else:
            raise ValueError(
                f"Regla de orden no reconocida: {rule}"
            )

    if "candidate_id" not in sort_fields:
        sort_fields.append("candidate_id")
        ascending.append(True)

    output = output.sort_values(
        sort_fields,
        ascending=ascending,
        kind="mergesort",
    )

    return output.drop(
        columns="_source_sort"
    ).reset_index(drop=True)


def thin_points_by_distance(
    points: gpd.GeoDataFrame,
    distance_m: float,
    selection_order: list[str],
    protected_candidates: pd.DataFrame | None = None,
    keep_protected_points_even_if_close: bool = True,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """
    Filtrado greedy con índice espacial basado en celdas.

    La lógica sigue siendo simple:
    1. Se aceptan primero los candidatos protegidos por representación mínima.
    2. Luego se aplica la distancia mínima al resto.
    """
    if distance_m <= 0:
        raise ValueError(
            "La distancia mínima debe ser mayor que cero."
        )

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

    spatial_cells: dict[
        tuple[int, int],
        list[int],
    ] = {}

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
                        accepted_x, accepted_y = (
                            accepted_coords[accepted_index]
                        )

                        delta_x = x - accepted_x
                        delta_y = y - accepted_y
                        candidate_distance_sq = (
                            delta_x * delta_x
                            + delta_y * delta_y
                        )

                        if candidate_distance_sq < distance_sq:
                            blocker_candidate_id = (
                                accepted_candidate_ids[
                                    accepted_index
                                ]
                            )
                            blocker_distance_m = math.sqrt(
                                candidate_distance_sq
                            )
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
        ordered["ordered_row_id"].isin(
            accepted_ordered_row_ids
        )
    ].copy()
    selected_points = selected_points.drop(
        columns=["ordered_row_id", "_is_protected"],
        errors="ignore",
    )

    selected_points["distance_scenario_m"] = int(
        distance_m
    )
    selected_points["selection_status"] = selected_points[
        "candidate_id"
    ].map(
        lambda value: accepted_reasons.get(
            int(value),
            "selected",
        )
    )
    selected_points["protected"] = selected_points[
        "candidate_id"
    ].map(
        lambda value: int(int(value) in protected_lookup)
    )
    selected_points["nearest_neighbor_m"] = (
        calculate_nearest_neighbor_distance(
            selected_points
        )
    )

    audit = pd.DataFrame(audit_rows)

    return (
        selected_points.reset_index(drop=True),
        audit,
    )

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
            "SciPy no está disponible. "
            "nearest_neighbor_m se dejará vacío."
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

def summarize_distances(
    selected_layers: dict[
        int,
        gpd.GeoDataFrame,
    ],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for distance_m, points in selected_layers.items():
        nearest = points["nearest_neighbor_m"]

        rows.append(
            {
                "distance_m": distance_m,
                "n_points": len(points),
                "n_states": (
                    points["num_edo"].nunique()
                ),
                "n_domains": (
                    points["dominio_inegi"].nunique()
                ),
                "n_claves": (
                    points["clave"].nunique()
                ),
                "n_strata": (
                    points["stratum_id"].nunique()
                ),
                "n_source_polygons": (
                    points["source_objectid"].nunique()
                ),
                "n_clipped_polygons": (
                    points["clip_id"].nunique()
                ),
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


def summarize_by_state(
    selected_layers: dict[
        int,
        gpd.GeoDataFrame,
    ],
) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []

    for distance_m, points in selected_layers.items():
        summary = (
            points.groupby(
                ["num_edo", "entidad"],
                dropna=False,
            )
            .agg(
                n_points=(
                    "candidate_id",
                    "size",
                ),
                n_domains=(
                    "dominio_inegi",
                    "nunique",
                ),
                n_claves=(
                    "clave",
                    "nunique",
                ),
                n_strata=(
                    "stratum_id",
                    "nunique",
                ),
                n_source_polygons=(
                    "source_uid",
                    "nunique",
                ),
                n_clipped_polygons=(
                    "clip_id",
                    "nunique",
                ),
            )
            .reset_index()
        )

        summary.insert(
            0,
            "distance_m",
            distance_m,
        )
        pieces.append(summary)

    if not pieces:
        return pd.DataFrame()

    return pd.concat(
        pieces,
        ignore_index=True,
    )


def summarize_by_domain(
    selected_layers: dict[
        int,
        gpd.GeoDataFrame,
    ],
) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []

    for distance_m, points in selected_layers.items():
        summary = (
            points.groupby(
                ["dominio_inegi"],
                dropna=False,
            )
            .agg(
                n_points=(
                    "candidate_id",
                    "size",
                ),
                n_states=(
                    "num_edo",
                    "nunique",
                ),
                n_claves=(
                    "clave",
                    "nunique",
                ),
                n_source_polygons=(
                    "source_uid",
                    "nunique",
                ),
                n_clipped_polygons=(
                    "clip_id",
                    "nunique",
                ),
                represented_clipped_area_ha=(
                    "clipped_area_ha",
                    "sum",
                ),
            )
            .reset_index()
        )

        summary.insert(
            0,
            "distance_m",
            distance_m,
        )
        pieces.append(summary)

    if not pieces:
        return pd.DataFrame()

    return pd.concat(
        pieces,
        ignore_index=True,
    )


def summarize_by_class(
    selected_layers: dict[
        int,
        gpd.GeoDataFrame,
    ],
) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []

    group_fields = [
        "clave",
        "descripcion",
        "dominio_inegi",
        "clave_base",
        "tipo_clase",
        "estado_vegetacion",
        "fase_vegetacion",
        "stratum_id",
    ]

    for distance_m, points in selected_layers.items():
        summary = (
            points.groupby(
                group_fields,
                dropna=False,
            )
            .agg(
                n_points=(
                    "candidate_id",
                    "size",
                ),
                n_states=(
                    "num_edo",
                    "nunique",
                ),
                n_source_polygons=(
                    "source_uid",
                    "nunique",
                ),
                n_clipped_polygons=(
                    "clip_id",
                    "nunique",
                ),
                represented_clipped_area_ha=(
                    "clipped_area_ha",
                    "sum",
                ),
            )
            .reset_index()
        )

        summary.insert(
            0,
            "distance_m",
            distance_m,
        )
        pieces.append(summary)

    if not pieces:
        return pd.DataFrame()

    return pd.concat(
        pieces,
        ignore_index=True,
    )


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
            n_states=("num_edo", "nunique"),
            represented_candidate_area_ha=(
                "clipped_area_ha",
                "sum",
            ),
        )
        .reset_index()
        .rename(columns={class_field: "class_value"})
    )
    base.insert(0, "class_field", class_field)

    audit = selection_audit.merge(
        candidate_points[["candidate_id", class_field]],
        on="candidate_id",
        how="left",
        validate="many_to_one",
    )

    summary = (
        audit.groupby(
            ["distance_m", class_field],
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
            "n_states",
            "represented_candidate_area_ha",
        ]
    ].sort_values(
        ["distance_m", "missing_after_selection", "class_value"],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def build_polygon_summary(
    candidate_points: gpd.GeoDataFrame,
    selection_audit: pd.DataFrame,
) -> pd.DataFrame:
    base_fields = [
        "candidate_id",
        "point_id",
        "clip_id",
        "source_objectid",
        "source_uid",
        "num_edo",
        "entidad",
        "clave",
        "descripcion",
        "dominio_inegi",
        "stratum_id",
        "clipped_area_ha",
    ]

    summary = candidate_points[
        base_fields
    ].copy()

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


def make_run_metadata(
    config: dict[str, Any],
    config_path: Path,
    states_path: Path,
    source_path: Path,
    processing_crs: str,
    output_crs: str,
) -> pd.DataFrame:
    metadata = {
        "project_name": (
            config["project"]["name"]
        ),
        "source_name": (
            config["project"]["source_name"]
        ),
        "base_year": (
            config["project"]["base_year"]
        ),
        "run_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "config_path": str(config_path),
        "states_path": str(states_path),
        "source_type": get_source_type(config),
        "source_path": str(
            source_path
        ),
        "processing_crs": processing_crs,
        "output_crs": output_crs,
        "state_codes": ",".join(
            str(value)
            for value in config["aoi"][
                "state_codes"
            ]
        ),
        "thinning_distances_m": ",".join(
            str(value)
            for value in config["sampling"][
                "thinning_distances_m"
            ]
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
        raise ValueError(
            f"La capa {layer_name} no tiene CRS."
        )

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
    last_change = datetime.now(
        timezone.utc
    ).strftime(
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

    table = table.astype(
        object
    ).where(
        pd.notna(table),
        None,
    )

    with sqlite3.connect(
        gpkg_path
    ) as connection:
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

        LOGGER.info(
            "Exportando CSV: %s",
            path,
        )

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
        "thematic_sampling.log",
    )
    configure_logger(log_path)

    gpkg_path = output_root / config["outputs"][
        "gpkg_name"
    ]

    if gpkg_path.exists():
        LOGGER.info(
            "Eliminando salida previa: %s",
            gpkg_path,
        )
        gpkg_path.unlink()

    crs_cfg = config.get("crs", {})

    processing_crs = crs_cfg.get(
        "processing_crs",
        crs_cfg.get("target_crs"),
    )

    if not processing_crs:
        raise ValueError(
            "El YAML debe incluir crs.processing_crs "
            "(o, por compatibilidad, crs.target_crs)."
        )

    output_crs = crs_cfg.get(
        "output_crs",
        "EPSG:4326",
    )

    validate_processing_crs(
        processing_crs
    )
    CRS.from_user_input(
        output_crs
    )

    states_cfg = config["inputs"]["states"]
    states_path = resolve_repo_path(
        states_cfg["path"]
    )

    source_type = get_source_type(config)
    source_cfg = get_thematic_source_config(config)

    if source_type == "vector":
        vector_cfg = source_cfg["vector"]
        source_path = resolve_repo_path(
            vector_cfg["path"]
        )
    elif source_type == "raster":
        raster_cfg = source_cfg["raster"]
        source_path = resolve_repo_path(
            raster_cfg["path"]
        )
    else:
        raise ValueError(
            f"source_type no reconocido: {source_type}. Use vector o raster."
        )

    states = read_vector(
        states_path,
        states_cfg.get("layer"),
    )

    state_fields = states_cfg["fields"]
    require_fields(
        states,
        [
            state_fields["state_code"],
            state_fields["state_name"],
            state_fields[
                "geographic_feature"
            ],
        ],
        "estados",
    )

    if config["geometry"].get(
        "repair_invalid",
        True,
    ):
        states = repair_geometries(
            states,
            "estados",
        )

    states = reproject(
        states,
        processing_crs,
        "estados",
    )

    aoi_states, aoi_union = prepare_aoi(
        states,
        config,
    )

    land_cover_clipped: gpd.GeoDataFrame | None = None

    if source_type == "vector":
        LOGGER.info("Procesando fuente temática vectorial")
        vector_cfg = get_vector_source_config(config)
        vector_fields = vector_cfg["fields"]
        key_field = vector_fields.get(
            "class_id",
            vector_fields.get("key"),
        )
        description_field = vector_fields.get(
            "class_label",
            vector_fields.get("description"),
        )
        if key_field is None or description_field is None:
            raise ValueError(
                "La fuente vectorial debe indicar class_id y class_label."
            )

        land_cover = read_vector(
            source_path,
            vector_cfg.get("layer"),
        )
        require_fields(
            land_cover,
            [key_field, description_field],
            "fuente temática vectorial",
        )

        if config["geometry"].get(
            "repair_invalid",
            True,
        ):
            land_cover = repair_geometries(
                land_cover,
                "fuente temática vectorial",
            )

        land_cover = reproject(
            land_cover,
            processing_crs,
            "fuente temática vectorial",
        )

        land_cover = normalize_land_cover_fields(
            land_cover,
            config,
        )

        land_cover_clipped = clip_land_cover_to_states(
            land_cover,
            aoi_states,
            aoi_union,
            minimum_area_ha=float(
                config["geometry"].get(
                    "minimum_area_ha",
                    0.0,
                )
            ),
        )

        field_audit = build_field_audit(
            land_cover_clipped,
        )
        class_catalog = build_class_catalog(
            land_cover_clipped,
            area_field="clipped_area_ha",
            polygon_id_field="clip_id",
        )

        candidate_points = create_candidate_points(
            land_cover_clipped,
            config,
        )

    else:
        LOGGER.info("Procesando fuente temática raster")
        candidate_points = create_raster_candidate_points(
            aoi_states,
            aoi_union,
            config,
            processing_crs,
        )

        field_audit = build_field_audit(
            candidate_points,
        )
        class_catalog = build_class_catalog(
            candidate_points,
            area_field="clipped_area_ha",
            polygon_id_field="candidate_id",
        )

    distances = [
        int(value)
        for value in config["sampling"][
            "thinning_distances_m"
        ]
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

    selected_layers: dict[
        int,
        gpd.GeoDataFrame,
    ] = {}

    audit_pieces: list[
        pd.DataFrame
    ] = []

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

        selected_layers[
            distance_m
        ] = selected

        audit_pieces.append(
            audit
        )

        LOGGER.info(
            "Escenario %s m | seleccionados=%s | "
            "rechazados=%s",
            f"{distance_m:,}",
            f"{len(selected):,}",
            f"{len(candidate_points) - len(selected):,}",
        )

    selection_audit = pd.concat(
        audit_pieces,
        ignore_index=True,
    )

    distance_summary = summarize_distances(
        selected_layers
    )
    state_summary = summarize_by_state(
        selected_layers
    )
    domain_summary = summarize_by_domain(
        selected_layers
    )
    class_summary = summarize_by_class(
        selected_layers
    )
    polygon_summary = build_polygon_summary(
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
        config,
        config_path,
        states_path,
        source_path,
        processing_crs,
        output_crs,
    )

    layer_names = config["outputs"]["layers"]

    write_spatial_layer(
        aoi_states,
        gpkg_path,
        get_layer_name(layer_names, "aoi_states", "aoi_estados"),
        output_crs,
    )
    write_spatial_layer(
        aoi_union,
        gpkg_path,
        get_layer_name(layer_names, "aoi_union", "aoi_union"),
        output_crs,
    )

    if land_cover_clipped is not None:
        write_spatial_layer(
            land_cover_clipped,
            gpkg_path,
            get_layer_name(
                layer_names,
                "land_cover_clipped",
                "fuente_vectorial_recortada",
            ),
            output_crs,
        )

    write_spatial_layer(
        candidate_points,
        gpkg_path,
        get_layer_name(layer_names, "candidate_points", "puntos_candidatos"),
        output_crs,
    )

    prefix = get_layer_name(layer_names, "thinned_prefix", "puntos_d")

    for (
        distance_m,
        selected,
    ) in selected_layers.items():
        layer_name = (
            f"{prefix}{distance_m:04d}"
        )

        write_spatial_layer(
            selected,
            gpkg_path,
            layer_name,
            output_crs,
        )

    nonspatial_tables = {
        get_layer_name(layer_names, "field_audit", "field_audit"): field_audit,
        get_layer_name(layer_names, "class_catalog", "catalogo_clases"): class_catalog,
        get_layer_name(layer_names, "distance_summary", "resumen_distancias"): distance_summary,
        get_layer_name(layer_names, "state_summary", "resumen_estados"): state_summary,
        get_layer_name(layer_names, "domain_summary", "resumen_dominios"): domain_summary,
        get_layer_name(layer_names, "class_summary", "resumen_clases"): class_summary,
        get_layer_name(layer_names, "polygon_summary", "resumen_poligonos"): polygon_summary,
        get_layer_name(layer_names, "class_representation_summary", "resumen_representacion_clases"): class_representation_summary,
        get_layer_name(layer_names, "selection_audit", "seleccion_auditoria"): selection_audit,
        get_layer_name(layer_names, "run_metadata", "run_metadata"): run_metadata,
    }

    for (
        table_name,
        dataframe,
    ) in nonspatial_tables.items():
        write_nonspatial_table(
            dataframe,
            gpkg_path,
            table_name,
        )

    if config["outputs"].get(
        "export_csv",
        True,
    ):
        export_csv_tables(
            output_root,
            {
                "field_audit": field_audit,
                "catalogo_clases": class_catalog,
                "resumen_distancias": distance_summary,
                "resumen_estados": state_summary,
                "resumen_dominios": domain_summary,
                "resumen_clases": class_summary,
                "resumen_poligonos": polygon_summary,
                "resumen_representacion_clases": class_representation_summary,
                "seleccion_auditoria": selection_audit,
                "run_metadata": run_metadata,
            },
        )

    LOGGER.info(
        "Proceso finalizado correctamente."
    )
    LOGGER.info(
        "GeoPackage: %s",
        gpkg_path,
    )
    LOGGER.info(
        "Log: %s",
        log_path,
    )

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extracción simple de puntos desde una fuente "
            "temática vectorial o raster."
        )
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=(
            "Ruta al YAML. Por defecto: "
            f"{DEFAULT_CONFIG}"
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(Path(arguments.config))
