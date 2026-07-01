# Metodología de muestreo SINAC para consenso de bosque deciduo 2021-2023

## Objetivo

Generar puntos de muestreo espacialmente controlados a partir del GeoPackage `consenso_bosque_deciduo_2021_2023.gpkg`, usando como clase objetivo `bosque deciduo` en el campo `clase_objetivo`.

El flujo está diseñado para integrarse al repositorio `PGBM_actividad_1_diagnostico` y mantener una lógica reproducible basada en configuración YAML, control de calidad geométrico, trazabilidad de fuente, separación entre datos de entrada y salidas procesadas, logs y reportes.

## Fuente de entrada

Archivo esperado:

```text
data/raw/Costa Rica/Datos_SINAC/consenso_bosque_deciduo_2021_2023.gpkg
```

Capa esperada:

```text
deciduo_consenso_2021_2023
```

Campo temático principal:

```text
clase_objetivo
```

Valor objetivo:

```text
bosque deciduo
```

Identificador fuente preferente:

```text
consenso_id
```

Área fuente preferente:

```text
area_consenso_ha
```

## Inspección inicial realizada

La capa inspeccionada contiene una única capa vectorial llamada `deciduo_consenso_2021_2023`, geometría `MultiPolygon`, 80,407 objetos y CRS `EPSG:8908` (`CR-SIRGAS / CRTM05`). Este CRS es proyectado y usa metros, por lo que es adecuado para cálculos internos de área y distancia en Costa Rica.

Todos los registros inspeccionados tienen `clase_objetivo = Bosque deciduo` y el criterio `Deciduo en 2021 y deciduo en 2023`.

## Flujo metodológico

1. Cargar parámetros desde `config/bosque_deciduo_sampling.yaml`.
2. Inspeccionar el GeoPackage y validar capa, CRS, geometría y campos críticos.
3. Leer únicamente los campos requeridos y campos de trazabilidad definidos en el YAML.
4. Filtrar registros cuyo campo `clase_objetivo` corresponda a `bosque deciduo`. La comparación normaliza mayúsculas, espacios y acentos, pero conserva los valores originales en las salidas.
5. Reparar geometrías inválidas cuando sea posible.
6. Eliminar geometrías nulas, vacías, inválidas no resueltas o no poligonales.
7. Reproyectar al CRS métrico de procesamiento definido en el YAML.
8. Calcular área geométrica en hectáreas como `source_area_ha`.
9. Aplicar un umbral configurable de área mínima. El valor inicial recomendado es `0.01 ha`, equivalente a 100 m², para reducir fragmentos residuales muy pequeños.
10. Generar un punto interior por polígono mediante `representative_point()`.
11. Ordenar los puntos candidatos de forma reproducible. Por defecto, se priorizan polígonos de mayor área y luego el identificador de fuente ascendente.
12. Aplicar escenarios de separación mínima global entre puntos mediante un filtro greedy basado en celdas espaciales.
13. Exportar capas espaciales, tablas de auditoría, resumen por escenario, log y reporte Markdown.

## Escenarios de distancia

El YAML propone cuatro escenarios, siguiendo la lógica de separación mínima global usada en el flujo de referencia INEGI:

- 500 m
- 1,000 m
- 2,000 m
- 5,000 m

Estos escenarios pueden ajustarse según la densidad espacial final, los objetivos del muestreo y la necesidad de reducir autocorrelación espacial.

## Salidas esperadas

GeoPackage principal:

```text
outputs/geodata/bosque_deciduo_sampling_sinac.gpkg
```

Capas espaciales principales:

```text
bosque_deciduo_sinac_poligonos_procesados
bosque_deciduo_sinac_puntos_candidatos
bosque_deciduo_sinac_puntos_d0500
bosque_deciduo_sinac_puntos_d1000
bosque_deciduo_sinac_puntos_d2000
bosque_deciduo_sinac_puntos_d5000
```

Tablas CSV principales:

```text
outputs/tables/bosque_deciduo_sinac_distribucion_clases.csv
outputs/tables/bosque_deciduo_sinac_resumen_filtro_area.csv
outputs/tables/bosque_deciduo_sinac_resumen_poligonos.csv
outputs/tables/bosque_deciduo_sinac_resumen_escenarios.csv
outputs/tables/bosque_deciduo_sinac_auditoria_seleccion.csv
outputs/tables/bosque_deciduo_sinac_matriz_candidatos.csv
outputs/tables/bosque_deciduo_sinac_run_metadata.csv
```

Reporte:

```text
outputs/reports/bosque_deciduo_sampling_sinac_reporte.md
```

Log:

```text
logs/bosque_deciduo_sampling_sinac.log
```

## Campos mínimos de puntos

Las capas de puntos incluyen, como mínimo:

- `point_id`
- `candidate_id`
- `source_polygon_id`
- `clase_objetivo`
- `source_area_ha`
- `distance_scenario_m` en capas seleccionadas
- `selection_status` en capas seleccionadas
- `source_name`
- `base_year`
- `extraction_method`
- `geometry`

Además, se conservan campos de trazabilidad 2021 y 2023 cuando están disponibles en la fuente.

## Ejecución

Desde la raíz del repositorio:

```bash
conda activate pgbm_actividad1
python src/actividad_3/run_bosque_deciduo_sampling.py --config config/bosque_deciduo_sampling.yaml
```

## Dependencias

El flujo requiere las dependencias geoespaciales ya esperables en el entorno del repositorio:

- Python 3.10+
- geopandas
- pyogrio
- pandas
- numpy
- PyYAML
- pyproj
- scipy, opcional para calcular distancia al vecino más cercano

## Supuestos y advertencias

- El archivo de entrada debe colocarse en `data/raw/Costa Rica/Datos_SINAC/`, ya que no se recomienda versionar datos geoespaciales pesados en GitHub.
- El CRS de procesamiento debe ser métrico. Para esta fuente se recomienda conservar `EPSG:8908`.
- El punto generado por `representative_point()` representa el polígono fuente, pero no reemplaza una validación temática independiente.
- El umbral `minimum_area_ha` debe revisarse si se desea conservar todos los fragmentos derivados de raster o intersección espacial.
- Los escenarios de distancia mínima controlan densidad espacial, pero no garantizan independencia estadística completa.
