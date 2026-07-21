# SVM

Flujo para explorar modelos Support Vector Machine sobre el dataset tabular
preparado en A4.6.

La configuracion operativa principal esta consolidada en
`config/a4_8_svm.yaml`. Los YAML individuales se conservan como respaldo de
corridas especificas en `config/a4_8_svm_legacy/`.

Orden propuesto:

1. `4_8_1_prepare_svm_dataset.py`: verifica dataset, objetivos, grupo espacial y
   predictores; genera una copia preparada y diagnosticos de variables.
2. `4_8_2_create_svm_spatial_splits.py`: define particiones espaciales propias
   del flujo SVM; crea holdout independiente por cuadrantes completos, folds
   internos de validacion cruzada y asignaciones reutilizables para entrenar.
3. `4_8_3_train_linear_svm.py`: entrena un SVM lineal escalable con
   imputacion y escalamiento dentro del pipeline, usando las particiones de
   A4.8.2. La configuracion activa usa una malla robusta sobre `C` y
   `class_weight`.
   Puede recibir un YAML alternativo como argumento para corridas refinadas,
   por ejemplo `config/a4_8_3_train_linear_svm_refined_c.yaml`.
4. `4_8_4_train_nystroem_rbf_svm.py`: explora una aproximacion no lineal RBF
   mediante `Nystroem -> LinearSVC`, evitando el costo de un `SVC(kernel="rbf")`
   clasico sobre todo el dataset.
   Puede recibir un YAML alternativo como argumento para refinamientos, por
   ejemplo `config/a4_8_4_train_nystroem_rbf_svm_refined.yaml`.
5. `4_8_5_svm_report.py`: consolida resultados e interpretacion.
   Implementado como `4_8_5_svm_final_report.py`, consolida metricas,
   configuraciones recomendadas, clases fuertes/debiles y confusiones.

Secciones principales del YAML maestro:

- `prepare_dataset`
- `spatial_splits`
- `linear_svm_gridsearch`
- `linear_svm_refined_c`
- `nystroem_rbf_svm`
- `nystroem_rbf_svm_refined`
- `final_report`

Ejemplos:

```bash
python src/actividad_4/SVM/4_8_1_prepare_svm_dataset.py
python src/actividad_4/SVM/4_8_2_create_svm_spatial_splits.py
python src/actividad_4/SVM/4_8_3_train_linear_svm.py
python src/actividad_4/SVM/4_8_3_train_linear_svm.py config/a4_8_svm.yaml::linear_svm_refined_c
python src/actividad_4/SVM/4_8_4_train_nystroem_rbf_svm.py
python src/actividad_4/SVM/4_8_4_train_nystroem_rbf_svm.py config/a4_8_svm.yaml::nystroem_rbf_svm_refined
python src/actividad_4/SVM/4_8_5_svm_final_report.py
```

La imputacion y el escalamiento deben ocurrir dentro de los pipelines de
entrenamiento, no durante la preparacion, para evitar fuga de informacion.
