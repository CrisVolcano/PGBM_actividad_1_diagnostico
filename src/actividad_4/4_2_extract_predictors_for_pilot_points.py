# -*- coding: utf-8 -*-
"""
Actividad 4.2 — Extracción de predictores para puntos piloto A4
===============================================================

Este script lee la base normalizada de cuadrantes piloto generada por A4 y
lanza directamente la extracción de predictores en Google Earth Engine para
esos puntos únicamente.

No usa --config ni --mode por consola. El YAML fijo del proyecto define rutas,
capas, campos, registro de predictores y parámetros de Earth Engine.
La ejecución siempre envía todos los predictores válidos y todos los lotes.

Ejecución desde la raíz del repositorio:

    python src/actividad_4/4_2_extract_predictors_for_pilot_points.py

Resultado principal:
    - tareas Export.table.toDrive() en Google Earth Engine;
    - CSV exportados a la carpeta de Google Drive configurada;
    - manifiesto local de tareas para control y trazabilidad.

El script no genera matriz de modelado ni une CSV descargados. Esa unión puede
hacerse después en otro paso si se necesita.
"""

from __future__ import annotations

import ast
import json
import logging
import math
import os
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import yaml

LOGGER = logging.getLogger("a4_2_predictor_extraction")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_2_predictor_extraction.yaml"


@dataclass(frozen=True)
class PredictorSpec:
    predictor_id: str
    project: str
    asset: str
    predictor_type: str
    resolution_m: float | None
    purpose: str
    period: str
    rescale: str
    description: str
    bands: list[str]
    output_bands: list[str]
    scale_m: float


def configure_logger(output_dir: Path) -> None:
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "extract_predictors_for_pilot_points.log"

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
    if "execution" in data:
        raise ValueError(
            "Este script ya no usa execution.mode. Elimine el bloque 'execution' del YAML. "
            "Al ejecutar el script, se envían directamente las tareas de extracción a Drive."
        )
    return data


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def normalize_token(value: Any) -> str:
    text = str(value).strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def asset_basename(asset: str) -> str:
    return normalize_token(str(asset).strip().rstrip("/").split("/")[-1])


def clean_asset(value: Any) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", "", str(value).strip())


def parse_resolution(value: Any) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    number = re.search(r"\d+(?:\.\d+)?", text)
    if not number:
        return None
    return float(number.group(0))


def normalize_quotes(text: str) -> str:
    replacements = {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def parse_bands(value: Any, registry_cfg: dict[str, Any]) -> list[str]:
    if pd.isna(value):
        raise ValueError("La columna de bandas contiene un valor nulo.")

    text = normalize_quotes(str(value).strip())
    lowered = text.lower()

    for rule in (registry_cfg.get("band_range_patterns") or {}).values():
        contains = [str(token).lower() for token in rule.get("contains", [])]
        if contains and all(token in lowered for token in contains):
            prefix = str(rule["prefix"])
            start = int(rule["start"])
            end = int(rule["end"])
            return [f"{prefix}{i}" for i in range(start, end + 1)]

    try:
        parsed = json.loads(text)
    except Exception:
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            parsed = None

    if isinstance(parsed, list):
        bands = [str(item).strip() for item in parsed]
    else:
        text = text.strip("[]")
        bands = [part.strip().strip('"').strip("'") for part in text.split(",")]

    bands = [band for band in bands if band]
    if not bands:
        raise ValueError(f"No se pudieron interpretar las bandas desde: {value}")
    return bands


def make_unique(values: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    out: list[str] = []
    for value in values:
        if value not in counts:
            counts[value] = 0
            out.append(value)
        else:
            counts[value] += 1
            out.append(f"{value}_{counts[value]}")
    return out


def read_predictor_registry(config: dict[str, Any]) -> tuple[list[PredictorSpec], pd.DataFrame]:
    registry_cfg = config["registry"]
    paths = config["paths"]
    registry_path = resolve_path(paths["predictor_registry"])
    if not registry_path.exists():
        raise FileNotFoundError(f"No existe el registro de capas predictoras: {registry_path}")

    columns = registry_cfg["columns"]
    sheet = registry_cfg.get("sheet", 0)
    LOGGER.info("Leyendo registro de predictores: %s | hoja=%s", registry_path, sheet)
    registry = pd.read_excel(registry_path, sheet_name=sheet)
    registry.columns = [str(col).strip() for col in registry.columns]

    required_columns = [str(value).strip() for value in columns.values()]
    missing = [col for col in required_columns if col not in registry.columns]
    if missing:
        raise ValueError(f"Faltan columnas en el registro de predictores: {missing}")

    purpose_column = columns["purpose"].strip()
    keep_purpose = {normalize_token(value) for value in registry_cfg.get("keep_purpose", [])}
    if keep_purpose:
        registry = registry[
            registry[purpose_column].map(normalize_token).isin(keep_purpose)
        ].copy()

    if registry.empty:
        raise ValueError("No quedaron filas de predictores después del filtro keep_purpose.")

    base_ids = [asset_basename(asset) for asset in registry[columns["asset"].strip()].map(clean_asset)]
    predictor_ids = make_unique(base_ids)

    specs: list[PredictorSpec] = []
    catalog_rows: list[dict[str, Any]] = []
    separator = config["outputs"].get("predictor_name_separator", "__")
    scale_policy = config["gee"].get("scale_policy", "registry")
    fixed_scale = config["gee"].get("fixed_scale_m", 10)

    all_output_bands: list[str] = []

    for predictor_id, (_, row) in zip(predictor_ids, registry.iterrows()):
        asset = clean_asset(row[columns["asset"].strip()])
        if not asset:
            raise ValueError(f"{predictor_id}: asset vacío.")

        bands = parse_bands(row[columns["bands"].strip()], registry_cfg)
        output_bands = [f"{predictor_id}{separator}{normalize_token(band)}" for band in bands]
        resolution_m = parse_resolution(row[columns["resolution"].strip()])

        if scale_policy == "fixed":
            scale_m = float(fixed_scale)
        else:
            scale_m = float(resolution_m if resolution_m is not None else fixed_scale)

        spec = PredictorSpec(
            predictor_id=predictor_id,
            project=str(row[columns["project"].strip()]),
            asset=asset,
            predictor_type=str(row[columns["type"].strip()]),
            resolution_m=resolution_m,
            purpose=str(row[columns["purpose"].strip()]),
            period=str(row[columns["period"].strip()]),
            rescale=str(row[columns["rescale"].strip()]),
            description=str(row[columns["description"].strip()]),
            bands=bands,
            output_bands=output_bands,
            scale_m=scale_m,
        )
        specs.append(spec)
        all_output_bands.extend(output_bands)

        for band, output_band in zip(bands, output_bands):
            catalog_rows.append(
                {
                    "predictor_id": predictor_id,
                    "asset": asset,
                    "project": spec.project,
                    "type": spec.predictor_type,
                    "period": spec.period,
                    "resolution_m": spec.resolution_m,
                    "scale_m": spec.scale_m,
                    "rescale": spec.rescale,
                    "band_original": band,
                    "band_output": output_band,
                    "description": spec.description,
                }
            )

    duplicated_output = pd.Series(all_output_bands).duplicated().sum()
    if duplicated_output:
        raise ValueError(f"Hay {duplicated_output} nombres de bandas de salida duplicados.")

    catalog = pd.DataFrame(catalog_rows)
    LOGGER.info(
        "Predictores a extraer: %s assets | %s bandas finales",
        f"{len(specs):,}",
        f"{len(catalog):,}",
    )
    return specs, catalog


def table_columns(gpkg_path: Path, table_name: str) -> list[str]:
    with sqlite3.connect(gpkg_path) as connection:
        rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    if not rows:
        raise ValueError(f"No existe la tabla/capa '{table_name}' en {gpkg_path}")
    return [row[1] for row in rows]


def read_attribute_table(gpkg_path: Path, table_name: str, fields: list[str]) -> pd.DataFrame:
    columns = table_columns(gpkg_path, table_name)
    missing = [field for field in fields if field not in columns]
    if missing:
        raise ValueError(f"Faltan campos en {table_name}: {missing}")
    quoted = ", ".join(f'"{field}"' for field in fields)
    with sqlite3.connect(gpkg_path) as connection:
        return pd.read_sql_query(f'SELECT {quoted} FROM "{table_name}"', connection)


def validate_unique(dataframe: pd.DataFrame, key: str, label: str) -> None:
    duplicated = int(dataframe[key].duplicated().sum())
    if duplicated:
        raise ValueError(f"{label} tiene {duplicated:,} valores duplicados en {key}.")


def merge_optional_table(
    base: gpd.GeoDataFrame,
    gpkg_path: Path,
    table_name: str,
    fields: list[str],
    requested_properties: list[str],
    key: str,
) -> gpd.GeoDataFrame:
    table_fields = [field for field in fields if field == key or field in requested_properties]
    if len(table_fields) <= 1:
        return base

    table = read_attribute_table(gpkg_path, table_name, table_fields)
    validate_unique(table, key, table_name)
    return base.merge(table, on=key, how="left", validate="one_to_one")


def read_pilot_points(config: dict[str, Any]) -> gpd.GeoDataFrame:
    paths = config["paths"]
    inputs = config["inputs"]
    fields = config["fields"]
    key = fields["key"]
    quadrant = fields["quadrant"]
    export_properties = list(fields["export_properties"])

    pilot_gpkg = resolve_path(paths["pilot_gpkg"])
    if not pilot_gpkg.exists():
        raise FileNotFoundError(f"No existe el GPKG piloto A4: {pilot_gpkg}")

    point_fields = list(fields["pilot_point_fields"])
    if key not in point_fields:
        point_fields.insert(0, key)

    points_layer = inputs["pilot_points_layer"]
    LOGGER.info("Leyendo puntos piloto desde A4: %s | layer=%s", pilot_gpkg, points_layer)
    points = gpd.read_file(pilot_gpkg, layer=points_layer)

    missing = [field for field in point_fields if field not in points.columns]
    if missing:
        raise ValueError(f"Faltan campos en {points_layer}: {missing}")
    if points.crs is None:
        raise ValueError(f"{points_layer} no tiene CRS definido.")

    points = points[point_fields + ["geometry"]].copy()
    validate_unique(points, key, points_layer)

    assignment = read_attribute_table(
        pilot_gpkg,
        inputs["assignment_table"],
        [key, quadrant],
    )
    validate_unique(assignment, key, inputs["assignment_table"])
    merged = points.merge(assignment, on=key, how="left", validate="one_to_one")

    merged = merge_optional_table(
        merged,
        pilot_gpkg,
        inputs["score_table"],
        list(fields.get("score_fields", [])),
        export_properties,
        key,
    )
    merged = merge_optional_table(
        merged,
        pilot_gpkg,
        inputs["action_table"],
        list(fields.get("action_fields", [])),
        export_properties,
        key,
    )

    missing_export = [field for field in export_properties if field not in merged.columns]
    if missing_export:
        raise ValueError(f"No se pudieron construir propiedades de exportación: {missing_export}")

    null_required = merged[export_properties].isna().any(axis=1).sum()
    if null_required:
        raise ValueError(f"Hay {null_required:,} puntos piloto con propiedades de exportación nulas.")

    merged = merged.to_crs("EPSG:4326")
    LOGGER.info("Puntos piloto para extracción en GEE: %s", f"{len(merged):,}")
    return merged



def configure_ssl_certificates_for_auth(config: dict[str, Any]) -> None:
    """Avoid Windows certificate-store failures during Earth Engine OAuth.

    Some Windows/Conda Python installations fail while reading the Windows
    certificate store during the HTTPS token exchange used by ee.Authenticate().
    Using certifi's CA bundle keeps the authentication inside the script and
    avoids relying on the Windows certificate store.
    """
    gee_config = config.get("gee", {})
    use_certifi_ssl = bool(gee_config.get("use_certifi_ssl", True))
    if not use_certifi_ssl:
        return

    try:
        import certifi
        import ssl
    except ImportError:
        LOGGER.warning(
            "No se pudo importar certifi. Si la autenticación falla por SSL, "
            "instala certifi en este ambiente Python."
        )
        return

    cafile = certifi.where()
    os.environ["SSL_CERT_FILE"] = cafile
    os.environ["REQUESTS_CA_BUNDLE"] = cafile

    # urllib, used internally by earthengine-api during OAuth, calls
    # ssl._create_default_https_context(). Force that context to use certifi
    # instead of trying to read the Windows certificate store.
    ssl._create_default_https_context = (
        lambda *args, **kwargs: ssl.create_default_context(cafile=cafile)
    )

    LOGGER.info("SSL para autenticación configurado con certifi: %s", cafile)

def initialize_ee(config: dict[str, Any]) -> Any:
    try:
        import ee
    except ImportError as error:
        raise ImportError(
            "No se encontró earthengine-api. Instala con `pip install earthengine-api` "
            "o `conda install -c conda-forge earthengine-api`."
        ) from error

    configure_ssl_certificates_for_auth(config)

    gee_config = config.get("gee", {})
    project = gee_config.get("project")
    authenticate_if_needed = bool(gee_config.get("authenticate_if_needed", True))
    force_authentication = bool(gee_config.get("force_authentication", False))
    auth_mode = gee_config.get("auth_mode")

    def _initialize() -> None:
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()

    LOGGER.info("Inicializando Earth Engine | project=%s", project or "configurado_por_defecto")

    if force_authentication:
        LOGGER.info("Autenticación forzada desde el código: ee.Authenticate(force=True).")
        if auth_mode:
            ee.Authenticate(force=True, auth_mode=auth_mode)
        else:
            ee.Authenticate(force=True)

    try:
        _initialize()
        return ee
    except Exception as first_error:
        if not authenticate_if_needed:
            raise

        LOGGER.warning(
            "Earth Engine no tenía credenciales inicializadas o no pudo inicializarse. "
            "Se lanzará ee.Authenticate() desde el código. Error original: %s",
            first_error,
        )

        if auth_mode:
            ee.Authenticate(auth_mode=auth_mode)
        else:
            ee.Authenticate()

        try:
            _initialize()
        except Exception as second_error:
            raise RuntimeError(
                "Earth Engine se autenticó, pero no pudo inicializarse. "
                "Si el error menciona Cloud Project, define gee.project en el YAML con "
                "un project ID de Google Cloud/Earth Engine al que tengas acceso."
            ) from second_error

        return ee


def dataframe_batch_iterator(dataframe: gpd.GeoDataFrame, batch_size: int) -> list[tuple[int, gpd.GeoDataFrame]]:
    n_rows = len(dataframe)
    n_batches = int(math.ceil(n_rows / batch_size))
    batches: list[tuple[int, gpd.GeoDataFrame]] = []
    for batch_id in range(n_batches):
        start = batch_id * batch_size
        end = min(start + batch_size, n_rows)
        batches.append((batch_id + 1, dataframe.iloc[start:end].copy()))
    return batches


def to_ee_feature_collection(ee: Any, points: gpd.GeoDataFrame, properties: list[str]) -> Any:
    features = []
    for _, row in points.iterrows():
        geom = row.geometry
        props: dict[str, Any] = {}
        for field in properties:
            value = row[field]
            if pd.isna(value):
                props[field] = None
            elif hasattr(value, "item"):
                props[field] = value.item()
            else:
                props[field] = value
        features.append(
            ee.Feature(
                ee.Geometry.Point([float(geom.x), float(geom.y)]),
                props,
            )
        )
    return ee.FeatureCollection(features)


def write_audit_outputs(
    config: dict[str, Any],
    catalog: pd.DataFrame,
    points: gpd.GeoDataFrame,
) -> None:
    output_dir = resolve_path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    catalog_path = output_dir / config["outputs"].get("predictor_catalog_csv", "predictor_catalog.csv")
    catalog.to_csv(catalog_path, index=False, encoding="utf-8-sig")
    LOGGER.info("Catálogo de predictores escrito: %s", catalog_path)

    if bool(config["outputs"].get("write_local_selected_points_csv", False)):
        points_path = output_dir / config["outputs"].get("selected_points_csv", "pilot_points_for_gee.csv")
        properties = list(config["fields"]["export_properties"])
        local_points = pd.DataFrame(points[properties].copy())
        local_points["lon_wgs84"] = points.geometry.x
        local_points["lat_wgs84"] = points.geometry.y
        local_points.to_csv(points_path, index=False, encoding="utf-8-sig")
        LOGGER.info("Puntos piloto de auditoría escritos: %s", points_path)



def validate_gee_assets_if_requested(
    ee: Any,
    specs: list[PredictorSpec],
    config: dict[str, Any],
    output_dir: Path,
) -> None:
    """Check asset access and requested source bands before submitting tasks.

    The check is applied to all predictors from the filtered Excel registry.
    A probe CSV is always written when validation is enabled, so asset access
    and available bands can be audited without guessing from the Earth Engine
    Task Manager.
    """
    gee_cfg = config.get("gee", {}) or {}
    if not bool(gee_cfg.get("validate_assets_before_submit", True)):
        return

    strict = bool(gee_cfg.get("strict_asset_validation", True))
    probe_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    LOGGER.info(
        "Validando assets y bandas en GEE antes de enviar tareas | strict=%s",
        strict,
    )

    for spec in specs:
        try:
            image = ee.Image(spec.asset)
            available_bands = image.bandNames().getInfo()
            missing = [band for band in spec.bands if band not in available_bands]
            status = "ok" if not missing else "missing_bands"
            error_text = ""
        except Exception as error:
            available_bands = []
            missing = list(spec.bands)
            status = "asset_read_error"
            error_text = str(error)

        probe_rows.append(
            {
                "predictor_id": spec.predictor_id,
                "asset": spec.asset,
                "status": status,
                "requested_bands": "|".join(spec.bands),
                "available_bands": "|".join(map(str, available_bands)),
                "missing_bands": "|".join(missing),
                "error": error_text,
            }
        )

        if status == "asset_read_error":
            errors.append(
                f"{spec.predictor_id}: no se puede leer asset '{spec.asset}'. Error: {error_text}"
            )
        elif missing:
            errors.append(
                f"{spec.predictor_id}: bandas no encontradas {missing}. "
                f"Bandas disponibles: {available_bands}"
            )

    probe_path = output_dir / config.get("outputs", {}).get(
        "gee_asset_probe_csv",
        "gee_asset_probe.csv",
    )
    pd.DataFrame(probe_rows).to_csv(probe_path, index=False, encoding="utf-8-sig")
    LOGGER.info("Sondeo de assets escrito: %s", probe_path)

    if errors:
        joined = "\n- " + "\n- ".join(errors)
        message = (
            "La validación previa de GEE encontró problemas en los predictores "
            "seleccionados para envío:" + joined
        )
        if strict:
            raise ValueError(message)
        LOGGER.warning("%s", message)



def submit_gee_exports(config: dict[str, Any]) -> None:
    output_dir = resolve_path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    specs, catalog = read_predictor_registry(config)
    points = read_pilot_points(config)
    write_audit_outputs(config, catalog, points)

    ee = initialize_ee(config)

    manifest_path = output_dir / config["outputs"].get("task_manifest_csv", "gee_task_manifest.csv")
    gee_cfg = config["gee"]
    properties = list(config["fields"]["export_properties"])
    batch_size = int(gee_cfg.get("batch_size", 20000))
    batches = dataframe_batch_iterator(points, batch_size=batch_size)

    # Corrida completa: todos los predictores válidos del Excel y todos los lotes.
    # No hay filtros, flags true/false, ni plan de reintentos en el YAML.
    validate_gee_assets_if_requested(ee, specs, config, output_dir)

    expected_tasks = len(specs) * len(batches)
    max_tasks = int(gee_cfg.get("max_tasks_to_submit", 500))
    if expected_tasks > max_tasks:
        raise ValueError(
            f"Se intentarían enviar {expected_tasks} tareas, pero max_tasks_to_submit={max_tasks}. "
            "Si realmente querés ejecutar todo, subí max_tasks_to_submit en el YAML."
        )

    LOGGER.info(
        "Enviando extracción completa a Drive | predictores=%s | lotes=%s | tareas=%s | carpeta=%s",
        f"{len(specs):,}",
        f"{len(batches):,}",
        f"{expected_tasks:,}",
        gee_cfg["drive_folder"],
    )

    manifest_rows: list[dict[str, Any]] = []
    crs = gee_cfg.get("crs")
    if crs:
        LOGGER.warning(
            "gee.crs está definido (%s), pero sampleRegions no lo aplica directamente. "
            "Se deja la proyección del asset y la escala configurada.",
            crs,
        )

    image_cache: dict[str, Any] = {}
    for spec in specs:
        if spec.predictor_id not in image_cache:
            image_cache[spec.predictor_id] = ee.Image(spec.asset).select(spec.bands).rename(spec.output_bands)
        image = image_cache[spec.predictor_id]

        for batch_id, batch_points in batches:
            fc = to_ee_feature_collection(ee, batch_points, properties=properties)
            sampled = image.sampleRegions(
                collection=fc,
                properties=properties,
                scale=spec.scale_m,
                tileScale=int(gee_cfg.get("tile_scale", 16)),
                geometries=bool(gee_cfg.get("geometries", False)),
            )

            prefix = f"a4_2_{spec.predictor_id}_batch_{batch_id:03d}"
            task = ee.batch.Export.table.toDrive(
                collection=sampled,
                description=prefix,
                folder=gee_cfg["drive_folder"],
                fileNamePrefix=prefix,
                fileFormat=gee_cfg.get("file_format", "CSV"),
            )
            task.start()
            LOGGER.info(
                "Tarea enviada: %s | predictor=%s | batch=%s | puntos=%s",
                task.id,
                spec.predictor_id,
                batch_id,
                f"{len(batch_points):,}",
            )
            manifest_rows.append(
                {
                    "submitted_at_utc": datetime.now(timezone.utc).isoformat(),
                    "task_id": task.id,
                    "description": prefix,
                    "file_prefix": prefix,
                    "drive_folder": gee_cfg["drive_folder"],
                    "predictor_id": spec.predictor_id,
                    "asset": spec.asset,
                    "batch_id": batch_id,
                    "n_points_batch": len(batch_points),
                    "scale_m": spec.scale_m,
                    "run_type": "full_export_all_predictors_all_batches",
                    "status_at_submit": "SUBMITTED",
                }
            )

    manifest = pd.DataFrame(manifest_rows)
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")
    LOGGER.info("Manifiesto de tareas escrito: %s", manifest_path)
    LOGGER.info("Extracción enviada a Google Drive. Revise las tareas en Earth Engine.")


def main() -> None:
    config = read_yaml(DEFAULT_CONFIG)
    output_dir = resolve_path(config["paths"]["output_dir"])
    configure_logger(output_dir)

    LOGGER.info("YAML de configuración: %s", DEFAULT_CONFIG)
    LOGGER.info("Ejecución directa: extracción de predictores y exportación a Drive.")
    submit_gee_exports(config)


if __name__ == "__main__":
    main()