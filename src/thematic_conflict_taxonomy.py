"""
Módulo 5C - Taxonomía y severidad de conflictos temáticos.

Este módulo toma los grupos XY conflictivos identificados en el Módulo 5B
y los clasifica por tipo, severidad y prioridad de revisión.

Objetivos:
- Clasificar conflictos temáticos por tipo:
  bosque_vs_no_bosque, intraforestal, agropecuario_interno, residual_otras,
  mismo_nivel1_distinto_nivel2, posible_cambio_temporal, conflicto_mismo_anio,
  conflicto_multifuente_mismo_anio u otro_conflicto_tematico.
- Identificar conflictos en el mismo año.
- Identificar conflictos multifuente.
- Generar ranking de revisión prioritaria.
- Generar combinaciones conflictivas Nivel_1 y Nivel_2.
- Producir tablas, figuras y reporte Markdown.

Requisitos:
- data/interim/05_thematic_audit.sqlite con:
  - thematic_base
  - xy_subset_agg
- data/interim/03b_multirregistros_xy.sqlite no se consulta directamente aquí,
  salvo que xy_subset_agg haya sido generado previamente por el Módulo 5B.

Principios:
- No modifica el GeoPackage original.
- Trabaja sobre bases intermedias.
- Prioriza la ventana 2018-2022 como subconjunto operativo principal.
"""

from __future__ import annotations

from datetime import datetime
from itertools import combinations
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


# ============================================================
# FUNCIONES GENERALES
# ============================================================

def crear_carpetas_salida() -> None:
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


def dataframe_a_markdown(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


def abrir_conexion() -> sqlite3.Connection:
    if not THEMATIC_DB.exists():
        raise FileNotFoundError(
            "No existe data/interim/05_thematic_audit.sqlite. "
            "Ejecuta primero el Módulo 5."
        )

    conn = sqlite3.connect(THEMATIC_DB)
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -200000;")
    return conn


def tabla_existe(conn: sqlite3.Connection, table_name: str) -> bool:
    sql = """
    SELECT COUNT(*) AS n
    FROM sqlite_master
    WHERE type = 'table' AND name = ?;
    """
    return int(conn.execute(sql, (table_name,)).fetchone()[0]) > 0


def validar_insumos(conn: sqlite3.Connection) -> None:
    requeridas = ["thematic_base", "xy_subset_agg"]
    faltantes = [t for t in requeridas if not tabla_existe(conn, t)]

    if faltantes:
        raise ValueError(
            f"Faltan tablas requeridas en {THEMATIC_DB}: {faltantes}. "
            "Ejecuta primero el Módulo 5 y luego el Módulo 5B con --rebuild-xy-subset."
        )


def obtener_subsets_conflictivos(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT subset
        FROM xy_subset_agg
        WHERE estado_xy_subset = 'conflicto_tematico_subset'
        ORDER BY subset;
        """
    ).fetchall()

    return [r[0] for r in rows]


def subset_where_clause(subset: str, target_year: int, near_window: int) -> str:
    start_year = target_year - near_window
    end_year = target_year + near_window

    if subset == f"exacto_{target_year}":
        return f"b.anio = {int(target_year)}"

    if subset == f"ventana_{start_year}_{end_year}":
        return f"b.anio BETWEEN {int(start_year)} AND {int(end_year)}"

    # Fallback para subconjuntos con nombres esperados.
    if subset.startswith("exacto_"):
        year = int(subset.replace("exacto_", ""))
        return f"b.anio = {year}"

    if subset.startswith("ventana_"):
        parts = subset.replace("ventana_", "").split("_")
        if len(parts) == 2:
            return f"b.anio BETWEEN {int(parts[0])} AND {int(parts[1])}"

    raise ValueError(f"No se pudo interpretar el subconjunto temporal: {subset}")


def normalizar_texto(valor) -> str:
    if pd.isna(valor):
        return ""
    return str(valor).strip().lower()


def contiene_alguna(texto: str, keywords: list[str]) -> bool:
    texto = normalizar_texto(texto)
    return any(k.lower() in texto for k in keywords)


# ============================================================
# CONSTRUCCIÓN DE DETALLE DE CONFLICTOS
# ============================================================

def construir_conflict_records(
    conn: sqlite3.Connection,
    subsets: list[str],
    target_year: int,
    near_window: int,
) -> None:
    """
    Crea una tabla detallada con los registros involucrados en conflictos temáticos
    dentro de los subconjuntos temporales definidos en xy_subset_agg.
    """
    conn.execute("DROP TABLE IF EXISTS conflict_records_05c;")

    conn.execute(
        """
        CREATE TABLE conflict_records_05c (
            subset TEXT,
            xy_group_id INTEGER,
            lon REAL,
            lat REAL,
            pais_grupo TEXT,
            tipo_grupo_original TEXT,
            n_registros_original INTEGER,
            n_registros_subset INTEGER,
            estado_xy_subset TEXT,
            source_rowid INTEGER,
            pais TEXT,
            fuente TEXT,
            anio INTEGER,
            nivel_0 TEXT,
            nivel_1 TEXT,
            nivel_2 TEXT
        );
        """
    )

    for subset in subsets:
        where_clause = subset_where_clause(subset, target_year, near_window)

        sql = f"""
        INSERT INTO conflict_records_05c
        SELECT
            c.subset,
            c.xy_group_id,
            c.lon,
            c.lat,
            c.pais_grupo,
            c.tipo_grupo_original,
            c.n_registros_original,
            c.n_registros_subset,
            c.estado_xy_subset,
            b.source_rowid,
            b.pais,
            b.fuente,
            b.anio,
            b.nivel_0,
            b.nivel_1,
            b.nivel_2
        FROM xy_subset_agg AS c
        JOIN thematic_base AS b
          ON c.lon = b.lon
         AND c.lat = b.lat
        WHERE c.subset = '{subset}'
          AND c.estado_xy_subset = 'conflicto_tematico_subset'
          AND {where_clause};
        """
        conn.executescript(sql)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_conflict_records_05c_subset ON conflict_records_05c(subset);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conflict_records_05c_xy ON conflict_records_05c(xy_group_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conflict_records_05c_pais ON conflict_records_05c(pais_grupo);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conflict_records_05c_anio ON conflict_records_05c(anio);")
    conn.commit()


def leer_group_base(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
    SELECT
        subset,
        xy_group_id,
        lon,
        lat,
        pais_grupo,
        MIN(tipo_grupo_original) AS tipo_grupo_original,
        MAX(n_registros_original) AS n_registros_original,
        COUNT(*) AS n_registros_conflicto,
        COUNT(DISTINCT pais) AS n_paises,
        COUNT(DISTINCT fuente) AS n_fuentes,
        COUNT(DISTINCT anio) AS n_anios,
        COUNT(DISTINCT nivel_0) AS n_nivel0,
        COUNT(DISTINCT nivel_1) AS n_nivel1,
        COUNT(DISTINCT nivel_2) AS n_nivel2,
        MIN(anio) AS anio_min,
        MAX(anio) AS anio_max,
        GROUP_CONCAT(DISTINCT pais) AS paises,
        GROUP_CONCAT(DISTINCT fuente) AS fuentes,
        GROUP_CONCAT(DISTINCT anio) AS anios,
        GROUP_CONCAT(DISTINCT nivel_0) AS valores_nivel_0,
        GROUP_CONCAT(DISTINCT nivel_1) AS valores_nivel_1,
        GROUP_CONCAT(DISTINCT nivel_2) AS valores_nivel_2
    FROM conflict_records_05c
    GROUP BY subset, xy_group_id, lon, lat, pais_grupo
    ORDER BY subset, n_registros_conflicto DESC;
    """
    return pd.read_sql_query(sql, conn)


def leer_same_year_flags(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
    WITH year_agg AS (
        SELECT
            subset,
            xy_group_id,
            anio,
            COUNT(*) AS n_registros_anio,
            COUNT(DISTINCT fuente) AS n_fuentes_anio,
            COUNT(DISTINCT nivel_0) AS n_nivel0_anio,
            COUNT(DISTINCT nivel_1) AS n_nivel1_anio,
            COUNT(DISTINCT nivel_2) AS n_nivel2_anio,
            GROUP_CONCAT(DISTINCT fuente) AS fuentes_anio,
            GROUP_CONCAT(DISTINCT nivel_1) AS valores_nivel1_anio,
            GROUP_CONCAT(DISTINCT nivel_2) AS valores_nivel2_anio
        FROM conflict_records_05c
        GROUP BY subset, xy_group_id, anio
    )
    SELECT
        subset,
        xy_group_id,
        MAX(
            CASE
                WHEN n_nivel1_anio > 1 OR n_nivel2_anio > 1 THEN 1
                ELSE 0
            END
        ) AS flag_conflicto_mismo_anio,
        MAX(
            CASE
                WHEN (n_nivel1_anio > 1 OR n_nivel2_anio > 1)
                 AND n_fuentes_anio > 1 THEN 1
                ELSE 0
            END
        ) AS flag_conflicto_multifuente_mismo_anio,
        MAX(n_fuentes_anio) AS max_fuentes_en_un_anio,
        MAX(n_nivel1_anio) AS max_nivel1_en_un_anio,
        MAX(n_nivel2_anio) AS max_nivel2_en_un_anio
    FROM year_agg
    GROUP BY subset, xy_group_id;
    """
    return pd.read_sql_query(sql, conn)


def leer_same_year_details(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
    WITH year_agg AS (
        SELECT
            subset,
            xy_group_id,
            anio,
            COUNT(*) AS n_registros_anio,
            COUNT(DISTINCT fuente) AS n_fuentes_anio,
            COUNT(DISTINCT nivel_0) AS n_nivel0_anio,
            COUNT(DISTINCT nivel_1) AS n_nivel1_anio,
            COUNT(DISTINCT nivel_2) AS n_nivel2_anio,
            GROUP_CONCAT(DISTINCT fuente) AS fuentes_anio,
            GROUP_CONCAT(DISTINCT nivel_0) AS valores_nivel0_anio,
            GROUP_CONCAT(DISTINCT nivel_1) AS valores_nivel1_anio,
            GROUP_CONCAT(DISTINCT nivel_2) AS valores_nivel2_anio
        FROM conflict_records_05c
        GROUP BY subset, xy_group_id, anio
    )
    SELECT *
    FROM year_agg
    WHERE n_nivel1_anio > 1 OR n_nivel2_anio > 1
    ORDER BY subset, n_registros_anio DESC;
    """
    return pd.read_sql_query(sql, conn)


# ============================================================
# CLASIFICACIÓN DE CONFLICTOS
# ============================================================

def calcular_flags_semanticos(
    df: pd.DataFrame,
    forest_keywords: list[str],
    agro_keywords: list[str],
    residual_keywords: list[str],
    water_keywords: list[str],
) -> pd.DataFrame:
    rows = []

    for _, row in df.iterrows():
        textos = " | ".join(
            [
                normalizar_texto(row.get("valores_nivel_0", "")),
                normalizar_texto(row.get("valores_nivel_1", "")),
                normalizar_texto(row.get("valores_nivel_2", "")),
            ]
        )

        nivel0 = normalizar_texto(row.get("valores_nivel_0", ""))
        nivel1 = normalizar_texto(row.get("valores_nivel_1", ""))
        nivel2 = normalizar_texto(row.get("valores_nivel_2", ""))

        has_forest = contiene_alguna(textos, forest_keywords)
        has_agro = contiene_alguna(textos, agro_keywords)
        has_residual = contiene_alguna(textos, residual_keywords)
        has_water = contiene_alguna(textos, water_keywords)

        # No forestal aproximado: cualquier grupo que tenga señales no forestales
        # o más de un Nivel_0 con una señal forestal.
        has_nonforest = (
            has_agro
            or has_water
            or has_residual
            or ("cultivo" in nivel0)
            or ("artificial" in nivel0)
            or ("agua" in nivel0)
            or ("humedal" in nivel0)
            or ("otras" in nivel0)
        )

        rows.append(
            {
                "subset": row["subset"],
                "xy_group_id": row["xy_group_id"],
                "flag_forestal": int(has_forest),
                "flag_no_forestal": int(has_nonforest),
                "flag_bosque_vs_no_bosque": int(has_forest and has_nonforest),
                "flag_agropecuario": int(has_agro),
                "flag_residual_otras": int(has_residual),
                "flag_agua_humedal": int(has_water),
            }
        )

    flags = pd.DataFrame(rows)

    return df.merge(flags, on=["subset", "xy_group_id"], how="left")


def asignar_tipo_conflicto(row: pd.Series) -> str:
    mismo_anio = int(row.get("flag_conflicto_mismo_anio", 0) or 0)
    multifuente_mismo_anio = int(row.get("flag_conflicto_multifuente_mismo_anio", 0) or 0)
    bosque_no_bosque = int(row.get("flag_bosque_vs_no_bosque", 0) or 0)
    residual = int(row.get("flag_residual_otras", 0) or 0)
    forestal = int(row.get("flag_forestal", 0) or 0)
    no_forestal = int(row.get("flag_no_forestal", 0) or 0)
    agro = int(row.get("flag_agropecuario", 0) or 0)

    n_anios = int(row.get("n_anios", 0) or 0)
    n_nivel1 = int(row.get("n_nivel1", 0) or 0)
    n_nivel2 = int(row.get("n_nivel2", 0) or 0)

    if bosque_no_bosque:
        return "bosque_vs_no_bosque"

    if multifuente_mismo_anio:
        return "conflicto_multifuente_mismo_anio"

    if mismo_anio:
        return "conflicto_mismo_anio"

    if residual:
        return "residual_otras"

    if n_anios > 1 and mismo_anio == 0:
        return "posible_cambio_temporal"

    if forestal and not no_forestal:
        return "intraforestal"

    if agro and not forestal:
        return "agropecuario_interno"

    if n_nivel1 == 1 and n_nivel2 > 1:
        return "mismo_nivel1_distinto_nivel2"

    return "otro_conflicto_tematico"


def asignar_severidad(row: pd.Series) -> str:
    tipo = row.get("tipo_conflicto", "")
    mismo_anio = int(row.get("flag_conflicto_mismo_anio", 0) or 0)
    multifuente_mismo_anio = int(row.get("flag_conflicto_multifuente_mismo_anio", 0) or 0)
    n_nivel0 = int(row.get("n_nivel0", 0) or 0)

    if tipo == "bosque_vs_no_bosque" and mismo_anio:
        return "muy_alta"

    if mismo_anio and n_nivel0 > 1:
        return "muy_alta"

    if tipo in [
        "bosque_vs_no_bosque",
        "conflicto_multifuente_mismo_anio",
        "conflicto_mismo_anio",
        "residual_otras",
    ]:
        return "alta"

    if multifuente_mismo_anio:
        return "alta"

    if tipo in [
        "posible_cambio_temporal",
        "agropecuario_interno",
    ]:
        return "media"

    if tipo in [
        "intraforestal",
        "mismo_nivel1_distinto_nivel2",
    ]:
        return "baja"

    return "media"


def asignar_recomendacion(row: pd.Series) -> str:
    severidad = row.get("severidad_conflicto", "")
    tipo = row.get("tipo_conflicto", "")

    if severidad == "muy_alta":
        return "revision_prioritaria_fotointerpretacion"

    if tipo == "bosque_vs_no_bosque":
        return "revision_prioritaria_bosque_no_bosque"

    if tipo == "conflicto_multifuente_mismo_anio":
        return "resolver_por_jerarquia_fuente_o_revision"

    if tipo == "conflicto_mismo_anio":
        return "revision_tematico_temporal_prioritaria"

    if tipo == "residual_otras":
        return "revisar_semantica_categoria_otras"

    if tipo == "posible_cambio_temporal":
        return "evaluar_como_cambio_temporal_potencial"

    if tipo == "intraforestal":
        return "posible_uso_en_nivel_agregado_forestal"

    if tipo == "mismo_nivel1_distinto_nivel2":
        return "usar_potencialmente_a_nivel1"

    if tipo == "agropecuario_interno":
        return "revisar_si_afecta_objetivo_forestal"

    return "revision_general"


def calcular_score_prioridad(row: pd.Series, priority_subset: str) -> int:
    severidad = row.get("severidad_conflicto", "")
    tipo = row.get("tipo_conflicto", "")
    subset = row.get("subset", "")

    base = {
        "muy_alta": 70,
        "alta": 55,
        "media": 35,
        "baja": 20,
    }.get(severidad, 30)

    score = base

    if subset == priority_subset:
        score += 12

    if str(subset).startswith("exacto_"):
        score += 20

    if int(row.get("flag_conflicto_mismo_anio", 0) or 0) == 1:
        score += 10

    if int(row.get("flag_conflicto_multifuente_mismo_anio", 0) or 0) == 1:
        score += 10

    if int(row.get("flag_bosque_vs_no_bosque", 0) or 0) == 1:
        score += 12

    if int(row.get("flag_residual_otras", 0) or 0) == 1:
        score += 6

    n_reg = int(row.get("n_registros_conflicto", 0) or 0)
    score += min(10, n_reg)

    if tipo == "posible_cambio_temporal":
        score += 3

    return int(min(score, 100))


def clasificar_conflictos(
    group_base: pd.DataFrame,
    same_year_flags: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    cfg = config.get("conflict_taxonomy", {})
    temporal_cfg = config.get("temporal", {})

    target_year = int(temporal_cfg.get("target_year", 2020))
    near_window = int(temporal_cfg.get("near_window_years", 2))
    priority_subset = cfg.get(
        "priority_subset",
        f"ventana_{target_year - near_window}_{target_year + near_window}",
    )

    forest_keywords = cfg.get("forest_keywords", ["forest", "bosque", "manglar"])
    agro_keywords = cfg.get("agro_keywords", ["cultivo", "pastizal", "matorral", "cafe", "café"])
    residual_keywords = cfg.get("residual_keywords", ["otras", "otra"])
    water_keywords = cfg.get("water_keywords", ["agua", "humedal"])

    df = group_base.merge(
        same_year_flags,
        on=["subset", "xy_group_id"],
        how="left",
    )

    fill_cols = [
        "flag_conflicto_mismo_anio",
        "flag_conflicto_multifuente_mismo_anio",
        "max_fuentes_en_un_anio",
        "max_nivel1_en_un_anio",
        "max_nivel2_en_un_anio",
    ]

    for col in fill_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)

    df = calcular_flags_semanticos(
        df,
        forest_keywords=forest_keywords,
        agro_keywords=agro_keywords,
        residual_keywords=residual_keywords,
        water_keywords=water_keywords,
    )

    df["tipo_conflicto"] = df.apply(asignar_tipo_conflicto, axis=1)
    df["severidad_conflicto"] = df.apply(asignar_severidad, axis=1)
    df["recomendacion_operativa"] = df.apply(asignar_recomendacion, axis=1)
    df["score_prioridad_revision"] = df.apply(
        lambda row: calcular_score_prioridad(row, priority_subset),
        axis=1,
    )

    df = df.sort_values(
        ["score_prioridad_revision", "n_registros_conflicto"],
        ascending=[False, False],
    ).reset_index(drop=True)

    return df


# ============================================================
# RESÚMENES Y PARES DE CLASES
# ============================================================

def resumen_taxonomia(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    out = (
        df.groupby(["subset", "tipo_conflicto", "severidad_conflicto"], dropna=False)
        .agg(
            n_grupos=("xy_group_id", "count"),
            n_registros=("n_registros_conflicto", "sum"),
            promedio_score=("score_prioridad_revision", "mean"),
            max_score=("score_prioridad_revision", "max"),
        )
        .reset_index()
        .sort_values(["subset", "n_registros"], ascending=[True, False])
    )

    out["promedio_score"] = out["promedio_score"].round(3)

    return out


def resumen_severidad_pais(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    out = (
        df.groupby(["subset", "pais_grupo", "severidad_conflicto"], dropna=False)
        .agg(
            n_grupos=("xy_group_id", "count"),
            n_registros=("n_registros_conflicto", "sum"),
            promedio_score=("score_prioridad_revision", "mean"),
            max_score=("score_prioridad_revision", "max"),
        )
        .reset_index()
        .sort_values(["subset", "pais_grupo", "n_registros"], ascending=[True, True, False])
    )

    out["promedio_score"] = out["promedio_score"].round(3)

    return out


def resumen_tipo_pais(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    out = (
        df.groupby(["subset", "pais_grupo", "tipo_conflicto"], dropna=False)
        .agg(
            n_grupos=("xy_group_id", "count"),
            n_registros=("n_registros_conflicto", "sum"),
            promedio_score=("score_prioridad_revision", "mean"),
            max_score=("score_prioridad_revision", "max"),
        )
        .reset_index()
        .sort_values(["subset", "pais_grupo", "n_registros"], ascending=[True, True, False])
    )

    out["promedio_score"] = out["promedio_score"].round(3)

    return out


def casos_revision_prioritaria(
    df: pd.DataFrame,
    review_threshold: int,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    return (
        df[df["score_prioridad_revision"] >= review_threshold]
        .copy()
        .sort_values(["score_prioridad_revision", "n_registros_conflicto"], ascending=[False, False])
    )


def posibles_cambios_temporales(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    return df[df["tipo_conflicto"] == "posible_cambio_temporal"].copy()


def conflictos_mismo_anio(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    return df[df["flag_conflicto_mismo_anio"] == 1].copy()


def conflictos_multifuente_mismo_anio(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    return df[df["flag_conflicto_multifuente_mismo_anio"] == 1].copy()


def construir_pares_clase(
    records_df: pd.DataFrame,
    details_df: pd.DataFrame,
    class_field: str,
    class_level: str,
) -> pd.DataFrame:
    if records_df.empty or details_df.empty:
        return pd.DataFrame()

    rows = []

    grouped = records_df.groupby(["subset", "xy_group_id"], dropna=False)

    details_index = details_df.set_index(["subset", "xy_group_id"])

    for (subset, xy_group_id), g in grouped:
        classes = sorted([str(x) for x in g[class_field].dropna().unique().tolist()])

        if len(classes) < 2:
            continue

        try:
            detail = details_index.loc[(subset, xy_group_id)]
            if isinstance(detail, pd.DataFrame):
                detail = detail.iloc[0]
        except KeyError:
            continue

        for a, b in combinations(classes, 2):
            rows.append(
                {
                    "subset": subset,
                    "xy_group_id": xy_group_id,
                    "pais_grupo": detail.get("pais_grupo"),
                    "class_level": class_level,
                    "clase_a": a,
                    "clase_b": b,
                    "n_registros_conflicto": detail.get("n_registros_conflicto"),
                    "tipo_conflicto": detail.get("tipo_conflicto"),
                    "severidad_conflicto": detail.get("severidad_conflicto"),
                    "score_prioridad_revision": detail.get("score_prioridad_revision"),
                }
            )

    pair_df = pd.DataFrame(rows)

    if pair_df.empty:
        return pair_df

    summary = (
        pair_df.groupby(
            [
                "subset",
                "pais_grupo",
                "class_level",
                "clase_a",
                "clase_b",
                "tipo_conflicto",
                "severidad_conflicto",
            ],
            dropna=False,
        )
        .agg(
            n_grupos=("xy_group_id", "nunique"),
            n_registros=("n_registros_conflicto", "sum"),
            promedio_score=("score_prioridad_revision", "mean"),
            max_score=("score_prioridad_revision", "max"),
        )
        .reset_index()
        .sort_values(["subset", "n_registros"], ascending=[True, False])
    )

    summary["promedio_score"] = summary["promedio_score"].round(3)

    return summary


# ============================================================
# FIGURAS
# ============================================================

def generar_figuras(
    taxonomy_summary: pd.DataFrame,
    severity_country: pd.DataFrame,
    priority_cases: pd.DataFrame,
) -> None:
    if not taxonomy_summary.empty:
        for subset in taxonomy_summary["subset"].dropna().unique():
            data = taxonomy_summary[taxonomy_summary["subset"] == subset].copy()

            if data.empty:
                continue

            plot_data = (
                data.groupby("tipo_conflicto", dropna=False)["n_registros"]
                .sum()
                .reset_index()
                .sort_values("n_registros", ascending=True)
            )

            plt.figure(figsize=(10, 6))
            plt.barh(plot_data["tipo_conflicto"].astype(str), plot_data["n_registros"])
            plt.xlabel("Registros en conflicto")
            plt.ylabel("Tipo de conflicto")
            plt.title(f"Taxonomía de conflictos temáticos - {subset}")
            plt.tight_layout()
            plt.savefig(FIGURES_DIR / f"05c_taxonomia_conflictos_{subset}.png", dpi=200)
            plt.close()

    if not severity_country.empty:
        for subset in severity_country["subset"].dropna().unique():
            data = severity_country[severity_country["subset"] == subset].copy()

            if data.empty:
                continue

            country_data = (
                data.groupby("pais_grupo", dropna=False)["n_registros"]
                .sum()
                .reset_index()
                .sort_values("n_registros", ascending=True)
            )

            plt.figure(figsize=(9, 6))
            plt.barh(country_data["pais_grupo"].astype(str), country_data["n_registros"])
            plt.xlabel("Registros en conflicto")
            plt.ylabel("País")
            plt.title(f"Conflictos temáticos por país - {subset}")
            plt.tight_layout()
            plt.savefig(FIGURES_DIR / f"05c_conflictos_por_pais_{subset}.png", dpi=200)
            plt.close()

    if not priority_cases.empty:
        data = (
            priority_cases.groupby("pais_grupo", dropna=False)
            .agg(n_casos=("xy_group_id", "count"))
            .reset_index()
            .sort_values("n_casos", ascending=True)
        )

        plt.figure(figsize=(9, 6))
        plt.barh(data["pais_grupo"].astype(str), data["n_casos"])
        plt.xlabel("Casos prioritarios")
        plt.ylabel("País")
        plt.title("Casos de revisión prioritaria por país")
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "05c_casos_prioritarios_por_pais.png", dpi=200)
        plt.close()


# ============================================================
# REPORTE
# ============================================================

def generar_reporte(
    conflict_details: pd.DataFrame,
    taxonomy_summary: pd.DataFrame,
    severity_country: pd.DataFrame,
    type_country: pd.DataFrame,
    same_year_details: pd.DataFrame,
    priority_cases: pd.DataFrame,
    possible_temporal_change: pd.DataFrame,
    pair_nivel1: pd.DataFrame,
    pair_nivel2: pd.DataFrame,
    review_threshold: int,
) -> None:
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_path = REPORTS_DIR / "05c_taxonomia_conflictos_tematicos.md"

    total_groups = len(conflict_details)
    total_records = int(conflict_details["n_registros_conflicto"].sum()) if not conflict_details.empty else 0
    n_priority = len(priority_cases)
    n_same_year = int((conflict_details["flag_conflicto_mismo_anio"] == 1).sum()) if not conflict_details.empty else 0
    n_multisource_same_year = int((conflict_details["flag_conflicto_multifuente_mismo_anio"] == 1).sum()) if not conflict_details.empty else 0

    contenido = "\n".join(
        [
            "# Taxonomía y severidad de conflictos temáticos",
            "",
            "## Módulo 5C",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## Propósito",
            "",
            "Este módulo clasifica los conflictos temáticos XY detectados en el Módulo 5B por tipo, severidad y prioridad de revisión.",
            "",
            "## Resumen ejecutivo",
            "",
            "| Concepto | Valor |",
            "|---|---:|",
            f"| Grupos conflictivos evaluados | {total_groups} |",
            f"| Registros involucrados en conflictos | {total_records} |",
            f"| Grupos con conflicto en el mismo año | {n_same_year} |",
            f"| Grupos con conflicto multifuente en el mismo año | {n_multisource_same_year} |",
            f"| Casos con score de revisión >= {review_threshold} | {n_priority} |",
            "",
            "## Taxonomía general",
            "",
            dataframe_a_markdown(taxonomy_summary),
            "",
            "## Severidad por país",
            "",
            dataframe_a_markdown(severity_country),
            "",
            "## Tipo de conflicto por país",
            "",
            dataframe_a_markdown(type_country),
            "",
            "## Conflictos en el mismo año",
            "",
            dataframe_a_markdown(same_year_details.head(80)),
            "",
            "## Casos de revisión prioritaria",
            "",
            dataframe_a_markdown(priority_cases.head(100)),
            "",
            "## Posibles cambios temporales",
            "",
            dataframe_a_markdown(possible_temporal_change.head(80)),
            "",
            "## Principales pares conflictivos Nivel_1",
            "",
            dataframe_a_markdown(pair_nivel1.head(80)),
            "",
            "## Principales pares conflictivos Nivel_2",
            "",
            dataframe_a_markdown(pair_nivel2.head(80)),
            "",
            "## Interpretación metodológica",
            "",
            "No todo conflicto temático XY debe tratarse como error. Algunos conflictos pueden representar cambios reales en el tiempo, diferencias de fuente, ambigüedad temática o problemas de leyenda fina.",
            "",
            "La prioridad operativa debe concentrarse en conflictos cercanos a la línea base 2020, especialmente si ocurren dentro de la ventana 2018-2022, si involucran bosque versus no bosque, si ocurren en el mismo año o si aparecen entre múltiples fuentes.",
            "",
            "## Regla operativa recomendada",
            "",
            "```text",
            "Los conflictos de severidad alta o muy alta no deben usarse como muestras directas de entrenamiento. Deben pasar por revisión experta, jerarquía de fuente o fotointerpretación dirigida.",
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
        description="Módulo 5C: taxonomía y severidad de conflictos temáticos."
    )

    parser.add_argument(
        "--rebuild-records",
        action="store_true",
        help="Reconstruye la tabla conflict_records_05c.",
    )

    args = parser.parse_args()

    crear_carpetas_salida()
    config = cargar_yaml(CONFIG_PATH)

    temporal_cfg = config.get("temporal", {})
    tax_cfg = config.get("conflict_taxonomy", {})

    target_year = int(temporal_cfg.get("target_year", 2020))
    near_window = int(temporal_cfg.get("near_window_years", 2))
    review_threshold = int(tax_cfg.get("review_priority_threshold", 75))

    conn = abrir_conexion()

    try:
        validar_insumos(conn)

        subsets = obtener_subsets_conflictivos(conn)

        if not subsets:
            raise ValueError(
                "No se encontraron subconjuntos con conflictos temáticos en xy_subset_agg."
            )

        if args.rebuild_records or not tabla_existe(conn, "conflict_records_05c"):
            print("Construyendo conflict_records_05c...")
            construir_conflict_records(
                conn=conn,
                subsets=subsets,
                target_year=target_year,
                near_window=near_window,
            )
        else:
            print("Usando conflict_records_05c existente. Usa --rebuild-records para reconstruir.")

        records_df = pd.read_sql_query("SELECT * FROM conflict_records_05c;", conn)
        group_base = leer_group_base(conn)
        same_year_flags = leer_same_year_flags(conn)
        same_year_details = leer_same_year_details(conn)

        conflict_details = clasificar_conflictos(
            group_base=group_base,
            same_year_flags=same_year_flags,
            config=config,
        )

        taxonomy_summary = resumen_taxonomia(conflict_details)
        severity_country = resumen_severidad_pais(conflict_details)
        type_country = resumen_tipo_pais(conflict_details)

        priority_cases = casos_revision_prioritaria(
            conflict_details,
            review_threshold=review_threshold,
        )

        possible_temporal_change = posibles_cambios_temporales(conflict_details)
        same_year_cases = conflictos_mismo_anio(conflict_details)
        multisource_same_year_cases = conflictos_multifuente_mismo_anio(conflict_details)

        pair_nivel1 = construir_pares_clase(
            records_df=records_df,
            details_df=conflict_details,
            class_field="nivel_1",
            class_level="Nivel_1",
        )

        pair_nivel2 = construir_pares_clase(
            records_df=records_df,
            details_df=conflict_details,
            class_field="nivel_2",
            class_level="Nivel_2",
        )

        # Exportar tablas
        records_df.to_csv(TABLES_DIR / "05c_conflict_records.csv", index=False, encoding="utf-8-sig")
        conflict_details.to_csv(TABLES_DIR / "05c_conflict_taxonomy_details.csv", index=False, encoding="utf-8-sig")
        taxonomy_summary.to_csv(TABLES_DIR / "05c_conflict_taxonomy_summary.csv", index=False, encoding="utf-8-sig")
        severity_country.to_csv(TABLES_DIR / "05c_conflict_severity_by_country.csv", index=False, encoding="utf-8-sig")
        type_country.to_csv(TABLES_DIR / "05c_conflict_type_by_country.csv", index=False, encoding="utf-8-sig")
        same_year_details.to_csv(TABLES_DIR / "05c_conflict_same_year_details.csv", index=False, encoding="utf-8-sig")
        same_year_cases.to_csv(TABLES_DIR / "05c_conflict_same_year_cases.csv", index=False, encoding="utf-8-sig")
        multisource_same_year_cases.to_csv(TABLES_DIR / "05c_conflict_multisource_same_year_cases.csv", index=False, encoding="utf-8-sig")
        possible_temporal_change.to_csv(TABLES_DIR / "05c_conflict_possible_temporal_change.csv", index=False, encoding="utf-8-sig")
        priority_cases.to_csv(TABLES_DIR / "05c_review_priority_cases.csv", index=False, encoding="utf-8-sig")
        pair_nivel1.to_csv(TABLES_DIR / "05c_conflict_class_pair_summary_nivel1.csv", index=False, encoding="utf-8-sig")
        pair_nivel2.to_csv(TABLES_DIR / "05c_conflict_class_pair_summary_nivel2.csv", index=False, encoding="utf-8-sig")

        audit_summary = pd.DataFrame(
            [
                {
                    "target_year": target_year,
                    "near_window_years": near_window,
                    "subsets_evaluados": ";".join(subsets),
                    "n_registros_conflictivos": len(records_df),
                    "n_grupos_conflictivos": len(conflict_details),
                    "n_casos_revision_prioritaria": len(priority_cases),
                    "n_casos_conflicto_mismo_anio": len(same_year_cases),
                    "n_casos_conflicto_multifuente_mismo_anio": len(multisource_same_year_cases),
                    "review_priority_threshold": review_threshold,
                }
            ]
        )

        audit_summary.to_csv(TABLES_DIR / "05c_conflict_taxonomy_audit_summary.csv", index=False, encoding="utf-8-sig")

        generar_figuras(
            taxonomy_summary=taxonomy_summary,
            severity_country=severity_country,
            priority_cases=priority_cases,
        )

        generar_reporte(
            conflict_details=conflict_details,
            taxonomy_summary=taxonomy_summary,
            severity_country=severity_country,
            type_country=type_country,
            same_year_details=same_year_details,
            priority_cases=priority_cases,
            possible_temporal_change=possible_temporal_change,
            pair_nivel1=pair_nivel1,
            pair_nivel2=pair_nivel2,
            review_threshold=review_threshold,
        )

        registrar_log(
            "Módulo 5C ejecutado correctamente. "
            f"Subsets: {subsets}. "
            f"Grupos conflictivos: {len(conflict_details)}. "
            f"Casos prioritarios: {len(priority_cases)}."
        )

        print("Módulo 5C ejecutado correctamente.")
        print(f"Subconjuntos evaluados: {subsets}")
        print(f"Registros conflictivos evaluados: {len(records_df)}")
        print(f"Grupos conflictivos evaluados: {len(conflict_details)}")
        print(f"Casos de revisión prioritaria: {len(priority_cases)}")
        print("Salidas generadas en outputs/tables, outputs/figures y outputs/reports.")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        registrar_log("Error durante la ejecución del Módulo 5C.")
        traceback.print_exc()
        raise
