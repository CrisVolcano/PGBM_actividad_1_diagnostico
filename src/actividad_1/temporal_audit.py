"""
Módulo 4 - Auditoría temporal del GeoPackage.

Este script evalúa la estructura temporal de la capa principal del GeoPackage
sin modificar los datos originales.

Objetivos:
- Evaluar calidad del campo Año.
- Identificar años nulos, vacíos o fuera de rango plausible.
- Analizar distribución anual general.
- Clasificar registros según cercanía al año objetivo 2020.
- Resumir cobertura temporal por país, fuente y clases temáticas.
- Integrar resumen temporal de grupos XY del Módulo 3B, si existe.
- Generar tablas, figuras y reporte Markdown.

Principios:
- No modifica el GeoPackage original.
- Abre el GeoPackage en modo lectura.
- Evita uniones pesadas.
- Usa agregaciones SQL directas.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
import traceback

import matplotlib.pyplot as plt
import pandas as pd
import yaml


# ============================================================
# RUTAS GENERALES
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

TABLES_DIR = PROJECT_ROOT / "outputs" / "tables"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"
LOGS_DIR = PROJECT_ROOT / "logs"

XY_GROUPS_DB = PROJECT_ROOT / "data" / "interim" / "03b_multirregistros_xy.sqlite"


# ============================================================
# FUNCIONES GENERALES
# ============================================================

def crear_carpetas_salida() -> None:
    """Crea carpetas de salida si no existen."""
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def registrar_log(mensaje: str) -> None:
    """Registra un mensaje en logs/auditoria.log."""
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOGS_DIR / "auditoria.log", "a", encoding="utf-8") as log:
        log.write(f"[{fecha}] {mensaje}\n")


def cargar_yaml(path: Path) -> dict:
    """Carga un archivo YAML."""
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo requerido: {path}")

    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return data or {}


def quote_ident(identifier: str) -> str:
    """Protege nombres de campos o tablas para SQL."""
    return '"' + str(identifier).replace('"', '""') + '"'


def dataframe_a_markdown(df: pd.DataFrame) -> str:
    """Convierte un DataFrame a Markdown."""
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


def abrir_conexion_lectura(gpkg_path: Path) -> sqlite3.Connection:
    """Abre el GeoPackage en modo solo lectura."""
    if not gpkg_path.exists():
        raise FileNotFoundError(f"No existe el GeoPackage: {gpkg_path}")

    return sqlite3.connect(f"file:{gpkg_path}?mode=ro", uri=True)


def obtener_schema(conn: sqlite3.Connection, table_name: str) -> pd.DataFrame:
    """Obtiene esquema SQLite de la tabla principal."""
    schema = pd.read_sql_query(f"PRAGMA table_info({quote_ident(table_name)});", conn)
    schema = schema.rename(
        columns={
            "cid": "ordinal",
            "name": "field_name",
            "type": "sqlite_type",
            "notnull": "not_null",
            "dflt_value": "default_value",
            "pk": "primary_key",
        }
    )
    return schema


def campo_existe(schema: pd.DataFrame, field_name: str) -> bool:
    """Evalúa si un campo existe en el esquema."""
    return field_name in set(schema["field_name"].tolist())


def validar_campos(schema: pd.DataFrame, campos: list[str]) -> None:
    """Valida que los campos requeridos existan."""
    faltantes = [campo for campo in campos if not campo_existe(schema, campo)]

    if faltantes:
        raise ValueError(f"Campos requeridos ausentes: {faltantes}")


def obtener_total_registros(conn: sqlite3.Connection, table_name: str) -> int:
    """Cuenta registros de la tabla principal."""
    sql = f"SELECT COUNT(*) AS n FROM {quote_ident(table_name)};"
    return int(pd.read_sql_query(sql, conn)["n"].iloc[0])


# ============================================================
# EXPRESIONES TEMPORALES
# ============================================================

def year_text_expr(year_field: str) -> str:
    """Expresión SQL para Año como texto limpio."""
    return f"TRIM(CAST({quote_ident(year_field)} AS TEXT))"


def year_num_expr(year_field: str) -> str:
    """
    Expresión SQL para convertir Año a entero.

    SQLite puede convertir textos no numéricos a 0 al usar CAST.
    Esos casos quedan capturados como fuera de rango plausible.
    """
    txt = year_text_expr(year_field)

    return f"""
    CASE
        WHEN {quote_ident(year_field)} IS NULL THEN NULL
        WHEN {txt} = '' THEN NULL
        ELSE CAST(CAST({txt} AS REAL) AS INTEGER)
    END
    """


# ============================================================
# AUDITORÍA TEMPORAL
# ============================================================

def calcular_calidad_temporal(
    conn: sqlite3.Connection,
    table_name: str,
    year_field: str,
    total_registros: int,
    min_year: int,
    max_year: int,
) -> pd.DataFrame:
    """Calcula calidad general del campo Año."""
    year_sql = quote_ident(year_field)
    year_txt = year_text_expr(year_field)
    year_num = year_num_expr(year_field)

    sql = f"""
    WITH base AS (
        SELECT
            {year_sql} AS year_original,
            {year_txt} AS year_text,
            {year_num} AS year_num
        FROM {quote_ident(table_name)}
    )
    SELECT
        COUNT(*) AS n_total,

        SUM(CASE WHEN year_original IS NULL THEN 1 ELSE 0 END) AS n_anio_null,

        SUM(
            CASE
                WHEN year_original IS NOT NULL
                AND year_text = ''
                THEN 1 ELSE 0
            END
        ) AS n_anio_vacio,

        SUM(
            CASE
                WHEN year_num IS NULL
                OR year_num < {int(min_year)}
                OR year_num > {int(max_year)}
                THEN 1 ELSE 0
            END
        ) AS n_anio_fuera_rango_plausible,

        MIN(year_num) AS anio_min_observado,
        MAX(year_num) AS anio_max_observado,
        COUNT(DISTINCT year_num) AS n_anios_distintos

    FROM base;
    """

    df = pd.read_sql_query(sql, conn)

    for col in ["n_anio_null", "n_anio_vacio", "n_anio_fuera_rango_plausible"]:
        df[f"pct_{col.replace('n_', '')}"] = round((df[col] / total_registros) * 100, 6)

    df["min_plausible_year"] = min_year
    df["max_plausible_year"] = max_year

    return df


def distribucion_anual(
    conn: sqlite3.Connection,
    table_name: str,
    year_field: str,
    min_year: int,
    max_year: int,
) -> pd.DataFrame:
    """Distribución anual de registros válidos."""
    year_num = year_num_expr(year_field)

    sql = f"""
    WITH base AS (
        SELECT {year_num} AS year_num
        FROM {quote_ident(table_name)}
    )
    SELECT
        CAST(year_num AS INTEGER) AS anio,
        COUNT(*) AS n
    FROM base
    WHERE year_num BETWEEN {int(min_year)} AND {int(max_year)}
    GROUP BY CAST(year_num AS INTEGER)
    ORDER BY anio;
    """

    df = pd.read_sql_query(sql, conn)

    total = df["n"].sum() if not df.empty else 0
    df["pct"] = round((df["n"] / total) * 100, 6) if total > 0 else 0

    return df


def distribucion_relevancia_temporal(
    conn: sqlite3.Connection,
    table_name: str,
    year_field: str,
    target_year: int,
    near_window: int,
    min_year: int,
    max_year: int,
) -> pd.DataFrame:
    """Clasifica registros según relación con el año objetivo."""
    year_num = year_num_expr(year_field)

    sql = f"""
    WITH base AS (
        SELECT {year_num} AS year_num
        FROM {quote_ident(table_name)}
    ),
    clasificada AS (
        SELECT
            CASE
                WHEN year_num IS NULL THEN 'anio_ausente_o_vacio'
                WHEN year_num < {int(min_year)} OR year_num > {int(max_year)} THEN 'anio_fuera_rango_plausible'
                WHEN CAST(year_num AS INTEGER) = {int(target_year)} THEN 'anio_objetivo'
                WHEN ABS(CAST(year_num AS INTEGER) - {int(target_year)}) <= {int(near_window)} THEN 'cercano_anio_objetivo'
                WHEN CAST(year_num AS INTEGER) < {int(target_year)} - {int(near_window)} THEN 'anterior_a_ventana_objetivo'
                WHEN CAST(year_num AS INTEGER) > {int(target_year)} + {int(near_window)} THEN 'posterior_a_ventana_objetivo'
                ELSE 'revision_temporal'
            END AS relevancia_temporal
        FROM base
    )
    SELECT
        relevancia_temporal,
        COUNT(*) AS n
    FROM clasificada
    GROUP BY relevancia_temporal
    ORDER BY n DESC;
    """

    df = pd.read_sql_query(sql, conn)
    total = df["n"].sum() if not df.empty else 0

    df["pct"] = round((df["n"] / total) * 100, 6) if total > 0 else 0
    df["target_year"] = target_year
    df["near_window_years"] = near_window

    return df


def distribucion_anual_por_campo(
    conn: sqlite3.Connection,
    table_name: str,
    year_field: str,
    group_field: str,
    min_year: int,
    max_year: int,
    schema: pd.DataFrame,
) -> pd.DataFrame:
    """Distribución anual por un campo categórico."""
    if not campo_existe(schema, group_field):
        return pd.DataFrame(
            [{"group_field": group_field, "warning": "Campo no existe."}]
        )

    year_num = year_num_expr(year_field)

    sql = f"""
    WITH base AS (
        SELECT
            CAST({quote_ident(group_field)} AS TEXT) AS grupo,
            {year_num} AS year_num
        FROM {quote_ident(table_name)}
    )
    SELECT
        '{group_field}' AS group_field,
        grupo,
        CAST(year_num AS INTEGER) AS anio,
        COUNT(*) AS n
    FROM base
    WHERE year_num BETWEEN {int(min_year)} AND {int(max_year)}
    GROUP BY grupo, CAST(year_num AS INTEGER)
    ORDER BY grupo, anio;
    """

    return pd.read_sql_query(sql, conn)


def cobertura_temporal_por_campo(
    conn: sqlite3.Connection,
    table_name: str,
    year_field: str,
    group_field: str,
    min_year: int,
    max_year: int,
    schema: pd.DataFrame,
) -> pd.DataFrame:
    """Resume cobertura temporal por campo categórico."""
    if not campo_existe(schema, group_field):
        return pd.DataFrame(
            [{"group_field": group_field, "warning": "Campo no existe."}]
        )

    year_num = year_num_expr(year_field)

    sql = f"""
    WITH base AS (
        SELECT
            CAST({quote_ident(group_field)} AS TEXT) AS grupo,
            {year_num} AS year_num
        FROM {quote_ident(table_name)}
    )
    SELECT
        '{group_field}' AS group_field,
        grupo,
        COUNT(*) AS n_registros,
        MIN(CAST(year_num AS INTEGER)) AS anio_min,
        MAX(CAST(year_num AS INTEGER)) AS anio_max,
        COUNT(DISTINCT CAST(year_num AS INTEGER)) AS n_anios_distintos
    FROM base
    WHERE year_num BETWEEN {int(min_year)} AND {int(max_year)}
    GROUP BY grupo
    ORDER BY n_registros DESC;
    """

    return pd.read_sql_query(sql, conn)


def cobertura_temporal_pais_fuente(
    conn: sqlite3.Connection,
    table_name: str,
    year_field: str,
    country_field: str,
    source_field: str,
    min_year: int,
    max_year: int,
    schema: pd.DataFrame,
) -> pd.DataFrame:
    """Resume cobertura temporal por país y fuente."""
    if not campo_existe(schema, country_field) or not campo_existe(schema, source_field):
        return pd.DataFrame(
            [{"warning": "Campo de país o fuente no existe."}]
        )

    year_num = year_num_expr(year_field)

    sql = f"""
    WITH base AS (
        SELECT
            CAST({quote_ident(country_field)} AS TEXT) AS pais,
            CAST({quote_ident(source_field)} AS TEXT) AS fuente,
            {year_num} AS year_num
        FROM {quote_ident(table_name)}
    )
    SELECT
        pais,
        fuente,
        COUNT(*) AS n_registros,
        MIN(CAST(year_num AS INTEGER)) AS anio_min,
        MAX(CAST(year_num AS INTEGER)) AS anio_max,
        COUNT(DISTINCT CAST(year_num AS INTEGER)) AS n_anios_distintos
    FROM base
    WHERE year_num BETWEEN {int(min_year)} AND {int(max_year)}
    GROUP BY pais, fuente
    ORDER BY pais, n_registros DESC;
    """

    return pd.read_sql_query(sql, conn)


def muestra_anios_invalidos(
    conn: sqlite3.Connection,
    table_name: str,
    year_field: str,
    id_field: str,
    country_field: str,
    source_field: str,
    level1_field: str,
    min_year: int,
    max_year: int,
    schema: pd.DataFrame,
    limit: int = 10000,
) -> pd.DataFrame:
    """Extrae una muestra de registros con año problemático."""
    year_num = year_num_expr(year_field)

    select_cols = [
        "ROWID AS sqlite_rowid",
        f"{quote_ident(year_field)} AS anio_original",
        f"{year_text_expr(year_field)} AS anio_texto",
        f"{year_num} AS anio_num",
    ]

    for field in [id_field, country_field, source_field, level1_field]:
        if field and campo_existe(schema, field):
            select_cols.append(f"{quote_ident(field)} AS {quote_ident(field)}")

    sql = f"""
    WITH base AS (
        SELECT
            {", ".join(select_cols)}
        FROM {quote_ident(table_name)}
    )
    SELECT *
    FROM base
    WHERE
        anio_num IS NULL
        OR anio_num < {int(min_year)}
        OR anio_num > {int(max_year)}
    LIMIT {int(limit)};
    """

    return pd.read_sql_query(sql, conn)


# ============================================================
# ANÁLISIS TEMPORAL DE GRUPOS XY
# ============================================================

def analizar_grupos_xy_temporales(
    target_year: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Analiza temporalidad a nivel de grupos XY si existe la base intermedia del Módulo 3B.

    Nota:
    En grupos_xy tenemos anio_min, anio_max y n_anios.
    No necesariamente sabemos si existe un registro exacto de 2020 dentro del grupo.
    Por eso usamos 'rango_incluye_anio_objetivo' como indicador exploratorio.
    """
    if not XY_GROUPS_DB.exists():
        warning = pd.DataFrame(
            [{"warning": "No existe data/interim/03b_multirregistros_xy.sqlite"}]
        )
        return warning, warning

    conn = sqlite3.connect(f"file:{XY_GROUPS_DB}?mode=ro", uri=True)

    try:
        tablas = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table';",
            conn,
        )["name"].tolist()

        if "grupos_xy" not in tablas:
            warning = pd.DataFrame(
                [{"warning": "La base intermedia no contiene tabla grupos_xy."}]
            )
            return warning, warning

        summary_sql = """
        SELECT
            CASE
                WHEN n_anios = 1 THEN 'un_solo_anio'
                WHEN n_anios BETWEEN 2 AND 3 THEN 'dos_a_tres_anios'
                WHEN n_anios BETWEEN 4 AND 6 THEN 'cuatro_a_seis_anios'
                WHEN n_anios BETWEEN 7 AND 10 THEN 'siete_a_diez_anios'
                ELSE 'mas_de_diez_anios'
            END AS categoria_n_anios,
            COUNT(*) AS n_grupos,
            SUM(n_registros) AS n_registros,
            SUM(CASE WHEN n_registros > 1 THEN n_registros - 1 ELSE 0 END) AS exceso_registros,
            AVG(n_anios) AS promedio_n_anios
        FROM grupos_xy
        GROUP BY categoria_n_anios
        ORDER BY n_grupos DESC;
        """

        relevance_sql = f"""
        SELECT
            tipo_grupo_xy,
            CASE
                WHEN CAST(anio_min AS INTEGER) <= {int(target_year)}
                 AND CAST(anio_max AS INTEGER) >= {int(target_year)}
                THEN 'rango_incluye_anio_objetivo'
                WHEN CAST(anio_max AS INTEGER) < {int(target_year)}
                THEN 'rango_anterior_anio_objetivo'
                WHEN CAST(anio_min AS INTEGER) > {int(target_year)}
                THEN 'rango_posterior_anio_objetivo'
                ELSE 'revision_rango_temporal'
            END AS relacion_rango_con_anio_objetivo,
            COUNT(*) AS n_grupos,
            SUM(n_registros) AS n_registros,
            AVG(n_anios) AS promedio_n_anios,
            MIN(CAST(anio_min AS INTEGER)) AS anio_min_global,
            MAX(CAST(anio_max AS INTEGER)) AS anio_max_global
        FROM grupos_xy
        GROUP BY tipo_grupo_xy, relacion_rango_con_anio_objetivo
        ORDER BY tipo_grupo_xy, n_registros DESC;
        """

        return (
            pd.read_sql_query(summary_sql, conn),
            pd.read_sql_query(relevance_sql, conn),
        )

    finally:
        conn.close()


# ============================================================
# FIGURAS
# ============================================================

def generar_figuras(
    year_distribution_df: pd.DataFrame,
    relevance_df: pd.DataFrame,
    coverage_source_df: pd.DataFrame,
) -> None:
    """Genera figuras exploratorias simples."""
    if not year_distribution_df.empty and "anio" in year_distribution_df.columns:
        plt.figure(figsize=(10, 5))
        plt.bar(year_distribution_df["anio"].astype(str), year_distribution_df["n"])
        plt.xlabel("Año")
        plt.ylabel("Número de registros")
        plt.title("Distribución anual de registros")
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "04_year_distribution.png", dpi=200)
        plt.close()

    if not relevance_df.empty and "relevancia_temporal" in relevance_df.columns:
        df = relevance_df.sort_values("n", ascending=True)
        plt.figure(figsize=(9, 5))
        plt.barh(df["relevancia_temporal"], df["n"])
        plt.xlabel("Número de registros")
        plt.ylabel("Categoría temporal")
        plt.title("Relevancia temporal respecto al año objetivo")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "04_temporal_relevance_distribution.png", dpi=200)
        plt.close()

    if not coverage_source_df.empty and "n_registros" in coverage_source_df.columns:
        top = coverage_source_df.head(15).sort_values("n_registros", ascending=True)
        plt.figure(figsize=(9, 6))
        plt.barh(top["grupo"].astype(str), top["n_registros"])
        plt.xlabel("Número de registros")
        plt.ylabel("Fuente")
        plt.title("Principales fuentes por cantidad de registros")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "04_top_sources_by_records.png", dpi=200)
        plt.close()


# ============================================================
# REPORTE
# ============================================================

def generar_reporte(
    gpkg_path: Path,
    table_name: str,
    total_registros: int,
    target_year: int,
    near_window: int,
    quality_df: pd.DataFrame,
    year_distribution_df: pd.DataFrame,
    relevance_df: pd.DataFrame,
    coverage_source_df: pd.DataFrame,
    coverage_country_df: pd.DataFrame,
    xy_temporal_summary_df: pd.DataFrame,
    xy_temporal_relevance_df: pd.DataFrame,
) -> None:
    """Genera reporte Markdown de auditoría temporal."""
    report_path = REPORTS_DIR / "04_auditoria_temporal.md"
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    quality = quality_df.iloc[0].to_dict()

    contenido = "\n".join(
        [
            "# Auditoría temporal",
            "",
            "## Módulo 4",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## Archivo inspeccionado",
            "",
            "```text",
            str(gpkg_path),
            "```",
            "",
            "## Capa auditada",
            "",
            "```text",
            str(table_name),
            "```",
            "",
            "## Parámetros temporales",
            "",
            "| Parámetro | Valor |",
            "|---|---:|",
            f"| Año objetivo | {target_year} |",
            f"| Ventana cercana al año objetivo | ±{near_window} años |",
            f"| Total de registros | {total_registros} |",
            "",
            "## Calidad general del campo Año",
            "",
            dataframe_a_markdown(quality_df),
            "",
            "## Resumen interpretativo",
            "",
            f"- Años nulos: {int(quality.get('n_anio_null', 0))}.",
            f"- Años vacíos: {int(quality.get('n_anio_vacio', 0))}.",
            f"- Años fuera de rango plausible: {int(quality.get('n_anio_fuera_rango_plausible', 0))}.",
            f"- Año mínimo observado: {quality.get('anio_min_observado', '')}.",
            f"- Año máximo observado: {quality.get('anio_max_observado', '')}.",
            f"- Número de años distintos: {int(quality.get('n_anios_distintos', 0))}.",
            "",
            "## Distribución anual",
            "",
            dataframe_a_markdown(year_distribution_df),
            "",
            "## Relevancia temporal respecto al año objetivo",
            "",
            dataframe_a_markdown(relevance_df),
            "",
            "## Cobertura temporal por fuente",
            "",
            dataframe_a_markdown(coverage_source_df.head(40)),
            "",
            "## Cobertura temporal por país",
            "",
            dataframe_a_markdown(coverage_country_df.head(40)),
            "",
            "## Temporalidad en grupos XY",
            "",
            dataframe_a_markdown(xy_temporal_summary_df),
            "",
            "## Relación de rangos temporales de grupos XY con el año objetivo",
            "",
            dataframe_a_markdown(xy_temporal_relevance_df),
            "",
            "## Nota metodológica",
            "",
            "Esta auditoría temporal no modifica el GeoPackage original.",
            "La clasificación temporal sirve para evaluar la aptitud de los registros respecto al año objetivo 2020.",
            "Los registros fuera de la ventana temporal no deben descartarse automáticamente; deben evaluarse según fuente, clase, confiabilidad y objetivo de uso.",
            "",
            "La tabla de relación temporal de grupos XY usa anio_min y anio_max. Por tanto, cuando indica que el rango incluye el año objetivo, no significa necesariamente que exista un registro exacto de 2020 dentro del grupo; significa que el intervalo temporal del grupo cubre 2020.",
            "",
        ]
    )

    report_path.write_text(contenido, encoding="utf-8")


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def main() -> None:
    """Ejecuta auditoría temporal."""
    crear_carpetas_salida()

    config = cargar_yaml(CONFIG_PATH)

    gpkg_rel = config.get("input_data", {}).get("gpkg_file")
    table_name = config.get("input_data", {}).get("gpkg_layer")

    if not gpkg_rel:
        raise ValueError("No se definió input_data.gpkg_file en config/config.yaml.")

    if not table_name:
        raise ValueError("No se definió input_data.gpkg_layer en config/config.yaml.")

    gpkg_path = PROJECT_ROOT / gpkg_rel

    fields_cfg = config.get("fields", {})
    temporal_cfg = config.get("temporal", {})

    id_field = fields_cfg.get("id_primary", "Id")
    year_field = fields_cfg.get("year", "Año")
    country_field = fields_cfg.get("country", "Pais_es")
    source_field = fields_cfg.get("source", "Fuente")
    level1_field = fields_cfg.get("level_1", "Nivel_1")
    level2_field = fields_cfg.get("level_2", "Nivel_2")

    target_year = int(temporal_cfg.get("target_year", 2020))
    near_window = int(temporal_cfg.get("near_window_years", 2))
    min_year = int(temporal_cfg.get("min_plausible_year", 1980))
    max_year = int(temporal_cfg.get("max_plausible_year", 2026))

    conn = abrir_conexion_lectura(gpkg_path)

    try:
        schema = obtener_schema(conn, table_name)

        validar_campos(
            schema,
            [
                year_field,
                country_field,
                source_field,
                level1_field,
                level2_field,
            ],
        )

        total_registros = obtener_total_registros(conn, table_name)

        quality_df = calcular_calidad_temporal(
            conn=conn,
            table_name=table_name,
            year_field=year_field,
            total_registros=total_registros,
            min_year=min_year,
            max_year=max_year,
        )

        year_distribution_df = distribucion_anual(
            conn=conn,
            table_name=table_name,
            year_field=year_field,
            min_year=min_year,
            max_year=max_year,
        )

        relevance_df = distribucion_relevancia_temporal(
            conn=conn,
            table_name=table_name,
            year_field=year_field,
            target_year=target_year,
            near_window=near_window,
            min_year=min_year,
            max_year=max_year,
        )

        year_by_country_df = distribucion_anual_por_campo(
            conn=conn,
            table_name=table_name,
            year_field=year_field,
            group_field=country_field,
            min_year=min_year,
            max_year=max_year,
            schema=schema,
        )

        year_by_source_df = distribucion_anual_por_campo(
            conn=conn,
            table_name=table_name,
            year_field=year_field,
            group_field=source_field,
            min_year=min_year,
            max_year=max_year,
            schema=schema,
        )

        year_by_level1_df = distribucion_anual_por_campo(
            conn=conn,
            table_name=table_name,
            year_field=year_field,
            group_field=level1_field,
            min_year=min_year,
            max_year=max_year,
            schema=schema,
        )

        year_by_level2_df = distribucion_anual_por_campo(
            conn=conn,
            table_name=table_name,
            year_field=year_field,
            group_field=level2_field,
            min_year=min_year,
            max_year=max_year,
            schema=schema,
        )

        coverage_source_df = cobertura_temporal_por_campo(
            conn=conn,
            table_name=table_name,
            year_field=year_field,
            group_field=source_field,
            min_year=min_year,
            max_year=max_year,
            schema=schema,
        )

        coverage_country_df = cobertura_temporal_por_campo(
            conn=conn,
            table_name=table_name,
            year_field=year_field,
            group_field=country_field,
            min_year=min_year,
            max_year=max_year,
            schema=schema,
        )

        coverage_country_source_df = cobertura_temporal_pais_fuente(
            conn=conn,
            table_name=table_name,
            year_field=year_field,
            country_field=country_field,
            source_field=source_field,
            min_year=min_year,
            max_year=max_year,
            schema=schema,
        )

        invalid_sample_df = muestra_anios_invalidos(
            conn=conn,
            table_name=table_name,
            year_field=year_field,
            id_field=id_field,
            country_field=country_field,
            source_field=source_field,
            level1_field=level1_field,
            min_year=min_year,
            max_year=max_year,
            schema=schema,
            limit=10000,
        )

        xy_temporal_summary_df, xy_temporal_relevance_df = analizar_grupos_xy_temporales(
            target_year=target_year,
        )

        temporal_summary_df = pd.DataFrame(
            [
                {
                    "gpkg_path": str(gpkg_path),
                    "table_name": table_name,
                    "total_registros": total_registros,
                    "year_field": year_field,
                    "target_year": target_year,
                    "near_window_years": near_window,
                    "min_plausible_year": min_year,
                    "max_plausible_year": max_year,
                    "n_anio_null": int(quality_df["n_anio_null"].iloc[0]),
                    "n_anio_vacio": int(quality_df["n_anio_vacio"].iloc[0]),
                    "n_anio_fuera_rango_plausible": int(
                        quality_df["n_anio_fuera_rango_plausible"].iloc[0]
                    ),
                    "anio_min_observado": quality_df["anio_min_observado"].iloc[0],
                    "anio_max_observado": quality_df["anio_max_observado"].iloc[0],
                    "n_anios_distintos": int(quality_df["n_anios_distintos"].iloc[0]),
                }
            ]
        )

        # Exportar tablas
        quality_df.to_csv(TABLES_DIR / "04_temporal_quality_summary.csv", index=False, encoding="utf-8-sig")
        year_distribution_df.to_csv(TABLES_DIR / "04_year_distribution.csv", index=False, encoding="utf-8-sig")
        relevance_df.to_csv(TABLES_DIR / "04_temporal_relevance_distribution.csv", index=False, encoding="utf-8-sig")
        year_by_country_df.to_csv(TABLES_DIR / "04_year_by_country.csv", index=False, encoding="utf-8-sig")
        year_by_source_df.to_csv(TABLES_DIR / "04_year_by_source.csv", index=False, encoding="utf-8-sig")
        year_by_level1_df.to_csv(TABLES_DIR / "04_year_by_level1.csv", index=False, encoding="utf-8-sig")
        year_by_level2_df.to_csv(TABLES_DIR / "04_year_by_level2.csv", index=False, encoding="utf-8-sig")
        coverage_source_df.to_csv(TABLES_DIR / "04_temporal_coverage_by_source.csv", index=False, encoding="utf-8-sig")
        coverage_country_df.to_csv(TABLES_DIR / "04_temporal_coverage_by_country.csv", index=False, encoding="utf-8-sig")
        coverage_country_source_df.to_csv(TABLES_DIR / "04_temporal_coverage_by_country_source.csv", index=False, encoding="utf-8-sig")
        invalid_sample_df.to_csv(TABLES_DIR / "04_invalid_year_records_sample.csv", index=False, encoding="utf-8-sig")
        xy_temporal_summary_df.to_csv(TABLES_DIR / "04_xy_temporal_group_summary.csv", index=False, encoding="utf-8-sig")
        xy_temporal_relevance_df.to_csv(TABLES_DIR / "04_xy_temporal_relevance_by_group_type.csv", index=False, encoding="utf-8-sig")
        temporal_summary_df.to_csv(TABLES_DIR / "04_temporal_audit_summary.csv", index=False, encoding="utf-8-sig")

        generar_figuras(
            year_distribution_df=year_distribution_df,
            relevance_df=relevance_df,
            coverage_source_df=coverage_source_df,
        )

        generar_reporte(
            gpkg_path=gpkg_path,
            table_name=table_name,
            total_registros=total_registros,
            target_year=target_year,
            near_window=near_window,
            quality_df=quality_df,
            year_distribution_df=year_distribution_df,
            relevance_df=relevance_df,
            coverage_source_df=coverage_source_df,
            coverage_country_df=coverage_country_df,
            xy_temporal_summary_df=xy_temporal_summary_df,
            xy_temporal_relevance_df=xy_temporal_relevance_df,
        )

        registrar_log(
            f"Módulo 4 ejecutado correctamente. Tabla: {table_name}. "
            f"Campo temporal: {year_field}. Año objetivo: {target_year}."
        )

        print("Módulo 4 ejecutado correctamente.")
        print(f"GeoPackage: {gpkg_path}")
        print(f"Capa auditada: {table_name}")
        print(f"Registros: {total_registros}")
        print(f"Campo temporal: {year_field}")
        print(f"Año objetivo: {target_year}")
        print("Salidas generadas en outputs/tables, outputs/figures y outputs/reports.")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        registrar_log("Error durante la ejecución del Módulo 4.")
        traceback.print_exc()
        raise
