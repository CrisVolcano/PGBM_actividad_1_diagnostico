# Preparación de insumos para GEE - Sentinel-2 SR

Fecha de ejecución: 2026-05-19 09:24:00

## Propósito

Este módulo prepara la base de puntos evaluables para la caracterización espectro-temporal con Sentinel-2 Surface Reflectance en Google Earth Engine.

## Regla aplicada

```text
2018 <= Año <= 2022
```

No se seleccionan todavía muestras finales de entrenamiento, validación o prueba.

## Unidad de extracción para GEE

La extracción en GEE se realizará una sola vez por combinación única:

```text
Longitud + Latitud + Año
```

Los resultados espectrales podrán unirse posteriormente a todos los registros originales mediante `extract_id`.

## Resumen

| Métrica | Valor |
|---|---:|
| Total de registros de entrada | 2,881,123 |
| Registros elegibles 2018-2022 | 1,195,911 |
| Unidades únicas Longitud-Latitud-Año para GEE | 1,185,946 |
| Extracciones redundantes evitadas | 9,965 |
| Registros sin unión con grupos_xy | 0 |
| Tamaño máximo de batch | 50,000 |
| Total de batches generados | 42 |

## Salidas principales

- GeoPackage de registros elegibles: `C:\Users\jesus\OneDrive\Ejercicio 7\Documents\Work\CR\Github\PGBM_actividad_1_diagnostico\data\processed\s2_sr_gee_input\puntos_s2_sr_2018_2022.gpkg`
- Capa: `puntos_s2_sr_2018_2022`
- CSV de unidades de extracción: `C:\Users\jesus\OneDrive\Ejercicio 7\Documents\Work\CR\Github\PGBM_actividad_1_diagnostico\data\processed\s2_sr_gee_input\s2_sr_extract_units_2018_2022.csv`
- Carpeta de batches para GEE: `C:\Users\jesus\OneDrive\Ejercicio 7\Documents\Work\CR\Github\PGBM_actividad_1_diagnostico\data\processed\s2_sr_gee_input\batches`
- Tablas resumen: `C:\Users\jesus\OneDrive\Ejercicio 7\Documents\Work\CR\Github\PGBM_actividad_1_diagnostico\outputs\tables\s2_sr_gee_input`
