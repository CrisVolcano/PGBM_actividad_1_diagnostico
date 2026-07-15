# Preparación de insumos para GEE - nueva fuente puntual

Fecha de ejecución: 2026-07-14 22:38:17

## Propósito

Este módulo prepara una fuente puntual normalizada e independiente para extracción Sentinel-2 Surface Reflectance en Google Earth Engine.

## Configuración usada

- Configuración YAML: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/config/a3_auditorias_nuevas_fuentes/caso_panama/config_mapa_forestal_panama_2021.yaml`
- GeoPackage de entrada: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_panama/xy_groups/mapa_forestal_panama_src15_2021_xy_groups_outputs.gpkg`
- Capa de entrada: `mapa_forestal_panama_src15_records_with_xy_groups`
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
| Registros de entrada | 12,551 |
| Registros elegibles | 12,551 |
| Unidades únicas Longitud-Latitud-Año | 12,551 |
| Extracciones redundantes evitadas | 0 |
| Unidades con posible conflicto temático | 0 |
| Batch size | 50,000 |
| Batches generados | 1 |

## Salidas principales

- GeoPackage con registros elegibles y `extract_id`: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_panama/gee_input/puntos_mapa_forestal_panama_src15_2021_con_extract_id.gpkg`
- Capa: `puntos_mapa_forestal_panama_src15_2021_con_extract_id`
- CSV de unidades únicas para GEE: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_panama/gee_input/s2_sr_extract_units_mapa_forestal_panama_src15_2021.csv`
- Índice de batches: `                              batch_id  ...                                          batch_csv
0  s2sr_units_PAN_2021_SRC15_batch_001  ...  /media/estb/PGB_disco/PGBM_actividad_1_diagnos...

[1 rows x 6 columns]`
