# Auditorías integradas y scoring multicriterio - nuevas fuentes

Fecha: 2026-07-14 23:38:10

## Alcance

Este módulo adapta metodológicamente el cierre del flujo original a la fuente configurada.
La unidad de decisión es `xy_group_id` y el score total combina criterios temporal, espacial, temático/semántico, espectral, confiabilidad, representatividad y fuente.

## Configuración

- YAML: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/config/a3_auditorias_nuevas_fuentes/caso_panama/config_mapa_forestal_panama_2021.yaml`
- GeoPackage de salida: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_panama/quality_scoring/mapa_forestal_panama_src15_2021_quality_scoring_outputs.gpkg`
- Tablas: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/outputs/tables/a3_auditorias_nuevas_fuentes/caso_panama/quality_scoring`

## Categorías de aptitud

| categoria_aptitud          |   n_xy_groups |   score_mean |   pct_xy_groups |
|:---------------------------|--------------:|-------------:|----------------:|
| entrenamiento_alta         |         12023 |       96.978 |          95.793 |
| entrenamiento_condicionado |           505 |       70.938 |           4.024 |
| referencia_contextual      |            23 |       60     |           0.183 |

## Resumen de componentes del score

| statistic   |   score_temporal |   score_espacial |   score_tematico |   score_espectral |   score_confiabilidad |   score_representatividad |   score_fuente |   score_aptitud_raw |   score_aptitud_total |
|:------------|-----------------:|-----------------:|-----------------:|------------------:|----------------------:|--------------------------:|---------------:|--------------------:|----------------------:|
| count       |            12551 |            12551 |        12551     |         12551     |             12551     |                 12551     |          12551 |            12551    |             12551     |
| min         |              100 |              100 |           74     |            10     |                70     |                    40     |             85 |               76.15 |                60     |
| mean        |              100 |              100 |           99.198 |            91.081 |                89.292 |                    97.491 |             85 |               96.43 |                95.862 |
| median      |              100 |              100 |          100     |           100     |                90     |                   100     |             85 |               98.25 |                98.25  |
| max         |              100 |              100 |          100     |           100     |                90     |                   100     |             85 |               98.25 |                98.25  |

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
