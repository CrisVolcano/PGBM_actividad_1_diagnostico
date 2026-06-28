"""
Módulo 3B - Caracterización optimizada de multirregistros espaciales XY.

Esta versión evita las uniones pesadas contra el GeoPackage original para generar
detalles de conflictos y multitemporalidad. El objetivo es producir una auditoría
robusta, reproducible y ejecutable en tiempos razonables.

Flujo:
1. Si ya existe data/interim/03b_multirregistros_xy.sqlite con tabla grupos_xy,
   reutiliza esa tabla.
2. Si no existe, construye grupos_xy desde el GeoPackage.
3. Genera resúmenes, tablas, figuras y reporte desde grupos_xy.
4. No modifica el GeoPackage original.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import sqlite3
import traceback

import matplotlib.pyplot as plt
import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

DATA_INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
TABLES_DIR = PROJECT_ROOT / "outputs" / "tables"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"
LOGS_DIR = PROJECT_ROOT / "logs"

INTERIM_DB_PATH = DATA_INTERIM_DIR / "03b_multirregistros_xy.sqlite"


def crear_carpetas_salida() -> None:
    DATA_INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def registrar_log(mensaje: str) -> None:
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOGS_DIR / "auditoria.log", "a", encoding="utf-8") as log:
        log.write(f"[{fecha}] {mensaje}\n")


def cargar_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo requerido: {path}")

    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return data or {}


def quote_ident(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def dataframe_a_markdown(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


def abrir_conexion_intermedia() -> sqlite3.Connection:
    conn = sqlite3.connect(INTERIM_DB_PATH)
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -200000;")
    return conn


def tabla_existe(conn: sqlite3.Connection, table_name: str) -> bool:
    sql = """
    SELECT COUNT(*) AS n
    FROM sqlite_master
    WHERE type = 'table' AND name = ?;
    """
    n = conn.execute(sql, (table_name,)).fetchone()[0]
    return n > 0


def obtener_schema(conn: sqlite3.Connection, table_name: str, db_alias: str = "src") -> pd.DataFrame:
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
    return field_name in set(schema["field_name"].tolist())


def validar_campos_requeridos(schema: pd.DataFrame, fields: list[str]) -> None:
    faltantes = [field for field in fields if not campo_existe(schema, field)]

    if faltantes:
        raise ValueError(f"Campos requeridos ausentes en el GeoPackage: {faltantes}")


def obtener_total_registros(conn: sqlite3.Connection, table_name: str) -> int:
    sql = f"SELECT COUNT(*) AS n FROM src.{quote_ident(table_name)};"
    return int(pd.read_sql_query(sql, conn)["n"].iloc[0])


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


def generar_tablas(conn: sqlite3.Connection, total_registros: int) -> dict[str, pd.DataFrame]:
    resumen = pd.read_sql_query(
        f"""
        SELECT
            {int(total_registros)} AS total_registros_originales,
            COUNT(*) AS total_grupos_xy,
            SUM(CASE WHEN n_registros = 1 THEN 1 ELSE 0 END) AS grupos_xy_unicos,
            SUM(CASE WHEN n_registros > 1 THEN 1 ELSE 0 END) AS grupos_xy_repetidos,
            SUM(CASE WHEN n_registros > 1 THEN n_registros ELSE 0 END) AS registros_en_grupos_repetidos,
            SUM(CASE WHEN n_registros > 1 THEN n_registros - 1 ELSE 0 END) AS exceso_registros_repetidos,
            COUNT(*) AS registros_unicos_xy_finales,
            ROUND(
                100.0 * SUM(CASE WHEN n_registros > 1 THEN n_registros - 1 ELSE 0 END) / {int(total_registros)},
                4
            ) AS pct_reduccion_si_uno_por_xy,
            MAX(n_registros) AS max_registros_misma_coordenada
        FROM grupos_xy;
        """,
        conn,
    )

    distribucion_tipo = pd.read_sql_query(
        """
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
        """,
        conn,
    )

    distribucion_tamano = pd.read_sql_query(
        """
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
        """,
        conn,
    )

    tipo_por_pais = pd.read_sql_query(
        """
        SELECT
            pais_grupo,
            tipo_grupo_xy,
            COUNT(*) AS n_grupos,
            SUM(n_registros) AS n_registros,
            SUM(CASE WHEN n_registros > 1 THEN n_registros - 1 ELSE 0 END) AS exceso_registros
        FROM grupos_xy
        GROUP BY pais_grupo, tipo_grupo_xy
        ORDER BY pais_grupo, n_registros DESC;
        """,
        conn,
    )

    top_grupos = pd.read_sql_query(
        """
        SELECT *
        FROM grupos_xy
        ORDER BY n_registros DESC
        LIMIT 1000;
        """,
        conn,
    )

    top_conflictos = pd.read_sql_query(
        """
        SELECT *
        FROM grupos_xy
        WHERE tipo_grupo_xy = 'conflicto_tematico_xy'
        ORDER BY n_registros DESC
        LIMIT 1000;
        """,
        conn,
    )

    top_multitemporales = pd.read_sql_query(
        """
        SELECT *
        FROM grupos_xy
        WHERE tipo_grupo_xy = 'multitemporal_xy'
        ORDER BY n_registros DESC
        LIMIT 1000;
        """,
        conn,
    )

    return {
        "resumen": resumen,
        "distribucion_tipo": distribucion_tipo,
        "distribucion_tamano": distribucion_tamano,
        "tipo_por_pais": tipo_por_pais,
        "top_grupos": top_grupos,
        "top_conflictos": top_conflictos,
        "top_multitemporales": top_multitemporales,
    }


def exportar_tablas(tablas: dict[str, pd.DataFrame]) -> None:
    tablas["resumen"].to_csv(TABLES_DIR / "03b_resumen_ejecutivo.csv", index=False, encoding="utf-8-sig")
    tablas["distribucion_tipo"].to_csv(TABLES_DIR / "03b_distribucion_tipo_grupo_xy.csv", index=False, encoding="utf-8-sig")
    tablas["distribucion_tamano"].to_csv(TABLES_DIR / "03b_distribucion_tamano_grupo_xy.csv", index=False, encoding="utf-8-sig")
    tablas["tipo_por_pais"].to_csv(TABLES_DIR / "03b_tipo_grupo_por_pais.csv", index=False, encoding="utf-8-sig")
    tablas["top_grupos"].to_csv(TABLES_DIR / "03b_top_grupos_mas_registros.csv", index=False, encoding="utf-8-sig")
    tablas["top_conflictos"].to_csv(TABLES_DIR / "03b_top_conflictos_tematicos_xy.csv", index=False, encoding="utf-8-sig")
    tablas["top_multitemporales"].to_csv(TABLES_DIR / "03b_top_multitemporales_xy.csv", index=False, encoding="utf-8-sig")


def generar_figuras(tablas: dict[str, pd.DataFrame]) -> None:
    dist_tipo = tablas["distribucion_tipo"]
    dist_tamano = tablas["distribucion_tamano"]

    if not dist_tipo.empty:
        df = dist_tipo.sort_values("n_registros", ascending=True)

        plt.figure(figsize=(10, 6))
        plt.barh(df["tipo_grupo_xy"], df["n_registros"])
        plt.xlabel("Número de registros")
        plt.ylabel("Tipo de grupo XY")
        plt.title("Registros por tipo de grupo XY")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "03b_registros_por_tipo_grupo_xy.png", dpi=200)
        plt.close()

    if not dist_tamano.empty:
        plt.figure(figsize=(9, 5))
        plt.bar(dist_tamano["rango_tamano_grupo"], dist_tamano["n_grupos"])
        plt.xlabel("Tamaño del grupo XY")
        plt.ylabel("Número de grupos")
        plt.title("Distribución de tamaños de grupos XY")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "03b_distribucion_tamano_grupo_xy.png", dpi=200)
        plt.close()


def generar_reporte(tablas: dict[str, pd.DataFrame], total_registros: int, rebuild: bool) -> None:
    resumen = tablas["resumen"].iloc[0].to_dict()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    modo = "reconstrucción de grupos_xy" if rebuild else "reutilización de grupos_xy existente"

    contenido = "\n".join(
        [
            "# Caracterización de multirregistros espaciales XY",
            "",
            "## Módulo 3B - Versión optimizada",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## Modo de ejecución",
            "",
            f"`{modo}`",
            "",
            "## Fuente intermedia",
            "",
            "```text",
            str(INTERIM_DB_PATH),
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
            dataframe_a_markdown(tablas["distribucion_tipo"]),
            "",
            "## Distribución por tamaño de grupo XY",
            "",
            dataframe_a_markdown(tablas["distribucion_tamano"]),
            "",
            "## Tipos de grupo XY por país",
            "",
            dataframe_a_markdown(tablas["tipo_por_pais"].head(80)),
            "",
            "## Principales grupos con conflicto temático",
            "",
            dataframe_a_markdown(tablas["top_conflictos"].head(50)),
            "",
            "## Principales grupos multitemporales",
            "",
            dataframe_a_markdown(tablas["top_multitemporales"].head(50)),
            "",
            "## Nota metodológica",
            "",
            "Este reporte no modifica el GeoPackage original.",
            "La versión optimizada evita uniones pesadas contra la tabla completa original.",
            "Los listados de conflictos y multitemporales se derivan directamente de la tabla grupos_xy.",
            "",
            "## Regla operativa recomendada",
            "",
            "```text",
            "Toda partición de entrenamiento, validación y prueba debe hacerse a nivel de grupo XY, no a nivel de fila individual.",
            "```",
            "",
        ]
    )

    report_path = REPORTS_DIR / "03b_caracterizacion_multirregistros_xy.md"
    report_path.write_text(contenido, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Módulo 3B optimizado: caracteriza multirregistros XY."
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Reconstruye grupos_xy desde el GeoPackage. Si no se usa, reutiliza la tabla existente.",
    )
    args = parser.parse_args()

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

    if args.rebuild and INTERIM_DB_PATH.exists():
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

        if args.rebuild or not tabla_existe(conn, "grupos_xy"):
            print("Creando tabla grupos_xy desde el GeoPackage. Esto puede tardar varios minutos...")
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
        else:
            print("Usando tabla grupos_xy existente. No se reconstruirá la base intermedia.")

        tablas = generar_tablas(conn, total_registros=total_registros)
        exportar_tablas(tablas)
        generar_figuras(tablas)
        generar_reporte(tablas, total_registros=total_registros, rebuild=args.rebuild)

        resumen = tablas["resumen"].iloc[0]

        registrar_log(
            "Módulo 3B optimizado ejecutado correctamente. "
            f"Total grupos XY: {int(resumen['total_grupos_xy'])}. "
            f"Grupos repetidos: {int(resumen['grupos_xy_repetidos'])}. "
            f"Exceso registros repetidos: {int(resumen['exceso_registros_repetidos'])}."
        )

        print("Módulo 3B optimizado ejecutado correctamente.")
        print(f"Total grupos XY: {int(resumen['total_grupos_xy'])}")
        print(f"Grupos XY repetidos: {int(resumen['grupos_xy_repetidos'])}")
        print(f"Exceso registros repetidos: {int(resumen['exceso_registros_repetidos'])}")
        print("Salidas generadas en outputs/tables, outputs/figures y outputs/reports.")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        registrar_log("Error durante la ejecución del Módulo 3B optimizado.")
        traceback.print_exc()
        raise