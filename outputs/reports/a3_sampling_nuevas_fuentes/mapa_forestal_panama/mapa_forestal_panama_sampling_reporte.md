# Reporte de sampling - mapa forestal Panama

## Identificacion

- Proyecto: PGBM - A3 sampling mapa forestal Panama
- Fuente: ForestCoverLandUse_2021_25k_mangle_recorte
- Pais: Panama
- Anio base: 2021
- Fecha de ejecucion UTC: 2026-07-14T21:43:20.273962+00:00
- Raster: `/media/estb/PGB_disco/PGBM_actividad_1_diagnostico/data/raw/Panama/ForestCoverLandUse_2021_25k_mangle_recorte.tif`
- CRS raster: `EPSG:32617`
- CRS salida: `EPSG:4326`

## Candidatos

- Candidatos validos: 50,691
- Clases representadas: 23
- Espaciamiento de malla: 250 m

## Escenarios de separacion minima

|   distance_m |   n_candidates |   n_selected |   n_rejected |   pct_selected |   n_classes |   min_nearest_neighbor_m |   median_nearest_neighbor_m |   mean_nearest_neighbor_m |
|-------------:|---------------:|-------------:|-------------:|---------------:|------------:|-------------------------:|----------------------------:|--------------------------:|
|          250 |          50691 |        50691 |            0 |      100       |          23 |                      250 |                      250    |                   250.077 |
|          500 |          50691 |        12551 |        38140 |       24.7598  |          23 |                      250 |                      500    |                   501.247 |
|         1000 |          50691 |         3107 |        47584 |        6.12929 |          23 |                      250 |                     1000    |                  1012.23  |
|         2000 |          50691 |          851 |        49840 |        1.6788  |          23 |                      250 |                     2015.56 |                  1981.18  |
|         3000 |          50691 |          391 |        50300 |        0.77134 |          23 |                      250 |                     3010.4  |                  2898.79  |

## Catalogo de clases

|   raster_value |   class_value | class_name                                  | class_name_en                              |      pixel_count |   raster_area_ha |
|---------------:|--------------:|:--------------------------------------------|:-------------------------------------------|-----------------:|-----------------:|
|              1 |             1 | Bosque latifoliado mixto maduro             | Mature Broadleaf Forest                    |      2.0103e+06  |         20103    |
|              2 |             2 | Bosque latifoliado mixto secundario         | Secondary Mixed Broadleaf Forest           |      7.34954e+06 |         73495.4  |
|              3 |             3 | Bosque de mangle                            | Mangrove Forest                            |      2.77928e+06 |         27792.8  |
|              4 |             4 | Bosque de orey                              | Orey Forest                                |      0           |             0    |
|              5 |             5 | Bosque de cativo                            | Cativo Forest                              |      0           |             0    |
|              6 |             6 | Bosque de rafia                             | Rafia Forest                               |      0           |             0    |
|              7 |             7 | Bosque plantado de coníferas                | Coniferous Forest                          |  10285           |           102.85 |
|              8 |             8 | Bosque plantado de latifoliadas             | Broadleaf Forest                           | 557909           |          5579.09 |
|              9 |             9 | Rastrojo y vegetación arbustiva             | Shrubs and Bushes                          |      3.90509e+06 |         39050.9  |
|             10 |            10 | Vegetación herbácea                         | Herbaceous Vegetation                      | 384741           |          3847.41 |
|             11 |            11 | Vegetación baja inundable                   | Flooded Vegetation                         |  11062           |           110.62 |
|             12 |            12 | Afloramiento rocoso y tierra desnuda        | Rocks and Bare Soils                       |  49409           |           494.09 |
|             13 |            13 | Playa y arenal natural                      | Sand Beaches                               |  83842           |           838.42 |
|             14 |            14 | Café                                        | Coffee                                     |    522           |             5.22 |
|             15 |            15 | Cítrico                                     | Citrus                                     |  11956           |           119.56 |
|             16 |            16 | Palma aceitera                              | Oil Palm                                   | 372118           |          3721.18 |
|             17 |            17 | Plátano/banano                              | Banana                                     |      0           |             0    |
|             18 |            18 | Otro cultivo permanente                     | Permanent Crops                            |  54157           |           541.57 |
|             19 |            19 | Arroz                                       | Rice                                       | 274492           |          2744.92 |
|             20 |            20 | Caña de azúcar                              | Sugar Cane                                 | 183957           |          1839.57 |
|             21 |            21 | Horticultura mixta                          | Mixed Horticulture                         |      0           |             0    |
|             22 |            22 | Maíz                                        | Corn                                       |      0           |             0    |
|             23 |            23 | Piña                                        | Pineapple                                  |  57560           |           575.6  |
|             24 |            24 | Otro cultivo anual                          | Other Annual Crops                         | 136885           |          1368.85 |
|             25 |            25 | Área heterogénea de producción agropecuaria | Heterogeneous Area Agricultural Production |   1125           |            11.25 |
|             26 |            26 | Pasto                                       | Pasture                                    |      1.16298e+07 |        116298    |
|             27 |            27 | Superficie de agua                          | Water Bodies                               | 910077           |          9100.77 |
|             28 |            28 | Área poblada                                | Urban Areas                                | 658089           |          6580.89 |
|             29 |            29 | Infraestructura                             | Infrastructure                             | 281073           |          2810.73 |
|             30 |            30 | Explotación minera                          | Mining                                     |      0           |             0    |
|             31 |            31 | Estanque para acuicultura                   | Aquaculture Ponds                          |    580           |             5.8  |
|             32 |            32 | Salinera                                    | Salt Mine                                  |      0           |             0    |
|             33 |            33 | Albinas                                     | Albinas                                    |      0           |             0    |

## Criterio metodologico

El flujo genera una malla regular de candidatos sobre el GeoTIFF recortado y conserva solo los puntos cuyo valor raster es valido y esta documentado en la VAT. Cada valor se homologa con `Classvalue` y `Class_name`. Luego se aplica seleccion greedy reproducible por escenarios de distancia minima, con proteccion opcional de representacion minima por clase.
