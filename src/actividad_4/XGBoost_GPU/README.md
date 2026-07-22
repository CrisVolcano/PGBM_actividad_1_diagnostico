# Actividad 4.9 - XGBoost GPU

Esta carpeta replica el flujo XGBoost CPU usando el ambiente `pgbm_gpu` y
`XGBClassifier` con `device: cuda`.

La idea metodologica es mantener constantes los datos:

- mismos predictores;
- mismo target `id_1_propuesta`;
- mismos folds espaciales por `id_cuadrante`;
- misma validacion independiente;
- misma metrica principal `f1_macro`.

Asi, la diferencia entre `XGBoost` y `XGBoost_GPU` es computacional, no de
diseno experimental.

## Ambiente

Ambiente conda:

```bash
pgbm_gpu
```

Paquetes clave:

```text
xgboost 2.1.4
libxgboost cuda128
py-xgboost-gpu
```

## Comandos

Validar insumos:

```bash
conda run -n pgbm_gpu python src/actividad_4/XGBoost_GPU/4_9_gpu_1_validate_xgboost_inputs.py
```

Entrenar modelo base GPU:

```bash
conda run -n pgbm_gpu python src/actividad_4/XGBoost_GPU/4_9_gpu_2_train_xgboost_base_model.py
```

Hiperparametrizar con GPU:

```bash
conda run -n pgbm_gpu python src/actividad_4/XGBoost_GPU/4_9_gpu_3_train_xgboost_gridsearch.py
```

Nota: para que XGBoost vea la GPU, estos comandos deben ejecutarse en una
sesion con acceso real al dispositivo NVIDIA.
