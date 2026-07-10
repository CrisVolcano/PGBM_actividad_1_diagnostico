# Metodología de extracción de puntos para cuadrantes piloto

## Objetivo

Construir una extensión normalizada del modelo A2.1 que asigne puntos `xy_point` a
cuadrantes piloto sin duplicar atributos que ya tienen una fuente maestra.

La extensión materializa únicamente:

- el subconjunto espacial de puntos piloto;
- las zonas y los cuadrantes piloto;
- la relación `xy_group_id → id_cuadrante`;
- la geometría interior usada para la asignación;
- los metadatos y posibles conflictos del proceso.

Los países, las clases, la homologación, los puntajes y las acciones permanecen en las
tablas canónicas de A2.1.

## Script

El flujo está implementado en:

```text
src/actividad_4/extract_pilot_quadrant_points.py
```

Ejecución recomendada desde la raíz del repositorio:

```bash
conda run -n pgbm_actividad1 python src/actividad_4/extract_pilot_quadrant_points.py
```

## Insumos

### Modelo normalizado A2.1

Archivo:

```text
data/processed/a2_1_modelo_datos/gpkg/a2_1_xy_point.gpkg
```

El extractor usa:

- `xy_point`, con `xy_group_id`, coordenadas, geometría y las FK normalizadas
  `id_pais_grupo`, `id_0`, `id_1` e `id_2`;
- `xy_accion`, únicamente para seleccionar los puntos cuyo
  `categoria_uso_actividad_1_8` sea `entrenamiento` o `validación`.

No se copian `pais`, los catálogos de clase, `xy_homologacion_final`, `xy_score` ni
`xy_accion` al GeoPackage de Actividad 4. Estas tablas siguen siendo la fuente
canónica y se consultan mediante `xy_group_id` o las FK correspondientes.

### Cuadrantes piloto

Archivo:

```text
data/raw/cuadrantes_pilotos/zonas_cuadrantes_pilotos.gpkg
```

Capa:

```text
zonas_cuadrantes
```

Campos requeridos:

- `id_zona`;
- `id_cuadrante`;
- `geometry`.

`id_cuadrante` debe ser único globalmente. Una zona puede contener varios cuadrantes.

## Flujo metodológico

1. Validar los insumos, el CRS, los campos obligatorios, la nulabilidad de los
   identificadores y la unicidad global de `id_cuadrante`.

2. Construir `pilot_zone` disolviendo los polígonos por `id_zona`.

3. Construir `pilot_quadrant` con:

   ```text
   id_cuadrante (PK lógica)
   id_zona       (FK lógica a pilot_zone)
   geometry
   ```

4. Reproyectar los cuadrantes a un CRS métrico y aplicar un buffer negativo. La
   distancia predeterminada es 30 m y puede modificarse con
   `--buffer-negative-m`.

5. Guardar la geometría reducida en `pilot_quadrant_buffer`. La geometría original de
   `pilot_quadrant` no se modifica.

6. Leer de `xy_point` los puntos candidatos contenidos en el bbox de los cuadrantes
   reducidos. El extractor exige el esquema 3FN vigente; si, por ejemplo, aparece
   `pais_grupo` en vez de `id_pais_grupo`, la ejecución falla de forma explícita.

7. Ejecutar el join espacial con el predicado `within` por defecto.

8. Detectar puntos que coincidan con más de un cuadrante reducido. Por defecto se
   excluyen y se registran en las tablas de conflicto. El script nunca selecciona
   silenciosamente la primera coincidencia. Con `--multiple-match-policy raise`, la
   ejecución se detiene al detectar el conflicto.

9. Consultar `xy_accion` y conservar solamente asignaciones con uso
   `entrenamiento` o `validación`. La tabla se usa como filtro, pero no se duplica en
   la salida.

10. Materializar `pilot_xy_point` con los campos:

    ```text
    xy_group_id
    lon
    lat
    id_pais_grupo
    id_0
    id_1
    id_2
    geometry
    ```

11. Crear `xy_pilot_quadrant` con solo:

    ```text
    xy_group_id
    id_cuadrante
    ```

12. Exportar las entidades, la relación y los metadatos al GeoPackage normalizado.
    Se crean índices únicos sobre las claves lógicas para impedir duplicados.

## Productos generados

GeoPackage:

```text
data/processed/a4_pilot_quadrant_extraction/gpkg/pilot_quadrant_extraction_normalized.gpkg
```

Log:

```text
data/processed/a4_pilot_quadrant_extraction/logs/extract_pilot_quadrant_points_normalized.log
```

Capas espaciales:

- `pilot_xy_point`;
- `pilot_zone`;
- `pilot_quadrant`;
- `pilot_quadrant_buffer`.

Tablas atributivas:

- `pilot_buffer_run`;
- `pilot_assignment_run`;
- `xy_pilot_quadrant`;
- `xy_pilot_quadrant_conflict`;
- `xy_pilot_quadrant_conflict_match`.

No se generan capas por cuadrante ni una capa plana enriquecida.

## Respuesta a la tercera forma normal

La relación central cumple la dependencia:

```text
xy_group_id → id_cuadrante
```

No almacena `id_zona`, porque:

```text
id_cuadrante → id_zona
```

Guardar ambos campos en `xy_pilot_quadrant` introduciría la dependencia transitiva
`xy_group_id → id_cuadrante → id_zona`. La zona se resuelve mediante
`pilot_quadrant`.

Del mismo modo, `pilot_xy_point` conserva `id_pais_grupo`, pero no el nombre del país:

```text
id_pais_grupo → pais
```

El nombre vive una sola vez en `pais` dentro de A2.1. Las etiquetas de clase, la
homologación, los puntajes y las acciones también se resuelven en sus tablas
canónicas; Actividad 4 no crea segundos catálogos ni copias maestras.

`pilot_xy_point` es una proyección materializada y derivada de `xy_point`, no una nueva
fuente maestra. `xy_group_id` conserva la identidad y permite volver al modelo A2.1.

## Regla de bordes

El buffer negativo elimina una franja interior del ancho configurado antes de asignar
los puntos. Así, un punto cercano al límite entre cuadrantes no influye en la selección
del cuadrante vecino.

La distancia y el CRS métrico quedan registrados en `pilot_buffer_run`. Esta regla es
espacial y no altera las dependencias funcionales del modelo.

## Validaciones

El script comprueba:

- existencia de archivos, capas, tablas y campos obligatorios;
- presencia de CRS en las capas;
- `id_cuadrante` único y no nulo;
- `id_zona` no nulo y único en `pilot_zone`;
- `xy_group_id` único en los puntos y en `xy_accion`;
- presencia estricta de `id_pais_grupo`, `id_0`, `id_1` e `id_2`;
- una sola asignación válida por `xy_group_id`;
- registro o interrupción ante coincidencias múltiples;
- presencia de categoría de uso para toda asignación espacial;
- índices únicos sobre las claves lógicas de la salida.

Los GeoPackages generados permanecen fuera de Git mediante las reglas del repositorio
para `data/processed/` y `*.gpkg`.
