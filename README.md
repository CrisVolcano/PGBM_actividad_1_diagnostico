# PGBM - Actividades de diagnóstico y modelado geoespacial

## Resumen

Repositorio reproducible del proyecto PGBM que contiene múltiples actividades: diagnóstico regional de aptitud, auditorías de datos geoespaciales, normalización, muestreo y modelado predictivo. Incluye auditorías estructurales, espaciales, temporales y temáticas, junto con preparación de datos y modelos para actividades 2, 3 y 4.

## Estructura del repositorio

- `config/`: YAML de configuración para auditorías, extracción, normalización y modelado.
- `data/`: datos organizados en `raw/`, `interim/`, `processed/`, `external/` y `maps/`.
- `src/`: código fuente por actividad (`actividad_1` a `actividad_4`) y utilidades.
- `notebooks/`: scripts y notebooks para inspección de GPKG, auditorías y análisis de resultados.
- `docs/`: documentación de entregables y resultados de la actividad 1.
- `outputs/`: figuras, mapas, reportes y tablas generadas.
- `logs/`: registros de decisiones metodológicas y auditorías.

## Descripción de actividades

- `Actividad 1`: Diagnóstico regional de aptitud de fuentes y vacíos de información.
  - Inventario de fuentes y metadatos.
  - Auditoría estructural de la base de datos.
  - Auditoría espacial de multirregistros, coordenadas y calidad geoespacial.
  - Auditoría temporal y análisis de ventanas de tiempo.
  - Auditoría temática y clasificación de conflictos semánticos.
  - Scoring multicriterio y clasificación funcional.
  - Principal código en `src/actividad_1/`, documentación en `docs/actividad_1/` y validación en `notebooks/`.

- `Actividad 2`: Preparación y normalización de datos para modelado.
  - Normalización de clases y atributos.
  - Generación de grillas de densidad y balance de puntos.
  - Preparación de dataset de entrenamiento espacialmente balanceado.
  - Código clave en `src/actividad_2/`.

- `Actividad 3`: Auditoría de nuevas fuentes y muestreo especializado.
  - Evaluación de nuevas fuentes de datos y auditorías adicionales.
  - Muestreo de bosque deciduo y otros casos de estudio.
  - Extracción y validación de muestras de entrenamiento.
  - Código clave en `src/actividad_3/`.

- `Actividad 4`: Extracción de predictores y modelado predictivo.
  - Extracción de puntos piloto y cuadrantes piloto.
  - Preparación de predictores ráster y normalización de salidas puntuales.
  - Validación de entradas de modelado y variogramas espaciales.
  - Entrenamiento y comparación de modelos RF, DNN, SVM y XGBoost.
  - Generación de mapas de predicción raster y comparación de resolución/consenso.
  - Código clave en `src/actividad_4/`.

## Entorno de trabajo

El proyecto utiliza Python 3.11 y dependencias manejadas por Conda.

Crear el entorno:

```bash
conda env create -f environment.yml
```

Activar el entorno:

```bash
conda activate pgbm_actividad1
```

Herramientas de desarrollo y formato:

- `black`
- `ruff`
- `isort`

## Archivos clave

- `environment.yml`: entorno Conda y dependencias principales.
- `pyproject.toml`: metadatos de proyecto, configuración de `black`, `ruff` e `isort`.
- `config/config.yaml`: configuración general del flujo de trabajo.
- `logs/decisiones_metodologicas.csv`: trazabilidad de decisiones metodológicas.
- `docs/actividad_1/`: entregables de alcance, inventario, auditorías y scoring.
- `src/actividad_1/`: código fuente para el diagnóstico de la primera actividad.
- `notebooks/`: análisis exploratorios y notebooks de validación.

## Flujo recomendado

1. Revisar configuraciones en `config/` y datos en `data/`.
2. Ejecutar auditorías con el código en `src/actividad_1`.
3. Inspeccionar resultados y generadores en `notebooks/`.
4. Documentar las decisiones en `logs/decisiones_metodologicas.csv`.
5. Revisar entregables y análisis en `docs/actividad_1`.
6. Guardar outputs en `outputs/`.

