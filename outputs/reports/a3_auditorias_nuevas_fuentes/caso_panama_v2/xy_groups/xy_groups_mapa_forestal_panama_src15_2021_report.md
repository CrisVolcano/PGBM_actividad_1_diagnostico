# Grupos XY para nueva fuente puntual

Fecha de ejecucion: 2026-07-16 00:20:36

## Proposito

Este modulo crea identificadores espaciales estables para auditar las nuevas fuentes por coordenada, anio y Clase/GranClase sin tocar el flujo original.

## Configuracion

- YAML: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/config/a3_auditorias_nuevas_fuentes/caso_panama_v2/config_mapa_forestal_panama_2021_a1.yaml`
- GeoPackage entrada: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_panama_v2/homologacion_a1/mapa_forestal_panama_src15_2021_homologado_a1.gpkg`
- Capa entrada: `mapa_forestal_panama_src15_2021_homologado_a1`
- Namespace de IDs: `SRC15_PAN_2021`
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
| Registros | 12,551 |
| Grupos XY | 12,551 |
| Grupos XY-Anio | 12,551 |
| Grupos XY-Anio-Clase | 12,551 |
| XY con conflicto tematico | 0 |
| XY-Anio con conflicto tematico | 0 |

## Distribucion por clase

|   Clase |   records |   percentage |
|--------:|----------:|-------------:|
|     332 |      4709 |      37.5189 |
|     412 |      2893 |      23.05   |
|     444 |      1571 |      12.5169 |
|     430 |      1122 |       8.9395 |
|     411 |       787 |       6.2704 |
|     210 |       366 |       2.9161 |
|     110 |       279 |       2.2229 |
|     442 |       210 |       1.6732 |
|     331 |       167 |       1.3306 |
|     311 |       143 |       1.1394 |
|     121 |       102 |       0.8127 |
|     313 |        79 |       0.6294 |
|     122 |        62 |       0.494  |
|     325 |        25 |       0.1992 |
|     314 |        24 |       0.1912 |
|     220 |         6 |       0.0478 |
|     323 |         5 |       0.0398 |
|     212 |         1 |       0.008  |

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

- GeoPackage: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_panama_v2/xy_groups/mapa_forestal_panama_src15_2021_xy_groups_outputs.gpkg`
- Tablas: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/outputs/tables/a3_auditorias_nuevas_fuentes/caso_panama_v2/xy_groups`
- Reporte: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/outputs/reports/a3_auditorias_nuevas_fuentes/caso_panama_v2/xy_groups/xy_groups_mapa_forestal_panama_src15_2021_report.md`
