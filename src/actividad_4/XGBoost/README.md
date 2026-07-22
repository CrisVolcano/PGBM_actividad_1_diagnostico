# Actividad 4.9 - XGBoost

Esta carpeta contiene una linea de modelado XGBoost independiente para la
clasificacion multiclase de `id_1_propuesta`.

La estrategia metodologica prevista reutiliza los splits espaciales ya creados
en A4.8:

- desarrollo para entrenamiento e hiperparametrizacion;
- validacion cruzada interna agrupada por `id_cuadrante`;
- validacion independiente por cuadrantes completos;
- seleccion de hiperparametros mediante `f1_macro`.

## Configuracion

El YAML maestro es:

```bash
config/a4_9_xgboost.yaml
```

Se organiza en secciones:

- `validate_inputs`: diagnostico de insumos y particiones.
- `base_model`: entrenamiento base previsto.
- `gridsearch`: hiperparametrizacion prevista.
- `final_report`: consolidacion prevista.

## Script disponible

Validar insumos:

```bash
conda run -n pgbm_actividad1 python src/actividad_4/XGBoost/4_9_1_validate_xgboost_inputs.py
```

Este script no entrena ningun modelo. Solo verifica que los datos y folds esten
listos para XGBoost.

Entrenar modelo base:

```bash
conda run -n pgbm_actividad1 python src/actividad_4/XGBoost/4_9_2_train_xgboost_base_model.py
```

Este script entrena un XGBoost multiclase con parametros fijos del YAML,
calcula diagnostico OOF con los folds espaciales existentes y evalua la
validacion independiente.

Hiperparametrizar XGBoost:

```bash
conda run -n pgbm_actividad1 python src/actividad_4/XGBoost/4_9_3_train_xgboost_gridsearch.py
```

La malla inicial definida en `config/a4_9_xgboost.yaml` evalua 16
combinaciones con 3 folds espaciales, es decir 48 entrenamientos internos. La
validacion independiente queda fuera de `GridSearchCV` y se evalua solo al
final.
