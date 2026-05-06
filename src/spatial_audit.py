"""
Módulo 3 - Auditoría espacial inicial del GeoPackage.

Este script realiza una auditoría espacial inicial de la capa principal del GeoPackage
sin modificar los datos originales.

Objetivos:
- Revisar referencia espacial declarada en el GeoPackage.
- Confirmar campos de coordenadas.
- Evaluar rangos globales y regionales de Longitud/Latitud.
- Identificar coordenadas nulas, vacías o fuera de rango.
- Identificar duplicados por coordenadas exactas.
- Identificar duplicados por coordenadas redondeadas.
- Resumir distribución espacial por país, fuente y clase.
- Calcular bounding box global y por país.
- Generar una muestra de puntos para visualización.
- Generar figuras exploratorias simples.
- Generar reporte Markdown.

Salidas:
- outputs/tables/03_spatial_reference.csv
- outputs/tables/03_coordinate_fields_check.csv
- outputs/tables/03_bbox_global.csv
- outputs/tables/03_coordinate_quality_summary.csv
- outputs/tables/03_coordinate_invalid_records_sample.csv
- outputs/tables/03_duplicate_xy_exact_summary.csv
- outputs/tables/03_duplicate_xy_exact_top.csv
- outputs/tables/03_duplicate_xy_rounded_summary.csv
- outputs/tables/03_duplicate_xy_rounded_top.csv
- outputs/tables/03_distribution_by_country.csv
- outputs/tables/03_distribution_by_country_source.csv
- outputs/tables/03_distribution_by_country_level1.csv
- outputs/tables/03_bbox_by_country.csv
- outputs/tables/03_sample_points_for_map.csv
- outputs/tables/03_spatial_audit_summary.csv
- outputs/figures/03_mapa_muestra_puntos.png
- outputs/figures/03_hist_longitud.png
- outputs/figures/03_hist_latitud.png
- outputs/figures/03_top_paises.png
- outputs/reports/03_auditoria_espacial.md
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
    log_path = LOGS_DIR / "auditoria.log"
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"[{fecha}] {mensaje}\n")


def cargar_yaml(path: Path) -> dict:
    """Carga un archivo YAML."""
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo requerido: {path}")

    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if data is None:
        return {}

    return data


def quote_ident(identifier: str) -> str:
    """Protege nombres de campos o tablas para consultas SQL."""
    return '"' + str(identifier).replace('"', '""') + '"'


def dataframe_a_markdown(df: pd.DataFrame) -> str:
    """Convierte un DataFrame a Markdown de forma segura."""
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


def abrir_conexion(gpkg_path: Path) -> sqlite3.Connection:
    """Abre conexión SQLite al GeoPackage."""
    if not gpkg_path.exists():
        raise FileNotFoundError(f"No existe el GeoPackage: {gpkg_path}")

    return sqlite3.connect(gpkg_path)


def obtener_tablas_sqlite(conn: sqlite3.Connection) -> list[str]:
    """Lista tablas existentes en el GeoPackage/SQLite."""
    sql = """
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    ORDER BY name;
    """
    return pd.read_sql_query(sql, conn)["name"].tolist()


def validar_tabla(conn: sqlite3.Connection, table_name: str) -> None:
    """Verifica que la tabla/capa exista."""
    tablas = obtener_tablas_sqlite(conn)

    if table_name not in tablas:
        raise ValueError(
            f"La tabla/capa '{table_name}' no existe en el GeoPackage.\n"
            f"Tablas disponibles: {tablas}"
        )


def obtener_schema(conn: sqlite3.Connection, table_name: str) -> pd.DataFrame:
    """Obtiene esquema de la tabla principal."""
    sql = f"PRAGMA table_info({quote_ident(table_name)});"
    schema = pd.read_sql_query(sql, conn)

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


def obtener_total_registros(conn: sqlite3.Connection, table_name: str) -> int:
    """Cuenta registros de la tabla principal."""
    sql = f"SELECT COUNT(*) AS n FROM {quote_ident(table_name)};"
    return int(pd.read_sql_query(sql, conn)["n"].iloc[0])


# ============================================================
# REFERENCIA ESPACIAL
# ============================================================

def obtener_referencia_espacial(conn: sqlite3.Connection, table_name: str) -> pd.DataFrame:
    """Obtiene referencia espacial declarada en gpkg_geometry_columns."""
    try:
        sql = """
        SELECT
            g.table_name,
            g.column_name,
            g.geometry_type_name,
            g.srs_id,
            s.srs_name,
            s.organization,
            s.organization_coordsys_id,
            s.definition
        FROM gpkg_geometry_columns AS g
        LEFT JOIN gpkg_spatial_ref_sys AS s
        ON g.srs_id = s.srs_id
        WHERE g.table_name = ?;
        """

        df = pd.read_sql_query(sql, conn, params=[table_name])

        if df.empty:
            return pd.DataFrame(
                [
                    {
                        "table_name": table_name,
                        "column_name": "",
                        "geometry_type_name": "",
                        "srs_id": "",
                        "srs_name": "",
                        "organization": "",
                        "organization_coordsys_id": "",
                        "definition": "",
                        "warning": "No se encontró registro en gpkg_geometry_columns.",
                    }
                ]
            )

        df["warning"] = ""

        return df

    except Exception as error:
        return pd.DataFrame(
            [
                {
                    "table_name": table_name,
                    "column_name": "",
                    "geometry_type_name": "",
                    "srs_id": "",
                    "srs_name": "",
                    "organization": "",
                    "organization_coordsys_id": "",
                    "definition": "",
                    "warning": str(error),
                }
            ]
        )


# ============================================================
# COORDENADAS Y CALIDAD ESPACIAL
# ============================================================

def construir_expr_coordenada(field_name: str) -> str:
    """
    Construye expresión SQL para transformar coordenada a número.

    Nota:
    SQLite convierte textos no numéricos a 0. En esta fase se asume que Longitud/Latitud
    son campos numéricos o textos numéricos. La auditoría estructural ayuda a verificar tipos.
    """
    field_sql = quote_ident(field_name)
    return f"CAST(NULLIF(TRIM(CAST({field_sql} AS TEXT)), '') AS REAL)"


def verificar_campos_coordenadas(
    schema: pd.DataFrame,
    lon_field: str,
    lat_field: str,
) -> pd.DataFrame:
    """Verifica si existen los campos Longitud/Latitud."""
    rows = []

    for campo, rol in [(lon_field, "longitud"), (lat_field, "latitud")]:
        existe = campo_existe(schema, campo)

        tipo = ""
        if existe:
            tipo = schema.loc[schema["field_name"] == campo, "sqlite_type"].iloc[0]

        rows.append(
            {
                "rol": rol,
                "field_name": campo,
                "presente": existe,
                "sqlite_type": tipo,
            }
        )

    return pd.DataFrame(rows)


def calcular_bbox_global(
    conn: sqlite3.Connection,
    table_name: str,
    lon_field: str,
    lat_field: str,
) -> pd.DataFrame:
    """Calcula bounding box global usando campos de coordenadas."""
    lon_expr = construir_expr_coordenada(lon_field)
    lat_expr = construir_expr_coordenada(lat_field)

    sql = f"""
    WITH coords AS (
        SELECT
            {lon_expr} AS lon,
            {lat_expr} AS lat
        FROM {quote_ident(table_name)}
    )
    SELECT
        COUNT(*) AS n_total,
        MIN(lon) AS lon_min,
        MAX(lon) AS lon_max,
        MIN(lat) AS lat_min,
        MAX(lat) AS lat_max,
        AVG(lon) AS lon_mean,
        AVG(lat) AS lat_mean
    FROM coords;
    """

    return pd.read_sql_query(sql, conn)


def evaluar_calidad_coordenadas(
    conn: sqlite3.Connection,
    table_name: str,
    lon_field: str,
    lat_field: str,
    regional_bounds: dict,
) -> pd.DataFrame:
    """Evalúa nulos, vacíos y coordenadas fuera de rango."""
    lon_sql = quote_ident(lon_field)
    lat_sql = quote_ident(lat_field)

    lon_expr = construir_expr_coordenada(lon_field)
    lat_expr = construir_expr_coordenada(lat_field)

    lon_min_reg = regional_bounds["lon_min"]
    lon_max_reg = regional_bounds["lon_max"]
    lat_min_reg = regional_bounds["lat_min"]
    lat_max_reg = regional_bounds["lat_max"]

    sql = f"""
    WITH coords AS (
        SELECT
            {lon_sql} AS lon_original,
            {lat_sql} AS lat_original,
            {lon_expr} AS lon,
            {lat_expr} AS lat
        FROM {quote_ident(table_name)}
    )
    SELECT
        COUNT(*) AS n_total,

        SUM(CASE WHEN lon_original IS NULL THEN 1 ELSE 0 END) AS n_lon_null,
        SUM(CASE WHEN lat_original IS NULL THEN 1 ELSE 0 END) AS n_lat_null,

        SUM(
            CASE
                WHEN lon_original IS NOT NULL
                AND TRIM(CAST(lon_original AS TEXT)) = ''
                THEN 1 ELSE 0
            END
        ) AS n_lon_vacia,

        SUM(
            CASE
                WHEN lat_original IS NOT NULL
                AND TRIM(CAST(lat_original AS TEXT)) = ''
                THEN 1 ELSE 0
            END
        ) AS n_lat_vacia,

        SUM(
            CASE
                WHEN lon < -180 OR lon > 180 OR lat < -90 OR lat > 90
                THEN 1 ELSE 0
            END
        ) AS n_fuera_rango_global,

        SUM(
            CASE
                WHEN lon < {lon_min_reg} OR lon > {lon_max_reg}
                  OR lat < {lat_min_reg} OR lat > {lat_max_reg}
                THEN 1 ELSE 0
            END
        ) AS n_fuera_rango_regional_amplio

    FROM coords;
    """

    df = pd.read_sql_query(sql, conn)

    total = int(df["n_total"].iloc[0])

    for campo in [
        "n_lon_null",
        "n_lat_null",
        "n_lon_vacia",
        "n_lat_vacia",
        "n_fuera_rango_global",
        "n_fuera_rango_regional_amplio",
    ]:
        df[f"pct_{campo.replace('n_', '')}"] = round((df[campo] / total) * 100, 6)

    df["regional_bounds"] = str(regional_bounds)

    return df


def extraer_muestra_coordenadas_invalidas(
    conn: sqlite3.Connection,
    table_name: str,
    lon_field: str,
    lat_field: str,
    id_field: str,
    country_field: str,
    source_field: str,
    level1_field: str,
    regional_bounds: dict,
    limit: int = 10000,
) -> pd.DataFrame:
    """Extrae muestra de registros con coordenadas problemáticas."""
    schema = obtener_schema(conn, table_name)
    existing_fields = set(schema["field_name"].tolist())

    optional_fields = []
    for field in [id_field, country_field, source_field, level1_field]:
        if field and field in existing_fields:
            optional_fields.append(field)

    select_optional = ""
    if optional_fields:
        select_optional = ", " + ", ".join(quote_ident(f) for f in optional_fields)

    lon_expr = construir_expr_coordenada(lon_field)
    lat_expr = construir_expr_coordenada(lat_field)

    lon_min_reg = regional_bounds["lon_min"]
    lon_max_reg = regional_bounds["lon_max"]
    lat_min_reg = regional_bounds["lat_min"]
    lat_max_reg = regional_bounds["lat_max"]

    sql = f"""
    WITH coords AS (
        SELECT
            ROWID AS sqlite_rowid
            {select_optional},
            {quote_ident(lon_field)} AS lon_original,
            {quote_ident(lat_field)} AS lat_original,
            {lon_expr} AS lon,
            {lat_expr} AS lat
        FROM {quote_ident(table_name)}
    )
    SELECT *
    FROM coords
    WHERE
        lon_original IS NULL
        OR lat_original IS NULL
        OR TRIM(CAST(lon_original AS TEXT)) = ''
        OR TRIM(CAST(lat_original AS TEXT)) = ''
        OR lon < -180 OR lon > 180 OR lat < -90 OR lat > 90
        OR lon < {lon_min_reg} OR lon > {lon_max_reg}
        OR lat < {lat_min_reg} OR lat > {lat_max_reg}
    LIMIT {int(limit)};
    """

    try:
        return pd.read_sql_query(sql, conn)
    except Exception as error:
        return pd.DataFrame([{"error": str(error)}])


# ============================================================
# DUPLICADOS DE COORDENADAS
# ============================================================

def calcular_duplicados_xy(
    conn: sqlite3.Connection,
    table_name: str,
    lon_field: str,
    lat_field: str,
    precision: int | None = None,
    top_limit: int = 10000,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Calcula duplicados por coordenadas exactas o redondeadas.

    Si precision es None, usa coordenadas numéricas exactas.
    Si precision es entero, usa ROUND(lon, precision), ROUND(lat, precision).
    """
    lon_expr = construir_expr_coordenada(lon_field)
    lat_expr = construir_expr_coordenada(lat_field)

    if precision is None:
        lon_group = "lon"
        lat_group = "lat"
        tipo = "exacto"
    else:
        lon_group = f"ROUND(lon, {int(precision)})"
        lat_group = f"ROUND(lat, {int(precision)})"
        tipo = f"redondeado_{precision}_decimales"

    sql_summary = f"""
    WITH coords AS (
        SELECT
            {lon_expr} AS lon,
            {lat_expr} AS lat
        FROM {quote_ident(table_name)}
        WHERE {quote_ident(lon_field)} IS NOT NULL
          AND {quote_ident(lat_field)} IS NOT NULL
          AND TRIM(CAST({quote_ident(lon_field)} AS TEXT)) != ''
          AND TRIM(CAST({quote_ident(lat_field)} AS TEXT)) != ''
    ),
    grupos AS (
        SELECT
            {lon_group} AS lon_group,
            {lat_group} AS lat_group,
            COUNT(*) AS n
        FROM coords
        GROUP BY lon_group, lat_group
        HAVING COUNT(*) > 1
    )
    SELECT
        '{tipo}' AS tipo_duplicado,
        COUNT(*) AS grupos_duplicados,
        COALESCE(SUM(n), 0) AS registros_en_grupos_duplicados,
        COALESCE(SUM(n) - COUNT(*), 0) AS exceso_registros_duplicados,
        COALESCE(MAX(n), 0) AS max_registros_misma_coordenada
    FROM grupos;
    """

    sql_top = f"""
    WITH coords AS (
        SELECT
            {lon_expr} AS lon,
            {lat_expr} AS lat
        FROM {quote_ident(table_name)}
        WHERE {quote_ident(lon_field)} IS NOT NULL
          AND {quote_ident(lat_field)} IS NOT NULL
          AND TRIM(CAST({quote_ident(lon_field)} AS TEXT)) != ''
          AND TRIM(CAST({quote_ident(lat_field)} AS TEXT)) != ''
    )
    SELECT
        '{tipo}' AS tipo_duplicado,
        {lon_group} AS lon,
        {lat_group} AS lat,
        COUNT(*) AS n
    FROM coords
    GROUP BY lon, lat
    HAVING COUNT(*) > 1
    ORDER BY n DESC
    LIMIT {int(top_limit)};
    """

    summary_df = pd.read_sql_query(sql_summary, conn)
    top_df = pd.read_sql_query(sql_top, conn)

    return summary_df, top_df


# ============================================================
# DISTRIBUCIÓN ESPACIAL POR ATRIBUTOS
# ============================================================

def distribucion_por_campo(
    conn: sqlite3.Connection,
    table_name: str,
    field_name: str,
    schema: pd.DataFrame,
) -> pd.DataFrame:
    """Calcula distribución por un campo categórico."""
    if not campo_existe(schema, field_name):
        return pd.DataFrame(
            [{"field_name": field_name, "warning": "Campo no existe en la tabla."}]
        )

    sql = f"""
    SELECT
        CAST({quote_ident(field_name)} AS TEXT) AS valor,
        COUNT(*) AS n
    FROM {quote_ident(table_name)}
    GROUP BY {quote_ident(field_name)}
    ORDER BY n DESC;
    """

    df = pd.read_sql_query(sql, conn)
    df.insert(0, "field_name", field_name)

    total = df["n"].sum()
    df["pct"] = round((df["n"] / total) * 100, 6)

    return df


def distribucion_por_dos_campos(
    conn: sqlite3.Connection,
    table_name: str,
    field_a: str,
    field_b: str,
    schema: pd.DataFrame,
) -> pd.DataFrame:
    """Calcula distribución cruzada por dos campos categóricos."""
    if not campo_existe(schema, field_a) or not campo_existe(schema, field_b):
        return pd.DataFrame(
            [
                {
                    "field_a": field_a,
                    "field_b": field_b,
                    "warning": "Uno o ambos campos no existen en la tabla.",
                }
            ]
        )

    sql = f"""
    SELECT
        CAST({quote_ident(field_a)} AS TEXT) AS {quote_ident(field_a)},
        CAST({quote_ident(field_b)} AS TEXT) AS {quote_ident(field_b)},
        COUNT(*) AS n
    FROM {quote_ident(table_name)}
    GROUP BY {quote_ident(field_a)}, {quote_ident(field_b)}
    ORDER BY n DESC;
    """

    return pd.read_sql_query(sql, conn)


def bbox_por_pais(
    conn: sqlite3.Connection,
    table_name: str,
    lon_field: str,
    lat_field: str,
    country_field: str,
    schema: pd.DataFrame,
) -> pd.DataFrame:
    """Calcula bounding box por país."""
    if not campo_existe(schema, country_field):
        return pd.DataFrame(
            [{"country_field": country_field, "warning": "Campo de país no existe."}]
        )

    lon_expr = construir_expr_coordenada(lon_field)
    lat_expr = construir_expr_coordenada(lat_field)

    sql = f"""
    WITH coords AS (
        SELECT
            CAST({quote_ident(country_field)} AS TEXT) AS pais,
            {lon_expr} AS lon,
            {lat_expr} AS lat
        FROM {quote_ident(table_name)}
    )
    SELECT
        pais,
        COUNT(*) AS n,
        MIN(lon) AS lon_min,
        MAX(lon) AS lon_max,
        MIN(lat) AS lat_min,
        MAX(lat) AS lat_max
    FROM coords
    GROUP BY pais
    ORDER BY n DESC;
    """

    return pd.read_sql_query(sql, conn)


# ============================================================
# MUESTRA Y FIGURAS
# ============================================================

def crear_muestra_puntos(
    conn: sqlite3.Connection,
    table_name: str,
    lon_field: str,
    lat_field: str,
    country_field: str,
    source_field: str,
    level1_field: str,
    total_registros: int,
    sample_size: int = 200000,
) -> pd.DataFrame:
    """
    Crea una muestra sistemática aproximada usando ROWID.

    Evita ORDER BY RANDOM(), que puede ser costoso en tablas grandes.
    """
    schema = obtener_schema(conn, table_name)
    existing_fields = set(schema["field_name"].tolist())

    optional_fields = []
    for field in [country_field, source_field, level1_field]:
        if field and field in existing_fields:
            optional_fields.append(field)

    select_optional = ""
    if optional_fields:
        select_optional = ", " + ", ".join(quote_ident(f) for f in optional_fields)

    step = max(int(total_registros / sample_size), 1)

    lon_expr = construir_expr_coordenada(lon_field)
    lat_expr = construir_expr_coordenada(lat_field)

    sql = f"""
    SELECT
        ROWID AS sqlite_rowid,
        {lon_expr} AS lon,
        {lat_expr} AS lat
        {select_optional}
    FROM {quote_ident(table_name)}
    WHERE
        {quote_ident(lon_field)} IS NOT NULL
        AND {quote_ident(lat_field)} IS NOT NULL
        AND TRIM(CAST({quote_ident(lon_field)} AS TEXT)) != ''
        AND TRIM(CAST({quote_ident(lat_field)} AS TEXT)) != ''
        AND (ROWID % {step}) = 0
    LIMIT {int(sample_size)};
    """

    try:
        return pd.read_sql_query(sql, conn)
    except Exception as error:
        return pd.DataFrame([{"error": str(error)}])


def generar_figuras(sample_df: pd.DataFrame, dist_country_df: pd.DataFrame) -> None:
    """Genera figuras exploratorias simples."""
    if sample_df.empty or "error" in sample_df.columns:
        return

    if "lon" not in sample_df.columns or "lat" not in sample_df.columns:
        return

    # Mapa simple de muestra de puntos
    plt.figure(figsize=(8, 8))
    plt.scatter(sample_df["lon"], sample_df["lat"], s=1, alpha=0.3)
    plt.xlabel("Longitud")
    plt.ylabel("Latitud")
    plt.title("Muestra espacial de puntos de control")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "03_mapa_muestra_puntos.png", dpi=200)
    plt.close()

    # Histograma de longitud
    plt.figure(figsize=(8, 5))
    plt.hist(sample_df["lon"].dropna(), bins=60)
    plt.xlabel("Longitud")
    plt.ylabel("Frecuencia")
    plt.title("Distribución de longitud en muestra")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "03_hist_longitud.png", dpi=200)
    plt.close()

    # Histograma de latitud
    plt.figure(figsize=(8, 5))
    plt.hist(sample_df["lat"].dropna(), bins=60)
    plt.xlabel("Latitud")
    plt.ylabel("Frecuencia")
    plt.title("Distribución de latitud en muestra")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "03_hist_latitud.png", dpi=200)
    plt.close()

    # Barras top países
    if not dist_country_df.empty and "valor" in dist_country_df.columns and "n" in dist_country_df.columns:
        top = dist_country_df.head(15).copy()

        plt.figure(figsize=(9, 6))
        plt.barh(top["valor"].astype(str), top["n"])
        plt.xlabel("Número de registros")
        plt.ylabel("País")
        plt.title("Distribución de registros por país")
        plt.gca().invert_yaxis()
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "03_top_paises.png", dpi=200)
        plt.close()


# ============================================================
# REPORTE
# ============================================================

def generar_reporte(
    gpkg_path: Path,
    table_name: str,
    total_registros: int,
    spatial_ref_df: pd.DataFrame,
    coord_check_df: pd.DataFrame,
    bbox_global_df: pd.DataFrame,
    coord_quality_df: pd.DataFrame,
    dup_exact_summary_df: pd.DataFrame,
    dup_round_summary_df: pd.DataFrame,
    dist_country_df: pd.DataFrame,
    bbox_country_df: pd.DataFrame,
) -> None:
    """Genera reporte Markdown del Módulo 3."""
    report_path = REPORTS_DIR / "03_auditoria_espacial.md"
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    n_total = total_registros

    n_fuera_global = int(coord_quality_df["n_fuera_rango_global"].iloc[0])
    n_fuera_regional = int(coord_quality_df["n_fuera_rango_regional_amplio"].iloc[0])

    exact_groups = int(dup_exact_summary_df["grupos_duplicados"].iloc[0])
    exact_records = int(dup_exact_summary_df["registros_en_grupos_duplicados"].iloc[0])

    round_groups = int(dup_round_summary_df["grupos_duplicados"].iloc[0])
    round_records = int(dup_round_summary_df["registros_en_grupos_duplicados"].iloc[0])

    contenido = "\n".join(
        [
            "# Auditoría espacial inicial",
            "",
            "## Módulo 3",
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
            "## Resumen general",
            "",
            "| Elemento | Valor |",
            "|---|---:|",
            f"| Total de registros | {n_total} |",
            f"| Registros fuera de rango global | {n_fuera_global} |",
            f"| Registros fuera de rango regional amplio | {n_fuera_regional} |",
            f"| Grupos duplicados XY exactos | {exact_groups} |",
            f"| Registros en grupos duplicados XY exactos | {exact_records} |",
            f"| Grupos duplicados XY redondeados | {round_groups} |",
            f"| Registros en grupos duplicados XY redondeados | {round_records} |",
            "",
            "## Referencia espacial declarada",
            "",
            dataframe_a_markdown(spatial_ref_df),
            "",
            "## Verificación de campos de coordenadas",
            "",
            dataframe_a_markdown(coord_check_df),
            "",
            "## Bounding box global",
            "",
            dataframe_a_markdown(bbox_global_df),
            "",
            "## Calidad general de coordenadas",
            "",
            dataframe_a_markdown(coord_quality_df),
            "",
            "## Duplicados por coordenadas exactas",
            "",
            dataframe_a_markdown(dup_exact_summary_df),
            "",
            "## Duplicados por coordenadas redondeadas",
            "",
            dataframe_a_markdown(dup_round_summary_df),
            "",
            "## Distribución por país",
            "",
            dataframe_a_markdown(dist_country_df.head(20)),
            "",
            "## Bounding box por país",
            "",
            dataframe_a_markdown(bbox_country_df.head(20)),
            "",
            "## Nota metodológica",
            "",
            "Esta auditoría espacial no modifica el GeoPackage original.",
            "Los duplicados espaciales no deben eliminarse automáticamente.",
            "Primero deben cruzarse con fuente, clase, año, confiabilidad y duplicados atributivos.",
            "",
            "El rango regional amplio se usa solo como alerta exploratoria, no como criterio definitivo de descarte.",
            "",
        ]
    )

    with open(report_path, "w", encoding="utf-8") as file:
        file.write(contenido)


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def main() -> None:
    """Ejecuta auditoría espacial inicial."""
    crear_carpetas_salida()

    config = cargar_yaml(CONFIG_PATH)

    gpkg_rel = config.get("input_data", {}).get("gpkg_file")
    table_name = config.get("input_data", {}).get("gpkg_layer")

    if not gpkg_rel:
        raise ValueError("No se definió input_data.gpkg_file en config/config.yaml.")

    if not table_name:
        raise ValueError(
            "No se definió input_data.gpkg_layer en config/config.yaml. "
            "Debe ser: Puntos_control_mesoamerica"
        )

    gpkg_path = PROJECT_ROOT / gpkg_rel

    # Campos base
    fields_cfg = config.get("fields", {})
    lon_field = fields_cfg.get("longitude", "Longitud")
    lat_field = fields_cfg.get("latitude", "Latitud")
    id_field = fields_cfg.get("id_primary", "Id")
    country_field = fields_cfg.get("country", "Pais_es")
    source_field = fields_cfg.get("source", "Fuente")
    level1_field = fields_cfg.get("level_1", "Nivel_1")

    # Rango regional amplio de alerta para Mesoamérica
    regional_bounds = config.get("spatial", {}).get(
        "regional_bounds",
        {
            "lon_min": -120,
            "lon_max": -75,
            "lat_min": 5,
            "lat_max": 25,
        },
    )

    coordinate_precision = int(config.get("spatial", {}).get("coordinate_precision", 6))

    conn = abrir_conexion(gpkg_path)

    try:
        validar_tabla(conn, table_name)

        total_registros = obtener_total_registros(conn, table_name)
        schema = obtener_schema(conn, table_name)

        coord_check_df = verificar_campos_coordenadas(schema, lon_field, lat_field)

        if not coord_check_df["presente"].all():
            raise ValueError(
                "No se encontraron todos los campos de coordenadas requeridos. "
                f"Revisión: {coord_check_df.to_dict(orient='records')}"
            )

        spatial_ref_df = obtener_referencia_espacial(conn, table_name)

        bbox_global_df = calcular_bbox_global(
            conn=conn,
            table_name=table_name,
            lon_field=lon_field,
            lat_field=lat_field,
        )

        coord_quality_df = evaluar_calidad_coordenadas(
            conn=conn,
            table_name=table_name,
            lon_field=lon_field,
            lat_field=lat_field,
            regional_bounds=regional_bounds,
        )

        invalid_sample_df = extraer_muestra_coordenadas_invalidas(
            conn=conn,
            table_name=table_name,
            lon_field=lon_field,
            lat_field=lat_field,
            id_field=id_field,
            country_field=country_field,
            source_field=source_field,
            level1_field=level1_field,
            regional_bounds=regional_bounds,
            limit=10000,
        )

        dup_exact_summary_df, dup_exact_top_df = calcular_duplicados_xy(
            conn=conn,
            table_name=table_name,
            lon_field=lon_field,
            lat_field=lat_field,
            precision=None,
            top_limit=10000,
        )

        dup_round_summary_df, dup_round_top_df = calcular_duplicados_xy(
            conn=conn,
            table_name=table_name,
            lon_field=lon_field,
            lat_field=lat_field,
            precision=coordinate_precision,
            top_limit=10000,
        )

        dist_country_df = distribucion_por_campo(
            conn=conn,
            table_name=table_name,
            field_name=country_field,
            schema=schema,
        )

        dist_country_source_df = distribucion_por_dos_campos(
            conn=conn,
            table_name=table_name,
            field_a=country_field,
            field_b=source_field,
            schema=schema,
        )

        dist_country_level1_df = distribucion_por_dos_campos(
            conn=conn,
            table_name=table_name,
            field_a=country_field,
            field_b=level1_field,
            schema=schema,
        )

        bbox_country_df = bbox_por_pais(
            conn=conn,
            table_name=table_name,
            lon_field=lon_field,
            lat_field=lat_field,
            country_field=country_field,
            schema=schema,
        )

        sample_points_df = crear_muestra_puntos(
            conn=conn,
            table_name=table_name,
            lon_field=lon_field,
            lat_field=lat_field,
            country_field=country_field,
            source_field=source_field,
            level1_field=level1_field,
            total_registros=total_registros,
            sample_size=200000,
        )

        generar_figuras(
            sample_df=sample_points_df,
            dist_country_df=dist_country_df,
        )

        spatial_summary_df = pd.DataFrame(
            [
                {
                    "gpkg_path": str(gpkg_path),
                    "table_name": table_name,
                    "total_registros": total_registros,
                    "lon_field": lon_field,
                    "lat_field": lat_field,
                    "coordinate_precision": coordinate_precision,
                    "n_fuera_rango_global": int(coord_quality_df["n_fuera_rango_global"].iloc[0]),
                    "n_fuera_rango_regional_amplio": int(
                        coord_quality_df["n_fuera_rango_regional_amplio"].iloc[0]
                    ),
                    "grupos_duplicados_xy_exactos": int(
                        dup_exact_summary_df["grupos_duplicados"].iloc[0]
                    ),
                    "registros_en_duplicados_xy_exactos": int(
                        dup_exact_summary_df["registros_en_grupos_duplicados"].iloc[0]
                    ),
                    "grupos_duplicados_xy_redondeados": int(
                        dup_round_summary_df["grupos_duplicados"].iloc[0]
                    ),
                    "registros_en_duplicados_xy_redondeados": int(
                        dup_round_summary_df["registros_en_grupos_duplicados"].iloc[0]
                    ),
                }
            ]
        )

        # Exportar tablas
        spatial_ref_df.to_csv(
            TABLES_DIR / "03_spatial_reference.csv",
            index=False,
            encoding="utf-8-sig",
        )

        coord_check_df.to_csv(
            TABLES_DIR / "03_coordinate_fields_check.csv",
            index=False,
            encoding="utf-8-sig",
        )

        bbox_global_df.to_csv(
            TABLES_DIR / "03_bbox_global.csv",
            index=False,
            encoding="utf-8-sig",
        )

        coord_quality_df.to_csv(
            TABLES_DIR / "03_coordinate_quality_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )

        invalid_sample_df.to_csv(
            TABLES_DIR / "03_coordinate_invalid_records_sample.csv",
            index=False,
            encoding="utf-8-sig",
        )

        dup_exact_summary_df.to_csv(
            TABLES_DIR / "03_duplicate_xy_exact_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )

        dup_exact_top_df.to_csv(
            TABLES_DIR / "03_duplicate_xy_exact_top.csv",
            index=False,
            encoding="utf-8-sig",
        )

        dup_round_summary_df.to_csv(
            TABLES_DIR / "03_duplicate_xy_rounded_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )

        dup_round_top_df.to_csv(
            TABLES_DIR / "03_duplicate_xy_rounded_top.csv",
            index=False,
            encoding="utf-8-sig",
        )

        dist_country_df.to_csv(
            TABLES_DIR / "03_distribution_by_country.csv",
            index=False,
            encoding="utf-8-sig",
        )

        dist_country_source_df.to_csv(
            TABLES_DIR / "03_distribution_by_country_source.csv",
            index=False,
            encoding="utf-8-sig",
        )

        dist_country_level1_df.to_csv(
            TABLES_DIR / "03_distribution_by_country_level1.csv",
            index=False,
            encoding="utf-8-sig",
        )

        bbox_country_df.to_csv(
            TABLES_DIR / "03_bbox_by_country.csv",
            index=False,
            encoding="utf-8-sig",
        )

        sample_points_df.to_csv(
            TABLES_DIR / "03_sample_points_for_map.csv",
            index=False,
            encoding="utf-8-sig",
        )

        spatial_summary_df.to_csv(
            TABLES_DIR / "03_spatial_audit_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )

        generar_reporte(
            gpkg_path=gpkg_path,
            table_name=table_name,
            total_registros=total_registros,
            spatial_ref_df=spatial_ref_df,
            coord_check_df=coord_check_df,
            bbox_global_df=bbox_global_df,
            coord_quality_df=coord_quality_df,
            dup_exact_summary_df=dup_exact_summary_df,
            dup_round_summary_df=dup_round_summary_df,
            dist_country_df=dist_country_df,
            bbox_country_df=bbox_country_df,
        )

        registrar_log(
            f"Módulo 3 ejecutado correctamente. Tabla: {table_name}. "
            f"Registros: {total_registros}. "
            f"Duplicados XY exactos: {spatial_summary_df['grupos_duplicados_xy_exactos'].iloc[0]} grupos."
        )

        print("Módulo 3 ejecutado correctamente.")
        print(f"GeoPackage: {gpkg_path}")
        print(f"Capa auditada: {table_name}")
        print(f"Registros: {total_registros}")
        print(f"Duplicados XY exactos: {spatial_summary_df['grupos_duplicados_xy_exactos'].iloc[0]}")
        print(f"Duplicados XY redondeados: {spatial_summary_df['grupos_duplicados_xy_redondeados'].iloc[0]}")
        print("Salidas generadas en outputs/tables, outputs/figures y outputs/reports.")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        registrar_log("Error durante la ejecución del Módulo 3.")
        traceback.print_exc()
        raise