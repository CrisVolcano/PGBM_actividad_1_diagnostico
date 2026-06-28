"""
Funciones preliminares para auditoría estructural.
Estas funciones se ampliarán en el Módulo 2.
"""

import pandas as pd


def resumen_nulos(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula número y porcentaje de valores nulos por campo."""
    total = len(df)

    return (
        df.isna()
        .sum()
        .reset_index()
        .rename(columns={"index": "campo", 0: "n_nulos"})
        .assign(pct_nulos=lambda x: 100 * x["n_nulos"] / total if total > 0 else 0)
        .sort_values("pct_nulos", ascending=False)
    )


def resumen_tipos(df: pd.DataFrame) -> pd.DataFrame:
    """Resume tipo de dato y número de valores únicos por campo."""
    return pd.DataFrame(
        {
            "campo": df.columns,
            "tipo": [str(df[c].dtype) for c in df.columns],
            "n_unicos": [df[c].nunique(dropna=True) for c in df.columns],
        }
    )
