# Propuesta metodológica para la extracción de puntos de referencia desde fuentes temáticas

## 1. Objetivo

El objetivo de esta metodología es generar conjuntos de puntos de referencia a partir de diferentes fuentes temáticas disponibles para la región de estudio, con el fin de apoyar procesos de validación, comparación, homologación temática y análisis de consistencia entre mapas de cobertura y uso del suelo.

La propuesta busca ser suficientemente general para aplicarse a distintas fuentes espaciales, incluyendo:

* mapas regionales de cobertura o uso del suelo;
* mapas nacionales o locales;
* productos derivados de clasificación supervisada o no supervisada;
* capas vectoriales de polígonos temáticos;
* rásteres categóricos;
* áreas de clasificación previamente delimitadas;
* fuentes auxiliares con información temática útil para interpretación o validación.

El enfoque prioriza una metodología simple, reproducible y auditable. La intención no es construir un sistema complejo de optimización del muestreo, sino una estrategia práctica que permita extraer puntos de manera consistente desde múltiples fuentes, conservando la trazabilidad de su origen y evitando, en la medida de lo posible, la pérdida completa de clases temáticas relevantes.

---

## 2. Principios generales de la metodología

La metodología se basa en los siguientes principios:

1. **Generalidad**
   El procedimiento debe poder aplicarse tanto a fuentes vectoriales como raster, siempre que sea posible identificar una clase temática asociada a cada unidad espacial o píxel.

2. **Simplicidad operativa**
   El método debe ser fácil de configurar mediante archivos externos, evitando modificaciones constantes en el código fuente.

3. **Trazabilidad**
   Cada punto debe conservar información sobre su fuente original, clase temática, identificador de origen y método de extracción.

4. **Representación temática mínima**
   Las clases disponibles en la fuente no deberían desaparecer del conjunto final únicamente por efecto del filtrado espacial. Por ello, se incorpora una regla simple para conservar al menos un número mínimo de puntos por clase.

5. **Reducción de redundancia espacial**
   Después de asegurar la representación mínima por clase, se aplican escenarios de distancia mínima entre puntos para evitar concentraciones excesivas y reducir redundancia espacial.

6. **Auditoría de resultados**
   El proceso debe generar tablas de resumen que permitan evaluar cuántos puntos fueron extraídos, cuántas clases quedaron representadas y cómo cambian los resultados bajo diferentes distancias mínimas.

---

## 3. Tipos de fuentes consideradas

La metodología contempla dos grandes tipos de fuentes temáticas: vectoriales y raster.

---

## 3.1. Fuentes vectoriales

Las fuentes vectoriales corresponden a capas de polígonos con atributos temáticos asociados. Algunos ejemplos son:

* mapas nacionales de cobertura y uso del suelo;
* mapas regionales de bosque/no bosque;
* mapas de vegetación;
* inventarios forestales;
* áreas de clasificación manual;
* polígonos de entrenamiento o validación;
* unidades cartográficas temáticas.

En este caso, cada polígono o fragmento de polígono contiene uno o más campos que permiten identificar su clase temática.

Ejemplos de campos posibles:

```text
CLAVE
DESCRIPCIO
CODE
CLASS
ID_CLASE
NIVEL_1
NIVEL_2
COBERTURA
USO_SUELO
```

El usuario debe indicar en la configuración cuál campo representa el identificador de clase y, opcionalmente, cuál campo representa la descripción o etiqueta temática.

---

## 3.2. Fuentes raster

Las fuentes raster corresponden a mapas categóricos donde el valor de cada píxel representa una clase temática.

Algunos ejemplos son:

* mapas regionales raster de cobertura;
* clasificaciones supervisadas;
* productos derivados de sensores satelitales;
* mapas binarios de bosque/no bosque;
* mapas multiclase;
* capas raster de cambio/no cambio;
* mapas locales producidos por clasificación automática.

En este caso, la clase temática se obtiene a partir del valor del píxel. Si existe una tabla externa de clases, esta puede utilizarse para traducir los valores numéricos del raster a nombres de clase.

Ejemplo:

```text
1 = Bosque
2 = No bosque
3 = Agricultura
4 = Pastos
5 = Agua
```

Para evitar generar un punto por cada píxel, especialmente en rásteres de alta resolución, se utiliza una malla de puntos candidatos con un espaciamiento definido por el usuario.

---

## 4. Estructura general del flujo metodológico

El procedimiento se divide en siete etapas principales:

```text
1. Definición del área de interés.
2. Lectura y validación de la fuente temática.
3. Recorte espacial de la fuente al área de interés.
4. Generación de puntos candidatos.
5. Estandarización de atributos temáticos.
6. Selección de puntos con representación mínima por clase.
7. Aplicación de escenarios de distancia mínima y generación de salidas auditables.
```

---

## 5. Definición del área de interés

El primer paso consiste en definir el área geográfica dentro de la cual se realizará la extracción de puntos.

Esta área puede estar definida por:

* límites administrativos;
* países;
* regiones de estudio;
* zonas ecológicas;
* tiles satelitales;
* áreas de proyecto;
* polígonos de interés definidos manualmente.

Cuando el área de interés se construye a partir de límites administrativos, se pueden aplicar filtros por código, nombre o atributos específicos. También es posible excluir elementos no deseados, por ejemplo islas, cuerpos de agua o geometrías fuera del ámbito de análisis.

El área de interés cumple dos funciones:

1. limitar espacialmente la fuente temática;
2. asegurar que los puntos extraídos pertenezcan únicamente al ámbito de trabajo definido.

---

## 6. Sistema de referencia y unidades de trabajo

Para calcular áreas y distancias, las capas deben procesarse en un sistema de coordenadas proyectado en metros.

Por ello, la metodología distingue entre:

```text
CRS de procesamiento
```

y

```text
CRS de salida
```

El CRS de procesamiento se utiliza para:

* calcular áreas;
* aplicar distancias mínimas;
* generar mallas;
* evaluar proximidad entre puntos.

El CRS de salida se utiliza para exportar las capas finales, generalmente en coordenadas geográficas, por ejemplo EPSG:4326.

Esta separación permite realizar cálculos espaciales correctamente y, al mismo tiempo, entregar resultados en un formato común para visualización o intercambio.

---

## 7. Preparación de la fuente temática

## 7.1. Preparación de fuentes vectoriales

Para fuentes vectoriales, el proceso consiste en:

1. leer la capa temática;
2. verificar que tenga CRS definido;
3. reparar geometrías inválidas si es necesario;
4. reproyectar al CRS de procesamiento;
5. recortar la fuente al área de interés;
6. calcular el área de cada fragmento resultante;
7. generar un identificador único de origen;
8. construir una clase o estrato temático estandarizado.

Cuando la capa de entrada tiene un identificador original, este se conserva. Cuando no lo tiene, se genera un identificador interno basado en el orden de lectura o en una combinación de atributos y geometría.

Para cada polígono recortado se genera una estructura mínima como:

```text
source_uid
source_objectid
class_id
class_label
stratum_id
area_ha
geometry
```

Donde:

* `source_uid` identifica de forma única la unidad de origen;
* `source_objectid` conserva el identificador original, si existe;
* `class_id` corresponde al código de clase;
* `class_label` corresponde al nombre o descripción de la clase;
* `stratum_id` combina código y descripción para definir una unidad temática única;
* `area_ha` corresponde al área del fragmento recortado.

---

## 7.2. Preparación de fuentes raster

Para fuentes raster, el proceso consiste en:

1. leer el raster categórico;
2. verificar su CRS;
3. reproyectar o trabajar en un CRS compatible con el área de interés;
4. recortar el raster al área de interés;
5. generar una malla de puntos candidatos;
6. extraer el valor del raster en cada punto;
7. eliminar puntos con valores NoData;
8. unir una tabla de clases, si existe;
9. construir los campos temáticos estandarizados.

A diferencia del vector, donde los candidatos derivan de polígonos, en raster los candidatos derivan de una malla de puntos.

La distancia entre puntos de esa malla se define mediante:

```text
candidate_spacing_m
```

Este parámetro representa el espaciamiento inicial entre puntos candidatos para leer el raster.

Por ejemplo:

```text
candidate_spacing_m = 500
```

significa que se generará aproximadamente un punto cada 500 metros dentro del área de interés. En cada punto se lee el valor del raster y ese valor se usa como clase temática.

Este parámetro no debe confundirse con la distancia mínima final entre puntos seleccionados.

La diferencia es:

```text
candidate_spacing_m
```

define la densidad inicial de puntos candidatos en fuentes raster.

```text
thinning_distances_m
```

define las distancias mínimas usadas para seleccionar los puntos finales.

El uso de `candidate_spacing_m` evita generar millones de puntos cuando el raster tiene resolución fina, por ejemplo 10 m o 30 m. En lugar de leer cada píxel, se toma una muestra sistemática controlada por el espaciamiento definido.

---

## 8. Generación de puntos candidatos

La generación de puntos candidatos depende del tipo de fuente.

---

## 8.1. Puntos candidatos desde polígonos

Para fuentes vectoriales, se genera al menos un punto por fragmento poligonal recortado al área de interés.

El punto se genera dentro del polígono usando un método de punto interior, por ejemplo:

```text
point_on_surface
```

Este método tiene la ventaja de que el punto cae dentro de la geometría, incluso en polígonos irregulares o multipartes.

Cada punto candidato conserva los atributos temáticos del polígono del cual proviene.

---

## 8.2. Puntos candidatos desde raster

Para fuentes raster, los puntos candidatos se generan a partir de una malla regular dentro del área de interés.

El procedimiento general es:

```text
1. Crear una malla de puntos separados por candidate_spacing_m.
2. Conservar únicamente los puntos dentro del área de interés.
3. Extraer el valor del raster en cada punto.
4. Eliminar valores NoData.
5. Convertir el valor raster en class_id.
6. Asociar una etiqueta class_label si existe una tabla de clases.
```

Este enfoque permite aplicar la misma lógica de selección posterior tanto a fuentes vectoriales como raster.

---

## 9. Estandarización temática

Independientemente del tipo de fuente, todos los puntos candidatos se transforman a una estructura común.

La estructura mínima recomendada es:

```text
candidate_id
point_id
source_name
source_type
source_uid
source_objectid
class_id
class_label
stratum_id
area_ha
geometry
```

Donde:

* `candidate_id` es el identificador interno del candidato;
* `point_id` es el identificador final del punto;
* `source_name` indica el nombre de la fuente;
* `source_type` indica si la fuente es vectorial o raster;
* `source_uid` identifica la unidad espacial o píxel de origen;
* `source_objectid` conserva el identificador original, cuando existe;
* `class_id` corresponde al código de clase;
* `class_label` corresponde a la etiqueta de clase;
* `stratum_id` corresponde a la unidad temática usada para el muestreo;
* `area_ha` corresponde al área asociada, cuando aplica;
* `geometry` corresponde a la geometría puntual.

El campo `stratum_id` es especialmente importante porque define la unidad temática sobre la cual se asegura la representación mínima.

En fuentes simples puede ser igual a:

```text
class_id
```

En fuentes con código y descripción puede construirse como:

```text
class_id | class_label
```

---

## 10. Representación mínima por clase

Uno de los problemas de aplicar únicamente una distancia mínima global es que las clases pequeñas, raras o fragmentadas pueden desaparecer del conjunto final.

Para evitarlo, la metodología incorpora una etapa sencilla de protección temática.

La regla general es:

```text
Si una clase tiene puntos candidatos disponibles, se intenta conservar al menos N puntos para esa clase.
```

Por defecto, se recomienda:

```text
minimum_points_per_class = 1
```

Esto significa que cada clase disponible en la fuente debe quedar representada por al menos un punto, siempre que existan candidatos válidos.

Esta regla evita que el muestreo quede dominado únicamente por clases extensas o polígonos grandes.

---

## 11. Clases prioritarias

La metodología permite definir clases prioritarias. Estas son clases que, por interés del proyecto, dificultad de interpretación o importancia temática, pueden recibir un número mínimo mayor de puntos.

Ejemplos de clases prioritarias podrían ser:

* bosques secos;
* bosques de coníferas;
* manglares;
* clases de transición;
* clases con alta confusión temática;
* coberturas raras o fragmentadas;
* clases relevantes para la homologación regional.

La definición de clases prioritarias debe hacerse desde la configuración externa, no desde el código. Esto permite adaptar el procedimiento a cada fuente sin modificar la metodología general.

Ejemplo conceptual:

```yaml
priority_classes:
  enabled: true
  field: "stratum_id"
  values:
    - "BS | Bosque seco"
    - "BC | Bosque de coníferas"
  minimum_points_per_class: 3
```

En este ejemplo, las clases prioritarias intentan conservar al menos tres puntos, mientras que las clases normales conservan al menos uno.

---

## 12. Separación espacial mínima

Después de asegurar la representación mínima por clase, se aplica una selección por distancia mínima entre puntos.

La distancia mínima se evalúa mediante escenarios definidos por el usuario, por ejemplo:

```text
500 m
1000 m
2000 m
3000 m
5000 m
```

Cada escenario produce una capa diferente de puntos seleccionados.

La lógica es:

```text
A mayor distancia mínima, menor cantidad de puntos seleccionados.
```

Por ejemplo, se espera que:

```text
puntos_d0500 > puntos_d1000 > puntos_d2000 > puntos_d3000 > puntos_d5000
```

La selección por distancia permite reducir redundancia espacial y generar alternativas de muestreo más o menos densas.

---

## 13. Orden de selección

Cuando dos o más puntos compiten por la misma distancia mínima, se utiliza un criterio de orden para decidir cuál se conserva primero.

Un criterio simple y práctico es conservar primero los puntos asociados a unidades espaciales más grandes.

Ejemplo:

```yaml
selection_order:
  - "area_desc"
  - "objectid_asc"
```

Esto significa:

1. seleccionar primero candidatos de mayor área;
2. usar el identificador original como criterio secundario.

Este criterio es simple y reproducible. Sin embargo, debe entenderse como una regla operativa, no como una optimización estadística.

---

## 14. Puntos protegidos y distancia mínima

Los puntos seleccionados para garantizar representación mínima por clase pueden quedar más cerca entre sí que la distancia mínima definida.

Esto no debe interpretarse como un error, sino como una decisión metodológica.

La lógica es:

```text
La representación temática mínima tiene prioridad sobre la distancia espacial perfecta.
```

Por ello, los puntos protegidos deben quedar identificados en la salida mediante un campo como:

```text
selection_status
```

Con valores posibles como:

```text
selected_minimum_class
selected_distance
rejected_distance
```

De esta forma, cualquier usuario puede distinguir entre puntos seleccionados por representación temática y puntos seleccionados por distancia espacial.

---

## 15. Salidas esperadas

La metodología debe generar tanto capas espaciales como tablas de auditoría.

---

## 15.1. Capas espaciales

Las capas espaciales mínimas recomendadas son:

```text
aoi
fuente_recortada
puntos_candidatos
puntos_d0500
puntos_d1000
puntos_d2000
puntos_d3000
puntos_d5000
```

Donde:

* `aoi` corresponde al área de interés;
* `fuente_recortada` corresponde a la fuente temática limitada al AOI;
* `puntos_candidatos` contiene todos los puntos generados antes del filtrado;
* `puntos_dXXXX` contiene los puntos seleccionados bajo cada escenario de distancia mínima.

---

## 15.2. Tablas de auditoría

Las tablas recomendadas son:

```text
catalogo_clases
resumen_distancias
resumen_clases
resumen_representacion_clases
resumen_estados
resumen_dominios
resumen_poligonos
seleccion_auditoria
run_metadata
```

Estas tablas permiten responder preguntas como:

* ¿cuántas clases existen en la fuente?
* ¿cuántos candidatos se generaron por clase?
* ¿cuántos puntos quedaron seleccionados por escenario?
* ¿qué clases quedaron representadas?
* ¿alguna clase quedó sin puntos?
* ¿cuántos puntos fueron protegidos por representación mínima?
* ¿cuántos puntos fueron eliminados por distancia?
* ¿qué configuración se usó para generar los resultados?

---

## 16. Evaluación de resultados

Después de ejecutar el proceso, se recomienda revisar los resultados en tres niveles.

---

## 16.1. Revisión tabular

Primero deben revisarse las tablas:

```text
catalogo_clases
resumen_distancias
resumen_representacion_clases
seleccion_auditoria
```

La tabla más importante para evaluar la representación temática es:

```text
resumen_representacion_clases
```

En esta tabla debe revisarse si alguna clase presenta:

```text
missing_after_selection = 1
```

Esto indicaría que la clase quedó sin puntos en un escenario determinado.

---

## 16.2. Revisión espacial

Luego se debe abrir el GeoPackage en un SIG, por ejemplo QGIS, y revisar:

* que los puntos estén dentro del área de interés;
* que no existan puntos fuera del AOI;
* que las zonas excluidas hayan sido respetadas;
* que los puntos candidatos cubran razonablemente la fuente;
* que los escenarios de distancia tengan densidades coherentes;
* que las clases prioritarias estén representadas.

---

## 16.3. Revisión temática

Finalmente, se debe revisar si las clases extraídas son útiles para los objetivos del proyecto.

En esta etapa pueden identificarse:

* clases redundantes;
* clases que requieren homologación;
* clases que deben agruparse;
* clases prioritarias;
* clases con baja representación;
* clases que deben excluirse del análisis.

Esta revisión puede alimentar una segunda ejecución del proceso con ajustes en la configuración.

---

## 17. Configuración general del método

La metodología debe controlarse mediante un archivo de configuración. Esto evita modificar el código para cada fuente.

Una estructura general de configuración puede ser:

```yaml
project:
  name: thematic_sampling
  source_name: "SOURCE_NAME"
  base_year: 2020

inputs:
  thematic_source:
    source_type: "vector"

    vector:
      path: "path/to/vector_file.gpkg"
      layer: null
      fields:
        object_id: null
        class_id: "CLASS_CODE"
        class_label: "CLASS_NAME"

    raster:
      path: null
      band: 1
      nodata: null
      class_table: null
      candidate_spacing_m: 500
      fields:
        class_id: "value"
        class_label: "label"

sampling:
  class_representation:
    enabled: true
    class_field: "stratum_id"
    minimum_points_per_class: 1

    priority_classes:
      enabled: true
      field: "stratum_id"
      values: []
      minimum_points_per_class: 3

    keep_protected_points_even_if_close: true

  thinning_distances_m:
    - 500
    - 1000
    - 2000
    - 3000
    - 5000

  selection_order:
    - "area_desc"
    - "objectid_asc"
```

---

## 18. Interpretación del parámetro `candidate_spacing_m`

El parámetro `candidate_spacing_m` se utiliza únicamente para fuentes raster.

Este parámetro define cada cuántos metros se genera un punto candidato para leer el valor del raster.

Por ejemplo:

```yaml
candidate_spacing_m: 500
```

significa que se generará una malla de puntos separados aproximadamente cada 500 metros. En cada punto se extrae el valor del raster y ese valor se convierte en clase temática.

Este parámetro permite controlar el tamaño inicial del conjunto de candidatos.

Valores más pequeños generan más puntos candidatos:

```text
250 m = más candidatos
500 m = cantidad intermedia
1000 m = menos candidatos
```

La elección depende de:

* resolución del raster;
* tamaño del área de estudio;
* fragmentación de las clases;
* capacidad de procesamiento;
* nivel de detalle deseado.

Como regla práctica:

```text
500 m puede usarse como valor inicial para exploración regional.
250 m puede usarse si se pierden clases pequeñas o fragmentadas.
1000 m puede usarse si el área es muy grande o el proceso genera demasiados candidatos.
```

---

## 19. Ventajas de la propuesta

La propuesta tiene varias ventajas:

1. **Es aplicable a múltiples fuentes**
   Puede usarse con mapas nacionales, regionales, locales, vectoriales o raster.

2. **Es simple de explicar**
   Primero se generan candidatos, luego se asegura representación mínima por clase y finalmente se aplica distancia espacial.

3. **Es configurable**
   Los campos de clase, rutas, distancias y clases prioritarias se definen fuera del código.

4. **Es auditable**
   Las salidas permiten revisar cuántos puntos fueron generados, seleccionados o rechazados.

5. **Reduce pérdida temática**
   La representación mínima evita que clases raras desaparezcan automáticamente.

6. **Permite comparar escenarios**
   Las diferentes distancias mínimas permiten seleccionar posteriormente el escenario más adecuado.

---

## 20. Limitaciones

La metodología no busca producir un diseño estadístico óptimo de muestreo. Su propósito es generar una base práctica de puntos de referencia a partir de fuentes existentes.

Algunas limitaciones son:

* la calidad de los puntos depende de la calidad de la fuente temática original;
* los puntos no sustituyen la validación visual o de campo;
* en fuentes raster, el resultado depende del espaciamiento inicial de la malla;
* las clases muy pequeñas pueden requerir ajustes específicos;
* los puntos protegidos por clase pueden incumplir la distancia mínima;
* las clases temáticas deben revisarse antes de integrarse a una leyenda homologada.

Estas limitaciones deben documentarse y considerarse durante la interpretación de resultados.

---

## 21. Uso dentro del flujo de homologación

Los puntos generados mediante esta metodología pueden usarse como insumos para:

* revisión visual de clases;
* comparación entre mapas nacionales y regionales;
* evaluación de consistencia temática;
* identificación de clases problemáticas;
* análisis de confusión entre leyendas;
* construcción de ejemplos para validación;
* apoyo a procesos de homologación temática.

La extracción de puntos no reemplaza el proceso de homologación, sino que lo complementa. La fuente original conserva su leyenda y sus atributos, mientras que la homologación puede realizarse posteriormente mediante tablas de correspondencia.

---

## 22. Conclusión

La metodología propuesta permite extraer puntos de referencia desde múltiples fuentes temáticas de forma simple, reproducible y auditable.

El procedimiento se basa en una lógica común:

```text
fuente temática → puntos candidatos → representación mínima por clase → distancia mínima → salidas auditables
```

Este enfoque permite trabajar con fuentes vectoriales y raster sin modificar la lógica principal del método. Además, evita que clases temáticas relevantes desaparezcan del conjunto final únicamente por efecto del filtrado espacial.

La propuesta mantiene un equilibrio entre simplicidad metodológica y control de calidad, permitiendo adaptar la extracción de puntos a diferentes fuentes, escalas y objetivos del proyecto.
