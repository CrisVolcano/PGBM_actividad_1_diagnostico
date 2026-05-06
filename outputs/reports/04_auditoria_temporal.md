# Auditoría temporal

## Módulo 4

Fecha de ejecución: 2026-05-06 15:01:04

## Archivo inspeccionado

```text
/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/raw/GeoPackage_puntos_control_mesoamerica.gpkg
```

## Capa auditada

```text
Puntos_control_mesoamerica
```

## Parámetros temporales

| Parámetro | Valor |
|---|---:|
| Año objetivo | 2020 |
| Ventana cercana al año objetivo | ±2 años |
| Total de registros | 2881123 |

## Calidad general del campo Año

|     n_total |   n_anio_null |   n_anio_vacio |   n_anio_fuera_rango_plausible |   anio_min_observado |   anio_max_observado |   n_anios_distintos |   pct_anio_null |   pct_anio_vacio |   pct_anio_fuera_rango_plausible |   min_plausible_year |   max_plausible_year |
|------------:|--------------:|---------------:|-------------------------------:|---------------------:|---------------------:|--------------------:|----------------:|-----------------:|---------------------------------:|---------------------:|---------------------:|
| 2.88112e+06 |             0 |              0 |                              0 |                 2000 |                 2022 |                  23 |               0 |                0 |                                0 |                 1980 |                 2026 |

## Resumen interpretativo

- Años nulos: 0.
- Años vacíos: 0.
- Años fuera de rango plausible: 0.
- Año mínimo observado: 2000.0.
- Año máximo observado: 2022.0.
- Número de años distintos: 23.

## Distribución anual

|   anio |      n |       pct |
|-------:|-------:|----------:|
|   2000 | 535974 | 18.603    |
|   2001 |  87565 |  3.03927  |
|   2002 |  21780 |  0.755955 |
|   2003 |  21842 |  0.758107 |
|   2004 |  21762 |  0.75533  |
|   2005 | 146014 |  5.06795  |
|   2006 |  51649 |  1.79267  |
|   2007 |  40586 |  1.40869  |
|   2008 |  40266 |  1.39758  |
|   2009 |  40266 |  1.39758  |
|   2010 |  40266 |  1.39758  |
|   2011 |  40266 |  1.39758  |
|   2012 | 227254 |  7.88769  |
|   2013 |  40266 |  1.39758  |
|   2014 |  40616 |  1.40973  |
|   2015 |  44354 |  1.53947  |
|   2016 | 139840 |  4.85366  |
|   2017 | 104646 |  3.63212  |
|   2018 | 761746 | 26.4392   |
|   2019 |  42637 |  1.47987  |
|   2020 | 225478 |  7.82605  |
|   2021 | 147522 |  5.12029  |
|   2022 |  18528 |  0.643083 |

## Relevancia temporal respecto al año objetivo

| relevancia_temporal         |       n |      pct |   target_year |   near_window_years |
|:----------------------------|--------:|---------:|--------------:|--------------------:|
| anterior_a_ventana_objetivo | 1685212 | 58.4915  |          2020 |                   2 |
| cercano_anio_objetivo       |  970433 | 33.6825  |          2020 |                   2 |
| anio_objetivo               |  225478 |  7.82605 |          2020 |                   2 |

## Cobertura temporal por fuente

| group_field   | grupo                                                                |   n_registros |   anio_min |   anio_max |   n_anios_distintos |
|:--------------|:---------------------------------------------------------------------|--------------:|-----------:|-----------:|--------------------:|
| Fuente        | FCPF - Malla MRV-REDD+ El Salvador                                   |       1028472 |       2000 |       2018 |                   2 |
| Fuente        | FCPF - Malla MRV-REDD+ Belize                                        |        413022 |       2000 |       2018 |                  19 |
| Fuente        | FCPF - Malla MRV-REDD+ Honduras                                      |        333504 |       2005 |       2022 |                  18 |
| Fuente        | CCAD/GIZ-REDD+Landscape - Malla Piloto Costa Rica                    |        316785 |       2005 |       2018 |                   5 |
| Fuente        | MAGA - Cultivos - Mapa Guatemala                                     |        206950 |       2020 |       2020 |                   1 |
| Fuente        | CCAD/GIZ-REDD+Landscape - Malla Piloto El Salvador                   |        197376 |       2001 |       2018 |                   3 |
| Fuente        | ICF - Cultivos - Mapa Honduras                                       |        106416 |       2018 |       2018 |                   1 |
| Fuente        | SINAC - Malla de Entrenamientos del Mapa de Bosques 2021, Costa Rica |         99803 |       2021 |       2021 |                   1 |
| Fuente        | ICAFE - Poligono de zonasdel cultivo de café de Costa Rica           |         31176 |       2012 |       2018 |                   2 |
| Fuente        | MIAMBIENTE - Cultivos Mapa Panamá                                    |         24475 |       2021 |       2021 |                   1 |
| Fuente        | FCPF - Malla MRV-REDD+ Guatemala                                     |         22766 |       2006 |       2016 |                   2 |
| Fuente        | CENAT/PRIAS - Cultivos - Costa Rica                                  |         22224 |       2019 |       2019 |                   1 |
| Fuente        | Muestras de Entrenamiento de Jimenez, 2020 - Honduras                |         12500 |       2017 |       2017 |                   1 |
| Fuente        | FOREST DEPARTMENT - Cultivos - Mapa Belize                           |         11585 |       2018 |       2018 |                   1 |
| Fuente        | Muestras de Entrenamiento de Jimenez, 2020 - Panamá                  |         10433 |       2017 |       2017 |                   1 |
| Fuente        | Muestras de Entrenamiento de Jimenez, 2020 - Costa Rica              |          7856 |       2017 |       2017 |                   1 |
| Fuente        | Muestras de Entrenamiento de Jimenez, 2020 - Guatemala               |          6786 |       2017 |       2017 |                   1 |
| Fuente        | Muestras de Entrenamiento de Jimenez, 2020 - El Salvador             |          6221 |       2017 |       2017 |                   1 |
| Fuente        | MIAMBIENTE - Mapa de bosques y otras tierras boscosas de Panamá      |          4716 |       2021 |       2021 |                   1 |
| Fuente        | CONAFOR -Inventario Forestal Estado Quintana Roo, México             |          3150 |       2015 |       2019 |                   5 |
| Fuente        | CONAFOR -Inventario Forestal Estado Campeche, México                 |          2693 |       2015 |       2019 |                   5 |
| Fuente        | Muestras de Entrenamiento de Jimenez, 2020 - Belice                  |          2408 |       2017 |       2017 |                   1 |
| Fuente        | CCAD/GIZ-REDD+Landscape - Malla Piloto Guatemala                     |          2267 |       2018 |       2019 |                   2 |
| Fuente        | CONAFOR -Inventario Forestal Estado Yucatán, México                  |          1974 |       2015 |       2019 |                   5 |
| Fuente        | CONAFOR -Inventario Forestal Estado Chiapas, , México                |          1818 |       2015 |       2019 |                   5 |
| Fuente        | Muestras de Entrenamiento de Jimenez, 2020 - Nicaragua               |          1490 |       2017 |       2017 |                   1 |
| Fuente        | CONAFOR -Inventario Forestal Estado Tabasco, México                  |           334 |       2015 |       2019 |                   4 |
| Fuente        | FAO - Evaluación Nacional Forestal  Nicaragua                        |           320 |       2007 |       2007 |                   1 |
| Fuente        | MARN-MAG/FCPF - Inventario Forestal El Salvador                      |           318 |       2018 |       2018 |                   1 |
| Fuente        | SINAC-CCAD/GIZ - Inventario Forestal Costa Rica                      |           276 |       2014 |       2014 |                   1 |
| Fuente        | CCAD/GIZ-REDD+Landscape - Datos de Campo Piloto Guatemala            |           250 |       2019 |       2019 |                   1 |
| Fuente        | FAO - Evaluación Nacional Forestal Honduras                          |           153 |       2005 |       2005 |                   1 |
| Fuente        | CCAD/GIZ-REDD+Landscape - Datos de Campo Piloto El Salvador          |           112 |       2019 |       2019 |                   1 |
| Fuente        | FAO - Evaluación Nacional Forestal Guatemala                         |           100 |       2002 |       2003 |                   2 |
| Fuente        | ACP-CCAD/GIZ - Inventario Forestal Complemento Piloto Panamá         |            73 |       2016 |       2016 |                   1 |
| Fuente        | MAG - Inventario Forestal Preliminar Piloto El Salvador              |            70 |       2003 |       2004 |                   2 |
| Fuente        | INAB-CCAD/GIZ- Inventario Bosque Municipal Olintepeque               |            54 |       2014 |       2015 |                   2 |
| Fuente        | ACP-CCAD/GIZ - Inventario de Bosque Natural Piloto Panamá            |            49 |       2015 |       2015 |                   1 |
| Fuente        | ACP-CCAD/GIZ - Inventario Forestal Piloto Panamá                     |            37 |       2014 |       2014 |                   1 |
| Fuente        | MIAMBIENTE/ONUREDD - Inventario Forestal Panamá                      |            36 |       2015 |       2015 |                   1 |

## Cobertura temporal por país

| group_field   | grupo       |   n_registros |   anio_min |   anio_max |   n_anios_distintos |
|:--------------|:------------|--------------:|-----------:|-----------:|--------------------:|
| Pais_es       | El Salvador |       1215773 |       2000 |       2022 |                  22 |
| Pais_es       | Costa Rica  |        478141 |       2001 |       2021 |                   9 |
| Pais_es       | Honduras    |        468040 |       2000 |       2022 |                  19 |
| Pais_es       | Belice      |        426926 |       2000 |       2020 |                  20 |
| Pais_es       | Guatemala   |        240339 |       2000 |       2020 |                  21 |
| Pais_es       | Panamá      |         39847 |       2014 |       2021 |                   7 |
| Pais_es       | México      |         10085 |       2000 |       2020 |                  21 |
| Pais_es       | Nicaragua   |          1972 |       2005 |       2022 |                  18 |

## Temporalidad en grupos XY

| categoria_n_anios   |   n_grupos |   n_registros |   exceso_registros |   promedio_n_anios |
|:--------------------|-----------:|--------------:|-------------------:|-------------------:|
| dos_a_tres_anios    |     709225 |       1591081 |             881856 |            2.24151 |
| un_solo_anio        |     534156 |        543516 |               9360 |            1       |
| mas_de_diez_anios   |      40255 |        746526 |             706271 |           18.5398  |

## Relación de rangos temporales de grupos XY con el año objetivo

| tipo_grupo_xy                        | relacion_rango_con_anio_objetivo   |   n_grupos |   n_registros |   promedio_n_anios |   anio_min_global |   anio_max_global |
|:-------------------------------------|:-----------------------------------|-----------:|--------------:|-------------------:|------------------:|------------------:|
| coincidencia_fuentes_misma_clase     | rango_anterior_anio_objetivo       |          1 |             2 |            1       |              2019 |              2019 |
| conflicto_tematico_xy                | rango_anterior_anio_objetivo       |     216849 |        580350 |            2.6748  |              2000 |              2018 |
| conflicto_tematico_xy                | rango_incluye_anio_objetivo        |       2333 |         41994 |           18       |              2005 |              2022 |
| conflicto_tematico_xy                | rango_posterior_anio_objetivo      |       2160 |          4320 |            1       |              2021 |              2021 |
| multitemporal_xy                     | rango_anterior_anio_objetivo       |     514109 |       1423757 |            2.76711 |              2000 |              2018 |
| multitemporal_xy                     | rango_incluye_anio_objetivo        |      16191 |        291510 |           18       |              2005 |              2022 |
| redundancia_misma_fuente_misma_clase | rango_posterior_anio_objetivo      |       7020 |         14040 |            1       |              2021 |              2021 |
| redundancia_misma_fuente_misma_clase | rango_incluye_anio_objetivo        |         72 |           186 |            1       |              2020 |              2020 |
| redundancia_misma_fuente_misma_clase | rango_anterior_anio_objetivo       |         62 |           125 |            1       |              2002 |              2019 |
| xy_unico                             | rango_anterior_anio_objetivo       |     207441 |        207441 |            1       |              2001 |              2019 |
| xy_unico                             | rango_incluye_anio_objetivo        |     206764 |        206764 |            1       |              2020 |              2020 |
| xy_unico                             | rango_posterior_anio_objetivo      |     110634 |        110634 |            1       |              2021 |              2021 |

## Nota metodológica

Esta auditoría temporal no modifica el GeoPackage original.
La clasificación temporal sirve para evaluar la aptitud de los registros respecto al año objetivo 2020.
Los registros fuera de la ventana temporal no deben descartarse automáticamente; deben evaluarse según fuente, clase, confiabilidad y objetivo de uso.

La tabla de relación temporal de grupos XY usa anio_min y anio_max. Por tanto, cuando indica que el rango incluye el año objetivo, no significa necesariamente que exista un registro exacto de 2020 dentro del grupo; significa que el intervalo temporal del grupo cubre 2020.
