# -*- coding: utf-8 -*-
"""
Extract pilot-quadrant points from the A2.1 XY point model.

Default execution from the repository root:

    conda run -n pgbm_actividad1 python src/actividad_4/extract_pilot_quadrant_points.py

The extraction:
1. Reads A2.1 xy_point from the model GeoPackage.
2. Reads xy_homologacion_final and xy_score from the same GeoPackage.
3. Spatially assigns points to pilot quadrants.
4. Adds id_zona and id_cuadrante to each extracted point.
5. Adds id_1_propuesta, nivel_1_propuesta and score_confiabilidad.
6. Exports a combined point layer, optional per-quadrant layers, and summary tables.
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
DEFAULT_OUTPUT_GPKG = DEFAULT_OUTPUT_ROOT / "gpkg" / "pilot_quadrant_points.gpkg"
DEFAULT_SUMMARY_CSV = DEFAULT_OUTPUT_ROOT / "tables" / "pilot_quadrant_summary.csv"
DEFAULT_LOG_PATH = DEFAULT_OUTPUT_ROOT / "logs" / "extract_pilot_quadrant_points.log"

POINTS_LAYER = "xy_point"
HOMOLOGATION_TABLE = "xy_homologacion_final"
SCORE_TABLE = "xy_score"
QUADRANTS_LAYER = "zonas_cuadrantes"
OUTPUT_POINTS_LAYER = "pilot_quadrant_points"
OUTPUT_SUMMARY_TABLE = "pilot_quadrant_summary"
OUTPUT_METADATA_TABLE = "pilot_quadrant_extraction_metadata"

KEY_FIELD = "xy_group_id"
QUADRANT_FIELDS = ["id_zona", "id_cuadrante"]
HOMOLOGATION_FIELDS = [KEY_FIELD, "id_1_propuesta", "nivel_1_propuesta"]
SCORE_FIELDS = [KEY_FIELD, "score_confiabilidad"]

LOGGER = logging.getLogger("pilot_quadrant_extraction")


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


def read_quadrants(quadrants_gpkg: Path, quadrants_layer: str) -> gpd.GeoDataFrame:
    LOGGER.info("Leyendo cuadrantes: %s | layer=%s", quadrants_gpkg, quadrants_layer)
    quadrants = gpd.read_file(quadrants_gpkg, layer=quadrants_layer)
    require_fields(list(quadrants.columns), QUADRANT_FIELDS + ["geometry"], quadrants_layer)

    if quadrants.empty:
        raise ValueError("La capa de cuadrantes está vacía.")
    if quadrants.crs is None:
        raise ValueError("La capa de cuadrantes no tiene CRS definido.")

    invalid_geometry = (~quadrants.geometry.is_valid).sum()
    if invalid_geometry:
        LOGGER.warning("Cuadrantes con geometría inválida: %s", f"{invalid_geometry:,}")
        quadrants = quadrants.copy()
        quadrants["geometry"] = quadrants.geometry.make_valid()

    quadrants = quadrants[QUADRANT_FIELDS + ["geometry"]].copy()
    LOGGER.info("Cuadrantes leídos: %s | CRS=%s", f"{len(quadrants):,}", quadrants.crs)
    return quadrants


def read_points_in_quadrants_bbox(
    points_gpkg: Path,
    points_layer: str,
    quadrants: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    LOGGER.info("Inspeccionando CRS de puntos: %s | layer=%s", points_gpkg, points_layer)
    point_sample = gpd.read_file(points_gpkg, layer=points_layer, rows=1)

    if point_sample.crs is None:
        raise ValueError("La capa xy_point no tiene CRS definido.")

    quadrants_for_bbox = quadrants.to_crs(point_sample.crs)
    bbox = tuple(quadrants_for_bbox.total_bounds)

    LOGGER.info("Leyendo puntos dentro del bbox de cuadrantes: %s", bbox)
    points = gpd.read_file(points_gpkg, layer=points_layer, bbox=bbox)
    require_fields(list(points.columns), [KEY_FIELD, "geometry"], points_layer)

    if points.crs is None:
        points = points.set_crs(point_sample.crs)

    LOGGER.info("Puntos candidatos por bbox: %s | CRS=%s", f"{len(points):,}", points.crs)
    return points


def assign_quadrants(
    points: gpd.GeoDataFrame,
    quadrants: gpd.GeoDataFrame,
    predicate: str,
) -> gpd.GeoDataFrame:
    if points.empty:
        LOGGER.warning("No hay puntos candidatos dentro del bbox de cuadrantes.")
        return points.assign(id_zona=pd.Series(dtype="Int64"), id_cuadrante=pd.Series(dtype="Int64"))

    if points.crs != quadrants.crs:
        LOGGER.info("Reproyectando cuadrantes de %s a %s", quadrants.crs, points.crs)
        quadrants = quadrants.to_crs(points.crs)

    LOGGER.info("Ejecutando join espacial | predicate=%s", predicate)
    joined = gpd.sjoin(
        points,
        quadrants[QUADRANT_FIELDS + ["geometry"]],
        how="inner",
        predicate=predicate,
    ).drop(columns=["index_right"])

    duplicate_matches = joined[KEY_FIELD].duplicated(keep=False).sum()
    if duplicate_matches:
        LOGGER.warning(
            "Puntos con más de una coincidencia de cuadrante: %s. "
            "Se conservará la primera coincidencia ordenada por id_zona/id_cuadrante.",
            f"{duplicate_matches:,}",
        )
        joined = (
            joined.sort_values([KEY_FIELD, "id_zona", "id_cuadrante"])
            .drop_duplicates(subset=[KEY_FIELD], keep="first")
            .copy()
        )

    LOGGER.info("Puntos asignados a cuadrantes: %s", f"{len(joined):,}")
    return joined


def enrich_points(
    points: gpd.GeoDataFrame,
    homologation: pd.DataFrame,
    scores: pd.DataFrame,
) -> gpd.GeoDataFrame:
    validate_unique_key(points, KEY_FIELD, POINTS_LAYER)
    validate_unique_key(homologation, KEY_FIELD, HOMOLOGATION_TABLE)
    validate_unique_key(scores, KEY_FIELD, SCORE_TABLE)

    LOGGER.info("Uniendo homologación final.")
    enriched = points.merge(homologation, on=KEY_FIELD, how="left", validate="one_to_one")

    LOGGER.info("Uniendo score de confiabilidad.")
    enriched = enriched.merge(scores, on=KEY_FIELD, how="left", validate="one_to_one")

    missing_homologation = enriched["id_1_propuesta"].isna().sum()
    missing_score = enriched["score_confiabilidad"].isna().sum()

    if missing_homologation:
        raise ValueError(f"Puntos sin homologación final: {missing_homologation:,}")
    if missing_score:
        raise ValueError(f"Puntos sin score_confiabilidad: {missing_score:,}")

    preferred_columns = [
        KEY_FIELD,
        "lon",
        "lat",
        "pais_grupo",
        "id_0",
        "id_1",
        "id_2",
        "id_1_propuesta",
        "nivel_1_propuesta",
        "score_confiabilidad",
        "id_zona",
        "id_cuadrante",
        "geometry",
    ]
    existing_columns = [column for column in preferred_columns if column in enriched.columns]
    extra_columns = [
        column for column in enriched.columns if column not in existing_columns and column != "geometry"
    ]

    return enriched[existing_columns[:-1] + extra_columns + ["geometry"]].copy()


def dominant_value(series: pd.Series) -> Any:
    values = series.dropna()
    if values.empty:
        return pd.NA

    modes = values.mode()
    if modes.empty:
        return pd.NA

    return modes.iloc[0]


def build_quadrant_summary(
    points: gpd.GeoDataFrame,
    quadrants: gpd.GeoDataFrame,
) -> pd.DataFrame:
    if points.empty:
        summary = pd.DataFrame(
            columns=[
                "id_zona",
                "id_cuadrante",
                "n_points",
                "n_unique_xy",
                "n_nivel_1_propuesta",
                "nivel_1_propuesta_dominante",
                "score_confiabilidad_mean",
                "score_confiabilidad_min",
                "score_confiabilidad_max",
            ]
        )
    else:
        summary = (
            points.groupby(["id_zona", "id_cuadrante"], dropna=False)
            .agg(
                n_points=(KEY_FIELD, "size"),
                n_unique_xy=(KEY_FIELD, "nunique"),
                n_nivel_1_propuesta=("nivel_1_propuesta", "nunique"),
                nivel_1_propuesta_dominante=("nivel_1_propuesta", dominant_value),
                score_confiabilidad_mean=("score_confiabilidad", "mean"),
                score_confiabilidad_min=("score_confiabilidad", "min"),
                score_confiabilidad_max=("score_confiabilidad", "max"),
            )
            .reset_index()
        )

    all_quadrants = quadrants[QUADRANT_FIELDS].drop_duplicates().copy()
    summary = all_quadrants.merge(summary, on=QUADRANT_FIELDS, how="left")

    count_columns = ["n_points", "n_unique_xy", "n_nivel_1_propuesta"]
    for column in count_columns:
        summary[column] = summary[column].fillna(0).astype("int64")

    score_columns = [
        "score_confiabilidad_mean",
        "score_confiabilidad_min",
        "score_confiabilidad_max",
    ]
    for column in score_columns:
        summary[column] = summary[column].round(6)

    return summary.sort_values(QUADRANT_FIELDS).reset_index(drop=True)


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
    LOGGER.info("Exportando tabla: %s | filas=%s", table_name, f"{len(dataframe):,}")
    with sqlite3.connect(gpkg_path) as connection:
        dataframe.to_sql(table_name, connection, if_exists="replace", index=False)
        register_attribute_table_in_gpkg(connection, table_name, description)


def layer_name_for_quadrant(id_zona: Any, id_cuadrante: Any) -> str:
    return f"z{id_zona}_q{id_cuadrante}".lower().replace("-", "_").replace(".", "_")


def write_outputs(
    points: gpd.GeoDataFrame,
    summary: pd.DataFrame,
    output_gpkg: Path,
    summary_csv: Path,
    metadata: pd.DataFrame,
    write_per_quadrant_layers: bool,
) -> None:
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    summary_csv.parent.mkdir(parents=True, exist_ok=True)

    if output_gpkg.exists():
        LOGGER.info("Eliminando salida previa: %s", output_gpkg)
        output_gpkg.unlink()

    LOGGER.info(
        "Exportando capa combinada: %s | layer=%s | filas=%s",
        output_gpkg,
        OUTPUT_POINTS_LAYER,
        f"{len(points):,}",
    )
    points.to_file(output_gpkg, layer=OUTPUT_POINTS_LAYER, driver="GPKG", index=False)

    if write_per_quadrant_layers:
        LOGGER.info("Exportando capas individuales por cuadrante.")
        for (id_zona, id_cuadrante), quadrant_points in points.groupby(
            ["id_zona", "id_cuadrante"],
            dropna=False,
        ):
            layer_name = layer_name_for_quadrant(id_zona, id_cuadrante)
            quadrant_points.to_file(output_gpkg, layer=layer_name, driver="GPKG", index=False)

    LOGGER.info("Exportando CSV resumen: %s", summary_csv)
    summary.to_csv(summary_csv, index=False, encoding="utf-8")

    write_table_to_gpkg(
        summary,
        output_gpkg,
        OUTPUT_SUMMARY_TABLE,
        "Resumen de puntos extraídos por zona y cuadrante piloto.",
    )
    write_table_to_gpkg(
        metadata,
        output_gpkg,
        OUTPUT_METADATA_TABLE,
        "Metadatos de ejecución de la extracción de cuadrantes piloto.",
    )


def build_metadata(
    points_gpkg: Path,
    quadrants_gpkg: Path,
    output_gpkg: Path,
    predicate: str,
    quadrants_count: int,
    bbox_candidate_count: int,
    extracted_count: int,
    write_per_quadrant_layers: bool,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "points_gpkg": str(points_gpkg),
                "points_layer": POINTS_LAYER,
                "homologation_table": HOMOLOGATION_TABLE,
                "score_table": SCORE_TABLE,
                "quadrants_gpkg": str(quadrants_gpkg),
                "quadrants_layer": QUADRANTS_LAYER,
                "output_gpkg": str(output_gpkg),
                "spatial_predicate": predicate,
                "quadrants_count": quadrants_count,
                "bbox_candidate_points": bbox_candidate_count,
                "extracted_points": extracted_count,
                "write_per_quadrant_layers": write_per_quadrant_layers,
            }
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract A2.1 XY points that fall inside pilot quadrants."
    )
    parser.add_argument("--points-gpkg", default=str(DEFAULT_POINTS_GPKG))
    parser.add_argument("--quadrants-gpkg", default=str(DEFAULT_QUADRANTS_GPKG))
    parser.add_argument("--output-gpkg", default=str(DEFAULT_OUTPUT_GPKG))
    parser.add_argument("--summary-csv", default=str(DEFAULT_SUMMARY_CSV))
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument(
        "--predicate",
        default="within",
        choices=["within", "intersects", "covered_by"],
        help="Spatial predicate used to assign points to quadrants.",
    )
    parser.add_argument(
        "--no-per-quadrant-layers",
        action="store_true",
        help="Only write the combined layer and summary table.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    points_gpkg = resolve_path(args.points_gpkg)
    quadrants_gpkg = resolve_path(args.quadrants_gpkg)
    output_gpkg = resolve_path(args.output_gpkg)
    summary_csv = resolve_path(args.summary_csv)
    log_path = resolve_path(args.log_path)
    write_per_quadrant_layers = not args.no_per_quadrant_layers

    configure_logger(log_path)

    require_path(points_gpkg, "GeoPackage de puntos A2.1")
    require_path(quadrants_gpkg, "GeoPackage de cuadrantes piloto")

    LOGGER.info("Iniciando extracción de puntos por cuadrantes piloto.")
    LOGGER.info("Ambiente Python: %s", sys.prefix)

    quadrants = read_quadrants(quadrants_gpkg, QUADRANTS_LAYER)
    points = read_points_in_quadrants_bbox(points_gpkg, POINTS_LAYER, quadrants)
    assigned = assign_quadrants(points, quadrants, args.predicate)

    homologation = read_attribute_table(points_gpkg, HOMOLOGATION_TABLE, HOMOLOGATION_FIELDS)
    scores = read_attribute_table(points_gpkg, SCORE_TABLE, SCORE_FIELDS)
    enriched = enrich_points(assigned, homologation, scores)

    summary = build_quadrant_summary(enriched, quadrants)
    metadata = build_metadata(
        points_gpkg=points_gpkg,
        quadrants_gpkg=quadrants_gpkg,
        output_gpkg=output_gpkg,
        predicate=args.predicate,
        quadrants_count=len(quadrants),
        bbox_candidate_count=len(points),
        extracted_count=len(enriched),
        write_per_quadrant_layers=write_per_quadrant_layers,
    )

    write_outputs(
        points=enriched,
        summary=summary,
        output_gpkg=output_gpkg,
        summary_csv=summary_csv,
        metadata=metadata,
        write_per_quadrant_layers=write_per_quadrant_layers,
    )

    LOGGER.info("Extracción finalizada.")
    LOGGER.info("GeoPackage: %s", output_gpkg)
    LOGGER.info("Resumen CSV: %s", summary_csv)
    LOGGER.info("Log: %s", log_path)


if __name__ == "__main__":
    main()
