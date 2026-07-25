#!/usr/bin/env python3
"""Actividad 4.11 - Verificación y preparación de inferencia raster.

Verifica las 16 fuentes raster/96 bandas por zona, los artefactos congelados,
las clases homologadas y las cuadrículas anidadas de 10 m y 20 m. Genera un
manifiesto; no remuestrea rasters y no realiza predicciones.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform_bounds


SCRIPT_PATH = Path(__file__).resolve()
sys.path.insert(0, str(SCRIPT_PATH.parent))

from raster_prediction_common import (  # noqa: E402
    REPO_ROOT,
    atomic_write_json,
    class_style_rows,
    dataframe_to_markdown,
    file_sha256,
    load_class_catalog,
    parse_csv_list,
    quick_file_fingerprint,
    read_config,
    read_feature_columns,
    resolve_path,
    sanitize_identifier,
)


DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_11_13_raster_prediction.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument(
        "--regions",
        help="IDs separados por coma. Por defecto usa shared.regions.",
    )
    parser.add_argument(
        "--output-dir",
        help="Sobrescribe prepare.output_dir; útil para auditorías parciales.",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Escribe el diagnóstico sin devolver error si faltan archivos.",
    )
    return parser.parse_args()


def issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    region_id: str = "",
    path: str = "",
) -> None:
    issues.append(
        {
            "severity": severity,
            "code": code,
            "region_id": region_id,
            "path": path,
            "message": message,
        }
    )


def auto_utm_crs(source_crs: CRS, bounds: Any) -> CRS:
    west, south, east, north = transform_bounds(
        source_crs,
        "EPSG:4326",
        *bounds,
        densify_pts=21,
    )
    lon = (west + east) / 2.0
    lat = (south + north) / 2.0
    zone = max(1, min(60, int(math.floor((lon + 180.0) / 6.0) + 1)))
    epsg = (32600 if lat >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def build_nested_grids(
    reference_path: Path,
    grid_config: dict[str, Any],
) -> list[dict[str, Any]]:
    resolutions = sorted({int(value) for value in grid_config["resolutions_m"]})
    alignment = int(grid_config.get("alignment_m", max(resolutions)))
    if any(alignment % resolution != 0 for resolution in resolutions):
        raise ValueError(
            f"alignment_m={alignment} debe ser múltiplo de {resolutions}."
        )
    with rasterio.open(reference_path) as reference:
        if reference.crs is None:
            raise ValueError(f"Raster de referencia sin CRS: {reference_path}")
        target_setting = str(grid_config.get("target_crs", "auto_utm"))
        target_crs = (
            auto_utm_crs(reference.crs, reference.bounds)
            if target_setting == "auto_utm"
            else CRS.from_user_input(target_setting)
        )
        left, bottom, right, top = transform_bounds(
            reference.crs,
            target_crs,
            *reference.bounds,
            densify_pts=21,
        )

    aligned_left = math.floor(left / alignment) * alignment
    aligned_bottom = math.floor(bottom / alignment) * alignment
    aligned_right = math.ceil(right / alignment) * alignment
    aligned_top = math.ceil(top / alignment) * alignment
    grids: list[dict[str, Any]] = []
    for resolution in resolutions:
        width = int(round((aligned_right - aligned_left) / resolution))
        height = int(round((aligned_top - aligned_bottom) / resolution))
        transform = Affine(
            resolution,
            0.0,
            aligned_left,
            0.0,
            -resolution,
            aligned_top,
        )
        grids.append(
            {
                "resolution_m": resolution,
                "crs": target_crs.to_string(),
                "crs_wkt": target_crs.to_wkt(),
                "transform": list(transform)[:6],
                "width": width,
                "height": height,
                "bounds": [
                    aligned_left,
                    aligned_bottom,
                    aligned_right,
                    aligned_top,
                ],
                "pixel_count": int(width * height),
            }
        )
    return grids


def load_feature_mapping(
    catalog_path: Path,
    features: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    catalog = pd.read_csv(catalog_path, encoding="utf-8-sig")
    required = {
        "predictor_id",
        "resolution_m",
        "scale_m",
        "band_original",
        "band_output",
        "type",
    }
    missing = required - set(catalog.columns)
    if missing:
        raise ValueError(f"Faltan columnas en catálogo raster: {sorted(missing)}")
    catalog = catalog.copy()
    catalog["predictor_id"] = catalog["predictor_id"].astype(str).str.strip()
    catalog["band_output"] = catalog["band_output"].astype(str).str.strip()
    catalog["feature_column"] = catalog["band_output"].map(sanitize_identifier)
    catalog["band_index"] = catalog.groupby("predictor_id", sort=False).cumcount() + 1

    duplicated = catalog["feature_column"].duplicated(keep=False)
    if duplicated.any():
        values = sorted(catalog.loc[duplicated, "feature_column"].unique())
        raise ValueError(f"Bandas normalizadas duplicadas: {values[:10]}")
    lookup = catalog.set_index("feature_column", drop=False)
    missing_features = [feature for feature in features if feature not in lookup.index]
    if missing_features:
        raise ValueError(
            f"{len(missing_features)} predictores del modelo no están en el catálogo: "
            f"{missing_features[:10]}"
        )
    selected = lookup.loc[features].reset_index(drop=True)
    selected.insert(0, "feature_order", range(1, len(selected) + 1))
    predictor_summary = (
        selected.groupby("predictor_id", sort=False)
        .agg(
            selected_band_count=("feature_column", "size"),
            native_resolution_m=("resolution_m", "first"),
            predictor_type=("type", "first"),
        )
        .reset_index()
    )
    return selected, predictor_summary


def validate_model_files(
    shared: dict[str, Any],
    features: list[str],
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id, model_config in shared["models"].items():
        artifact_path = resolve_path(model_config["artifact"])
        feature_path = resolve_path(model_config["feature_columns"])
        status = "ready"
        model_features: list[str] = []
        expected_scope = str(
            model_config.get("expected_trained_on", "development_only")
        )
        artifact_name = artifact_path.stem.lower()
        if (
            expected_scope == "development_only"
            and (
                "development" not in artifact_name
                or "all_modelable" in artifact_name
            )
        ):
            status = "unsafe_training_scope_name"
            issue(
                issues,
                "critical",
                "unsafe_model_training_scope",
                (
                    f"{model_id}: el nombre del artefacto no identifica "
                    "inequívocamente el modelo de desarrollo."
                ),
                path=str(artifact_path),
            )
        if not artifact_path.exists():
            status = "missing_artifact"
            issue(
                issues,
                "critical",
                "missing_model_artifact",
                f"Falta artefacto del modelo {model_id}.",
                path=str(artifact_path),
            )
        if not feature_path.exists():
            status = "missing_feature_columns"
            issue(
                issues,
                "critical",
                "missing_model_feature_columns",
                f"Falta lista de predictores de {model_id}.",
                path=str(feature_path),
            )
        else:
            model_features = read_feature_columns(feature_path)
            if model_features != features:
                status = "feature_mismatch"
                issue(
                    issues,
                    "critical",
                    "model_feature_mismatch",
                    f"{model_id} no usa exactamente los mismos predictores/orden.",
                    path=str(feature_path),
                )

        optional_paths = [
            key
            for key in ["label_encoder", "preprocessor"]
            if key in model_config
        ]
        for key in optional_paths:
            optional_path = resolve_path(model_config[key])
            if not optional_path.exists():
                status = f"missing_{key}"
                issue(
                    issues,
                    "critical",
                    f"missing_model_{key}",
                    f"Falta {key} de {model_id}.",
                    path=str(optional_path),
                )
        rows.append(
            {
                "model_id": model_id,
                "adapter": model_config["adapter"],
                "expected_trained_on": model_config.get("expected_trained_on"),
                "artifact_path": str(artifact_path),
                "artifact_status": status,
                "artifact_size_bytes": (
                    artifact_path.stat().st_size if artifact_path.exists() else np.nan
                ),
                "feature_count": len(model_features),
                "feature_columns_sha256": (
                    file_sha256(feature_path) if feature_path.exists() else ""
                ),
            }
        )
    return rows


def development_feature_ranges(
    shared: dict[str, Any],
    prepare: dict[str, Any],
    features: list[str],
    issues: list[dict[str, Any]],
) -> pd.DataFrame:
    dataset_path = resolve_path(shared["paths"]["modeling_dataset_parquet"])
    assignments_path = resolve_path(shared["paths"]["split_assignments_csv"])
    if not dataset_path.exists() or not assignments_path.exists():
        missing = [
            str(path)
            for path in [dataset_path, assignments_path]
            if not path.exists()
        ]
        issue(
            issues,
            "critical",
            "missing_development_range_input",
            f"No se pueden calcular rangos de desarrollo; faltan: {missing}",
        )
        return pd.DataFrame()

    key = "xy_group_id"
    role = str(prepare.get("development_split_role", "development_cv"))
    assignments = pd.read_csv(
        assignments_path,
        usecols=[key, "split_role"],
        encoding="utf-8-sig",
    )
    development_keys = assignments.loc[
        assignments["split_role"].astype(str) == role,
        key,
    ].astype(str)
    if development_keys.empty:
        issue(
            issues,
            "critical",
            "empty_development_split",
            f"No hay filas con split_role={role!r}.",
        )
        return pd.DataFrame()

    data = pd.read_parquet(dataset_path, columns=[key, *features])
    data[key] = data[key].astype(str)
    development = data[data[key].isin(set(development_keys))].copy()
    if len(development) != len(development_keys):
        issue(
            issues,
            "critical",
            "development_key_mismatch",
            f"Claves esperadas={len(development_keys):,}; encontradas={len(development):,}.",
        )
        return pd.DataFrame()
    quantiles = [float(value) for value in prepare.get("training_range_quantiles", [0.01, 0.99])]
    q_low, q_high = min(quantiles), max(quantiles)
    rows: list[dict[str, Any]] = []
    for feature in features:
        values = pd.to_numeric(development[feature], errors="coerce")
        row = {
            "feature_column": feature,
            "n_development": len(values),
            "n_non_null": int(values.notna().sum()),
            "min_development": float(values.min()),
            f"q{q_low:g}_development": float(values.quantile(q_low)),
            f"q{q_high:g}_development": float(values.quantile(q_high)),
            "max_development": float(values.max()),
        }
        if not all(
            math.isfinite(row[column])
            for column in [
                "min_development",
                f"q{q_low:g}_development",
                f"q{q_high:g}_development",
                "max_development",
            ]
        ):
            issue(
                issues,
                "critical",
                "invalid_development_feature_range",
                (
                    f"{feature}: no se pudo obtener un rango finito usando "
                    "exclusivamente development_cv."
                ),
            )
        rows.append(row)
    return pd.DataFrame(rows)


def inspect_regions(
    shared: dict[str, Any],
    selected: pd.DataFrame,
    predictor_summary: pd.DataFrame,
    regions: list[str],
    issues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    root = resolve_path(shared["paths"]["raster_root"])
    layout = shared["raster_layout"]
    grid_config = shared["grids"]
    default_resampling = str(shared["resampling"].get("default", "bilinear"))
    overrides = shared["resampling"].get("overrides", {}) or {}
    inventory_rows: list[dict[str, Any]] = []
    region_manifests: list[dict[str, Any]] = []

    grouped = {
        predictor_id: group.sort_values("band_index")
        for predictor_id, group in selected.groupby("predictor_id", sort=False)
    }
    directory_overrides = {
        str(key): resolve_path(value)
        for key, value in (
            layout.get("region_directories", {}) or {}
        ).items()
    }
    for region_id in regions:
        region_dir = directory_overrides.get(
            region_id,
            root
            / layout["region_directory_template"].format(
                region_id=region_id
            ),
        )
        sources: list[dict[str, Any]] = []
        region_ok = True
        for summary in predictor_summary.itertuples(index=False):
            predictor_id = str(summary.predictor_id)
            raster_path = region_dir / layout["filename_template"].format(
                region_id=region_id,
                predictor_id=predictor_id,
            )
            expected_bands = grouped[predictor_id]
            row: dict[str, Any] = {
                "region_id": region_id,
                "predictor_id": predictor_id,
                "raster_path": str(raster_path),
                "exists": raster_path.exists(),
                "expected_band_count": len(expected_bands),
                "status": "missing",
            }
            if not raster_path.exists():
                region_ok = False
                issue(
                    issues,
                    "critical",
                    "missing_predictor_raster",
                    f"Falta raster {predictor_id} en zona {region_id}.",
                    region_id,
                    str(raster_path),
                )
                inventory_rows.append(row)
                continue
            try:
                with rasterio.open(raster_path) as raster:
                    row.update(
                        {
                            "status": "ok",
                            "band_count": raster.count,
                            "width": raster.width,
                            "height": raster.height,
                            "crs": raster.crs.to_string() if raster.crs else "",
                            "pixel_size_x": abs(float(raster.transform.a)),
                            "pixel_size_y": abs(float(raster.transform.e)),
                            "nodata": raster.nodata,
                            "dtype": "|".join(raster.dtypes),
                            "bounds": ",".join(map(str, raster.bounds)),
                        }
                    )
                    if raster.crs is None:
                        region_ok = False
                        row["status"] = "missing_crs"
                        issue(
                            issues,
                            "critical",
                            "missing_raster_crs",
                            f"{predictor_id} no tiene CRS.",
                            region_id,
                            str(raster_path),
                        )
                    if raster.count != len(expected_bands):
                        region_ok = False
                        row["status"] = "band_count_mismatch"
                        issue(
                            issues,
                            "critical",
                            "raster_band_count_mismatch",
                            f"{predictor_id}: bandas={raster.count}; esperadas={len(expected_bands)}.",
                            region_id,
                            str(raster_path),
                        )
                    descriptions = list(raster.descriptions)
                    expected_descriptions = expected_bands["band_output"].tolist()
                    observed = descriptions[: len(expected_descriptions)]
                    if any(value not in {None, ""} for value in observed):
                        mismatches = [
                            (index + 1, expected, found)
                            for index, (expected, found) in enumerate(
                                zip(expected_descriptions, observed)
                            )
                            if found not in {None, "", expected}
                        ]
                        if mismatches:
                            region_ok = False
                            row["status"] = "band_description_mismatch"
                            issue(
                                issues,
                                "critical",
                                "raster_band_description_mismatch",
                                f"{predictor_id}: descripciones no coinciden: {mismatches[:3]}",
                                region_id,
                                str(raster_path),
                            )
            except Exception as error:
                region_ok = False
                row["status"] = "open_error"
                issue(
                    issues,
                    "critical",
                    "raster_open_error",
                    f"No se pudo abrir {predictor_id}: {error}",
                    region_id,
                    str(raster_path),
                )
            inventory_rows.append(row)
            if row["status"] == "ok":
                sources.append(
                    {
                        "predictor_id": predictor_id,
                        "path": str(raster_path),
                        "fingerprint": quick_file_fingerprint(raster_path),
                        "resampling": str(overrides.get(predictor_id, default_resampling)),
                        "bands": [
                            {
                                "band_index": int(item.band_index),
                                "band_output": str(item.band_output),
                                "feature_column": str(item.feature_column),
                                "feature_order": int(item.feature_order),
                            }
                            for item in expected_bands.itertuples(index=False)
                        ],
                    }
                )

        reference_id = str(grid_config["reference_predictor_id"])
        reference_matches = [
            source for source in sources if source["predictor_id"] == reference_id
        ]
        grids: list[dict[str, Any]] = []
        if not reference_matches:
            region_ok = False
            issue(
                issues,
                "critical",
                "missing_reference_raster",
                f"No existe raster de referencia {reference_id}.",
                region_id,
            )
        else:
            try:
                grids = build_nested_grids(
                    Path(reference_matches[0]["path"]),
                    grid_config,
                )
            except Exception as error:
                region_ok = False
                issue(
                    issues,
                    "critical",
                    "grid_build_error",
                    f"No se pudieron construir cuadrículas: {error}",
                    region_id,
                    reference_matches[0]["path"],
                )
        region_manifests.append(
            {
                "region_id": region_id,
                "ready": bool(region_ok),
                "region_directory": str(region_dir),
                "sources": sources,
                "grids": grids,
            }
        )
    return region_manifests, pd.DataFrame(inventory_rows)


def main() -> None:
    args = parse_args()
    config_path = resolve_path(args.config)
    config = read_config(config_path)
    shared = config["shared"]
    prepare = config["prepare"]
    regions = (
        parse_csv_list(args.regions, str)
        or [str(value) for value in shared["regions"]]
    )
    output_dir = resolve_path(args.output_dir or prepare["output_dir"])
    tables_dir = output_dir / "tables"
    reports_dir = output_dir / "reports"
    tables_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    issues: list[dict[str, Any]] = []
    features = read_feature_columns(shared["paths"]["feature_columns"])
    catalog_path = resolve_path(shared["paths"]["predictor_catalog"])
    selected, predictor_summary = load_feature_mapping(catalog_path, features)
    if len(predictor_summary) != 16 or len(selected) != 96:
        issue(
            issues,
            "critical",
            "unexpected_predictor_inventory",
            f"Se esperaban 16 rasters/96 bandas; encontrados "
            f"{len(predictor_summary)}/{len(selected)}.",
        )

    class_catalog = load_class_catalog(shared["paths"]["class_catalog"])
    expected_classes = sorted(map(int, shared["target"]["expected_classes"]))
    observed_classes = sorted(class_catalog["id_1_propuesta"].tolist())
    if observed_classes != expected_classes:
        issue(
            issues,
            "critical",
            "homologated_class_mismatch",
            f"Clases esperadas={expected_classes}; catálogo={observed_classes}.",
        )
    style_rows: list[dict[str, Any]] = []
    try:
        style_rows = class_style_rows(
            class_catalog,
            shared["target"].get("style", {}),
        )
        class_catalog = class_catalog.merge(
            pd.DataFrame(style_rows),
            on=["id_1_propuesta", "nivel_1_propuesta"],
            how="left",
            validate="one_to_one",
        )
    except Exception as error:
        issue(
            issues,
            "critical",
            "invalid_homologated_class_palette",
            f"No se pudo validar la paleta temática: {error}",
        )

    model_rows = validate_model_files(shared, features, issues)
    ranges = development_feature_ranges(shared, prepare, features, issues)
    region_manifests, inventory = inspect_regions(
        shared,
        selected,
        predictor_summary,
        regions,
        issues,
    )

    issues_table = pd.DataFrame(
        issues,
        columns=["severity", "code", "region_id", "path", "message"],
    )
    critical_count = int((issues_table["severity"] == "critical").sum())
    ready = (
        critical_count == 0
        and bool(region_manifests)
        and all(region["ready"] for region in region_manifests)
        and len(ranges) == len(features)
    )
    range_records = (
        ranges.set_index("feature_column").to_dict(orient="index")
        if not ranges.empty
        else {}
    )
    model_manifest = []
    for model_id, model_config in shared["models"].items():
        resolved = {
            key: str(resolve_path(value))
            for key, value in model_config.items()
            if key in {"artifact", "label_encoder", "preprocessor", "feature_columns"}
        }
        artifact = resolve_path(model_config["artifact"])
        component_fingerprints = {
            key: quick_file_fingerprint(path)
            for key, path_value in model_config.items()
            if key
            in {"artifact", "label_encoder", "preprocessor", "feature_columns"}
            and (path := resolve_path(path_value)).exists()
        }
        model_manifest.append(
            {
                "model_id": model_id,
                "adapter": model_config["adapter"],
                "expected_trained_on": model_config.get("expected_trained_on"),
                **resolved,
                "artifact_fingerprint": (
                    quick_file_fingerprint(artifact) if artifact.exists() else None
                ),
                "component_fingerprints": component_fingerprints,
            }
        )

    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "ready": ready,
        "critical_issue_count": critical_count,
        "target": {
            "field": shared["target"]["field"],
            "label_field": shared["target"]["label_field"],
            "classes": class_catalog.to_dict(orient="records"),
        },
        "feature_count": len(features),
        "feature_columns": features,
        "feature_columns_sha256": file_sha256(shared["paths"]["feature_columns"]),
        "predictor_raster_count": len(predictor_summary),
        "feature_mapping": selected[
            [
                "feature_order",
                "feature_column",
                "predictor_id",
                "band_index",
                "band_output",
            ]
        ].to_dict(orient="records"),
        "development_only_feature_ranges": range_records,
        "development_split_role": prepare.get(
            "development_split_role", "development_cv"
        ),
        "models": model_manifest,
        "regions": region_manifests,
    }

    selected.to_csv(
        tables_dir / "feature_to_raster_band_mapping.csv",
        index=False,
        encoding="utf-8-sig",
    )
    predictor_summary.to_csv(
        tables_dir / "predictor_raster_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(style_rows).to_csv(
        tables_dir / "homologated_class_palette.csv",
        index=False,
        encoding="utf-8-sig",
    )
    inventory.to_csv(
        tables_dir / "raster_inventory.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(model_rows).to_csv(
        tables_dir / "model_artifact_inventory.csv",
        index=False,
        encoding="utf-8-sig",
    )
    ranges.to_csv(
        tables_dir / "development_only_feature_ranges.csv",
        index=False,
        encoding="utf-8-sig",
    )
    issues_table.to_csv(
        tables_dir / "preparation_issues.csv",
        index=False,
        encoding="utf-8-sig",
    )
    manifest_path = tables_dir / "raster_inference_manifest.json"
    atomic_write_json(manifest, manifest_path)

    readiness_rows = [
        {
            "region_id": region["region_id"],
            "ready": region["ready"],
            "source_rasters": len(region["sources"]),
            "feature_bands": sum(
                len(source["bands"]) for source in region["sources"]
            ),
            "grid_count": len(region["grids"]),
        }
        for region in region_manifests
    ]
    readiness = pd.DataFrame(readiness_rows)
    readiness.to_csv(
        tables_dir / "region_readiness.csv",
        index=False,
        encoding="utf-8-sig",
    )
    report_lines = [
        "# Actividad 4.11 - Preparación de inferencia raster",
        "",
        f"**Listo para inferencia:** `{ready}`",
        "",
        f"- Zonas verificadas: {', '.join(regions)}",
        f"- Rasters predictores esperados por zona: {len(predictor_summary)}",
        f"- Bandas/columnas del modelo: {len(features)}",
        f"- Clases homologadas: {', '.join(map(str, expected_classes))}",
        f"- Incidencias críticas: {critical_count}",
        "- Rangos de aplicabilidad calculados exclusivamente con `development_cv`.",
        "- No se ejecutó entrenamiento, ajuste ni predicción.",
        "",
        "## Estado por zona",
        "",
        dataframe_to_markdown(readiness),
        "",
        "## Artefactos de modelos congelados",
        "",
        dataframe_to_markdown(pd.DataFrame(model_rows)),
        "",
        "## Paleta de clases homologadas",
        "",
        dataframe_to_markdown(pd.DataFrame(style_rows)),
        "",
        "## Incidencias",
        "",
        dataframe_to_markdown(issues_table, max_rows=100),
        "",
        "## Manifiesto",
        "",
        f"`{manifest_path}`",
    ]
    report_path = reports_dir / "a4_11_prepare_raster_inference_report.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"Listo para inferencia: {ready}")
    print(f"Manifiesto: {manifest_path}")
    print(f"Reporte: {report_path}")

    fail_on_incomplete = bool(prepare.get("fail_on_incomplete", True))
    if not ready and fail_on_incomplete and not args.allow_incomplete:
        raise SystemExit(
            "Preparación incompleta. Revise preparation_issues.csv; "
            "no se habilitó la inferencia."
        )


if __name__ == "__main__":
    main()
