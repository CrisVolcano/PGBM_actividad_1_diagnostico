# Reporte metodológico y control inicial de exportación GEE Sentinel-2 SR

## 1. Identificación del piloto

| Elemento | Valor |
| --- | --- |
| Fuente | SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica |
| Código fuente | SRC10 |
| `source_id` | 10 |
| País | CRI |
| Año de referencia | 2021 |
| Fecha de generación del reporte | 2026-07-14 09:42:11 |
| Script GEE documentado | `scripts/gee/a3_auditorias_nuevas_fuentes/s2_sr_monthly_s2cloudless_export_sinac_src10_2021.js` |
| Hash SHA256 del JS | `6128941fefb2dfaa89237909e9f9622f9c91a38ad221de933e50b3e550c4165b` |
| Número de líneas del JS | 460 |

## 2. Ubicación de insumos y salidas

Script JavaScript usado en Google Earth Engine:

    scripts/gee/a3_auditorias_nuevas_fuentes/s2_sr_monthly_s2cloudless_export_sinac_src10_2021.js

Carpeta revisada con CSV exportados desde GEE:

    data/processed/a3_auditorias_nuevas_fuentes/gee_exports

Patrón de CSV analizado:

    pgbm_s2sr_monthly_s2cloudless_sinac_src10_2021*.csv

Reporte generado:

    outputs/reports/a3_auditorias_nuevas_fuentes/gee_input/gee_export_report_sinac_src10_2021.md

## 3. Propósito de la exportación

La exportación obtuvo variables espectro-temporales mensuales de Sentinel-2 Surface Reflectance para una fuente puntual independiente incorporada al flujo de auditoría espectral de nuevas fuentes.

La unidad de extracción fue:

    Longitud + Latitud + Año

Este piloto no depende de `grupos_xy`, `Nivel_1` ni `Nivel_2`. La trazabilidad temática se conserva mediante `class_code`, `class_group_code`, `class_name` y `class_group_name`.

## 4. Parámetros principales del JavaScript

| Parámetro | Valor |
| --- | --- |
| `DRIVE_FOLDER` | PGBM_S2SR_monthly_s2cloudless_sinac_src10_2021 |
| `scale` | 20 |
| `CLD_PRB_THRESH` | 50 |
| `NIR_DRK_THRESH` | 0.15 |
| `CLD_PRJ_DIST` | 1 |
| `BUFFER` | 60 |
| `EXPORT_GEOMETRIES` | false |
| `tileScale` | 8 |
| `fileFormat` | CSV |
| `outputName` | `'pgbm_s2sr_monthly_s2cloudless_sinac_src10_2021_' + cleanBatchName` |

## 5. Colecciones de Google Earth Engine

- `COPERNICUS/S2_CLOUD_PROBABILITY`
- `COPERNICUS/S2_SR_HARMONIZED`

La colección `COPERNICUS/S2_SR_HARMONIZED` se usó para reflectancia de superficie y `COPERNICUS/S2_CLOUD_PROBABILITY` para la máscara s2cloudless.

## 6. Batches configurados en GEE

| Batch | run |
| --- | --- |
| `s2sr_units_CRI_2021_SRC10_batch_001` | true |

## 7. Propiedades de punto conservadas

- `extract_id`
- `lon_out`
- `lat_out`
- `year_ref`
- `n_records_extract_unit`
- `country`
- `country_code`
- `source`
- `source_id`
- `class_code`
- `class_group_code`
- `class_name`
- `class_group_name`
- `n_unique_class_code_extract_unit`
- `n_unique_class_group_code_extract_unit`
- `n_unique_class_name_extract_unit`
- `n_unique_class_group_name_extract_unit`
- `has_thematic_conflict`
- `batch_id`

Campos metodológicos agregados:
- `month`
- `year_extraction`
- `s2_collection`
- `cloud_mask_method`
- `cloud_prob_threshold`
- `nir_dark_threshold`
- `cloud_proj_dist_km`
- `buffer_m`
- `scale_m`

## 8. Bandas e índices exportados

- `B2`
- `B3`
- `B4`
- `B5`
- `B6`
- `B7`
- `B8`
- `B8A`
- `B11`
- `B12`
- `NDVI`
- `NDVI8A`
- `NDRE`

Índices calculados:

    NDVI   = (B8  - B4) / (B8  + B4)
    NDVI8A = (B8A - B4) / (B8A + B4)
    NDRE   = (B8A - B5) / (B8A + B5)

## 9. Máscara de nubes, sombras y SCL

La máscara combina probabilidad de nube, píxeles oscuros en NIR, proyección de sombra y exclusión de clases SCL.

| Clase SCL excluida | Descripción |
| --- | --- |
| 6 | Sin descripción |
| 0 | no data |
| 1 | saturated / defective |
| 3 | cloud shadow |
| 8 | cloud medium probability |
| 9 | cloud high probability |
| 10 | cirrus |
| 11 | snow / ice |

## 10. Inventario local de CSV exportados desde GEE

| Métrica | Valor |
| --- | --- |
| Carpeta existe | Sí |
| Número de CSV identificados | 1 |
| Tamaño total aproximado | 105.52 MB |
| Firmas de encabezado distintas | 1 |

| Archivo | Tamaño | Número de columnas |
| --- | --- | --- |
| `pgbm_s2sr_monthly_s2cloudless_sinac_src10_2021_s2sr_units_CRI_2021_SRC10_batch_001.csv` | 105.52 MB | 43 |

## 11. Control inicial del contenido exportado

| Control | Resultado |
| --- | --- |
| Filas exportadas | 233,460 |
| Columnas | 44 |
| CSV analizados | 1 |
| `extract_id` únicos | 19,455 |
| Meses presentes | 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0 |
| Filas esperadas según extract_id × meses | 233,460 |
| Duplicados `extract_id + month` | 0 |
| `year_ref` | 2021 |
| `year_extraction` | 2021 |
| `source_id` | 10 |
| `country_code` | CRI |
| Unidades con posible conflicto temático | 19 |
| Filas con `n_obs_clean = 0` | 2230 |
| Porcentaje con `n_obs_clean = 0` | 0.9552% |
| Mínimo `n_obs_clean` | 0.0 |
| Mediana `n_obs_clean` | 3.0 |
| Máximo `n_obs_clean` | 6.0 |

Columnas requeridas faltantes:
- Ninguna.

## 12. Control mensual de observaciones limpias

| month | rows | extract_ids | rows_zero_clean_obs | median_clean_obs | max_clean_obs | pct_zero_clean_obs |
| --- | --- | --- | --- | --- | --- | --- |
| 1.0 | 19455.0 | 19455.0 | 10.0 | 4.0 | 6.0 | 0.0514 |
| 2.0 | 19455.0 | 19455.0 | 11.0 | 4.0 | 6.0 | 0.0565 |
| 3.0 | 19455.0 | 19455.0 | 7.0 | 5.0 | 6.0 | 0.036 |
| 4.0 | 19455.0 | 19455.0 | 24.0 | 3.0 | 4.0 | 0.1234 |
| 5.0 | 19455.0 | 19455.0 | 604.0 | 2.0 | 4.0 | 3.1046 |
| 6.0 | 19455.0 | 19455.0 | 39.0 | 3.0 | 5.0 | 0.2005 |
| 7.0 | 19455.0 | 19455.0 | 68.0 | 3.0 | 5.0 | 0.3495 |
| 8.0 | 19455.0 | 19455.0 | 786.0 | 2.0 | 5.0 | 4.0401 |
| 9.0 | 19455.0 | 19455.0 | 264.0 | 3.0 | 6.0 | 1.357 |
| 10.0 | 19455.0 | 19455.0 | 411.0 | 3.0 | 5.0 | 2.1126 |
| 11.0 | 19455.0 | 19455.0 | 6.0 | 3.0 | 6.0 | 0.0308 |
| 12.0 | 19455.0 | 19455.0 | 0.0 | 5.0 | 6.0 | 0.0 |

## 13. Distribución temática de unidades exportadas

| class_group_code | class_group_name | class_code | class_name | extract_units |
| --- | --- | --- | --- | --- |
| 9 | Cultivos | 9 | Cultivos | 8471 |
| 16 | Edificaciones | 16 | Edificaciones | 5928 |
| 1 | Forestal | 4 | Bosque secundario deciduo | 1587 |
| 8 | Pastos | 8 | Pastos | 1179 |
| 1 | Forestal | 2 | Bosque secundario | 903 |
| 1 | Forestal | 6 | Manglar | 799 |
| 11 | Humedal Palustre | 11 | Humedal Palustre | 409 |
| 10 | Agua | 10 | Agua | 150 |
| 1 | Forestal | 1 | Bosque maduro | 29 |

## 14. Valores sin datos por banda o índice

| Variable | Cantidad de -9999 |
| --- | --- |
| B2 | 2,230 |
| B3 | 2,230 |
| B4 | 2,230 |
| B5 | 2,230 |
| B6 | 2,230 |
| B7 | 2,230 |
| B8 | 2,230 |
| B8A | 2,230 |
| B11 | 2,230 |
| B12 | 2,230 |
| NDVI | 2,230 |
| NDVI8A | 2,230 |
| NDRE | 2,230 |
| cloud_prob_median | 2,230 |

## 15. Consideraciones para el procesamiento posterior

1. Tratar `-9999` como valor sin datos.
2. Revisar los registros con `n_obs_clean = 0` antes de cualquier scoring.
3. Mantener `extract_id` como llave principal para integrar resultados espectrales.
4. Usar `has_thematic_conflict` para excluir o priorizar revisión en unidades conflictivas.
5. Evaluar completitud mensual por clase antes de usar estos datos como entrenamiento.
6. Documentar cualquier cambio posterior en el JavaScript mediante hash o versión.
