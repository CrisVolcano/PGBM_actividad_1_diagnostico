from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import csv
import hashlib
import re
from collections import Counter
from typing import Any


# =============================================================================
# PGBM - Report generator for Google Earth Engine Sentinel-2 SR export script
# =============================================================================
#
# Purpose:
#   Read the GEE JavaScript extraction script and generate a Markdown report
#   documenting what was done in the spectral export.
#
# Expected inputs:
#   scripts/gee/06_s2_sr_monthly_s2cloudless_export.js
#   data/raw/PGBM_S2SR_monthly_s2cloudless/*.csv
#
# Expected output:
#   outputs/reports/gee_extraction/06_s2_sr_monthly_s2cloudless_export_report.md
#
# Run from project root:
#   python src/07_generate_gee_export_report.py
# =============================================================================


DEFAULT_JS_RELATIVE_PATH = Path("scripts/gee/06_s2_sr_monthly_s2cloudless_export.js")
DEFAULT_RAW_EXPORT_DIR = Path("data/raw/PGBM_S2SR_monthly_s2cloudless")
DEFAULT_REPORT_RELATIVE_PATH = Path(
    "outputs/reports/gee_extraction/06_s2_sr_monthly_s2cloudless_export_report.md"
)


def find_project_root() -> Path:
    """
    Find project root by searching upward from this script location and cwd.
    """
    starts = [Path(__file__).resolve().parent, Path.cwd().resolve()]
    visited: set[Path] = set()

    for start in starts:
        for candidate in [start, *start.parents]:
            if candidate in visited:
                continue

            visited.add(candidate)

            if (candidate / ".git").exists():
                return candidate

            if (candidate / "config" / "config.yaml").exists():
                return candidate

    raise FileNotFoundError(
        "No se pudo localizar la raíz del proyecto. "
        "Ejecute este script desde el repositorio o guárdelo dentro de src/."
    )


PROJECT_ROOT = find_project_root()


def resolve_project_path(path_value: str | Path) -> Path:
    """
    Resolve a relative path from PROJECT_ROOT. Absolute paths are preserved.
    """
    path = Path(path_value)

    if path.is_absolute():
        return path

    return PROJECT_ROOT / path


def rel(path: Path) -> str:
    """
    Return path relative to project root when possible.
    """
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def read_text(path: Path) -> str:
    """
    Read UTF-8 text.
    """
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo requerido: {path}")

    return path.read_text(encoding="utf-8")


def sha256_text(text: str) -> str:
    """
    Calculate SHA256 hash of text.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_string_var(text: str, var_name: str, default: str = "No identificado") -> str:
    """
    Extract JavaScript string variable:
      var NAME = 'value';
      var NAME = "value";
    """
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*['\"]([^'\"]+)['\"]\s*;"
    match = re.search(pattern, text)
    return match.group(1) if match else default


def extract_number_var(text: str, var_name: str, default: str = "No identificado") -> str:
    """
    Extract JavaScript numeric variable:
      var NAME = 20;
      var NAME = 0.15;
    """
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*;"
    match = re.search(pattern, text)
    return match.group(1) if match else default


def extract_boolean_var(text: str, var_name: str, default: str = "No identificado") -> str:
    """
    Extract JavaScript boolean variable:
      var NAME = false;
    """
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*(true|false)\s*;"
    match = re.search(pattern, text)
    return match.group(1) if match else default


def extract_array(text: str, var_name: str) -> list[str]:
    """
    Extract simple JavaScript array with quoted string values.

    Example:
      var spectralBands = [
        'B2', 'B3'
      ];
    """
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*\[(.*?)\]\s*;"
    match = re.search(pattern, text, flags=re.DOTALL)

    if not match:
        return []

    body = match.group(1)
    return re.findall(r"['\"]([^'\"]+)['\"]", body)


def extract_collection_ids(text: str) -> list[str]:
    """
    Extract ee.ImageCollection IDs.
    """
    values = re.findall(r"ee\.ImageCollection\(['\"]([^'\"]+)['\"]\)", text)
    return sorted(set(values))


def extract_function_names(text: str) -> list[str]:
    """
    Extract function names.
    """
    return re.findall(r"function\s+([A-Za-z0-9_]+)\s*\(", text)


def extract_batch_entries(text: str) -> list[dict[str, str]]:
    """
    Extract batch names and run flags from BATCHES_TO_EXPORT.

    This is intentionally simple and robust enough for the current GEE script.
    """
    entries: list[dict[str, str]] = []

    batch_section_match = re.search(
        r"var\s+BATCHES_TO_EXPORT\s*=\s*\[(.*?)\]\s*;",
        text,
        flags=re.DOTALL,
    )

    if not batch_section_match:
        return entries

    batch_section = batch_section_match.group(1)

    object_blocks = re.findall(r"\{(.*?)\}", batch_section, flags=re.DOTALL)

    for block in object_blocks:
        name_match = re.search(r"name\s*:\s*['\"]([^'\"]+)['\"]", block)
        run_match = re.search(r"run\s*:\s*(true|false)", block)

        if not name_match:
            continue

        entries.append(
            {
                "name": name_match.group(1),
                "run": run_match.group(1) if run_match else "No identificado",
            }
        )

    return entries


def extract_scl_exclusions(text: str) -> list[tuple[str, str]]:
    """
    Extract SCL excluded classes from lines such as:
      .and(scl.neq(8))          // cloud medium probability
    """
    rows: list[tuple[str, str]] = []

    for line in text.splitlines():
        clean_line = line.strip()
        match = re.search(r"scl\.neq\((\d+)\).*?(?://\s*(.*))?$", clean_line)

        if not match:
            continue

        code = match.group(1)
        label = match.group(2).strip() if match.group(2) else "Sin descripción"
        rows.append((code, label))

    seen: set[str] = set()
    unique_rows: list[tuple[str, str]] = []

    for code, label in rows:
        if code in seen:
            continue

        seen.add(code)
        unique_rows.append((code, label))

    return unique_rows


def extract_file_format(text: str) -> str:
    """
    Extract fileFormat from Export.table.toDrive block.
    """
    match = re.search(r"fileFormat\s*:\s*['\"]([^'\"]+)['\"]", text)
    return match.group(1) if match else "No identificado"


def extract_tile_scale(text: str) -> str:
    """
    Extract tileScale from sampleRegions block.
    """
    match = re.search(r"tileScale\s*:\s*([0-9]+(?:\.[0-9]+)?)", text)
    return match.group(1) if match else "No identificado"


def extract_output_prefix_expression(text: str) -> str:
    """
    Extract the outputName assignment expression when possible.
    """
    match = re.search(r"var\s+outputName\s*=\s*(.*?);", text)

    if not match:
        return "No identificado"

    return match.group(1).strip()


def format_bytes(size_bytes: int) -> str:
    """
    Human-readable file size.
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"

    value = float(size_bytes)

    for unit in ["KB", "MB", "GB", "TB"]:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:,.2f} {unit}"

    return f"{value:,.2f} PB"


def read_csv_header(path: Path) -> list[str]:
    """
    Read only the CSV header. Avoid loading large GEE exports into memory.
    """
    encodings = ["utf-8-sig", "utf-8", "latin-1"]

    for encoding in encodings:
        try:
            with open(path, "r", encoding=encoding, newline="") as file:
                reader = csv.reader(file)
                return next(reader, [])
        except UnicodeDecodeError:
            continue
        except StopIteration:
            return []
        except Exception:
            return []

    return []


def inventory_raw_exports(raw_dir: Path) -> dict[str, Any]:
    """
    Inventory exported CSV files without loading full content.
    """
    csv_files = sorted(raw_dir.glob("*.csv")) if raw_dir.exists() else []

    total_size = sum(path.stat().st_size for path in csv_files)
    header_counter: Counter[tuple[str, ...]] = Counter()

    file_rows: list[list[str]] = []

    for path in csv_files:
        header = read_csv_header(path)
        header_counter[tuple(header)] += 1

        file_rows.append(
            [
                f"`{path.name}`",
                format_bytes(path.stat().st_size),
                str(len(header)),
            ]
        )

    most_common_header: list[str] = []

    if header_counter:
        most_common_header = list(header_counter.most_common(1)[0][0])

    return {
        "exists": raw_dir.exists(),
        "n_csv": len(csv_files),
        "total_size": total_size,
        "n_header_signatures": len(header_counter),
        "most_common_header": most_common_header,
        "file_rows": file_rows,
    }


def md_bullets(values: list[str], empty: str = "No identificado") -> list[str]:
    """
    Markdown bullet list as list of lines.
    """
    if not values:
        return [f"- {empty}"]

    return [f"- `{value}`" for value in values]


def md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """
    Markdown table as list of lines.
    """
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    for row in rows:
        output.append("| " + " | ".join(row) + " |")

    return output


def add_code_block(lines: list[str], content: str) -> None:
    """
    Add code-like content as indented block.

    This avoids nested triple-backtick issues when copying this script through bash.
    """
    lines.append("")
    for line in content.splitlines():
        lines.append(f"    {line}")
    lines.append("")


def generate_report(
    js_path: Path,
    raw_export_dir: Path,
    report_path: Path,
) -> str:
    """
    Generate Markdown report content.
    """
    js_text = read_text(js_path)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    script_hash = sha256_text(js_text)
    line_count = len(js_text.splitlines())

    drive_folder = extract_string_var(js_text, "DRIVE_FOLDER")
    scale = extract_number_var(js_text, "scale")
    cloud_threshold = extract_number_var(js_text, "CLD_PRB_THRESH")
    nir_dark_threshold = extract_number_var(js_text, "NIR_DRK_THRESH")
    cloud_proj_dist = extract_number_var(js_text, "CLD_PRJ_DIST")
    buffer_m = extract_number_var(js_text, "BUFFER")
    export_geometries = extract_boolean_var(js_text, "EXPORT_GEOMETRIES")
    file_format = extract_file_format(js_text)
    tile_scale = extract_tile_scale(js_text)
    output_prefix_expression = extract_output_prefix_expression(js_text)

    collections = extract_collection_ids(js_text)
    spectral_bands = extract_array(js_text, "spectralBands")
    point_properties = extract_array(js_text, "pointProperties")
    metadata_properties = extract_array(js_text, "metadataProperties")
    batch_entries = extract_batch_entries(js_text)
    function_names = extract_function_names(js_text)
    scl_rows = extract_scl_exclusions(js_text)

    raw_inventory = inventory_raw_exports(raw_export_dir)

    lines: list[str] = []

    lines.append("# Reporte metodológico de la exportación espectral Sentinel-2 SR en Google Earth Engine")
    lines.append("")
    lines.append("## 1. Identificación")
    lines.append("")
    lines.append(
        "Este reporte documenta el procedimiento utilizado para extraer variables "
        "espectro-temporales mensuales de Sentinel-2 Surface Reflectance en Google Earth Engine."
    )
    lines.append("")
    lines.append(
        "El reporte fue generado automáticamente a partir del script JavaScript conservado "
        "en el repositorio, con el objetivo de dejar trazabilidad metodológica de la "
        "exportación ya ejecutada."
    )
    lines.append("")
    lines.extend(
        md_table(
            ["Elemento", "Valor"],
            [
                ["Fecha de generación", generated_at],
                ["Script GEE documentado", f"`{rel(js_path)}`"],
                ["Reporte generado", f"`{rel(report_path)}`"],
                ["Hash SHA256 del script", f"`{script_hash}`"],
                ["Número de líneas del script", f"{line_count:,}"],
            ],
        )
    )

    lines.append("")
    lines.append("## 2. Ubicación de datos y código")
    lines.append("")
    lines.append("El código de Google Earth Engine se conserva en:")
    add_code_block(lines, rel(js_path))

    lines.append("Los CSV exportados desde Google Earth Engine se almacenan como datos crudos derivados en:")
    add_code_block(lines, rel(raw_export_dir))

    lines.append("El reporte metodológico queda guardado en:")
    add_code_block(lines, rel(report_path))

    lines.append("## 3. Propósito de la exportación")
    lines.append("")
    lines.append(
        "La exportación tuvo como objetivo obtener información espectro-temporal mensual "
        "para unidades de extracción previamente preparadas en el repositorio."
    )
    lines.append("")
    lines.append("Cada unidad de extracción representa una combinación única de:")
    add_code_block(lines, "Longitud + Latitud + Año de referencia")
    lines.append(
        "La extracción genera, para cada punto y mes, valores de reflectancia, índices "
        "espectrales, conteo de observaciones limpias y metadatos del procedimiento de "
        "enmascaramiento."
    )

    lines.append("")
    lines.append("## 4. Colecciones de Google Earth Engine utilizadas")
    lines.append("")
    lines.extend(md_bullets(collections))
    lines.append("")
    lines.append(
        "La colección `COPERNICUS/S2_SR_HARMONIZED` se utilizó como fuente de reflectancia "
        "de superficie Sentinel-2. La colección `COPERNICUS/S2_CLOUD_PROBABILITY` se utilizó "
        "como insumo para la máscara s2cloudless."
    )

    lines.append("")
    lines.append("## 5. Parámetros principales")
    lines.append("")
    lines.extend(
        md_table(
            ["Parámetro", "Valor"],
            [
                ["`DRIVE_FOLDER`", drive_folder],
                ["`scale`", scale],
                ["`CLD_PRB_THRESH`", cloud_threshold],
                ["`NIR_DRK_THRESH`", nir_dark_threshold],
                ["`CLD_PRJ_DIST`", cloud_proj_dist],
                ["`BUFFER`", buffer_m],
                ["`EXPORT_GEOMETRIES`", export_geometries],
                ["`tileScale`", tile_scale],
                ["`fileFormat`", file_format],
                ["`outputName`", f"`{output_prefix_expression}`"],
            ],
        )
    )

    lines.append("")
    lines.append("## 6. Batches definidos en el script")
    lines.append("")
    lines.append(
        "El script usa el arreglo `BATCHES_TO_EXPORT` para definir manualmente las tablas "
        "importadas en GEE y activar o desactivar su exportación."
    )
    lines.append("")

    batch_rows = [[f"`{entry['name']}`", entry["run"]] for entry in batch_entries]

    if not batch_rows:
        batch_rows = [["No identificado", "No identificado"]]

    lines.extend(md_table(["Batch", "run"], batch_rows))
    lines.append("")
    lines.append(
        "Cada batch debe corresponder a un conjunto de unidades de extracción asociado a "
        "un único año de referencia. El año se obtiene desde el campo `year_ref` del "
        "primer registro de la tabla."
    )

    lines.append("")
    lines.append("## 7. Funciones principales del script")
    lines.append("")
    lines.extend(md_bullets(function_names))
    lines.append("")
    lines.append(
        "Estas funciones cubren la preparación de puntos, cálculo de máscara de nubes y "
        "sombras, escalado de bandas, cálculo de índices, construcción de composiciones "
        "mensuales y creación de tareas de exportación."
    )

    lines.append("")
    lines.append("## 8. Preparación de puntos")
    lines.append("")
    lines.append(
        "El script espera que los puntos estén importados en Google Earth Engine como tabla "
        "o `FeatureCollection`."
    )
    lines.append("")
    lines.append("Durante la preparación de puntos:")
    lines.append("")
    lines.append("1. Se leen las coordenadas desde la geometría de cada feature.")
    lines.append("2. Se generan los campos `lon_out` y `lat_out`.")
    lines.append("3. Se conserva el identificador `extract_id`.")
    lines.append(
        "4. Se mantienen campos de trazabilidad como país, fuente, niveles temáticos, "
        "grupo XY y batch."
    )

    lines.append("")
    lines.append("## 9. Periodo temporal")
    lines.append("")
    lines.append("El año de extracción se toma desde el campo:")
    add_code_block(lines, "year_ref")
    lines.append("Para cada batch se construye un periodo anual completo:")
    add_code_block(lines, "1 de enero del year_ref hasta 1 de enero del año siguiente")
    lines.append("Posteriormente se generan composiciones mensuales para los meses 1 a 12.")

    lines.append("")
    lines.append("## 10. Máscara de nubes y sombras")
    lines.append("")
    lines.append("El script aplica una máscara combinada basada en:")
    lines.append("")
    lines.append("- Probabilidad de nube de s2cloudless.")
    lines.append("- Píxeles oscuros en la banda NIR.")
    lines.append("- Proyección de sombra a partir del ángulo solar.")
    lines.append("- Exclusión de clases SCL problemáticas.")
    lines.append("")
    lines.append("Las clases SCL excluidas en el script son:")
    lines.append("")

    scl_table_rows = [[code, label] for code, label in scl_rows]

    if not scl_table_rows:
        scl_table_rows = [["No identificado", "No identificado"]]

    lines.extend(md_table(["Clase SCL", "Descripción en el script"], scl_table_rows))
    lines.append("")
    lines.append(
        "La máscara final combina la exclusión SCL con la máscara de nubes y sombras "
        "generada a partir de `s2cloudless`."
    )

    lines.append("")
    lines.append("## 11. Escalado de bandas")
    lines.append("")
    lines.append("Las bandas ópticas Sentinel-2 se escalan mediante el factor:")
    add_code_block(lines, "0.0001")
    lines.append(
        "Esto convierte los valores enteros de reflectancia escalada en valores decimales "
        "de reflectancia."
    )

    lines.append("")
    lines.append("## 12. Bandas e índices extraídos")
    lines.append("")
    lines.append("Las bandas e índices definidos en `spectralBands` son:")
    lines.append("")
    lines.extend(md_bullets(spectral_bands))
    lines.append("")
    lines.append("Los índices calculados son:")
    add_code_block(
        lines,
        "\n".join(
            [
                "NDVI   = (B8  - B4) / (B8  + B4)",
                "NDVI8A = (B8A - B4) / (B8A + B4)",
                "NDRE   = (B8A - B5) / (B8A + B5)",
            ]
        ),
    )

    lines.append("## 13. Composición mensual")
    lines.append("")
    lines.append(
        "Para cada mes se filtra la colección Sentinel-2 limpia y se calcula una "
        "composición mensual por mediana."
    )
    lines.append("")
    lines.append("Además de las bandas e índices, el script exporta:")
    lines.append("")
    lines.append(
        "- `n_obs_clean`: número de observaciones válidas después del enmascaramiento, "
        "usando la banda B4 como referencia."
    )
    lines.append("- `cloud_prob_median`: mediana mensual de probabilidad de nube.")
    lines.append("")
    lines.append("Cuando no hay datos válidos para un mes, se asignan valores de relleno:")
    lines.append("")
    lines.extend(
        md_table(
            ["Variable", "Valor sin datos"],
            [
                ["Bandas espectrales", "-9999"],
                ["Índices espectrales", "-9999"],
                ["`cloud_prob_median`", "-9999"],
                ["`n_obs_clean`", "0"],
            ],
        )
    )

    lines.append("")
    lines.append("## 14. Propiedades de punto conservadas")
    lines.append("")
    lines.append("El script conserva las siguientes propiedades provenientes de las unidades de extracción:")
    lines.append("")
    lines.extend(md_bullets(point_properties))

    lines.append("")
    lines.append("## 15. Metadatos agregados a la salida")
    lines.append("")
    lines.append("El script agrega los siguientes metadatos metodológicos:")
    lines.append("")
    lines.extend(md_bullets(metadata_properties))

    lines.append("")
    lines.append("## 16. Exportación a Google Drive")
    lines.append("")
    lines.append("La exportación se realiza mediante:")
    add_code_block(lines, "Export.table.toDrive")
    lines.append("La carpeta configurada en Google Drive fue:")
    add_code_block(lines, drive_folder)
    lines.append("El formato de salida configurado fue:")
    add_code_block(lines, file_format)
    lines.append("Cada batch activo genera un CSV independiente.")

    lines.append("")
    lines.append("## 17. Inventario local preliminar de CSV exportados")
    lines.append("")
    lines.append("Carpeta revisada:")
    add_code_block(lines, rel(raw_export_dir))

    raw_exists_text = "Sí" if raw_inventory["exists"] else "No"

    lines.extend(
        md_table(
            ["Métrica", "Valor"],
            [
                ["Carpeta existe", raw_exists_text],
                ["Número de CSV identificados", str(raw_inventory["n_csv"])],
                ["Tamaño total aproximado", format_bytes(int(raw_inventory["total_size"]))],
                ["Firmas de encabezado distintas", str(raw_inventory["n_header_signatures"])],
            ],
        )
    )

    lines.append("")
    lines.append("### Encabezado más frecuente identificado")
    lines.append("")
    header_values = raw_inventory["most_common_header"]
    lines.extend(md_bullets(header_values, empty="No se pudo leer encabezado CSV."))

    lines.append("")
    lines.append("### Archivos CSV identificados")
    lines.append("")
    file_rows = raw_inventory["file_rows"]

    if file_rows:
        lines.extend(
            md_table(
                ["Archivo", "Tamaño", "Número de columnas"],
                file_rows[:50],
            )
        )

        if len(file_rows) > 50:
            lines.append("")
            lines.append(f"Nota: se muestran los primeros 50 archivos de {len(file_rows)} identificados.")
    else:
        lines.append("No se identificaron CSV en la carpeta configurada.")

    lines.append("")
    lines.append(
        "Nota: este inventario lee únicamente los encabezados de los CSV para evitar "
        "cargar archivos grandes en memoria."
    )

    lines.append("")
    lines.append("## 18. Consideraciones de trazabilidad")
    lines.append("")
    lines.append(
        "Los CSV exportados deben considerarse la versión oficial de esta ejecución de "
        "Google Earth Engine, dado que ya fueron generados y representaron un costo "
        "computacional relevante."
    )
    lines.append("")
    lines.append(
        "El script JavaScript se conserva como evidencia metodológica del procedimiento "
        "aplicado. No se recomienda modificarlo retroactivamente para reinterpretar los "
        "resultados ya exportados."
    )

    lines.append("")
    lines.append("## 19. Consideraciones para análisis posterior")
    lines.append("")
    lines.append("Durante la consolidación posterior en Python se recomienda:")
    lines.append("")
    lines.append("1. Unificar todos los CSV exportados.")
    lines.append("2. Verificar consistencia de columnas entre batches.")
    lines.append("3. Tratar `-9999` como valor sin datos.")
    lines.append("4. Identificar meses con `n_obs_clean = 0`.")
    lines.append("5. Calcular métricas de completitud temporal por `extract_id`, país, año, fuente y clase.")
    lines.append("6. Revisar batches con pocos datos válidos o patrones anómalos.")
    lines.append("7. Integrar los resultados espectro-temporales con la base original mediante `extract_id`.")

    lines.append("")
    lines.append("## 20. Limitaciones conocidas")
    lines.append("")
    lines.append("- La extracción se realizó a escala nominal de 20 m.")
    lines.append("- Algunas bandas Sentinel-2 tienen resolución nativa de 10 m y otras de 20 m.")
    lines.append("- El script asume que cada batch contiene un único `year_ref`.")
    lines.append("- La región de filtrado se construye con el contorno envolvente de los puntos del batch.")
    lines.append("- Los meses sin datos válidos quedan representados por `-9999` y `n_obs_clean = 0`.")

    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Genera un reporte Markdown a partir del script JavaScript de GEE "
            "usado para la exportación Sentinel-2 SR mensual."
        )
    )

    parser.add_argument(
        "--js",
        type=str,
        default=str(DEFAULT_JS_RELATIVE_PATH),
        help="Ruta relativa o absoluta al script JavaScript de GEE.",
    )

    parser.add_argument(
        "--raw-dir",
        type=str,
        default=str(DEFAULT_RAW_EXPORT_DIR),
        help="Carpeta con los CSV crudos exportados desde GEE.",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_REPORT_RELATIVE_PATH),
        help="Ruta relativa o absoluta del reporte Markdown de salida.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    js_path = resolve_project_path(args.js)
    raw_export_dir = resolve_project_path(args.raw_dir)
    report_path = resolve_project_path(args.output)

    report_path.parent.mkdir(parents=True, exist_ok=True)

    report = generate_report(
        js_path=js_path,
        raw_export_dir=raw_export_dir,
        report_path=report_path,
    )

    report_path.write_text(report, encoding="utf-8")

    print("Reporte generado correctamente.")
    print(f"Script GEE: {js_path}")
    print(f"CSV raw dir: {raw_export_dir}")
    print(f"Reporte MD: {report_path}")


if __name__ == "__main__":
    main()
