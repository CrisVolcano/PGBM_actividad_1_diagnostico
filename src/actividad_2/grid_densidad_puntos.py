# ============================================================
# A2.2 - Grid de densidad de puntos normalizados
# ============================================================
# Objetivo:
# Crear una malla regular de 20 km x 20 km ajustada a la
# extensión actual de la capa de puntos normalizados y calcular
# la cantidad/densidad de puntos por celda.
#
# Flujo:
# 1. Leer puntos en EPSG:4326.
# 2. Reproyectar temporalmente a CRS métrico/equal-area.
# 3. Crear grid de 20 km en metros.
# 4. Contar puntos por celda.
# 5. Calcular área y densidad.
# 6. Conservar celdas sin puntos, pero excluirlas de percentiles.
# 7. Calcular percentiles 0,10,20,...,100 sobre celdas con puntos.
# 8. Clasificar celdas con puntos en rangos percentiles.
# 9. Exportar resultados en EPSG:4326 para QGIS.
#
# Entrada:
# data/processed/a2_1_modelo_datos/gpkg/a2_1_xy_point.gpkg
# layer: xy_point
#
# Salidas:
# data/processed/a2_2_grid_densidad_puntos/gpkg/grid_densidad_puntos.gpkg
# data/processed/a2_2_grid_densidad_puntos/tables/resumen_densidad_grid.csv
# data/processed/a2_2_grid_densidad_puntos/tables/percentiles_densidad_grid_sin_ceros.csv
# data/processed/a2_2_grid_densidad_puntos/tables/resumen_deciles_densidad_grid_sin_ceros.csv
# data/processed/a2_2_grid_densidad_puntos/figures/grid_densidad_puntos.png
# ============================================================

from pathlib import Path

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

OUT_DIR = PROJECT_ROOT / "data" / "processed" / "a2_2_grid_densidad_puntos"
OUT_GPKG_DIR = OUT_DIR / "gpkg"
OUT_TABLE_DIR = OUT_DIR / "tables"
OUT_FIG_DIR = OUT_DIR / "figures"

OUT_GPKG = OUT_GPKG_DIR / "grid_densidad_puntos.gpkg"
OUT_CSV = OUT_TABLE_DIR / "resumen_densidad_grid.csv"
OUT_PERCENTILES_CSV = OUT_TABLE_DIR / "percentiles_densidad_grid_sin_ceros.csv"
OUT_DECILES_CSV = OUT_TABLE_DIR / "resumen_deciles_densidad_grid_sin_ceros.csv"
OUT_FIG = OUT_FIG_DIR / "grid_densidad_puntos.png"

# Entrada esperada
INPUT_CRS_EXPECTED = "EPSG:4326"

# CRS de trabajo en metros.
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

# Campo usado para los percentiles.
# Para este diagnóstico recomiendo n_points.
PERCENTILE_VALUE_COL = "n_points"

# Percentiles a exportar.
PERCENTILE_STEPS = list(range(0, 101, 10))


# ============================================================
# HELPERS
# ============================================================

def ensure_dirs():
    OUT_GPKG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_TABLE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FIG_DIR.mkdir(parents=True, exist_ok=True)


def read_points(points_path: Path, layer: str) -> gpd.GeoDataFrame:
    if not points_path.exists():
        raise FileNotFoundError(f"No existe la capa de puntos: {points_path}")

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


def validate_input_crs(points: gpd.GeoDataFrame):
    input_crs = points.crs

    if input_crs is None:
        raise ValueError("La capa de entrada no tiene CRS.")

    if input_crs.to_string() != INPUT_CRS_EXPECTED:
        print(
            f"ADVERTENCIA: el CRS de entrada es {input_crs}, "
            f"pero se esperaba {INPUT_CRS_EXPECTED}."
        )
        print("Se continuará usando el CRS declarado en la capa.")


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


def make_grid_from_bounds(bounds, cell_size_m, crs):
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


def assign_points_to_grid(points_m, minx, miny, nx, ny, cell_size_m):
    """
    Asigna cada punto a una celda usando coordenadas.
    Es más rápido que hacer spatial join para más de un millón de puntos.
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

    tmp = pd.DataFrame(
        {
            "ix": ix,
            "iy": iy,
        }
    )

    counts = (
        tmp
        .groupby(["ix", "iy"])
        .size()
        .reset_index(name="n_points")
    )

    return counts


def add_percentile_distribution(
    grid_density: gpd.GeoDataFrame,
    value_col: str = "n_points",
) -> gpd.GeoDataFrame:
    """
    Añade percentil y rango percentil usando solamente celdas con puntos.

    Las celdas con n_points = 0:
    - se conservan en el GPKG,
    - no participan en percentiles,
    - quedan etiquetadas como 'sin puntos'.
    """

    grid = grid_density.copy()

    grid["percentil_rank"] = np.nan
    grid["decil"] = np.nan
    grid["rango_percentil"] = "sin puntos"

    mask = grid[value_col] > 0

    if mask.sum() == 0:
        return grid

    # Percentil relativo entre celdas con puntos.
    # El método average evita saltos extremos cuando hay muchos empates.
    pct_rank = (
        grid.loc[mask, value_col]
        .rank(method="average", pct=True)
        * 100
    )

    grid.loc[mask, "percentil_rank"] = pct_rank

    bins = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

    labels = [
        "P00-P10",
        "P10-P20",
        "P20-P30",
        "P30-P40",
        "P40-P50",
        "P50-P60",
        "P60-P70",
        "P70-P80",
        "P80-P90",
        "P90-P100",
    ]

    cut_values = pd.cut(
        grid.loc[mask, "percentil_rank"],
        bins=bins,
        labels=labels,
        include_lowest=True,
        right=True,
    )

    grid.loc[mask, "rango_percentil"] = cut_values.astype(str)

    decile_map = {
        "P00-P10": 1,
        "P10-P20": 2,
        "P20-P30": 3,
        "P30-P40": 4,
        "P40-P50": 5,
        "P50-P60": 6,
        "P60-P70": 7,
        "P70-P80": 8,
        "P80-P90": 9,
        "P90-P100": 10,
    }

    grid.loc[mask, "decil"] = (
        grid.loc[mask, "rango_percentil"]
        .map(decile_map)
        .astype(float)
    )

    return grid


def make_percentile_table(
    grid_density: gpd.GeoDataFrame,
    value_col: str = "n_points",
) -> pd.DataFrame:
    """
    Crea tabla de percentiles excluyendo celdas sin puntos.
    Percentiles: 0,10,20,...,100.
    """

    positive = grid_density[grid_density[value_col] > 0].copy()

    if positive.empty:
        return pd.DataFrame(
            columns=[
                "percentil",
                value_col,
            ]
        )

    rows = []

    for p in PERCENTILE_STEPS:
        rows.append(
            {
                "percentil": p,
                value_col: positive[value_col].quantile(p / 100),
            }
        )

    percentiles = pd.DataFrame(rows)

    percentiles[value_col] = percentiles[value_col].round(2)

    return percentiles


def make_general_summary(grid_density: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Resumen general incluyendo celdas sin puntos.
    Sirve para saber cuántas celdas quedaron vacías.
    """

    resumen = (
        grid_density
        .groupby("rango_percentil", dropna=False)
        .agg(
            n_celdas=("grid_id", "count"),
            area_km2=("area_km2", "sum"),
            puntos=("n_points", "sum"),
            min_puntos=("n_points", "min"),
            max_puntos=("n_points", "max"),
            promedio_puntos=("n_points", "mean"),
            mediana_puntos=("n_points", "median"),
            promedio_puntos_km2=("points_km2", "mean"),
            mediana_puntos_km2=("points_km2", "median"),
        )
        .reset_index()
    )

    orden = {
        "sin puntos": 0,
        "P00-P10": 1,
        "P10-P20": 2,
        "P20-P30": 3,
        "P30-P40": 4,
        "P40-P50": 5,
        "P50-P60": 6,
        "P60-P70": 7,
        "P70-P80": 8,
        "P80-P90": 9,
        "P90-P100": 10,
    }

    resumen["orden"] = resumen["rango_percentil"].map(orden)

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
    )

    round_cols = [
        "area_km2",
        "promedio_puntos",
        "mediana_puntos",
        "promedio_puntos_km2",
        "mediana_puntos_km2",
        "porcentaje_celdas_total",
        "porcentaje_area_total",
    ]

    for col in round_cols:
        resumen[col] = resumen[col].round(2)

    return resumen


def make_decile_summary_without_zeros(
    grid_density: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """
    Resume la distribución por rangos percentiles excluyendo celdas sin puntos.
    Esta es la tabla principal para interpretar la distribución real de densidad.
    """

    positive = grid_density[grid_density["n_points"] > 0].copy()

    if positive.empty:
        return pd.DataFrame()

    resumen_deciles = (
        positive
        .groupby("rango_percentil", dropna=False)
        .agg(
            n_celdas=("grid_id", "count"),
            area_km2=("area_km2", "sum"),
            puntos=("n_points", "sum"),
            min_puntos=("n_points", "min"),
            max_puntos=("n_points", "max"),
            promedio_puntos=("n_points", "mean"),
            mediana_puntos=("n_points", "median"),
            min_puntos_km2=("points_km2", "min"),
            max_puntos_km2=("points_km2", "max"),
            promedio_puntos_km2=("points_km2", "mean"),
            mediana_puntos_km2=("points_km2", "median"),
        )
        .reset_index()
    )

    orden = {
        "P00-P10": 1,
        "P10-P20": 2,
        "P20-P30": 3,
        "P30-P40": 4,
        "P40-P50": 5,
        "P50-P60": 6,
        "P60-P70": 7,
        "P70-P80": 8,
        "P80-P90": 9,
        "P90-P100": 10,
    }

    resumen_deciles["orden"] = resumen_deciles["rango_percentil"].map(orden)

    resumen_deciles["porcentaje_celdas_con_puntos"] = (
        resumen_deciles["n_celdas"]
        / resumen_deciles["n_celdas"].sum()
        * 100
    )

    resumen_deciles["porcentaje_area_con_puntos"] = (
        resumen_deciles["area_km2"]
        / resumen_deciles["area_km2"].sum()
        * 100
    )

    resumen_deciles = (
        resumen_deciles
        .sort_values("orden")
        .drop(columns="orden")
    )

    round_cols = [
        "area_km2",
        "promedio_puntos",
        "mediana_puntos",
        "min_puntos_km2",
        "max_puntos_km2",
        "promedio_puntos_km2",
        "mediana_puntos_km2",
        "porcentaje_celdas_con_puntos",
        "porcentaje_area_con_puntos",
    ]

    for col in round_cols:
        resumen_deciles[col] = resumen_deciles[col].round(2)

    return resumen_deciles


def export_outputs(grid_density: gpd.GeoDataFrame, low_density: gpd.GeoDataFrame):
    """
    Exporta GPKG.
    El cálculo ya fue hecho en WORK_CRS.
    Si EXPORT_TO_OUTPUT_CRS=True, solo cambia la geometría de salida a EPSG:4326.
    Los campos area_km2 y points_km2 conservan los valores correctos calculados en metros.
    """

    if EXPORT_TO_OUTPUT_CRS:
        print(f"Exportando geometrías finales en {OUTPUT_CRS}...")
        grid_out = grid_density.to_crs(OUTPUT_CRS)
        low_out = low_density.to_crs(OUTPUT_CRS)
    else:
        print(f"Exportando geometrías finales en CRS de trabajo {WORK_CRS}...")
        grid_out = grid_density.copy()
        low_out = low_density.copy()

    print(f"Exportando GPKG: {OUT_GPKG}")

    if OUT_GPKG.exists():
        OUT_GPKG.unlink()

    grid_out.to_file(
        OUT_GPKG,
        layer="grid_densidad_puntos",
        driver="GPKG",
    )

    low_out.to_file(
        OUT_GPKG,
        layer="grid_baja_densidad",
        driver="GPKG",
    )


def export_figure(grid_density: gpd.GeoDataFrame):
    """
    Exporta figura rápida por cantidad de puntos.
    """
    if EXPORT_TO_OUTPUT_CRS:
        grid_plot = grid_density.to_crs(OUTPUT_CRS)
    else:
        grid_plot = grid_density.copy()

    print(f"Exportando figura: {OUT_FIG}")

    fig, ax = plt.subplots(figsize=(12, 9))

    grid_plot.plot(
        column="n_points",
        ax=ax,
        legend=True,
        linewidth=0.05,
        edgecolor="black",
    )

    ax.set_title(
        f"Densidad de puntos normalizados por celda "
        f"({GRID_SIZE_M / 1000:.0f} x {GRID_SIZE_M / 1000:.0f} km)"
    )

    ax.set_axis_off()

    plt.tight_layout()
    plt.savefig(OUT_FIG, dpi=300)
    plt.close()


# ============================================================
# MAIN
# ============================================================

def main():
    ensure_dirs()

    print("============================================================")
    print("A2.2 - Grid de densidad de puntos normalizados")
    print("============================================================")
    print(f"Proyecto: {PROJECT_ROOT}")
    print(f"Entrada:  {POINTS_GPKG}")
    print(f"Layer:    {POINTS_LAYER}")
    print(f"Grid:     {GRID_SIZE_M / 1000:.0f} x {GRID_SIZE_M / 1000:.0f} km")
    print(f"CRS trabajo: {WORK_CRS}")
    print(f"CRS salida:  {OUTPUT_CRS if EXPORT_TO_OUTPUT_CRS else WORK_CRS}")
    print("Percentiles: excluyen celdas con n_points = 0")
    print("============================================================\n")

    # --------------------------------------------------------
    # 1. Leer puntos
    # --------------------------------------------------------

    points = read_points(POINTS_GPKG, POINTS_LAYER)
    validate_input_crs(points)

    print(f"Total de puntos leídos: {len(points):,}")

    # --------------------------------------------------------
    # 2. Reproyectar a CRS métrico
    # --------------------------------------------------------

    points_m = reproject_to_work_crs(points)

    # --------------------------------------------------------
    # 3. Crear grid sobre extensión de puntos
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
    # 4. Asignar puntos a celdas
    # --------------------------------------------------------

    print("Asignando puntos a celdas...")

    counts = assign_points_to_grid(
        points_m=points_m,
        minx=grid_minx,
        miny=grid_miny,
        nx=nx,
        ny=ny,
        cell_size_m=GRID_SIZE_M,
    )

    print(f"Celdas con al menos un punto: {len(counts):,}")

    # --------------------------------------------------------
    # 5. Unir conteos al grid
    # --------------------------------------------------------

    grid_density = grid.merge(
        counts,
        on=["ix", "iy"],
        how="left",
    )

    grid_density["n_points"] = (
        grid_density["n_points"]
        .fillna(0)
        .astype(int)
    )

    # --------------------------------------------------------
    # 6. Calcular área y densidad en CRS métrico
    # --------------------------------------------------------

    if grid_density.crs.is_geographic:
        raise ValueError(
            "El grid está en CRS geográfico antes de calcular área. "
            "Esto no debería pasar."
        )

    grid_density["area_km2"] = grid_density.geometry.area / 1_000_000
    grid_density["points_km2"] = (
        grid_density["n_points"] / grid_density["area_km2"]
    )

    grid_density["grid_size_m"] = GRID_SIZE_M
    grid_density["grid_size_km"] = GRID_SIZE_M / 1000

    # --------------------------------------------------------
    # 7. Percentiles y rangos percentiles sin ceros
    # --------------------------------------------------------

    print("Calculando percentiles excluyendo celdas sin puntos...")

    grid_density = add_percentile_distribution(
        grid_density,
        value_col=PERCENTILE_VALUE_COL,
    )

    percentiles_table = make_percentile_table(
        grid_density,
        value_col=PERCENTILE_VALUE_COL,
    )

    resumen_general = make_general_summary(grid_density)

    resumen_deciles = make_decile_summary_without_zeros(grid_density)

    print(f"Exportando resumen general: {OUT_CSV}")
    resumen_general.to_csv(
        OUT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    print(f"Exportando percentiles sin ceros: {OUT_PERCENTILES_CSV}")
    percentiles_table.to_csv(
        OUT_PERCENTILES_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    print(f"Exportando resumen por deciles sin ceros: {OUT_DECILES_CSV}")
    resumen_deciles.to_csv(
        OUT_DECILES_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    # --------------------------------------------------------
    # 8. Capa de baja densidad
    # --------------------------------------------------------
    # Ahora baja densidad se define de forma clara:
    # - sin puntos
    # - P00-P10
    # - P10-P20
    # Puedes ajustar esta lista si quieres ser más o menos estricto.
    # --------------------------------------------------------

    low_density_labels = [
        "sin puntos",
        "P00-P10",
        "P10-P20",
    ]

    low_density = grid_density[
        grid_density["rango_percentil"].isin(low_density_labels)
    ].copy()

    orden_low = {
        "sin puntos": 0,
        "P00-P10": 1,
        "P10-P20": 2,
    }

    low_density["orden_baja_densidad"] = (
        low_density["rango_percentil"]
        .map(orden_low)
        .fillna(99)
        .astype(int)
    )

    low_density = low_density.sort_values(
        [
            "orden_baja_densidad",
            "n_points",
            "points_km2",
        ],
        ascending=[
            True,
            True,
            True,
        ],
    )

    # --------------------------------------------------------
    # 9. Exportar GPKG
    # --------------------------------------------------------

    export_outputs(grid_density, low_density)

    # --------------------------------------------------------
    # 10. Exportar figura
    # --------------------------------------------------------

    export_figure(grid_density)

    # --------------------------------------------------------
    # 11. Mensajes finales
    # --------------------------------------------------------

    n_total_celdas = len(grid_density)
    n_celdas_con_puntos = int((grid_density["n_points"] > 0).sum())
    n_celdas_sin_puntos = int((grid_density["n_points"] == 0).sum())

    print("\n============================================================")
    print("Proceso finalizado.")
    print("============================================================")
    print(f"Total de puntos: {len(points_m):,}")
    print(f"Total de celdas: {n_total_celdas:,}")
    print(f"Celdas con puntos: {n_celdas_con_puntos:,}")
    print(f"Celdas sin puntos: {n_celdas_sin_puntos:,}")
    print(f"Celdas baja densidad exportadas: {len(low_density):,}")
    print("")
    print("Salidas:")
    print(f"  GPKG: {OUT_GPKG}")
    print("    - layer: grid_densidad_puntos")
    print("    - layer: grid_baja_densidad")
    print(f"  CSV resumen general:        {OUT_CSV}")
    print(f"  CSV percentiles sin ceros:  {OUT_PERCENTILES_CSV}")
    print(f"  CSV deciles sin ceros:      {OUT_DECILES_CSV}")
    print(f"  PNG:                        {OUT_FIG}")
    print("============================================================")


if __name__ == "__main__":
    main()