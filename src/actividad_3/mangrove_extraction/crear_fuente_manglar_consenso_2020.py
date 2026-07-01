#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
crear_fuente_manglar_consenso_2020.py

Construye una fuente espacial de alta confianza para manglar a partir de:

    Global Mangrove Watch 2020
    INTERSECT
    ESA WorldCover 2020 clase 95: Mangroves

No extrae puntos.
No hace auditoría espectral.
No usa Google Earth Engine.

Salida:
    data/processed/mangrove_consensus_2020/

El flujo es:
1. Detectar automáticamente la raíz del repositorio.
2. Leer AOI regional desde data/raw/paises_region_estudio/.
3. Leer tiles ESA WorldCover 2020 descargados.
4. Leer rasters GMW 2020.
5. Crear máscara ESA manglar: ESA == 95.
6. Crear máscara GMW manglar: GMW > 0.
7. Intersectar ambas máscaras usando la grilla de ESA.
8. Generar raster crudo de consenso por tile.
9. Vectorizar el consenso crudo.
10. Disolver parches contiguos.
11. Calcular área en proyección equivalente.
12. Eliminar parches menores a 0.5 ha.
13. Guardar vector final y raster final filtrado.

"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features, windows
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.warp import reproject, transform_bounds
from shapely.geometry import box, shape
from shapely.ops import unary_union
from tqdm import tqdm


# ============================================================
# CONFIGURACIÓN
# ============================================================

YEAR = "2020"

ESA_MANGROVE_VALUE = 95

# Umbral final solicitado:
# eliminar parches menores a 0.5 ha.
MIN_PATCH_HA = 0.5

# Proyección equivalente para calcular área.
# EPSG:6933 = World Cylindrical Equal Area.
AREA_CRS = "EPSG:6933"

# Carpetas relativas a data/.
AOI_SUBDIR = Path("raw") / "paises_region_estudio"
ESA_SUBDIR = Path("raw") / "ESA_WorldCover_mangrove_2020"
GMW_SUBDIR = Path("raw") / "gmw_mangrove_data_2020"
OUT_SUBDIR = Path("processed") / "mangrove_consensus_2020"

# Nombre base esperado del AOI.
# Si no encuentra este nombre, busca automáticamente un único vector
# dentro de data/raw/paises_region_estudio/.
AOI_FILE_STEM = "paises_region_estudio"
AOI_LAYER = None

# GMW normalmente usa 1 = manglar y 0 = no manglar.
# Si se deja None, el script usa GMW > 0.
# Si conoces valores específicos, puedes poner por ejemplo: [1]
GMW_MANGROVE_VALUES = None

# Conectividad conceptual para la limpieza vectorial:
# se disuelven parches que se tocan.
# El filtro final se hace por área vectorial >= 0.5 ha.
FILTER_MIN_AREA_VECTOR = True

# También generar raster final filtrado desde el vector depurado.
WRITE_FILTERED_RASTER_TILES = True

# Sobrescribir salidas existentes.
OVERWRITE = True

# Compresión de salidas raster.
RASTER_COMPRESS = "DEFLATE"


# ============================================================
# DETECCIÓN DEL REPOSITORIO
# ============================================================

def find_repo_root(start_path: Path | None = None) -> Path:
    """
    Detecta la raíz del repositorio buscando una carpeta data/
    hacia arriba desde la ubicación del script.
    """
    if start_path is None:
        start_path = Path(__file__).resolve()

    current = start_path.parent if start_path.is_file() else start_path.resolve()

    candidates = [current] + list(current.parents)

    for candidate in candidates:
        if (candidate / "data").exists():
            return candidate

    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate

    raise RuntimeError(
        "No se pudo detectar la raíz del repositorio. "
        "Asegúrate de que exista una carpeta data/."
    )


REPO_ROOT = find_repo_root()
DATA_DIR = REPO_ROOT / "data"

AOI_DIR = DATA_DIR / AOI_SUBDIR
ESA_DIR = DATA_DIR / ESA_SUBDIR
GMW_DIR = DATA_DIR / GMW_SUBDIR
OUT_DIR = DATA_DIR / OUT_SUBDIR

RAW_RASTER_DIR = OUT_DIR / "raster_raw_tiles"
FILTERED_RASTER_DIR = OUT_DIR / "raster_filtered_tiles"
VECTOR_DIR = OUT_DIR / "vector"
MANIFEST_DIR = OUT_DIR / "manifest"
LOG_DIR = OUT_DIR / "logs"


# ============================================================
# BÚSQUEDA DE INSUMOS
# ============================================================

def find_vector_file(folder: Path, stem: str) -> Path:
    """
    Busca un archivo vectorial dentro de una carpeta.
    Primero intenta con el nombre base indicado.
    Si no lo encuentra, acepta un único vector disponible.
    """
    if not folder.exists():
        raise FileNotFoundError(f"No existe la carpeta: {folder}")

    allowed_ext = [".gpkg", ".shp", ".geojson", ".json"]

    candidates = [
        folder / f"{stem}{ext}"
        for ext in allowed_ext
        if (folder / f"{stem}{ext}").exists()
    ]

    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) > 1:
        raise RuntimeError(
            "Se encontró más de un AOI con el mismo nombre base:\n"
            + "\n".join(str(c) for c in candidates)
        )

    fallback = []

    for ext in allowed_ext:
        fallback.extend(folder.rglob(f"*{ext}"))

    if len(fallback) == 1:
        return fallback[0]

    if len(fallback) > 1:
        raise RuntimeError(
            "Hay varios archivos vectoriales posibles. "
            "Define AOI_FILE_STEM o deja solo uno en la carpeta:\n"
            + "\n".join(str(c) for c in fallback)
        )

    raise FileNotFoundError(
        f"No se encontró ningún vector en {folder}."
    )


def find_esa_tiles(folder: Path) -> List[Path]:
    """
    Busca tiles ESA WorldCover 2020 descargados.
    """
    if not folder.exists():
        raise FileNotFoundError(f"No existe la carpeta ESA: {folder}")

    patterns = [
        "**/ESA_WorldCover_10m_2020_v100_*_Map.tif",
        "**/*WorldCover*2020*v100*Map.tif",
        "**/*.tif",
        "**/*.tiff",
    ]

    for pattern in patterns:
        tiles = sorted(folder.rglob(pattern))
        if tiles:
            return tiles

    raise FileNotFoundError(
        f"No se encontraron rasters ESA WorldCover dentro de {folder}."
    )


def find_gmw_rasters(folder: Path) -> List[Path]:
    """
    Busca rasters Global Mangrove Watch 2020.
    """
    if not folder.exists():
        raise FileNotFoundError(f"No existe la carpeta GMW: {folder}")

    rasters = sorted(folder.rglob("*.tif")) + sorted(folder.rglob("*.tiff"))

    if rasters:
        return rasters

    zip_files = sorted(folder.rglob("*.zip"))

    if zip_files:
        raise FileNotFoundError(
            "No se encontraron .tif/.tiff de GMW, pero sí archivos .zip. "
            "Extrae primero los ZIP dentro de la carpeta GMW:\n"
            + "\n".join(str(z) for z in zip_files)
        )

    raise FileNotFoundError(
        f"No se encontraron rasters GMW dentro de {folder}."
    )


def get_tile_id_from_name(path: Path) -> str:
    """
    Extrae identificador tipo N09W084 desde el nombre de un tile ESA.
    """
    match = re.search(r"([NS]\d{2}[EW]\d{3})", path.name)

    if match:
        return match.group(1)

    return path.stem


# ============================================================
# LECTURA DE AOI
# ============================================================

def read_aoi(aoi_path: Path, layer: str | None = None) -> gpd.GeoDataFrame:
    """
    Lee AOI y transforma a EPSG:4326.
    """
    if layer is None:
        aoi = gpd.read_file(aoi_path)
    else:
        aoi = gpd.read_file(aoi_path, layer=layer)

    if aoi.empty:
        raise ValueError(f"AOI vacío: {aoi_path}")

    if aoi.crs is None:
        raise ValueError(
            f"El AOI no tiene CRS definido: {aoi_path}"
        )

    aoi = aoi.to_crs("EPSG:4326")
    aoi["geometry"] = aoi.geometry.buffer(0)
    aoi = aoi[~aoi.geometry.is_empty].copy()

    if aoi.empty:
        raise ValueError("El AOI quedó vacío después de reparar geometrías.")

    return aoi


# ============================================================
# ÍNDICE DE RASTERS GMW
# ============================================================

def build_gmw_index(
    gmw_paths: List[Path],
    target_crs,
) -> gpd.GeoDataFrame:
    """
    Construye un índice espacial de los rasters GMW.
    Los bounds se transforman al CRS objetivo.
    """
    records = []

    for path in tqdm(gmw_paths, desc="Indexando rasters GMW"):
        with rasterio.open(path) as src:
            bounds_target = transform_bounds(
                src.crs,
                target_crs,
                src.bounds.left,
                src.bounds.bottom,
                src.bounds.right,
                src.bounds.top,
                densify_pts=21,
            )

            records.append(
                {
                    "path": str(path),
                    "filename": path.name,
                    "crs": str(src.crs),
                    "nodata": src.nodata,
                    "width": src.width,
                    "height": src.height,
                    "geometry": box(*bounds_target),
                }
            )

    return gpd.GeoDataFrame(records, crs=target_crs)


# ============================================================
# UTILIDADES RASTER
# ============================================================

def make_output_profile(template_src) -> Dict:
    """
    Perfil base para raster binario de salida.
    """
    profile = template_src.profile.copy()

    profile.update(
        driver="GTiff",
        count=1,
        dtype="uint8",
        nodata=0,
        compress=RASTER_COMPRESS,
        predictor=1,
        tiled=True,
        blockxsize=512,
        blockysize=512,
        BIGTIFF="IF_SAFER",
        SPARSE_OK="TRUE",
    )

    return profile


def gmw_array_to_mask(arr: np.ndarray) -> np.ndarray:
    """
    Convierte bloque GMW reproyectado a máscara binaria de manglar.
    """
    if GMW_MANGROVE_VALUES is None:
        return arr > 0

    return np.isin(arr, GMW_MANGROVE_VALUES)


def rasterize_aoi_for_window(
    aoi_geom,
    out_shape: Tuple[int, int],
    transform,
) -> np.ndarray:
    """
    Rasteriza AOI para una ventana específica.
    """
    return rasterize(
        [(aoi_geom, 1)],
        out_shape=out_shape,
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=False,
    )


# ============================================================
# CREACIÓN DE CONSENSO CRUDO POR TILE
# ============================================================

def create_raw_consensus_for_tile(
    esa_path: Path,
    gmw_index: gpd.GeoDataFrame,
    aoi_geom,
    out_dir: Path,
) -> Dict:
    """
    Crea raster binario de consenso crudo para un tile ESA:

        ESA == 95 AND GMW > 0 AND dentro del AOI

    El resultado se escribe en la grilla del tile ESA.
    """
    tile_id = get_tile_id_from_name(esa_path)

    out_path = out_dir / f"mangrove_consensus_raw_gmw2020_esa2020_{tile_id}.tif"

    if out_path.exists() and not OVERWRITE:
        return {
            "tile_id": tile_id,
            "esa_path": str(esa_path),
            "raw_raster": str(out_path),
            "status": "skipped_exists",
            "consensus_pixels": None,
            "gmw_sources": None,
        }

    with rasterio.open(esa_path) as esa:
        if esa.crs is None:
            raise ValueError(f"ESA tile sin CRS: {esa_path}")

        tile_geom = box(*esa.bounds)

        gmw_overlap = gmw_index[gmw_index.geometry.intersects(tile_geom)].copy()

        if gmw_overlap.empty:
            return {
                "tile_id": tile_id,
                "esa_path": str(esa_path),
                "raw_raster": None,
                "status": "no_gmw_overlap",
                "consensus_pixels": 0,
                "gmw_sources": 0,
            }

        profile = make_output_profile(esa)

        out_dir.mkdir(parents=True, exist_ok=True)

        consensus_pixels = 0

        gmw_sources = []

        for _, row in gmw_overlap.iterrows():
            gmw_sources.append(
                {
                    "path": Path(row["path"]),
                    "geometry": row["geometry"],
                }
            )

        opened_gmw = []

        try:
            for src_info in gmw_sources:
                opened_gmw.append(
                    {
                        "src": rasterio.open(src_info["path"]),
                        "geometry": src_info["geometry"],
                    }
                )

            with rasterio.open(out_path, "w", **profile) as dst:

                block_iter = list(esa.block_windows(1))

                for _, window in tqdm(
                    block_iter,
                    desc=f"Procesando {tile_id}",
                    leave=False,
                ):
                    esa_arr = esa.read(1, window=window)

                    esa_mask = esa_arr == ESA_MANGROVE_VALUE

                    if not esa_mask.any():
                        continue

                    window_transform = windows.transform(window, esa.transform)
                    out_shape = (int(window.height), int(window.width))

                    block_bounds = windows.bounds(window, esa.transform)
                    block_geom = box(*block_bounds)

                    if not block_geom.intersects(aoi_geom):
                        continue

                    aoi_mask = rasterize_aoi_for_window(
                        aoi_geom=aoi_geom,
                        out_shape=out_shape,
                        transform=window_transform,
                    ).astype(bool)

                    esa_mask = esa_mask & aoi_mask

                    if not esa_mask.any():
                        continue

                    gmw_mask = np.zeros(out_shape, dtype=bool)

                    for gmw_item in opened_gmw:
                        gmw_src = gmw_item["src"]
                        gmw_geom = gmw_item["geometry"]

                        if not gmw_geom.intersects(block_geom):
                            continue

                        temp = np.zeros(out_shape, dtype="uint8")

                        reproject(
                            source=rasterio.band(gmw_src, 1),
                            destination=temp,
                            src_transform=gmw_src.transform,
                            src_crs=gmw_src.crs,
                            src_nodata=gmw_src.nodata,
                            dst_transform=window_transform,
                            dst_crs=esa.crs,
                            dst_nodata=0,
                            resampling=Resampling.nearest,
                        )

                        gmw_mask = gmw_mask | gmw_array_to_mask(temp)

                    if not gmw_mask.any():
                        continue

                    consensus = (esa_mask & gmw_mask).astype("uint8")

                    if consensus.any():
                        consensus_pixels += int(consensus.sum())
                        dst.write(consensus, 1, window=window)

        finally:
            for item in opened_gmw:
                item["src"].close()

    if consensus_pixels == 0:
        try:
            out_path.unlink()
        except FileNotFoundError:
            pass

        return {
            "tile_id": tile_id,
            "esa_path": str(esa_path),
            "raw_raster": None,
            "status": "no_consensus_pixels",
            "consensus_pixels": 0,
            "gmw_sources": len(gmw_overlap),
        }

    return {
        "tile_id": tile_id,
        "esa_path": str(esa_path),
        "raw_raster": str(out_path),
        "status": "created",
        "consensus_pixels": consensus_pixels,
        "gmw_sources": len(gmw_overlap),
    }


# ============================================================
# VECTORIZACIÓN Y FILTRO DE PARCHES
# ============================================================

def vectorize_raw_consensus(
    raw_rasters: List[Path],
    out_path: Path,
) -> gpd.GeoDataFrame:
    """
    Vectoriza todos los rasters crudos de consenso.
    """
    records = []

    for raster_path in tqdm(raw_rasters, desc="Vectorizando consenso crudo"):
        tile_id = get_tile_id_from_name(raster_path)

        with rasterio.open(raster_path) as src:
            crs = src.crs

            for geom_json, value in features.shapes(
                rasterio.band(src, 1),
                transform=src.transform,
            ):
                if int(value) != 1:
                    continue

                geom = shape(geom_json)

                if geom.is_empty:
                    continue

                records.append(
                    {
                        "tile_id": tile_id,
                        "value": 1,
                        "geometry": geom,
                    }
                )

    if not records:
        raise RuntimeError(
            "No se generó ningún polígono de consenso crudo."
        )

    raw_gdf = gpd.GeoDataFrame(records, crs=crs)

    raw_gdf["geometry"] = raw_gdf.geometry.buffer(0)
    raw_gdf = raw_gdf[~raw_gdf.geometry.is_empty].copy()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_gdf.to_file(out_path, layer="raw_consensus", driver="GPKG")

    return raw_gdf


def explode_geometry(geom) -> List:
    """
    Explota Polygon/MultiPolygon/GeometryCollection en geometrías individuales.
    """
    if geom.is_empty:
        return []

    if geom.geom_type == "Polygon":
        return [geom]

    if geom.geom_type in ["MultiPolygon", "GeometryCollection"]:
        parts = []

        for part in geom.geoms:
            parts.extend(explode_geometry(part))

        return parts

    return []


def dissolve_and_filter_patches(
    raw_gdf: gpd.GeoDataFrame,
    min_patch_ha: float,
    out_path: Path,
) -> gpd.GeoDataFrame:
    """
    Disuelve parches contiguos y elimina parches menores al umbral definido.
    """
    if raw_gdf.empty:
        raise ValueError("raw_gdf está vacío.")

    print("\nDisolviendo parches contiguos...")
    merged_geom = unary_union(raw_gdf.geometry)

    parts = explode_geometry(merged_geom)

    if not parts:
        raise RuntimeError(
            "No se generaron partes después del dissolve."
        )

    patches = gpd.GeoDataFrame(
        {
            "patch_id": list(range(1, len(parts) + 1)),
            "geometry": parts,
        },
        crs=raw_gdf.crs,
    )

    patches["geometry"] = patches.geometry.buffer(0)
    patches = patches[~patches.geometry.is_empty].copy()

    patches_area = patches.to_crs(AREA_CRS)
    patches["area_ha"] = patches_area.area / 10000.0

    patches["source"] = "GMW2020_ESAWorldCover2020"
    patches["rule"] = "GMW_2020_intersect_ESA_WorldCover_2020_class_95"
    patches["min_patch_ha"] = min_patch_ha
    patches["class_id"] = 95
    patches["class_name"] = "Mangrove"
    patches["confidence"] = "high_consensus"

    filtered = patches[patches["area_ha"] >= min_patch_ha].copy()
    filtered = filtered.reset_index(drop=True)
    filtered["patch_id"] = list(range(1, len(filtered) + 1))

    if filtered.empty:
        raise RuntimeError(
            f"Todos los parches fueron eliminados con umbral {min_patch_ha} ha."
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_file(out_path, layer="mangrove_consensus_min05ha", driver="GPKG")

    return filtered


# ============================================================
# RASTER FINAL FILTRADO
# ============================================================

def rasterize_filtered_vector_to_tiles(
    filtered_gdf: gpd.GeoDataFrame,
    esa_tiles: List[Path],
    out_dir: Path,
) -> List[Dict]:
    """
    Rasteriza el vector filtrado a la grilla de cada tile ESA.
    Escribe solo tiles con presencia de manglar filtrado.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    statuses = []

    for esa_path in tqdm(esa_tiles, desc="Rasterizando vector filtrado"):
        tile_id = get_tile_id_from_name(esa_path)

        with rasterio.open(esa_path) as esa:
            tile_geom = box(*esa.bounds)

            filtered_tile = filtered_gdf.to_crs(esa.crs)
            filtered_tile = filtered_tile[
                filtered_tile.geometry.intersects(tile_geom)
            ].copy()

            if filtered_tile.empty:
                statuses.append(
                    {
                        "tile_id": tile_id,
                        "filtered_raster": None,
                        "status": "no_filtered_polygon",
                    }
                )
                continue

            out_path = out_dir / f"mangrove_consensus_gmw2020_esa2020_min05ha_{tile_id}.tif"

            if out_path.exists() and not OVERWRITE:
                statuses.append(
                    {
                        "tile_id": tile_id,
                        "filtered_raster": str(out_path),
                        "status": "skipped_exists",
                    }
                )
                continue

            profile = make_output_profile(esa)

            sindex = filtered_tile.sindex

            written_pixels = 0

            with rasterio.open(out_path, "w", **profile) as dst:

                for _, window in esa.block_windows(1):
                    out_shape = (int(window.height), int(window.width))
                    window_transform = windows.transform(window, esa.transform)
                    block_geom = box(*windows.bounds(window, esa.transform))

                    idx = list(sindex.query(block_geom, predicate="intersects"))

                    if not idx:
                        continue

                    block_geoms = [
                        (geom, 1)
                        for geom in filtered_tile.iloc[idx].geometry
                        if geom.intersects(block_geom)
                    ]

                    if not block_geoms:
                        continue

                    arr = rasterize(
                        block_geoms,
                        out_shape=out_shape,
                        transform=window_transform,
                        fill=0,
                        dtype="uint8",
                        all_touched=False,
                    )

                    if arr.any():
                        written_pixels += int(arr.sum())
                        dst.write(arr, 1, window=window)

            if written_pixels == 0:
                try:
                    out_path.unlink()
                except FileNotFoundError:
                    pass

                statuses.append(
                    {
                        "tile_id": tile_id,
                        "filtered_raster": None,
                        "status": "no_pixels_written",
                    }
                )
            else:
                statuses.append(
                    {
                        "tile_id": tile_id,
                        "filtered_raster": str(out_path),
                        "status": "created",
                        "written_pixels": written_pixels,
                    }
                )

    return statuses


# ============================================================
# RESÚMENES
# ============================================================

def write_summary(
    raw_status: List[Dict],
    filtered_gdf: gpd.GeoDataFrame,
    raster_status: List[Dict] | None,
    out_dir: Path,
) -> None:
    """
    Guarda manifiestos y resumen general.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_df = pd.DataFrame(raw_status)
    raw_csv = out_dir / "raw_consensus_tile_status.csv"
    raw_df.to_csv(raw_csv, index=False, encoding="utf-8")

    summary = {
        "year": YEAR,
        "esa_mangrove_value": ESA_MANGROVE_VALUE,
        "min_patch_ha": MIN_PATCH_HA,
        "n_tiles_processed": len(raw_df),
        "n_tiles_created_raw": int((raw_df["status"] == "created").sum())
        if "status" in raw_df.columns else None,
        "n_final_patches": len(filtered_gdf),
        "total_area_ha": float(filtered_gdf["area_ha"].sum()),
        "min_area_ha": float(filtered_gdf["area_ha"].min()),
        "max_area_ha": float(filtered_gdf["area_ha"].max()),
        "mean_area_ha": float(filtered_gdf["area_ha"].mean()),
    }

    summary_df = pd.DataFrame([summary])
    summary_csv = out_dir / "mangrove_consensus_gmw2020_esa2020_min05ha_summary.csv"
    summary_df.to_csv(summary_csv, index=False, encoding="utf-8")

    if raster_status is not None:
        raster_df = pd.DataFrame(raster_status)
        raster_csv = out_dir / "filtered_raster_tile_status.csv"
        raster_df.to_csv(raster_csv, index=False, encoding="utf-8")

    print("\nResumen final:")
    print(summary_df.to_string(index=False))
    print(f"\nManifest raw tiles: {raw_csv}")
    print(f"Summary CSV: {summary_csv}")


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    for folder in [
        RAW_RASTER_DIR,
        FILTERED_RASTER_DIR,
        VECTOR_DIR,
        MANIFEST_DIR,
        LOG_DIR,
    ]:
        folder.mkdir(parents=True, exist_ok=True)

    print("\n=== Fuente de manglar consenso 2020 ===")
    print(f"Repositorio: {REPO_ROOT}")
    print(f"Data dir: {DATA_DIR}")
    print(f"AOI dir: {AOI_DIR}")
    print(f"ESA dir: {ESA_DIR}")
    print(f"GMW dir: {GMW_DIR}")
    print(f"Output dir: {OUT_DIR}")
    print(f"ESA mangrove value: {ESA_MANGROVE_VALUE}")
    print(f"Minimum patch area: {MIN_PATCH_HA} ha")
    print(f"Overwrite: {OVERWRITE}")

    aoi_path = find_vector_file(AOI_DIR, AOI_FILE_STEM)
    print(f"\nAOI detectado: {aoi_path}")

    aoi = read_aoi(aoi_path, AOI_LAYER)
    aoi_geom = unary_union(aoi.geometry)

    print(f"AOI features: {len(aoi)}")
    print(f"AOI bounds EPSG:4326: {aoi.total_bounds}")

    esa_tiles = find_esa_tiles(ESA_DIR)
    gmw_rasters = find_gmw_rasters(GMW_DIR)

    print(f"\nTiles ESA encontrados: {len(esa_tiles)}")
    print(f"Rasters GMW encontrados: {len(gmw_rasters)}")

    # Usamos el CRS del primer tile ESA como CRS de trabajo.
    with rasterio.open(esa_tiles[0]) as template:
        target_crs = template.crs

    if target_crs is None:
        raise ValueError(f"Primer tile ESA sin CRS: {esa_tiles[0]}")

    print(f"CRS de trabajo: {target_crs}")

    print("\nConstruyendo índice espacial de GMW...")
    gmw_index = build_gmw_index(gmw_rasters, target_crs)

    raw_status = []

    print("\nCreando consenso crudo por tile...")
    for esa_path in tqdm(esa_tiles, desc="Tiles ESA"):
        status = create_raw_consensus_for_tile(
            esa_path=esa_path,
            gmw_index=gmw_index,
            aoi_geom=aoi_geom,
            out_dir=RAW_RASTER_DIR,
        )

        raw_status.append(status)

    raw_df = pd.DataFrame(raw_status)

    created_raw = raw_df[
        raw_df["status"] == "created"
    ]["raw_raster"].dropna().tolist()

    raw_rasters = [Path(p) for p in created_raw]

    if not raw_rasters:
        raise RuntimeError(
            "No se generó ningún raster crudo de consenso. "
            "Revisar rutas, valores de GMW, clase ESA 95 y AOI."
        )

    raw_vector_path = VECTOR_DIR / "mangrove_consensus_gmw2020_esa2020_raw.gpkg"

    print("\nVectorizando consenso crudo...")
    raw_gdf = vectorize_raw_consensus(
        raw_rasters=raw_rasters,
        out_path=raw_vector_path,
    )

    print(f"Polígonos crudos: {len(raw_gdf)}")
    print(f"Vector crudo: {raw_vector_path}")

    filtered_vector_path = (
        VECTOR_DIR / "mangrove_consensus_gmw2020_esa2020_min05ha.gpkg"
    )

    filtered_gdf = dissolve_and_filter_patches(
        raw_gdf=raw_gdf,
        min_patch_ha=MIN_PATCH_HA,
        out_path=filtered_vector_path,
    )

    print(f"\nParches finales >= {MIN_PATCH_HA} ha: {len(filtered_gdf)}")
    print(f"Área total final: {filtered_gdf['area_ha'].sum():,.2f} ha")
    print(f"Vector final: {filtered_vector_path}")

    raster_status = None

    if WRITE_FILTERED_RASTER_TILES:
        print("\nGenerando raster final filtrado por tile...")
        raster_status = rasterize_filtered_vector_to_tiles(
            filtered_gdf=filtered_gdf,
            esa_tiles=esa_tiles,
            out_dir=FILTERED_RASTER_DIR,
        )

    write_summary(
        raw_status=raw_status,
        filtered_gdf=filtered_gdf,
        raster_status=raster_status,
        out_dir=MANIFEST_DIR,
    )

    print("\nListo.")
    print("\nSalida principal:")
    print(filtered_vector_path)

    if WRITE_FILTERED_RASTER_TILES:
        print(FILTERED_RASTER_DIR)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)