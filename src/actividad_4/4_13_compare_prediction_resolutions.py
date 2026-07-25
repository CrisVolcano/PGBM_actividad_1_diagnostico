#!/usr/bin/env python3
"""Actividad 4.13 - Comparación de mapas de predicción a 10 m y 20 m.

Compara cada mapa de 20 m con la moda de sus píxeles de 10 m. Este código no
entrena, selecciona ni modifica modelos; únicamente evalúa la sensibilidad de
la cartografía a la resolución de salida.
"""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT


SCRIPT_PATH = Path(__file__).resolve()
sys.path.insert(0, str(SCRIPT_PATH.parent))

from raster_prediction_common import (  # noqa: E402
    REPO_ROOT,
    dataframe_to_markdown,
    parse_csv_list,
    read_config,
    resolve_path,
)


DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_11_13_raster_prediction.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--regions", help="IDs de zona separados por coma.")
    parser.add_argument("--models", help="Modelos separados por coma.")
    return parser.parse_args()


def prediction_paths(
    prediction_dir: Path,
    model_id: str,
    region_id: str,
    resolution: int,
) -> dict[str, Path]:
    directory = (
        prediction_dir
        / model_id
        / f"{resolution}m"
        / f"region_{region_id}"
    )
    stem = f"{region_id}__{model_id}__id_1_propuesta__{resolution}m"
    return {
        "class": directory / f"{stem}.tif",
        "confidence": directory / f"{stem}__confidence.tif",
    }


def agreement_path(
    output_dir: Path,
    model_id: str,
    region_id: str,
    fine_resolution: int,
    coarse_resolution: int,
) -> Path:
    return (
        output_dir
        / model_id
        / f"region_{region_id}"
        / (
            f"{region_id}__{model_id}__agreement_"
            f"{fine_resolution}m_mode_vs_{coarse_resolution}m.tif"
        )
    )


def assert_nested_grids(
    fine: rasterio.io.DatasetReader,
    coarse: rasterio.io.DatasetReader,
    fine_resolution: int,
    coarse_resolution: int,
) -> None:
    if fine.crs is None or coarse.crs is None or fine.crs != coarse.crs:
        raise ValueError("Los mapas fino y grueso no comparten el mismo CRS.")
    observed_fine = (abs(float(fine.transform.a)), abs(float(fine.transform.e)))
    observed_coarse = (
        abs(float(coarse.transform.a)),
        abs(float(coarse.transform.e)),
    )
    tolerance = 1e-6
    if any(abs(value - fine_resolution) > tolerance for value in observed_fine):
        raise ValueError(
            f"El mapa fino no tiene píxel de {fine_resolution} m: "
            f"{observed_fine}"
        )
    if any(
        abs(value - coarse_resolution) > tolerance
        for value in observed_coarse
    ):
        raise ValueError(
            f"El mapa grueso no tiene píxel de {coarse_resolution} m: "
            f"{observed_coarse}"
        )
    ratio = coarse_resolution / fine_resolution
    if not float(ratio).is_integer():
        raise ValueError("La resolución gruesa no es múltiplo de la fina.")
    bounds_fine = np.asarray(fine.bounds, dtype=float)
    bounds_coarse = np.asarray(coarse.bounds, dtype=float)
    if not np.allclose(bounds_fine, bounds_coarse, atol=tolerance):
        raise ValueError(
            "Los mapas no tienen la misma extensión. Deben proceder de las "
            "cuadrículas anidadas de A4.11."
        )
    x_offset = (coarse.transform.c - fine.transform.c) / fine.transform.a
    y_offset = (coarse.transform.f - fine.transform.f) / fine.transform.e
    if not (
        math.isclose(x_offset, round(x_offset), abs_tol=tolerance)
        and math.isclose(y_offset, round(y_offset), abs_tol=tolerance)
    ):
        raise ValueError("Los orígenes de las cuadrículas no están alineados.")


def validate_classes(
    values: np.ndarray,
    valid: np.ndarray,
    expected_classes: set[int],
    path: Path,
) -> None:
    observed = set(map(int, np.unique(values[valid])))
    unexpected = sorted(observed - expected_classes)
    if unexpected:
        raise ValueError(
            f"{path} contiene clases no homologadas: {unexpected}"
        )


def native_class_areas(
    path: Path,
    model_id: str,
    region_id: str,
    resolution: int,
    classes: list[int],
    labels: dict[int, str],
) -> pd.DataFrame:
    counts = {class_id: 0 for class_id in classes}
    with rasterio.open(path) as source:
        for _, window in source.block_windows(1):
            values = source.read(1, window=window, masked=True)
            valid_values = np.asarray(values.compressed(), dtype=np.int64)
            unexpected = sorted(set(map(int, np.unique(valid_values))) - set(classes))
            if unexpected:
                raise ValueError(
                    f"{path} contiene clases no homologadas: {unexpected}"
                )
            unique, frequencies = np.unique(
                valid_values, return_counts=True
            )
            for class_id, count in zip(unique, frequencies):
                counts[int(class_id)] += int(count)
        pixel_area_m2 = abs(
            float(
                source.transform.a * source.transform.e
                - source.transform.b * source.transform.d
            )
        )
    total = sum(counts.values())
    return pd.DataFrame(
        [
            {
                "model_id": model_id,
                "region_id": region_id,
                "resolution_m": resolution,
                "class_id": class_id,
                "class_label": labels[class_id],
                "pixel_count": counts[class_id],
                "pct_valid_pixels": (
                    counts[class_id] / total if total else np.nan
                ),
                "area_ha": counts[class_id] * pixel_area_m2 / 10000.0,
            }
            for class_id in classes
        ]
    )


def kappa_from_matrix(matrix: np.ndarray) -> float:
    total = float(matrix.sum())
    if total == 0:
        return float("nan")
    observed = float(np.trace(matrix)) / total
    expected = float(
        np.dot(matrix.sum(axis=1), matrix.sum(axis=0)) / (total * total)
    )
    denominator = 1.0 - expected
    if math.isclose(denominator, 0.0):
        return float("nan")
    return (observed - expected) / denominator


def confidence_metrics(
    fine_path: Path,
    coarse_path: Path,
    coarse_reference: rasterio.io.DatasetReader,
) -> dict[str, Any]:
    if not fine_path.exists() or not coarse_path.exists():
        return {
            "confidence_compared_pixels": 0,
            "confidence_fine_mean": np.nan,
            "confidence_coarse_mean": np.nan,
            "confidence_mean_signed_difference": np.nan,
            "confidence_mean_absolute_difference": np.nan,
            "confidence_rmse": np.nan,
            "confidence_correlation": np.nan,
        }

    n = 0
    sum_fine = 0.0
    sum_coarse = 0.0
    sum_delta = 0.0
    sum_abs_delta = 0.0
    sum_squared_delta = 0.0
    sum_fine_squared = 0.0
    sum_coarse_squared = 0.0
    sum_product = 0.0
    with contextlib.ExitStack() as stack:
        fine = stack.enter_context(rasterio.open(fine_path))
        coarse = stack.enter_context(rasterio.open(coarse_path))
        fine_vrt = stack.enter_context(
            WarpedVRT(
                fine,
                crs=coarse_reference.crs,
                transform=coarse_reference.transform,
                width=coarse_reference.width,
                height=coarse_reference.height,
                resampling=Resampling.average,
                src_nodata=fine.nodata,
                nodata=-9999.0,
                dtype="float32",
            )
        )
        for _, window in coarse_reference.block_windows(1):
            fine_values = fine_vrt.read(1, window=window, masked=True)
            coarse_values = coarse.read(1, window=window, masked=True)
            valid = ~np.ma.getmaskarray(fine_values)
            valid &= ~np.ma.getmaskarray(coarse_values)
            fine_array = np.asarray(fine_values.data, dtype=np.float64)[valid]
            coarse_array = np.asarray(
                coarse_values.data, dtype=np.float64
            )[valid]
            finite = np.isfinite(fine_array) & np.isfinite(coarse_array)
            fine_array = fine_array[finite]
            coarse_array = coarse_array[finite]
            if fine_array.size == 0:
                continue
            delta = fine_array - coarse_array
            n += int(fine_array.size)
            sum_fine += float(fine_array.sum())
            sum_coarse += float(coarse_array.sum())
            sum_delta += float(delta.sum())
            sum_abs_delta += float(np.abs(delta).sum())
            sum_squared_delta += float(np.square(delta).sum())
            sum_fine_squared += float(np.square(fine_array).sum())
            sum_coarse_squared += float(np.square(coarse_array).sum())
            sum_product += float(np.multiply(fine_array, coarse_array).sum())

    if n == 0:
        return confidence_metrics(
            Path("__missing_fine__"),
            Path("__missing_coarse__"),
            coarse_reference,
        )
    covariance_numerator = sum_product - (sum_fine * sum_coarse / n)
    fine_variance = sum_fine_squared - (sum_fine * sum_fine / n)
    coarse_variance = sum_coarse_squared - (sum_coarse * sum_coarse / n)
    correlation_denominator = math.sqrt(
        max(0.0, fine_variance) * max(0.0, coarse_variance)
    )
    correlation = (
        covariance_numerator / correlation_denominator
        if correlation_denominator > 0
        else np.nan
    )
    return {
        "confidence_compared_pixels": n,
        "confidence_fine_mean": sum_fine / n,
        "confidence_coarse_mean": sum_coarse / n,
        "confidence_mean_signed_difference": sum_delta / n,
        "confidence_mean_absolute_difference": sum_abs_delta / n,
        "confidence_rmse": math.sqrt(sum_squared_delta / n),
        "confidence_correlation": correlation,
    }


def compare_pair(
    fine_path: Path,
    coarse_path: Path,
    output_path: Path,
    model_id: str,
    region_id: str,
    fine_resolution: int,
    coarse_resolution: int,
    classes: list[int],
    labels: dict[int, str],
    write_agreement: bool,
    compare_confidence: bool,
    fine_confidence_path: Path,
    coarse_confidence_path: Path,
) -> tuple[dict[str, Any], pd.DataFrame]:
    for path in [fine_path, coarse_path]:
        if not path.exists():
            raise FileNotFoundError(
                f"Falta salida de A4.12 para comparar: {path}"
            )

    class_lookup = np.full(256, -1, dtype=np.int16)
    for index, class_id in enumerate(classes):
        class_lookup[class_id] = index
    matrix = np.zeros((len(classes), len(classes)), dtype=np.int64)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial = output_path.with_name(
        output_path.stem + ".partial" + output_path.suffix
    )
    if partial.exists():
        partial.unlink()

    with contextlib.ExitStack() as stack:
        fine = stack.enter_context(rasterio.open(fine_path))
        coarse = stack.enter_context(rasterio.open(coarse_path))
        assert_nested_grids(
            fine,
            coarse,
            fine_resolution,
            coarse_resolution,
        )
        fine_vrt = stack.enter_context(
            WarpedVRT(
                fine,
                crs=coarse.crs,
                transform=coarse.transform,
                width=coarse.width,
                height=coarse.height,
                resampling=Resampling.mode,
                src_nodata=fine.nodata,
                nodata=0,
                dtype="uint8",
            )
        )
        agreement_output = None
        if write_agreement:
            profile = coarse.profile.copy()
            profile.update(
                driver="GTiff",
                count=1,
                dtype="uint8",
                nodata=0,
                compress="DEFLATE",
                tiled=True,
                blockxsize=256,
                blockysize=256,
                BIGTIFF="IF_SAFER",
            )
            agreement_output = stack.enter_context(
                rasterio.open(partial, "w", **profile)
            )
            agreement_output.update_tags(
                model_id=model_id,
                region_id=region_id,
                fine_resolution_m=fine_resolution,
                coarse_resolution_m=coarse_resolution,
                values="0=nodata;1=agreement;2=disagreement",
                comparison="fine_mode_vs_coarse",
            )

        for _, window in coarse.block_windows(1):
            fine_values = fine_vrt.read(1, window=window, masked=True)
            coarse_values = coarse.read(1, window=window, masked=True)
            fine_array = np.asarray(fine_values.data, dtype=np.uint8)
            coarse_array = np.asarray(coarse_values.data, dtype=np.uint8)
            valid = ~np.ma.getmaskarray(fine_values)
            valid &= ~np.ma.getmaskarray(coarse_values)
            valid &= fine_array != 0
            valid &= coarse_array != 0
            validate_classes(fine_array, valid, set(classes), fine_path)
            validate_classes(coarse_array, valid, set(classes), coarse_path)
            if valid.any():
                fine_indexes = class_lookup[fine_array[valid]]
                coarse_indexes = class_lookup[coarse_array[valid]]
                encoded = fine_indexes * len(classes) + coarse_indexes
                matrix += np.bincount(
                    encoded,
                    minlength=len(classes) * len(classes),
                ).reshape(len(classes), len(classes))
            if agreement_output is not None:
                agreement = np.zeros(fine_array.shape, dtype=np.uint8)
                agreement[valid & (fine_array == coarse_array)] = 1
                agreement[valid & (fine_array != coarse_array)] = 2
                agreement_output.write(agreement, 1, window=window)

        confidence = (
            confidence_metrics(
                fine_confidence_path,
                coarse_confidence_path,
                coarse,
            )
            if compare_confidence
            else {}
        )

    if agreement_output is not None:
        os.replace(partial, output_path)

    total = int(matrix.sum())
    agreement_count = int(np.trace(matrix))
    transition_rows = []
    for fine_index, fine_class in enumerate(classes):
        for coarse_index, coarse_class in enumerate(classes):
            count = int(matrix[fine_index, coarse_index])
            transition_rows.append(
                {
                    "model_id": model_id,
                    "region_id": region_id,
                    "fine_resolution_m": fine_resolution,
                    "coarse_resolution_m": coarse_resolution,
                    "fine_class_id": fine_class,
                    "fine_class_label": labels[fine_class],
                    "coarse_class_id": coarse_class,
                    "coarse_class_label": labels[coarse_class],
                    "pixel_count_at_coarse_grid": count,
                    "pct_compared_pixels": count / total if total else np.nan,
                }
            )
    summary = {
        "model_id": model_id,
        "region_id": region_id,
        "fine_resolution_m": fine_resolution,
        "coarse_resolution_m": coarse_resolution,
        "compared_pixels_at_coarse_grid": total,
        "agreement_pixels": agreement_count,
        "disagreement_pixels": total - agreement_count,
        "overall_agreement": (
            agreement_count / total if total else np.nan
        ),
        "cohen_kappa": kappa_from_matrix(matrix),
        "fine_class_raster": str(fine_path),
        "coarse_class_raster": str(coarse_path),
        "agreement_raster": (
            str(output_path) if write_agreement else ""
        ),
        **confidence,
    }
    return summary, pd.DataFrame(transition_rows)


def main() -> None:
    args = parse_args()
    config = read_config(args.config)
    shared = config["shared"]
    compare_config = config["compare"]
    prediction_dir = resolve_path(compare_config["prediction_dir"])
    output_dir = resolve_path(compare_config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    regions = (
        parse_csv_list(args.regions, str)
        or [str(value) for value in shared["regions"]]
    )
    models = (
        parse_csv_list(args.models, str)
        or [str(value) for value in compare_config["model_ids"]]
    )
    unknown_models = sorted(set(models) - set(shared["models"]))
    if unknown_models:
        raise ValueError(f"Modelos no configurados: {unknown_models}")
    fine_resolution = int(compare_config["fine_resolution_m"])
    coarse_resolution = int(compare_config["coarse_resolution_m"])
    classes = sorted(map(int, shared["target"]["expected_classes"]))
    labels = {
        int(row["id_1_propuesta"]): str(row["nivel_1_propuesta"])
        for row in pd.read_csv(
            resolve_path(shared["paths"]["class_catalog"]),
            encoding="utf-8-sig",
        ).to_dict(orient="records")
    }
    if set(classes) != set(labels):
        raise ValueError(
            "El catálogo no contiene exactamente las clases homologadas "
            "esperadas."
        )

    summaries: list[dict[str, Any]] = []
    transitions: list[pd.DataFrame] = []
    areas: list[pd.DataFrame] = []
    for model_id in models:
        for region_id in regions:
            fine_paths = prediction_paths(
                prediction_dir,
                model_id,
                region_id,
                fine_resolution,
            )
            coarse_paths = prediction_paths(
                prediction_dir,
                model_id,
                region_id,
                coarse_resolution,
            )
            pair_summary, pair_transitions = compare_pair(
                fine_paths["class"],
                coarse_paths["class"],
                agreement_path(
                    output_dir,
                    model_id,
                    region_id,
                    fine_resolution,
                    coarse_resolution,
                ),
                model_id,
                region_id,
                fine_resolution,
                coarse_resolution,
                classes,
                labels,
                bool(compare_config.get("write_agreement_raster", True)),
                bool(compare_config.get("compare_confidence", True)),
                fine_paths["confidence"],
                coarse_paths["confidence"],
            )
            summaries.append(pair_summary)
            transitions.append(pair_transitions)
            areas.extend(
                [
                    native_class_areas(
                        fine_paths["class"],
                        model_id,
                        region_id,
                        fine_resolution,
                        classes,
                        labels,
                    ),
                    native_class_areas(
                        coarse_paths["class"],
                        model_id,
                        region_id,
                        coarse_resolution,
                        classes,
                        labels,
                    ),
                ]
            )
            print(
                f"Comparado {model_id} | zona {region_id} | "
                f"{fine_resolution} m vs. {coarse_resolution} m"
            )

    summary_table = pd.DataFrame(summaries)
    transition_table = (
        pd.concat(transitions, ignore_index=True)
        if transitions
        else pd.DataFrame()
    )
    area_table = (
        pd.concat(areas, ignore_index=True) if areas else pd.DataFrame()
    )
    tables_dir = output_dir / "tables"
    reports_dir = output_dir / "reports"
    tables_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_table.to_csv(
        tables_dir / "resolution_comparison_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    transition_table.to_csv(
        tables_dir / "resolution_class_transitions.csv",
        index=False,
        encoding="utf-8-sig",
    )
    area_table.to_csv(
        tables_dir / "resolution_class_areas.csv",
        index=False,
        encoding="utf-8-sig",
    )

    report = [
        "# Actividad 4.13 - Comparación de resoluciones",
        "",
        (
            f"Se comparó el mapa de {coarse_resolution} m contra la moda de "
            f"los píxeles del mapa de {fine_resolution} m en su misma "
            "cuadrícula."
        ),
        "",
        (
            "> Esta comparación mide sensibilidad a la resolución. No es una "
            "validación de exactitud contra datos independientes."
        ),
        "",
        "## Resumen",
        "",
        dataframe_to_markdown(summary_table),
        "",
        "## Superficie por clase y resolución",
        "",
        dataframe_to_markdown(area_table, max_rows=250),
        "",
        "## Codificación del raster de acuerdo",
        "",
        "- 0: sin datos comparables.",
        "- 1: acuerdo entre la moda de 10 m y el mapa de 20 m.",
        "- 2: desacuerdo.",
    ]
    report_path = reports_dir / "a4_13_resolution_comparison_report.md"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Reporte: {report_path}")


if __name__ == "__main__":
    main()
