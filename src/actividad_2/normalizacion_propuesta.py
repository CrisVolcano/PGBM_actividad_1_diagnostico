
# -*- coding: utf-8 -*-
"""
Actividad 2.1 — Implementación del modelo de datos
==================================================

Ordena la salida de Actividad 1 en una estructura relacional pragmática:

- una capa espacial principal: xy_point
- FKs de clase directamente en xy_point: id_0, id_1, id_2
- tablas de referencia de clases de origen en 3NF
- CSVs temáticos enlazables por xy_group_id
- validación dominante vs valores
- metadatos de auditoría
- reporte de validación

Criterios:
- No se exportan los campos compuestos nivel_*_dominante ni valores_nivel_*.
- Esos campos se usan solo como insumos para calcular FKs y validar consistencia.
- Los labels de clase solo viven en las tablas de referencia:
  clase_origen_nivel_0, clase_origen_nivel_1, clase_origen_nivel_2.
"""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import yaml

try:
    import fiona
except Exception:
    fiona = None


# ============================================================
# RUTAS BASE DEL REPOSITORIO
# ============================================================


ROOT = Path(__file__).resolve().parents[2]

ROOT_yaml = Path(__file__).resolve().parents[2]


CONFIG = ROOT_yaml / "config" / "a2_1_modelo_datos.yaml"

OUT = ROOT / "outputs" / "tables"
REP = ROOT / "outputs" / "reports"
LOG = ROOT / "logs"

# PROCESSED = ROOT / "data"
# PROCESSED_SCORING = PROCESSED / "scoring_aptitud"
# PROCESSED_A2_1 = PROCESSED / "a2_1_modelo_datos_implemented"

# SCORING_GPKG = PROCESSED_SCORING / "10_scoring_aptitud_outputs.gpkg"



# ============================================================
# CONFIGURACIÓN Y LOGS
# ============================================================

def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo de configuración: {path}")

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def as_project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT / path


def setup_logging(log_dir: Path, activity: str) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{activity}.log"

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_path, mode="w", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    return log_path


# ============================================================
# NORMALIZACIÓN DE NOMBRES
# ============================================================

def normalize_name(name: str) -> str:
    text = str(name).strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def normalize_columns(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    original_cols = list(gdf.columns)
    normalized_cols: list[str] = []
    seen: dict[str, int] = {}

    for col in original_cols:
        new_col = "geometry" if col == "geometry" else normalize_name(col)

        if new_col in seen:
            seen[new_col] += 1
            new_col = f"{new_col}_{seen[new_col]}"
        else:
            seen[new_col] = 0

        normalized_cols.append(new_col)

    out = gdf.copy()
    out.columns = normalized_cols

    mapping = pd.DataFrame(
        {
            "campo_original_archivo": original_cols,
            "campo_normalizado_archivo": normalized_cols,
        }
    )

    return out, mapping


# ============================================================
# LECTURA DE GPKG
# ============================================================

def list_gpkg_layers(gpkg: Path) -> list[str]:
    if fiona is not None:
        return list(fiona.listlayers(str(gpkg)))

    try:
        import pyogrio
        return list(pyogrio.list_layers(gpkg)["name"])
    except Exception:
        return []


def read_input_gpkg(gpkg: Path, layer: str | None) -> tuple[gpd.GeoDataFrame, str | None]:
    if not gpkg.exists():
        raise FileNotFoundError(f"No existe el GeoPackage de entrada: {gpkg}")

    layers = list_gpkg_layers(gpkg)

    if layer is None and len(layers) == 1:
        layer = layers[0]

    if layer is None and len(layers) > 1:
        raise ValueError(
            "El GeoPackage tiene varias capas. Defina input.layer en el YAML. "
            f"Capas disponibles: {layers}"
        )

    logging.info("Leyendo GeoPackage: %s", gpkg)
    logging.info("Capa seleccionada: %s", layer)

    gdf = gpd.read_file(gpkg, layer=layer) if layer else gpd.read_file(gpkg)
    return gdf, layer


# ============================================================
# ESQUEMA
# ============================================================

def schema_tables(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg["schema"]["tables"]


def pk_field(cfg: dict[str, Any]) -> str:
    return cfg["schema"]["pk"]


def class_fk_sources(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg.get("normalization", {}).get("class_fk_sources", {})


def fields_by_type(cfg: dict[str, Any], dtype: str) -> set[str]:
    return set(cfg["schema"]["field_types"].get(dtype, []))


def expected_fields(cfg: dict[str, Any]) -> list[str]:
    fields: list[str] = []

    for table_def in schema_tables(cfg).values():
        for field in table_def["fields"]:
            if field not in fields:
                fields.append(field)

    return fields


def analytic_fields(cfg: dict[str, Any]) -> list[str]:
    pk = pk_field(cfg)
    return [field for field in expected_fields(cfg) if field != pk]


def source_fields_required(cfg: dict[str, Any]) -> list[str]:
    """Campos que deben existir en la entrada original."""
    required: list[str] = []

    # Campos directos del modelo.
    for table_def in schema_tables(cfg).values():
        for field in table_def["fields"]:
            if field not in {"id_0", "id_1", "id_2"} and field not in required:
                required.append(field)

    # Campos fuente para derivar FKs de clase y validar duplicados.
    for info in class_fk_sources(cfg).values():
        for source_field in [info.get("dominante"), info.get("valores")]:
            if source_field and source_field not in required:
                required.append(source_field)

    return required


def source_only_fields(cfg: dict[str, Any]) -> set[str]:
    fields: set[str] = set()

    for info in class_fk_sources(cfg).values():
        if info.get("dominante"):
            fields.add(info["dominante"])
        if info.get("valores"):
            fields.add(info["valores"])

    return fields


def infer_field_type(field: str, cfg: dict[str, Any]) -> str:
    pk = pk_field(cfg)

    if field == pk:
        return "VARCHAR UNIQUE NOT NULL"
    if field in fields_by_type(cfg, "boolean"):
        return "BOOLEAN"
    if field in fields_by_type(cfg, "integer"):
        return "INT"
    if field in fields_by_type(cfg, "float"):
        return "FLOAT"

    return "VARCHAR"


# ============================================================
# TIPOS
# ============================================================

def to_boolean_01(series: pd.Series) -> pd.Series:
    true_values = {"1", "true", "t", "si", "sí", "yes", "y", "verdadero"}
    false_values = {"0", "false", "f", "no", "n", "falso"}

    def convert(value):
        if pd.isna(value):
            return pd.NA

        if isinstance(value, bool):
            return 1 if value else 0

        if isinstance(value, (int, float)) and not pd.isna(value):
            if float(value) == 1:
                return 1
            if float(value) == 0:
                return 0

        text = str(value).strip().lower()

        if text in true_values:
            return 1
        if text in false_values:
            return 0

        return pd.NA

    return series.map(convert).astype("Int64")


def coerce_types(
    df: pd.DataFrame,
    cfg: dict[str, Any],
    table_name: str,
    warnings: list[str],
) -> pd.DataFrame:
    out = df.copy()

    text_fields = fields_by_type(cfg, "text")
    integer_fields = fields_by_type(cfg, "integer")
    float_fields = fields_by_type(cfg, "float")
    boolean_fields = fields_by_type(cfg, "boolean")

    for field in out.columns:
        if field == "geometry":
            continue

        if field in boolean_fields:
            out[field] = to_boolean_01(out[field])

        elif field in integer_fields:
            values = pd.to_numeric(out[field], errors="coerce")
            non_null = values.dropna()

            if len(non_null) and not ((non_null - non_null.round()).abs() < 1e-9).all():
                warnings.append(
                    f"{table_name}.{field}: se esperaba INT, pero contiene valores "
                    "no enteros. Se conserva como FLOAT para no perder información."
                )
                out[field] = values.astype("Float64")
            else:
                out[field] = values.round().astype("Int64")

        elif field in float_fields:
            out[field] = pd.to_numeric(out[field], errors="coerce").astype("Float64")

        elif field in text_fields:
            out[field] = out[field].astype("string")

    return out


def csvt_type(field: str, cfg: dict[str, Any]) -> str:
    if field in fields_by_type(cfg, "boolean"):
        return "Integer"
    if field in fields_by_type(cfg, "integer"):
        return "Integer"
    if field in fields_by_type(cfg, "float"):
        return "Real"

    return "String"


# ============================================================
# CATÁLOGO DE CLASES DE ORIGEN EN 3NF
# ============================================================

def source_catalog_raw_df(cfg: dict[str, Any]) -> pd.DataFrame:
    catalog = cfg.get("source_class_catalog", {})
    rows = catalog.get("rows", [])
    fields = catalog.get("fields", ["id_0", "nivel_0", "id_1", "nivel_1", "id_2", "nivel_2"])

    df = pd.DataFrame(rows, columns=fields)

    for field in ["id_0", "id_1", "id_2"]:
        df[field] = pd.to_numeric(df[field], errors="raise").astype("Int64")

    for field in ["nivel_0", "nivel_1", "nivel_2"]:
        df[field] = df[field].astype("string")

    return df


def validate_unique_dependency(df: pd.DataFrame, key: str, attrs: list[str]) -> None:
    for attr in attrs:
        counts = df[[key, attr]].drop_duplicates().groupby(key)[attr].nunique()
        bad = counts[counts > 1]
        if len(bad):
            raise ValueError(
                f"El catálogo no cumple dependencia funcional {key} -> {attr}. "
                f"Valores problemáticos: {bad.index.tolist()[:20]}"
            )


def source_catalog_tables(cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    raw = source_catalog_raw_df(cfg)

    validate_unique_dependency(raw, "id_0", ["nivel_0"])
    validate_unique_dependency(raw, "id_1", ["nivel_1", "id_0"])
    validate_unique_dependency(raw, "id_2", ["nivel_2", "id_1"])

    table_names = cfg["source_class_catalog"]["tables"]

    nivel_0 = (
        raw[["id_0", "nivel_0"]]
        .drop_duplicates()
        .sort_values("id_0")
        .reset_index(drop=True)
    )

    nivel_1 = (
        raw[["id_1", "nivel_1", "id_0"]]
        .drop_duplicates()
        .sort_values("id_1")
        .reset_index(drop=True)
    )

    nivel_2 = (
        raw[["id_2", "nivel_2", "id_1"]]
        .drop_duplicates()
        .sort_values("id_2")
        .reset_index(drop=True)
    )

    return {
        table_names["nivel_0"]: nivel_0,
        table_names["nivel_1"]: nivel_1,
        table_names["nivel_2"]: nivel_2,
    }


def class_lookup(cfg: dict[str, Any], level: int) -> set[int]:
    raw = source_catalog_raw_df(cfg)
    field = f"id_{level}"
    return set(int(x) for x in raw[field].dropna().unique())


def extract_class_code(value: Any, cfg: dict[str, Any]) -> int | pd._libs.missing.NAType:
    empty_values = set(str(v).strip().lower() for v in cfg.get("normalization", {}).get("empty_values", []))

    if pd.isna(value):
        return pd.NA

    text = str(value).strip()

    if text.lower() in empty_values:
        return pd.NA

    regex = cfg.get("normalization", {}).get("code_regex", r"^\s*(?P<cod>\d{2,3})\b.*$")
    match = re.match(regex, text)

    if match:
        return int(match.group("cod"))

    first = text.split()[0] if text.split() else ""
    if re.fullmatch(r"\d{2,3}", first):
        return int(first)

    return pd.NA


def split_multivalue(value: Any, cfg: dict[str, Any]) -> list[str]:
    if pd.isna(value):
        return []

    empty_values = set(str(v).strip().lower() for v in cfg.get("normalization", {}).get("empty_values", []))
    text = str(value).strip()

    if text.lower() in empty_values:
        return []

    split_regex = cfg.get("normalization", {}).get("split_regex", r"\s*(?:\||;)\s*")
    parts = [part.strip() for part in re.split(split_regex, text) if part.strip()]

    return parts


def derive_class_fks(
    gdf: gpd.GeoDataFrame,
    cfg: dict[str, Any],
    warnings: list[str],
) -> gpd.GeoDataFrame:
    """Calcula id_0, id_1 e id_2 para xy_point usando nivel_*_dominante."""
    out = gdf.copy()

    for id_field, info in class_fk_sources(cfg).items():
        source_field = info["dominante"]
        level = int(info["level"])

        if source_field not in out.columns:
            raise ValueError(f"No existe el campo fuente para derivar {id_field}: {source_field}")

        out[id_field] = out[source_field].apply(lambda value: extract_class_code(value, cfg)).astype("Int64")

        valid_codes = class_lookup(cfg, level)
        observed_codes = set(int(x) for x in out[id_field].dropna().unique())
        unknown_codes = sorted(observed_codes - valid_codes)

        if unknown_codes:
            msg = f"{id_field}: códigos no encontrados en clase_origen_nivel_{level}: {unknown_codes}"
            if cfg["validation"].get("fail_on_unknown_class_code", False):
                raise ValueError(msg)
            warnings.append(msg)

    return out


def validate_dominante_vs_valores(
    gdf: gpd.GeoDataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Compara nivel_*_dominante contra valores_nivel_* por cada XY.

    La validación no exporta los campos originales: solo reporta si son equivalentes.
    """
    pk = pk_field(cfg)
    rows: list[dict[str, Any]] = []

    for id_field, info in class_fk_sources(cfg).items():
        level = int(info["level"])
        dominant_field = info["dominante"]
        values_field = info["valores"]

        if dominant_field not in gdf.columns or values_field not in gdf.columns:
            continue

        valid_codes = class_lookup(cfg, level)

        for record in gdf[[pk, dominant_field, values_field]].itertuples(index=False):
            xy_value = getattr(record, pk)
            dominant_value = getattr(record, dominant_field)
            values_value = getattr(record, values_field)

            dominant_code = extract_class_code(dominant_value, cfg)
            values_codes = [
                extract_class_code(value, cfg)
                for value in split_multivalue(values_value, cfg)
            ]
            values_codes = [
                int(code) for code in values_codes if pd.notna(code)
            ]

            unique_values_codes = sorted(set(values_codes))

            dominant_code_int = int(dominant_code) if pd.notna(dominant_code) else pd.NA

            same = (
                pd.notna(dominant_code)
                and len(unique_values_codes) == 1
                and unique_values_codes[0] == dominant_code_int
            )

            unknown_codes = sorted(
                {
                    code for code in ([dominant_code_int] if pd.notna(dominant_code) else []) + unique_values_codes
                    if pd.notna(code) and code not in valid_codes
                }
            )

            rows.append(
                {
                    pk: xy_value,
                    "nivel": level,
                    "id_field": id_field,
                    "campo_dominante": dominant_field,
                    "campo_valores": values_field,
                    "codigo_dominante": dominant_code_int,
                    "codigos_valores": "|".join(str(code) for code in unique_values_codes),
                    "n_codigos_valores": len(unique_values_codes),
                    "dominante_igual_a_valores": bool(same),
                    "codigos_fuera_catalogo": "|".join(str(code) for code in unknown_codes),
                }
            )

    return pd.DataFrame(rows)


# ============================================================
# ESCRITURA DE SALIDAS
# ============================================================

def write_csv_with_csvt(df: pd.DataFrame, out_csv: Path, cfg: dict[str, Any]) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    csvt = ",".join(f'"{csvt_type(field, cfg)}"' for field in df.columns)
    out_csv.with_suffix(".csvt").write_text(csvt + "\n", encoding="utf-8")


def register_attribute_table_in_gpkg(
    conn: sqlite3.Connection,
    table_name: str,
    description: str = "",
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    conn.execute(
        """
        INSERT OR REPLACE INTO gpkg_contents
            (table_name, data_type, identifier, description, last_change)
        VALUES
            (?, 'attributes', ?, ?, ?)
        """,
        (table_name, table_name, description, now),
    )


def write_table_to_gpkg(
    df: pd.DataFrame,
    gpkg_path: Path,
    table_name: str,
    pk: str | None = None,
    create_index: bool = True,
) -> None:
    with sqlite3.connect(gpkg_path) as conn:
        df.to_sql(table_name, conn, if_exists="replace", index=False)

        register_attribute_table_in_gpkg(
            conn,
            table_name=table_name,
            description="Tabla no espacial de Actividad 2.1.",
        )

        if create_index and pk and pk in df.columns:
            index_name = f"idx_{table_name}_{pk}"
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS "{index_name}" '
                f'ON "{table_name}" ("{pk}")'
            )

        conn.commit()


def write_source_class_catalog_outputs(
    cfg: dict[str, Any],
    tables_dir: Path,
    gpkg_path: Path,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    create_index = bool(cfg["output"].get("create_join_indexes", True))

    for table_name, df in source_catalog_tables(cfg).items():
        df = coerce_types(df, cfg, table_name, warnings=[])

        out_csv = tables_dir / f"{table_name}.csv"
        write_csv_with_csvt(df, out_csv, cfg)

        pk = "id_0" if table_name.endswith("nivel_0") else "id_1" if table_name.endswith("nivel_1") else "id_2"

        if cfg["output"].get("write_tables_to_gpkg", True):
            write_table_to_gpkg(
                df=df,
                gpkg_path=gpkg_path,
                table_name=table_name,
                pk=pk,
                create_index=create_index,
            )

        summaries.append(
            {
                "tabla": table_name,
                "filas": len(df),
                "campos_incluyendo_pk": len(df.columns),
                "cardinalidad": "referencia_3nf",
                "ruta_csv": str(out_csv.relative_to(ROOT)),
                "en_gpkg": bool(cfg["output"].get("write_tables_to_gpkg", True)),
            }
        )

    return summaries


def write_metadata_to_gpkg(metadata_dir: Path, gpkg_path: Path) -> None:
    metadata_tables = {
        "campo_mapeo": metadata_dir / "campo_mapeo.csv",
        "field_audit": metadata_dir / "field_audit.csv",
        "table_summary": metadata_dir / "table_summary.csv",
        "column_name_normalization": metadata_dir / "column_name_normalization.csv",
        "validacion_dominante_vs_valores": metadata_dir / "validacion_dominante_vs_valores.csv",
    }

    with sqlite3.connect(gpkg_path) as conn:
        for table_name, csv_path in metadata_tables.items():
            if not csv_path.exists():
                continue

            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df.to_sql(table_name, conn, if_exists="replace", index=False)

            register_attribute_table_in_gpkg(
                conn,
                table_name=table_name,
                description="Tabla de metadata de Actividad 2.1.",
            )

        conn.commit()


# ============================================================
# METADATA
# ============================================================

def build_campo_mapeo(
    cfg: dict[str, Any],
    original_mapping: pd.DataFrame,
) -> pd.DataFrame:
    pk = pk_field(cfg)
    original_lookup = dict(
        zip(
            original_mapping["campo_normalizado_archivo"],
            original_mapping["campo_original_archivo"],
        )
    )

    rows: list[dict[str, str]] = []
    documented_pk = False

    def add_pk_once():
        nonlocal documented_pk
        if documented_pk:
            return

        rows.append(
            {
                "campo_original": original_lookup.get(pk, pk),
                "campo_normalizado": pk,
                "tabla_destino": "xy_point / csv_tematicos",
                "tipo_dato_propuesto": infer_field_type(pk, cfg),
                "accion": "pk_join",
                "observacion": (
                    "Llave natural de Actividad 1. Se conserva como PK lógica en "
                    "xy_point y como campo de join en cada CSV temático."
                ),
            }
        )
        documented_pk = True

    for table_name, table_def in schema_tables(cfg).items():
        add_pk_once()

        for field in table_def["fields"]:
            if field == pk:
                continue

            source_note = ""
            action = "conservar_en_gpkg" if table_name == "xy_point" else "separar_por_tema"

            if table_name == "xy_point" and field in class_fk_sources(cfg):
                source_note = f" Derivado desde {class_fk_sources(cfg)[field]['dominante']}."
                action = "extraer_fk_clase_desde_dominante"

            rows.append(
                {
                    "campo_original": original_lookup.get(field, field),
                    "campo_normalizado": field,
                    "tabla_destino": table_name,
                    "tipo_dato_propuesto": infer_field_type(field, cfg),
                    "accion": action,
                    "observacion": (
                        "Campo existente redistribuido sin crear atributos analíticos nuevos."
                        + source_note
                    ),
                }
            )

    # Documentar campos fuente eliminados de las salidas.
    for id_field, info in class_fk_sources(cfg).items():
        for source_kind in ["dominante", "valores"]:
            source = info[source_kind]
            rows.append(
                {
                    "campo_original": original_lookup.get(source, source),
                    "campo_normalizado": source,
                    "tabla_destino": "no_exportado",
                    "tipo_dato_propuesto": "SOURCE_ONLY",
                    "accion": "usar_para_fk_y_validacion",
                    "observacion": (
                        f"Campo usado para calcular/validar {id_field}. "
                        "No se exporta porque duplica información de clase y no corresponde a 3NF."
                    ),
                }
            )

    for table_name, df in source_catalog_tables(cfg).items():
        for field in df.columns:
            rows.append(
                {
                    "campo_original": "Tabla 1 - Sistema de clasificación de origen",
                    "campo_normalizado": field,
                    "tabla_destino": table_name,
                    "tipo_dato_propuesto": infer_field_type(field, cfg),
                    "accion": "tabla_referencia_3nf",
                    "observacion": (
                        "Tabla de referencia separada por nivel para eliminar dependencias "
                        "transitivas entre id_0, id_1 e id_2."
                    ),
                }
            )

    return pd.DataFrame(rows)


def build_field_audit(cfg: dict[str, Any], input_fields: list[str]) -> pd.DataFrame:
    model_fields = set(expected_fields(cfg))
    required_sources = set(source_fields_required(cfg))
    source_only = source_only_fields(cfg)

    rows: list[dict[str, Any]] = []

    for field in input_fields:
        if field == "geometry":
            continue

        assigned_tables = [
            table_name
            for table_name, table_def in schema_tables(cfg).items()
            if field in table_def.get("fields", [])
        ]

        used_to_build = []
        for id_field, info in class_fk_sources(cfg).items():
            if field == info.get("dominante"):
                used_to_build.append(f"xy_point.{id_field}")
            if field == info.get("valores"):
                used_to_build.append(f"validacion_dominante_vs_valores.{id_field}")

        rows.append(
            {
                "campo": field,
                "en_salida_modelo": field in model_fields,
                "usado_como_fuente": field in source_only,
                "requerido": field in required_sources,
                "tablas_asignadas": ";".join(assigned_tables),
                "tablas_derivadas": ";".join(used_to_build),
                "tipo_dato_propuesto": infer_field_type(field, cfg) if field in model_fields else "",
            }
        )

    return pd.DataFrame(rows)


def write_readme(out_dir: Path, cfg: dict[str, Any]) -> None:
    pk = pk_field(cfg)
    table_names = cfg["source_class_catalog"]["tables"]

    readme = f"""# Actividad 2.1 — Modelo de datos implementado

## Criterio

La salida de Actividad 1 se reorganiza sin crear atributos analíticos nuevos.
Los campos se separan por dominio temático para facilitar joins selectivos.

## Llave central

`{pk}`

## Clases

`xy_point` conserva directamente las FKs de clase dominante:

- `id_0`
- `id_1`
- `id_2`

Los labels no se guardan en `xy_point`. Se consultan con joins directos:

- `xy_point.id_0` -> `{table_names["nivel_0"]}.id_0`
- `xy_point.id_1` -> `{table_names["nivel_1"]}.id_1`
- `xy_point.id_2` -> `{table_names["nivel_2"]}.id_2`

## Validación

Los campos fuente `nivel_*_dominante` y `valores_nivel_*` no se exportan.
Se usan para:

1. calcular `id_0`, `id_1`, `id_2`;
2. validar que dominante y valores sean equivalentes.

La validación queda en:

`metadata/validacion_dominante_vs_valores.csv`

## Tablas de referencia de clases de origen

- `{table_names["nivel_0"]}`: `id_0`, `nivel_0`
- `{table_names["nivel_1"]}`: `id_1`, `nivel_1`, `id_0`
- `{table_names["nivel_2"]}`: `id_2`, `nivel_2`, `id_1`

## Salidas

- `gpkg/{cfg["output"]["spatial_gpkg"]}`
  - capa: `{cfg["output"]["spatial_layer"]}`
  - tablas no espaciales para joins y referencias

- `tables/*.csv`
  - tablas temáticas y tablas de referencia

- `metadata/*.csv`
  - auditorías y trazabilidad del modelo
"""

    (out_dir / "README.md").write_text(readme, encoding="utf-8")


# ============================================================
# PROCESO PRINCIPAL
# ============================================================

def run() -> None:
    cfg = read_yaml(CONFIG)

    activity = cfg.get("activity", "a2_1_modelo_datos")
    log_dir = as_project_path(cfg["output"].get("logs_dir", LOG))
    log_file = setup_logging(log_dir, activity)

    logging.info("ROOT: %s", ROOT)
    logging.info("CONFIG: %s", CONFIG)
    logging.info("LOG: %s", log_file)

    input_gpkg = as_project_path(cfg["input"]["gpkg"])
    input_layer = cfg["input"].get("layer")

    processed_dir = as_project_path(cfg["output"]["processed_dir"])
    reports_dir = as_project_path(cfg["output"]["reports_dir"])

    gpkg_dir = processed_dir / cfg["output"]["gpkg_dir"]
    tables_dir = processed_dir / cfg["output"]["tables_dir"]
    metadata_dir = processed_dir / cfg["output"]["metadata_dir"]

    overwrite = bool(cfg["output"].get("overwrite", False))

    if processed_dir.exists() and overwrite:
        logging.info("Eliminando salida anterior: %s", processed_dir)
        shutil.rmtree(processed_dir)

    gpkg_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []

    # --------------------------------------------------------
    # Leer entrada
    # --------------------------------------------------------
    gdf_raw, layer_used = read_input_gpkg(input_gpkg, input_layer)
    gdf, original_mapping = normalize_columns(gdf_raw)

    pk = pk_field(cfg)

    input_fields_raw = [field for field in gdf.columns if field != "geometry"]
    model_fields = expected_fields(cfg)
    model_analytic_fields = analytic_fields(cfg)
    required_source_fields = source_fields_required(cfg)
    source_only = source_only_fields(cfg)

    missing = [field for field in required_source_fields if field not in input_fields_raw]
    extra = [
        field for field in input_fields_raw
        if field not in required_source_fields and field not in model_fields and field not in source_only
    ]

    strict_schema = bool(cfg["validation"].get("strict_schema", True))
    warn_extra_fields = bool(cfg["validation"].get("warn_extra_fields", True))

    if missing:
        msg = f"Campos esperados faltantes: {missing}"
        if strict_schema:
            raise ValueError(msg)
        warnings.append(msg)

    if extra and warn_extra_fields:
        warnings.append(f"Campos extra no asignados al modelo: {extra}")

    if pk not in gdf.columns:
        raise ValueError(f"No existe la llave principal esperada: {pk}")

    n_rows = len(gdf)
    n_null_pk = int(gdf[pk].isna().sum())
    n_dup_pk = int(gdf[pk].duplicated().sum())

    if cfg["validation"].get("require_non_null_pk", True) and n_null_pk > 0:
        raise ValueError(f"{pk} contiene {n_null_pk} valores nulos.")

    if cfg["validation"].get("require_unique_pk", True) and n_dup_pk > 0:
        raise ValueError(
            f"{pk} contiene {n_dup_pk} duplicados. "
            "La cardinalidad 1:1 con tablas temáticas no es válida."
        )

    # Validar catálogo antes de procesar.
    source_catalog_tables(cfg)

    # Derivar FKs de clase directamente para xy_point.
    gdf = derive_class_fks(gdf, cfg, warnings)

    # Validar duplicidad dominante/valores.
    validation_df = validate_dominante_vs_valores(gdf, cfg)

    mismatches = int((~validation_df["dominante_igual_a_valores"]).sum()) if not validation_df.empty else 0

    if mismatches > 0:
        msg = (
            f"Validación dominante vs valores: {mismatches} filas-nivel no coinciden. "
            "Revise metadata/validacion_dominante_vs_valores.csv."
        )
        if cfg["validation"].get("fail_on_dominante_valores_mismatch", False):
            raise ValueError(msg)
        warnings.append(msg)

    input_fields = [field for field in gdf.columns if field != "geometry"]
    gdf = coerce_types(gdf, cfg, "input", warnings)

    # --------------------------------------------------------
    # 1. Capa espacial
    # --------------------------------------------------------
    spatial_def = schema_tables(cfg)["xy_point"]
    spatial_fields = [field for field in spatial_def["fields"] if field in gdf.columns]

    xy_point = gdf[spatial_fields + ["geometry"]].copy()
    xy_point = coerce_types(xy_point, cfg, "xy_point", warnings)

    out_gpkg = gpkg_dir / cfg["output"]["spatial_gpkg"]

    if out_gpkg.exists():
        out_gpkg.unlink()

    logging.info("Escribiendo capa espacial: %s", out_gpkg)
    xy_point.to_file(
        out_gpkg,
        layer=cfg["output"]["spatial_layer"],
        driver="GPKG",
    )

    # --------------------------------------------------------
    # 2. CSVs temáticos
    # --------------------------------------------------------
    table_summary: list[dict[str, Any]] = []

    for table_name, table_def in schema_tables(cfg).items():
        if table_def.get("format") != "csv":
            continue

        fields = [field for field in table_def["fields"] if field in gdf.columns]

        if pk not in fields:
            raise ValueError(f"La tabla {table_name} no contiene {pk}.")

        table_df = gdf[fields].copy()
        table_df = coerce_types(table_df, cfg, table_name, warnings)

        out_csv = tables_dir / f"{table_name}.csv"
        write_csv_with_csvt(table_df, out_csv, cfg)

        logging.info("CSV creado: %s", out_csv)

        if cfg["output"].get("write_tables_to_gpkg", True):
            write_table_to_gpkg(
                df=table_df,
                gpkg_path=out_gpkg,
                table_name=table_name,
                pk=pk,
                create_index=bool(cfg["output"].get("create_join_indexes", True)),
            )
            logging.info("Tabla no espacial añadida al GPKG: %s", table_name)

        table_summary.append(
            {
                "tabla": table_name,
                "filas": len(table_df),
                "campos_incluyendo_pk": len(table_df.columns),
                "cardinalidad": table_def.get("cardinality", "1:1"),
                "ruta_csv": str(out_csv.relative_to(ROOT)),
                "en_gpkg": bool(cfg["output"].get("write_tables_to_gpkg", True)),
            }
        )

    # --------------------------------------------------------
    # 3. Tablas de referencia de clases de origen en 3NF
    # --------------------------------------------------------
    catalog_summaries = write_source_class_catalog_outputs(
        cfg=cfg,
        tables_dir=tables_dir,
        gpkg_path=out_gpkg,
    )
    table_summary.extend(catalog_summaries)

    # --------------------------------------------------------
    # 4. Metadata
    # --------------------------------------------------------
    campo_mapeo = build_campo_mapeo(cfg, original_mapping)
    campo_mapeo.to_csv(
        metadata_dir / "campo_mapeo.csv",
        index=False,
        encoding="utf-8-sig",
    )

    field_audit = build_field_audit(cfg, input_fields_raw)
    field_audit.to_csv(
        metadata_dir / "field_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )

    validation_df.to_csv(
        metadata_dir / "validacion_dominante_vs_valores.csv",
        index=False,
        encoding="utf-8-sig",
    )

    pd.DataFrame(table_summary).to_csv(
        metadata_dir / "table_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    original_mapping.to_csv(
        metadata_dir / "column_name_normalization.csv",
        index=False,
        encoding="utf-8-sig",
    )

    if cfg["output"].get("write_tables_to_gpkg", True):
        write_metadata_to_gpkg(metadata_dir=metadata_dir, gpkg_path=out_gpkg)
        logging.info("Tablas de metadata añadidas al GPKG.")

    write_readme(processed_dir, cfg)

    # --------------------------------------------------------
    # 5. Reporte
    # --------------------------------------------------------
    report_lines: list[str] = []

    report_lines.append("Actividad 2.1 — Reporte de implementación del modelo de datos")
    report_lines.append("=" * 72)
    report_lines.append(f"Fecha de proceso: {datetime.now().isoformat(timespec='seconds')}")
    report_lines.append(f"ROOT: {ROOT}")
    report_lines.append(f"CONFIG: {CONFIG}")
    report_lines.append(f"Archivo de entrada: {input_gpkg}")
    report_lines.append(f"Capa de entrada: {layer_used}")
    report_lines.append(f"Filas: {n_rows}")
    report_lines.append(f"CRS: {gdf.crs}")
    report_lines.append("")
    report_lines.append("Validación de campos")
    report_lines.append("-" * 72)
    report_lines.append(f"Campos fuente requeridos desde Actividad 1: {len(required_source_fields)}")
    report_lines.append(f"Campos de salida esperados, incluyendo {pk}: {len(model_fields)}")
    report_lines.append(f"Campos analíticos de salida, excluyendo {pk}: {len(model_analytic_fields)}")
    report_lines.append(f"Campos de salida generados/encontrados: {len([f for f in model_fields if f in input_fields])}")
    report_lines.append(f"Campos faltantes: {len(missing)}")
    report_lines.append(f"Campos extra no asignados: {len(extra)}")

    if missing:
        report_lines.append(f"Lista de faltantes: {missing}")
    if extra:
        report_lines.append(f"Lista de extra: {extra}")

    report_lines.append("")
    report_lines.append("Validación de llave")
    report_lines.append("-" * 72)
    report_lines.append(f"{pk} nulos: {n_null_pk}")
    report_lines.append(f"{pk} duplicados: {n_dup_pk}")
    report_lines.append("")
    report_lines.append("Normalización de clases")
    report_lines.append("-" * 72)
    report_lines.append("xy_point guarda FKs directas: id_0, id_1, id_2.")
    report_lines.append("Los labels de clase quedan solo en tablas de referencia de origen:")
    for table_name in cfg["source_class_catalog"]["tables"].values():
        report_lines.append(f"- {table_name}")
    report_lines.append(f"Filas-nivel con diferencia dominante vs valores: {mismatches}")
    report_lines.append("")
    report_lines.append("Salidas")
    report_lines.append("-" * 72)
    report_lines.append(f"GPKG espacial + tablas: {out_gpkg.relative_to(ROOT)}")
    report_lines.append(f"Tablas temáticas dentro del GPKG: {bool(cfg['output'].get('write_tables_to_gpkg', True))}")

    for row in table_summary:
        report_lines.append(
            f"CSV: {row['ruta_csv']} | filas={row['filas']} | "
            f"campos={row['campos_incluyendo_pk']} | cardinalidad={row['cardinalidad']} | "
            f"en_gpkg={row.get('en_gpkg', False)}"
        )

    report_lines.append(f"Metadata: {(metadata_dir / 'campo_mapeo.csv').relative_to(ROOT)}")
    report_lines.append(f"Metadata: {(metadata_dir / 'field_audit.csv').relative_to(ROOT)}")
    report_lines.append(f"Metadata: {(metadata_dir / 'table_summary.csv').relative_to(ROOT)}")
    report_lines.append(f"Metadata: {(metadata_dir / 'column_name_normalization.csv').relative_to(ROOT)}")
    report_lines.append(f"Metadata: {(metadata_dir / 'validacion_dominante_vs_valores.csv').relative_to(ROOT)}")
    report_lines.append("")
    report_lines.append("Advertencias")
    report_lines.append("-" * 72)

    if warnings:
        report_lines.extend(warnings)
    else:
        report_lines.append("Sin advertencias.")

    report_text = "\n".join(report_lines)

    report_path = reports_dir / "a2_1_modelo_datos_reporte_implementacion.txt"
    report_path.write_text(report_text, encoding="utf-8")

    logging.info("Reporte creado: %s", report_path)
    logging.info("Proceso finalizado correctamente.")

    print(report_text)


if __name__ == "__main__":
    run()
