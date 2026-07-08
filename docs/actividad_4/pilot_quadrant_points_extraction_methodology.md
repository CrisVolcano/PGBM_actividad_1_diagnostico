# Metodología de extracción de puntos para cuadrantes piloto

## Objetivo

Construir una extracción reproducible de los puntos `xy_point` de A2.1 que caen dentro
de los cuadrantes piloto, enriqueciendo cada punto con:

- `id_1_propuesta`
- `nivel_1_propuesta`
- `score_aptitud_total`
- `uso`
- `id_zona`
- `id_cuadrante`

La salida conserva únicamente puntos con uso funcional `entrenamiento` o `validación`,
según la clasificación de aptitud de A1/A2.1. Esto permite revisar y analizar los puntos
disponibles por zona y cuadrante piloto sin modificar el GeoPackage original del modelo
de datos.

## Script

El flujo está implementado en:

```bash
src/actividad_4/extract_pilot_quadrant_points.py
```

Ejecución recomendada desde la raíz del repositorio:

```bash
conda run -n pgbm_actividad1 python src/actividad_4/extract_pilot_quadrant_points.py
```

El ambiente `pgbm_actividad1` se considera el ambiente pertinente porque está definido en
`environment.yml` e incluye las dependencias geoespaciales usadas por el proyecto
(`geopandas`, `pyogrio`, `fiona`, `gdal`, `shapely`, `pyproj`).

## Insumos

### Modelo de datos A2.1

Archivo:

```bash
data/processed/a2_1_modelo_datos/gpkg/a2_1_xy_point.gpkg
```

Capas/tablas utilizadas:

- `xy_point`: capa espacial principal de puntos.
- `xy_homologacion_final`: tabla atributiva para traer `id_1_propuesta` y
  `nivel_1_propuesta`.
- `xy_score`: tabla atributiva para traer `score_aptitud_total`.
- `xy_accion`: tabla atributiva para traer `categoria_aptitud_preliminar` y
  `categoria_uso_actividad_1_8`.

Llave de join:

```text
xy_group_id
```

### Cuadrantes piloto

Archivo:

```bash
data/raw/cuadrantes_pilotos/zonas_cuadrantes_pilotos.gpkg
```

Capa utilizada:

```text
zonas_cuadrantes
```

Campos utilizados:

- `id_zona`
- `id_cuadrante`
- `geometry`

## Flujo metodológico

1. Leer la capa `zonas_cuadrantes` y validar que tenga CRS, geometría y los campos
   `id_zona` e `id_cuadrante`.

2. Leer una muestra de `xy_point` para identificar el CRS de los puntos.

3. Reproyectar temporalmente los cuadrantes al CRS de `xy_point`, cuando sea necesario,
   y calcular el bbox total de los cuadrantes.

4. Leer de `xy_point` únicamente los puntos candidatos dentro del bbox de los cuadrantes.
   Esto reduce el volumen de lectura antes del cruce espacial.

5. Ejecutar un join espacial entre puntos candidatos y cuadrantes.

   Predicado por defecto:

   ```text
   within
   ```

   Es decir, se conserva cada punto cuya geometría cae dentro de un polígono de cuadrante.
   El script también permite `intersects` o `covered_by` mediante el argumento
   `--predicate`, si se requiere incluir casos sobre bordes.

6. Resolver posibles coincidencias múltiples.

   Si un punto cae en más de un cuadrante, el script ordena por `xy_group_id`,
   `id_zona` e `id_cuadrante`, y conserva la primera coincidencia. Esta regla deja una
   asignación determinística.

7. Leer las tablas atributivas `xy_homologacion_final`, `xy_score` y `xy_accion` desde
   el mismo GPKG de A2.1 mediante SQLite.

8. Validar unicidad de `xy_group_id` en:

   - puntos asignados a cuadrantes
   - `xy_homologacion_final`
   - `xy_score`
   - `xy_accion`

9. Hacer joins atributivos uno a uno:

   - `xy_point` -> `xy_homologacion_final`, para traer `id_1_propuesta` y
     `nivel_1_propuesta`.
   - `xy_point` -> `xy_score`, para traer `score_aptitud_total`.
   - `xy_point` -> `xy_accion`, para traer la categoría funcional de uso.

10. Crear la columna `uso` a partir de `categoria_uso_actividad_1_8`.

11. Filtrar la salida final a:

    - `uso = entrenamiento`, equivalente a `score_aptitud_total >= 85` cuando no
      existen reglas prioritarias de exclusión.
    - `uso = validación`, equivalente a `score_aptitud_total >= 70` y menor que el
      umbral de entrenamiento cuando no existen reglas prioritarias de exclusión.

    La clasificación completa de A1/A2.1 se respeta porque `xy_accion` ya incorpora
    las prioridades por conflicto activo, alerta espectral, prueba, referencia
    contextual y máscaras.

12. Validar que no queden puntos extraídos sin homologación final, sin
    `score_aptitud_total` ni sin categoría de uso.

13. Exportar la capa combinada, las capas individuales por cuadrante, una tabla resumen
    y una tabla de metadatos de ejecución.

## Productos generados

Directorio de salida:

```bash
data/processed/a4_pilot_quadrant_extraction/
```

Productos principales:

```bash
data/processed/a4_pilot_quadrant_extraction/gpkg/pilot_quadrant_points.gpkg
data/processed/a4_pilot_quadrant_extraction/tables/pilot_quadrant_summary.csv
data/processed/a4_pilot_quadrant_extraction/logs/extract_pilot_quadrant_points.log
```

El GeoPackage de salida contiene:

- `pilot_quadrant_points`: capa combinada con todos los puntos extraídos.
- `z{id_zona}_q{id_cuadrante}`: capas individuales por cuadrante.
- `pilot_quadrant_summary`: tabla resumen por zona y cuadrante.
- `pilot_quadrant_extraction_metadata`: metadatos de ejecución.

Campos principales de `pilot_quadrant_points`:

- `xy_group_id`
- `lon`
- `lat`
- `pais_grupo`
- `id_0`
- `id_1`
- `id_2`
- `id_1_propuesta`
- `nivel_1_propuesta`
- `score_aptitud_total`
- `categoria_aptitud_preliminar`
- `categoria_uso_actividad_1_8`
- `uso`
- `id_zona`
- `id_cuadrante`
- `geometry`

## Resultado de la ejecución actual

La ejecución actual con los insumos indicados produjo:

- Cuadrantes leídos: `45`
- Puntos candidatos dentro del bbox de cuadrantes: `689,790`
- Puntos asignados a cuadrantes: `107,604`
- Puntos exportados después del filtro entrenamiento/validación: `103,256`
- Puntos excluidos por no pertenecer a entrenamiento/validación: `4,348`
- Puntos exportados con `uso = entrenamiento`: `92,922`
- Puntos exportados con `uso = validación`: `10,334`
- Cuadrantes con al menos un punto: `45`

Rango de `score_aptitud_total` en la salida exportada:

- `entrenamiento`: `85.0` a `97.583`
- `validación`: `75.0` a `84.999`

El resumen por cuadrante se guarda en:

```bash
data/processed/a4_pilot_quadrant_extraction/tables/pilot_quadrant_summary.csv
```

## Validaciones realizadas

Se verificó que:

- Las capas y tablas requeridas existen en los GeoPackages de entrada.
- Los campos obligatorios están presentes.
- Las capas espaciales tienen CRS definido.
- `xy_group_id` no queda duplicado después de la asignación final a cuadrantes.
- Los joins atributivos contra homologación y score son uno a uno.
- No quedan puntos extraídos sin `id_1_propuesta`.
- No quedan puntos extraídos sin `score_aptitud_total`.
- No quedan puntos extraídos sin categoría de uso.
- La salida final contiene solo `uso = entrenamiento` o `uso = validación`.

Validaciones de código ejecutadas:

```bash
conda run -n pgbm_actividad1 python -m py_compile src/actividad_4/extract_pilot_quadrant_points.py
conda run -n pgbm_actividad1 ruff check src/actividad_4/extract_pilot_quadrant_points.py
```

## Consideraciones para GitHub

El archivo `pilot_quadrant_points.gpkg` no debe subirse al repositorio porque es una
salida geoespacial pesada. Actualmente queda protegido por `.gitignore` mediante:

```text
data/processed/
*.gpkg
```

Los archivos que sí deben versionarse para reproducir la extracción son:

- `src/actividad_4/extract_pilot_quadrant_points.py`
- `docs/actividad_4/pilot_quadrant_points_extraction_methodology.md`

Opcionalmente, si se quisiera versionar un resumen liviano en el futuro, habría que mover
o copiar una tabla depurada fuera de `data/processed/`, ya que ese directorio está
ignorado globalmente.
