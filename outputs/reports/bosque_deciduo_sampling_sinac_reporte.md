# Reporte de muestreo SINAC - bosque deciduo 2021-2023

## Identificación del proceso

- Proyecto: PGBM - muestreo SINAC de bosque deciduo
- Fuente: SINAC - Consenso bosque deciduo 2021-2023
- Año base: 2021-2023
- Fecha de ejecución UTC: 2026-07-01T21:13:58.327365+00:00
- Capa de entrada: `deciduo_consenso_2021_2023`
- CRS de entrada: `EPSG:8908` (CR-SIRGAS epoch 2014.59 / CRTM05)
- CRS de procesamiento: `EPSG:8908`
- CRS de salida: `EPSG:4326`

## Inspección de entrada

- Objetos reportados por la capa: 7,652
- Tipo geométrico reportado: MultiPolygon
- Campos disponibles: consenso_id, clase_objetivo, criterio_consenso, fuente_2021, campo_2021, valores_2021, fid_2021, id_original_2021, clase_2021, area_deciduo_2021_ha, fuente_2023, campo_2023, valor_2023, fid_2023, dn_2023, area_attr_2023, area_deciduo_2023_ha, area_consenso_ha
- Bounds de entrada: [287109.90983764, 1058443.9508, 413466.4817, 1235108.38023311]

## Filtro temático

Campo de clase: `clase_objetivo`  
Valor objetivo: `bosque deciduo`

| class_value    |   n_features |   selected_as_target |
|:---------------|-------------:|---------------------:|
| Bosque deciduo |         7652 |                    1 |

## Control geométrico

- Geometrías de entrada al control: 7,652
- Geometrías nulas/vacías descartadas antes de reparar: 0
- Geometrías inválidas detectadas antes de reparar: 0
- Geometrías nulas/vacías descartadas después de reparar: 0
- Geometrías inválidas no resueltas descartadas: 0
- Geometrías no poligonales descartadas: 0
- Geometrías válidas después del control: 7,652

## Resumen de polígonos procesados

- Polígonos procesados: 7,652
- Área total procesada: 116,378.75 ha
- Área media: 15.2089 ha
- Área mediana: 2.2382 ha
- Área mínima: 1.00090652 ha
- Área máxima: 6,808.55 ha

## Escenarios de separación mínima

|   distance_m |   n_candidates |   n_selected |   n_rejected |   pct_selected |   total_source_area_ha_selected |   mean_nearest_neighbor_m |   min_nearest_neighbor_m |
|-------------:|---------------:|-------------:|-------------:|---------------:|--------------------------------:|--------------------------:|-------------------------:|
|          500 |           7652 |         4769 |         2883 |       62.3236  |                        110283   |                   744.961 |                   500.1  |
|         1000 |           7652 |         2464 |         5188 |       32.2007  |                        100783   |                  1268.12  |                  1000.04 |
|         2000 |           7652 |          989 |         6663 |       12.9247  |                         87091.4 |                  2349.17  |                  2000.08 |
|         5000 |           7652 |          224 |         7428 |        2.92734 |                         61673.1 |                  5581.11  |                  5018.56 |

## Criterio metodológico

El flujo genera un punto interior por polígono mediante `representative_point()`. Posteriormente aplica una selección greedy reproducible con separación mínima global por escenario. La prioridad de selección se controla desde el YAML mediante `sampling.selection_order`; por defecto se priorizan polígonos de mayor área y luego el identificador de fuente.

## Advertencias metodológicas

- El filtro temático se realiza de forma robusta ante mayúsculas, espacios y acentos, pero conserva el valor original en la salida.
- El CRS de procesamiento debe ser métrico. Para Costa Rica se recomienda `EPSG:8908` cuando la fuente ya está en CR-SIRGAS / CRTM05.
- Los escenarios de distancia mínima no sustituyen una validación temática independiente; solamente controlan densidad y autocorrelación espacial aproximada.
- La existencia de muchos polígonos pequeños puede reflejar una fuente derivada de raster o intersecciones. El parámetro `geometry.minimum_area_ha` permite controlar fragmentos residuales.
