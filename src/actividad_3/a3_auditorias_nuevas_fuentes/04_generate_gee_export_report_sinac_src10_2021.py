from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import csv
import hashlib
import re
from collections import Counter
from typing import Any

import pandas as pd


# =============================================================================
# PGBM - Reporte GEE Sentinel-2 SR para nueva fuente puntual
# Caso: SINAC SRC10 2021
# =============================================================================
#
# Propósito:
#   Generar un reporte metodológico y de control básico para la extracción
#   espectro-temporal Sentinel-2 SR mensual realizada en Google Earth Engine.
#
# Este script está adaptado al piloto:
#   SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica
#   id_fuente / source_id = 10
#
# Diferencia respecto al reporte original:
#   - No asume grupos_xy.
#   - No asume Nivel_1 / Nivel_2.
#   - Documenta Clase / GranClase / nombre_clase / nombre_gran_clase.
#   - Inventaría y valida CSV exportados desde GEE.
#   - Calcula controles básicos: filas, meses, extract_id, duplicados,
#     observaciones limpias y valores sin datos.
#
# Uso recomendado desde la carpeta del piloto:
#
#   python3 src/actividad_3/a3_auditorias_nuevas_fuentes/04_generate_gee_export_report_sinac_src10_2021.py
#
# O con rutas explícitas:
#
#   python3 src/actividad_3/a3_auditorias_nuevas_fuentes/04_generate_gee_export_report_sinac_src10_2021.py \
#     --js scripts/gee/a3_auditorias_nuevas_fuentes/s2_sr_monthly_s2cloudless_export_sinac_src10_2021.js \
#     --raw-dir data/processed/a3_auditorias_nuevas_fuentes/gee_exports \
#     --output outputs/reports/a3_auditorias_nuevas_fuentes/gee_input/gee_export_report_sinac_src10_2021.md
# =============================================================================


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]

DEFAULT_JS_CANDIDATES = [
    "scripts/gee/a3_auditorias_nuevas_fuentes/s2_sr_monthly_s2cloudless_export_sinac_src10_2021.js",
]

DEFAULT_RAW_DIR = "data/processed/a3_auditorias_nuevas_fuentes/gee_exports"
DEFAULT_CSV_PATTERN = "pgbm_s2sr_monthly_s2cloudless_sinac_src10_2021*.csv"
DEFAULT_OUTPUT = "outputs/reports/a3_auditorias_nuevas_fuentes/gee_input/gee_export_report_sinac_src10_2021.md"

SOURCE_NAME = "SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica"
SOURCE_ID = "10"
SOURCE_CODE = "SRC10"
COUNTRY_CODE = "CRI"
YEAR_REF = "2021"

SPECTRAL_OUTPUT_COLUMNS = [
    "B2", "B3", "B4", "B5", "B6", "B7",
    "B8", "B8A", "B11", "B12",
    "NDVI", "NDVI8A", "NDRE",
    "cloud_prob_median",
]


def resolve_path(path_value: str | Path, base_dir: Path = PROJECT_DIR) -> Path:
    """Resolve absolute or pilot-folder-relative path."""
    path = Path(path_value)
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def resolve_default_js() -> Path:
    """Find default JS path among known candidate names."""
    for name in DEFAULT_JS_CANDIDATES:
        candidate = PROJECT_DIR / name
        if candidate.exists():
            return candidate.resolve()

    # Return first candidate even if it does not exist, so the error is explicit.
    return (PROJECT_DIR / DEFAULT_JS_CANDIDATES[0]).resolve()


def read_text(path: Path) -> str:
    """Read UTF-8 text."""
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo requerido: {path}")
    return path.read_text(encoding="utf-8")


def sha256_text(text: str) -> str:
    """Calculate SHA256 hash of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def format_bytes(size_bytes: int) -> str:
    """Human-readable file size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"

    value = float(size_bytes)
    for unit in ["KB", "MB", "GB", "TB"]:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:,.2f} {unit}"

    return f"{value:,.2f} PB"


def rel(path: Path) -> str:
    """Return path relative to pilot folder when possible."""
    try:
        return str(path.relative_to(PROJECT_DIR)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def extract_string_var(text: str, var_name: str, default: str = "No identificado") -> str:
    """Extract JavaScript string var assignment."""
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*['\"]([^'\"]+)['\"]\s*;"
    match = re.search(pattern, text)
    return match.group(1) if match else default


def extract_number_var(text: str, var_name: str, default: str = "No identificado") -> str:
    """Extract JavaScript numeric var assignment."""
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*;"
    match = re.search(pattern, text)
    return match.group(1) if match else default


def extract_boolean_var(text: str, var_name: str, default: str = "No identificado") -> str:
    """Extract JavaScript boolean var assignment."""
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*(true|false)\s*;"
    match = re.search(pattern, text)
    return match.group(1) if match else default


def extract_array(text: str, var_name: str) -> list[str]:
    """Extract simple JavaScript array with quoted values."""
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*\[(.*?)\]\s*;"
    match = re.search(pattern, text, flags=re.DOTALL)
    if not match:
        return []
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))


def extract_collection_ids(text: str) -> list[str]:
    """Extract ee.ImageCollection IDs."""
    values = re.findall(r"ee\.ImageCollection\(['\"]([^'\"]+)['\"]\)", text)
    return sorted(set(values))


def extract_function_names(text: str) -> list[str]:
    """Extract JavaScript function names."""
    return re.findall(r"function\s+([A-Za-z0-9_]+)\s*\(", text)


def extract_batch_entries(text: str) -> list[dict[str, str]]:
    """Extract batch names and run flags from BATCHES_TO_EXPORT."""
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
    """Extract SCL exclusions from scl.neq lines."""
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
    """Extract Export.table.toDrive fileFormat."""
    match = re.search(r"fileFormat\s*:\s*['\"]([^'\"]+)['\"]", text)
    return match.group(1) if match else "No identificado"


def extract_tile_scale(text: str) -> str:
    """Extract sampleRegions tileScale."""
    match = re.search(r"tileScale\s*:\s*([0-9]+(?:\.[0-9]+)?)", text)
    return match.group(1) if match else "No identificado"


def extract_output_prefix_expression(text: str) -> str:
    """Extract var outputName expression."""
    match = re.search(r"var\s+outputName\s*=\s*(.*?);", text)
    return match.group(1).strip() if match else "No identificado"


def read_csv_header(path: Path) -> list[str]:
    """Read only CSV header."""
    for encoding in ["utf-8-sig", "utf-8", "latin-1"]:
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


def inventory_raw_exports(raw_dir: Path, pattern: str) -> dict[str, Any]:
    """Inventory exported CSV files."""
    csv_files = sorted(raw_dir.glob(pattern)) if raw_dir.exists() else []
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
        "csv_files": csv_files,
        "total_size": total_size,
        "n_header_signatures": len(header_counter),
        "most_common_header": most_common_header,
        "file_rows": file_rows,
    }


def analyze_export_csvs(csv_files: list[Path]) -> dict[str, Any]:
    """
    Analyze exported GEE CSVs.

    Uses pandas because expected pilot size is moderate. For very large future
    exports, this function can be changed to chunked reading.
    """
    if not csv_files:
        return {
            "has_data": False,
            "summary": {},
            "month_table": pd.DataFrame(),
            "class_table": pd.DataFrame(),
            "missing_columns": [],
        }

    frames = []
    for path in csv_files:
        df = pd.read_csv(path, encoding="utf-8-sig")
        df["_source_csv"] = path.name
        frames.append(df)

    data = pd.concat(frames, ignore_index=True)

    required = [
        "extract_id", "month", "year_ref", "source_id", "country_code",
        "class_code", "class_group_code", "class_name", "class_group_name",
        "n_obs_clean",
    ]
    missing_columns = [col for col in required if col not in data.columns]

    summary: dict[str, Any] = {
        "n_rows": len(data),
        "n_columns": data.shape[1],
        "n_csv": len(csv_files),
        "csv_names": [path.name for path in csv_files],
        "missing_columns": missing_columns,
    }

    if "extract_id" in data.columns:
        summary["n_extract_id"] = int(data["extract_id"].nunique(dropna=True))
    else:
        summary["n_extract_id"] = None

    if {"extract_id", "month"}.issubset(data.columns):
        summary["duplicated_extract_id_month"] = int(
            data.duplicated(subset=["extract_id", "month"]).sum()
        )
    else:
        summary["duplicated_extract_id_month"] = None

    if "month" in data.columns:
        months = sorted(data["month"].dropna().unique().tolist())
        summary["months"] = ", ".join(map(str, months))
        summary["n_months"] = len(months)
    else:
        summary["months"] = "No identificado"
        summary["n_months"] = None

    for col in ["year_ref", "year_extraction", "source_id", "country_code", "country"]:
        if col in data.columns:
            values = sorted(data[col].dropna().astype(str).unique().tolist())
            summary[f"{col}_values"] = ", ".join(values)
        else:
            summary[f"{col}_values"] = "No identificado"

    if "has_thematic_conflict" in data.columns:
        conflict_by_unit = (
            data[["extract_id", "has_thematic_conflict"]]
            .drop_duplicates()
        )
        summary["thematic_conflict_units"] = int(
            pd.to_numeric(conflict_by_unit["has_thematic_conflict"], errors="coerce")
            .fillna(0)
            .sum()
        )
    else:
        summary["thematic_conflict_units"] = "No identificado"

    if "n_obs_clean" in data.columns:
        n_obs = pd.to_numeric(data["n_obs_clean"], errors="coerce")
        summary["n_rows_zero_clean_obs"] = int((n_obs == 0).sum())
        summary["pct_rows_zero_clean_obs"] = round(float((n_obs == 0).mean() * 100), 4)
        summary["n_obs_clean_min"] = float(n_obs.min())
        summary["n_obs_clean_median"] = float(n_obs.median())
        summary["n_obs_clean_max"] = float(n_obs.max())
    else:
        summary["n_rows_zero_clean_obs"] = "No identificado"
        summary["pct_rows_zero_clean_obs"] = "No identificado"
        summary["n_obs_clean_min"] = "No identificado"
        summary["n_obs_clean_median"] = "No identificado"
        summary["n_obs_clean_max"] = "No identificado"

    present_spectral = [col for col in SPECTRAL_OUTPUT_COLUMNS if col in data.columns]
    if present_spectral:
        nodata_counts = {}
        for col in present_spectral:
            numeric = pd.to_numeric(data[col], errors="coerce")
            nodata_counts[col] = int((numeric == -9999).sum())
        summary["nodata_counts"] = nodata_counts
    else:
        summary["nodata_counts"] = {}

    if "month" in data.columns and "n_obs_clean" in data.columns:
        month_table = (
            data.assign(n_obs_clean_num=pd.to_numeric(data["n_obs_clean"], errors="coerce"))
            .groupby("month", dropna=False)
            .agg(
                rows=("extract_id", "size"),
                extract_ids=("extract_id", "nunique"),
                rows_zero_clean_obs=("n_obs_clean_num", lambda s: int((s == 0).sum())),
                median_clean_obs=("n_obs_clean_num", "median"),
                max_clean_obs=("n_obs_clean_num", "max"),
            )
            .reset_index()
            .sort_values("month")
        )
        month_table["pct_zero_clean_obs"] = (
            month_table["rows_zero_clean_obs"] / month_table["rows"] * 100
        ).round(4)
    else:
        month_table = pd.DataFrame()

    if "class_name" in data.columns:
        class_table = (
            data[["extract_id", "class_code", "class_group_code", "class_name", "class_group_name"]]
            .drop_duplicates()
            .groupby(["class_group_code", "class_group_name", "class_code", "class_name"], dropna=False)
            .size()
            .reset_index(name="extract_units")
            .sort_values("extract_units", ascending=False)
        )
    else:
        class_table = pd.DataFrame()

    return {
        "has_data": True,
        "summary": summary,
        "month_table": month_table,
        "class_table": class_table,
        "missing_columns": missing_columns,
    }


def md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Return Markdown table lines."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(map(str, row)) + " |")
    return lines


def md_bullets(values: list[str], empty: str = "No identificado") -> list[str]:
    """Return Markdown bullets."""
    if not values:
        return [f"- {empty}"]
    return [f"- `{value}`" for value in values]


def add_code_block(lines: list[str], content: str) -> None:
    """Add indented code block."""
    lines.append("")
    for line in str(content).splitlines():
        lines.append(f"    {line}")
    lines.append("")


def dataframe_to_md_rows(df: pd.DataFrame, max_rows: int = 30) -> list[list[str]]:
    """Convert DataFrame head to Markdown rows."""
    if df.empty:
        return []
    df2 = df.head(max_rows).copy()
    return [[str(value) for value in row] for row in df2.to_numpy().tolist()]


def generate_report(
    js_path: Path,
    raw_export_dir: Path,
    csv_pattern: str,
    report_path: Path,
    source_name: str = SOURCE_NAME,
    source_id: str = SOURCE_ID,
    source_code: str = SOURCE_CODE,
    country_code: str = COUNTRY_CODE,
    year_ref: str = YEAR_REF,
) -> str:
    """Generate Markdown report."""
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

    raw_inventory = inventory_raw_exports(raw_export_dir, csv_pattern)
    csv_analysis = analyze_export_csvs(raw_inventory["csv_files"])

    lines: list[str] = []

    lines.append("# Reporte metodológico y control inicial de exportación GEE Sentinel-2 SR")
    lines.append("")
    lines.append("## 1. Identificación del piloto")
    lines.append("")
    lines.extend(
        md_table(
            ["Elemento", "Valor"],
            [
                ["Fuente", source_name],
                ["Código fuente", source_code],
                ["`source_id`", source_id],
                ["País", country_code],
                ["Año de referencia", year_ref],
                ["Fecha de generación del reporte", generated_at],
                ["Script GEE documentado", f"`{rel(js_path)}`"],
                ["Hash SHA256 del JS", f"`{script_hash}`"],
                ["Número de líneas del JS", f"{line_count:,}"],
            ],
        )
    )

    lines.append("")
    lines.append("## 2. Ubicación de insumos y salidas")
    lines.append("")
    lines.append("Script JavaScript usado en Google Earth Engine:")
    add_code_block(lines, rel(js_path))
    lines.append("Carpeta revisada con CSV exportados desde GEE:")
    add_code_block(lines, rel(raw_export_dir))
    lines.append("Patrón de CSV analizado:")
    add_code_block(lines, csv_pattern)
    lines.append("Reporte generado:")
    add_code_block(lines, rel(report_path))

    lines.append("## 3. Propósito de la exportación")
    lines.append("")
    lines.append(
        "La exportación obtuvo variables espectro-temporales mensuales de Sentinel-2 "
        "Surface Reflectance para una fuente puntual independiente incorporada al flujo "
        "de auditoría espectral de nuevas fuentes."
    )
    lines.append("")
    lines.append("La unidad de extracción fue:")
    add_code_block(lines, "Longitud + Latitud + Año")
    lines.append(
        "Este piloto no depende de `grupos_xy`, `Nivel_1` ni `Nivel_2`. "
        "La trazabilidad temática se conserva mediante `class_code`, "
        "`class_group_code`, `class_name` y `class_group_name`."
    )

    lines.append("")
    lines.append("## 4. Parámetros principales del JavaScript")
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
    lines.append("## 5. Colecciones de Google Earth Engine")
    lines.append("")
    lines.extend(md_bullets(collections))
    lines.append("")
    lines.append(
        "La colección `COPERNICUS/S2_SR_HARMONIZED` se usó para reflectancia de superficie "
        "y `COPERNICUS/S2_CLOUD_PROBABILITY` para la máscara s2cloudless."
    )

    lines.append("")
    lines.append("## 6. Batches configurados en GEE")
    lines.append("")
    batch_rows = [[f"`{entry['name']}`", entry["run"]] for entry in batch_entries]
    if not batch_rows:
        batch_rows = [["No identificado", "No identificado"]]
    lines.extend(md_table(["Batch", "run"], batch_rows))

    lines.append("")
    lines.append("## 7. Propiedades de punto conservadas")
    lines.append("")
    lines.extend(md_bullets(point_properties))
    lines.append("")
    lines.append("Campos metodológicos agregados:")
    lines.extend(md_bullets(metadata_properties))

    lines.append("")
    lines.append("## 8. Bandas e índices exportados")
    lines.append("")
    lines.extend(md_bullets(spectral_bands))
    lines.append("")
    lines.append("Índices calculados:")
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

    lines.append("## 9. Máscara de nubes, sombras y SCL")
    lines.append("")
    lines.append(
        "La máscara combina probabilidad de nube, píxeles oscuros en NIR, "
        "proyección de sombra y exclusión de clases SCL."
    )
    lines.append("")
    scl_table_rows = [[code, label] for code, label in scl_rows]
    if not scl_table_rows:
        scl_table_rows = [["No identificado", "No identificado"]]
    lines.extend(md_table(["Clase SCL excluida", "Descripción"], scl_table_rows))

    lines.append("")
    lines.append("## 10. Inventario local de CSV exportados desde GEE")
    lines.append("")
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
    file_rows = raw_inventory["file_rows"]
    if file_rows:
        lines.extend(md_table(["Archivo", "Tamaño", "Número de columnas"], file_rows))
    else:
        lines.append("No se identificaron CSV con el patrón configurado.")

    lines.append("")
    lines.append("## 11. Control inicial del contenido exportado")
    lines.append("")
    if not csv_analysis["has_data"]:
        lines.append("No se analizaron datos porque no se identificaron CSV exportados.")
    else:
        s = csv_analysis["summary"]
        expected_rows = "No calculable"
        if s.get("n_extract_id") is not None and s.get("n_months") is not None:
            expected_rows = f"{int(s['n_extract_id']) * int(s['n_months']):,}"

        lines.extend(
            md_table(
                ["Control", "Resultado"],
                [
                    ["Filas exportadas", f"{int(s['n_rows']):,}"],
                    ["Columnas", f"{int(s['n_columns']):,}"],
                    ["CSV analizados", f"{int(s['n_csv']):,}"],
                    ["`extract_id` únicos", f"{int(s['n_extract_id']):,}" if s.get("n_extract_id") is not None else "No identificado"],
                    ["Meses presentes", s.get("months", "No identificado")],
                    ["Filas esperadas según extract_id × meses", expected_rows],
                    ["Duplicados `extract_id + month`", str(s.get("duplicated_extract_id_month"))],
                    ["`year_ref`", s.get("year_ref_values", "No identificado")],
                    ["`year_extraction`", s.get("year_extraction_values", "No identificado")],
                    ["`source_id`", s.get("source_id_values", "No identificado")],
                    ["`country_code`", s.get("country_code_values", "No identificado")],
                    ["Unidades con posible conflicto temático", str(s.get("thematic_conflict_units"))],
                    ["Filas con `n_obs_clean = 0`", str(s.get("n_rows_zero_clean_obs"))],
                    ["Porcentaje con `n_obs_clean = 0`", f"{s.get('pct_rows_zero_clean_obs')}%"],
                    ["Mínimo `n_obs_clean`", str(s.get("n_obs_clean_min"))],
                    ["Mediana `n_obs_clean`", str(s.get("n_obs_clean_median"))],
                    ["Máximo `n_obs_clean`", str(s.get("n_obs_clean_max"))],
                ],
            )
        )

        missing = csv_analysis.get("missing_columns", [])
        lines.append("")
        lines.append("Columnas requeridas faltantes:")
        lines.extend(md_bullets(missing, empty="Ninguna."))

    lines.append("")
    lines.append("## 12. Control mensual de observaciones limpias")
    lines.append("")
    month_table = csv_analysis.get("month_table", pd.DataFrame())
    if isinstance(month_table, pd.DataFrame) and not month_table.empty:
        lines.extend(md_table(list(month_table.columns), dataframe_to_md_rows(month_table, max_rows=12)))
    else:
        lines.append("No se generó tabla mensual.")

    lines.append("")
    lines.append("## 13. Distribución temática de unidades exportadas")
    lines.append("")
    class_table = csv_analysis.get("class_table", pd.DataFrame())
    if isinstance(class_table, pd.DataFrame) and not class_table.empty:
        lines.extend(md_table(list(class_table.columns), dataframe_to_md_rows(class_table, max_rows=50)))
    else:
        lines.append("No se generó tabla temática.")

    lines.append("")
    lines.append("## 14. Valores sin datos por banda o índice")
    lines.append("")
    if csv_analysis["has_data"]:
        nodata_counts = csv_analysis["summary"].get("nodata_counts", {})
        if nodata_counts:
            nodata_rows = [[band, f"{count:,}"] for band, count in nodata_counts.items()]
            lines.extend(md_table(["Variable", "Cantidad de -9999"], nodata_rows))
        else:
            lines.append("No se identificaron columnas espectrales para este control.")
    else:
        lines.append("No se analizaron valores sin datos.")

    lines.append("")
    lines.append("## 15. Consideraciones para el procesamiento posterior")
    lines.append("")
    lines.append("1. Tratar `-9999` como valor sin datos.")
    lines.append("2. Revisar los registros con `n_obs_clean = 0` antes de cualquier scoring.")
    lines.append("3. Mantener `extract_id` como llave principal para integrar resultados espectrales.")
    lines.append("4. Usar `has_thematic_conflict` para excluir o priorizar revisión en unidades conflictivas.")
    lines.append("5. Evaluar completitud mensual por clase antes de usar estos datos como entrenamiento.")
    lines.append("6. Documentar cualquier cambio posterior en el JavaScript mediante hash o versión.")

    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Genera un reporte metodológico y control inicial para la exportación "
            "GEE Sentinel-2 SR del piloto SINAC SRC10 2021."
        )
    )

    parser.add_argument(
        "--js",
        type=str,
        default=None,
        help="Ruta al JavaScript de GEE. Si se omite, busca nombres conocidos en la carpeta del script.",
    )

    parser.add_argument(
        "--raw-dir",
        type=str,
        default=DEFAULT_RAW_DIR,
        help="Carpeta con CSV exportados desde GEE.",
    )

    parser.add_argument(
        "--csv-pattern",
        type=str,
        default=DEFAULT_CSV_PATTERN,
        help="Patrón glob para identificar CSV exportados desde GEE.",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT,
        help="Ruta del reporte Markdown de salida.",
    )

    parser.add_argument(
        "--source-name",
        type=str,
        default=SOURCE_NAME,
        help="Nombre de la fuente para el reporte.",
    )

    parser.add_argument(
        "--source-id",
        type=str,
        default=SOURCE_ID,
        help="source_id para el reporte.",
    )

    parser.add_argument(
        "--source-code",
        type=str,
        default=SOURCE_CODE,
        help="Código corto de fuente para el reporte.",
    )

    parser.add_argument(
        "--country-code",
        type=str,
        default=COUNTRY_CODE,
        help="Código de país para el reporte.",
    )

    parser.add_argument(
        "--year-ref",
        type=str,
        default=YEAR_REF,
        help="Año de referencia para el reporte.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    js_path = resolve_path(args.js) if args.js else resolve_default_js()
    raw_dir = resolve_path(args.raw_dir)
    output_path = resolve_path(args.output)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    report = generate_report(
        js_path=js_path,
        raw_export_dir=raw_dir,
        csv_pattern=args.csv_pattern,
        report_path=output_path,
        source_name=args.source_name,
        source_id=args.source_id,
        source_code=args.source_code,
        country_code=args.country_code,
        year_ref=args.year_ref,
    )

    output_path.write_text(report, encoding="utf-8")

    print("Reporte generado correctamente.")
    print(f"JS documentado: {js_path}")
    print(f"Carpeta CSV: {raw_dir}")
    print(f"Patrón CSV: {args.csv_pattern}")
    print(f"Reporte MD: {output_path}")


if __name__ == "__main__":
    main()
