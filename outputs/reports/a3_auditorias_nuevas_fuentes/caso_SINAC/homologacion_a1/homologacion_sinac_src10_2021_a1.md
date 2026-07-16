# Homologación temática A1 - caso SINAC

Fecha: 2026-07-16 00:26:52

- Entrada: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_SINAC/preparacion/preparacion_sinac_src10_2021.gpkg`
- Salida: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/processed/a3_auditorias_nuevas_fuentes/caso_SINAC/homologacion_a1/sinac_src10_2021_homologado_a1.gpkg`

## Resumen

|   records |   source_classes |   homologated_classes |   unmatched_classes |   records_requiring_review |
|----------:|-----------------:|----------------------:|--------------------:|---------------------------:|
|     19474 |                9 |                     9 |                   0 |                       8489 |

## Clases que requieren revisión

|   Clase |   GranClase | nombre_clase   | nombre_gran_clase   |   id_nivel_0 | nivel_0                     |   id_nivel_1 | nivel_1                         |   id_nivel_2 | nivel_2                               | homologacion_tipo_equivalencia   | homologacion_confianza   | homologacion_nota                                             |
|--------:|------------:|:---------------|:--------------------|-------------:|:----------------------------|-------------:|:--------------------------------|-------------:|:--------------------------------------|:---------------------------------|:-------------------------|:--------------------------------------------------------------|
|       9 |           9 | Cultivos       | Cultivos            |           30 | Tierras de Cultivo y Pastos |           31 | Cultivos intensivos No-Arbóreos |          315 | Otros cultivos intensivos no arbóreos | agregacion                       | baja                     | Clase genérica; puede mezclar cultivos arbóreos y no arbóreos |

## Clases sin homologación

No hay clases sin homologación.

## Regla

Las clases originales SINAC se conservan como `Clase`, `GranClase`, `nombre_clase` y `nombre_gran_clase`. La taxonomía de trabajo A1 se agrega como `id_nivel_0`, `nivel_0`, `id_nivel_1`, `nivel_1`, `id_nivel_2` y `nivel_2`.