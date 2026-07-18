# -*- coding: utf-8 -*-
"""
Actividad 4 — extracción normalizada de puntos por cuadrantes piloto
===================================================================

Extensión 3NF que asigna puntos XY normalizados a cuadrantes piloto.

Opcionalmente, A4.1 puede seleccionar registros completos de A3 para Costa
Rica y Panamá y conservar A2.1 como fuente de los demás países. Las fuentes
son de solo lectura: no se actualizan atributos ni se trasladan valores entre
registros.

La configuración operativa vive en YAML, por defecto:

    config/a4_pilot_quadrant_extraction.yaml

Ejecución desde la raíz del repositorio:

    conda run -n pgbm_actividad1 python src/actividad_4/extract_pilot_quadrant_points.py \
      --config config/a4_pilot_quadrant_extraction.yaml

El script sigue la hoja 4 del modelo:

- genera la extensión normalizada para cuadrantes piloto;
- conserva una proyección materializada de los puntos seleccionados;
- registra la fuente original de cada punto y la comparación de atributos;
- copia solo las tablas de referencia/catálogos indicadas en el YAML;
- exporta xy_score mínimo: xy_group_id + score_aptitud_total;
- exporta xy_accion filtrado al subconjunto piloto;
- exporta xy_homologacion_final desde la fuente propia de cada punto;
- no genera capas planas tipo pilot_quadrant_points o vw_pilot_quadrant_points;
- no exporta tablas temáticas de A2.1 que no estén declaradas en el YAML.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def configure_conda_geodata_paths() -> None:
    """Help GDAL/PROJ discovery inside Conda environments."""
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

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_pilot_quadrant_extraction.yaml"

LOGGER = logging.getLogger("pilot_quadrant_extraction_normalized")


# ============================================================
# Configuración
# ============================================================


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo YAML de configuración: {path}")
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError(f"El YAML no contiene un diccionario válido: {path}")
    return data


def get_required(cfg: dict[str, Any], *keys: str) -> Any:
    current: Any = cfg
    path = ".".join(keys)
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Falta la clave de configuración: {path}")
        current = current[key]
    return current


def get_optional(cfg: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = cfg
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} debe ser una lista.")
    return value


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def require_path(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"No existe {label}: {path}")


def configure_logger(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
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


def validate_config(cfg: dict[str, Any]) -> None:
    required_paths = ["points_gpkg", "quadrants_gpkg", "output_gpkg", "log_path"]
    for key in required_paths:
        get_required(cfg, "paths", key)

    required_inputs = [
        "points_layer",
        "action_table",
        "score_table",
        "homologation_table",
        "quadrants_layer",
    ]
    for key in required_inputs:
        get_required(cfg, "inputs", key)

    required_fields = [
        "key",
        "zone",
        "quadrant",
        "quadrant_fields",
        "pilot_xy_point",
        "score",
        "action",
        "homologation",
        "point_source",
        "point_attribute_check",
    ]
    for key in required_fields:
        get_required(cfg, "fields", key)

    required_output_layers = ["pilot_xy_point", "pilot_zone", "pilot_quadrant", "pilot_quadrant_buffer"]
    for key in required_output_layers:
        get_required(cfg, "outputs", "layers", key)

    required_output_tables = [
        "pilot_buffer_run",
        "pilot_assignment_run",
        "xy_pilot_quadrant",
        "xy_pilot_point_source",
        "xy_pilot_point_attribute_check",
        "xy_score",
        "xy_accion",
        "xy_homologacion_final",
        "xy_pilot_quadrant_conflict",
        "xy_pilot_quadrant_conflict_match",
    ]
    for key in required_output_tables:
        get_required(cfg, "outputs", "tables", key)

    predicate = get_required(cfg, "spatial", "predicate")
    allowed_predicates = as_list(get_required(cfg, "spatial", "allowed_predicates"), "spatial.allowed_predicates")
    if predicate not in allowed_predicates:
        raise ValueError(f"spatial.predicate='{predicate}' no está en {allowed_predicates}")

    multiple_match_policy = get_required(cfg, "spatial", "multiple_match_policy")
    allowed_policies = as_list(
        get_required(cfg, "spatial", "allowed_multiple_match_policies"),
        "spatial.allowed_multiple_match_policies",
    )
    if multiple_match_policy not in allowed_policies:
        raise ValueError(
            f"spatial.multiple_match_policy='{multiple_match_policy}' no está en {allowed_policies}"
        )

    key_field = get_required(cfg, "fields", "key")
    action_use_field = get_required(cfg, "filters", "action_use_field")
    action_fields = as_list(get_required(cfg, "fields", "action"), "fields.action")
    if key_field not in action_fields:
        raise ValueError(f"fields.action debe contener {key_field}.")
    if action_use_field not in action_fields:
        raise ValueError(f"fields.action debe contener filters.action_use_field='{action_use_field}'.")

    score_fields = as_list(get_required(cfg, "fields", "score"), "fields.score")
    if key_field not in score_fields:
        raise ValueError(f"fields.score debe contener {key_field}.")

    homologation_fields = as_list(
        get_required(cfg, "fields", "homologation"),
        "fields.homologation",
    )
    if key_field not in homologation_fields:
        raise ValueError(f"fields.homologation debe contener {key_field}.")

    point_source_fields = as_list(
        get_required(cfg, "fields", "point_source"),
        "fields.point_source",
    )
    if key_field not in point_source_fields:
        raise ValueError(f"fields.point_source debe contener {key_field}.")

    attribute_check_fields = as_list(
        get_required(cfg, "fields", "point_attribute_check"),
        "fields.point_attribute_check",
    )
    required_attribute_check_fields = [
        "point_source_key",
        "selected_country_id",
        "attribute_name",
        "reference_dtype",
        "source_dtype",
        "type_compatible",
        "reference_null_count",
        "source_null_count",
        "reference_null_pct",
        "source_null_pct",
        "check_status",
        "check_note",
    ]
    require_fields(
        attribute_check_fields,
        required_attribute_check_fields,
        "fields.point_attribute_check",
    )
    unexpected_check_fields = sorted(
        set(attribute_check_fields) - set(required_attribute_check_fields)
    )
    if unexpected_check_fields or len(attribute_check_fields) != len(
        required_attribute_check_fields
    ):
        raise ValueError(
            "fields.point_attribute_check debe contener exactamente los campos "
            f"de auditoría esperados; campos inesperados={unexpected_check_fields}."
        )

    selection = get_optional(cfg, "point_source_selection", default={})
    if not isinstance(selection, dict):
        raise ValueError("point_source_selection debe ser un diccionario.")
    enabled = selection.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("point_source_selection.enabled debe ser true o false.")

    boolean_options = [
        "require_base_country_candidates",
        "require_selected_source_candidates",
        "require_selected_source_final_points",
        "compare_attributes_with_base",
    ]
    for option_name in boolean_options:
        option_value = selection.get(option_name, True)
        if not isinstance(option_value, bool):
            raise ValueError(
                f"point_source_selection.{option_name} debe ser true o false."
            )

    country_field = selection.get("country_field", "id_pais_grupo")
    if not isinstance(country_field, str) or not country_field.strip():
        raise ValueError("point_source_selection.country_field debe ser un campo válido.")
    pilot_fields = as_list(
        get_required(cfg, "fields", "pilot_xy_point"),
        "fields.pilot_xy_point",
    )
    if country_field not in pilot_fields:
        raise ValueError(
            f"point_source_selection.country_field='{country_field}' debe estar "
            "en fields.pilot_xy_point."
        )

    base_source_key = selection.get("base_source_key", "a2_1_original")
    if not isinstance(base_source_key, str) or not base_source_key.strip():
        raise ValueError("point_source_selection.base_source_key debe ser un texto no vacío.")

    provenance_fields = selection.get("provenance_fields", {})
    required_provenance = [
        "source_key",
        "source_role",
        "selected_country_id",
        "source_gpkg",
    ]
    if not isinstance(provenance_fields, dict):
        raise ValueError(
            "point_source_selection.provenance_fields debe ser un diccionario."
        )
    provenance_names: list[str] = []
    for semantic_name in required_provenance:
        field_name = provenance_fields.get(semantic_name)
        if not isinstance(field_name, str) or not field_name:
            raise ValueError(
                "point_source_selection.provenance_fields no define "
                f"{semantic_name}."
            )
        if field_name not in point_source_fields:
            raise ValueError(
                f"El campo de procedencia '{field_name}' debe estar en "
                "fields.point_source."
            )
        provenance_names.append(field_name)
    if len(provenance_names) != len(set(provenance_names)):
        raise ValueError("Los campos de procedencia deben tener nombres distintos.")
    if key_field in provenance_names:
        raise ValueError(f"Los campos de procedencia no pueden reutilizar {key_field}.")
    expected_point_source_fields = [key_field] + provenance_names
    if set(point_source_fields) != set(expected_point_source_fields) or len(
        point_source_fields
    ) != len(expected_point_source_fields):
        raise ValueError(
            "fields.point_source debe contener únicamente la llave y los cuatro "
            "campos declarados en provenance_fields."
        )

    sources = selection.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("point_source_selection.sources debe ser una lista.")
    if enabled and not sources:
        raise ValueError(
            "point_source_selection.enabled=true requiere al menos una fuente A3."
        )

    country_ids: list[int] = []
    source_keys: list[str] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(
                f"point_source_selection.sources[{index}] debe ser un diccionario."
            )
        for field in ["country_id", "source_key", "points_gpkg"]:
            if source.get(field) in (None, ""):
                raise ValueError(
                    f"point_source_selection.sources[{index}] no define {field}."
                )
        try:
            country_ids.append(int(source["country_id"]))
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"point_source_selection.sources[{index}].country_id debe ser entero."
            ) from error
        source_keys.append(str(source["source_key"]))

    if len(country_ids) != len(set(country_ids)):
        raise ValueError("Hay country_id duplicados en point_source_selection.sources.")
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("Hay source_key duplicados en point_source_selection.sources.")
    if base_source_key in source_keys:
        raise ValueError("base_source_key no puede coincidir con una fuente A3.")

    reference_tables = get_required(cfg, "reference_tables")
    if not isinstance(reference_tables, dict) or not reference_tables:
        raise ValueError("reference_tables debe ser un diccionario no vacío.")
    for table_name, spec in reference_tables.items():
        if not isinstance(spec, dict):
            raise ValueError(f"reference_tables.{table_name} debe ser un diccionario.")
        fields = as_list(spec.get("fields"), f"reference_tables.{table_name}.fields")
        pk = spec.get("pk")
        if pk and pk not in fields:
            raise ValueError(f"reference_tables.{table_name}.pk='{pk}' no está en fields.")

    relationships = get_optional(cfg, "relationships", default=[])
    if not isinstance(relationships, list):
        raise ValueError("relationships debe ser una lista.")
    for index, relation in enumerate(relationships):
        if not isinstance(relation, dict):
            raise ValueError(f"relationships[{index}] debe ser un diccionario.")
        for key in ["child_table", "child_field", "parent_table", "parent_field"]:
            if key not in relation:
                raise ValueError(f"relationships[{index}] no define {key}.")


# ============================================================
# Acceso a GeoPackage / tablas
# ============================================================


def table_columns(gpkg_path: Path, table_name: str) -> list[str]:
    with sqlite3.connect(gpkg_path) as connection:
        rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    if not rows:
        raise ValueError(f"No existe la tabla/capa '{table_name}' en {gpkg_path}")
    return [row[1] for row in rows]


def require_fields(columns: list[str], fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in columns]
    if missing:
        raise ValueError(f"Faltan campos en {label}: {missing}")


def read_attribute_table(gpkg_path: Path, table_name: str, fields: list[str]) -> pd.DataFrame:
    columns = table_columns(gpkg_path, table_name)
    require_fields(columns, fields, table_name)

    quoted_fields = ", ".join(f'"{field}"' for field in fields)
    query = f'SELECT {quoted_fields} FROM "{table_name}"'

    LOGGER.info("Leyendo tabla %s | campos=%s", table_name, fields)
    with sqlite3.connect(gpkg_path) as connection:
        return pd.read_sql_query(query, connection)


# ============================================================
# Validaciones relacionales
# ============================================================


def validate_unique_key(dataframe: pd.DataFrame, key_field: str, label: str) -> None:
    if key_field not in dataframe.columns:
        raise ValueError(f"{label} no contiene la llave {key_field}.")
    duplicated = int(dataframe[key_field].duplicated().sum())
    if duplicated:
        raise ValueError(f"{label} tiene {duplicated:,} llaves duplicadas en {key_field}.")


def validate_not_null(dataframe: pd.DataFrame, fields: list[str], label: str) -> None:
    for field in fields:
        if field not in dataframe.columns:
            raise ValueError(f"{label} no contiene {field}.")
        missing = int(dataframe[field].isna().sum())
        if missing:
            raise ValueError(f"{label} tiene {missing:,} valores nulos en {field}.")


def validate_reference(
    child: pd.DataFrame,
    child_field: str,
    parent: pd.DataFrame,
    parent_field: str,
    label: str,
) -> None:
    parent_values = set(parent[parent_field].dropna())
    child_values = set(child[child_field].dropna())
    missing = child_values - parent_values
    if missing:
        examples = sorted(map(str, missing))[:5]
        raise ValueError(
            f"Referencia inválida en {label}: {len(missing):,} valores de "
            f"{child_field} no existen en {parent_field}. Ejemplos: {examples}"
        )


# ============================================================
# Construcción de capas / tablas A4
# ============================================================


def infer_metric_crs(dataframe: gpd.GeoDataFrame, metric_crs: str) -> Any:
    if str(metric_crs).lower() != "auto":
        return metric_crs

    estimated = dataframe.estimate_utm_crs()
    if estimated is None:
        raise ValueError(
            "No se pudo inferir un CRS métrico automáticamente. "
            "Indica uno explícitamente en spatial.metric_crs, por ejemplo EPSG:32616."
        )
    return estimated


def read_quadrants(cfg: dict[str, Any], quadrants_gpkg: Path) -> gpd.GeoDataFrame:
    quadrants_layer = get_required(cfg, "inputs", "quadrants_layer")
    quadrant_fields = as_list(get_required(cfg, "fields", "quadrant_fields"), "fields.quadrant_fields")
    quadrant_field = get_required(cfg, "fields", "quadrant")

    LOGGER.info("Leyendo cuadrantes: %s | layer=%s", quadrants_gpkg, quadrants_layer)
    quadrants = gpd.read_file(quadrants_gpkg, layer=quadrants_layer)
    require_fields(list(quadrants.columns), quadrant_fields + ["geometry"], quadrants_layer)

    if quadrants.empty:
        raise ValueError("La capa de cuadrantes está vacía.")
    if quadrants.crs is None:
        raise ValueError("La capa de cuadrantes no tiene CRS definido.")

    validate_not_null(quadrants, quadrant_fields, quadrants_layer)
    duplicated_quadrants = int(quadrants[quadrant_field].duplicated().sum())
    if duplicated_quadrants:
        raise ValueError(
            f"{quadrant_field} debe ser único globalmente, pero hay "
            f"{duplicated_quadrants:,} duplicados."
        )

    invalid_geometry = int((~quadrants.geometry.is_valid).sum())
    if invalid_geometry:
        LOGGER.warning("Cuadrantes con geometría inválida: %s", f"{invalid_geometry:,}")
        quadrants = quadrants.copy()
        quadrants["geometry"] = quadrants.geometry.make_valid()

    quadrants = quadrants[quadrant_fields + ["geometry"]].copy()
    LOGGER.info("Cuadrantes leídos: %s | CRS=%s", f"{len(quadrants):,}", quadrants.crs)
    return quadrants


def build_pilot_zone(cfg: dict[str, Any], quadrants: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    zone_field = get_required(cfg, "fields", "zone")
    output_layer = get_required(cfg, "outputs", "layers", "pilot_zone")

    LOGGER.info("Construyendo %s por disolución de cuadrantes.", output_layer)
    zones = quadrants[[zone_field, "geometry"]].dissolve(by=zone_field, as_index=False)
    zones = zones[[zone_field, "geometry"]].copy()
    validate_not_null(zones, [zone_field], output_layer)
    validate_unique_key(zones, zone_field, output_layer)
    return zones


def build_pilot_quadrant(cfg: dict[str, Any], quadrants: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    quadrant_field = get_required(cfg, "fields", "quadrant")
    zone_field = get_required(cfg, "fields", "zone")
    LOGGER.info("Construyendo pilot_quadrant normalizado.")
    return quadrants[[quadrant_field, zone_field, "geometry"]].copy()


def build_quadrant_buffer(
    cfg: dict[str, Any],
    quadrants: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, str]:
    quadrant_field = get_required(cfg, "fields", "quadrant")
    buffer_run_id = get_required(cfg, "runs", "buffer_run_id")
    buffer_negative_m = float(get_required(cfg, "spatial", "buffer_negative_m"))
    metric_crs = get_required(cfg, "spatial", "metric_crs")

    metric_crs_resolved = infer_metric_crs(quadrants, metric_crs)
    metric_crs_text = str(metric_crs_resolved)

    LOGGER.info(
        "Aplicando buffer negativo a cuadrantes | distancia=%s m | CRS métrico=%s",
        buffer_negative_m,
        metric_crs_text,
    )

    buffered_metric = quadrants[[quadrant_field, "geometry"]].copy().to_crs(metric_crs_resolved)

    if buffer_negative_m > 0:
        buffered_metric["geometry"] = buffered_metric.geometry.buffer(-buffer_negative_m)
    elif buffer_negative_m == 0:
        LOGGER.warning("buffer_negative_m=0: se usará la geometría completa del cuadrante.")
    else:
        raise ValueError("spatial.buffer_negative_m debe ser mayor o igual que 0.")

    empty_count = int(buffered_metric.geometry.is_empty.sum())
    if empty_count:
        LOGGER.warning("Cuadrantes eliminados por buffer negativo excesivo: %s", f"{empty_count:,}")
        buffered_metric = buffered_metric[~buffered_metric.geometry.is_empty].copy()

    if buffered_metric.empty:
        raise ValueError(
            "El buffer negativo eliminó todos los cuadrantes. "
            "Reduce spatial.buffer_negative_m o revisa spatial.metric_crs."
        )

    buffered = buffered_metric.to_crs(quadrants.crs)
    buffered.insert(0, "buffer_run_id", buffer_run_id)
    return buffered[["buffer_run_id", quadrant_field, "geometry"]].copy(), metric_crs_text


def read_points_in_quadrants_bbox(
    cfg: dict[str, Any],
    points_gpkg: Path,
    quadrants_for_assignment: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    points_layer = get_required(cfg, "inputs", "points_layer")
    pilot_xy_point_fields = as_list(get_required(cfg, "fields", "pilot_xy_point"), "fields.pilot_xy_point")
    key_field = get_required(cfg, "fields", "key")

    LOGGER.info("Inspeccionando CRS de puntos: %s | layer=%s", points_gpkg, points_layer)
    point_sample = gpd.read_file(points_gpkg, layer=points_layer, rows=1)

    if point_sample.crs is None:
        raise ValueError("La capa xy_point no tiene CRS definido.")

    quadrants_for_bbox = quadrants_for_assignment.to_crs(point_sample.crs)
    bbox = tuple(quadrants_for_bbox.total_bounds)

    LOGGER.info("Leyendo puntos dentro del bbox de cuadrantes con buffer: %s", bbox)
    points = gpd.read_file(points_gpkg, layer=points_layer, bbox=bbox)
    require_fields(list(points.columns), pilot_xy_point_fields + ["geometry"], points_layer)

    if points.crs is None:
        points = points.set_crs(point_sample.crs)

    validate_unique_key(points, key_field, points_layer)
    LOGGER.info("Puntos candidatos por bbox: %s | CRS=%s", f"{len(points):,}", points.crs)
    return points


def assign_quadrants(
    cfg: dict[str, Any],
    points: gpd.GeoDataFrame,
    quadrant_buffer: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    key_field = get_required(cfg, "fields", "key")
    quadrant_field = get_required(cfg, "fields", "quadrant")
    predicate = get_required(cfg, "spatial", "predicate")
    multiple_match_policy = get_required(cfg, "spatial", "multiple_match_policy")
    output_assignment_table = get_required(cfg, "outputs", "tables", "xy_pilot_quadrant")

    if points.empty:
        LOGGER.warning("No hay puntos candidatos dentro del bbox de cuadrantes.")
        empty_assignments = pd.DataFrame(columns=[key_field, quadrant_field])
        empty_conflicts = pd.DataFrame(columns=[key_field, "n_matches", "conflict_reason"])
        empty_conflict_matches = pd.DataFrame(columns=[key_field, quadrant_field])
        return empty_assignments, empty_conflicts, empty_conflict_matches, 0

    if points.crs != quadrant_buffer.crs:
        LOGGER.info("Reproyectando buffer de cuadrantes de %s a %s", quadrant_buffer.crs, points.crs)
        quadrant_buffer = quadrant_buffer.to_crs(points.crs)

    LOGGER.info("Ejecutando join espacial contra cuadrantes con buffer | predicate=%s", predicate)
    matches = gpd.sjoin(
        points[[key_field, "geometry"]],
        quadrant_buffer[[quadrant_field, "geometry"]],
        how="inner",
        predicate=predicate,
    ).drop(columns=["index_right"])

    total_matches = len(matches)
    LOGGER.info("Coincidencias punto-cuadrante antes de depurar conflictos: %s", f"{total_matches:,}")

    if matches.empty:
        empty_assignments = pd.DataFrame(columns=[key_field, quadrant_field])
        empty_conflicts = pd.DataFrame(columns=[key_field, "n_matches", "conflict_reason"])
        empty_conflict_matches = pd.DataFrame(columns=[key_field, quadrant_field])
        return empty_assignments, empty_conflicts, empty_conflict_matches, total_matches

    match_counts = matches.groupby(key_field).size().rename("n_matches").reset_index()
    conflict_keys = match_counts.loc[match_counts["n_matches"] > 1, key_field]

    if not conflict_keys.empty:
        n_conflict_points = len(conflict_keys)
        LOGGER.warning("Puntos con más de un cuadrante candidato: %s", f"{n_conflict_points:,}")
        if multiple_match_policy == "raise":
            raise ValueError(
                f"Hay {n_conflict_points:,} puntos con múltiples cuadrantes. "
                "Revise xy_pilot_quadrant_conflict o use multiple_match_policy='exclude'."
            )

    conflict_matches = matches[matches[key_field].isin(conflict_keys)][[key_field, quadrant_field]].copy()
    conflicts = match_counts[match_counts[key_field].isin(conflict_keys)].copy()
    conflicts["conflict_reason"] = "multiple_quadrant_matches_after_buffer"
    conflicts = conflicts[[key_field, "n_matches", "conflict_reason"]]

    valid_matches = matches[~matches[key_field].isin(conflict_keys)].copy()
    assignments = valid_matches[[key_field, quadrant_field]].copy()
    validate_unique_key(assignments, key_field, output_assignment_table)

    LOGGER.info(
        "Asignaciones válidas sin conflictos: %s | conflictos excluidos: %s",
        f"{len(assignments):,}",
        f"{len(conflicts):,}",
    )
    return assignments, conflicts, conflict_matches, total_matches


def filter_assignments_by_use(
    cfg: dict[str, Any],
    assignments: pd.DataFrame,
    actions: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    key_field = get_required(cfg, "fields", "key")
    action_table = get_required(cfg, "inputs", "action_table")
    action_use_field = get_required(cfg, "filters", "action_use_field")
    export_uses = as_list(get_required(cfg, "filters", "export_uses"), "filters.export_uses")

    validate_unique_key(actions, key_field, action_table)

    before = len(assignments)
    assignments_with_use = assignments.merge(
        actions[[key_field, action_use_field]],
        on=key_field,
        how="left",
        validate="one_to_one",
    )

    missing_usage = int(assignments_with_use[action_use_field].isna().sum())
    if missing_usage:
        raise ValueError(f"Asignaciones sin categoría de uso en {action_table}: {missing_usage:,}")

    keep_mask = assignments_with_use[action_use_field].isin(export_uses)
    kept_keys = assignments_with_use.loc[keep_mask, key_field]
    excluded_by_use_count = int((~keep_mask).sum())

    filtered_assignments = assignments[assignments[key_field].isin(kept_keys)].copy()
    LOGGER.info(
        "Filtro de uso: antes=%s | conservados=%s | excluidos=%s | usos=%s",
        f"{before:,}",
        f"{len(filtered_assignments):,}",
        f"{excluded_by_use_count:,}",
        ", ".join(str(value) for value in export_uses),
    )

    return filtered_assignments, excluded_by_use_count


def subset_pilot_xy_point(
    cfg: dict[str, Any],
    points: gpd.GeoDataFrame,
    selected_keys: pd.Series,
) -> gpd.GeoDataFrame:
    key_field = get_required(cfg, "fields", "key")
    points_layer = get_required(cfg, "inputs", "points_layer")
    output_layer = get_required(cfg, "outputs", "layers", "pilot_xy_point")
    pilot_xy_point_fields = as_list(get_required(cfg, "fields", "pilot_xy_point"), "fields.pilot_xy_point")

    require_fields(list(points.columns), pilot_xy_point_fields + ["geometry"], points_layer)
    pilot_xy_point = points.loc[
        points[key_field].isin(selected_keys),
        pilot_xy_point_fields + ["geometry"],
    ].copy()
    validate_unique_key(pilot_xy_point, key_field, output_layer)

    missing = len(set(selected_keys.astype("string"))) - pilot_xy_point[key_field].astype("string").nunique()
    if missing:
        raise ValueError(f"{output_layer} no contiene {missing:,} puntos asignados.")
    return pilot_xy_point


def read_table_subset(
    cfg: dict[str, Any],
    source_gpkg: Path,
    source_table: str,
    fields: list[str],
    selected_keys: pd.Series,
    label: str,
) -> pd.DataFrame:
    key_field = get_required(cfg, "fields", "key")
    selected_key_values = set(selected_keys.astype("string").dropna().tolist())
    if not selected_key_values:
        raise ValueError(f"No hay {key_field} seleccionados para extraer {label}.")

    data = read_attribute_table(source_gpkg, source_table, fields)
    validate_unique_key(data, key_field, source_table)
    data[key_field] = data[key_field].astype("string")

    subset = data[data[key_field].isin(selected_key_values)].copy()
    subset = subset[fields].sort_values(key_field).reset_index(drop=True)

    missing = selected_key_values - set(subset[key_field].astype("string"))
    if missing:
        examples = sorted(missing)[:5]
        raise ValueError(
            f"{source_table} no contiene registros para {len(missing):,} puntos piloto. "
            f"Ejemplos: {examples}"
        )
    return subset


def read_source_tables_for_points(
    cfg: dict[str, Any],
    source_gpkg: Path,
    points: gpd.GeoDataFrame,
    source_label: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Lee las relaciones propias de los puntos, sin combinar valores entre fuentes."""
    key_field = get_required(cfg, "fields", "key")
    action_table = get_required(cfg, "inputs", "action_table")
    score_table = get_required(cfg, "inputs", "score_table")
    homologation_table = get_required(cfg, "inputs", "homologation_table")
    action_fields = as_list(get_required(cfg, "fields", "action"), "fields.action")
    score_fields = as_list(get_required(cfg, "fields", "score"), "fields.score")
    homologation_fields = as_list(
        get_required(cfg, "fields", "homologation"),
        "fields.homologation",
    )

    if points.empty:
        return (
            pd.DataFrame(columns=action_fields),
            pd.DataFrame(columns=score_fields),
            pd.DataFrame(columns=homologation_fields),
        )

    keys = points[key_field]
    actions = read_table_subset(
        cfg,
        source_gpkg,
        action_table,
        action_fields,
        keys,
        f"xy_accion de {source_label}",
    )
    scores = read_table_subset(
        cfg,
        source_gpkg,
        score_table,
        score_fields,
        keys,
        f"xy_score de {source_label}",
    )
    homologation = read_table_subset(
        cfg,
        source_gpkg,
        homologation_table,
        homologation_fields,
        keys,
        f"xy_homologacion_final de {source_label}",
    )
    return actions, scores, homologation


def build_point_source_table(
    cfg: dict[str, Any],
    points: gpd.GeoDataFrame,
    source_key: str,
    source_role: str,
    source_gpkg: Path,
    selected_country_id: int | None,
) -> pd.DataFrame:
    key_field = get_required(cfg, "fields", "key")
    selection = get_optional(cfg, "point_source_selection", default={})
    provenance = selection["provenance_fields"]
    fields = as_list(get_required(cfg, "fields", "point_source"), "fields.point_source")
    keys = points[key_field].astype("string").reset_index(drop=True)

    data = pd.DataFrame(
        {
            key_field: keys,
            provenance["source_key"]: str(source_key),
            provenance["source_role"]: str(source_role),
            provenance["selected_country_id"]: selected_country_id,
            provenance["source_gpkg"]: str(source_gpkg),
        }
    )
    return data[fields]


def series_type_family(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series.dtype):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "datetime"
    return "text"


def empty_point_attribute_check(cfg: dict[str, Any]) -> pd.DataFrame:
    fields = as_list(
        get_required(cfg, "fields", "point_attribute_check"),
        "fields.point_attribute_check",
    )
    return pd.DataFrame(columns=fields)


def compare_point_attributes(
    cfg: dict[str, Any],
    reference_points: gpd.GeoDataFrame,
    source_points: gpd.GeoDataFrame,
    source_key: str,
    country_id: int,
) -> pd.DataFrame:
    """Compara estructura y nulos; no modifica ningún atributo de los puntos."""
    if reference_points.empty:
        raise ValueError(
            "No hay puntos A2.1 de los cuadrantes para comparar los atributos "
            f"de {source_key}."
        )
    if source_points.empty:
        return empty_point_attribute_check(cfg)

    point_fields = as_list(
        get_required(cfg, "fields", "pilot_xy_point"),
        "fields.pilot_xy_point",
    )
    output_fields = as_list(
        get_required(cfg, "fields", "point_attribute_check"),
        "fields.point_attribute_check",
    )
    rows: list[dict[str, Any]] = []

    for field_name in point_fields + ["geometry"]:
        reference_series = reference_points[field_name]
        source_series = source_points[field_name]

        if field_name == "geometry":
            reference_types = sorted(reference_series.dropna().geom_type.unique())
            source_types = sorted(source_series.dropna().geom_type.unique())
            reference_dtype = "|".join(reference_types) or "sin_geometría"
            source_dtype = "|".join(source_types) or "sin_geometría"
            type_compatible = bool(source_types) and set(source_types).issubset(
                set(reference_types)
            )
            reference_null_count = int(
                reference_series.isna().sum() + reference_series.is_empty.sum()
            )
            source_null_count = int(
                source_series.isna().sum() + source_series.is_empty.sum()
            )
        else:
            reference_dtype = str(reference_series.dtype)
            source_dtype = str(source_series.dtype)
            type_compatible = (
                series_type_family(reference_series) == series_type_family(source_series)
            )
            reference_null_count = int(reference_series.isna().sum())
            source_null_count = int(source_series.isna().sum())

        reference_null_pct = 100.0 * reference_null_count / len(reference_points)
        source_null_pct = 100.0 * source_null_count / len(source_points)

        if not type_compatible:
            status = "error"
            note = "tipo incompatible con los puntos A2.1 de referencia"
        elif source_null_pct > reference_null_pct:
            status = "warning"
            note = "mayor porcentaje de nulos que la referencia"
        else:
            status = "ok"
            note = "atributo compatible"

        rows.append(
            {
                "point_source_key": source_key,
                "selected_country_id": country_id,
                "attribute_name": field_name,
                "reference_dtype": reference_dtype,
                "source_dtype": source_dtype,
                "type_compatible": int(type_compatible),
                "reference_null_count": reference_null_count,
                "source_null_count": source_null_count,
                "reference_null_pct": round(reference_null_pct, 6),
                "source_null_pct": round(source_null_pct, 6),
                "check_status": status,
                "check_note": note,
            }
        )

    report = pd.DataFrame(rows)[output_fields]
    errors = report.loc[report["check_status"] == "error", "attribute_name"].tolist()
    if errors:
        raise ValueError(
            f"La fuente {source_key} tiene atributos incompatibles: {errors}. "
            "No se modificó ningún dato."
        )

    warnings = report.loc[report["check_status"] == "warning", "attribute_name"].tolist()
    if warnings:
        LOGGER.warning(
            "Comparación de atributos de %s con advertencias: %s",
            source_key,
            warnings,
        )
    else:
        LOGGER.info("Comparación de atributos de %s: compatible.", source_key)
    return report


def validate_selected_point_universe(
    cfg: dict[str, Any],
    points: gpd.GeoDataFrame,
    actions: pd.DataFrame,
    scores: pd.DataFrame,
    homologation: pd.DataFrame,
    point_sources: pd.DataFrame,
) -> None:
    key_field = get_required(cfg, "fields", "key")
    homologation_fields = as_list(
        get_required(cfg, "fields", "homologation"),
        "fields.homologation",
    )
    validate_not_null(
        homologation,
        homologation_fields,
        "clases homologadas de sus fuentes",
    )
    datasets: dict[str, pd.DataFrame] = {
        "puntos seleccionados": points,
        "acciones de sus fuentes": actions,
        "scores de sus fuentes": scores,
        "clases homologadas de sus fuentes": homologation,
        "procedencia de puntos": point_sources,
    }
    key_sets: dict[str, set[str]] = {}

    for label, dataframe in datasets.items():
        validate_unique_key(dataframe, key_field, label)
        validate_not_null(dataframe, [key_field], label)
        key_sets[label] = set(dataframe[key_field].astype("string"))

    point_keys = key_sets["puntos seleccionados"]
    for label, keys in key_sets.items():
        if keys != point_keys:
            missing = point_keys - keys
            extra = keys - point_keys
            raise ValueError(
                f"El universo de {label} no coincide con los puntos: "
                f"faltan={len(missing):,}, sobran={len(extra):,}."
            )


def load_selected_point_sources(
    cfg: dict[str, Any],
    base_points_gpkg: Path,
    quadrant_buffer: gpd.GeoDataFrame,
) -> tuple[
    gpd.GeoDataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
]:
    """Selecciona filas completas por fuente, sin actualizar valores."""
    key_field = get_required(cfg, "fields", "key")
    selection = get_optional(cfg, "point_source_selection", default={})
    enabled = bool(selection.get("enabled", False))
    country_field = selection.get("country_field", "id_pais_grupo")
    base_source_key = str(selection.get("base_source_key", "a2_1_original"))
    selected_sources = selection.get("sources", [])

    base_candidates_all = read_points_in_quadrants_bbox(
        cfg,
        base_points_gpkg,
        quadrant_buffer,
    )
    base_count_all = len(base_candidates_all)
    comparison_reference_points = base_candidates_all
    selected_country_ids = [int(item["country_id"]) for item in selected_sources]

    if enabled:
        base_country = pd.to_numeric(
            base_candidates_all[country_field],
            errors="coerce",
        )
        if selection.get("require_base_country_candidates", True):
            missing_countries = [
                country_id
                for country_id in selected_country_ids
                if not (base_country == country_id).any()
            ]
            if missing_countries:
                raise ValueError(
                    "A2.1 no contiene candidatos de referencia para los países "
                    f"configurados: {missing_countries}."
                )
        source_country_mask = base_country.isin(selected_country_ids)
        base_points = base_candidates_all.loc[~source_country_mask].copy()
        base_not_selected_count = int(source_country_mask.sum())
    else:
        base_points = base_candidates_all
        base_not_selected_count = 0

    point_frames: list[gpd.GeoDataFrame] = [base_points]
    action_frames: list[pd.DataFrame] = []
    score_frames: list[pd.DataFrame] = []
    homologation_frames: list[pd.DataFrame] = []
    provenance_frames: list[pd.DataFrame] = []
    check_frames: list[pd.DataFrame] = []
    source_counts: dict[str, int] = {}

    base_actions, base_scores, base_homologation = read_source_tables_for_points(
        cfg,
        base_points_gpkg,
        base_points,
        base_source_key,
    )
    action_frames.append(base_actions)
    score_frames.append(base_scores)
    homologation_frames.append(base_homologation)
    provenance_frames.append(
        build_point_source_table(
            cfg,
            base_points,
            source_key=base_source_key,
            source_role="a2_1",
            source_gpkg=base_points_gpkg,
            selected_country_id=None,
        )
    )

    if enabled:
        for source in selected_sources:
            country_id = int(source["country_id"])
            source_key = str(source["source_key"])
            source_gpkg = resolve_path(source["points_gpkg"])
            require_path(source_gpkg, f"GeoPackage A3 de {source_key}")

            source_points = read_points_in_quadrants_bbox(
                cfg,
                source_gpkg,
                quadrant_buffer,
            )
            if source_points.empty and selection.get(
                "require_selected_source_candidates",
                True,
            ):
                raise ValueError(
                    f"La fuente {source_key} no aporta puntos candidatos a A4.1."
                )

            observed_country = pd.to_numeric(
                source_points[country_field],
                errors="coerce",
            )
            invalid_country = observed_country.isna() | (observed_country != country_id)
            if invalid_country.any():
                raise ValueError(
                    f"La fuente {source_key} contiene {int(invalid_country.sum()):,} "
                    f"puntos cuyo {country_field} no es {country_id}."
                )

            if source_points.crs != base_candidates_all.crs:
                raise ValueError(
                    f"La fuente {source_key} usa CRS {source_points.crs}, pero A2.1 "
                    f"usa {base_candidates_all.crs}. No se reproyectaron ni modificaron "
                    "los puntos."
                )

            if selection.get("compare_attributes_with_base", True):
                check_frames.append(
                    compare_point_attributes(
                        cfg,
                        comparison_reference_points,
                        source_points,
                        source_key,
                        country_id,
                    )
                )

            source_actions, source_scores, source_homologation = (
                read_source_tables_for_points(
                    cfg,
                    source_gpkg,
                    source_points,
                    source_key,
                )
            )
            point_frames.append(source_points)
            action_frames.append(source_actions)
            score_frames.append(source_scores)
            homologation_frames.append(source_homologation)
            provenance_frames.append(
                build_point_source_table(
                    cfg,
                    source_points,
                    source_key=source_key,
                    source_role="a3_selected",
                    source_gpkg=source_gpkg,
                    selected_country_id=country_id,
                )
            )
            source_counts[source_key] = len(source_points)

    points = gpd.GeoDataFrame(
        pd.concat(point_frames, ignore_index=True),
        geometry="geometry",
        crs=base_candidates_all.crs,
    )
    actions = pd.concat(action_frames, ignore_index=True)
    scores = pd.concat(score_frames, ignore_index=True)
    homologation = pd.concat(homologation_frames, ignore_index=True)
    point_sources = pd.concat(provenance_frames, ignore_index=True)
    attribute_checks = (
        pd.concat(check_frames, ignore_index=True)
        if check_frames
        else empty_point_attribute_check(cfg)
    )

    points[key_field] = points[key_field].astype("string")
    actions[key_field] = actions[key_field].astype("string")
    scores[key_field] = scores[key_field].astype("string")
    homologation[key_field] = homologation[key_field].astype("string")
    point_sources[key_field] = point_sources[key_field].astype("string")
    validate_selected_point_universe(
        cfg,
        points,
        actions,
        scores,
        homologation,
        point_sources,
    )

    warning_count = int(
        (attribute_checks.get("check_status", pd.Series(dtype="string")) == "warning").sum()
    )
    stats = {
        "a3_sources_enabled": enabled,
        "base_candidate_count_all": base_count_all,
        "base_candidate_count_selected": len(base_points),
        "base_country_points_not_selected": base_not_selected_count,
        "a3_candidate_count_selected": sum(source_counts.values()),
        "selected_source_keys": "|".join(source_counts),
        "selected_source_counts": "|".join(
            f"{source_key}:{count}" for source_key, count in source_counts.items()
        ),
        "attribute_check_status": (
            "not_applicable"
            if not enabled
            else "passed_with_warnings"
            if warning_count
            else "passed"
        ),
        "attribute_warning_count": warning_count,
    }
    LOGGER.info(
        "Selección de fuentes A4.1 | A3=%s | A2.1 seleccionados=%s | "
        "A3 seleccionados=%s | total=%s",
        enabled,
        f"{len(base_points):,}",
        f"{stats['a3_candidate_count_selected']:,}",
        f"{len(points):,}",
    )
    return (
        points,
        actions,
        scores,
        homologation,
        point_sources,
        attribute_checks,
        stats,
    )


def subset_loaded_table(
    cfg: dict[str, Any],
    dataframe: pd.DataFrame,
    fields: list[str],
    selected_keys: pd.Series,
    label: str,
) -> pd.DataFrame:
    key_field = get_required(cfg, "fields", "key")
    require_fields(list(dataframe.columns), fields, label)
    validate_unique_key(dataframe, key_field, label)
    selected = set(selected_keys.astype("string").dropna())

    out = dataframe[fields].copy()
    out[key_field] = out[key_field].astype("string")
    out = out[out[key_field].isin(selected)].sort_values(key_field).reset_index(drop=True)
    missing = selected - set(out[key_field])
    if missing:
        raise ValueError(
            f"{label} no contiene {len(missing):,} llaves seleccionadas. "
            f"Ejemplos: {sorted(missing)[:5]}"
        )
    return out


def validate_selected_sources_in_final_points(
    cfg: dict[str, Any],
    point_sources: pd.DataFrame,
) -> None:
    selection = get_optional(cfg, "point_source_selection", default={})
    if not selection.get("enabled", False) or not selection.get(
        "require_selected_source_final_points",
        True,
    ):
        return

    source_field = selection["provenance_fields"]["source_key"]
    expected = {str(item["source_key"]) for item in selection.get("sources", [])}
    observed = set(point_sources[source_field].dropna().astype(str))
    missing = sorted(expected - observed)
    if missing:
        raise ValueError(
            "Estas fuentes A3 no aportaron puntos finales después de la "
            f"asignación espacial y el filtro de uso: {missing}."
        )


def read_reference_tables(cfg: dict[str, Any], points_gpkg: Path) -> dict[str, pd.DataFrame]:
    reference_tables_cfg = get_required(cfg, "reference_tables")
    reference_tables: dict[str, pd.DataFrame] = {}

    for table_name, spec in reference_tables_cfg.items():
        fields = as_list(spec["fields"], f"reference_tables.{table_name}.fields")
        dataframe = read_attribute_table(points_gpkg, table_name, fields)
        dataframe = dataframe[fields].copy()

        pk = spec.get("pk")
        if pk:
            validate_not_null(dataframe, [pk], table_name)
            validate_unique_key(dataframe, pk, table_name)

        reference_tables[table_name] = dataframe

    return reference_tables


def validate_configured_relationships(
    cfg: dict[str, Any],
    tables_by_name: dict[str, pd.DataFrame],
) -> None:
    """Validate FK paths declared in the YAML.

    The relationship list is part of the diagram specification. Keeping it in
    YAML avoids hard-coding which A2.1 catalogs and A4 extension tables are
    connected by foreign-key logic.
    """
    relationships = get_optional(cfg, "relationships", default=[])
    for relation in relationships:
        child_table = relation["child_table"]
        child_field = relation["child_field"]
        parent_table = relation["parent_table"]
        parent_field = relation["parent_field"]

        if child_table not in tables_by_name:
            raise ValueError(f"Relación YAML inválida: no existe child_table={child_table}.")
        if parent_table not in tables_by_name:
            raise ValueError(f"Relación YAML inválida: no existe parent_table={parent_table}.")

        validate_reference(
            tables_by_name[child_table],
            child_field,
            tables_by_name[parent_table],
            parent_field,
            f"{child_table}.{child_field} -> {parent_table}.{parent_field}",
        )

def build_buffer_run_table(cfg: dict[str, Any], metric_crs_text: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "buffer_run_id": get_required(cfg, "runs", "buffer_run_id"),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "buffer_negative_m": float(get_required(cfg, "spatial", "buffer_negative_m")),
                "metric_crs": metric_crs_text,
            }
        ]
    )


def build_assignment_run_table(
    cfg: dict[str, Any],
    points_gpkg: Path,
    quadrants_gpkg: Path,
    output_gpkg: Path,
    quadrants_count: int,
    buffer_quadrants_count: int,
    bbox_candidate_count: int,
    raw_match_count: int,
    valid_assignment_count_before_use: int,
    extracted_assignment_count: int,
    conflict_point_count: int,
    excluded_by_use_count: int,
    point_source_stats: dict[str, Any],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "assignment_run_id": get_required(cfg, "runs", "assignment_run_id"),
                "buffer_run_id": get_required(cfg, "runs", "buffer_run_id"),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "config_activity": get_optional(cfg, "activity", default="a4_pilot_quadrant_extraction"),
                "points_gpkg": str(points_gpkg),
                "points_layer": get_required(cfg, "inputs", "points_layer"),
                "action_filter_table": get_required(cfg, "inputs", "action_table"),
                "action_filter_field": get_required(cfg, "filters", "action_use_field"),
                "quadrants_gpkg": str(quadrants_gpkg),
                "quadrants_layer": get_required(cfg, "inputs", "quadrants_layer"),
                "output_gpkg": str(output_gpkg),
                "a2_1_reference_policy": "diagram_reference_tables_from_yaml_xy_score_minimal_and_xy_accion_filtered",
                "point_input_policy": "complete_source_records_no_field_overwrite",
                "a3_point_sources_enabled": int(
                    bool(point_source_stats["a3_sources_enabled"])
                ),
                "base_bbox_candidate_points_all": point_source_stats[
                    "base_candidate_count_all"
                ],
                "base_bbox_candidate_points_selected": point_source_stats[
                    "base_candidate_count_selected"
                ],
                "base_country_points_not_selected": point_source_stats[
                    "base_country_points_not_selected"
                ],
                "a3_bbox_candidate_points_selected": point_source_stats[
                    "a3_candidate_count_selected"
                ],
                "selected_a3_source_keys": point_source_stats[
                    "selected_source_keys"
                ],
                "selected_a3_source_counts": point_source_stats[
                    "selected_source_counts"
                ],
                "point_attribute_check_status": point_source_stats[
                    "attribute_check_status"
                ],
                "point_attribute_warning_count": point_source_stats[
                    "attribute_warning_count"
                ],
                "spatial_predicate": get_required(cfg, "spatial", "predicate"),
                "multiple_match_policy": get_required(cfg, "spatial", "multiple_match_policy"),
                "quadrants_count": quadrants_count,
                "buffer_quadrants_count": buffer_quadrants_count,
                "bbox_candidate_points": bbox_candidate_count,
                "raw_spatial_matches": raw_match_count,
                "valid_assignments_before_use_filter": valid_assignment_count_before_use,
                "extracted_assignments": extracted_assignment_count,
                "conflict_points": conflict_point_count,
                "excluded_by_use": excluded_by_use_count,
                "exported_uses": "|".join(str(value) for value in get_required(cfg, "filters", "export_uses")),
            }
        ]
    )


# ============================================================
# Escritura
# ============================================================


def register_attribute_table_in_gpkg(
    connection: sqlite3.Connection,
    table_name: str,
    description: str,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    connection.execute(
        """
        INSERT OR REPLACE INTO gpkg_contents
            (table_name, data_type, identifier, description, last_change)
        VALUES (?, 'attributes', ?, ?, ?)
        """,
        (table_name, table_name, description, now),
    )


def write_table_to_gpkg(
    dataframe: pd.DataFrame,
    gpkg_path: Path,
    table_name: str,
    description: str,
) -> None:
    LOGGER.info("Exportando tabla normalizada: %s | filas=%s", table_name, f"{len(dataframe):,}")
    with sqlite3.connect(gpkg_path) as connection:
        dataframe.to_sql(table_name, connection, if_exists="replace", index=False)
        register_attribute_table_in_gpkg(connection, table_name, description)
        connection.commit()


def create_indexes(cfg: dict[str, Any], connection: sqlite3.Connection) -> None:
    key_field = get_required(cfg, "fields", "key")
    zone_field = get_required(cfg, "fields", "zone")
    quadrant_field = get_required(cfg, "fields", "quadrant")

    layers = get_required(cfg, "outputs", "layers")
    tables = get_required(cfg, "outputs", "tables")
    reference_tables = get_required(cfg, "reference_tables")

    statements = [
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{layers["pilot_xy_point"]}_{key_field} ON "{layers["pilot_xy_point"]}" ("{key_field}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{layers["pilot_zone"]}_{zone_field} ON "{layers["pilot_zone"]}" ("{zone_field}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{layers["pilot_quadrant"]}_{quadrant_field} ON "{layers["pilot_quadrant"]}" ("{quadrant_field}")',
        f'CREATE INDEX IF NOT EXISTS idx_{layers["pilot_quadrant"]}_{zone_field} ON "{layers["pilot_quadrant"]}" ("{zone_field}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{layers["pilot_quadrant_buffer"]}_run_quad ON "{layers["pilot_quadrant_buffer"]}" ("buffer_run_id", "{quadrant_field}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{tables["pilot_buffer_run"]}_id ON "{tables["pilot_buffer_run"]}" ("buffer_run_id")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{tables["pilot_assignment_run"]}_id ON "{tables["pilot_assignment_run"]}" ("assignment_run_id")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{tables["xy_pilot_quadrant"]}_{key_field} ON "{tables["xy_pilot_quadrant"]}" ("{key_field}")',
        f'CREATE INDEX IF NOT EXISTS idx_{tables["xy_pilot_quadrant"]}_{quadrant_field} ON "{tables["xy_pilot_quadrant"]}" ("{quadrant_field}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{tables["xy_pilot_point_source"]}_{key_field} ON "{tables["xy_pilot_point_source"]}" ("{key_field}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{tables["xy_pilot_point_attribute_check"]}_source_attribute ON "{tables["xy_pilot_point_attribute_check"]}" ("point_source_key", "attribute_name")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{tables["xy_score"]}_{key_field} ON "{tables["xy_score"]}" ("{key_field}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{tables["xy_accion"]}_{key_field} ON "{tables["xy_accion"]}" ("{key_field}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{tables["xy_homologacion_final"]}_{key_field} ON "{tables["xy_homologacion_final"]}" ("{key_field}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{tables["xy_pilot_quadrant_conflict"]}_{key_field} ON "{tables["xy_pilot_quadrant_conflict"]}" ("{key_field}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{tables["xy_pilot_quadrant_conflict_match"]}_{key_field}_{quadrant_field} ON "{tables["xy_pilot_quadrant_conflict_match"]}" ("{key_field}", "{quadrant_field}")',
    ]

    for table_name, spec in reference_tables.items():
        pk = spec.get("pk")
        if pk:
            statements.append(
                f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{table_name}_{pk} ON "{table_name}" ("{pk}")'
            )

    for statement in statements:
        try:
            connection.execute(statement)
        except sqlite3.OperationalError as error:
            LOGGER.warning("No se pudo crear índice con sentencia: %s | error=%s", statement, error)


def write_outputs(
    cfg: dict[str, Any],
    output_gpkg: Path,
    pilot_xy_point: gpd.GeoDataFrame,
    pilot_zone: gpd.GeoDataFrame,
    pilot_quadrant: gpd.GeoDataFrame,
    pilot_quadrant_buffer: gpd.GeoDataFrame,
    buffer_run: pd.DataFrame,
    assignment_run: pd.DataFrame,
    xy_pilot_quadrant: pd.DataFrame,
    xy_pilot_point_source: pd.DataFrame,
    xy_pilot_point_attribute_check: pd.DataFrame,
    xy_score: pd.DataFrame,
    xy_accion: pd.DataFrame,
    xy_homologacion_final: pd.DataFrame,
    reference_tables: dict[str, pd.DataFrame],
    conflicts: pd.DataFrame,
    conflict_matches: pd.DataFrame,
) -> None:
    layers = get_required(cfg, "outputs", "layers")
    tables = get_required(cfg, "outputs", "tables")
    reference_cfg = get_required(cfg, "reference_tables")

    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    if output_gpkg.exists():
        LOGGER.info("Eliminando salida previa: %s", output_gpkg)
        output_gpkg.unlink()

    LOGGER.info("Exportando capa normalizada: %s", layers["pilot_xy_point"])
    pilot_xy_point.to_file(output_gpkg, layer=layers["pilot_xy_point"], driver="GPKG", index=False)

    LOGGER.info("Exportando capa normalizada: %s", layers["pilot_zone"])
    pilot_zone.to_file(output_gpkg, layer=layers["pilot_zone"], driver="GPKG", index=False)

    LOGGER.info("Exportando capa normalizada: %s", layers["pilot_quadrant"])
    pilot_quadrant.to_file(output_gpkg, layer=layers["pilot_quadrant"], driver="GPKG", index=False)

    LOGGER.info("Exportando capa normalizada: %s", layers["pilot_quadrant_buffer"])
    pilot_quadrant_buffer.to_file(
        output_gpkg,
        layer=layers["pilot_quadrant_buffer"],
        driver="GPKG",
        index=False,
    )

    write_table_to_gpkg(buffer_run, output_gpkg, tables["pilot_buffer_run"], "Ejecución del buffer negativo.")
    write_table_to_gpkg(assignment_run, output_gpkg, tables["pilot_assignment_run"], "Ejecución de asignación punto-cuadrante.")
    write_table_to_gpkg(xy_pilot_quadrant, output_gpkg, tables["xy_pilot_quadrant"], "Relación normalizada entre puntos XY y cuadrantes piloto.")
    write_table_to_gpkg(
        xy_pilot_point_source,
        output_gpkg,
        tables["xy_pilot_point_source"],
        "Fuente completa de origen de cada punto utilizado por A4.1.",
    )
    write_table_to_gpkg(
        xy_pilot_point_attribute_check,
        output_gpkg,
        tables["xy_pilot_point_attribute_check"],
        "Comparación de atributos A3 contra puntos A2.1 de los cuadrantes piloto.",
    )
    write_table_to_gpkg(xy_score, output_gpkg, tables["xy_score"], "Tabla mínima A4: xy_group_id y score_aptitud_total.")
    write_table_to_gpkg(xy_accion, output_gpkg, tables["xy_accion"], "Tabla A4 de acción filtrada al subconjunto piloto.")
    write_table_to_gpkg(
        xy_homologacion_final,
        output_gpkg,
        tables["xy_homologacion_final"],
        "Clases homologadas finales tomadas del GeoPackage de origen de cada punto.",
    )

    for table_name, dataframe in reference_tables.items():
        write_table_to_gpkg(
            dataframe,
            output_gpkg,
            table_name,
            str(reference_cfg[table_name].get("description", f"Tabla de referencia {table_name}.")),
        )

    write_table_to_gpkg(conflicts, output_gpkg, tables["xy_pilot_quadrant_conflict"], "Puntos XY con múltiples coincidencias de cuadrante.")
    write_table_to_gpkg(conflict_matches, output_gpkg, tables["xy_pilot_quadrant_conflict_match"], "Detalle normalizado de cada coincidencia en conflicto.")

    with sqlite3.connect(output_gpkg) as connection:
        create_indexes(cfg, connection)
        connection.commit()


# ============================================================
# CLI / proceso principal
# ============================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extracción normalizada A4 de puntos A2.1 asignados a cuadrantes piloto."
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Ruta al YAML de configuración A4.",
    )
    parser.add_argument("--points-gpkg", default=None, help="Override opcional de paths.points_gpkg.")
    parser.add_argument("--quadrants-gpkg", default=None, help="Override opcional de paths.quadrants_gpkg.")
    parser.add_argument("--output-gpkg", default=None, help="Override opcional de paths.output_gpkg.")
    parser.add_argument("--log-path", default=None, help="Override opcional de paths.log_path.")
    parser.add_argument("--buffer-negative-m", type=float, default=None, help="Override opcional de spatial.buffer_negative_m.")
    parser.add_argument("--metric-crs", default=None, help="Override opcional de spatial.metric_crs.")
    parser.add_argument("--predicate", default=None, help="Override opcional de spatial.predicate.")
    parser.add_argument("--multiple-match-policy", default=None, help="Override opcional de spatial.multiple_match_policy.")
    return parser.parse_args()


def apply_cli_overrides(cfg: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    out = dict(cfg)
    out.setdefault("paths", {})
    out.setdefault("spatial", {})

    path_overrides = {
        "points_gpkg": args.points_gpkg,
        "quadrants_gpkg": args.quadrants_gpkg,
        "output_gpkg": args.output_gpkg,
        "log_path": args.log_path,
    }
    for key, value in path_overrides.items():
        if value is not None:
            out["paths"][key] = value

    spatial_overrides = {
        "buffer_negative_m": args.buffer_negative_m,
        "metric_crs": args.metric_crs,
        "predicate": args.predicate,
        "multiple_match_policy": args.multiple_match_policy,
    }
    for key, value in spatial_overrides.items():
        if value is not None:
            out["spatial"][key] = value

    return out


def main() -> None:
    args = parse_args()
    config_path = resolve_path(args.config)
    cfg = apply_cli_overrides(read_yaml(config_path), args)
    validate_config(cfg)

    points_gpkg = resolve_path(get_required(cfg, "paths", "points_gpkg"))
    quadrants_gpkg = resolve_path(get_required(cfg, "paths", "quadrants_gpkg"))
    output_gpkg = resolve_path(get_required(cfg, "paths", "output_gpkg"))
    log_path = resolve_path(get_required(cfg, "paths", "log_path"))

    configure_logger(log_path)

    require_path(points_gpkg, "GeoPackage de puntos A2.1")
    require_path(quadrants_gpkg, "GeoPackage de cuadrantes piloto")

    LOGGER.info("Iniciando extracción normalizada A4 de puntos por cuadrantes piloto.")
    LOGGER.info("CONFIG: %s", config_path)
    LOGGER.info("Ambiente Python: %s", sys.prefix)
    LOGGER.info(
        "Uso de fuentes A3 completas para Costa Rica y Panamá: %s",
        bool(
            get_optional(cfg, "point_source_selection", default={}).get(
                "enabled",
                False,
            )
        ),
    )

    quadrants = read_quadrants(cfg, quadrants_gpkg)
    pilot_zone = build_pilot_zone(cfg, quadrants)
    pilot_quadrant = build_pilot_quadrant(cfg, quadrants)
    pilot_quadrant_buffer, metric_crs_text = build_quadrant_buffer(cfg, quadrants)

    (
        points,
        actions,
        scores,
        homologation,
        point_sources,
        point_attribute_checks,
        point_source_stats,
    ) = load_selected_point_sources(
        cfg=cfg,
        base_points_gpkg=points_gpkg,
        quadrant_buffer=pilot_quadrant_buffer,
    )
    assignments_before_use, conflicts, conflict_matches, raw_match_count = assign_quadrants(
        cfg=cfg,
        points=points,
        quadrant_buffer=pilot_quadrant_buffer,
    )

    assignments, excluded_by_use_count = filter_assignments_by_use(cfg, assignments_before_use, actions)
    if assignments.empty:
        raise ValueError("No quedaron puntos asignados con uso entrenamiento o validación.")

    key_field = get_required(cfg, "fields", "key")
    quadrant_field = get_required(cfg, "fields", "quadrant")
    selected_keys = assignments[key_field]

    pilot_xy_point = subset_pilot_xy_point(cfg, points, selected_keys)
    xy_score = subset_loaded_table(
        cfg,
        scores,
        as_list(get_required(cfg, "fields", "score"), "fields.score"),
        selected_keys,
        "scores de las fuentes seleccionadas",
    )
    xy_accion = subset_loaded_table(
        cfg,
        actions,
        as_list(get_required(cfg, "fields", "action"), "fields.action"),
        selected_keys,
        "acciones de las fuentes seleccionadas",
    )
    xy_homologacion_final = subset_loaded_table(
        cfg,
        homologation,
        as_list(
            get_required(cfg, "fields", "homologation"),
            "fields.homologation",
        ),
        selected_keys,
        "clases homologadas de las fuentes seleccionadas",
    )
    xy_pilot_point_source = subset_loaded_table(
        cfg,
        point_sources,
        as_list(get_required(cfg, "fields", "point_source"), "fields.point_source"),
        selected_keys,
        "procedencia de los puntos seleccionados",
    )
    validate_selected_sources_in_final_points(cfg, xy_pilot_point_source)
    reference_tables = read_reference_tables(cfg, points_gpkg)

    layers = get_required(cfg, "outputs", "layers")
    output_tables = get_required(cfg, "outputs", "tables")
    tables_by_name: dict[str, pd.DataFrame] = {
        layers["pilot_xy_point"]: pilot_xy_point,
        layers["pilot_zone"]: pilot_zone,
        layers["pilot_quadrant"]: pilot_quadrant,
        layers["pilot_quadrant_buffer"]: pilot_quadrant_buffer,
        output_tables["xy_pilot_quadrant"]: assignments,
        output_tables["xy_pilot_point_source"]: xy_pilot_point_source,
        output_tables["xy_pilot_point_attribute_check"]: point_attribute_checks,
        output_tables["xy_score"]: xy_score,
        output_tables["xy_accion"]: xy_accion,
        output_tables["xy_homologacion_final"]: xy_homologacion_final,
        output_tables["xy_pilot_quadrant_conflict"]: conflicts,
        output_tables["xy_pilot_quadrant_conflict_match"]: conflict_matches,
    }
    tables_by_name.update(reference_tables)
    validate_configured_relationships(cfg, tables_by_name)

    assignments = assignments.sort_values([quadrant_field, key_field]).reset_index(drop=True)

    buffer_run = build_buffer_run_table(cfg, metric_crs_text)
    assignment_run = build_assignment_run_table(
        cfg=cfg,
        points_gpkg=points_gpkg,
        quadrants_gpkg=quadrants_gpkg,
        output_gpkg=output_gpkg,
        quadrants_count=len(pilot_quadrant),
        buffer_quadrants_count=len(pilot_quadrant_buffer),
        bbox_candidate_count=len(points),
        raw_match_count=raw_match_count,
        valid_assignment_count_before_use=len(assignments_before_use),
        extracted_assignment_count=len(assignments),
        conflict_point_count=len(conflicts),
        excluded_by_use_count=excluded_by_use_count,
        point_source_stats=point_source_stats,
    )

    write_outputs(
        cfg=cfg,
        output_gpkg=output_gpkg,
        pilot_xy_point=pilot_xy_point,
        pilot_zone=pilot_zone,
        pilot_quadrant=pilot_quadrant,
        pilot_quadrant_buffer=pilot_quadrant_buffer,
        buffer_run=buffer_run,
        assignment_run=assignment_run,
        xy_pilot_quadrant=assignments,
        xy_pilot_point_source=xy_pilot_point_source,
        xy_pilot_point_attribute_check=point_attribute_checks,
        xy_score=xy_score,
        xy_accion=xy_accion,
        xy_homologacion_final=xy_homologacion_final,
        reference_tables=reference_tables,
        conflicts=conflicts,
        conflict_matches=conflict_matches,
    )

    LOGGER.info("Extracción normalizada A4 finalizada.")
    LOGGER.info("GeoPackage: %s", output_gpkg)
    LOGGER.info("Log: %s", log_path)


if __name__ == "__main__":
    main()
