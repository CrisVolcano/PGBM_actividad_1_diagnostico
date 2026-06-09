# -*- coding: utf-8 -*-
# ============================================================
# A2.3 - Grid de balance por id_0_propuesta
# ============================================================
# Objetivo:
# Crear una malla regular de 20 km x 20 km ajustada a la
# extensión actual de la capa de puntos normalizados y calcular,
# por celda, el balance espacial entre las clases binarias 0 y 1
# de id_0_propuesta, derivado desde id_0 mediante la homologación A2.1.
#
# Flujo:
# 1. Leer puntos en EPSG:4326.
# 2. Leer homologación id_0 -> id_0_propuesta.
# 3. Derivar y validar el campo binario id_0_propuesta.
# 4. Reproyectar temporalmente a CRS métrico/equal-area.
# 5. Crear grid de 20 km en metros.
# 6. Asignar puntos a celdas mediante coordenadas.
# 7. Contar puntos totales, clase 0, clase 1, otros y nulos.
# 8. Calcular porcentajes, diferencia absoluta, clase dominante
#    e índice continuo de dominancia entre -1 y 1.
# 9. Conservar celdas sin puntos.
# 10. Exportar resultados en EPSG:4326 para QGIS.
#
# Entrada:
# data/processed/a2_1_modelo_datos/gpkg/a2_1_xy_point.gpkg
# layer: xy_point
#
# Campo derivado:
# id_0_propuesta
#
# Salidas:
# data/processed/a2_3_grid_balance_nivel_0_origen_propuesta/gpkg/grid_balance_nivel_0_origen_propuesta.gpkg
# data/processed/a2_3_grid_balance_nivel_0_origen_propuesta/tables/resumen_balance_nivel_0_origen_propuesta.csv
# data/processed/a2_3_grid_balance_nivel_0_origen_propuesta/tables/resumen_global_balance_nivel_0_origen_propuesta.csv
# data/processed/a2_3_grid_balance_nivel_0_origen_propuesta/figures/grid_balance_nivel_0_origen_propuesta.png
# ============================================================

from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import box
import matplotlib.pyplot as plt


# ============================================================
# CONFIG
# ============================================================

def get_project_root() -> Path:
    """
    Devuelve la raíz del proyecto.
    Si el script está en src/actividad_2/, sube dos niveles.
    Si se ejecuta en notebook o consola sin __file__, usa cwd().
    """
    try:
        return Path(__file__).resolve().parents[2]
    except NameError:
        return Path.cwd().resolve()


PROJECT_ROOT = get_project_root()

POINTS_GPKG = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "a2_1_modelo_datos"
    / "gpkg"
    / "a2_1_xy_point.gpkg"
)

POINTS_LAYER = "xy_point"

# Campo binario que se evaluará dentro de cada celda. No vive en xy_point:
# se deriva mediante la tabla de homologación creada en A2.1.
SOURCE_CLASS_FIELD = "id_0"
CLASS_FIELD = "id_0_propuesta"
HOMOLOGATION_TABLE = "homologacion_nivel_0_origen_propuesta"
HOMOLOGATION_SOURCE_FIELD = "id_0"
HOMOLOGATION_TARGET_FIELD = "id_0_propuesta"

# Valores esperados del campo binario.
CLASS_0_VALUE = 0
CLASS_1_VALUE = 1
EXPECTED_CLASS_VALUES = {CLASS_0_VALUE, CLASS_1_VALUE}

OUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "a2_3_grid_balance_nivel_0_origen_propuesta"
)

OUT_GPKG_DIR = OUT_DIR / "gpkg"
OUT_TABLE_DIR = OUT_DIR / "tables"
OUT_FIG_DIR = OUT_DIR / "figures"

OUT_GPKG = OUT_GPKG_DIR / "grid_balance_nivel_0_origen_propuesta.gpkg"
OUT_SUMMARY_CSV = OUT_TABLE_DIR / "resumen_balance_nivel_0_origen_propuesta.csv"
OUT_GLOBAL_CSV = OUT_TABLE_DIR / "resumen_global_balance_nivel_0_origen_propuesta.csv"
OUT_FIG = OUT_FIG_DIR / "grid_balance_nivel_0_origen_propuesta.png"

# Entrada esperada.
INPUT_CRS_EXPECTED = "EPSG:4326"

# CRS de trabajo en metros/equal-area.
# El cálculo de grid, área y densidad se hace aquí.
WORK_CRS = "EPSG:6933"

# CRS final para revisar en QGIS junto con las demás capas.
OUTPUT_CRS = "EPSG:4326"
EXPORT_TO_OUTPUT_CRS = True

# Grid de 20 km.
GRID_SIZE_M = 20_000

# Buffer opcional alrededor de la extensión de puntos.
# 0 = extensión exacta ajustada al múltiplo del grid.
EXTENT_BUFFER_M = 0

# Tolerancias para etiqueta interpretativa.
# BALANCE_TOLERANCE = 0.10 significa que valores entre -0.10 y 0.10
# se etiquetan como equilibrio operativo.
# Si se desea etiquetar solo equilibrio perfecto, usar 0.0.
BALANCE_TOLERANCE = 0.10

# Umbral a partir del cual se considera dominancia fuerte.
# Ejemplo: <= -0.50 domina clase 0; >= 0.50 domina clase 1.
DOMINANCE_STRONG_THRESHOLD = 0.50


# ============================================================
# HELPERS
# ============================================================

def ensure_dirs() -> None:
    OUT_GPKG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_TABLE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FIG_DIR.mkdir(parents=True, exist_ok=True)


def list_gpkg_layers(gpkg: Path) -> list[str]:
    """
    Lista capas de un GeoPackage si fiona o pyogrio están disponibles.
    Si no se pueden listar, devuelve lista vacía y se deja que geopandas
    levante el error al intentar leer.
    """
    try:
        import fiona
        return list(fiona.listlayers(str(gpkg)))
    except Exception:
        pass

    try:
        import pyogrio
        layers = pyogrio.list_layers(gpkg)
        return list(layers["name"])
    except Exception:
        return []


def sql_identifier(name: str) -> str:
    """Quote an SQLite identifier safely."""
    return '"' + str(name).replace('"', '""') + '"'


def read_homologation_table(gpkg: Path) -> pd.DataFrame:
    """
    Lee la tabla de homologación A2.1 que traduce id_0 de origen a
    id_0_propuesta. Se usa SQLite porque la tabla no es espacial.
    """
    layers = list_gpkg_layers(gpkg)

    if layers and HOMOLOGATION_TABLE not in layers:
        raise ValueError(
            f"No existe la tabla '{HOMOLOGATION_TABLE}' en {gpkg}. "
            f"Capas/tablas disponibles: {layers}"
        )

    query = (
        "SELECT "
        f"{sql_identifier(HOMOLOGATION_SOURCE_FIELD)}, "
        f"{sql_identifier(HOMOLOGATION_TARGET_FIELD)} "
        f"FROM {sql_identifier(HOMOLOGATION_TABLE)}"
    )

    with sqlite3.connect(gpkg) as conn:
        table = pd.read_sql_query(query, conn)

    if table.empty:
        raise ValueError(f"La tabla {HOMOLOGATION_TABLE} está vacía.")

    required = [HOMOLOGATION_SOURCE_FIELD, HOMOLOGATION_TARGET_FIELD]
    missing = [field for field in required if field not in table.columns]

    if missing:
        raise ValueError(
            f"La tabla {HOMOLOGATION_TABLE} no contiene campos requeridos: "
            f"{missing}"
        )

    table = table[required].copy()

    for field in required:
        table[field] = pd.to_numeric(table[field], errors="coerce").astype("Int64")

    if table[required].isna().any().any():
        raise ValueError(
            f"La tabla {HOMOLOGATION_TABLE} contiene valores nulos o no "
            "numéricos en la homologación."
        )

    duplicated = table[HOMOLOGATION_SOURCE_FIELD].duplicated(keep=False)
    if duplicated.any():
        repeated = (
            table.loc[duplicated, HOMOLOGATION_SOURCE_FIELD]
            .dropna()
            .astype(int)
            .drop_duplicates()
            .sort_values()
            .tolist()
        )
        raise ValueError(
            "La homologación no es 1:1 desde id_0 de origen. "
            f"id_0 repetidos: {repeated}"
        )

    return table


def attach_proposed_level0_class(
    points: gpd.GeoDataFrame,
    gpkg: Path,
) -> gpd.GeoDataFrame:
    """
    Añade id_0_propuesta a los puntos mediante:

    xy_point.id_0 -> homologacion_nivel_0_origen_propuesta.id_0
    -> homologacion_nivel_0_origen_propuesta.id_0_propuesta.

    Esta derivación es intencional: A2.1 no almacena id_0_propuesta en xy_point
    para evitar redundancia.
    """
    if SOURCE_CLASS_FIELD not in points.columns:
        raise ValueError(
            f"No existe {SOURCE_CLASS_FIELD} en xy_point. "
            "No se puede derivar la clase propuesta de nivel 0."
        )

    homologation = read_homologation_table(gpkg)

    out = points.copy()
    out[SOURCE_CLASS_FIELD] = pd.to_numeric(
        out[SOURCE_CLASS_FIELD],
        errors="coerce",
    ).astype("Int64")

    out = out.merge(
        homologation,
        left_on=SOURCE_CLASS_FIELD,
        right_on=HOMOLOGATION_SOURCE_FIELD,
        how="left",
        suffixes=("", "_homologacion"),
    )

    if f"{HOMOLOGATION_SOURCE_FIELD}_homologacion" in out.columns:
        out = out.drop(columns=f"{HOMOLOGATION_SOURCE_FIELD}_homologacion")

    n_source_na = int(out[SOURCE_CLASS_FIELD].isna().sum())
    n_target_na = int(out[CLASS_FIELD].isna().sum())
    observed_unmapped = (
        out.loc[
            out[SOURCE_CLASS_FIELD].notna() & out[CLASS_FIELD].isna(),
            SOURCE_CLASS_FIELD,
        ]
        .dropna()
        .astype(int)
        .drop_duplicates()
        .sort_values()
        .tolist()
    )

    print("Homologación de clase propuesta:")
    print(f"  Tabla: {HOMOLOGATION_TABLE}")
    print(f"  Campo origen: {SOURCE_CLASS_FIELD}")
    print(f"  Campo derivado: {CLASS_FIELD}")
    print(f"  Puntos sin {SOURCE_CLASS_FIELD}: {n_source_na:,}")
    print(f"  Puntos sin {CLASS_FIELD}: {n_target_na:,}")

    if observed_unmapped:
        print(
            "ADVERTENCIA: existen id_0 observados sin homologación: "
            f"{observed_unmapped}. Se tratarán como nulos para el balance."
        )

    return out


def read_points(points_path: Path, layer: str) -> gpd.GeoDataFrame:
    if not points_path.exists():
        raise FileNotFoundError(f"No existe el GeoPackage de puntos: {points_path}")

    layers = list_gpkg_layers(points_path)

    if layers and layer not in layers:
        raise ValueError(
            f"No existe la capa '{layer}' en {points_path}. "
            f"Capas disponibles: {layers}"
        )

    print(f"Leyendo puntos: {points_path}")
    print(f"Leyendo layer: {layer}")

    points = gpd.read_file(points_path, layer=layer)

    if points.empty:
        raise ValueError("La capa de puntos está vacía.")

    if points.crs is None:
        raise ValueError(
            "La capa de puntos no tiene CRS definido. "
            "Según el flujo esperado debería venir en EPSG:4326."
        )

    print(f"CRS original de puntos: {points.crs}")

    points = points[points.geometry.notna()].copy()
    points = points[~points.geometry.is_empty].copy()

    if points.empty:
        raise ValueError(
            "La capa de puntos quedó vacía después de filtrar geometrías nulas."
        )

    return points


def validate_input_crs(points: gpd.GeoDataFrame) -> None:
    input_crs = points.crs

    if input_crs is None:
        raise ValueError("La capa de entrada no tiene CRS.")

    if input_crs.to_string() != INPUT_CRS_EXPECTED:
        print(
            f"ADVERTENCIA: el CRS de entrada es {input_crs}, "
            f"pero se esperaba {INPUT_CRS_EXPECTED}."
        )
        print("Se continuará usando el CRS declarado en la capa.")


def validate_class_field(
    points: gpd.GeoDataFrame,
    class_field: str,
) -> gpd.GeoDataFrame:
    """
    Valida y normaliza el campo binario de clase.

    Crea una columna temporal _class_bin:
    - 0.0 para clase 0,
    - 1.0 para clase 1,
    - otros valores numéricos se conservan para advertencia,
    - valores no convertibles quedan como NaN.
    """
    if class_field not in points.columns:
        columns_preview = ", ".join(points.columns[:60])
        raise ValueError(
            f"No existe el campo requerido '{class_field}' en la capa de entrada. "
            f"Primeras columnas disponibles: {columns_preview}"
        )

    out = points.copy()

    original = out[class_field]
    class_num = pd.to_numeric(original, errors="coerce")

    non_null_original = original.notna()
    non_numeric_mask = non_null_original & class_num.isna()

    if int(non_numeric_mask.sum()) > 0:
        print(
            "ADVERTENCIA: existen valores no numéricos en "
            f"{class_field}: {int(non_numeric_mask.sum()):,}. "
            "Se tratarán como nulos para el cálculo de balance."
        )

    observed_values = sorted(class_num.dropna().unique().tolist())
    unexpected_values = [
        value
        for value in observed_values
        if value not in EXPECTED_CLASS_VALUES
    ]

    if unexpected_values:
        print(
            "ADVERTENCIA: se encontraron valores fuera de {0, 1} en "
            f"{class_field}: {unexpected_values}. "
            "No se usarán en la fórmula de dominancia, pero se contarán "
            "en n_other."
        )

    n_class_0 = int((class_num == CLASS_0_VALUE).sum())
    n_class_1 = int((class_num == CLASS_1_VALUE).sum())
    n_expected = n_class_0 + n_class_1

    if n_expected == 0:
        raise ValueError(
            f"El campo {class_field} no contiene valores válidos 0/1. "
            "No es posible calcular el balance binario."
        )

    print("Validación del campo binario:")
    print(f"  Campo: {class_field}")
    print(f"  Clase 0: {n_class_0:,}")
    print(f"  Clase 1: {n_class_1:,}")
    print(f"  Valores observados no nulos: {observed_values}")

    out["_class_bin"] = class_num

    return out


def reproject_to_work_crs(points: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    print(f"Reproyectando puntos a CRS de trabajo: {WORK_CRS}")

    points_m = points.to_crs(WORK_CRS)

    if points_m.crs is None:
        raise ValueError("La capa reproyectada quedó sin CRS.")

    if points_m.crs.is_geographic:
        raise ValueError(
            f"ERROR: WORK_CRS={WORK_CRS} es geográfico. "
            "Para un grid de 20 km se necesita un CRS proyectado en metros."
        )

    print(f"CRS de trabajo confirmado: {points_m.crs}")

    return points_m


def make_grid_from_bounds(bounds, cell_size_m: int, crs):
    """
    Crea una malla rectangular ajustada a los límites dados.
    Los límites deben estar en un CRS métrico.
    """
    minx, miny, maxx, maxy = bounds

    if EXTENT_BUFFER_M > 0:
        minx -= EXTENT_BUFFER_M
        miny -= EXTENT_BUFFER_M
        maxx += EXTENT_BUFFER_M
        maxy += EXTENT_BUFFER_M

    minx_grid = np.floor(minx / cell_size_m) * cell_size_m
    miny_grid = np.floor(miny / cell_size_m) * cell_size_m
    maxx_grid = np.ceil(maxx / cell_size_m) * cell_size_m
    maxy_grid = np.ceil(maxy / cell_size_m) * cell_size_m

    xs = np.arange(minx_grid, maxx_grid, cell_size_m)
    ys = np.arange(miny_grid, maxy_grid, cell_size_m)

    records = []
    grid_id = 1

    for ix, x in enumerate(xs):
        for iy, y in enumerate(ys):
            records.append(
                {
                    "grid_id": grid_id,
                    "ix": ix,
                    "iy": iy,
                    "geometry": box(
                        x,
                        y,
                        x + cell_size_m,
                        y + cell_size_m,
                    ),
                }
            )
            grid_id += 1

    grid = gpd.GeoDataFrame(records, geometry="geometry", crs=crs)

    return grid, minx_grid, miny_grid, len(xs), len(ys)


def assign_points_to_grid_balance(
    points_m: gpd.GeoDataFrame,
    minx: float,
    miny: float,
    nx: int,
    ny: int,
    cell_size_m: int,
) -> pd.DataFrame:
    """
    Asigna cada punto a una celda usando coordenadas y resume clases 0/1.

    Este método evita un spatial join y mantiene el mismo enfoque eficiente
    del script de densidad para más de un millón de puntos.
    """
    geom_types = set(points_m.geometry.geom_type.unique())

    if not geom_types.issubset({"Point"}):
        raise ValueError(
            f"La capa contiene geometrías que no son Point: {geom_types}. "
            "Este script espera una capa puntual."
        )

    x = points_m.geometry.x.to_numpy()
    y = points_m.geometry.y.to_numpy()

    ix = np.floor((x - minx) / cell_size_m).astype(int)
    iy = np.floor((y - miny) / cell_size_m).astype(int)

    # Control para puntos exactamente sobre el borde máximo.
    ix = np.clip(ix, 0, nx - 1)
    iy = np.clip(iy, 0, ny - 1)

    class_values = points_m["_class_bin"]

    tmp = pd.DataFrame(
        {
            "ix": ix,
            "iy": iy,
            "_class_bin": class_values.to_numpy(),
        }
    )

    tmp["is_c0"] = (tmp["_class_bin"] == CLASS_0_VALUE).astype(int)
    tmp["is_c1"] = (tmp["_class_bin"] == CLASS_1_VALUE).astype(int)
    tmp["is_na"] = tmp["_class_bin"].isna().astype(int)
    tmp["is_other"] = (
        tmp["_class_bin"].notna()
        & ~tmp["_class_bin"].isin([CLASS_0_VALUE, CLASS_1_VALUE])
    ).astype(int)

    counts = (
        tmp
        .groupby(["ix", "iy"])
        .agg(
            n_points=("_class_bin", "size"),
            n_c0=("is_c0", "sum"),
            n_c1=("is_c1", "sum"),
            n_other=("is_other", "sum"),
            n_na=("is_na", "sum"),
        )
        .reset_index()
    )

    return counts


def add_balance_metrics(grid_balance: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Calcula métricas de balance binario para cada celda.

    dominancia_01 = (n_c1 - n_c0) / (n_c1 + n_c0)

    Interpretación:
    - -1 = domina completamente clase 0.
    -  0 = equilibrio entre clase 0 y clase 1.
    -  1 = domina completamente clase 1.
    """
    grid = grid_balance.copy()

    if grid.crs is None:
        raise ValueError("El grid no tiene CRS.")

    if grid.crs.is_geographic:
        raise ValueError(
            "El grid está en CRS geográfico antes de calcular área. "
            "Esto no debería pasar."
        )

    grid["area_km2"] = grid.geometry.area / 1_000_000
    grid["points_km2"] = grid["n_points"] / grid["area_km2"]

    grid["n_bin"] = grid["n_c0"] + grid["n_c1"]

    # Porcentajes sobre registros binarios válidos.
    grid["pct_c0"] = np.nan
    grid["pct_c1"] = np.nan

    mask_bin = grid["n_bin"] > 0

    grid.loc[mask_bin, "pct_c0"] = (
        grid.loc[mask_bin, "n_c0"]
        / grid.loc[mask_bin, "n_bin"]
        * 100
    )

    grid.loc[mask_bin, "pct_c1"] = (
        grid.loc[mask_bin, "n_c1"]
        / grid.loc[mask_bin, "n_bin"]
        * 100
    )

    # Porcentajes sobre el total de puntos de la celda.
    # Estos sirven para auditar si hay valores nulos u otros.
    grid["pct_c0_total"] = np.nan
    grid["pct_c1_total"] = np.nan

    mask_points = grid["n_points"] > 0

    grid.loc[mask_points, "pct_c0_total"] = (
        grid.loc[mask_points, "n_c0"]
        / grid.loc[mask_points, "n_points"]
        * 100
    )

    grid.loc[mask_points, "pct_c1_total"] = (
        grid.loc[mask_points, "n_c1"]
        / grid.loc[mask_points, "n_points"]
        * 100
    )

    grid["dif_abs"] = (grid["n_c1"] - grid["n_c0"]).abs()
    grid["dif_signed"] = grid["n_c1"] - grid["n_c0"]

    grid["dominancia_01"] = np.nan

    grid.loc[mask_bin, "dominancia_01"] = (
        (
            grid.loc[mask_bin, "n_c1"]
            - grid.loc[mask_bin, "n_c0"]
        )
        / grid.loc[mask_bin, "n_bin"]
    )

    grid["clase_dominante"] = "sin puntos"
    grid.loc[(grid["n_points"] > 0) & (grid["n_bin"] == 0), "clase_dominante"] = "sin clase 0/1"
    grid.loc[(grid["n_bin"] > 0) & (grid["n_c0"] > grid["n_c1"]), "clase_dominante"] = "0"
    grid.loc[(grid["n_bin"] > 0) & (grid["n_c1"] > grid["n_c0"]), "clase_dominante"] = "1"
    grid.loc[(grid["n_bin"] > 0) & (grid["n_c0"] == grid["n_c1"]), "clase_dominante"] = "equilibrio"

    grid["categoria_dom"] = grid.apply(classify_dominance_category, axis=1)

    grid["grid_size_m"] = GRID_SIZE_M
    grid["grid_size_km"] = GRID_SIZE_M / 1000

    # Redondeos prácticos para salida SIG.
    round_cols = [
        "area_km2",
        "points_km2",
        "pct_c0",
        "pct_c1",
        "pct_c0_total",
        "pct_c1_total",
        "dominancia_01",
    ]

    for col in round_cols:
        grid[col] = grid[col].round(6)

    return grid


def classify_dominance_category(row: pd.Series) -> str:
    """
    Etiqueta interpretativa para QGIS.
    """
    if row["n_points"] == 0:
        return "sin puntos"

    if row["n_bin"] == 0:
        return "sin clase 0/1"

    value = row["dominancia_01"]

    if pd.isna(value):
        return "sin clase 0/1"

    if abs(value) <= BALANCE_TOLERANCE:
        return "equilibrio"

    if value <= -DOMINANCE_STRONG_THRESHOLD:
        return "domina clase 0"

    if value < -BALANCE_TOLERANCE:
        return "leve predominio clase 0"

    if value >= DOMINANCE_STRONG_THRESHOLD:
        return "domina clase 1"

    if value > BALANCE_TOLERANCE:
        return "leve predominio clase 1"

    return "equilibrio"


def make_balance_summary(grid_balance: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Resume la distribución por categoría de dominancia.
    Incluye celdas sin puntos para documentar cobertura del grid.
    """
    resumen = (
        grid_balance
        .groupby("categoria_dom", dropna=False)
        .agg(
            n_celdas=("grid_id", "count"),
            area_km2=("area_km2", "sum"),
            puntos_total=("n_points", "sum"),
            puntos_binarios=("n_bin", "sum"),
            puntos_clase_0=("n_c0", "sum"),
            puntos_clase_1=("n_c1", "sum"),
            puntos_otros=("n_other", "sum"),
            puntos_nulos=("n_na", "sum"),
            min_dominancia=("dominancia_01", "min"),
            max_dominancia=("dominancia_01", "max"),
            promedio_dominancia=("dominancia_01", "mean"),
            mediana_dominancia=("dominancia_01", "median"),
            promedio_puntos=("n_points", "mean"),
            mediana_puntos=("n_points", "median"),
            promedio_puntos_km2=("points_km2", "mean"),
            mediana_puntos_km2=("points_km2", "median"),
        )
        .reset_index()
    )

    orden = {
        "sin puntos": 0,
        "sin clase 0/1": 1,
        "domina clase 0": 2,
        "leve predominio clase 0": 3,
        "equilibrio": 4,
        "leve predominio clase 1": 5,
        "domina clase 1": 6,
    }

    resumen["orden"] = resumen["categoria_dom"].map(orden).fillna(99)

    resumen["porcentaje_celdas_total"] = (
        resumen["n_celdas"] / resumen["n_celdas"].sum() * 100
    )

    resumen["porcentaje_area_total"] = (
        resumen["area_km2"] / resumen["area_km2"].sum() * 100
    )

    resumen = (
        resumen
        .sort_values("orden")
        .drop(columns="orden")
        .reset_index(drop=True)
    )

    round_cols = [
        "area_km2",
        "min_dominancia",
        "max_dominancia",
        "promedio_dominancia",
        "mediana_dominancia",
        "promedio_puntos",
        "mediana_puntos",
        "promedio_puntos_km2",
        "mediana_puntos_km2",
        "porcentaje_celdas_total",
        "porcentaje_area_total",
    ]

    for col in round_cols:
        resumen[col] = resumen[col].round(4)

    return resumen


def make_global_summary(grid_balance: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Crea una tabla global de auditoría del balance binario.
    """
    n_points = int(grid_balance["n_points"].sum())
    n_c0 = int(grid_balance["n_c0"].sum())
    n_c1 = int(grid_balance["n_c1"].sum())
    n_bin = n_c0 + n_c1
    n_other = int(grid_balance["n_other"].sum())
    n_na = int(grid_balance["n_na"].sum())

    if n_bin > 0:
        dominancia_global = (n_c1 - n_c0) / n_bin
        pct_c0 = n_c0 / n_bin * 100
        pct_c1 = n_c1 / n_bin * 100
    else:
        dominancia_global = np.nan
        pct_c0 = np.nan
        pct_c1 = np.nan

    rows = [
        {
            "metrica": "n_points_total",
            "valor": n_points,
            "descripcion": "Total de puntos asignados al grid.",
        },
        {
            "metrica": "n_clase_0",
            "valor": n_c0,
            "descripcion": "Total de puntos con id_0_propuesta = 0.",
        },
        {
            "metrica": "n_clase_1",
            "valor": n_c1,
            "descripcion": "Total de puntos con id_0_propuesta = 1.",
        },
        {
            "metrica": "n_binarios_validos",
            "valor": n_bin,
            "descripcion": "Total de puntos válidos para la fórmula de dominancia.",
        },
        {
            "metrica": "n_otros",
            "valor": n_other,
            "descripcion": "Total de puntos con valores numéricos distintos de 0 y 1.",
        },
        {
            "metrica": "n_nulos_o_no_numericos",
            "valor": n_na,
            "descripcion": "Total de puntos con valores nulos o no convertibles a número.",
        },
        {
            "metrica": "pct_clase_0_sobre_binarios",
            "valor": round(pct_c0, 6) if pd.notna(pct_c0) else np.nan,
            "descripcion": "Porcentaje de clase 0 usando solo registros binarios válidos.",
        },
        {
            "metrica": "pct_clase_1_sobre_binarios",
            "valor": round(pct_c1, 6) if pd.notna(pct_c1) else np.nan,
            "descripcion": "Porcentaje de clase 1 usando solo registros binarios válidos.",
        },
        {
            "metrica": "dominancia_01_global",
            "valor": round(dominancia_global, 6) if pd.notna(dominancia_global) else np.nan,
            "descripcion": "(n_clase_1 - n_clase_0) / (n_clase_1 + n_clase_0).",
        },
        {
            "metrica": "n_celdas_total",
            "valor": int(len(grid_balance)),
            "descripcion": "Total de celdas generadas.",
        },
        {
            "metrica": "n_celdas_con_puntos",
            "valor": int((grid_balance["n_points"] > 0).sum()),
            "descripcion": "Celdas con al menos un punto.",
        },
        {
            "metrica": "n_celdas_sin_puntos",
            "valor": int((grid_balance["n_points"] == 0).sum()),
            "descripcion": "Celdas sin puntos.",
        },
    ]

    return pd.DataFrame(rows)


def export_outputs(grid_balance: gpd.GeoDataFrame) -> None:
    """
    Exporta el GeoPackage.
    El cálculo ya fue hecho en WORK_CRS.
    Si EXPORT_TO_OUTPUT_CRS=True, solo cambia la geometría de salida a EPSG:4326.
    Los campos area_km2, points_km2 y dominancia_01 conservan los valores
    calculados en CRS métrico.
    """
    if EXPORT_TO_OUTPUT_CRS:
        print(f"Exportando geometrías finales en {OUTPUT_CRS}...")
        grid_out = grid_balance.to_crs(OUTPUT_CRS)
    else:
        print(f"Exportando geometrías finales en CRS de trabajo {WORK_CRS}...")
        grid_out = grid_balance.copy()

    print(f"Exportando GPKG: {OUT_GPKG}")

    if OUT_GPKG.exists():
        OUT_GPKG.unlink()

    grid_out.to_file(
        OUT_GPKG,
        layer="grid_balance_nivel_0_origen_propuesta",
        driver="GPKG",
    )


def export_figure(grid_balance: gpd.GeoDataFrame) -> None:
    """
    Exporta figura rápida por índice de dominancia.
    """
    if EXPORT_TO_OUTPUT_CRS:
        grid_plot = grid_balance.to_crs(OUTPUT_CRS)
    else:
        grid_plot = grid_balance.copy()

    print(f"Exportando figura: {OUT_FIG}")

    fig, ax = plt.subplots(figsize=(12, 9))

    grid_plot.plot(
        column="dominancia_01",
        ax=ax,
        legend=True,
        linewidth=0.05,
        edgecolor="black",
        missing_kwds={
            "color": "lightgrey",
            "label": "sin puntos / sin valor",
        },
    )

    ax.set_title(
        f"Balance id_0_propuesta por celda "
        f"({GRID_SIZE_M / 1000:.0f} x {GRID_SIZE_M / 1000:.0f} km)"
    )

    ax.set_axis_off()

    plt.tight_layout()
    plt.savefig(OUT_FIG, dpi=300)
    plt.close()


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    ensure_dirs()

    print("============================================================")
    print("A2.3 - Grid de balance id_0_propuesta")
    print("============================================================")
    print(f"Proyecto: {PROJECT_ROOT}")
    print(f"Entrada:  {POINTS_GPKG}")
    print(f"Layer:    {POINTS_LAYER}")
    print(f"Campo origen:   {SOURCE_CLASS_FIELD}")
    print(f"Campo balance:  {CLASS_FIELD}")
    print(f"Homologación:   {HOMOLOGATION_TABLE}")
    print(f"Grid:     {GRID_SIZE_M / 1000:.0f} x {GRID_SIZE_M / 1000:.0f} km")
    print(f"CRS trabajo: {WORK_CRS}")
    print(f"CRS salida:  {OUTPUT_CRS if EXPORT_TO_OUTPUT_CRS else WORK_CRS}")
    print(
        "Dominancia: (n_clase_1 - n_clase_0) / "
        "(n_clase_1 + n_clase_0)"
    )
    print("============================================================\n")

    # --------------------------------------------------------
    # 1. Leer puntos
    # --------------------------------------------------------

    points = read_points(POINTS_GPKG, POINTS_LAYER)
    validate_input_crs(points)

    print(f"Total de puntos leídos: {len(points):,}")

    # --------------------------------------------------------
    # 2. Derivar y validar campo binario propuesto
    # --------------------------------------------------------

    points = attach_proposed_level0_class(points, POINTS_GPKG)
    points = validate_class_field(points, CLASS_FIELD)

    # --------------------------------------------------------
    # 3. Reproyectar a CRS métrico/equal-area
    # --------------------------------------------------------

    points_m = reproject_to_work_crs(points)

    # --------------------------------------------------------
    # 4. Crear grid sobre extensión de puntos
    # --------------------------------------------------------

    bounds = points_m.total_bounds

    print(
        f"Creando grid de {GRID_SIZE_M / 1000:.0f} x "
        f"{GRID_SIZE_M / 1000:.0f} km ajustado a la extensión de puntos..."
    )

    grid, grid_minx, grid_miny, nx, ny = make_grid_from_bounds(
        bounds=bounds,
        cell_size_m=GRID_SIZE_M,
        crs=WORK_CRS,
    )

    print(f"Celdas creadas: {len(grid):,}")
    print(f"Columnas del grid: {nx:,}")
    print(f"Filas del grid:    {ny:,}")

    if len(grid) <= 1:
        raise ValueError(
            "El grid tiene 1 celda o menos. "
            "Esto normalmente indica que el cálculo se hizo en grados "
            "en vez de metros. Revisa WORK_CRS."
        )

    # --------------------------------------------------------
    # 5. Asignar puntos a celdas y contar clases
    # --------------------------------------------------------

    print("Asignando puntos a celdas y calculando conteos por clase...")

    counts = assign_points_to_grid_balance(
        points_m=points_m,
        minx=grid_minx,
        miny=grid_miny,
        nx=nx,
        ny=ny,
        cell_size_m=GRID_SIZE_M,
    )

    print(f"Celdas con al menos un punto: {len(counts):,}")

    # --------------------------------------------------------
    # 6. Unir conteos al grid y conservar celdas sin puntos
    # --------------------------------------------------------

    grid_balance = grid.merge(
        counts,
        on=["ix", "iy"],
        how="left",
    )

    count_cols = [
        "n_points",
        "n_c0",
        "n_c1",
        "n_other",
        "n_na",
    ]

    for col in count_cols:
        grid_balance[col] = (
            grid_balance[col]
            .fillna(0)
            .astype(int)
        )

    # --------------------------------------------------------
    # 7. Calcular métricas de balance
    # --------------------------------------------------------

    print("Calculando métricas de balance y dominancia...")

    grid_balance = add_balance_metrics(grid_balance)

    # --------------------------------------------------------
    # 8. Exportar tablas resumen
    # --------------------------------------------------------

    resumen_balance = make_balance_summary(grid_balance)
    resumen_global = make_global_summary(grid_balance)

    print(f"Exportando resumen por categoría: {OUT_SUMMARY_CSV}")
    resumen_balance.to_csv(
        OUT_SUMMARY_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    print(f"Exportando resumen global: {OUT_GLOBAL_CSV}")
    resumen_global.to_csv(
        OUT_GLOBAL_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    # --------------------------------------------------------
    # 9. Exportar GeoPackage
    # --------------------------------------------------------

    export_outputs(grid_balance)

    # --------------------------------------------------------
    # 10. Exportar figura
    # --------------------------------------------------------

    export_figure(grid_balance)

    # --------------------------------------------------------
    # 11. Mensajes finales
    # --------------------------------------------------------

    n_total_celdas = len(grid_balance)
    n_celdas_con_puntos = int((grid_balance["n_points"] > 0).sum())
    n_celdas_sin_puntos = int((grid_balance["n_points"] == 0).sum())

    n_total_puntos = int(grid_balance["n_points"].sum())
    n_c0 = int(grid_balance["n_c0"].sum())
    n_c1 = int(grid_balance["n_c1"].sum())
    n_other = int(grid_balance["n_other"].sum())
    n_na = int(grid_balance["n_na"].sum())

    print("\n============================================================")
    print("Proceso finalizado.")
    print("============================================================")
    print(f"Total de puntos: {n_total_puntos:,}")
    print(f"Total clase 0:   {n_c0:,}")
    print(f"Total clase 1:   {n_c1:,}")
    print(f"Otros valores:   {n_other:,}")
    print(f"Nulos/no num.:   {n_na:,}")
    print(f"Total de celdas: {n_total_celdas:,}")
    print(f"Celdas con puntos: {n_celdas_con_puntos:,}")
    print(f"Celdas sin puntos: {n_celdas_sin_puntos:,}")
    print("")
    print("Salidas:")
    print(f"  GPKG: {OUT_GPKG}")
    print("    - layer: grid_balance_nivel_0_origen_propuesta")
    print(f"  CSV resumen por categoría: {OUT_SUMMARY_CSV}")
    print(f"  CSV resumen global:        {OUT_GLOBAL_CSV}")
    print(f"  PNG:                       {OUT_FIG}")
    print("============================================================")


if __name__ == "__main__":
    main()
