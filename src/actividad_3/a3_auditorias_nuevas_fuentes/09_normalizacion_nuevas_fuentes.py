# -*- coding: utf-8 -*-
# Adaptación independiente para A3: auditorías y nuevas fuentes.
"""
Actividad 3 — Normalización de auditorías y nuevas fuentes
==========================================================

Adapta las salidas finales de SINAC y Panamá a la estructura relacional A2.1
mediante un código independiente y parametrizado por fuente:

- una capa espacial principal: xy_point
- FKs de clase de origen directamente en xy_point: id_0, id_1, id_2
- tablas de referencia de clases de origen en 3NF
- catálogo normalizado de países y FKs de país por rol
- catálogos propuestos de niveles 0 y 1
- homologación general N:1 por id_0 e id_1
- excepciones N:1 por id_2 con prioridad sobre la regla general de nivel 1
- tabla final de homologación por xy_group_id lista para un único join en QGIS
- CSVs temáticos enlazables por xy_group_id
- validación dominante vs valores
- xy_score conserva solo los scores finales reales del Módulo 10
- exclusión explícita de subcriterios e insumos internos del scoring para evitar redundancia
- metadatos de auditoría
- reporte de validación

Criterios:
- No se exportan los campos compuestos nivel_*_dominante ni valores_nivel_*.
- Esos campos se usan solo como insumos para calcular FKs y validar consistencia.
- xy_point no almacena pais_grupo como texto; almacena id_pais_grupo.
- xy_core no almacena pais_dominante como texto; almacena id_pais_dominante.
- xy_point no almacena id_0_propuesta ni id_1_propuesta.
- El nivel 1 final se resuelve con prioridad:
  1) excepción id_2 -> id_1_propuesta, cuando exista;
  2) regla general id_1 -> id_1_propuesta, en caso contrario.
- El nivel 0 propuesto final se deriva del padre de id_1_propuesta final;
  la regla id_0 -> id_0_propuesta se conserva como regla general de respaldo
  y como tabla normalizada, pero no domina las excepciones de nivel 2.
- Todas las tablas de homologación son N:1 y deterministas.
- xy_homologacion_final materializa códigos y labels finales solo para revisión/join.
- Los labels maestros de clase continúan en sus tablas de referencia.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
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


ROOT = Path(__file__).resolve().parents[3]

CONFIG = (
    ROOT
    / "config"
    / "a3_auditorias_nuevas_fuentes"
    / "config_normalizacion_nuevas_fuentes.yaml"
)

LOG = ROOT / "logs"



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


def require_output_child(path: Path, parent: Path) -> None:
    """Impide que overwrite elimine la raíz compartida o una ruta externa."""
    resolved_path = path.resolve()
    resolved_parent = parent.resolve()
    if resolved_path == resolved_parent or not resolved_path.is_relative_to(resolved_parent):
        raise ValueError(
            f"Ruta de salida insegura: {resolved_path}. Debe estar dentro de "
            f"{resolved_parent} y no puede ser la raíz compartida."
        )


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


def adapt_source_input(
    gdf: gpd.GeoDataFrame,
    source_cfg: dict[str, Any],
    cfg: dict[str, Any],
    warnings: list[str],
) -> gpd.GeoDataFrame:
    """Estandariza la procedencia sin reconstruir datos intermedios ausentes."""
    out = gdf.copy()
    source_key = str(source_cfg["source_key"]).strip()
    if not source_key:
        raise ValueError("Cada entrada debe definir un source_key no vacío.")

    out["source_key"] = source_key

    field_map = source_cfg.get("traceability_field_map", {})
    for target_field in [
        "clase_original_codigo",
        "clase_original_nombre",
        "gran_clase_original_codigo",
        "gran_clase_original_nombre",
    ]:
        source_field = field_map.get(target_field)
        if source_field in (None, ""):
            out[target_field] = pd.NA
            continue
        source_field = normalize_name(source_field)
        if source_field not in out.columns:
            raise ValueError(
                f"{source_key}: no existe el campo de trazabilidad "
                f"{source_field!r} requerido para construir {target_field}."
            )
        out[target_field] = out[source_field]

    for canonical_field, alias_field in source_cfg.get(
        "a1_alias_field_map", {}
    ).items():
        canonical_field = normalize_name(canonical_field)
        alias_field = normalize_name(alias_field)
        missing_alias_fields = [
            field for field in [canonical_field, alias_field] if field not in out.columns
        ]
        if missing_alias_fields:
            raise ValueError(
                f"{source_key}: faltan campos para validar alias A1: "
                f"{missing_alias_fields}"
            )

        if canonical_field.startswith("id_"):
            canonical_values = pd.to_numeric(out[canonical_field], errors="coerce")
            alias_values = pd.to_numeric(out[alias_field], errors="coerce")
        else:
            canonical_values = out[canonical_field].map(
                lambda value: pd.NA if pd.isna(value) else normalize_name(value)
            )
            alias_values = out[alias_field].map(
                lambda value: pd.NA if pd.isna(value) else normalize_name(value)
            )

        mismatch = ~(
            (canonical_values.isna() & alias_values.isna())
            | (canonical_values == alias_values)
        )
        if mismatch.any():
            msg = (
                f"{source_key}: {int(mismatch.sum())} valores de {alias_field} "
                f"no coinciden con {canonical_field}."
            )
            if cfg["validation"].get("fail_on_class_id_label_mismatch", True):
                raise ValueError(msg)
            warnings.append(msg)

    expected_source_id = source_cfg.get("expected_source_id")
    if expected_source_id is not None:
        source_id_field = "id_fuente_dominante"
        if source_id_field not in out.columns:
            raise ValueError(
                f"{source_key}: falta {source_id_field} para validar la procedencia."
            )
        observed = set(
            pd.to_numeric(out[source_id_field], errors="coerce")
            .dropna()
            .astype(int)
            .unique()
        )
        expected = {int(expected_source_id)}
        if observed != expected:
            msg = (
                f"{source_key}: id_fuente_dominante observado={sorted(observed)}; "
                f"esperado={sorted(expected)}."
            )
            if cfg["validation"].get("fail_on_source_identity_mismatch", True):
                raise ValueError(msg)
            warnings.append(msg)

    expected_country = source_cfg.get("expected_country")
    if expected_country is not None:
        country_field = "pais_grupo"
        if country_field not in out.columns:
            raise ValueError(
                f"{source_key}: falta {country_field} para validar la procedencia."
            )
        observed_countries = {
            normalize_name(value)
            for value in out[country_field].dropna().astype(str).unique()
        }
        expected_countries = {normalize_name(expected_country)}
        if observed_countries != expected_countries:
            msg = (
                f"{source_key}: pais_grupo observado={sorted(observed_countries)}; "
                f"esperado={sorted(expected_countries)}."
            )
            if cfg["validation"].get("fail_on_source_identity_mismatch", True):
                raise ValueError(msg)
            warnings.append(msg)

    return out


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


def traceability_field_map(cfg: dict[str, Any]) -> dict[str, str]:
    source_cfg = cfg.get("_runtime_source", {})
    raw = source_cfg.get("traceability_field_map", {})
    return {
        str(target): normalize_name(source)
        for target, source in raw.items()
        if source not in (None, "")
    }


def a1_alias_field_map(cfg: dict[str, Any]) -> dict[str, str]:
    source_cfg = cfg.get("_runtime_source", {})
    raw = source_cfg.get("a1_alias_field_map", {})
    return {
        normalize_name(canonical): normalize_name(alias)
        for canonical, alias in raw.items()
    }


# ============================================================
# NORMALIZACIÓN DE PAÍSES
# ============================================================

def country_normalization_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return country-normalization configuration.

    Expected YAML structure:

    normalization:
      country:
        enabled: true
        catalog_table: pais
        id_field: id_pais_grupo
        name_field: pais
        null_values:
          - multipais_o_inconsistente
        rows:
          - id_pais_grupo: 1
            pais: Belice
          ...
        sources:
          id_pais_grupo:
            source_field: pais_grupo
          id_pais_dominante:
            source_field: pais_dominante
    """
    country_cfg = cfg.get("normalization", {}).get("country", {}) or {}
    if not bool(country_cfg.get("enabled", False)):
        return {}

    required = {"catalog_table", "id_field", "name_field", "rows", "sources"}
    missing = sorted(required - set(country_cfg))
    if missing:
        raise ValueError(f"Faltan claves en normalization.country: {missing}")

    catalog_table = str(country_cfg["catalog_table"])
    id_field = str(country_cfg["id_field"])
    name_field = str(country_cfg["name_field"])
    if not catalog_table or not id_field or not name_field:
        raise ValueError(
            "normalization.country debe definir catalog_table, id_field y name_field."
        )
    if id_field == name_field:
        raise ValueError("normalization.country.id_field y name_field deben ser distintos.")

    rows = country_cfg.get("rows", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError(
            "normalization.country.rows debe definir el único catálogo maestro de países."
        )

    sources = country_cfg.get("sources", {})
    if not isinstance(sources, dict) or not sources:
        raise ValueError("normalization.country.sources debe ser un diccionario no vacío.")

    for fk_field, spec in sources.items():
        if not isinstance(spec, dict) or not spec.get("source_field"):
            raise ValueError(
                f"normalization.country.sources.{fk_field} debe definir source_field."
            )
        if fk_field == name_field:
            raise ValueError(
                f"La FK por rol {fk_field} no puede reutilizar el campo textual del catálogo pais."
            )
        # Se permite que una FK por rol tenga el mismo nombre que la PK del catálogo.
        # En este modelo, id_pais_grupo es simultáneamente:
        # - PK de pais; y
        # - FK en xy_point que conserva el mismo identificador trazable desde A2.1.

    schema_defs = cfg.get("schema", {}).get("tables", {})
    if catalog_table in schema_defs:
        raise ValueError(
            f"{catalog_table} debe ser un único catálogo de referencia, no una tabla temática."
        )

    for fk_field in sources:
        destinations = [
            table_name
            for table_name, table_def in schema_defs.items()
            if fk_field in table_def.get("fields", [])
        ]
        if len(destinations) != 1:
            raise ValueError(
                f"{fk_field} debe aparecer una sola vez en schema.tables; "
                f"destinos encontrados: {destinations}"
            )

    return country_cfg


def country_source_specs(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    country_cfg = country_normalization_config(cfg)
    if not country_cfg:
        return {}
    return country_cfg["sources"]


def country_fk_fields(cfg: dict[str, Any]) -> set[str]:
    return set(country_source_specs(cfg).keys())


def country_source_fields(cfg: dict[str, Any]) -> set[str]:
    fields: set[str] = set()
    for spec in country_source_specs(cfg).values():
        fields.add(str(spec["source_field"]))
    return fields


def country_empty_values(cfg: dict[str, Any]) -> set[str]:
    values = {
        str(value).strip().lower()
        for value in cfg.get("normalization", {}).get("empty_values", [])
    }
    country_cfg = cfg.get("normalization", {}).get("country", {}) or {}
    values.update(
        str(value).strip().lower()
        for value in country_cfg.get("null_values", [])
    )
    return values


def clean_country_label(value: Any, cfg: dict[str, Any]) -> str | pd._libs.missing.NAType:
    if pd.isna(value):
        return pd.NA

    text = re.sub(r"\s+", " ", str(value).strip())
    if not text or text.lower() in country_empty_values(cfg):
        return pd.NA

    if lowercase_text_values(cfg):
        text = text.lower()

    return text


def country_key(value: Any, cfg: dict[str, Any]) -> str | pd._libs.missing.NAType:
    label = clean_country_label(value, cfg)
    if pd.isna(label):
        return pd.NA

    key = unicodedata.normalize("NFKD", str(label))
    key = "".join(ch for ch in key if not unicodedata.combining(ch))
    key = key.lower().strip()
    key = re.sub(r"\s+", " ", key)
    return key


def build_country_catalog_table(gdf: gpd.GeoDataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    country_cfg = country_normalization_config(cfg)
    if not country_cfg:
        return pd.DataFrame()

    id_field = country_cfg["id_field"]
    name_field = country_cfg["name_field"]
    catalog = pd.DataFrame(country_cfg["rows"], columns=[id_field, name_field])

    if catalog[[id_field, name_field]].isna().any().any():
        raise ValueError("normalization.country.rows contiene IDs o nombres nulos.")

    catalog[id_field] = pd.to_numeric(catalog[id_field], errors="raise").astype("Int64")
    if (catalog[id_field] <= 0).any():
        raise ValueError("pais.<id_field> debe contener enteros positivos.")
    if catalog[id_field].duplicated().any():
        duplicated = catalog.loc[catalog[id_field].duplicated(False), id_field].tolist()
        raise ValueError(f"normalization.country.rows tiene IDs de país duplicados: {duplicated}")

    catalog[name_field] = catalog[name_field].apply(
        lambda value: clean_country_label(value, cfg)
    ).astype("string")
    catalog["_country_key"] = catalog[name_field].apply(
        lambda value: country_key(value, cfg)
    ).astype("string")

    if catalog["_country_key"].isna().any():
        raise ValueError("normalization.country.rows contiene nombres de país no válidos.")
    if catalog["_country_key"].duplicated().any():
        duplicated = catalog.loc[
            catalog["_country_key"].duplicated(False),
            name_field,
        ].tolist()
        raise ValueError(
            "normalization.country.rows contiene nombres equivalentes duplicados: "
            f"{duplicated}"
        )

    known_keys = set(catalog["_country_key"].astype(str))
    observed_keys: set[str] = set()
    for source_field in sorted(country_source_fields(cfg)):
        if source_field not in gdf.columns:
            raise ValueError(f"No existe el campo fuente de país: {source_field}")
        observed_keys.update(
            str(key)
            for value in gdf[source_field].drop_duplicates()
            if not pd.isna(key := country_key(value, cfg))
        )

    unknown_keys = sorted(observed_keys - known_keys)
    if unknown_keys:
        raise ValueError(
            "Se observaron países sin ID en normalization.country.rows: "
            f"{unknown_keys}"
        )

    return (
        catalog[[id_field, name_field]]
        .sort_values(id_field)
        .reset_index(drop=True)
    )


def derive_country_fks(
    gdf: gpd.GeoDataFrame,
    cfg: dict[str, Any],
    country_catalog: pd.DataFrame,
    warnings: list[str],
) -> gpd.GeoDataFrame:
    country_cfg = country_normalization_config(cfg)
    if not country_cfg:
        return gdf

    id_field = country_cfg["id_field"]
    name_field = country_cfg["name_field"]

    if country_catalog.empty:
        warnings.append("No se encontraron países válidos para construir el catálogo pais.")
        return gdf

    key_to_id = {
        str(country_key(row[name_field], cfg)): int(row[id_field])
        for _, row in country_catalog.iterrows()
    }

    out = gdf.copy()
    for fk_field, spec in country_source_specs(cfg).items():
        source_field = spec["source_field"]
        if source_field not in out.columns:
            raise ValueError(f"No existe el campo fuente de país para {fk_field}: {source_field}")

        source_keys = out[source_field].map(lambda value: country_key(value, cfg))
        out[fk_field] = source_keys.map(key_to_id).astype("Int64")

        unresolved = int((source_keys.notna() & out[fk_field].isna()).sum())
        if unresolved:
            raise ValueError(
                f"{fk_field}: {unresolved} registros con país no resuelto desde {source_field}."
            )

    return out


# Campos derivados por el Módulo 10 que se conservan en sus salidas de
# auditoría/scoring, pero no forman parte del modelo relacional 3NF de A2.1.
# No se exportan a xy_point ni a las tablas temáticas para evitar redundancia:
# - score_fuente ya resume los componentes fuente;
# - score_confiabilidad ya resume la confiabilidad por XY;
# - listas tipo ids_fuente_presentes/fuentes_presentes no son 1NF;
# - campos *_dominante de fuente son descriptores agregados, no llaves normalizadas.
# Campos que pueden venir desde el Módulo 10, pero que NO forman parte
# del modelo normalizado depurado. Se documentan en metadata/field_audit.csv
# y no generan advertencia de esquema.
#
# Regla actual del modelo A2.1:
# - conservar únicamente scores finales reales por criterio;
# - excluir subcriterios o insumos usados para calcular esos scores;
# - excluir listas agregadas y campos descriptivos de fuente cuando no son
#   necesarios para el uso final del modelo normalizado.
DEFAULT_AUDIT_ONLY_FIELDS: set[str] = {
    # Fuente: descripción, listas o subcriterios del score_fuente.
    "id_fuente_dominante",
    "tipo_fuente_dominante",
    "detalle_tipo_fuente_dominante",
    "ids_fuente_presentes",
    "fuentes_presentes",
    "tipos_fuente_presentes",
    "score_directitud_fuente_promedio",
    "score_trazabilidad_fuente_promedio",
    "score_temporal_metadata_fuente_promedio",
    "score_fuente_promedio",
    "score_fuente_minimo",
    "score_fuente_maximo",
    "n_fuentes_anio_inconsistente",
    "n_fuentes_pais_inconsistente",
    # Confiabilidad: insumos o trazabilidad interna del score_confiabilidad.
    "conf_integrada_promedio_observada",
    "n_conf_integrada_observada",
    "pct_conf_integrada_observada",
    "flag_confianza_imputada",
    "score_confiabilidad_base",
    "origen_score_confiabilidad",
    # Temático: subcriterios internos que alimentan score_tematico.
    "score_prioridad_revision",
    "score_consistencia_clase",
    "score_viabilidad_clase",
    "score_claridad_semantica",
    "score_nivel_leyenda",
    # Aptitud: campos previos/intermedios. El modelo conserva score_aptitud_total.
    "score_aptitud_raw",
    "score_cap",
    "cap_reason",
}

FINAL_XY_SCORE_FIELDS: list[str] = [
    "xy_group_id",
    "score_temporal",
    "score_espacial",
    "score_tematico",
    "score_espectral",
    "score_confiabilidad",
    "score_representatividad",
    "score_fuente",
    "score_aptitud_total",
]


def apply_score_final_policy(cfg: dict[str, Any]) -> dict[str, Any]:
    """Ajusta el esquema para conservar solo scores finales en xy_score.

    El YAML puede definir explícitamente:

    normalization:
      keep_only_final_scores: true
      final_score_table: xy_score
      final_score_fields:
        - xy_group_id
        - score_temporal
        ...

    Por defecto esta política está activa, porque A2.1 no debe almacenar
    insumos internos del cálculo multicriterio.
    """
    normalization = cfg.setdefault("normalization", {})
    keep_only = bool(normalization.get("keep_only_final_scores", True))
    if not keep_only:
        return cfg

    score_table = str(normalization.get("final_score_table", "xy_score"))
    score_fields = normalization.get("final_score_fields", FINAL_XY_SCORE_FIELDS)
    if not isinstance(score_fields, list) or not score_fields:
        raise ValueError("normalization.final_score_fields debe ser una lista no vacía.")

    pk = pk_field(cfg)
    normalized_score_fields: list[str] = []
    for field in score_fields:
        normalized = normalize_name(field)
        if normalized not in normalized_score_fields:
            normalized_score_fields.append(normalized)

    if pk not in normalized_score_fields:
        normalized_score_fields.insert(0, pk)

    tables = schema_tables(cfg)
    if score_table not in tables:
        raise ValueError(
            f"normalization.final_score_table='{score_table}' no existe en schema.tables."
        )

    tables[score_table]["fields"] = normalized_score_fields

    # Asegurar tipos float para los scores finales, sin obligar a guardar
    # subcriterios en el modelo.
    field_types = cfg.setdefault("schema", {}).setdefault("field_types", {})
    float_fields = field_types.setdefault("float", [])
    for field in normalized_score_fields:
        if field != pk and field not in float_fields:
            float_fields.append(field)

    # Los campos excluidos pueden declararse también desde YAML, pero el script
    # mantiene una lista base para no convertir subcriterios en advertencias.
    audit_fields = normalization.get("audit_only_fields", []) or []
    audit_set = {normalize_name(field) for field in audit_fields}
    audit_set.update(DEFAULT_AUDIT_ONLY_FIELDS)
    normalization["audit_only_fields"] = sorted(audit_set)

    return cfg


def audit_only_fields(cfg: dict[str, Any]) -> set[str]:
    """Campos aceptados como insumos de auditoría, pero excluidos del modelo.

    Se pueden ampliar desde YAML:

    normalization:
      audit_only_fields:
        - campo_extra_derivado
    """
    configured = cfg.get("normalization", {}).get("audit_only_fields", [])
    if configured is None:
        configured = []
    return DEFAULT_AUDIT_ONLY_FIELDS | {normalize_name(field) for field in configured}


def extra_field_policy(field: str, cfg: dict[str, Any]) -> str:
    """Clasifica campos no asignados directamente a tablas del modelo."""
    if field in audit_only_fields(cfg):
        return "excluido_por_diseno_auditoria_scoring"
    return "extra_no_asignado"



def proposed_homologations_config(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Devuelve todas las homologaciones configuradas por nivel propuesto."""
    homologations = cfg.get("proposed_class_homologations", {})

    if not isinstance(homologations, dict) or not homologations:
        raise ValueError(
            "Debe definir proposed_class_homologations en el YAML."
        )

    return homologations



def homologation_cardinality(hom: dict[str, Any]) -> str:
    """Valida que cada tabla de homologación sea determinista N:1."""
    value = str(hom.get("cardinality", "N:1")).upper()
    value = value.replace(" ", "").replace("M", "N")
    aliases = {
        "N:1": "N:1",
        "M:1": "N:1",
        "MANY_TO_ONE": "N:1",
        "MANY-TO-ONE": "N:1",
    }
    if value not in aliases:
        raise ValueError(
            f"Cardinalidad no soportada: {hom.get('cardinality')}. "
            "La implementación usa únicamente homologaciones N:1."
        )
    return aliases[value]

def fields_by_type(cfg: dict[str, Any], dtype: str) -> set[str]:
    return set(cfg["schema"]["field_types"].get(dtype, []))


def lowercase_text_values(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("normalization", {}).get("lowercase_text_values", False))


def lowercase_text_exclude_fields(cfg: dict[str, Any]) -> set[str]:
    configured = cfg.get("normalization", {}).get("lowercase_text_exclude_fields")
    if configured is None:
        configured = [pk_field(cfg)]
    return {str(field) for field in configured}


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
    """Campos que deben existir en la entrada original.

    Los campos generados por normalización, por ejemplo id_pais_grupo o
    id_pais_dominante, no se exigen como campos de entrada. En su lugar se
    exigen sus campos fuente textuales, como pais_grupo y pais_dominante.
    """
    required: list[str] = []
    generated_country_fields = country_fk_fields(cfg)

    # Campos directos del modelo, excepto FKs generadas y clases derivadas.
    for table_def in schema_tables(cfg).values():
        for field in table_def["fields"]:
            if field in {"id_0", "id_1", "id_2"}:
                continue
            if field in generated_country_fields:
                continue
            if field not in required:
                required.append(field)

    # Campos fuente para derivar FKs de clase y validar duplicados.
    for info in class_fk_sources(cfg).values():
        for source_field in [
            info.get("source_id"),
            info.get("dominante"),
            info.get("valores"),
        ]:
            if source_field and source_field not in required:
                required.append(source_field)

    # Campos fuente para construir el catálogo de países y sus FKs.
    for source_field in sorted(country_source_fields(cfg)):
        if source_field not in required:
            required.append(source_field)

    # Campos de clase originales usados para la tabla de trazabilidad A3.
    for source_field in traceability_field_map(cfg).values():
        if source_field not in required:
            required.append(source_field)

    for source_field in a1_alias_field_map(cfg).values():
        if source_field not in required:
            required.append(source_field)

    return required


def source_only_fields(cfg: dict[str, Any]) -> set[str]:
    fields: set[str] = set()

    for info in class_fk_sources(cfg).values():
        if info.get("source_id"):
            fields.add(info["source_id"])
        if info.get("dominante"):
            fields.add(info["dominante"])
        if info.get("valores"):
            fields.add(info["valores"])

    fields.update(country_source_fields(cfg))
    fields.update(traceability_field_map(cfg).values())
    fields.update(a1_alias_field_map(cfg).values())

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
            values = out[field].astype("string").str.strip()
            if lowercase_text_values(cfg) and field not in lowercase_text_exclude_fields(cfg):
                values = values.str.lower()
            out[field] = values

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




def proposed_homologation_tables(cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Construye y valida catálogos y reglas N:1 de homologación.

    La regla final de nivel 1 se compone de:

    - una homologación general ``id_1 -> id_1_propuesta``;
    - excepciones ``id_2 -> id_1_propuesta`` que tienen prioridad.

    Los catálogos propuestos pueden compartirse entre varias reglas mediante
    ``catalog_ref``. Cada tabla puente mantiene como PK/FK la llave de origen,
    garantizando un único destino por clase de origen.
    """
    homologations = proposed_homologations_config(cfg)
    raw_catalog = source_catalog_raw_df(cfg)
    tables: dict[str, pd.DataFrame] = {}

    required_keys = {
        "source_level",
        "source_id_field",
        "target_level",
        "target_id_field",
        "target_label_field",
        "target_table",
        "mapping_table",
        "mapping",
    }

    # --------------------------------------------------------
    # 1. Catálogos propuestos compartidos
    # --------------------------------------------------------
    for hom_name, hom in homologations.items():
        missing_keys = sorted(required_keys - set(hom))
        if missing_keys:
            raise ValueError(
                f"Faltan claves en proposed_class_homologations.{hom_name}: "
                f"{missing_keys}"
            )

        homologation_cardinality(hom)
        source_level = int(hom["source_level"])
        source_field = hom["source_id_field"]
        expected_source_field = f"id_{source_level}"
        if source_level not in {0, 1, 2}:
            raise ValueError(f"{hom_name}: source_level debe ser 0, 1 o 2.")
        if source_field != expected_source_field:
            raise ValueError(
                f"{hom_name}: source_id_field debe ser "
                f"{expected_source_field}, no {source_field}."
            )

        target_field = hom["target_id_field"]
        label_field = hom["target_label_field"]
        target_table = hom["target_table"]
        parent_field = hom.get("parent_target_id_field")
        parent_table = hom.get("parent_target_table")

        if bool(parent_field) != bool(parent_table):
            raise ValueError(
                f"{hom_name}: parent_target_id_field y parent_target_table "
                "deben definirse conjuntamente."
            )

        catalog_owner = hom
        catalog_ref = hom.get("catalog_ref")
        if catalog_ref:
            if catalog_ref not in homologations:
                raise ValueError(
                    f"{hom_name}: catalog_ref inexistente: {catalog_ref}."
                )
            catalog_owner = homologations[catalog_ref]
            if catalog_owner["target_table"] != target_table:
                raise ValueError(
                    f"{hom_name}: catalog_ref debe apuntar al mismo target_table."
                )

        if "classes" not in catalog_owner:
            raise ValueError(
                f"{hom_name}: no se encontraron clases para {target_table}."
            )

        class_fields = [target_field, label_field]
        if parent_field:
            class_fields.append(parent_field)

        classes_df = pd.DataFrame(catalog_owner["classes"])
        if not set(class_fields).issubset(classes_df.columns):
            raise ValueError(
                f"{hom_name}: el catálogo {target_table} debe contener "
                f"{class_fields}."
            )
        classes_df = classes_df[class_fields].copy()
        classes_df[target_field] = pd.to_numeric(
            classes_df[target_field], errors="raise"
        ).astype("Int64")
        classes_df[label_field] = classes_df[label_field].astype("string").str.strip()
        if parent_field:
            classes_df[parent_field] = pd.to_numeric(
                classes_df[parent_field], errors="raise"
            ).astype("Int64")

        if classes_df[class_fields].isna().any().any():
            raise ValueError(f"{hom_name}: {target_table} no admite nulos.")
        if classes_df[target_field].duplicated().any():
            duplicated = sorted(
                int(x) for x in classes_df.loc[
                    classes_df[target_field].duplicated(keep=False), target_field
                ].unique()
            )
            raise ValueError(
                f"{hom_name}: {target_field} repetidos en {target_table}: "
                f"{duplicated}"
            )

        classes_df = classes_df.sort_values(target_field).reset_index(drop=True)
        if target_table in tables:
            previous = tables[target_table].sort_values(target_field).reset_index(drop=True)
            if not previous.equals(classes_df):
                raise ValueError(
                    f"{hom_name}: definiciones incompatibles para el catálogo "
                    f"compartido {target_table}."
                )
        else:
            tables[target_table] = classes_df

    # --------------------------------------------------------
    # 2. Tablas puente N:1
    # --------------------------------------------------------
    for hom_name, hom in homologations.items():
        source_level = int(hom["source_level"])
        source_field = hom["source_id_field"]
        target_field = hom["target_id_field"]
        target_table = hom["target_table"]
        mapping_table = hom["mapping_table"]

        mapping_fields = [source_field, target_field]
        mapping_rows = hom.get("mapping", [])
        allow_empty_mapping = bool(hom.get("allow_empty_mapping", False))

        if not mapping_rows and allow_empty_mapping:
            # Permite tablas de excepción sin reglas activas. Esto evita inventar
            # excepciones cuando la homologación final usa solo la regla general.
            mapping_df = pd.DataFrame(columns=mapping_fields)
        else:
            mapping_df = pd.DataFrame(mapping_rows)
            if not set(mapping_fields).issubset(mapping_df.columns):
                raise ValueError(
                    f"{hom_name}: la tabla de homologación debe contener "
                    f"{mapping_fields}."
                )
            mapping_df = mapping_df[mapping_fields].copy()
        mapping_df[source_field] = pd.to_numeric(
            mapping_df[source_field], errors="raise"
        ).astype("Int64")
        mapping_df[target_field] = pd.to_numeric(
            mapping_df[target_field], errors="raise"
        ).astype("Int64")

        if mapping_df[mapping_fields].isna().any().any():
            raise ValueError(f"{hom_name}: la homologación no admite nulos.")
        if mapping_df[source_field].duplicated().any():
            duplicated = sorted(
                int(x) for x in mapping_df.loc[
                    mapping_df[source_field].duplicated(keep=False), source_field
                ].unique()
            )
            raise ValueError(
                f"{hom_name}: una clase de origen no puede tener varios "
                f"destinos. {source_field} repetidos: {duplicated}"
            )

        valid_source_ids = class_lookup(cfg, source_level)
        mapped_source_ids = set(int(x) for x in mapping_df[source_field].unique())
        missing_source_ids = sorted(valid_source_ids - mapped_source_ids)
        extra_source_ids = sorted(mapped_source_ids - valid_source_ids)
        if extra_source_ids:
            raise ValueError(
                f"{hom_name}: {source_field} inexistentes en el catálogo de "
                f"origen: {extra_source_ids}"
            )
        if missing_source_ids and bool(hom.get("require_complete_source_mapping", False)):
            raise ValueError(
                f"{hom_name}: clases de origen sin homologación: "
                f"{missing_source_ids}"
            )

        valid_target_ids = set(
            int(x) for x in tables[target_table][target_field].unique()
        )
        mapped_target_ids = set(int(x) for x in mapping_df[target_field].unique())
        unknown_targets = sorted(mapped_target_ids - valid_target_ids)
        if unknown_targets:
            raise ValueError(
                f"{hom_name}: destinos propuestos inexistentes: {unknown_targets}"
            )

        tables[mapping_table] = (
            mapping_df.sort_values(source_field).reset_index(drop=True)
        )

    # --------------------------------------------------------
    # 3. Validación de jerarquía propuesta y prioridad
    # --------------------------------------------------------
    level0_homs = [
        (name, hom) for name, hom in homologations.items()
        if int(hom["target_level"]) == 0
    ]
    level0_source_to_target: dict[int, int] = {}
    if level0_homs:
        level0_name, level0_hom = level0_homs[0]
        level0_df = tables[level0_hom["mapping_table"]]
        level0_source_to_target = dict(
            level0_df[[level0_hom["source_id_field"], level0_hom["target_id_field"]]]
            .astype(int)
            .itertuples(index=False, name=None)
        )

    for hom_name, hom in homologations.items():
        parent_field = hom.get("parent_target_id_field")
        if not parent_field:
            continue

        source_level = int(hom["source_level"])
        source_field = hom["source_id_field"]
        target_field = hom["target_id_field"]
        target_table = hom["target_table"]
        mapping_df = tables[hom["mapping_table"]]
        target_parent = dict(
            tables[target_table][[target_field, parent_field]]
            .astype(int)
            .itertuples(index=False, name=None)
        )

        if source_level == 0:
            source_to_id0 = {int(x): int(x) for x in raw_catalog["id_0"].unique()}
        else:
            source_to_id0 = dict(
                raw_catalog[[source_field, "id_0"]]
                .drop_duplicates()
                .astype(int)
                .itertuples(index=False, name=None)
            )

        # Validación de jerarquía propuesta.
        #
        # Las reglas generales deben respetar la relación padre-hijo entre
        # nivel 0 propuesto y nivel 1 propuesto. Sin embargo, las reglas
        # override por id_2 pueden cruzar dominio de forma intencional.
        # Ejemplo: 443 viene de 40/44 en la leyenda documental, pero se
        # homologa operativamente hacia 2/25 (No Bosques / Otras tierras).
        # En esos casos, la coherencia final se garantiza más adelante
        # derivando id_0_propuesta desde el padre de id_1_propuesta final.
        inconsistent: list[tuple[int, int, int, int]] = []
        for source_id, target_id in mapping_df[[source_field, target_field]].astype(int).itertuples(index=False, name=None):
            source_id0 = source_to_id0[source_id]
            expected_parent = level0_source_to_target.get(source_id0)
            observed_parent = target_parent[target_id]
            if expected_parent is not None and expected_parent != observed_parent:
                inconsistent.append(
                    (source_id, target_id, expected_parent, observed_parent)
                )

        if inconsistent and hom.get("role") == "override":
            logging.info(
                "%s: excepciones que cruzan dominio nivel 0 detectadas y permitidas: %s",
                hom_name,
                inconsistent[:20],
            )
        elif inconsistent:
            raise ValueError(
                f"{hom_name}: la homologación no respeta el nivel 0 propuesto: "
                f"{inconsistent[:20]}"
            )

        fallback_name = hom.get("fallback_homologation")
        if fallback_name:
            if fallback_name not in homologations:
                raise ValueError(
                    f"{hom_name}: fallback_homologation inexistente: "
                    f"{fallback_name}."
                )
            fallback = homologations[fallback_name]
            if int(fallback["target_level"]) != int(hom["target_level"]):
                raise ValueError(
                    f"{hom_name}: la regla general y las excepciones deben "
                    "tener el mismo target_level."
                )
            if fallback["target_table"] != hom["target_table"]:
                raise ValueError(
                    f"{hom_name}: la regla general y las excepciones deben "
                    "usar el mismo catálogo propuesto."
                )
            fallback_source = fallback["source_id_field"]
            fallback_ids = set(
                int(x) for x in tables[fallback["mapping_table"]][fallback_source].unique()
            )
            source_to_fallback = dict(
                raw_catalog[[source_field, fallback_source]]
                .drop_duplicates()
                .astype(int)
                .itertuples(index=False, name=None)
            )
            orphan_exceptions = sorted(
                source_id
                for source_id in mapping_df[source_field].astype(int).tolist()
                if source_to_fallback[source_id] not in fallback_ids
            )
            if orphan_exceptions:
                raise ValueError(
                    f"{hom_name}: excepciones sin regla general padre: "
                    f"{orphan_exceptions}"
                )

    return tables

def class_lookup(cfg: dict[str, Any], level: int) -> set[int]:
    raw = source_catalog_raw_df(cfg)
    field = f"id_{level}"
    return set(int(x) for x in raw[field].dropna().unique())


def class_label_lookup(cfg: dict[str, Any], level: int) -> dict[str, int]:
    """Relaciona labels A1 con sus IDs, tolerando mayúsculas y tildes."""
    raw = source_catalog_raw_df(cfg)
    id_field = f"id_{level}"
    label_field = f"nivel_{level}"
    lookup: dict[str, int] = {}

    for class_id, label in raw[[id_field, label_field]].drop_duplicates().itertuples(
        index=False, name=None
    ):
        key = normalize_name(label)
        class_id = int(class_id)
        previous = lookup.get(key)
        if previous is not None and previous != class_id:
            raise ValueError(
                f"El label {label!r} del nivel {level} corresponde a más de un ID."
            )
        lookup[key] = class_id

    return lookup


def extract_class_code(
    value: Any,
    cfg: dict[str, Any],
    level: int | None = None,
    label_lookup: dict[str, int] | None = None,
) -> int | pd._libs.missing.NAType:
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

    if level is not None:
        lookup = label_lookup if label_lookup is not None else class_label_lookup(cfg, level)
        return lookup.get(normalize_name(text), pd.NA)

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
    """Copia los IDs A1 entregados y los contrasta con sus labels dominantes."""
    out = gdf.copy()

    for id_field, info in class_fk_sources(cfg).items():
        source_field = info["dominante"]
        source_id_field = info.get("source_id")
        level = int(info["level"])

        if source_field not in out.columns:
            raise ValueError(f"No existe el campo fuente para derivar {id_field}: {source_field}")

        label_lookup = class_label_lookup(cfg, level)
        label_codes = out[source_field].apply(
            lambda value: extract_class_code(
                value,
                cfg,
                level=level,
                label_lookup=label_lookup,
            )
        ).astype("Int64")

        if source_id_field:
            if source_id_field not in out.columns:
                raise ValueError(
                    f"No existe el ID A1 entregado para construir {id_field}: "
                    f"{source_id_field}"
                )
            numeric_ids = pd.to_numeric(out[source_id_field], errors="coerce")
            invalid_ids = out[source_id_field].notna() & numeric_ids.isna()
            if invalid_ids.any():
                raise ValueError(
                    f"{source_id_field} contiene {int(invalid_ids.sum())} valores no numéricos."
                )
            fractional = numeric_ids.notna() & (
                (numeric_ids - numeric_ids.round()).abs() > 1e-9
            )
            if fractional.any():
                raise ValueError(
                    f"{source_id_field} contiene {int(fractional.sum())} IDs no enteros."
                )
            out[id_field] = numeric_ids.round().astype("Int64")

            mismatches = (
                out[id_field].notna()
                & label_codes.notna()
                & (out[id_field] != label_codes)
            )
            if mismatches.any():
                msg = (
                    f"{id_field}: {int(mismatches.sum())} IDs entregados en "
                    f"{source_id_field} no coinciden con {source_field}."
                )
                if cfg["validation"].get("fail_on_class_id_label_mismatch", True):
                    raise ValueError(msg)
                warnings.append(msg)

            labels_without_code = out[source_field].notna() & label_codes.isna()
            if labels_without_code.any():
                msg = (
                    f"{id_field}: {int(labels_without_code.sum())} labels de "
                    f"{source_field} no se encontraron en el catálogo A1."
                )
                if cfg["validation"].get("fail_on_class_id_label_mismatch", True):
                    raise ValueError(msg)
                warnings.append(msg)
        else:
            out[id_field] = label_codes

        valid_codes = class_lookup(cfg, level)
        observed_codes = set(int(x) for x in out[id_field].dropna().unique())
        unknown_codes = sorted(observed_codes - valid_codes)

        if unknown_codes:
            msg = f"{id_field}: códigos no encontrados en clase_origen_nivel_{level}: {unknown_codes}"
            if cfg["validation"].get("fail_on_unknown_class_code", False):
                raise ValueError(msg)
            warnings.append(msg)

    return out




def validate_observed_proposed_homologations(
    gdf: gpd.GeoDataFrame,
    cfg: dict[str, Any],
    warnings: list[str],
) -> dict[str, dict[str, int]]:
    """Valida cobertura y calcula la asignación final sin modificar xy_point.

    Para las reglas con ``fallback_homologation`` se aplica la prioridad:

    1. usar la excepción definida por la llave más detallada;
    2. si no existe, usar la homologación general.

    El resultado es único para cada punto y se utiliza solo para auditoría y
    reporte; las FKs propuestas continúan normalizadas en tablas separadas.
    """
    homologations = proposed_homologations_config(cfg)
    tables = proposed_homologation_tables(cfg)
    all_counts: dict[str, dict[str, int]] = {}

    # Cobertura individual de cada tabla puente.
    for hom_name, hom in homologations.items():
        source_field = hom["source_id_field"]
        target_field = hom["target_id_field"]
        mapping_df = tables[hom["mapping_table"]]
        target_df = tables[hom["target_table"]]

        if source_field not in gdf.columns:
            raise ValueError(
                f"{hom_name}: no existe {source_field} para validar la "
                "homologación propuesta."
            )

        mapping = dict(
            mapping_df[[source_field, target_field]]
            .astype(int)
            .itertuples(index=False, name=None)
        )
        observed_source_ids = set(int(x) for x in gdf[source_field].dropna().unique())
        unmapped_source_ids = sorted(observed_source_ids - set(mapping))
        if unmapped_source_ids and bool(hom.get("fail_on_unmapped_observed", False)):
            raise ValueError(
                f"{hom_name}: clases observadas sin homologación: "
                f"{unmapped_source_ids}"
            )

        mapped_values = gdf[source_field].map(mapping).astype("Int64")
        counts: dict[str, int] = {
            str(target_id): int((mapped_values == target_id).sum())
            for target_id in target_df[target_field].astype(int).tolist()
        }
        if hom.get("role") == "override":
            counts["registros_con_excepcion"] = int(mapped_values.notna().sum())
            counts["registros_sin_excepcion_usan_regla_general"] = int(
                mapped_values.isna().sum()
            )
            counts["clases_observadas_con_excepcion"] = int(
                len(observed_source_ids & set(mapping))
            )
        else:
            counts[f"registros_sin_{source_field}_o_sin_regla"] = int(
                mapped_values.isna().sum()
            )
            counts["clases_observadas_sin_regla"] = len(unmapped_source_ids)
        all_counts[hom_name] = counts

    # Resolución final: excepción > regla general.
    for exception_name, exception in homologations.items():
        fallback_name = exception.get("fallback_homologation")
        if not fallback_name:
            continue

        fallback = homologations[fallback_name]
        exception_source = exception["source_id_field"]
        fallback_source = fallback["source_id_field"]
        target_field = exception["target_id_field"]
        target_df = tables[exception["target_table"]]

        exception_map = dict(
            tables[exception["mapping_table"]][[exception_source, target_field]]
            .astype(int)
            .itertuples(index=False, name=None)
        )
        fallback_map = dict(
            tables[fallback["mapping_table"]][[fallback_source, target_field]]
            .astype(int)
            .itertuples(index=False, name=None)
        )

        exception_values = gdf[exception_source].map(exception_map).astype("Int64")
        fallback_values = gdf[fallback_source].map(fallback_map).astype("Int64")
        final_values = exception_values.combine_first(fallback_values).astype("Int64")

        # Validar que id_1/id_2 observados respeten la jerarquía de origen.
        raw_catalog = source_catalog_raw_df(cfg)
        valid_pairs = set(
            tuple(int(v) for v in row)
            for row in raw_catalog[[fallback_source, exception_source]]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        )
        observed_pairs = set(
            tuple(int(v) for v in row)
            for row in gdf[[fallback_source, exception_source]]
            .dropna()
            .drop_duplicates()
            .itertuples(index=False, name=None)
        )
        invalid_pairs = sorted(observed_pairs - valid_pairs)
        if invalid_pairs:
            warnings.append(
                f"{exception_name}: combinaciones observadas "
                f"{fallback_source}/{exception_source} fuera del catálogo: "
                f"{invalid_pairs[:20]}"
            )

        final_counts: dict[str, int] = {
            str(target_id): int((final_values == target_id).sum())
            for target_id in target_df[target_field].astype(int).tolist()
        }
        final_counts["registros_resueltos_por_excepcion"] = int(
            exception_values.notna().sum()
        )
        final_counts["registros_resueltos_por_regla_general"] = int(
            (exception_values.isna() & fallback_values.notna()).sum()
        )
        final_counts["registros_sin_homologacion_final"] = int(
            final_values.isna().sum()
        )

        final_name = exception.get(
            "final_assignment_name", f"{fallback_name}_final"
        )
        all_counts[final_name] = final_counts

    return all_counts

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
        label_lookup = class_label_lookup(cfg, level)

        for record in gdf[[pk, dominant_field, values_field]].itertuples(index=False):
            xy_value = getattr(record, pk)
            dominant_value = getattr(record, dominant_field)
            values_value = getattr(record, values_field)

            dominant_code = extract_class_code(
                dominant_value,
                cfg,
                level=level,
                label_lookup=label_lookup,
            )
            values_codes = [
                extract_class_code(
                    value,
                    cfg,
                    level=level,
                    label_lookup=label_lookup,
                )
                for value in split_multivalue(values_value, cfg)
            ]
            values_codes = [
                int(code) for code in values_codes if pd.notna(code)
            ]

            unique_values_codes = sorted(set(values_codes))

            dominant_code_int = int(dominant_code) if pd.notna(dominant_code) else pd.NA

            dominant_present = pd.notna(dominant_code)
            dominant_in_values = (
                dominant_present
                and dominant_code_int in unique_values_codes
            )
            same = (
                dominant_present
                and len(unique_values_codes) == 1
                and unique_values_codes[0] == dominant_code_int
            )

            if same:
                difference_type = "equivalente_unico"
            elif dominant_in_values and len(unique_values_codes) > 1:
                difference_type = "dominante_entre_multiples_valores"
            elif dominant_present and not unique_values_codes:
                difference_type = "dominante_sin_valores"
            elif dominant_present and not dominant_in_values:
                difference_type = "dominante_fuera_de_valores"
            elif not dominant_present and unique_values_codes:
                difference_type = "sin_dominante_con_valores"
            else:
                difference_type = "sin_dominante_sin_valores"

            unknown_codes = sorted(
                {
                    code for code in ([dominant_code_int] if dominant_present else []) + unique_values_codes
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
                    "dominante_en_valores": bool(dominant_in_values),
                    "tipo_diferencia": difference_type,
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
            description="Tabla no espacial de la normalización A3.",
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





def write_country_catalog_outputs(
    cfg: dict[str, Any],
    tables_dir: Path,
    gpkg_path: Path,
    country_catalog: pd.DataFrame,
) -> dict[str, Any] | None:
    country_cfg = country_normalization_config(cfg)
    if not country_cfg:
        return None

    table_name = country_cfg["catalog_table"]
    id_field = country_cfg["id_field"]

    df = coerce_types(country_catalog, cfg, table_name, warnings=[])
    out_csv = tables_dir / f"{table_name}.csv"
    write_csv_with_csvt(df, out_csv, cfg)

    if cfg["output"].get("write_tables_to_gpkg", True):
        write_table_to_gpkg(
            df=df,
            gpkg_path=gpkg_path,
            table_name=table_name,
            pk=id_field,
            create_index=bool(cfg["output"].get("create_join_indexes", True)),
        )

    return {
        "tabla": table_name,
        "filas": len(df),
        "campos_incluyendo_pk": len(df.columns),
        "cardinalidad": "referencia_3nf",
        "ruta_csv": str(out_csv.relative_to(ROOT)),
        "en_gpkg": bool(cfg["output"].get("write_tables_to_gpkg", True)),
    }

def sql_identifier(name: str) -> str:
    """Quote an SQLite identifier safely."""
    return '"' + str(name).replace('"', '""') + '"'



def write_proposed_homologations_to_gpkg(
    cfg: dict[str, Any],
    gpkg_path: Path,
    tables: dict[str, pd.DataFrame],
) -> None:
    """Escribe catálogos compartidos y homologaciones N:1 con PK/FK reales."""
    homologations = proposed_homologations_config(cfg)
    source_tables = cfg["source_class_catalog"]["tables"]

    with sqlite3.connect(gpkg_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        mapping_tables = list(dict.fromkeys(
            hom["mapping_table"] for hom in homologations.values()
        ))
        target_tables = list(dict.fromkeys(
            hom["target_table"] for hom in homologations.values()
        ))

        for table_name in mapping_tables:
            conn.execute(f"DROP TABLE IF EXISTS {sql_identifier(table_name)}")
        for table_name in reversed(target_tables):
            conn.execute(f"DROP TABLE IF EXISTS {sql_identifier(table_name)}")

        all_names = mapping_tables + target_tables
        placeholders = ",".join("?" for _ in all_names)
        conn.execute(
            f"DELETE FROM gpkg_contents WHERE table_name IN ({placeholders})",
            all_names,
        )

        # Crear cada catálogo propuesto una sola vez, de padre a hijo.
        target_specs: dict[str, dict[str, Any]] = {}
        for hom in homologations.values():
            target_specs.setdefault(hom["target_table"], hom)

        for target_table, hom in sorted(
            target_specs.items(), key=lambda item: int(item[1]["target_level"])
        ):
            target_field = hom["target_id_field"]
            label_field = hom["target_label_field"]
            parent_field = hom.get("parent_target_id_field")
            parent_table = hom.get("parent_target_table")
            target_df = tables[target_table]

            definitions = [
                f"{sql_identifier(target_field)} INTEGER PRIMARY KEY NOT NULL",
                f"{sql_identifier(label_field)} TEXT NOT NULL",
            ]
            if parent_field:
                definitions.extend([
                    f"{sql_identifier(parent_field)} INTEGER NOT NULL",
                    f"FOREIGN KEY ({sql_identifier(parent_field)}) "
                    f"REFERENCES {sql_identifier(parent_table)} "
                    f"({sql_identifier(parent_field)})",
                ])

            conn.execute(
                f"CREATE TABLE {sql_identifier(target_table)} "
                f"({', '.join(definitions)})"
            )
            insert_fields = [target_field, label_field]
            if parent_field:
                insert_fields.append(parent_field)
            conn.executemany(
                f"INSERT INTO {sql_identifier(target_table)} "
                f"({', '.join(sql_identifier(f) for f in insert_fields)}) "
                f"VALUES ({', '.join('?' for _ in insert_fields)})",
                [
                    tuple(
                        int(row[f]) if f != label_field else str(row[f])
                        for f in insert_fields
                    )
                    for _, row in target_df.iterrows()
                ],
            )
            register_attribute_table_in_gpkg(
                conn,
                table_name=target_table,
                description=(
                    f"Catálogo de nivel {hom['target_level']} de la "
                    "clasificación propuesta."
                ),
            )

        # Crear cada regla N:1. La llave de origen es PK y FK.
        for hom_name, hom in homologations.items():
            source_level = int(hom["source_level"])
            source_table = source_tables[f"nivel_{source_level}"]
            source_field = hom["source_id_field"]
            target_table = hom["target_table"]
            target_field = hom["target_id_field"]
            mapping_table = hom["mapping_table"]
            mapping_df = tables[mapping_table]

            conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS "
                f"{sql_identifier(f'uq_{source_table}_{source_field}')} "
                f"ON {sql_identifier(source_table)} "
                f"({sql_identifier(source_field)})"
            )
            conn.execute(
                f"CREATE TABLE {sql_identifier(mapping_table)} ("
                f"{sql_identifier(source_field)} INTEGER PRIMARY KEY NOT NULL, "
                f"{sql_identifier(target_field)} INTEGER NOT NULL, "
                f"FOREIGN KEY ({sql_identifier(source_field)}) "
                f"REFERENCES {sql_identifier(source_table)} "
                f"({sql_identifier(source_field)}), "
                f"FOREIGN KEY ({sql_identifier(target_field)}) "
                f"REFERENCES {sql_identifier(target_table)} "
                f"({sql_identifier(target_field)})"
                f")"
            )
            conn.executemany(
                f"INSERT INTO {sql_identifier(mapping_table)} "
                f"({sql_identifier(source_field)}, {sql_identifier(target_field)}) "
                "VALUES (?, ?)",
                [
                    (int(row[source_field]), int(row[target_field]))
                    for _, row in mapping_df.iterrows()
                ],
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS "
                f"{sql_identifier(f'idx_{mapping_table}_{target_field}')} "
                f"ON {sql_identifier(mapping_table)} "
                f"({sql_identifier(target_field)})"
            )
            role = hom.get("role", "general")
            register_attribute_table_in_gpkg(
                conn,
                table_name=mapping_table,
                description=(
                    f"Homologación N:1 ({role}) desde {source_field} de origen "
                    f"hacia {target_field}."
                ),
            )

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError(
                "Se detectaron violaciones de FK en las tablas propuestas: "
                f"{violations[:20]}"
            )
        conn.commit()

def write_proposed_homologation_outputs(
    cfg: dict[str, Any],
    tables_dir: Path,
    gpkg_path: Path,
) -> list[dict[str, Any]]:
    """Escribe todos los catálogos propuestos y tablas puente."""
    summaries: list[dict[str, Any]] = []
    homologations = proposed_homologations_config(cfg)
    tables = proposed_homologation_tables(cfg)

    target_names = {
        hom["target_table"] for hom in homologations.values()
    }
    mapping_names = {
        hom["mapping_table"] for hom in homologations.values()
    }

    for table_name, df in tables.items():
        df = coerce_types(df, cfg, table_name, warnings=[])
        tables[table_name] = df
        out_csv = tables_dir / f"{table_name}.csv"
        write_csv_with_csvt(df, out_csv, cfg)

        if table_name in target_names:
            cardinality = "referencia_3nf"
        elif table_name in mapping_names:
            hom_for_table = next(
                hom for hom in homologations.values()
                if hom["mapping_table"] == table_name
            )
            cardinality = (
                f"{homologation_cardinality(hom_for_table)}_origen_a_propuesta"
            )
        else:
            cardinality = "propuesta"

        summaries.append(
            {
                "tabla": table_name,
                "filas": len(df),
                "campos_incluyendo_pk": len(df.columns),
                "cardinalidad": cardinality,
                "ruta_csv": str(out_csv.relative_to(ROOT)),
                "en_gpkg": bool(
                    cfg["output"].get("write_tables_to_gpkg", True)
                ),
            }
        )

    if cfg["output"].get("write_tables_to_gpkg", True):
        write_proposed_homologations_to_gpkg(
            cfg=cfg,
            gpkg_path=gpkg_path,
            tables=tables,
        )

    return summaries



def build_xy_homologacion_final(
    gdf: gpd.GeoDataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Materializa la homologación final para revisión mediante un único join.

    La tabla resultante no sustituye las tablas normalizadas. Es una vista
    materializada 1:1 por ``xy_group_id`` que resuelve internamente:

    - nivel 1: excepción por ``id_2`` cuando exista;
    - nivel 1: regla general por ``id_1`` en los demás casos;
    - nivel 0: padre del ``id_1_propuesta`` final.

    Nota metodológica: el nivel 0 propuesto no debe dominar la excepción
    de nivel 2. Esto permite casos como 443, que proviene de 40/44 en la
    leyenda documental, pero se homologa hacia 2/25 en la leyenda operativa.
    """
    pk = pk_field(cfg)
    homologations = proposed_homologations_config(cfg)
    tables = proposed_homologation_tables(cfg)

    level0_candidates = [
        hom for hom in homologations.values()
        if int(hom["target_level"]) == 0 and hom.get("role", "general") == "general"
    ]
    level1_general_candidates = [
        (name, hom) for name, hom in homologations.items()
        if int(hom["target_level"]) == 1
        and hom.get("role", "general") == "general"
    ]
    level1_override_candidates = [
        (name, hom) for name, hom in homologations.items()
        if int(hom["target_level"]) == 1 and hom.get("role") == "override"
    ]

    if len(level0_candidates) != 1:
        raise ValueError(
            "Debe existir exactamente una homologación general hacia nivel 0."
        )
    if len(level1_general_candidates) != 1:
        raise ValueError(
            "Debe existir exactamente una homologación general hacia nivel 1."
        )
    if len(level1_override_candidates) != 1:
        raise ValueError(
            "Debe existir exactamente una homologación override hacia nivel 1."
        )

    hom0 = level0_candidates[0]
    hom1_name, hom1 = level1_general_candidates[0]
    _, hom1_override = level1_override_candidates[0]

    if hom1_override.get("fallback_homologation") != hom1_name:
        raise ValueError(
            "La excepción de nivel 1 debe apuntar a la homologación general "
            "mediante fallback_homologation."
        )

    required_fields = {
        pk,
        hom0["source_id_field"],
        hom1["source_id_field"],
        hom1_override["source_id_field"],
    }
    missing_fields = sorted(required_fields - set(gdf.columns))
    if missing_fields:
        raise ValueError(
            "No se puede construir xy_homologacion_final. Faltan campos: "
            f"{missing_fields}"
        )

    def mapping_dict(hom: dict[str, Any]) -> dict[int, int]:
        source_field = hom["source_id_field"]
        target_field = hom["target_id_field"]
        mapping_df = tables[hom["mapping_table"]]
        return dict(
            mapping_df[[source_field, target_field]]
            .astype(int)
            .itertuples(index=False, name=None)
        )

    map0 = mapping_dict(hom0)
    map1 = mapping_dict(hom1)
    map1_override = mapping_dict(hom1_override)

    id0_general = (
        gdf[hom0["source_id_field"]].map(map0).astype("Int64")
    )
    id1_general = (
        gdf[hom1["source_id_field"]].map(map1).astype("Int64")
    )
    id1_excepcion = (
        gdf[hom1_override["source_id_field"]]
        .map(map1_override)
        .astype("Int64")
    )
    id1_propuesta = id1_excepcion.combine_first(id1_general).astype("Int64")

    catalog0 = tables[hom0["target_table"]]
    catalog1 = tables[hom1["target_table"]]

    # El id_0_propuesta final se deriva desde el padre de id_1_propuesta
    # final. Así, una excepción de nivel 2 puede cruzar dominio sin dejar
    # una contradicción jerárquica en xy_homologacion_final.
    parent_field = hom1.get("parent_target_id_field")
    if parent_field and parent_field in catalog1.columns:
        parent_map = dict(
            zip(
                catalog1[hom1["target_id_field"]].astype(int),
                catalog1[parent_field].astype(int),
            )
        )
        id0_from_level1 = id1_propuesta.map(parent_map).astype("Int64")
        cross_domain = (
            id0_general.notna()
            & id0_from_level1.notna()
            & (id0_general != id0_from_level1)
        )
        if cross_domain.any():
            logging.info(
                "xy_homologacion_final: %s registros cruzan dominio nivel 0 "
                "por excepción o regla de nivel 1; se usa el padre de "
                "id_1_propuesta final.",
                int(cross_domain.sum()),
            )
        id0_propuesta = id0_from_level1.combine_first(id0_general).astype("Int64")
    else:
        id0_propuesta = id0_general
    label0_map = dict(
        zip(
            catalog0[hom0["target_id_field"]].astype(int),
            catalog0[hom0["target_label_field"]].astype(str),
        )
    )
    label1_map = dict(
        zip(
            catalog1[hom1["target_id_field"]].astype(int),
            catalog1[hom1["target_label_field"]].astype(str),
        )
    )

    out = pd.DataFrame(
        {
            pk: gdf[pk].astype("string"),
            "id_0_propuesta": id0_propuesta,
            "nivel_0_propuesta": id0_propuesta.map(label0_map).astype("string"),
            "id_1_propuesta": id1_propuesta,
            "nivel_1_propuesta": id1_propuesta.map(label1_map).astype("string"),
        }
    )

    if out[pk].isna().any() or out[pk].duplicated().any():
        raise ValueError(
            f"La tabla final debe ser 1:1 y única por {pk}."
        )

    missing_final = out[
        [
            "id_0_propuesta",
            "nivel_0_propuesta",
            "id_1_propuesta",
            "nivel_1_propuesta",
        ]
    ].isna().any(axis=1)
    n_missing = int(missing_final.sum())
    if n_missing:
        msg = (
            f"xy_homologacion_final contiene {n_missing} registros sin "
            "homologación completa."
        )
        if cfg["validation"].get(
            "require_complete_final_homologation", True
        ):
            raise ValueError(msg)
        logging.warning(msg)

    # Comprobar coherencia entre nivel 0 final y el padre del nivel 1 final.
    # Como id_0_propuesta se deriva arriba desde id_1_propuesta, esta
    # validación debería fallar solo si el catálogo propuesto está mal definido.
    if parent_field and parent_field in catalog1.columns:
        parent_from_level1 = id1_propuesta.map(parent_map).astype("Int64")
        hierarchy_error = (
            id0_propuesta.notna()
            & parent_from_level1.notna()
            & (id0_propuesta != parent_from_level1)
        )
        if hierarchy_error.any():
            raise ValueError(
                "La homologación final contiene inconsistencias entre "
                "id_0_propuesta e id_1_propuesta."
            )

    return out


def write_xy_homologacion_final_outputs(
    gdf: gpd.GeoDataFrame,
    cfg: dict[str, Any],
    tables_dir: Path,
    gpkg_path: Path,
) -> dict[str, Any]:
    """Escribe la tabla final 1:1 usada para un único join en QGIS."""
    table_name = cfg["output"].get(
        "homologation_final_table", "xy_homologacion_final"
    )
    pk = pk_field(cfg)
    df = build_xy_homologacion_final(gdf=gdf, cfg=cfg)
    df = coerce_types(df, cfg, table_name, warnings=[])

    out_csv = tables_dir / f"{table_name}.csv"
    if cfg["output"].get("write_homologation_final_csv", True):
        write_csv_with_csvt(df, out_csv, cfg)

    write_to_gpkg = bool(cfg["output"].get("write_tables_to_gpkg", True))
    if write_to_gpkg:
        with sqlite3.connect(gpkg_path) as conn:
            q_table = sql_identifier(table_name)
            q_pk = sql_identifier(pk)
            conn.execute(f"DROP TABLE IF EXISTS {q_table}")
            conn.execute(
                "DELETE FROM gpkg_contents WHERE table_name = ?",
                (table_name,),
            )
            df.to_sql(table_name, conn, if_exists="replace", index=False)
            register_attribute_table_in_gpkg(
                conn,
                table_name=table_name,
                description=(
                    "Tabla 1:1 por xy_group_id con códigos y labels "
                    "homologados finales para un único join en QGIS."
                ),
            )
            conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS "
                f"{sql_identifier(f'uq_{table_name}_{pk}')} "
                f"ON {q_table} ({q_pk})"
            )
            conn.commit()

    return {
        "tabla": table_name,
        "filas": len(df),
        "campos_incluyendo_pk": len(df.columns),
        "cardinalidad": "1:1_revision_qgis",
        "ruta_csv": (
            (
                str(out_csv.relative_to(ROOT))
                if out_csv.is_relative_to(ROOT)
                else str(out_csv)
            )
            if cfg["output"].get("write_homologation_final_csv", True)
            else ""
        ),
        "en_gpkg": write_to_gpkg,
    }

def write_metadata_to_gpkg(metadata_dir: Path, gpkg_path: Path) -> None:
    metadata_tables = {
        "campo_mapeo": metadata_dir / "campo_mapeo.csv",
        "field_audit": metadata_dir / "field_audit.csv",
        "table_summary": metadata_dir / "table_summary.csv",
        "column_name_normalization": metadata_dir / "column_name_normalization.csv",
        "validacion_dominante_vs_valores": metadata_dir / "validacion_dominante_vs_valores.csv",
        "normalization_source": metadata_dir / "normalization_source.csv",
    }

    with sqlite3.connect(gpkg_path) as conn:
        for table_name, csv_path in metadata_tables.items():
            if not csv_path.exists():
                continue

            df = pd.read_csv(csv_path, encoding="utf-8-sig", low_memory=False)
            df.to_sql(table_name, conn, if_exists="replace", index=False)

            register_attribute_table_in_gpkg(
                conn,
                table_name=table_name,
                description="Tabla de metadata de la normalización A3.",
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
    runtime_source = cfg.get("_runtime_source", {})
    raw_trace_map = runtime_source.get("traceability_field_map", {})

    def add_pk_once() -> None:
        nonlocal documented_pk
        if documented_pk:
            return
        rows.append({
            "campo_original": original_lookup.get(pk, pk),
            "campo_normalizado": pk,
            "tabla_destino": "xy_point / csv_tematicos",
            "tipo_dato_propuesto": infer_field_type(pk, cfg),
            "accion": "pk_join",
            "observacion": (
                "Llave natural de Actividad 1. Se conserva como PK lógica en "
                "xy_point y como campo de join en cada CSV temático."
            ),
        })
        documented_pk = True

    for table_name, table_def in schema_tables(cfg).items():
        add_pk_once()
        for field in table_def["fields"]:
            if field == pk:
                continue
            source_note = ""
            source_field = field
            action = "conservar_en_gpkg" if table_name == "xy_point" else "separar_por_tema"
            if field == "source_key":
                source_field = "Configuración inputs.source_key"
                source_note = " Identificador constante de la entrada procesada."
                action = "generar_identificador_fuente"
            elif table_name == "xy_trazabilidad_fuente" and field in raw_trace_map:
                raw_source = raw_trace_map.get(field)
                if raw_source:
                    source_field = normalize_name(raw_source)
                    source_note = f" Estandarizado desde {source_field}."
                    action = "estandarizar_trazabilidad_entregada"
                else:
                    source_field = "No disponible en el GeoPackage final"
                    source_note = " Se conserva nulo y se documenta la limitación."
                    action = "documentar_trazabilidad_no_disponible"
            elif table_name == "xy_point" and field in class_fk_sources(cfg):
                class_source = class_fk_sources(cfg)[field]
                source_field = class_source.get("source_id") or class_source["dominante"]
                source_note = (
                    f" Copiado desde {source_field} y contrastado con "
                    f"{class_source['dominante']}."
                )
                action = "copiar_fk_clase_a1_entregada"
            elif field in country_source_specs(cfg):
                source_field = country_source_specs(cfg)[field]["source_field"]
                source_note = (
                    f" FK por rol derivada desde {source_field}; "
                    f"referencia {country_normalization_config(cfg)['catalog_table']}."
                )
                action = "extraer_fk_pais_desde_texto"
            if action == "documentar_trazabilidad_no_disponible":
                base_observation = "Campo estándar sin equivalente disponible en la salida final."
            elif action == "generar_identificador_fuente":
                base_observation = "Campo de procedencia generado desde la configuración."
            else:
                base_observation = "Campo existente redistribuido sin crear atributos analíticos nuevos."
            rows.append({
                "campo_original": original_lookup.get(source_field, source_field),
                "campo_normalizado": field,
                "tabla_destino": table_name,
                "tipo_dato_propuesto": infer_field_type(field, cfg),
                "accion": action,
                "observacion": base_observation + source_note,
            })

    for id_field, info in class_fk_sources(cfg).items():
        for source_kind in ["valores"]:
            source = info[source_kind]
            rows.append({
                "campo_original": original_lookup.get(source, source),
                "campo_normalizado": source,
                "tabla_destino": "no_exportado",
                "tipo_dato_propuesto": "SOURCE_ONLY",
                "accion": "usar_para_fk_y_validacion",
                "observacion": (
                    f"Campo usado para calcular/validar {id_field}. No se "
                    "exporta porque duplica información de clase."
                ),
            })

    country_cfg = country_normalization_config(cfg)
    if country_cfg:
        rows.append({
            "campo_original": "Configuración normalization.country.rows",
            "campo_normalizado": country_cfg["id_field"],
            "tabla_destino": country_cfg["catalog_table"],
            "tipo_dato_propuesto": infer_field_type(country_cfg["id_field"], cfg),
            "accion": "pk_catalogo_pais",
            "observacion": "PK estable del único catálogo normalizado de países.",
        })
        rows.append({
            "campo_original": "Configuración normalization.country.rows",
            "campo_normalizado": country_cfg["name_field"],
            "tabla_destino": country_cfg["catalog_table"],
            "tipo_dato_propuesto": infer_field_type(country_cfg["name_field"], cfg),
            "accion": "label_catalogo_pais",
            "observacion": "Nombre de país almacenado una sola vez en el catálogo normalizado.",
        })

    for table_name, df in source_catalog_tables(cfg).items():
        for field in df.columns:
            rows.append({
                "campo_original": "Tabla 1 - Sistema de clasificación de origen",
                "campo_normalizado": field,
                "tabla_destino": table_name,
                "tipo_dato_propuesto": infer_field_type(field, cfg),
                "accion": "tabla_referencia_3nf",
                "observacion": (
                    "Tabla de referencia separada por nivel para eliminar "
                    "dependencias transitivas entre id_0, id_1 e id_2."
                ),
            })

    homologations = proposed_homologations_config(cfg)
    proposed_tables = proposed_homologation_tables(cfg)
    documented_targets: set[str] = set()

    for hom_name, hom in homologations.items():
        source_level = int(hom["source_level"])
        target_level = int(hom["target_level"])
        source_field = hom["source_id_field"]
        target_field = hom["target_id_field"]
        mapping_table = hom["mapping_table"]
        role = hom.get("role", "general")

        for field in proposed_tables[mapping_table].columns:
            if field == source_field:
                action = f"pk_fk_clase_origen_nivel_{source_level}"
                observation = (
                    f"PK de la regla {role} y FK hacia "
                    f"clase_origen_nivel_{source_level}.{source_field}."
                )
            else:
                action = f"fk_clase_propuesta_nivel_{target_level}"
                observation = (
                    f"FK hacia {hom['target_table']}.{target_field}. "
                    "Puede repetirse para permitir varias clases de origen por destino."
                )
            rows.append({
                "campo_original": "Propuesta de clasificación llave",
                "campo_normalizado": field,
                "tabla_destino": mapping_table,
                "tipo_dato_propuesto": infer_field_type(field, cfg),
                "accion": action,
                "observacion": observation,
            })

        target_table = hom["target_table"]
        if target_table in documented_targets:
            continue
        documented_targets.add(target_table)
        for field in proposed_tables[target_table].columns:
            if field == target_field:
                action = f"pk_clase_propuesta_nivel_{target_level}"
                observation = "PK del catálogo propuesto."
            elif field == hom["target_label_field"]:
                action = f"label_clase_propuesta_nivel_{target_level}"
                observation = "Etiqueta almacenada únicamente en el catálogo propuesto."
            elif field == hom.get("parent_target_id_field"):
                action = "fk_jerarquia_clase_propuesta"
                observation = f"FK hacia {hom['parent_target_table']}."
            else:
                action = "campo_propuesta"
                observation = "Campo de la clasificación propuesta."
            rows.append({
                "campo_original": "Propuesta de clasificación llave",
                "campo_normalizado": field,
                "tabla_destino": target_table,
                "tipo_dato_propuesto": infer_field_type(field, cfg),
                "accion": action,
                "observacion": observation,
            })

    final_table = cfg["output"].get(
        "homologation_final_table", "xy_homologacion_final"
    )
    final_fields = [
        pk,
        "id_0_propuesta",
        "nivel_0_propuesta",
        "id_1_propuesta",
        "nivel_1_propuesta",
    ]
    for field in final_fields:
        rows.append({
            "campo_original": "Derivado de las reglas de homologación",
            "campo_normalizado": field,
            "tabla_destino": final_table,
            "tipo_dato_propuesto": infer_field_type(field, cfg),
            "accion": "vista_materializada_revision_qgis",
            "observacion": (
                "Campo materializado para permitir un único join por "
                f"{pk} en QGIS. No sustituye las tablas normalizadas."
            ),
        })

    return pd.DataFrame(rows)

def build_field_audit(cfg: dict[str, Any], input_fields: list[str]) -> pd.DataFrame:
    model_fields = set(expected_fields(cfg))
    required_sources = set(source_fields_required(cfg))
    source_only = source_only_fields(cfg)
    audit_only = audit_only_fields(cfg)

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
            if field == info.get("source_id"):
                used_to_build.append(f"xy_point.{id_field}")
            if field == info.get("dominante"):
                used_to_build.append(f"validacion_label_a1.{id_field}")
            if field == info.get("valores"):
                used_to_build.append(f"validacion_dominante_vs_valores.{id_field}")

        for target_field, source_field in traceability_field_map(cfg).items():
            if field == source_field:
                used_to_build.append(f"xy_trazabilidad_fuente.{target_field}")

        for canonical_field, alias_field in a1_alias_field_map(cfg).items():
            if field == alias_field:
                used_to_build.append(f"validacion_alias_a1.{canonical_field}")

        if field in model_fields:
            decision_modelo = "exportado_modelo"
        elif field in source_only:
            decision_modelo = "insumo_para_fk_o_validacion_no_exportado"
        elif field in audit_only:
            decision_modelo = "excluido_por_diseno_auditoria_scoring"
        else:
            decision_modelo = "extra_no_asignado"

        rows.append(
            {
                "campo": field,
                "en_salida_modelo": field in model_fields,
                "usado_como_fuente": field in source_only,
                "requerido": field in required_sources,
                "tablas_asignadas": ";".join(assigned_tables),
                "tablas_derivadas": ";".join(used_to_build),
                "decision_modelo": decision_modelo,
                "tipo_dato_propuesto": infer_field_type(field, cfg) if field in model_fields else "",
            }
        )

    return pd.DataFrame(rows)


def build_normalization_source_metadata(
    source_cfg: dict[str, Any],
    input_gpkg: Path,
    layer_used: str | None,
    gdf: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Documenta qué se recibió y qué limitaciones no puede resolver A3."""
    field_map = source_cfg.get("traceability_field_map", {})
    available = [field for field, source in field_map.items() if source]
    unavailable = [field for field, source in field_map.items() if not source]
    input_label = str(input_gpkg.relative_to(ROOT)) if input_gpkg.is_relative_to(ROOT) else str(input_gpkg)

    return pd.DataFrame(
        [
            {
                "source_key": source_cfg["source_key"],
                "input_gpkg": input_label,
                "input_layer": layer_used or "",
                "input_rows": len(gdf),
                "input_crs": str(gdf.crs),
                "expected_source_id": source_cfg.get("expected_source_id"),
                "expected_country": source_cfg.get("expected_country"),
                "class_id_policy": "usar_id_nivel_0_1_2_entregados",
                "score_policy": "preservar_scores_finales_entregados_sin_recalculo",
                "traceability_status": source_cfg.get(
                    "traceability_status", "parcial_desde_salida_final"
                ),
                "traceability_standard_fields_available": "|".join(available),
                "traceability_standard_fields_unavailable": "|".join(unavailable),
                "intermediate_data_available": False,
                "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        ]
    )



def write_readme(out_dir: Path, cfg: dict[str, Any]) -> None:
    pk = pk_field(cfg)
    source_cfg = cfg.get("_runtime_source", {})
    source_key = source_cfg.get("source_key", "fuente_no_definida")
    source_tables = cfg["source_class_catalog"]["tables"]
    homologations = proposed_homologations_config(cfg)
    proposed_tables = proposed_homologation_tables(cfg)

    sections: list[str] = []
    for hom_name, hom in homologations.items():
        mapping_df = proposed_tables[hom["mapping_table"]]
        target_df = proposed_tables[hom["target_table"]]
        labels = dict(zip(
            target_df[hom["target_id_field"]].astype(int),
            target_df[hom["target_label_field"]].astype(str),
        ))
        mapping_lines = "\n".join(
            f"- `{int(row[hom['source_id_field']])}` -> "
            f"`{int(row[hom['target_id_field']])}` "
            f"({labels[int(row[hom['target_id_field']])]})"
            for _, row in mapping_df.iterrows()
        )
        role = hom.get("role", "general")
        priority_note = ""
        if hom.get("fallback_homologation"):
            priority_note = (
                f"\nEsta tabla contiene excepciones y tiene prioridad sobre "
                f"`{hom['fallback_homologation']}`.\n"
            )
        sections.append(
            f"""## {hom_name}

Rol: **{role}**. Cardinalidad: **N:1**.

- `{hom['source_id_field']}` es PK/FK de `{hom['mapping_table']}`.
- `{hom['target_id_field']}` es FK hacia `{hom['target_table']}`.
{priority_note}
{mapping_lines}
"""
        )

    readme = f"""# Actividad 3 — Normalización de la fuente `{source_key}`

## Criterio

La salida final auditada de la nueva fuente se reorganiza sin crear atributos
analíticos nuevos. Se utiliza el mismo modelo relacional de A2.1 mediante un
código A3 independiente.

Los IDs `id_nivel_0`, `id_nivel_1` e `id_nivel_2` entregados se copian a
`xy_point.id_0`, `xy_point.id_1` y `xy_point.id_2`, respectivamente, y se
contrastan con los labels A1. Los scores finales se preservan sin recalcularlos.

La tabla `xy_trazabilidad_fuente` conserva la clase original disponible y la
clase A1 entregada. No se reconstruyen indicadores de homologación que no estén
presentes en el GeoPackage final.

Los identificadores propuestos no se almacenan en `xy_point`; se resuelven
mediante tablas normalizadas de homologación.

Los campos derivados del scoring, de confiabilidad y de auditoría de fuente
que ya están resumidos por otros scores no se duplican en el modelo relacional.
Se documentan en metadata/field_audit.csv como
`excluido_por_diseno_auditoria_scoring`.

## Llave central

`{pk}`

## País normalizado

Los nombres de país observados en los campos fuente se almacenan una sola vez en `pais`.
Las tablas del modelo conservan únicamente FKs por rol:

- `xy_point.id_pais_grupo` -> `pais.id_pais_grupo`
- `xy_core.id_pais_dominante` -> `pais.id_pais_grupo`

## Clases de origen en `xy_point`

- `id_0`
- `id_1`
- `id_2`

Los labels se consultan mediante:

- `xy_point.id_0` -> `{source_tables['nivel_0']}.id_0`
- `xy_point.id_1` -> `{source_tables['nivel_1']}.id_1`
- `xy_point.id_2` -> `{source_tables['nivel_2']}.id_2`

## Regla final de homologación

El nivel 1 propuesto se obtiene con una regla de prioridad determinista:

1. buscar `id_2` en `homologacion_nivel_2_excepcion_nivel_1_propuesta`;
2. cuando no exista excepción, buscar `id_1` en
   `homologacion_nivel_1_origen_propuesta`.

Equivalente lógico:

`id_1_propuesta_final = COALESCE(excepcion.id_1_propuesta, general.id_1_propuesta)`

El nivel 0 propuesto final se deriva del padre de `id_1_propuesta_final`
en `clase_propuesta_nivel_1`. La regla `id_0 -> id_0_propuesta` se conserva
como tabla normalizada y respaldo, pero no domina las excepciones de nivel 2.

Equivalente lógico:

`id_0_propuesta_final = parent(id_1_propuesta_final)`

De esta manera, cada punto recibe una sola clase propuesta y se permiten
excepciones controladas que cruzan dominio, como `443 -> 25`, sin romper la
coherencia jerárquica final. Todas las tablas de homologación conservan
cardinalidad N:1.

{chr(10).join(sections)}

## Revisión en QGIS con un único join

El proceso materializa la tabla `{cfg['output'].get('homologation_final_table', 'xy_homologacion_final')}` con:

- `{pk}`
- `id_0_propuesta`
- `nivel_0_propuesta`
- `id_1_propuesta`
- `nivel_1_propuesta`

En QGIS solo se requiere:

`xy_point.{pk} -> {cfg['output'].get('homologation_final_table', 'xy_homologacion_final')}.{pk}`

## Salidas

- `gpkg/{cfg['output']['spatial_gpkg']}`
- `tables/*.csv`
- `metadata/*.csv`
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

def run_source(
    base_cfg: dict[str, Any],
    source_cfg: dict[str, Any],
    config_path: Path,
) -> dict[str, Any]:
    """Normaliza una fuente; el orquestador llama esta función para cada entrada."""
    cfg = deepcopy(base_cfg)
    cfg = apply_score_final_policy(cfg)
    source_cfg = deepcopy(source_cfg)
    source_key = str(source_cfg["source_key"])
    cfg["input"] = source_cfg
    cfg["_runtime_source"] = source_cfg

    spatial_pattern = cfg["output"].get(
        "spatial_gpkg_pattern", "{source_key}_normalizado.gpkg"
    )
    cfg["output"]["spatial_gpkg"] = spatial_pattern.format(source_key=source_key)

    activity = f"{cfg.get('activity', 'a3_normalizacion_nuevas_fuentes')}_{source_key}"
    log_dir = as_project_path(cfg["output"].get("logs_dir", LOG))
    log_file = setup_logging(log_dir, activity)

    logging.info("ROOT: %s", ROOT)
    logging.info("CONFIG: %s", config_path)
    logging.info("SOURCE_KEY: %s", source_key)
    logging.info("LOG: %s", log_file)

    input_gpkg = as_project_path(cfg["input"]["gpkg"])
    input_layer = cfg["input"].get("layer")

    processed_root = as_project_path(cfg["output"]["processed_dir"])
    processed_dir = processed_root / source_key
    reports_dir = as_project_path(cfg["output"]["reports_dir"])

    gpkg_dir = processed_dir / cfg["output"]["gpkg_dir"]
    tables_dir = processed_dir / cfg["output"]["tables_dir"]
    metadata_dir = processed_dir / cfg["output"]["metadata_dir"]

    overwrite = bool(cfg["output"].get("overwrite", False))

    if processed_dir.exists() and overwrite:
        require_output_child(processed_dir, processed_root)
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
    gdf = adapt_source_input(
        gdf=gdf,
        source_cfg=source_cfg,
        cfg=cfg,
        warnings=warnings,
    )

    pk = pk_field(cfg)

    input_fields_raw = [field for field in gdf.columns if field != "geometry"]
    model_fields = expected_fields(cfg)
    model_analytic_fields = analytic_fields(cfg)
    required_source_fields = source_fields_required(cfg)
    source_only = source_only_fields(cfg)

    missing = [field for field in required_source_fields if field not in input_fields_raw]
    all_extra_fields = [
        field for field in input_fields_raw
        if field not in required_source_fields
        and field not in model_fields
        and field not in source_only
    ]
    audit_only_extra = [
        field for field in all_extra_fields
        if extra_field_policy(field, cfg) == "excluido_por_diseno_auditoria_scoring"
    ]
    extra = [
        field for field in all_extra_fields
        if extra_field_policy(field, cfg) == "extra_no_asignado"
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

    if audit_only_extra:
        logging.info(
            "Campos derivados de auditoría/scoring excluidos por diseño del modelo 3NF: %s",
            audit_only_extra,
        )

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

    # Validate all reference and homologation tables before processing.
    source_catalog_tables(cfg)
    proposed_homologation_tables(cfg)

    # Derive only the source class FKs stored in xy_point.
    gdf = derive_class_fks(gdf, cfg, warnings)

    # Construir catálogo normalizado de países y derivar FKs por rol.
    country_catalog = build_country_catalog_table(gdf, cfg)
    gdf = derive_country_fks(gdf, cfg, country_catalog, warnings)

    # Validar todas las homologaciones sin añadir FKs propuestas a xy_point.
    proposed_usage_counts = validate_observed_proposed_homologations(
        gdf=gdf,
        cfg=cfg,
        warnings=warnings,
    )

    # Validar duplicidad dominante/valores.
    validation_df = validate_dominante_vs_valores(gdf, cfg)

    if not validation_df.empty:
        mismatches = int((~validation_df["dominante_igual_a_valores"]).sum())
        dominant_between_multiple = int(
            (validation_df["tipo_diferencia"] == "dominante_entre_multiples_valores").sum()
        )
        critical_dominant_mismatches = int(
            validation_df["tipo_diferencia"].isin(
                [
                    "dominante_fuera_de_valores",
                    "dominante_sin_valores",
                    "sin_dominante_con_valores",
                ]
            ).sum()
        )
    else:
        mismatches = 0
        dominant_between_multiple = 0
        critical_dominant_mismatches = 0

    if critical_dominant_mismatches > 0:
        msg = (
            f"Validación dominante vs valores: {critical_dominant_mismatches} "
            "filas-nivel tienen una diferencia crítica "
            "(dominante fuera de valores, dominante sin valores o valores sin dominante). "
            "Revise metadata/validacion_dominante_vs_valores.csv."
        )
        if cfg["validation"].get("fail_on_dominante_valores_mismatch", False):
            raise ValueError(msg)
        warnings.append(msg)
    elif mismatches > 0:
        logging.info(
            "Validación dominante vs valores: %s filas-nivel no son equivalencia estricta; "
            "%s corresponden a dominante incluido dentro de múltiples valores del grupo XY. "
            "Se documentan en metadata/validacion_dominante_vs_valores.csv sin tratarse como error.",
            mismatches,
            dominant_between_multiple,
        )

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
    # 3b. Catálogo normalizado de países
    # --------------------------------------------------------
    country_summary = write_country_catalog_outputs(
        cfg=cfg,
        tables_dir=tables_dir,
        gpkg_path=out_gpkg,
        country_catalog=country_catalog,
    )
    if country_summary is not None:
        table_summary.append(country_summary)

    # --------------------------------------------------------
    # 4. Catálogos propuestos y homologaciones de niveles 0 y 1
    # --------------------------------------------------------
    proposed_summaries = write_proposed_homologation_outputs(
        cfg=cfg,
        tables_dir=tables_dir,
        gpkg_path=out_gpkg,
    )
    table_summary.extend(proposed_summaries)

    # --------------------------------------------------------
    # 5. Tabla final para un único join en QGIS
    # --------------------------------------------------------
    final_homologation_summary = write_xy_homologacion_final_outputs(
        gdf=gdf,
        cfg=cfg,
        tables_dir=tables_dir,
        gpkg_path=out_gpkg,
    )
    table_summary.append(final_homologation_summary)
    logging.info(
        "Tabla final de homologación creada: %s",
        final_homologation_summary["tabla"],
    )

    # --------------------------------------------------------
    # 6. Metadata
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

    source_metadata = build_normalization_source_metadata(
        source_cfg=source_cfg,
        input_gpkg=input_gpkg,
        layer_used=layer_used,
        gdf=gdf,
    )
    source_metadata.to_csv(
        metadata_dir / "normalization_source.csv",
        index=False,
        encoding="utf-8-sig",
    )

    if cfg["output"].get("write_tables_to_gpkg", True):
        write_metadata_to_gpkg(metadata_dir=metadata_dir, gpkg_path=out_gpkg)
        logging.info("Tablas de metadata añadidas al GPKG.")

    write_readme(processed_dir, cfg)

    # --------------------------------------------------------
    # 7. Reporte
    # --------------------------------------------------------
    report_lines: list[str] = []

    report_lines.append("Actividad 3 — Normalización de auditorías y nuevas fuentes")
    report_lines.append("=" * 72)
    report_lines.append(f"Fecha de proceso: {datetime.now().isoformat(timespec='seconds')}")
    report_lines.append(f"ROOT: {ROOT}")
    report_lines.append(f"CONFIG: {config_path}")
    report_lines.append(f"Fuente: {source_key}")
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
    report_lines.append(
        "Campos derivados de auditoría/scoring excluidos por diseño: "
        f"{len(audit_only_extra)}"
    )

    if missing:
        report_lines.append(f"Lista de faltantes: {missing}")
    if extra:
        report_lines.append(f"Lista de extra no asignados: {extra}")
    if audit_only_extra:
        report_lines.append(
            "Lista de campos excluidos por diseño: "
            f"{audit_only_extra}"
        )

    report_lines.append("")
    report_lines.append("Validación de llave")
    report_lines.append("-" * 72)
    report_lines.append(f"{pk} nulos: {n_null_pk}")
    report_lines.append(f"{pk} duplicados: {n_dup_pk}")
    report_lines.append("")
    report_lines.append("Normalización de países y clases")
    report_lines.append("-" * 72)
    report_lines.append("xy_point guarda las FKs de país y clase: id_pais_grupo, id_0, id_1, id_2.")
    report_lines.append("xy_core guarda id_pais_dominante; los nombres de país quedan solo en pais.")
    report_lines.append(
        "id_0_propuesta e id_1_propuesta no se almacenan en xy_point; se resuelven mediante reglas N:1."
    )
    report_lines.append("Los labels de origen quedan solo en sus tablas de referencia:")
    for table_name in cfg["source_class_catalog"]["tables"].values():
        report_lines.append(f"- {table_name}")

    homologations = proposed_homologations_config(cfg)
    proposed_tables = proposed_homologation_tables(cfg)
    for hom_name, hom in homologations.items():
        mapping_df = proposed_tables[hom["mapping_table"]]
        target_df = proposed_tables[hom["target_table"]]
        labels = dict(
            zip(
                target_df[hom["target_id_field"]].astype(int),
                target_df[hom["target_label_field"]].astype(str),
            )
        )

        report_lines.append(
            f"Homologación {hom.get('role', 'general')} de nivel "
            f"{hom['target_level']} desde {hom['source_id_field']} "
            f"(N:1):"
        )
        for _, row in mapping_df.iterrows():
            source_id = int(row[hom["source_id_field"]])
            target_id = int(row[hom["target_id_field"]])
            report_lines.append(
                f"- {hom['source_id_field']} {source_id} -> "
                f"{hom['target_id_field']} {target_id} "
                f"({labels[target_id]})"
            )
        source_ids = class_lookup(cfg, int(hom["source_level"]))
        mapped_ids = set(mapping_df[hom["source_id_field"]].astype(int))
        missing_ids = sorted(source_ids - mapped_ids)
        report_lines.append(
            f"- tabla de homologación: {hom['mapping_table']}"
        )
        report_lines.append(f"- catálogo propuesto: {hom['target_table']}")
        if hom.get("role") == "override":
            report_lines.append(
                f"- clases con excepción explícita: {sorted(mapped_ids)}"
            )
            report_lines.append(
                "- las demás clases utilizan la regla general de nivel 1"
            )
        else:
            report_lines.append(
                f"- clases de origen sin homologación: {missing_ids}"
            )
        report_lines.append(
            f"- conteos de auditoría: {proposed_usage_counts[hom_name]}"
        )

    final_keys = [
        name for name in proposed_usage_counts
        if name.endswith("_final") or name == "nivel_1_final"
    ]
    for final_key in final_keys:
        report_lines.append(
            f"Asignación propuesta final ({final_key}; excepción > general): "
            f"{proposed_usage_counts[final_key]}"
        )

    report_lines.append(
        f"Filas-nivel sin equivalencia estricta dominante vs valores: {mismatches}"
    )
    report_lines.append(
        "Filas-nivel donde el dominante está incluido dentro de múltiples valores: "
        f"{dominant_between_multiple}"
    )
    report_lines.append(
        "Filas-nivel con diferencia crítica dominante/valores: "
        f"{critical_dominant_mismatches}"
    )
    report_lines.append(
        "Tabla final para QGIS: "
        f"{final_homologation_summary['tabla']} | join 1:1 por {pk} | "
        "incluye id_0_propuesta, nivel_0_propuesta, "
        "id_1_propuesta y nivel_1_propuesta."
    )
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
    report_lines.append(f"Metadata: {(metadata_dir / 'normalization_source.csv').relative_to(ROOT)}")
    report_lines.append("")
    report_lines.append("Advertencias")
    report_lines.append("-" * 72)

    if warnings:
        report_lines.extend(warnings)
    else:
        report_lines.append("Sin advertencias.")

    report_text = "\n".join(report_lines)

    report_path = reports_dir / f"{source_key}_normalizacion_reporte_implementacion.txt"
    report_path.write_text(report_text, encoding="utf-8")

    logging.info("Reporte creado: %s", report_path)
    logging.info("Proceso finalizado correctamente.")

    print(report_text)

    return {
        "source_key": source_key,
        "status": "ok",
        "rows": n_rows,
        "input_gpkg": str(input_gpkg),
        "input_layer": layer_used or "",
        "output_gpkg": str(out_gpkg),
        "report": str(report_path),
        "warnings": len(warnings),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Normaliza las salidas finales de las nuevas fuentes A3 con el "
            "mismo modelo relacional de A2.1."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG,
        help="YAML de configuración de las fuentes A3.",
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        help=(
            "source_key a procesar. Puede repetirse. Si se omite, se procesan "
            "todas las entradas configuradas."
        ),
    )
    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="Lista las fuentes configuradas y termina.",
    )
    return parser.parse_args()


def run() -> None:
    args = parse_args()
    config_path = as_project_path(args.config)
    cfg = read_yaml(config_path)
    sources = cfg.get("inputs")
    if not isinstance(sources, list) or not sources:
        raise ValueError("El YAML debe contener una lista no vacía en inputs.")

    source_keys = [str(source.get("source_key", "")).strip() for source in sources]
    if any(not key for key in source_keys):
        raise ValueError("Todas las entradas deben definir source_key.")
    if len(source_keys) != len(set(source_keys)):
        raise ValueError(f"Hay source_key duplicados en el YAML: {source_keys}")

    if args.list_sources:
        print("\n".join(source_keys))
        return

    selected = set(args.sources or source_keys)
    unknown = sorted(selected - set(source_keys))
    if unknown:
        raise ValueError(
            f"Fuentes no configuradas: {unknown}. Disponibles: {source_keys}"
        )

    selected_sources = [
        source for source in sources if source["source_key"] in selected
    ]
    results: list[dict[str, Any]] = []

    for source_cfg in selected_sources:
        results.append(
            run_source(
                base_cfg=cfg,
                source_cfg=source_cfg,
                config_path=config_path,
            )
        )

    processed_root = as_project_path(cfg["output"]["processed_dir"])
    processed_root.mkdir(parents=True, exist_ok=True)
    summary_path = processed_root / "normalization_run_summary.csv"
    pd.DataFrame(results).to_csv(
        summary_path,
        index=False,
        encoding="utf-8-sig",
    )

    print("\nResumen A3")
    print("=" * 72)
    for result in results:
        print(
            f"{result['source_key']}: {result['rows']} filas -> "
            f"{result['output_gpkg']}"
        )
    print(f"Resumen: {summary_path}")


if __name__ == "__main__":
    run()
