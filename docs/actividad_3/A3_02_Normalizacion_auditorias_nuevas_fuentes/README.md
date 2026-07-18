# A3.2 — Normalización de auditorías y nuevas fuentes

## Objetivo

Normalizar las salidas finales de SINAC y del Mapa Forestal de Panamá con el
mismo modelo relacional de A2.1, mediante un código A3 independiente.

El proceso no requiere los datos intermedios de las auditorías. Parte de la
capa `xy_group_aptitude_master` presente en cada GeoPackage final.

## Implementación

- Código: `src/actividad_3/a3_auditorias_nuevas_fuentes/09_normalizacion_nuevas_fuentes.py`
- Configuración: `config/a3_auditorias_nuevas_fuentes/config_normalizacion_nuevas_fuentes.yaml`

Un solo ejecutable procesa las dos fuentes configuradas. Cada fuente se valida
y se escribe en un directorio independiente para evitar mezclarlas antes de
comprobar su integridad.

## Ejecución

Procesar todas las fuentes:

```powershell
python src/actividad_3/a3_auditorias_nuevas_fuentes/09_normalizacion_nuevas_fuentes.py
```

Procesar solo una fuente:

```powershell
python src/actividad_3/a3_auditorias_nuevas_fuentes/09_normalizacion_nuevas_fuentes.py --source sinac_src10_2021
python src/actividad_3/a3_auditorias_nuevas_fuentes/09_normalizacion_nuevas_fuentes.py --source mapa_forestal_panama_src15_2021
```

Listar las fuentes configuradas:

```powershell
python src/actividad_3/a3_auditorias_nuevas_fuentes/09_normalizacion_nuevas_fuentes.py --list-sources
```

## Reglas aplicadas

- Los IDs A1 entregados en `id_nivel_0`, `id_nivel_1` e `id_nivel_2` se usan
  directamente para construir `xy_point.id_0`, `id_1` e `id_2`.
- Los IDs se contrastan con los labels `nivel_0`, `nivel_1` y `nivel_2` y con
  los campos dominantes.
- Los scores finales se preservan como fueron entregados; no se recalculan.
- Las reglas y catálogos de homologación propuesta son los mismos de A2.1.
- La clase original disponible y la clase A1 entregada se conservan en
  `xy_trazabilidad_fuente`.
- No se inventan ni reconstruyen indicadores de trazabilidad que no estén en
  los GeoPackage finales.

## Salidas

Raíz:

`data/processed/3_auditorias_nuevas_fuentes/normalizacion/`

Cada fuente contiene:

- `gpkg/<source_key>_normalizado.gpkg`
- `tables/*.csv` y sus archivos `.csvt`
- `metadata/*.csv`
- `README.md`

Se generan las mismas tablas temáticas y de homologación de A2.1, además de
`xy_trazabilidad_fuente` como extensión específica de A3. La tabla
`normalization_source` documenta el archivo recibido, la política aplicada y
las limitaciones de procedencia.

## Validaciones principales

- unicidad y no nulidad de `xy_group_id`;
- identidad esperada de fuente y país;
- correspondencia entre IDs A1 y labels;
- cobertura completa de las homologaciones propuestas;
- coherencia entre clase dominante y valores observados;
- integridad de las tablas y relaciones escritas en el GeoPackage.
