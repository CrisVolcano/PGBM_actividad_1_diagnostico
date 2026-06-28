"""
Módulo 5B - Auditoría temática focalizada en 2020 y ventana 2018-2022.

Este script complementa el Módulo 5. Repite análisis temáticos clave sobre dos
subconjuntos temporales:

1. exacto_2020:
   Registros cuyo año es exactamente el año objetivo.

2. ventana_2018_2022:
   Registros dentro de la ventana temporal definida como año objetivo ± ventana.

Objetivos:
- Evaluar qué clases siguen siendo representativas en 2020 y 2018-2022.
- Identificar vacíos país-clase dentro de la ventana operativa.
- Evaluar fuentes dominantes dentro de la ventana útil.
- Recalcular conflictos temáticos XY dentro de 2020 y 2018-2022.
- Generar insumos para scoring de aptitud y selección de muestras.

Requisitos:
- Debe existir data/interim/05_thematic_audit.sqlite con tabla thematic_base.
  Esta tabla fue creada por el Módulo 5.
- Se recomienda que exista data/interim/03b_multirregistros_xy.sqlite con tabla grupos_xy.
  Esta tabla fue creada por el Módulo 3B.

Principios:
- No modifica el GeoPackage original.
- Trabaja sobre bases intermedias.
- Genera tablas, figuras y reporte Markdown.
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

THEMATIC_DB = DATA_INTERIM_DIR / "05_thematic_audit.sqlite"
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


def abrir_conexion() -> sqlite3.Connection:
    if not THEMATIC_DB.exists():
        raise FileNotFoundError(
            "No existe data/interim/05_thematic_audit.sqlite. "
            "Ejecuta primero el Módulo 5: python src/thematic_audit.py --rebuild-base"
        )

    conn = sqlite3.connect(THEMATIC_DB)
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -200000;")
    return conn


def tabla_existe(conn: sqlite3.Connection, table_name: str, db_alias: str = "main") -> bool:
    if db_alias == "main":
        sql = """
        SELECT COUNT(*) AS n
        FROM sqlite_master
        WHERE type = 'table' AND name = ?;
        """
    else:
        sql = f"""
        SELECT COUNT(*) AS n
        FROM {db_alias}.sqlite_master
        WHERE type = 'table' AND name = ?;
        """
    return int(conn.execute(sql, (table_name,)).fetchone()[0]) > 0


def validar_thematic_base(conn: sqlite3.Connection) -> None:
    if not tabla_existe(conn, "thematic_base"):
        raise ValueError(
            "La base intermedia existe, pero no contiene thematic_base. "
            "Ejecuta primero el Módulo 5 con --rebuild-base."
        )

    schema = pd.read_sql_query("PRAGMA table_info(thematic_base);", conn)
    fields = set(schema["name"].tolist())

    requeridos = {
        "source_rowid",
        "lon",
        "lat",
        "anio",
        "pais",
        "fuente",
        "nivel_0",
        "nivel_1",
        "nivel_2",
    }

    faltantes = sorted(requeridos - fields)
    if faltantes:
        raise ValueError(f"thematic_base no contiene campos requeridos: {faltantes}")


def obtener_total_base(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM thematic_base;").fetchone()[0])


def attach_xy_db(conn: sqlite3.Connection) -> bool:
    if not XY_GROUPS_DB.exists():
        return False

    dbs = pd.read_sql_query("PRAGMA database_list;", conn)
    if "xydb" not in set(dbs["name"].tolist()):
        conn.execute("ATTACH DATABASE ? AS xydb;", (str(XY_GROUPS_DB),))

    if not tabla_existe(conn, "grupos_xy", db_alias="xydb"):
        return False

    return True


# ============================================================
# SUBCONJUNTOS TEMPORALES
# ============================================================

def construir_subsets(target_year: int, near_window: int) -> list[dict]:
    start_year = target_year - near_window
    end_year = target_year + near_window

    return [
        {
            "subset": f"exacto_{target_year}",
            "descripcion": f"Registros exactamente del año {target_year}",
            "where": f"anio = {int(target_year)}",
            "year_min": target_year,
            "year_max": target_year,
        },
        {
            "subset": f"ventana_{start_year}_{end_year}",
            "descripcion": f"Registros entre {start_year} y {end_year}",
            "where": f"anio BETWEEN {int(start_year)} AND {int(end_year)}",
            "year_min": start_year,
            "year_max": end_year,
        },
    ]


# ============================================================
# RESÚMENES DE SUBCONJUNTOS
# ============================================================

def resumen_subsets(
    conn: sqlite3.Connection,
    subsets: list[dict],
    total_base: int,
) -> pd.DataFrame:
    rows = []

    for spec in subsets:
        sql = f"""
        SELECT
            COUNT(*) AS n_registros,
            COUNT(DISTINCT pais) AS n_paises,
            COUNT(DISTINCT fuente) AS n_fuentes,
            COUNT(DISTINCT anio) AS n_anios,
            MIN(anio) AS anio_min,
            MAX(anio) AS anio_max,
            COUNT(DISTINCT nivel_0) AS n_nivel0,
            COUNT(DISTINCT nivel_1) AS n_nivel1,
            COUNT(DISTINCT nivel_2) AS n_nivel2
        FROM thematic_base
        WHERE {spec["where"]};
        """

        r = pd.read_sql_query(sql, conn).iloc[0].to_dict()
        n = int(r["n_registros"])

        rows.append(
            {
                "subset": spec["subset"],
                "descripcion": spec["descripcion"],
                "n_registros": n,
                "pct_total_base": round((n / total_base) * 100, 6) if total_base else 0,
                "n_paises": int(r["n_paises"] or 0),
                "n_fuentes": int(r["n_fuentes"] or 0),
                "n_anios": int(r["n_anios"] or 0),
                "anio_min": r["anio_min"],
                "anio_max": r["anio_max"],
                "n_nivel0": int(r["n_nivel0"] or 0),
                "n_nivel1": int(r["n_nivel1"] or 0),
                "n_nivel2": int(r["n_nivel2"] or 0),
            }
        )

    return pd.DataFrame(rows)


def cobertura_pais_subset(
    conn: sqlite3.Connection,
    subsets: list[dict],
) -> pd.DataFrame:
    parts = []

    for spec in subsets:
        sql = f"""
        SELECT
            '{spec["subset"]}' AS subset,
            pais,
            COUNT(*) AS n_registros,
            COUNT(DISTINCT fuente) AS n_fuentes,
            COUNT(DISTINCT anio) AS n_anios,
            MIN(anio) AS anio_min,
            MAX(anio) AS anio_max,
            COUNT(DISTINCT nivel_1) AS n_nivel1,
            COUNT(DISTINCT nivel_2) AS n_nivel2
        FROM thematic_base
        WHERE {spec["where"]}
          AND pais IS NOT NULL
        GROUP BY pais
        ORDER BY n_registros DESC;
        """
        parts.append(pd.read_sql_query(sql, conn))

    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if not df.empty:
        df["pct_subset"] = df.groupby("subset")["n_registros"].transform(
            lambda s: round((s / s.sum()) * 100, 6)
        )
    return df


def cobertura_fuente_subset(
    conn: sqlite3.Connection,
    subsets: list[dict],
) -> pd.DataFrame:
    parts = []

    for spec in subsets:
        sql = f"""
        SELECT
            '{spec["subset"]}' AS subset,
            fuente,
            COUNT(*) AS n_registros,
            COUNT(DISTINCT pais) AS n_paises,
            COUNT(DISTINCT anio) AS n_anios,
            MIN(anio) AS anio_min,
            MAX(anio) AS anio_max,
            COUNT(DISTINCT nivel_1) AS n_nivel1,
            COUNT(DISTINCT nivel_2) AS n_nivel2
        FROM thematic_base
        WHERE {spec["where"]}
          AND fuente IS NOT NULL
        GROUP BY fuente
        ORDER BY n_registros DESC;
        """
        parts.append(pd.read_sql_query(sql, conn))

    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if not df.empty:
        df["pct_subset"] = df.groupby("subset")["n_registros"].transform(
            lambda s: round((s / s.sum()) * 100, 6)
        )
    return df


# ============================================================
# DISTRIBUCIÓN DE CLASES
# ============================================================

def flag_balance_clase(
    n: int,
    pct: float,
    n_paises: int,
    n_fuentes: int,
    min_low: int,
    min_critical: int,
) -> str:
    if n < min_critical:
        return "critica_muy_baja"
    if n < min_low:
        return "baja"
    if n_paises <= 1:
        return "territorialmente_limitada"
    if n_fuentes <= 1:
        return "dependiente_fuente_unica"
    if pct >= 20:
        return "dominante_extrema"
    if pct >= 10:
        return "dominante"
    return "representacion_media"


def distribucion_clases_subset(
    conn: sqlite3.Connection,
    subsets: list[dict],
    class_field: str,
    class_level: str,
    min_low: int,
    min_critical: int,
) -> pd.DataFrame:
    parts = []

    for spec in subsets:
        total = int(
            conn.execute(
                f"SELECT COUNT(*) FROM thematic_base WHERE {spec['where']};"
            ).fetchone()[0]
        )

        sql = f"""
        SELECT
            '{spec["subset"]}' AS subset,
            '{class_level}' AS nivel,
            {quote_ident(class_field)} AS clase,
            COUNT(*) AS n_registros,
            COUNT(DISTINCT pais) AS n_paises,
            COUNT(DISTINCT fuente) AS n_fuentes,
            COUNT(DISTINCT anio) AS n_anios,
            MIN(anio) AS anio_min,
            MAX(anio) AS anio_max
        FROM thematic_base
        WHERE {spec["where"]}
          AND {quote_ident(class_field)} IS NOT NULL
        GROUP BY {quote_ident(class_field)}
        ORDER BY n_registros DESC;
        """

        df = pd.read_sql_query(sql, conn)

        if not df.empty:
            df["pct_subset"] = round((df["n_registros"] / total) * 100, 6) if total else 0
            df["pct_acumulado"] = df["pct_subset"].cumsum().round(6)
            df["balance_flag"] = [
                flag_balance_clase(
                    int(n),
                    float(pct),
                    int(n_paises),
                    int(n_fuentes),
                    min_low,
                    min_critical,
                )
                for n, pct, n_paises, n_fuentes in zip(
                    df["n_registros"],
                    df["pct_subset"],
                    df["n_paises"],
                    df["n_fuentes"],
                )
            ]

        parts.append(df)

    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def distribucion_clase_por_pais(
    conn: sqlite3.Connection,
    subsets: list[dict],
    class_field: str,
    class_level: str,
) -> pd.DataFrame:
    parts = []

    for spec in subsets:
        sql = f"""
        SELECT
            '{spec["subset"]}' AS subset,
            '{class_level}' AS nivel,
            pais,
            {quote_ident(class_field)} AS clase,
            COUNT(*) AS n_registros
        FROM thematic_base
        WHERE {spec["where"]}
          AND pais IS NOT NULL
          AND {quote_ident(class_field)} IS NOT NULL
        GROUP BY pais, {quote_ident(class_field)}
        ORDER BY pais, n_registros DESC;
        """
        df = pd.read_sql_query(sql, conn)

        if not df.empty:
            df["pct_pais_subset"] = df.groupby(["subset", "pais"])["n_registros"].transform(
                lambda s: round((s / s.sum()) * 100, 6)
            )

        parts.append(df)

    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def distribucion_clase_por_fuente(
    conn: sqlite3.Connection,
    subsets: list[dict],
    class_field: str,
    class_level: str,
) -> pd.DataFrame:
    parts = []

    for spec in subsets:
        sql = f"""
        SELECT
            '{spec["subset"]}' AS subset,
            '{class_level}' AS nivel,
            fuente,
            {quote_ident(class_field)} AS clase,
            COUNT(*) AS n_registros
        FROM thematic_base
        WHERE {spec["where"]}
          AND fuente IS NOT NULL
          AND {quote_ident(class_field)} IS NOT NULL
        GROUP BY fuente, {quote_ident(class_field)}
        ORDER BY fuente, n_registros DESC;
        """
        df = pd.read_sql_query(sql, conn)

        if not df.empty:
            df["pct_fuente_subset"] = df.groupby(["subset", "fuente"])["n_registros"].transform(
                lambda s: round((s / s.sum()) * 100, 6)
            )

        parts.append(df)

    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ============================================================
# MATRIZ PAÍS-CLASE
# ============================================================

def estado_pais_clase(
    n: int,
    min_low: int,
    min_critical: int,
    min_sufficient: int,
) -> str:
    if n == 0:
        return "vacio"
    if n < min_critical:
        return "critico"
    if n < min_low:
        return "bajo"
    if n < min_sufficient:
        return "moderado"
    return "suficiente"


def matriz_pais_clase(
    conn: sqlite3.Connection,
    subsets: list[dict],
    class_field: str,
    class_level: str,
    min_low: int,
    min_critical: int,
    min_sufficient: int,
) -> pd.DataFrame:
    all_countries = pd.read_sql_query(
        """
        SELECT DISTINCT pais
        FROM thematic_base
        WHERE pais IS NOT NULL
        ORDER BY pais;
        """,
        conn,
    )

    all_classes = pd.read_sql_query(
        f"""
        SELECT DISTINCT {quote_ident(class_field)} AS clase
        FROM thematic_base
        WHERE {quote_ident(class_field)} IS NOT NULL
        ORDER BY clase;
        """,
        conn,
    )

    parts = []

    for spec in subsets:
        observed = pd.read_sql_query(
            f"""
            SELECT
                pais,
                {quote_ident(class_field)} AS clase,
                COUNT(*) AS n_registros
            FROM thematic_base
            WHERE {spec["where"]}
              AND pais IS NOT NULL
              AND {quote_ident(class_field)} IS NOT NULL
            GROUP BY pais, {quote_ident(class_field)};
            """,
            conn,
        )

        grid = all_countries.merge(all_classes, how="cross")
        grid["subset"] = spec["subset"]
        grid["nivel"] = class_level

        merged = grid.merge(
            observed,
            how="left",
            on=["pais", "clase"],
        )

        merged["n_registros"] = merged["n_registros"].fillna(0).astype(int)
        merged["estado_pais_clase"] = [
            estado_pais_clase(int(n), min_low, min_critical, min_sufficient)
            for n in merged["n_registros"]
        ]

        parts.append(merged[["subset", "nivel", "pais", "clase", "n_registros", "estado_pais_clase"]])

    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def resumen_matriz_pais_clase(matrix_df: pd.DataFrame) -> pd.DataFrame:
    if matrix_df.empty:
        return matrix_df

    df = (
        matrix_df
        .groupby(["subset", "nivel", "estado_pais_clase"], dropna=False)
        .agg(n_celdas=("n_registros", "size"))
        .reset_index()
    )

    df["pct_celdas"] = df.groupby(["subset", "nivel"])["n_celdas"].transform(
        lambda s: round((s / s.sum()) * 100, 6)
    )

    return df.sort_values(["subset", "nivel", "estado_pais_clase"])


# ============================================================
# CONFLICTOS XY DENTRO DE LOS SUBCONJUNTOS
# ============================================================

def construir_xy_subset_agg(
    conn: sqlite3.Connection,
    subsets: list[dict],
) -> None:
    if not attach_xy_db(conn):
        raise FileNotFoundError(
            "No se pudo acceder a data/interim/03b_multirregistros_xy.sqlite "
            "o no contiene la tabla grupos_xy."
        )

    conn.execute("DROP TABLE IF EXISTS xy_subset_agg;")

    conn.execute(
        """
        CREATE TABLE xy_subset_agg (
            subset TEXT,
            xy_group_id INTEGER,
            lon REAL,
            lat REAL,
            pais_grupo TEXT,
            tipo_grupo_original TEXT,
            n_registros_original INTEGER,
            n_registros_subset INTEGER,
            n_paises_subset INTEGER,
            n_fuentes_subset INTEGER,
            n_anios_subset INTEGER,
            n_nivel0_subset INTEGER,
            n_nivel1_subset INTEGER,
            n_nivel2_subset INTEGER,
            anio_min_subset INTEGER,
            anio_max_subset INTEGER,
            paises_subset TEXT,
            fuentes_subset TEXT,
            anios_subset TEXT,
            valores_nivel0_subset TEXT,
            valores_nivel1_subset TEXT,
            valores_nivel2_subset TEXT,
            estado_xy_subset TEXT
        );
        """
    )

    for spec in subsets:
        sql = f"""
        INSERT INTO xy_subset_agg
        WITH joined AS (
            SELECT
                g.xy_group_id,
                g.lon,
                g.lat,
                g.pais_grupo,
                g.tipo_grupo_xy AS tipo_grupo_original,
                g.n_registros AS n_registros_original,
                b.pais,
                b.fuente,
                b.anio,
                b.nivel_0,
                b.nivel_1,
                b.nivel_2
            FROM xydb.grupos_xy AS g
            JOIN thematic_base AS b
              ON g.lon = b.lon
             AND g.lat = b.lat
            WHERE {spec["where"]}
        ),
        agg AS (
            SELECT
                '{spec["subset"]}' AS subset,
                xy_group_id,
                lon,
                lat,
                pais_grupo,
                tipo_grupo_original,
                n_registros_original,
                COUNT(*) AS n_registros_subset,
                COUNT(DISTINCT pais) AS n_paises_subset,
                COUNT(DISTINCT fuente) AS n_fuentes_subset,
                COUNT(DISTINCT anio) AS n_anios_subset,
                COUNT(DISTINCT nivel_0) AS n_nivel0_subset,
                COUNT(DISTINCT nivel_1) AS n_nivel1_subset,
                COUNT(DISTINCT nivel_2) AS n_nivel2_subset,
                MIN(anio) AS anio_min_subset,
                MAX(anio) AS anio_max_subset,
                GROUP_CONCAT(DISTINCT pais) AS paises_subset,
                GROUP_CONCAT(DISTINCT fuente) AS fuentes_subset,
                GROUP_CONCAT(DISTINCT anio) AS anios_subset,
                GROUP_CONCAT(DISTINCT nivel_0) AS valores_nivel0_subset,
                GROUP_CONCAT(DISTINCT nivel_1) AS valores_nivel1_subset,
                GROUP_CONCAT(DISTINCT nivel_2) AS valores_nivel2_subset
            FROM joined
            GROUP BY
                xy_group_id,
                lon,
                lat,
                pais_grupo,
                tipo_grupo_original,
                n_registros_original
        )
        SELECT
            subset,
            xy_group_id,
            lon,
            lat,
            pais_grupo,
            tipo_grupo_original,
            n_registros_original,
            n_registros_subset,
            n_paises_subset,
            n_fuentes_subset,
            n_anios_subset,
            n_nivel0_subset,
            n_nivel1_subset,
            n_nivel2_subset,
            anio_min_subset,
            anio_max_subset,
            paises_subset,
            fuentes_subset,
            anios_subset,
            valores_nivel0_subset,
            valores_nivel1_subset,
            valores_nivel2_subset,
            CASE
                WHEN n_nivel1_subset > 1 OR n_nivel2_subset > 1 THEN 'conflicto_tematico_subset'
                WHEN n_registros_subset = 1 THEN 'xy_unico_en_subset'
                WHEN n_anios_subset > 1 THEN 'multitemporal_estable_subset'
                WHEN n_fuentes_subset > 1 THEN 'coincidencia_fuentes_misma_clase_subset'
                ELSE 'redundancia_misma_fuente_misma_clase_subset'
            END AS estado_xy_subset
        FROM agg;
        """
        conn.executescript(sql)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_xy_subset_agg_subset ON xy_subset_agg(subset);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_xy_subset_agg_estado ON xy_subset_agg(estado_xy_subset);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_xy_subset_agg_pais ON xy_subset_agg(pais_grupo);")
    conn.commit()


def resumen_estado_xy_subset(conn: sqlite3.Connection) -> pd.DataFrame:
    if not tabla_existe(conn, "xy_subset_agg"):
        return pd.DataFrame([{"warning": "No existe xy_subset_agg."}])

    df = pd.read_sql_query(
        """
        SELECT
            subset,
            estado_xy_subset,
            COUNT(*) AS n_grupos,
            SUM(n_registros_subset) AS n_registros,
            SUM(CASE WHEN n_registros_subset > 1 THEN n_registros_subset - 1 ELSE 0 END) AS exceso_registros_subset,
            AVG(n_registros_subset) AS promedio_registros_por_grupo
        FROM xy_subset_agg
        GROUP BY subset, estado_xy_subset
        ORDER BY subset, n_registros DESC;
        """,
        conn,
    )

    if not df.empty and "n_registros" in df.columns:
        df["pct_grupos_subset"] = df.groupby("subset")["n_grupos"].transform(
            lambda s: round((s / s.sum()) * 100, 6)
        )
        df["pct_registros_subset"] = df.groupby("subset")["n_registros"].transform(
            lambda s: round((s / s.sum()) * 100, 6)
        )

    return df


def resumen_conflictos_xy_subset(conn: sqlite3.Connection) -> pd.DataFrame:
    if not tabla_existe(conn, "xy_subset_agg"):
        return pd.DataFrame([{"warning": "No existe xy_subset_agg."}])

    return pd.read_sql_query(
        """
        SELECT
            subset,
            COUNT(*) AS n_grupos_conflicto,
            SUM(n_registros_subset) AS n_registros_conflicto,
            AVG(n_registros_subset) AS promedio_registros_por_grupo,
            MAX(n_registros_subset) AS max_registros_por_grupo,
            AVG(n_anios_subset) AS promedio_anios_por_grupo,
            MAX(n_anios_subset) AS max_anios_por_grupo,
            AVG(n_nivel1_subset) AS promedio_nivel1_distintos,
            AVG(n_nivel2_subset) AS promedio_nivel2_distintos
        FROM xy_subset_agg
        WHERE estado_xy_subset = 'conflicto_tematico_subset'
        GROUP BY subset
        ORDER BY subset;
        """,
        conn,
    )


def conflictos_xy_por_pais_subset(conn: sqlite3.Connection) -> pd.DataFrame:
    if not tabla_existe(conn, "xy_subset_agg"):
        return pd.DataFrame([{"warning": "No existe xy_subset_agg."}])

    return pd.read_sql_query(
        """
        SELECT
            subset,
            pais_grupo,
            COUNT(*) AS n_grupos_conflicto,
            SUM(n_registros_subset) AS n_registros_conflicto,
            AVG(n_registros_subset) AS promedio_registros_por_grupo,
            AVG(n_anios_subset) AS promedio_anios_por_grupo,
            MAX(n_anios_subset) AS max_anios_por_grupo
        FROM xy_subset_agg
        WHERE estado_xy_subset = 'conflicto_tematico_subset'
        GROUP BY subset, pais_grupo
        ORDER BY subset, n_registros_conflicto DESC;
        """,
        conn,
    )


def combinaciones_conflictivas_subset(conn: sqlite3.Connection, limit: int = 3000) -> pd.DataFrame:
    if not tabla_existe(conn, "xy_subset_agg"):
        return pd.DataFrame([{"warning": "No existe xy_subset_agg."}])

    return pd.read_sql_query(
        f"""
        SELECT
            subset,
            pais_grupo,
            valores_nivel1_subset,
            valores_nivel2_subset,
            COUNT(*) AS n_grupos,
            SUM(n_registros_subset) AS n_registros,
            AVG(n_anios_subset) AS promedio_anios,
            MIN(anio_min_subset) AS anio_min_global,
            MAX(anio_max_subset) AS anio_max_global
        FROM xy_subset_agg
        WHERE estado_xy_subset = 'conflicto_tematico_subset'
        GROUP BY
            subset,
            pais_grupo,
            valores_nivel1_subset,
            valores_nivel2_subset
        ORDER BY subset, n_registros DESC
        LIMIT {int(limit)};
        """,
        conn,
    )


def detalles_conflictos_top_subset(conn: sqlite3.Connection, limit: int = 2000) -> pd.DataFrame:
    if not tabla_existe(conn, "xy_subset_agg"):
        return pd.DataFrame([{"warning": "No existe xy_subset_agg."}])

    return pd.read_sql_query(
        f"""
        SELECT *
        FROM xy_subset_agg
        WHERE estado_xy_subset = 'conflicto_tematico_subset'
        ORDER BY subset, n_registros_subset DESC
        LIMIT {int(limit)};
        """,
        conn,
    )


# ============================================================
# FIGURAS
# ============================================================

def figura_top_clases(df: pd.DataFrame, subset: str, nivel: str, output_name: str) -> None:
    data = df[(df["subset"] == subset) & (df["nivel"] == nivel)].copy()
    if data.empty:
        return

    top = data.head(15).sort_values("n_registros", ascending=True)

    plt.figure(figsize=(9, 6))
    plt.barh(top["clase"].astype(str), top["n_registros"])
    plt.xlabel("Número de registros")
    plt.ylabel(nivel)
    plt.title(f"Top clases {nivel} - {subset}")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / output_name, dpi=200)
    plt.close()


def figura_conflictos_pais(df: pd.DataFrame, subset: str, output_name: str) -> None:
    if df.empty or "subset" not in df.columns:
        return

    data = df[df["subset"] == subset].copy()
    if data.empty:
        return

    top = data.head(12).sort_values("n_registros_conflicto", ascending=True)

    plt.figure(figsize=(9, 6))
    plt.barh(top["pais_grupo"].astype(str), top["n_registros_conflicto"])
    plt.xlabel("Registros en conflicto temático")
    plt.ylabel("País")
    plt.title(f"Conflictos temáticos XY por país - {subset}")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / output_name, dpi=200)
    plt.close()


def generar_figuras(
    dist_nivel1: pd.DataFrame,
    dist_nivel2: pd.DataFrame,
    conflicts_by_country: pd.DataFrame,
    subsets: list[dict],
) -> None:
    for spec in subsets:
        subset = spec["subset"]
        figura_top_clases(
            dist_nivel1,
            subset=subset,
            nivel="Nivel_1",
            output_name=f"05b_top_nivel1_{subset}.png",
        )
        figura_top_clases(
            dist_nivel2,
            subset=subset,
            nivel="Nivel_2",
            output_name=f"05b_top_nivel2_{subset}.png",
        )
        figura_conflictos_pais(
            conflicts_by_country,
            subset=subset,
            output_name=f"05b_conflictos_tematicos_pais_{subset}.png",
        )


# ============================================================
# REPORTE
# ============================================================

def generar_reporte(
    total_base: int,
    subset_summary: pd.DataFrame,
    dist_nivel1: pd.DataFrame,
    dist_nivel2: pd.DataFrame,
    country_summary: pd.DataFrame,
    source_summary: pd.DataFrame,
    matrix_summary: pd.DataFrame,
    xy_state_summary: pd.DataFrame,
    conflicts_summary: pd.DataFrame,
    conflicts_by_country: pd.DataFrame,
    conflict_combinations: pd.DataFrame,
) -> None:
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_path = REPORTS_DIR / "05b_auditoria_tematica_ventana.md"

    contenido = "\n".join(
        [
            "# Auditoría temática focalizada en 2020 y ventana 2018-2022",
            "",
            "## Módulo 5B",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## Propósito",
            "",
            "Este módulo complementa la auditoría temática general del Módulo 5, restringiendo el análisis a dos subconjuntos temporales: registros exactamente del año objetivo 2020 y registros dentro de la ventana 2018-2022.",
            "",
            "## Total de registros de la base temática",
            "",
            f"`{total_base}` registros.",
            "",
            "## Resumen de subconjuntos temporales",
            "",
            dataframe_a_markdown(subset_summary),
            "",
            "## Distribución de clases Nivel_1",
            "",
            dataframe_a_markdown(dist_nivel1.head(60)),
            "",
            "## Distribución de clases Nivel_2",
            "",
            dataframe_a_markdown(dist_nivel2.head(80)),
            "",
            "## Cobertura por país",
            "",
            dataframe_a_markdown(country_summary),
            "",
            "## Principales fuentes por subconjunto",
            "",
            dataframe_a_markdown(source_summary.head(60)),
            "",
            "## Resumen de matriz país-clase",
            "",
            dataframe_a_markdown(matrix_summary),
            "",
            "## Estado de grupos XY dentro de cada subconjunto",
            "",
            dataframe_a_markdown(xy_state_summary),
            "",
            "## Resumen de conflictos temáticos XY dentro de cada subconjunto",
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
            "## Interpretación metodológica",
            "",
            "La auditoría general del Módulo 5 indica cómo se comporta toda la base histórica. El Módulo 5B permite identificar qué parte de esa estructura temática permanece vigente cuando se prioriza la línea base 2020.",
            "",
            "La comparación entre exacto_2020 y ventana_2018_2022 permite distinguir tres situaciones:",
            "",
            "1. Clases robustas en 2020 estricto.",
            "2. Clases que solo se vuelven robustas al ampliar la ventana temporal.",
            "3. Clases, países o combinaciones país-clase que permanecen críticas incluso con ventana ampliada.",
            "",
            "## Regla operativa recomendada",
            "",
            "```text",
            "No usar la distribución temática global como único criterio de aptitud. Para línea base 2020, toda decisión de clase, país, fuente o conflicto debe revisarse también dentro de exacto_2020 y ventana_2018_2022.",
            "```",
            "",
        ]
    )

    report_path.write_text(contenido, encoding="utf-8")


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Módulo 5B: auditoría temática focalizada en 2020 y ventana 2018-2022."
    )
    parser.add_argument(
        "--rebuild-xy-subset",
        action="store_true",
        help="Reconstruye la tabla xy_subset_agg.",
    )
    parser.add_argument(
        "--skip-xy-conflicts",
        action="store_true",
        help="Omite análisis de conflictos XY para ejecución rápida.",
    )
    args = parser.parse_args()

    crear_carpetas_salida()

    config = cargar_yaml(CONFIG_PATH)

    temporal_cfg = config.get("temporal", {})
    thematic_cfg = config.get("thematic", {})
    thematic_window_cfg = config.get("thematic_window", {})

    target_year = int(
        thematic_window_cfg.get(
            "target_year",
            temporal_cfg.get("target_year", 2020),
        )
    )
    near_window = int(
        thematic_window_cfg.get(
            "near_window_years",
            temporal_cfg.get("near_window_years", 2),
        )
    )

    min_low = int(
        thematic_window_cfg.get(
            "min_records_low_class",
            thematic_cfg.get("min_records_low_class", 100),
        )
    )
    min_critical = int(
        thematic_window_cfg.get(
            "min_records_critical_class",
            thematic_cfg.get("min_records_critical_class", 30),
        )
    )
    min_sufficient = int(
        thematic_window_cfg.get("min_records_sufficient_country_class", 500)
    )

    subsets = construir_subsets(target_year, near_window)

    conn = abrir_conexion()

    try:
        validar_thematic_base(conn)

        total_base = obtener_total_base(conn)

        subset_summary = resumen_subsets(conn, subsets, total_base)
        country_summary = cobertura_pais_subset(conn, subsets)
        source_summary = cobertura_fuente_subset(conn, subsets)

        dist_nivel0 = distribucion_clases_subset(
            conn,
            subsets,
            class_field="nivel_0",
            class_level="Nivel_0",
            min_low=min_low,
            min_critical=min_critical,
        )
        dist_nivel1 = distribucion_clases_subset(
            conn,
            subsets,
            class_field="nivel_1",
            class_level="Nivel_1",
            min_low=min_low,
            min_critical=min_critical,
        )
        dist_nivel2 = distribucion_clases_subset(
            conn,
            subsets,
            class_field="nivel_2",
            class_level="Nivel_2",
            min_low=min_low,
            min_critical=min_critical,
        )

        class_country_nivel1 = distribucion_clase_por_pais(
            conn,
            subsets,
            class_field="nivel_1",
            class_level="Nivel_1",
        )
        class_country_nivel2 = distribucion_clase_por_pais(
            conn,
            subsets,
            class_field="nivel_2",
            class_level="Nivel_2",
        )

        class_source_nivel1 = distribucion_clase_por_fuente(
            conn,
            subsets,
            class_field="nivel_1",
            class_level="Nivel_1",
        )
        class_source_nivel2 = distribucion_clase_por_fuente(
            conn,
            subsets,
            class_field="nivel_2",
            class_level="Nivel_2",
        )

        matrix_nivel1 = matriz_pais_clase(
            conn,
            subsets,
            class_field="nivel_1",
            class_level="Nivel_1",
            min_low=min_low,
            min_critical=min_critical,
            min_sufficient=min_sufficient,
        )
        matrix_nivel2 = matriz_pais_clase(
            conn,
            subsets,
            class_field="nivel_2",
            class_level="Nivel_2",
            min_low=min_low,
            min_critical=min_critical,
            min_sufficient=min_sufficient,
        )

        matrix_all = pd.concat([matrix_nivel1, matrix_nivel2], ignore_index=True)
        matrix_summary = resumen_matriz_pais_clase(matrix_all)

        if args.skip_xy_conflicts:
            xy_state_summary = pd.DataFrame([{"warning": "Análisis XY omitido por --skip-xy-conflicts."}])
            conflicts_summary = xy_state_summary.copy()
            conflicts_by_country = xy_state_summary.copy()
            conflict_combinations = xy_state_summary.copy()
            conflict_details = xy_state_summary.copy()
        else:
            if args.rebuild_xy_subset or not tabla_existe(conn, "xy_subset_agg"):
                print("Construyendo xy_subset_agg. Esto puede tardar varios minutos...")
                construir_xy_subset_agg(conn, subsets)
            else:
                print("Usando xy_subset_agg existente. Usa --rebuild-xy-subset para reconstruirla.")

            xy_state_summary = resumen_estado_xy_subset(conn)
            conflicts_summary = resumen_conflictos_xy_subset(conn)
            conflicts_by_country = conflictos_xy_por_pais_subset(conn)
            conflict_combinations = combinaciones_conflictivas_subset(conn)
            conflict_details = detalles_conflictos_top_subset(conn)

        # Exportar tablas
        subset_summary.to_csv(TABLES_DIR / "05b_subset_summary.csv", index=False, encoding="utf-8-sig")
        country_summary.to_csv(TABLES_DIR / "05b_country_summary_by_subset.csv", index=False, encoding="utf-8-sig")
        source_summary.to_csv(TABLES_DIR / "05b_source_summary_by_subset.csv", index=False, encoding="utf-8-sig")

        dist_nivel0.to_csv(TABLES_DIR / "05b_class_distribution_nivel0_by_subset.csv", index=False, encoding="utf-8-sig")
        dist_nivel1.to_csv(TABLES_DIR / "05b_class_distribution_nivel1_by_subset.csv", index=False, encoding="utf-8-sig")
        dist_nivel2.to_csv(TABLES_DIR / "05b_class_distribution_nivel2_by_subset.csv", index=False, encoding="utf-8-sig")

        class_country_nivel1.to_csv(TABLES_DIR / "05b_class_by_country_nivel1_by_subset.csv", index=False, encoding="utf-8-sig")
        class_country_nivel2.to_csv(TABLES_DIR / "05b_class_by_country_nivel2_by_subset.csv", index=False, encoding="utf-8-sig")
        class_source_nivel1.to_csv(TABLES_DIR / "05b_class_by_source_nivel1_by_subset.csv", index=False, encoding="utf-8-sig")
        class_source_nivel2.to_csv(TABLES_DIR / "05b_class_by_source_nivel2_by_subset.csv", index=False, encoding="utf-8-sig")

        matrix_nivel1.to_csv(TABLES_DIR / "05b_country_class_matrix_nivel1.csv", index=False, encoding="utf-8-sig")
        matrix_nivel2.to_csv(TABLES_DIR / "05b_country_class_matrix_nivel2.csv", index=False, encoding="utf-8-sig")
        matrix_summary.to_csv(TABLES_DIR / "05b_country_class_matrix_summary.csv", index=False, encoding="utf-8-sig")

        xy_state_summary.to_csv(TABLES_DIR / "05b_xy_group_type_by_subset.csv", index=False, encoding="utf-8-sig")
        conflicts_summary.to_csv(TABLES_DIR / "05b_thematic_conflicts_xy_summary_by_subset.csv", index=False, encoding="utf-8-sig")
        conflicts_by_country.to_csv(TABLES_DIR / "05b_thematic_conflicts_xy_by_country_by_subset.csv", index=False, encoding="utf-8-sig")
        conflict_combinations.to_csv(TABLES_DIR / "05b_thematic_conflict_class_combinations_by_subset.csv", index=False, encoding="utf-8-sig")
        conflict_details.to_csv(TABLES_DIR / "05b_thematic_conflicts_xy_details_top_by_subset.csv", index=False, encoding="utf-8-sig")

        audit_summary = pd.DataFrame(
            [
                {
                    "total_base": total_base,
                    "target_year": target_year,
                    "near_window_years": near_window,
                    "window_start": target_year - near_window,
                    "window_end": target_year + near_window,
                    "n_subsets": len(subsets),
                    "min_records_low_class": min_low,
                    "min_records_critical_class": min_critical,
                    "min_records_sufficient_country_class": min_sufficient,
                }
            ]
        )
        audit_summary.to_csv(TABLES_DIR / "05b_thematic_window_audit_summary.csv", index=False, encoding="utf-8-sig")

        generar_figuras(
            dist_nivel1=dist_nivel1,
            dist_nivel2=dist_nivel2,
            conflicts_by_country=conflicts_by_country,
            subsets=subsets,
        )

        generar_reporte(
            total_base=total_base,
            subset_summary=subset_summary,
            dist_nivel1=dist_nivel1,
            dist_nivel2=dist_nivel2,
            country_summary=country_summary,
            source_summary=source_summary,
            matrix_summary=matrix_summary,
            xy_state_summary=xy_state_summary,
            conflicts_summary=conflicts_summary,
            conflicts_by_country=conflicts_by_country,
            conflict_combinations=conflict_combinations,
        )

        registrar_log(
            "Módulo 5B ejecutado correctamente. "
            f"Año objetivo: {target_year}. Ventana: ±{near_window}. "
            f"Total thematic_base: {total_base}."
        )

        print("Módulo 5B ejecutado correctamente.")
        print(f"Total base temática: {total_base}")
        print(f"Año objetivo: {target_year}")
        print(f"Ventana: {target_year - near_window}-{target_year + near_window}")
        print("Salidas generadas en outputs/tables, outputs/figures y outputs/reports.")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        registrar_log("Error durante la ejecución del Módulo 5B.")
        traceback.print_exc()
        raise
