# Protocolo de replicacion de la Actividad 3: extraccion, auditoria y normalizacion de nuevas fuentes de referencia

## 1. Proposito del protocolo

Este documento establece una metodologia robusta para replicar la Actividad 3 del proyecto PGBM con nuevas fuentes de informacion tematica. Su objetivo es guiar a usuarios tecnicos en la preparacion, extraccion, homologacion, auditoria, scoring y normalizacion de datos de referencia que puedan complementar vacios de informacion identificados durante la Actividad 1.

El protocolo esta disenado para ser aplicado a diferentes tipos de fuentes:

- puntos ya existentes, como mallas de entrenamiento, inventarios, puntos de campo o puntos de interpretacion visual;
- poligonos tematicos, como mapas nacionales, mapas forestales, unidades de cobertura, areas de entrenamiento o capas auxiliares;
- raster categoricos, como mapas de cobertura/uso del suelo, productos de bosque/no bosque, mapas de manglar, clasificaciones supervisadas o capas de consenso.

La metodologia toma como referencia las practicas implementadas en tres lineas de trabajo del repositorio:

- **SINAC Costa Rica 2021**, como ejemplo de fuente puntual institucional ya estructurada;
- **Mapa Forestal de Panama 2021**, como ejemplo de fuente raster/poligonal nacional convertida en puntos candidatos y auditada con el flujo A1;
- **Manglares 2020**, como ejemplo de fuente auxiliar de alta confianza creada mediante consenso entre Global Mangrove Watch 2020 y ESA WorldCover 2020.

El protocolo no pretende sustituir la revision experta. Su funcion es asegurar que toda nueva fuente siga un flujo comun, documentado y reproducible antes de incorporarse a los productos derivados del proyecto.

## 2. Principios metodologicos

Toda replicacion debe respetar los principios generales del proyecto:

1. **No modificar los datos originales.** Los archivos fuente deben conservarse intactos en la carpeta de datos crudos o en la ubicacion documental definida para la fuente.
2. **No limpiar antes de auditar.** Las inconsistencias deben registrarse antes de aplicar filtros o normalizaciones.
3. **No descartar registros sin documentacion.** Todo descarte debe quedar trazado mediante tablas, logs o reportes.
4. **Separar datos crudos, intermedios y procesados.** Cada etapa debe producir salidas nuevas.
5. **Conservar trazabilidad de fuente.** Cada punto debe mantener informacion suficiente para reconstruir su origen, clase original, fuente documental, ano y metodo de extraccion.
6. **Usar configuracion externa.** Las rutas, campos, clases, anos, fuentes y parametros espaciales deben definirse en archivos YAML o catalogos, no como valores rigidos dentro del codigo.
7. **Generar evidencia auditable.** Cada ejecucion debe producir reportes, tablas de resumen, logs y metadatos.
8. **Separar extraccion de aptitud.** Una fuente puede producir puntos, pero su uso como entrenamiento, validacion, prueba o referencia contextual debe depender de la auditoria y el scoring.

## 3. Alcance operativo

La Actividad 3 cubre el proceso que inicia con una fuente candidata y termina con una salida normalizada compatible con el modelo de datos del proyecto. El flujo completo puede dividirse en siete bloques:

1. seleccion y documentacion de la fuente;
2. preparacion espacial y tematica;
3. generacion o consolidacion de puntos de referencia;
4. homologacion a la leyenda A1;
5. auditoria por grupos XY y preparacion de insumos Sentinel-2;
6. auditoria espectral y scoring de aptitud;
7. normalizacion final e incorporacion como nueva fuente.

No todas las fuentes requieren todos los pasos. Por ejemplo, una fuente puntual como SINAC no necesita generar candidatos desde raster, mientras que una fuente raster como Panama o una capa de consenso de manglares si requiere convertir unidades espaciales en puntos candidatos antes de auditar.

## 4. Insumos minimos requeridos

Antes de iniciar una replicacion debe existir, como minimo, la siguiente informacion:

| Insumo | Descripcion | Obligatorio |
|---|---|---|
| Fuente espacial | Archivo puntual, vectorial o raster que contiene la informacion tematica de interes. | Si |
| Area de interes | Limite regional, pais, zona piloto, AOI administrativo o poligono de trabajo. | Si |
| Ano base | Ano de referencia de la fuente o periodo documentado. | Si |
| Campos tematicos | Codigo y/o nombre de clase original. | Si |
| Identificador de fuente | `id_fuente`, nombre oficial, pais, tipo y medio de obtencion. | Si |
| Tabla de homologacion | Relacion entre clases originales y clases A1. | Si, antes del scoring |
| Reglas de muestreo | Distancia minima, representacion minima por clase y CRS de procesamiento. | Si para poligonos/raster |
| Configuracion YAML | Archivo con rutas, campos, parametros y salidas. | Si |
| Catalogo documental | Registro en `config/source_catalog.csv` o equivalente para nuevas fuentes. | Recomendado |

Cuando la fuente no tenga un ano unico, se debe documentar la regla temporal usada. Por ejemplo, si un mapa nacional fue publicado en 2021 pero representa condiciones 2020-2021, debe quedar claro que ano se usara como `base_year` y como se justifico.

## 5. Estructura recomendada de carpetas

Cada nueva fuente debe procesarse en una carpeta independiente para evitar mezclar resultados antes de validar su integridad. La estructura recomendada es:

```text
config/a3_auditorias_nuevas_fuentes/caso_<fuente>/
docs/actividad_3/<fuente>/
data/processed/a3_auditorias_nuevas_fuentes/caso_<fuente>/
outputs/reports/a3_auditorias_nuevas_fuentes/caso_<fuente>/
outputs/tables/a3_auditorias_nuevas_fuentes/caso_<fuente>/
logs/a3_auditorias_nuevas_fuentes/caso_<fuente>/
```

Para fuentes que requieren muestreo desde raster o poligonos, puede existir una etapa previa:

```text
data/processed/a3_sampling_nuevas_fuentes/<fuente>/
outputs/reports/a3_sampling_nuevas_fuentes/<fuente>/
outputs/tables/a3_sampling_nuevas_fuentes/<fuente>/
logs/a3_sampling_nuevas_fuentes/<fuente>/
```

El caso de Panama usa esta separacion: primero genera puntos candidatos desde el mapa forestal y luego esos puntos entran al flujo de auditoria A3/A1.

## 6. Definicion del tipo de fuente

El primer paso metodologico es clasificar la fuente segun su geometria y nivel de preparacion.

### 6.1. Fuente puntual

Una fuente puntual ya contiene coordenadas o geometria de puntos. Ejemplos:

- mallas de entrenamiento;
- puntos de campo;
- puntos de fotointerpretacion;
- inventarios forestales;
- puntos de validacion institucional.

El caso SINAC corresponde a este escenario. El flujo debe concentrarse en validar campos, coordenadas, clases, ano, fuente, duplicados y consistencia tematica.

### 6.2. Fuente de poligonos

Una fuente poligonal contiene unidades espaciales con una clase asociada. Ejemplos:

- mapas nacionales vectoriales;
- unidades cartograficas de cobertura/uso;
- mapas de bosque/no bosque;
- areas de entrenamiento delimitadas manualmente;
- poligonos de consenso o parches filtrados.

Para estas fuentes se debe generar al menos un punto candidato por poligono o fragmento, normalmente mediante `point_on_surface` o punto interior. Si los poligonos son grandes, se puede generar una malla de candidatos dentro de cada clase y luego aplicar adelgazamiento espacial.

El flujo de manglares usa una logica poligonal despues de construir la fuente de consenso: se genera un punto interior por parche filtrado y se aplican escenarios de distancia minima.

### 6.3. Fuente raster

Una fuente raster contiene valores categoricos por pixel. Ejemplos:

- mapas de cobertura raster;
- clasificaciones de uso del suelo;
- productos de bosque/no bosque;
- mapas de cultivos;
- mapas de manglar u otras clases auxiliares.

En este caso se debe generar una malla de puntos candidatos con un espaciamiento definido, extraer el valor raster en cada punto, eliminar NoData y unir una tabla de clases. El caso del Mapa Forestal de Panama ilustra este escenario.

## 7. Bloque 1: seleccion y documentacion de la fuente

Antes de procesar una fuente, el usuario debe completar una ficha minima:

| Campo | Descripcion |
|---|---|
| `id_fuente` | Identificador numerico unico. |
| `fuente_reporte` | Nombre documental de la fuente. |
| `pais_documentado` | Pais o region principal. |
| `anio_base` | Ano operativo usado para auditoria. |
| `anios_documentados` | Ano o rango real descrito por la fuente. |
| `tipo_documentado` | Interpretacion visual, mapa nacional, inventario, producto auxiliar, etc. |
| `medio_obtencion` | Portal, repositorio, entrega institucional, carpeta interna o geoservicio. |
| `restriccion_uso` | Dominio publico, uso interno, licencia, restriccion institucional. |
| `clase_trazabilidad` | Nivel de trazabilidad documental. |
| `score_directitud` | Puntaje de directitud del dato. |
| `score_trazabilidad` | Puntaje de trazabilidad documental. |

Esta informacion debe registrarse en el catalogo de fuentes (`config/source_catalog.csv`) o en una configuracion equivalente si la fuente aun se encuentra en etapa piloto.

## 8. Bloque 2: configuracion YAML

Cada fuente debe tener un archivo YAML que concentre las decisiones operativas. El YAML debe incluir, como minimo:

```yaml
project:
  name: nombre_corto_del_caso
  base_year: 2021

source:
  id_fuente: 10
  fuente_reporte: "Nombre documental de la fuente"
  pais: "Costa Rica"
  tipo_fuente: "Interpretacion Visual"

inputs:
  source_path: "ruta/al/archivo.gpkg"
  source_layer: "nombre_capa"

fields:
  lon: "lon"
  lat: "lat"
  class_id: "Clase"
  class_label: "nombre_clase"
  year: "Anio"

outputs:
  root: "data/processed/a3_auditorias_nuevas_fuentes/caso_fuente"
```

Para fuentes raster o poligonales, el YAML debe agregar parametros de muestreo:

```yaml
sampling:
  candidate_spacing_m: 250
  thinning_distances_m: [250, 500, 1000, 2000, 3000]
  class_representation:
    enabled: true
    minimum_points_per_class: 1
  selection_order:
    - "area_desc"
    - "objectid_asc"
```

Para fuentes que requieren calculos de distancia o area, debe existir una separacion entre CRS de procesamiento y CRS de salida:

```yaml
crs:
  processing_crs: "EPSG:3857"
  output_crs: "EPSG:4326"
```

El CRS de procesamiento debe estar en metros. El CRS de salida normalmente debe ser `EPSG:4326`.

## 9. Bloque 3: preparacion de la fuente

La preparacion depende del tipo de fuente, pero siempre debe producir una capa o tabla con campos normalizados minimos.

### 9.1. Preparacion de fuente puntual

Para una fuente puntual se deben ejecutar las siguientes acciones:

1. leer el archivo de entrada;
2. verificar que existe geometria o campos de coordenadas;
3. validar CRS;
4. asegurar que cada registro tenga identificador unico;
5. normalizar nombres de campos;
6. asignar `id_fuente`, `fuente_reporte`, pais y ano;
7. conservar campos originales relevantes;
8. exportar una capa preparada.

Campos minimos esperados:

```text
id_registro
id_fuente
fuente_reporte
pais
anio
lon
lat
clase_original_codigo
clase_original_nombre
geometry
```

En el caso SINAC, esta etapa prepara una malla de entrenamientos del mapa de bosques 2021 y conserva columnas originales utiles para trazabilidad tematica.

### 9.2. Preparacion de fuente poligonal

Para una fuente poligonal:

1. leer la capa;
2. validar CRS;
3. reparar geometria si es necesario;
4. reproyectar al CRS metrico;
5. recortar al AOI;
6. calcular area por fragmento;
7. eliminar fragmentos menores al umbral definido, si aplica;
8. crear un identificador unico de unidad fuente;
9. construir campos `class_id`, `class_label` y `stratum_id`;
10. generar puntos candidatos.

Cuando se use `point_on_surface`, debe aclararse que el punto representa el poligono o fragmento, no una observacion de campo independiente.

En la fuente de manglares, primero se construye una capa de consenso entre GMW 2020 y ESA WorldCover 2020, se eliminan parches menores a 0.5 ha y luego se generan puntos candidatos desde los parches resultantes.

### 9.3. Preparacion de fuente raster

Para una fuente raster:

1. leer el raster categorico;
2. verificar CRS, NoData y valores validos;
3. definir o cargar tabla de clases;
4. recortar al AOI;
5. generar malla de candidatos con `candidate_spacing_m`;
6. extraer el valor raster en cada punto;
7. eliminar valores NoData o no documentados;
8. homologar cada valor a un codigo/nombre de clase original;
9. aplicar escenarios de distancia minima;
10. exportar puntos seleccionados y tablas de auditoria.

En el caso Panama, se generaron candidatos desde el GeoTIFF recortado, se conservaron valores raster documentados y se evaluaron escenarios de separacion minima de 250, 500, 1000, 2000 y 3000 m.

## 10. Bloque 4: generacion de puntos candidatos

Los puntos candidatos son la unidad base para auditoria posterior. La metodologia debe evitar tanto la perdida de clases raras como la concentracion excesiva de puntos.

### 10.1. Representacion minima por clase

Antes de aplicar adelgazamiento espacial, se debe proteger una cantidad minima de puntos por clase. La regla recomendada es:

```text
minimum_points_per_class >= 1
```

Para clases prioritarias o muy escasas se puede aumentar el minimo. Esta regla evita que una clase desaparezca por efecto de distancia minima.

### 10.2. Adelgazamiento espacial

Luego de proteger la representacion minima, se aplican escenarios de distancia minima. El resultado no debe ser una unica seleccion opaca, sino una comparacion de escenarios:

```text
250 m
500 m
1000 m
2000 m
3000 m
5000 m
```

La distancia final debe seleccionarse con base en:

- cantidad de puntos seleccionados;
- numero de clases conservadas;
- redundancia espacial;
- representacion por pais o AOI;
- objetivo de uso posterior;
- factibilidad de procesamiento en GEE o modelado.

No se recomienda elegir automaticamente el escenario mas restrictivo. Un escenario de 3000 m puede reducir redundancia, pero tambien puede eliminar demasiados puntos de clases raras o fragmentadas.

### 10.3. Orden de seleccion

Cuando se aplica adelgazamiento, debe definirse un orden reproducible. Ejemplos:

- poligonos de mayor area primero;
- clases prioritarias primero;
- menor nubosidad primero, si existe evidencia espectral;
- identificador original ascendente como criterio final.

El orden debe estar documentado en el YAML y en el reporte.

## 11. Bloque 5: homologacion tematica A1

Toda fuente debe traducirse desde su leyenda original hacia la leyenda homologada A1. Esta etapa es critica porque determina si los puntos podran compararse con el resto de la base.

La tabla de homologacion debe incluir, como minimo:

```text
clase_original_codigo
clase_original_nombre
id_nivel_0
nivel_0
id_nivel_1
nivel_1
id_nivel_2
nivel_2
decision_homologacion
observacion
```

Las decisiones deben distinguir:

- homologacion directa;
- homologacion aproximada;
- clase no homologada;
- clase residual;
- clase que requiere revision experta;
- clase fuera del alcance.

En SINAC y Panama se usaron tablas especificas de homologacion (`homologacion_sinac_a1.csv` y `homologacion_panama_a1.csv`). Esa practica debe replicarse para cada nueva fuente, incluso si la fuente parece tener clases faciles de mapear.

## 12. Bloque 6: grupos XY

Luego de preparar y homologar la fuente, se deben generar identificadores estables de agrupacion espacial y tematica.

Los identificadores recomendados son:

| Identificador | Definicion | Uso |
|---|---|---|
| `xy_group_id` | Longitud + latitud normalizadas | Unidad espacial principal |
| `xy_year_group_id` | Longitud + latitud + ano | Control temporal |
| `xy_class_group_id` | Longitud + latitud + ano + clase | Control tematico |

El objetivo es detectar:

- puntos duplicados;
- registros multitemporales;
- clases distintas en la misma coordenada;
- redundancia de una misma fuente;
- conflictos tematicos.

El `xy_group_id` no debe depender del orden de lectura. Debe generarse de forma reproducible mediante reglas documentadas de redondeo o namespace.

## 13. Bloque 7: preparacion de insumos para Google Earth Engine

Para auditar coherencia espectral, los puntos elegibles deben prepararse como unidades de extraccion Sentinel-2 Surface Reflectance.

La preparacion debe:

1. filtrar registros con coordenadas validas;
2. conservar el ano base o anos elegibles;
3. crear `extract_id` estable;
4. exportar CSV de unidades unicas para GEE;
5. generar indice de lotes si el volumen lo requiere;
6. producir resumen por pais, fuente, ano y clase;
7. documentar registros excluidos.

Salidas esperadas:

```text
s2_sr_extract_units_<fuente>.csv
s2_sr_gee_batch_index.csv
records_by_year.csv
records_by_class_code.csv
records_by_country.csv
s2_sr_nueva_fuente_summary.csv
```

Los scripts de GEE deben mantenerse separados por fuente cuando cambian rutas, nombres de assets o identificadores.

## 14. Bloque 8: union de resultados espectrales

Una vez descargados o exportados los CSV desde GEE, se debe hacer una union controlada con los registros originales.

La validacion minima debe revisar:

- `extract_id` faltantes en GEE;
- `extract_id` adicionales;
- duplicados por `extract_id` y mes;
- cobertura mensual;
- numero de observaciones limpias;
- consistencia entre unidades solicitadas y unidades recibidas.

La salida no debe reemplazar la fuente original. Debe generar una tabla enriquecida con variables espectrales y un reporte de union.

## 15. Bloque 9: auditoria espectral

La auditoria espectral evalua si la senal Sentinel-2 es coherente con la clase homologada y si existe disponibilidad suficiente de observaciones.

Los criterios pueden incluir:

- disponibilidad mensual;
- observaciones limpias;
- probabilidad de nube;
- NDVI;
- NDVI8A;
- NDRE;
- rareza por pais, clase y ano;
- alertas por ausencia de datos;
- alertas por senal inesperada.

Las alertas deben expresarse en categorias interpretables:

```text
sin_alerta
baja
media
alta
alta_sin_datos
```

La auditoria espectral no decide por si sola el uso final del punto, pero puede limitar su aptitud. Una alerta alta puede convertir un punto en apoyo interpretativo o referencia contextual, aunque otros criterios sean favorables.

## 16. Bloque 10: scoring de aptitud

El scoring integra multiples dimensiones:

- temporal;
- espacial;
- tematica;
- espectral;
- confiabilidad;
- representatividad;
- fuente.

El resultado debe producir, al menos:

```text
score_temporal
score_espacial
score_tematico
score_espectral
score_confiabilidad
score_representatividad
score_fuente
score_aptitud_total
categoria_aptitud_preliminar
categoria_uso_actividad_1_8
accion_recomendada
```

Categorias recomendadas:

- datos para entrenamiento;
- datos para validacion;
- datos para prueba;
- apoyo interpretativo;
- referencia contextual;
- mascara o exclusion;
- revision experta.

En los pilotos A3, SINAC produjo principalmente puntos de entrenamiento alta, mientras Panama mostro una mezcla entre entrenamiento alto, entrenamiento condicionado y referencia contextual. Esa diferencia es metodologicamente importante: el protocolo no fuerza a que todas las fuentes sean entrenamiento.

## 17. Bloque 11: normalizacion al modelo de datos

La normalizacion final permite que las nuevas fuentes se integren al modelo relacional derivado de A2.1. Esta etapa no debe recalcular los scores finales si ya fueron generados por el flujo de auditoria; debe preservarlos y documentar su origen.

La normalizacion debe validar:

- unicidad y no nulidad de `xy_group_id`;
- identidad esperada de fuente y pais;
- correspondencia entre IDs A1 y labels;
- cobertura completa de homologaciones;
- coherencia entre clase dominante y valores observados;
- integridad de tablas y relaciones en GeoPackage;
- existencia de tabla de trazabilidad.

Tablas esperadas:

```text
xy_point
xy_score
xy_accion
xy_trazabilidad_fuente
normalization_source
catalogos de clase/pais/fuente
```

La tabla `xy_trazabilidad_fuente` debe conservar la clase original y la clase A1 asignada. No se deben inventar indicadores de trazabilidad que la fuente no provee.

## 18. Escenarios especificos de replicacion

### 18.1. Replicar una fuente similar a SINAC

Usar este escenario cuando la fuente ya es puntual.

Pasos:

1. crear YAML de caso;
2. preparar puntos originales;
3. homologar clases;
4. generar grupos XY;
5. preparar insumos para GEE;
6. correr extraccion GEE;
7. unir resultados espectrales;
8. auditar espectralmente;
9. calcular scoring A1;
10. normalizar salida.

Riesgos principales:

- clases originales ambiguas;
- coordenadas duplicadas;
- puntos sin ano;
- puntos con clase residual;
- campos de confianza inexistentes;
- mezcla de paises o fuente.

### 18.2. Replicar una fuente similar al Mapa Forestal de Panama

Usar este escenario cuando la fuente es raster categorica o mapa nacional convertido a raster.

Pasos:

1. documentar raster y tabla de clases;
2. definir AOI;
3. definir espaciamiento de candidatos;
4. extraer puntos candidatos por valor raster;
5. proteger representacion minima por clase;
6. aplicar escenarios de distancia minima;
7. elegir escenario operativo;
8. homologar clases;
9. continuar con flujo A3 de grupos XY, GEE, auditoria y scoring.

Riesgos principales:

- valores raster sin tabla de clases;
- NoData confundido con clase valida;
- clases con area muy pequena;
- sobre-representacion de clases dominantes;
- seleccion de distancia demasiado restrictiva;
- CRS no metrico para distancias.

### 18.3. Replicar una fuente similar a manglares

Usar este escenario cuando se desea construir una fuente auxiliar de alta confianza por consenso.

Pasos:

1. seleccionar dos o mas productos independientes;
2. documentar regla de consenso;
3. alinear grillas o reproyectar de forma controlada;
4. crear mascara comun;
5. vectorizar o consolidar parches;
6. eliminar fragmentos menores a un umbral ecologicamente razonable;
7. calcular area;
8. generar puntos candidatos;
9. aplicar representacion minima y distancia;
10. documentar que la fuente representa consenso, no verdad de campo directa.

Ejemplo de regla:

```text
manglar_consenso = Global Mangrove Watch 2020 > 0
                   INTERSECT
                   ESA WorldCover 2020 clase 95
                   con parches >= 0.5 ha
```

Riesgos principales:

- resoluciones distintas entre productos;
- errores de alineacion raster;
- perdida de parches pequenos;
- falsa seguridad por usar consenso;
- confundir producto auxiliar con observacion directa.

## 19. Controles de calidad obligatorios

Cada replicacion debe producir evidencia para los siguientes controles:

| Control | Pregunta que responde |
|---|---|
| Inventario de entrada | Que archivo, capa, CRS, campos y registros se recibieron? |
| Calidad de campos | Que campos estan completos, nulos o ausentes? |
| Calidad espacial | Las coordenadas/geometrias son validas y caen dentro del AOI? |
| Calidad temporal | El ano es valido y consistente con la fuente? |
| Calidad tematica | Las clases existen, son homologables y no son ambiguas? |
| Duplicados XY | Hay puntos repetidos o conflictos en la misma coordenada? |
| Representacion | Que paises y clases quedan representados? |
| Redundancia espacial | Que efecto tienen los escenarios de distancia minima? |
| Disponibilidad espectral | Hay suficientes observaciones Sentinel-2? |
| Coherencia espectral | La senal es compatible con la clase esperada? |
| Scoring | Que puntos son aptos para entrenamiento, validacion, prueba o referencia? |
| Trazabilidad | Puede reconstruirse el origen de cada punto? |

## 20. Salidas obligatorias

Una ejecucion completa debe producir:

### 20.1. Reportes

```text
reporte_preparacion.md
reporte_homologacion.md
reporte_xy_groups.md
reporte_gee_input.md
reporte_join_s2sr.md
reporte_auditoria_espectral.md
reporte_scoring.md
reporte_normalizacion.md
```

### 20.2. Tablas

```text
field_quality.csv
bbox_summary.csv
records_by_year.csv
records_by_class_code.csv
records_by_country.csv
xy_groups.csv
xy_group_records.csv
possible_thematic_conflicts.csv
audit_summary.csv
alert_distribution.csv
xy_group_aptitude_master.csv
source_aptitude_ranking.csv
gap_priority_country_class.csv
```

### 20.3. Capas espaciales

```text
fuente_preparada.gpkg
fuente_homologada.gpkg
xy_groups_outputs.gpkg
puntos_con_extract_id.gpkg
scoring_a1_outputs.gpkg
normalizado.gpkg
```

Los nombres pueden variar por fuente, pero la estructura conceptual debe mantenerse.

## 21. Criterios de aceptacion

Una fuente puede considerarse lista para integracion si cumple:

1. tiene documentacion de origen y ano;
2. tiene `id_fuente` unico;
3. conserva clase original y clase homologada;
4. tiene coordenadas/geometria valida;
5. fue recortada correctamente al AOI;
6. tiene `xy_group_id` unico para la salida de aptitud;
7. tiene reporte de homologacion;
8. tiene auditoria espectral o justificacion de por que no aplica;
9. tiene scoring final;
10. tiene tabla de trazabilidad;
11. puede reproducirse desde codigo y YAML.

## 22. Criterios de rechazo o cuarentena

Una fuente no debe usarse como entrenamiento directo si presenta alguna de las siguientes condiciones sin resolucion:

- origen documental desconocido;
- ano ausente o incompatible;
- CRS indefinido y sin forma confiable de reconstruirlo;
- coordenadas fuera del pais o AOI;
- leyenda no homologable;
- clases mezcladas sin criterio;
- conflictos tematicos severos no revisados;
- ausencia total de trazabilidad;
- resultados espectrales con alerta alta generalizada;
- duplicados masivos sin regla de deduplicacion;
- fuente derivada de otro producto ya usado, sin valor adicional claro.

Estas fuentes pueden mantenerse como referencia contextual o apoyo interpretativo, pero no deben ingresar al nucleo de entrenamiento sin revision experta.

## 23. Plantilla de bitacora metodologica

Cada usuario debe completar una bitacora corta por fuente:

```text
Nombre de fuente:
Responsable:
Fecha de ejecucion:
Version del repositorio/script:
YAML usado:
Archivo original:
AOI usado:
Ano base:
Tipo de fuente:
Regla de extraccion:
Regla de homologacion:
Distancias evaluadas:
Escenario seleccionado:
Numero de puntos candidatos:
Numero de puntos seleccionados:
Clases representadas:
Alertas principales:
Categoria final dominante:
Limitaciones:
Decision de uso:
```

## 24. Secuencia operativa recomendada

Para una nueva fuente, se recomienda seguir esta secuencia:

1. Registrar la fuente en el catalogo documental.
2. Crear YAML del caso.
3. Preparar o generar puntos candidatos.
4. Crear tabla de homologacion.
5. Ejecutar homologacion.
6. Generar grupos XY.
7. Revisar conflictos espaciales y tematicos.
8. Preparar insumos GEE.
9. Ejecutar extraccion Sentinel-2.
10. Unir resultados espectrales.
11. Ejecutar auditoria espectral.
12. Calcular scoring A1.
13. Revisar categorias de uso.
14. Normalizar al modelo A3/A2.1.
15. Revisar reportes y tablas de control.
16. Documentar decision final.

## 25. Codigo y configuraciones de referencia

Los usuarios que repliquen la Actividad 3 deben revisar los siguientes archivos del repositorio:

### Flujo general

```text
src/actividad_3/sampling.py
src/actividad_3/run_bosque_deciduo_sampling.py
src/actividad_3/a3_auditorias_nuevas_fuentes/02_xy_groups_nuevas_fuentes.py
src/actividad_3/a3_auditorias_nuevas_fuentes/03_s2_sr_gee_input_nuevas_fuentes_caso_SINAC.py
src/actividad_3/a3_auditorias_nuevas_fuentes/05_join_s2sr_to_sinac_src10_2021_records.py
src/actividad_3/a3_auditorias_nuevas_fuentes/06_s2sr_spectral_class_audit_sinac_src10_2021.py
src/actividad_3/a3_auditorias_nuevas_fuentes/08_scoring_integral_nuevas_fuentes.py
src/actividad_3/a3_auditorias_nuevas_fuentes/09_normalizacion_nuevas_fuentes.py
src/actividad_3/a3_auditorias_nuevas_fuentes/a1_scoring_package.py
```

### Casos piloto

```text
src/actividad_3/a3_auditorias_nuevas_fuentes/caso_SINAC/
src/actividad_3/a3_auditorias_nuevas_fuentes/caso_panama_v2/
src/actividad_3/mangrove_extraction/
```

### Configuraciones

```text
config/a3_auditorias_nuevas_fuentes/caso_SINAC/config_sinac_src10_2021.yaml
config/a3_auditorias_nuevas_fuentes/caso_panama_v2/config_mapa_forestal_panama_2021_a1.yaml
config/a3_auditorias_nuevas_fuentes/config_normalizacion_nuevas_fuentes.yaml
config/mapa_forestal_panama_sampling.yaml
config/mangrove_sampling.yaml
config/scoring_aptitud.yaml
config/source_catalog.csv
```

### Homologaciones

```text
docs/actividad_3/SINAC/homologacion_sinac_a1.csv
docs/actividad_3/Panama/homologacion_panama_a1.csv
```

## 26. Consideraciones finales

La Actividad 3 debe entenderse como un puente entre el diagnostico de vacios de la Actividad 1 y la construccion de datos utilizables para modelado o validacion. Su valor no esta solo en extraer mas puntos, sino en extraerlos con trazabilidad, evaluar su consistencia y clasificarlos segun su aptitud.

Una fuente nueva no debe considerarse exitosa solo por producir muchos puntos. Debe responder positivamente a tres preguntas:

1. **Es documentable?** Se conoce su origen, ano, tipo y restricciones.
2. **Es comparable?** Sus clases pueden homologarse a la leyenda A1.
3. **Es utilizable?** Sus puntos tienen calidad espacial, temporal, tematica y espectral suficiente para el uso propuesto.

Si alguna respuesta es negativa, la fuente puede seguir siendo valiosa, pero su uso debe limitarse a apoyo interpretativo, referencia contextual, revision experta o mascara auxiliar.
