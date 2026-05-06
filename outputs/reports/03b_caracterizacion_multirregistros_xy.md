# Caracterización de multirregistros espaciales XY

## Módulo 3B - Versión optimizada

Fecha de ejecución: 2026-05-06 08:27:36

## Modo de ejecución

`reutilización de grupos_xy existente`

## Fuente intermedia

```text
/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/interim/03b_multirregistros_xy.sqlite
```

## Resumen ejecutivo

| Concepto | Valor |
|---|---:|
| Total de registros originales | 2881123 |
| Total de grupos XY únicos | 1283636 |
| Grupos XY únicos sin repetición | 524839 |
| Grupos XY repetidos | 758797 |
| Registros en grupos repetidos | 2356284 |
| Exceso de registros repetidos | 1597487 |
| Registros únicos XY finales | 1283636 |
| Reducción si se conserva uno por XY (%) | 55.4467 |
| Máximo de registros en una misma coordenada | 38 |

## Distribución por tipo de grupo XY

| tipo_grupo_xy                        |   n_grupos |   n_registros |   exceso_registros |   pct_grupos |   pct_registros |
|:-------------------------------------|-----------:|--------------:|-------------------:|-------------:|----------------:|
| multitemporal_xy                     |     530300 |       1715267 |            1184967 |    41.3123   |       59.5347   |
| conflicto_tematico_xy                |     221342 |        626664 |             405322 |    17.2434   |       21.7507   |
| xy_unico                             |     524839 |        524839 |                  0 |    40.8869   |       18.2165   |
| redundancia_misma_fuente_misma_clase |       7154 |         14351 |               7197 |     0.557323 |        0.498104 |
| coincidencia_fuentes_misma_clase     |          1 |             2 |                  1 |     7.8e-05  |        6.9e-05  |

## Distribución por tamaño de grupo XY

| rango_tamano_grupo   |   n_grupos |   n_registros |   exceso_registros |
|:---------------------|-----------:|--------------:|-------------------:|
| 1                    |     524839 |        524839 |                  0 |
| 2                    |     546724 |       1093448 |             546724 |
| 3                    |     171182 |        513546 |             342364 |
| 4                    |        529 |          2116 |               1587 |
| 6-10                 |        107 |           648 |                541 |
| 11-20                |      40244 |        746116 |             705872 |
| >20                  |         11 |           410 |                399 |

## Tipos de grupo XY por país

| pais_grupo                | tipo_grupo_xy                        |   n_grupos |   n_registros |   exceso_registros |
|:--------------------------|:-------------------------------------|-----------:|--------------:|-------------------:|
| Belice                    | multitemporal_xy                     |      19540 |        371336 |             351796 |
| Belice                    | conflicto_tematico_xy                |       2186 |         41553 |              39367 |
| Belice                    | xy_unico                             |      13993 |         13993 |                  0 |
| Costa Rica                | conflicto_tematico_xy                |      80915 |        240583 |             159668 |
| Costa Rica                | xy_unico                             |     117343 |        117343 |                  0 |
| Costa Rica                | multitemporal_xy                     |      39679 |        106208 |              66529 |
| Costa Rica                | redundancia_misma_fuente_misma_clase |       6977 |         13954 |               6977 |
| El Salvador               | multitemporal_xy                     |     438175 |        911540 |             473365 |
| El Salvador               | conflicto_tematico_xy                |     132923 |        296233 |             163310 |
| El Salvador               | xy_unico                             |       6661 |          6661 |                  0 |
| Guatemala                 | xy_unico                             |     216221 |        216221 |                  0 |
| Guatemala                 | multitemporal_xy                     |       9708 |         19452 |               9744 |
| Guatemala                 | conflicto_tematico_xy                |       1879 |          3765 |               1886 |
| Guatemala                 | redundancia_misma_fuente_misma_clase |          1 |             2 |                  1 |
| Honduras                  | multitemporal_xy                     |      22706 |        304340 |             281634 |
| Honduras                  | xy_unico                             |     119071 |        119071 |                  0 |
| Honduras                  | conflicto_tematico_xy                |       3304 |         43936 |              40632 |
| México                    | xy_unico                             |       9919 |          9919 |                  0 |
| México                    | redundancia_misma_fuente_misma_clase |         24 |            49 |                 25 |
| México                    | multitemporal_xy                     |          6 |            29 |                 23 |
| México                    | coincidencia_fuentes_misma_clase     |          1 |             2 |                  1 |
| Nicaragua                 | xy_unico                             |       1813 |          1813 |                  0 |
| Nicaragua                 | multitemporal_xy                     |          4 |            72 |                 68 |
| Panamá                    | xy_unico                             |      39818 |         39818 |                  0 |
| multipais_o_inconsistente | multitemporal_xy                     |        482 |          2290 |               1808 |
| multipais_o_inconsistente | conflicto_tematico_xy                |        135 |           594 |                459 |
| multipais_o_inconsistente | redundancia_misma_fuente_misma_clase |        152 |           346 |                194 |

## Principales grupos con conflicto temático

| xy_group_id     |      lon |     lat |   n_registros |   n_paises |   n_fuentes |   n_anios |   n_nivel1 |   n_nivel2 |   anio_min |   anio_max | pais_grupo   |   conf_integrada_promedio |   conf_integrada_min |   conf_integrada_max | tipo_grupo_xy         |
|:----------------|---------:|--------:|--------------:|-----------:|------------:|----------:|-----------:|-----------:|-----------:|-----------:|:-------------|--------------------------:|---------------------:|---------------------:|:----------------------|
| XY_000000513739 | -89.0531 | 16.185  |            38 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   83.1175 |              62.3788 |              88.6479 | conflicto_tematico_xy |
| XY_000000455197 | -89.2192 | 15.9846 |            19 |          1 |           1 |        19 |          1 |          2 |       2000 |       2018 | Belice       |                   92.3175 |              92.3175 |              92.3175 | conflicto_tematico_xy |
| XY_000000455237 | -89.2191 | 15.9756 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   71.3912 |              69.5297 |              87.214  | conflicto_tematico_xy |
| XY_000000457779 | -89.2112 | 16.1112 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   68.0751 |              60.6806 |              78.2426 | conflicto_tematico_xy |
| XY_000000457806 | -89.2111 | 16.1021 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   65.4491 |              56.1948 |              81.3136 | conflicto_tematico_xy |
| XY_000000457834 | -89.211  | 16.0931 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   79.0537 |              55.7339 |              81.7972 | conflicto_tematico_xy |
| XY_000000457905 | -89.2108 | 16.075  |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   85.6511 |              47.318  |              92.8385 | conflicto_tematico_xy |
| XY_000000457948 | -89.2107 | 16.066  |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   69.8502 |              69.4914 |              72.8996 | conflicto_tematico_xy |
| XY_000000458253 | -89.2099 | 15.9937 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   53.61   |              51.2353 |              96.3557 | conflicto_tematico_xy |
| XY_000000458321 | -89.2097 | 15.9757 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   64.022  |              63.0083 |              72.6379 | conflicto_tematico_xy |
| XY_000000458397 | -89.2095 | 15.9576 |            19 |          1 |           1 |        19 |          1 |          2 |       2000 |       2018 | Belice       |                   86.3802 |              86.3802 |              86.3802 | conflicto_tematico_xy |
| XY_000000458423 | -89.2094 | 15.9486 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   80.6877 |              47.0507 |              86.9947 | conflicto_tematico_xy |
| XY_000000458484 | -89.2089 | 15.9034 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   83.0193 |              54.3435 |              93.2606 | conflicto_tematico_xy |
| XY_000000460850 | -89.2019 | 16.1113 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   72.6987 |              63.2376 |              75.2217 | conflicto_tematico_xy |
| XY_000000460891 | -89.2018 | 16.1022 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   69.3472 |              60.1018 |              95.2345 | conflicto_tematico_xy |
| XY_000000461178 | -89.201  | 16.03   |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   72.5178 |              70.4735 |              83.4205 | conflicto_tematico_xy |
| XY_000000461259 | -89.2008 | 16.0119 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   67.0391 |              64.5183 |              88.4654 | conflicto_tematico_xy |
| XY_000000461339 | -89.2006 | 15.9938 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   75.0318 |              60.0371 |              79.0304 | conflicto_tematico_xy |
| XY_000000461495 | -89.2001 | 15.9487 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   81.146  |              54.5243 |              93.4329 | conflicto_tematico_xy |
| XY_000000461524 | -89.1999 | 15.9306 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   79.1343 |              65.0919 |              84.1494 | conflicto_tematico_xy |
| XY_000000463049 | -89.1952 | 16.3553 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   90.0748 |              59.444  |              93.6785 | conflicto_tematico_xy |
| XY_000000463371 | -89.1942 | 16.2649 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   88.9235 |              69.6075 |              92.5453 | conflicto_tematico_xy |
| XY_000000463537 | -89.1938 | 16.2288 |            19 |          1 |           1 |        19 |          1 |          2 |       2000 |       2018 | Belice       |                   81.5368 |              81.5368 |              81.5368 | conflicto_tematico_xy |
| XY_000000463915 | -89.1927 | 16.1294 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   76.2195 |              59.778  |              79.3023 | conflicto_tematico_xy |
| XY_000000463941 | -89.1926 | 16.1204 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   51.548  |              44.2872 |              90.272  | conflicto_tematico_xy |
| XY_000000463984 | -89.1925 | 16.1114 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   79.4642 |              76.2872 |              86.3476 | conflicto_tematico_xy |
| XY_000000464047 | -89.1923 | 16.0933 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   67.3452 |              62.2476 |              94.5328 | conflicto_tematico_xy |
| XY_000000464410 | -89.1914 | 16.012  |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   77.9832 |              77.7071 |              79.0184 | conflicto_tematico_xy |
| XY_000000464514 | -89.1911 | 15.9849 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   71.1632 |              54.7858 |              93.6821 | conflicto_tematico_xy |
| XY_000000464558 | -89.191  | 15.9759 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   77.086  |              54.4783 |              83.1147 | conflicto_tematico_xy |
| XY_000000464584 | -89.1909 | 15.9668 |            19 |          1 |           1 |        19 |          1 |          2 |       2000 |       2018 | Belice       |                   87.1374 |              87.1374 |              87.1374 | conflicto_tematico_xy |
| XY_000000465879 | -89.1868 | 16.4367 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   85.4507 |              66.6679 |              96.4073 | conflicto_tematico_xy |
| XY_000000466060 | -89.1863 | 16.3915 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   72.5758 |              62.2701 |              86.7462 | conflicto_tematico_xy |
| XY_000000466318 | -89.1855 | 16.3192 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   79.9439 |              78.168  |              95.0386 | conflicto_tematico_xy |
| XY_000000466417 | -89.1852 | 16.2921 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   83.5396 |              82.4775 |              92.567  | conflicto_tematico_xy |
| XY_000000466450 | -89.1851 | 16.2831 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   75.4017 |              73.2936 |              93.3204 | conflicto_tematico_xy |
| XY_000000466533 | -89.1849 | 16.265  |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   79.7133 |              69.1809 |              87.3732 | conflicto_tematico_xy |
| XY_000000466723 | -89.1844 | 16.2199 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   81.0159 |              55.1067 |              82.4553 | conflicto_tematico_xy |
| XY_000000467061 | -89.1834 | 16.1295 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   74.8171 |              61.449  |              77.3237 | conflicto_tematico_xy |
| XY_000000467087 | -89.1833 | 16.1205 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   65.2039 |              64.7479 |              73.4118 | conflicto_tematico_xy |
| XY_000000467219 | -89.1829 | 16.0844 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   58.769  |              54.6741 |              93.5757 | conflicto_tematico_xy |
| XY_000000467478 | -89.1822 | 16.0211 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   81.2115 |              62.0879 |              86.3112 | conflicto_tematico_xy |
| XY_000000467519 | -89.1821 | 16.0121 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   72.7989 |              62.0667 |              74.8112 | conflicto_tematico_xy |
| XY_000000467653 | -89.1817 | 15.976  |            19 |          1 |           1 |        19 |          1 |          2 |       2000 |       2018 | Belice       |                   79.6729 |              79.6729 |              79.6729 | conflicto_tematico_xy |
| XY_000000467680 | -89.1816 | 15.9669 |            19 |          1 |           1 |        19 |          1 |          2 |       2000 |       2018 | Belice       |                   86.7067 |              86.7067 |              86.7067 | conflicto_tematico_xy |
| XY_000000468247 | -89.1794 | 16.6174 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   71.3873 |              52.3563 |              82.4887 | conflicto_tematico_xy |
| XY_000000468415 | -89.1789 | 16.5723 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   80.7883 |              74.2596 |              86.664  | conflicto_tematico_xy |
| XY_000000469172 | -89.1766 | 16.3645 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   91.7476 |              89.8145 |              91.855  | conflicto_tematico_xy |
| XY_000000469239 | -89.1764 | 16.3464 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   77.9173 |              75.8812 |              95.2244 | conflicto_tematico_xy |
| XY_000000469538 | -89.1755 | 16.2651 |            19 |          1 |           1 |        19 |          2 |          2 |       2000 |       2018 | Belice       |                   73.5461 |              49.8547 |              79.8639 | conflicto_tematico_xy |

## Principales grupos multitemporales

| xy_group_id     |      lon |     lat |   n_registros |   n_paises |   n_fuentes |   n_anios |   n_nivel1 |   n_nivel2 |   anio_min |   anio_max | pais_grupo                |   conf_integrada_promedio |   conf_integrada_min |   conf_integrada_max | tipo_grupo_xy    |
|:----------------|---------:|--------:|--------------:|-----------:|------------:|----------:|-----------:|-----------:|-----------:|-----------:|:--------------------------|--------------------------:|---------------------:|---------------------:|:-----------------|
| XY_000000455074 | -89.2195 | 16.0117 |            38 |          2 |           1 |        19 |          1 |          1 |       2000 |       2018 | multipais_o_inconsistente |                   96.5488 |              96.5488 |              96.5488 | multitemporal_xy |
| XY_000000460298 | -89.2035 | 16.2558 |            38 |          2 |           1 |        19 |          1 |          1 |       2000 |       2018 | multipais_o_inconsistente |                   83.6132 |              83.6132 |              83.6132 | multitemporal_xy |
| XY_000000487187 | -89.1252 | 15.9313 |            38 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   93.3828 |              93.3828 |              93.3828 | multitemporal_xy |
| XY_000000510366 | -89.0625 | 16.194  |            38 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   87.3003 |              87.3003 |              87.3003 | multitemporal_xy |
| XY_000000510441 | -89.0623 | 16.1759 |            38 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   92.2246 |              92.2246 |              92.2246 | multitemporal_xy |
| XY_000000907728 | -87.7865 | 17.4951 |            38 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   86.8033 |              86.8033 |              86.8033 | multitemporal_xy |
| XY_000000632175 | -88.7199 | 14.0474 |            36 |          2 |           1 |        18 |          1 |          1 |       2005 |       2022 | multipais_o_inconsistente |                   79.777  |              79.777  |              79.777  | multitemporal_xy |
| XY_000000943464 | -87.2376 | 12.9919 |            36 |          2 |           1 |        18 |          1 |          1 |       2005 |       2022 | multipais_o_inconsistente |                   92.7918 |              92.7918 |              92.7918 | multitemporal_xy |
| XY_000001003087 | -85.3961 | 14.1372 |            36 |          2 |           1 |        18 |          1 |          1 |       2005 |       2022 | multipais_o_inconsistente |                   94.2363 |              94.2363 |              94.2363 | multitemporal_xy |
| XY_000001223607 | -83.1728 | 14.9906 |            36 |          2 |           1 |        18 |          1 |          1 |       2005 |       2022 | multipais_o_inconsistente |                   86.78   |              86.78   |              86.78   | multitemporal_xy |
| XY_000000455119 | -89.2194 | 16.0027 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   81.3946 |              81.3946 |              81.3946 | multitemporal_xy |
| XY_000000455150 | -89.2193 | 15.9936 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   80.7177 |              80.7177 |              80.7177 | multitemporal_xy |
| XY_000000455274 | -89.219  | 15.9665 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   90.1857 |              90.1857 |              90.1857 | multitemporal_xy |
| XY_000000455315 | -89.2189 | 15.9575 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   58.0247 |              58.0247 |              58.0247 | multitemporal_xy |
| XY_000000455335 | -89.2188 | 15.9485 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   95.7652 |              95.7652 |              95.7652 | multitemporal_xy |
| XY_000000455351 | -89.2187 | 15.9394 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   94.4222 |              94.4222 |              94.4222 | multitemporal_xy |
| XY_000000455376 | -89.2186 | 15.9304 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   95.5506 |              95.5506 |              95.5506 | multitemporal_xy |
| XY_000000455394 | -89.2185 | 15.9214 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   70.7459 |              70.7459 |              70.7459 | multitemporal_xy |
| XY_000000455414 | -89.2184 | 15.9123 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   51.887  |              51.887  |              51.887  | multitemporal_xy |
| XY_000000455433 | -89.2183 | 15.9033 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   82.9317 |              82.9317 |              82.9317 | multitemporal_xy |
| XY_000000455449 | -89.2182 | 15.8943 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   90.2891 |              90.2891 |              90.2891 | multitemporal_xy |
| XY_000000457715 | -89.2114 | 16.1292 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   89.7616 |              89.7616 |              89.7616 | multitemporal_xy |
| XY_000000457743 | -89.2113 | 16.1202 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   68.8504 |              68.8504 |              68.8504 | multitemporal_xy |
| XY_000000457876 | -89.2109 | 16.0841 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   73.5117 |              73.5117 |              73.5117 | multitemporal_xy |
| XY_000000457982 | -89.2106 | 16.057  |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   57.6638 |              57.6638 |              57.6638 | multitemporal_xy |
| XY_000000458017 | -89.2105 | 16.0479 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   87.7277 |              87.7277 |              87.7277 | multitemporal_xy |
| XY_000000458059 | -89.2104 | 16.0389 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   92.2677 |              92.2677 |              92.2677 | multitemporal_xy |
| XY_000000458093 | -89.2103 | 16.0299 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   75.4341 |              75.4341 |              75.4341 | multitemporal_xy |
| XY_000000458137 | -89.2102 | 16.0208 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   95.3376 |              95.3376 |              95.3376 | multitemporal_xy |
| XY_000000458169 | -89.2101 | 16.0118 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   71.9455 |              71.9455 |              71.9455 | multitemporal_xy |
| XY_000000458203 | -89.21   | 16.0028 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   93.2889 |              93.2889 |              93.2889 | multitemporal_xy |
| XY_000000458286 | -89.2098 | 15.9847 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   86.4182 |              86.4182 |              86.4182 | multitemporal_xy |
| XY_000000458370 | -89.2096 | 15.9666 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   89.041  |              89.041  |              89.041  | multitemporal_xy |
| XY_000000458435 | -89.2093 | 15.9395 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   63.4092 |              63.4092 |              63.4092 | multitemporal_xy |
| XY_000000458448 | -89.2092 | 15.9305 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   88.2599 |              88.2599 |              88.2599 | multitemporal_xy |
| XY_000000458460 | -89.2091 | 15.9215 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   82.3859 |              82.3859 |              82.3859 | multitemporal_xy |
| XY_000000458471 | -89.209  | 15.9124 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   93.5438 |              93.5438 |              93.5438 | multitemporal_xy |
| XY_000000460341 | -89.2034 | 16.2468 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   81.9903 |              81.9903 |              81.9903 | multitemporal_xy |
| XY_000000460377 | -89.2033 | 16.2377 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   83.4277 |              83.4277 |              83.4277 | multitemporal_xy |
| XY_000000460414 | -89.2032 | 16.2287 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   81.4329 |              81.4329 |              81.4329 | multitemporal_xy |
| XY_000000460459 | -89.2031 | 16.2197 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   83.2805 |              83.2805 |              83.2805 | multitemporal_xy |
| XY_000000460492 | -89.203  | 16.2106 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   82.3641 |              82.3641 |              82.3641 | multitemporal_xy |
| XY_000000460524 | -89.2029 | 16.2016 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   82.0136 |              82.0136 |              82.0136 | multitemporal_xy |
| XY_000000460571 | -89.2028 | 16.1926 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   71.0711 |              71.0711 |              71.0711 | multitemporal_xy |
| XY_000000460602 | -89.2027 | 16.1835 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   81.7932 |              81.7932 |              81.7932 | multitemporal_xy |
| XY_000000460638 | -89.2026 | 16.1745 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   75.6982 |              75.6982 |              75.6982 | multitemporal_xy |
| XY_000000460664 | -89.2025 | 16.1655 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   95.8295 |              95.8295 |              95.8295 | multitemporal_xy |
| XY_000000460692 | -89.2024 | 16.1564 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   94.6395 |              94.6395 |              94.6395 | multitemporal_xy |
| XY_000000460733 | -89.2023 | 16.1474 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   88.2899 |              88.2899 |              88.2899 | multitemporal_xy |
| XY_000000460759 | -89.2022 | 16.1384 |            19 |          1 |           1 |        19 |          1 |          1 |       2000 |       2018 | Belice                    |                   79.5862 |              79.5862 |              79.5862 | multitemporal_xy |

## Nota metodológica

Este reporte no modifica el GeoPackage original.
La versión optimizada evita uniones pesadas contra la tabla completa original.
Los listados de conflictos y multitemporales se derivan directamente de la tabla grupos_xy.

## Regla operativa recomendada

```text
Toda partición de entrenamiento, validación y prueba debe hacerse a nivel de grupo XY, no a nivel de fila individual.
```
