from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[3]

CASE_REPORTS = PROJECT_DIR / "outputs/reports/a3_auditorias_nuevas_fuentes/caso_panama"
CASE_TABLES = PROJECT_DIR / "outputs/tables/a3_auditorias_nuevas_fuentes/caso_panama"

METHODOLOGY_HTML = CASE_REPORTS / "metodologia_auditoria_espectral_mapa_forestal_panama_src15_2021.html"
RESULTS_HTML = CASE_REPORTS / "analisis_resultados_auditoria_espectral_mapa_forestal_panama_src15_2021.html"

GEE_INPUT_TABLES = CASE_TABLES / "gee_input"
XY_TABLES = CASE_TABLES / "xy_groups"
JOIN_TABLES = CASE_TABLES / "s2sr_join"
AUDIT_TABLES = CASE_TABLES / "spectral_class_audit"
SCORING_TABLES = CASE_TABLES / "quality_scoring"


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def fmt_int(value: object) -> str:
    if pd.isna(value):
        return "NA"
    return f"{int(float(value)):,}"


def fmt_float(value: object, digits: int = 3) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):,.{digits}f}"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_DIR)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def html_table(df: pd.DataFrame, columns: list[str] | None = None, max_rows: int | None = None) -> str:
    out = df.copy()
    if columns is not None:
        out = out[[c for c in columns if c in out.columns]]
    if max_rows is not None:
        out = out.head(max_rows)
    return out.to_html(index=False, classes="data-table", border=0, escape=True)


def metric_card(label: str, value: str, note: str = "") -> str:
    note_html = f"<span>{escape(note)}</span>" if note else ""
    return f"""
      <article class="metric">
        <strong>{escape(value)}</strong>
        <p>{escape(label)}</p>
        {note_html}
      </article>
    """


def bar_rows(df: pd.DataFrame, label_col: str, value_col: str, pct_col: str | None = None) -> str:
    rows = []
    max_value = float(df[value_col].max()) if len(df) else 1.0
    for _, row in df.iterrows():
        label = str(row[label_col])
        value = float(row[value_col])
        pct = float(row[pct_col]) if pct_col and pct_col in row else 0.0
        width = min(100.0, max(0.0, value / max_value * 100 if max_value else 0))
        rows.append(
            f"""
            <div class="bar-row">
              <div class="bar-label">{escape(label)}</div>
              <div class="bar-track"><div class="bar-fill" style="width:{width:.2f}%"></div></div>
              <div class="bar-value">{fmt_int(value)} <span>{pct:.3f}%</span></div>
            </div>
            """
        )
    return "\n".join(rows)


def page(title: str, subtitle: str, body: str) -> str:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f6f7f4;
      --ink: #1f2933;
      --muted: #5f6b76;
      --line: #d9ded6;
      --panel: #ffffff;
      --accent: #1f7a6d;
      --accent-2: #9d5c2e;
      --soft: #edf6f2;
      --warn: #fff5df;
      --danger: #fae7e5;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.55;
    }}
    header {{
      background: #153f3a;
      color: white;
      padding: 44px clamp(20px, 6vw, 72px) 36px;
    }}
    header p {{ max-width: 980px; color: #d7ebe6; font-size: 1.06rem; margin: 10px 0 0; }}
    h1 {{ margin: 0; font-size: clamp(2rem, 4vw, 3.2rem); line-height: 1.08; letter-spacing: 0; }}
    h2 {{ margin-top: 38px; border-bottom: 1px solid var(--line); padding-bottom: 8px; }}
    h3 {{ margin-top: 24px; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 30px clamp(16px, 4vw, 44px) 70px; }}
    .meta {{ color: #d7ebe6; font-size: .92rem; margin-top: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin: 20px 0; }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-height: 120px;
    }}
    .metric strong {{ display: block; font-size: 1.75rem; color: var(--accent); line-height: 1.1; }}
    .metric p {{ margin: 8px 0 0; color: var(--ink); font-weight: 650; }}
    .metric span {{ display: block; margin-top: 8px; color: var(--muted); font-size: .9rem; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin: 16px 0;
    }}
    .note {{ background: var(--soft); border-left: 5px solid var(--accent); }}
    .warning {{ background: var(--warn); border-left: 5px solid var(--accent-2); }}
    .danger {{ background: var(--danger); border-left: 5px solid #b6463a; }}
    code {{ background: #eef1ee; border: 1px solid #dce2dd; border-radius: 5px; padding: 1px 5px; font-size: .92em; }}
    pre {{ overflow: auto; background: #172421; color: #e7f2ef; border-radius: 8px; padding: 14px; }}
    ul, ol {{ padding-left: 1.25rem; }}
    .data-table {{ width: 100%; border-collapse: collapse; background: white; margin: 14px 0 24px; font-size: .92rem; }}
    .data-table th, .data-table td {{ border: 1px solid var(--line); padding: 8px 10px; vertical-align: top; text-align: left; }}
    .data-table th {{ background: #eef4ef; font-weight: 750; }}
    .table-wrap {{ overflow-x: auto; }}
    .bar-row {{ display: grid; grid-template-columns: minmax(120px, 230px) 1fr minmax(120px, 160px); gap: 12px; align-items: center; margin: 9px 0; }}
    .bar-track {{ height: 12px; background: #e2e8e3; border-radius: 999px; overflow: hidden; }}
    .bar-fill {{ height: 100%; background: var(--accent); }}
    .bar-label {{ font-weight: 650; }}
    .bar-value {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .bar-value span {{ color: var(--muted); }}
    .two-col {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; }}
    footer {{ color: var(--muted); font-size: .9rem; margin-top: 44px; }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(title)}</h1>
    <p>{escape(subtitle)}</p>
    <div class="meta">Generado: {escape(generated)} · Carpeta base: {escape(PROJECT_DIR.name)}</div>
  </header>
  <main>
    {body}
    <footer>Documento generado a partir de scripts, YAML, GeoPackages y CSV de control del caso mapa forestal de Panamá SRC15 2021.</footer>
  </main>
</body>
</html>
"""


def build_methodology() -> str:
    rules = read_csv(AUDIT_TABLES / "mapa_forestal_panama_class_rules_reference.csv")
    params = read_csv(AUDIT_TABLES / "audit_rule_parameters.csv")
    weights = read_csv(SCORING_TABLES / "scoring_weights.csv")

    body = f"""
    <section class="panel note">
      <h2>Resumen ejecutivo</h2>
      <p>Este flujo documenta la auditoría espectral y el scoring multicriterio del caso <strong>MIAMBIENTE - Cultivos Mapa Panamá</strong>, identificado como <code>SRC15</code> e <code>id_fuente=15</code>. El año de referencia es 2021.</p>
      <p>El proceso parte del muestreo d500 sobre el raster recortado del mapa forestal de Panamá, normaliza los puntos, genera grupos XY, extrae métricas Sentinel-2 SR, une la respuesta espectral con los registros y produce alertas exploratorias por clase temática.</p>
    </section>

    <h2>Orden lógico del flujo</h2>
    <div class="panel">
      <ol>
        <li>Preparación de puntos del mapa forestal de Panamá para auditoría.</li>
        <li>Creación de <code>xy_group_id</code>, <code>xy_year_group_id</code> y <code>xy_class_group_id</code>.</li>
        <li>Preparación del CSV de unidades únicas para Google Earth Engine.</li>
        <li>Extracción mensual Sentinel-2 SR con s2cloudless en GEE.</li>
        <li>Control del CSV exportado y unión mensual/anual con registros originales.</li>
        <li>Auditoría espectral preliminar por clase y grupo XY.</li>
        <li>Scoring multicriterio por <code>xy_group_id</code>.</li>
        <li>Generación de documentación HTML trazable.</li>
      </ol>
    </div>

    <h2>Unidades de análisis</h2>
    <div class="two-col">
      <div class="panel">
        <h3>Unidad espacial</h3>
        <p><code>xy_group_id</code> representa una coordenada única. En este caso se usa el namespace <code>SRC15_PAN_2021</code>, compatible con el flujo de nuevas fuentes y aislado de otros casos.</p>
      </div>
      <div class="panel">
        <h3>Unidad espectral</h3>
        <p><code>extract_id</code> representa <code>Longitud + Latitud + Año</code>. Así se evita repetir extracciones Sentinel-2 cuando varios registros comparten punto y año.</p>
      </div>
    </div>

    <h2>Reglas temático-espectrales</h2>
    <p>Las reglas son concordantes con las auditorías de Actividad 1 y SINAC en indicadores, severidad y umbrales base, pero adaptadas a los <code>Class_value</code> del mapa forestal de Panamá.</p>
    <div class="table-wrap">{html_table(rules)}</div>

    <h2>Parámetros de auditoría</h2>
    <div class="table-wrap">{html_table(params)}</div>

    <h2>Pesos del scoring</h2>
    <div class="table-wrap">{html_table(weights)}</div>

    <h2>Comandos de reproducción</h2>
    <pre><code>conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/caso_panama/01_preparar_mapa_forestal_panama_auditoria_espectral.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/caso_panama/02_xy_groups_mapa_forestal_panama.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/caso_panama/03_s2_sr_gee_input_mapa_forestal_panama.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/caso_panama/04_generate_gee_export_report_mapa_forestal_panama.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/caso_panama/05_join_s2sr_to_mapa_forestal_panama_records.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/caso_panama/06_s2sr_spectral_class_audit_mapa_forestal_panama.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/caso_panama/08_scoring_integral_mapa_forestal_panama.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/caso_panama/07_generate_project_html_docs_mapa_forestal_panama.py</code></pre>
    """
    return page(
        "Metodología de auditoría espectral - Mapa Forestal Panamá SRC15 2021",
        "Flujo reproducible de preparación, extracción Sentinel-2 SR, auditoría espectral y scoring para la fuente MIAMBIENTE.",
        body,
    )


def build_results() -> str:
    xy_summary = read_csv(XY_TABLES / "xy_groups_audit_summary.csv").iloc[0]
    gee_summary = read_csv(GEE_INPUT_TABLES / "s2_sr_nueva_fuente_summary.csv").iloc[0]
    join_validation = read_csv(JOIN_TABLES / "validation_summary.csv").iloc[0]
    monthly = read_csv(JOIN_TABLES / "monthly_clean_obs_summary.csv")
    thematic = read_csv(JOIN_TABLES / "thematic_extract_units_summary.csv")
    audit_summary = read_csv(AUDIT_TABLES / "audit_summary.csv").iloc[0]
    alert_original = read_csv(AUDIT_TABLES / "alert_distribution_original_records.csv")
    alert_units = read_csv(AUDIT_TABLES / "alert_distribution_extract_units.csv")
    class_original = read_csv(AUDIT_TABLES / "class_spectral_audit_original_records.csv")
    xy_audit = read_csv(AUDIT_TABLES / "xy_group_spectral_audit.csv")
    rules = read_csv(AUDIT_TABLES / "mapa_forestal_panama_class_rules_reference.csv")
    score_categories = read_csv(SCORING_TABLES / "aptitude_category_summary.csv")
    score_components = read_csv(SCORING_TABLES / "score_component_summary.csv")

    class_cols = [
        "audit_class_name",
        "n_records",
        "n_spectral_priority",
        "pct_spectral_priority",
        "n_alert_high",
        "n_alert_medium",
        "pct_class_rule_high",
        "pct_class_rule_medium",
        "pct_rare_spectral_value",
        "class_priority_level",
    ]
    class_view = class_original[[c for c in class_cols if c in class_original.columns]].copy()
    class_view = class_view.head(30)

    xy_cols = [
        "xy_group_id",
        "n_records",
        "n_extract_ids",
        "n_priority_records",
        "pct_priority_records",
        "max_spectral_alert_level",
        "n_classes",
        "n_class_groups",
    ]
    xy_view = xy_audit[[c for c in xy_cols if c in xy_audit.columns]].copy()
    xy_view = xy_view.sort_values(
        ["n_priority_records", "pct_priority_records", "n_records"],
        ascending=[False, False, False],
    ).head(30)

    score_mean = score_components.loc[
        score_components["statistic"].eq("mean"), "score_aptitud_total"
    ].iloc[0]

    body = f"""
    <section class="grid">
      {metric_card("Registros elegibles", fmt_int(gee_summary["eligible_records"]), "Puntos d500 normalizados")}
      {metric_card("Grupos XY", fmt_int(xy_summary["xy_groups"]), "Coordenadas únicas auditadas")}
      {metric_card("Unidades extract_id", fmt_int(gee_summary["extract_units_lon_lat_year"]), "Longitud + Latitud + Año")}
      {metric_card("Extract ID en GEE", fmt_int(join_validation["gee_unique_extract_id"]), "Validados en el CSV exportado")}
      {metric_card("Registros prioritarios", fmt_int(audit_summary["n_priority_original_records"]), f'{fmt_float(audit_summary["pct_priority_original_records"])}% del total')}
      {metric_card("Rareza espectral", fmt_int(audit_summary["n_rare_spectral_records"]), f'{fmt_float(audit_summary["pct_rare_spectral_records"])}%')}
      {metric_card("Baja disponibilidad", fmt_int(audit_summary["n_low_availability_records"]), f'{fmt_float(audit_summary["pct_low_availability_records"])}%')}
      {metric_card("Score promedio", fmt_float(score_mean), "Score total por xy_group_id")}
    </section>

    <section class="panel note">
      <h2>Lectura general</h2>
      <p>El procesamiento cerró sin pérdidas de <code>extract_id</code>: los {fmt_int(join_validation["original_unique_extract_id"])} identificadores originales tienen correspondencia en el CSV de GEE, sin extras ni duplicados por mes.</p>
      <p>La auditoría espectral marcó {fmt_int(audit_summary["n_priority_original_records"])} registros como prioritarios ({fmt_float(audit_summary["pct_priority_original_records"])}%). La mayoría de los registros queda sin alerta, y el scoring clasifica {fmt_float(score_categories.loc[score_categories["categoria_aptitud"].eq("entrenamiento_alta"), "pct_xy_groups"].iloc[0])}% de los grupos como <code>entrenamiento_alta</code>.</p>
    </section>

    <h2>Distribución de alertas</h2>
    <div class="two-col">
      <div class="panel">
        <h3>Registros originales</h3>
        {bar_rows(alert_original, "spectral_alert_level", "n", "pct")}
      </div>
      <div class="panel">
        <h3>Unidades únicas</h3>
        {bar_rows(alert_units, "spectral_alert_level", "n", "pct")}
      </div>
    </div>

    <h2>Categorías de aptitud</h2>
    <div class="table-wrap">{html_table(score_categories)}</div>

    <h2>Componentes del score</h2>
    <div class="table-wrap">{html_table(score_components)}</div>

    <h2>Clases priorizadas</h2>
    <div class="table-wrap">{html_table(class_view)}</div>

    <h2>Grupos XY priorizados</h2>
    <div class="table-wrap">{html_table(xy_view)}</div>

    <h2>Control mensual de observaciones limpias</h2>
    <div class="table-wrap">{html_table(monthly)}</div>

    <h2>Distribución temática de unidades</h2>
    <div class="table-wrap">{html_table(thematic, max_rows=40)}</div>

    <h2>Reglas usadas</h2>
    <div class="table-wrap">{html_table(rules)}</div>

    <h2>Productos principales</h2>
    <div class="panel">
      <ul>
        <li><code>{escape(rel(PROJECT_DIR / "data/processed/a3_auditorias_nuevas_fuentes/caso_panama/spectral_class_audit/s2sr_spectral_class_audit_mapa_forestal_panama_src15_2021_outputs.gpkg"))}</code></li>
        <li><code>{escape(rel(PROJECT_DIR / "data/processed/a3_auditorias_nuevas_fuentes/caso_panama/quality_scoring/mapa_forestal_panama_src15_2021_quality_scoring_outputs.gpkg"))}</code></li>
        <li><code>{escape(rel(AUDIT_TABLES))}</code></li>
        <li><code>{escape(rel(SCORING_TABLES))}</code></li>
        <li><code>{escape(rel(CASE_REPORTS))}</code></li>
      </ul>
    </div>
    """
    return page(
        "Análisis de resultados - Mapa Forestal Panamá SRC15 2021",
        "Síntesis de controles GEE, auditoría espectral, clases priorizadas y scoring multicriterio.",
        body,
    )


def main() -> None:
    CASE_REPORTS.mkdir(parents=True, exist_ok=True)
    METHODOLOGY_HTML.write_text(build_methodology(), encoding="utf-8")
    RESULTS_HTML.write_text(build_results(), encoding="utf-8")
    print("HTML metodológico:", METHODOLOGY_HTML)
    print("HTML resultados:", RESULTS_HTML)


if __name__ == "__main__":
    main()
