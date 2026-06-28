"""
Módulo 1 - Lectura inicial del GeoPackage.

Este script inspecciona el GeoPackage principal del proyecto sin realizar limpieza,
depuración ni modificaciones sobre los datos originales.

Esta versión usa Fiona para extraer la estructura de capas, campos, CRS y conteos,
evitando errores de ambigüedad con arreglos devueltos por pyogrio.read_info().

Salidas generadas:
- outputs/tables/01_inventario_capas.csv
- outputs/tables/01_resumen_capas.csv
- outputs/tables/01_resumen_campos.csv
- outputs/tables/01_capa_principal_sugerida.csv
- outputs/tables/01_muestra_atributos_capa_principal.csv
- outputs/reports/01_perfil_inicial_gpkg.md
"""

from pathlib import Path
from datetime import datetime
import traceback

import fiona
import geopandas as gpd
import pandas as pd
import pyogrio
import yaml


# ============================================================
# RUTAS GENERALES
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def cargar_configuracion():
    """Carga el archivo config.yaml."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"No existe el archivo de configuración: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def crear_carpetas_salida():
    """Crea carpetas de salida si no existen."""
    (PROJECT_ROOT / "outputs" / "tables").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "outputs" / "reports").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)


def registrar_log(mensaje):
    """Registra un mensaje en logs/auditoria.log."""
    log_path = PROJECT_ROOT / "logs" / "auditoria.log"
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"[{fecha}] {mensaje}\n")


def formato_tamano(bytes_size):
    """Convierte tamaño en bytes a formato legible."""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    if bytes_size < 1024**2:
        return f"{bytes_size / 1024:.2f} KB"
    if bytes_size < 1024**3:
        return f"{bytes_size / 1024**2:.2f} MB"
    return f"{bytes_size / 1024**3:.2f} GB"


def valor_seguro(valor):
    """Convierte valores potencialmente nulos o complejos a texto seguro."""
    if valor is None:
        return ""

    try:
        return str(valor)
    except Exception:
        return ""


def dataframe_a_markdown(df):
    """
    Convierte un DataFrame a tabla Markdown.

    Usa pandas.to_markdown si tabulate está disponible. Si no, usa texto simple.
    """
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


# ============================================================
# INSPECCIÓN DEL GEOPACKAGE
# ============================================================

def listar_capas(gpkg_path):
    """Lista las capas del GeoPackage usando pyogrio."""
    capas_raw = pyogrio.list_layers(gpkg_path)
    capas = pd.DataFrame(capas_raw)

    if capas.empty:
        raise ValueError("No se encontraron capas en el GeoPackage.")

    if capas.shape[1] >= 2:
        capas = capas.iloc[:, :2]
        capas.columns = ["layer_name", "geometry_type"]
    else:
        capas.columns = ["layer_name"]
        capas["geometry_type"] = ""

    capas.insert(0, "layer_id", range(1, len(capas) + 1))

    return capas


def obtener_info_capa_con_fiona(gpkg_path, layer_name):
    """
    Obtiene información de una capa usando Fiona.

    Fiona permite leer metadatos de schema, CRS, geometría y número de registros
    sin cargar todo el GeoPackage en memoria.
    """
    with fiona.open(gpkg_path, layer=layer_name) as src:
        schema = src.schema
        properties = schema.get("properties", {})
        geometry_type = schema.get("geometry", "")
        crs = src.crs
        crs_wkt = src.crs_wkt
        driver = src.driver

        try:
            features = len(src)
        except Exception:
            features = ""

        campos = []
        for field_name, field_type in properties.items():
            campos.append(
                {
                    "layer_name": layer_name,
                    "field_name": field_name,
                    "dtype": field_type,
                }
            )

        resumen = {
            "layer_name": layer_name,
            "geometry_type": valor_seguro(geometry_type),
            "features": features,
            "crs": valor_seguro(crs),
            "crs_wkt_available": bool(crs_wkt),
            "driver": valor_seguro(driver),
            "n_fields": len(campos),
            "error": "",
        }

    return resumen, campos


def resumir_capas_y_campos(gpkg_path, capas):
    """Genera resumen de capas y campos usando Fiona."""
    resumen_capas = []
    resumen_campos = []

    for _, row in capas.iterrows():
        layer_name = row["layer_name"]

        try:
            resumen, campos = obtener_info_capa_con_fiona(gpkg_path, layer_name)

            # Si pyogrio detectó geometría y Fiona no, usar valor de pyogrio como apoyo.
            if not resumen.get("geometry_type"):
                resumen["geometry_type"] = row.get("geometry_type", "")

            resumen_capas.append(resumen)
            resumen_campos.extend(campos)

        except Exception as error:
            resumen_capas.append(
                {
                    "layer_name": layer_name,
                    "geometry_type": row.get("geometry_type", ""),
                    "features": "",
                    "crs": "",
                    "crs_wkt_available": "",
                    "driver": "",
                    "n_fields": "",
                    "error": str(error),
                }
            )

    return pd.DataFrame(resumen_capas), pd.DataFrame(resumen_campos)


def sugerir_capa_principal(resumen_capas, config):
    """
    Sugiere la capa principal.

    Prioridad:
    1. Si config.yaml define una capa válida, se usa esa.
    2. Si no, se usa la capa con mayor número de registros.
    """
    capa_config = config.get("input_data", {}).get("gpkg_layer")

    if capa_config:
        if capa_config in resumen_capas["layer_name"].tolist():
            return capa_config

    resumen = resumen_capas.copy()
    resumen["features_num"] = pd.to_numeric(
        resumen["features"],
        errors="coerce"
    ).fillna(-1)

    if resumen.empty:
        raise ValueError("No se encontraron capas disponibles en el GeoPackage.")

    return resumen.sort_values("features_num", ascending=False).iloc[0]["layer_name"]


def exportar_muestra(gpkg_path, layer_name):
    """Exporta una muestra de 10 registros de la capa principal."""
    output_path = PROJECT_ROOT / "outputs" / "tables" / "01_muestra_atributos_capa_principal.csv"

    try:
        muestra = gpd.read_file(
            gpkg_path,
            layer=layer_name,
            rows=10,
            engine="pyogrio",
        )

        if isinstance(muestra, gpd.GeoDataFrame):
            geom_name = muestra.geometry.name
            muestra["geometry_wkt"] = muestra.geometry.to_wkt()
            muestra = pd.DataFrame(muestra.drop(columns=[geom_name]))

        muestra.to_csv(output_path, index=False, encoding="utf-8-sig")

    except Exception as error:
        error_df = pd.DataFrame(
            [
                {
                    "layer_name": layer_name,
                    "error": str(error),
                }
            ]
        )
        error_df.to_csv(output_path, index=False, encoding="utf-8-sig")


# ============================================================
# REPORTE
# ============================================================

def generar_reporte(gpkg_path, file_size, resumen_capas, resumen_campos, capa_principal):
    """Genera reporte Markdown de perfil inicial."""
    report_path = PROJECT_ROOT / "outputs" / "reports" / "01_perfil_inicial_gpkg.md"
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    tabla_capas = dataframe_a_markdown(resumen_capas)

    contenido = "\n".join(
        [
            "# Perfil inicial del GeoPackage",
            "",
            "## Módulo 1 - Lectura inicial",
            "",
            f"Fecha de ejecución: {fecha}",
            "",
            "## Archivo inspeccionado",
            "",
            "```text",
            str(gpkg_path),
            "```",
            "",
            "## Tamaño del archivo",
            "",
            "```text",
            str(file_size),
            "```",
            "",
            "## Resumen general",
            "",
            "| Elemento | Valor |",
            "|---|---:|",
            f"| Número de capas | {len(resumen_capas)} |",
            f"| Número total de campos registrados | {len(resumen_campos)} |",
            f"| Capa principal sugerida | {capa_principal} |",
            "",
            "## Capas identificadas",
            "",
            tabla_capas,
            "",
            "## Nota metodológica",
            "",
            "Este reporte corresponde únicamente a la lectura inicial del GeoPackage.",
            "",
            "No se realizó limpieza, eliminación de duplicados, corrección de geometrías,",
            "reclasificación temática ni auditoría profunda.",
            "",
            "La capa principal sugerida debe ser validada por el equipo técnico antes de avanzar",
            "hacia auditorías estructurales, espaciales, temporales o temáticas.",
            "",
        ]
    )

    with open(report_path, "w", encoding="utf-8") as file:
        file.write(contenido)


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def main():
    """Ejecuta el Módulo 1."""
    crear_carpetas_salida()

    config = cargar_configuracion()

    gpkg_rel = config.get("input_data", {}).get("gpkg_file")

    if not gpkg_rel:
        raise ValueError(
            "No se encontró la ruta del GeoPackage en config/config.yaml, "
            "campo input_data.gpkg_file."
        )

    gpkg_path = PROJECT_ROOT / gpkg_rel

    if not gpkg_path.exists():
        raise FileNotFoundError(
            f"\nNo se encontró el GeoPackage esperado:\n{gpkg_path}\n\n"
            "Coloca el archivo en data/raw/ o actualiza config/config.yaml.\n"
        )

    file_size = formato_tamano(gpkg_path.stat().st_size)

    capas = listar_capas(gpkg_path)
    resumen_capas, resumen_campos = resumir_capas_y_campos(gpkg_path, capas)
    capa_principal = sugerir_capa_principal(resumen_capas, config)

    tables_dir = PROJECT_ROOT / "outputs" / "tables"

    capas.to_csv(
        tables_dir / "01_inventario_capas.csv",
        index=False,
        encoding="utf-8-sig",
    )

    resumen_capas.to_csv(
        tables_dir / "01_resumen_capas.csv",
        index=False,
        encoding="utf-8-sig",
    )

    resumen_campos.to_csv(
        tables_dir / "01_resumen_campos.csv",
        index=False,
        encoding="utf-8-sig",
    )

    pd.DataFrame(
        [
            {
                "gpkg_path": str(gpkg_path),
                "file_size": file_size,
                "capa_principal_sugerida": capa_principal,
            }
        ]
    ).to_csv(
        tables_dir / "01_capa_principal_sugerida.csv",
        index=False,
        encoding="utf-8-sig",
    )

    exportar_muestra(gpkg_path, capa_principal)

    generar_reporte(
        gpkg_path=gpkg_path,
        file_size=file_size,
        resumen_capas=resumen_capas,
        resumen_campos=resumen_campos,
        capa_principal=capa_principal,
    )

    registrar_log(
        f"Módulo 1 ejecutado correctamente. GeoPackage: {gpkg_path}. "
        f"Capa principal sugerida: {capa_principal}."
    )

    print("Módulo 1 ejecutado correctamente.")
    print(f"GeoPackage: {gpkg_path}")
    print(f"Tamaño: {file_size}")
    print(f"Capa principal sugerida: {capa_principal}")
    print("Salidas generadas en outputs/tables y outputs/reports.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        registrar_log("Error durante la ejecución del Módulo 1.")
        traceback.print_exc()
        raise