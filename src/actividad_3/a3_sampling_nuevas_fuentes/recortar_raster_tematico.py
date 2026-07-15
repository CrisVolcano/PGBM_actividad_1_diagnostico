#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recorta un raster temático con una capa vectorial y conserva su estructura
categórica: valores de clase, tabla VAT, colores, etiquetas y metadatos.

Dependencias:
    numpy, rasterio, geopandas, shapely, pyshp

Ejemplo:
    python recortar_raster_tematico.py \
        --raster ForestCoverLandUse_2021_25k.tif \
        --vector ejemplo_Panama_mangle.gpkg \
        --salida ForestCoverLandUse_2021_25k_mangle.tif
"""

from __future__ import annotations

import argparse
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.mask import mask
from shapely.geometry import box, mapping

try:
    import shapefile  # paquete pyshp
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Falta la dependencia 'pyshp'. Instálela con: conda install -c conda-forge pyshp"
    ) from exc


STAT_KEYS = {
    "STATISTICS_MINIMUM",
    "STATISTICS_MAXIMUM",
    "STATISTICS_MEAN",
    "STATISTICS_STDDEV",
    "STATISTICS_MEDIAN",
    "STATISTICS_COVARIANCES",
    "STATISTICS_SKIPFACTORX",
    "STATISTICS_SKIPFACTORY",
    "STATISTICS_VALID_PERCENT",
}

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3]
PANAMA_RAW_DIR = REPO_ROOT / "data" / "raw" / "Panama"
DEFAULT_RASTER = (
    PANAMA_RAW_DIR
    / "ForestCoverLandUse_2021_25k"
    / "ForestCoverLandUse_2021_25k.tif"
)
DEFAULT_VECTOR = PANAMA_RAW_DIR / "ejemplo_Panama_mangle.gpkg"
DEFAULT_OUTPUT = PANAMA_RAW_DIR / "ForestCoverLandUse_2021_25k_mangle_recorte.tif"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Recorta un GeoTIFF temático con un vector y conserva/reconstruye "
            "la tabla de clases, nombres, colores y metadatos temáticos."
        )
    )
    parser.add_argument(
        "--raster",
        default=DEFAULT_RASTER,
        type=Path,
        help=f"GeoTIFF de entrada. Por defecto: {DEFAULT_RASTER}",
    )
    parser.add_argument(
        "--vector",
        default=DEFAULT_VECTOR,
        type=Path,
        help=f"GPKG u otro vector de recorte. Por defecto: {DEFAULT_VECTOR}",
    )
    parser.add_argument(
        "--salida",
        default=DEFAULT_OUTPUT,
        type=Path,
        help=f"GeoTIFF de salida. Por defecto: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--capa",
        default=None,
        help="Nombre de la capa dentro del GPKG. Si se omite, se usa la primera.",
    )
    parser.add_argument(
        "--nodata",
        type=int,
        default=None,
        help=(
            "Valor para el exterior del polígono. Si se omite, usa el nodata del "
            "raster; si no existe, usa 0."
        ),
    )
    parser.add_argument(
        "--all-touched",
        action="store_true",
        help="Incluye todo píxel tocado por el polígono. Por defecto usa el centro del píxel.",
    )
    parser.add_argument(
        "--sin-overviews",
        action="store_true",
        help="No construir pirámides internas con remuestreo vecino más cercano.",
    )
    parser.add_argument(
        "--sin-qml",
        action="store_true",
        help="No crear un estilo QML auxiliar para QGIS.",
    )
    return parser.parse_args()


def buscar_vat(raster: Path) -> tuple[Path | None, Path | None]:
    """Busca los archivos laterales raster.tif.vat.dbf y raster.tif.vat.cpg."""
    dbf = Path(str(raster) + ".vat.dbf")
    cpg = Path(str(raster) + ".vat.cpg")
    return (dbf if dbf.exists() else None, cpg if cpg.exists() else None)


def leer_codificacion(cpg: Path | None) -> str:
    if cpg is None:
        return "utf-8"
    value = cpg.read_text(encoding="ascii", errors="ignore").strip()
    return value or "utf-8"


def leer_vat(dbf: Path, encoding: str) -> tuple[list[list[Any]], list[list[Any]]]:
    reader = shapefile.Reader(dbf=str(dbf), encoding=encoding)
    fields = [list(field) for field in reader.fields[1:]]  # omitir DeletionFlag
    records = [list(record) for record in reader.records()]
    return fields, records


def indice_campo(fields: list[list[Any]], nombre: str) -> int | None:
    objetivo = nombre.casefold()
    for i, field in enumerate(fields):
        if str(field[0]).casefold() == objetivo:
            return i
    return None


def tabla_vat_como_dicts(
    fields: list[list[Any]], records: list[list[Any]]
) -> list[dict[str, Any]]:
    names = [str(field[0]) for field in fields]
    return [dict(zip(names, record)) for record in records]


def actualizar_y_escribir_vat(
    source_dbf: Path,
    source_cpg: Path | None,
    output_raster: Path,
    counts: dict[int, int],
) -> tuple[Path, list[dict[str, Any]]]:
    encoding = leer_codificacion(source_cpg)
    fields, records = leer_vat(source_dbf, encoding)

    idx_value = indice_campo(fields, "Value")
    idx_count = indice_campo(fields, "Count")
    if idx_value is None:
        raise ValueError(f"La tabla VAT no contiene un campo 'Value': {source_dbf}")

    if idx_count is not None:
        for record in records:
            value = int(record[idx_value])
            record[idx_count] = float(counts.get(value, 0))

    output_dbf = Path(str(output_raster) + ".vat.dbf")
    output_cpg = Path(str(output_raster) + ".vat.cpg")

    writer = shapefile.Writer(dbf=str(output_dbf), encoding=encoding)
    for name, field_type, size, decimal in fields:
        writer.field(str(name), str(field_type), size=int(size), decimal=int(decimal))
    for record in records:
        writer.record(*record)
    writer.close()

    if source_cpg is not None:
        shutil.copy2(source_cpg, output_cpg)
    else:
        output_cpg.write_text(encoding, encoding="ascii")

    return output_dbf, tabla_vat_como_dicts(fields, records)


def crear_colormap(rows: list[dict[str, Any]], nodata: int | float | None) -> dict[int, tuple[int, int, int, int]]:
    """Construye una paleta RGBA a partir de Value, Red, Green y Blue."""
    normalized = [{str(k).casefold(): v for k, v in row.items()} for row in rows]
    required = {"value", "red", "green", "blue"}
    if not normalized or not required.issubset(normalized[0]):
        return {}

    cmap: dict[int, tuple[int, int, int, int]] = {}
    for row in normalized:
        try:
            value = int(row["value"])
            rgba = (
                int(row["red"]),
                int(row["green"]),
                int(row["blue"]),
                255,
            )
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 65535:
            cmap[value] = rgba

    if nodata is not None and float(nodata).is_integer():
        nodata_i = int(nodata)
        if 0 <= nodata_i <= 65535:
            cmap[nodata_i] = (0, 0, 0, 0)
    return cmap


def crear_qml(output_raster: Path, rows: list[dict[str, Any]], nodata: int | float | None) -> Path | None:
    """Crea un estilo paletizado sencillo para QGIS."""
    normalized = [{str(k).casefold(): v for k, v in row.items()} for row in rows]
    needed = {"value", "class_name", "red", "green", "blue"}
    if not normalized or not needed.issubset(normalized[0]):
        return None

    root = ET.Element(
        "qgis",
        {
            "version": "3.34.0",
            "styleCategories": "Symbology",
        },
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

    if nodata is not None:
        ET.SubElement(
            palette,
            "paletteEntry",
            {
                "value": str(int(nodata)),
                "color": "#000000",
                "alpha": "0",
                "label": "Sin datos",
            },
        )

    for row in normalized:
        try:
            value = int(row["value"])
            red = int(row["red"])
            green = int(row["green"])
            blue = int(row["blue"])
            label = str(row["class_name"])
        except (TypeError, ValueError, KeyError):
            continue
        ET.SubElement(
            palette,
            "paletteEntry",
            {
                "value": str(value),
                "color": f"#{red:02x}{green:02x}{blue:02x}",
                "alpha": "255",
                "label": label,
            },
        )

    qml = output_raster.with_suffix(".qml")
    ET.ElementTree(root).write(qml, encoding="utf-8", xml_declaration=True)
    return qml


def escribir_world_file(output_raster: Path, transform: rasterio.Affine) -> Path:
    """Escribe un TFW auxiliar usando coordenadas del centro del píxel superior izquierdo."""
    c_center = transform.c + (transform.a / 2.0) + (transform.b / 2.0)
    f_center = transform.f + (transform.d / 2.0) + (transform.e / 2.0)
    tfw = output_raster.with_suffix(".tfw")
    values = [transform.a, transform.d, transform.b, transform.e, c_center, f_center]
    tfw.write_text("\n".join(f"{v:.12f}" for v in values) + "\n", encoding="ascii")
    return tfw


def calcular_estadisticas(data: np.ndarray) -> dict[str, str]:
    values = data.astype(np.float64, copy=False).ravel()
    mean = float(np.mean(values))
    std = float(np.std(values))
    return {
        "STATISTICS_MINIMUM": f"{float(np.min(values)):.15g}",
        "STATISTICS_MAXIMUM": f"{float(np.max(values)):.15g}",
        "STATISTICS_MEAN": f"{mean:.15g}",
        "STATISTICS_STDDEV": f"{std:.15g}",
        "STATISTICS_MEDIAN": f"{float(np.median(values)):.15g}",
        "STATISTICS_COVARIANCES": f"{std ** 2:.15g}",
        "STATISTICS_SKIPFACTORX": "1",
        "STATISTICS_SKIPFACTORY": "1",
    }


def escribir_aux_xml(output_raster: Path, data: np.ndarray, stats: dict[str, str]) -> Path:
    """Genera un PAM .aux.xml compatible con la naturaleza temática del raster."""
    root = ET.Element("PAMDataset")
    metadata = ET.SubElement(root, "Metadata")
    mdi = ET.SubElement(metadata, "MDI", {"key": "DataType"})
    mdi.text = "Thematic"

    metadata_esri = ET.SubElement(root, "Metadata", {"domain": "Esri"})
    mdi = ET.SubElement(metadata_esri, "MDI", {"key": "PyramidResamplingType"})
    mdi.text = "NEAREST"

    band = ET.SubElement(root, "PAMRasterBand", {"band": "1"})

    # Para uint8 se conserva el histograma completo de 256 categorías posibles.
    if data.dtype == np.uint8:
        counts = np.bincount(data.ravel(), minlength=256)[:256]
        histograms = ET.SubElement(band, "Histograms")
        hist_item = ET.SubElement(histograms, "HistItem")
        for tag, text in (
            ("HistMin", "-0.5"),
            ("HistMax", "255.5"),
            ("BucketCount", "256"),
            ("IncludeOutOfRange", "1"),
            ("Approximate", "0"),
            ("HistCounts", "|".join(str(int(v)) for v in counts)),
        ):
            element = ET.SubElement(hist_item, tag)
            element.text = text

    band_metadata = ET.SubElement(band, "Metadata")
    representation = ET.SubElement(band_metadata, "MDI", {"key": "RepresentationType"})
    representation.text = "THEMATIC"
    for key, value in stats.items():
        mdi = ET.SubElement(band_metadata, "MDI", {"key": key})
        mdi.text = value

    aux = Path(str(output_raster) + ".aux.xml")
    ET.ElementTree(root).write(aux, encoding="utf-8", xml_declaration=True)
    return aux


def copiar_tags_no_estadisticos(src: rasterio.DatasetReader, dst: rasterio.DatasetWriter) -> None:
    dataset_tags = src.tags()
    if dataset_tags:
        dst.update_tags(**dataset_tags)
    dst.update_tags(DataType="Thematic")

    band_tags = {k: v for k, v in src.tags(1).items() if k not in STAT_KEYS}
    band_tags["RepresentationType"] = "THEMATIC"
    dst.update_tags(1, **band_tags)


def main() -> int:
    args = parse_args()
    raster_path = args.raster.expanduser().resolve()
    vector_path = args.vector.expanduser().resolve()
    output_path = args.salida.expanduser().resolve()

    if not raster_path.exists():
        raise FileNotFoundError(f"No existe el raster: {raster_path}")
    if not vector_path.exists():
        raise FileNotFoundError(f"No existe el vector: {vector_path}")
    if output_path.suffix.lower() not in {".tif", ".tiff"}:
        raise ValueError("La salida debe tener extensión .tif o .tiff")
    if output_path == raster_path:
        raise ValueError("La salida debe ser distinta del raster de entrada.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Leer la capa vectorial. GeoPandas usa la primera capa cuando no se especifica.
    gdf = gpd.read_file(vector_path, layer=args.capa)
    if gdf.empty:
        raise ValueError("La capa vectorial no contiene entidades.")
    if gdf.crs is None:
        raise ValueError("La capa vectorial no tiene CRS definido.")

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.empty:
        raise ValueError("La capa vectorial no contiene geometrías válidas.")

    # Reparar geometrías cuando la versión de GeoPandas/Shapely lo permite.
    try:
        gdf.geometry = gdf.geometry.make_valid()
    except AttributeError:
        gdf.geometry = gdf.geometry.buffer(0)

    source_dbf, source_cpg = buscar_vat(raster_path)

    with rasterio.open(raster_path) as src:
        if src.count != 1:
            raise ValueError(
                f"Se esperaba un raster temático de una banda, pero tiene {src.count} bandas."
            )
        if src.crs is None:
            raise ValueError("El raster no tiene CRS definido.")
        if not np.issubdtype(np.dtype(src.dtypes[0]), np.integer):
            raise ValueError(
                f"El raster debe tener clases enteras; el tipo encontrado es {src.dtypes[0]}."
            )

        gdf = gdf.to_crs(src.crs)
        geometry = gdf.geometry.union_all()
        if geometry.is_empty:
            raise ValueError("La unión de las geometrías de recorte quedó vacía.")
        if not geometry.intersects(box(*src.bounds)):
            raise ValueError("La capa vectorial no intersecta la extensión del raster.")

        nodata = args.nodata if args.nodata is not None else src.nodata
        if nodata is None:
            nodata = 0

        clipped, out_transform = mask(
            src,
            [mapping(geometry)],
            crop=True,
            nodata=nodata,
            filled=True,
            all_touched=args.all_touched,
            indexes=[1],
        )
        data = clipped[0]

        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            transform=out_transform,
            count=1,
            nodata=nodata,
            compress=src.profile.get("compress", "lzw") or "lzw",
            tiled=True,
            BIGTIFF="IF_SAFER",
        )

        # Mantener bloques válidos para TIFF. Se conservan los originales cuando existen.
        profile["blockxsize"] = int(src.profile.get("blockxsize", 256))
        profile["blockysize"] = int(src.profile.get("blockysize", 256))

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(data, 1)
            copiar_tags_no_estadisticos(src, dst)

            if src.descriptions[0]:
                dst.set_band_description(1, src.descriptions[0])
            try:
                dst.scales = src.scales
                dst.offsets = src.offsets
                dst.units = src.units
            except (AttributeError, TypeError, ValueError):
                pass

            stats = calcular_estadisticas(data)
            dst.update_tags(1, **stats)

            # La tabla VAT se procesa antes de escribir la paleta.
            if source_dbf is not None:
                unique, freq = np.unique(data, return_counts=True)
                counts = {int(v): int(n) for v, n in zip(unique, freq)}
                _, vat_rows = actualizar_y_escribir_vat(
                    source_dbf, source_cpg, output_path, counts
                )
                colormap = crear_colormap(vat_rows, nodata)
                if colormap:
                    try:
                        dst.write_colormap(1, colormap)
                    except ValueError as exc:
                        print(f"ADVERTENCIA: no se pudo incorporar la paleta: {exc}", file=sys.stderr)
            else:
                vat_rows = []
                print(
                    "ADVERTENCIA: no se encontró la tabla lateral "
                    f"{raster_path.name}.vat.dbf; se conservarán valores y metadatos, "
                    "pero no los nombres de clase.",
                    file=sys.stderr,
                )

            if not args.sin_overviews:
                levels = [
                    level
                    for level in (2, 4, 8, 16, 32, 64)
                    if min(data.shape) // level >= 64
                ]
                if levels:
                    dst.build_overviews(levels, Resampling.nearest)
                    dst.update_tags(ns="rio_overview", resampling="nearest")

    # Archivos auxiliares fuera del contexto de escritura del TIFF.
    stats = calcular_estadisticas(data)
    aux_path = escribir_aux_xml(output_path, data, stats)
    tfw_path = escribir_world_file(output_path, out_transform)

    qml_path = None
    if source_dbf is not None and not args.sin_qml:
        qml_path = crear_qml(output_path, vat_rows, nodata)

    print("Proceso completado correctamente")
    print(f"  Raster:        {output_path}")
    print(f"  Tamaño:        {data.shape[1]} x {data.shape[0]} píxeles")
    print(f"  Tipo:          {data.dtype}")
    print(f"  Nodata:        {nodata}")
    print(f"  AUX XML:       {aux_path}")
    print(f"  World file:    {tfw_path}")
    if source_dbf is not None:
        print(f"  VAT DBF:       {Path(str(output_path) + '.vat.dbf')}")
        print(f"  VAT CPG:       {Path(str(output_path) + '.vat.cpg')}")
    if qml_path is not None:
        print(f"  Estilo QGIS:   {qml_path}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
