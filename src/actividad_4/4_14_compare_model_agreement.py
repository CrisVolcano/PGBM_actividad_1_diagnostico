#!/usr/bin/env python3
"""Actividad 4.14 - Acuerdo espacial entre modelos de clasificación.

Compara mapas ya predichos por RF, SVM, XGBoost y DNN. No carga artefactos,
no entrena modelos y no modifica las predicciones originales. Genera:

* nivel de acuerdo entre los cuatro modelos;
* clase de consenso estricto, solo con al menos tres votos;
* clase propuesta por los otros tres cuando RF es el único disidente;
* número de votos para la clase ``construido``;
* tablas de acuerdo por zona, clase, pareja de modelos y patrón de votos.
"""

from __future__ import annotations

import argparse
import contextlib
import itertools
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio


SCRIPT_PATH = Path(__file__).resolve()
sys.path.insert(0, str(SCRIPT_PATH.parent))

from raster_prediction_common import (  # noqa: E402
    REPO_ROOT,
    atomic_write_json,
    dataframe_to_markdown,
    parse_csv_list,
    read_config,
    resolve_path,
    write_class_raster_styles,
)


DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_11_13_raster_prediction.yaml"

AGREEMENT_CATEGORIES = [
    {
        "value": 1,
        "label": "Sin consenso (empate 2-2 o cuatro clases)",
        "color_hex": "#D73027",
    },
    {
        "value": 2,
        "label": "Pluralidad débil 2-1-1",
        "color_hex": "#FC8D59",
    },
    {
        "value": 3,
        "label": "Mayoría 3 de 4",
        "color_hex": "#91CF60",
    },
    {
        "value": 4,
        "label": "Unanimidad 4 de 4",
        "color_hex": "#1A9850",
    },
]

BUILT_VOTE_CATEGORIES = [
    {"value": 0, "label": "Ningún modelo", "color_hex": "#F2F2F2"},
    {"value": 1, "label": "Un modelo", "color_hex": "#FEE8C8"},
    {"value": 2, "label": "Dos modelos", "color_hex": "#FDBB84"},
    {"value": 3, "label": "Tres modelos", "color_hex": "#E34A33"},
    {"value": 4, "label": "Cuatro modelos", "color_hex": "#B30000"},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--regions", help="IDs de zona separados por coma.")
    parser.add_argument(
        "--resolutions",
        help="Resoluciones separadas por coma; por defecto 10,20.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recalcula incluso si existe una caché válida.",
    )
    return parser.parse_args()


def prediction_path(
    prediction_dir: Path,
    model_id: str,
    region_id: str,
    resolution: int,
) -> Path:
    stem = f"{region_id}__{model_id}__id_1_propuesta__{resolution}m"
    return (
        prediction_dir
        / model_id
        / f"{resolution}m"
        / f"region_{region_id}"
        / f"{stem}.tif"
    )


def output_paths(
    output_dir: Path,
    region_id: str,
    resolution: int,
) -> dict[str, Path]:
    directory = output_dir / f"{resolution}m" / f"region_{region_id}"
    return {
        "agreement": directory
        / f"{region_id}__model_agreement_level__{resolution}m.tif",
        "consensus": directory
        / f"{region_id}__strict_consensus_id_1_propuesta__{resolution}m.tif",
        "reference_outvoted": directory
        / (
            f"{region_id}__rf_outvoted_consensus_"
            f"id_1_propuesta__{resolution}m.tif"
        ),
        "focus_votes": directory
        / f"{region_id}__built_class_vote_count__{resolution}m.tif",
    }


def partial_path(path: Path) -> Path:
    return path.with_name(path.stem + ".partial" + path.suffix)


def cache_path(
    output_dir: Path,
    region_id: str,
    resolution: int,
) -> Path:
    return (
        output_dir
        / "cache"
        / f"region_{region_id}__{resolution}m.json"
    )


def source_fingerprints(
    prediction_dir: Path,
    model_ids: list[str],
    region_id: str,
    resolution: int,
) -> dict[str, dict[str, Any]]:
    fingerprints: dict[str, dict[str, Any]] = {}
    for model_id in model_ids:
        path = prediction_path(
            prediction_dir,
            model_id,
            region_id,
            resolution,
        )
        if not path.exists():
            raise FileNotFoundError(f"Falta mapa de predicción: {path}")
        stat = path.stat()
        fingerprints[model_id] = {
            "path": str(path.resolve()),
            "size_bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }
    return fingerprints


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, np.generic):
        return json_ready(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def assert_aligned(
    sources: dict[str, rasterio.io.DatasetReader],
    expected_resolution: int,
) -> None:
    reference_model, reference = next(iter(sources.items()))
    if reference.count != 1:
        raise ValueError(f"{reference.name}: se esperaba una banda.")
    if reference.crs is None:
        raise ValueError(f"{reference.name}: raster sin CRS.")
    observed_resolution = (
        abs(float(reference.transform.a)),
        abs(float(reference.transform.e)),
    )
    if not np.allclose(
        observed_resolution,
        (expected_resolution, expected_resolution),
        atol=1e-6,
    ):
        raise ValueError(
            f"{reference.name}: resolución observada={observed_resolution}; "
            f"esperada={expected_resolution}."
        )
    for model_id, source in sources.items():
        if source.count != 1:
            raise ValueError(f"{source.name}: se esperaba una banda.")
        if (
            source.crs != reference.crs
            or source.width != reference.width
            or source.height != reference.height
            or not source.transform.almost_equals(reference.transform)
        ):
            raise ValueError(
                f"{model_id} no está alineado con {reference_model}: "
                f"{source.name}"
            )


def create_output(
    path: Path,
    reference: rasterio.io.DatasetReader,
    nodata: int,
    compression: str,
    tags: dict[str, Any],
) -> rasterio.io.DatasetWriter:
    temporary = partial_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if temporary.exists():
        temporary.unlink()
    profile = reference.profile.copy()
    profile.pop("photometric", None)
    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)
    profile.update(
        driver="GTiff",
        count=1,
        dtype="uint8",
        nodata=nodata,
        compress=compression,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        BIGTIFF="IF_SAFER",
    )
    destination = rasterio.open(temporary, "w", **profile)
    destination.update_tags(
        **{key: str(value) for key, value in tags.items()}
    )
    return destination


def hex_to_rgba(color: str) -> tuple[int, int, int, int]:
    normalized = str(color).strip().lstrip("#")
    if len(normalized) != 6:
        raise ValueError(f"Color hexadecimal inválido: {color}")
    return (
        int(normalized[0:2], 16),
        int(normalized[2:4], 16),
        int(normalized[4:6], 16),
        255,
    )


def write_generic_qml(
    path: Path,
    categories: list[dict[str, Any]],
    nodata: int,
) -> None:
    root = ET.Element(
        "qgis",
        {"version": "3.34.0", "styleCategories": "Symbology"},
    )
    pipe = ET.SubElement(root, "pipe")
    renderer = ET.SubElement(
        pipe,
        "rasterrenderer",
        {
            "type": "paletted",
            "band": "1",
            "opacity": "1",
            "alphaBand": "-1",
        },
    )
    ET.SubElement(renderer, "rasterTransparency")
    palette = ET.SubElement(renderer, "colorPalette")
    ET.SubElement(
        palette,
        "paletteEntry",
        {
            "value": str(nodata),
            "color": "#000000",
            "alpha": "0",
            "label": "Sin datos",
        },
    )
    for category in categories:
        ET.SubElement(
            palette,
            "paletteEntry",
            {
                "value": str(category["value"]),
                "color": str(category["color_hex"]),
                "alpha": "255",
                "label": str(category["label"]),
            },
        )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_generic_style(
    raster_path: Path,
    categories: list[dict[str, Any]],
    nodata: int,
    palette_name: str,
) -> dict[str, str]:
    color_map = {
        nodata: (0, 0, 0, 0),
        **{
            int(category["value"]): hex_to_rgba(
                str(category["color_hex"])
            )
            for category in categories
        },
    }
    with rasterio.open(raster_path, "r+") as raster:
        raster.write_colormap(1, color_map)
        raster.update_tags(style_palette=palette_name)
    qml_path = raster_path.with_suffix(".qml")
    write_generic_qml(qml_path, categories, nodata)
    legend_path = raster_path.with_suffix(".csv")
    pd.DataFrame(categories).to_csv(
        legend_path,
        index=False,
        encoding="utf-8-sig",
    )
    return {"qml": str(qml_path), "legend_csv": str(legend_path)}


def pattern_type(values: tuple[int, ...]) -> str:
    frequencies = sorted(Counter(values).values(), reverse=True)
    if frequencies == [4]:
        return "unanimity_4"
    if frequencies == [3, 1]:
        return "majority_3_1"
    if frequencies == [2, 1, 1]:
        return "plurality_2_1_1"
    if frequencies == [2, 2]:
        return "tie_2_2"
    if frequencies == [1, 1, 1, 1]:
        return "all_different"
    raise ValueError(f"Patrón de cuatro votos inesperado: {values}")


def decode_pattern(
    encoded: int,
    class_ids: list[int],
    model_count: int,
) -> tuple[int, ...]:
    base = len(class_ids)
    indexes = [0] * model_count
    remaining = int(encoded)
    for position in range(model_count - 1, -1, -1):
        indexes[position] = remaining % base
        remaining //= base
    return tuple(class_ids[index] for index in indexes)


def process_combination(
    prediction_dir: Path,
    output_dir: Path,
    model_ids: list[str],
    reference_model_id: str,
    region_id: str,
    resolution: int,
    class_ids: list[int],
    labels: dict[int, str],
    class_catalog: list[dict[str, Any]],
    class_style_config: dict[str, Any],
    minimum_consensus_votes: int,
    focus_class_id: int,
    compression: str,
) -> dict[str, Any]:
    source_paths = {
        model_id: prediction_path(
            prediction_dir,
            model_id,
            region_id,
            resolution,
        )
        for model_id in model_ids
    }
    missing = [str(path) for path in source_paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Faltan mapas de predicción: " + "; ".join(missing)
        )
    paths = output_paths(output_dir, region_id, resolution)
    model_count = len(model_ids)
    reference_index = model_ids.index(reference_model_id)
    class_lookup = np.full(256, -1, dtype=np.int16)
    for index, class_id in enumerate(class_ids):
        class_lookup[class_id] = index

    status_counts = {
        "unanimity_4": 0,
        "majority_3_1": 0,
        "plurality_2_1_1": 0,
        "tie_2_2": 0,
        "all_different": 0,
    }
    pairwise_counts = {
        pair: 0 for pair in itertools.combinations(range(model_count), 2)
    }
    model_prediction_counts = {
        model_id: np.zeros(len(class_ids), dtype=np.int64)
        for model_id in model_ids
    }
    any_vote_counts = np.zeros(len(class_ids), dtype=np.int64)
    strict_class_counts = np.zeros(len(class_ids), dtype=np.int64)
    unanimous_class_counts = np.zeros(len(class_ids), dtype=np.int64)
    reference_outvoted_class_counts = np.zeros(
        len(class_ids), dtype=np.int64
    )
    dissent_counts = np.zeros(model_count, dtype=np.int64)
    focus_vote_counts = np.zeros(model_count + 1, dtype=np.int64)
    encoded_pattern_counts: dict[int, int] = defaultdict(int)
    valid_pixels = 0
    partial_coverage_pixels = 0

    tags = {
        "region_id": region_id,
        "resolution_m": resolution,
        "models": ",".join(model_ids),
        "model_count": model_count,
        "strict_consensus_min_votes": minimum_consensus_votes,
        "reference_model": reference_model_id,
        "training_or_prediction_performed": False,
    }
    with contextlib.ExitStack() as stack:
        sources = {
            model_id: stack.enter_context(rasterio.open(path))
            for model_id, path in source_paths.items()
        }
        assert_aligned(sources, resolution)
        reference = sources[model_ids[0]]
        destinations = {
            "agreement": stack.enter_context(
                create_output(
                    paths["agreement"],
                    reference,
                    0,
                    compression,
                    {**tags, "product": "model_agreement_level"},
                )
            ),
            "consensus": stack.enter_context(
                create_output(
                    paths["consensus"],
                    reference,
                    0,
                    compression,
                    {
                        **tags,
                        "product": "strict_consensus_id_1_propuesta",
                    },
                )
            ),
            "reference_outvoted": stack.enter_context(
                create_output(
                    paths["reference_outvoted"],
                    reference,
                    0,
                    compression,
                    {
                        **tags,
                        "product": "reference_outvoted_consensus_class",
                    },
                )
            ),
            "focus_votes": stack.enter_context(
                create_output(
                    paths["focus_votes"],
                    reference,
                    255,
                    compression,
                    {
                        **tags,
                        "product": "focus_class_vote_count",
                        "focus_class_id": focus_class_id,
                    },
                )
            ),
        }

        for _, window in reference.block_windows(1):
            arrays: list[np.ndarray] = []
            valid_masks: list[np.ndarray] = []
            for model_id in model_ids:
                values = sources[model_id].read(
                    1,
                    window=window,
                    masked=True,
                )
                array = np.asarray(values.data, dtype=np.uint8).reshape(-1)
                valid = ~np.ma.getmaskarray(values).reshape(-1)
                valid &= array != int(sources[model_id].nodata or 0)
                observed = set(map(int, np.unique(array[valid])))
                unexpected = sorted(observed - set(class_ids))
                if unexpected:
                    raise ValueError(
                        f"{sources[model_id].name} contiene clases no "
                        f"homologadas: {unexpected}"
                    )
                arrays.append(array)
                valid_masks.append(valid)

            all_valid = np.logical_and.reduce(valid_masks)
            any_valid = np.logical_or.reduce(valid_masks)
            partial_coverage_pixels += int((any_valid & ~all_valid).sum())
            window_pixels = len(arrays[0])
            agreement_output = np.zeros(window_pixels, dtype=np.uint8)
            consensus_output = np.zeros(window_pixels, dtype=np.uint8)
            reference_outvoted_output = np.zeros(
                window_pixels, dtype=np.uint8
            )
            focus_votes_output = np.full(
                window_pixels, 255, dtype=np.uint8
            )

            if all_valid.any():
                values = np.stack(
                    [array[all_valid] for array in arrays],
                    axis=0,
                )
                rows = values.shape[1]
                valid_pixels += rows
                vote_counts = np.zeros(
                    (rows, len(class_ids)),
                    dtype=np.uint8,
                )
                indexed_values = class_lookup[values]
                if (indexed_values < 0).any():
                    raise ValueError("No se pudo codificar una clase válida.")
                for model_index in range(model_count):
                    vote_counts[
                        np.arange(rows),
                        indexed_values[model_index],
                    ] += 1

                maximum_votes = vote_counts.max(axis=1)
                tied_maximum = (
                    vote_counts == maximum_votes[:, None]
                ).sum(axis=1)
                winner_indexes = vote_counts.argmax(axis=1)
                winner_classes = np.asarray(
                    class_ids, dtype=np.uint8
                )[winner_indexes]

                level = np.ones(rows, dtype=np.uint8)
                level[
                    (maximum_votes == 2) & (tied_maximum == 1)
                ] = 2
                level[maximum_votes == 3] = 3
                level[maximum_votes == 4] = 4
                agreement_output[all_valid] = level

                strict = maximum_votes >= minimum_consensus_votes
                strict_values = np.zeros(rows, dtype=np.uint8)
                strict_values[strict] = winner_classes[strict]
                consensus_output[all_valid] = strict_values

                reference_outvoted = (
                    (maximum_votes == 3)
                    & (values[reference_index] != winner_classes)
                )
                outvoted_values = np.zeros(rows, dtype=np.uint8)
                outvoted_values[reference_outvoted] = winner_classes[
                    reference_outvoted
                ]
                reference_outvoted_output[all_valid] = outvoted_values

                focus_votes = (values == focus_class_id).sum(axis=0).astype(
                    np.uint8
                )
                focus_votes_output[all_valid] = focus_votes

                unanimity = maximum_votes == 4
                majority = maximum_votes == 3
                plurality = (
                    (maximum_votes == 2) & (tied_maximum == 1)
                )
                tie = (maximum_votes == 2) & (tied_maximum == 2)
                all_different = maximum_votes == 1
                status_counts["unanimity_4"] += int(unanimity.sum())
                status_counts["majority_3_1"] += int(majority.sum())
                status_counts["plurality_2_1_1"] += int(plurality.sum())
                status_counts["tie_2_2"] += int(tie.sum())
                status_counts["all_different"] += int(
                    all_different.sum()
                )

                for left, right in pairwise_counts:
                    pairwise_counts[(left, right)] += int(
                        (values[left] == values[right]).sum()
                    )
                for model_index, model_id in enumerate(model_ids):
                    model_prediction_counts[model_id] += np.bincount(
                        indexed_values[model_index],
                        minlength=len(class_ids),
                    )
                    dissent_counts[model_index] += int(
                        (
                            majority
                            & (values[model_index] != winner_classes)
                        ).sum()
                    )
                for class_index in range(len(class_ids)):
                    any_vote_counts[class_index] += int(
                        (indexed_values == class_index).any(axis=0).sum()
                    )
                    strict_class_counts[class_index] += int(
                        (strict & (winner_indexes == class_index)).sum()
                    )
                    unanimous_class_counts[class_index] += int(
                        (
                            unanimity
                            & (winner_indexes == class_index)
                        ).sum()
                    )
                    reference_outvoted_class_counts[class_index] += int(
                        (
                            reference_outvoted
                            & (winner_indexes == class_index)
                        ).sum()
                    )
                focus_vote_counts += np.bincount(
                    focus_votes,
                    minlength=model_count + 1,
                )

                encoded = np.zeros(rows, dtype=np.int32)
                for model_index in range(model_count):
                    encoded = (
                        encoded * len(class_ids)
                        + indexed_values[model_index]
                    )
                unique_patterns, frequencies = np.unique(
                    encoded,
                    return_counts=True,
                )
                for encoded_value, frequency in zip(
                    unique_patterns, frequencies
                ):
                    encoded_pattern_counts[int(encoded_value)] += int(
                        frequency
                    )

            shape = (int(window.height), int(window.width))
            destinations["agreement"].write(
                agreement_output.reshape(shape), 1, window=window
            )
            destinations["consensus"].write(
                consensus_output.reshape(shape), 1, window=window
            )
            destinations["reference_outvoted"].write(
                reference_outvoted_output.reshape(shape),
                1,
                window=window,
            )
            destinations["focus_votes"].write(
                focus_votes_output.reshape(shape), 1, window=window
            )

        pixel_area_ha = abs(
            float(
                reference.transform.a * reference.transform.e
                - reference.transform.b * reference.transform.d
            )
        ) / 10000.0

    for path in paths.values():
        os.replace(partial_path(path), path)

    agreement_styles = write_generic_style(
        paths["agreement"],
        AGREEMENT_CATEGORIES,
        0,
        "model_agreement_level_v1",
    )
    focus_styles = write_generic_style(
        paths["focus_votes"],
        BUILT_VOTE_CATEGORIES,
        255,
        "built_class_vote_count_v1",
    )
    consensus_styles = write_class_raster_styles(
        paths["consensus"],
        class_catalog,
        class_style_config,
        0,
    )
    outvoted_styles = write_class_raster_styles(
        paths["reference_outvoted"],
        class_catalog,
        class_style_config,
        0,
    )

    summary = {
        "region_id": region_id,
        "resolution_m": resolution,
        "valid_pixels": valid_pixels,
        "partial_coverage_pixels": partial_coverage_pixels,
        **status_counts,
        "strict_consensus_pixels": (
            status_counts["unanimity_4"] + status_counts["majority_3_1"]
        ),
        "unanimity_pct": (
            status_counts["unanimity_4"] / valid_pixels
            if valid_pixels
            else np.nan
        ),
        "majority_3_1_pct": (
            status_counts["majority_3_1"] / valid_pixels
            if valid_pixels
            else np.nan
        ),
        "strict_consensus_pct": (
            (
                status_counts["unanimity_4"]
                + status_counts["majority_3_1"]
            )
            / valid_pixels
            if valid_pixels
            else np.nan
        ),
        "plurality_2_1_1_pct": (
            status_counts["plurality_2_1_1"] / valid_pixels
            if valid_pixels
            else np.nan
        ),
        "tie_2_2_pct": (
            status_counts["tie_2_2"] / valid_pixels
            if valid_pixels
            else np.nan
        ),
        "all_different_pct": (
            status_counts["all_different"] / valid_pixels
            if valid_pixels
            else np.nan
        ),
        "valid_area_ha": valid_pixels * pixel_area_ha,
        "strict_consensus_area_ha": (
            status_counts["unanimity_4"]
            + status_counts["majority_3_1"]
        )
        * pixel_area_ha,
    }

    pairwise_rows = [
        {
            "region_id": region_id,
            "resolution_m": resolution,
            "model_a": model_ids[left],
            "model_b": model_ids[right],
            "valid_pixels": valid_pixels,
            "agreement_pixels": count,
            "agreement_pct": (
                count / valid_pixels if valid_pixels else np.nan
            ),
        }
        for (left, right), count in pairwise_counts.items()
    ]
    class_rows = []
    for class_index, class_id in enumerate(class_ids):
        row = {
            "region_id": region_id,
            "resolution_m": resolution,
            "class_id": class_id,
            "class_label": labels[class_id],
            "any_model_vote_pixels": int(any_vote_counts[class_index]),
            "strict_consensus_pixels": int(
                strict_class_counts[class_index]
            ),
            "unanimous_pixels": int(
                unanimous_class_counts[class_index]
            ),
            "rf_outvoted_consensus_pixels": int(
                reference_outvoted_class_counts[class_index]
            ),
            "strict_consensus_area_ha": (
                strict_class_counts[class_index] * pixel_area_ha
            ),
        }
        row.update(
            {
                f"{model_id}_predicted_pixels": int(
                    model_prediction_counts[model_id][class_index]
                )
                for model_id in model_ids
            }
        )
        class_rows.append(row)
    dissent_rows = [
        {
            "region_id": region_id,
            "resolution_m": resolution,
            "model_id": model_id,
            "majority_3_1_pixels": status_counts["majority_3_1"],
            "sole_dissent_pixels": int(dissent_counts[index]),
            "pct_of_majority_3_1": (
                dissent_counts[index] / status_counts["majority_3_1"]
                if status_counts["majority_3_1"]
                else np.nan
            ),
        }
        for index, model_id in enumerate(model_ids)
    ]
    focus_rows = [
        {
            "region_id": region_id,
            "resolution_m": resolution,
            "focus_class_id": focus_class_id,
            "focus_class_label": labels[focus_class_id],
            "model_votes": votes,
            "pixel_count": int(focus_vote_counts[votes]),
            "pct_valid_pixels": (
                focus_vote_counts[votes] / valid_pixels
                if valid_pixels
                else np.nan
            ),
            "area_ha": focus_vote_counts[votes] * pixel_area_ha,
        }
        for votes in range(model_count + 1)
    ]
    pattern_rows = []
    for encoded, count in encoded_pattern_counts.items():
        predictions = decode_pattern(encoded, class_ids, model_count)
        frequencies = Counter(predictions)
        maximum = max(frequencies.values())
        winners = [
            class_id
            for class_id, frequency in frequencies.items()
            if frequency == maximum
        ]
        row = {
            "region_id": region_id,
            "resolution_m": resolution,
            "pattern_type": pattern_type(predictions),
            "maximum_votes": maximum,
            "unique_winner_class": (
                winners[0] if len(winners) == 1 else np.nan
            ),
            "pixel_count": count,
            "pct_valid_pixels": (
                count / valid_pixels if valid_pixels else np.nan
            ),
        }
        row.update(
            {
                f"{model_id}_class": predictions[index]
                for index, model_id in enumerate(model_ids)
            }
        )
        pattern_rows.append(row)
    inventory = {
        "region_id": region_id,
        "resolution_m": resolution,
        "agreement_raster": str(paths["agreement"]),
        "strict_consensus_raster": str(paths["consensus"]),
        "rf_outvoted_consensus_raster": str(
            paths["reference_outvoted"]
        ),
        "built_vote_count_raster": str(paths["focus_votes"]),
        "agreement_qml": agreement_styles["qml"],
        "consensus_qml": consensus_styles["qml"],
        "rf_outvoted_qml": outvoted_styles["qml"],
        "built_votes_qml": focus_styles["qml"],
    }
    return {
        "summary": summary,
        "pairwise": pairwise_rows,
        "classes": class_rows,
        "dissent": dissent_rows,
        "focus": focus_rows,
        "patterns": pattern_rows,
        "inventory": inventory,
    }


def global_summary(summary: pd.DataFrame) -> pd.DataFrame:
    count_columns = [
        "valid_pixels",
        "partial_coverage_pixels",
        "unanimity_4",
        "majority_3_1",
        "plurality_2_1_1",
        "tie_2_2",
        "all_different",
        "strict_consensus_pixels",
    ]
    grouped = (
        summary.groupby("resolution_m", as_index=False)[count_columns]
        .sum()
        .sort_values("resolution_m")
    )
    valid = grouped["valid_pixels"].replace(0, np.nan)
    for count_column in [
        "unanimity_4",
        "majority_3_1",
        "plurality_2_1_1",
        "tie_2_2",
        "all_different",
        "strict_consensus_pixels",
    ]:
        grouped[f"{count_column}_pct"] = grouped[count_column] / valid
    return grouped


def main() -> None:
    args = parse_args()
    config = read_config(args.config)
    shared = config["shared"]
    agreement_config = config.get("agreement")
    if not isinstance(agreement_config, dict):
        raise ValueError("Falta la sección YAML agreement.")
    model_ids = [
        str(model_id) for model_id in agreement_config["model_ids"]
    ]
    if len(model_ids) != 4 or len(set(model_ids)) != 4:
        raise ValueError(
            "A4.14 requiere exactamente cuatro modelos distintos."
        )
    unknown_models = sorted(set(model_ids) - set(shared["models"]))
    if unknown_models:
        raise ValueError(f"Modelos no configurados: {unknown_models}")
    reference_model_id = str(
        agreement_config.get("reference_model_id", "rf")
    )
    if reference_model_id not in model_ids:
        raise ValueError("reference_model_id no pertenece a model_ids.")
    minimum_votes = int(
        agreement_config.get("minimum_strict_consensus_votes", 3)
    )
    if minimum_votes != 3:
        raise ValueError(
            "A4.14 exige minimum_strict_consensus_votes=3."
        )
    regions = (
        parse_csv_list(args.regions, str)
        or [str(region) for region in shared["regions"]]
    )
    resolutions = (
        parse_csv_list(args.resolutions, int)
        or [
            int(resolution)
            for resolution in agreement_config["resolutions_m"]
        ]
    )
    prediction_dir = resolve_path(agreement_config["prediction_dir"])
    output_dir = resolve_path(agreement_config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    class_catalog = pd.read_csv(
        resolve_path(shared["paths"]["class_catalog"]),
        encoding="utf-8-sig",
    )[["id_1_propuesta", "nivel_1_propuesta"]]
    class_catalog["id_1_propuesta"] = pd.to_numeric(
        class_catalog["id_1_propuesta"], errors="raise"
    ).astype(int)
    class_records = class_catalog.to_dict(orient="records")
    class_ids = sorted(map(int, shared["target"]["expected_classes"]))
    observed_classes = sorted(class_catalog["id_1_propuesta"].tolist())
    if observed_classes != class_ids:
        raise ValueError(
            f"Catálogo={observed_classes}; esperado={class_ids}."
        )
    labels = {
        int(row["id_1_propuesta"]): str(row["nivel_1_propuesta"])
        for row in class_records
    }
    focus_class_id = int(agreement_config.get("focus_class_id", 23))
    if focus_class_id not in class_ids:
        raise ValueError("focus_class_id no es una clase homologada.")

    result_keys = [
        "summary",
        "pairwise",
        "classes",
        "dissent",
        "focus",
        "patterns",
        "inventory",
    ]

    def signature_for(region_id: str, resolution: int) -> dict[str, Any]:
        return json_ready(
            {
                "source_fingerprints": source_fingerprints(
                    prediction_dir,
                    model_ids,
                    region_id,
                    resolution,
                ),
                "model_ids": model_ids,
                "reference_model_id": reference_model_id,
                "minimum_consensus_votes": minimum_votes,
                "focus_class_id": focus_class_id,
                "class_ids": class_ids,
                "class_style": shared["target"]["style"],
            }
        )

    for resolution in sorted(set(resolutions)):
        for region_id in regions:
            combination_cache = cache_path(
                output_dir, region_id, resolution
            )
            signature = signature_for(region_id, resolution)
            final_outputs = output_paths(
                output_dir, region_id, resolution
            ).values()
            cached_payload: dict[str, Any] | None = None
            if (
                not args.force
                and combination_cache.exists()
                and all(path.exists() for path in final_outputs)
            ):
                candidate = json.loads(
                    combination_cache.read_text(encoding="utf-8")
                )
                if candidate.get("signature") == signature:
                    cached_payload = candidate
            if cached_payload is not None:
                print(
                    f"Usando caché | zona {region_id} | "
                    f"{resolution} m"
                )
                continue
            result = process_combination(
                prediction_dir=prediction_dir,
                output_dir=output_dir,
                model_ids=model_ids,
                reference_model_id=reference_model_id,
                region_id=region_id,
                resolution=resolution,
                class_ids=class_ids,
                labels=labels,
                class_catalog=class_records,
                class_style_config=shared["target"]["style"],
                minimum_consensus_votes=minimum_votes,
                focus_class_id=focus_class_id,
                compression=str(
                    agreement_config.get("compression", "DEFLATE")
                ),
            )
            atomic_write_json(
                {
                    "signature": signature,
                    "result": json_ready(result),
                },
                combination_cache,
            )
            print(
                f"Acuerdo calculado | zona {region_id} | "
                f"{resolution} m"
            )

    expected_regions = [str(region) for region in shared["regions"]]
    expected_resolutions = [
        int(resolution)
        for resolution in agreement_config["resolutions_m"]
    ]
    cached_results: list[dict[str, Any]] = []
    missing_cache: list[str] = []
    for resolution in sorted(set(expected_resolutions)):
        for region_id in expected_regions:
            combination_cache = cache_path(
                output_dir, region_id, resolution
            )
            if not combination_cache.exists():
                missing_cache.append(f"zona {region_id}, {resolution} m")
                continue
            payload = json.loads(
                combination_cache.read_text(encoding="utf-8")
            )
            if payload.get("signature") != signature_for(
                region_id, resolution
            ):
                missing_cache.append(
                    f"zona {region_id}, {resolution} m (caché obsoleta)"
                )
                continue
            if not all(
                path.exists()
                for path in output_paths(
                    output_dir, region_id, resolution
                ).values()
            ):
                missing_cache.append(
                    f"zona {region_id}, {resolution} m (salida incompleta)"
                )
                continue
            cached_results.append(payload["result"])
    if missing_cache:
        print(
            f"Caché completa: {len(cached_results)}/"
            f"{len(expected_regions) * len(expected_resolutions)}"
        )
        print("Pendientes: " + "; ".join(missing_cache))
        return

    collected: dict[str, list[Any]] = {
        "summary": [],
        "pairwise": [],
        "classes": [],
        "dissent": [],
        "focus": [],
        "patterns": [],
        "inventory": [],
    }
    for result in cached_results:
        for key in result_keys:
            value = result[key]
            if isinstance(value, list):
                collected[key].extend(value)
            else:
                collected[key].append(value)

    tables_dir = output_dir / "tables"
    reports_dir = output_dir / "reports"
    tables_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    frames = {
        key: pd.DataFrame(rows) for key, rows in collected.items()
    }
    global_table = global_summary(frames["summary"])
    filenames = {
        "summary": "model_agreement_summary.csv",
        "pairwise": "pairwise_model_agreement.csv",
        "classes": "class_agreement_summary.csv",
        "dissent": "model_dissent_summary.csv",
        "focus": "built_class_vote_summary.csv",
        "patterns": "prediction_pattern_summary.csv",
        "inventory": "model_agreement_output_inventory.csv",
    }
    for key, filename in filenames.items():
        frames[key].to_csv(
            tables_dir / filename,
            index=False,
            encoding="utf-8-sig",
        )
    global_table.to_csv(
        tables_dir / "model_agreement_global_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    pairwise_global = (
        frames["pairwise"]
        .groupby(
            ["resolution_m", "model_a", "model_b"],
            as_index=False,
        )[["valid_pixels", "agreement_pixels"]]
        .sum()
    )
    pairwise_global["agreement_pct"] = (
        pairwise_global["agreement_pixels"]
        / pairwise_global["valid_pixels"].replace(0, np.nan)
    )
    reference_dissent = frames["dissent"][
        frames["dissent"]["model_id"] == reference_model_id
    ].copy()
    report = [
        "# Actividad 4.14 - Acuerdo espacial entre modelos",
        "",
        (
            "Se compararon RF, SVM, XGBoost y DNN sobre los mismos píxeles. "
            "No se ejecutó entrenamiento ni se modificaron los mapas fuente."
        ),
        "",
        (
            "> El acuerdo entre modelos mide estabilidad, no exactitud. "
            "Los cuatro modelos pueden coincidir y estar equivocados por "
            "falta de datos representativos."
        ),
        "",
        "## Criterio",
        "",
        "- 4 votos: unanimidad.",
        "- 3 votos: mayoría y consenso estricto.",
        "- 2-1-1: pluralidad débil, sin clase de consenso.",
        "- 2-2 o cuatro clases distintas: sin consenso.",
        "",
        "## Resumen global por resolución",
        "",
        dataframe_to_markdown(global_table),
        "",
        "## Resumen por zona",
        "",
        dataframe_to_markdown(frames["summary"]),
        "",
        "## Acuerdo por parejas",
        "",
        dataframe_to_markdown(pairwise_global),
        "",
        "## RF como único disidente frente a una mayoría 3-1",
        "",
        dataframe_to_markdown(reference_dissent),
        "",
        "## Votos para la clase construido",
        "",
        dataframe_to_markdown(frames["focus"], max_rows=100),
        "",
        "## Productos",
        "",
        dataframe_to_markdown(frames["inventory"]),
    ]
    report_path = reports_dir / "a4_14_model_agreement_report.md"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Reporte: {report_path}")


if __name__ == "__main__":
    main()
