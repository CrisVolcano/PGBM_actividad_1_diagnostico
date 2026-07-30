#!/usr/bin/env python3
"""Calcula importancia por permutación para la DNN final sin reentrenarla.

La importancia de una variable es la caída de la métrica del holdout espacial
independiente al permutar únicamente esa columna. El modelo y el preprocesador
se cargan desde los artefactos congelados de A4.8; nunca se crea un optimizador
ni se actualizan los pesos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Se inicia antes de importar las dependencias científicas para que la duración
# registrada incluya también el costo de cargar NumPy, scikit-learn y PyTorch.
PROCESS_STARTED = time.perf_counter()
PROCESS_STARTED_UTC = datetime.now(timezone.utc)

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    accuracy_score,
    balanced_accuracy_score,
    cohen_kappa_score,
    f1_score,
)


LOGGER = logging.getLogger("a4_8_dnn_permutation_importance")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_8_dnn_permutation_importance.yaml"
SUPPORTED_METRICS = ("f1_macro", "f1_weighted", "balanced_accuracy", "accuracy")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"))
    parser.add_argument("--n-repeats", type=int)
    parser.add_argument("--sample-size", type=int)
    parser.add_argument("--max-features", type=int)
    parser.add_argument(
        "--features",
        nargs="+",
        help="Nombres exactos de variables; si se omite se usa la lista del YAML.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Sobrescribe paths.output_dir (útil para una prueba acotada).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Valida y carga artefactos, pero no ejecuta permutaciones.",
    )
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError(f"El YAML no contiene un diccionario: {path}")
    return config


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def configure_logger(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, mode="w", encoding="utf-8"),
        ],
        force=True,
    )


def import_torch() -> tuple[Any, Any]:
    try:
        import torch
        from torch import nn
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "PyTorch no está instalado en este entorno. Ejecute el análisis en el "
            "mismo entorno usado para entrenar la DNN."
        ) from exc
    return torch, nn


def choose_device(torch: Any, configured: str) -> Any:
    configured = configured.lower()
    if configured == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    device = torch.device(configured)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Se solicitó CUDA, pero PyTorch no detecta una GPU CUDA.")
    if (
        device.type == "mps"
        and (not hasattr(torch.backends, "mps") or not torch.backends.mps.is_available())
    ):
        raise RuntimeError("Se solicitó MPS, pero PyTorch no lo tiene disponible.")
    return device


def torch_load(torch: Any, path: Path, map_location: Any) -> dict[str, Any]:
    try:
        artifact = torch.load(path, map_location=map_location, weights_only=False)
    except TypeError:
        artifact = torch.load(path, map_location=map_location)
    if not isinstance(artifact, dict):
        raise TypeError(f"El artefacto del modelo no es un diccionario: {path}")
    return artifact


def build_model_from_artifact(nn: Any, artifact: dict[str, Any]) -> Any:
    required = {
        "model_state_dict",
        "input_dim",
        "n_classes",
        "hidden_units",
        "activation",
        "dropout",
        "feature_columns",
        "class_mapping",
        "trained_on",
    }
    missing = sorted(required - set(artifact))
    if missing:
        raise KeyError(f"Al artefacto DNN le faltan campos: {missing}")

    activation_name = str(artifact["activation"]).lower()
    if activation_name == "tanh":
        activation_factory = nn.Tanh
    elif activation_name == "relu":
        activation_factory = nn.ReLU
    else:
        raise ValueError(f"Activación no soportada: {activation_name}")

    layers: list[Any] = []
    previous = int(artifact["input_dim"])
    dropout = float(artifact["dropout"])
    for width_value in artifact["hidden_units"]:
        width = int(width_value)
        layers.append(nn.Linear(previous, width))
        layers.append(activation_factory())
        if dropout > 0:
            layers.append(nn.Dropout(p=dropout))
        previous = width
    layers.append(nn.Linear(previous, int(artifact["n_classes"])))
    model = nn.Sequential(*layers)
    model.load_state_dict(artifact["model_state_dict"], strict=True)
    return model


def read_features(path: Path) -> list[str]:
    features = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not features or len(features) != len(set(features)):
        raise ValueError("feature_columns.txt está vacío o contiene duplicados.")
    return features


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_artifacts(
    prepared_dir: Path,
    model_path: Path,
    preprocessor_path: Path,
    artifact: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]], np.ndarray]:
    feature_path = prepared_dir / "metadata" / "feature_columns.txt"
    class_path = prepared_dir / "metadata" / "class_mapping.json"
    split_path = prepared_dir / "arrays" / "spatial_indices.npz"
    required = [
        prepared_dir / "arrays" / "X_raw_float32.npy",
        prepared_dir / "arrays" / "y_encoded.npy",
        feature_path,
        class_path,
        split_path,
        model_path,
        preprocessor_path,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Faltan artefactos requeridos: {missing}")

    features = read_features(feature_path)
    classes = load_json(class_path)
    if artifact["trained_on"] != "development_only":
        raise ValueError(
            "La importancia debe usar el modelo 'development_only'; se encontró "
            f"{artifact['trained_on']!r}."
        )
    if list(artifact["feature_columns"]) != features:
        raise ValueError("Las variables del modelo no coinciden con los datos preparados.")
    if artifact["class_mapping"] != classes:
        raise ValueError("Las clases del modelo no coinciden con class_mapping.json.")
    if int(artifact["input_dim"]) != len(features):
        raise ValueError("input_dim del modelo no coincide con feature_columns.txt.")
    if int(artifact["n_classes"]) != len(classes):
        raise ValueError("n_classes del modelo no coincide con class_mapping.json.")

    with np.load(split_path, allow_pickle=False) as archive:
        if "independent_indices" not in archive.files:
            raise KeyError("spatial_indices.npz no contiene independent_indices.")
        independent = archive["independent_indices"].astype(np.int64, copy=False)
        if "development_indices" in archive.files:
            development = archive["development_indices"].astype(np.int64, copy=False)
            if np.intersect1d(independent, development).size:
                raise ValueError("Desarrollo y holdout independiente comparten filas.")
    if len(independent) != len(np.unique(independent)):
        raise ValueError("El holdout independiente contiene índices duplicados.")
    return features, classes, independent


def select_evaluation_rows(
    independent: np.ndarray,
    sample_size: int | None,
    random_state: int,
) -> np.ndarray:
    if sample_size is None:
        return independent
    if sample_size <= 0:
        raise ValueError("sample_size debe ser positivo.")
    if sample_size >= len(independent):
        return independent
    rng = np.random.default_rng(random_state)
    positions = np.sort(rng.choice(len(independent), size=sample_size, replace=False))
    return independent[positions]


def select_feature_indices(
    all_features: list[str],
    configured_features: list[str] | None,
    max_features: int | None,
) -> list[int]:
    selected_names = configured_features or all_features
    if len(selected_names) != len(set(selected_names)):
        raise ValueError("La selección de variables contiene duplicados.")
    unknown = sorted(set(selected_names) - set(all_features))
    if unknown:
        raise ValueError(f"Variables solicitadas no encontradas: {unknown}")
    indices = [all_features.index(name) for name in selected_names]
    if max_features is not None:
        if max_features <= 0:
            raise ValueError("max_features debe ser positivo.")
        indices = indices[:max_features]
    if not indices:
        raise ValueError("No se seleccionó ninguna variable para analizar.")
    return indices


def predict_labels(
    torch: Any,
    model: Any,
    X: np.ndarray,
    batch_size: int,
    device: Any,
) -> np.ndarray:
    if batch_size <= 0:
        raise ValueError("prediction_batch_size debe ser positivo.")
    predictions: list[np.ndarray] = []
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(X), batch_size):
            batch = np.ascontiguousarray(X[start : start + batch_size])
            tensor = torch.from_numpy(batch).to(
                device,
                non_blocking=device.type == "cuda",
            )
            logits = model(tensor)
            predictions.append(torch.argmax(logits, dim=1).cpu().numpy())
    return np.concatenate(predictions)


def metric_functions(
    labels: np.ndarray,
) -> dict[str, Callable[[np.ndarray, np.ndarray], float]]:
    return {
        "f1_macro": lambda y, pred: float(
            f1_score(y, pred, labels=labels, average="macro", zero_division=0)
        ),
        "f1_weighted": lambda y, pred: float(
            f1_score(y, pred, labels=labels, average="weighted", zero_division=0)
        ),
        "balanced_accuracy": lambda y, pred: float(balanced_accuracy_score(y, pred)),
        "accuracy": lambda y, pred: float(accuracy_score(y, pred)),
    }


def calculate_baseline_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    labels: np.ndarray,
) -> dict[str, float]:
    functions = metric_functions(labels)
    return {
        name: function(y_true, y_pred)
        for name, function in functions.items()
    } | {"cohen_kappa": float(cohen_kappa_score(y_true, y_pred, labels=labels))}


def permutation_seed(random_state: int, feature_index: int, repeat: int) -> int:
    sequence = np.random.SeedSequence([random_state, feature_index, repeat])
    return int(sequence.generate_state(1, dtype=np.uint32)[0])


def run_permutations(
    torch: Any,
    model: Any,
    X: np.ndarray,
    y: np.ndarray,
    all_features: list[str],
    feature_indices: list[int],
    metric_name: str,
    baseline_score: float,
    labels: np.ndarray,
    n_repeats: int,
    random_state: int,
    batch_size: int,
    device: Any,
) -> pd.DataFrame:
    if n_repeats <= 0:
        raise ValueError("n_repeats debe ser positivo.")
    score_function = metric_functions(labels)[metric_name]
    X_work = X.copy()
    records: list[dict[str, Any]] = []

    for position, feature_index in enumerate(feature_indices, start=1):
        feature_name = all_features[feature_index]
        original_column = X[:, feature_index].copy()
        LOGGER.info(
            "Variable %s/%s: %s",
            position,
            len(feature_indices),
            feature_name,
        )
        for repeat in range(1, n_repeats + 1):
            seed = permutation_seed(random_state, feature_index, repeat)
            rng = np.random.default_rng(seed)
            started = time.perf_counter()
            order = rng.permutation(len(X))
            X_work[:, feature_index] = original_column[order]
            prediction = predict_labels(
                torch,
                model,
                X_work,
                batch_size,
                device,
            )
            permuted_score = score_function(y, prediction)
            duration = time.perf_counter() - started
            records.append(
                {
                    "feature_index": feature_index,
                    "feature": feature_name,
                    "repeat": repeat,
                    "seed": seed,
                    "baseline_metric": baseline_score,
                    "permuted_metric": permuted_score,
                    "importance_drop": baseline_score - permuted_score,
                    "duration_seconds": duration,
                    "n_rows": len(y),
                }
            )
            LOGGER.info(
                "  repetición=%s/%s | %s=%.6f | caída=%.6f | tiempo=%.2fs",
                repeat,
                n_repeats,
                metric_name,
                permuted_score,
                baseline_score - permuted_score,
                duration,
            )
        X_work[:, feature_index] = original_column
    return pd.DataFrame.from_records(records)


def summarize_importance(repeats: pd.DataFrame) -> pd.DataFrame:
    summary = (
        repeats.groupby(["feature_index", "feature"], as_index=False)
        .agg(
            importance_mean=("importance_drop", "mean"),
            importance_std=("importance_drop", "std"),
            importance_min=("importance_drop", "min"),
            importance_max=("importance_drop", "max"),
            permuted_metric_mean=("permuted_metric", "mean"),
            mean_duration_seconds=("duration_seconds", "mean"),
            n_repeats=("repeat", "count"),
        )
        .sort_values(
            ["importance_mean", "feature"],
            ascending=[False, True],
            kind="stable",
        )
        .reset_index(drop=True)
    )
    summary["importance_std"] = summary["importance_std"].fillna(0.0)
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))
    return summary


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv_atomic(dataframe: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    dataframe.to_csv(temporary, index=False)
    temporary.replace(path)


def write_json_atomic(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text_atomic(value: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def dataframe_to_markdown(dataframe: pd.DataFrame) -> str:
    def render(value: Any) -> str:
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.6f}"
        return str(value).replace("|", "\\|")

    columns = list(dataframe.columns)
    rows = [
        "| " + " | ".join(render(value) for value in row) + " |"
        for row in dataframe.itertuples(index=False, name=None)
    ]
    return "\n".join(
        [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join(["---"] * len(columns)) + " |",
            *rows,
        ]
    )


def build_report(
    summary: pd.DataFrame,
    baseline: dict[str, float],
    metric_name: str,
    n_rows: int,
    n_holdout_rows: int,
    n_all_features: int,
    n_selected_features: int,
    n_repeats: int,
    device: Any,
    trained_on: str,
    total_seconds: float,
) -> str:
    top = summary[
        [
            "rank",
            "feature",
            "importance_mean",
            "importance_std",
            "permuted_metric_mean",
        ]
    ].head(20)
    baseline_table = pd.DataFrame(
        [{"metric": name, "value": value} for name, value in baseline.items()]
    )
    return "\n".join(
        [
            "# A4.8 — Importancia por permutación de la DNN",
            "",
            "## Protocolo",
            "",
            "Este análisis carga la DNN congelada, la coloca en modo de evaluación "
            "y **no reentrena ni modifica sus pesos**. Cada importancia es la caída "
            f"de `{metric_name}` al permutar una variable en el holdout espacial "
            "independiente.",
            "",
            f"- Modelo entrenado sobre: `{trained_on}`",
            f"- Dispositivo de inferencia: `{device}`",
            f"- Filas evaluadas: {n_rows:,} de {n_holdout_rows:,} del holdout",
            f"- Variables analizadas: {n_selected_features:,} de {n_all_features:,}",
            f"- Repeticiones por variable: {n_repeats}",
            f"- Duración total: {total_seconds:.2f} s ({total_seconds / 60:.2f} min)",
            "",
            "## Métricas de referencia",
            "",
            dataframe_to_markdown(baseline_table),
            "",
            "## Variables con mayor caída de la métrica",
            "",
            dataframe_to_markdown(top),
            "",
            "Una importancia negativa significa que la métrica mejoró ligeramente "
            "al permutar la variable; no debe forzarse a cero. En variables "
            "correlacionadas, la importancia puede repartirse entre predictores y "
            "subestimar el aporte conjunto.",
            "",
        ]
    )


def output_path(output_dir: Path, outputs: dict[str, Any], key: str) -> Path:
    return output_dir / Path(str(outputs[key]))


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    config = read_yaml(config_path)
    paths = config["paths"]
    runtime = config.get("runtime", {})
    analysis = config.get("analysis", {})
    outputs = config["outputs"]

    prepared_dir = resolve_repo_path(paths["prepared_data_dir"])
    model_path = resolve_repo_path(paths["model_artifact"])
    preprocessor_path = resolve_repo_path(paths["preprocessor"])
    output_dir = (
        resolve_repo_path(args.output_dir)
        if args.output_dir is not None
        else resolve_repo_path(paths["output_dir"])
    )
    log_path = output_path(output_dir, outputs, "log")
    configure_logger(log_path)

    started_utc = PROCESS_STARTED_UTC
    total_started = PROCESS_STARTED
    LOGGER.info("Configuración: %s", config_path)
    LOGGER.info("Análisis posentrenamiento: los pesos de la DNN no se modificarán.")

    torch, nn = import_torch()
    device_name = args.device or str(runtime.get("device", "auto"))
    device = choose_device(torch, device_name)
    artifact = torch_load(torch, model_path, map_location=device)
    features, classes, independent = validate_artifacts(
        prepared_dir,
        model_path,
        preprocessor_path,
        artifact,
    )
    model = build_model_from_artifact(nn, artifact).to(device)
    model.eval()
    if any(parameter.requires_grad for parameter in model.parameters()):
        for parameter in model.parameters():
            parameter.requires_grad_(False)

    configured_sample = args.sample_size
    if configured_sample is None:
        configured_sample = analysis.get("sample_size")
    random_state = int(analysis.get("random_state", 42))
    evaluation_indices = select_evaluation_rows(
        independent,
        int(configured_sample) if configured_sample is not None else None,
        random_state,
    )

    X_path = prepared_dir / "arrays" / "X_raw_float32.npy"
    y_path = prepared_dir / "arrays" / "y_encoded.npy"
    X_raw = np.load(X_path, mmap_mode="r", allow_pickle=False)
    y_all = np.load(y_path, mmap_mode="r", allow_pickle=False)
    if X_raw.ndim != 2 or X_raw.shape[1] != len(features):
        raise ValueError(f"Forma inesperada de X: {X_raw.shape}")
    if len(y_all) != len(X_raw):
        raise ValueError("X e y no contienen la misma cantidad de filas.")
    if np.any(evaluation_indices < 0) or np.any(evaluation_indices >= len(X_raw)):
        raise IndexError("El holdout contiene índices fuera del rango de X.")

    preprocessor = joblib.load(preprocessor_path)
    n_features_in = getattr(preprocessor, "n_features_in_", len(features))
    if int(n_features_in) != len(features):
        raise ValueError("El preprocesador no fue ajustado con las mismas variables.")
    transform_started = time.perf_counter()
    X = preprocessor.transform(np.asarray(X_raw[evaluation_indices]))
    X = np.asarray(X, dtype=np.float32)
    y = np.asarray(y_all[evaluation_indices], dtype=np.int64)
    transform_seconds = time.perf_counter() - transform_started
    if not np.isfinite(X).all():
        raise ValueError("El preprocesamiento produjo valores no finitos.")

    configured_features = args.features
    if configured_features is None:
        configured_features = list(analysis.get("features") or [])
    feature_indices = select_feature_indices(
        features,
        configured_features,
        args.max_features,
    )
    metric_name = str(analysis.get("metric", "f1_macro"))
    if metric_name not in SUPPORTED_METRICS:
        raise ValueError(
            f"Métrica {metric_name!r} no soportada; opciones: {SUPPORTED_METRICS}"
        )
    n_repeats = (
        args.n_repeats
        if args.n_repeats is not None
        else int(analysis.get("n_repeats", 5))
    )
    batch_size = int(runtime.get("prediction_batch_size", 4096))
    LOGGER.info(
        "Artefactos validados | holdout=%s | muestra=%s | variables=%s | device=%s",
        len(independent),
        len(evaluation_indices),
        len(feature_indices),
        device,
    )
    if args.validate_only:
        LOGGER.info(
            "Validación terminada en %.2fs; no se ejecutaron inferencias ni permutaciones.",
            time.perf_counter() - total_started,
        )
        return 0

    labels = np.arange(len(classes), dtype=np.int64)
    baseline_started = time.perf_counter()
    baseline_prediction = predict_labels(
        torch,
        model,
        X,
        batch_size,
        device,
    )
    baseline_inference_seconds = time.perf_counter() - baseline_started
    baseline = calculate_baseline_metrics(y, baseline_prediction, labels)
    baseline_score = baseline[metric_name]
    LOGGER.info(
        "Referencia | %s=%.6f | inferencia=%.2fs",
        metric_name,
        baseline_score,
        baseline_inference_seconds,
    )

    repeats = run_permutations(
        torch,
        model,
        X,
        y,
        features,
        feature_indices,
        metric_name,
        baseline_score,
        labels,
        n_repeats,
        random_state,
        batch_size,
        device,
    )
    summary = summarize_importance(repeats)
    total_seconds = time.perf_counter() - total_started
    finished_utc = datetime.now(timezone.utc)

    baseline_frame = pd.DataFrame(
        [
            {
                "evaluation": "independent_holdout",
                "n_rows": len(y),
                "n_holdout_rows": len(independent),
                "metric_used_for_importance": metric_name,
                **baseline,
                "preprocessing_seconds": transform_seconds,
                "baseline_inference_seconds": baseline_inference_seconds,
                "total_run_seconds": total_seconds,
            }
        ]
    )
    importance_path = output_path(output_dir, outputs, "importance_csv")
    repeats_path = output_path(output_dir, outputs, "repeats_csv")
    baseline_path = output_path(output_dir, outputs, "baseline_metrics_csv")
    report_path = output_path(output_dir, outputs, "report_md")
    metadata_path = output_path(output_dir, outputs, "metadata_json")
    write_csv_atomic(summary, importance_path)
    write_csv_atomic(repeats, repeats_path)
    write_csv_atomic(baseline_frame, baseline_path)

    report = build_report(
        summary,
        baseline,
        metric_name,
        len(y),
        len(independent),
        len(features),
        len(feature_indices),
        n_repeats,
        device,
        str(artifact["trained_on"]),
        total_seconds,
    )
    write_text_atomic(report, report_path)
    metadata = {
        "status": "completed",
        "started_utc": started_utc.isoformat(),
        "finished_utc": finished_utc.isoformat(),
        "duration_seconds": total_seconds,
        "config_path": str(config_path),
        "prepared_data_dir": str(prepared_dir),
        "model_artifact": str(model_path),
        "model_artifact_sha256": sha256_file(model_path),
        "preprocessor": str(preprocessor_path),
        "preprocessor_sha256": sha256_file(preprocessor_path),
        "trained_on": artifact["trained_on"],
        "device": str(device),
        "torch_version": str(torch.__version__),
        "metric": metric_name,
        "baseline_score": baseline_score,
        "n_holdout_rows": len(independent),
        "n_evaluated_rows": len(y),
        "n_available_features": len(features),
        "n_analyzed_features": len(feature_indices),
        "analyzed_features": [features[index] for index in feature_indices],
        "n_repeats": n_repeats,
        "random_state": random_state,
        "preprocessing_seconds": transform_seconds,
        "baseline_inference_seconds": baseline_inference_seconds,
        "sum_permutation_seconds": float(repeats["duration_seconds"].sum()),
    }
    write_json_atomic(metadata, metadata_path)
    metadata_copy = output_dir / "metadata" / "config_used.yaml"
    metadata_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, metadata_copy)

    LOGGER.info(
        "Importancia finalizada | tiempo_total=%.2fs (%.2fmin) | tabla=%s",
        total_seconds,
        total_seconds / 60,
        importance_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
