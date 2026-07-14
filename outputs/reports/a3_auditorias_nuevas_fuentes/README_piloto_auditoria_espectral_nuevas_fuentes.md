# Piloto auditoria espectral nuevas fuentes

Estructura del piloto SINAC SRC10 2021.

## Carpetas

- `src/actividad_3/a3_auditorias_nuevas_fuentes/`: codigos Python del flujo.
- `config/a3_auditorias_nuevas_fuentes/`: configuracion YAML del flujo.
- `scripts/gee/a3_auditorias_nuevas_fuentes/`: JavaScript para Google Earth Engine.
- `data/processed/a3_auditorias_nuevas_fuentes/raw/`: datos originales de entrada.
- `data/processed/a3_auditorias_nuevas_fuentes/`: datos normalizados intermedios.
- `data/processed/a3_auditorias_nuevas_fuentes/gee_exports/`: CSV descargados/exportados desde Google Earth Engine.
- `data/processed/a3_auditorias_nuevas_fuentes/gee_input/`: insumos generados para correr GEE, batches y tablas de control.
- `outputs/reports/a3_auditorias_nuevas_fuentes/`: reportes metodologicos y de control.
- `logs/a3_auditorias_nuevas_fuentes/`: bitacoras de ejecucion.

## Comandos principales

Desde esta carpeta del piloto:

```bash
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/01_preparar_sinac_auditoria_espectral.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/02_xy_groups_nuevas_fuentes.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/03_s2_sr_gee_input_nuevas_fuentes_caso_SINAC.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/04_generate_gee_export_report_sinac_src10_2021.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/05_join_s2sr_to_sinac_src10_2021_records.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/06_s2sr_spectral_class_audit_sinac_src10_2021.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/08_scoring_integral_nuevas_fuentes.py
conda run -n pgbm_actividad1 python src/actividad_3/a3_auditorias_nuevas_fuentes/07_generate_project_html_docs_sinac_src10_2021.py
```

## Grupos XY para nuevas fuentes

El paso `src/actividad_3/a3_auditorias_nuevas_fuentes/02_xy_groups_nuevas_fuentes.py` genera identificadores estables
para auditar por coordenada y por `Clase`/`GranClase` sin depender del flujo
original de `PGBM_actividad_1_diagnostico`.

Identificadores:

- `xy_group_id`: Longitud + Latitud.
- `xy_year_group_id`: Longitud + Latitud + Año.
- `xy_class_group_id`: Longitud + Latitud + Año + Clase + GranClase.

Los IDs usan el namespace configurado en
`config/a3_auditorias_nuevas_fuentes/config_sinac_malla_entrenamientos_2021.yaml` para evitar colisiones con
grupos XY de otros procesos. Las salidas quedan en:

```text
data/processed/a3_auditorias_nuevas_fuentes/xy_groups/
data/processed/a3_auditorias_nuevas_fuentes/xy_groups/tables/
outputs/reports/a3_auditorias_nuevas_fuentes/xy_groups/xy_groups_sinac_src10_2021_report.md
```

El paso de preparación GEE usa esta salida cuando
`xy_groups.use_for_gee_input: true` en el YAML.

## Auditorías integradas y scoring

El paso `src/actividad_3/a3_auditorias_nuevas_fuentes/08_scoring_integral_nuevas_fuentes.py` adapta el cierre del
flujo original a la fuente SINAC. Trabaja por `xy_group_id` y combina criterios
temporal, espacial, temático/semántico, espectral, confiabilidad,
representatividad y fuente.

Salidas:

```text
data/processed/a3_auditorias_nuevas_fuentes/quality_scoring/
data/processed/a3_auditorias_nuevas_fuentes/quality_scoring/tables/
outputs/reports/a3_auditorias_nuevas_fuentes/quality_scoring/quality_scoring_sinac_src10_2021_report.md
```

El JavaScript para Earth Engine esta en:

```text
scripts/gee/a3_auditorias_nuevas_fuentes/s2_sr_monthly_s2cloudless_export_sinac_src10_2021.js
```
