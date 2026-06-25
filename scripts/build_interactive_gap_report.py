from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
TABLES_DIR = PROJECT_DIR / "outputs" / "tables"
DOCS_DIR = (
    PROJECT_DIR
    / "docs"
    / "A1_06-A1_07-A1_08_scoring_multicriterio_y_clasificacion_funcional_final"
)
OUTPUT_HTML = DOCS_DIR / "10_explorador_interactivo_vacios_clases.html"

COUNT_FILES = {
    "Nivel_1": TABLES_DIR / "10_baja_cantidad_puntos_pais_clase_Nivel_1.csv",
    "Nivel_2": TABLES_DIR / "10_baja_cantidad_puntos_pais_clase_Nivel_2.csv",
}

SCORE_FILES = {
    "Nivel_1": TABLES_DIR / "10_bajo_scoring_pais_clase_Nivel_1.csv",
    "Nivel_2": TABLES_DIR / "10_bajo_scoring_pais_clase_Nivel_2.csv",
}

INT_FIELDS = {
    "n_xy",
    "n_registros",
    "n_xy_regional",
    "n_xy_pais_total",
    "prioridad_count",
}

FLOAT_FIELDS = {
    "pct_clase_en_pais",
    "score_medio",
    "score_min",
}


def coerce_value(key: str, value: str) -> Any:
    value = "" if value is None else value.strip()
    if value == "":
        return None

    if key in INT_FIELDS:
        return int(float(value))

    if key in FLOAT_FIELDS:
        return round(float(value), 6)

    return value


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el CSV requerido: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [
            {key: coerce_value(key, value) for key, value in row.items()}
            for row in reader
        ]


def build_payload() -> dict[str, Any]:
    count_data = {level: read_csv(path) for level, path in COUNT_FILES.items()}
    score_data = {level: read_csv(path) for level, path in SCORE_FILES.items()}

    countries = sorted(
        {
            str(row["pais"])
            for dataset in [count_data, score_data]
            for rows in dataset.values()
            for row in rows
            if row.get("pais")
        }
    )

    return {
        "generated_at": date.today().isoformat(),
        "levels": list(COUNT_FILES.keys()),
        "countries": ["Todos", *countries],
        "count": count_data,
        "score": score_data,
        "sources": {
            "count": {level: str(path.relative_to(PROJECT_DIR)) for level, path in COUNT_FILES.items()},
            "score": {level: str(path.relative_to(PROJECT_DIR)) for level, path in SCORE_FILES.items()},
        },
    }


def html_template(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    payload_json = payload_json.replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Explorador interactivo de vacíos país-clase</title>
<style>
:root {{
  --bg: #f6f7f9;
  --surface: #ffffff;
  --surface-2: #eef2f6;
  --text: #1f2933;
  --muted: #5f6c7b;
  --border: #d8dee6;
  --primary: #174a7c;
  --primary-2: #25636f;
  --green: #13795b;
  --amber: #b45309;
  --red: #b42318;
  --blue: #2563eb;
  --shadow: 0 8px 24px rgba(16, 24, 40, 0.08);
}}

* {{
  box-sizing: border-box;
}}

body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: "Segoe UI", Roboto, Arial, sans-serif;
  line-height: 1.45;
}}

a {{
  color: var(--primary);
}}

.shell {{
  max-width: 1440px;
  margin: 0 auto;
  padding: 22px;
}}

.topbar {{
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 16px;
}}

.eyebrow {{
  margin: 0 0 4px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}}

h1 {{
  margin: 0;
  color: var(--primary);
  font-size: 28px;
  line-height: 1.15;
}}

.topbar p {{
  margin: 8px 0 0;
  color: var(--muted);
  max-width: 820px;
}}

.toplinks {{
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 280px;
}}

.link-button,
button {{
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font: inherit;
  font-weight: 700;
  padding: 9px 12px;
  text-decoration: none;
}}

.link-button:hover,
button:hover {{
  border-color: var(--primary);
}}

.workspace {{
  display: grid;
  grid-template-columns: 330px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}}

.panel,
.viz,
.details {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: var(--shadow);
}}

.panel {{
  position: sticky;
  top: 16px;
  padding: 16px;
}}

.control {{
  margin-bottom: 14px;
}}

label {{
  display: block;
  margin-bottom: 6px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}}

select,
input[type="search"],
input[type="range"] {{
  width: 100%;
}}

select,
input[type="search"] {{
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  color: var(--text);
  font: inherit;
  padding: 9px 10px;
}}

.range-row {{
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  align-items: center;
}}

.top-value {{
  color: var(--primary);
  font-weight: 800;
  min-width: 36px;
  text-align: right;
}}

.button-row {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 16px;
}}

.hint {{
  margin: 12px 0 0;
  color: var(--muted);
  font-size: 12px;
}}

.viz {{
  min-width: 0;
  overflow: hidden;
}}

.viz-head {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
  padding: 18px 18px 12px;
  border-bottom: 1px solid var(--border);
}}

h2 {{
  margin: 0;
  color: var(--primary);
  font-size: 21px;
}}

.subtitle {{
  margin: 6px 0 0;
  color: var(--muted);
}}

.stats {{
  display: grid;
  grid-template-columns: repeat(4, minmax(90px, 1fr));
  gap: 8px;
  min-width: 430px;
}}

.stat {{
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  padding: 8px 10px;
}}

.stat span {{
  display: block;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}}

.stat strong {{
  display: block;
  margin-top: 3px;
  font-size: 18px;
}}

.chart {{
  padding: 12px 18px 20px;
}}

.bar-row {{
  display: grid;
  grid-template-columns: minmax(190px, 330px) minmax(160px, 1fr) minmax(150px, 260px);
  gap: 10px;
  align-items: center;
  padding: 7px 0;
  border-bottom: 1px solid #edf0f4;
}}

.bar-row:last-child {{
  border-bottom: 0;
}}

.label-main {{
  font-weight: 700;
  overflow-wrap: anywhere;
}}

.label-sub {{
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}}

.bar-track {{
  position: relative;
  height: 18px;
  overflow: hidden;
  border-radius: 8px;
  background: #e9edf2;
}}

.bar-fill {{
  height: 100%;
  min-width: 2px;
  border-radius: 8px;
  background: var(--blue);
}}

.bar-fill.critical {{
  background: var(--red);
}}

.bar-fill.warning {{
  background: var(--amber);
}}

.bar-fill.ok {{
  background: var(--green);
}}

.metric {{
  text-align: right;
  font-variant-numeric: tabular-nums;
}}

.metric strong {{
  display: block;
}}

.metric span {{
  display: block;
  color: var(--muted);
  font-size: 12px;
}}

.empty {{
  padding: 36px;
  color: var(--muted);
  text-align: center;
}}

.details {{
  margin-top: 16px;
  padding: 18px;
}}

.details h2 {{
  margin-bottom: 10px;
}}

.table-wrap {{
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
}}

table {{
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
  font-size: 13px;
}}

th,
td {{
  padding: 9px 10px;
  border-bottom: 1px solid #edf0f4;
  text-align: left;
  vertical-align: top;
}}

th {{
  background: #f0f5f9;
  color: #17324d;
  font-weight: 800;
}}

tbody tr:nth-child(even) {{
  background: #fafbfc;
}}

.badge {{
  display: inline-block;
  border-radius: 999px;
  padding: 2px 8px;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}}

.badge.critical {{
  background: var(--red);
}}

.badge.warning {{
  background: var(--amber);
}}

.badge.ok {{
  background: var(--green);
}}

.method {{
  margin-top: 16px;
  color: var(--muted);
  font-size: 13px;
}}

.method code {{
  background: #eef2f6;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 1px 5px;
}}

.status {{
  min-height: 18px;
  margin-top: 10px;
  color: var(--muted);
  font-size: 12px;
}}

@media (max-width: 1120px) {{
  .workspace {{
    grid-template-columns: 1fr;
  }}

  .panel {{
    position: static;
  }}

  .stats {{
    min-width: 0;
  }}
}}

@media (max-width: 760px) {{
  .shell {{
    padding: 14px;
  }}

  .topbar,
  .viz-head {{
    display: block;
  }}

  .toplinks {{
    justify-content: flex-start;
    margin-top: 12px;
    min-width: 0;
  }}

  .stats {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
    margin-top: 12px;
  }}

  .bar-row {{
    grid-template-columns: 1fr;
    gap: 6px;
  }}

  .metric {{
    text-align: left;
  }}
}}
</style>
</head>
<body>
<main class="shell">
  <header class="topbar">
    <div>
      <p class="eyebrow">PGBM Actividad 1 · Módulo 10</p>
      <h1>Explorador interactivo de vacíos país-clase</h1>
      <p>Consulta publicable para revisar baja cantidad de puntos, clases ausentes con soporte regional y combinaciones con scoring bajo. Funciona como HTML estático en GitHub Pages.</p>
    </div>
    <nav class="toplinks" aria-label="Enlaces del reporte">
      <a class="link-button" href="10_scoring_multicriterio_aptitud.html">Reporte del scoring</a>
      <a class="link-button" href="#tabla">Tabla filtrada</a>
    </nav>
  </header>

  <section class="workspace" aria-label="Explorador interactivo">
    <aside class="panel">
      <div class="control">
        <label for="level">Nivel</label>
        <select id="level"></select>
      </div>
      <div class="control">
        <label for="country">País</label>
        <select id="country"></select>
      </div>
      <div class="control">
        <label for="view">Vista</label>
        <select id="view">
          <option value="gaps">Vacíos y baja cantidad</option>
          <option value="count">Cantidad de puntos</option>
          <option value="score">Scoring más bajo</option>
        </select>
      </div>
      <div class="control" id="order-control">
        <label for="order">Orden</label>
        <select id="order">
          <option value="asc">Menor cantidad</option>
          <option value="desc">Mayor cantidad</option>
        </select>
      </div>
      <div class="control">
        <label for="topn">Top N</label>
        <div class="range-row">
          <input id="topn" type="range" min="10" max="80" value="30" step="5">
          <span id="topn-value" class="top-value">30</span>
        </div>
      </div>
      <div class="control">
        <label for="class-filter">Filtrar clase</label>
        <input id="class-filter" type="search" placeholder="Nombre o código de clase">
      </div>
      <div class="button-row">
        <button id="copy-link" type="button">Copiar enlace</button>
        <button id="download-csv" type="button">Descargar CSV</button>
      </div>
      <button id="reset" type="button" style="width:100%;margin-top:8px">Restablecer</button>
      <p class="hint">Datos embebidos desde los CSV del módulo 10. Última generación: {payload["generated_at"]}.</p>
      <div id="status" class="status" aria-live="polite"></div>
    </aside>

    <section class="viz">
      <div class="viz-head">
        <div>
          <h2 id="chart-title">Exploración</h2>
          <p id="chart-subtitle" class="subtitle"></p>
        </div>
        <div class="stats" aria-label="Resumen del filtro">
          <div class="stat"><span>Filas</span><strong id="stat-rows">0</strong></div>
          <div class="stat"><span>Países</span><strong id="stat-countries">0</strong></div>
          <div class="stat"><span>Clases</span><strong id="stat-classes">0</strong></div>
          <div class="stat"><span>Máximo</span><strong id="stat-max">0</strong></div>
        </div>
      </div>
      <div id="chart" class="chart"></div>
    </section>
  </section>

  <section id="tabla" class="details">
    <h2>Tabla filtrada</h2>
    <div class="table-wrap">
      <table>
        <thead id="table-head"></thead>
        <tbody id="table-body"></tbody>
      </table>
    </div>
    <p class="method">
      Para <code>Vacíos y baja cantidad</code>, la métrica de priorización usa <code>n_xy_regional</code> cuando <code>n_xy</code> del país es cero, y <code>n_xy</code> cuando la clase sí existe en el país. Para <code>Scoring más bajo</code>, se ordena por <code>score_medio</code> ascendente.
    </p>
    <p class="method" id="source-files"></p>
  </section>
</main>

<script type="application/json" id="gap-data">{payload_json}</script>
<script>
const DATA = JSON.parse(document.getElementById("gap-data").textContent);

const controls = {{
  level: document.getElementById("level"),
  country: document.getElementById("country"),
  view: document.getElementById("view"),
  order: document.getElementById("order"),
  orderControl: document.getElementById("order-control"),
  topn: document.getElementById("topn"),
  topnValue: document.getElementById("topn-value"),
  classFilter: document.getElementById("class-filter"),
  reset: document.getElementById("reset"),
  copyLink: document.getElementById("copy-link"),
  downloadCsv: document.getElementById("download-csv"),
  status: document.getElementById("status")
}};

const chart = document.getElementById("chart");
const chartTitle = document.getElementById("chart-title");
const chartSubtitle = document.getElementById("chart-subtitle");
const tableHead = document.getElementById("table-head");
const tableBody = document.getElementById("table-body");
const sourceFiles = document.getElementById("source-files");
const statRows = document.getElementById("stat-rows");
const statCountries = document.getElementById("stat-countries");
const statClasses = document.getElementById("stat-classes");
const statMax = document.getElementById("stat-max");

const VIEW_LABELS = {{
  gaps: "Vacíos y baja cantidad",
  count: "Cantidad de puntos",
  score: "Scoring más bajo"
}};

function fmtInt(value) {{
  const number = Number(value || 0);
  return Math.round(number).toLocaleString("es-CR");
}}

function fmtFloat(value, digits = 2) {{
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "NA";
  return Number(value).toLocaleString("es-CR", {{
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  }});
}}

function normalizeText(value) {{
  return String(value || "")
    .normalize("NFD")
    .replace(/[\\u0300-\\u036f]/g, "")
    .toLowerCase();
}}

function badgeClass(state) {{
  const text = normalizeText(state);
  if (text.includes("critico") || text.includes("sin score")) return "critical";
  if (text.includes("baja") || text.includes("bajo")) return "warning";
  return "ok";
}}

function metricFor(row, view) {{
  if (view === "score") return Number(row.score_medio || 0);
  if (view === "gaps") return Number(row.n_xy === 0 ? row.n_xy_regional : row.n_xy);
  return Number(row.n_xy || 0);
}}

function detailFor(row, view) {{
  if (view === "score") {{
    return `score min=${{fmtFloat(row.score_min, 2)}} · puntos=${{fmtInt(row.n_xy)}}`;
  }}

  if (view === "gaps" && Number(row.n_xy || 0) === 0) {{
    return `ausente en país · soporte regional=${{fmtInt(row.n_xy_regional)}}`;
  }}

  return `puntos=${{fmtInt(row.n_xy)}} · registros=${{fmtInt(row.n_registros)}} · regional=${{fmtInt(row.n_xy_regional)}}`;
}}

function rowsForState() {{
  const level = controls.level.value;
  const country = controls.country.value;
  const view = controls.view.value;
  const query = normalizeText(controls.classFilter.value);

  let rows = view === "score"
    ? [...DATA.score[level]]
    : [...DATA.count[level]];

  if (country !== "Todos") {{
    rows = rows.filter(row => row.pais === country);
  }}

  if (query) {{
    rows = rows.filter(row => normalizeText(row.clase).includes(query));
  }}

  if (view === "gaps") {{
    rows = rows.filter(row => row.estado_count !== "suficiente");
    rows.sort((a, b) =>
      Number(a.n_xy || 0) - Number(b.n_xy || 0) ||
      metricFor(b, view) - metricFor(a, view) ||
      Number(b.n_xy_regional || 0) - Number(a.n_xy_regional || 0) ||
      String(a.clase).localeCompare(String(b.clase), "es")
    );
  }} else if (view === "count") {{
    rows = rows.filter(row => Number(row.n_xy || 0) > 0);
    rows.sort((a, b) => {{
      const diff = Number(a.n_xy || 0) - Number(b.n_xy || 0);
      const ordered = controls.order.value === "desc" ? -diff : diff;
      return ordered || String(a.clase).localeCompare(String(b.clase), "es");
    }});
  }} else {{
    rows = rows.filter(row => Number(row.n_xy || 0) > 0);
    rows.sort((a, b) =>
      Number(a.score_medio || 0) - Number(b.score_medio || 0) ||
      Number(a.n_xy || 0) - Number(b.n_xy || 0) ||
      String(a.clase).localeCompare(String(b.clase), "es")
    );
  }}

  return rows;
}}

function selectedRows() {{
  return rowsForState().slice(0, Number(controls.topn.value));
}}

function renderCountries() {{
  const selected = controls.country.value || "Todos";
  const level = controls.level.value || DATA.levels[0];
  const countries = new Set(["Todos"]);

  for (const group of [DATA.count[level], DATA.score[level]]) {{
    for (const row of group) countries.add(row.pais);
  }}

  controls.country.innerHTML = [...countries].sort((a, b) => {{
    if (a === "Todos") return -1;
    if (b === "Todos") return 1;
    return a.localeCompare(b, "es");
  }}).map(country => `<option value="${{escapeAttr(country)}}">${{escapeHtml(country)}}</option>`).join("");

  controls.country.value = countries.has(selected) ? selected : "Todos";
}}

function renderControlsFromQuery() {{
  const params = new URLSearchParams(window.location.search);
  const level = params.get("nivel");
  const country = params.get("pais");
  const view = params.get("vista");
  const order = params.get("orden");
  const top = params.get("top");
  const q = params.get("clase");

  controls.level.innerHTML = DATA.levels
    .map(levelName => `<option value="${{escapeAttr(levelName)}}">${{escapeHtml(levelName)}}</option>`)
    .join("");

  controls.level.value = DATA.levels.includes(level) ? level : DATA.levels[1] || DATA.levels[0];
  renderCountries();

  if (country) controls.country.value = country;
  if (["gaps", "count", "score"].includes(view)) controls.view.value = view;
  if (["asc", "desc"].includes(order)) controls.order.value = order;
  if (top && Number(top) >= 10 && Number(top) <= 80) controls.topn.value = String(Number(top));
  if (q) controls.classFilter.value = q;
}}

function render() {{
  renderCountries();
  controls.orderControl.style.display = controls.view.value === "count" ? "block" : "none";
  controls.topnValue.textContent = controls.topn.value;

  const rows = rowsForState();
  const shown = selectedRows();
  const metrics = shown.map(row => metricFor(row, controls.view.value));
  const maxMetric = metrics.length ? Math.max(...metrics) : 0;
  const countries = new Set(rows.map(row => row.pais));
  const classes = new Set(rows.map(row => row.clase));

  chartTitle.textContent = `${{VIEW_LABELS[controls.view.value]}} · ${{controls.level.value}}`;
  chartSubtitle.textContent = `País: ${{controls.country.value}} · Top ${{controls.topn.value}}`;
  statRows.textContent = fmtInt(rows.length);
  statCountries.textContent = fmtInt(countries.size);
  statClasses.textContent = fmtInt(classes.size);
  statMax.textContent = controls.view.value === "score" ? fmtFloat(maxMetric, 2) : fmtInt(maxMetric);

  renderChart(shown, maxMetric);
  renderTable(shown);
  renderSources();
  updateUrl();
}}

function renderChart(rows, maxMetric) {{
  if (!rows.length) {{
    chart.innerHTML = `<div class="empty">No hay datos para el filtro seleccionado.</div>`;
    return;
  }}

  chart.innerHTML = rows.map(row => {{
    const view = controls.view.value;
    const metric = metricFor(row, view);
    const width = view === "score"
      ? Math.max(2, Math.min(100, metric))
      : Math.max(2, maxMetric ? (metric / maxMetric) * 100 : 0);
    const state = view === "score" ? row.estado_score : row.estado_count;
    const css = badgeClass(state);
    const metricLabel = view === "score" ? fmtFloat(metric, 2) : fmtInt(metric);
    const metricSub = view === "score" ? "score medio" : (view === "gaps" ? "prioridad" : "nXY país");

    return `
      <div class="bar-row">
        <div>
          <div class="label-main">${{escapeHtml(row.pais)}} | ${{escapeHtml(row.clase)}}</div>
          <div class="label-sub"><span class="badge ${{css}}">${{escapeHtml(state || "sin estado")}}</span> ${{escapeHtml(detailFor(row, view))}}</div>
        </div>
        <div class="bar-track" aria-hidden="true">
          <div class="bar-fill ${{css}}" style="width:${{width.toFixed(3)}}%"></div>
        </div>
        <div class="metric"><strong>${{metricLabel}}</strong><span>${{metricSub}}</span></div>
      </div>`;
  }}).join("");
}}

function renderTable(rows) {{
  const view = controls.view.value;
  const headers = view === "score"
    ? ["País", "Clase", "Estado", "nXY", "Registros", "Score medio", "Score min"]
    : ["País", "Clase", "Estado", "nXY país", "Registros", "nXY regional", "% clase país", "Métrica"];

  tableHead.innerHTML = `<tr>${{headers.map(header => `<th>${{escapeHtml(header)}}</th>`).join("")}}</tr>`;

  tableBody.innerHTML = rows.map(row => {{
    if (view === "score") {{
      return `<tr>
        <td>${{escapeHtml(row.pais)}}</td>
        <td>${{escapeHtml(row.clase)}}</td>
        <td><span class="badge ${{badgeClass(row.estado_score)}}">${{escapeHtml(row.estado_score)}}</span></td>
        <td>${{fmtInt(row.n_xy)}}</td>
        <td>${{fmtInt(row.n_registros)}}</td>
        <td>${{fmtFloat(row.score_medio, 3)}}</td>
        <td>${{fmtFloat(row.score_min, 3)}}</td>
      </tr>`;
    }}

    return `<tr>
      <td>${{escapeHtml(row.pais)}}</td>
      <td>${{escapeHtml(row.clase)}}</td>
      <td><span class="badge ${{badgeClass(row.estado_count)}}">${{escapeHtml(row.estado_count)}}</span></td>
      <td>${{fmtInt(row.n_xy)}}</td>
      <td>${{fmtInt(row.n_registros)}}</td>
      <td>${{fmtInt(row.n_xy_regional)}}</td>
      <td>${{fmtFloat(row.pct_clase_en_pais, 3)}}</td>
      <td>${{view === "gaps" ? fmtInt(metricFor(row, view)) : fmtInt(row.n_xy)}}</td>
    </tr>`;
  }}).join("");
}}

function renderSources() {{
  const level = controls.level.value;
  sourceFiles.innerHTML = `Fuentes: <code>${{escapeHtml(DATA.sources.count[level])}}</code> y <code>${{escapeHtml(DATA.sources.score[level])}}</code>.`;
}}

function updateUrl() {{
  const params = new URLSearchParams();
  params.set("nivel", controls.level.value);
  params.set("pais", controls.country.value);
  params.set("vista", controls.view.value);
  params.set("orden", controls.order.value);
  params.set("top", controls.topn.value);
  if (controls.classFilter.value.trim()) params.set("clase", controls.classFilter.value.trim());
  try {{
    window.history.replaceState(null, "", `${{window.location.pathname}}?${{params.toString()}}`);
  }} catch (error) {{
    // Some local file viewers restrict history updates; GitHub Pages supports them.
  }}
}}

function csvEscape(value) {{
  const text = String(value ?? "");
  if (/[",\\n]/.test(text)) return `"${{text.replace(/"/g, '""')}}"`;
  return text;
}}

function downloadCurrentCsv() {{
  const rows = selectedRows();
  if (!rows.length) {{
    controls.status.textContent = "No hay filas para descargar.";
    return;
  }}

  const view = controls.view.value;
  const headers = view === "score"
    ? ["pais", "clase", "estado_score", "n_xy", "n_registros", "score_medio", "score_min"]
    : ["pais", "clase", "estado_count", "n_xy", "n_registros", "n_xy_regional", "pct_clase_en_pais", "metrica"];

  const lines = [headers.join(",")];
  for (const row of rows) {{
    const values = view === "score"
      ? headers.map(key => row[key])
      : headers.map(key => key === "metrica" ? metricFor(row, view) : row[key]);
    lines.push(values.map(csvEscape).join(","));
  }}

  const blob = new Blob([lines.join("\\n")], {{type: "text/csv;charset=utf-8"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `explorador_vacios_${{controls.level.value}}_${{view}}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  controls.status.textContent = "CSV descargado con el filtro actual.";
}}

async function copyCurrentLink() {{
  const href = window.location.href;
  try {{
    await navigator.clipboard.writeText(href);
    controls.status.textContent = "Enlace copiado.";
  }} catch (error) {{
    controls.status.textContent = href;
  }}
}}

function resetControls() {{
  controls.level.value = DATA.levels[1] || DATA.levels[0];
  renderCountries();
  controls.country.value = "Todos";
  controls.view.value = "gaps";
  controls.order.value = "asc";
  controls.topn.value = "30";
  controls.classFilter.value = "";
  render();
}}

function escapeHtml(value) {{
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}}

function escapeAttr(value) {{
  return escapeHtml(value);
}}

for (const control of [controls.level, controls.country, controls.view, controls.order, controls.topn, controls.classFilter]) {{
  control.addEventListener("input", render);
  control.addEventListener("change", render);
}}

controls.reset.addEventListener("click", resetControls);
controls.copyLink.addEventListener("click", copyCurrentLink);
controls.downloadCsv.addEventListener("click", downloadCurrentCsv);

renderControlsFromQuery();
render();
</script>
<noscript>Esta página necesita JavaScript para aplicar filtros y dibujar la gráfica.</noscript>
</body>
</html>
"""


def main() -> None:
    payload = build_payload()
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_template(payload), encoding="utf-8")
    print(f"[OK] HTML generado: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
