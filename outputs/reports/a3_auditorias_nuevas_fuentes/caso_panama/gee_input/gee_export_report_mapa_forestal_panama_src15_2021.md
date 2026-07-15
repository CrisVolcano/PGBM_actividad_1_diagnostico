# Reporte metodológico y control inicial de exportación GEE Sentinel-2 SR

## 1. Identificación del piloto

| Elemento | Valor |
| --- | --- |
| Fuente | MIAMBIENTE - Cultivos Mapa Panamá |
| Código fuente | SRC15 |
| `source_id` | 15 |
| País | PAN |
| Año de referencia | 2021 |
| Fecha de generación del reporte | 2026-07-14 23:13:12 |
| Script GEE documentado | `scripts/gee/a3_auditorias_nuevas_fuentes/s2_sr_monthly_s2cloudless_export_mapa_forestal_panama_src15_2021.js` |
| Hash SHA256 del JS | `0a385817a0210dfc9b698f867c7d342bc3a1346f7c2b975378c88cc70c0d8684` |
| Número de líneas del JS | 463 |

## 2. Ubicación de insumos y salidas

Script JavaScript usado en Google Earth Engine:

    scripts/gee/a3_auditorias_nuevas_fuentes/s2_sr_monthly_s2cloudless_export_mapa_forestal_panama_src15_2021.js

Carpeta revisada con CSV exportados desde GEE:

    data/processed/a3_auditorias_nuevas_fuentes/caso_panama/gee_exports

Patrón de CSV analizado:

    pgbm_s2sr_monthly_s2cloudless_mapa_forestal_panama_src15_2021*.csv

Reporte generado:

    outputs/reports/a3_auditorias_nuevas_fuentes/caso_panama/gee_input/gee_export_report_mapa_forestal_panama_src15_2021.md

## 3. Propósito de la exportación

La exportación obtuvo variables espectro-temporales mensuales de Sentinel-2 Surface Reflectance para una fuente puntual independiente incorporada al flujo de auditoría espectral de nuevas fuentes.

La unidad de extracción fue:

    Longitud + Latitud + Año

Este piloto no depende de `grupos_xy`, `Nivel_1` ni `Nivel_2`. La trazabilidad temática se conserva mediante `class_code`, `class_group_code`, `class_name` y `class_group_name`.

## 4. Parámetros principales del JavaScript

| Parámetro | Valor |
| --- | --- |
| `DRIVE_FOLDER` | PGBM_S2SR_monthly_s2cloudless_mapa_forestal_panama_src15_2021 |
| `scale` | 20 |
| `CLD_PRB_THRESH` | 50 |
| `NIR_DRK_THRESH` | 0.15 |
| `CLD_PRJ_DIST` | 1 |
| `BUFFER` | 60 |
| `EXPORT_GEOMETRIES` | false |
| `tileScale` | 8 |
| `fileFormat` | CSV |
| `outputName` | `'pgbm_s2sr_monthly_s2cloudless_mapa_forestal_panama_src15_2021_' + cleanBatchName` |

## 5. Colecciones de Google Earth Engine

- `COPERNICUS/S2_CLOUD_PROBABILITY`
- `COPERNICUS/S2_SR_HARMONIZED`

La colección `COPERNICUS/S2_SR_HARMONIZED` se usó para reflectancia de superficie y `COPERNICUS/S2_CLOUD_PROBABILITY` para la máscara s2cloudless.

## 6. Batches configurados en GEE

| Batch | run |
| --- | --- |
| `s2sr_units_PAN_2021_SRC15_batch_001` | true |

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
- `xy_group_id`
- `xy_year_group_id`
- `xy_class_group_id`
- `source_record_id`
- `original_source_record_id`
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
| Tamaño total aproximado | 81.56 MB |
| Firmas de encabezado distintas | 1 |

| Archivo | Tamaño | Número de columnas |
| --- | --- | --- |
| `pgbm_s2sr_monthly_s2cloudless_mapa_forestal_panama_src15_2021_s2sr_units_PAN_2021_SRC15_batch_001.csv` | 81.56 MB | 48 |

## 11. Control inicial del contenido exportado

| Control | Resultado |
| --- | --- |
| Filas exportadas | 150,612 |
| Columnas | 49 |
| CSV analizados | 1 |
| `extract_id` únicos | 12,551 |
| Meses presentes | 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0 |
| Filas esperadas según extract_id × meses | 150,612 |
| Duplicados `extract_id + month` | 0 |
| `year_ref` | 2021 |
| `year_extraction` | 2021 |
| `source_id` | 15 |
| `country_code` | PAN |
| Unidades con posible conflicto temático | 0 |
| Filas con `n_obs_clean = 0` | 36523 |
| Porcentaje con `n_obs_clean = 0` | 24.2497% |
| Mínimo `n_obs_clean` | 0.0 |
| Mediana `n_obs_clean` | 2.0 |
| Máximo `n_obs_clean` | 12.0 |

Columnas requeridas faltantes:
- Ninguna.

## 12. Control mensual de observaciones limpias

| month | rows | extract_ids | rows_zero_clean_obs | median_clean_obs | max_clean_obs | pct_zero_clean_obs |
| --- | --- | --- | --- | --- | --- | --- |
| 1.0 | 12551.0 | 12551.0 | 87.0 | 4.0 | 12.0 | 0.6932 |
| 2.0 | 12551.0 | 12551.0 | 322.0 | 5.0 | 12.0 | 2.5655 |
| 3.0 | 12551.0 | 12551.0 | 131.0 | 4.0 | 12.0 | 1.0437 |
| 4.0 | 12551.0 | 12551.0 | 621.0 | 2.0 | 8.0 | 4.9478 |
| 5.0 | 12551.0 | 12551.0 | 7607.0 | 0.0 | 4.0 | 60.6087 |
| 6.0 | 12551.0 | 12551.0 | 10110.0 | 0.0 | 6.0 | 80.5514 |
| 7.0 | 12551.0 | 12551.0 | 1769.0 | 2.0 | 8.0 | 14.0945 |
| 8.0 | 12551.0 | 12551.0 | 6917.0 | 0.0 | 3.0 | 55.1111 |
| 9.0 | 12551.0 | 12551.0 | 1981.0 | 2.0 | 8.0 | 15.7836 |
| 10.0 | 12551.0 | 12551.0 | 3617.0 | 1.0 | 6.0 | 28.8184 |
| 11.0 | 12551.0 | 12551.0 | 2204.0 | 1.0 | 4.0 | 17.5604 |
| 12.0 | 12551.0 | 12551.0 | 1157.0 | 2.0 | 8.0 | 9.2184 |

## 13. Distribución temática de unidades exportadas

| class_group_code | class_group_name | class_code | class_name | extract_units |
| --- | --- | --- | --- | --- |
| 3 | Pasto | 26 | Pasto | 4564 |
| 1 | Bosque y vegetación natural | 2 | Bosque latifoliado mixto secundario | 2893 |
| 1 | Bosque y vegetación natural | 9 | Rastrojo y vegetación arbustiva | 1571 |
| 1 | Bosque y vegetación natural | 3 | Bosque de mangle | 1122 |
| 1 | Bosque y vegetación natural | 1 | Bosque latifoliado mixto maduro | 787 |
| 4 | Agua y acuicultura | 27 | Superficie de agua | 366 |
| 6 | Urbano e infraestructura | 28 | Área poblada | 279 |
| 1 | Bosque y vegetación natural | 8 | Bosque plantado de latifoliadas | 206 |
| 1 | Bosque y vegetación natural | 10 | Vegetación herbácea | 145 |
| 2 | Cultivos | 16 | Palma aceitera | 143 |
| 2 | Cultivos | 19 | Arroz | 115 |
| 6 | Urbano e infraestructura | 29 | Infraestructura | 102 |
| 2 | Cultivos | 20 | Caña de azúcar | 79 |
| 2 | Cultivos | 24 | Otro cultivo anual | 52 |
| 5 | Suelo desnudo y rasgos naturales | 13 | Playa y arenal natural | 42 |
| 2 | Cultivos | 23 | Piña | 24 |
| 2 | Cultivos | 18 | Otro cultivo permanente | 24 |
| 5 | Suelo desnudo y rasgos naturales | 12 | Afloramiento rocoso y tierra desnuda | 20 |
| 1 | Bosque y vegetación natural | 11 | Vegetación baja inundable | 6 |
| 2 | Cultivos | 15 | Cítrico | 5 |
| 1 | Bosque y vegetación natural | 7 | Bosque plantado de coníferas | 4 |
| 4 | Agua y acuicultura | 31 | Estanque para acuicultura | 1 |
| 2 | Cultivos | 25 | Área heterogénea de producción agropecuaria | 1 |

## 14. Valores sin datos por banda o índice

| Variable | Cantidad de -9999 |
| --- | --- |
| B2 | 36,523 |
| B3 | 36,523 |
| B4 | 36,523 |
| B5 | 36,523 |
| B6 | 36,526 |
| B7 | 36,525 |
| B8 | 36,523 |
| B8A | 36,528 |
| B11 | 36,523 |
| B12 | 36,523 |
| NDVI | 36,523 |
| NDVI8A | 36,528 |
| NDRE | 36,528 |
| cloud_prob_median | 36,523 |

## 15. Consideraciones para el procesamiento posterior

1. Tratar `-9999` como valor sin datos.
2. Revisar los registros con `n_obs_clean = 0` antes de cualquier scoring.
3. Mantener `extract_id` como llave principal para integrar resultados espectrales.
4. Usar `has_thematic_conflict` para excluir o priorizar revisión en unidades conflictivas.
5. Evaluar completitud mensual por clase antes de usar estos datos como entrenamiento.
6. Documentar cualquier cambio posterior en el JavaScript mediante hash o versión.
