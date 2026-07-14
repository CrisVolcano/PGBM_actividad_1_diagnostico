# Grupos XY para nueva fuente puntual

Fecha de ejecucion: 2026-07-14 09:41:49

## Proposito

Este modulo crea identificadores espaciales estables para auditar las nuevas fuentes por coordenada, anio y Clase/GranClase sin tocar el flujo original.

## Configuracion

- YAML: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/config/a3_auditorias_nuevas_fuentes/config_sinac_malla_entrenamientos_2021.yaml`
- GeoPackage entrada: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/preparacion/preparacion_datos_sinac_auditoria_espectral.gpkg`
- Capa entrada: `preparacion_datos_sinac_auditoria_espectral`
- Namespace de IDs: `SRC10_CRI_2021`
- CRS esperado: `EPSG:4326`
- Precision de coordenadas: `6`

## Identificadores generados

- `xy_group_id`: Longitud + Latitud.
- `xy_year_group_id`: Longitud + Latitud + Año.
- `xy_class_group_id`: Longitud + Latitud + Año + Clase + GranClase.

Los IDs incluyen namespace y hash para evitar colisiones con el proceso original.

## Resumen

| Metrica | Valor |
|---|---:|
| Registros | 19,474 |
| Grupos XY | 19,455 |
| Grupos XY-Anio | 19,455 |
| Grupos XY-Anio-Clase | 19,474 |
| XY con conflicto tematico | 19 |
| XY-Anio con conflicto tematico | 19 |

## Distribucion por clase

|   Clase |   records |   percentage |
|--------:|----------:|-------------:|
|       9 |      8489 |      43.5915 |
|      16 |      5928 |      30.4406 |
|       4 |      1587 |       8.1493 |
|       8 |      1179 |       6.0542 |
|       2 |       903 |       4.637  |
|       6 |       800 |       4.108  |
|      11 |       409 |       2.1002 |
|      10 |       150 |       0.7703 |
|       1 |        29 |       0.1489 |

## Calidad de campos configurados

| logical_field    | field             | present   |   nulls |   empty_strings |   pct_null_or_empty |
|:-----------------|:------------------|:----------|--------:|----------------:|--------------------:|
| id               | id_registro       | True      |       0 |               0 |                   0 |
| source           | Fuente            | True      |       0 |               0 |                   0 |
| source_id        | id_fuente         | True      |       0 |               0 |                   0 |
| year             | Año               | True      |       0 |               0 |                   0 |
| country          | Pais_es           | True      |       0 |               0 |                   0 |
| country_code     | Pais_cod3         | True      |       0 |               0 |                   0 |
| longitude        | Longitud          | True      |       0 |               0 |                   0 |
| latitude         | Latitud           | True      |       0 |               0 |                   0 |
| class_code       | Clase             | True      |       0 |               0 |                   0 |
| class_group_code | GranClase         | True      |       0 |               0 |                   0 |
| class_name       | nombre_clase      | True      |       0 |               0 |                   0 |
| class_group_name | nombre_gran_clase | True      |       0 |               0 |                   0 |

## Salidas

- GeoPackage: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/xy_groups/sinac_src10_2021_xy_groups_outputs.gpkg`
- Tablas: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/outputs/tables/a3_auditorias_nuevas_fuentes/xy_groups`
- Reporte: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/outputs/reports/a3_auditorias_nuevas_fuentes/xy_groups/xy_groups_sinac_src10_2021_report.md`
