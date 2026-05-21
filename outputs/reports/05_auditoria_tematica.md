# Auditoría temática y consistencia de clases

## Módulo 5

Fecha de ejecución: 2026-05-20 18:17:30

## Resumen ejecutivo

| Concepto | Valor |
|---|---:|
| Total de registros evaluados | 2881123 |
| Campos temáticos evaluados | 8 |
| Inconsistencias jerárquicas detectadas | 0 |
| Grupos XY con conflicto temático | 221342 |
| Registros en grupos con conflicto temático | 626664 |

## Calidad de campos temáticos

| campo         | descripcion     |   n_total |   n_null_o_vacio |   pct_null_o_vacio |   n_valores_distintos |
|:--------------|:----------------|----------:|-----------------:|-------------------:|----------------------:|
| uso_origen    | Uso original    |   2881123 |                0 |                  0 |                   170 |
| subuso_origen | Subuso original |   2881123 |                0 |                  0 |                   387 |
| id_nivel_0    | Código Nivel_0  |   2881123 |                0 |                  0 |                     5 |
| nivel_0       | Nivel_0         |   2881123 |                0 |                  0 |                     5 |
| id_nivel_1    | Código Nivel_1  |   2881123 |                0 |                  0 |                    12 |
| nivel_1       | Nivel_1         |   2881123 |                0 |                  0 |                    12 |
| id_nivel_2    | Código Nivel_2  |   2881123 |                0 |                  0 |                    40 |
| nivel_2       | Nivel_2         |   2881123 |                0 |                  0 |                    40 |

## Resumen de calidad temática

|   total_registros |   n_campos_tematicos_evaluados |   campos_con_null_o_vacio |   max_pct_null_o_vacio | campo_con_mayor_null_o_vacio   |
|------------------:|-------------------------------:|--------------------------:|-----------------------:|:-------------------------------|
|           2881123 |                              8 |                         0 |                      0 | uso_origen                     |

## Distribución por Nivel_0

| clase                             |       n |      pct |   pct_acumulado | balance_flag         |
|:----------------------------------|--------:|---------:|----------------:|:---------------------|
| 30 Tierras de Cultivo y Pastos    | 1541708 | 53.5107  |         53.5107 | dominante_extrema    |
| 40 Tierras Forestales             | 1118313 | 38.8152  |         92.3258 | dominante_extrema    |
| 10 Artificializado y otra tierras |   99621 |  3.45771 |         95.7836 | representacion_media |
| 90 Otras                          |   73010 |  2.53408 |         98.3176 | representacion_media |
| 20 Tierras húmedas y agua         |   48471 |  1.68237 |        100      | representacion_media |

## Distribución por Nivel_1

| clase                                           |      n |       pct |   pct_acumulado | balance_flag         |
|:------------------------------------------------|-------:|----------:|----------------:|:---------------------|
| 41 Bosque latifoliado y mixto                   | 867264 | 30.1016   |         30.1016 | dominante_extrema    |
| 33 Cultivos extensivos, Pastizales y matorrales | 634175 | 22.0114   |         52.113  | dominante_extrema    |
| 31 Cultivos intensivos No-Arbóreos              | 500263 | 17.3635   |         69.4765 | dominante            |
| 32 Cultivos Arbóreos                            | 407270 | 14.1358   |         83.6123 | dominante            |
| 42 Bosque de coníferas                          | 110221 |  3.82563  |         87.4379 | representacion_media |
| 44 Otros arbóreo en tierras no agrícola         | 101282 |  3.51537  |         90.9532 | representacion_media |
| 11 Urbano                                       |  86470 |  3.00126  |         93.9545 | representacion_media |
| 91 Otras                                        |  73010 |  2.53408  |         96.4886 | representacion_media |
| 43 Manglares                                    |  39546 |  1.37259  |         97.8612 | representacion_media |
| 22 Humedales                                    |  34882 |  1.21071  |         99.0719 | representacion_media |
| 21 Cuerpos de Agua                              |  13589 |  0.471656 |         99.5435 | representacion_media |
| 12 Otras tierras                                |  13151 |  0.456454 |        100      | representacion_media |

## Distribución por Nivel_2

| clase                                                |      n |       pct |   pct_acumulado | balance_flag         |
|:-----------------------------------------------------|-------:|----------:|----------------:|:---------------------|
| 410 Bosque latifoliado y mixto                       | 511603 | 17.7571   |         17.7571 | dominante            |
| 332 Pastizales naturales y cultivados                | 346197 | 12.016    |         29.7731 | dominante            |
| 321 Café                                             | 317678 | 11.0262   |         40.7993 | dominante            |
| 315 Otros cultivos intensivos no arbóreos            | 246132 |  8.54292  |         49.3422 | representacion_media |
| 411 Latifoliado maduro húmedo                        | 240046 |  8.33168  |         57.6739 | representacion_media |
| 333 Matorrales (barbecho o en descanso)              | 197248 |  6.84622  |         64.5201 | representacion_media |
| 313 Caña de azúcar                                   | 135835 |  4.71465  |         69.2348 | representacion_media |
| 331 Granos básicos y hortalizas  y otros             |  90730 |  3.14912  |         72.3839 | representacion_media |
| 311 Palma aceitera                                   |  87428 |  3.03451  |         75.4184 | representacion_media |
| 443  Árboles fuera de bosque y otras áreas naturales |  83868 |  2.91095  |         78.3294 | representacion_media |
| 420 Bosque de coníferas                              |  78256 |  2.71616  |         81.0455 | representacion_media |
| 910 Otras                                            |  73010 |  2.53408  |         83.5796 | representacion_media |
| 412 Latifoliado secundario húmedo                    |  67901 |  2.35676  |         85.9364 | representacion_media |
| 325 Otros sistemas agroforestales o silvopastoriles  |  52389 |  1.81835  |         87.7547 | representacion_media |
| 430 Manglares                                        |  39344 |  1.36558  |         89.1203 | representacion_media |
| 220 Humedales                                        |  34882 |  1.21071  |         90.331  | representacion_media |
| 112 Urbano discontinuo                               |  33607 |  1.16646  |         91.4974 | representacion_media |
| 414 Bosque seco o deciduo                            |  30636 |  1.06333  |         92.5608 | representacion_media |
| 110 Urbano                                           |  29798 |  1.03425  |         93.595  | representacion_media |
| 423 Sabanas de pino                                  |  28933 |  1.00423  |         94.5993 | representacion_media |
| 111 Urbano continuo                                  |  23065 |  0.800556 |         95.3998 | representacion_media |
| 324 Hule                                             |  22718 |  0.788512 |         96.1883 | representacion_media |
| 312 Bananeras                                        |  17402 |  0.604001 |         96.7923 | representacion_media |
| 413 Bosque Mixto (Lat-Coniferas)                     |  17078 |  0.592755 |         97.3851 | representacion_media |
| 323 Frutales                                         |  13865 |  0.481236 |         97.8663 | representacion_media |
| 314 Piña                                             |  13466 |  0.467387 |         98.3337 | representacion_media |
| 210 Cuerpos de Agua                                  |  12291 |  0.426604 |         98.7603 | representacion_media |
| 444 Regeneración forestal                            |   9673 |  0.335737 |         99.096  | representacion_media |
| 122 Suelo desnudo, arena, rocoso, lava, otros        |   6987 |  0.24251  |         99.3386 | representacion_media |
| 442 Plantaciones forestales                          |   6776 |  0.235186 |         99.5737 | representacion_media |
| 121 Otros artificializado                            |   6164 |  0.213944 |         99.7877 | representacion_media |
| 421 Coníferas denso                                  |   2593 |  0.09     |         99.8777 | representacion_media |
| 441 Masa arbórea ribereña                            |    917 |  0.031828 |         99.9095 | representacion_media |
| 212 Cuerpos de agua artificial                       |    892 |  0.03096  |         99.9405 | representacion_media |
| 322 Cacao                                            |    620 |  0.021519 |         99.962  | representacion_media |
| 422 Coníferas ralo                                   |    439 |  0.015237 |         99.9772 | representacion_media |
| 211 Cuerpos de agua natural                          |    406 |  0.014092 |         99.9913 | representacion_media |
| 431 Manglar alto                                     |    194 |  0.006733 |         99.9981 | representacion_media |
| 445 Bosque de Palmas                                 |     48 |  0.001666 |         99.9997 | baja                 |
| 432 Manglar bajo                                     |      8 |  0.000278 |        100      | critica_muy_baja     |

## Inconsistencias jerárquicas

| relacion   | clase_hija   | n_registros   | n_padres_distintos   | padres_asociados   | inconsistente   |
|------------|--------------|---------------|----------------------|--------------------|-----------------|

## Resumen de conflictos temáticos XY

|   n_grupos_conflicto |   n_registros_en_conflicto |   promedio_registros_por_grupo |   max_registros_por_grupo |   promedio_anios_por_grupo |   max_anios_por_grupo |   promedio_nivel1_distintos |   promedio_nivel2_distintos |
|---------------------:|---------------------------:|-------------------------------:|--------------------------:|---------------------------:|----------------------:|----------------------------:|----------------------------:|
|               221342 |                     626664 |                         2.8312 |                        38 |                    2.81999 |                    19 |                     1.96295 |                     2.11924 |

## Conflictos temáticos XY por país

| pais_grupo                |   n_grupos_conflicto |   n_registros_en_conflicto |   promedio_registros_por_grupo |   promedio_anios_por_grupo |   max_anios_por_grupo |
|:--------------------------|---------------------:|---------------------------:|-------------------------------:|---------------------------:|----------------------:|
| El Salvador               |               132923 |                     296233 |                        2.22861 |                    2.22861 |                     3 |
| Costa Rica                |                80915 |                     240583 |                        2.97328 |                    2.94656 |                     3 |
| Honduras                  |                 3304 |                      43936 |                       13.2978  |                   13.2978  |                    18 |
| Belice                    |                 2186 |                      41553 |                       19.0087  |                   19       |                    19 |
| Guatemala                 |                 1879 |                       3765 |                        2.00373 |                    2.00266 |                     3 |
| multipais_o_inconsistente |                  135 |                        594 |                        4.4     |                    2.18519 |                     3 |

## Principales combinaciones conflictivas

| pais_grupo   | valores_nivel_1                                                                                                       | valores_nivel_2                                                                                                              |   n_grupos |   n_registros |   promedio_anios |   anio_min_global |   anio_max_global |
|:-------------|:----------------------------------------------------------------------------------------------------------------------|:-----------------------------------------------------------------------------------------------------------------------------|-----------:|--------------:|-----------------:|------------------:|------------------:|
| El Salvador  | 31 Cultivos intensivos No-Arbóreos,33 Cultivos extensivos, Pastizales y matorrales                                    | 315 Otros cultivos intensivos no arbóreos,333 Matorrales (barbecho o en descanso)                                            |      22839 |         45678 |          2       |              2000 |              2018 |
| Costa Rica   | 41 Bosque latifoliado y mixto,91 Otras                                                                                | 411 Latifoliado maduro húmedo,910 Otras                                                                                      |      12822 |         38466 |          3       |              2005 |              2018 |
| El Salvador  | 31 Cultivos intensivos No-Arbóreos,33 Cultivos extensivos, Pastizales y matorrales                                    | 315 Otros cultivos intensivos no arbóreos,332 Pastizales naturales y cultivados                                              |      18463 |         36926 |          2       |              2000 |              2018 |
| Costa Rica   | 44 Otros arbóreo en tierras no agrícola,91 Otras                                                                      | 443  Árboles fuera de bosque y otras áreas naturales,910 Otras                                                               |      11006 |         33018 |          3       |              2005 |              2018 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales,91 Otras                                                              | 332 Pastizales naturales y cultivados,910 Otras                                                                              |      10841 |         32159 |          2.93285 |              2005 |              2021 |
| El Salvador  | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 410 Bosque latifoliado y mixto,333 Matorrales (barbecho o en descanso)                                                       |      13569 |         28342 |          2.08873 |              2000 |              2018 |
| El Salvador  | 41 Bosque latifoliado y mixto,31 Cultivos intensivos No-Arbóreos                                                      | 410 Bosque latifoliado y mixto,315 Otros cultivos intensivos no arbóreos                                                     |      11258 |         22516 |          2       |              2000 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales                                                                       | 332 Pastizales naturales y cultivados,333 Matorrales (barbecho o en descanso)                                                |       9738 |         19833 |          2.03666 |              2000 |              2018 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales,44 Otros arbóreo en tierras no agrícola,91 Otras                      | 332 Pastizales naturales y cultivados,443  Árboles fuera de bosque y otras áreas naturales,910 Otras                         |       5332 |         15996 |          3       |              2005 |              2018 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales,44 Otros arbóreo en tierras no agrícola                               | 332 Pastizales naturales y cultivados,443  Árboles fuera de bosque y otras áreas naturales                                   |       5151 |         15453 |          3       |              2005 |              2018 |
| Costa Rica   | 41 Bosque latifoliado y mixto,44 Otros arbóreo en tierras no agrícola,91 Otras                                        | 412 Latifoliado secundario húmedo,443  Árboles fuera de bosque y otras áreas naturales,910 Otras                             |       4588 |         13764 |          3       |              2005 |              2018 |
| Costa Rica   | 11 Urbano,91 Otras                                                                                                    | 110 Urbano,910 Otras                                                                                                         |       4323 |         12969 |          3       |              2005 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales                                                                       | 333 Matorrales (barbecho o en descanso),332 Pastizales naturales y cultivados                                                |       6135 |         12897 |          2.1022  |              2000 |              2018 |
| El Salvador  | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 410 Bosque latifoliado y mixto,332 Pastizales naturales y cultivados                                                         |       5443 |         11892 |          2.18482 |              2000 |              2018 |
| Honduras     | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 410 Bosque latifoliado y mixto,332 Pastizales naturales y cultivados                                                         |        639 |         11070 |         17.3239  |              2000 |              2022 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales,91 Otras                                                              | 331 Granos básicos y hortalizas  y otros,910 Otras                                                                           |       3687 |         10981 |          2.9566  |              2005 |              2021 |
| Costa Rica   | 41 Bosque latifoliado y mixto,44 Otros arbóreo en tierras no agrícola                                                 | 412 Latifoliado secundario húmedo,443  Árboles fuera de bosque y otras áreas naturales                                       |       3547 |         10641 |          3       |              2005 |              2018 |
| El Salvador  | 41 Bosque latifoliado y mixto,32 Cultivos Arbóreos                                                                    | 410 Bosque latifoliado y mixto,321 Café                                                                                      |       3677 |         10001 |          2.71988 |              2000 |              2018 |
| El Salvador  | 31 Cultivos intensivos No-Arbóreos,33 Cultivos extensivos, Pastizales y matorrales                                    | 313 Caña de azúcar,332 Pastizales naturales y cultivados                                                                     |       4013 |          9108 |          2.26962 |              2000 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales                                                                       | 332 Pastizales naturales y cultivados,331 Granos básicos y hortalizas  y otros                                               |       2938 |          8814 |          3       |              2001 |              2018 |
| El Salvador  | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 410 Bosque latifoliado y mixto,331 Granos básicos y hortalizas  y otros                                                      |       2217 |          6651 |          3       |              2001 |              2018 |
| Belice       | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 412 Latifoliado secundario húmedo,333 Matorrales (barbecho o en descanso)                                                    |        284 |          5396 |         19       |              2000 |              2018 |
| Honduras     | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 410 Bosque latifoliado y mixto,333 Matorrales (barbecho o en descanso)                                                       |        371 |          5158 |         13.903   |              2000 |              2022 |
| Belice       | 41 Bosque latifoliado y mixto,31 Cultivos intensivos No-Arbóreos                                                      | 412 Latifoliado secundario húmedo,315 Otros cultivos intensivos no arbóreos                                                  |        251 |          4769 |         19       |              2000 |              2018 |
| Belice       | 41 Bosque latifoliado y mixto,31 Cultivos intensivos No-Arbóreos                                                      | 411 Latifoliado maduro húmedo,315 Otros cultivos intensivos no arbóreos                                                      |        237 |          4503 |         19       |              2000 |              2018 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales,44 Otros arbóreo en tierras no agrícola,91 Otras                      | 331 Granos básicos y hortalizas  y otros,443  Árboles fuera de bosque y otras áreas naturales,910 Otras                      |       1427 |          4281 |          3       |              2005 |              2018 |
| Belice       | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 411 Latifoliado maduro húmedo,333 Matorrales (barbecho o en descanso)                                                        |        225 |          4275 |         19       |              2000 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales                                                                       | 331 Granos básicos y hortalizas  y otros,332 Pastizales naturales y cultivados                                               |       1420 |          4260 |          3       |              2001 |              2018 |
| Belice       | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 411 Latifoliado maduro húmedo,332 Pastizales naturales y cultivados                                                          |        215 |          4085 |         19       |              2000 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales                                                                       | 333 Matorrales (barbecho o en descanso),331 Granos básicos y hortalizas  y otros                                             |       1348 |          4044 |          3       |              2001 |              2018 |
| Belice       | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 412 Latifoliado secundario húmedo,332 Pastizales naturales y cultivados                                                      |        210 |          4009 |         19       |              2000 |              2018 |
| El Salvador  | 31 Cultivos intensivos No-Arbóreos                                                                                    | 315 Otros cultivos intensivos no arbóreos,313 Caña de azúcar                                                                 |       1903 |          3806 |          2       |              2000 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales,32 Cultivos Arbóreos                                                  | 331 Granos básicos y hortalizas  y otros,321 Café                                                                            |       1237 |          3711 |          3       |              2001 |              2018 |
| Costa Rica   | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales,44 Otros arbóreo en tierras no agrícola | 412 Latifoliado secundario húmedo,332 Pastizales naturales y cultivados,443  Árboles fuera de bosque y otras áreas naturales |       1138 |          3414 |          3       |              2005 |              2018 |
| Costa Rica   | 91 Otras,32 Cultivos Arbóreos                                                                                         | 910 Otras,321 Café                                                                                                           |       1129 |          3387 |          3       |              2005 |              2017 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales,91 Otras                                                              | 332 Pastizales naturales y cultivados,331 Granos básicos y hortalizas  y otros,910 Otras                                     |       1070 |          3210 |          3       |              2005 |              2018 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales                                                                       | 332 Pastizales naturales y cultivados,331 Granos básicos y hortalizas  y otros                                               |       1016 |          2953 |          2.81299 |              2005 |              2021 |
| Costa Rica   | 11 Urbano,44 Otros arbóreo en tierras no agrícola,91 Otras                                                            | 110 Urbano,443  Árboles fuera de bosque y otras áreas naturales,910 Otras                                                    |        934 |          2802 |          3       |              2005 |              2018 |
| Honduras     | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 414 Bosque seco o deciduo,333 Matorrales (barbecho o en descanso)                                                            |        148 |          2664 |         18       |              2005 |              2022 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales,44 Otros arbóreo en tierras no agrícola                               | 331 Granos básicos y hortalizas  y otros,443  Árboles fuera de bosque y otras áreas naturales                                |        866 |          2598 |          3       |              2005 |              2018 |
| Costa Rica   | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales,91 Otras                                | 412 Latifoliado secundario húmedo,332 Pastizales naturales y cultivados,910 Otras                                            |        809 |          2427 |          3       |              2005 |              2018 |
| Belice       | 41 Bosque latifoliado y mixto,44 Otros arbóreo en tierras no agrícola                                                 | 411 Latifoliado maduro húmedo,444 Regeneración forestal                                                                      |        112 |          2128 |         19       |              2000 |              2018 |
| El Salvador  | 31 Cultivos intensivos No-Arbóreos,33 Cultivos extensivos, Pastizales y matorrales                                    | 313 Caña de azúcar,331 Granos básicos y hortalizas  y otros                                                                  |        708 |          2124 |          3       |              2001 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales,32 Cultivos Arbóreos                                                  | 332 Pastizales naturales y cultivados,325 Otros sistemas agroforestales o silvopastoriles                                    |        912 |          2065 |          2.26425 |              2000 |              2018 |
| El Salvador  | 31 Cultivos intensivos No-Arbóreos,32 Cultivos Arbóreos                                                               | 315 Otros cultivos intensivos no arbóreos,321 Café                                                                           |       1018 |          2036 |          2       |              2000 |              2018 |
| Costa Rica   | 41 Bosque latifoliado y mixto,44 Otros arbóreo en tierras no agrícola                                                 | 411 Latifoliado maduro húmedo,443  Árboles fuera de bosque y otras áreas naturales                                           |        675 |          2025 |          3       |              2005 |              2018 |
| Honduras     | 33 Cultivos extensivos, Pastizales y matorrales,42 Bosque de coníferas                                                | 333 Matorrales (barbecho o en descanso),420 Bosque de coníferas                                                              |        195 |          2022 |         10.3692  |              2000 |              2022 |
| Honduras     | 33 Cultivos extensivos, Pastizales y matorrales,42 Bosque de coníferas                                                | 332 Pastizales naturales y cultivados,420 Bosque de coníferas                                                                |        131 |          2006 |         15.313   |              2000 |              2022 |
| Costa Rica   | 31 Cultivos intensivos No-Arbóreos,91 Otras                                                                           | 311 Palma aceitera,910 Otras                                                                                                 |        644 |          1932 |          3       |              2005 |              2017 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales,11 Urbano                                                             | 332 Pastizales naturales y cultivados,112 Urbano discontinuo                                                                 |        816 |          1875 |          2.29779 |              2000 |              2018 |
| El Salvador  | 31 Cultivos intensivos No-Arbóreos,32 Cultivos Arbóreos                                                               | 315 Otros cultivos intensivos no arbóreos,323 Frutales                                                                       |        927 |          1854 |          2       |              2000 |              2018 |
| Costa Rica   | 11 Urbano,44 Otros arbóreo en tierras no agrícola                                                                     | 110 Urbano,443  Árboles fuera de bosque y otras áreas naturales                                                              |        578 |          1734 |          3       |              2005 |              2018 |
| El Salvador  | 41 Bosque latifoliado y mixto,31 Cultivos intensivos No-Arbóreos                                                      | 410 Bosque latifoliado y mixto,313 Caña de azúcar                                                                            |        735 |          1731 |          2.3551  |              2000 |              2018 |
| El Salvador  | 31 Cultivos intensivos No-Arbóreos,33 Cultivos extensivos, Pastizales y matorrales                                    | 313 Caña de azúcar,333 Matorrales (barbecho o en descanso)                                                                   |        721 |          1679 |          2.32871 |              2000 |              2018 |
| Costa Rica   | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 410 Bosque latifoliado y mixto,332 Pastizales naturales y cultivados                                                         |        815 |          1630 |          1       |              2021 |              2021 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales,11 Urbano,91 Otras                                                    | 332 Pastizales naturales y cultivados,110 Urbano,910 Otras                                                                   |        538 |          1614 |          3       |              2005 |              2018 |
| El Salvador  | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 410 Bosque latifoliado y mixto,331 Granos básicos y hortalizas  y otros,332 Pastizales naturales y cultivados                |        532 |          1596 |          3       |              2001 |              2018 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales,11 Urbano                                                             | 332 Pastizales naturales y cultivados,110 Urbano                                                                             |        519 |          1557 |          3       |              2005 |              2018 |
| El Salvador  | 31 Cultivos intensivos No-Arbóreos,32 Cultivos Arbóreos                                                               | 315 Otros cultivos intensivos no arbóreos,325 Otros sistemas agroforestales o silvopastoriles                                |        743 |          1486 |          2       |              2000 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales,32 Cultivos Arbóreos                                                  | 332 Pastizales naturales y cultivados,323 Frutales                                                                           |        656 |          1476 |          2.25    |              2000 |              2018 |
| El Salvador  | 41 Bosque latifoliado y mixto,44 Otros arbóreo en tierras no agrícola                                                 | 410 Bosque latifoliado y mixto,443  Árboles fuera de bosque y otras áreas naturales                                          |        491 |          1473 |          3       |              2001 |              2018 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales,91 Otras                                                              | 331 Granos básicos y hortalizas  y otros,332 Pastizales naturales y cultivados,910 Otras                                     |        486 |          1458 |          3       |              2005 |              2017 |
| Belice       | 41 Bosque latifoliado y mixto                                                                                         | 411 Latifoliado maduro húmedo,412 Latifoliado secundario húmedo                                                              |         71 |          1349 |         19       |              2000 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales,32 Cultivos Arbóreos                                                  | 331 Granos básicos y hortalizas  y otros,323 Frutales                                                                        |        438 |          1314 |          3       |              2001 |              2018 |
| Belice       | 33 Cultivos extensivos, Pastizales y matorrales,42 Bosque de coníferas                                                | 333 Matorrales (barbecho o en descanso),420 Bosque de coníferas                                                              |         68 |          1292 |         19       |              2000 |              2018 |
| El Salvador  | 31 Cultivos intensivos No-Arbóreos,11 Urbano                                                                          | 315 Otros cultivos intensivos no arbóreos,112 Urbano discontinuo                                                             |        633 |          1266 |          2       |              2000 |              2018 |
| El Salvador  | 41 Bosque latifoliado y mixto,32 Cultivos Arbóreos                                                                    | 410 Bosque latifoliado y mixto,325 Otros sistemas agroforestales o silvopastoriles                                           |        571 |          1255 |          2.1979  |              2000 |              2018 |
| Belice       | 31 Cultivos intensivos No-Arbóreos,33 Cultivos extensivos, Pastizales y matorrales                                    | 315 Otros cultivos intensivos no arbóreos,333 Matorrales (barbecho o en descanso)                                            |         66 |          1254 |         19       |              2000 |              2018 |
| El Salvador  | 44 Otros arbóreo en tierras no agrícola,32 Cultivos Arbóreos                                                          | 443  Árboles fuera de bosque y otras áreas naturales,321 Café                                                                |        406 |          1218 |          3       |              2001 |              2018 |
| El Salvador  | 11 Urbano,44 Otros arbóreo en tierras no agrícola                                                                     | 112 Urbano discontinuo,443  Árboles fuera de bosque y otras áreas naturales                                                  |        398 |          1194 |          3       |              2001 |              2018 |
| Honduras     | 32 Cultivos Arbóreos                                                                                                  | 321 Café,325 Otros sistemas agroforestales o silvopastoriles                                                                 |         66 |          1188 |         18       |              2005 |              2022 |
| El Salvador  | 41 Bosque latifoliado y mixto,11 Urbano                                                                               | 410 Bosque latifoliado y mixto,112 Urbano discontinuo                                                                        |        468 |          1164 |          2.48718 |              2000 |              2018 |
| Costa Rica   | 33 Cultivos extensivos, Pastizales y matorrales                                                                       | 331 Granos básicos y hortalizas  y otros,332 Pastizales naturales y cultivados                                               |        399 |          1134 |          2.68421 |              2005 |              2021 |
| Honduras     | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 410 Bosque latifoliado y mixto,331 Granos básicos y hortalizas  y otros                                                      |         62 |          1116 |         18       |              2005 |              2022 |
| Honduras     | 31 Cultivos intensivos No-Arbóreos,33 Cultivos extensivos, Pastizales y matorrales                                    | 311 Palma aceitera,332 Pastizales naturales y cultivados                                                                     |         56 |          1008 |         18       |              2005 |              2022 |
| Honduras     | 41 Bosque latifoliado y mixto,33 Cultivos extensivos, Pastizales y matorrales                                         | 414 Bosque seco o deciduo,332 Pastizales naturales y cultivados                                                              |         55 |           990 |         18       |              2005 |              2022 |
| El Salvador  | 11 Urbano,32 Cultivos Arbóreos                                                                                        | 112 Urbano discontinuo,321 Café                                                                                              |        385 |           948 |          2.46234 |              2000 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales,12 Otras tierras                                                      | 333 Matorrales (barbecho o en descanso),122 Suelo desnudo, arena, rocoso, lava, otros                                        |        391 |           931 |          2.38107 |              2000 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales,32 Cultivos Arbóreos                                                  | 333 Matorrales (barbecho o en descanso),325 Otros sistemas agroforestales o silvopastoriles                                  |        444 |           908 |          2.04505 |              2000 |              2018 |
| El Salvador  | 33 Cultivos extensivos, Pastizales y matorrales,11 Urbano                                                             | 332 Pastizales naturales y cultivados,111 Urbano continuo                                                                    |        332 |           890 |          2.68072 |              2000 |              2018 |

## Nota metodológica

Esta auditoría temática no modifica el GeoPackage original.
La base intermedia thematic_base contiene únicamente campos necesarios para análisis temático.
Los conflictos temáticos XY se calculan cruzando la tabla thematic_base con los grupos XY del Módulo 3B.

## Regla operativa recomendada

```text
Los grupos con conflicto temático no deben usarse directamente como muestras confiables de entrenamiento hasta resolver clase, año, fuente y confiabilidad.
```
