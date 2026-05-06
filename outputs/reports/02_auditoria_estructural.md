# Auditoría estructural y tabular

## Módulo 2

Fecha de ejecución: 2026-05-04 18:04:39

## Archivo inspeccionado

```text
/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/raw/GeoPackage_puntos_control_mesoamerica.gpkg
```

## Capa auditada

```text
Puntos_control_mesoamerica
```

## Resumen general

| Elemento | Valor |
|---|---:|
| Total de registros | 2881123 |
| Total de campos en SQLite | 43 |
| Campos críticos ausentes | 0 |
| Grupos de duplicados por hash de atributos | 7091 |
| Registros en grupos duplicados por hash | 14183 |

## Campos críticos ausentes

No se detectaron campos críticos ausentes.

## Esquema SQLite

|   ordinal | field_name     | sqlite_type   |   not_null | default_value   |   primary_key | is_geometry_column   |
|----------:|:---------------|:--------------|-----------:|:----------------|--------------:|:---------------------|
|         0 | OBJECTID       | INTEGER       |          1 |                 |             1 | False                |
|         1 | Shape          | POINT         |          0 |                 |             0 | True                 |
|         2 | Id             | MEDIUMINT     |          0 |                 |             0 | False                |
|         3 | Id_Origen      | MEDIUMINT     |          0 |                 |             0 | False                |
|         4 | Longitud       | DOUBLE        |          0 |                 |             0 | False                |
|         5 | Latitud        | DOUBLE        |          0 |                 |             0 | False                |
|         6 | id_fuente      | MEDIUMINT     |          0 |                 |             0 | False                |
|         7 | Fuente         | TEXT(8000)    |          0 |                 |             0 | False                |
|         8 | Tipo           | TEXT(8000)    |          0 |                 |             0 | False                |
|         9 | Detalle_Tipo   | TEXT(8000)    |          0 |                 |             0 | False                |
|        10 | Año            | MEDIUMINT     |          0 |                 |             0 | False                |
|        11 | Uso_Origen     | TEXT(8000)    |          0 |                 |             0 | False                |
|        12 | Subuso_Origen  | TEXT(8000)    |          0 |                 |             0 | False                |
|        13 | Clave          | TEXT(8000)    |          0 |                 |             0 | False                |
|        14 | id_0           | MEDIUMINT     |          0 |                 |             0 | False                |
|        15 | Nivel_0        | TEXT(8000)    |          0 |                 |             0 | False                |
|        16 | id_cob_niv1    | MEDIUMINT     |          0 |                 |             0 | False                |
|        17 | Nivel_1        | TEXT(8000)    |          0 |                 |             0 | False                |
|        18 | id_cob_niv2    | MEDIUMINT     |          0 |                 |             0 | False                |
|        19 | Nivel_2        | TEXT(8000)    |          0 |                 |             0 | False                |
|        20 | IDRegMunic     | TEXT(8000)    |          0 |                 |             0 | False                |
|        21 | Pais_cod3      | TEXT(8000)    |          0 |                 |             0 | False                |
|        22 | Pais_es        | TEXT(8000)    |          0 |                 |             0 | False                |
|        23 | Admin1_id      | MEDIUMINT     |          0 |                 |             0 | False                |
|        24 | Admin1name     | TEXT(8000)    |          0 |                 |             0 | False                |
|        25 | Adm1tipo       | TEXT(8000)    |          0 |                 |             0 | False                |
|        26 | Admin2_id      | MEDIUMINT     |          0 |                 |             0 | False                |
|        27 | Admin2name     | TEXT(8000)    |          0 |                 |             0 | False                |
|        28 | Adm2tipo       | TEXT(8000)    |          0 |                 |             0 | False                |
|        29 | CodigoNiv1     | MEDIUMINT     |          0 |                 |             0 | False                |
|        30 | CodigoNiv2     | MEDIUMINT     |          0 |                 |             0 | False                |
|        31 | GBM_Nivel1     | TEXT(8000)    |          0 |                 |             0 | False                |
|        32 | GBM_Nivel2     | TEXT(8000)    |          0 |                 |             0 | False                |
|        33 | Cobertura      | MEDIUMINT     |          0 |                 |             0 | False                |
|        34 | Altura         | MEDIUMINT     |          0 |                 |             0 | False                |
|        35 | NDVI           | DOUBLE        |          0 |                 |             0 | False                |
|        36 | Deforesta      | MEDIUMINT     |          0 |                 |             0 | False                |
|        37 | conf_ndvi      | DOUBLE        |          0 |                 |             0 | False                |
|        38 | conf_cobertura | DOUBLE        |          0 |                 |             0 | False                |
|        39 | conf_altura    | DOUBLE        |          0 |                 |             0 | False                |
|        40 | conf_integrada | DOUBLE        |          0 |                 |             0 | False                |
|        41 | Forest20       | MEDIUMINT     |          0 |                 |             0 | False                |
|        42 | WorldCov21     | MEDIUMINT     |          0 |                 |             0 | False                |

## Estado de campos críticos

| campo   | presente   | estado   |
|:--------|:-----------|:---------|
| Id      | True       | presente |
| Fuente  | True       | presente |
| Tipo    | True       | presente |
| Año     | True       | presente |
| Pais_es | True       | presente |
| Nivel_0 | True       | presente |
| Nivel_1 | True       | presente |
| Nivel_2 | True       | presente |

## Campos con mayor porcentaje de nulos

| field_name    |   n_total |   n_nulos |   pct_nulos |   n_vacios_texto |   pct_vacios_texto |
|:--------------|----------:|----------:|------------:|-----------------:|-------------------:|
| GBM_Nivel1    |   2881123 |   2131439 |     73.9795 |                0 |                  0 |
| GBM_Nivel2    |   2881123 |   2131439 |     73.9795 |                0 |                  0 |
| Id_Origen     |   2881123 |   1750203 |     60.7473 |                0 |                  0 |
| OBJECTID      |   2881123 |         0 |      0      |                0 |                  0 |
| Id            |   2881123 |         0 |      0      |                0 |                  0 |
| Longitud      |   2881123 |         0 |      0      |                0 |                  0 |
| Latitud       |   2881123 |         0 |      0      |                0 |                  0 |
| id_fuente     |   2881123 |         0 |      0      |                0 |                  0 |
| Fuente        |   2881123 |         0 |      0      |                0 |                  0 |
| Tipo          |   2881123 |         0 |      0      |                0 |                  0 |
| Detalle_Tipo  |   2881123 |         0 |      0      |                0 |                  0 |
| Año           |   2881123 |         0 |      0      |                0 |                  0 |
| Uso_Origen    |   2881123 |         0 |      0      |                0 |                  0 |
| Subuso_Origen |   2881123 |         0 |      0      |                0 |                  0 |
| Clave         |   2881123 |         0 |      0      |                0 |                  0 |

## Campos con mayor número de valores únicos

| field_name     |   n_total |   n_unicos_no_nulos |   pct_unicos_sobre_total |
|:---------------|----------:|--------------------:|-------------------------:|
| OBJECTID       |   2881123 |             2881123 |                 100      |
| Id             |   2881123 |             2879481 |                  99.943  |
| conf_integrada |   2881123 |             1405623 |                  48.7873 |
| conf_ndvi      |   2881123 |             1089935 |                  37.8302 |
| NDVI           |   2881123 |              583395 |                  20.2489 |
| Longitud       |   2881123 |              291022 |                  10.101  |
| Latitud        |   2881123 |              284952 |                   9.8903 |
| Id_Origen      |   2881123 |              219814 |                   7.6295 |
| IDRegMunic     |   2881123 |                1417 |                   0.0492 |
| Admin2name     |   2881123 |                1323 |                   0.0459 |
| conf_cobertura |   2881123 |                1092 |                   0.0379 |
| CodigoNiv2     |   2881123 |                 790 |                   0.0274 |
| Clave          |   2881123 |                 717 |                   0.0249 |
| Subuso_Origen  |   2881123 |                 388 |                   0.0135 |
| conf_altura    |   2881123 |                 372 |                   0.0129 |

## Resumen de duplicados en identificadores

| field_name   | presente   |   grupos_duplicados |   registros_en_grupos_duplicados |   exceso_registros_duplicados |
|:-------------|:-----------|--------------------:|---------------------------------:|------------------------------:|
| Id           | True       |                1588 |                             3230 |                          1642 |
| Id_Origen    | True       |              124988 |                          1036094 |                        911106 |

## Nota metodológica

Esta auditoría estructural no modifica el GeoPackage original.
Los resultados deben interpretarse como diagnóstico inicial para orientar decisiones posteriores.
Los duplicados por hash no constituyen eliminación automática; solo indican registros que requieren revisión.
