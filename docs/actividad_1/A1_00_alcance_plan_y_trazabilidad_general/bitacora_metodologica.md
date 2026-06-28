# Bitácora metodológica

## Proyecto

PGBM - Actividad 1: Diagnóstico regional de aptitud de fuentes y vacíos de información.

## Propósito

Registrar decisiones técnicas, metodológicas y operativas tomadas durante la implementación del proyecto.

## Decisiones iniciales

### Configuración inicial del proyecto

Se crea la estructura base del proyecto en:

/media/estb/PGB_disco/PGBM_actividad_1_diagnostico

La estructura separa:

- datos originales en `data/raw/`;
- datos intermedios en `data/interim/`;
- datos procesados en `data/processed/`;
- scripts en `src/`;
- notebooks en `notebooks/`;
- reportes, tablas, figuras y mapas en `outputs/`;
- documentación en `docs/`;
- bitácoras y logs en `logs/`.

## Criterio metodológico inicial

No se modifican datos originales. Toda transformación futura deberá generar archivos nuevos en carpetas intermedias o procesadas.
