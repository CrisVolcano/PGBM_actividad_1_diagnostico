# -*- coding: utf-8 -*-
"""
Actividad 4.4 — Normalización de predictores extraídos en puntos piloto
=======================================================================

Este script toma los CSV exportados desde Google Earth Engine en A4.2 y los
integra a la base de cuadrantes/puntos A4 sin desnormalizar las tablas base.

Entrada principal:
    - GeoPackage A4 con pilot_xy_point, xy_pilot_quadrant, xy_score, xy_accion
      y xy_homologacion_final; si la salida existente aún no contiene esta
      última tabla, se reconstruye desde xy_pilot_point_source y las fuentes.
    - predictor_catalog.csv generado por A4.2.
    - Carpeta local con los CSV descargados desde Drive.

Salida principal:
    - GeoPackage A4.4 con:
        pilot_xy_point          # capa espacial copiada desde A4
        xy_pilot_quadrant       # tabla A4 copiada como relación separada
        xy_score                # tabla A4 copiada como relación separada
        xy_accion               # tabla A4 copiada como relación separada
        xy_homologacion_final   # objetivos y etiquetas homologadas
        predictor_source        # catálogo de assets/predictores
        predictor_band          # catálogo de bandas y tabla destino
        xy_pred_<predictor_id>  # una tabla por predictor, 1 fila por xy_group_id
        pilot_model_matrix      # tabla derivada opcional para modelado

Decisión de diseño:
    - No se usa una única tabla EAV gigante xy_predictor_value.
    - Los valores se separan por predictor/asset para mantener tablas manejables.
    - Las tablas base A4 se preservan separadas; xy_accion no se mezcla dentro de
      las tablas de predictores.
    - La homologación faltante en una salida A4.1 previa se lee desde la fuente
      propia de cada punto; no exige repetir A4.1 ni volver a exportar en GEE.
    - Si Earth Engine omite pocos puntos por píxeles enmascarados, se conserva
      su xy_group_id y las bandas del predictor se materializan como NULL.
    - pilot_model_matrix es derivada para modelado, no reemplaza la normalización.

Ejecución desde la raíz del repositorio:
    python src/actividad_4/4_4_normalize_point_predictor_exports.py
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

LOGGER = logging.getLogger("a4_4_predictor_normalization_by_predictor")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_4_normalize_point_predictor_exports.yaml"


@dataclass(frozen=True)
class ExportFileInfo:
    path: Path
    filename: str
    predictor_id: str
    batch_id: int | None


def configure_logger(output_dir: Path) -> None:
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "normalize_point_predictor_exports.log"

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


def table_columns(gpkg_path: Path, table_name: str) -> list[str]:
    with sqlite3.connect(gpkg_path) as connection:
        rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    if not rows:
        raise ValueError(f"No existe la tabla/capa '{table_name}' en {gpkg_path}")
    return [row[1] for row in rows]


def table_exists(gpkg_path: Path, table_name: str) -> bool:
    with sqlite3.connect(gpkg_path) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type IN ('table', 'view') AND name = ?
            LIMIT 1
            """,
            (table_name,),
        ).fetchone()
    return row is not None


def require_fields(columns: list[str], fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in columns]
    if missing:
        raise ValueError(f"Faltan campos en {label}: {missing}")


def read_attribute_table(gpkg_path: Path, table_name: str, fields: list[str]) -> pd.DataFrame:
    columns = table_columns(gpkg_path, table_name)
    require_fields(columns, fields, table_name)
    quoted = ", ".join(f'"{field}"' for field in fields)
    with sqlite3.connect(gpkg_path) as connection:
        return pd.read_sql_query(f'SELECT {quoted} FROM "{table_name}"', connection)


def validate_unique(dataframe: pd.DataFrame, key_fields: str | list[str], label: str) -> None:
    if isinstance(key_fields, str):
        key_fields = [key_fields]
    duplicated = int(dataframe.duplicated(subset=key_fields).sum())
    if duplicated:
        raise ValueError(f"{label} tiene {duplicated:,} filas duplicadas para {key_fields}.")


def sanitize_identifier(value: str, prefix_if_needed: str = "t_") -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^0-9a-zA-Z_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise ValueError(f"No se pudo construir un identificador SQL válido desde: {value!r}")
    if re.match(r"^[0-9]", text):
        text = prefix_if_needed + text
    return text


def register_attribute_table(connection: sqlite3.Connection, table_name: str, description: str) -> None:
    """Register a non-spatial table inside an already valid GeoPackage."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    connection.execute(
        """
        INSERT OR REPLACE INTO gpkg_contents
            (table_name, data_type, identifier, description, last_change, srs_id)
        VALUES (?, 'attributes', ?, ?, ?, NULL)
        """,
        (table_name, table_name, description, now),
    )


def write_attribute_table(
    connection: sqlite3.Connection,
    dataframe: pd.DataFrame,
    table_name: str,
    description: str,
) -> None:
    LOGGER.info("Escribiendo tabla: %s | filas=%s", table_name, f"{len(dataframe):,}")
    dataframe.to_sql(table_name, connection, if_exists="replace", index=False)
    register_attribute_table(connection, table_name, description)


def create_index(connection: sqlite3.Connection, statement: str) -> None:
    try:
        connection.execute(statement)
    except sqlite3.OperationalError as error:
        LOGGER.warning("No se pudo crear índice: %s | error=%s", statement, error)


def create_common_indexes(connection: sqlite3.Connection, config: dict[str, Any], predictor_tables: dict[str, str]) -> None:
    key = config["fields"]["key"]
    inputs = config["inputs"]

    statements = [
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_pilot_xy_point_key ON "{inputs["pilot_points_layer"]}" ("{key}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_xy_pilot_quadrant_key ON "{inputs["assignment_table"]}" ("{key}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_xy_score_key ON "{inputs["score_table"]}" ("{key}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_xy_accion_key ON "{inputs["action_table"]}" ("{key}")',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_xy_homologacion_final_key ON "{inputs["homologation_table"]}" ("{key}")',
        'CREATE UNIQUE INDEX IF NOT EXISTS ux_predictor_source_id ON predictor_source (predictor_id)',
        'CREATE UNIQUE INDEX IF NOT EXISTS ux_predictor_band_id ON predictor_band (predictor_band_id)',
        'CREATE INDEX IF NOT EXISTS idx_predictor_band_predictor ON predictor_band (predictor_id)',
        'CREATE INDEX IF NOT EXISTS idx_predictor_band_table ON predictor_band (predictor_table)',
        f'CREATE UNIQUE INDEX IF NOT EXISTS ux_pilot_model_matrix_key ON pilot_model_matrix ("{key}")',
    ]

    for table_name in predictor_tables.values():
        statements.append(f'CREATE UNIQUE INDEX IF NOT EXISTS ux_{table_name}_{key} ON "{table_name}" ("{key}")')

    for statement in statements:
        create_index(connection, statement)


def normalize_key_column(dataframe: pd.DataFrame, key: str, key_as_text: bool) -> pd.DataFrame:
    out = dataframe.copy()
    if key_as_text and key in out.columns:
        out[key] = out[key].astype("string").str.strip()
    return out


def validate_homologation(
    dataframe: pd.DataFrame,
    fields: list[str],
    key: str,
    label: str,
) -> None:
    validate_unique(dataframe, key, label)

    null_counts = dataframe[fields].isna().sum()
    incomplete = {
        field: int(count)
        for field, count in null_counts.items()
        if int(count) > 0
    }
    if incomplete:
        raise ValueError(f"{label} contiene campos nulos: {incomplete}")

    id_label_pairs = [
        ("id_0_propuesta", "nivel_0_propuesta"),
        ("id_1_propuesta", "nivel_1_propuesta"),
    ]
    for id_field, label_field in id_label_pairs:
        if id_field not in dataframe.columns or label_field not in dataframe.columns:
            continue
        labels_per_id = dataframe.groupby(id_field, dropna=False)[label_field].nunique(dropna=False)
        ids_per_label = dataframe.groupby(label_field, dropna=False)[id_field].nunique(dropna=False)
        if bool((labels_per_id > 1).any()) or bool((ids_per_label > 1).any()):
            raise ValueError(
                f"{label} no tiene una correspondencia unívoca entre "
                f"{id_field} y {label_field}."
            )


def build_homologation_from_point_provenance(
    config: dict[str, Any],
    pilot_gpkg: Path,
    base_keys: set[str],
    homologation_fields: list[str],
) -> pd.DataFrame:
    """Reconstruye la homologación sin repetir A4.1 ni modificar las fuentes."""
    inputs = config["inputs"]
    fields = config["fields"]
    key = fields["key"]
    key_as_text = bool(config.get("validation", {}).get("key_as_text", True))
    point_source_table = inputs["point_source_table"]
    point_source_fields = list(fields.get("point_source_fields", []))
    required_provenance = [key, "point_source_key", "point_source_gpkg"]
    for field in required_provenance:
        if field not in point_source_fields:
            point_source_fields.append(field)

    provenance = read_attribute_table(
        pilot_gpkg,
        point_source_table,
        point_source_fields,
    )
    provenance = normalize_key_column(provenance, key, key_as_text)
    validate_unique(provenance, key, point_source_table)

    provenance_nulls = provenance[required_provenance].isna().sum()
    incomplete_provenance = {
        field: int(count)
        for field, count in provenance_nulls.items()
        if int(count) > 0
    }
    if incomplete_provenance:
        raise ValueError(
            f"{point_source_table} contiene campos nulos: {incomplete_provenance}"
        )

    provenance_keys = set(provenance[key].astype(str))
    if provenance_keys != base_keys:
        raise ValueError(
            f"{point_source_table} no tiene el mismo universo de puntos que "
            f"{inputs['pilot_points_layer']}: faltan={len(base_keys - provenance_keys):,}, "
            f"sobran={len(provenance_keys - base_keys):,}."
        )

    parts: list[pd.DataFrame] = []
    group_fields = ["point_source_key", "point_source_gpkg"]
    for (source_key, source_gpkg_value), source_rows in provenance.groupby(
        group_fields,
        sort=True,
        dropna=False,
    ):
        source_gpkg = resolve_path(str(source_gpkg_value).strip())
        if not source_gpkg.exists():
            raise FileNotFoundError(
                f"No existe el GPKG de la fuente {source_key}: {source_gpkg}"
            )

        source_homologation = read_attribute_table(
            source_gpkg,
            inputs["homologation_table"],
            homologation_fields,
        )
        source_homologation = normalize_key_column(
            source_homologation,
            key,
            key_as_text,
        )
        validate_unique(
            source_homologation,
            key,
            f"{inputs['homologation_table']} de {source_key}",
        )

        requested_keys = set(source_rows[key].astype(str))
        selected = source_homologation[
            source_homologation[key].astype(str).isin(requested_keys)
        ].copy()
        selected_keys = set(selected[key].astype(str))
        missing = requested_keys - selected_keys
        if missing:
            raise ValueError(
                f"{inputs['homologation_table']} de {source_key} no contiene "
                f"{len(missing):,} puntos requeridos. Ejemplos: {sorted(missing)[:5]}"
            )

        LOGGER.info(
            "Homologación recuperada desde %s: %s puntos",
            source_key,
            f"{len(selected):,}",
        )
        parts.append(selected[homologation_fields])

    if not parts:
        raise ValueError(
            f"{point_source_table} no contiene fuentes para reconstruir la homologación."
        )

    homologation = pd.concat(parts, ignore_index=True)
    validate_homologation(
        homologation,
        homologation_fields,
        key,
        "Homologación reconstruida desde la trazabilidad A4.1",
    )
    homologation_keys = set(homologation[key].astype(str))
    if homologation_keys != base_keys:
        raise ValueError(
            "La homologación reconstruida no cubre exactamente los puntos piloto: "
            f"faltan={len(base_keys - homologation_keys):,}, "
            f"sobran={len(homologation_keys - base_keys):,}."
        )

    LOGGER.info(
        "Homologación reconstruida desde xy_pilot_point_source: %s puntos",
        f"{len(homologation):,}",
    )
    return homologation


def load_predictor_catalog(path: Path, separator: str, table_prefix: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"No existe predictor_catalog.csv: {path}")

    catalog = pd.read_csv(path, encoding="utf-8-sig")
    required = [
        "predictor_id",
        "asset",
        "project",
        "type",
        "period",
        "resolution_m",
        "scale_m",
        "rescale",
        "band_original",
        "band_output",
        "description",
    ]
    missing = [field for field in required if field not in catalog.columns]
    if missing:
        raise ValueError(f"Faltan columnas en predictor_catalog.csv: {missing}")

    catalog = catalog[required].copy()
    catalog["predictor_id"] = catalog["predictor_id"].astype(str).str.strip()
    catalog["band_output"] = catalog["band_output"].astype(str).str.strip()
    catalog["predictor_band_id"] = catalog["predictor_id"] + separator + catalog["band_output"]
    catalog["band_order"] = catalog.groupby("predictor_id", sort=False).cumcount() + 1

    predictor_tables = {
        predictor_id: table_prefix + sanitize_identifier(predictor_id)
        for predictor_id in sorted(catalog["predictor_id"].unique())
    }
    catalog["predictor_table"] = catalog["predictor_id"].map(predictor_tables)
    catalog["band_column"] = catalog["band_output"].map(lambda value: sanitize_identifier(value, prefix_if_needed="b_"))

    # Mantener columnas de salida únicas globalmente facilita pilot_model_matrix.
    duplicated_band_columns = catalog["band_column"].duplicated().sum()
    if duplicated_band_columns:
        duplicates = sorted(catalog.loc[catalog["band_column"].duplicated(), "band_column"].unique())[:10]
        raise ValueError(
            "Hay nombres de columna de banda duplicados después de normalizar. "
            f"Ejemplos: {duplicates}. Renombrá band_output con prefijos únicos."
        )

    predictor_source = (
        catalog[
            [
                "predictor_id",
                "predictor_table",
                "asset",
                "project",
                "type",
                "period",
                "resolution_m",
                "scale_m",
                "rescale",
                "description",
            ]
        ]
        .drop_duplicates(subset=["predictor_id"])
        .sort_values("predictor_id")
        .reset_index(drop=True)
    )
    validate_unique(predictor_source, "predictor_id", "predictor_source")
    validate_unique(predictor_source, "predictor_table", "predictor_source")

    predictor_band = catalog[
        [
            "predictor_band_id",
            "predictor_id",
            "predictor_table",
            "band_original",
            "band_output",
            "band_column",
            "band_order",
            "resolution_m",
            "scale_m",
        ]
    ].copy()
    predictor_band = predictor_band.sort_values(["predictor_id", "band_order"]).reset_index(drop=True)
    validate_unique(predictor_band, "predictor_band_id", "predictor_band")

    LOGGER.info(
        "Catálogo cargado: %s predictores | %s bandas",
        f"{len(predictor_source):,}",
        f"{len(predictor_band):,}",
    )
    return predictor_source, predictor_band, predictor_tables


def read_a4_base_tables(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    paths = config["paths"]
    inputs = config["inputs"]
    fields = config["fields"]
    key = fields["key"]
    quadrant = fields["quadrant"]
    key_as_text = bool(config.get("validation", {}).get("key_as_text", True))

    pilot_gpkg = resolve_path(paths["pilot_gpkg"])
    if not pilot_gpkg.exists():
        raise FileNotFoundError(f"No existe GPKG A4: {pilot_gpkg}")

    point_fields = list(fields.get("pilot_point_fields", []))
    if key not in point_fields:
        point_fields.insert(0, key)

    pilot_xy_point_attrs = read_attribute_table(pilot_gpkg, inputs["pilot_points_layer"], point_fields)
    pilot_xy_point_attrs = normalize_key_column(
        pilot_xy_point_attrs,
        key,
        key_as_text,
    )
    validate_unique(pilot_xy_point_attrs, key, inputs["pilot_points_layer"])
    if bool(pilot_xy_point_attrs[key].isna().any()):
        raise ValueError(f"{inputs['pilot_points_layer']} contiene {key} nulos.")
    base_keys = set(pilot_xy_point_attrs[key].astype(str))

    xy_pilot_quadrant = read_attribute_table(pilot_gpkg, inputs["assignment_table"], [key, quadrant])

    score_fields = list(fields.get("score_fields", []))
    if key not in score_fields:
        score_fields.insert(0, key)
    xy_score = read_attribute_table(pilot_gpkg, inputs["score_table"], score_fields)

    action_fields = list(fields.get("action_fields", []))
    if key not in action_fields:
        action_fields.insert(0, key)
    xy_accion = read_attribute_table(pilot_gpkg, inputs["action_table"], action_fields)

    homologation_fields = list(fields.get("homologation_fields", []))
    if key not in homologation_fields:
        homologation_fields.insert(0, key)
    if table_exists(pilot_gpkg, inputs["homologation_table"]):
        xy_homologacion_final = read_attribute_table(
            pilot_gpkg,
            inputs["homologation_table"],
            homologation_fields,
        )
        xy_homologacion_final = normalize_key_column(
            xy_homologacion_final,
            key,
            key_as_text,
        )
        LOGGER.info(
            "Usando %s incluida en el GPKG A4.1.",
            inputs["homologation_table"],
        )
    elif bool(
        config.get("validation", {}).get(
            "build_homologation_from_point_provenance_if_missing",
            False,
        )
    ):
        LOGGER.info(
            "%s no está en el GPKG A4.1; se reconstruirá desde %s sin repetir A4.1.",
            inputs["homologation_table"],
            inputs["point_source_table"],
        )
        xy_homologacion_final = build_homologation_from_point_provenance(
            config,
            pilot_gpkg,
            base_keys,
            homologation_fields,
        )
    else:
        raise ValueError(
            f"No existe {inputs['homologation_table']} en {pilot_gpkg} y está "
            "desactivada su reconstrucción desde la trazabilidad A4.1."
        )

    validate_homologation(
        xy_homologacion_final,
        homologation_fields,
        key,
        inputs["homologation_table"],
    )

    tables = {
        inputs["pilot_points_layer"]: pilot_xy_point_attrs,
        inputs["assignment_table"]: normalize_key_column(xy_pilot_quadrant, key, key_as_text),
        inputs["score_table"]: normalize_key_column(xy_score, key, key_as_text),
        inputs["action_table"]: normalize_key_column(xy_accion, key, key_as_text),
        inputs["homologation_table"]: normalize_key_column(
            xy_homologacion_final,
            key,
            key_as_text,
        ),
    }

    for name, dataframe in tables.items():
        validate_unique(dataframe, key, name)

    for name in [
        inputs["assignment_table"],
        inputs["score_table"],
        inputs["action_table"],
        inputs["homologation_table"],
    ]:
        current_keys = set(tables[name][key].astype(str))
        if current_keys != base_keys:
            raise ValueError(
                f"{name} no tiene el mismo universo de xy_group_id que {inputs['pilot_points_layer']}: "
                f"faltan={len(base_keys - current_keys):,}, sobran={len(current_keys - base_keys):,}."
            )

    LOGGER.info("Tablas base A4 leídas: %s puntos", f"{len(base_keys):,}")
    return tables


def copy_pilot_point_layer(config: dict[str, Any], output_gpkg: Path, expected_keys: set[str]) -> None:
    paths = config["paths"]
    inputs = config["inputs"]
    fields = config["fields"]
    key = fields["key"]
    key_as_text = bool(config.get("validation", {}).get("key_as_text", True))
    pilot_gpkg = resolve_path(paths["pilot_gpkg"])
    layer_name = inputs["pilot_points_layer"]

    point_fields = list(fields.get("pilot_point_fields", []))
    if key not in point_fields:
        point_fields.insert(0, key)

    pilot_points = gpd.read_file(pilot_gpkg, layer=layer_name)
    require_fields(list(pilot_points.columns), point_fields + [pilot_points.geometry.name], layer_name)
    pilot_points = pilot_points[point_fields + [pilot_points.geometry.name]].copy()
    if key_as_text:
        pilot_points[key] = pilot_points[key].astype("string").str.strip()

    validate_unique(pilot_points, key, layer_name)
    actual_keys = set(pilot_points[key].astype(str))
    if actual_keys != expected_keys:
        raise ValueError(
            f"El universo espacial {layer_name} no coincide con las tablas A4: "
            f"faltan={len(expected_keys - actual_keys):,}, sobran={len(actual_keys - expected_keys):,}."
        )
    if pilot_points.geometry.isna().any() or pilot_points.geometry.is_empty.any():
        raise ValueError(f"{layer_name} contiene geometrías nulas o vacías.")

    LOGGER.info("Escribiendo capa espacial base: %s | puntos=%s", layer_name, f"{len(pilot_points):,}")
    pilot_points.to_file(output_gpkg, layer=layer_name, driver="GPKG", index=False)


def discover_export_files(config: dict[str, Any], predictor_ids: set[str]) -> list[ExportFileInfo]:
    csv_cfg = config["csv_import"]
    exports_dir = resolve_path(config["paths"]["drive_exports_dir"])
    if not exports_dir.exists():
        raise FileNotFoundError(f"No existe la carpeta local de CSV descargados: {exports_dir}")

    glob_pattern = csv_cfg.get("glob", "*.csv")
    recursive = bool(csv_cfg.get("recursive", True))
    regex = re.compile(csv_cfg.get("filename_regex", r"^a4_2_(?P<predictor_id>.+)_batch_(?P<batch_id>\d+)\.csv$"))
    iterator = exports_dir.rglob(glob_pattern) if recursive else exports_dir.glob(glob_pattern)

    files: list[ExportFileInfo] = []
    for path in sorted(iterator):
        if not path.is_file():
            continue
        match = regex.match(path.name)
        if not match:
            if bool(csv_cfg.get("ignore_unmatched_files", True)):
                LOGGER.warning("CSV ignorado porque no calza con filename_regex: %s", path.name)
                continue
            raise ValueError(f"El CSV no calza con filename_regex: {path.name}")

        predictor_id = str(match.group("predictor_id")).strip()
        batch_text = match.groupdict().get("batch_id")
        batch_id = int(batch_text) if batch_text is not None else None
        if predictor_id not in predictor_ids:
            raise ValueError(
                f"El archivo {path.name} tiene predictor_id='{predictor_id}', "
                "pero no existe en predictor_catalog.csv."
            )
        files.append(ExportFileInfo(path=path, filename=path.name, predictor_id=predictor_id, batch_id=batch_id))

    if not files:
        raise ValueError(f"No se encontraron CSV de exportación en: {exports_dir}")

    LOGGER.info("CSV de Drive detectados: %s", f"{len(files):,}")
    return files


def build_predictor_tables(
    config: dict[str, Any],
    files: list[ExportFileInfo],
    predictor_band: pd.DataFrame,
    predictor_tables: dict[str, str],
    base_keys: set[str],
) -> dict[str, pd.DataFrame]:
    key = config["fields"]["key"]
    csv_cfg = config["csv_import"]
    encoding = csv_cfg.get("encoding", "utf-8-sig")
    ignore_columns = set(csv_cfg.get("ignore_columns", ["system:index", ".geo", "geo", "id_cuadrante"]))
    export_properties = set(config["fields"].get("export_properties", []))
    require_complete = bool(config.get("validation", {}).get("require_complete_point_universe", True))

    band_meta_by_predictor = {
        predictor_id: group.sort_values("band_order").copy()
        for predictor_id, group in predictor_band.groupby("predictor_id", sort=False)
    }
    files_by_predictor: dict[str, list[ExportFileInfo]] = {predictor_id: [] for predictor_id in predictor_tables}
    for info in files:
        files_by_predictor[info.predictor_id].append(info)

    missing_predictors = [pid for pid, items in files_by_predictor.items() if not items]
    if missing_predictors and require_complete:
        raise ValueError(
            "No hay CSV para estos predictores del catálogo: "
            + ", ".join(sorted(missing_predictors))
        )

    out_tables: dict[str, pd.DataFrame] = {}

    for predictor_id in sorted(files_by_predictor):
        info_list = files_by_predictor[predictor_id]
        if not info_list:
            continue

        band_meta = band_meta_by_predictor[predictor_id]
        band_output_to_column = dict(zip(band_meta["band_output"], band_meta["band_column"]))
        expected_band_outputs = list(band_output_to_column)
        parts: list[pd.DataFrame] = []

        for info in sorted(info_list, key=lambda item: (-1 if item.batch_id is None else item.batch_id, item.filename)):
            dataframe = pd.read_csv(info.path, encoding=encoding)
            dataframe.columns = [str(col).strip() for col in dataframe.columns]
            if key not in dataframe.columns:
                raise ValueError(f"{info.filename} no contiene la llave {key}.")

            dataframe[key] = dataframe[key].astype("string").str.strip()
            missing_band_columns = [band for band in expected_band_outputs if band not in dataframe.columns]
            if missing_band_columns:
                raise ValueError(
                    f"{info.filename} no contiene bandas esperadas para {predictor_id}: "
                    f"{missing_band_columns}"
                )

            unexpected = [
                col
                for col in dataframe.columns
                if col not in expected_band_outputs
                and col not in ignore_columns
                and col != key
                and col not in export_properties
            ]
            if unexpected:
                LOGGER.warning(
                    "%s tiene columnas no esperadas que serán ignoradas: %s",
                    info.filename,
                    unexpected,
                )

            unknown_keys = sorted(set(dataframe[key].astype(str)) - base_keys)[:10]
            if unknown_keys:
                raise ValueError(
                    f"{info.filename} contiene xy_group_id que no existen en pilot_xy_point. "
                    f"Ejemplos: {unknown_keys}"
                )

            duplicated_keys = int(dataframe[key].duplicated().sum())
            if duplicated_keys:
                raise ValueError(f"{info.filename} tiene {duplicated_keys:,} xy_group_id duplicados.")

            part = dataframe[[key] + expected_band_outputs].copy()
            part = part.rename(columns=band_output_to_column)
            for col in band_output_to_column.values():
                part[col] = pd.to_numeric(part[col], errors="coerce")
            parts.append(part)

            LOGGER.info(
                "Leído CSV: %s | predictor=%s | filas=%s | bandas=%s",
                info.filename,
                predictor_id,
                f"{len(part):,}",
                f"{len(expected_band_outputs):,}",
            )

        predictor_table = pd.concat(parts, ignore_index=True)
        duplicated = int(predictor_table[key].duplicated().sum())
        if duplicated:
            raise ValueError(
                f"Los CSV del predictor {predictor_id} producen {duplicated:,} xy_group_id duplicados. "
                "Probablemente mezclaste corridas o batches superpuestos."
            )

        current_keys = set(predictor_table[key].astype(str))
        missing_keys = base_keys - current_keys
        extra_keys = current_keys - base_keys
        if extra_keys:
            raise ValueError(
                f"El predictor {predictor_id} contiene {len(extra_keys):,} llaves "
                "que no existen en el universo A4. "
                f"Ejemplos: {sorted(extra_keys)[:5]}"
            )

        validation_cfg = config.get("validation", {})
        materialize_nulls = bool(
            validation_cfg.get("materialize_missing_predictor_rows_as_null", False)
        )
        max_missing_pct = float(
            validation_cfg.get("max_missing_point_rows_pct_to_materialize", 0.0)
        )
        if not 0.0 <= max_missing_pct <= 100.0:
            raise ValueError(
                "validation.max_missing_point_rows_pct_to_materialize debe estar "
                "entre 0 y 100."
            )

        if missing_keys and materialize_nulls:
            missing_pct = 100.0 * len(missing_keys) / len(base_keys) if base_keys else 0.0
            if missing_pct > max_missing_pct:
                raise ValueError(
                    f"El predictor {predictor_id} omite {len(missing_keys):,} puntos "
                    f"({missing_pct:.6f}%), por encima del máximo permitido de "
                    f"{max_missing_pct:.6f}% para materializarlos como NULL. "
                    "Revise si falta un batch de exportación."
                )

            null_rows = pd.DataFrame(
                {key: pd.Series(sorted(missing_keys), dtype="string")}
            )
            for band_column in band_output_to_column.values():
                null_rows[band_column] = float("nan")
            predictor_table = pd.concat(
                [predictor_table, null_rows],
                ignore_index=True,
            )
            LOGGER.warning(
                "Predictor %s: %s puntos sin píxel válido (%.6f%%); "
                "se conservaron con bandas NULL.",
                predictor_id,
                f"{len(missing_keys):,}",
                missing_pct,
            )

        final_keys = set(predictor_table[key].astype(str))
        final_missing = base_keys - final_keys
        if require_complete and final_missing:
            raise ValueError(
                f"El predictor {predictor_id} no conserva el universo exacto de puntos A4: "
                f"esperados={len(base_keys):,}, observados={len(final_keys):,}, "
                f"faltan={len(final_missing):,}, sobran=0. "
                f"Ejemplos faltantes: {sorted(final_missing)[:5]}"
            )

        predictor_table = predictor_table.sort_values(key).reset_index(drop=True)
        out_tables[predictor_id] = predictor_table

    return out_tables


def build_model_matrix(
    a4_tables: dict[str, pd.DataFrame],
    predictor_value_tables: dict[str, pd.DataFrame],
    config: dict[str, Any],
) -> pd.DataFrame:
    inputs = config["inputs"]
    key = config["fields"]["key"]
    matrix = a4_tables[inputs["pilot_points_layer"]].copy()

    for table_name in [
        inputs["assignment_table"],
        inputs["score_table"],
        inputs["action_table"],
        inputs["homologation_table"],
    ]:
        matrix = matrix.merge(a4_tables[table_name], on=key, how="left", validate="one_to_one")

    for predictor_id in sorted(predictor_value_tables):
        matrix = matrix.merge(predictor_value_tables[predictor_id], on=key, how="left", validate="one_to_one")

    validate_unique(matrix, key, "pilot_model_matrix")
    return matrix


def write_outputs(config: dict[str, Any]) -> None:
    paths = config["paths"]
    inputs = config["inputs"]
    outputs = config["outputs"]
    validation = config.get("validation", {})
    key = config["fields"]["key"]

    output_dir = resolve_path(paths["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    output_gpkg = resolve_path(paths["output_gpkg"])
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    if output_gpkg.exists() and bool(outputs.get("overwrite_output_gpkg", True)):
        LOGGER.info("Eliminando GPKG previo: %s", output_gpkg)
        output_gpkg.unlink()

    separator = outputs.get("predictor_name_separator", "::")
    table_prefix = outputs.get("predictor_table_prefix", "xy_pred_")

    predictor_catalog_csv = resolve_path(paths["predictor_catalog_csv"])
    predictor_source, predictor_band, predictor_tables = load_predictor_catalog(
        predictor_catalog_csv,
        separator=separator,
        table_prefix=table_prefix,
    )

    a4_tables = read_a4_base_tables(config)
    base_keys = set(a4_tables[inputs["pilot_points_layer"]][key].astype(str))
    files = discover_export_files(config, set(predictor_source["predictor_id"]))
    predictor_value_tables = build_predictor_tables(
        config=config,
        files=files,
        predictor_band=predictor_band,
        predictor_tables=predictor_tables,
        base_keys=base_keys,
    )

    # Crear GPKG válido con la capa espacial base. Luego se agregan tablas no espaciales.
    copy_pilot_point_layer(config, output_gpkg, expected_keys=base_keys)

    with sqlite3.connect(output_gpkg) as connection:
        write_attribute_table(
            connection,
            a4_tables[inputs["assignment_table"]],
            inputs["assignment_table"],
            "Relación A4 entre puntos XY y cuadrantes piloto.",
        )
        write_attribute_table(
            connection,
            a4_tables[inputs["score_table"]],
            inputs["score_table"],
            "Tabla A4 de score filtrada al universo piloto.",
        )
        write_attribute_table(
            connection,
            a4_tables[inputs["action_table"]],
            inputs["action_table"],
            "Tabla A4 de acción/uso filtrada al universo piloto.",
        )
        write_attribute_table(
            connection,
            a4_tables[inputs["homologation_table"]],
            inputs["homologation_table"],
            "Clases homologadas finales del universo piloto.",
        )
        write_attribute_table(
            connection,
            predictor_source,
            "predictor_source",
            "Catálogo de predictores/assets usados en la extracción A4.2.",
        )
        write_attribute_table(
            connection,
            predictor_band,
            "predictor_band",
            "Catálogo de bandas por predictor y tabla destino.",
        )

        for predictor_id in sorted(predictor_value_tables):
            table_name = predictor_tables[predictor_id]
            write_attribute_table(
                connection,
                predictor_value_tables[predictor_id],
                table_name,
                f"Valores extraídos para el predictor {predictor_id}; una fila por xy_group_id.",
            )

        if bool(outputs.get("write_wide_model_matrix", True)):
            matrix = build_model_matrix(a4_tables, predictor_value_tables, config)
            csv_path = output_dir / outputs.get("model_matrix_csv", "pilot_model_matrix.csv")
            matrix.to_csv(csv_path, index=False, encoding="utf-8-sig")
            LOGGER.info(
                "Matriz de modelado escrita: %s | filas=%s | columnas=%s",
                csv_path,
                f"{len(matrix):,}",
                f"{len(matrix.columns):,}",
            )

            if bool(outputs.get("write_model_matrix_to_gpkg", True)):
                write_attribute_table(
                    connection,
                    matrix,
                    "pilot_model_matrix",
                    "Matriz ancha derivada para modelado; no reemplaza las tablas normalizadas.",
                )

        create_common_indexes(connection, config, predictor_tables)

    LOGGER.info("Normalización de predictores finalizada.")
    LOGGER.info("GeoPackage A4.4: %s", output_gpkg)


def main() -> None:
    config = read_yaml(DEFAULT_CONFIG)
    output_dir = resolve_path(config["paths"]["output_dir"])
    configure_logger(output_dir)
    LOGGER.info("YAML de configuración: %s", DEFAULT_CONFIG)
    write_outputs(config)


if __name__ == "__main__":
    main()
