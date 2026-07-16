# Preparación de insumos para GEE - nueva fuente puntual

Fecha de ejecución: 2026-07-16 00:27:32

## Propósito

Este módulo prepara una fuente puntual normalizada e independiente para extracción Sentinel-2 Surface Reflectance en Google Earth Engine.

## Configuración usada

- Configuración YAML: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/config/a3_auditorias_nuevas_fuentes/caso_SINAC/config_sinac_src10_2021.yaml`
- GeoPackage de entrada: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_SINAC/xy_groups/sinac_src10_2021_xy_groups_outputs.gpkg`
- Capa de entrada: `sinac_src10_records_with_xy_groups`
- CRS de trabajo: `EPSG:4326`
- Decimales de coordenadas: `6`

## Unidad de extracción

```text
Longitud + Latitud + Año
```

Si el GeoPackage de entrada proviene del modulo de grupos XY, las columnas `xy_group_id`, `xy_year_group_id` y `xy_class_group_id` se conservan en registros elegibles y unidades de extraccion.

## Resumen

| Métrica | Valor |
|---|---:|
| Registros de entrada | 19,474 |
| Registros elegibles | 19,474 |
| Unidades únicas Longitud-Latitud-Año | 19,455 |
| Extracciones redundantes evitadas | 19 |
| Unidades con posible conflicto temático | 19 |
| Batch size | 50,000 |
| Batches generados | 1 |

## Salidas principales

- GeoPackage con registros elegibles y `extract_id`: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_SINAC/gee_input/puntos_sinac_src10_2021_con_extract_id.gpkg`
- Capa: `puntos_sinac_src10_2021_con_extract_id`
- CSV de unidades únicas para GEE: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_SINAC/gee_input/s2_sr_extract_units_sinac_src10_2021.csv`
- Índice de batches: `                              batch_id  ...                                          batch_csv
0  s2sr_units_CRI_2021_SRC10_batch_001  ...  /media/estb/PGB_disco/PGBM_actividad_1_diagnos...

[1 rows x 6 columns]`
