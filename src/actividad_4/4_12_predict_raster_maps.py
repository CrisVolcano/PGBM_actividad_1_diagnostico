#!/usr/bin/env python3
"""Actividad 4.12 - Inferencia cartográfica por ventanas.

Consume exclusivamente el manifiesto aprobado de A4.11 y artefactos congelados
entrenados en ``development_only``. Aplica el modelo a todos los píxeles
válidos, incluidos los cuadrantes independientes, sin incorporarlos al modelo.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window


SCRIPT_PATH = Path(__file__).resolve()
sys.path.insert(0, str(SCRIPT_PATH.parent))

from raster_prediction_common import (  # noqa: E402
    REPO_ROOT,
    FrozenModelRunner,
    atomic_write_json,
    class_style_rows,
    dataframe_to_markdown,
    parse_csv_list,
    quick_file_fingerprint,
    read_config,
    resolve_path,
    write_class_raster_styles,
)


DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_11_13_raster_prediction.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--regions", help="IDs de zona separados por coma.")
    parser.add_argument("--resolutions", help="Resoluciones separadas por coma.")
    parser.add_argument(
        "--models",
        help="Modelos separados por coma: rf,svm,xgboost,dnn.",
    )
    parser.add_argument(
        "--styles-only",
        action="store_true",
        help=(
            "Genera o actualiza QML/SLD/CLR para predicciones existentes, "
            "sin cargar modelos ni leer los rasters predictores."
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"No existe manifiesto A4.11: {path}. Ejecute primero 4_11."
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not bool(manifest.get("ready", False)):
        raise ValueError(
            "El manifiesto A4.11 no está aprobado (ready=false). "
            "No se ejecutará inferencia."
        )
    if manifest.get("development_split_role") != "development_cv":
        raise ValueError(
            "El manifiesto no documenta rangos calculados solo en development_cv."
        )
    return manifest


def rasterio_resampling(name: str) -> Resampling:
    normalized = str(name).strip().lower()
    mapping = {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
        "average": Resampling.average,
        "mode": Resampling.mode,
    }
    if normalized not in mapping:
        raise ValueError(f"Remuestreo no soportado: {name}")
    return mapping[normalized]


def output_paths(
    output_dir: Path,
    model_id: str,
    region_id: str,
    resolution: int,
) -> dict[str, Path]:
    directory = output_dir / model_id / f"{resolution}m" / f"region_{region_id}"
    stem = f"{region_id}__{model_id}__id_1_propuesta__{resolution}m"
    return {
        "class": directory / f"{stem}.tif",
        "confidence": directory / f"{stem}__confidence.tif",
    }


def extrapolation_path(
    output_dir: Path,
    region_id: str,
    resolution: int,
) -> Path:
    directory = output_dir / "diagnostics" / f"{resolution}m" / f"region_{region_id}"
    return directory / (
        f"{region_id}__outside_development_range_count__{resolution}m.tif"
    )


def partial_path(final_path: Path) -> Path:
    return final_path.with_name(final_path.stem + ".partial" + final_path.suffix)


def grid_windows(width: int, height: int, block_size: int) -> list[Window]:
    windows: list[Window] = []
    for row_off in range(0, height, block_size):
        for col_off in range(0, width, block_size):
            windows.append(
                Window(
                    col_off,
                    row_off,
                    min(block_size, width - col_off),
                    min(block_size, height - row_off),
                )
            )
    return windows


def create_output(
    path: Path,
    grid: dict[str, Any],
    dtype: str,
    nodata: int | float,
    block_size: int,
    compression: str,
    tags: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": int(grid["width"]),
        "height": int(grid["height"]),
        "count": 1,
        "crs": grid["crs_wkt"],
        "transform": Affine(*grid["transform"]),
        "dtype": dtype,
        "nodata": nodata,
        "tiled": True,
        "blockxsize": block_size,
        "blockysize": block_size,
        "compress": compression,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(path, "w", **profile) as destination:
        destination.update_tags(
            **{key: str(value) for key, value in tags.items()}
        )


def verify_source_fingerprint(source: dict[str, Any]) -> None:
    path = Path(source["path"])
    if not path.exists():
        raise FileNotFoundError(f"Raster desapareció después de A4.11: {path}")
    observed = quick_file_fingerprint(path)
    if observed != source["fingerprint"]:
        raise ValueError(
            f"Raster cambió después del manifiesto A4.11: {path}. "
            "Vuelva a ejecutar 4_11."
        )


def verify_model_manifest(
    manifest: dict[str, Any],
    shared: dict[str, Any],
    model_ids: list[str],
) -> None:
    """Impide inferencia con artefactos distintos de los aprobados en A4.11."""
    manifest_models = {
        str(item["model_id"]): item for item in manifest.get("models", [])
    }
    for model_id in model_ids:
        if model_id not in manifest_models:
            raise ValueError(
                f"{model_id}: no aparece en el manifiesto aprobado de A4.11."
            )
        approved = manifest_models[model_id]
        model_config = shared["models"][model_id]
        configured_path = resolve_path(model_config["artifact"])
        approved_path = Path(approved["artifact"]).resolve()
        if configured_path != approved_path:
            raise ValueError(
                f"{model_id}: el artefacto configurado no es el aprobado por "
                f"A4.11 ({configured_path} != {approved_path})."
            )
        if not configured_path.exists():
            raise FileNotFoundError(
                f"{model_id}: desapareció el artefacto {configured_path}."
            )
        observed = quick_file_fingerprint(configured_path)
        if observed != approved.get("artifact_fingerprint"):
            raise ValueError(
                f"{model_id}: el artefacto cambió después de A4.11. "
                "Vuelva a ejecutar 4_11."
            )
        if approved.get("expected_trained_on") != "development_only":
            raise ValueError(
                f"{model_id}: el manifiesto no lo identifica como "
                "development_only."
            )
        approved_components = approved.get("component_fingerprints", {})
        for component in [
            "artifact",
            "label_encoder",
            "preprocessor",
            "feature_columns",
        ]:
            if component not in model_config:
                continue
            component_path = resolve_path(model_config[component])
            if not component_path.exists():
                raise FileNotFoundError(
                    f"{model_id}: desapareció {component}: {component_path}"
                )
            if quick_file_fingerprint(component_path) != approved_components.get(
                component
            ):
                raise ValueError(
                    f"{model_id}: {component} cambió después de A4.11. "
                    "Vuelva a ejecutar 4_11."
                )


def open_source_vrts(
    stack: contextlib.ExitStack,
    region: dict[str, Any],
    grid: dict[str, Any],
    predictor_threads: int,
) -> dict[str, tuple[Any, list[dict[str, Any]]]]:
    output: dict[str, tuple[Any, list[dict[str, Any]]]] = {}
    target_transform = Affine(*grid["transform"])
    for source in region["sources"]:
        verify_source_fingerprint(source)
        dataset = stack.enter_context(rasterio.open(source["path"]))
        vrt_options: dict[str, Any] = {
            "crs": grid["crs_wkt"],
            "transform": target_transform,
            "width": int(grid["width"]),
            "height": int(grid["height"]),
            "resampling": rasterio_resampling(source["resampling"]),
            "nodata": np.nan,
            "dtype": "float32",
            "warp_extras": {"NUM_THREADS": str(max(1, predictor_threads))},
        }
        if dataset.nodata is not None:
            vrt_options["src_nodata"] = dataset.nodata
        vrt = stack.enter_context(WarpedVRT(dataset, **vrt_options))
        output[source["predictor_id"]] = (vrt, source["bands"])
    return output


def read_feature_window(
    source_vrts: dict[str, tuple[Any, list[dict[str, Any]]]],
    window: Window,
    feature_count: int,
    require_all: bool,
) -> tuple[np.ndarray, np.ndarray]:
    pixel_count = int(window.width * window.height)
    X = np.full((pixel_count, feature_count), np.nan, dtype=np.float32)
    valid = np.ones(pixel_count, dtype=bool) if require_all else np.zeros(
        pixel_count, dtype=bool
    )
    for vrt, bands in source_vrts.values():
        indexes = [int(band["band_index"]) for band in bands]
        values = vrt.read(
            indexes=indexes,
            window=window,
            masked=True,
            out_dtype="float32",
        )
        data = np.asarray(values.filled(np.nan), dtype=np.float32)
        band_valid = np.isfinite(data) & ~np.ma.getmaskarray(values)
        for local_index, band in enumerate(bands):
            feature_index = int(band["feature_order"]) - 1
            X[:, feature_index] = data[local_index].reshape(-1)
        source_valid = band_valid.all(axis=0).reshape(-1)
        valid = valid & source_valid if require_all else valid | source_valid
    if require_all:
        valid &= np.isfinite(X).all(axis=1)
    return X, valid


def outside_range_count(
    X: np.ndarray,
    valid: np.ndarray,
    feature_columns: list[str],
    ranges: dict[str, Any],
) -> np.ndarray:
    output = np.full(len(X), 255, dtype=np.uint8)
    if not valid.any():
        return output
    minimum = np.asarray(
        [ranges[feature]["min_development"] for feature in feature_columns],
        dtype=np.float32,
    )
    maximum = np.asarray(
        [ranges[feature]["max_development"] for feature in feature_columns],
        dtype=np.float32,
    )
    values = X[valid]
    outside = ((values < minimum) | (values > maximum)) & np.isfinite(values)
    output[valid] = outside.sum(axis=1).astype(np.uint8)
    return output


def run_signature(
    manifest: dict[str, Any],
    region: dict[str, Any],
    grid: dict[str, Any],
    model_ids: list[str],
) -> str:
    payload = {
        "schema": 1,
        "manifest_feature_hash": manifest["feature_columns_sha256"],
        "region_id": region["region_id"],
        "grid": grid,
        "models": model_ids,
        "sources": [
            {
                "path": source["path"],
                "fingerprint": source["fingerprint"],
                "resampling": source["resampling"],
            }
            for source in region["sources"]
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def class_area_table(
    class_path: Path,
    model_id: str,
    region_id: str,
    resolution: int,
    class_catalog: list[dict[str, Any]],
) -> pd.DataFrame:
    counts: dict[int, int] = {}
    with rasterio.open(class_path) as source:
        for _, window in source.block_windows(1):
            values = source.read(1, window=window)
            unique, frequencies = np.unique(values[values != source.nodata], return_counts=True)
            for class_id, count in zip(unique, frequencies):
                counts[int(class_id)] = counts.get(int(class_id), 0) + int(count)
        pixel_area_m2 = abs(float(source.transform.a * source.transform.e))
    labels = {
        int(row["id_1_propuesta"]): row["nivel_1_propuesta"]
        for row in class_catalog
    }
    total = sum(counts.values())
    rows = []
    for class_id in sorted(labels):
        count = counts.get(class_id, 0)
        rows.append(
            {
                "model_id": model_id,
                "region_id": region_id,
                "resolution_m": resolution,
                "class_id": class_id,
                "class_label": labels[class_id],
                "pixel_count": count,
                "pct_valid_pixels": count / total if total else np.nan,
                "area_ha": count * pixel_area_m2 / 10000.0,
            }
        )
    return pd.DataFrame(rows)


def style_inventory_fields(
    class_path: Path,
    class_catalog: list[dict[str, Any]],
    style_config: dict[str, Any],
    nodata: int,
) -> dict[str, Any]:
    generated = write_class_raster_styles(
        class_path,
        class_catalog,
        style_config,
        nodata,
    )
    return {
        "qml_style": generated["qml"],
        "sld_style": generated["sld"],
        "clr_style": generated["clr"],
        "embedded_colormap": generated["embedded_colormap"],
    }


def generate_styles_only(
    output_dir: Path,
    model_ids: list[str],
    selected_regions: set[str],
    resolutions: set[int],
    class_catalog: list[dict[str, Any]],
    style_config: dict[str, Any],
    nodata_class: int,
) -> pd.DataFrame:
    """Actualiza estilos de mapas existentes sin cargar los modelos."""
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for model_id in model_ids:
        for resolution in sorted(resolutions):
            for region_id in sorted(selected_regions, key=int):
                class_path = output_paths(
                    output_dir,
                    model_id,
                    region_id,
                    resolution,
                )["class"]
                if not class_path.exists():
                    missing.append(str(class_path))
                    rows.append(
                        {
                            "model_id": model_id,
                            "region_id": region_id,
                            "resolution_m": resolution,
                            "class_raster": str(class_path),
                            "status": "missing_class_raster",
                        }
                    )
                    continue
                style_fields = style_inventory_fields(
                    class_path,
                    class_catalog,
                    style_config,
                    nodata_class,
                )
                rows.append(
                    {
                        "model_id": model_id,
                        "region_id": region_id,
                        "resolution_m": resolution,
                        "class_raster": str(class_path),
                        "status": "styles_updated",
                        **style_fields,
                    }
                )
    inventory = pd.DataFrame(rows)
    inventory.to_csv(
        output_dir / "styles" / "prediction_style_inventory.csv",
        index=False,
        encoding="utf-8-sig",
    )
    if missing:
        raise FileNotFoundError(
            "Faltan rasters de clase para generar estilos: "
            + "; ".join(missing[:10])
        )
    return inventory


def main() -> None:
    args = parse_args()
    config = read_config(args.config)
    shared = config["shared"]
    predict_config = config["predict"]
    manifest_path = resolve_path(predict_config["manifest_json"])
    manifest = load_manifest(manifest_path)
    output_dir = resolve_path(predict_config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_regions = set(
        parse_csv_list(args.regions, str)
        or [str(value) for value in shared["regions"]]
    )
    resolutions = set(
        parse_csv_list(args.resolutions, int)
        or [int(value) for value in predict_config["resolutions_m"]]
    )
    model_ids = (
        parse_csv_list(args.models, str)
        or [str(value) for value in predict_config["model_ids"]]
    )
    unknown_models = sorted(set(model_ids) - set(shared["models"]))
    if unknown_models:
        raise ValueError(f"Modelos no configurados: {unknown_models}")
    if not model_ids:
        raise ValueError("Debe seleccionar al menos un modelo.")
    manifest_region_ids = {
        str(region["region_id"]) for region in manifest.get("regions", [])
    }
    missing_manifest_regions = sorted(selected_regions - manifest_region_ids)
    if missing_manifest_regions:
        raise ValueError(
            "Las siguientes zonas no están en el manifiesto aprobado: "
            f"{missing_manifest_regions}"
        )
    manifest_resolutions = {
        int(grid["resolution_m"])
        for region in manifest.get("regions", [])
        for grid in region.get("grids", [])
    }
    missing_resolutions = sorted(resolutions - manifest_resolutions)
    if missing_resolutions:
        raise ValueError(
            "Las siguientes resoluciones no están en el manifiesto: "
            f"{missing_resolutions}"
        )
    if args.styles_only:
        class_catalog = manifest["target"]["classes"]
        style_config = shared["target"].get("style", {})
        style_rows = class_style_rows(class_catalog, style_config)
        approved_colors = {
            int(row["id_1_propuesta"]): str(
                row.get("color_hex", "")
            ).upper()
            for row in class_catalog
        }
        configured_colors = {
            int(row["id_1_propuesta"]): str(row["color_hex"]).upper()
            for row in style_rows
        }
        if approved_colors != configured_colors:
            raise ValueError(
                "La paleta cambió después del manifiesto A4.11. "
                "Vuelva a ejecutar 4_11."
            )
        styles_dir = output_dir / "styles"
        styles_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(style_rows).to_csv(
            styles_dir / "homologated_class_palette.csv",
            index=False,
            encoding="utf-8-sig",
        )
        inventory = generate_styles_only(
            output_dir,
            model_ids,
            selected_regions,
            resolutions,
            class_catalog,
            style_config,
            int(shared["target"].get("nodata_class", 0)),
        )
        print(
            f"Estilos actualizados: {len(inventory):,} rasters de clase."
        )
        print(
            "Inventario: "
            f"{styles_dir / 'prediction_style_inventory.csv'}"
        )
        return
    verify_model_manifest(manifest, shared, model_ids)
    overwrite = bool(args.overwrite or predict_config.get("overwrite", False))
    block_size = int(predict_config.get("block_size", 256))
    if block_size < 16 or block_size % 16:
        raise ValueError("block_size debe ser múltiplo de 16 y al menos 16.")

    feature_columns = list(manifest["feature_columns"])
    runners = {
        model_id: FrozenModelRunner(
            model_id,
            shared["models"][model_id],
            feature_columns,
            int(predict_config.get("prediction_batch_size", 65536)),
            str(predict_config.get("dnn_device", "auto")),
        )
        for model_id in model_ids
    }
    confidence_models = {
        model_id
        for model_id, runner in runners.items()
        if bool(predict_config.get("write_confidence", True))
        and runner.supports_confidence
    }
    expected_classes = set(map(int, shared["target"]["expected_classes"]))
    class_catalog = manifest["target"]["classes"]
    style_config = shared["target"].get("style", {})
    style_rows = class_style_rows(class_catalog, style_config)
    approved_colors = {
        int(row["id_1_propuesta"]): str(row.get("color_hex", "")).upper()
        for row in class_catalog
    }
    configured_colors = {
        int(row["id_1_propuesta"]): str(row["color_hex"]).upper()
        for row in style_rows
    }
    if approved_colors != configured_colors:
        raise ValueError(
            "La paleta cambió después del manifiesto A4.11. "
            "Vuelva a ejecutar 4_11."
        )
    styles_dir = output_dir / "styles"
    styles_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(style_rows).to_csv(
        styles_dir / "homologated_class_palette.csv",
        index=False,
        encoding="utf-8-sig",
    )
    nodata_class = int(shared["target"].get("nodata_class", 0))
    area_tables: list[pd.DataFrame] = []
    run_rows: list[dict[str, Any]] = []

    for region in manifest["regions"]:
        region_id = str(region["region_id"])
        if region_id not in selected_regions:
            continue
        if not region["ready"]:
            raise ValueError(f"Zona {region_id} no está lista en el manifiesto.")
        grids = {
            int(grid["resolution_m"]): grid for grid in region["grids"]
        }
        for resolution in sorted(resolutions):
            if resolution not in grids:
                raise ValueError(
                    f"Zona {region_id} sin cuadrícula de {resolution} m."
                )
            grid = grids[resolution]
            paths_by_model = {
                model_id: output_paths(
                    output_dir, model_id, region_id, resolution
                )
                for model_id in model_ids
            }
            required_products = {
                model_id: [paths["class"]]
                + (
                    [paths["confidence"]]
                    if model_id in confidence_models
                    else []
                )
                for model_id, paths in paths_by_model.items()
            }
            active_models = [
                model_id
                for model_id, paths in required_products.items()
                if overwrite or not all(path.exists() for path in paths)
            ]
            extrap_final = extrapolation_path(
                output_dir, region_id, resolution
            )
            extrap_active = bool(
                predict_config.get("write_extrapolation_count", True)
            ) and (overwrite or not extrap_final.exists())
            if not active_models and not extrap_active:
                for model_id in model_ids:
                    areas = class_area_table(
                        paths_by_model[model_id]["class"],
                        model_id,
                        region_id,
                        resolution,
                        class_catalog,
                    )
                    area_tables.append(areas)
                    style_fields = style_inventory_fields(
                        paths_by_model[model_id]["class"],
                        class_catalog,
                        style_config,
                        nodata_class,
                    )
                    run_rows.append(
                        {
                            "model_id": model_id,
                            "region_id": region_id,
                            "resolution_m": resolution,
                            "class_raster": str(
                                paths_by_model[model_id]["class"]
                            ),
                            "confidence_raster": str(
                                paths_by_model[model_id]["confidence"]
                            )
                            if model_id in confidence_models
                            else "",
                            "extrapolation_raster": str(extrap_final),
                            "valid_pixels": int(
                                areas["pixel_count"].sum()
                            ),
                            "status": "already_complete",
                            **style_fields,
                        }
                    )
                print(f"Saltando zona {region_id} {resolution} m: salidas completas.")
                continue

            progress_path = (
                output_dir
                / "progress"
                / f"region_{region_id}__{resolution}m.json"
            )
            if overwrite:
                candidates = [progress_path, partial_path(extrap_final), extrap_final]
                for paths in paths_by_model.values():
                    candidates.extend(
                        [
                            paths["class"],
                            paths["confidence"],
                            partial_path(paths["class"]),
                            partial_path(paths["confidence"]),
                        ]
                    )
                for candidate in candidates:
                    if candidate.exists():
                        candidate.unlink()

            expected_partials = [
                partial_path(paths_by_model[model_id]["class"])
                for model_id in active_models
            ]
            expected_partials.extend(
                partial_path(paths_by_model[model_id]["confidence"])
                for model_id in active_models
                if model_id in confidence_models
            )
            if extrap_active:
                expected_partials.append(partial_path(extrap_final))
            if progress_path.exists() and not all(
                path.exists() for path in expected_partials
            ):
                # Una promoción parcial de productos finales deja inválido el
                # contador de ventanas. Se reinicia el conjunto para impedir
                # que un raster vacío reemplace una salida ya calculada.
                progress_path.unlink()
                for path in expected_partials:
                    if path.exists():
                        path.unlink()

            tags = {
                "target": shared["target"]["field"],
                "trained_on": "development_only",
                "region_id": region_id,
                "resolution_m": resolution,
                "feature_count": len(feature_columns),
                "independent_pixels_in_training": 0,
            }
            for model_id in active_models:
                class_partial = partial_path(paths_by_model[model_id]["class"])
                confidence_partial = partial_path(
                    paths_by_model[model_id]["confidence"]
                )
                if not class_partial.exists():
                    create_output(
                        class_partial,
                        grid,
                        "uint8",
                        nodata_class,
                        block_size,
                        str(predict_config.get("compression", "DEFLATE")),
                        {**tags, "model_id": model_id, "product": "class"},
                    )
                if (
                    model_id in confidence_models
                    and not confidence_partial.exists()
                ):
                    create_output(
                        confidence_partial,
                        grid,
                        "float32",
                        -9999.0,
                        block_size,
                        str(predict_config.get("compression", "DEFLATE")),
                        {**tags, "model_id": model_id, "product": "confidence"},
                    )
            if extrap_active and not partial_path(extrap_final).exists():
                create_output(
                    partial_path(extrap_final),
                    grid,
                    "uint8",
                    255,
                    block_size,
                    str(predict_config.get("compression", "DEFLATE")),
                    {**tags, "product": "outside_development_range_count"},
                )

            signature = run_signature(
                manifest,
                region,
                grid,
                active_models,
            )
            completed_windows = 0
            if progress_path.exists():
                if not bool(predict_config.get("resume", True)):
                    raise ValueError(
                        f"Existe progreso parcial y resume=false: {progress_path}"
                    )
                progress = json.loads(progress_path.read_text(encoding="utf-8"))
                if progress.get("run_signature") != signature:
                    raise ValueError(
                        f"El progreso parcial no corresponde a esta ejecución: {progress_path}"
                    )
                completed_windows = int(progress.get("completed_windows", 0))

            windows = grid_windows(
                int(grid["width"]),
                int(grid["height"]),
                block_size,
            )
            checkpoint_every = max(
                1, int(predict_config.get("checkpoint_every_windows", 10))
            )
            require_all = bool(
                predict_config.get("require_all_predictors_valid", True)
            )
            with contextlib.ExitStack() as source_stack:
                source_vrts = open_source_vrts(
                    source_stack,
                    region,
                    grid,
                    int(predict_config.get("predictor_threads", 2)),
                )
                for batch_start in range(
                    completed_windows, len(windows), checkpoint_every
                ):
                    batch_end = min(
                        batch_start + checkpoint_every, len(windows)
                    )
                    with contextlib.ExitStack() as output_stack:
                        class_outputs = {
                            model_id: output_stack.enter_context(
                                rasterio.open(
                                    partial_path(
                                        paths_by_model[model_id]["class"]
                                    ),
                                    "r+",
                                )
                            )
                            for model_id in active_models
                        }
                        confidence_outputs = {}
                        if confidence_models:
                            confidence_outputs = {
                                model_id: output_stack.enter_context(
                                    rasterio.open(
                                        partial_path(
                                            paths_by_model[model_id][
                                                "confidence"
                                            ]
                                        ),
                                        "r+",
                                    )
                                )
                                for model_id in active_models
                                if model_id in confidence_models
                            }
                        extrap_output = (
                            output_stack.enter_context(
                                rasterio.open(
                                    partial_path(extrap_final), "r+"
                                )
                            )
                            if extrap_active
                            else None
                        )

                        for window in windows[batch_start:batch_end]:
                            X, valid = read_feature_window(
                                source_vrts,
                                window,
                                len(feature_columns),
                                require_all,
                            )
                            if extrap_output is not None:
                                extrapolated = outside_range_count(
                                    X,
                                    valid,
                                    feature_columns,
                                    manifest[
                                        "development_only_feature_ranges"
                                    ],
                                ).reshape(
                                    int(window.height), int(window.width)
                                )
                                extrap_output.write(
                                    extrapolated, 1, window=window
                                )

                            for model_id in active_models:
                                class_array = np.zeros(
                                    len(X), dtype=np.uint8
                                )
                                confidence_array = np.full(
                                    len(X), -9999.0, dtype=np.float32
                                )
                                confidence_method = (
                                    "not_evaluated_no_valid_pixels"
                                )
                                if valid.any():
                                    result = runners[model_id].predict(X[valid])
                                    unexpected = sorted(
                                        set(map(int, np.unique(result.classes)))
                                        - expected_classes
                                    )
                                    if unexpected:
                                        raise ValueError(
                                            f"{model_id} produjo clases no homologadas: "
                                            f"{unexpected}"
                                        )
                                    class_array[valid] = result.classes
                                    if result.confidence is not None:
                                        confidence_array[valid] = (
                                            result.confidence
                                        )
                                    confidence_method = (
                                        result.confidence_method
                                    )
                                class_outputs[model_id].write(
                                    class_array.reshape(
                                        int(window.height),
                                        int(window.width),
                                    ),
                                    1,
                                    window=window,
                                )
                                if model_id in confidence_outputs:
                                    confidence_outputs[model_id].write(
                                        confidence_array.reshape(
                                            int(window.height),
                                            int(window.width),
                                        ),
                                        1,
                                        window=window,
                                    )
                                    confidence_outputs[
                                        model_id
                                    ].update_tags(
                                        confidence_method=confidence_method
                                    )

                    atomic_write_json(
                        {
                            "run_signature": signature,
                            "region_id": region_id,
                            "resolution_m": resolution,
                            "models": active_models,
                            "completed_windows": batch_end,
                            "total_windows": len(windows),
                            "updated_at_utc": datetime.now(
                                timezone.utc
                            ).isoformat(),
                        },
                        progress_path,
                    )
                    print(
                        f"Zona {region_id} | {resolution} m | "
                        f"ventanas {batch_end}/{len(windows)}"
                    )

            for model_id in active_models:
                os.replace(
                    partial_path(paths_by_model[model_id]["class"]),
                    paths_by_model[model_id]["class"],
                )
                if model_id in confidence_models:
                    os.replace(
                        partial_path(paths_by_model[model_id]["confidence"]),
                        paths_by_model[model_id]["confidence"],
                    )
            if extrap_active:
                os.replace(partial_path(extrap_final), extrap_final)
            if progress_path.exists():
                progress_path.unlink()

            for model_id in model_ids:
                class_path = paths_by_model[model_id]["class"]
                if class_path.exists():
                    areas = class_area_table(
                        class_path,
                        model_id,
                        region_id,
                        resolution,
                        class_catalog,
                    )
                    area_tables.append(areas)
                    style_fields = style_inventory_fields(
                        class_path,
                        class_catalog,
                        style_config,
                        nodata_class,
                    )
                    run_rows.append(
                        {
                            "model_id": model_id,
                            "region_id": region_id,
                            "resolution_m": resolution,
                            "class_raster": str(class_path),
                            "confidence_raster": str(
                                paths_by_model[model_id]["confidence"]
                            )
                            if model_id in confidence_models
                            else "",
                            "extrapolation_raster": str(extrap_final),
                            "valid_pixels": int(
                                areas["pixel_count"].sum()
                            ),
                            "status": "complete",
                            **style_fields,
                        }
                    )

    tables_dir = output_dir / "tables"
    reports_dir = output_dir / "reports"
    tables_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    areas = (
        pd.concat(area_tables, ignore_index=True)
        if area_tables
        else pd.DataFrame()
    )
    runs = pd.DataFrame(run_rows)
    areas.to_csv(
        tables_dir / "prediction_class_areas.csv",
        index=False,
        encoding="utf-8-sig",
    )
    runs.to_csv(
        tables_dir / "prediction_run_inventory.csv",
        index=False,
        encoding="utf-8-sig",
    )
    report_lines = [
        "# Actividad 4.12 - Predicción cartográfica",
        "",
        "- Los artefactos se cargaron congelados.",
        "- Ningún cuadrante independiente se incorporó al modelo.",
        "- La predicción cubre todos los píxeles válidos de cada zona.",
        "- Los rasters de clase incluyen paleta GeoTIFF y estilos QML, SLD y CLR.",
        f"- Modelos: {', '.join(model_ids)}",
        f"- Resoluciones: {', '.join(map(str, sorted(resolutions)))} m",
        "",
        "## Salidas",
        "",
        dataframe_to_markdown(runs),
        "",
        "## Superficie por clase",
        "",
        dataframe_to_markdown(areas, max_rows=200),
    ]
    report_path = reports_dir / "a4_12_raster_prediction_report.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"Reporte: {report_path}")


if __name__ == "__main__":
    main()
