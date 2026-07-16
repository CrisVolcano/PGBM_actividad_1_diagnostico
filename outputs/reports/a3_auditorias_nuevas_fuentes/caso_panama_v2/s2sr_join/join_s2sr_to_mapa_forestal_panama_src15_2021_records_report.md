# Unión de registros MIAMBIENTE - Cultivos Mapa Panamá (SRC15 PAN 2021) con valores espectrales Sentinel-2 SR

Fecha de ejecución: 2026-07-16 00:21:01

## 1. Propósito

Este módulo une los registros originales/elegibles de la fuente MIAMBIENTE - Cultivos Mapa Panamá (SRC15 PAN 2021) con los valores espectro-temporales mensuales exportados desde Google Earth Engine.

La llave de unión es `extract_id`, que representa la unidad única de extracción definida como `Longitud + Latitud + Año`.

## 2. Entradas principales

| Insumo | Ruta / valor |
|---|---|
| GPKG de registros con `extract_id` | `data/processed/a3_auditorias_nuevas_fuentes/caso_panama_v2/gee_input/puntos_mapa_forestal_panama_src15_2021_con_extract_id.gpkg` |
| Capa de referencia | `puntos_mapa_forestal_panama_src15_2021_con_extract_id` |
| Carpeta de CSV GEE | `data/processed/a3_auditorias_nuevas_fuentes/caso_panama_v2/gee_exports` |
| Prefijo de CSV procesados | `pgbm_s2sr_monthly_s2cloudless_mapa_forestal_panama_src15_2021` |

## 3. Salidas principales

| Producto | Ruta |
|---|---|
| GeoPackage final | `data/processed/a3_auditorias_nuevas_fuentes/caso_panama_v2/s2sr_join/mapa_forestal_panama_src15_2021_s2sr_join_outputs.gpkg` |
| Tablas de control CSV | `outputs/tables/a3_auditorias_nuevas_fuentes/caso_panama_v2/s2sr_join` |
| Reporte Markdown | `outputs/reports/a3_auditorias_nuevas_fuentes/caso_panama_v2/s2sr_join/join_s2sr_to_mapa_forestal_panama_src15_2021_records_report.md` |

## 4. Capas y tablas generadas

| capa_tabla                                           | tipo          | unidad            |   filas | descripcion                                                                                    |
|:-----------------------------------------------------|:--------------|:------------------|--------:|:-----------------------------------------------------------------------------------------------|
| mapa_forestal_panama_src15_records_s2sr_full         | capa espacial | registro original |   12551 | Columnas originales + bandas/índices mensuales + métricas anuales.                             |
| mapa_forestal_panama_src15_records_s2sr_reduced      | capa espacial | registro original |   12551 | Capa práctica para revisión: campos clave + índices mensuales + observaciones + resumen anual. |
| mapa_forestal_panama_src15_records_s2sr_annual       | capa espacial | registro original |   12551 | Resumen anual por registro original.                                                           |
| mapa_forestal_panama_src15_extract_units_s2sr_annual | capa espacial | extract_id único  |   12551 | Resumen anual sin duplicados por unidad espectral extraída en GEE.                             |
| validation_summary                                   | tabla         | control           |       1 | Resumen de validación.                                                                         |
| input_files_inventory                                | tabla         | archivo CSV       |       1 | Inventario de CSV.                                                                             |
| missing_extract_id_in_gee                            | tabla         | extract_id        |       0 | Extract ID faltantes en GEE.                                                                   |
| extra_extract_id_in_gee                              | tabla         | extract_id        |       0 | Extract ID extra en GEE.                                                                       |
| duplicate_gee_extract_id_month                       | tabla         | extract_id + mes  |       0 | Duplicados en CSV GEE.                                                                         |
| monthly_clean_obs_summary                            | tabla         | mes               |      12 | Control mensual de observaciones limpias.                                                      |
| thematic_extract_units_summary                       | tabla         | clase             |      18 | Resumen temático de unidades/registros.                                                        |

## 5. Resumen de validación

| indicador                            |   valor |
|:-------------------------------------|--------:|
| Filas originales                     |   12551 |
| Filas capa completa                  |   12551 |
| Filas capa reducida                  |   12551 |
| Filas capa anual                     |   12551 |
| Filas capa anual sin duplicados      |   12551 |
| Extract ID únicos originales         |   12551 |
| Extract ID únicos en GEE             |   12551 |
| Extract ID faltantes en GEE          |       0 |
| Extract ID extra en GEE              |       0 |
| Duplicados GEE por extract_id + mes  |       0 |
| CSV seleccionados para procesamiento |       1 |

## 6. Control mensual de observaciones limpias

|   month |   rows |   extract_ids |   rows_zero_clean_obs |   median_clean_obs |   max_clean_obs |   pct_zero_clean_obs |
|--------:|-------:|--------------:|----------------------:|-------------------:|----------------:|---------------------:|
|       1 |  12551 |         12551 |                    87 |                  4 |              12 |               0.6932 |
|       2 |  12551 |         12551 |                   322 |                  5 |              12 |               2.5655 |
|       3 |  12551 |         12551 |                   131 |                  4 |              12 |               1.0437 |
|       4 |  12551 |         12551 |                   621 |                  2 |               8 |               4.9478 |
|       5 |  12551 |         12551 |                  7607 |                  0 |               4 |              60.6087 |
|       6 |  12551 |         12551 |                 10110 |                  0 |               6 |              80.5514 |
|       7 |  12551 |         12551 |                  1769 |                  2 |               8 |              14.0945 |
|       8 |  12551 |         12551 |                  6917 |                  0 |               3 |              55.1111 |
|       9 |  12551 |         12551 |                  1981 |                  2 |               8 |              15.7836 |
|      10 |  12551 |         12551 |                  3617 |                  1 |               6 |              28.8184 |
|      11 |  12551 |         12551 |                  2204 |                  1 |               4 |              17.5604 |
|      12 |  12551 |         12551 |                  1157 |                  2 |               8 |               9.2184 |

## 7. Resumen temático

|   GranClase | nombre_gran_clase                            |   Clase | nombre_clase                                    |   extract_units_or_records |
|------------:|:---------------------------------------------|--------:|:------------------------------------------------|---------------------------:|
|          33 | Cultivos extensivos, Pastizales y matorrales |     332 | Pastizales naturales y cultivados               |                       4709 |
|          41 | Bosque latifoliado y mixto                   |     412 | Latifoliado secundario húmedo                   |                       2893 |
|          44 | Otros arbóreo en tierras no agrícola         |     444 | Regeneración forestal                           |                       1571 |
|          43 | Manglares                                    |     430 | Manglares                                       |                       1122 |
|          41 | Bosque latifoliado y mixto                   |     411 | Latifoliado maduro húmedo                       |                        787 |
|          21 | Cuerpos de Agua                              |     210 | Cuerpos de Agua                                 |                        366 |
|          11 | Urbano                                       |     110 | Urbano                                          |                        279 |
|          44 | Otros arbóreo en tierras no agrícola         |     442 | Plantaciones forestales                         |                        210 |
|          33 | Cultivos extensivos, Pastizales y matorrales |     331 | Granos básicos y hortalizas y otros             |                        167 |
|          31 | Cultivos intensivos No-Arbóreos              |     311 | Palma aceitera                                  |                        143 |
|          12 | Otras tierras                                |     121 | Otros artificializado                           |                        102 |
|          31 | Cultivos intensivos No-Arbóreos              |     313 | Caña de azúcar                                  |                         79 |
|          12 | Otras tierras                                |     122 | Suelo desnudo, arena, rocoso, lava, otros       |                         62 |
|          32 | Cultivos Arbóreos                            |     325 | Otros sistemas agroforestales o silvopastoriles |                         25 |
|          31 | Cultivos intensivos No-Arbóreos              |     314 | Piña                                            |                         24 |
|          22 | Humedales                                    |     220 | Humedales                                       |                          6 |
|          32 | Cultivos Arbóreos                            |     323 | Frutales                                        |                          5 |
|          21 | Cuerpos de Agua                              |     212 | Cuerpos de agua artificial                      |                          1 |

## 8. Nota metodológica

Los CSV de GEE llegan en formato largo, con una fila por `extract_id` y mes. Este módulo transforma los datos a formato ancho para unirlos con los registros originales.

Los valores `-9999` exportados desde GEE se interpretan como ausencia de dato válido y se convierten a nulos antes de calcular métricas anuales. El campo `n_obs_clean` conserva el valor cero porque indica explícitamente meses sin observaciones limpias.

La capa completa conserva todos los registros originales, incluyendo casos en que varios registros comparten un mismo `extract_id`. La capa de unidades anuales elimina duplicados por `extract_id` para análisis espectral sin sobreponderar puntos repetidos.
