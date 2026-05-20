# Unión de registros originales con valores espectrales Sentinel-2 SR

## Módulo 08

Fecha de ejecución: 2026-05-19 13:13:42

## Propósito

Este módulo une los registros originales elegibles con los valores espectrales mensuales de Sentinel-2 SR exportados desde Google Earth Engine.

La unión se realiza mediante el campo `extract_id`, que representa la unidad única de extracción espectral.

## Entradas principales

| Insumo | Ruta / valor |
|---|---|
| GPKG de registros originales | `data/processed/s2_sr_gee_input/puntos_s2_sr_2018_2022.gpkg` |
| Capa de registros originales | `puntos_s2_sr_2018_2022` |
| Carpeta de CSV GEE | `data/raw/PGBM_S2SR_monthly_s2cloudless` |
| Prefijo de CSV procesados | `pgbm_s2sr_monthly_s2cloudless_` |

## Salidas principales

| Producto | Ruta |
|---|---|
| GeoPackage final | `data/processed/s2_sr_original_records_with_spectral/puntos_s2_sr_2018_2022_s2sr_join_outputs.gpkg` |
| Tablas de control | `outputs/tables/s2_sr_original_records_with_spectral` |
| Reporte Markdown | `outputs/reports/s2_sr_original_records_with_spectral/08_s2sr_original_records_join_report.md` |

## Capas y tablas generadas

| capa_tabla                     | tipo          | unidad            |   filas | descripcion                                                                        |
|:-------------------------------|:--------------|:------------------|--------:|:-----------------------------------------------------------------------------------|
| original_records_s2sr_full     | capa espacial | registro original | 1195911 | Versión completa con columnas originales, variables mensuales y resúmenes anuales. |
| original_records_s2sr_reduced  | capa espacial | registro original | 1195911 | Versión práctica con columnas clave e índices mensuales.                           |
| original_records_s2sr_annual   | capa espacial | registro original | 1195911 | Resumen anual por registro original.                                               |
| extract_units_s2sr_annual      | capa espacial | extract_id único  | 1185946 | Resumen anual sin duplicados, equivalente a las unidades extraídas en GEE.         |
| validation_summary             | tabla         | control           |       1 | Resumen de validación de conteos.                                                  |
| input_files_inventory          | tabla         | archivo CSV       |      42 | Inventario de archivos CSV encontrados y procesados.                               |
| missing_extract_id_in_gee      | tabla         | extract_id        |       0 | Extract ID presentes en el GPKG original pero ausentes en GEE.                     |
| extra_extract_id_in_gee        | tabla         | extract_id        |       0 | Extract ID presentes en GEE pero ausentes en el GPKG original.                     |
| duplicate_gee_extract_id_month | tabla         | extract_id + mes  |       0 | Duplicados detectados en los CSV de GEE.                                           |

## Resumen de validación

| indicador                            |   valor |
|:-------------------------------------|--------:|
| Filas originales                     | 1195911 |
| Filas capa completa                  | 1195911 |
| Filas capa reducida                  | 1195911 |
| Filas capa anual                     | 1195911 |
| Filas capa anual sin duplicados      | 1185946 |
| Extract ID únicos originales         | 1185946 |
| Extract ID únicos en GEE             | 1185946 |
| Extract ID faltantes en GEE          |       0 |
| Extract ID extra en GEE              |       0 |
| Duplicados GEE por extract_id + mes  |       0 |
| CSV seleccionados para procesamiento |      42 |

## Grupos de columnas Sentinel-2

| grupo                          | patron                                 | ejemplos                                         | incluido_en                                                                         |
|:-------------------------------|:---------------------------------------|:-------------------------------------------------|:------------------------------------------------------------------------------------|
| Columnas mensuales completas   | s2_MM_variable                         | s2_01_b02, s2_01_ndvi, s2_12_cloudprob           | original_records_s2sr_full                                                          |
| Índices mensuales              | s2_MM_ndvi / s2_MM_ndvi8a / s2_MM_ndre | s2_01_ndvi, s2_06_ndre, s2_12_ndvi8a             | original_records_s2sr_full, original_records_s2sr_reduced                           |
| Resumen anual de observaciones | s2yr_obs_*                             | s2yr_obs_total, s2yr_obs_mean, s2yr_months_obs   | original_records_s2sr_full, original_records_s2sr_annual, extract_units_s2sr_annual |
| Resumen anual de índices       | s2yr_indice_metrica                    | s2yr_ndvi_mean, s2yr_ndvi_median, s2yr_ndre_mean | original_records_s2sr_full, original_records_s2sr_annual, extract_units_s2sr_annual |

## Interpretación de las capas

- `original_records_s2sr_full` conserva toda la trazabilidad: columnas originales, variables mensuales, bandas, índices, observaciones y resúmenes anuales.
- `original_records_s2sr_reduced` es una versión práctica para QGIS: mantiene columnas clave e índices mensuales, pero excluye bandas, observaciones mensuales y probabilidad mensual de nube.
- `original_records_s2sr_annual` resume cada registro original con métricas anuales de observaciones, nube e índices.
- `extract_units_s2sr_annual` elimina duplicados por `extract_id` y representa directamente las unidades espectrales extraídas en GEE.

## Nota metodológica

Los CSV de GEE están en formato largo, con una fila por `extract_id` y mes. Este módulo transforma esa información a formato ancho.

Los valores `-9999` exportados desde GEE se interpretan como ausencia de dato válido y se convierten a valores nulos para el cálculo de métricas anuales.

La capa de registros originales conserva duplicados porque corresponden a registros reales del flujo de datos. La capa sin duplicados se incluye para análisis espectral sin sobreponderar unidades repetidas.

Este módulo no modifica los datos originales de entrada. Todas las salidas se generan como productos derivados.
