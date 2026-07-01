# Reporte de muestreo SINAC - bosque deciduo 2021-2023

## Identificación del proceso

- Proyecto: PGBM - muestreo SINAC de bosque deciduo
- Fuente: SINAC - Consenso bosque deciduo 2021-2023
- Año base: 2021-2023
- Fecha de ejecución UTC: 2026-06-29T23:44:23.619929+00:00
- Capa de entrada: `deciduo_consenso_2021_2023`
- CRS de entrada: `EPSG:8908` (CR-SIRGAS epoch 2014.59 / CRTM05)
- CRS de procesamiento: `EPSG:8908`
- CRS de salida: `EPSG:4326`

## Inspección de entrada

- Objetos reportados por la capa: 80,407
- Tipo geométrico reportado: MultiPolygon
- Campos disponibles: consenso_id, clase_objetivo, criterio_consenso, fuente_2021, campo_2021, valores_2021, fid_2021, id_original_2021, clase_2021, area_deciduo_2021_ha, fuente_2023, campo_2023, valor_2023, fid_2023, dn_2023, area_attr_2023, area_deciduo_2023_ha, area_consenso_ha
- Bounds de entrada: [287109.90983764, 1057323.9508, 423443.261740218, 1238543.9508]

## Filtro temático

Campo de clase: `clase_objetivo`  
Valor objetivo: `bosque deciduo`

| class_value    |   n_features |   selected_as_target |
|:---------------|-------------:|---------------------:|
| Bosque deciduo |        80407 |                    1 |

## Control geométrico

- Geometrías de entrada al control: 80,407
- Geometrías nulas/vacías descartadas antes de reparar: 0
- Geometrías inválidas detectadas antes de reparar: 0
- Geometrías nulas/vacías descartadas después de reparar: 0
- Geometrías inválidas no resueltas descartadas: 0
- Geometrías no poligonales descartadas: 0
- Geometrías válidas después del control: 80,407

## Resumen de polígonos procesados

- Polígonos procesados: 71,866
- Área total procesada: 125,586.72 ha
- Área media: 1.7475 ha
- Área mediana: 0.0676 ha
- Área mínima: 0.01000000 ha
- Área máxima: 6,808.55 ha

## Escenarios de separación mínima

|   distance_m |   n_candidates |   n_selected |   n_rejected |   pct_selected |   total_source_area_ha_selected |   mean_nearest_neighbor_m |   min_nearest_neighbor_m |
|-------------:|---------------:|-------------:|-------------:|---------------:|--------------------------------:|--------------------------:|-------------------------:|
|          500 |          71866 |        10470 |        61396 |       14.5688  |                        112198   |                   615.423 |                   500    |
|         1000 |          71866 |         3921 |        67945 |        5.45599 |                        101343   |                  1156.55  |                  1000    |
|         2000 |          71866 |         1290 |        70576 |        1.79501 |                         87202.8 |                  2242.07  |                  2000.08 |
|         5000 |          71866 |          257 |        71609 |        0.35761 |                         61691.1 |                  5490.48  |                  5016.07 |

## Criterio metodológico

El flujo genera un punto interior por polígono mediante `representative_point()`. Posteriormente aplica una selección greedy reproducible con separación mínima global por escenario. La prioridad de selección se controla desde el YAML mediante `sampling.selection_order`; por defecto se priorizan polígonos de mayor área y luego el identificador de fuente.

## Advertencias metodológicas

- El filtro temático se realiza de forma robusta ante mayúsculas, espacios y acentos, pero conserva el valor original en la salida.
- El CRS de procesamiento debe ser métrico. Para Costa Rica se recomienda `EPSG:8908` cuando la fuente ya está en CR-SIRGAS / CRTM05.
- Los escenarios de distancia mínima no sustituyen una validación temática independiente; solamente controlan densidad y autocorrelación espacial aproximada.
- La existencia de muchos polígonos pequeños puede reflejar una fuente derivada de raster o intersecciones. El parámetro `geometry.minimum_area_ha` permite controlar fragmentos residuales.
