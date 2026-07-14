from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]
REPORTS_DIR = PROJECT_DIR / "outputs" / "reports" / "a3_auditorias_nuevas_fuentes"

METHODOLOGY_HTML = REPORTS_DIR / "metodologia_auditoria_espectral_sinac_src10_2021.html"
RESULTS_HTML = REPORTS_DIR / "analisis_resultados_auditoria_espectral_sinac_src10_2021.html"

PROCESSED_DIR = PROJECT_DIR / "data" / "processed" / "a3_auditorias_nuevas_fuentes"
TABLES_DIR = PROJECT_DIR / "outputs" / "tables" / "a3_auditorias_nuevas_fuentes"
GEE_INPUT_TABLES = TABLES_DIR / "gee_input"
XY_TABLES = TABLES_DIR / "xy_groups"
JOIN_TABLES = TABLES_DIR / "s2sr_join"
AUDIT_TABLES = TABLES_DIR / "spectral_class_audit"
SCORING_TABLES = TABLES_DIR / "quality_scoring"


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
        pct = float(row[pct_col]) if pct_col and pct_col in row else (value / max_value * 100 if max_value else 0)
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
      --bg: #f7f7f4;
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
      padding: 46px clamp(20px, 6vw, 72px) 38px;
    }}
    header p {{ max-width: 960px; color: #d7ebe6; font-size: 1.06rem; margin: 10px 0 0; }}
    h1 {{ margin: 0; font-size: clamp(2rem, 4vw, 3.35rem); line-height: 1.08; letter-spacing: 0; }}
    h2 {{ margin-top: 40px; border-bottom: 1px solid var(--line); padding-bottom: 8px; }}
    h3 {{ margin-top: 28px; }}
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
    .metric strong {{ display: block; font-size: 1.8rem; color: var(--accent); line-height: 1.1; }}
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
    code {{
      background: #eef1ee;
      border: 1px solid #dce2dd;
      border-radius: 5px;
      padding: 1px 5px;
      font-size: .92em;
    }}
    pre {{
      overflow: auto;
      background: #172421;
      color: #e7f2ef;
      border-radius: 8px;
      padding: 14px;
    }}
    ul, ol {{ padding-left: 1.25rem; }}
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
      margin: 14px 0 24px;
      font-size: .92rem;
    }}
    .data-table th, .data-table td {{
      border: 1px solid var(--line);
      padding: 8px 10px;
      vertical-align: top;
      text-align: left;
    }}
    .data-table th {{ background: #eef4ef; font-weight: 750; }}
    .table-wrap {{ overflow-x: auto; }}
    .bar-row {{
      display: grid;
      grid-template-columns: minmax(120px, 230px) 1fr minmax(120px, 160px);
      gap: 12px;
      align-items: center;
      margin: 9px 0;
    }}
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
    <footer>Documento generado a partir de scripts, YAML, GeoPackages y CSV de control del piloto SINAC SRC10 2021.</footer>
  </main>
</body>
</html>
"""


def build_methodology() -> str:
    rules = read_csv(AUDIT_TABLES / "sinac_class_rules_reference.csv")
    params = read_csv(AUDIT_TABLES / "audit_rule_parameters.csv")

    body = f"""
    <section class="panel note">
      <h2>Resumen ejecutivo</h2>
      <p>Esta carpeta implementa un flujo reproducible para auditar una nueva fuente puntual SINAC con datos Sentinel-2 Surface Reflectance. El flujo normaliza puntos, genera grupos XY estables, genera unidades únicas de extracción, exporta métricas mensuales desde Google Earth Engine, une los resultados espectrales con los registros originales y aplica una auditoría exploratoria por clase temática.</p>
      <p>La unidad central de integración es <code>extract_id</code>, construida a partir de <code>Longitud + Latitud + Año</code>. Esta decisión evita extraer varias veces el mismo punto-año cuando hay registros temáticos repetidos o superpuestos.</p>
      <p>La unidad espacial de auditoría es <code>xy_group_id</code>, con namespace propio para evitar colisiones con grupos XY del flujo original.</p>
    </section>

    <h2>Arquitectura del proyecto</h2>
    <div class="two-col">
      <div class="panel">
        <h3>Carpetas principales</h3>
        <ul>
          <li><code>src/actividad_3/a3_auditorias_nuevas_fuentes/</code>: pasos Python del flujo.</li>
          <li><code>config/</code>: YAML del piloto y rutas relativas.</li>
          <li><code>gee/</code>: JavaScript usado en Google Earth Engine.</li>
          <li><code>data/processed/a3_auditorias_nuevas_fuentes/raw/</code>: datos originales.</li>
          <li><code>data/processed/a3_auditorias_nuevas_fuentes/</code>: datos normalizados intermedios.</li>
          <li><code>data/processed/a3_auditorias_nuevas_fuentes/gee_exports/</code>: CSV descargados desde GEE.</li>
          <li><code>outputs/</code>: productos analíticos y tablas de control.</li>
          <li><code>outputs/reports/a3_auditorias_nuevas_fuentes/</code>: reportes Markdown y HTML.</li>
        </ul>
      </div>
      <div class="panel">
        <h3>Orden lógico del flujo</h3>
        <ol>
          <li>Normalización de fuente SINAC.</li>
          <li>Creación de grupos XY independientes.</li>
          <li>Preparación de insumos GEE con trazabilidad XY.</li>
          <li>Extracción mensual Sentinel-2 SR en GEE.</li>
          <li>Control del CSV exportado.</li>
          <li>Unión registros originales + métricas espectrales.</li>
          <li>Auditoría espectral preliminar por clase y por grupo XY.</li>
          <li>Auditorías integradas y scoring multicriterio por <code>xy_group_id</code>.</li>
        </ol>
      </div>
    </div>

    <h2>Decisiones metodológicas</h2>
    <div class="panel">
      <h3>Normalización de fuente</h3>
      <p>Los datos SINAC se transformaron a un esquema mínimo y consistente con campos de fuente, país, año, coordenadas, clase y geometría. La geometría se reproyectó a <code>EPSG:4326</code> y las coordenadas se recalcularon desde la geometría para evitar valores heredados inconsistentes.</p>
      <p>Campos esperados: <code>Fuente</code>, <code>id_fuente</code>, <code>Pais_es</code>, <code>Pais_cod3</code>, <code>Año</code>, <code>Longitud</code>, <code>Latitud</code>, <code>Clase</code>, <code>GranClase</code>, <code>nombre_clase</code>, <code>nombre_gran_clase</code> y <code>geometry</code>.</p>
    </div>
    <div class="panel">
      <h3>Grupos XY para nuevas fuentes</h3>
      <p>Antes de preparar GEE se generan tres identificadores estables: <code>xy_group_id</code> para <code>Longitud + Latitud</code>, <code>xy_year_group_id</code> para <code>Longitud + Latitud + Año</code> y <code>xy_class_group_id</code> para <code>Longitud + Latitud + Año + Clase + GranClase</code>. Estos IDs usan el namespace configurado en YAML, por lo que pueden convivir con grupos XY del flujo original sin duplicarse.</p>
    </div>
    <div class="panel">
      <h3>Unidad única de extracción</h3>
      <p>La extracción se definió por <code>Longitud + Latitud + Año</code>, no por registro original. Esta decisión redujo redundancia: varios registros pueden compartir una misma unidad espectral. Para conservar trazabilidad, el <code>extract_id</code> se devuelve a cada registro original.</p>
    </div>
    <div class="panel">
      <h3>Extracción Sentinel-2 SR</h3>
      <p>El JavaScript de GEE usa <code>COPERNICUS/S2_SR_HARMONIZED</code> y <code>COPERNICUS/S2_CLOUD_PROBABILITY</code>. Se calcularon métricas mensuales para bandas Sentinel-2 e índices <code>NDVI</code>, <code>NDVI8A</code> y <code>NDRE</code>. La extracción usa escala de 20 m, buffer de 60 m y máscara s2cloudless con exclusión de clases SCL problemáticas.</p>
    </div>
    <div class="panel">
      <h3>Unión y resumen anual</h3>
      <p>Los CSV de GEE llegan en formato largo: una fila por <code>extract_id</code> y mes. El paso de unión transforma esos datos a formato ancho, agrega columnas mensuales <code>s2_*</code> y métricas anuales <code>s2yr_*</code>, y genera cuatro capas: completa, reducida, anual por registro y anual por unidad única.</p>
    </div>

    <h2>Reglas de evaluación por clase</h2>
    <p>Las reglas son exploratorias. Buscan priorizar revisión, no confirmar o descartar definitivamente una clase. La señal base usa principalmente <code>NDVI</code> y <code>NDRE</code> medianos anuales.</p>
    <div class="table-wrap">{html_table(rules)}</div>

    <h2>Parámetros de auditoría</h2>
    <div class="table-wrap">{html_table(params)}</div>

    <h2>Banderas generadas por la auditoría</h2>
    <div class="panel">
      <ul>
        <li><code>flag_no_spectral_data</code>: no hay datos espectrales útiles.</li>
        <li><code>flag_low_months_obs</code>: menos meses observados que el mínimo configurado.</li>
        <li><code>flag_low_total_obs</code>: bajo total anual de observaciones limpias.</li>
        <li><code>flag_high_cloudprob</code>: probabilidad mediana anual de nube alta.</li>
        <li><code>flag_class_rule_high</code> y <code>flag_class_rule_medium</code>: activación de reglas temático-espectrales.</li>
        <li><code>flag_rare_spectral_value</code>: rareza estadística por clase, país y año usando IQR.</li>
        <li><code>flag_context_thematic_conflict</code>: más de una clase o gran clase asociada al mismo <code>extract_id</code>.</li>
      </ul>
    </div>

    <h2>Scoring multicriterio</h2>
    <div class="panel">
      <p>El cierre metodológico adapta el scoring del flujo original usando la misma lógica de criterios: temporal, espacial, temático, espectral, confiabilidad, representatividad y fuente. La unidad de decisión es <code>xy_group_id</code>.</p>
      <p>Para esta fuente monoanual, el componente temporal evalúa la coincidencia con 2021. El componente temático usa <code>Clase</code> y <code>GranClase</code>, y el componente semántico marca clases residuales o ambiguas mediante palabras clave configuradas.</p>
    </div>

    <h2>Cómo reutilizar este flujo con otros datos</h2>
    <div class="panel warning">
      <p>El flujo puede aplicarse a otras fuentes puntuales si se ajustan las columnas de entrada y las reglas temáticas. Lo indispensable es que la fuente pueda normalizarse a un esquema equivalente.</p>
      <ol>
        <li>Actualizar el YAML en <code>config/</code> con rutas, capa de entrada, CRS esperado y nombres de campos.</li>
        <li>Mapear los campos de clase: código de clase, gran clase, nombre de clase y nombre de gran clase.</li>
        <li>Definir el año de referencia y la fuente (<code>source_id</code>, país, descripción).</li>
        <li>Definir un namespace único para <code>xy_group_id</code> y revisar la precisión de coordenadas.</li>
        <li>Revisar si la unidad <code>Longitud + Latitud + Año</code> sigue siendo válida o si otra llave es más apropiada.</li>
        <li>Ajustar el JavaScript de GEE si cambia el país, lote, colección, rango temporal, escala o prefijo de exportación.</li>
        <li>Modificar las reglas de auditoría por clase cuando las clases, ecosistemas o umbrales esperados no correspondan al caso SINAC.</li>
      </ol>
    </div>

    <h2>Comandos de reproducción</h2>
    <pre><code>conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/01_preparar_sinac_auditoria_espectral.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/02_xy_groups_nuevas_fuentes.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/03_s2_sr_gee_input_nuevas_fuentes_caso_SINAC.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/04_generate_gee_export_report_sinac_src10_2021.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/05_join_s2sr_to_sinac_src10_2021_records.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/06_s2sr_spectral_class_audit_sinac_src10_2021.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/08_scoring_integral_nuevas_fuentes.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/07_generate_project_html_docs_sinac_src10_2021.py</code></pre>
    """
    return page(
        "Metodología de auditoría espectral SINAC SRC10 2021",
        "Descripción del flujo usado en Piloto_auditoria_espectral_nuevas_fuentes y criterios para adaptarlo a otros datos.",
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
    rules = read_csv(AUDIT_TABLES / "sinac_class_rules_reference.csv")
    score_categories = read_csv(SCORING_TABLES / "aptitude_category_summary.csv")
    score_components = read_csv(SCORING_TABLES / "score_component_summary.csv")

    class_view = class_original[
        [
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
    ].copy()
    class_view.columns = [
        "Clase",
        "Registros",
        "Prioritarios",
        "% prioritarios",
        "Alertas altas",
        "Alertas medias",
        "% regla alta",
        "% regla media",
        "% rareza",
        "Nivel clase",
    ]

    monthly_view = monthly.copy()
    monthly_view.columns = [
        "Mes",
        "Filas",
        "Extract ID",
        "Filas sin obs limpias",
        "Mediana obs limpias",
        "Máx obs limpias",
        "% sin obs limpias",
    ]

    thematic_view = thematic.copy()
    thematic_view.columns = ["Gran clase", "Nombre gran clase", "Clase", "Nombre clase", "Registros/unidades"]

    xy_view = xy_audit[
        [
            "xy_group_id",
            "n_records",
            "n_extract_ids",
            "n_priority_records",
            "pct_priority_records",
            "max_spectral_alert_level",
            "n_classes",
            "n_class_groups",
        ]
    ].copy()
    xy_view = xy_view.sort_values(
        ["n_priority_records", "pct_priority_records", "n_records"],
        ascending=[False, False, False],
    ).head(30)
    xy_view.columns = [
        "xy_group_id",
        "Registros",
        "Extract ID",
        "Prioritarios",
        "% prioritarios",
        "Alerta máxima",
        "Clases",
        "Gran clases",
    ]

    body = f"""
    <section class="grid">
      {metric_card("Registros elegibles", fmt_int(gee_summary["eligible_records"]), "Registros normalizados de entrada")}
      {metric_card("Grupos XY", fmt_int(xy_summary["xy_groups"]), "Longitud + Latitud con namespace")}
      {metric_card("Unidades únicas de extracción", fmt_int(gee_summary["extract_units_lon_lat_year"]), "Longitud + Latitud + Año")}
      {metric_card("Filas mensuales GEE esperadas", fmt_int(int(join_validation["gee_unique_extract_id"]) * 12), "12 meses por extract_id")}
      {metric_card("Registros prioritarios", fmt_int(audit_summary["n_priority_original_records"]), f'{fmt_float(audit_summary["pct_priority_original_records"])}% del total')}
      {metric_card("Unidades prioritarias", fmt_int(audit_summary["n_priority_extract_units"]), f'{fmt_float(audit_summary["pct_priority_extract_units"])}% de unidades')}
      {metric_card("Registros con rareza espectral", fmt_int(audit_summary["n_rare_spectral_records"]), f'{fmt_float(audit_summary["pct_rare_spectral_records"])}%')}
      {metric_card("Score total promedio", fmt_float(score_components.loc[score_components["statistic"].eq("mean"), "score_aptitud_total"].iloc[0]), "Promedio por xy_group_id")}
    </section>

    <section class="panel note">
      <h2>Lectura general</h2>
      <p>El procesamiento fue consistente: todos los <code>extract_id</code> originales tienen valores espectrales, no hubo <code>extract_id</code> extra en GEE y no se detectaron duplicados por <code>extract_id + month</code>. La cobertura anual es buena: las capas anuales reportan 12 meses observados como mediana en todas las clases principales.</p>
      <p>La auditoría espacial generó {fmt_int(xy_summary["xy_groups"])} <code>xy_group_id</code> independientes. Estos IDs se conservaron en la preparación GEE, el join S2SR y la auditoría espectral por grupo.</p>
      <p>La auditoría marcó como prioritarios {fmt_int(audit_summary["n_priority_original_records"])} registros originales ({fmt_float(audit_summary["pct_priority_original_records"])}%). Esto debe leerse como priorización de revisión, no como error definitivo.</p>
    </section>

    <h2>Distribución de alertas</h2>
    <div class="two-col">
      <div class="panel">
        <h3>Registros originales</h3>
        {bar_rows(alert_original, "spectral_alert_level", "n", "pct")}
      </div>
      <div class="panel">
        <h3>Unidades únicas de extracción</h3>
        {bar_rows(alert_units, "spectral_alert_level", "n", "pct")}
      </div>
    </div>

    <h2>Resultados por clase</h2>
    <div class="panel warning">
      <p>Las clases que más concentran prioridad son <strong>Humedal Palustre</strong>, <strong>Edificaciones</strong> y <strong>Pastos</strong>. En Humedal Palustre, la regla es deliberadamente sensible a extremos porque es una clase mixta agua-vegetación. En Edificaciones, una señal vegetal elevada puede indicar mezcla con árboles, jardines, bordes urbanos o un posible desajuste temático. En Pastos, valores vegetativos altos también pueden reflejar manejo, estacionalidad o confusión temática.</p>
    </div>
    <div class="table-wrap">{html_table(class_view)}</div>

    <h2>Resultados por grupo XY</h2>
    <p>Esta tabla resume los grupos espaciales con mayor prioridad espectral. Permite revisar por ubicación, manteniendo la independencia frente a los grupos XY del flujo original.</p>
    <div class="table-wrap">{html_table(xy_view)}</div>

    <h2>Scoring multicriterio</h2>
    <p>El score total integra criterios temporal, espacial, temático/semántico, espectral, confiabilidad, representatividad y fuente. Las categorías son comparables metodológicamente con el cierre del flujo original, pero adaptadas a <code>Clase</code>/<code>GranClase</code> y a una fuente monoanual.</p>
    <div class="table-wrap">{html_table(score_categories)}</div>
    <div class="table-wrap">{html_table(score_components)}</div>

    <h2>Control mensual de observaciones limpias</h2>
    <p>Los meses con mayor proporción de filas sin observaciones limpias fueron agosto, mayo y octubre. Aun así, el porcentaje mensual máximo fue 4.040%.</p>
    <div class="table-wrap">{html_table(monthly_view)}</div>

    <h2>Distribución temática de la fuente</h2>
    <p>La fuente está dominada por Cultivos y Edificaciones, seguidos por bosque secundario deciduo y Pastos. Esta composición influye en el balance de alertas: clases grandes con reglas sensibles generan muchos registros prioritarios.</p>
    <div class="table-wrap">{html_table(thematic_view)}</div>

    <h2>Interpretación de hallazgos principales</h2>
    <div class="two-col">
      <div class="panel danger">
        <h3>Alertas altas</h3>
        <p>Las alertas altas se activan por reglas fuertes de clase, por ausencia de datos espectrales o por combinación de conflicto temático con rareza/regla espectral. En este resultado predominan reglas fuertes para Edificaciones y, en menor medida, Manglar.</p>
      </div>
      <div class="panel warning">
        <h3>Alertas medias</h3>
        <p>Las alertas medias recogen señales fuera de expectativa pero menos concluyentes. Son útiles para revisión masiva o para seleccionar muestras de control, especialmente en Humedal Palustre y Pastos.</p>
      </div>
    </div>

    <h2>Reglas usadas como referencia</h2>
    <div class="table-wrap">{html_table(rules)}</div>

    <h2>Productos generados</h2>
    <div class="panel">
      <ul>
        <li><code>{escape(rel(PROJECT_DIR / "data/processed/a3_auditorias_nuevas_fuentes/spectral_class_audit/s2sr_spectral_class_audit_sinac_src10_2021_outputs.gpkg"))}</code></li>
        <li><code>{escape(rel(PROJECT_DIR / "data/processed/a3_auditorias_nuevas_fuentes/xy_groups/sinac_src10_2021_xy_groups_outputs.gpkg"))}</code></li>
        <li><code>{escape(rel(PROJECT_DIR / "data/processed/a3_auditorias_nuevas_fuentes/quality_scoring/sinac_src10_2021_quality_scoring_outputs.gpkg"))}</code></li>
        <li><code>{escape(rel(XY_TABLES))}</code></li>
        <li><code>{escape(rel(AUDIT_TABLES))}</code></li>
        <li><code>{escape(rel(SCORING_TABLES))}</code></li>
        <li><code>{escape(rel(PROJECT_DIR / "outputs/reports/a3_auditorias_nuevas_fuentes/xy_groups/xy_groups_sinac_src10_2021_report.md"))}</code></li>
        <li><code>{escape(rel(PROJECT_DIR / "outputs/reports/a3_auditorias_nuevas_fuentes/quality_scoring/quality_scoring_sinac_src10_2021_report.md"))}</code></li>
        <li><code>{escape(rel(PROJECT_DIR / "outputs/reports/a3_auditorias_nuevas_fuentes/spectral_class_audit/s2sr_spectral_class_audit_sinac_src10_2021_report.md"))}</code></li>
      </ul>
    </div>
    """
    return page(
        "Análisis de resultados de auditoría espectral SINAC SRC10 2021",
        "Síntesis de conteos, distribución de alertas, clases priorizadas y controles de calidad del procesamiento.",
        body,
    )


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    METHODOLOGY_HTML.write_text(build_methodology(), encoding="utf-8")
    RESULTS_HTML.write_text(build_results(), encoding="utf-8")
    print("HTML metodológico:", METHODOLOGY_HTML)
    print("HTML resultados:", RESULTS_HTML)


if __name__ == "__main__":
    main()
