# Auditorías integradas y scoring multicriterio - nuevas fuentes

Fecha: 2026-07-14 09:43:52

## Alcance

Este módulo adapta metodológicamente el cierre del flujo original a la fuente SINAC SRC10 2021.
La unidad de decisión es `xy_group_id` y el score total combina criterios temporal, espacial, temático/semántico, espectral, confiabilidad, representatividad y fuente.

## Configuración

- YAML: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/config/a3_auditorias_nuevas_fuentes/config_sinac_malla_entrenamientos_2021.yaml`
- GeoPackage de salida: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/quality_scoring/sinac_src10_2021_quality_scoring_outputs.gpkg`
- Tablas: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/outputs/tables/a3_auditorias_nuevas_fuentes/quality_scoring`

## Categorías de aptitud

| categoria_aptitud          |   n_xy_groups |   score_mean |   pct_xy_groups |
|:---------------------------|--------------:|-------------:|----------------:|
| entrenamiento_alta         |         16291 |       96.759 |          83.737 |
| entrenamiento_condicionado |          3145 |       70.004 |          16.166 |
| referencia_contextual      |            19 |       57.861 |           0.098 |

## Resumen de componentes del score

| statistic   |   score_temporal |   score_espacial |   score_tematico |   score_espectral |   score_confiabilidad |   score_representatividad |   score_fuente |   score_aptitud_raw |   score_aptitud_total |
|:------------|-----------------:|-----------------:|-----------------:|------------------:|----------------------:|--------------------------:|---------------:|--------------------:|----------------------:|
| count       |            19455 |        19455     |        19455     |         19455     |             19455     |                  19455    |          19455 |           19455     |             19455     |
| min         |              100 |            0     |           55.5   |            30     |                70     |                     40    |             85 |              55.35  |                55.35  |
| mean        |              100 |           99.902 |           99.805 |            80.845 |                86.748 |                     99.48 |             85 |              94.941 |                92.396 |
| median      |              100 |          100     |          100     |           100     |                90     |                    100    |             85 |              98.25  |                98.25  |
| max         |              100 |          100     |          100     |           100     |                90     |                    100    |             85 |              98.25  |                98.25  |

## Pesos usados

| criterion        |   weight |
|:-----------------|---------:|
| temporal         |     0.2  |
| spatial          |     0.2  |
| thematic         |     0.2  |
| spectral         |     0.15 |
| confidence       |     0.1  |
| representativity |     0.1  |
| source           |     0.05 |

## Auditorías generadas

- Estructural/tabular: esquema, campos configurados, duplicados de ID.
- Espacial: CRS, bbox, calidad de coordenadas, duplicados y conflictos XY.
- Temporal: calidad del año y cobertura del año objetivo.
- Temática: distribución Clase/GranClase, representatividad y jerarquía clase-gran clase.
- Semántica: clases residuales o ambiguas por palabras clave.
- Espectral: alertas Sentinel-2 agregadas por `xy_group_id`.
- Scoring: score multicriterio total por `xy_group_id`.
