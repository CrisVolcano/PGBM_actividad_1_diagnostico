# -*- coding: utf-8 -*-
"""
Actividad 4.8.1 — Preparación específica del dataset para SVM
=============================================================

Esta etapa toma el dataset tabular de A4.6 y lo deja listo para una etapa SVM
independiente. No entrena modelos, no crea splits definitivos y no aplica
imputación ni escalamiento. Esas transformaciones deben vivir dentro del
pipeline de entrenamiento para evitar fuga de información.

Ejecución desde la raíz del repositorio:

    python src/actividad_4/SVM/4_8_1_prepare_svm_dataset.py
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


LOGGER = logging.getLogger("a4_8_1_prepare_svm_dataset")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) >= 4 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_8_svm.yaml"
CONFIG_SECTION = "prepare_dataset"


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el YAML de configuración: {path}")
    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("El YAML debe contener un diccionario en la raíz.")
    return config


def select_config_section(config: dict[str, Any], section: str) -> dict[str, Any]:
    if section in config:
        selected = config[section]
        if not isinstance(selected, dict):
            raise ValueError(f"La sección {section} debe contener un diccionario.")
        return selected
    return config


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def ensure_dirs(output_dir: Path) -> None:
    for dirname in ["logs", "tables", "reports"]:
        (output_dir / dirname).mkdir(parents=True, exist_ok=True)


def configure_logger(output_dir: Path) -> None:
    ensure_dirs(output_dir)
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for handler in (
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            output_dir / "logs" / "a4_8_1_prepare_svm_dataset.log",
            mode="w",
            encoding="utf-8",
        ),
    ):
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)


def read_text_list(path: Path, label: str) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"No existe {label}: {path}")
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def read_dataset(config: dict[str, Any]) -> tuple[pd.DataFrame, Path, str]:
    paths = config["paths"]
    prefer_parquet = bool(config.get("read", {}).get("prefer_parquet", True))
    parquet_path = resolve_path(paths["modeling_dataset_parquet"])
    csv_path = resolve_path(paths["modeling_dataset_csv"])
    csv_encoding = str(config.get("read", {}).get("csv_encoding", "utf-8-sig"))

    if prefer_parquet and parquet_path.exists():
        LOGGER.info("Leyendo dataset Parquet: %s", parquet_path)
        return pd.read_parquet(parquet_path), parquet_path, "parquet"

    if csv_path.exists():
        LOGGER.info("Leyendo dataset CSV: %s", csv_path)
        return pd.read_csv(csv_path, encoding=csv_encoding, low_memory=False), csv_path, "csv"

    if parquet_path.exists():
        LOGGER.info("Leyendo dataset Parquet: %s", parquet_path)
        return pd.read_parquet(parquet_path), parquet_path, "parquet"

    raise FileNotFoundError(f"No existe dataset A4.6: {parquet_path} ni {csv_path}")


def validate_required_fields(dataframe: pd.DataFrame, config: dict[str, Any]) -> None:
    fields = config["fields"]
    required = [
        str(fields["key"]),
        str(fields["group"]),
        str(fields["primary_target"]),
    ]
    required.extend(str(field) for field in as_list(fields.get("targets")))
    required.extend(str(field) for field in as_list(fields.get("context_fields")))
    missing = sorted(set(required) - set(dataframe.columns))
    if missing and bool(config.get("quality", {}).get("fail_on_missing_required_fields", True)):
        raise ValueError(f"Faltan campos requeridos en el dataset: {missing}")
    if missing:
        LOGGER.warning("Faltan campos requeridos que serán omitidos: %s", missing)


def validate_target_columns(config: dict[str, Any]) -> None:
    target_path = resolve_path(config["paths"]["target_columns_txt"])
    prepared_targets = set(read_text_list(target_path, "target_columns_txt"))
    primary_target = str(config["fields"]["primary_target"])
    configured_targets = {str(field) for field in as_list(config["fields"].get("targets"))}
    missing = sorted((configured_targets | {primary_target}) - prepared_targets)
    if missing:
        raise ValueError(
            "El objetivo configurado para SVM no coincide con target_columns.txt de A4.6. "
            f"Faltantes: {missing}; preparados: {sorted(prepared_targets)}"
        )


def apply_row_filters(dataframe: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    row_cfg = config.get("row_filter", {}) or {}
    output = dataframe.copy()
    required_targets = [str(field) for field in as_list(row_cfg.get("required_non_null_targets"))]
    if required_targets:
        missing = [field for field in required_targets if field not in output.columns]
        if missing:
            raise ValueError(f"required_non_null_targets contiene campos inexistentes: {missing}")
        before = len(output)
        output = output.dropna(subset=required_targets).copy()
        LOGGER.info(
            "Filtro objetivos no nulos: %s -> %s filas",
            f"{before:,}",
            f"{len(output):,}",
        )

    action_filter = row_cfg.get("action_filter", {}) or {}
    if bool(action_filter.get("enabled", False)):
        field = str(action_filter.get("field", ""))
        allowed = {str(value) for value in as_list(action_filter.get("allowed_values"))}
        if field not in output.columns:
            raise ValueError(f"No existe el campo para action_filter: {field}")
        before = len(output)
        output = output[output[field].astype(str).isin(allowed)].copy()
        LOGGER.info(
            "Filtro acción %s: %s -> %s filas",
            field,
            f"{before:,}",
            f"{len(output):,}",
        )

    if output.empty:
        raise ValueError("El dataset SVM quedó vacío después de aplicar filtros.")
    return output.reset_index(drop=True)


def compile_exclusion_regexes(config: dict[str, Any]) -> list[re.Pattern[str]]:
    return [re.compile(str(pattern)) for pattern in as_list(config.get("features", {}).get("exclude_feature_regex"))]


def select_candidate_features(dataframe: pd.DataFrame, config: dict[str, Any]) -> list[str]:
    feature_path = resolve_path(config["paths"]["selected_feature_columns_txt"])
    base_features = read_text_list(feature_path, "selected_feature_columns_txt")
    feature_cfg = config.get("features", {}) or {}
    include_features = [str(field) for field in as_list(feature_cfg.get("include_feature_columns"))]
    exclude_features = {str(field) for field in as_list(feature_cfg.get("exclude_feature_columns"))}
    regexes = compile_exclusion_regexes(config)

    if include_features:
        base_features = include_features

    duplicated = sorted({feature for feature in base_features if base_features.count(feature) > 1})
    if duplicated and bool(config.get("quality", {}).get("fail_on_duplicate_feature_columns", True)):
        raise ValueError(f"Columnas predictoras duplicadas: {duplicated}")

    filtered: list[str] = []
    for feature in base_features:
        if feature in exclude_features:
            continue
        if any(regex.search(feature) for regex in regexes):
            continue
        filtered.append(feature)

    missing = sorted(set(filtered) - set(dataframe.columns))
    if missing and bool(config.get("quality", {}).get("fail_on_missing_feature_columns", True)):
        raise ValueError(f"Predictores configurados ausentes en el dataset: {missing}")

    filtered = [feature for feature in filtered if feature in dataframe.columns]
    if not filtered:
        raise ValueError("No quedó ningún predictor candidato para SVM.")
    return filtered


def dominant_value_fraction(series: pd.Series) -> float:
    counts = series.dropna().value_counts(normalize=True)
    if counts.empty:
        return 0.0
    return float(counts.iloc[0])


def build_feature_diagnostics(
    dataframe: pd.DataFrame,
    features: list[str],
    config: dict[str, Any],
) -> tuple[pd.DataFrame, list[str]]:
    quality_cfg = config.get("quality", {}) or {}
    max_null_pct = float(quality_cfg.get("max_feature_null_pct_to_use", 0.05))
    drop_constant = bool(quality_cfg.get("drop_constant_features", True))
    drop_near_constant = bool(quality_cfg.get("drop_near_constant_features", False))
    near_constant_pct = float(quality_cfg.get("near_constant_dominant_pct", 0.995))
    coerce_numeric = bool(quality_cfg.get("coerce_features_to_numeric", True))
    fail_on_conversion_nulls = bool(quality_cfg.get("fail_on_numeric_conversion_nulls", False))

    rows: list[dict[str, Any]] = []
    selected: list[str] = []

    for feature in features:
        original = dataframe[feature]
        original_nulls = int(original.isna().sum())
        numeric = pd.to_numeric(original, errors="coerce") if coerce_numeric else original
        numeric_nulls = int(numeric.isna().sum())
        conversion_nulls = max(0, numeric_nulls - original_nulls)
        n_rows = int(len(numeric))
        n_non_null = int(n_rows - numeric_nulls)
        pct_null = float(numeric_nulls / n_rows) if n_rows else 1.0
        n_unique = int(numeric.nunique(dropna=True))
        is_constant = n_unique <= 1
        dom_pct = dominant_value_fraction(numeric)
        is_near_constant = bool(dom_pct >= near_constant_pct) if n_non_null else True

        reasons: list[str] = []
        if conversion_nulls and fail_on_conversion_nulls:
            reasons.append("numeric_conversion_created_nulls")
        if pct_null > max_null_pct:
            reasons.append("high_null_fraction")
        if drop_constant and is_constant:
            reasons.append("constant_feature")
        if drop_near_constant and is_near_constant:
            reasons.append("near_constant_feature")

        use_in_svm = not reasons
        if use_in_svm:
            selected.append(feature)

        quantiles = numeric.quantile([0.25, 0.5, 0.75]) if n_non_null else pd.Series(dtype=float)
        q1 = float(quantiles.get(0.25, float("nan"))) if n_non_null else float("nan")
        median = float(quantiles.get(0.5, float("nan"))) if n_non_null else float("nan")
        q3 = float(quantiles.get(0.75, float("nan"))) if n_non_null else float("nan")

        rows.append(
            {
                "feature_column": feature,
                "dtype_original": str(original.dtype),
                "n_rows": n_rows,
                "n_null_original": original_nulls,
                "n_null_numeric": numeric_nulls,
                "numeric_conversion_new_nulls": conversion_nulls,
                "pct_null": pct_null,
                "n_non_null": n_non_null,
                "n_unique": n_unique,
                "is_constant": is_constant,
                "dominant_value_pct": dom_pct,
                "is_near_constant": is_near_constant,
                "min": float(numeric.min()) if n_non_null else float("nan"),
                "q1": q1,
                "median": median,
                "q3": q3,
                "max": float(numeric.max()) if n_non_null else float("nan"),
                "mean": float(numeric.mean()) if n_non_null else float("nan"),
                "std": float(numeric.std()) if n_non_null else float("nan"),
                "iqr": q3 - q1 if n_non_null else float("nan"),
                "use_in_svm": use_in_svm,
                "exclusion_reason": ";".join(reasons),
            }
        )

    diagnostics = pd.DataFrame(rows)
    if not selected:
        raise ValueError("Ningún predictor pasó los criterios de preparación SVM.")
    return diagnostics, selected


def build_prepared_dataset(
    dataframe: pd.DataFrame,
    selected_features: list[str],
    config: dict[str, Any],
) -> tuple[pd.DataFrame, list[str], list[str]]:
    fields = config["fields"]
    key = str(fields["key"])
    group = str(fields["group"])
    targets = [str(field) for field in as_list(fields.get("targets"))]
    context = [str(field) for field in as_list(fields.get("context_fields"))]

    for field in [key, group]:
        if field not in context:
            context.insert(0 if field == key else 1, field)

    context = [field for field in context if field in dataframe.columns]
    targets = [field for field in targets if field in dataframe.columns]
    columns: list[str] = []
    for field in context + targets + selected_features:
        if field not in columns:
            columns.append(field)

    output = dataframe[columns].copy()
    output[key] = output[key].astype(str).str.strip()
    duplicated = int(output[key].duplicated().sum())
    if duplicated:
        raise ValueError(f"El dataset preparado tiene {duplicated:,} xy_group_id duplicados.")

    for feature in selected_features:
        output[feature] = pd.to_numeric(output[feature], errors="coerce")

    return output, context, targets


def build_schema(
    dataframe: pd.DataFrame,
    key: str,
    group: str,
    context: list[str],
    targets: list[str],
    features: list[str],
) -> pd.DataFrame:
    roles = {field: "context" for field in context}
    roles.update({field: "target" for field in targets})
    roles.update({field: "feature" for field in features})
    roles[key] = "key"
    roles[group] = "group"

    rows = []
    for order, column in enumerate(dataframe.columns, start=1):
        rows.append(
            {
                "column_order": order,
                "column_name": column,
                "role": roles.get(column, "other"),
                "dtype": str(dataframe[column].dtype),
                "n_null": int(dataframe[column].isna().sum()),
                "n_unique": int(dataframe[column].nunique(dropna=True)),
            }
        )
    return pd.DataFrame(rows)


def summarize_targets(
    dataframe: pd.DataFrame,
    targets: list[str],
    group_field: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    distribution_rows: list[dict[str, Any]] = []
    by_group_rows: list[dict[str, Any]] = []
    for target in targets:
        total = len(dataframe)
        grouped = (
            dataframe.groupby(target, dropna=False)
            .agg(n_points=(target, "size"), n_groups=(group_field, "nunique"))
            .reset_index()
            .rename(columns={target: "class_id"})
        )
        grouped["target_field"] = target
        grouped["pct_points"] = grouped["n_points"] / total if total else 0.0
        distribution_rows.extend(
            grouped[["target_field", "class_id", "n_points", "pct_points", "n_groups"]].to_dict("records")
        )

        class_group = (
            dataframe.groupby([target, group_field], dropna=False)
            .size()
            .reset_index(name="n_points")
            .rename(columns={target: "class_id", group_field: "group_id"})
        )
        class_group["target_field"] = target
        by_group_rows.extend(
            class_group[["target_field", "class_id", "group_id", "n_points"]].to_dict("records")
        )

    distribution = pd.DataFrame(distribution_rows)
    by_group = pd.DataFrame(by_group_rows)
    if not distribution.empty:
        distribution = distribution.sort_values(["target_field", "n_points"], ascending=[True, False])
    if not by_group.empty:
        by_group = by_group.sort_values(["target_field", "class_id", "group_id"])
    return distribution, by_group


def write_outputs(
    prepared: pd.DataFrame,
    selected_features: list[str],
    diagnostics: pd.DataFrame,
    schema: pd.DataFrame,
    target_distribution: pd.DataFrame,
    class_by_group: pd.DataFrame,
    output_dir: Path,
    config: dict[str, Any],
) -> None:
    outputs = config.get("outputs", {}) or {}

    if bool(outputs.get("write_parquet", True)):
        parquet_path = output_dir / outputs.get("prepared_dataset_parquet", "tables/svm_modeling_dataset.parquet")
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        prepared.to_parquet(parquet_path, index=False)
        LOGGER.info("Dataset SVM Parquet escrito: %s", parquet_path)

    if bool(outputs.get("write_csv", False)):
        csv_path = output_dir / outputs.get("prepared_dataset_csv", "tables/svm_modeling_dataset.csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        prepared.to_csv(csv_path, index=False, encoding="utf-8-sig")
        LOGGER.info("Dataset SVM CSV escrito: %s", csv_path)

    selected_path = output_dir / outputs.get("selected_features_txt", "tables/svm_selected_feature_columns.txt")
    selected_path.write_text("\n".join(selected_features) + "\n", encoding="utf-8")

    diagnostics.to_csv(
        output_dir / outputs.get("feature_diagnostics_csv", "tables/svm_feature_diagnostics.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    diagnostics.loc[~diagnostics["use_in_svm"]].to_csv(
        output_dir / outputs.get("excluded_features_csv", "tables/svm_excluded_features.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    schema.to_csv(
        output_dir / outputs.get("dataset_schema_csv", "tables/svm_dataset_schema.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    target_distribution.to_csv(
        output_dir / outputs.get("target_distribution_csv", "tables/svm_target_distribution.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    class_by_group.to_csv(
        output_dir / outputs.get("class_by_group_csv", "tables/svm_class_by_group.csv"),
        index=False,
        encoding="utf-8-sig",
    )


def build_report(
    input_path: Path,
    input_kind: str,
    prepared: pd.DataFrame,
    selected_features: list[str],
    diagnostics: pd.DataFrame,
    target_distribution: pd.DataFrame,
    output_dir: Path,
    config: dict[str, Any],
) -> None:
    outputs = config.get("outputs", {}) or {}
    report_path = output_dir / outputs.get("report_md", "reports/a4_8_1_prepare_svm_dataset_report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    excluded = diagnostics.loc[~diagnostics["use_in_svm"]].copy()
    max_null = diagnostics["pct_null"].max() if not diagnostics.empty else 0.0
    primary_target = str(config["fields"]["primary_target"])
    target_text = target_distribution[target_distribution["target_field"] == primary_target]

    lines = [
        "# Actividad 4.8.1 — Preparación del dataset SVM",
        "",
        f"**Fecha:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Insumo",
        "",
        f"- Dataset leído: `{input_path.relative_to(REPO_ROOT)}`",
        f"- Formato usado: `{input_kind}`",
        "",
        "## Resultado",
        "",
        "| elemento | valor |",
        "|:--|--:|",
        f"| filas | {len(prepared):,} |",
        f"| columnas totales | {prepared.shape[1]:,} |",
        f"| predictores candidatos | {len(diagnostics):,} |",
        f"| predictores seleccionados SVM | {len(selected_features):,} |",
        f"| predictores excluidos | {len(excluded):,} |",
        f"| máximo pct. nulos en predictores | {max_null:.6f} |",
        "",
        "## Objetivo principal",
        "",
        f"`{primary_target}`",
        "",
        "## Distribución del objetivo principal",
        "",
    ]
    if target_text.empty:
        lines.append("_Sin datos._")
    else:
        lines.append(target_text.to_markdown(index=False))

    lines.extend(
        [
            "",
            "## Nota metodológica",
            "",
            "Esta etapa no imputa, no escala y no crea particiones finales. "
            "La imputación y el escalamiento deben aplicarse dentro del pipeline "
            "de entrenamiento SVM para evitar fuga de información.",
            "",
        ]
    )
    if not excluded.empty:
        lines.extend(
            [
                "## Variables excluidas",
                "",
                excluded[["feature_column", "exclusion_reason"]].to_markdown(index=False),
                "",
            ]
        )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Reporte SVM escrito: %s", report_path)


def main() -> None:
    config_path = resolve_path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG
    config = select_config_section(read_yaml(config_path), CONFIG_SECTION)
    output_dir = resolve_path(config["paths"]["output_dir"])
    configure_logger(output_dir)
    LOGGER.info("YAML de configuración: %s | sección=%s", config_path, CONFIG_SECTION)

    dataset, input_path, input_kind = read_dataset(config)
    validate_required_fields(dataset, config)
    validate_target_columns(config)

    filtered = apply_row_filters(dataset, config)
    features = select_candidate_features(filtered, config)
    diagnostics, selected_features = build_feature_diagnostics(filtered, features, config)
    prepared, context, targets = build_prepared_dataset(filtered, selected_features, config)

    key = str(config["fields"]["key"])
    group = str(config["fields"]["group"])
    schema = build_schema(prepared, key, group, context, targets, selected_features)
    target_distribution, class_by_group = summarize_targets(prepared, targets, group)

    write_outputs(
        prepared=prepared,
        selected_features=selected_features,
        diagnostics=diagnostics,
        schema=schema,
        target_distribution=target_distribution,
        class_by_group=class_by_group,
        output_dir=output_dir,
        config=config,
    )
    build_report(
        input_path=input_path,
        input_kind=input_kind,
        prepared=prepared,
        selected_features=selected_features,
        diagnostics=diagnostics,
        target_distribution=target_distribution,
        output_dir=output_dir,
        config=config,
    )
    LOGGER.info(
        "A4.8.1 finalizado: filas=%s | features_svm=%s",
        f"{len(prepared):,}",
        f"{len(selected_features):,}",
    )


if __name__ == "__main__":
    main()
