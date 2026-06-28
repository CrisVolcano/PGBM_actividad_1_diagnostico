"""
Módulo 3B - Caracterización de multirregistros espaciales XY.

Este script caracteriza los grupos de coordenadas Longitud-Latitud de la capa principal
del GeoPackage sin modificar los datos originales.

Objetivos:
- Crear una tabla de grupos XY únicos.
- Contar registros por coordenada.
- Identificar si cada grupo tiene una o varias fuentes.
- Identificar si cada grupo tiene uno o varios años.
- Identificar si cada grupo tiene una o varias clases Nivel_1/Nivel_2.
- Clasificar los grupos XY según redundancia, coincidencia, multitemporalidad o conflicto.
- Generar tablas resumidas y reporte Markdown.

Salidas principales:
- data/interim/03b_multirregistros_xy.sqlite
- outputs/tables/03b_resumen_ejecutivo.csv
- outputs/tables/03b_distribucion_tipo_grupo_xy.csv
- outputs/tables/03b_distribucion_tamano_grupo_xy.csv
- outputs/tables/03b_tipo_grupo_por_pais.csv
- outputs/tables/03b_top_grupos_mas_registros.csv
- outputs/tables/03b_top_conflictos_tematicos_xy.csv
- outputs/tables/03b_top_multitemporales_xy.csv
- outputs/reports/03b_caracterizacion_multirregistros_xy.md
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

DATA_INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
TABLES_DIR = PROJECT_ROOT / "outputs" / "tables"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"
LOGS_DIR = PROJECT_ROOT / "logs"

INTERIM_DB_PATH = DATA_INTERIM_DIR / "03b_multirregistros_xy.sqlite"


# ============================================================
# FUNCIONES GENERALES
# ============================================================

def crear_carpetas_salida() -> None:
    """Crea carpetas de salida si no existen."""
    DATA_INTERIM_DIR.mkdir(parents=True, exist_ok=True)
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

    return data or {}


def quote_ident(identifier: str) -> str:
    """Protege nombres de campos o tablas para consultas SQL."""
    return '"' + str(identifier).replace('"', '""') + '"'


def dataframe_a_markdown(df: pd.DataFrame) -> str:
    """Convierte DataFrame a Markdown de forma segura."""
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


def abrir_conexion_intermedia() -> sqlite3.Connection:
    """Abre conexión a la base SQLite intermedia."""
    conn = sqlite3.connect(INTERIM_DB_PATH)
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -200000;")
    return conn


def obtener_schema(conn: sqlite3.Connection, table_name: str, db_alias: str = "src") -> pd.DataFrame:
    """Obtiene esquema de una tabla en una base SQLite adjunta."""
    sql = f"PRAGMA {db_alias}.table_info({quote_ident(table_name)});"
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


def validar_campos_requeridos(schema: pd.DataFrame, fields: list[str]) -> None:
    """Valida que existan los campos mínimos requeridos."""
    faltantes = [field for field in fields if not campo_existe(schema, field)]

    if faltantes:
        raise ValueError(f"Campos requeridos ausentes en el GeoPackage: {faltantes}")


def obtener_total_registros(conn: sqlite3.Connection, table_name: str) -> int:
    """Cuenta registros en la tabla fuente."""
    sql = f"SELECT COUNT(*) AS n FROM src.{quote_ident(table_name)};"
    return int(pd.read_sql_query(sql, conn)["n"].iloc[0])


# ============================================================
# CONSTRUCCIÓN DE GRUPOS XY
# ============================================================

def crear_tabla_grupos_xy(
    conn: sqlite3.Connection,
    table_name: str,
    lon_field: str,
    lat_field: str,
    country_field: str,
    source_field: str,
    year_field: str,
    level1_field: str,
    level2_field: str,
    conf_field: str,
) -> None:
    """
    Crea tabla intermedia grupos_xy.

    La tabla resume cada coordenada única Longitud-Latitud y la clasifica según
    cantidad de registros, fuentes, años y clases.
    """
    source_table = f"src.{quote_ident(table_name)}"

    conn.execute("DROP TABLE IF EXISTS grupos_xy;")

    sql = f"""
    CREATE TABLE grupos_xy AS
    WITH base AS (
        SELECT
            CAST({quote_ident(lon_field)} AS REAL) AS lon,
            CAST({quote_ident(lat_field)} AS REAL) AS lat,
            CAST({quote_ident(country_field)} AS TEXT) AS pais,
            CAST({quote_ident(source_field)} AS TEXT) AS fuente,
            CAST({quote_ident(year_field)} AS TEXT) AS anio,
            CAST({quote_ident(level1_field)} AS TEXT) AS nivel_1,
            CAST({quote_ident(level2_field)} AS TEXT) AS nivel_2,
            CAST({quote_ident(conf_field)} AS REAL) AS conf_integrada
        FROM {source_table}
        WHERE {quote_ident(lon_field)} IS NOT NULL
          AND {quote_ident(lat_field)} IS NOT NULL
          AND TRIM(CAST({quote_ident(lon_field)} AS TEXT)) != ''
          AND TRIM(CAST({quote_ident(lat_field)} AS TEXT)) != ''
    ),
    grupos AS (
        SELECT
            lon,
            lat,
            COUNT(*) AS n_registros,
            COUNT(DISTINCT pais) AS n_paises,
            COUNT(DISTINCT fuente) AS n_fuentes,
            COUNT(DISTINCT anio) AS n_anios,
            COUNT(DISTINCT nivel_1) AS n_nivel1,
            COUNT(DISTINCT nivel_2) AS n_nivel2,
            MIN(anio) AS anio_min,
            MAX(anio) AS anio_max,
            CASE
                WHEN COUNT(DISTINCT pais) = 1 THEN MIN(pais)
                ELSE 'multipais_o_inconsistente'
            END AS pais_grupo,
            AVG(conf_integrada) AS conf_integrada_promedio,
            MIN(conf_integrada) AS conf_integrada_min,
            MAX(conf_integrada) AS conf_integrada_max
        FROM base
        GROUP BY lon, lat
    ),
    clasificados AS (
        SELECT
            lon,
            lat,
            n_registros,
            n_paises,
            n_fuentes,
            n_anios,
            n_nivel1,
            n_nivel2,
            anio_min,
            anio_max,
            pais_grupo,
            conf_integrada_promedio,
            conf_integrada_min,
            conf_integrada_max,
            CASE
                WHEN n_registros = 1 THEN 'xy_unico'
                WHEN n_nivel1 > 1 OR n_nivel2 > 1 THEN 'conflicto_tematico_xy'
                WHEN n_anios > 1 THEN 'multitemporal_xy'
                WHEN n_fuentes > 1 THEN 'coincidencia_fuentes_misma_clase'
                WHEN n_fuentes = 1 AND n_nivel1 = 1 AND n_nivel2 = 1 THEN 'redundancia_misma_fuente_misma_clase'
                ELSE 'revision_xy'
            END AS tipo_grupo_xy
        FROM grupos
    )
    SELECT
        'XY_' || printf('%012d', ROW_NUMBER() OVER (ORDER BY lon, lat)) AS xy_group_id,
        *
    FROM clasificados;
    """

    conn.executescript(sql)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_grupos_xy_lon_lat ON grupos_xy(lon, lat);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_grupos_xy_tipo ON grupos_xy(tipo_grupo_xy);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_grupos_xy_pais ON grupos_xy(pais_grupo);")
    conn.commit()


# ============================================================
# TABLAS DE RESUMEN
# ============================================================

def generar_resumen_ejecutivo(conn: sqlite3.Connection, total_registros: int) -> pd.DataFrame:
    """Genera resumen ejecutivo de grupos XY."""
    sql = """
    SELECT
        COUNT(*) AS total_grupos_xy,
        SUM(CASE WHEN n_registros = 1 THEN 1 ELSE 0 END) AS grupos_xy_unicos,
        SUM(CASE WHEN n_registros > 1 THEN 1 ELSE 0 END) AS grupos_xy_repetidos,
        SUM(n_registros) AS total_registros_representados,
        SUM(CASE WHEN n_registros > 1 THEN n_registros ELSE 0 END) AS registros_en_grupos_repetidos,
        SUM(CASE WHEN n_registros > 1 THEN n_registros - 1 ELSE 0 END) AS exceso_registros_repetidos,
        MAX(n_registros) AS max_registros_misma_coordenada
    FROM grupos_xy;
    """

    df = pd.read_sql_query(sql, conn)

    df["total_registros_originales"] = total_registros
    df["pct_reduccion_si_uno_por_xy"] = round(
        (df["exceso_registros_repetidos"] / total_registros) * 100,
        4,
    )

    df["registros_unicos_xy_finales"] = df["total_grupos_xy"]

    cols = [
        "total_registros_originales",
        "total_grupos_xy",
        "grupos_xy_unicos",
        "grupos_xy_repetidos",
        "registros_en_grupos_repetidos",
        "exceso_registros_repetidos",
        "registros_unicos_xy_finales",
        "pct_reduccion_si_uno_por_xy",
        "max_registros_misma_coordenada",
    ]

    return df[cols]


def generar_distribucion_tipo(conn: sqlite3.Connection) -> pd.DataFrame:
    """Resume grupos y registros por tipo de grupo XY."""
    sql = """
    SELECT
        tipo_grupo_xy,
        COUNT(*) AS n_grupos,
        SUM(n_registros) AS n_registros,
        SUM(CASE WHEN n_registros > 1 THEN n_registros - 1 ELSE 0 END) AS exceso_registros,
        ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM grupos_xy), 6) AS pct_grupos,
        ROUND(100.0 * SUM(n_registros) / (SELECT SUM(n_registros) FROM grupos_xy), 6) AS pct_registros
    FROM grupos_xy
    GROUP BY tipo_grupo_xy
    ORDER BY n_registros DESC;
    """

    return pd.read_sql_query(sql, conn)


def generar_distribucion_tamano(conn: sqlite3.Connection) -> pd.DataFrame:
    """Resume distribución por tamaño de grupo XY."""
    sql = """
    SELECT
        CASE
            WHEN n_registros = 1 THEN '1'
            WHEN n_registros = 2 THEN '2'
            WHEN n_registros = 3 THEN '3'
            WHEN n_registros = 4 THEN '4'
            WHEN n_registros = 5 THEN '5'
            WHEN n_registros BETWEEN 6 AND 10 THEN '6-10'
            WHEN n_registros BETWEEN 11 AND 20 THEN '11-20'
            ELSE '>20'
        END AS rango_tamano_grupo,
        COUNT(*) AS n_grupos,
        SUM(n_registros) AS n_registros,
        SUM(CASE WHEN n_registros > 1 THEN n_registros - 1 ELSE 0 END) AS exceso_registros
    FROM grupos_xy
    GROUP BY rango_tamano_grupo
    ORDER BY
        CASE
            WHEN rango_tamano_grupo = '1' THEN 1
            WHEN rango_tamano_grupo = '2' THEN 2
            WHEN rango_tamano_grupo = '3' THEN 3
            WHEN rango_tamano_grupo = '4' THEN 4
            WHEN rango_tamano_grupo = '5' THEN 5
            WHEN rango_tamano_grupo = '6-10' THEN 6
            WHEN rango_tamano_grupo = '11-20' THEN 7
            ELSE 8
        END;
    """

    return pd.read_sql_query(sql, conn)


def generar_tipo_por_pais(conn: sqlite3.Connection) -> pd.DataFrame:
    """Resume tipos de grupo XY por país."""
    sql = """
    SELECT
        pais_grupo,
        tipo_grupo_xy,
        COUNT(*) AS n_grupos,
        SUM(n_registros) AS n_registros,
        SUM(CASE WHEN n_registros > 1 THEN n_registros - 1 ELSE 0 END) AS exceso_registros
    FROM grupos_xy
    GROUP BY pais_grupo, tipo_grupo_xy
    ORDER BY pais_grupo, n_registros DESC;
    """

    return pd.read_sql_query(sql, conn)


def generar_top_grupos_mas_registros(conn: sqlite3.Connection, limit: int = 1000) -> pd.DataFrame:
    """Extrae grupos XY con más registros."""
    sql = f"""
    SELECT *
    FROM grupos_xy
    ORDER BY n_registros DESC
    LIMIT {int(limit)};
    """

    return pd.read_sql_query(sql, conn)


def generar_detalle_grupos(
    conn: sqlite3.Connection,
    table_name: str,
    lon_field: str,
    lat_field: str,
    source_field: str,
    year_field: str,
    level1_field: str,
    level2_field: str,
    tipo_grupo: str,
    limit: int = 1000,
) -> pd.DataFrame:
    """Genera detalle de grupos XY de un tipo específico."""
    source_table = f"src.{quote_ident(table_name)}"

    sql = f"""
    SELECT
        g.xy_group_id,
        g.lon,
        g.lat,
        g.pais_grupo,
        g.n_registros,
        g.n_fuentes,
        g.n_anios,
        g.n_nivel1,
        g.n_nivel2,
        g.anio_min,
        g.anio_max,
        g.tipo_grupo_xy,
        GROUP_CONCAT(DISTINCT CAST(t.{quote_ident(source_field)} AS TEXT)) AS fuentes,
        GROUP_CONCAT(DISTINCT CAST(t.{quote_ident(year_field)} AS TEXT)) AS anios,
        GROUP_CONCAT(DISTINCT CAST(t.{quote_ident(level1_field)} AS TEXT)) AS valores_nivel_1,
        GROUP_CONCAT(DISTINCT CAST(t.{quote_ident(level2_field)} AS TEXT)) AS valores_nivel_2
    FROM grupos_xy AS g
    JOIN {source_table} AS t
      ON g.lon = CAST(t.{quote_ident(lon_field)} AS REAL)
     AND g.lat = CAST(t.{quote_ident(lat_field)} AS REAL)
    WHERE g.tipo_grupo_xy = ?
    GROUP BY
        g.xy_group_id,
        g.lon,
        g.lat,
        g.pais_grupo,
        g.n_registros,
        g.n_fuentes,
        g.n_anios,
        g.n_nivel1,
        g.n_nivel2,
        g.anio_min,
        g.anio_max,
        g.tipo_grupo_xy
    ORDER BY g.n_registros DESC
    LIMIT {int(limit)};
    """

    return pd.read_sql_query(sql, conn, params=[tipo_grupo])


# ============================================================
# FIGURAS
# ============================================================

def generar_figuras(distribucion_tipo_df: pd.DataFrame, distribucion_tamano_df: pd.DataFrame) -> None:
    """Genera figuras simples del Módulo 3B."""
    if not distribucion_tipo_df.empty:
        df = distribucion_tipo_df.sort_values("n_registros", ascending=True)

        plt.figure(figsize=(10, 6))
        plt.barh(df["tipo_grupo_xy"], df["n_registros"])
        plt.xlabel("Número de registros")
        plt.ylabel("Tipo de grupo XY")
        plt.title("Registros por tipo de grupo XY")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "03b_registros_por_tipo_grupo_xy.png", dpi=200)
        plt.close()

    if not distribucion_tamano_df.empty:
        plt.figure(figsize=(9, 5))
        plt.bar(distribucion_tamano_df["rango_tamano_grupo"], distribucion_tamano_df["n_grupos"])
        plt.xlabel("Tamaño del grupo XY")
        plt.ylabel("Número de grupos")
        plt.title("Distribución de tamaños de grupos XY")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "03b_distribucion_tamano_grupo_xy.png", dpi=200)
        plt.close()


# ============================================================
# REPORTE
# ============================================================

def generar_reporte(
    gpkg_path: Path,
    table_name: str,
    resumen_ejecutivo_df: pd.DataFrame,
    distribucion_tipo_df: pd.DataFrame,
    distribucion_tamano_df: pd.DataFrame,
    tipo_por_pais_df: pd.DataFrame,
    top_conflictos_df: pd.DataFrame,
    top_multitemporales_df: pd.DataFrame,
) -> None:
    """Genera reporte Markdown del Módulo 3B."""
    report_path = REPORTS_DIR / "03b_caracterizacion_multirregistros_xy.md"
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    resumen = resumen_ejecutivo_df.iloc[0].to_dict()

    contenido = "\n".join(
        [
            "# Caracterización de multirregistros espaciales XY",
            "",
            "## Módulo 3B",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## Archivo inspeccionado",
            "",
            "```text",
            str(gpkg_path),
            "```",
            "",
            "## Capa analizada",
            "",
            "```text",
            str(table_name),
            "```",
            "",
            "## Resumen ejecutivo",
            "",
            "| Concepto | Valor |",
            "|---|---:|",
            f"| Total de registros originales | {int(resumen['total_registros_originales'])} |",
            f"| Total de grupos XY únicos | {int(resumen['total_grupos_xy'])} |",
            f"| Grupos XY únicos sin repetición | {int(resumen['grupos_xy_unicos'])} |",
            f"| Grupos XY repetidos | {int(resumen['grupos_xy_repetidos'])} |",
            f"| Registros en grupos repetidos | {int(resumen['registros_en_grupos_repetidos'])} |",
            f"| Exceso de registros repetidos | {int(resumen['exceso_registros_repetidos'])} |",
            f"| Registros únicos XY finales | {int(resumen['registros_unicos_xy_finales'])} |",
            f"| Reducción si se conserva uno por XY (%) | {resumen['pct_reduccion_si_uno_por_xy']} |",
            f"| Máximo de registros en una misma coordenada | {int(resumen['max_registros_misma_coordenada'])} |",
            "",
            "## Distribución por tipo de grupo XY",
            "",
            dataframe_a_markdown(distribucion_tipo_df),
            "",
            "## Distribución por tamaño de grupo XY",
            "",
            dataframe_a_markdown(distribucion_tamano_df),
            "",
            "## Tipos de grupo XY por país",
            "",
            dataframe_a_markdown(tipo_por_pais_df.head(50)),
            "",
            "## Principales grupos con conflicto temático",
            "",
            dataframe_a_markdown(top_conflictos_df.head(50)),
            "",
            "## Principales grupos multitemporales",
            "",
            dataframe_a_markdown(top_multitemporales_df.head(50)),
            "",
            "## Interpretación metodológica",
            "",
            "Este módulo no elimina registros ni modifica el GeoPackage original.",
            "La clasificación de grupos XY permite diferenciar redundancia simple, coincidencia entre fuentes, multitemporalidad y conflicto temático.",
            "",
            "Los grupos con conflicto temático deben priorizarse para revisión antes de construir bases de entrenamiento, validación o prueba.",
            "Los grupos multitemporales no deben eliminarse automáticamente, ya que podrían representar cambios reales de cobertura o diferencias temporales entre fuentes.",
            "",
            "## Regla operativa recomendada",
            "",
            "```text",
            "Toda partición de entrenamiento, validación y prueba debe hacerse a nivel de grupo XY, no a nivel de fila individual.",
            "```",
            "",
        ]
    )

    with open(report_path, "w", encoding="utf-8") as file:
        file.write(contenido)


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def main() -> None:
    """Ejecuta Módulo 3B."""
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
    quality_cfg = config.get("quality_fields", {})

    lon_field = fields_cfg.get("longitude", "Longitud")
    lat_field = fields_cfg.get("latitude", "Latitud")
    country_field = fields_cfg.get("country", "Pais_es")
    source_field = fields_cfg.get("source", "Fuente")
    year_field = fields_cfg.get("year", "Año")
    level1_field = fields_cfg.get("level_1", "Nivel_1")
    level2_field = fields_cfg.get("level_2", "Nivel_2")
    conf_field = quality_cfg.get("conf_integrated", "conf_integrada")

    if INTERIM_DB_PATH.exists():
        INTERIM_DB_PATH.unlink()

    conn = abrir_conexion_intermedia()

    try:
        conn.execute("ATTACH DATABASE ? AS src;", (str(gpkg_path),))

        schema = obtener_schema(conn, table_name, db_alias="src")

        validar_campos_requeridos(
            schema,
            [
                lon_field,
                lat_field,
                country_field,
                source_field,
                year_field,
                level1_field,
                level2_field,
                conf_field,
            ],
        )

        total_registros = obtener_total_registros(conn, table_name)

        print("Creando tabla de grupos XY. Esto puede tardar varios minutos...")
        crear_tabla_grupos_xy(
            conn=conn,
            table_name=table_name,
            lon_field=lon_field,
            lat_field=lat_field,
            country_field=country_field,
            source_field=source_field,
            year_field=year_field,
            level1_field=level1_field,
            level2_field=level2_field,
            conf_field=conf_field,
        )

        resumen_ejecutivo_df = generar_resumen_ejecutivo(conn, total_registros)
        distribucion_tipo_df = generar_distribucion_tipo(conn)
        distribucion_tamano_df = generar_distribucion_tamano(conn)
        tipo_por_pais_df = generar_tipo_por_pais(conn)
        top_grupos_df = generar_top_grupos_mas_registros(conn, limit=1000)

        top_conflictos_df = generar_detalle_grupos(
            conn=conn,
            table_name=table_name,
            lon_field=lon_field,
            lat_field=lat_field,
            source_field=source_field,
            year_field=year_field,
            level1_field=level1_field,
            level2_field=level2_field,
            tipo_grupo="conflicto_tematico_xy",
            limit=1000,
        )

        top_multitemporales_df = generar_detalle_grupos(
            conn=conn,
            table_name=table_name,
            lon_field=lon_field,
            lat_field=lat_field,
            source_field=source_field,
            year_field=year_field,
            level1_field=level1_field,
            level2_field=level2_field,
            tipo_grupo="multitemporal_xy",
            limit=1000,
        )

        # Exportar tablas
        resumen_ejecutivo_df.to_csv(
            TABLES_DIR / "03b_resumen_ejecutivo.csv",
            index=False,
            encoding="utf-8-sig",
        )

        distribucion_tipo_df.to_csv(
            TABLES_DIR / "03b_distribucion_tipo_grupo_xy.csv",
            index=False,
            encoding="utf-8-sig",
        )

        distribucion_tamano_df.to_csv(
            TABLES_DIR / "03b_distribucion_tamano_grupo_xy.csv",
            index=False,
            encoding="utf-8-sig",
        )

        tipo_por_pais_df.to_csv(
            TABLES_DIR / "03b_tipo_grupo_por_pais.csv",
            index=False,
            encoding="utf-8-sig",
        )

        top_grupos_df.to_csv(
            TABLES_DIR / "03b_top_grupos_mas_registros.csv",
            index=False,
            encoding="utf-8-sig",
        )

        top_conflictos_df.to_csv(
            TABLES_DIR / "03b_top_conflictos_tematicos_xy.csv",
            index=False,
            encoding="utf-8-sig",
        )

        top_multitemporales_df.to_csv(
            TABLES_DIR / "03b_top_multitemporales_xy.csv",
            index=False,
            encoding="utf-8-sig",
        )

        generar_figuras(
            distribucion_tipo_df=distribucion_tipo_df,
            distribucion_tamano_df=distribucion_tamano_df,
        )

        generar_reporte(
            gpkg_path=gpkg_path,
            table_name=table_name,
            resumen_ejecutivo_df=resumen_ejecutivo_df,
            distribucion_tipo_df=distribucion_tipo_df,
            distribucion_tamano_df=distribucion_tamano_df,
            tipo_por_pais_df=tipo_por_pais_df,
            top_conflictos_df=top_conflictos_df,
            top_multitemporales_df=top_multitemporales_df,
        )

        resumen = resumen_ejecutivo_df.iloc[0]

        registrar_log(
            f"Módulo 3B ejecutado correctamente. "
            f"Total grupos XY: {int(resumen['total_grupos_xy'])}. "
            f"Grupos repetidos: {int(resumen['grupos_xy_repetidos'])}. "
            f"Exceso registros repetidos: {int(resumen['exceso_registros_repetidos'])}."
        )

        print("Módulo 3B ejecutado correctamente.")
        print(f"Base intermedia: {INTERIM_DB_PATH}")
        print(f"Total registros originales: {int(resumen['total_registros_originales'])}")
        print(f"Total grupos XY únicos: {int(resumen['total_grupos_xy'])}")
        print(f"Grupos XY repetidos: {int(resumen['grupos_xy_repetidos'])}")
        print(f"Exceso de registros repetidos: {int(resumen['exceso_registros_repetidos'])}")
        print("Salidas generadas en outputs/tables, outputs/figures y outputs/reports.")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        registrar_log("Error durante la ejecución del Módulo 3B.")
        traceback.print_exc()
        raise