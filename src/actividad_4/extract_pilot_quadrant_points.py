# -*- coding: utf-8 -*-
"""
3NF extension that assigns A2.1 XY points to pilot quadrants.

Default execution from the repository root:

    conda run -n pgbm_actividad1 python src/actividad_4/extract_pilot_quadrant_points.py

This script follows the A4 diagram: it creates the normalized pilot-quadrant
extension, keeps a materialized projection of the selected A2.1 points, copies
only the A2.1 reference/catalog tables shown in the diagram, and exports the
minimal score table required by A4: xy_score(xy_group_id, score_aptitud_total), and the normalized xy_accion table shown in the diagram.

It intentionally does NOT create a flattened point layer such as
`pilot_quadrant_points` or `vw_pilot_quadrant_points`, and it does NOT export
A2.1 thematic tables that are not part of the A4 diagram, such as xy_core,
xy_temporal, xy_spectral, xy_conflicto, xy_clase_resumen, or
xy_homologacion_final.

Spatial layers
--------------
1. pilot_xy_point
   Materialized projection of A2.1 `xy_point` for the selected points. It keeps
   the normalized foreign keys `id_pais_grupo`, `id_0`, `id_1`, and `id_2`;
   it does not duplicate country names, class labels, action attributes, or
   quadrant attributes.

2. pilot_zone
   Pilot zone entity, dissolved from the quadrant layer by id_zona.

3. pilot_quadrant
   Pilot quadrant entity. id_cuadrante is the primary identifier and id_zona is
   a foreign key to pilot_zone.

4. pilot_quadrant_buffer
   Assignment geometry produced by applying the negative buffer. This is kept as
   a separate relation because it is derived from pilot_quadrant and a buffer run.

Attribute/reference tables
--------------------------
5. pilot_buffer_run
6. pilot_assignment_run
7. xy_pilot_quadrant
8. xy_score                         # only xy_group_id + score_aptitud_total
9. xy_accion                         # A4 action table, filtered to selected points
10. pais
11. clase_origen_nivel_0
12. clase_origen_nivel_1
13. clase_origen_nivel_2
14. clase_propuesta_nivel_0
15. clase_propuesta_nivel_1
16. homologacion_nivel_0_origen_propuesta
17. homologacion_nivel_1_origen_propuesta
18. homologacion_nivel_2_excepcion_nivel_1_propuesta
19. xy_pilot_quadrant_conflict
20. xy_pilot_quadrant_conflict_match

xy_accion is both read to filter entrenamiento/validación and exported as the
1:1 action table shown in the A4 diagram, filtered to the selected pilot points.
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


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]

DEFAULT_POINTS_GPKG = (
    REPO_ROOT / "data" / "processed" / "a2_1_modelo_datos" / "gpkg" / "a2_1_xy_point.gpkg"
)
DEFAULT_QUADRANTS_GPKG = (
    REPO_ROOT / "data" / "raw" / "cuadrantes_pilotos" / "zonas_cuadrantes_pilotos.gpkg"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "processed" / "a4_pilot_quadrant_extraction"
DEFAULT_OUTPUT_GPKG = DEFAULT_OUTPUT_ROOT / "gpkg" / "pilot_quadrant_extraction_normalized.gpkg"
DEFAULT_LOG_PATH = DEFAULT_OUTPUT_ROOT / "logs" / "extract_pilot_quadrant_points_normalized.log"

POINTS_LAYER = "xy_point"
ACTION_TABLE = "xy_accion"
SCORE_TABLE = "xy_score"
QUADRANTS_LAYER = "zonas_cuadrantes"

OUTPUT_PILOT_XY_POINT_LAYER = "pilot_xy_point"
OUTPUT_ZONE_LAYER = "pilot_zone"
OUTPUT_QUADRANT_LAYER = "pilot_quadrant"
OUTPUT_QUADRANT_BUFFER_LAYER = "pilot_quadrant_buffer"
OUTPUT_BUFFER_RUN_TABLE = "pilot_buffer_run"
OUTPUT_ASSIGNMENT_RUN_TABLE = "pilot_assignment_run"
OUTPUT_XY_QUADRANT_TABLE = "xy_pilot_quadrant"
OUTPUT_SCORE_TABLE = "xy_score"
OUTPUT_ACTION_TABLE = "xy_accion"
OUTPUT_CONFLICT_TABLE = "xy_pilot_quadrant_conflict"
OUTPUT_CONFLICT_MATCH_TABLE = "xy_pilot_quadrant_conflict_match"

KEY_FIELD = "xy_group_id"
ZONE_FIELD = "id_zona"
QUADRANT_FIELD = "id_cuadrante"
QUADRANT_FIELDS = [ZONE_FIELD, QUADRANT_FIELD]

PILOT_XY_POINT_FIELDS = [
    KEY_FIELD,
    "lon",
    "lat",
    "id_pais_grupo",
    "id_0",
    "id_1",
    "id_2",
]
ACTION_FIELDS = [
    KEY_FIELD,
    "categoria_aptitud_preliminar",
    "categoria_uso_actividad_1_8",
    "definicion_categoria_aptitud",
    "accion_recomendada",
    "razon_categoria_aptitud",
]
SCORE_FIELDS = [KEY_FIELD, "score_aptitud_total"]

# Reference/catalog tables explicitly shown in the A4 diagram.
# They are copied complete because they are lookup tables, not point-specific
# thematic tables. The selected point subset remains in pilot_xy_point and
# xy_score.
REFERENCE_TABLE_SPECS = {
    "pais": {
        "fields": ["id_pais_grupo", "pais"],
        "pk": "id_pais_grupo",
        "description": "Catálogo normalizado de países usado por pilot_xy_point.id_pais_grupo.",
    },
    "clase_origen_nivel_0": {
        "fields": ["id_0", "nivel_0"],
        "pk": "id_0",
        "description": "Catálogo de clases de origen nivel 0.",
    },
    "clase_origen_nivel_1": {
        "fields": ["id_1", "nivel_1", "id_0"],
        "pk": "id_1",
        "description": "Catálogo de clases de origen nivel 1.",
    },
    "clase_origen_nivel_2": {
        "fields": ["id_2", "nivel_2", "id_1"],
        "pk": "id_2",
        "description": "Catálogo de clases de origen nivel 2.",
    },
    "clase_propuesta_nivel_0": {
        "fields": ["id_0_propuesta", "nivel_0_propuesta"],
        "pk": "id_0_propuesta",
        "description": "Catálogo de clases propuestas nivel 0.",
    },
    "clase_propuesta_nivel_1": {
        "fields": ["id_1_propuesta", "nivel_1_propuesta", "id_0_propuesta"],
        "pk": "id_1_propuesta",
        "description": "Catálogo de clases propuestas nivel 1.",
    },
    "homologacion_nivel_0_origen_propuesta": {
        "fields": ["id_0", "id_0_propuesta"],
        "pk": "id_0",
        "description": "Homologación N:1 de nivel 0 de origen a propuesta.",
    },
    "homologacion_nivel_1_origen_propuesta": {
        "fields": ["id_1", "id_1_propuesta"],
        "pk": "id_1",
        "description": "Homologación N:1 de nivel 1 de origen a propuesta.",
    },
    "homologacion_nivel_2_excepcion_nivel_1_propuesta": {
        "fields": ["id_2", "id_1_propuesta"],
        "pk": "id_2",
        "description": "Excepciones N:1 desde nivel 2 de origen a nivel 1 propuesto.",
    },
}

EXPORT_USES = ["entrenamiento", "validación"]

BUFFER_RUN_ID = "buffer_run_001"
ASSIGNMENT_RUN_ID = "assignment_run_001"

LOGGER = logging.getLogger("pilot_quadrant_extraction_normalized")


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


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def require_path(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"No existe {label}: {path}")


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
        dataframe = pd.read_sql_query(query, connection)

    return dataframe


def validate_unique_key(dataframe: pd.DataFrame, key_field: str, label: str) -> None:
    duplicated = dataframe[key_field].duplicated().sum()
    if duplicated:
        raise ValueError(f"{label} tiene {duplicated:,} llaves duplicadas en {key_field}")


def validate_not_null(dataframe: pd.DataFrame, fields: list[str], label: str) -> None:
    for field in fields:
        missing = dataframe[field].isna().sum()
        if missing:
            raise ValueError(f"{label} tiene {missing:,} valores nulos en {field}")


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


def infer_metric_crs(dataframe: gpd.GeoDataFrame, metric_crs: str) -> Any:
    if metric_crs.lower() != "auto":
        return metric_crs

    estimated = dataframe.estimate_utm_crs()
    if estimated is None:
        raise ValueError(
            "No se pudo inferir un CRS métrico automáticamente. "
            "Indica uno explícitamente, por ejemplo --metric-crs EPSG:32616."
        )

    return estimated


def read_quadrants(quadrants_gpkg: Path, quadrants_layer: str) -> gpd.GeoDataFrame:
    LOGGER.info("Leyendo cuadrantes: %s | layer=%s", quadrants_gpkg, quadrants_layer)
    quadrants = gpd.read_file(quadrants_gpkg, layer=quadrants_layer)
    require_fields(list(quadrants.columns), QUADRANT_FIELDS + ["geometry"], quadrants_layer)

    if quadrants.empty:
        raise ValueError("La capa de cuadrantes está vacía.")
    if quadrants.crs is None:
        raise ValueError("La capa de cuadrantes no tiene CRS definido.")

    validate_not_null(quadrants, QUADRANT_FIELDS, quadrants_layer)

    duplicated_quadrants = quadrants[QUADRANT_FIELD].duplicated().sum()
    if duplicated_quadrants:
        raise ValueError(
            f"{QUADRANT_FIELD} debe ser único globalmente, pero hay "
            f"{duplicated_quadrants:,} duplicados."
        )

    invalid_geometry = (~quadrants.geometry.is_valid).sum()
    if invalid_geometry:
        LOGGER.warning("Cuadrantes con geometría inválida: %s", f"{invalid_geometry:,}")
        quadrants = quadrants.copy()
        quadrants["geometry"] = quadrants.geometry.make_valid()

    quadrants = quadrants[QUADRANT_FIELDS + ["geometry"]].copy()
    LOGGER.info("Cuadrantes leídos: %s | CRS=%s", f"{len(quadrants):,}", quadrants.crs)
    return quadrants


def build_pilot_zone(quadrants: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    LOGGER.info("Construyendo pilot_zone por disolución de cuadrantes.")
    zones = quadrants[[ZONE_FIELD, "geometry"]].dissolve(by=ZONE_FIELD, as_index=False)
    zones = zones[[ZONE_FIELD, "geometry"]].copy()
    validate_not_null(zones, [ZONE_FIELD], OUTPUT_ZONE_LAYER)
    validate_unique_key(zones, ZONE_FIELD, OUTPUT_ZONE_LAYER)
    return zones


def build_pilot_quadrant(quadrants: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    LOGGER.info("Construyendo pilot_quadrant normalizado.")
    return quadrants[[QUADRANT_FIELD, ZONE_FIELD, "geometry"]].copy()


def build_quadrant_buffer(
    quadrants: gpd.GeoDataFrame,
    buffer_negative_m: float,
    metric_crs: str,
) -> tuple[gpd.GeoDataFrame, str]:
    metric_crs_resolved = infer_metric_crs(quadrants, metric_crs)
    metric_crs_text = str(metric_crs_resolved)

    LOGGER.info(
        "Aplicando buffer negativo a cuadrantes | distancia=%s m | CRS métrico=%s",
        buffer_negative_m,
        metric_crs_text,
    )

    buffered_metric = quadrants[[QUADRANT_FIELD, "geometry"]].copy().to_crs(metric_crs_resolved)

    if buffer_negative_m > 0:
        buffered_metric["geometry"] = buffered_metric.geometry.buffer(-float(buffer_negative_m))
    elif buffer_negative_m == 0:
        LOGGER.warning("buffer_negative_m=0: se usará la geometría completa del cuadrante.")
    else:
        raise ValueError("buffer_negative_m debe ser mayor o igual que 0.")

    empty_count = buffered_metric.geometry.is_empty.sum()
    if empty_count:
        LOGGER.warning(
            "Cuadrantes eliminados por buffer negativo excesivo: %s",
            f"{empty_count:,}",
        )
        buffered_metric = buffered_metric[~buffered_metric.geometry.is_empty].copy()

    if buffered_metric.empty:
        raise ValueError(
            "El buffer negativo eliminó todos los cuadrantes. "
            "Reduce --buffer-negative-m o revisa el CRS métrico."
        )

    buffered = buffered_metric.to_crs(quadrants.crs)
    buffered.insert(0, "buffer_run_id", BUFFER_RUN_ID)
    buffered = buffered[["buffer_run_id", QUADRANT_FIELD, "geometry"]].copy()

    return buffered, metric_crs_text


def read_points_in_quadrants_bbox(
    points_gpkg: Path,
    points_layer: str,
    quadrants_for_assignment: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    LOGGER.info("Inspeccionando CRS de puntos: %s | layer=%s", points_gpkg, points_layer)
    point_sample = gpd.read_file(points_gpkg, layer=points_layer, rows=1)

    if point_sample.crs is None:
        raise ValueError("La capa xy_point no tiene CRS definido.")

    quadrants_for_bbox = quadrants_for_assignment.to_crs(point_sample.crs)
    bbox = tuple(quadrants_for_bbox.total_bounds)

    LOGGER.info("Leyendo puntos dentro del bbox de cuadrantes con buffer: %s", bbox)
    points = gpd.read_file(points_gpkg, layer=points_layer, bbox=bbox)
    require_fields(
        list(points.columns),
        PILOT_XY_POINT_FIELDS + ["geometry"],
        points_layer,
    )

    if points.crs is None:
        points = points.set_crs(point_sample.crs)

    validate_unique_key(points, KEY_FIELD, points_layer)

    LOGGER.info("Puntos candidatos por bbox: %s | CRS=%s", f"{len(points):,}", points.crs)
    return points


def assign_quadrants(
    points: gpd.GeoDataFrame,
    quadrant_buffer: gpd.GeoDataFrame,
    predicate: str,
    multiple_match_policy: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    if points.empty:
        LOGGER.warning("No hay puntos candidatos dentro del bbox de cuadrantes.")
        empty_assignments = pd.DataFrame(columns=[KEY_FIELD, QUADRANT_FIELD])
        empty_conflicts = pd.DataFrame(
            columns=[KEY_FIELD, "n_matches", "conflict_reason"]
        )
        empty_conflict_matches = pd.DataFrame(columns=[KEY_FIELD, QUADRANT_FIELD])
        return empty_assignments, empty_conflicts, empty_conflict_matches, 0

    if points.crs != quadrant_buffer.crs:
        LOGGER.info("Reproyectando buffer de cuadrantes de %s a %s", quadrant_buffer.crs, points.crs)
        quadrant_buffer = quadrant_buffer.to_crs(points.crs)

    LOGGER.info("Ejecutando join espacial contra cuadrantes con buffer | predicate=%s", predicate)
    matches = gpd.sjoin(
        points[[KEY_FIELD, "geometry"]],
        quadrant_buffer[[QUADRANT_FIELD, "geometry"]],
        how="inner",
        predicate=predicate,
    ).drop(columns=["index_right"])

    total_matches = len(matches)
    LOGGER.info("Coincidencias punto-cuadrante antes de depurar conflictos: %s", f"{total_matches:,}")

    if matches.empty:
        empty_assignments = pd.DataFrame(columns=[KEY_FIELD, QUADRANT_FIELD])
        empty_conflicts = pd.DataFrame(
            columns=[KEY_FIELD, "n_matches", "conflict_reason"]
        )
        empty_conflict_matches = pd.DataFrame(columns=[KEY_FIELD, QUADRANT_FIELD])
        return empty_assignments, empty_conflicts, empty_conflict_matches, total_matches

    match_counts = matches.groupby(KEY_FIELD).size().rename("n_matches").reset_index()
    conflict_keys = match_counts.loc[match_counts["n_matches"] > 1, KEY_FIELD]

    if not conflict_keys.empty:
        n_conflict_points = len(conflict_keys)
        LOGGER.warning("Puntos con más de un cuadrante candidato: %s", f"{n_conflict_points:,}")
        if multiple_match_policy == "raise":
            raise ValueError(
                f"Hay {n_conflict_points:,} puntos con múltiples cuadrantes. "
                "Revise xy_pilot_quadrant_conflict o use --multiple-match-policy exclude."
            )

    conflict_matches = matches[matches[KEY_FIELD].isin(conflict_keys)][
        [KEY_FIELD, QUADRANT_FIELD]
    ].copy()

    conflicts = match_counts[match_counts[KEY_FIELD].isin(conflict_keys)].copy()
    conflicts["conflict_reason"] = "multiple_quadrant_matches_after_buffer"
    conflicts = conflicts[[KEY_FIELD, "n_matches", "conflict_reason"]]

    valid_matches = matches[~matches[KEY_FIELD].isin(conflict_keys)].copy()
    assignments = valid_matches[[KEY_FIELD, QUADRANT_FIELD]].copy()

    validate_unique_key(assignments, KEY_FIELD, OUTPUT_XY_QUADRANT_TABLE)

    LOGGER.info(
        "Asignaciones válidas sin conflictos: %s | conflictos excluidos: %s",
        f"{len(assignments):,}",
        f"{len(conflicts):,}",
    )
    return assignments, conflicts, conflict_matches, total_matches


def filter_assignments_by_use(
    assignments: pd.DataFrame,
    actions: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    validate_unique_key(actions, KEY_FIELD, ACTION_TABLE)

    before = len(assignments)
    assignments_with_use = assignments.merge(
        actions[[KEY_FIELD, "categoria_uso_actividad_1_8"]],
        on=KEY_FIELD,
        how="left",
        validate="one_to_one",
    )

    missing_usage = assignments_with_use["categoria_uso_actividad_1_8"].isna().sum()
    if missing_usage:
        raise ValueError(f"Asignaciones sin categoría de uso en {ACTION_TABLE}: {missing_usage:,}")

    keep_mask = assignments_with_use["categoria_uso_actividad_1_8"].isin(EXPORT_USES)
    kept_keys = assignments_with_use.loc[keep_mask, KEY_FIELD]
    excluded_by_use_count = int((~keep_mask).sum())

    filtered_assignments = assignments[assignments[KEY_FIELD].isin(kept_keys)].copy()

    LOGGER.info(
        "Filtro de uso: antes=%s | conservados=%s | excluidos=%s | usos=%s",
        f"{before:,}",
        f"{len(filtered_assignments):,}",
        f"{excluded_by_use_count:,}",
        ", ".join(EXPORT_USES),
    )

    return filtered_assignments, excluded_by_use_count


def subset_pilot_xy_point(points: gpd.GeoDataFrame, selected_keys: pd.Series) -> gpd.GeoDataFrame:
    require_fields(
        list(points.columns),
        PILOT_XY_POINT_FIELDS + ["geometry"],
        POINTS_LAYER,
    )
    pilot_xy_point = points.loc[
        points[KEY_FIELD].isin(selected_keys),
        PILOT_XY_POINT_FIELDS + ["geometry"],
    ].copy()
    validate_unique_key(pilot_xy_point, KEY_FIELD, OUTPUT_PILOT_XY_POINT_LAYER)
    missing = len(selected_keys) - pilot_xy_point[KEY_FIELD].nunique()
    if missing:
        raise ValueError(f"{OUTPUT_PILOT_XY_POINT_LAYER} no contiene {missing:,} puntos asignados.")
    return pilot_xy_point


def read_xy_score_subset(
    points_gpkg: Path,
    selected_keys: pd.Series,
) -> pd.DataFrame:
    """Read only the score needed by A4: score_aptitud_total.

    The table is filtered to the selected pilot points and keeps only two
    fields: xy_group_id and score_aptitud_total. No other score components or
    A2.1 thematic/reference tables are copied to the A4 GeoPackage.
    """
    selected_key_values = set(selected_keys.astype("string").dropna().tolist())
    if not selected_key_values:
        raise ValueError("No hay xy_group_id seleccionados para extraer xy_score.")

    score = read_attribute_table(points_gpkg, SCORE_TABLE, SCORE_FIELDS)
    validate_unique_key(score, KEY_FIELD, SCORE_TABLE)

    score[KEY_FIELD] = score[KEY_FIELD].astype("string")
    subset = score[score[KEY_FIELD].isin(selected_key_values)].copy()
    subset = subset[SCORE_FIELDS].sort_values(KEY_FIELD).reset_index(drop=True)

    missing = selected_key_values - set(subset[KEY_FIELD].astype("string"))
    if missing:
        examples = sorted(missing)[:5]
        raise ValueError(
            f"{SCORE_TABLE} no contiene score_aptitud_total para "
            f"{len(missing):,} puntos piloto. Ejemplos: {examples}"
        )

    return subset




def read_xy_accion_subset(
    actions: pd.DataFrame,
    selected_keys: pd.Series,
) -> pd.DataFrame:
    """Return the A4 xy_accion table filtered to selected pilot points."""
    selected_key_values = set(selected_keys.astype("string").dropna().tolist())
    if not selected_key_values:
        raise ValueError("No hay xy_group_id seleccionados para extraer xy_accion.")

    require_fields(list(actions.columns), ACTION_FIELDS, ACTION_TABLE)
    validate_unique_key(actions, KEY_FIELD, ACTION_TABLE)

    out = actions[ACTION_FIELDS].copy()
    out[KEY_FIELD] = out[KEY_FIELD].astype("string")
    subset = out[out[KEY_FIELD].isin(selected_key_values)].copy()
    subset = subset[ACTION_FIELDS].sort_values(KEY_FIELD).reset_index(drop=True)

    missing = selected_key_values - set(subset[KEY_FIELD].astype("string"))
    if missing:
        examples = sorted(missing)[:5]
        raise ValueError(
            f"{ACTION_TABLE} no contiene acción para {len(missing):,} puntos piloto. "
            f"Ejemplos: {examples}"
        )

    return subset


def read_reference_tables(points_gpkg: Path) -> dict[str, pd.DataFrame]:
    """Read the A2.1 lookup tables that are explicitly part of the A4 diagram."""
    reference_tables: dict[str, pd.DataFrame] = {}

    for table_name, spec in REFERENCE_TABLE_SPECS.items():
        fields = spec["fields"]
        dataframe = read_attribute_table(points_gpkg, table_name, fields)
        dataframe = dataframe[fields].copy()

        pk = spec.get("pk")
        if pk:
            validate_not_null(dataframe, [pk], table_name)
            validate_unique_key(dataframe, pk, table_name)

        reference_tables[table_name] = dataframe

    return reference_tables


def validate_reference_tables_for_a4(
    pilot_xy_point: pd.DataFrame,
    reference_tables: dict[str, pd.DataFrame],
) -> None:
    """Validate the foreign-key paths represented in the A4 diagram."""
    pais = reference_tables["pais"]
    clase0 = reference_tables["clase_origen_nivel_0"]
    clase1 = reference_tables["clase_origen_nivel_1"]
    clase2 = reference_tables["clase_origen_nivel_2"]
    propuesta0 = reference_tables["clase_propuesta_nivel_0"]
    propuesta1 = reference_tables["clase_propuesta_nivel_1"]
    hom0 = reference_tables["homologacion_nivel_0_origen_propuesta"]
    hom1 = reference_tables["homologacion_nivel_1_origen_propuesta"]
    hom2 = reference_tables["homologacion_nivel_2_excepcion_nivel_1_propuesta"]

    validate_reference(
        pilot_xy_point,
        "id_pais_grupo",
        pais,
        "id_pais_grupo",
        "pilot_xy_point.id_pais_grupo -> pais.id_pais_grupo",
    )
    validate_reference(pilot_xy_point, "id_0", clase0, "id_0", "pilot_xy_point.id_0 -> clase_origen_nivel_0.id_0")
    validate_reference(pilot_xy_point, "id_1", clase1, "id_1", "pilot_xy_point.id_1 -> clase_origen_nivel_1.id_1")
    validate_reference(pilot_xy_point, "id_2", clase2, "id_2", "pilot_xy_point.id_2 -> clase_origen_nivel_2.id_2")

    validate_reference(clase1, "id_0", clase0, "id_0", "clase_origen_nivel_1.id_0 -> clase_origen_nivel_0.id_0")
    validate_reference(clase2, "id_1", clase1, "id_1", "clase_origen_nivel_2.id_1 -> clase_origen_nivel_1.id_1")
    validate_reference(propuesta1, "id_0_propuesta", propuesta0, "id_0_propuesta", "clase_propuesta_nivel_1.id_0_propuesta -> clase_propuesta_nivel_0.id_0_propuesta")

    validate_reference(hom0, "id_0", clase0, "id_0", "homologacion_nivel_0_origen_propuesta.id_0 -> clase_origen_nivel_0.id_0")
    validate_reference(hom0, "id_0_propuesta", propuesta0, "id_0_propuesta", "homologacion_nivel_0_origen_propuesta.id_0_propuesta -> clase_propuesta_nivel_0.id_0_propuesta")
    validate_reference(hom1, "id_1", clase1, "id_1", "homologacion_nivel_1_origen_propuesta.id_1 -> clase_origen_nivel_1.id_1")
    validate_reference(hom1, "id_1_propuesta", propuesta1, "id_1_propuesta", "homologacion_nivel_1_origen_propuesta.id_1_propuesta -> clase_propuesta_nivel_1.id_1_propuesta")
    validate_reference(hom2, "id_2", clase2, "id_2", "homologacion_nivel_2_excepcion_nivel_1_propuesta.id_2 -> clase_origen_nivel_2.id_2")
    validate_reference(hom2, "id_1_propuesta", propuesta1, "id_1_propuesta", "homologacion_nivel_2_excepcion_nivel_1_propuesta.id_1_propuesta -> clase_propuesta_nivel_1.id_1_propuesta")


def build_buffer_run_table(
    buffer_negative_m: float,
    metric_crs_text: str,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "buffer_run_id": BUFFER_RUN_ID,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "buffer_negative_m": float(buffer_negative_m),
                "metric_crs": metric_crs_text,
            }
        ]
    )


def build_assignment_run_table(
    points_gpkg: Path,
    quadrants_gpkg: Path,
    output_gpkg: Path,
    predicate: str,
    multiple_match_policy: str,
    quadrants_count: int,
    buffer_quadrants_count: int,
    bbox_candidate_count: int,
    raw_match_count: int,
    valid_assignment_count_before_use: int,
    extracted_assignment_count: int,
    conflict_point_count: int,
    excluded_by_use_count: int,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "assignment_run_id": ASSIGNMENT_RUN_ID,
                "buffer_run_id": BUFFER_RUN_ID,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "points_gpkg": str(points_gpkg),
                "points_layer": POINTS_LAYER,
                "action_filter_table": ACTION_TABLE,
                "action_filter_field": "categoria_uso_actividad_1_8",
                "quadrants_gpkg": str(quadrants_gpkg),
                "quadrants_layer": QUADRANTS_LAYER,
                "output_gpkg": str(output_gpkg),
                "a2_1_reference_policy": "diagram_reference_tables_copied_xy_score_minimal_and_xy_accion_filtered",
                "spatial_predicate": predicate,
                "multiple_match_policy": multiple_match_policy,
                "quadrants_count": quadrants_count,
                "buffer_quadrants_count": buffer_quadrants_count,
                "bbox_candidate_points": bbox_candidate_count,
                "raw_spatial_matches": raw_match_count,
                "valid_assignments_before_use_filter": valid_assignment_count_before_use,
                "extracted_assignments": extracted_assignment_count,
                "conflict_points": conflict_point_count,
                "excluded_by_use": excluded_by_use_count,
                "exported_uses": "|".join(EXPORT_USES),
            }
        ]
    )


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


def create_indexes(connection: sqlite3.Connection) -> None:
    statements = [
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_pilot_xy_point_key '
        f'ON "{OUTPUT_PILOT_XY_POINT_LAYER}" ("{KEY_FIELD}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_pilot_zone_id '
        f'ON "{OUTPUT_ZONE_LAYER}" ("{ZONE_FIELD}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_pilot_quadrant_id '
        f'ON "{OUTPUT_QUADRANT_LAYER}" ("{QUADRANT_FIELD}")',
        f'CREATE INDEX IF NOT EXISTS idx_pilot_quadrant_zone '
        f'ON "{OUTPUT_QUADRANT_LAYER}" ("{ZONE_FIELD}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_pilot_quadrant_buffer '
        f'ON "{OUTPUT_QUADRANT_BUFFER_LAYER}" ("buffer_run_id", "{QUADRANT_FIELD}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_buffer_run '
        f'ON "{OUTPUT_BUFFER_RUN_TABLE}" ("buffer_run_id")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_assignment_run '
        f'ON "{OUTPUT_ASSIGNMENT_RUN_TABLE}" ("assignment_run_id")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_xy_pilot_quadrant_xy '
        f'ON "{OUTPUT_XY_QUADRANT_TABLE}" ("{KEY_FIELD}")',
        f'CREATE INDEX IF NOT EXISTS idx_xy_pilot_quadrant_quad '
        f'ON "{OUTPUT_XY_QUADRANT_TABLE}" ("{QUADRANT_FIELD}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_xy_score_xy '
        f'ON "{OUTPUT_SCORE_TABLE}" ("{KEY_FIELD}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_xy_accion_xy '
        f'ON "{OUTPUT_ACTION_TABLE}" ("{KEY_FIELD}")',
        'CREATE UNIQUE INDEX IF NOT EXISTS ux_pais_id ON "pais" ("id_pais_grupo")',
        'CREATE UNIQUE INDEX IF NOT EXISTS ux_clase_origen_nivel_0_id ON "clase_origen_nivel_0" ("id_0")',
        'CREATE UNIQUE INDEX IF NOT EXISTS ux_clase_origen_nivel_1_id ON "clase_origen_nivel_1" ("id_1")',
        'CREATE INDEX IF NOT EXISTS idx_clase_origen_nivel_1_id0 ON "clase_origen_nivel_1" ("id_0")',
        'CREATE UNIQUE INDEX IF NOT EXISTS ux_clase_origen_nivel_2_id ON "clase_origen_nivel_2" ("id_2")',
        'CREATE INDEX IF NOT EXISTS idx_clase_origen_nivel_2_id1 ON "clase_origen_nivel_2" ("id_1")',
        'CREATE UNIQUE INDEX IF NOT EXISTS ux_clase_propuesta_nivel_0_id ON "clase_propuesta_nivel_0" ("id_0_propuesta")',
        'CREATE UNIQUE INDEX IF NOT EXISTS ux_clase_propuesta_nivel_1_id ON "clase_propuesta_nivel_1" ("id_1_propuesta")',
        'CREATE INDEX IF NOT EXISTS idx_clase_propuesta_nivel_1_id0 ON "clase_propuesta_nivel_1" ("id_0_propuesta")',
        'CREATE UNIQUE INDEX IF NOT EXISTS ux_homologacion_nivel_0_id ON "homologacion_nivel_0_origen_propuesta" ("id_0")',
        'CREATE INDEX IF NOT EXISTS idx_homologacion_nivel_0_prop ON "homologacion_nivel_0_origen_propuesta" ("id_0_propuesta")',
        'CREATE UNIQUE INDEX IF NOT EXISTS ux_homologacion_nivel_1_id ON "homologacion_nivel_1_origen_propuesta" ("id_1")',
        'CREATE INDEX IF NOT EXISTS idx_homologacion_nivel_1_prop ON "homologacion_nivel_1_origen_propuesta" ("id_1_propuesta")',
        'CREATE UNIQUE INDEX IF NOT EXISTS ux_homologacion_nivel_2_id ON "homologacion_nivel_2_excepcion_nivel_1_propuesta" ("id_2")',
        'CREATE INDEX IF NOT EXISTS idx_homologacion_nivel_2_prop ON "homologacion_nivel_2_excepcion_nivel_1_propuesta" ("id_1_propuesta")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_xy_pilot_conflict_xy '
        f'ON "{OUTPUT_CONFLICT_TABLE}" ("{KEY_FIELD}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_xy_pilot_conflict_match '
        f'ON "{OUTPUT_CONFLICT_MATCH_TABLE}" ("{KEY_FIELD}", "{QUADRANT_FIELD}")',
    ]
    for statement in statements:
        try:
            connection.execute(statement)
        except sqlite3.OperationalError as error:
            LOGGER.warning("No se pudo crear índice con sentencia: %s | error=%s", statement, error)


def write_outputs(
    output_gpkg: Path,
    pilot_xy_point: gpd.GeoDataFrame,
    pilot_zone: gpd.GeoDataFrame,
    pilot_quadrant: gpd.GeoDataFrame,
    pilot_quadrant_buffer: gpd.GeoDataFrame,
    buffer_run: pd.DataFrame,
    assignment_run: pd.DataFrame,
    xy_pilot_quadrant: pd.DataFrame,
    xy_score: pd.DataFrame,
    xy_accion: pd.DataFrame,
    reference_tables: dict[str, pd.DataFrame],
    conflicts: pd.DataFrame,
    conflict_matches: pd.DataFrame,
) -> None:
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)

    if output_gpkg.exists():
        LOGGER.info("Eliminando salida previa: %s", output_gpkg)
        output_gpkg.unlink()

    LOGGER.info("Exportando capa normalizada: %s", OUTPUT_PILOT_XY_POINT_LAYER)
    pilot_xy_point.to_file(output_gpkg, layer=OUTPUT_PILOT_XY_POINT_LAYER, driver="GPKG", index=False)

    LOGGER.info("Exportando capa normalizada: %s", OUTPUT_ZONE_LAYER)
    pilot_zone.to_file(output_gpkg, layer=OUTPUT_ZONE_LAYER, driver="GPKG", index=False)

    LOGGER.info("Exportando capa normalizada: %s", OUTPUT_QUADRANT_LAYER)
    pilot_quadrant.to_file(output_gpkg, layer=OUTPUT_QUADRANT_LAYER, driver="GPKG", index=False)

    LOGGER.info("Exportando capa normalizada: %s", OUTPUT_QUADRANT_BUFFER_LAYER)
    pilot_quadrant_buffer.to_file(
        output_gpkg,
        layer=OUTPUT_QUADRANT_BUFFER_LAYER,
        driver="GPKG",
        index=False,
    )

    write_table_to_gpkg(
        buffer_run,
        output_gpkg,
        OUTPUT_BUFFER_RUN_TABLE,
        "Ejecución del buffer negativo.",
    )
    write_table_to_gpkg(
        assignment_run,
        output_gpkg,
        OUTPUT_ASSIGNMENT_RUN_TABLE,
        "Ejecución de asignación punto-cuadrante.",
    )
    write_table_to_gpkg(
        xy_pilot_quadrant,
        output_gpkg,
        OUTPUT_XY_QUADRANT_TABLE,
        "Relación normalizada entre puntos XY y cuadrantes piloto.",
    )
    write_table_to_gpkg(
        xy_score,
        output_gpkg,
        OUTPUT_SCORE_TABLE,
        "Tabla mínima A2.1 filtrada al subconjunto piloto: xy_group_id y score_aptitud_total.",
    )
    write_table_to_gpkg(
        xy_accion,
        output_gpkg,
        OUTPUT_ACTION_TABLE,
        "Tabla A4 de acción filtrada al subconjunto piloto.",
    )

    for table_name, dataframe in reference_tables.items():
        write_table_to_gpkg(
            dataframe,
            output_gpkg,
            table_name,
            REFERENCE_TABLE_SPECS[table_name]["description"],
        )

    write_table_to_gpkg(
        conflicts,
        output_gpkg,
        OUTPUT_CONFLICT_TABLE,
        "Puntos XY con múltiples coincidencias de cuadrante.",
    )
    write_table_to_gpkg(
        conflict_matches,
        output_gpkg,
        OUTPUT_CONFLICT_MATCH_TABLE,
        "Detalle normalizado de cada coincidencia en conflicto.",
    )

    with sqlite3.connect(output_gpkg) as connection:
        create_indexes(connection)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strict normalized extraction of A2.1 XY points assigned to pilot quadrants."
    )
    parser.add_argument("--points-gpkg", default=str(DEFAULT_POINTS_GPKG))
    parser.add_argument("--quadrants-gpkg", default=str(DEFAULT_QUADRANTS_GPKG))
    parser.add_argument("--output-gpkg", default=str(DEFAULT_OUTPUT_GPKG))
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument(
        "--predicate",
        default="within",
        choices=["within", "intersects", "covered_by"],
        help="Spatial predicate used to assign points to buffered quadrants.",
    )
    parser.add_argument(
        "--buffer-negative-m",
        type=float,
        default=30.0,
        help="Negative buffer distance in meters applied inside each quadrant before point assignment.",
    )
    parser.add_argument(
        "--metric-crs",
        default="auto",
        help="Metric CRS for the buffer. Use 'auto' or an explicit CRS such as EPSG:32616.",
    )
    parser.add_argument(
        "--multiple-match-policy",
        default="exclude",
        choices=["exclude", "raise"],
        help="How to handle points matching more than one buffered quadrant. No first-match assignment is allowed.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    points_gpkg = resolve_path(args.points_gpkg)
    quadrants_gpkg = resolve_path(args.quadrants_gpkg)
    output_gpkg = resolve_path(args.output_gpkg)
    log_path = resolve_path(args.log_path)

    configure_logger(log_path)

    require_path(points_gpkg, "GeoPackage de puntos A2.1")
    require_path(quadrants_gpkg, "GeoPackage de cuadrantes piloto")

    LOGGER.info("Iniciando extracción estrictamente normalizada de puntos por cuadrantes piloto.")
    LOGGER.info("Ambiente Python: %s", sys.prefix)

    quadrants = read_quadrants(quadrants_gpkg, QUADRANTS_LAYER)
    pilot_zone = build_pilot_zone(quadrants)
    pilot_quadrant = build_pilot_quadrant(quadrants)
    pilot_quadrant_buffer, metric_crs_text = build_quadrant_buffer(
        quadrants=quadrants,
        buffer_negative_m=args.buffer_negative_m,
        metric_crs=args.metric_crs,
    )

    points = read_points_in_quadrants_bbox(points_gpkg, POINTS_LAYER, pilot_quadrant_buffer)

    assignments_before_use, conflicts, conflict_matches, raw_match_count = assign_quadrants(
        points=points,
        quadrant_buffer=pilot_quadrant_buffer,
        predicate=args.predicate,
        multiple_match_policy=args.multiple_match_policy,
    )

    actions = read_attribute_table(points_gpkg, ACTION_TABLE, ACTION_FIELDS)

    assignments, excluded_by_use_count = filter_assignments_by_use(
        assignments=assignments_before_use,
        actions=actions,
    )
    if assignments.empty:
        raise ValueError(
            "No quedaron puntos asignados con uso entrenamiento o validación."
        )

    selected_keys = assignments[KEY_FIELD]
    pilot_xy_point = subset_pilot_xy_point(points, selected_keys)
    xy_score = read_xy_score_subset(points_gpkg, selected_keys)
    xy_accion = read_xy_accion_subset(actions, selected_keys)
    reference_tables = read_reference_tables(points_gpkg)
    validate_reference_tables_for_a4(pilot_xy_point, reference_tables)

    validate_reference(
        pilot_quadrant,
        ZONE_FIELD,
        pilot_zone,
        ZONE_FIELD,
        f"{OUTPUT_QUADRANT_LAYER}.{ZONE_FIELD} -> {OUTPUT_ZONE_LAYER}.{ZONE_FIELD}",
    )
    validate_reference(
        pilot_quadrant_buffer,
        QUADRANT_FIELD,
        pilot_quadrant,
        QUADRANT_FIELD,
        f"{OUTPUT_QUADRANT_BUFFER_LAYER} -> {OUTPUT_QUADRANT_LAYER}",
    )
    validate_reference(
        assignments,
        KEY_FIELD,
        pilot_xy_point,
        KEY_FIELD,
        f"{OUTPUT_XY_QUADRANT_TABLE} -> {OUTPUT_PILOT_XY_POINT_LAYER}",
    )
    validate_reference(
        assignments,
        QUADRANT_FIELD,
        pilot_quadrant,
        QUADRANT_FIELD,
        f"{OUTPUT_XY_QUADRANT_TABLE} -> {OUTPUT_QUADRANT_LAYER}",
    )
    validate_reference(
        xy_score,
        KEY_FIELD,
        pilot_xy_point,
        KEY_FIELD,
        f"{OUTPUT_SCORE_TABLE} -> {OUTPUT_PILOT_XY_POINT_LAYER}",
    )
    validate_reference(
        xy_accion,
        KEY_FIELD,
        pilot_xy_point,
        KEY_FIELD,
        f"{OUTPUT_ACTION_TABLE} -> {OUTPUT_PILOT_XY_POINT_LAYER}",
    )
    validate_reference(
        conflict_matches,
        QUADRANT_FIELD,
        pilot_quadrant,
        QUADRANT_FIELD,
        f"{OUTPUT_CONFLICT_MATCH_TABLE} -> {OUTPUT_QUADRANT_LAYER}",
    )
    validate_reference(
        conflict_matches,
        KEY_FIELD,
        conflicts,
        KEY_FIELD,
        f"{OUTPUT_CONFLICT_MATCH_TABLE} -> {OUTPUT_CONFLICT_TABLE}",
    )

    assignments = assignments.sort_values([QUADRANT_FIELD, KEY_FIELD]).reset_index(drop=True)

    buffer_run = build_buffer_run_table(
        buffer_negative_m=args.buffer_negative_m,
        metric_crs_text=metric_crs_text,
    )
    assignment_run = build_assignment_run_table(
        points_gpkg=points_gpkg,
        quadrants_gpkg=quadrants_gpkg,
        output_gpkg=output_gpkg,
        predicate=args.predicate,
        multiple_match_policy=args.multiple_match_policy,
        quadrants_count=len(pilot_quadrant),
        buffer_quadrants_count=len(pilot_quadrant_buffer),
        bbox_candidate_count=len(points),
        raw_match_count=raw_match_count,
        valid_assignment_count_before_use=len(assignments_before_use),
        extracted_assignment_count=len(assignments),
        conflict_point_count=len(conflicts),
        excluded_by_use_count=excluded_by_use_count,
    )

    write_outputs(
        output_gpkg=output_gpkg,
        pilot_xy_point=pilot_xy_point,
        pilot_zone=pilot_zone,
        pilot_quadrant=pilot_quadrant,
        pilot_quadrant_buffer=pilot_quadrant_buffer,
        buffer_run=buffer_run,
        assignment_run=assignment_run,
        xy_pilot_quadrant=assignments,
        xy_score=xy_score,
        xy_accion=xy_accion,
        reference_tables=reference_tables,
        conflicts=conflicts,
        conflict_matches=conflict_matches,
    )

    LOGGER.info("Extracción estrictamente normalizada finalizada.")
    LOGGER.info("GeoPackage: %s", output_gpkg)
    LOGGER.info("Log: %s", log_path)


if __name__ == "__main__":
    main()
