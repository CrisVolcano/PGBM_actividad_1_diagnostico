"""
Módulo 2 - Auditoría estructural y tabular del GeoPackage.

Este script realiza una auditoría estructural de la capa principal del GeoPackage
sin modificar los datos originales.

Objetivos:
- Revisar esquema de campos.
- Identificar campos críticos presentes y ausentes.
- Calcular valores nulos y vacíos por campo.
- Calcular número de valores únicos por campo.
- Extraer dominios de campos categóricos.
- Revisar duplicados en identificadores.
- Estimar duplicados exactos de atributos mediante hash por bloques.
- Generar reporte Markdown de auditoría estructural.

Salidas:
- outputs/tables/02_schema_sqlite.csv
- outputs/tables/02_campos_criticos_estado.csv
- outputs/tables/02_nulos_por_campo.csv
- outputs/tables/02_unicos_por_campo.csv
- outputs/tables/02_dominios_valores_bajos.csv
- outputs/tables/02_duplicados_identificadores_resumen.csv
- outputs/tables/02_duplicados_identificadores_detalle.csv
- outputs/tables/02_duplicados_atributos_hash.csv
- outputs/tables/02_resumen_estructural.csv
- outputs/reports/02_auditoria_estructural.md
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import sqlite3
import traceback

import pandas as pd
import yaml
from pandas.util import hash_pandas_object
from tqdm import tqdm


# ============================================================
# RUTAS GENERALES
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
CAMPOS_ESPERADOS_PATH = PROJECT_ROOT / "config" / "campos_esperados.yaml"

TABLES_DIR = PROJECT_ROOT / "outputs" / "tables"
REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"
LOGS_DIR = PROJECT_ROOT / "logs"


# ============================================================
# FUNCIONES GENERALES
# ============================================================

def crear_carpetas_salida() -> None:
    """Crea carpetas de salida si no existen."""
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
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
        return yaml.safe_load(file)


def quote_ident(identifier: str) -> str:
    """
    Protege nombres de campos o tablas para consultas SQL.

    SQLite permite comillas dobles para identificadores.
    """
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

    conn = sqlite3.connect(gpkg_path)
    return conn


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
    """Verifica que la tabla/capa exista en el GeoPackage."""
    tablas = obtener_tablas_sqlite(conn)

    if table_name not in tablas:
        raise ValueError(
            f"La tabla/capa '{table_name}' no existe en el GeoPackage.\n"
            f"Tablas disponibles: {tablas}"
        )


# ============================================================
# ESQUEMA Y CAMPOS
# ============================================================

def obtener_schema_sqlite(conn: sqlite3.Connection, table_name: str) -> pd.DataFrame:
    """Obtiene esquema de la tabla mediante PRAGMA table_info."""
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


def obtener_columnas_geometria(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """Identifica columnas de geometría declaradas en gpkg_geometry_columns."""
    try:
        sql = """
        SELECT column_name
        FROM gpkg_geometry_columns
        WHERE table_name = ?;
        """
        df = pd.read_sql_query(sql, conn, params=[table_name])
        return df["column_name"].tolist()
    except Exception:
        return []


def obtener_total_registros(conn: sqlite3.Connection, table_name: str) -> int:
    """Cuenta registros de la tabla principal."""
    sql = f"SELECT COUNT(*) AS n FROM {quote_ident(table_name)};"
    return int(pd.read_sql_query(sql, conn)["n"].iloc[0])


def evaluar_campos_criticos(
    schema: pd.DataFrame,
    campos_esperados_config: dict,
) -> pd.DataFrame:
    """Evalúa presencia de campos críticos mínimos."""
    campos_existentes = set(schema["field_name"].tolist())
    campos_criticos = campos_esperados_config.get("campos_criticos_minimos", [])

    rows = []

    for campo in campos_criticos:
        rows.append(
            {
                "campo": campo,
                "presente": campo in campos_existentes,
                "estado": "presente" if campo in campos_existentes else "ausente",
            }
        )

    return pd.DataFrame(rows)


# ============================================================
# NULOS, VACÍOS Y ÚNICOS
# ============================================================

def calcular_nulos_por_campo(
    conn: sqlite3.Connection,
    table_name: str,
    campos_atributivos: list[str],
    total_registros: int,
) -> pd.DataFrame:
    """Calcula valores nulos y vacíos por campo."""
    rows = []

    for campo in tqdm(campos_atributivos, desc="Calculando nulos/vacíos por campo"):
        campo_sql = quote_ident(campo)

        sql = f"""
        SELECT
            SUM(CASE WHEN {campo_sql} IS NULL THEN 1 ELSE 0 END) AS n_nulos,
            SUM(
                CASE
                    WHEN {campo_sql} IS NOT NULL
                    AND TRIM(CAST({campo_sql} AS TEXT)) = ''
                    THEN 1
                    ELSE 0
                END
            ) AS n_vacios
        FROM {quote_ident(table_name)};
        """

        result = pd.read_sql_query(sql, conn).iloc[0]

        n_nulos = int(result["n_nulos"] or 0)
        n_vacios = int(result["n_vacios"] or 0)

        rows.append(
            {
                "field_name": campo,
                "n_total": total_registros,
                "n_nulos": n_nulos,
                "pct_nulos": round((n_nulos / total_registros) * 100, 4),
                "n_vacios_texto": n_vacios,
                "pct_vacios_texto": round((n_vacios / total_registros) * 100, 4),
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["pct_nulos", "pct_vacios_texto"],
        ascending=False,
    )


def calcular_unicos_por_campo(
    conn: sqlite3.Connection,
    table_name: str,
    campos_atributivos: list[str],
    total_registros: int,
) -> pd.DataFrame:
    """Calcula cantidad de valores únicos por campo."""
    rows = []

    for campo in tqdm(campos_atributivos, desc="Calculando valores únicos por campo"):
        campo_sql = quote_ident(campo)

        sql = f"""
        SELECT COUNT(DISTINCT {campo_sql}) AS n_unicos
        FROM {quote_ident(table_name)};
        """

        n_unicos = int(pd.read_sql_query(sql, conn)["n_unicos"].iloc[0] or 0)

        rows.append(
            {
                "field_name": campo,
                "n_total": total_registros,
                "n_unicos_no_nulos": n_unicos,
                "pct_unicos_sobre_total": round((n_unicos / total_registros) * 100, 4),
            }
        )

    return pd.DataFrame(rows).sort_values(
        "n_unicos_no_nulos",
        ascending=False,
    )


def extraer_dominios_bajos(
    conn: sqlite3.Connection,
    table_name: str,
    unicos_df: pd.DataFrame,
    max_dominios: int = 80,
) -> pd.DataFrame:
    """
    Extrae frecuencias de campos con pocos valores únicos.

    Esto es útil para campos categóricos como país, fuente, clase, tipo, año, etc.
    """
    campos_categoricos = unicos_df.loc[
        (unicos_df["n_unicos_no_nulos"] > 0)
        & (unicos_df["n_unicos_no_nulos"] <= max_dominios),
        "field_name",
    ].tolist()

    rows = []

    for campo in tqdm(campos_categoricos, desc="Extrayendo dominios de campos categóricos"):
        campo_sql = quote_ident(campo)

        sql = f"""
        SELECT
            CAST({campo_sql} AS TEXT) AS valor,
            COUNT(*) AS n
        FROM {quote_ident(table_name)}
        GROUP BY {campo_sql}
        ORDER BY n DESC;
        """

        df = pd.read_sql_query(sql, conn)

        for _, row in df.iterrows():
            rows.append(
                {
                    "field_name": campo,
                    "valor": row["valor"],
                    "n": int(row["n"]),
                }
            )

    return pd.DataFrame(rows)


# ============================================================
# DUPLICADOS
# ============================================================

def evaluar_duplicados_identificadores(
    conn: sqlite3.Connection,
    table_name: str,
    campos_candidatos: list[str],
    schema: pd.DataFrame,
    max_detalle: int = 10000,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evalúa duplicados en campos identificadores."""
    campos_existentes = set(schema["field_name"].tolist())

    resumen_rows = []
    detalle_rows = []

    for campo in campos_candidatos:
        if campo not in campos_existentes:
            resumen_rows.append(
                {
                    "field_name": campo,
                    "presente": False,
                    "grupos_duplicados": None,
                    "registros_en_grupos_duplicados": None,
                    "exceso_registros_duplicados": None,
                }
            )
            continue

        campo_sql = quote_ident(campo)

        resumen_sql = f"""
        SELECT
            COUNT(*) AS grupos_duplicados,
            SUM(n) AS registros_en_grupos_duplicados,
            SUM(n) - COUNT(*) AS exceso_registros_duplicados
        FROM (
            SELECT {campo_sql}, COUNT(*) AS n
            FROM {quote_ident(table_name)}
            WHERE {campo_sql} IS NOT NULL
            GROUP BY {campo_sql}
            HAVING COUNT(*) > 1
        );
        """

        resumen = pd.read_sql_query(resumen_sql, conn).iloc[0]

        resumen_rows.append(
            {
                "field_name": campo,
                "presente": True,
                "grupos_duplicados": int(resumen["grupos_duplicados"] or 0),
                "registros_en_grupos_duplicados": int(resumen["registros_en_grupos_duplicados"] or 0),
                "exceso_registros_duplicados": int(resumen["exceso_registros_duplicados"] or 0),
            }
        )

        detalle_sql = f"""
        SELECT
            CAST({campo_sql} AS TEXT) AS valor,
            COUNT(*) AS n
        FROM {quote_ident(table_name)}
        WHERE {campo_sql} IS NOT NULL
        GROUP BY {campo_sql}
        HAVING COUNT(*) > 1
        ORDER BY n DESC
        LIMIT {int(max_detalle)};
        """

        detalle = pd.read_sql_query(detalle_sql, conn)
        detalle["field_name"] = campo

        detalle_rows.append(detalle[["field_name", "valor", "n"]])

    resumen_df = pd.DataFrame(resumen_rows)

    if detalle_rows:
        detalle_df = pd.concat(detalle_rows, ignore_index=True)
    else:
        detalle_df = pd.DataFrame(columns=["field_name", "valor", "n"])

    return resumen_df, detalle_df


def estimar_duplicados_atributos_hash(
    conn: sqlite3.Connection,
    table_name: str,
    campos_atributivos: list[str],
    campos_excluir_hash: list[str],
    chunksize: int = 200000,
) -> pd.DataFrame:
    """
    Estima duplicados exactos de atributos mediante hash por bloques.

    No incluye geometría. Por defecto excluye identificadores técnicos como Id
    para detectar registros con contenido equivalente aunque tengan Id distinto.

    Esta revisión no elimina registros; solo genera alertas estructurales.
    """
    campos_hash = [c for c in campos_atributivos if c not in set(campos_excluir_hash)]

    if not campos_hash:
        return pd.DataFrame(
            columns=["row_hash", "n", "tipo_revision"]
        )

    select_cols = ", ".join(quote_ident(c) for c in campos_hash)
    sql = f"SELECT {select_cols} FROM {quote_ident(table_name)};"

    contador_hashes = Counter()

    for chunk in tqdm(
        pd.read_sql_query(sql, conn, chunksize=chunksize),
        desc="Calculando hash de duplicados por bloques",
    ):
        # Convertir a string reduce problemas por tipos mixtos, None, NaN o enteros.
        chunk = chunk.astype("string").fillna("<NA>")

        hashes = hash_pandas_object(chunk, index=False).astype("uint64")
        contador_hashes.update(hashes.tolist())

    duplicados = [
        {
            "row_hash": str(row_hash),
            "n": count,
            "tipo_revision": "hash_atributos_sin_geometria",
        }
        for row_hash, count in contador_hashes.items()
        if count > 1
    ]

    df = pd.DataFrame(duplicados)

    if df.empty:
        return pd.DataFrame(columns=["row_hash", "n", "tipo_revision"])

    return df.sort_values("n", ascending=False)


# ============================================================
# REPORTE
# ============================================================

def generar_reporte(
    gpkg_path: Path,
    table_name: str,
    total_registros: int,
    schema_df: pd.DataFrame,
    campos_criticos_df: pd.DataFrame,
    nulos_df: pd.DataFrame,
    unicos_df: pd.DataFrame,
    duplicados_id_resumen_df: pd.DataFrame,
    duplicados_hash_df: pd.DataFrame,
) -> None:
    """Genera reporte Markdown de auditoría estructural."""
    report_path = REPORTS_DIR / "02_auditoria_estructural.md"
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    campos_ausentes = campos_criticos_df.loc[
        campos_criticos_df["presente"] == False, "campo"  # noqa: E712
    ].tolist()

    top_nulos = nulos_df.head(15)
    top_unicos = unicos_df.head(15)

    n_hash_groups = len(duplicados_hash_df)
    n_hash_records = int(duplicados_hash_df["n"].sum()) if not duplicados_hash_df.empty else 0

    contenido = "\n".join(
        [
            "# Auditoría estructural y tabular",
            "",
            "## Módulo 2",
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
            f"| Total de registros | {total_registros} |",
            f"| Total de campos en SQLite | {len(schema_df)} |",
            f"| Campos críticos ausentes | {len(campos_ausentes)} |",
            f"| Grupos de duplicados por hash de atributos | {n_hash_groups} |",
            f"| Registros en grupos duplicados por hash | {n_hash_records} |",
            "",
            "## Campos críticos ausentes",
            "",
            ", ".join(campos_ausentes) if campos_ausentes else "No se detectaron campos críticos ausentes.",
            "",
            "## Esquema SQLite",
            "",
            dataframe_a_markdown(schema_df),
            "",
            "## Estado de campos críticos",
            "",
            dataframe_a_markdown(campos_criticos_df),
            "",
            "## Campos con mayor porcentaje de nulos",
            "",
            dataframe_a_markdown(top_nulos),
            "",
            "## Campos con mayor número de valores únicos",
            "",
            dataframe_a_markdown(top_unicos),
            "",
            "## Resumen de duplicados en identificadores",
            "",
            dataframe_a_markdown(duplicados_id_resumen_df),
            "",
            "## Nota metodológica",
            "",
            "Esta auditoría estructural no modifica el GeoPackage original.",
            "Los resultados deben interpretarse como diagnóstico inicial para orientar decisiones posteriores.",
            "Los duplicados por hash no constituyen eliminación automática; solo indican registros que requieren revisión.",
            "",
        ]
    )

    with open(report_path, "w", encoding="utf-8") as file:
        file.write(contenido)


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def main() -> None:
    """Ejecuta auditoría estructural y tabular."""
    crear_carpetas_salida()

    config = cargar_yaml(CONFIG_PATH)
    campos_esperados_config = cargar_yaml(CAMPOS_ESPERADOS_PATH)

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

    conn = abrir_conexion(gpkg_path)

    try:
        validar_tabla(conn, table_name)

        total_registros = obtener_total_registros(conn, table_name)

        schema_df = obtener_schema_sqlite(conn, table_name)
        geometry_columns = obtener_columnas_geometria(conn, table_name)

        schema_df["is_geometry_column"] = schema_df["field_name"].isin(geometry_columns)

        campos_atributivos = schema_df.loc[
            ~schema_df["is_geometry_column"],
            "field_name",
        ].tolist()

        campos_criticos_df = evaluar_campos_criticos(
            schema=schema_df,
            campos_esperados_config=campos_esperados_config,
        )

        nulos_df = calcular_nulos_por_campo(
            conn=conn,
            table_name=table_name,
            campos_atributivos=campos_atributivos,
            total_registros=total_registros,
        )

        unicos_df = calcular_unicos_por_campo(
            conn=conn,
            table_name=table_name,
            campos_atributivos=campos_atributivos,
            total_registros=total_registros,
        )

        dominios_df = extraer_dominios_bajos(
            conn=conn,
            table_name=table_name,
            unicos_df=unicos_df,
            max_dominios=80,
        )

        campos_id_candidatos = [
            config.get("fields", {}).get("id_primary", "Id"),
            config.get("fields", {}).get("id_origin", "Id_Origen"),
        ]

        duplicados_id_resumen_df, duplicados_id_detalle_df = evaluar_duplicados_identificadores(
            conn=conn,
            table_name=table_name,
            campos_candidatos=campos_id_candidatos,
            schema=schema_df,
        )

        campos_excluir_hash = [
            "fid",
            "FID",
            "OBJECTID",
            config.get("fields", {}).get("id_primary", "Id"),
        ] + geometry_columns

        duplicados_hash_df = estimar_duplicados_atributos_hash(
            conn=conn,
            table_name=table_name,
            campos_atributivos=campos_atributivos,
            campos_excluir_hash=campos_excluir_hash,
            chunksize=200000,
        )

        resumen_estructural_df = pd.DataFrame(
            [
                {
                    "gpkg_path": str(gpkg_path),
                    "table_name": table_name,
                    "total_registros": total_registros,
                    "total_campos_sqlite": len(schema_df),
                    "total_campos_atributivos": len(campos_atributivos),
                    "total_columnas_geometria": len(geometry_columns),
                    "campos_criticos_ausentes": int(
                        (campos_criticos_df["presente"] == False).sum()  # noqa: E712
                    ),
                    "grupos_duplicados_hash_atributos": len(duplicados_hash_df),
                    "registros_en_grupos_duplicados_hash": int(
                        duplicados_hash_df["n"].sum()
                    )
                    if not duplicados_hash_df.empty
                    else 0,
                }
            ]
        )

        # Exportar tablas
        schema_df.to_csv(
            TABLES_DIR / "02_schema_sqlite.csv",
            index=False,
            encoding="utf-8-sig",
        )

        campos_criticos_df.to_csv(
            TABLES_DIR / "02_campos_criticos_estado.csv",
            index=False,
            encoding="utf-8-sig",
        )

        nulos_df.to_csv(
            TABLES_DIR / "02_nulos_por_campo.csv",
            index=False,
            encoding="utf-8-sig",
        )

        unicos_df.to_csv(
            TABLES_DIR / "02_unicos_por_campo.csv",
            index=False,
            encoding="utf-8-sig",
        )

        dominios_df.to_csv(
            TABLES_DIR / "02_dominios_valores_bajos.csv",
            index=False,
            encoding="utf-8-sig",
        )

        duplicados_id_resumen_df.to_csv(
            TABLES_DIR / "02_duplicados_identificadores_resumen.csv",
            index=False,
            encoding="utf-8-sig",
        )

        duplicados_id_detalle_df.to_csv(
            TABLES_DIR / "02_duplicados_identificadores_detalle.csv",
            index=False,
            encoding="utf-8-sig",
        )

        duplicados_hash_df.to_csv(
            TABLES_DIR / "02_duplicados_atributos_hash.csv",
            index=False,
            encoding="utf-8-sig",
        )

        resumen_estructural_df.to_csv(
            TABLES_DIR / "02_resumen_estructural.csv",
            index=False,
            encoding="utf-8-sig",
        )

        generar_reporte(
            gpkg_path=gpkg_path,
            table_name=table_name,
            total_registros=total_registros,
            schema_df=schema_df,
            campos_criticos_df=campos_criticos_df,
            nulos_df=nulos_df,
            unicos_df=unicos_df,
            duplicados_id_resumen_df=duplicados_id_resumen_df,
            duplicados_hash_df=duplicados_hash_df,
        )

        registrar_log(
            f"Módulo 2 ejecutado correctamente. Tabla: {table_name}. "
            f"Registros: {total_registros}. Campos atributivos: {len(campos_atributivos)}."
        )

        print("Módulo 2 ejecutado correctamente.")
        print(f"GeoPackage: {gpkg_path}")
        print(f"Capa auditada: {table_name}")
        print(f"Registros: {total_registros}")
        print(f"Campos SQLite: {len(schema_df)}")
        print(f"Campos atributivos: {len(campos_atributivos)}")
        print("Salidas generadas en outputs/tables y outputs/reports.")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        registrar_log("Error durante la ejecución del Módulo 2.")
        traceback.print_exc()
        raise