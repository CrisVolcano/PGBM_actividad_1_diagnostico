# Reporte metodológico de la exportación espectral Sentinel-2 SR en Google Earth Engine

## 1. Identificación

Este reporte documenta el procedimiento utilizado para extraer variables espectro-temporales mensuales de Sentinel-2 Surface Reflectance en Google Earth Engine.

El reporte fue generado automáticamente a partir del script JavaScript conservado en el repositorio, con el objetivo de dejar trazabilidad metodológica de la exportación ya ejecutada.

| Elemento | Valor |
| --- | --- |
| Fecha de generación | 2026-05-19 09:33:01 |
| Script GEE documentado | `scripts/gee/06_s2_sr_monthly_s2cloudless_export.js` |
| Reporte generado | `outputs/reports/gee_extraction/06_s2_sr_monthly_s2cloudless_export_report.md` |
| Hash SHA256 del script | `643a4549dc91b67e68eca43e3aeae1c09b6e3b44026eb07cc2059112e115bf82` |
| Número de líneas del script | 465 |

## 2. Ubicación de datos y código

El código de Google Earth Engine se conserva en:

    scripts/gee/06_s2_sr_monthly_s2cloudless_export.js

Los CSV exportados desde Google Earth Engine se almacenan como datos crudos derivados en:

    data/raw/PGBM_S2SR_monthly_s2cloudless

El reporte metodológico queda guardado en:

    outputs/reports/gee_extraction/06_s2_sr_monthly_s2cloudless_export_report.md

## 3. Propósito de la exportación

La exportación tuvo como objetivo obtener información espectro-temporal mensual para unidades de extracción previamente preparadas en el repositorio.

Cada unidad de extracción representa una combinación única de:

    Longitud + Latitud + Año de referencia

La extracción genera, para cada punto y mes, valores de reflectancia, índices espectrales, conteo de observaciones limpias y metadatos del procedimiento de enmascaramiento.

## 4. Colecciones de Google Earth Engine utilizadas

- `COPERNICUS/S2_CLOUD_PROBABILITY`
- `COPERNICUS/S2_SR_HARMONIZED`

La colección `COPERNICUS/S2_SR_HARMONIZED` se utilizó como fuente de reflectancia de superficie Sentinel-2. La colección `COPERNICUS/S2_CLOUD_PROBABILITY` se utilizó como insumo para la máscara s2cloudless.

## 5. Parámetros principales

| Parámetro | Valor |
| --- | --- |
| `DRIVE_FOLDER` | PGBM_S2SR_monthly_s2cloudless |
| `scale` | 20 |
| `CLD_PRB_THRESH` | 50 |
| `NIR_DRK_THRESH` | 0.15 |
| `CLD_PRJ_DIST` | 1 |
| `BUFFER` | 60 |
| `EXPORT_GEOMETRIES` | false |
| `tileScale` | 8 |
| `fileFormat` | CSV |
| `outputName` | `'pgbm_s2sr_monthly_s2cloudless_' + cleanBatchName` |

## 6. Batches definidos en el script

El script usa el arreglo `BATCHES_TO_EXPORT` para definir manualmente las tablas importadas en GEE y activar o desactivar su exportación.

| Batch | run |
| --- | --- |
| `s2sr_units_Guatemala_2020_batch_002` | true |

Cada batch debe corresponder a un conjunto de unidades de extracción asociado a un único año de referencia. El año se obtiene desde el campo `year_ref` del primer registro de la tabla.

## 7. Funciones principales del script

- `cleanName`
- `addCloudBands`
- `addShadowBands`
- `addCloudShadowMask`
- `applyMask`
- `scaleS2`
- `addIndices`
- `emptyMonthlyImage`
- `monthlyComposite`
- `preparePoints`
- `buildMonthlySamples`

Estas funciones cubren la preparación de puntos, cálculo de máscara de nubes y sombras, escalado de bandas, cálculo de índices, construcción de composiciones mensuales y creación de tareas de exportación.

## 8. Preparación de puntos

El script espera que los puntos estén importados en Google Earth Engine como tabla o `FeatureCollection`.

Durante la preparación de puntos:

1. Se leen las coordenadas desde la geometría de cada feature.
2. Se generan los campos `lon_out` y `lat_out`.
3. Se conserva el identificador `extract_id`.
4. Se mantienen campos de trazabilidad como país, fuente, niveles temáticos, grupo XY y batch.

## 9. Periodo temporal

El año de extracción se toma desde el campo:

    year_ref

Para cada batch se construye un periodo anual completo:

    1 de enero del year_ref hasta 1 de enero del año siguiente

Posteriormente se generan composiciones mensuales para los meses 1 a 12.

## 10. Máscara de nubes y sombras

El script aplica una máscara combinada basada en:

- Probabilidad de nube de s2cloudless.
- Píxeles oscuros en la banda NIR.
- Proyección de sombra a partir del ángulo solar.
- Exclusión de clases SCL problemáticas.

Las clases SCL excluidas en el script son:

| Clase SCL | Descripción en el script |
| --- | --- |
| 6 | Sin descripción |
| 0 | no data |
| 1 | saturated / defective |
| 3 | cloud shadow |
| 8 | cloud medium probability |
| 9 | cloud high probability |
| 10 | cirrus |
| 11 | snow / ice |

La máscara final combina la exclusión SCL con la máscara de nubes y sombras generada a partir de `s2cloudless`.

## 11. Escalado de bandas

Las bandas ópticas Sentinel-2 se escalan mediante el factor:

    0.0001

Esto convierte los valores enteros de reflectancia escalada en valores decimales de reflectancia.

## 12. Bandas e índices extraídos

Las bandas e índices definidos en `spectralBands` son:

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

Los índices calculados son:

    NDVI   = (B8  - B4) / (B8  + B4)
    NDVI8A = (B8A - B4) / (B8A + B4)
    NDRE   = (B8A - B5) / (B8A + B5)

## 13. Composición mensual

Para cada mes se filtra la colección Sentinel-2 limpia y se calcula una composición mensual por mediana.

Además de las bandas e índices, el script exporta:

- `n_obs_clean`: número de observaciones válidas después del enmascaramiento, usando la banda B4 como referencia.
- `cloud_prob_median`: mediana mensual de probabilidad de nube.

Cuando no hay datos válidos para un mes, se asignan valores de relleno:

| Variable | Valor sin datos |
| --- | --- |
| Bandas espectrales | -9999 |
| Índices espectrales | -9999 |
| `cloud_prob_median` | -9999 |
| `n_obs_clean` | 0 |

## 14. Propiedades de punto conservadas

El script conserva las siguientes propiedades provenientes de las unidades de extracción:

- `extract_id`
- `lon_out`
- `lat_out`
- `year_ref`
- `n_records_extract_unit`
- `xy_group_id`
- `tipo_grupo_xy`
- `n_registros`
- `n_paises`
- `n_fuentes`
- `n_anios`
- `n_nivel1`
- `n_nivel2`
- `anio_min`
- `anio_max`
- `pais_grupo`
- `country`
- `source`
- `level_1`
- `level_2`
- `n_unique_country_extract_unit`
- `n_unique_source_extract_unit`
- `n_unique_level1_extract_unit`
- `n_unique_level2_extract_unit`
- `batch_id`

## 15. Metadatos agregados a la salida

El script agrega los siguientes metadatos metodológicos:

- `month`
- `year_extraction`
- `s2_collection`
- `cloud_mask_method`
- `cloud_prob_threshold`
- `nir_dark_threshold`
- `cloud_proj_dist_km`
- `buffer_m`
- `scale_m`

## 16. Exportación a Google Drive

La exportación se realiza mediante:

    Export.table.toDrive

La carpeta configurada en Google Drive fue:

    PGBM_S2SR_monthly_s2cloudless

El formato de salida configurado fue:

    CSV

Cada batch activo genera un CSV independiente.

## 17. Inventario local preliminar de CSV exportados

Carpeta revisada:

    data/raw/PGBM_S2SR_monthly_s2cloudless

| Métrica | Valor |
| --- | --- |
| Carpeta existe | Sí |
| Número de CSV identificados | 42 |
| Tamaño total aproximado | 6.50 GB |
| Firmas de encabezado distintas | 1 |

### Encabezado más frecuente identificado

- `extract_id`
- `lon_out`
- `lat_out`
- `year_ref`
- `n_records_extract_unit`
- `xy_group_id`
- `tipo_grupo_xy`
- `n_registros`
- `n_paises`
- `n_fuentes`
- `n_anios`
- `n_nivel1`
- `n_nivel2`
- `anio_min`
- `anio_max`
- `pais_grupo`
- `country`
- `source`
- `level_1`
- `level_2`
- `n_unique_country_extract_unit`
- `n_unique_source_extract_unit`
- `n_unique_level1_extract_unit`
- `n_unique_level2_extract_unit`
- `batch_id`
- `month`
- `year_extraction`
- `s2_collection`
- `cloud_mask_method`
- `cloud_prob_threshold`
- `nir_dark_threshold`
- `cloud_proj_dist_km`
- `buffer_m`
- `scale_m`
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
- `n_obs_clean`
- `cloud_prob_median`

### Archivos CSV identificados

| Archivo | Tamaño | Número de columnas |
| --- | --- | --- |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Belice_2018_batch_001.csv` | 173.76 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Belice_2020_batch_001.csv` | 39.44 KB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Costa_Rica_2018_batch_001.csv` | 107.54 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Costa_Rica_2019_batch_001.csv` | 129.21 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Costa_Rica_2021_batch_001.csv` | 320.16 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Costa_Rica_2021_batch_002.csv` | 256.62 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_001.csv` | 278.61 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_002.csv` | 279.94 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_003.csv` | 278.97 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_004.csv` | 280.91 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_005.csv` | 279.73 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_006.csv` | 279.79 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_007.csv` | 278.36 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_008.csv` | 276.83 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_009.csv` | 273.06 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_010.csv` | 274.79 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_011.csv` | 277.49 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2018_batch_012.csv` | 117.78 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_El_Salvador_2019_batch_001.csv` | 722.46 KB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Guatemala_2018_batch_001.csv` | 14.67 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Guatemala_2019_batch_001.csv` | 2.31 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Guatemala_2020_batch_001.csv` | 283.27 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Guatemala_2020_batch_002.csv` | 288.65 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Guatemala_2020_batch_003.csv` | 287.02 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Guatemala_2020_batch_004.csv` | 284.93 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Guatemala_2020_batch_005.csv` | 39.27 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Honduras_2018_batch_001.csv` | 246.08 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Honduras_2018_batch_002.csv` | 251.22 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Honduras_2018_batch_003.csv` | 166.85 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Honduras_2019_batch_001.csv` | 111.78 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Honduras_2020_batch_001.csv` | 111.56 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Honduras_2021_batch_001.csv` | 111.58 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Honduras_2022_batch_001.csv` | 110.99 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Mxico_2018_batch_001.csv` | 4.24 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Mxico_2019_batch_001.csv` | 8.61 MB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Mxico_2020_batch_001.csv` | 6.70 KB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Nicaragua_2018_batch_001.csv` | 26.66 KB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Nicaragua_2019_batch_001.csv` | 24.78 KB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Nicaragua_2020_batch_001.csv` | 24.67 KB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Nicaragua_2021_batch_001.csv` | 37.78 KB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Nicaragua_2022_batch_001.csv` | 24.66 KB | 49 |
| `pgbm_s2sr_monthly_s2cloudless_s2sr_units_Panam_2021_batch_001.csv` | 170.88 MB | 49 |

Nota: este inventario lee únicamente los encabezados de los CSV para evitar cargar archivos grandes en memoria.

## 18. Consideraciones de trazabilidad

Los CSV exportados deben considerarse la versión oficial de esta ejecución de Google Earth Engine, dado que ya fueron generados y representaron un costo computacional relevante.

El script JavaScript se conserva como evidencia metodológica del procedimiento aplicado. No se recomienda modificarlo retroactivamente para reinterpretar los resultados ya exportados.

## 19. Consideraciones para análisis posterior

Durante la consolidación posterior en Python se recomienda:

1. Unificar todos los CSV exportados.
2. Verificar consistencia de columnas entre batches.
3. Tratar `-9999` como valor sin datos.
4. Identificar meses con `n_obs_clean = 0`.
5. Calcular métricas de completitud temporal por `extract_id`, país, año, fuente y clase.
6. Revisar batches con pocos datos válidos o patrones anómalos.
7. Integrar los resultados espectro-temporales con la base original mediante `extract_id`.

## 20. Limitaciones conocidas

- La extracción se realizó a escala nominal de 20 m.
- Algunas bandas Sentinel-2 tienen resolución nativa de 10 m y otras de 20 m.
- El script asume que cada batch contiene un único `year_ref`.
- La región de filtrado se construye con el contorno envolvente de los puntos del batch.
- Los meses sin datos válidos quedan representados por `-9999` y `n_obs_clean = 0`.
