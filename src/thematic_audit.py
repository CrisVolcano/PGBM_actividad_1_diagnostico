"""
Módulo 5 - Auditoría temática y consistencia de clases.

Este script evalúa la calidad, distribución, balance y consistencia temática
de la capa principal del GeoPackage, sin modificar los datos originales.

Objetivos:
- Evaluar integridad de campos temáticos.
- Analizar distribución de clases Nivel_0, Nivel_1 y Nivel_2.
- Identificar clases dominantes, bajas y críticas.
- Evaluar consistencia jerárquica Nivel_0 -> Nivel_1 -> Nivel_2.
- Analizar clases por país, fuente y año.
- Caracterizar conflictos temáticos XY usando la base del Módulo 3B.
- Generar tablas, figuras y reporte Markdown.

Principios:
- No modifica el GeoPackage original.
- Crea una base intermedia liviana en data/interim.
- Evita uniones pesadas contra el GeoPackage original.
- Usa una tabla temática reducida e indexada.
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


# ============================================================
# RUTAS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

DATA_INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
TABLES_DIR = PROJECT_ROOT / "outputs" / "tables"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"
LOGS_DIR = PROJECT_ROOT / "logs"

INTERIM_DB_PATH = DATA_INTERIM_DIR / "05_thematic_audit.sqlite"
XY_GROUPS_DB = DATA_INTERIM_DIR / "03b_multirregistros_xy.sqlite"


# ============================================================
# FUNCIONES GENERALES
# ============================================================

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
    conn = sqlite3.connect(INTERIM_DB_PATH, uri=True)
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


def expr_campo_texto(schema: pd.DataFrame, field_name: str, alias: str) -> str:
    if field_name and campo_existe(schema, field_name):
        return f"NULLIF(TRIM(CAST({quote_ident(field_name)} AS TEXT)), '') AS {quote_ident(alias)}"
    return f"NULL AS {quote_ident(alias)}"


def expr_campo_real(schema: pd.DataFrame, field_name: str, alias: str) -> str:
    if field_name and campo_existe(schema, field_name):
        return f"CAST({quote_ident(field_name)} AS REAL) AS {quote_ident(alias)}"
    return f"NULL AS {quote_ident(alias)}"


def expr_campo_entero(schema: pd.DataFrame, field_name: str, alias: str) -> str:
    if field_name and campo_existe(schema, field_name):
        return f"CAST(CAST(NULLIF(TRIM(CAST({quote_ident(field_name)} AS TEXT)), '') AS REAL) AS INTEGER) AS {quote_ident(alias)}"
    return f"NULL AS {quote_ident(alias)}"


# ============================================================
# BASE TEMÁTICA INTERMEDIA
# ============================================================

def crear_base_tematica(
    conn: sqlite3.Connection,
    gpkg_path: Path,
    table_name: str,
    schema: pd.DataFrame,
    fields: dict,
) -> None:
    """
    Crea thematic_base con solo los campos necesarios para auditoría temática.
    Esto evita consultar repetidamente el GeoPackage completo.
    """
    conn.execute("DROP TABLE IF EXISTS thematic_base;")

    source_uri = f"file:{gpkg_path}?mode=ro"
    conn.execute("ATTACH DATABASE ? AS src;", (source_uri,))

    source_table = f"src.{quote_ident(table_name)}"

    select_cols = [
        "ROWID AS source_rowid",
        expr_campo_real(schema, fields["lon"], "lon"),
        expr_campo_real(schema, fields["lat"], "lat"),
        expr_campo_entero(schema, fields["year"], "anio"),
        expr_campo_texto(schema, fields["country"], "pais"),
        expr_campo_texto(schema, fields["source"], "fuente"),
        expr_campo_texto(schema, fields["source_use"], "uso_origen"),
        expr_campo_texto(schema, fields["source_subuse"], "subuso_origen"),
        expr_campo_texto(schema, fields["id_level_0"], "id_nivel_0"),
        expr_campo_texto(schema, fields["level_0"], "nivel_0"),
        expr_campo_texto(schema, fields["id_level_1"], "id_nivel_1"),
        expr_campo_texto(schema, fields["level_1"], "nivel_1"),
        expr_campo_texto(schema, fields["id_level_2"], "id_nivel_2"),
        expr_campo_texto(schema, fields["level_2"], "nivel_2"),
    ]

    sql = f"""
    CREATE TABLE thematic_base AS
    SELECT
        {", ".join(select_cols)}
    FROM {source_table};
    """

    conn.executescript(sql)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_thematic_base_lon_lat ON thematic_base(lon, lat);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thematic_base_pais ON thematic_base(pais);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thematic_base_fuente ON thematic_base(fuente);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thematic_base_anio ON thematic_base(anio);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thematic_base_nivel1 ON thematic_base(nivel_1);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thematic_base_nivel2 ON thematic_base(nivel_2);")

    conn.commit()


def obtener_total_base_tematica(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM thematic_base;").fetchone()[0])


# ============================================================
# CALIDAD DE CAMPOS TEMÁTICOS
# ============================================================

def calidad_campos_tematicos(conn: sqlite3.Connection, total: int) -> pd.DataFrame:
    campos = [
        ("uso_origen", "Uso original"),
        ("subuso_origen", "Subuso original"),
        ("id_nivel_0", "Código Nivel_0"),
        ("nivel_0", "Nivel_0"),
        ("id_nivel_1", "Código Nivel_1"),
        ("nivel_1", "Nivel_1"),
        ("id_nivel_2", "Código Nivel_2"),
        ("nivel_2", "Nivel_2"),
    ]

    rows = []

    for campo, descripcion in campos:
        sql = f"""
        SELECT
            SUM(CASE WHEN {quote_ident(campo)} IS NULL THEN 1 ELSE 0 END) AS n_null,
            COUNT(DISTINCT {quote_ident(campo)}) AS n_valores_distintos
        FROM thematic_base;
        """
        r = pd.read_sql_query(sql, conn).iloc[0].to_dict()

        n_null = int(r["n_null"]) if r["n_null"] is not None else 0
        n_distinct = int(r["n_valores_distintos"]) if r["n_valores_distintos"] is not None else 0

        rows.append(
            {
                "campo": campo,
                "descripcion": descripcion,
                "n_total": total,
                "n_null_o_vacio": n_null,
                "pct_null_o_vacio": round((n_null / total) * 100, 6),
                "n_valores_distintos": n_distinct,
            }
        )

    return pd.DataFrame(rows)


def resumen_calidad_tematica(field_quality_df: pd.DataFrame, total: int) -> pd.DataFrame:
    campos_con_null = int((field_quality_df["n_null_o_vacio"] > 0).sum())
    max_pct_null = float(field_quality_df["pct_null_o_vacio"].max())
    campo_mayor_null = field_quality_df.sort_values(
        "pct_null_o_vacio",
        ascending=False,
    )["campo"].iloc[0]

    return pd.DataFrame(
        [
            {
                "total_registros": total,
                "n_campos_tematicos_evaluados": len(field_quality_df),
                "campos_con_null_o_vacio": campos_con_null,
                "max_pct_null_o_vacio": max_pct_null,
                "campo_con_mayor_null_o_vacio": campo_mayor_null,
            }
        ]
    )


# ============================================================
# DISTRIBUCIÓN Y BALANCE DE CLASES
# ============================================================

def distribucion_clase(
    conn: sqlite3.Connection,
    campo: str,
    total: int,
    min_low: int,
    min_critical: int,
) -> pd.DataFrame:
    sql = f"""
    SELECT
        {quote_ident(campo)} AS clase,
        COUNT(*) AS n
    FROM thematic_base
    WHERE {quote_ident(campo)} IS NOT NULL
    GROUP BY {quote_ident(campo)}
    ORDER BY n DESC;
    """

    df = pd.read_sql_query(sql, conn)

    if df.empty:
        return df

    df["pct"] = round((df["n"] / total) * 100, 6)
    df["pct_acumulado"] = round(df["pct"].cumsum(), 6)

    def flag_balance(n: int, pct: float) -> str:
        if n < min_critical:
            return "critica_muy_baja"
        if n < min_low:
            return "baja"
        if pct >= 20:
            return "dominante_extrema"
        if pct >= 10:
            return "dominante"
        return "representacion_media"

    df["balance_flag"] = [
        flag_balance(int(n), float(pct))
        for n, pct in zip(df["n"], df["pct"])
    ]

    return df


def distribucion_clase_por_campo(
    conn: sqlite3.Connection,
    class_field: str,
    group_field: str,
) -> pd.DataFrame:
    sql = f"""
    SELECT
        {quote_ident(group_field)} AS grupo,
        {quote_ident(class_field)} AS clase,
        COUNT(*) AS n
    FROM thematic_base
    WHERE {quote_ident(group_field)} IS NOT NULL
      AND {quote_ident(class_field)} IS NOT NULL
    GROUP BY {quote_ident(group_field)}, {quote_ident(class_field)}
    ORDER BY grupo, n DESC;
    """

    return pd.read_sql_query(sql, conn)


def distribucion_clase_por_anio(
    conn: sqlite3.Connection,
    class_field: str,
) -> pd.DataFrame:
    sql = f"""
    SELECT
        anio,
        {quote_ident(class_field)} AS clase,
        COUNT(*) AS n
    FROM thematic_base
    WHERE anio IS NOT NULL
      AND {quote_ident(class_field)} IS NOT NULL
    GROUP BY anio, {quote_ident(class_field)}
    ORDER BY anio, n DESC;
    """

    return pd.read_sql_query(sql, conn)


def matriz_fuente_pais(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
    SELECT
        pais,
        fuente,
        COUNT(*) AS n_registros,
        MIN(anio) AS anio_min,
        MAX(anio) AS anio_max,
        COUNT(DISTINCT anio) AS n_anios_distintos,
        COUNT(DISTINCT nivel_1) AS n_nivel1_distintos,
        COUNT(DISTINCT nivel_2) AS n_nivel2_distintos
    FROM thematic_base
    WHERE pais IS NOT NULL
      AND fuente IS NOT NULL
    GROUP BY pais, fuente
    ORDER BY pais, n_registros DESC;
    """

    return pd.read_sql_query(sql, conn)


# ============================================================
# CONSISTENCIA JERÁRQUICA
# ============================================================

def consistencia_jerarquica(
    conn: sqlite3.Connection,
    child_field: str,
    parent_field: str,
    relationship_name: str,
) -> pd.DataFrame:
    sql = f"""
    SELECT
        '{relationship_name}' AS relacion,
        {quote_ident(child_field)} AS clase_hija,
        COUNT(*) AS n_registros,
        COUNT(DISTINCT {quote_ident(parent_field)}) AS n_padres_distintos,
        GROUP_CONCAT(DISTINCT {quote_ident(parent_field)}) AS padres_asociados
    FROM thematic_base
    WHERE {quote_ident(child_field)} IS NOT NULL
      AND {quote_ident(parent_field)} IS NOT NULL
    GROUP BY {quote_ident(child_field)}
    ORDER BY n_padres_distintos DESC, n_registros DESC;
    """

    df = pd.read_sql_query(sql, conn)
    df["inconsistente"] = df["n_padres_distintos"] > 1

    return df


def inconsistencias_jerarquia(*dfs: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for df in dfs:
        if not df.empty and "inconsistente" in df.columns:
            parts.append(df[df["inconsistente"]].copy())

    if not parts:
        return pd.DataFrame(
            columns=[
                "relacion",
                "clase_hija",
                "n_registros",
                "n_padres_distintos",
                "padres_asociados",
                "inconsistente",
            ]
        )

    return pd.concat(parts, ignore_index=True)


# ============================================================
# CONFLICTOS TEMÁTICOS XY
# ============================================================

def preparar_conflictos_xy(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Usa grupos_xy del Módulo 3B para caracterizar conflictos temáticos.

    Se evita unir directamente contra el GeoPackage original. La unión se realiza contra thematic_base,
    que es una tabla reducida e indexada.
    """
    if not XY_GROUPS_DB.exists():
        warning = pd.DataFrame(
            [{"warning": "No existe data/interim/03b_multirregistros_xy.sqlite"}]
        )
        return warning, warning, warning

    conn.execute("ATTACH DATABASE ? AS xydb;", (str(XY_GROUPS_DB),))

    tablas = pd.read_sql_query(
        "SELECT name FROM xydb.sqlite_master WHERE type='table';",
        conn,
    )["name"].tolist()

    if "grupos_xy" not in tablas:
        warning = pd.DataFrame(
            [{"warning": "La base intermedia no contiene tabla grupos_xy."}]
        )
        return warning, warning, warning

    conn.execute("DROP TABLE IF EXISTS conflict_xy_groups;")
    conn.execute("DROP TABLE IF EXISTS conflict_xy_details;")

    conn.executescript(
        """
        CREATE TABLE conflict_xy_groups AS
        SELECT
            xy_group_id,
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
            tipo_grupo_xy
        FROM xydb.grupos_xy
        WHERE tipo_grupo_xy = 'conflicto_tematico_xy';

        CREATE INDEX IF NOT EXISTS idx_conflict_xy_groups_lon_lat
        ON conflict_xy_groups(lon, lat);
        """
    )

    conn.executescript(
        """
        CREATE TABLE conflict_xy_details AS
        SELECT
            c.xy_group_id,
            c.lon,
            c.lat,
            c.pais_grupo,
            c.n_registros AS n_registros_grupo,
            c.n_paises,
            c.n_fuentes,
            c.n_anios,
            c.n_nivel1,
            c.n_nivel2,
            c.anio_min,
            c.anio_max,
            c.conf_integrada_promedio,
            c.conf_integrada_min,
            c.conf_integrada_max,
            COUNT(*) AS n_registros_join,
            COUNT(DISTINCT b.pais) AS n_paises_calc,
            COUNT(DISTINCT b.fuente) AS n_fuentes_calc,
            COUNT(DISTINCT b.anio) AS n_anios_calc,
            COUNT(DISTINCT b.nivel_1) AS n_nivel1_calc,
            COUNT(DISTINCT b.nivel_2) AS n_nivel2_calc,
            GROUP_CONCAT(DISTINCT b.pais) AS paises,
            GROUP_CONCAT(DISTINCT b.fuente) AS fuentes,
            GROUP_CONCAT(DISTINCT b.anio) AS anios,
            GROUP_CONCAT(DISTINCT b.nivel_1) AS valores_nivel_1,
            GROUP_CONCAT(DISTINCT b.nivel_2) AS valores_nivel_2
        FROM conflict_xy_groups AS c
        JOIN thematic_base AS b
          ON c.lon = b.lon
         AND c.lat = b.lat
        GROUP BY
            c.xy_group_id,
            c.lon,
            c.lat,
            c.pais_grupo,
            c.n_registros,
            c.n_paises,
            c.n_fuentes,
            c.n_anios,
            c.n_nivel1,
            c.n_nivel2,
            c.anio_min,
            c.anio_max,
            c.conf_integrada_promedio,
            c.conf_integrada_min,
            c.conf_integrada_max;

        CREATE INDEX IF NOT EXISTS idx_conflict_xy_details_pais
        ON conflict_xy_details(pais_grupo);
        """
    )

    summary = pd.read_sql_query(
        """
        SELECT
            COUNT(*) AS n_grupos_conflicto,
            SUM(n_registros_grupo) AS n_registros_en_conflicto,
            AVG(n_registros_grupo) AS promedio_registros_por_grupo,
            MAX(n_registros_grupo) AS max_registros_por_grupo,
            AVG(n_anios) AS promedio_anios_por_grupo,
            MAX(n_anios) AS max_anios_por_grupo,
            AVG(n_nivel1) AS promedio_nivel1_distintos,
            AVG(n_nivel2) AS promedio_nivel2_distintos
        FROM conflict_xy_details;
        """,
        conn,
    )

    by_country = pd.read_sql_query(
        """
        SELECT
            pais_grupo,
            COUNT(*) AS n_grupos_conflicto,
            SUM(n_registros_grupo) AS n_registros_en_conflicto,
            AVG(n_registros_grupo) AS promedio_registros_por_grupo,
            AVG(n_anios) AS promedio_anios_por_grupo,
            MAX(n_anios) AS max_anios_por_grupo
        FROM conflict_xy_details
        GROUP BY pais_grupo
        ORDER BY n_registros_en_conflicto DESC;
        """,
        conn,
    )

    combinations = pd.read_sql_query(
        """
        SELECT
            pais_grupo,
            valores_nivel_1,
            valores_nivel_2,
            COUNT(*) AS n_grupos,
            SUM(n_registros_grupo) AS n_registros,
            AVG(n_anios) AS promedio_anios,
            MIN(anio_min) AS anio_min_global,
            MAX(anio_max) AS anio_max_global
        FROM conflict_xy_details
        GROUP BY pais_grupo, valores_nivel_1, valores_nivel_2
        ORDER BY n_registros DESC
        LIMIT 2000;
        """,
        conn,
    )

    return summary, by_country, combinations


def top_conflict_details(conn: sqlite3.Connection, limit: int = 1000) -> pd.DataFrame:
    if not tabla_existe(conn, "conflict_xy_details"):
        return pd.DataFrame(
            [{"warning": "No existe tabla conflict_xy_details."}]
        )

    return pd.read_sql_query(
        f"""
        SELECT *
        FROM conflict_xy_details
        ORDER BY n_registros_grupo DESC
        LIMIT {int(limit)};
        """,
        conn,
    )


# ============================================================
# FIGURAS
# ============================================================

def generar_figuras(
    dist_nivel1: pd.DataFrame,
    dist_nivel2: pd.DataFrame,
    conflicts_by_country: pd.DataFrame,
) -> None:
    if not dist_nivel1.empty:
        top = dist_nivel1.head(15).sort_values("n", ascending=True)
        plt.figure(figsize=(9, 6))
        plt.barh(top["clase"].astype(str), top["n"])
        plt.xlabel("Número de registros")
        plt.ylabel("Nivel_1")
        plt.title("Top clases Nivel_1 por registros")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "05_top_nivel1.png", dpi=200)
        plt.close()

    if not dist_nivel2.empty:
        top = dist_nivel2.head(20).sort_values("n", ascending=True)
        plt.figure(figsize=(10, 7))
        plt.barh(top["clase"].astype(str), top["n"])
        plt.xlabel("Número de registros")
        plt.ylabel("Nivel_2")
        plt.title("Top clases Nivel_2 por registros")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "05_top_nivel2.png", dpi=200)
        plt.close()

    if not conflicts_by_country.empty and "n_registros_en_conflicto" in conflicts_by_country.columns:
        top = conflicts_by_country.head(12).sort_values("n_registros_en_conflicto", ascending=True)
        plt.figure(figsize=(9, 6))
        plt.barh(top["pais_grupo"].astype(str), top["n_registros_en_conflicto"])
        plt.xlabel("Registros en conflicto temático XY")
        plt.ylabel("País")
        plt.title("Conflictos temáticos XY por país")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "05_conflictos_tematicos_por_pais.png", dpi=200)
        plt.close()


# ============================================================
# REPORTE
# ============================================================

def generar_reporte(
    total: int,
    field_quality: pd.DataFrame,
    thematic_summary: pd.DataFrame,
    dist_nivel0: pd.DataFrame,
    dist_nivel1: pd.DataFrame,
    dist_nivel2: pd.DataFrame,
    hierarchy_inconsistencies: pd.DataFrame,
    conflicts_summary: pd.DataFrame,
    conflicts_by_country: pd.DataFrame,
    conflict_combinations: pd.DataFrame,
) -> None:
    report_path = REPORTS_DIR / "05_auditoria_tematica.md"
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    n_inconsistencias = len(hierarchy_inconsistencies)
    n_conflict_groups = ""
    n_conflict_records = ""

    if not conflicts_summary.empty and "n_grupos_conflicto" in conflicts_summary.columns:
        n_conflict_groups = int(conflicts_summary["n_grupos_conflicto"].iloc[0])
        n_conflict_records = int(conflicts_summary["n_registros_en_conflicto"].iloc[0])

    contenido = "\n".join(
        [
            "# Auditoría temática y consistencia de clases",
            "",
            "## Módulo 5",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## Resumen ejecutivo",
            "",
            "| Concepto | Valor |",
            "|---|---:|",
            f"| Total de registros evaluados | {total} |",
            f"| Campos temáticos evaluados | {len(field_quality)} |",
            f"| Inconsistencias jerárquicas detectadas | {n_inconsistencias} |",
            f"| Grupos XY con conflicto temático | {n_conflict_groups} |",
            f"| Registros en grupos con conflicto temático | {n_conflict_records} |",
            "",
            "## Calidad de campos temáticos",
            "",
            dataframe_a_markdown(field_quality),
            "",
            "## Resumen de calidad temática",
            "",
            dataframe_a_markdown(thematic_summary),
            "",
            "## Distribución por Nivel_0",
            "",
            dataframe_a_markdown(dist_nivel0),
            "",
            "## Distribución por Nivel_1",
            "",
            dataframe_a_markdown(dist_nivel1.head(30)),
            "",
            "## Distribución por Nivel_2",
            "",
            dataframe_a_markdown(dist_nivel2.head(40)),
            "",
            "## Inconsistencias jerárquicas",
            "",
            dataframe_a_markdown(hierarchy_inconsistencies.head(100)),
            "",
            "## Resumen de conflictos temáticos XY",
            "",
            dataframe_a_markdown(conflicts_summary),
            "",
            "## Conflictos temáticos XY por país",
            "",
            dataframe_a_markdown(conflicts_by_country),
            "",
            "## Principales combinaciones conflictivas",
            "",
            dataframe_a_markdown(conflict_combinations.head(80)),
            "",
            "## Nota metodológica",
            "",
            "Esta auditoría temática no modifica el GeoPackage original.",
            "La base intermedia thematic_base contiene únicamente campos necesarios para análisis temático.",
            "Los conflictos temáticos XY se calculan cruzando la tabla thematic_base con los grupos XY del Módulo 3B.",
            "",
            "## Regla operativa recomendada",
            "",
            "```text",
            "Los grupos con conflicto temático no deben usarse directamente como muestras confiables de entrenamiento hasta resolver clase, año, fuente y confiabilidad.",
            "```",
            "",
        ]
    )

    report_path.write_text(contenido, encoding="utf-8")


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Módulo 5: auditoría temática y consistencia de clases."
    )
    parser.add_argument(
        "--rebuild-base",
        action="store_true",
        help="Reconstruye thematic_base desde el GeoPackage.",
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
    thematic_cfg = config.get("thematic", {})

    fields = {
        "lon": fields_cfg.get("longitude", "Longitud"),
        "lat": fields_cfg.get("latitude", "Latitud"),
        "year": fields_cfg.get("year", "Año"),
        "country": fields_cfg.get("country", "Pais_es"),
        "source": fields_cfg.get("source", "Fuente"),
        "source_use": thematic_cfg.get("source_use", "Uso_Origen"),
        "source_subuse": thematic_cfg.get("source_subuse", "Subuso_Origen"),
        "id_level_0": thematic_cfg.get("id_level_0", "id_0"),
        "level_0": thematic_cfg.get("level_0", fields_cfg.get("level_0", "Nivel_0")),
        "id_level_1": thematic_cfg.get("id_level_1", "id_cob_niv1"),
        "level_1": thematic_cfg.get("level_1", fields_cfg.get("level_1", "Nivel_1")),
        "id_level_2": thematic_cfg.get("id_level_2", "id_cob_niv2"),
        "level_2": thematic_cfg.get("level_2", fields_cfg.get("level_2", "Nivel_2")),
    }

    min_low = int(thematic_cfg.get("min_records_low_class", 100))
    min_critical = int(thematic_cfg.get("min_records_critical_class", 30))

    conn = abrir_conexion_intermedia()

    try:
        # Attach temporalmente para leer esquema.
        source_uri = f"file:{gpkg_path}?mode=ro"
        conn.execute("ATTACH DATABASE ? AS src;", (source_uri,))
        schema = obtener_schema(conn, table_name, db_alias="src")

        validar_campos_requeridos(
            schema,
            [
                fields["lon"],
                fields["lat"],
                fields["year"],
                fields["country"],
                fields["source"],
                fields["level_0"],
                fields["level_1"],
                fields["level_2"],
            ],
        )

        total_source = obtener_total_registros(conn, table_name)
        conn.execute("DETACH DATABASE src;")

        if args.rebuild_base or not tabla_existe(conn, "thematic_base"):
            print("Creando thematic_base desde el GeoPackage. Esto puede tardar varios minutos...")
            crear_base_tematica(
                conn=conn,
                gpkg_path=gpkg_path,
                table_name=table_name,
                schema=schema,
                fields=fields,
            )
        else:
            print("Usando thematic_base existente. No se reconstruirá la base intermedia.")

        total = obtener_total_base_tematica(conn)

        field_quality = calidad_campos_tematicos(conn, total)
        thematic_summary = resumen_calidad_tematica(field_quality, total)

        dist_nivel0 = distribucion_clase(conn, "nivel_0", total, min_low, min_critical)
        dist_nivel1 = distribucion_clase(conn, "nivel_1", total, min_low, min_critical)
        dist_nivel2 = distribucion_clase(conn, "nivel_2", total, min_low, min_critical)

        class_country_nivel1 = distribucion_clase_por_campo(conn, "nivel_1", "pais")
        class_country_nivel2 = distribucion_clase_por_campo(conn, "nivel_2", "pais")
        class_source_nivel1 = distribucion_clase_por_campo(conn, "nivel_1", "fuente")
        class_source_nivel2 = distribucion_clase_por_campo(conn, "nivel_2", "fuente")
        class_year_nivel1 = distribucion_clase_por_anio(conn, "nivel_1")
        class_year_nivel2 = distribucion_clase_por_anio(conn, "nivel_2")

        source_country = matriz_fuente_pais(conn)

        nivel1_to_nivel0 = consistencia_jerarquica(
            conn,
            child_field="nivel_1",
            parent_field="nivel_0",
            relationship_name="Nivel_1 -> Nivel_0",
        )

        nivel2_to_nivel1 = consistencia_jerarquica(
            conn,
            child_field="nivel_2",
            parent_field="nivel_1",
            relationship_name="Nivel_2 -> Nivel_1",
        )

        nivel2_to_nivel0 = consistencia_jerarquica(
            conn,
            child_field="nivel_2",
            parent_field="nivel_0",
            relationship_name="Nivel_2 -> Nivel_0",
        )

        hierarchy_inconsistencies = inconsistencias_jerarquia(
            nivel1_to_nivel0,
            nivel2_to_nivel1,
            nivel2_to_nivel0,
        )

        conflicts_summary, conflicts_by_country, conflict_combinations = preparar_conflictos_xy(conn)
        conflict_details_top = top_conflict_details(conn, limit=1000)

        audit_summary = pd.DataFrame(
            [
                {
                    "total_registros": total,
                    "total_registros_fuente": total_source,
                    "n_clases_nivel0": len(dist_nivel0),
                    "n_clases_nivel1": len(dist_nivel1),
                    "n_clases_nivel2": len(dist_nivel2),
                    "n_inconsistencias_jerarquicas": len(hierarchy_inconsistencies),
                    "n_grupos_conflicto_xy": (
                        int(conflicts_summary["n_grupos_conflicto"].iloc[0])
                        if "n_grupos_conflicto" in conflicts_summary.columns
                        else None
                    ),
                    "n_registros_conflicto_xy": (
                        int(conflicts_summary["n_registros_en_conflicto"].iloc[0])
                        if "n_registros_en_conflicto" in conflicts_summary.columns
                        else None
                    ),
                }
            ]
        )

        # Exportar tablas principales
        field_quality.to_csv(TABLES_DIR / "05_thematic_field_quality.csv", index=False, encoding="utf-8-sig")
        thematic_summary.to_csv(TABLES_DIR / "05_thematic_quality_summary.csv", index=False, encoding="utf-8-sig")

        dist_nivel0.to_csv(TABLES_DIR / "05_class_distribution_nivel0.csv", index=False, encoding="utf-8-sig")
        dist_nivel1.to_csv(TABLES_DIR / "05_class_distribution_nivel1.csv", index=False, encoding="utf-8-sig")
        dist_nivel2.to_csv(TABLES_DIR / "05_class_distribution_nivel2.csv", index=False, encoding="utf-8-sig")

        nivel1_to_nivel0.to_csv(TABLES_DIR / "05_hierarchy_nivel1_to_nivel0.csv", index=False, encoding="utf-8-sig")
        nivel2_to_nivel1.to_csv(TABLES_DIR / "05_hierarchy_nivel2_to_nivel1.csv", index=False, encoding="utf-8-sig")
        nivel2_to_nivel0.to_csv(TABLES_DIR / "05_hierarchy_nivel2_to_nivel0.csv", index=False, encoding="utf-8-sig")
        hierarchy_inconsistencies.to_csv(TABLES_DIR / "05_hierarchy_inconsistencies.csv", index=False, encoding="utf-8-sig")

        class_country_nivel1.to_csv(TABLES_DIR / "05_class_by_country_nivel1.csv", index=False, encoding="utf-8-sig")
        class_country_nivel2.to_csv(TABLES_DIR / "05_class_by_country_nivel2.csv", index=False, encoding="utf-8-sig")
        class_source_nivel1.to_csv(TABLES_DIR / "05_class_by_source_nivel1.csv", index=False, encoding="utf-8-sig")
        class_source_nivel2.to_csv(TABLES_DIR / "05_class_by_source_nivel2.csv", index=False, encoding="utf-8-sig")
        class_year_nivel1.to_csv(TABLES_DIR / "05_class_by_year_nivel1.csv", index=False, encoding="utf-8-sig")
        class_year_nivel2.to_csv(TABLES_DIR / "05_class_by_year_nivel2.csv", index=False, encoding="utf-8-sig")

        source_country.to_csv(TABLES_DIR / "05_source_country_matrix.csv", index=False, encoding="utf-8-sig")

        conflicts_summary.to_csv(TABLES_DIR / "05_thematic_conflicts_xy_summary.csv", index=False, encoding="utf-8-sig")
        conflicts_by_country.to_csv(TABLES_DIR / "05_thematic_conflicts_xy_by_country.csv", index=False, encoding="utf-8-sig")
        conflict_combinations.to_csv(TABLES_DIR / "05_thematic_conflict_class_combinations.csv", index=False, encoding="utf-8-sig")
        conflict_details_top.to_csv(TABLES_DIR / "05_thematic_conflicts_xy_details_top.csv", index=False, encoding="utf-8-sig")

        audit_summary.to_csv(TABLES_DIR / "05_thematic_audit_summary.csv", index=False, encoding="utf-8-sig")

        generar_figuras(
            dist_nivel1=dist_nivel1,
            dist_nivel2=dist_nivel2,
            conflicts_by_country=conflicts_by_country,
        )

        generar_reporte(
            total=total,
            field_quality=field_quality,
            thematic_summary=thematic_summary,
            dist_nivel0=dist_nivel0,
            dist_nivel1=dist_nivel1,
            dist_nivel2=dist_nivel2,
            hierarchy_inconsistencies=hierarchy_inconsistencies,
            conflicts_summary=conflicts_summary,
            conflicts_by_country=conflicts_by_country,
            conflict_combinations=conflict_combinations,
        )

        registrar_log(
            "Módulo 5 ejecutado correctamente. "
            f"Registros evaluados: {total}. "
            f"Clases Nivel_1: {len(dist_nivel1)}. "
            f"Clases Nivel_2: {len(dist_nivel2)}. "
            f"Inconsistencias jerárquicas: {len(hierarchy_inconsistencies)}."
        )

        print("Módulo 5 ejecutado correctamente.")
        print(f"Registros evaluados: {total}")
        print(f"Clases Nivel_0: {len(dist_nivel0)}")
        print(f"Clases Nivel_1: {len(dist_nivel1)}")
        print(f"Clases Nivel_2: {len(dist_nivel2)}")
        print(f"Inconsistencias jerárquicas: {len(hierarchy_inconsistencies)}")
        print("Salidas generadas en outputs/tables, outputs/figures y outputs/reports.")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        registrar_log("Error durante la ejecución del Módulo 5.")
        traceback.print_exc()
        raise
    
