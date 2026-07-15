# Metodología integral de la Actividad 4

## 1. Propósito y alcance

La Actividad 4 construye el conjunto piloto de puntos y áreas espaciales, extrae
predictores mediante Google Earth Engine (GEE) y consolida los resultados en una
base local preparada para análisis y modelado.

El flujo se divide en cuatro etapas:

1. **A4.1 — selección y normalización de puntos por cuadrante piloto**;
2. **A4.2 — extracción de valores de predictores para los puntos piloto**;
3. **A4.3 — exportación de los predictores como ráster por grupo espacial**;
4. **A4.4 — integración local de los CSV de A4.2 en un GeoPackage organizado por predictor**.

A4.2 y A4.3 son ramas complementarias. Ambas usan la base creada en A4.1 y el
mismo registro de capas predictoras, pero producen objetos diferentes:

- A4.2 produce valores tabulares por punto para modelado;
- A4.3 produce GeoTIFF por área piloto para aplicación espacial, inspección y
  procesamiento ráster.

A4.4 depende de A4.2, no de A4.3.

## 2. Implementación y configuración

| Etapa | Código | Configuración |
|---|---|---|
| A4.1 | `src/actividad_4/4_1_extract_pilot_quadrant_points.py` | `config/a4_pilot_quadrant_extraction.yaml` |
| A4.2 | `src/actividad_4/4_2_extract_predictors_for_pilot_points.py` | `config/a4_2_predictor_extraction.yaml` |
| A4.3 | `src/actividad_4/4_3_export_quadrant_rasters.py` | `config/a4_3_export_quadrant_rasters.yaml` |
| A4.4 | `src/actividad_4/4_4_normalize_point_predictor_exports_essential.py` | `config/a4_4_normalize_point_predictor_exports.yaml` |

Las rutas relativas se resuelven desde la raíz del repositorio. Los YAML son la
fuente operativa para rutas, capas, campos, filtros, escalas, nombres de salida y
límites de seguridad. Los cambios en esos parámetros deben realizarse en la
configuración y no introduciendo nombres rígidos adicionales en el código.

## 3. Relación con el modelo lógico Draw.io

El archivo de referencia es:

```text
docs/actividad_2/A2_1_normalizacion/propuesta_normalizacion/actividad_2_1_modelo_ordenado.drawio
```

Las páginas pertinentes son:

- **04_extension_actividad_4_cuadrantes**: extensión lógica para zonas,
  cuadrantes, buffer, asignación de puntos y control de conflictos;
- **05_extension_predictores_puntos**: separación lógica entre puntos,
  asignación espacial, catálogo de predictores, bandas y valores derivados.

El Draw.io expresa el modelo lógico y las reglas de separación. El código define
la materialización física vigente. En particular, la página 5 muestra una
posible representación larga de valores (`xy_predictor_value`), mientras que
A4.4 implementa actualmente **una tabla ancha por predictor/asset**, denominada
`xy_pred_<predictor_id>`, con una fila por `xy_group_id` y una columna por banda.
Esta diferencia es deliberada y debe considerarse al interpretar el esquema:

- se conserva la separación entre el punto, el catálogo y los valores;
- no se mezclan `xy_score` ni `xy_accion` dentro de las tablas de predictores;
- `pilot_model_matrix` continúa siendo un producto derivado;
- la estructura física evita una tabla EAV única de gran tamaño.

## 4. Llaves y reglas comunes

### 4.1 Llave canónica

`xy_group_id` es la llave estable de los puntos durante todo el flujo. Se usa para:

- seleccionar el subconjunto piloto desde A2.1;
- relacionar el punto con su cuadrante;
- enviar la identidad del punto a GEE;
- recuperar y validar los CSV descargados;
- unir las tablas de predictores;
- construir la matriz final de modelado.

Las coordenadas no sustituyen esta llave. `lon`, `lat` y la geometría se usan para
la localización y el muestreo espacial, no como criterio primario de unión.

### 4.2 Universo de puntos

La implementación exige unicidad de `xy_group_id` en las entidades con
cardinalidad 1:1. En A4.4, con
`validation.require_complete_point_universe: true`, cada predictor debe contener
exactamente el mismo conjunto de llaves que `pilot_xy_point`:

```text
llaves_predictor = llaves_pilot_xy_point
```

La ejecución falla si existen llaves faltantes, adicionales o duplicadas.

### 4.3 Registro de predictores

A4.2 y A4.3 leen la hoja `Hoja1` de:

```text
data/raw/predictors/Registro de Capas Predictoras Centroamérica PGBM Red II - AECID - GIZ.xlsx
```

El filtro `registry.keep_purpose` conserva las filas cuyo propósito normalizado es
`Predictor`. De cada fila se interpretan proyecto, tipo, asset, resolución,
período, reescalado, descripción y lista de bandas.

El `predictor_id` se deriva del último componente del asset: se eliminan acentos,
se pasa a minúsculas y se sustituyen caracteres no alfanuméricos por guion bajo.
Si dos assets generan el mismo identificador, se añaden sufijos para mantenerlo
único.

Las bandas de salida se construyen como:

```text
<predictor_id>__<banda_normalizada>
```

La regla configurable `worldclim_b1_b19` expande descripciones de rango a las 19
bandas `b1`–`b19`.

### 4.4 Escala

Con `scale_policy: registry`, cada predictor usa la resolución interpretada desde
el registro. Si no puede interpretarse, se usa `fixed_scale_m`. No se homogenizan
todos los predictores a una resolución única.

## 5. A4.1 — Extracción normalizada de puntos por cuadrantes piloto

### 5.1 Objetivo

Construir una extensión del modelo A2.1 que identifique los puntos aptos ubicados
en los cuadrantes piloto y preserve las entidades y relaciones necesarias para
las siguientes etapas.

La estructura conceptual se encuentra en la página
`04_extension_actividad_4_cuadrantes` del Draw.io.

### 5.2 Entradas

**Modelo normalizado A2.1**

```text
data/processed/a2_1_modelo_datos/gpkg/a2_1_xy_point.gpkg
```

Entradas principales:

- capa `xy_point`;
- tabla `xy_accion`;
- tabla `xy_score`;
- catálogos de país, clases de origen y clases propuestas;
- tablas de homologación configuradas en `reference_tables`.

**Cuadrantes piloto**

```text
data/raw/cuadrantes_pilotos/zonas_cuadrantes_pilotos.gpkg
```

Capa `zonas_cuadrantes`, con `id_zona`, `id_cuadrante` y geometría.
`id_cuadrante` debe ser globalmente único.

### 5.3 Preparación espacial

1. Se valida la existencia de archivos, capas y campos.
2. Se rechazan identificadores nulos o duplicados.
3. Las geometrías inválidas de cuadrantes se reparan con `make_valid()`.
4. `pilot_zone` se obtiene disolviendo los cuadrantes por `id_zona`.
5. `pilot_quadrant` conserva `id_cuadrante`, `id_zona` y geometría original.
6. Para la asignación se estima un CRS UTM mediante `estimate_utm_crs()` cuando
   `spatial.metric_crs` es `auto`.
7. Se aplica un buffer interior de 30 m por defecto. La geometría original no se
   altera; el resultado se almacena separadamente en `pilot_quadrant_buffer`.
8. Si el buffer elimina polígonos se informa; si elimina todos, la ejecución falla.

El buffer negativo reduce asignaciones ambiguas de puntos muy próximos a los
límites de cuadrantes.

### 5.4 Lectura y asignación de puntos

Para reducir E/S, primero se obtiene el bounding box conjunto de los cuadrantes
interiores y sólo se leen los puntos de `xy_point` dentro de esa extensión.

La relación punto–cuadrante se obtiene mediante `geopandas.sjoin`. El predicado
predeterminado es `within`; el YAML admite `within`, `intersects` o `covered_by`.

Después del join se cuentan las coincidencias por `xy_group_id`:

- una coincidencia: asignación válida;
- más de una: conflicto espacial;
- ninguna: punto fuera del universo piloto.

Con `multiple_match_policy: exclude`, los conflictos se excluyen de la asignación
y se conservan en tablas de auditoría. Con `raise`, la ejecución se detiene.

### 5.5 Filtro de uso

Las asignaciones espaciales se unen 1:1 con `xy_accion` mediante `xy_group_id`.
Sólo se conservan las categorías configuradas:

```text
entrenamiento
validación
```

Una asignación sin categoría de uso causa error. El subconjunto final determina
el universo de `pilot_xy_point`, `xy_pilot_quadrant`, `xy_score` y `xy_accion`.

### 5.6 Validaciones relacionales

Las relaciones declaradas en `relationships` se verifican antes de escribir:

- punto → país y clases de origen;
- jerarquías entre niveles de clase;
- homologaciones de clases;
- cuadrante → zona;
- buffer → cuadrante;
- punto → asignación, score y acción;
- conflicto → coincidencias de conflicto.

El código valida referencias en memoria y crea índices SQL sobre las claves
lógicas. Estos índices materializan unicidad y aceleran consultas, aunque el
GeoPackage no declare todas las relaciones como restricciones SQL `FOREIGN KEY`.

### 5.7 Salida

```text
data/processed/a4_pilot_quadrant_extraction/gpkg/pilot_quadrant_extraction_normalized.gpkg
```

Capas espaciales:

| Capa | Contenido |
|---|---|
| `pilot_xy_point` | puntos seleccionados con geometría y FK normalizadas |
| `pilot_zone` | zonas piloto disueltas |
| `pilot_quadrant` | cuadrantes originales |
| `pilot_quadrant_buffer` | geometría interior usada para asignar |

Tablas principales:

| Tabla | Contenido |
|---|---|
| `xy_pilot_quadrant` | relación única `xy_group_id → id_cuadrante` |
| `xy_score` | score del subconjunto piloto |
| `xy_accion` | acción y uso del subconjunto piloto |
| `pilot_buffer_run` | parámetros y fecha del buffer |
| `pilot_assignment_run` | insumos, reglas y conteos de la corrida |
| `xy_pilot_quadrant_conflict` | resumen de puntos con múltiples coincidencias |
| `xy_pilot_quadrant_conflict_match` | cuadrantes candidatos de cada conflicto |

También se copian los catálogos y homologaciones enumerados en
`reference_tables` para mantener una salida autocontenida y validar las rutas de
referencia indicadas en el Draw.io.

El log se escribe en:

```text
data/processed/a4_pilot_quadrant_extraction/logs/extract_pilot_quadrant_points_normalized.log
```

## 6. A4.2 — Extracción de predictores en puntos mediante GEE

### 6.1 Objetivo

Muestrear cada predictor válido en todos los puntos de `pilot_xy_point`,
conservando `xy_group_id` para recuperar la identidad y `id_cuadrante` para
auditar la procedencia espacial.

### 6.2 Construcción de la entrada

1. Se lee `pilot_xy_point` y se exige CRS.
2. Se valida que `xy_group_id` sea único.
3. Se incorpora `id_cuadrante` desde `xy_pilot_quadrant` mediante unión 1:1.
4. `xy_score` y `xy_accion` sólo se incorporan si alguno de sus campos fue
   solicitado en `fields.export_properties`.
5. Se comprueba que todas las propiedades de exportación existan y no sean nulas.
6. Los puntos se reproyectan a EPSG:4326 para crear geometrías de GEE.

La configuración actual envía únicamente:

```text
xy_group_id
id_cuadrante
```

### 6.3 Preparación del catálogo

El registro Excel se transforma en `predictor_catalog.csv`, con una fila por
banda y los campos necesarios para reproducir la extracción: `predictor_id`,
asset, proyecto, tipo, período, resolución, escala, reescalado, banda original,
banda de salida y descripción.

Antes de enviar tareas, si `validate_assets_before_submit` está activo, el script:

- intenta abrir cada `ee.Image`;
- consulta sus bandas disponibles;
- compara bandas requeridas y disponibles;
- escribe `gee_asset_probe.csv`;
- detiene el proceso si hay errores y `strict_asset_validation` es verdadero.

### 6.4 Autenticación

El proyecto configurado es `ee-jesusc461`. El script intenta inicializar GEE y,
si es necesario, ejecuta `ee.Authenticate()`. En Windows puede configurar
`certifi` mediante `SSL_CERT_FILE` y `REQUESTS_CA_BUNDLE` para evitar fallos del
almacén de certificados durante OAuth.

### 6.5 Lotes y muestreo

Los puntos se dividen en lotes consecutivos de 5.000 registros. Para cada
predictor se crea una imagen mediante:

```text
ee.Image(asset).select(bandas_originales).rename(bandas_salida)
```

Cada lote se convierte en una `ee.FeatureCollection` y se procesa con
`sampleRegions` usando:

- la escala propia del predictor;
- `tileScale: 16`;
- `geometries: false`;
- las propiedades `xy_group_id` e `id_cuadrante`.

El número de tareas es:

```text
n_predictores × ceil(n_puntos / batch_size)
```

Si supera `max_tasks_to_submit: 500`, no se envía ninguna corrida completa.

### 6.6 Exportación y trazabilidad

Cada tarea exporta un CSV a la carpeta Drive
`PGBM_A4_2_predictor_exports`, siguiendo el patrón:

```text
a4_2_<predictor_id>_batch_<NNN>.csv
```

Productos locales:

```text
data/processed/a4_2_predictor_extraction/predictor_catalog.csv
data/processed/a4_2_predictor_extraction/gee_asset_probe.csv
data/processed/a4_2_predictor_extraction/gee_task_manifest.csv
```

El manifiesto registra task ID, fecha, predictor, asset, lote, número de puntos,
escala y estado `SUBMITTED`. El script envía la corrida completa; no implementa
modos parciales, selección de tareas fallidas ni reintento automático.

## 7. A4.3 — Exportación ráster por grupo espacial piloto

### 7.1 Objetivo

Exportar cada predictor como GeoTIFF para cada grupo espacial piloto. Esta etapa
no produce los valores tabulares usados por A4.4.

### 7.2 Regiones

La fuente es `pilot_quadrant`. Los cuadrantes se disuelven por `id_zona`, por lo
que la configuración prevista transforma los 45 cuadrantes de 20 × 20 km en
cinco grupos espaciales piloto.

El procedimiento:

1. valida capa, identificador, CRS y geometrías;
2. aplica `make_valid()` si corresponde;
3. disuelve por `id_zona`;
4. opcionalmente simplifica geometrías si `simplify_geometry_m > 0`;
5. reproyecta a EPSG:4326 para construir las regiones de GEE.

Con el valor actual `simplify_geometry_m: 0`, se conserva la geometría completa.

### 7.3 Exportación

Para cada combinación grupo–predictor se seleccionan y renombran las bandas, se
recorta la imagen a la región y se crea una tarea `Export.image.toDrive`.

La cantidad de tareas es:

```text
n_grupos_espaciales × n_predictores
```

La configuración documenta 5 grupos × 16 predictores = 80 tareas y fija el
límite de seguridad en 120.

Parámetros principales:

- formato GeoTIFF;
- escala propia del registro;
- `maxPixels: 10^13`;
- Cloud Optimized GeoTIFF;
- omisión de tiles vacíos;
- sin CRS forzado, salvo que se configure explícitamente.

Las carpetas y archivos de Drive siguen estas plantillas:

```text
carpeta: PGBM_A4_3_spatial_group_rasters_<id_zona>
archivo: <id_zona>__<predictor_id>.tif
tarea:   a4_3_<id_zona>_<predictor_id>
```

Productos locales:

```text
data/processed/a4_3_spatial_group_raster_export/predictor_catalog_rasters.csv
data/processed/a4_3_spatial_group_raster_export/spatial_groups_for_raster_export.csv
data/processed/a4_3_spatial_group_raster_export/gee_asset_probe_rasters.csv
data/processed/a4_3_spatial_group_raster_export/gee_spatial_group_raster_task_manifest.csv
```

## 8. A4.4 — Integración local de predictores por punto

### 8.1 Objetivo

Importar los CSV descargados desde Drive, validar que reproduzcan el universo de
puntos de A4.1 y crear un GeoPackage autocontenido con una tabla por predictor.

Esta es la materialización física vigente de la extensión descrita
conceptualmente en la página `05_extension_predictores_puntos` del Draw.io.

### 8.2 Entradas

```text
data/processed/a4_pilot_quadrant_extraction/gpkg/pilot_quadrant_extraction_normalized.gpkg
data/processed/a4_2_predictor_extraction/predictor_catalog.csv
data/raw/datos_extraidos_predictores/**/*.csv
```

La búsqueda de CSV es recursiva. Sólo se aceptan nombres que cumplan:

```regex
^a4_2_(?P<predictor_id>.+)_batch_(?P<batch_id>\d+)\.csv$
```

Los archivos no coincidentes se ignoran y se registran como advertencia. Un
`predictor_id` reconocido en el nombre pero ausente del catálogo causa error.

### 8.3 Catálogos y nombres físicos

`predictor_source` contiene una fila por predictor y registra su tabla física.
`predictor_band` contiene una fila por banda y vincula:

- `predictor_band_id`;
- `predictor_id`;
- `predictor_table`;
- banda original y banda de salida;
- nombre físico de columna (`band_column`);
- orden, resolución y escala.

Las tablas de valores se denominan:

```text
xy_pred_<predictor_id>
```

Los identificadores SQL se normalizan a minúsculas y guiones bajos; si comienzan
por número reciben un prefijo seguro.

### 8.4 Validación de los CSV

Para cada predictor:

1. se agrupan todos sus lotes;
2. se exige `xy_group_id`;
3. se exigen todas las bandas declaradas en el catálogo;
4. las columnas adicionales no previstas se ignoran con advertencia;
5. se rechazan llaves desconocidas;
6. se rechazan llaves duplicadas dentro de un lote;
7. se concatenan los lotes y se vuelven a rechazar duplicados entre lotes;
8. las bandas se convierten con `pandas.to_numeric(errors="coerce")`;
9. se exige igualdad exacta con el universo base cuando
   `require_complete_point_universe` está activo.

Por tanto, cada tabla `xy_pred_*` tiene cardinalidad 1:1 respecto de
`pilot_xy_point`: una fila por punto y varias columnas de bandas pertenecientes
al mismo predictor.

### 8.5 Preservación de las tablas A4

Antes de incorporar predictores se comprueba que `pilot_xy_point`,
`xy_pilot_quadrant`, `xy_score` y `xy_accion` tengan el mismo universo de llaves.

La capa `pilot_xy_point` se copia con geometría. Las demás se escriben como
tablas independientes. No se mezclan score, acción o asignación dentro de cada
tabla `xy_pred_*`.

### 8.6 Matriz de modelado

`pilot_model_matrix` se construye mediante uniones 1:1 por `xy_group_id` de:

1. atributos de `pilot_xy_point` sin geometría;
2. `xy_pilot_quadrant`;
3. `xy_score`;
4. `xy_accion`;
5. cada tabla `xy_pred_*`.

La matriz tiene una fila por punto y una columna por variable contextual o banda.
Es una salida derivada destinada a algoritmos de modelado; no sustituye las
tablas separadas del GeoPackage.

### 8.7 Salidas

```text
data/processed/a4_4_predictor_normalization/gpkg/a4_4_point_predictors_normalized.gpkg
data/processed/a4_4_predictor_normalization/pilot_model_matrix.csv
data/processed/a4_4_predictor_normalization/logs/normalize_point_predictor_exports.log
```

Contenido principal del GeoPackage:

| Objeto | Cardinalidad y función |
|---|---|
| `pilot_xy_point` | una geometría por `xy_group_id` |
| `xy_pilot_quadrant` | una asignación por punto |
| `xy_score` | un score por punto |
| `xy_accion` | una acción/uso por punto |
| `predictor_source` | una fila por predictor |
| `predictor_band` | una fila por banda |
| `xy_pred_<predictor_id>` | una fila por punto; columnas de bandas del predictor |
| `pilot_model_matrix` | una fila por punto; unión ancha derivada |

Se crean índices únicos en las entidades 1:1, en los catálogos y en todas las
tablas por predictor.

## 9. Secuencia de ejecución

Desde la raíz del repositorio y dentro del ambiente geoespacial del proyecto:

```powershell
python src/actividad_4/4_1_extract_pilot_quadrant_points.py
python src/actividad_4/4_2_extract_predictors_for_pilot_points.py
python src/actividad_4/4_3_export_quadrant_rasters.py
```

Después de que las tareas de A4.2 terminen en GEE:

1. descargar los CSV desde Google Drive;
2. conservar el patrón de nombres generado;
3. ubicarlos dentro de `data/raw/datos_extraidos_predictores`;
4. ejecutar:

```powershell
python src/actividad_4/4_4_normalize_point_predictor_exports_essential.py
```

A4.3 puede ejecutarse antes o después de A4.2 porque ambas ramas son
independientes después de A4.1.

## 10. Controles de calidad y criterios de aceptación

Una corrida completa debe satisfacer, como mínimo:

### A4.1

- `id_cuadrante` único y no nulo;
- geometrías con CRS y válidas o reparables;
- una asignación como máximo por punto después de resolver conflictos;
- sólo usos autorizados;
- `xy_score` y `xy_accion` completos para el subconjunto;
- referencias de catálogos sin valores huérfanos;
- índices únicos creados en el GeoPackage.

### A4.2

- catálogo sin nombres de banda de salida duplicados;
- acceso válido a todos los assets;
- presencia de todas las bandas solicitadas;
- propiedades de exportación completas;
- número de tareas por debajo del límite;
- manifiesto con una fila por tarea enviada.

### A4.3

- regiones únicas después de disolver;
- geometrías válidas y no vacías;
- assets y bandas válidos;
- cantidad de tareas igual a grupos × predictores;
- manifiesto y catálogo coherentes con Drive.

### A4.4

- todos los predictores del catálogo con CSV disponibles;
- ninguna llave desconocida o duplicada;
- todas las bandas esperadas presentes;
- igualdad exacta de `xy_group_id` entre A4.1 y cada predictor;
- una fila por punto en cada `xy_pred_*`;
- una fila por punto en `pilot_model_matrix`;
- GeoPackage reconocido por GDAL/QGIS y tablas registradas en `gpkg_contents`.

## 11. Reproducibilidad y limitaciones operativas

- Los manifiestos registran el estado al momento del envío, no el resultado final
  de las tareas remotas. La finalización debe verificarse en GEE o Drive.
- A4.2 y A4.3 no implementan reintentos automáticos.
- Cambiar el registro Excel puede modificar identificadores, nombres de banda,
  cantidad de tareas y estructura física de A4.4.
- La conversión numérica de A4.4 transforma valores no interpretables en nulos;
  conviene revisar estadísticos y nulidad antes del entrenamiento.
- `pilot_model_matrix` puede ser grande; se mantiene como producto derivado para
  no convertirla en la única representación de los datos.
- Los logs, catálogos, sondeos de assets y manifiestos forman parte de la
  trazabilidad y deben conservarse junto con cada corrida.

