#!/usr/bin/env python3
"""Crea un GeoPackage con los puntos de entrenamiento y estilos de validación espacial.

Toma sample_index.csv del A4.8, añade geometría desde lon/lat, y genera un GeoPackage
con un estilo QML que colorea los puntos por rol (development_cv, independent_validation, excluded_border).

Salida:
  - training_points_with_split_roles.gpkg (con puntos y estilo QML)
  - training_points_with_split_roles.qml (estilo independiente)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

LOGGER = logging.getLogger("prepare_training_points")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else Path.cwd()

# Configuración de estilos por rol
ROLE_COLORS = {
    "development_cv": "#1F6F78",  # Turquesa/verde (training)
    "independent_validation": "#2C7FB8",  # Azul (testing)
    "excluded_border": "#D73027",  # Rojo (excluded)
}

ROLE_LABELS = {
    "development_cv": "Desarrollo (Entrenamiento CV)",
    "independent_validation": "Validación Independiente",
    "excluded_border": "Excluido (Borde)",
}


def configure_logger(output_dir: Path) -> None:
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler()]
    handlers.append(
        logging.FileHandler(
            output_dir / "logs" / "prepare_training_points.log", encoding="utf-8"
        )
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.expanduser().resolve()
    return (REPO_ROOT / path).expanduser().resolve()


def read_sample_index(sample_index_csv: Path) -> pd.DataFrame:
    if not sample_index_csv.exists():
        raise FileNotFoundError(f"No existe sample_index.csv: {sample_index_csv}")
    df = pd.read_csv(sample_index_csv, low_memory=False)
    required = ["xy_group_id", "split_role"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas en sample_index.csv: {missing}")
    LOGGER.info("sample_index.csv leído: filas=%s", len(df))
    return df


def read_coordinates(modeling_dataset_parquet: Path) -> pd.DataFrame:
    """Lee lon/lat desde el dataset de modelado."""
    if modeling_dataset_parquet.exists():
        try:
            df = pd.read_parquet(modeling_dataset_parquet, columns=["xy_group_id", "lon", "lat"])
            LOGGER.info("Coordenadas leídas desde Parquet")
            return df
        except Exception as exc:
            LOGGER.warning("No se pudo leer Parquet (%s); se intentará CSV", exc)
    
    modeling_dataset_csv = modeling_dataset_parquet.parent / "modeling_dataset.csv"
    if not modeling_dataset_csv.exists():
        raise FileNotFoundError(
            f"No se encontró dataset de modelado. Parquet={modeling_dataset_parquet}; CSV={modeling_dataset_csv}"
        )
    df = pd.read_csv(modeling_dataset_csv, usecols=["xy_group_id", "lon", "lat"], low_memory=False)
    LOGGER.info("Coordenadas leídas desde CSV")
    return df


def merge_with_coordinates(
    sample_index_df: pd.DataFrame,
    coordinates_df: pd.DataFrame
) -> pd.DataFrame:
    """Une sample_index con coordenadas."""
    required_coords = ["xy_group_id", "lon", "lat"]
    missing = [col for col in required_coords if col not in coordinates_df.columns]
    if missing:
        raise ValueError(f"Faltan columnas en dataset: {missing}")
    
    merged = sample_index_df.merge(
        coordinates_df,
        on="xy_group_id",
        how="left",
        validate="many_to_one"
    )
    missing_coords = merged["lon"].isna().sum()
    if missing_coords > 0:
        LOGGER.warning("Hay %s puntos sin coordenadas", missing_coords)
        merged = merged.dropna(subset=["lon", "lat"])
    
    LOGGER.info("Datos unidos: filas=%s (tras eliminar sin coordenadas)", len(merged))
    return merged


def create_geodataframe(merged_df: pd.DataFrame) -> gpd.GeoDataFrame:
    """Convierte DataFrame a GeoDataFrame con geometría de puntos."""
    geometry = [Point(xy) for xy in zip(merged_df["lon"], merged_df["lat"])]
    gdf = gpd.GeoDataFrame(merged_df, geometry=geometry, crs="EPSG:4326")
    LOGGER.info("GeoDataFrame creado: geometría=POINT, crs=EPSG:4326")
    return gdf


def build_qml_style(gdf: gpd.GeoDataFrame) -> str:
    """Genera un QML con estilos por split_role."""
    roles_in_data = gdf["split_role"].unique()
    rules = []
    for role in roles_in_data:
        if pd.isna(role):
            continue
        role = str(role).strip()
        color = ROLE_COLORS.get(role, "#808080")
        label = ROLE_LABELS.get(role, role)
        rules.append(
            f"""    <rule>
      <filter>split_role = '{role}'</filter>
      <PointSymbolizer>
        <Graphic>
          <Mark>
            <WellKnownName>circle</WellKnownName>
            <Fill>
              <CssParameter name="fill">{color}</CssParameter>
            </Fill>
            <Stroke>
              <CssParameter name="stroke">#000000</CssParameter>
              <CssParameter name="stroke-width">0.5</CssParameter>
            </Stroke>
          </Mark>
          <Size>8</Size>
        </Graphic>
      </PointSymbolizer>
      <TextSymbolizer>
        <Label>{label}</Label>
        <Font>
          <CssParameter name="font-family">Arial</CssParameter>
          <CssParameter name="font-size">10</CssParameter>
        </Font>
        <Halo>
          <Radius>1</Radius>
          <Fill>
            <CssParameter name="fill">#FFFFFF</CssParameter>
          </Fill>
        </Halo>
        <Placement>
          <PointPlacement>
            <Displacement>
              <DisplacementX>0</DisplacementX>
              <DisplacementY>15</DisplacementY>
            </Displacement>
          </PointPlacement>
        </Placement>
      </TextSymbolizer>
    </rule>
"""
        )

    qml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xsi:schemaLocation="http://www.opengis.net/sld StyledLayerDescriptor.xsd"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <NamedLayer>
    <Name>Puntos de Entrenamiento - Roles de Validación</Name>
    <UserStyle>
      <FeatureTypeStyle>
{"".join(rules)}      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
"""
    return qml_content


def save_gpkg_and_style(
    gdf: gpd.GeoDataFrame,
    output_gpkg: Path,
    output_sld: Path,
) -> None:
    """Guarda el GeoPackage y el SLD."""
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(output_gpkg, driver="GPKG", layer="training_points", index=False)
    LOGGER.info("GeoPackage escrito: %s", output_gpkg)

    qml_content = build_qml_style(gdf)
    output_sld.write_text(qml_content, encoding="utf-8")
    LOGGER.info("Estilo SLD escrito: %s", output_sld)


def main() -> None:
    output_dir = resolve_path("data/processed/a4_8_dnn_prepared_data")
    configure_logger(output_dir)

    sample_index_csv = output_dir / "tables" / "sample_index.csv"
    modeling_dataset_parquet = output_dir.parent / "a4_6_modeling_dataset" / "tables" / "modeling_dataset.parquet"
    output_gpkg = output_dir / "tables" / "training_points_with_split_roles.gpkg"
    output_sld = output_dir / "tables" / "training_points_with_split_roles.sld"

    LOGGER.info("Iniciando preparación de puntos de entrenamiento con estilos")

    df = read_sample_index(sample_index_csv)
    coords = read_coordinates(modeling_dataset_parquet)
    merged = merge_with_coordinates(df, coords)
    gdf = create_geodataframe(merged)
    save_gpkg_and_style(gdf, output_gpkg, output_sld)

    LOGGER.info("Preparación finalizada:")
    LOGGER.info("  GeoPackage: %s", output_gpkg)
    LOGGER.info("  Estilo SLD: %s", output_sld)
    print(f"\nPuntos de entrenamiento con estilos creados:")
    print(f"  GeoPackage: {output_gpkg}")
    print(f"  Estilo (SLD): {output_sld}")
    print(f"\nCarga en QGIS:")
    print(f"  1. Abre {output_gpkg}")
    print(f"  2. Haz clic derecho en la capa - Propiedades - Estilo")
    print(f"  3. Carga {output_sld} (o copia el contenido)")


if __name__ == "__main__":
    main()
