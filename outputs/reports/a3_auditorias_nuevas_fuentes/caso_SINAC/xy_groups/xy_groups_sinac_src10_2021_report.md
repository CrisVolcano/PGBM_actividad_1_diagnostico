# Grupos XY para nueva fuente puntual

Fecha de ejecucion: 2026-07-16 00:27:21

## Proposito

Este modulo crea identificadores espaciales estables para auditar las nuevas fuentes por coordenada, anio y Clase/GranClase sin tocar el flujo original.

## Configuracion

- YAML: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/config/a3_auditorias_nuevas_fuentes/caso_SINAC/config_sinac_src10_2021.yaml`
- GeoPackage entrada: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_SINAC/homologacion_a1/sinac_src10_2021_homologado_a1.gpkg`
- Capa entrada: `sinac_src10_2021_homologado_a1`
- Namespace de IDs: `SRC10_CRI_2021_A1`
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

|   id_nivel_2 |   records |   percentage |
|-------------:|----------:|-------------:|
|          315 |      8489 |      43.5915 |
|          110 |      5928 |      30.4406 |
|          414 |      1587 |       8.1493 |
|          332 |      1179 |       6.0542 |
|          412 |       903 |       4.637  |
|          430 |       800 |       4.108  |
|          220 |       409 |       2.1002 |
|          210 |       150 |       0.7703 |
|          411 |        29 |       0.1489 |

## Calidad de campos configurados

| logical_field    | field       | present   |   nulls |   empty_strings |   pct_null_or_empty |
|:-----------------|:------------|:----------|--------:|----------------:|--------------------:|
| id               | id_registro | True      |       0 |               0 |                   0 |
| source           | Fuente      | True      |       0 |               0 |                   0 |
| source_id        | id_fuente   | True      |       0 |               0 |                   0 |
| year             | Año         | True      |       0 |               0 |                   0 |
| country          | Pais_es     | True      |       0 |               0 |                   0 |
| country_code     | Pais_cod3   | True      |       0 |               0 |                   0 |
| longitude        | Longitud    | True      |       0 |               0 |                   0 |
| latitude         | Latitud     | True      |       0 |               0 |                   0 |
| class_code       | id_nivel_2  | True      |       0 |               0 |                   0 |
| class_group_code | id_nivel_1  | True      |       0 |               0 |                   0 |
| class_name       | nivel_2     | True      |       0 |               0 |                   0 |
| class_group_name | nivel_1     | True      |       0 |               0 |                   0 |

## Salidas

- GeoPackage: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_SINAC/xy_groups/sinac_src10_2021_xy_groups_outputs.gpkg`
- Tablas: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/outputs/tables/a3_auditorias_nuevas_fuentes/caso_SINAC/xy_groups`
- Reporte: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/outputs/reports/a3_auditorias_nuevas_fuentes/caso_SINAC/xy_groups/xy_groups_sinac_src10_2021_report.md`
