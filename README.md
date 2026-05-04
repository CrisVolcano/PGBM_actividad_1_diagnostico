# PGBM - Actividad 1: Diagnóstico regional de aptitud de fuentes y vacíos de información

## Descripción

Repositorio técnico para implementar la Actividad 1 del proyecto PGBM, orientada al diagnóstico regional de aptitud de fuentes y vacíos de información.

El objetivo es construir una base reproducible para auditar datos geoespaciales desde dimensiones estructurales, espaciales, temporales, temáticas, de trazabilidad y confiabilidad.

## Ruta local del proyecto

/media/estb/PGB_disco/PGBM_actividad_1_diagnostico

## Principios de trabajo

1. No modificar datos originales.
2. No limpiar antes de auditar.
3. No descartar registros sin documentación.
4. Registrar decisiones metodológicas.
5. Separar datos crudos, intermedios y procesados.
6. Versionar scripts, notebooks, documentación y configuración.
7. No subir datos geoespaciales pesados a GitHub.

## Estructura principal

- config/
- data/
- notebooks/
- src/
- outputs/
- logs/
- docs/

## Entorno Conda

Para crear el entorno:

conda env create -f environment.yml

Para activarlo:

conda activate pgbm_actividad1

## Estado de implementación

- [x] Módulo 0: configuración inicial del proyecto.
- [ ] Módulo 1: lectura inicial del GeoPackage.
- [ ] Módulo 2: auditoría estructural.
- [ ] Módulo 3: auditoría espacial.
- [ ] Módulo 4: auditoría temporal.
- [ ] Módulo 5: auditoría temática.
- [ ] Módulo 6: fuentes y trazabilidad.
- [ ] Módulo 7: confiabilidad.
- [ ] Módulo 8: vacíos críticos.
- [ ] Módulo 9: scoring multicriterio.
- [ ] Módulo 10: clasificación funcional.
- [ ] Módulo 11: reportes.
