# Unión de registros SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica (SRC10 CRI 2021) con valores espectrales Sentinel-2 SR

Fecha de ejecución: 2026-07-16 00:27:59

## 1. Propósito

Este módulo une los registros originales/elegibles de la fuente SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica (SRC10 CRI 2021) con los valores espectro-temporales mensuales exportados desde Google Earth Engine.

La llave de unión es `extract_id`, que representa la unidad única de extracción definida como `Longitud + Latitud + Año`.

## 2. Entradas principales

| Insumo | Ruta / valor |
|---|---|
| GPKG de registros con `extract_id` | `data/processed/a3_auditorias_nuevas_fuentes/caso_SINAC/gee_input/puntos_sinac_src10_2021_con_extract_id.gpkg` |
| Capa de referencia | `puntos_sinac_src10_2021_con_extract_id` |
| Carpeta de CSV GEE | `data/processed/a3_auditorias_nuevas_fuentes/caso_SINAC/gee_exports` |
| Prefijo de CSV procesados | `pgbm_s2sr_monthly_s2cloudless_sinac_src10_2021` |

## 3. Salidas principales

| Producto | Ruta |
|---|---|
| GeoPackage final | `data/processed/a3_auditorias_nuevas_fuentes/caso_SINAC/s2sr_join/sinac_src10_2021_s2sr_join_outputs.gpkg` |
| Tablas de control CSV | `outputs/tables/a3_auditorias_nuevas_fuentes/caso_SINAC/s2sr_join` |
| Reporte Markdown | `outputs/reports/a3_auditorias_nuevas_fuentes/caso_SINAC/s2sr_join/join_s2sr_to_sinac_src10_2021_records_report.md` |

## 4. Capas y tablas generadas

| capa_tabla                            | tipo          | unidad            |   filas | descripcion                                                                                    |
|:--------------------------------------|:--------------|:------------------|--------:|:-----------------------------------------------------------------------------------------------|
| sinac_src10_records_s2sr_full         | capa espacial | registro original |   19474 | Columnas originales + bandas/índices mensuales + métricas anuales.                             |
| sinac_src10_records_s2sr_reduced      | capa espacial | registro original |   19474 | Capa práctica para revisión: campos clave + índices mensuales + observaciones + resumen anual. |
| sinac_src10_records_s2sr_annual       | capa espacial | registro original |   19474 | Resumen anual por registro original.                                                           |
| sinac_src10_extract_units_s2sr_annual | capa espacial | extract_id único  |   19455 | Resumen anual sin duplicados por unidad espectral extraída en GEE.                             |
| validation_summary                    | tabla         | control           |       1 | Resumen de validación.                                                                         |
| input_files_inventory                 | tabla         | archivo CSV       |       1 | Inventario de CSV.                                                                             |
| missing_extract_id_in_gee             | tabla         | extract_id        |       0 | Extract ID faltantes en GEE.                                                                   |
| extra_extract_id_in_gee               | tabla         | extract_id        |       0 | Extract ID extra en GEE.                                                                       |
| duplicate_gee_extract_id_month        | tabla         | extract_id + mes  |       0 | Duplicados en CSV GEE.                                                                         |
| monthly_clean_obs_summary             | tabla         | mes               |      12 | Control mensual de observaciones limpias.                                                      |
| thematic_extract_units_summary        | tabla         | clase             |       9 | Resumen temático de unidades/registros.                                                        |

## 5. Resumen de validación

| indicador                            |   valor |
|:-------------------------------------|--------:|
| Filas originales                     |   19474 |
| Filas capa completa                  |   19474 |
| Filas capa reducida                  |   19474 |
| Filas capa anual                     |   19474 |
| Filas capa anual sin duplicados      |   19455 |
| Extract ID únicos originales         |   19455 |
| Extract ID únicos en GEE             |   19455 |
| Extract ID faltantes en GEE          |       0 |
| Extract ID extra en GEE              |       0 |
| Duplicados GEE por extract_id + mes  |       0 |
| CSV seleccionados para procesamiento |       1 |

## 6. Control mensual de observaciones limpias

|   month |   rows |   extract_ids |   rows_zero_clean_obs |   median_clean_obs |   max_clean_obs |   pct_zero_clean_obs |
|--------:|-------:|--------------:|----------------------:|-------------------:|----------------:|---------------------:|
|       1 |  19455 |         19455 |                    10 |                  4 |               6 |               0.0514 |
|       2 |  19455 |         19455 |                    11 |                  4 |               6 |               0.0565 |
|       3 |  19455 |         19455 |                     7 |                  5 |               6 |               0.036  |
|       4 |  19455 |         19455 |                    24 |                  3 |               4 |               0.1234 |
|       5 |  19455 |         19455 |                   604 |                  2 |               4 |               3.1046 |
|       6 |  19455 |         19455 |                    39 |                  3 |               5 |               0.2005 |
|       7 |  19455 |         19455 |                    68 |                  3 |               5 |               0.3495 |
|       8 |  19455 |         19455 |                   786 |                  2 |               5 |               4.0401 |
|       9 |  19455 |         19455 |                   264 |                  3 |               6 |               1.357  |
|      10 |  19455 |         19455 |                   411 |                  3 |               5 |               2.1126 |
|      11 |  19455 |         19455 |                     6 |                  3 |               6 |               0.0308 |
|      12 |  19455 |         19455 |                     0 |                  5 |               6 |               0      |

## 7. Resumen temático

|   GranClase | nombre_gran_clase   |   Clase | nombre_clase              |   extract_units_or_records |
|------------:|:--------------------|--------:|:--------------------------|---------------------------:|
|           9 | Cultivos            |       9 | Cultivos                  |                       8489 |
|          16 | Edificaciones       |      16 | Edificaciones             |                       5928 |
|           1 | Forestal            |       4 | Bosque secundario deciduo |                       1587 |
|           8 | Pastos              |       8 | Pastos                    |                       1179 |
|           1 | Forestal            |       2 | Bosque secundario         |                        903 |
|           1 | Forestal            |       6 | Manglar                   |                        800 |
|          11 | Humedal Palustre    |      11 | Humedal Palustre          |                        409 |
|          10 | Agua                |      10 | Agua                      |                        150 |
|           1 | Forestal            |       1 | Bosque maduro             |                         29 |

## 8. Nota metodológica

Los CSV de GEE llegan en formato largo, con una fila por `extract_id` y mes. Este módulo transforma los datos a formato ancho para unirlos con los registros originales.

Los valores `-9999` exportados desde GEE se interpretan como ausencia de dato válido y se convierten a nulos antes de calcular métricas anuales. El campo `n_obs_clean` conserva el valor cero porque indica explícitamente meses sin observaciones limpias.

La capa completa conserva todos los registros originales, incluyendo casos en que varios registros comparten un mismo `extract_id`. La capa de unidades anuales elimina duplicados por `extract_id` para análisis espectral sin sobreponderar puntos repetidos.
