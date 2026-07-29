# -*- coding: utf-8 -*-
"""Diagnóstico espacial de predictores mediante variogramas.

Implementa un flujo inspirado en Stock (2025): toma una muestra del 5 % de
las observaciones dentro de cada cuadrante, calcula un variograma empírico por
predictor, ajusta modelos esférico y exponencial y compara el rango efectivo
estimado con bloques de 20 km.

La etapa es exclusivamente diagnóstica: no modifica los datos, los folds ni el
modelo de la Actividad 4.7.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib-cache"))

import matplotlib
import numpy as np
import pandas as pd
import yaml
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

try:
    from pyproj import CRS, Transformer
except ImportError:  # Permite ejecutar el diagnóstico en entornos mínimos.
    CRS = None
    Transformer = None


LOGGER = logging.getLogger("a4_7_predictor_variograms")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_6_1A_predictor_spatial_variograms.yaml"


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("El YAML debe contener un diccionario en la raíz.")
    return config


def configure_logger(output_dir: Path) -> None:
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    for handler in (
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(output_dir / "logs" / "predictor_variograms.log", mode="w", encoding="utf-8"),
    ):
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)


def read_dataset(config: dict[str, Any]) -> pd.DataFrame:
    paths = config["paths"]
    parquet = resolve_path(paths["modeling_dataset_parquet"])
    csv = resolve_path(paths["modeling_dataset_csv"])
    if parquet.exists():
        try:
            LOGGER.info("Leyendo Parquet: %s", parquet)
            return pd.read_parquet(parquet)
        except Exception as error:
            LOGGER.warning("Falló la lectura de Parquet (%s); se intentará CSV.", error)
    if csv.exists():
        LOGGER.info("Leyendo CSV: %s", csv)
        return pd.read_csv(csv, low_memory=False)
    raise FileNotFoundError(f"No existe el dataset: {parquet} ni {csv}")


def read_feature_columns(config: dict[str, Any], dataframe: pd.DataFrame) -> list[str]:
    path = resolve_path(config["paths"]["feature_columns_txt"])
    if not path.exists():
        raise FileNotFoundError(f"No existe la lista de predictores: {path}")
    features = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    missing = [name for name in features if name not in dataframe.columns]
    if missing:
        raise ValueError(f"Predictores ausentes en el dataset: {missing}")
    numeric = [name for name in features if pd.api.types.is_numeric_dtype(dataframe[name])]
    excluded = sorted(set(features) - set(numeric))
    if excluded:
        LOGGER.warning("Se omiten %d predictores no numéricos: %s", len(excluded), excluded)
    if not numeric:
        raise ValueError("No se encontraron predictores numéricos.")
    return numeric


def sample_within_groups(
    dataframe: pd.DataFrame,
    group_field: str,
    fraction: float,
    minimum: int,
    maximum_total: int | None,
    seed: int,
) -> pd.DataFrame:
    if not 0 < fraction <= 1:
        raise ValueError("sampling.fraction_per_group debe estar en (0, 1].")
    rng = np.random.default_rng(seed)
    selected: list[np.ndarray] = []
    for _, group in dataframe.groupby(group_field, sort=True, dropna=False):
        n = min(len(group), max(minimum, int(math.ceil(fraction * len(group)))))
        selected.append(rng.choice(group.index.to_numpy(), size=n, replace=False))
    indexes = np.concatenate(selected)
    sample = dataframe.loc[indexes].copy()

    if maximum_total is not None and len(sample) > maximum_total:
        LOGGER.warning(
            "La muestra estratificada (%d) supera max_rows_total=%d; se aplica un segundo muestreo.",
            len(sample), maximum_total,
        )
        # Conserva al menos una observación de cada grupo y completa aleatoriamente.
        anchors = sample.groupby(group_field, sort=True, dropna=False).sample(n=1, random_state=seed)
        remaining_n = maximum_total - len(anchors)
        if remaining_n < 0:
            raise ValueError("max_rows_total es menor que el número de cuadrantes.")
        remainder = sample.drop(index=anchors.index)
        extra = remainder.sample(n=min(remaining_n, len(remainder)), random_state=seed)
        sample = pd.concat([anchors, extra], ignore_index=False)

    return sample.sort_index().reset_index(drop=True)


def project_coordinates(
    longitude: pd.Series,
    latitude: pd.Series,
    source_crs: str,
    metric_crs: str,
) -> tuple[np.ndarray, np.ndarray, str]:
    lon = pd.to_numeric(longitude, errors="coerce").to_numpy(dtype=float)
    lat = pd.to_numeric(latitude, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(lon).all() or not np.isfinite(lat).all():
        raise ValueError("Las coordenadas contienen valores nulos o no numéricos.")

    if CRS is None or Transformer is None:
        if metric_crs != "auto_aeqd":
            raise ImportError(
                "Se requiere pyproj para usar un CRS explícito. Instale pyproj o use auto_aeqd."
            )
        # Respaldo equirectangular local. Para el análisis definitivo se recomienda
        # pyproj/AEQD; la aproximación permite pruebas en entornos mínimos.
        radius_m = 6_371_008.8
        lon0, lat0 = float(np.mean(lon)), float(np.mean(lat))
        x = radius_m * np.deg2rad(lon - lon0) * np.cos(np.deg2rad(lat0))
        y = radius_m * np.deg2rad(lat - lat0)
        LOGGER.warning(
            "pyproj no está disponible; se usa una aproximación equirectangular centrada en %.5f, %.5f.",
            lon0,
            lat0,
        )
        return x, y, f"equirectangular_local(lon_0={lon0:.10f},lat_0={lat0:.10f})"

    if metric_crs == "auto_aeqd":
        lon0, lat0 = float(np.mean(lon)), float(np.mean(lat))
        target = CRS.from_proj4(
            f"+proj=aeqd +lat_0={lat0:.10f} +lon_0={lon0:.10f} +datum=WGS84 +units=m +no_defs"
        )
        target_label = target.to_proj4()
    else:
        target = CRS.from_user_input(metric_crs)
        target_label = target.to_string()
        if not target.is_projected:
            raise ValueError("coordinates.metric_crs debe ser un CRS proyectado en metros.")

    transformer = Transformer.from_crs(CRS.from_user_input(source_crs), target, always_xy=True)
    x, y = transformer.transform(lon, lat)
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float), target_label


def generate_random_pairs(n: int, max_pairs: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    total = n * (n - 1) // 2
    if total <= max_pairs and n <= 10000:
        return np.triu_indices(n, k=1)

    rng = np.random.default_rng(seed)
    # El sobremuestreo compensa pares i == j; luego se eliminan duplicados.
    collected: list[np.ndarray] = []
    needed = min(max_pairs, total)
    current = 0
    while current < needed:
        batch_n = min(max(10000, (needed - current) * 2), 4000000)
        a = rng.integers(0, n, size=batch_n, dtype=np.int64)
        b = rng.integers(0, n, size=batch_n, dtype=np.int64)
        valid = a != b
        lo = np.minimum(a[valid], b[valid])
        hi = np.maximum(a[valid], b[valid])
        codes = np.unique(lo * np.int64(n) + hi)
        collected.append(codes)
        current += len(codes)
    codes = np.unique(np.concatenate(collected))[:needed]
    return codes // n, codes % n


def spherical(h: np.ndarray, nugget: float, partial_sill: float, effective_range: float) -> np.ndarray:
    ratio = np.asarray(h) / effective_range
    core = nugget + partial_sill * (1.5 * ratio - 0.5 * ratio**3)
    return np.where(h < effective_range, core, nugget + partial_sill)


def exponential(h: np.ndarray, nugget: float, partial_sill: float, effective_range: float) -> np.ndarray:
    # La parametrización hace que effective_range corresponda aproximadamente al 95 % del sill.
    return nugget + partial_sill * (1.0 - np.exp(-3.0 * np.asarray(h) / effective_range))


MODEL_FUNCTIONS: dict[str, Callable[[np.ndarray, float, float, float], np.ndarray]] = {
    "spherical": spherical,
    "exponential": exponential,
}


def empirical_variogram(
    values: np.ndarray,
    pair_i: np.ndarray,
    pair_j: np.ndarray,
    distances_km: np.ndarray,
    bin_edges: np.ndarray,
    min_pairs_per_bin: int,
) -> pd.DataFrame:
    valid = np.isfinite(values[pair_i]) & np.isfinite(values[pair_j])
    valid &= distances_km <= bin_edges[-1]
    i, j, distance = pair_i[valid], pair_j[valid], distances_km[valid]
    semivariance = 0.5 * np.square(values[i] - values[j])
    bins = np.digitize(distance, bin_edges, right=False) - 1
    rows: list[dict[str, Any]] = []
    for bin_id in range(len(bin_edges) - 1):
        mask = bins == bin_id
        count = int(mask.sum())
        if count < min_pairs_per_bin:
            continue
        rows.append(
            {
                "bin_id": bin_id,
                "distance_min_km": bin_edges[bin_id],
                "distance_max_km": bin_edges[bin_id + 1],
                "mean_distance_km": float(np.mean(distance[mask])),
                "semivariance": float(np.mean(semivariance[mask])),
                "n_pairs": count,
            }
        )
    return pd.DataFrame(rows)


def fit_variogram_models(
    empirical: pd.DataFrame,
    variance: float,
    candidate_models: list[str],
    max_lag_km: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if len(empirical) < 5 or not np.isfinite(variance) or variance <= 0:
        return {}, []
    h = empirical["mean_distance_km"].to_numpy(dtype=float)
    gamma = empirical["semivariance"].to_numpy(dtype=float)
    weights = empirical["n_pairs"].to_numpy(dtype=float)
    sigma = 1.0 / np.sqrt(weights / np.max(weights))
    fits: list[dict[str, Any]] = []
    for name in candidate_models:
        if name not in MODEL_FUNCTIONS:
            raise ValueError(f"Modelo de variograma no admitido: {name}")
        function = MODEL_FUNCTIONS[name]
        try:
            parameters, _ = curve_fit(
                function,
                h,
                gamma,
                p0=[max(0.0, float(gamma[0]) * 0.5), variance, max_lag_km * 0.5],
                bounds=([0.0, 0.0, max(h.min(), 1e-6)], [variance * 5, variance * 10, max_lag_km * 5]),
                sigma=sigma,
                absolute_sigma=False,
                maxfev=50000,
            )
            predicted = function(h, *parameters)
            residual = gamma - predicted
            rss = float(np.sum(residual**2))
            rmse = float(np.sqrt(np.mean(residual**2)))
            n, k = len(gamma), 3
            aic = float(n * np.log(max(rss / n, np.finfo(float).tiny)) + 2 * k)
            fits.append(
                {
                    "model": name,
                    "nugget": float(parameters[0]),
                    "partial_sill": float(parameters[1]),
                    "sill": float(parameters[0] + parameters[1]),
                    "effective_range_km": float(parameters[2]),
                    "rmse": rmse,
                    "aic": aic,
                }
            )
        except (RuntimeError, ValueError, FloatingPointError) as error:
            LOGGER.warning("No se pudo ajustar %s: %s", name, error)
    if not fits:
        return {}, []
    return min(fits, key=lambda item: item["aic"]), fits


def classify_range(range_km: float, block_km: float, tolerance: float) -> str:
    if not np.isfinite(range_km):
        return "indeterminado"
    lower, upper = block_km * (1 - tolerance), block_km * (1 + tolerance)
    if range_km < lower:
        return "rango_menor_que_bloque"
    if range_km <= upper:
        return "rango_aproximado_al_bloque"
    return "rango_mayor_que_bloque"


def safe_filename(value: str) -> str:
    """Convierte el nombre de un predictor en un nombre de archivo estable."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
    return cleaned or "predictor"


def plot_predictor_variogram(
    predictor: str,
    empirical: pd.DataFrame,
    best: dict[str, Any],
    max_lag_km: float,
    reference_block_km: float,
    plot_config: dict[str, Any],
    output_path: Path,
) -> None:
    """Grafica puntos empíricos, curva ajustada y referencias interpretativas."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(9.5, 6.0), constrained_layout=True)

    pair_counts = empirical["n_pairs"].to_numpy(dtype=float)
    sizes = 25.0 + 90.0 * np.sqrt(pair_counts / pair_counts.max())
    axis.scatter(
        empirical["mean_distance_km"],
        empirical["semivariance"],
        s=sizes,
        color="#1f77b4",
        edgecolor="white",
        linewidth=0.6,
        alpha=0.88,
        label="Variograma empírico",
        zorder=3,
    )

    curve_limit = max(max_lag_km, reference_block_km * 1.05)
    distance_grid = np.linspace(0.0, curve_limit, 600)
    function = MODEL_FUNCTIONS[best["model"]]
    fitted = function(
        distance_grid,
        best["nugget"],
        best["partial_sill"],
        best["effective_range_km"],
    )
    axis.plot(
        distance_grid,
        fitted,
        color="#d62728",
        linewidth=2.2,
        label=f"Ajuste {best['model']}",
        zorder=2,
    )

    range_km = float(best["effective_range_km"])
    if range_km <= curve_limit:
        axis.axvline(
            range_km,
            color="#d62728",
            linestyle="--",
            linewidth=1.5,
            label=f"Rango efectivo = {range_km:.2f} km",
        )
    else:
        axis.text(
            0.99,
            0.97,
            f"Rango estimado fuera del gráfico: {range_km:.2f} km",
            transform=axis.transAxes,
            ha="right",
            va="top",
            color="#a61b1b",
            bbox={"boxstyle": "round,pad=0.35", "facecolor": "#fff2f2", "edgecolor": "#d62728"},
        )

    if plot_config.get("show_reference_block_size", True):
        axis.axvline(
            reference_block_km,
            color="#2ca02c",
            linestyle=":",
            linewidth=2.0,
            label=f"Referencia de bloque = {reference_block_km:g} km",
        )

    if plot_config.get("show_nugget_and_sill", True):
        axis.axhline(best["nugget"], color="#7f7f7f", linestyle=":", linewidth=1.0, label=f"Nugget = {best['nugget']:.3g}")
        axis.axhline(best["sill"], color="#9467bd", linestyle="-.", linewidth=1.0, label=f"Sill = {best['sill']:.3g}")

    axis.set_title(f"Variograma espacial — {predictor}", fontsize=13, weight="bold")
    axis.set_xlabel("Distancia entre pares (km)")
    axis.set_ylabel("Semivarianza")
    axis.set_xlim(left=0.0, right=curve_limit)
    axis.set_ylim(bottom=0.0)
    axis.grid(True, color="#dddddd", linewidth=0.7, alpha=0.7)
    axis.legend(loc="best", fontsize=8.5, frameon=True)
    axis.text(
        0.01,
        0.01,
        "El tamaño de los puntos representa el número de pares por intervalo.",
        transform=axis.transAxes,
        fontsize=8,
        color="#555555",
        ha="left",
        va="bottom",
    )
    figure.savefig(output_path, dpi=int(plot_config.get("dpi", 180)), bbox_inches="tight")
    plt.close(figure)


def plot_range_detail(
    summary: pd.DataFrame,
    reference_block_km: float,
    plot_config: dict[str, Any],
    output_path: Path,
) -> None:
    """Grafica el detalle de los rangos estimados para los 96 predictores."""
    work = summary.loc[
        summary["effective_range_km"].notna(),
        ["predictor", "effective_range_km", "range_reaches_within_max_lag"],
    ].sort_values("effective_range_km")
    if work.empty:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    height = max(6.0, min(30.0, 0.27 * len(work) + 2.0))
    figure, axis = plt.subplots(figsize=(11.0, height), constrained_layout=True)
    colors = np.where(work["range_reaches_within_max_lag"], "#1f77b4", "#e07b39")
    positions = np.arange(len(work))
    axis.barh(positions, work["effective_range_km"], color=colors, alpha=0.9)
    axis.set_yticks(positions, labels=work["predictor"], fontsize=7.5)
    if plot_config.get("show_reference_block_size", True):
        axis.axvline(
            reference_block_km,
            color="#2ca02c",
            linestyle=":",
            linewidth=2.2,
            label=f"Referencia de bloque = {reference_block_km:g} km",
        )
    axis.set_title("Rangos efectivos estimados por predictor", fontsize=14, weight="bold")
    axis.set_xlabel("Rango efectivo (km)")
    axis.set_ylabel("Predictor")
    axis.grid(axis="x", color="#dddddd", linewidth=0.7, alpha=0.7)
    axis.legend(loc="lower right")
    axis.text(
        0.99,
        0.01,
        "Azul: rango dentro del máximo lag | Naranja: rango extrapolado",
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        color="#555555",
    )
    figure.savefig(output_path, dpi=int(plot_config.get("dpi", 180)), bbox_inches="tight")
    plt.close(figure)


def plot_range_summary(
    summary: pd.DataFrame,
    reference_block_km: float,
    plot_config: dict[str, Any],
    output_path: Path,
) -> None:
    """Genera una síntesis horizontal, compacta y legible al insertarla en Word."""
    category_order = [
        "rango_menor_que_bloque",
        "rango_aproximado_al_bloque",
        "rango_mayor_que_bloque",
    ]
    category_labels = {
        "rango_menor_que_bloque": "Menor que el bloque\n(< 16 km)",
        "rango_aproximado_al_bloque": "Aproximado al bloque\n(16–24 km)",
        "rango_mayor_que_bloque": "Mayor que el bloque\n(> 24 km)",
    }
    category_colors = {
        "rango_menor_que_bloque": "#2f80c1",
        "rango_aproximado_al_bloque": "#59a14f",
        "rango_mayor_que_bloque": "#e68645",
    }

    valid = summary.loc[summary["effective_range_km"].notna()].copy()
    if valid.empty:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    total = len(valid)
    category_counts = (
        valid["comparison_with_reference_block"]
        .value_counts()
        .reindex(category_order, fill_value=0)
    )
    reached = valid["range_reaches_within_max_lag"].fillna(False).astype(bool)
    n_reached = int(reached.sum())
    n_extrapolated = int((~reached).sum())

    figure, axis = plt.subplots(figsize=(11.5, 5.2))
    figure.suptitle(
        f"Diagnóstico de autocorrelación espacial frente a bloques de {reference_block_km:g} km",
        fontsize=18,
        weight="bold",
        y=0.95,
    )
    positions = np.arange(len(category_order))
    values = category_counts.to_numpy(dtype=int)
    axis.barh(
        positions,
        values,
        color=[category_colors[item] for item in category_order],
        height=0.58,
    )
    axis.set_yticks(
        positions,
        labels=[category_labels[item] for item in category_order],
        fontsize=14,
    )
    axis.invert_yaxis()
    axis.set_xlabel("Número de predictores", fontsize=14)
    axis.tick_params(axis="x", labelsize=12)
    axis.set_xlim(0, max(values) * 1.25)
    axis.grid(axis="x", color="#dddddd", linewidth=0.8, alpha=0.8)
    axis.set_axisbelow(True)
    for position, value in enumerate(values):
        percentage = 100.0 * value / total
        axis.text(
            value + max(values) * 0.025,
            position,
            f"{value} ({percentage:.1f} %)",
            va="center",
            ha="left",
            fontsize=14,
            weight="bold",
        )

    figure.subplots_adjust(left=0.30, right=0.96, bottom=0.22, top=0.79)
    figure.text(
        0.5,
        0.055,
        "Tolerancia descriptiva: ±20 %. "
        f"Rango alcanzado dentro del máximo lag: {n_reached}; "
        f"rango extrapolado: {n_extrapolated}. Total: {total} predictores.",
        ha="center",
        va="bottom",
        fontsize=11.5,
        color="#555555",
    )
    figure.savefig(
        output_path,
        dpi=max(300, int(plot_config.get("dpi", 180))),
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(figure)


def dataframe_to_markdown(dataframe: pd.DataFrame) -> str:
    if dataframe.empty:
        return "_Sin resultados._"
    work = dataframe.copy()
    for column in work.select_dtypes(include=["float"]).columns:
        work[column] = work[column].map(lambda value: "" if pd.isna(value) else f"{value:.4f}")
    headers = list(work.columns)
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in work.itertuples(index=False, name=None))
    return "\n".join(lines)


def write_report(
    path: Path,
    summary: pd.DataFrame,
    sample: pd.DataFrame,
    config: dict[str, Any],
    metric_crs: str,
    max_lag_km: float,
    n_pairs: int,
) -> None:
    assessment = config["block_assessment"]
    counts = summary["comparison_with_reference_block"].value_counts(dropna=False).rename_axis("resultado").reset_index(name="n_variables")
    display_columns = [
        "predictor", "n_non_null", "n_unique", "selected_model", "effective_range_km",
        "nugget", "sill", "nugget_sill_ratio", "fit_rmse", "range_reaches_within_max_lag",
        "comparison_with_reference_block", "status",
    ]
    text = f"""# Diagnóstico espacial de predictores mediante variogramas

## Propósito

Estimar el rango efectivo de autocorrelación de cada predictor y compararlo descriptivamente con bloques de **{assessment['reference_block_size_km']} km**. Este análisis no modifica los folds ni el modelo.

## Configuración ejecutada

- Filas muestreadas: {len(sample):,}
- Cuadrantes representados: {sample[config['fields']['group']].nunique():,}
- Fracción por cuadrante: {config['sampling']['fraction_per_group']}
- Pares espaciales utilizados: {n_pairs:,}
- Distancia máxima analizada: {max_lag_km:.3f} km
- CRS métrico: `{metric_crs}`
- Modelos candidatos: {', '.join(config['variogram']['candidate_models'])}
- Selección del modelo: menor AIC
- Gráficos individuales: `plots/by_predictor/`
- Gráfico resumen de rangos: `plots/predictor_effective_ranges_summary.png`

## Comparación con el bloque de referencia

{dataframe_to_markdown(counts)}

La comparación usa una tolerancia descriptiva de ±{100 * assessment['approximately_equal_relative_tolerance']:.1f} %. No constituye por sí sola una prueba de independencia entre entrenamiento y validación.

## Resultados por predictor

{dataframe_to_markdown(summary[display_columns])}

## Criterios de interpretación

- `range_reaches_within_max_lag = true`: el rango ajustado se encuentra dentro de la distancia observada; es más interpretable.
- `false`: el rango es una extrapolación del modelo más allá del máximo lag y debe considerarse incierto.
- Un rango mayor de 20 km indica que la estructura espacial del predictor atraviesa más de un cuadrante de 20 km.
- Un rango menor de 20 km indica compatibilidad de escala, pero no garantiza separación física entre cuadrantes vecinos.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(config_path: Path) -> None:
    config = read_yaml(config_path)
    output_dir = resolve_path(config["paths"]["output_dir"])
    for directory in ("tables", "reports", "logs"):
        (output_dir / directory).mkdir(parents=True, exist_ok=True)
    configure_logger(output_dir)

    dataframe = read_dataset(config)
    fields = config["fields"]
    required = [fields["group"], fields["longitude"], fields["latitude"]]
    missing = [column for column in required if column not in dataframe.columns]
    if missing:
        raise ValueError(f"Faltan campos requeridos: {missing}")
    dataframe = dataframe.dropna(subset=required).copy()
    features = read_feature_columns(config, dataframe)

    sampling = config["sampling"]
    sample = sample_within_groups(
        dataframe,
        fields["group"],
        float(sampling["fraction_per_group"]),
        int(sampling["min_rows_per_group"]),
        None if sampling.get("max_rows_total") is None else int(sampling["max_rows_total"]),
        int(sampling["random_state"]),
    )
    LOGGER.info("Muestra: %d de %d filas; %d cuadrantes.", len(sample), len(dataframe), sample[fields["group"]].nunique())

    coordinates = config["coordinates"]
    x, y, metric_crs = project_coordinates(
        sample[fields["longitude"]], sample[fields["latitude"]],
        coordinates["source_crs"], coordinates["metric_crs"],
    )
    pair_i, pair_j = generate_random_pairs(len(sample), int(config["variogram"]["max_pairs"]), int(sampling["random_state"]))
    distances_km = np.hypot(x[pair_i] - x[pair_j], y[pair_i] - y[pair_j]) / 1000.0

    variogram_config = config["variogram"]
    plot_config = config.get("plots", {"enabled": False})
    reference_block_km = float(config["block_assessment"]["reference_block_size_km"])
    plots_dir = output_dir / config["outputs"].get("plots_dir", "plots/by_predictor")
    if variogram_config["max_lag_method"] == "fixed_km":
        max_lag_km = float(variogram_config["max_lag_km"])
    elif variogram_config["max_lag_method"] == "pair_distance_quantile":
        max_lag_km = float(np.quantile(distances_km, float(variogram_config["max_lag_quantile"])))
    else:
        raise ValueError("max_lag_method debe ser fixed_km o pair_distance_quantile.")
    unit_edges = np.linspace(0.0, 1.0, int(variogram_config["n_distance_bins"]) + 1)
    spacing = variogram_config.get("distance_bin_spacing", "linear")
    if spacing == "quadratic":
        bin_edges = max_lag_km * unit_edges**2
    elif spacing == "linear":
        bin_edges = max_lag_km * unit_edges
    else:
        raise ValueError("distance_bin_spacing debe ser linear o quadratic.")
    LOGGER.info("Pares=%d | max lag=%.3f km | bins=%d", len(pair_i), max_lag_km, len(bin_edges) - 1)

    summary_rows: list[dict[str, Any]] = []
    empirical_tables: list[pd.DataFrame] = []
    for position, feature in enumerate(features, start=1):
        values = pd.to_numeric(sample[feature], errors="coerce").to_numpy(dtype=float)
        n_non_null = int(np.isfinite(values).sum())
        n_unique = int(pd.Series(values[np.isfinite(values)]).nunique())
        base = {"predictor": feature, "n_non_null": n_non_null, "n_unique": n_unique}
        if n_non_null < int(variogram_config["min_non_null_values"]) or n_unique < int(variogram_config["min_unique_values"]):
            summary_rows.append({**base, "status": "insufficient_values"})
            continue

        empirical = empirical_variogram(
            values, pair_i, pair_j, distances_km, bin_edges,
            int(variogram_config["min_pairs_per_bin"]),
        )
        empirical.insert(0, "predictor", feature)
        empirical_tables.append(empirical)
        best, fits = fit_variogram_models(
            empirical,
            float(np.nanvar(values, ddof=1)),
            list(variogram_config["candidate_models"]),
            max_lag_km,
        )
        if not best:
            summary_rows.append({**base, "n_empirical_bins": len(empirical), "status": "fit_failed"})
            continue
        range_km = best["effective_range_km"]
        block = float(config["block_assessment"]["reference_block_size_km"])
        tolerance = float(config["block_assessment"]["approximately_equal_relative_tolerance"])
        summary_rows.append(
            {
                **base,
                "n_empirical_bins": len(empirical),
                "selected_model": best["model"],
                "effective_range_km": range_km,
                "nugget": best["nugget"],
                "partial_sill": best["partial_sill"],
                "sill": best["sill"],
                "nugget_sill_ratio": best["nugget"] / best["sill"] if best["sill"] > 0 else np.nan,
                "fit_rmse": best["rmse"],
                "fit_aic": best["aic"],
                "range_reaches_within_max_lag": bool(range_km <= max_lag_km),
                "comparison_with_reference_block": classify_range(range_km, block, tolerance),
                "candidate_fits": "; ".join(f"{item['model']}:AIC={item['aic']:.3f}" for item in fits),
                "status": "ok" if range_km <= max_lag_km else "range_extrapolated_beyond_max_lag",
            }
        )
        if plot_config.get("enabled", True):
            extension = str(plot_config.get("format", "png")).lstrip(".")
            plot_path = plots_dir / f"{position:03d}_{safe_filename(feature)}.{extension}"
            plot_predictor_variogram(
                feature,
                empirical,
                best,
                max_lag_km,
                reference_block_km,
                plot_config,
                plot_path,
            )
        LOGGER.info("[%d/%d] %s | modelo=%s | rango=%.3f km", position, len(features), feature, best["model"], range_km)

    summary = pd.DataFrame(summary_rows).sort_values(["status", "effective_range_km"], na_position="last")
    empirical_all = pd.concat(empirical_tables, ignore_index=True) if empirical_tables else pd.DataFrame()
    outputs = config["outputs"]
    summary_path = output_dir / outputs["summary_csv"]
    empirical_path = output_dir / outputs["empirical_bins_csv"]
    sample_path = output_dir / outputs["sampled_points_csv"]
    for path in (summary_path, empirical_path, sample_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_path, index=False)
    empirical_all.to_csv(empirical_path, index=False)
    sample[[fields["group"], fields["longitude"], fields["latitude"]]].to_csv(sample_path, index=False)
    if plot_config.get("enabled", True):
        plot_range_summary(
            summary,
            reference_block_km,
            plot_config,
            output_dir / outputs.get("ranges_summary_plot", "plots/predictor_effective_ranges_summary.png"),
        )
        plot_range_detail(
            summary,
            reference_block_km,
            plot_config,
            output_dir / outputs.get("ranges_detailed_plot", "plots/predictor_effective_ranges_detailed.png"),
        )
    write_report(
        output_dir / outputs["report_md"], summary, sample, config, metric_crs,
        max_lag_km, len(pair_i),
    )
    LOGGER.info("Finalizado. Resumen: %s", summary_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Ruta al YAML de configuración.")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(arguments.config.resolve())
