# -*- coding: utf-8 -*-
"""
Actividad 4.3 — Exportación de mosaicos/predictores por grupo espacial piloto
=======================================================================

Este script lee la salida normalizada de A4 y exporta desde Google Earth Engine
los raster/predictores recortados por grupo espacial piloto.

No usa argumentos por consola. El YAML fijo del proyecto define rutas, nombres
de capas, registro de predictores y parámetros de exportación.

Ejecución desde la raíz del repositorio:

    python src/actividad_4/4_3_export_quadrant_rasters.py

Salida principal:
    - tareas Export.image.toDrive() en Google Earth Engine;
    - una carpeta de Drive por grupo espacial piloto;
    - dentro de cada carpeta, un GeoTIFF por predictor;
    - manifiesto local de tareas para control y trazabilidad.

Regla metodológica:
    - no se remuestrean todos los predictores a una resolución común;
    - cada predictor se exporta con la escala registrada en el Excel;
    - no se mezclan predictores de distinta resolución en un solo GeoTIFF.
"""

from __future__ import annotations

import ast
import json
import logging
import numbers
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
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
from shapely.geometry import mapping  # noqa: E402

LOGGER = logging.getLogger("a4_3_quadrant_raster_export")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_3_export_quadrant_rasters.yaml"


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
    log_path = logs_dir / "export_quadrant_rasters.log"

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
            "Este script no usa execution.mode. Al ejecutarlo, exporta todos los "
            "predictores válidos para todos los cuadrantes del GPKG A4."
        )
    if "submission" in data:
        raise ValueError(
            "Este script no usa submission/run_all/execute/failed. La exportación es completa."
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
    replacements = {"“": '"', "”": '"', "‘": "'", "’": "'"}
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
        "Predictores a exportar: %s assets | %s bandas finales",
        f"{len(specs):,}",
        f"{len(catalog):,}",
    )
    return specs, catalog


def get_region_input_config(config: dict[str, Any]) -> tuple[str, str, str | None]:
    """Return source layer, output region id field and optional dissolve field.

    The default A4.3 behavior is to export spatial groups formed by dissolving
    the 20 x 20 km pilot quadrants by id_zona. This reduces 45 grid cells to
    the 5 spatial pilot groups shown in the workflow, without changing the
    normalized A4 database.
    """
    inputs = config["inputs"]
    layer = inputs.get("region_source_layer") or inputs.get("quadrant_layer")
    id_field = inputs.get("region_id_field") or inputs.get("quadrant_id_field")
    dissolve_by_field = inputs.get("dissolve_by_field")

    if not layer:
        raise ValueError("Defina inputs.region_source_layer en el YAML.")
    if not id_field:
        raise ValueError("Defina inputs.region_id_field en el YAML.")

    return str(layer), str(id_field), str(dissolve_by_field) if dissolve_by_field else None


def read_export_regions(config: dict[str, Any]) -> gpd.GeoDataFrame:
    paths = config["paths"]
    gpkg_path = resolve_path(paths["pilot_gpkg"])
    if not gpkg_path.exists():
        raise FileNotFoundError(f"No existe el GPKG piloto A4: {gpkg_path}")

    layer, id_field, dissolve_by_field = get_region_input_config(config)
    LOGGER.info("Leyendo geometrías base desde A4: %s | layer=%s", gpkg_path, layer)
    regions = gpd.read_file(gpkg_path, layer=layer)

    required = ["geometry"]
    if dissolve_by_field:
        required.append(dissolve_by_field)
    else:
        required.append(id_field)

    missing = [field for field in required if field not in regions.columns]
    if missing:
        raise ValueError(f"Faltan campos en {layer}: {missing}")
    if regions.crs is None:
        raise ValueError(f"{layer} no tiene CRS definido.")
    if regions.empty:
        raise ValueError(f"{layer} está vacío.")

    if (~regions.geometry.is_valid).sum():
        LOGGER.warning("Se detectaron geometrías inválidas. Se aplicará make_valid().")
        regions = regions.copy()
        regions["geometry"] = regions.geometry.make_valid()

    if dissolve_by_field:
        missing_group = int(regions[dissolve_by_field].isna().sum())
        if missing_group:
            raise ValueError(
                f"{layer} tiene {missing_group:,} geometrías sin valor en {dissolve_by_field}."
            )
        n_input = len(regions)
        regions = regions[[dissolve_by_field, "geometry"]].dissolve(
            by=dissolve_by_field, as_index=False
        )
        if dissolve_by_field != id_field:
            regions = regions.rename(columns={dissolve_by_field: id_field})
        regions = regions[[id_field, "geometry"]].copy()
        LOGGER.info(
            "Geometrías agrupadas espacialmente: entrada=%s | grupos=%s | campo=%s",
            f"{n_input:,}",
            f"{len(regions):,}",
            dissolve_by_field,
        )
    else:
        duplicated = int(regions[id_field].duplicated().sum())
        if duplicated:
            raise ValueError(f"{layer} tiene {duplicated:,} valores duplicados en {id_field}.")
        regions = regions[[id_field, "geometry"]].copy()

    include_region_ids = config.get("inputs", {}).get("include_region_ids")
    if include_region_ids is not None:
        if not isinstance(include_region_ids, list) or not include_region_ids:
            raise ValueError("inputs.include_region_ids debe ser una lista no vacía.")

        def canonical_region_id(value: Any) -> str:
            if pd.isna(value):
                return ""
            if isinstance(value, numbers.Integral):
                return str(int(value))
            if isinstance(value, numbers.Real) and float(value).is_integer():
                return str(int(value))
            return str(value).strip()

        requested_ids = {canonical_region_id(value) for value in include_region_ids}
        observed_ids = regions[id_field].map(canonical_region_id)
        available_ids = set(observed_ids)
        missing_ids = sorted(requested_ids - available_ids)
        if missing_ids:
            raise ValueError(
                "inputs.include_region_ids contiene zonas inexistentes: "
                f"{missing_ids}. Disponibles: {sorted(available_ids)}"
            )
        before_filter = len(regions)
        regions = regions.loc[observed_ids.isin(requested_ids)].copy()
        LOGGER.info(
            "Filtro de zonas aplicado: solicitadas=%s | grupos antes=%s | grupos después=%s",
            sorted(requested_ids),
            f"{before_filter:,}",
            f"{len(regions):,}",
        )

    simplify_m = float(config.get("export", {}).get("simplify_geometry_m", 0) or 0)
    if simplify_m > 0:
        metric_crs = regions.estimate_utm_crs()
        if metric_crs is None:
            raise ValueError("No se pudo estimar CRS métrico para simplificar geometría.")
        tmp = regions.to_crs(metric_crs)
        tmp["geometry"] = tmp.geometry.simplify(simplify_m, preserve_topology=True)
        regions = tmp.to_crs(regions.crs)
        LOGGER.info("Geometría simplificada con tolerancia=%s m", simplify_m)

    regions = regions.to_crs("EPSG:4326")
    LOGGER.info("Grupos espaciales para exportación: %s", f"{len(regions):,}")
    return regions


def configure_ssl_certificates_for_auth(config: dict[str, Any]) -> None:
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
                "Si el error menciona Cloud Project, define gee.project en el YAML."
            ) from second_error
        return ee


def render_template(template: str, values: dict[str, Any]) -> str:
    try:
        return template.format(**values)
    except KeyError as error:
        raise KeyError(f"Variable no definida en template '{template}': {error}") from error


def sanitize_task_description(value: str) -> str:
    text = normalize_token(value)
    if not text:
        text = "a4_3_export"
    return text[:100]


def validate_gee_assets_if_requested(
    ee: Any,
    specs: list[PredictorSpec],
    config: dict[str, Any],
    output_dir: Path,
) -> None:
    gee_cfg = config.get("gee", {}) or {}
    if not bool(gee_cfg.get("validate_assets_before_submit", True)):
        return

    strict = bool(gee_cfg.get("strict_asset_validation", True))
    probe_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    LOGGER.info("Validando assets y bandas en GEE antes de exportar | strict=%s", strict)

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
            errors.append(f"{spec.predictor_id}: no se puede leer asset '{spec.asset}'. Error: {error_text}")
        elif missing:
            errors.append(
                f"{spec.predictor_id}: bandas no encontradas {missing}. Bandas disponibles: {available_bands}"
            )

    probe_path = output_dir / config.get("outputs", {}).get("gee_asset_probe_csv", "gee_asset_probe_rasters.csv")
    pd.DataFrame(probe_rows).to_csv(probe_path, index=False, encoding="utf-8-sig")
    LOGGER.info("Sondeo de assets escrito: %s", probe_path)

    if errors:
        joined = "\n- " + "\n- ".join(errors)
        message = "La validación previa de GEE encontró problemas:" + joined
        if strict:
            raise ValueError(message)
        LOGGER.warning("%s", message)


def write_audit_outputs(config: dict[str, Any], catalog: pd.DataFrame, regions: gpd.GeoDataFrame) -> None:
    output_dir = resolve_path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    catalog_path = output_dir / config["outputs"].get("predictor_catalog_csv", "predictor_catalog_rasters.csv")
    catalog.to_csv(catalog_path, index=False, encoding="utf-8-sig")
    LOGGER.info("Catálogo de predictores escrito: %s", catalog_path)

    _, id_field, _ = get_region_input_config(config)
    regions_path = output_dir / config["outputs"].get("regions_csv", config["outputs"].get("quadrants_csv", "regions_for_raster_export.csv"))
    regions[[id_field]].assign(
        id_region_safe=regions[id_field].map(normalize_token)
    ).to_csv(regions_path, index=False, encoding="utf-8-sig")
    LOGGER.info("Lista de grupos espaciales escrita: %s", regions_path)


def build_export_kwargs(config: dict[str, Any], image: Any, description: str, folder: str, file_prefix: str, region: Any, scale_m: float) -> dict[str, Any]:
    gee_cfg = config["gee"]
    kwargs: dict[str, Any] = {
        "image": image,
        "description": sanitize_task_description(description),
        "folder": folder,
        "fileNamePrefix": file_prefix,
        "region": region,
        "scale": float(scale_m),
        "maxPixels": int(gee_cfg.get("max_pixels", 10_000_000_000_000)),
        "fileFormat": gee_cfg.get("file_format", "GeoTIFF"),
    }

    if gee_cfg.get("crs"):
        kwargs["crs"] = gee_cfg["crs"]

    if kwargs["fileFormat"] == "GeoTIFF":
        format_options: dict[str, Any] = {}
        if "cloud_optimized" in gee_cfg:
            format_options["cloudOptimized"] = bool(gee_cfg.get("cloud_optimized", True))
        if format_options:
            kwargs["formatOptions"] = format_options
        if "skip_empty_tiles" in gee_cfg:
            kwargs["skipEmptyTiles"] = bool(gee_cfg.get("skip_empty_tiles", True))

    if gee_cfg.get("file_dimensions"):
        kwargs["fileDimensions"] = gee_cfg["file_dimensions"]
    if gee_cfg.get("shard_size"):
        kwargs["shardSize"] = int(gee_cfg["shard_size"])

    return kwargs


def submit_quadrant_raster_exports(config: dict[str, Any]) -> None:
    output_dir = resolve_path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    specs, catalog = read_predictor_registry(config)
    regions = read_export_regions(config)
    write_audit_outputs(config, catalog, regions)

    ee = initialize_ee(config)
    validate_gee_assets_if_requested(ee, specs, config, output_dir)

    expected_tasks = len(specs) * len(regions)
    max_tasks = int(config["gee"].get("max_tasks_to_submit", 500))
    if expected_tasks > max_tasks:
        raise ValueError(
            f"Se intentarían enviar {expected_tasks} tareas, pero max_tasks_to_submit={max_tasks}. "
            "Si realmente querés ejecutar todo, subí max_tasks_to_submit en el YAML."
        )

    _, id_field, _ = get_region_input_config(config)
    export_cfg = config["export"]
    root_drive_folder = config["gee"]["root_drive_folder"]
    folder_template = export_cfg.get("folder_template", "{root_drive_folder}_{id_cuadrante_safe}")
    filename_template = export_cfg.get("filename_template", "{id_cuadrante_safe}__{predictor_id}")
    description_template = export_cfg.get("description_template", "a4_3_{id_cuadrante_safe}_{predictor_id}")

    LOGGER.info(
        "Enviando exportación raster completa a Drive | grupos_espaciales=%s | predictores=%s | tareas=%s",
        f"{len(regions):,}",
        f"{len(specs):,}",
        f"{expected_tasks:,}",
    )

    manifest_rows: list[dict[str, Any]] = []
    image_cache: dict[str, Any] = {}

    for _, rrow in regions.iterrows():
        region_id = rrow[id_field]
        region_id_text = str(region_id)
        region_id_safe = normalize_token(region_id_text)
        region = ee.Geometry(mapping(rrow.geometry), geodesic=False)

        for spec in specs:
            if spec.predictor_id not in image_cache:
                image_cache[spec.predictor_id] = (
                    ee.Image(spec.asset)
                    .select(spec.bands)
                    .rename(spec.output_bands)
                )
            image = image_cache[spec.predictor_id].clip(region)

            template_values = {
                "root_drive_folder": root_drive_folder,
                "id_cuadrante": region_id_text,
                "id_cuadrante_safe": region_id_safe,
                "id_region": region_id_text,
                "id_region_safe": region_id_safe,
                "predictor_id": spec.predictor_id,
                "scale_m": int(spec.scale_m) if float(spec.scale_m).is_integer() else spec.scale_m,
            }
            folder = render_template(folder_template, template_values)
            file_prefix = render_template(filename_template, template_values)
            description = render_template(description_template, template_values)

            export_kwargs = build_export_kwargs(
                config=config,
                image=image,
                description=description,
                folder=folder,
                file_prefix=file_prefix,
                region=region,
                scale_m=spec.scale_m,
            )
            task = ee.batch.Export.image.toDrive(**export_kwargs)
            task.start()

            LOGGER.info(
                "Tarea enviada: %s | grupo_espacial=%s | predictor=%s | folder=%s | scale=%s",
                task.id,
                region_id_text,
                spec.predictor_id,
                folder,
                spec.scale_m,
            )
            manifest_rows.append(
                {
                    "submitted_at_utc": datetime.now(timezone.utc).isoformat(),
                    "task_id": task.id,
                    "description": sanitize_task_description(description),
                    "drive_folder": folder,
                    "file_prefix": file_prefix,
                    "id_cuadrante": region_id_text,
                    "id_cuadrante_safe": region_id_safe,
                    "id_region": region_id_text,
                    "id_region_safe": region_id_safe,
                    "predictor_id": spec.predictor_id,
                    "asset": spec.asset,
                    "bands": "|".join(spec.bands),
                    "output_bands": "|".join(spec.output_bands),
                    "scale_m": spec.scale_m,
                    "file_format": config["gee"].get("file_format", "GeoTIFF"),
                    "run_type": "selected_spatial_groups_all_predictors",
                    "status_at_submit": "SUBMITTED",
                }
            )

    manifest = pd.DataFrame(manifest_rows)
    manifest_path = output_dir / config["outputs"].get("task_manifest_csv", "gee_quadrant_raster_task_manifest.csv")
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")
    LOGGER.info("Manifiesto de tareas escrito: %s", manifest_path)
    LOGGER.info("Exportación enviada a Google Drive. Revise las tareas en Earth Engine.")


def main() -> None:
    config = read_yaml(DEFAULT_CONFIG)
    output_dir = resolve_path(config["paths"]["output_dir"])
    configure_logger(output_dir)

    LOGGER.info("YAML de configuración: %s", DEFAULT_CONFIG)
    LOGGER.info("Ejecución directa: exportación de mosaicos/predictores por grupo espacial a Drive.")
    submit_quadrant_raster_exports(config)


if __name__ == "__main__":
    main()
