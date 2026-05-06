# Auditoría espacial inicial

## Módulo 3

Fecha de ejecución: 2026-05-04 18:14:01

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
| Registros fuera de rango global | 0 |
| Registros fuera de rango regional amplio | 0 |
| Grupos duplicados XY exactos | 758797 |
| Registros en grupos duplicados XY exactos | 2356284 |
| Grupos duplicados XY redondeados | 719495 |
| Registros en grupos duplicados XY redondeados | 2356787 |

## Referencia espacial declarada

| table_name                 | column_name   | geometry_type_name   |   srs_id | srs_name     | organization   |   organization_coordsys_id | definition                                                                                                                                        | warning   |
|:---------------------------|:--------------|:---------------------|---------:|:-------------|:---------------|---------------------------:|:--------------------------------------------------------------------------------------------------------------------------------------------------|:----------|
| Puntos_control_mesoamerica | Shape         | POINT                |     4326 | GCS_WGS_1984 | EPSG           |                       4326 | GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]] |           |

## Verificación de campos de coordenadas

| rol      | field_name   | presente   | sqlite_type   |
|:---------|:-------------|:-----------|:--------------|
| longitud | Longitud     | True       | DOUBLE        |
| latitud  | Latitud      | True       | DOUBLE        |

## Bounding box global

|     n_total |   lon_min |   lon_max |   lat_min |   lat_max |   lon_mean |   lat_mean |
|------------:|----------:|----------:|----------:|----------:|-----------:|-----------:|
| 2.88112e+06 |  -94.1033 |  -77.1859 |   7.20538 |   21.6108 |   -87.8665 |     13.816 |

## Calidad general de coordenadas

|   n_total |   n_lon_null |   n_lat_null |   n_lon_vacia |   n_lat_vacia |   n_fuera_rango_global |   n_fuera_rango_regional_amplio |   pct_lonull |   pct_lat_null |   pct_lovacia |   pct_lat_vacia |   pct_fuera_rango_global |   pct_fuera_rango_regional_amplio | regional_bounds                                                |
|----------:|-------------:|-------------:|--------------:|--------------:|-----------------------:|--------------------------------:|-------------:|---------------:|--------------:|----------------:|-------------------------:|----------------------------------:|:---------------------------------------------------------------|
|   2881123 |            0 |            0 |             0 |             0 |                      0 |                               0 |            0 |              0 |             0 |               0 |                        0 |                                 0 | {'lon_min': -120, 'lon_max': -75, 'lat_min': 5, 'lat_max': 25} |

## Duplicados por coordenadas exactas

| tipo_duplicado   |   grupos_duplicados |   registros_en_grupos_duplicados |   exceso_registros_duplicados |   max_registros_misma_coordenada |
|:-----------------|--------------------:|---------------------------------:|------------------------------:|---------------------------------:|
| exacto           |              758797 |                          2356284 |                       1597487 |                               38 |

## Duplicados por coordenadas redondeadas

| tipo_duplicado         |   grupos_duplicados |   registros_en_grupos_duplicados |   exceso_registros_duplicados |   max_registros_misma_coordenada |
|:-----------------------|--------------------:|---------------------------------:|------------------------------:|---------------------------------:|
| redondeado_6_decimales |              719495 |                          2356787 |                       1637292 |                               38 |

## Distribución por país

| field_name   | valor       |       n |       pct |
|:-------------|:------------|--------:|----------:|
| Pais_es      | El Salvador | 1215773 | 42.1979   |
| Pais_es      | Costa Rica  |  478141 | 16.5956   |
| Pais_es      | Honduras    |  468040 | 16.2451   |
| Pais_es      | Belice      |  426926 | 14.818    |
| Pais_es      | Guatemala   |  240339 |  8.34185  |
| Pais_es      | Panamá      |   39847 |  1.38304  |
| Pais_es      | México      |   10085 |  0.350037 |
| Pais_es      | Nicaragua   |    1972 |  0.068446 |

## Bounding box por país

| pais        |       n |   lon_min |   lon_max |   lat_min |   lat_max |
|:------------|--------:|----------:|----------:|----------:|----------:|
| El Salvador | 1215773 |  -90.1181 |  -87.685  |  13.1571  |  14.4422  |
| Costa Rica  |  478141 |  -85.9176 |  -82.5539 |   8.04353 |  11.2095  |
| Honduras    |  468040 |  -89.3527 |  -83.1728 |  12.9891  |  16.5009  |
| Belice      |  426926 |  -89.2256 |  -87.4944 |  15.8943  |  18.4884  |
| Guatemala   |  240339 |  -92.2171 |  -88.2531 |  13.7406  |  17.8188  |
| Panamá      |   39847 |  -83.0183 |  -77.1859 |   7.20538 |   9.61665 |
| México      |   10085 |  -94.1033 |  -86.8341 |  14.5755  |  21.6108  |
| Nicaragua   |    1972 |  -87.6796 |  -83.0506 |  10.7136  |  14.9914  |

## Nota metodológica

Esta auditoría espacial no modifica el GeoPackage original.
Los duplicados espaciales no deben eliminarse automáticamente.
Primero deben cruzarse con fuente, clase, año, confiabilidad y duplicados atributivos.

El rango regional amplio se usa solo como alerta exploratoria, no como criterio definitivo de descarte.
