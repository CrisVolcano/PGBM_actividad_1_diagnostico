#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
download_esa_worldcover_by_aoi.py

Descarga tiles ESA WorldCover desde AWS usando un AOI vectorial local
ubicado dentro del repositorio.

No usa Google Earth Engine.
No usa rutas absolutas.
No recibe argumentos por bash.

Estructura esperada del repositorio:

repo/
├── data/
│   ├── aoi/
│   │   └── paises_interes.shp  # o .gpkg / .geojson
│   └── raw/
│       └── ESA_WorldCover/
└── scripts/
    └── download_esa_worldcover_by_aoi.py

Flujo:
1. Detecta automáticamente la raíz del repositorio.
2. Busca el AOI dentro de data/aoi/.
3. Lista los tiles ESA WorldCover disponibles en AWS.
4. Construye footprints de tiles 3 x 3 grados.
5. Selecciona solo los tiles que intersectan el AOI.
6. Descarga únicamente esos GeoTIFFs.
7. Genera manifiestos CSV y GPKG.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import boto3
import geopandas as gpd
import pandas as pd
from botocore import UNSIGNED
from botocore.config import Config
from shapely.geometry import box
from shapely.ops import unary_union
from tqdm import tqdm


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

YEAR = "2020"

# Primera corrida recomendada:
# True  = solo genera manifiestos y muestra qué tiles descargaría.
# False = descarga los archivos.
DRY_RUN = False

# Sobrescribir archivos existentes.
OVERWRITE = False

# Nombre esperado del AOI dentro de data/aoi/.
# Puedes cambiar solo este nombre, no toda la ruta.
# Acepta .shp, .gpkg, .geojson, .json.
AOI_FILE_STEM = "paises_interes"

# Si usas GeoPackage con varias capas, puedes indicar la capa.
# Para shapefile o geojson dejar None.
AOI_LAYER = None


# Bucket público de ESA WorldCover.
BUCKET = "esa-worldcover"

WORLD_COVER_CONFIG = {
    "2020": {
        "version": "v100",
        "prefix": "v100/2020/map/",
        "regex": r"ESA_WorldCover_10m_2020_v100_([NS]\d{2})([EW]\d{3})_Map\.tif$",
    },
    "2021": {
        "version": "v200",
        "prefix": "v200/2021/map/",
        "regex": r"ESA_WorldCover_10m_2021_v200_([NS]\d{2})([EW]\d{3})_Map\.tif$",
    },
}


# ============================================================
# DETECCIÓN DE RUTAS DEL REPOSITORIO
# ============================================================

def find_repo_root(start_path: Path | None = None) -> Path:
    """
    Detecta la raíz del repositorio buscando una carpeta data/
    o un directorio .git hacia arriba desde la ubicación del script.
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
        "Asegúrate de que exista una carpeta data/ en el repo."
    )


def find_aoi_file(data_dir: Path, stem: str) -> Path:
    """
    Busca automáticamente el AOI dentro de data/aoi/
    usando el nombre base definido en AOI_FILE_STEM.
    """
    aoi_dir = data_dir / "aoi"

    if not aoi_dir.exists():
        raise FileNotFoundError(
            f"No existe la carpeta esperada de AOI: {aoi_dir}"
        )

    allowed_ext = [".shp", ".gpkg", ".geojson", ".json"]

    candidates = [
        aoi_dir / f"{stem}{ext}"
        for ext in allowed_ext
        if (aoi_dir / f"{stem}{ext}").exists()
    ]

    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) > 1:
        raise RuntimeError(
            "Se encontró más de un AOI con el mismo nombre base:\n"
            + "\n".join(str(c) for c in candidates)
            + "\nDeja solo uno o ajusta AOI_FILE_STEM."
        )

    # Si no encuentra exactamente el stem, busca cualquier archivo vectorial.
    fallback_candidates = []

    for ext in allowed_ext:
        fallback_candidates.extend(aoi_dir.glob(f"*{ext}"))

    if len(fallback_candidates) == 1:
        return fallback_candidates[0]

    if len(fallback_candidates) > 1:
        raise RuntimeError(
            "No se encontró el AOI con AOI_FILE_STEM, "
            "pero hay varios archivos vectoriales en data/aoi/:\n"
            + "\n".join(str(c) for c in fallback_candidates)
            + "\nDefine AOI_FILE_STEM con el nombre correcto."
        )

    raise FileNotFoundError(
        f"No se encontró ningún AOI en {aoi_dir}. "
        "Coloca ahí un .shp, .gpkg, .geojson o .json."
    )


REPO_ROOT = find_repo_root()
DATA_DIR = REPO_ROOT / "data"
AOI_PATH = DATA_DIR / "raw" / "paises_region_estudio" / "paises_region_estudio.gpkg"
OUT_DIR = DATA_DIR / "raw" / "ESA_WorldCover_mangrove_2020"


# ============================================================
# FUNCIONES AWS
# ============================================================

def make_s3_client():
    """
    Crea cliente S3 sin credenciales.
    El bucket ESA WorldCover es público.
    """
    return boto3.client(
        "s3",
        region_name="eu-central-1",
        config=Config(signature_version=UNSIGNED),
    )


def list_s3_objects(s3, bucket: str, prefix: str) -> List[Dict]:
    """
    Lista objetos .tif dentro del prefijo indicado.
    """
    objects: List[Dict] = []
    continuation_token = None

    while True:
        kwargs = {
            "Bucket": bucket,
            "Prefix": prefix,
            "MaxKeys": 1000,
        }

        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        response = s3.list_objects_v2(**kwargs)

        for obj in response.get("Contents", []):
            key = obj["Key"]

            if key.endswith(".tif"):
                objects.append(
                    {
                        "key": key,
                        "size_bytes": int(obj["Size"]),
                        "last_modified": obj["LastModified"],
                        "etag": obj.get("ETag", "").replace('"', ""),
                    }
                )

        if not response.get("IsTruncated"):
            break

        continuation_token = response.get("NextContinuationToken")

    return objects


# ============================================================
# FUNCIONES TILES ESA
# ============================================================

def parse_esa_tile_origin(lat_code: str, lon_code: str) -> Tuple[int, int]:
    """
    Interpreta códigos ESA como N09W084.

    ESA WorldCover usa tiles de 3 x 3 grados.
    El código representa la esquina inferior izquierda del tile.

    Ejemplo:
        N09W084 -> lat_min = 9, lon_min = -84
    """
    lat_sign = 1 if lat_code[0] == "N" else -1
    lon_sign = 1 if lon_code[0] == "E" else -1

    lat_min = lat_sign * int(lat_code[1:])
    lon_min = lon_sign * int(lon_code[1:])

    return lat_min, lon_min


def build_tile_index(objects: List[Dict], regex: str) -> gpd.GeoDataFrame:
    """
    Construye un índice vectorial de tiles ESA WorldCover.
    """
    records = []
    pattern = re.compile(regex)

    for obj in objects:
        filename = Path(obj["key"]).name
        match = pattern.search(filename)

        if match is None:
            continue

        lat_code = match.group(1)
        lon_code = match.group(2)

        lat_min, lon_min = parse_esa_tile_origin(lat_code, lon_code)

        tile_id = f"{lat_code}{lon_code}"

        geom = box(
            lon_min,
            lat_min,
            lon_min + 3,
            lat_min + 3,
        )

        records.append(
            {
                "tile_id": tile_id,
                "filename": filename,
                "bucket": BUCKET,
                "key": obj["key"],
                "s3_uri": f"s3://{BUCKET}/{obj['key']}",
                "https_url": f"https://{BUCKET}.s3.amazonaws.com/{obj['key']}",
                "size_bytes": obj["size_bytes"],
                "size_mb": round(obj["size_bytes"] / (1024**2), 2),
                "etag": obj["etag"],
                "last_modified": str(obj["last_modified"]),
                "lon_min": lon_min,
                "lat_min": lat_min,
                "lon_max": lon_min + 3,
                "lat_max": lat_min + 3,
                "geometry": geom,
            }
        )

    if not records:
        raise RuntimeError(
            "No se pudo construir el índice de tiles. "
            "Revisar prefix o regex de nombres ESA WorldCover."
        )

    return gpd.GeoDataFrame(records, crs="EPSG:4326")


# ============================================================
# FUNCIONES AOI
# ============================================================

def read_aoi_geometry(aoi_path: Path, layer: str | None = None):
    """
    Lee AOI local y lo transforma a EPSG:4326.
    """
    if not aoi_path.exists():
        raise FileNotFoundError(f"No existe el AOI: {aoi_path}")

    if layer is None:
        aoi = gpd.read_file(aoi_path)
    else:
        aoi = gpd.read_file(aoi_path, layer=layer)

    if aoi.empty:
        raise ValueError(f"El AOI está vacío: {aoi_path}")

    if aoi.crs is None:
        raise ValueError(
            "El AOI no tiene CRS definido. "
            "Define el CRS antes de correr este script."
        )

    aoi = aoi.to_crs("EPSG:4326")

    # Reparación simple de geometrías inválidas.
    aoi["geometry"] = aoi.geometry.buffer(0)

    aoi = aoi[~aoi.geometry.is_empty].copy()

    if aoi.empty:
        raise ValueError("El AOI quedó vacío después de reparar geometrías.")

    geom = unary_union(aoi.geometry)

    if geom.is_empty:
        raise ValueError("La geometría unificada del AOI está vacía.")

    return aoi, geom


def select_intersecting_tiles(
    tiles: gpd.GeoDataFrame,
    aoi_geom,
) -> gpd.GeoDataFrame:
    """
    Selecciona tiles que intersectan el AOI.
    """
    selected = tiles[tiles.geometry.intersects(aoi_geom)].copy()

    if selected.empty:
        raise RuntimeError(
            "Ningún tile ESA WorldCover intersecta el AOI. "
            "Revisar CRS, ubicación o geometría del AOI."
        )

    selected = selected.sort_values("tile_id").reset_index(drop=True)

    return selected


# ============================================================
# DESCARGA
# ============================================================

class TqdmDownloadProgress:
    """
    Barra de progreso para boto3.
    """

    def __init__(self, total: int, desc: str):
        self.pbar = tqdm(
            total=total,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=desc,
        )

    def __call__(self, bytes_amount: int):
        self.pbar.update(bytes_amount)

    def close(self):
        self.pbar.close()


def download_tile(
    s3,
    bucket: str,
    key: str,
    local_path: Path,
    expected_size: int,
    overwrite: bool = False,
) -> str:
    """
    Descarga un tile desde S3.
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)

    if local_path.exists() and not overwrite:
        local_size = local_path.stat().st_size

        if local_size == expected_size:
            return "skipped_exists_size_ok"

        return "exists_size_mismatch_use_overwrite"

    progress = TqdmDownloadProgress(
        total=expected_size,
        desc=local_path.name,
    )

    try:
        s3.download_file(
            Bucket=bucket,
            Key=key,
            Filename=str(local_path),
            Callback=progress,
        )
    finally:
        progress.close()

    return "downloaded"


# ============================================================
# MANIFIESTOS
# ============================================================

def write_manifests(
    selected: gpd.GeoDataFrame,
    out_dir: Path,
    year: str,
) -> None:
    """
    Guarda manifiestos CSV y GPKG de tiles seleccionados.
    """
    manifest_dir = out_dir / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    csv_path = manifest_dir / f"esa_worldcover_{year}_selected_tiles.csv"
    gpkg_path = manifest_dir / f"esa_worldcover_{year}_selected_tiles.gpkg"

    selected.drop(columns="geometry").to_csv(
        csv_path,
        index=False,
        encoding="utf-8",
    )

    selected.to_file(
        gpkg_path,
        layer="selected_tiles",
        driver="GPKG",
    )

    print(f"\nManifest CSV: {csv_path}")
    print(f"Manifest GPKG: {gpkg_path}")


def write_download_status(
    statuses: List[Dict],
    out_dir: Path,
    year: str,
) -> None:
    """
    Guarda estado de descargas.
    """
    manifest_dir = out_dir / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    status_df = pd.DataFrame(statuses)

    status_path = manifest_dir / f"esa_worldcover_{year}_download_status.csv"

    status_df.to_csv(
        status_path,
        index=False,
        encoding="utf-8",
    )

    print("\nResumen de descarga:")
    print(status_df["status"].value_counts())
    print(f"\nStatus CSV: {status_path}")


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    if YEAR not in WORLD_COVER_CONFIG:
        raise ValueError(
            f"YEAR inválido: {YEAR}. Opciones: {list(WORLD_COVER_CONFIG.keys())}"
        )

    config = WORLD_COVER_CONFIG[YEAR]
    prefix = config["prefix"]
    regex = config["regex"]

    tiles_dir = OUT_DIR / YEAR / "map_tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== ESA WorldCover AOI downloader ===")
    print(f"Repositorio: {REPO_ROOT}")
    print(f"Data dir: {DATA_DIR}")
    print(f"Año: {YEAR}")
    print(f"Bucket: s3://{BUCKET}")
    print(f"Prefix: {prefix}")
    print(f"AOI detectado: {AOI_PATH}")
    print(f"Salida: {OUT_DIR}")
    print(f"DRY_RUN: {DRY_RUN}")
    print(f"OVERWRITE: {OVERWRITE}")

    print("\nLeyendo AOI...")
    aoi_gdf, aoi_geom = read_aoi_geometry(AOI_PATH, AOI_LAYER)

    print(f"AOI features: {len(aoi_gdf)}")
    print(f"AOI bounds EPSG:4326: {aoi_gdf.total_bounds}")

    print("\nListando tiles ESA WorldCover desde AWS...")
    s3 = make_s3_client()

    objects = list_s3_objects(
        s3=s3,
        bucket=BUCKET,
        prefix=prefix,
    )

    print(f"Objetos .tif listados: {len(objects)}")

    print("\nConstruyendo índice de tiles...")
    all_tiles = build_tile_index(
        objects=objects,
        regex=regex,
    )

    print(f"Tiles parseados: {len(all_tiles)}")

    print("\nSeleccionando tiles que intersectan el AOI...")
    selected = select_intersecting_tiles(
        tiles=all_tiles,
        aoi_geom=aoi_geom,
    )

    total_mb = selected["size_mb"].sum()
    total_gb = total_mb / 1024

    print(f"Tiles seleccionados: {len(selected)}")
    print(f"Tamaño estimado: {total_mb:.2f} MB / {total_gb:.2f} GB")
    print("IDs de tiles seleccionados:")
    print(", ".join(selected["tile_id"].tolist()))

    write_manifests(
        selected=selected,
        out_dir=OUT_DIR,
        year=YEAR,
    )

    if DRY_RUN:
        print("\nDRY_RUN = True. No se descargó ningún archivo.")
        print("Revise los manifiestos. Si todo está bien, cambie DRY_RUN = False.")
        return

    print("\nDescargando tiles seleccionados...")

    statuses = []

    for _, row in selected.iterrows():
        local_path = tiles_dir / row["filename"]

        status = download_tile(
            s3=s3,
            bucket=row["bucket"],
            key=row["key"],
            local_path=local_path,
            expected_size=int(row["size_bytes"]),
            overwrite=OVERWRITE,
        )

        statuses.append(
            {
                "tile_id": row["tile_id"],
                "filename": row["filename"],
                "status": status,
                "local_path": str(local_path),
                "size_mb": row["size_mb"],
                "s3_uri": row["s3_uri"],
                "https_url": row["https_url"],
            }
        )

    write_download_status(
        statuses=statuses,
        out_dir=OUT_DIR,
        year=YEAR,
    )

    print("\nListo.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)