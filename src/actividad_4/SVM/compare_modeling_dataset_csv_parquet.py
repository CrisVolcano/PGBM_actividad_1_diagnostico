# -*- coding: utf-8 -*-
"""
Comparacion rapida entre modeling_dataset.csv y modeling_dataset.parquet.

Este script es auxiliar y no forma parte numerada del flujo SVM. Sirve para
inspeccionar diferencias basicas entre ambos archivos: dimensiones, columnas,
distribucion de clases y presencia por cuadrante.

Ejecucion desde la raiz del repositorio:

    python src/actividad_4/SVM/compare_modeling_dataset_csv_parquet.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) >= 4 else Path.cwd()

CSV_PATH = REPO_ROOT / "data/processed/a4_6_modeling_dataset/tables/modeling_dataset.csv"
PARQUET_PATH = REPO_ROOT / "data/processed/a4_6_modeling_dataset/tables/modeling_dataset.parquet"

KEY_FIELD = "xy_group_id"
GROUP_FIELD = "id_cuadrante"
TARGET_FIELD = "id_1_propuesta"
TARGET_LABEL_FIELD = "nivel_1_propuesta"


def read_csv_dataset(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", low_memory=False)


def read_parquet_dataset(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def normalize_target(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
        .replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})
    )


def print_basic_summary(name: str, dataframe: pd.DataFrame) -> None:
    print(f"\n## {name}")
    print(f"shape: {dataframe.shape[0]:,} filas x {dataframe.shape[1]:,} columnas")
    print(f"columnas duplicadas: {int(dataframe.columns.duplicated().sum()):,}")

    for field in [KEY_FIELD, GROUP_FIELD, TARGET_FIELD, TARGET_LABEL_FIELD]:
        if field in dataframe.columns:
            print(f"{field}: presente | nulos={int(dataframe[field].isna().sum()):,} | unicos={dataframe[field].nunique(dropna=True):,}")
        else:
            print(f"{field}: AUSENTE")

    if KEY_FIELD in dataframe.columns:
        duplicated_keys = int(dataframe[KEY_FIELD].astype(str).duplicated().sum())
        print(f"{KEY_FIELD} duplicados: {duplicated_keys:,}")


def class_distribution(dataframe: pd.DataFrame) -> pd.DataFrame:
    if TARGET_FIELD not in dataframe.columns:
        return pd.DataFrame()

    temp = dataframe.copy()
    temp[TARGET_FIELD] = normalize_target(temp[TARGET_FIELD])
    group_cols = [TARGET_FIELD]
    if TARGET_LABEL_FIELD in temp.columns:
        group_cols.append(TARGET_LABEL_FIELD)

    output = (
        temp.groupby(group_cols, dropna=False)
        .agg(
            n_points=(TARGET_FIELD, "size"),
            n_quadrants=(GROUP_FIELD, "nunique") if GROUP_FIELD in temp.columns else (TARGET_FIELD, "size"),
        )
        .reset_index()
        .sort_values("n_points", ascending=False)
    )
    output["pct_points"] = output["n_points"] / len(temp)
    return output


def dry_columns_comparison(csv_df: pd.DataFrame, parquet_df: pd.DataFrame) -> None:
    csv_columns = set(csv_df.columns)
    parquet_columns = set(parquet_df.columns)
    only_csv = sorted(csv_columns - parquet_columns)
    only_parquet = sorted(parquet_columns - csv_columns)

    print("\n## Comparacion de columnas")
    print(f"columnas en ambos: {len(csv_columns & parquet_columns):,}")
    print(f"solo en CSV: {len(only_csv):,}")
    print(f"solo en Parquet: {len(only_parquet):,}")
    if only_csv:
        print("solo en CSV:", only_csv)
    if only_parquet:
        print("solo en Parquet:", only_parquet)


def key_overlap(csv_df: pd.DataFrame, parquet_df: pd.DataFrame) -> None:
    if KEY_FIELD not in csv_df.columns or KEY_FIELD not in parquet_df.columns:
        return

    csv_keys = set(csv_df[KEY_FIELD].astype(str).str.strip())
    parquet_keys = set(parquet_df[KEY_FIELD].astype(str).str.strip())
    print("\n## Comparacion por llave")
    print(f"llaves CSV: {len(csv_keys):,}")
    print(f"llaves Parquet: {len(parquet_keys):,}")
    print(f"llaves en ambos: {len(csv_keys & parquet_keys):,}")
    print(f"llaves solo CSV: {len(csv_keys - parquet_keys):,}")
    print(f"llaves solo Parquet: {len(parquet_keys - csv_keys):,}")


def compare_target_14(csv_df: pd.DataFrame, parquet_df: pd.DataFrame) -> None:
    print("\n## Foco clase 14 - bosques secos")
    for name, dataframe in [("CSV", csv_df), ("Parquet", parquet_df)]:
        if TARGET_FIELD not in dataframe.columns:
            continue
        target = normalize_target(dataframe[TARGET_FIELD])
        subset = dataframe[target == "14"].copy()
        print(f"{name}: {len(subset):,} puntos | pct={len(subset) / len(dataframe):.6f}")
        if GROUP_FIELD in subset.columns:
            groups = sorted(subset[GROUP_FIELD].astype(str).str.strip().unique())
            print(f"{name}: {len(groups):,} cuadrantes | {'|'.join(groups)}")


def main() -> None:
    print("Leyendo archivos...")
    csv_df = read_csv_dataset(CSV_PATH)
    parquet_df = read_parquet_dataset(PARQUET_PATH)

    print_basic_summary("CSV", csv_df)
    print_basic_summary("Parquet", parquet_df)
    dry_columns_comparison(csv_df, parquet_df)
    key_overlap(csv_df, parquet_df)

    print("\n## Distribucion de clases CSV")
    print(class_distribution(csv_df).to_string(index=False))

    print("\n## Distribucion de clases Parquet")
    print(class_distribution(parquet_df).to_string(index=False))

    compare_target_14(csv_df, parquet_df)


if __name__ == "__main__":
    main()
