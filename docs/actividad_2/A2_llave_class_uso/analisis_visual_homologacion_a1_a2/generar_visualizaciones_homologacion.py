# -*- coding: utf-8 -*-
"""Visualizaciones ejecutivas para resultados A1/A2 y base homologada.

El script evita dependencias externas: lee el GeoPackage normalizado con
sqlite3, cruza las tablas 1:1 por xy_group_id y exporta SVG/HTML/CSV.
"""

from __future__ import annotations

import csv
import html
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Iterable


PACKAGE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = PACKAGE_DIR / "resultados"
FIG_DIR = RESULTS_DIR / "figuras"
TABLE_DIR = RESULTS_DIR / "tablas"

COUNTRY_DISPLAY = {
    "belice": "Belice",
    "costa rica": "Costa Rica",
    "el salvador": "El Salvador",
    "guatemala": "Guatemala",
    "honduras": "Honduras",
    "méxico": "México",
    "mexico": "México",
    "nicaragua": "Nicaragua",
    "panamá": "Panamá",
    "panama": "Panamá",
}

USE_COLORS = {
    "entrenamiento": "#2E7D59",
    "validación": "#356C9A",
    "apoyo interpretativo": "#D49A2A",
    "referencia contextual": "#777A7E",
    "máscaras": "#B85C3A",
    "prueba": "#7E5AA6",
}

LEVEL0_COLORS = {
    "bosques/tierras forestales": "#246B4B",
    "no bosques": "#D2923A",
}

GAP_COLORS = {
    "sin puntos": "#B94A48",
    "baja cantidad": "#D9903D",
    "score bajo": "#D6B94A",
    "cumple umbral operativo": "#5E9E73",
}

TARGET_COLORS = {
    11: "#2E7D59",
    12: "#4D8E4A",
    13: "#1B8A7A",
    14: "#8AA64C",
    15: "#6B7F3A",
    21: "#B6812A",
    22: "#D2923A",
    23: "#8A6E58",
    24: "#3D7FA6",
    25: "#7A7A7A",
}


def find_project_root() -> Path:
    """Busca la raíz del proyecto desde la carpeta del script."""
    marker = Path("data/processed/a2_1_modelo_datos/gpkg/a2_1_xy_point.gpkg")
    for parent in [PACKAGE_DIR, *PACKAGE_DIR.parents]:
        if (parent / marker).exists():
            return parent
    raise FileNotFoundError(
        "No se encontró data/processed/a2_1_modelo_datos/gpkg/a2_1_xy_point.gpkg"
    )


PROJECT_ROOT = find_project_root()
GPKG = PROJECT_ROOT / "data/processed/a2_1_modelo_datos/gpkg/a2_1_xy_point.gpkg"
TABLES_A1 = PROJECT_ROOT / "outputs/tables"
GAP_INTEGRATED_L1 = (
    TABLES_A1
    / "10_diagnostico_vacios_clases/10_diagnostico_integrado_pais_clase_Nivel_1.csv"
)
GAP_COUNTRY_L1 = (
    TABLES_A1
    / "10_diagnostico_vacios_clases/10_resumen_problemas_por_pais_Nivel_1.csv"
)
GAP_CLASS_L1 = (
    TABLES_A1
    / "10_diagnostico_vacios_clases/10_resumen_problemas_por_clase_Nivel_1.csv"
)
SOURCE_RANKING = TABLES_A1 / "10_source_aptitude_ranking.csv"


def ensure_dirs() -> None:
    for path in [RESULTS_DIR, FIG_DIR, TABLE_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def sql_rows(sql: str, params: tuple = ()) -> list[dict]:
    with sqlite3.connect(GPKG) as con:
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute(sql, params)]


def stream_sql(sql: str, params: tuple = ()) -> Iterable[dict]:
    with sqlite3.connect(GPKG) as con:
        con.row_factory = sqlite3.Row
        for row in con.execute(sql, params):
            yield dict(row)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def save_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def as_float(value: object, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: object, default: int = 0) -> int:
    try:
        if value in ("", None):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def fmt_num(value: object, decimals: int = 0) -> str:
    number = as_float(value)
    if decimals == 0:
        return f"{number:,.0f}"
    return f"{number:,.{decimals}f}"


def fmt_pct(value: object, decimals: int = 1) -> str:
    return f"{as_float(value):.{decimals}f}%"


def display_country(value: str) -> str:
    key = str(value).strip().lower()
    return COUNTRY_DISPLAY.get(key, str(value).strip().title())


def display_class(value: str) -> str:
    text = str(value).strip()
    replacements = {
        "no bosques": "No bosques",
        "bosques/tierras forestales": "Bosques / tierras forestales",
        "zonas agrícolas no arbóreas": "Zonas agrícolas no arbóreas",
        "cultivos arbóreos": "Cultivos arbóreos",
        "bosques latifoliados y mixtos": "Bosques latifoliados y mixtos",
        "construido": "Construido",
        "otras tierras": "Otras tierras",
        "bosques de coníferas": "Bosques de coníferas",
        "bosques de mangle": "Bosques de mangle",
        "plantaciones forestales": "Plantaciones forestales",
        "cuerpos de agua": "Cuerpos de agua",
        "bosques secos": "Bosques secos",
    }
    return replacements.get(text.lower(), text)


def compact_source(value: str, limit: int = 58) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def slugify(value: str) -> str:
    text = value.lower()
    text = (
        text.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - pos) + values[hi] * (pos - lo)


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, c)):02X}" for c in rgb)


def blend(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    a = hex_to_rgb(c1)
    b = hex_to_rgb(c2)
    return rgb_to_hex(tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3)))


def text(
    x: float,
    y: float,
    value: object,
    size: int = 13,
    fill: str = "#263238",
    weight: int | str = 400,
    anchor: str = "start",
    extra: str = "",
) -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" {extra}>'
        f"{esc(value)}</text>"
    )


def wrap_text_lines(value: str, max_chars: int) -> list[str]:
    words = str(value).split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        if sum(len(w) for w in current) + len(current) + len(word) <= max_chars:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines or [""]


def wrapped_text(
    x: float,
    y: float,
    value: str,
    max_chars: int,
    size: int = 12,
    fill: str = "#263238",
    anchor: str = "start",
    line_gap: int = 14,
    weight: int | str = 400,
) -> str:
    lines = wrap_text_lines(value, max_chars)
    parts = []
    for i, line in enumerate(lines):
        parts.append(text(x, y + i * line_gap, line, size, fill, weight, anchor))
    return "\n".join(parts)


def svg_shell(width: int, height: int, title: str, subtitle: str, body: str) -> str:
    header = ""
    if title:
        header += text(34, 40, title, 23, "#172326", 700)
    if subtitle:
        header += "\n" + text(34, 64, subtitle, 13, "#697276", 400)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
<defs>
  <style>
    .axis {{ stroke: #C8CED1; stroke-width: 1; }}
    .grid {{ stroke: #E8ECEC; stroke-width: 1; }}
    .caption {{ fill: #697276; font-size: 13px; }}
  </style>
</defs>
<rect width="100%" height="100%" fill="#FFFFFF"/>
{header}
{body}
</svg>'''


def chart_stacked_country_l0(country_rows: list[dict], country_l0: list[dict]) -> str:
    width = 1280
    row_h = 42
    top = 112
    left = 225
    bar_w = 720
    bar_h = 24
    height = top + row_h * len(country_rows) + 105
    totals = {r["pais"]: as_float(r["n_xy"]) for r in country_rows}
    by_country: dict[str, dict[str, float]] = defaultdict(dict)
    for row in country_l0:
        by_country[row["pais"]][row["nivel_0_propuesta"]] = as_float(row["n_xy"])

    parts = []
    parts.append(text(left, top - 18, "Composición dentro de cada país", 12, "#697276"))
    parts.append(text(left + bar_w + 54, top - 18, "Volumen XY", 12, "#697276"))
    for i, row in enumerate(country_rows):
        pais = row["pais"]
        total = totals[pais]
        y = top + i * row_h
        parts.append(text(left - 18, y + 17, display_country(pais), 13, "#263238", 600, "end"))
        parts.append(
            f'<rect x="{left}" y="{y}" width="{bar_w}" height="{bar_h}" rx="5" fill="#EEF1F0"/>'
        )
        x = left
        for level in ["bosques/tierras forestales", "no bosques"]:
            val = by_country[pais].get(level, 0.0)
            w = 0 if total == 0 else bar_w * val / total
            parts.append(
                f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="{bar_h}" '
                f'fill="{LEVEL0_COLORS[level]}"/>'
            )
            if w > 72:
                pct = 100 * val / total if total else 0
                parts.append(text(x + w / 2, y + 16, f"{pct:.0f}%", 12, "#FFFFFF", 700, "middle"))
            x += w
        radius = 5 + 18 * math.sqrt(total / max(totals.values()))
        cx = left + bar_w + 72
        parts.append(f'<circle cx="{cx}" cy="{y + 12}" r="{radius:.2f}" fill="#263238" opacity="0.18"/>')
        parts.append(text(cx + 35, y + 16, fmt_num(total), 12, "#263238", 600))

    legend_y = height - 44
    x0 = left
    for label, color in [
        ("Bosques / tierras forestales", LEVEL0_COLORS["bosques/tierras forestales"]),
        ("No bosques", LEVEL0_COLORS["no bosques"]),
    ]:
        parts.append(f'<rect x="{x0}" y="{legend_y}" width="16" height="16" rx="3" fill="{color}"/>')
        parts.append(text(x0 + 24, legend_y + 13, label, 13, "#37474F"))
        x0 += 245
    subtitle = "Barras al 100% por país; el círculo codifica el volumen total de grupos XY."
    return svg_shell(width, height, "Balance país por nivel 0 homologado", subtitle, "\n".join(parts))


def chart_heatmap_country_l1(country_rows: list[dict], country_l1: list[dict]) -> str:
    countries = [r["pais"] for r in country_rows]
    class_totals: dict[int, dict] = {}
    matrix: dict[tuple[str, int], dict] = {}
    country_total = {r["pais"]: as_float(r["n_xy"]) for r in country_rows}
    for row in country_l1:
        cid = as_int(row["id_1_propuesta"])
        class_totals.setdefault(
            cid,
            {"id": cid, "name": display_class(row["nivel_1_propuesta"]), "n": 0.0},
        )
        class_totals[cid]["n"] += as_float(row["n_xy"])
        matrix[(row["pais"], cid)] = row
    classes = sorted(class_totals.values(), key=lambda r: r["n"], reverse=True)

    cell_w = 104
    cell_h = 36
    left = 138
    top = 166
    width = left + cell_w * len(classes) + 66
    height = top + cell_h * len(countries) + 98
    max_pct = 80.0
    parts = []

    for j, cls in enumerate(classes):
        x = left + j * cell_w + cell_w / 2
        lines = wrap_text_lines(cls["name"], 13)[:3]
        for k, line in enumerate(lines):
            parts.append(text(x, 104 + k * 13, line, 11, "#475258", 600, "middle"))
        parts.append(text(x, 150, fmt_num(cls["n"]), 10, "#697276", 400, "middle"))

    for i, pais in enumerate(countries):
        y = top + i * cell_h
        parts.append(text(left - 14, y + 23, display_country(pais), 12, "#263238", 600, "end"))
        for j, cls in enumerate(classes):
            cid = cls["id"]
            x = left + j * cell_w
            row = matrix.get((pais, cid), {})
            n_xy = as_float(row.get("n_xy"))
            pct = 100 * n_xy / country_total[pais] if country_total[pais] else 0
            color = blend("#F2F4F1", "#1C786A", math.sqrt(min(pct, max_pct) / max_pct))
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell_w - 2}" height="{cell_h - 2}" rx="4" fill="{color}"/>'
            )
            if pct >= 8:
                fill = "#FFFFFF" if pct >= 22 else "#263238"
                parts.append(text(x + cell_w / 2, y + 22, f"{pct:.0f}%", 11, fill, 700, "middle"))
            elif n_xy > 0:
                parts.append(text(x + cell_w / 2, y + 22, "·", 16, "#263238", 700, "middle"))

    lx = left
    ly = height - 45
    for label, pct in [("0%", 0), ("10%", 10), ("25%", 25), ("50%+", 50)]:
        color = blend("#F2F4F1", "#1C786A", math.sqrt(pct / max_pct))
        parts.append(f'<rect x="{lx}" y="{ly}" width="36" height="14" rx="3" fill="{color}"/>')
        parts.append(text(lx + 44, ly + 12, label, 12, "#697276"))
        lx += 105
    subtitle = "Color = porcentaje de la clase dentro del país. Punto = presencia menor a 8%."
    return svg_shell(width, height, "Matriz país x clase homologada nivel 1", subtitle, "\n".join(parts))


def chart_pareto_sources(source_rows: list[dict], source_display: dict[str, str], total_xy: float) -> str:
    rows = sorted(source_rows, key=lambda r: as_float(r["n_xy"]), reverse=True)
    top_n = 12
    if len(rows) > top_n:
        other = {
            "fuente": "Otras fuentes",
            "n_xy": sum(as_float(r["n_xy"]) for r in rows[top_n:]),
            "score_promedio": 0,
        }
        plot_rows = rows[:top_n] + [other]
    else:
        plot_rows = rows

    width = 1400
    left = 395
    top = 100
    row_h = 35
    bar_w = 760
    height = top + row_h * len(plot_rows) + 90
    max_pct = max(100 * as_float(r["n_xy"]) / total_xy for r in plot_rows)
    parts = []
    parts.append(text(left, top - 20, "% de grupos XY", 12, "#697276"))
    for tick in [0, 10, 20, 30, 40, 50]:
        x = left + bar_w * tick / 50
        parts.append(f'<line x1="{x}" y1="{top-10}" x2="{x}" y2="{height-76}" class="grid"/>')
        parts.append(text(x, height - 54, f"{tick}%", 11, "#697276", 400, "middle"))

    cumulative = 0.0
    line_points = []
    for i, row in enumerate(plot_rows):
        y = top + i * row_h
        source_key = str(row["fuente"]).lower()
        label = source_display.get(source_key, row["fuente"])
        pct = 100 * as_float(row["n_xy"]) / total_xy
        cumulative += pct
        w = bar_w * pct / 50
        color = "#2E7D59" if i < 5 else "#7E8B8D"
        if row["fuente"] == "Otras fuentes":
            color = "#BFC7C8"
        parts.append(wrapped_text(left - 18, y + 14, compact_source(label, 58), 54, 11, "#263238", "end", 12, 500))
        parts.append(f'<rect x="{left}" y="{y}" width="{w:.2f}" height="18" rx="5" fill="{color}"/>')
        parts.append(text(left + w + 8, y + 14, fmt_pct(pct, 1), 11, "#263238", 700))
        cx = left + bar_w * min(cumulative, 100) / 100
        cy = y + 9
        line_points.append((cx, cy, min(cumulative, 100)))

    if len(line_points) > 1:
        d = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y, _ in line_points)
        parts.append(f'<path d="{d}" fill="none" stroke="#C65F3D" stroke-width="2.5"/>')
    for cx, cy, cumulative_pct in line_points:
        label = f"{cumulative_pct:.0f}%"
        label_w = 34 if cumulative_pct < 100 else 42
        label_x = min(cx + 9, width - label_w - 28)
        parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="4" fill="#C65F3D" stroke="#FFFFFF" stroke-width="1.5"/>')
        parts.append(
            f'<rect x="{label_x:.2f}" y="{cy - 10:.2f}" width="{label_w}" height="18" '
            f'rx="6" fill="#FFFFFF" stroke="#C65F3D" stroke-width="1" opacity="0.96"/>'
        )
        parts.append(text(label_x + label_w / 2, cy + 4, label, 10, "#A94831", 700, "middle"))
    parts.append(text(left + bar_w + 22, top - 20, "Línea roja = acumulado", 12, "#C65F3D", 600))
    subtitle = "Las cinco fuentes principales explican 88.4% de los grupos XY."
    return svg_shell(width, height, "Pareto de fuentes dominantes", subtitle, "\n".join(parts))


def chart_regional_l1_xy(level1_summary: list[dict]) -> str:
    rows = sorted(level1_summary, key=lambda r: as_float(r["n_xy"]))
    width = 1400
    height = 620
    left = 320
    top = 108
    bar_w = 820
    bar_h = 26
    row_h = 40
    legend_x = 1185
    plot_h = row_h * len(rows)
    max_value = max(as_float(r["n_xy"]) for r in rows)
    tick_step = 100_000
    x_max = math.ceil(max_value / tick_step) * tick_step
    parts = []

    parts.append(
        f'<rect x="{left}" y="{top - 16}" width="{bar_w}" height="{plot_h + 22}" '
        f'rx="8" fill="#EEF3F8"/>'
    )
    for tick in range(0, int(x_max) + tick_step, tick_step):
        x = left + bar_w * tick / x_max
        parts.append(f'<line x1="{x:.2f}" y1="{top - 16}" x2="{x:.2f}" y2="{top + plot_h + 6}" stroke="#FFFFFF" stroke-width="2"/>')
        label = "0" if tick == 0 else f"{tick // 1000}k"
        parts.append(text(x, top + plot_h + 36, label, 12, "#536173", 500, "middle"))

    for i, row in enumerate(rows):
        y = top + i * row_h
        class_id = as_int(row["id_1_propuesta"])
        label = display_class(row["nivel_1_propuesta"])
        value = as_float(row["n_xy"])
        w = bar_w * value / x_max if x_max else 0
        color = TARGET_COLORS.get(class_id, "#7A7A7A")
        parts.append(text(left - 10, y + 18, label, 15, "#334155", 600, "end"))
        parts.append(
            f'<rect x="{left}" y="{y}" width="{w:.2f}" height="{bar_h}" '
            f'rx="4" fill="{color}"/>'
        )
        value_x = min(left + w + 10, left + bar_w - 48)
        fill = "#FFFFFF" if w > bar_w * 0.82 else "#334155"
        anchor = "end" if w > bar_w * 0.82 else "start"
        if anchor == "end":
            value_x = left + w - 10
        parts.append(text(value_x, y + 18, fmt_num(value), 12, fill, 700, anchor))

    parts.append(text(left + bar_w / 2, height - 42, "Cantidad de grupos XY únicos", 15, "#334155", 600, "middle"))
    parts.append(text(42, top + plot_h / 2, "Clase homologada", 15, "#334155", 600, "middle", f'transform="rotate(-90 42 {top + plot_h / 2:.2f})"'))

    parts.append(text(legend_x, top + 2, "Clase homologada", 15, "#334155", 700))
    for i, row in enumerate(rows):
        y = top + 34 + i * 30
        class_id = as_int(row["id_1_propuesta"])
        label = display_class(row["nivel_1_propuesta"])
        color = TARGET_COLORS.get(class_id, "#7A7A7A")
        parts.append(f'<rect x="{legend_x}" y="{y}" width="16" height="16" rx="3" fill="{color}"/>')
        parts.append(text(legend_x + 24, y + 13, label, 13, "#334155", 500))

    subtitle = "Conteo regional por clase homologada final de nivel 1; usa nXY para mantener comparabilidad con los heatmaps y diagnósticos de vacíos."
    return svg_shell(
        width,
        height,
        "Nivel 1 homologado: grupos XY regionales por clase",
        subtitle,
        "\n".join(parts),
    )


def chart_slide_l0_l1(country_rows: list[dict], country_l0: list[dict], level1_summary: list[dict]) -> str:
    """Figura compuesta 16:9 para una lámina de presentación."""
    width = 1600
    height = 660
    parts = []

    # Panel izquierdo: balance nivel 0 por país.
    left_panel_x = 54
    left_panel_y = 48
    left_panel_w = 710
    panel_h = 570
    parts.append(
        f'<rect x="{left_panel_x}" y="{left_panel_y}" width="{left_panel_w}" '
        f'height="{panel_h}" rx="10" fill="#FFFFFF" stroke="#DDE3E2"/>'
    )
    parts.append(text(left_panel_x + 24, left_panel_y + 36, "Balance país por nivel 0", 18, "#172326", 800))
    parts.append(text(left_panel_x + 24, left_panel_y + 60, "% dentro de cada país; etiqueta derecha = nXY", 12, "#697276", 500))

    countries = [row["pais"] for row in country_rows]
    totals = {row["pais"]: as_float(row["n_xy"]) for row in country_rows}
    by_country: dict[str, dict[str, float]] = defaultdict(dict)
    for row in country_l0:
        by_country[row["pais"]][row["nivel_0_propuesta"]] = as_float(row["n_xy"])

    bar_x = left_panel_x + 142
    bar_y = left_panel_y + 92
    bar_w = 420
    bar_h = 24
    row_h = 46
    for i, pais in enumerate(countries):
        y = bar_y + i * row_h
        total = totals[pais]
        parts.append(text(bar_x - 14, y + 17, display_country(pais), 13, "#263238", 650, "end"))
        parts.append(f'<rect x="{bar_x}" y="{y}" width="{bar_w}" height="{bar_h}" rx="5" fill="#EEF1F0"/>')
        x = bar_x
        for level in ["bosques/tierras forestales", "no bosques"]:
            value = by_country[pais].get(level, 0.0)
            w = bar_w * value / total if total else 0
            parts.append(
                f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="{bar_h}" '
                f'fill="{LEVEL0_COLORS[level]}"/>'
            )
            if w > 52:
                parts.append(text(x + w / 2, y + 16, f"{100 * value / total:.0f}%", 11, "#FFFFFF", 800, "middle"))
            x += w
        parts.append(text(bar_x + bar_w + 18, y + 17, fmt_num(total), 12, "#37474F", 700))

    legend_y = bar_y + row_h * len(countries) + 22
    legend_x = left_panel_x + 24
    for label, color in [
        ("Bosques / tierras forestales", LEVEL0_COLORS["bosques/tierras forestales"]),
        ("No bosques", LEVEL0_COLORS["no bosques"]),
    ]:
        parts.append(f'<rect x="{legend_x}" y="{legend_y}" width="16" height="16" rx="3" fill="{color}"/>')
        parts.append(text(legend_x + 24, legend_y + 13, label, 12, "#37474F", 600))
        legend_x += 250

    # Panel derecho: volumen regional por clase homologada nivel 1.
    right_panel_x = 810
    right_panel_y = left_panel_y
    right_panel_w = 736
    parts.append(
        f'<rect x="{right_panel_x}" y="{right_panel_y}" width="{right_panel_w}" '
        f'height="{panel_h}" rx="10" fill="#FFFFFF" stroke="#DDE3E2"/>'
    )
    parts.append(text(right_panel_x + 24, right_panel_y + 36, "Nivel 1 homologado regional", 18, "#172326", 800))
    parts.append(text(right_panel_x + 24, right_panel_y + 60, "Cantidad de grupos XY únicos por clase", 12, "#697276", 500))

    rows = sorted(level1_summary, key=lambda row: as_float(row["n_xy"]))
    class_label_x = right_panel_x + 252
    rbar_x = right_panel_x + 272
    rbar_y = right_panel_y + 94
    rbar_w = 390
    rbar_h = 22
    rrow_h = 40
    max_value = max(as_float(row["n_xy"]) for row in rows)
    tick_step = 100_000
    x_max = math.ceil(max_value / tick_step) * tick_step

    parts.append(
        f'<rect x="{rbar_x}" y="{rbar_y - 16}" width="{rbar_w}" '
        f'height="{rrow_h * len(rows) + 18}" rx="8" fill="#EEF3F8"/>'
    )
    for tick in range(0, int(x_max) + tick_step, tick_step):
        x = rbar_x + rbar_w * tick / x_max
        parts.append(f'<line x1="{x:.2f}" y1="{rbar_y - 16}" x2="{x:.2f}" y2="{rbar_y + rrow_h * len(rows) + 2}" stroke="#FFFFFF" stroke-width="2"/>')
        label = "0" if tick == 0 else f"{tick // 1000}k"
        parts.append(text(x, rbar_y + rrow_h * len(rows) + 32, label, 11, "#536173", 600, "middle"))

    for i, row in enumerate(rows):
        y = rbar_y + i * rrow_h
        class_id = as_int(row["id_1_propuesta"])
        label = display_class(row["nivel_1_propuesta"])
        value = as_float(row["n_xy"])
        w = rbar_w * value / x_max if x_max else 0
        color = TARGET_COLORS.get(class_id, "#7A7A7A")
        parts.append(text(class_label_x, y + 17, label, 12, "#334155", 650, "end"))
        parts.append(f'<rect x="{rbar_x}" y="{y}" width="{w:.2f}" height="{rbar_h}" rx="4" fill="{color}"/>')
        value_x = rbar_x + w + 8
        anchor = "start"
        fill = "#334155"
        if value_x > rbar_x + rbar_w - 48:
            value_x = rbar_x + w - 10
            anchor = "end"
            fill = "#FFFFFF"
        parts.append(text(value_x, y + 17, fmt_num(value), 11, fill, 800, anchor))

    return svg_shell(width, height, "", "", "\n".join(parts))


def chart_use_by_country(country_rows: list[dict], use_rows: list[dict]) -> str:
    countries = [r["pais"] for r in country_rows]
    totals = {r["pais"]: as_float(r["n_xy"]) for r in country_rows}
    by_country: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in use_rows:
        by_country[row["pais"]][row["categoria_uso_actividad_1_8"]] += as_float(row["n_xy"])

    order = [
        "entrenamiento",
        "validación",
        "apoyo interpretativo",
        "referencia contextual",
        "máscaras",
        "prueba",
    ]
    width = 1280
    left = 210
    top = 108
    bar_w = 790
    row_h = 40
    height = top + row_h * len(countries) + 115
    parts = []
    for tick in [0, 25, 50, 75, 100]:
        x = left + bar_w * tick / 100
        parts.append(f'<line x1="{x}" y1="{top-12}" x2="{x}" y2="{height-88}" class="grid"/>')
        parts.append(text(x, height - 68, f"{tick}%", 11, "#697276", 400, "middle"))

    for i, pais in enumerate(countries):
        y = top + i * row_h
        parts.append(text(left - 16, y + 16, display_country(pais), 12, "#263238", 600, "end"))
        x = left
        for uso in order:
            val = by_country[pais].get(uso, 0.0)
            w = bar_w * val / totals[pais] if totals[pais] else 0
            if w <= 0:
                continue
            parts.append(
                f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="22" fill="{USE_COLORS[uso]}"/>'
            )
            if w > 60:
                parts.append(text(x + w / 2, y + 15, f"{100*val/totals[pais]:.0f}%", 11, "#FFFFFF", 700, "middle"))
            x += w
        parts.append(text(left + bar_w + 16, y + 16, fmt_num(totals[pais]), 11, "#697276", 600))

    lx = left
    ly = height - 38
    for uso in order[:5]:
        parts.append(f'<rect x="{lx}" y="{ly}" width="14" height="14" rx="3" fill="{USE_COLORS[uso]}"/>')
        parts.append(text(lx + 21, ly + 12, uso.capitalize(), 12, "#37474F"))
        lx += 175 if uso != "apoyo interpretativo" else 210
    subtitle = "Composición de uso final A1.8 por país; etiqueta derecha = grupos XY."
    return svg_shell(width, height, "Uso homologado A1.8 por país", subtitle, "\n".join(parts))


def chart_score_intervals(score_stats: list[dict]) -> str:
    rows = sorted(score_stats, key=lambda r: as_float(r["median"]), reverse=True)
    width = 1180
    left = 190
    right = 1060
    top = 105
    row_h = 42
    height = top + row_h * len(rows) + 88
    min_s, max_s = 40.0, 100.0

    def sx(v: float) -> float:
        return left + (right - left) * (v - min_s) / (max_s - min_s)

    parts = []
    for tick in [40, 50, 60, 70, 80, 90, 100]:
        x = sx(tick)
        parts.append(f'<line x1="{x}" y1="{top-18}" x2="{x}" y2="{height-70}" class="grid"/>')
        parts.append(text(x, height - 48, tick, 11, "#697276", 400, "middle"))
    parts.append(text(right + 10, height - 48, "score", 11, "#697276"))

    for i, row in enumerate(rows):
        y = top + i * row_h
        parts.append(text(left - 18, y + 13, display_country(row["pais"]), 12, "#263238", 600, "end"))
        p10, p25, med, p75, p90 = [as_float(row[k]) for k in ["p10", "p25", "median", "p75", "p90"]]
        mean = as_float(row["mean"])
        parts.append(f'<line x1="{sx(p10):.2f}" y1="{y+9}" x2="{sx(p90):.2f}" y2="{y+9}" stroke="#AAB4B7" stroke-width="3" stroke-linecap="round"/>')
        parts.append(f'<line x1="{sx(p25):.2f}" y1="{y+9}" x2="{sx(p75):.2f}" y2="{y+9}" stroke="#2E7D59" stroke-width="10" stroke-linecap="round"/>')
        parts.append(f'<circle cx="{sx(med):.2f}" cy="{y+9}" r="5" fill="#172326"/>')
        mx = sx(mean)
        parts.append(
            f'<path d="M {mx:.2f} {y+2} L {mx+7:.2f} {y+9} L {mx:.2f} {y+16} L {mx-7:.2f} {y+9} Z" fill="#D2923A"/>'
        )
        parts.append(text(right + 18, y + 13, f"med {med:.1f}", 11, "#263238", 600))
    subtitle = "Línea gris = p10-p90; barra verde = p25-p75; punto = mediana; rombo = promedio."
    return svg_shell(width, height, "Distribución de score de aptitud por país", subtitle, "\n".join(parts))


def chart_bubble_country(country_rows: list[dict]) -> str:
    rows = list(country_rows)
    width = 1180
    height = 640
    left = 120
    right = 1080
    top = 90
    bottom = 535
    min_log = min(math.log10(max(1, as_float(r["n_xy"]))) for r in rows)
    max_log = max(math.log10(max(1, as_float(r["n_xy"]))) for r in rows)
    min_y, max_y = 78.0, 98.0

    def sx(n: float) -> float:
        value = math.log10(max(1.0, n))
        return left + (right - left) * (value - min_log) / (max_log - min_log)

    def sy(score: float) -> float:
        return bottom - (bottom - top) * (score - min_y) / (max_y - min_y)

    parts = []
    for tick in [10, 100, 1000, 10000, 100000, 1000000]:
        if math.log10(tick) < min_log or math.log10(tick) > max_log:
            continue
        x = sx(tick)
        parts.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{bottom}" class="grid"/>')
        parts.append(text(x, bottom + 28, fmt_num(tick), 11, "#697276", 400, "middle"))
    for tick in [80, 85, 90, 95]:
        y = sy(tick)
        parts.append(f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" class="grid"/>')
        parts.append(text(left - 16, y + 4, tick, 11, "#697276", 400, "end"))
    parts.append(text((left + right) / 2, height - 34, "Volumen de grupos XY (escala logarítmica)", 12, "#697276", 500, "middle"))
    parts.append(text(34, (top + bottom) / 2, "Score promedio", 12, "#697276", 500, "middle", 'transform="rotate(-90 34 312)"'))

    for row in rows:
        n_xy = as_float(row["n_xy"])
        score = as_float(row["score_promedio"])
        pct_train = as_float(row["pct_entrenamiento"])
        pct_forest = as_float(row["pct_bosques"])
        radius = 7 + 22 * pct_train / 100
        color = blend("#D2923A", "#246B4B", pct_forest / 75)
        x, y = sx(n_xy), sy(score)
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{color}" opacity="0.82" stroke="#FFFFFF" stroke-width="2"/>')
        dx = 10 if display_country(row["pais"]) not in {"El Salvador", "Guatemala"} else -10
        anchor = "start" if dx > 0 else "end"
        parts.append(text(x + dx, y - radius - 4, display_country(row["pais"]), 12, "#263238", 700, anchor))
    subtitle = "Tamaño = % entrenamiento; color ámbar-verde = menor/mayor proporción de bosques."
    return svg_shell(width, height, "Volumen, aptitud y balance forestal por país", subtitle, "\n".join(parts))


def gap_status(row: dict) -> str:
    if str(row.get("flag_sin_puntos", "")).lower() == "true":
        return "sin puntos"
    if str(row.get("flag_baja_cantidad", "")).lower() == "true":
        return "baja cantidad"
    if str(row.get("flag_score_bajo", "")).lower() == "true":
        return "score bajo"
    return "cumple umbral operativo"


def chart_gap_heatmap(gap_rows: list[dict], gap_country: list[dict], gap_class: list[dict]) -> str:
    country_order = [r["pais"] for r in gap_country]
    class_order = [r["clase"] for r in gap_class]
    matrix = {(r["pais"], r["clase"]): gap_status(r) for r in gap_rows}
    cell_w = 104
    cell_h = 34
    left = 122
    top = 178
    width = left + cell_w * len(class_order) + 50
    height = top + cell_h * len(country_order) + 136
    parts = []
    for j, cls in enumerate(class_order):
        label = re.sub(r"^\d+\s+", "", cls)
        x = left + j * cell_w + cell_w / 2
        lines = wrap_text_lines(label, 13)[:3]
        for k, line in enumerate(lines):
            parts.append(text(x, 96 + k * 13, line, 10, "#475258", 600, "middle"))
        code = cls.split()[0] if cls else ""
        parts.append(text(x, 153, code, 10, "#697276", 600, "middle"))

    marks = {
        "sin puntos": "0",
        "baja cantidad": "n",
        "score bajo": "s",
        "cumple umbral operativo": "",
    }
    for i, pais in enumerate(country_order):
        y = top + i * cell_h
        parts.append(text(left - 14, y + 21, pais, 12, "#263238", 600, "end"))
        for j, cls in enumerate(class_order):
            x = left + j * cell_w
            status = matrix.get((pais, cls), "cumple umbral operativo")
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell_w - 2}" height="{cell_h - 2}" rx="4" fill="{GAP_COLORS[status]}"/>'
            )
            mark = marks[status]
            if mark:
                parts.append(text(x + cell_w / 2, y + 21, mark, 13, "#FFFFFF", 800, "middle"))

    lx = left
    ly = height - 78
    legend = [
        ("sin puntos", "Sin puntos"),
        ("baja cantidad", "Baja cantidad"),
        ("score bajo", "Score bajo"),
        ("cumple umbral operativo", "Cumple umbral operativo"),
    ]
    for status, label in legend:
        parts.append(f'<rect x="{lx}" y="{ly}" width="16" height="16" rx="3" fill="{GAP_COLORS[status]}"/>')
        parts.append(text(lx + 24, ly + 13, label, 12, "#37474F"))
        lx += 160
    parts.append(
        text(
            left,
            height - 35,
            "Cumple umbral operativo = nXY >= 200 y score medio >= 80. No implica balance espacial, independencia entre fuentes ni suficiencia para modelado sin estratificación.",
            12,
            "#697276",
            500,
        )
    )
    subtitle = "Estado por país y clase original nivel 1. Los umbrales indican cobertura mínima operativa, no aptitud final para modelado."
    return svg_shell(width, height, "Vacíos y alertas país x clase", subtitle, "\n".join(parts))


def chart_alluvial(mapping_rows: list[dict]) -> str:
    left_nodes: dict[int, dict] = {}
    right_nodes: dict[int, dict] = {}
    total = sum(as_float(r["n_xy"]) for r in mapping_rows)
    for row in mapping_rows:
        oid = as_int(row["id_1"])
        tid = as_int(row["id_1_propuesta"])
        left_nodes.setdefault(oid, {"id": oid, "name": row["nivel_1"], "n": 0.0})
        right_nodes.setdefault(tid, {"id": tid, "name": display_class(row["nivel_1_propuesta"]), "n": 0.0})
        left_nodes[oid]["n"] += as_float(row["n_xy"])
        right_nodes[tid]["n"] += as_float(row["n_xy"])

    left_list = sorted(left_nodes.values(), key=lambda r: r["n"], reverse=True)
    right_list = sorted(right_nodes.values(), key=lambda r: r["n"], reverse=True)
    width = 1360
    height = 760
    left_x = 275
    right_x = 1060
    top = 105
    bottom = 680
    left_pos = {}
    right_pos = {}
    for i, node in enumerate(left_list):
        y = top + i * ((bottom - top) / max(1, len(left_list) - 1))
        left_pos[node["id"]] = y
    for i, node in enumerate(right_list):
        y = top + i * ((bottom - top) / max(1, len(right_list) - 1))
        right_pos[node["id"]] = y

    max_link = max(as_float(r["n_xy"]) for r in mapping_rows)
    parts = []
    parts.append(text(left_x, 85, "Leyenda original nivel 1", 13, "#697276", 700, "end"))
    parts.append(text(right_x, 85, "Leyenda homologada nivel 1", 13, "#697276", 700))

    for row in sorted(mapping_rows, key=lambda r: as_float(r["n_xy"]), reverse=True):
        oid = as_int(row["id_1"])
        tid = as_int(row["id_1_propuesta"])
        y1, y2 = left_pos[oid], right_pos[tid]
        sw = max(1.4, 26 * math.sqrt(as_float(row["n_xy"]) / max_link))
        color = TARGET_COLORS.get(tid, "#7A7A7A")
        d = f"M {left_x + 22} {y1:.2f} C 560 {y1:.2f}, 760 {y2:.2f}, {right_x - 22} {y2:.2f}"
        parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw:.2f}" stroke-opacity="0.28" stroke-linecap="round"/>')

    for node in left_list:
        y = left_pos[node["id"]]
        parts.append(f'<circle cx="{left_x}" cy="{y}" r="6" fill="#263238"/>')
        parts.append(wrapped_text(left_x - 12, y - 3, f'{node["id"]} {node["name"]}', 30, 11, "#263238", "end", 12, 600))
        parts.append(text(left_x - 12, y + 23, fmt_pct(100 * node["n"] / total, 1), 10, "#697276", 400, "end"))

    for node in right_list:
        y = right_pos[node["id"]]
        color = TARGET_COLORS.get(node["id"], "#7A7A7A")
        parts.append(f'<circle cx="{right_x}" cy="{y}" r="7" fill="{color}"/>')
        parts.append(wrapped_text(right_x + 14, y - 3, f'{node["id"]} {node["name"]}', 31, 11, "#263238", "start", 12, 700))
        parts.append(text(right_x + 14, y + 23, f'{fmt_num(node["n"])} XY · {fmt_pct(100 * node["n"] / total, 1)}', 10, "#697276"))

    subtitle = "Flujos finales origen -> propuesta; ancho proporcional a raíz cuadrada de n para hacer visibles clases menores."
    return svg_shell(width, height, "Homologación de clases: origen a propuesta", subtitle, "\n".join(parts))


def compute_score_stats() -> list[dict]:
    values: dict[str, list[float]] = defaultdict(list)
    for row in stream_sql(
        """
        SELECT c.pais_dominante AS pais, s.score_aptitud_total AS score
        FROM xy_core c
        JOIN xy_score s USING (xy_group_id)
        """
    ):
        values[row["pais"]].append(as_float(row["score"]))

    stats = []
    for pais, scores in values.items():
        scores.sort()
        stats.append(
            {
                "pais": pais,
                "n": len(scores),
                "mean": sum(scores) / len(scores),
                "p10": quantile(scores, 0.10),
                "p25": quantile(scores, 0.25),
                "median": quantile(scores, 0.50),
                "p75": quantile(scores, 0.75),
                "p90": quantile(scores, 0.90),
            }
        )
    return stats


def load_source_display() -> dict[str, str]:
    if not SOURCE_RANKING.exists():
        return {}
    out = {}
    for row in read_csv(SOURCE_RANKING):
        out[str(row.get("fuente", "")).lower()] = row.get("fuente", "")
    return out


def build_data() -> dict:
    total = sql_rows(
        """
        SELECT
          COUNT(*) AS n_xy,
          SUM(c.n_registros) AS n_registros,
          COUNT(DISTINCT c.pais_dominante) AS n_paises,
          COUNT(DISTINCT c.fuente_dominante) AS n_fuentes,
          SUM(CASE WHEN h.id_1_propuesta IS NULL THEN 1 ELSE 0 END) AS sin_homologacion,
          AVG(s.score_aptitud_total) AS score_promedio,
          MIN(s.score_aptitud_total) AS score_min,
          MAX(s.score_aptitud_total) AS score_max
        FROM xy_core c
        LEFT JOIN xy_homologacion_final h USING (xy_group_id)
        LEFT JOIN xy_score s USING (xy_group_id)
        """
    )[0]

    country_rows = sql_rows(
        """
        SELECT
          c.pais_dominante AS pais,
          COUNT(*) AS n_xy,
          100.0 * COUNT(*) / (SELECT COUNT(*) FROM xy_core) AS pct_xy,
          SUM(c.n_registros) AS n_registros,
          COUNT(DISTINCT c.fuente_dominante) AS n_fuentes,
          AVG(s.score_aptitud_total) AS score_promedio,
          SUM(CASE WHEN a.categoria_uso_actividad_1_8='entrenamiento' THEN 1 ELSE 0 END) AS n_entrenamiento,
          100.0 * SUM(CASE WHEN a.categoria_uso_actividad_1_8='entrenamiento' THEN 1 ELSE 0 END) / COUNT(*) AS pct_entrenamiento,
          SUM(CASE WHEN a.categoria_uso_actividad_1_8='validación' THEN 1 ELSE 0 END) AS n_validacion,
          100.0 * SUM(CASE WHEN a.categoria_uso_actividad_1_8='validación' THEN 1 ELSE 0 END) / COUNT(*) AS pct_validacion,
          SUM(CASE WHEN a.categoria_uso_actividad_1_8 NOT IN ('entrenamiento','validación','prueba') THEN 1 ELSE 0 END) AS n_no_uso_directo,
          100.0 * SUM(CASE WHEN a.categoria_uso_actividad_1_8 NOT IN ('entrenamiento','validación','prueba') THEN 1 ELSE 0 END) / COUNT(*) AS pct_no_uso_directo,
          SUM(CASE WHEN h.id_0_propuesta=1 THEN 1 ELSE 0 END) AS n_bosques,
          100.0 * SUM(CASE WHEN h.id_0_propuesta=1 THEN 1 ELSE 0 END) / COUNT(*) AS pct_bosques,
          SUM(CASE WHEN h.id_0_propuesta=2 THEN 1 ELSE 0 END) AS n_no_bosques,
          100.0 * SUM(CASE WHEN h.id_0_propuesta=2 THEN 1 ELSE 0 END) / COUNT(*) AS pct_no_bosques
        FROM xy_core c
        JOIN xy_homologacion_final h USING (xy_group_id)
        JOIN xy_score s USING (xy_group_id)
        JOIN xy_accion a USING (xy_group_id)
        GROUP BY c.pais_dominante
        ORDER BY n_xy DESC
        """
    )

    country_l0 = sql_rows(
        """
        SELECT
          c.pais_dominante AS pais,
          h.id_0_propuesta,
          h.nivel_0_propuesta,
          COUNT(*) AS n_xy
        FROM xy_core c
        JOIN xy_homologacion_final h USING (xy_group_id)
        GROUP BY c.pais_dominante, h.id_0_propuesta, h.nivel_0_propuesta
        """
    )

    country_l1 = sql_rows(
        """
        SELECT
          c.pais_dominante AS pais,
          h.id_1_propuesta,
          h.nivel_1_propuesta,
          COUNT(*) AS n_xy
        FROM xy_core c
        JOIN xy_homologacion_final h USING (xy_group_id)
        GROUP BY c.pais_dominante, h.id_1_propuesta, h.nivel_1_propuesta
        """
    )

    level1_summary = sql_rows(
        """
        SELECT
          h.id_1_propuesta,
          h.nivel_1_propuesta,
          COUNT(*) AS n_xy,
          100.0 * COUNT(*) / (SELECT COUNT(*) FROM xy_core) AS pct_xy,
          SUM(c.n_registros) AS n_registros,
          AVG(s.score_aptitud_total) AS score_promedio,
          COUNT(DISTINCT c.pais_dominante) AS n_paises,
          COUNT(DISTINCT c.fuente_dominante) AS n_fuentes
        FROM xy_core c
        JOIN xy_homologacion_final h USING (xy_group_id)
        JOIN xy_score s USING (xy_group_id)
        GROUP BY h.id_1_propuesta, h.nivel_1_propuesta
        ORDER BY n_xy DESC
        """
    )

    use_rows = sql_rows(
        """
        SELECT
          c.pais_dominante AS pais,
          a.categoria_uso_actividad_1_8,
          COUNT(*) AS n_xy
        FROM xy_core c
        JOIN xy_accion a USING (xy_group_id)
        GROUP BY c.pais_dominante, a.categoria_uso_actividad_1_8
        """
    )

    use_summary = sql_rows(
        """
        SELECT
          a.categoria_uso_actividad_1_8,
          COUNT(*) AS n_xy,
          100.0 * COUNT(*) / (SELECT COUNT(*) FROM xy_core) AS pct_xy,
          AVG(s.score_aptitud_total) AS score_promedio
        FROM xy_accion a
        JOIN xy_score s USING (xy_group_id)
        GROUP BY a.categoria_uso_actividad_1_8
        ORDER BY n_xy DESC
        """
    )

    source_rows = sql_rows(
        """
        SELECT
          c.fuente_dominante AS fuente,
          COUNT(*) AS n_xy,
          100.0 * COUNT(*) / (SELECT COUNT(*) FROM xy_core) AS pct_xy,
          SUM(c.n_registros) AS n_registros,
          COUNT(DISTINCT c.pais_dominante) AS n_paises,
          AVG(s.score_aptitud_total) AS score_promedio,
          SUM(CASE WHEN a.categoria_uso_actividad_1_8='entrenamiento' THEN 1 ELSE 0 END) AS n_entrenamiento,
          100.0 * SUM(CASE WHEN a.categoria_uso_actividad_1_8='entrenamiento' THEN 1 ELSE 0 END) / COUNT(*) AS pct_entrenamiento,
          SUM(CASE WHEN h.id_0_propuesta=1 THEN 1 ELSE 0 END) AS n_bosques,
          100.0 * SUM(CASE WHEN h.id_0_propuesta=1 THEN 1 ELSE 0 END) / COUNT(*) AS pct_bosques
        FROM xy_core c
        JOIN xy_homologacion_final h USING (xy_group_id)
        JOIN xy_score s USING (xy_group_id)
        JOIN xy_accion a USING (xy_group_id)
        GROUP BY c.fuente_dominante
        ORDER BY n_xy DESC
        """
    )

    mapping_rows = sql_rows(
        """
        SELECT
          p.id_1,
          o.nivel_1,
          h.id_1_propuesta,
          h.nivel_1_propuesta,
          COUNT(*) AS n_xy
        FROM xy_point p
        JOIN clase_origen_nivel_1 o ON p.id_1 = o.id_1
        JOIN xy_homologacion_final h USING (xy_group_id)
        GROUP BY p.id_1, o.nivel_1, h.id_1_propuesta, h.nivel_1_propuesta
        ORDER BY n_xy DESC
        """
    )

    print("Calculando percentiles de score por país...")
    score_stats = compute_score_stats()

    return {
        "total": total,
        "country_rows": country_rows,
        "country_l0": country_l0,
        "country_l1": country_l1,
        "level1_summary": level1_summary,
        "use_rows": use_rows,
        "use_summary": use_summary,
        "source_rows": source_rows,
        "mapping_rows": mapping_rows,
        "score_stats": score_stats,
        "source_display": load_source_display(),
        "gap_rows": read_csv(GAP_INTEGRATED_L1),
        "gap_country": read_csv(GAP_COUNTRY_L1),
        "gap_class": read_csv(GAP_CLASS_L1),
    }


def export_tables(data: dict) -> None:
    write_csv(
        TABLE_DIR / "resumen_pais_homologacion.csv",
        data["country_rows"],
        [
            "pais",
            "n_xy",
            "pct_xy",
            "n_registros",
            "n_fuentes",
            "score_promedio",
            "pct_entrenamiento",
            "pct_validacion",
            "pct_no_uso_directo",
            "pct_bosques",
            "pct_no_bosques",
        ],
    )
    write_csv(
        TABLE_DIR / "resumen_clase_nivel1_homologada.csv",
        data["level1_summary"],
        [
            "id_1_propuesta",
            "nivel_1_propuesta",
            "n_xy",
            "pct_xy",
            "n_registros",
            "score_promedio",
            "n_paises",
            "n_fuentes",
        ],
    )
    write_csv(
        TABLE_DIR / "resumen_fuentes_dominantes.csv",
        data["source_rows"],
        [
            "fuente",
            "n_xy",
            "pct_xy",
            "n_registros",
            "n_paises",
            "score_promedio",
            "pct_entrenamiento",
            "pct_bosques",
        ],
    )
    write_csv(
        TABLE_DIR / "resumen_uso_a1_8.csv",
        data["use_summary"],
        ["categoria_uso_actividad_1_8", "n_xy", "pct_xy", "score_promedio"],
    )
    write_csv(
        TABLE_DIR / "percentiles_score_pais.csv",
        data["score_stats"],
        ["pais", "n", "mean", "p10", "p25", "median", "p75", "p90"],
    )


def build_figures(data: dict) -> dict[str, str]:
    total_xy = as_float(data["total"]["n_xy"])
    figures = {
        "00_lamina_balance_pais_clases.svg": chart_slide_l0_l1(
            data["country_rows"], data["country_l0"], data["level1_summary"]
        ),
        "01_balance_pais_nivel0.svg": chart_stacked_country_l0(
            data["country_rows"], data["country_l0"]
        ),
        "02_heatmap_pais_clase_nivel1.svg": chart_heatmap_country_l1(
            data["country_rows"], data["country_l1"]
        ),
        "03_pareto_fuentes.svg": chart_pareto_sources(
            data["source_rows"], data["source_display"], total_xy
        ),
        "04_uso_a18_por_pais.svg": chart_use_by_country(
            data["country_rows"], data["use_rows"]
        ),
        "05_score_por_pais.svg": chart_score_intervals(data["score_stats"]),
        "06_burbujas_volumen_score_pais.svg": chart_bubble_country(data["country_rows"]),
        "07_heatmap_vacios_pais_clase.svg": chart_gap_heatmap(
            data["gap_rows"], data["gap_country"], data["gap_class"]
        ),
        "08_alluvial_homologacion_nivel1.svg": chart_alluvial(data["mapping_rows"]),
        "09_grupos_xy_regionales_nivel1.svg": chart_regional_l1_xy(
            data["level1_summary"]
        ),
    }
    for filename, svg in figures.items():
        save_text(FIG_DIR / filename, svg)
    return figures


def metric_card(label: str, value: str, note: str = "") -> str:
    return f"""
    <div class="metric">
      <div class="metric-label">{esc(label)}</div>
      <div class="metric-value">{esc(value)}</div>
      <div class="metric-note">{esc(note)}</div>
    </div>
    """


def build_dashboard(data: dict, figures: dict[str, str]) -> str:
    total = data["total"]
    top_sources = sorted(data["source_rows"], key=lambda r: as_float(r["n_xy"]), reverse=True)
    top5_pct = sum(as_float(r["n_xy"]) for r in top_sources[:5]) / as_float(total["n_xy"]) * 100
    no_bosques = next(
        (r for r in sql_rows(
            """
            SELECT h.nivel_0_propuesta, COUNT(*) AS n_xy
            FROM xy_homologacion_final h
            GROUP BY h.nivel_0_propuesta
            """
        ) if r["nivel_0_propuesta"] == "no bosques"),
        {"n_xy": 0},
    )
    no_bosques_pct = 100 * as_float(no_bosques["n_xy"]) / as_float(total["n_xy"])
    train = next((r for r in data["use_summary"] if r["categoria_uso_actividad_1_8"] == "entrenamiento"), {})
    valid = next((r for r in data["use_summary"] if r["categoria_uso_actividad_1_8"] == "validación"), {})

    cards = "\n".join(
        [
            metric_card("Grupos XY", fmt_num(total["n_xy"]), "Base A2.1 homologada"),
            metric_card("Registros representados", fmt_num(total["n_registros"]), "Desde A1 scoring"),
            metric_card("Sin homologación", fmt_num(total["sin_homologacion"]), "Debe permanecer en cero"),
            metric_card("Score promedio", fmt_num(total["score_promedio"], 2), "Aptitud multicriterio"),
            metric_card("No bosques", fmt_pct(no_bosques_pct, 1), "Nivel 0 final"),
            metric_card("Entrenamiento", fmt_pct(train.get("pct_xy", 0), 1), "Uso A1.8"),
            metric_card("Validación", fmt_pct(valid.get("pct_xy", 0), 1), "Uso A1.8"),
            metric_card("Top 5 fuentes", fmt_pct(top5_pct, 1), "Concentración por fuente"),
        ]
    )

    figure_order = [
        ("00_lamina_balance_pais_clases.svg", "Lámina síntesis: país y clases"),
        ("01_balance_pais_nivel0.svg", "Balance país por nivel 0"),
        ("02_heatmap_pais_clase_nivel1.svg", "Matriz país x clase"),
        ("03_pareto_fuentes.svg", "Pareto de fuentes"),
        ("04_uso_a18_por_pais.svg", "Uso A1.8 por país"),
        ("05_score_por_pais.svg", "Score por país"),
        ("06_burbujas_volumen_score_pais.svg", "Volumen y aptitud"),
        ("07_heatmap_vacios_pais_clase.svg", "Vacíos país x clase"),
        ("08_alluvial_homologacion_nivel1.svg", "Homologación origen-propuesta"),
        ("09_grupos_xy_regionales_nivel1.svg", "Grupos XY regionales por clase"),
    ]
    figure_blocks = []
    for filename, label in figure_order:
        figure_blocks.append(
            f"""
            <section class="figure-block">
              <div class="figure-header">
                <h2>{esc(label)}</h2>
                <a href="figuras/{esc(filename)}">SVG</a>
              </div>
              <div class="svg-wrap">{figures[filename]}</div>
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Análisis visual A1/A2 - base homologada</title>
  <style>
    :root {{
      --ink: #172326;
      --muted: #697276;
      --line: #DDE3E2;
      --surface: #FFFFFF;
      --bg: #F6F7F7;
      --green: #2E7D59;
      --amber: #D2923A;
      --blue: #356C9A;
    }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      padding: 32px 42px 22px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 30px;
      letter-spacing: 0;
    }}
    .lead {{
      max-width: 980px;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.55;
    }}
    main {{
      padding: 24px 42px 42px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }}
    .metric {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .metric-value {{
      font-size: 27px;
      font-weight: 800;
      margin-top: 5px;
    }}
    .metric-note {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 3px;
    }}
    .note-band {{
      background: #FFFFFF;
      border-left: 5px solid var(--amber);
      padding: 14px 18px;
      margin: 0 0 24px;
      line-height: 1.5;
      color: #37474F;
    }}
    .figure-block {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 18px;
      overflow: hidden;
    }}
    .figure-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
    }}
    .figure-header h2 {{
      margin: 0;
      font-size: 17px;
    }}
    .figure-header a {{
      color: var(--blue);
      text-decoration: none;
      font-weight: 700;
      font-size: 13px;
    }}
    .svg-wrap {{
      overflow-x: auto;
      padding: 12px;
    }}
    svg {{
      max-width: 100%;
      height: auto;
      display: block;
    }}
    footer {{
      color: var(--muted);
      font-size: 12px;
      padding: 10px 42px 30px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Análisis visual de resultados A1/A2 y base homologada</h1>
    <p class="lead">
      Visualizaciones generadas desde <code>data/processed/a2_1_modelo_datos/gpkg/a2_1_xy_point.gpkg</code>
      y tablas de diagnóstico A1. El foco es cobertura, concentración, aptitud y riesgos de uso para modelado.
    </p>
  </header>
  <main>
    <section class="metrics">{cards}</section>
    <section class="note-band">
      Lectura ejecutiva: la homologación está cerrada, sin registros huérfanos, pero la base queda altamente concentrada por país,
      fuente y clase. Para modelado regional conviene balancear por país, fuente y clase homologada; además, el conjunto A1.8 no
      define una partición de prueba.
    </section>
    {''.join(figure_blocks)}
  </main>
  <footer>
    Script: generar_visualizaciones_homologacion.py · Resultados: docs/actividad_2/A2_llave_class_uso/analisis_visual_homologacion_a1_a2/resultados
  </footer>
</body>
</html>
"""


def build_readme() -> str:
    return f"""# Análisis visual A1/A2 - base homologada

Esta carpeta contiene un paquete reproducible de visualizaciones para presentar
los resultados de la Actividad 1 y Actividad 2, con foco en la homologación de
clases y uso de la base normalizada.

Se organiza como subcarpeta de `docs/actividad_2/A2_llave_class_uso` para
mantenerlo junto al explorador previo de clases homologadas por país.

## Archivos principales

- `generar_visualizaciones_homologacion.py`: script sin dependencias externas.
- `analisis_visual_homologacion_a1_a2.ipynb`: notebook ejecutable.
- `resultados/dashboard_homologacion_a1_a2.html`: tablero autocontenido.
- `resultados/figuras/*.svg`: figuras vectoriales reutilizables.
- `resultados/tablas/*.csv`: resúmenes usados por las figuras.

## Ejecución

Desde la raíz del repositorio:

```bash
python3 docs/actividad_2/A2_llave_class_uso/analisis_visual_homologacion_a1_a2/generar_visualizaciones_homologacion.py
```

Fecha de generación local: se actualiza al ejecutar el script.
"""


def main() -> None:
    ensure_dirs()
    print(f"Proyecto: {PROJECT_ROOT}")
    print(f"Leyendo: {GPKG}")
    data = build_data()
    export_tables(data)
    figures = build_figures(data)
    dashboard = build_dashboard(data, figures)
    save_text(RESULTS_DIR / "dashboard_homologacion_a1_a2.html", dashboard)
    save_text(PACKAGE_DIR / "README.md", build_readme())
    print(f"Dashboard: {RESULTS_DIR / 'dashboard_homologacion_a1_a2.html'}")
    print(f"Figuras: {FIG_DIR}")
    print(f"Tablas: {TABLE_DIR}")


if __name__ == "__main__":
    main()
