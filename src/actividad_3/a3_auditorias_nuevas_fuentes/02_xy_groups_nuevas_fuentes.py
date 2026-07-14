from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import hashlib
import sqlite3
import traceback
from typing import Any

import geopandas as gpd
import pandas as pd
import yaml


# =============================================================================
# PGBM - Grupos XY para nuevas fuentes puntuales
# =============================================================================
#
# Este modulo crea identificadores espaciales estables para nuevas fuentes sin
# depender de la base original de PGBM ni de sus grupos XY. Los identificadores
# usan un namespace configurado para evitar colisiones si algun dia se integran
# con productos del flujo original.
#
# Unidades generadas:
#   - xy_group_id: Longitud + Latitud
#   - xy_year_group_id: Longitud + Latitud + Año
#   - xy_class_group_id: Longitud + Latitud + Año + Clase + GranClase
#
# Salidas:
#   - GeoPackage con registros y capas resumen
#   - CSV de control en outputs/tables/a3_auditorias_nuevas_fuentes/xy_groups
#   - Reporte Markdown en outputs/reports/a3_auditorias_nuevas_fuentes/xy_groups
# =============================================================================


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]
DEFAULT_CONFIG_RELATIVE = "config/a3_auditorias_nuevas_fuentes/config_sinac_malla_entrenamientos_2021.yaml"


def cargar_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el YAML requerido: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"El YAML no contiene un diccionario valido: {path}")
    return data


def resolver_config_path(config_arg: str | Path) -> Path:
    path = Path(config_arg)
    if path.is_absolute():
        return path.resolve()

    cwd_path = (Path.cwd() / path).resolve()
    if cwd_path.exists():
        return cwd_path

    script_path = (SCRIPT_DIR / path).resolve()
    if script_path.exists():
        return script_path

    return (PROJECT_DIR / path).resolve()


def resolver_project_root(config: dict[str, Any], config_path: Path) -> Path:
    paths_cfg = config.get("paths", {})
    if isinstance(paths_cfg, dict) and paths_cfg.get("project_root"):
        root = Path(paths_cfg["project_root"])
        return root.resolve() if root.is_absolute() else (config_path.parent / root).resolve()
    return config_path.parent.resolve()


def resolver_ruta(path_value: str | Path, base_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def dataframe_a_markdown(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```text\n" + df.to_string(index=False) + "\n```"


def clean_for_gpkg(df: pd.DataFrame | gpd.GeoDataFrame) -> pd.DataFrame | gpd.GeoDataFrame:
    out = df.copy()
    geometry_name = out.geometry.name if isinstance(out, gpd.GeoDataFrame) else None

    for col in out.columns:
        if col == geometry_name:
            continue
        dtype = str(out[col].dtype)
        if dtype.startswith("Int") or dtype.startswith("UInt"):
            out[col] = out[col].astype("float").where(out[col].notna(), None)
        elif dtype in {"string", "boolean"}:
            out[col] = out[col].astype(object)

    return out


def write_table_to_gpkg(df: pd.DataFrame, gpkg_path: Path, table_name: str) -> None:
    table = clean_for_gpkg(df)
    with sqlite3.connect(gpkg_path) as conn:
        table.to_sql(table_name, conn, if_exists="replace", index=False)


def normalizar_coord(series: pd.Series, decimals: int) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").round(decimals)


def normalizar_texto(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip()


def stable_hash(parts: list[object], length: int) -> str:
    text = "||".join("" if pd.isna(part) else str(part) for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def make_group_id(namespace: str, group_type: str, parts: list[object], hash_length: int) -> str:
    digest = stable_hash([namespace, group_type, *parts], hash_length)
    return f"{namespace}__{group_type}__{digest}"


def validar_config(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    input_data = config.get("input_data", {})
    fields = config.get("fields", {})
    settings = config.get("settings", {})
    xy_cfg = config.get("xy_groups", {})

    if not isinstance(input_data, dict):
        raise ValueError("La seccion input_data del YAML no es valida.")
    if not isinstance(fields, dict):
        raise ValueError("La seccion fields del YAML no es valida.")
    if not isinstance(settings, dict):
        settings = {}
    if not isinstance(xy_cfg, dict):
        xy_cfg = {}

    required = [
        "id",
        "source",
        "source_id",
        "year",
        "country",
        "country_code",
        "longitude",
        "latitude",
        "class_code",
        "class_group_code",
        "class_name",
        "class_group_name",
    ]
    missing = [key for key in required if not fields.get(key)]
    if missing:
        raise ValueError(f"Faltan campos requeridos en fields: {missing}")

    input_gpkg = xy_cfg.get("input_gpkg") or input_data.get("gpkg_file")
    input_layer = xy_cfg.get("input_layer") or input_data.get("gpkg_layer")
    if not input_gpkg or not input_layer:
        raise ValueError("Debe definirse input_gpkg/input_layer para xy_groups.")

    layers = xy_cfg.get("output_layers", {})
    if not isinstance(layers, dict):
        layers = {}

    return {
        "input_gpkg": resolver_ruta(input_gpkg, project_root),
        "input_layer": str(input_layer),
        "output_gpkg": resolver_ruta(
            xy_cfg.get("output_gpkg", "data/processed/a3_auditorias_nuevas_fuentes/xy_groups/xy_groups_outputs.gpkg"),
            project_root,
        ),
        "tables_dir": resolver_ruta(
            xy_cfg.get("tables_dir", "outputs/tables/a3_auditorias_nuevas_fuentes/xy_groups"),
            project_root,
        ),
        "report_md": resolver_ruta(
            xy_cfg.get("report_md", "outputs/reports/a3_auditorias_nuevas_fuentes/xy_groups/xy_groups_report.md"),
            project_root,
        ),
        "layers": {
            "records": str(layers.get("records", "records_with_xy_groups")),
            "xy_groups": str(layers.get("xy_groups", "xy_groups")),
            "xy_year_groups": str(layers.get("xy_year_groups", "xy_year_groups")),
            "xy_class_groups": str(layers.get("xy_class_groups", "xy_class_groups")),
        },
        "fields": {key: str(fields[key]) for key in required},
        "field_names": {
            "xy_group_id": str(fields.get("xy_group_id", "xy_group_id")),
            "xy_year_group_id": str(fields.get("xy_year_group_id", "xy_year_group_id")),
            "xy_class_group_id": str(fields.get("xy_class_group_id", "xy_class_group_id")),
        },
        "expected_crs": str(settings.get("expected_crs", "EPSG:4326")),
        "coordinate_precision": int(
            xy_cfg.get("coordinate_precision", settings.get("coordinate_precision", 6))
        ),
        "id_namespace": str(xy_cfg.get("id_namespace", "NEW_SOURCE")),
        "hash_length": int(xy_cfg.get("hash_length", 12)),
    }


def validar_campos(gdf: gpd.GeoDataFrame, fields: dict[str, str]) -> None:
    missing = [field for field in fields.values() if field not in gdf.columns]
    if missing:
        available = sorted(map(str, gdf.columns))
        raise ValueError(f"Faltan campos requeridos: {missing}. Disponibles: {available}")


def preparar_geometria(
    gdf: gpd.GeoDataFrame,
    expected_crs: str,
    lon_field: str,
    lat_field: str,
    decimals: int,
) -> gpd.GeoDataFrame:
    if gdf.empty:
        raise ValueError("La capa de entrada no contiene registros.")
    if gdf.crs is None:
        raise ValueError("La capa de entrada no tiene CRS definido.")
    if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
        raise ValueError("La capa contiene geometria nula o vacia.")

    geom_types = set(gdf.geometry.geom_type.dropna().unique())
    if geom_types != {"Point"}:
        raise ValueError(f"Este modulo solo acepta Point. Tipos detectados: {sorted(geom_types)}")

    if str(gdf.crs).upper() != expected_crs.upper():
        gdf = gdf.to_crs(expected_crs)

    gdf = gdf.copy()
    gdf[lon_field] = gdf.geometry.x.round(decimals)
    gdf[lat_field] = gdf.geometry.y.round(decimals)
    return gdf


def agregar_ids(gdf: gpd.GeoDataFrame, cfg: dict[str, Any]) -> gpd.GeoDataFrame:
    fields = cfg["fields"]
    names = cfg["field_names"]
    lon = fields["longitude"]
    lat = fields["latitude"]
    year = fields["year"]
    class_code = fields["class_code"]
    class_group = fields["class_group_code"]

    out = gdf.copy()
    out["_lon_xy"] = normalizar_coord(out[lon], cfg["coordinate_precision"])
    out["_lat_xy"] = normalizar_coord(out[lat], cfg["coordinate_precision"])
    out["_year_xy"] = pd.to_numeric(out[year], errors="coerce").astype("Int64")
    out["_class_xy"] = normalizar_texto(out[class_code])
    out["_class_group_xy"] = normalizar_texto(out[class_group])

    if out[["_lon_xy", "_lat_xy", "_year_xy"]].isna().any(axis=None):
        bad = int(out[["_lon_xy", "_lat_xy", "_year_xy"]].isna().any(axis=1).sum())
        raise ValueError(f"Hay registros sin lon/lat/año validos para grupos XY: {bad:,}")

    namespace = cfg["id_namespace"]
    hlen = cfg["hash_length"]

    out[names["xy_group_id"]] = [
        make_group_id(namespace, "XY", [lon_v, lat_v], hlen)
        for lon_v, lat_v in zip(out["_lon_xy"], out["_lat_xy"], strict=True)
    ]
    out[names["xy_year_group_id"]] = [
        make_group_id(namespace, "XYY", [lon_v, lat_v, year_v], hlen)
        for lon_v, lat_v, year_v in zip(out["_lon_xy"], out["_lat_xy"], out["_year_xy"], strict=True)
    ]
    out[names["xy_class_group_id"]] = [
        make_group_id(namespace, "XYC", [lon_v, lat_v, year_v, cls, grp], hlen)
        for lon_v, lat_v, year_v, cls, grp in zip(
            out["_lon_xy"],
            out["_lat_xy"],
            out["_year_xy"],
            out["_class_xy"],
            out["_class_group_xy"],
            strict=True,
        )
    ]

    return out


def first_value(series: pd.Series) -> object:
    vals = series.dropna()
    if vals.empty:
        return pd.NA
    return vals.iloc[0]


def build_xy_groups(gdf: gpd.GeoDataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    fields = cfg["fields"]
    names = cfg["field_names"]
    group_col = names["xy_group_id"]

    grouped = gdf.groupby(group_col, dropna=False)
    rows = grouped.agg(
        lon=(fields["longitude"], "first"),
        lat=(fields["latitude"], "first"),
        records=(group_col, "size"),
        n_years=(fields["year"], lambda s: s.nunique(dropna=True)),
        year_min=(fields["year"], "min"),
        year_max=(fields["year"], "max"),
        n_class_codes=(fields["class_code"], lambda s: s.nunique(dropna=True)),
        n_class_group_codes=(fields["class_group_code"], lambda s: s.nunique(dropna=True)),
        n_sources=(fields["source_id"], lambda s: s.nunique(dropna=True)),
        country=(fields["country"], first_value),
        country_code=(fields["country_code"], first_value),
    ).reset_index()

    rows["has_temporal_repetition"] = (rows["n_years"] > 1).astype("int8")
    rows["has_thematic_conflict"] = (
        (rows["n_class_codes"] > 1) | (rows["n_class_group_codes"] > 1)
    ).astype("int8")
    return rows


def build_xy_year_groups(gdf: gpd.GeoDataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    fields = cfg["fields"]
    names = cfg["field_names"]
    group_col = names["xy_year_group_id"]

    rows = (
        gdf.groupby(group_col, dropna=False)
        .agg(
            xy_group_id=(names["xy_group_id"], "first"),
            lon=(fields["longitude"], "first"),
            lat=(fields["latitude"], "first"),
            year_ref=(fields["year"], "first"),
            records=(group_col, "size"),
            n_class_codes=(fields["class_code"], lambda s: s.nunique(dropna=True)),
            n_class_group_codes=(fields["class_group_code"], lambda s: s.nunique(dropna=True)),
            n_sources=(fields["source_id"], lambda s: s.nunique(dropna=True)),
            country=(fields["country"], first_value),
            country_code=(fields["country_code"], first_value),
        )
        .reset_index()
    )
    rows["has_thematic_conflict"] = (
        (rows["n_class_codes"] > 1) | (rows["n_class_group_codes"] > 1)
    ).astype("int8")
    return rows


def build_xy_class_groups(gdf: gpd.GeoDataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    fields = cfg["fields"]
    names = cfg["field_names"]
    group_col = names["xy_class_group_id"]

    return (
        gdf.groupby(group_col, dropna=False)
        .agg(
            xy_group_id=(names["xy_group_id"], "first"),
            xy_year_group_id=(names["xy_year_group_id"], "first"),
            lon=(fields["longitude"], "first"),
            lat=(fields["latitude"], "first"),
            year_ref=(fields["year"], "first"),
            class_code=(fields["class_code"], first_value),
            class_group_code=(fields["class_group_code"], first_value),
            class_name=(fields["class_name"], first_value),
            class_group_name=(fields["class_group_name"], first_value),
            records=(group_col, "size"),
            country=(fields["country"], first_value),
            country_code=(fields["country_code"], first_value),
            source=(fields["source"], first_value),
            source_id=(fields["source_id"], first_value),
        )
        .reset_index()
    )


def tabla_nulos(gdf: gpd.GeoDataFrame, fields: dict[str, str]) -> pd.DataFrame:
    rows = []
    total = len(gdf)
    for logical, field in fields.items():
        if field not in gdf.columns:
            rows.append(
                {
                    "logical_field": logical,
                    "field": field,
                    "present": False,
                    "nulls": pd.NA,
                    "empty_strings": pd.NA,
                    "pct_null_or_empty": pd.NA,
                }
            )
            continue

        nulls = int(gdf[field].isna().sum())
        non_null_text = gdf.loc[gdf[field].notna(), field].astype("string").str.strip()
        empty = int((non_null_text == "").sum())
        rows.append(
            {
                "logical_field": logical,
                "field": field,
                "present": True,
                "nulls": nulls,
                "empty_strings": empty,
                "pct_null_or_empty": round((nulls + empty) / total * 100, 4) if total else 0,
            }
        )
    return pd.DataFrame(rows)


def export_count(df: pd.DataFrame, field: str, path: Path) -> pd.DataFrame:
    if field not in df.columns:
        out = pd.DataFrame([{"warning": f"Campo no encontrado: {field}"}])
    else:
        out = (
            df.groupby(field, dropna=False)
            .size()
            .reset_index(name="records")
            .sort_values("records", ascending=False)
        )
        total = int(out["records"].sum())
        out["percentage"] = (out["records"] / total * 100).round(4) if total else 0
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return out


def generar_reporte(
    cfg: dict[str, Any],
    config_path: Path,
    records: gpd.GeoDataFrame,
    xy_groups: pd.DataFrame,
    xy_year_groups: pd.DataFrame,
    xy_class_groups: pd.DataFrame,
    nulls: pd.DataFrame,
    class_dist: pd.DataFrame,
) -> None:
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_path = cfg["report_md"]
    report_path.parent.mkdir(parents=True, exist_ok=True)

    n_conflict_xy = int(xy_groups["has_thematic_conflict"].sum()) if not xy_groups.empty else 0
    n_conflict_xy_year = (
        int(xy_year_groups["has_thematic_conflict"].sum()) if not xy_year_groups.empty else 0
    )

    lines = [
        "# Grupos XY para nueva fuente puntual",
        "",
        f"Fecha de ejecucion: {fecha}",
        "",
        "## Proposito",
        "",
        (
            "Este modulo crea identificadores espaciales estables para auditar "
            "las nuevas fuentes por coordenada, anio y Clase/GranClase sin tocar "
            "el flujo original."
        ),
        "",
        "## Configuracion",
        "",
        f"- YAML: `{config_path}`",
        f"- GeoPackage entrada: `{cfg['input_gpkg']}`",
        f"- Capa entrada: `{cfg['input_layer']}`",
        f"- Namespace de IDs: `{cfg['id_namespace']}`",
        f"- CRS esperado: `{cfg['expected_crs']}`",
        f"- Precision de coordenadas: `{cfg['coordinate_precision']}`",
        "",
        "## Identificadores generados",
        "",
        "- `xy_group_id`: Longitud + Latitud.",
        "- `xy_year_group_id`: Longitud + Latitud + Año.",
        "- `xy_class_group_id`: Longitud + Latitud + Año + Clase + GranClase.",
        "",
        "Los IDs incluyen namespace y hash para evitar colisiones con el proceso original.",
        "",
        "## Resumen",
        "",
        "| Metrica | Valor |",
        "|---|---:|",
        f"| Registros | {len(records):,} |",
        f"| Grupos XY | {len(xy_groups):,} |",
        f"| Grupos XY-Anio | {len(xy_year_groups):,} |",
        f"| Grupos XY-Anio-Clase | {len(xy_class_groups):,} |",
        f"| XY con conflicto tematico | {n_conflict_xy:,} |",
        f"| XY-Anio con conflicto tematico | {n_conflict_xy_year:,} |",
        "",
        "## Distribucion por clase",
        "",
        dataframe_a_markdown(class_dist.head(20)),
        "",
        "## Calidad de campos configurados",
        "",
        dataframe_a_markdown(nulls),
        "",
        "## Salidas",
        "",
        f"- GeoPackage: `{cfg['output_gpkg']}`",
        f"- Tablas: `{cfg['tables_dir']}`",
        f"- Reporte: `{report_path}`",
        "",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")


def guardar_salidas(
    cfg: dict[str, Any],
    records: gpd.GeoDataFrame,
    xy_groups: pd.DataFrame,
    xy_year_groups: pd.DataFrame,
    xy_class_groups: pd.DataFrame,
    nulls: pd.DataFrame,
    bbox: pd.DataFrame,
    class_dist: pd.DataFrame,
    group_dist: pd.DataFrame,
    year_dist: pd.DataFrame,
) -> None:
    output_gpkg = cfg["output_gpkg"]
    tables_dir = cfg["tables_dir"]
    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    drop_aux = [c for c in ["_lon_xy", "_lat_xy", "_year_xy", "_class_xy", "_class_group_xy"] if c in records]
    records_out = records.drop(columns=drop_aux)

    if output_gpkg.exists():
        output_gpkg.unlink()

    clean_for_gpkg(records_out).to_file(
        output_gpkg,
        layer=cfg["layers"]["records"],
        driver="GPKG",
    )

    write_table_to_gpkg(xy_groups, output_gpkg, cfg["layers"]["xy_groups"])
    write_table_to_gpkg(xy_year_groups, output_gpkg, cfg["layers"]["xy_year_groups"])
    write_table_to_gpkg(xy_class_groups, output_gpkg, cfg["layers"]["xy_class_groups"])
    write_table_to_gpkg(nulls, output_gpkg, "field_quality")
    write_table_to_gpkg(bbox, output_gpkg, "bbox_summary")

    pd.DataFrame(
        [
            {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "input_gpkg": str(cfg["input_gpkg"]),
                "input_layer": cfg["input_layer"],
                "output_gpkg": str(output_gpkg),
                "records": len(records_out),
                "xy_groups": len(xy_groups),
                "xy_year_groups": len(xy_year_groups),
                "xy_class_groups": len(xy_class_groups),
                "id_namespace": cfg["id_namespace"],
                "coordinate_precision": cfg["coordinate_precision"],
            }
        ]
    ).to_csv(tables_dir / "xy_groups_audit_summary.csv", index=False, encoding="utf-8-sig")

    pd.DataFrame(records_out.drop(columns=[records_out.geometry.name], errors="ignore")).to_csv(
        tables_dir / "xy_group_records.csv",
        index=False,
        encoding="utf-8-sig",
    )
    xy_groups.to_csv(tables_dir / "xy_groups.csv", index=False, encoding="utf-8-sig")
    xy_year_groups.to_csv(tables_dir / "xy_year_groups.csv", index=False, encoding="utf-8-sig")
    xy_class_groups.to_csv(tables_dir / "xy_class_groups.csv", index=False, encoding="utf-8-sig")
    nulls.to_csv(tables_dir / "field_quality.csv", index=False, encoding="utf-8-sig")
    bbox.to_csv(tables_dir / "bbox_summary.csv", index=False, encoding="utf-8-sig")
    class_dist.to_csv(tables_dir / "records_by_class_code.csv", index=False, encoding="utf-8-sig")
    group_dist.to_csv(tables_dir / "records_by_class_group_code.csv", index=False, encoding="utf-8-sig")
    year_dist.to_csv(tables_dir / "records_by_year.csv", index=False, encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera grupos XY estables para nuevas fuentes puntuales."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_RELATIVE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = resolver_config_path(args.config)
    config = cargar_yaml(config_path)
    project_root = resolver_project_root(config, config_path)
    cfg = validar_config(config, project_root)

    print("============================================================")
    print("PGBM - Grupos XY para nuevas fuentes")
    print("============================================================")
    print(f"Config: {config_path}")
    print(f"GeoPackage entrada: {cfg['input_gpkg']}")
    print(f"Capa entrada: {cfg['input_layer']}")
    print(f"Namespace: {cfg['id_namespace']}")
    print(f"Salida GPKG: {cfg['output_gpkg']}")

    if not cfg["input_gpkg"].exists():
        raise FileNotFoundError(f"No existe el GeoPackage de entrada: {cfg['input_gpkg']}")

    gdf = gpd.read_file(cfg["input_gpkg"], layer=cfg["input_layer"])
    validar_campos(gdf, cfg["fields"])
    gdf = preparar_geometria(
        gdf,
        cfg["expected_crs"],
        cfg["fields"]["longitude"],
        cfg["fields"]["latitude"],
        cfg["coordinate_precision"],
    )
    records = agregar_ids(gdf, cfg)

    xy_groups = build_xy_groups(records, cfg)
    xy_year_groups = build_xy_year_groups(records, cfg)
    xy_class_groups = build_xy_class_groups(records, cfg)
    nulls = tabla_nulos(records, cfg["fields"])

    lon = cfg["fields"]["longitude"]
    lat = cfg["fields"]["latitude"]
    bbox = pd.DataFrame(
        [
            {
                "lon_min": records[lon].min(),
                "lon_max": records[lon].max(),
                "lat_min": records[lat].min(),
                "lat_max": records[lat].max(),
                "crs": str(records.crs),
            }
        ]
    )

    tables_dir = cfg["tables_dir"]
    tables_dir.mkdir(parents=True, exist_ok=True)
    class_dist = export_count(records, cfg["fields"]["class_code"], tables_dir / "records_by_class_code.csv")
    group_dist = export_count(
        records,
        cfg["fields"]["class_group_code"],
        tables_dir / "records_by_class_group_code.csv",
    )
    year_dist = export_count(records, cfg["fields"]["year"], tables_dir / "records_by_year.csv")

    guardar_salidas(
        cfg,
        records,
        xy_groups,
        xy_year_groups,
        xy_class_groups,
        nulls,
        bbox,
        class_dist,
        group_dist,
        year_dist,
    )
    generar_reporte(cfg, config_path, records, xy_groups, xy_year_groups, xy_class_groups, nulls, class_dist)

    print("\nDone.")
    print(f"Registros: {len(records):,}")
    print(f"Grupos XY: {len(xy_groups):,}")
    print(f"Grupos XY-Anio: {len(xy_year_groups):,}")
    print(f"Grupos XY-Anio-Clase: {len(xy_class_groups):,}")
    print(f"Tablas: {cfg['tables_dir']}")
    print(f"Reporte: {cfg['report_md']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
