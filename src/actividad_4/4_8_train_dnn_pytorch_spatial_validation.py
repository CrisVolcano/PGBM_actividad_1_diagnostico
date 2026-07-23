#!/usr/bin/env python3
"""Entrena y evalúa una DNN PyTorch con las particiones espaciales del RF.

La búsqueda reutiliza folds congelados. Cada trayectoria se entrena una sola vez
hasta ``max_epochs`` y guarda estados en ``evaluation_epochs``. La validación
independiente permanece fuera de la selección y se consulta una sola vez después
de reentrenar la configuración elegida con todo el conjunto de desarrollo.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import logging
import os
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_class_weight


LOGGER = logging.getLogger("a4_8_train_dnn_pytorch")
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else Path.cwd()
DEFAULT_CONFIG = REPO_ROOT / "config" / "a4_8_train_dnn_pytorch_spatial_validation.yaml"



@dataclass
class PreparedData:
    X: np.ndarray
    y: np.ndarray
    groups: np.ndarray
    row_keys: np.ndarray
    indices: dict[str, np.ndarray]
    sample_index: pd.DataFrame
    features: list[str]
    classes: list[dict[str, Any]]
    manifest: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help=(
            "Regenera el Markdown y las tablas derivadas usando los CSV existentes; "
            "no entrena, no ejecuta inferencia y no carga PyTorch."
        ),
    )
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError(f"El YAML no contiene un diccionario: {path}")
    return config


def resolve_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def configure_logger(output_dir: Path) -> None:
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(output_dir / "logs" / "train_dnn.log", encoding="utf-8"),
        ],
        force=True,
    )


def import_torch():
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, TensorDataset
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "PyTorch no está instalado. Instale una versión compatible con su CPU/GPU "
            "siguiendo https://pytorch.org/get-started/locally/ y vuelva a ejecutar."
        ) from exc
    return torch, nn, DataLoader, TensorDataset


def seed_everything(torch: Any, seed: int, deterministic: bool) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if deterministic:
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        try:
            torch.use_deterministic_algorithms(True, warn_only=True)
        except TypeError:
            torch.use_deterministic_algorithms(True)


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
        raise RuntimeError("Se configuró CUDA, pero PyTorch no detecta una GPU CUDA.")
    return device


def sha256_text(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def load_prepared_data(prepared_dir: Path) -> PreparedData:
    arrays = prepared_dir / "arrays"
    metadata = prepared_dir / "metadata"
    tables = prepared_dir / "tables"
    required = [
        arrays / "X_raw_float32.npy",
        arrays / "y_encoded.npy",
        arrays / "groups.npy",
        arrays / "row_keys.npy",
        arrays / "spatial_indices.npz",
        metadata / "feature_columns.txt",
        metadata / "class_mapping.json",
        metadata / "dataset_manifest.json",
        tables / "sample_index.csv",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Faltan artefactos preparados: {missing}")

    X = np.load(arrays / "X_raw_float32.npy", allow_pickle=False)
    y = np.load(arrays / "y_encoded.npy", allow_pickle=False)
    groups = np.load(arrays / "groups.npy", allow_pickle=False)
    row_keys = np.load(arrays / "row_keys.npy", allow_pickle=False)
    with np.load(arrays / "spatial_indices.npz", allow_pickle=False) as archive:
        indices = {key: archive[key].astype(np.int64, copy=False) for key in archive.files}
    features = [
        line.strip()
        for line in (metadata / "feature_columns.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    classes = json.loads((metadata / "class_mapping.json").read_text(encoding="utf-8"))
    manifest = json.loads((metadata / "dataset_manifest.json").read_text(encoding="utf-8"))
    sample_index = pd.read_csv(tables / "sample_index.csv", low_memory=False)

    n = X.shape[0]
    if X.ndim != 2:
        raise ValueError(f"X debe ser bidimensional; forma encontrada: {X.shape}")
    if any(len(value) != n for value in [y, groups, row_keys, sample_index]):
        raise ValueError("Los artefactos preparados no tienen la misma cantidad de filas.")
    if X.shape[1] != len(features):
        raise ValueError("El número de columnas de X no coincide con feature_columns.txt.")
    if sha256_text(features) != manifest.get("feature_columns_sha256"):
        raise ValueError("feature_columns.txt no coincide con el manifiesto preparado.")
    if int(manifest["n_classes"]) != len(classes):
        raise ValueError("class_mapping.json no coincide con el manifiesto.")
    expected_labels = np.arange(len(classes), dtype=np.int64)
    observed_labels = np.unique(y)
    if not np.array_equal(observed_labels, expected_labels):
        raise ValueError(
            f"Las clases codificadas deben ser consecutivas: {observed_labels.tolist()}"
        )
    return PreparedData(X, y, groups, row_keys, indices, sample_index, features, classes, manifest)


def validate_frozen_splits(data: PreparedData) -> list[int]:
    if "development_indices" not in data.indices or "independent_indices" not in data.indices:
        raise ValueError("spatial_indices.npz no contiene desarrollo/independiente.")
    fold_ids = [int(value) for value in data.manifest["fold_ids"]]
    n = len(data.y)
    all_used: list[np.ndarray] = []
    for fold_id in fold_ids:
        train_key = f"fold_{fold_id}_train"
        val_key = f"fold_{fold_id}_validation"
        if train_key not in data.indices or val_key not in data.indices:
            raise ValueError(f"Faltan índices del fold {fold_id}.")
        train_idx = data.indices[train_key]
        val_idx = data.indices[val_key]
        if np.any(train_idx < 0) or np.any(train_idx >= n) or np.any(val_idx < 0) or np.any(val_idx >= n):
            raise ValueError(f"Fold {fold_id} contiene índices fuera de rango.")
        if np.intersect1d(train_idx, val_idx).size:
            raise ValueError(f"Fold {fold_id} comparte filas entre train y validation.")
        if set(data.groups[train_idx].astype(str)) & set(data.groups[val_idx].astype(str)):
            raise ValueError(f"Fold {fold_id} comparte cuadrantes entre train y validation.")
        unseen = set(data.y[val_idx].tolist()) - set(data.y[train_idx].tolist())
        if unseen:
            raise ValueError(f"Fold {fold_id} contiene clases no vistas en train: {sorted(unseen)}")
        all_used.append(val_idx)
    concatenated = np.concatenate(all_used)
    development = np.sort(data.indices["development_indices"])
    if not np.array_equal(np.sort(concatenated), development):
        raise ValueError("Las validaciones de los folds no cubren exactamente el desarrollo.")
    independent_groups = set(data.groups[data.indices["independent_indices"]].astype(str))
    development_groups = set(data.groups[development].astype(str))
    if independent_groups & development_groups:
        raise ValueError("Hay cuadrantes compartidos entre desarrollo e independiente.")
    return fold_ids


def build_preprocessor(config: dict[str, Any]) -> Pipeline:
    prep_cfg = config.get("preprocessing", {})
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy=prep_cfg.get("imputer_strategy", "median"))),
            ("scaler", StandardScaler()),
        ]
    )


def fit_transform_fold(
    data: PreparedData,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    config: dict[str, Any],
    preprocessor_path: Path,
) -> tuple[np.ndarray, np.ndarray, Pipeline]:
    preprocessor = build_preprocessor(config)
    X_train = preprocessor.fit_transform(data.X[train_idx]).astype(np.float32, copy=False)
    X_val = preprocessor.transform(data.X[val_idx]).astype(np.float32, copy=False)
    preprocessor_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(preprocessor, preprocessor_path)
    if not np.isfinite(X_train).all() or not np.isfinite(X_val).all():
        raise ValueError("El preprocesamiento produjo valores no finitos.")
    return X_train, X_val, preprocessor


def make_model(nn: Any, input_dim: int, n_classes: int, config: dict[str, Any], dropout: float):
    model_cfg = config["model"]
    hidden_units = [int(value) for value in model_cfg["hidden_units"]]
    activation_name = str(model_cfg.get("activation", "tanh")).lower()
    if activation_name == "tanh":
        activation_factory = nn.Tanh
    elif activation_name == "relu":
        activation_factory = nn.ReLU
    else:
        raise ValueError(f"Activación no soportada: {activation_name}")

    layers: list[Any] = []
    previous = input_dim
    for width in hidden_units:
        layers.append(nn.Linear(previous, width))
        layers.append(activation_factory())
        if dropout > 0:
            layers.append(nn.Dropout(p=float(dropout)))
        previous = width
    layers.append(nn.Linear(previous, n_classes))
    model = nn.Sequential(*layers)

    initializer = str(model_cfg.get("initializer", "xavier_uniform")).lower()
    for module in model.modules():
        if isinstance(module, nn.Linear):
            if initializer == "xavier_uniform":
                nn.init.xavier_uniform_(module.weight)
            elif initializer == "xavier_normal":
                nn.init.xavier_normal_(module.weight)
            else:
                raise ValueError(f"Inicializador no soportado: {initializer}")
            nn.init.zeros_(module.bias)
    return model


def make_optimizer(
    torch: Any,
    model: Any,
    config: dict[str, Any],
    optimizer_name: str,
    learning_rate: float,
):
    training = config["training"]
    name = str(optimizer_name).lower()
    weight_decay = float(training.get("weight_decay", 0.0))
    if name == "adamw":
        return torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    if name == "adam":
        return torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    if name == "adagrad":
        return torch.optim.Adagrad(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    if name == "rmsprop":
        return torch.optim.RMSprop(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    if name == "sgd":
        return torch.optim.SGD(
            model.parameters(), lr=learning_rate, momentum=0.9, weight_decay=weight_decay
        )
    raise ValueError(f"Optimizador no soportado: {name}")


def validation_epoch_metrics(
    torch: Any,
    DataLoader: Any,
    TensorDataset: Any,
    model: Any,
    criterion: Any,
    X_val: np.ndarray,
    y_val: np.ndarray,
    batch_size: int,
    device: Any,
) -> tuple[float, float]:
    loader = make_loader(
        torch, DataLoader, TensorDataset, X_val, y_val, batch_size,
        False, None, 0, bool(device.type == "cuda"),
    )
    total_loss = 0.0
    total_rows = 0
    predictions: list[np.ndarray] = []
    model.eval()
    with torch.no_grad():
        for X_batch, y_batch in loader:
            X_batch = X_batch.to(device, non_blocking=device.type == "cuda")
            y_batch = y_batch.to(device, non_blocking=device.type == "cuda")
            logits = model(X_batch)
            loss = criterion(logits, y_batch)
            rows = int(y_batch.shape[0])
            total_loss += float(loss.detach().cpu()) * rows
            total_rows += rows
            predictions.append(torch.argmax(logits, dim=1).cpu().numpy())
    y_pred = np.concatenate(predictions)
    return total_loss / max(total_rows, 1), float(
        f1_score(y_val, y_pred, average="macro", zero_division=0)
    )


def save_learning_curve(
    history: pd.DataFrame,
    run_dir: Path,
    config: dict[str, Any],
    render_plot: bool,
) -> None:
    outputs = config.get("outputs", {})
    run_dir.mkdir(parents=True, exist_ok=True)
    if bool(outputs.get("save_learning_history_csv", True)):
        history.to_csv(
            run_dir / "learning_history.csv",
            index=False,
            encoding="utf-8-sig",
        )
    if not render_plot or not bool(outputs.get("save_final_learning_curve", True)):
        return

    figure = None
    pyplot = None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        pyplot = plt
        has_validation = bool(
            history["validation_loss"].notna().any()
            or history["validation_f1_macro"].notna().any()
        )
        n_panels = 2 if has_validation else 1
        figure, axes = plt.subplots(1, n_panels, figsize=(12 if has_validation else 7, 4.5))
        axes_array = np.atleast_1d(axes)
        axes_array[0].plot(
            history["epoch"],
            history["training_loss"],
            label="Entrenamiento",
        )
        if history["validation_loss"].notna().any():
            axes_array[0].plot(
                history["epoch"],
                history["validation_loss"],
                label="Validación",
            )
        axes_array[0].set(xlabel="Época", ylabel="Loss", title="Curva de pérdida")
        axes_array[0].legend()
        axes_array[0].grid(alpha=0.25)
        if has_validation:
            axes_array[1].plot(
                history["epoch"],
                history["validation_f1_macro"],
                color="#2a9d8f",
            )
            axes_array[1].set(
                xlabel="Época",
                ylabel="F1 macro",
                title="Aprendizaje en validación",
            )
            axes_array[1].grid(alpha=0.25)
        figure.suptitle(run_dir.parent.name + " | " + run_dir.name)
        figure.tight_layout()

        # run_dir = output_dir/checkpoints/config_id/fold_id
        output_dir = run_dir.parents[2]
        relative_plot_dir = Path(
            outputs.get("learning_curves_dir", "plots/learning_curves")
        )
        plot_format = str(outputs.get("final_learning_curve_format", "svg")).lower()
        if plot_format not in {"svg", "png", "pdf"}:
            raise ValueError(
                "outputs.final_learning_curve_format debe ser svg, png o pdf."
            )
        plot_path = (
            output_dir
            / relative_plot_dir
            / run_dir.parent.name
            / f"{run_dir.name}.{plot_format}"
        )
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        save_kwargs: dict[str, Any] = {
            "format": plot_format,
            "bbox_inches": "tight",
        }
        if plot_format == "png":
            save_kwargs["dpi"] = int(outputs.get("learning_curve_dpi", 180))
        figure.savefig(plot_path, **save_kwargs)
        LOGGER.info("Curva de aprendizaje final guardada: %s", plot_path)
    except Exception as error:
        LOGGER.warning(
            "No se pudo generar la curva de aprendizaje final; el entrenamiento "
            "y los checkpoints continúan. Error=%s",
            error,
        )
    finally:
        if figure is not None and pyplot is not None:
            pyplot.close(figure)


def balanced_class_weights(torch: Any, y_train: np.ndarray, n_classes: int, device: Any):
    observed = np.unique(y_train)
    weights_observed = compute_class_weight(class_weight="balanced", classes=observed, y=y_train)
    weights = np.zeros(n_classes, dtype=np.float32)
    weights[observed] = weights_observed.astype(np.float32)
    return torch.as_tensor(weights, dtype=torch.float32, device=device), weights


def make_loader(
    torch: Any,
    DataLoader: Any,
    TensorDataset: Any,
    X: np.ndarray,
    y: np.ndarray,
    batch_size: int,
    shuffle: bool,
    generator: Any,
    num_workers: int,
    pin_memory: bool,
):
    dataset = TensorDataset(
        torch.from_numpy(np.ascontiguousarray(X, dtype=np.float32)),
        torch.from_numpy(np.ascontiguousarray(y, dtype=np.int64)),
    )
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        generator=generator if shuffle else None,
        num_workers=num_workers,
        pin_memory=pin_memory,
        persistent_workers=bool(num_workers > 0),
    )


def atomic_torch_save(torch: Any, payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, path)


def torch_load(torch: Any, path: Path, device: Any) -> dict[str, Any]:
    try:
        return torch.load(path, map_location=device, weights_only=False)
    except TypeError:
        return torch.load(path, map_location=device)


def checkpoint_payload(
    torch: Any,
    model: Any,
    optimizer: Any,
    epoch: int,
    signature: dict[str, Any],
    loader_generator: Any,
) -> dict[str, Any]:
    payload = {
        "epoch": int(epoch),
        "signature": signature,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "python_random_state": random.getstate(),
        "numpy_random_state": np.random.get_state(),
        "torch_rng_state": torch.get_rng_state(),
        "loader_generator_state": loader_generator.get_state(),
    }
    if torch.cuda.is_available():
        payload["torch_cuda_rng_state_all"] = torch.cuda.get_rng_state_all()
    return payload


def restore_checkpoint(
    torch: Any,
    checkpoint: dict[str, Any],
    model: Any,
    optimizer: Any,
    expected_signature: dict[str, Any],
    loader_generator: Any,
) -> int:
    if checkpoint.get("signature") != expected_signature:
        raise ValueError("El checkpoint no corresponde al fold/configuración actual.")
    model.load_state_dict(checkpoint["model_state_dict"])
    optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
    random.setstate(checkpoint["python_random_state"])
    np.random.set_state(checkpoint["numpy_random_state"])
    # ``map_location=device`` también mueve estos estados a CUDA. Tanto el
    # generador global de CPU como el generador del DataLoader exigen aquí un
    # torch.ByteTensor residente en CPU.
    torch.set_rng_state(checkpoint["torch_rng_state"].detach().cpu())
    loader_generator.set_state(
        checkpoint["loader_generator_state"].detach().cpu()
    )
    if torch.cuda.is_available() and "torch_cuda_rng_state_all" in checkpoint:
        torch.cuda.set_rng_state_all(
            [state.detach().cpu() for state in checkpoint["torch_cuda_rng_state_all"]]
        )
    return int(checkpoint["epoch"])


def train_trajectory(
    torch: Any,
    nn: Any,
    DataLoader: Any,
    TensorDataset: Any,
    X_train: np.ndarray,
    y_train: np.ndarray,
    input_dim: int,
    n_classes: int,
    optimizer_name: str,
    learning_rate: float,
    dropout: float,
    fold_id: str,
    run_dir: Path,
    config: dict[str, Any],
    device: Any,
    seed: int,
    X_validation: np.ndarray | None = None,
    y_validation: np.ndarray | None = None,
    render_learning_curve: bool = False,
) -> None:
    training = config["training"]
    max_epochs = int(training["max_epochs"])
    milestones = sorted({int(value) for value in training["evaluation_epochs"]})
    if max(milestones) > max_epochs:
        raise ValueError("evaluation_epochs no puede superar max_epochs.")
    if min(milestones) < 1:
        raise ValueError("evaluation_epochs debe contener épocas positivas.")
    checkpoint_every = int(training.get("checkpoint_every_n_epochs", 10))
    resume = bool(training.get("resume", True))

    seed_everything(torch, seed, bool(training.get("deterministic", True)))
    model = make_model(nn, input_dim, n_classes, config, dropout).to(device)
    optimizer = make_optimizer(torch, model, config, optimizer_name, learning_rate)
    weights_tensor, weights_array = balanced_class_weights(torch, y_train, n_classes, device)
    criterion = nn.CrossEntropyLoss(weight=weights_tensor)
    loader_generator = torch.Generator()
    loader_generator.manual_seed(seed)
    batch_size = int(training.get("batch_size", 256))
    num_workers = int(config.get("runtime", {}).get("num_workers", 0))
    pin_memory = bool(config.get("runtime", {}).get("pin_memory", device.type == "cuda"))
    loader = make_loader(
        torch,
        DataLoader,
        TensorDataset,
        X_train,
        y_train,
        batch_size,
        True,
        loader_generator,
        num_workers,
        pin_memory,
    )
    signature = {
        "fold_id": str(fold_id),
        "optimizer": str(optimizer_name).lower(),
        "learning_rate": float(learning_rate),
        "dropout": float(dropout),
        "hidden_units": [int(value) for value in config["model"]["hidden_units"]],
        "activation": str(config["model"].get("activation", "tanh")),
        "input_dim": int(input_dim),
        "n_classes": int(n_classes),
        "seed": int(seed),
    }
    resume_path = run_dir / "resume" / "latest.pt"
    start_epoch = 0
    if resume and resume_path.exists():
        checkpoint = torch_load(torch, resume_path, device)
        start_epoch = restore_checkpoint(
            torch, checkpoint, model, optimizer, signature, loader_generator
        )
        if start_epoch > max_epochs:
            raise ValueError(
                f"El checkpoint está en la época {start_epoch}, superior al nuevo "
                f"max_epochs={max_epochs}. Desactive resume o retire el checkpoint "
                f"de esta ejecución: {resume_path}"
            )
        LOGGER.info("Reanudando %s desde época %s", run_dir, start_epoch)

    missing_milestones = [
        epoch for epoch in milestones if not (run_dir / f"epoch_{epoch:04d}.pt").exists()
    ]
    if not missing_milestones and start_epoch >= max_epochs:
        return

    history_path = run_dir / "learning_history.csv"
    history_rows = (
        pd.read_csv(history_path).to_dict("records")
        if start_epoch > 0 and history_path.exists()
        else []
    )
    history_rows = [row for row in history_rows if int(row["epoch"]) <= start_epoch]

    gradient_clip = training.get("gradient_clip_norm")
    for epoch in range(start_epoch + 1, max_epochs + 1):
        model.train()
        total_loss = 0.0
        total_rows = 0
        for X_batch, y_batch in loader:
            X_batch = X_batch.to(device, non_blocking=pin_memory)
            y_batch = y_batch.to(device, non_blocking=pin_memory)
            optimizer.zero_grad(set_to_none=True)
            logits = model(X_batch)
            loss = criterion(logits, y_batch)
            loss.backward()
            if gradient_clip is not None:
                torch.nn.utils.clip_grad_norm_(model.parameters(), float(gradient_clip))
            optimizer.step()
            rows = int(y_batch.shape[0])
            total_loss += float(loss.detach().cpu()) * rows
            total_rows += rows

        mean_training_loss = total_loss / max(total_rows, 1)
        validation_loss = np.nan
        validation_f1 = np.nan
        if X_validation is not None and y_validation is not None:
            validation_loss, validation_f1 = validation_epoch_metrics(
                torch, DataLoader, TensorDataset, model, criterion,
                X_validation, y_validation,
                int(training.get("prediction_batch_size", 4096)), device,
            )
        history_rows.append({
            "epoch": epoch,
            "training_loss": mean_training_loss,
            "validation_loss": validation_loss,
            "validation_f1_macro": validation_f1,
        })
        history = pd.DataFrame(history_rows)
        log_every = max(1, int(training.get("log_every_n_epochs", 10)))
        save_learning_curve(
            history,
            run_dir,
            config,
            render_plot=bool(render_learning_curve and epoch == max_epochs),
        )

        payload = checkpoint_payload(
            torch, model, optimizer, epoch, signature, loader_generator
        )
        if epoch in milestones:
            payload["class_weights"] = weights_array
            payload["mean_training_loss"] = mean_training_loss
            atomic_torch_save(torch, payload, run_dir / f"epoch_{epoch:04d}.pt")
        if checkpoint_every > 0 and (epoch % checkpoint_every == 0 or epoch == max_epochs):
            atomic_torch_save(torch, payload, resume_path)
        if epoch == 1 or epoch % log_every == 0:
            LOGGER.info(
                "%s | epoch=%s/%s | loss=%.6f",
                run_dir.name,
                epoch,
                max_epochs,
                mean_training_loss,
            )


def predict_arrays(
    torch: Any,
    DataLoader: Any,
    TensorDataset: Any,
    model: Any,
    X: np.ndarray,
    batch_size: int,
    device: Any,
) -> tuple[np.ndarray, np.ndarray]:
    dummy_y = np.zeros(len(X), dtype=np.int64)
    loader = make_loader(
        torch,
        DataLoader,
        TensorDataset,
        X,
        dummy_y,
        batch_size,
        False,
        None,
        0,
        bool(device.type == "cuda"),
    )
    predictions: list[np.ndarray] = []
    probabilities: list[np.ndarray] = []
    model.eval()
    with torch.no_grad():
        for X_batch, _ in loader:
            logits = model(X_batch.to(device, non_blocking=device.type == "cuda"))
            probs = torch.softmax(logits, dim=1)
            probabilities.append(probs.cpu().numpy())
            predictions.append(torch.argmax(probs, dim=1).cpu().numpy())
    return np.concatenate(predictions), np.concatenate(probabilities)


def load_model_at_checkpoint(
    torch: Any,
    nn: Any,
    checkpoint_path: Path,
    input_dim: int,
    n_classes: int,
    config: dict[str, Any],
    dropout: float,
    device: Any,
):
    model = make_model(nn, input_dim, n_classes, config, dropout).to(device)
    checkpoint = torch_load(torch, checkpoint_path, device)
    model.load_state_dict(checkpoint["model_state_dict"])
    return model, checkpoint


def metric_row(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "f1_weighted": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
        "kappa": float(cohen_kappa_score(y_true, y_pred)),
    }


def config_id(optimizer_name: str, learning_rate: float, dropout: float) -> str:
    lr_text = f"{learning_rate:.8g}".replace(".", "p")
    dropout_text = f"{dropout:.4g}".replace(".", "p")
    return f"opt_{optimizer_name.lower()}__lr_{lr_text}__dropout_{dropout_text}"


def run_spatial_search(
    torch: Any,
    nn: Any,
    DataLoader: Any,
    TensorDataset: Any,
    data: PreparedData,
    fold_ids: list[int],
    config: dict[str, Any],
    output_dir: Path,
    device: Any,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    search_cfg = config["search"]
    optimizers = [str(value).lower() for value in search_cfg.get("optimizers", ["adamw"])]
    learning_rates = [float(value) for value in search_cfg["learning_rates"]]
    dropouts = [float(value) for value in search_cfg["dropouts"]]
    milestones = sorted({int(value) for value in config["training"]["evaluation_epochs"]})
    base_seed = int(config["training"].get("random_state", 42))
    metric_rows: list[dict[str, Any]] = []
    input_dim = data.X.shape[1]
    n_classes = len(data.classes)

    for fold_position, fold_id in enumerate(fold_ids, start=1):
        train_idx = data.indices[f"fold_{fold_id}_train"]
        val_idx = data.indices[f"fold_{fold_id}_validation"]
        preprocessor_path = output_dir / "preprocessing" / f"fold_{fold_id:02d}.joblib"
        X_train, X_val, _ = fit_transform_fold(
            data, train_idx, val_idx, config, preprocessor_path
        )
        y_train = data.y[train_idx]
        y_val = data.y[val_idx]

        for trajectory_position, (optimizer_name, learning_rate, dropout) in enumerate(
            itertools.product(optimizers, learning_rates, dropouts), start=1
        ):
            current_id = config_id(optimizer_name, learning_rate, dropout)
            run_dir = output_dir / "checkpoints" / current_id / f"fold_{fold_id:02d}"
            seed = base_seed + fold_position * 10_000 + trajectory_position
            LOGGER.info(
                "Entrenando fold=%s | optimizer=%s | lr=%s | dropout=%s | device=%s",
                fold_id,
                optimizer_name,
                learning_rate,
                dropout,
                device,
            )
            train_trajectory(
                torch,
                nn,
                DataLoader,
                TensorDataset,
                X_train,
                y_train,
                input_dim,
                n_classes,
                optimizer_name,
                learning_rate,
                dropout,
                str(fold_id),
                run_dir,
                config,
                device,
                seed,
                X_val,
                y_val,
            )
            for epoch in milestones:
                checkpoint_path = run_dir / f"epoch_{epoch:04d}.pt"
                if not checkpoint_path.exists():
                    raise FileNotFoundError(f"No se generó el checkpoint: {checkpoint_path}")
                model, checkpoint = load_model_at_checkpoint(
                    torch,
                    nn,
                    checkpoint_path,
                    input_dim,
                    n_classes,
                    config,
                    dropout,
                    device,
                )
                train_pred, _ = predict_arrays(
                    torch,
                    DataLoader,
                    TensorDataset,
                    model,
                    X_train,
                    int(config["training"].get("prediction_batch_size", 4096)),
                    device,
                )
                val_pred, _ = predict_arrays(
                    torch,
                    DataLoader,
                    TensorDataset,
                    model,
                    X_val,
                    int(config["training"].get("prediction_batch_size", 4096)),
                    device,
                )
                row: dict[str, Any] = {
                    "config_id": current_id,
                    "fold_id": fold_id,
                    "optimizer": optimizer_name,
                    "learning_rate": learning_rate,
                    "dropout": dropout,
                    "epochs": epoch,
                    "n_train": len(train_idx),
                    "n_validation": len(val_idx),
                    "training_loss_at_checkpoint": checkpoint.get("mean_training_loss"),
                }
                row.update({f"train_{key}": value for key, value in metric_row(y_train, train_pred).items()})
                row.update({f"validation_{key}": value for key, value in metric_row(y_val, val_pred).items()})
                metric_rows.append(row)
                del model
                if device.type == "cuda":
                    torch.cuda.empty_cache()

    fold_results = pd.DataFrame(metric_rows)
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    fold_results.to_csv(tables_dir / "dnn_search_fold_results.csv", index=False, encoding="utf-8-sig")

    metric_columns = ["accuracy", "balanced_accuracy", "f1_macro", "f1_weighted", "kappa"]
    aggregations: dict[str, list[str]] = {}
    for prefix in ["train", "validation"]:
        for metric in metric_columns:
            aggregations[f"{prefix}_{metric}"] = ["mean", "std"]
    summary = (
        fold_results.groupby(
            ["config_id", "optimizer", "learning_rate", "dropout", "epochs"], as_index=False
        )
        .agg(aggregations)
    )
    summary.columns = [
        "_".join(str(part) for part in column if str(part))
        if isinstance(column, tuple)
        else str(column)
        for column in summary.columns
    ]
    refit = str(search_cfg.get("refit", "f1_macro"))
    selection_column = f"validation_{refit}_mean"
    if selection_column not in summary.columns:
        raise ValueError(f"Métrica refit no soportada: {refit}")
    summary = summary.sort_values(
        [selection_column, "validation_balanced_accuracy_mean", "validation_accuracy_mean"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))
    summary.to_csv(tables_dir / "dnn_search_summary.csv", index=False, encoding="utf-8-sig")
    best = {
        "config_id": str(summary.loc[0, "config_id"]),
        "optimizer": str(summary.loc[0, "optimizer"]),
        "learning_rate": float(summary.loc[0, "learning_rate"]),
        "dropout": float(summary.loc[0, "dropout"]),
        "epochs": int(summary.loc[0, "epochs"]),
        "refit": refit,
        "mean_validation_score": float(summary.loc[0, selection_column]),
    }
    (output_dir / "metadata").mkdir(parents=True, exist_ok=True)
    (output_dir / "metadata" / "best_hyperparameters.json").write_text(
        json.dumps(best, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return fold_results, summary, best


def class_metrics_table(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    classes: list[dict[str, Any]],
    evaluation: str,
) -> pd.DataFrame:
    labels = np.arange(len(classes), dtype=np.int64)
    report = classification_report(
        y_true,
        y_pred,
        labels=labels,
        output_dict=True,
        zero_division=0,
    )
    rows = []
    for class_info in classes:
        encoded = int(class_info["encoded_class"])
        metrics = report[str(encoded)]
        rows.append(
            {
                "evaluation": evaluation,
                **class_info,
                "precision": float(metrics["precision"]),
                "recall": float(metrics["recall"]),
                "f1_score": float(metrics["f1-score"]),
                "support": int(metrics["support"]),
            }
        )
    return pd.DataFrame(rows)


def confusion_table(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    classes: list[dict[str, Any]],
    evaluation: str,
) -> pd.DataFrame:
    labels = np.arange(len(classes), dtype=np.int64)
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    rows = []
    for real_index, real_info in enumerate(classes):
        for predicted_index, predicted_info in enumerate(classes):
            rows.append(
                {
                    "evaluation": evaluation,
                    "true_encoded_class": real_index,
                    "true_original_class": real_info["original_class"],
                    "predicted_encoded_class": predicted_index,
                    "predicted_original_class": predicted_info["original_class"],
                    "n": int(matrix[real_index, predicted_index]),
                }
            )
    return pd.DataFrame(rows)


def class_error_table(
    class_metrics: pd.DataFrame,
    confusion: pd.DataFrame,
) -> pd.DataFrame:
    """Resume errores de omisión y comisión para cada clase homologada."""
    metric_fields = {
        "evaluation",
        "encoded_class",
        "original_class",
        "class_label",
        "precision",
        "recall",
        "f1_score",
        "support",
    }
    confusion_fields = {
        "evaluation",
        "true_encoded_class",
        "predicted_encoded_class",
        "n",
    }
    missing_metrics = sorted(metric_fields - set(class_metrics.columns))
    missing_confusion = sorted(confusion_fields - set(confusion.columns))
    if missing_metrics or missing_confusion:
        raise ValueError(
            "No se pueden calcular errores por clase. "
            f"Faltan en class_metrics={missing_metrics}; "
            f"faltan en confusion={missing_confusion}."
        )

    matrix = confusion.copy()
    matrix["true_encoded_class"] = pd.to_numeric(
        matrix["true_encoded_class"], errors="raise"
    ).astype(int)
    matrix["predicted_encoded_class"] = pd.to_numeric(
        matrix["predicted_encoded_class"], errors="raise"
    ).astype(int)
    matrix["n"] = pd.to_numeric(matrix["n"], errors="raise").astype(int)

    rows: list[dict[str, Any]] = []
    for _, class_row in class_metrics.iterrows():
        encoded = int(class_row["encoded_class"])
        true_rows = matrix[matrix["true_encoded_class"] == encoded]
        predicted_rows = matrix[matrix["predicted_encoded_class"] == encoded]
        support_real = int(true_rows["n"].sum())
        predicted_total = int(predicted_rows["n"].sum())
        true_positive = int(
            true_rows.loc[
                true_rows["predicted_encoded_class"] == encoded,
                "n",
            ].sum()
        )
        reported_support = int(class_row["support"])
        if reported_support != support_real:
            raise ValueError(
                f"Soporte inconsistente para encoded_class={encoded}: "
                f"class_metrics={reported_support}, confusion={support_real}."
            )

        false_negatives = support_real - true_positive
        false_positives = predicted_total - true_positive
        omission_error_rate = (
            false_negatives / support_real if support_real else np.nan
        )
        commission_error_rate = (
            false_positives / predicted_total if predicted_total else np.nan
        )
        rows.append(
            {
                "evaluation": class_row["evaluation"],
                "encoded_class": encoded,
                "original_class": class_row["original_class"],
                "class_label": class_row["class_label"],
                "support_real": support_real,
                "correct": true_positive,
                "false_negatives": false_negatives,
                "omission_error_rate": float(omission_error_rate),
                "predicted_total": predicted_total,
                "false_positives": false_positives,
                "commission_error_rate": float(commission_error_rate),
                "precision": float(class_row["precision"]),
                "recall": float(class_row["recall"]),
                "f1_score": float(class_row["f1_score"]),
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["omission_error_rate", "commission_error_rate", "support_real"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)


def write_prediction_table(
    path: Path,
    data: PreparedData,
    indices: np.ndarray,
    predictions: np.ndarray,
    probabilities: np.ndarray,
    evaluation: str,
) -> None:
    original_by_encoded = {
        int(item["encoded_class"]): str(item["original_class"]) for item in data.classes
    }
    table = data.sample_index.iloc[indices].copy().reset_index(drop=True)
    table["evaluation"] = evaluation
    table["predicted_encoded_class"] = predictions
    table["predicted_original_class"] = [original_by_encoded[int(value)] for value in predictions]
    table["predicted_probability"] = probabilities.max(axis=1)
    for class_info in data.classes:
        encoded = int(class_info["encoded_class"])
        table[f"prob_class_{class_info['original_class']}"] = probabilities[:, encoded]
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False, encoding="utf-8-sig")


def evaluate_best_oof(
    torch: Any,
    nn: Any,
    DataLoader: Any,
    TensorDataset: Any,
    data: PreparedData,
    fold_ids: list[int],
    best: dict[str, Any],
    config: dict[str, Any],
    output_dir: Path,
    device: Any,
) -> dict[str, pd.DataFrame]:
    oof_pred = np.full(len(data.y), -1, dtype=np.int64)
    oof_prob = np.full((len(data.y), len(data.classes)), np.nan, dtype=np.float32)
    fold_metric_rows = []
    for fold_id in fold_ids:
        val_idx = data.indices[f"fold_{fold_id}_validation"]
        preprocessor = joblib.load(output_dir / "preprocessing" / f"fold_{fold_id:02d}.joblib")
        X_val = preprocessor.transform(data.X[val_idx]).astype(np.float32, copy=False)
        checkpoint_path = (
            output_dir
            / "checkpoints"
            / best["config_id"]
            / f"fold_{fold_id:02d}"
            / f"epoch_{int(best['epochs']):04d}.pt"
        )
        model, _ = load_model_at_checkpoint(
            torch,
            nn,
            checkpoint_path,
            data.X.shape[1],
            len(data.classes),
            config,
            float(best["dropout"]),
            device,
        )
        pred, prob = predict_arrays(
            torch,
            DataLoader,
            TensorDataset,
            model,
            X_val,
            int(config["training"].get("prediction_batch_size", 4096)),
            device,
        )
        oof_pred[val_idx] = pred
        oof_prob[val_idx] = prob
        fold_metric_rows.append(
            {"fold_id": fold_id, "n_rows": len(val_idx), **metric_row(data.y[val_idx], pred)}
        )

    development = data.indices["development_indices"]
    if np.any(oof_pred[development] < 0):
        raise RuntimeError("No se generaron predicciones OOF para todo el desarrollo.")
    overall = pd.DataFrame(
        [{"evaluation": "development_oof", "n_rows": len(development), **metric_row(data.y[development], oof_pred[development])}]
    )
    fold_metrics = pd.DataFrame(fold_metric_rows)
    class_metrics = class_metrics_table(
        data.y[development], oof_pred[development], data.classes, "development_oof"
    )
    confusion = confusion_table(
        data.y[development], oof_pred[development], data.classes, "development_oof"
    )
    tables = output_dir / "tables"
    overall.to_csv(tables / "dnn_cv_overall_metrics.csv", index=False, encoding="utf-8-sig")
    fold_metrics.to_csv(tables / "dnn_cv_fold_metrics.csv", index=False, encoding="utf-8-sig")
    class_metrics.to_csv(tables / "dnn_cv_class_metrics.csv", index=False, encoding="utf-8-sig")
    confusion.to_csv(tables / "dnn_cv_confusion_matrix.csv", index=False, encoding="utf-8-sig")
    write_prediction_table(
        tables / "dnn_cv_oof_predictions.csv",
        data,
        development,
        oof_pred[development],
        oof_prob[development],
        "development_oof",
    )
    return {
        "overall": overall,
        "fold_metrics": fold_metrics,
        "class_metrics": class_metrics,
        "confusion": confusion,
    }


def train_final_development_model(
    torch: Any,
    nn: Any,
    DataLoader: Any,
    TensorDataset: Any,
    data: PreparedData,
    best: dict[str, Any],
    config: dict[str, Any],
    output_dir: Path,
    device: Any,
) -> dict[str, pd.DataFrame]:
    development = data.indices["development_indices"]
    independent = data.indices["independent_indices"]
    preprocessor = build_preprocessor(config)
    X_dev = preprocessor.fit_transform(data.X[development]).astype(np.float32, copy=False)
    X_ind = preprocessor.transform(data.X[independent]).astype(np.float32, copy=False)
    models_dir = output_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(preprocessor, models_dir / "development_preprocessor.joblib")

    final_config = json.loads(json.dumps(config))
    final_config["training"]["max_epochs"] = int(best["epochs"])
    final_config["training"]["evaluation_epochs"] = [int(best["epochs"])]
    final_run = output_dir / "checkpoints" / "final_development" / str(best["config_id"])
    seed = int(config["training"].get("random_state", 42))
    train_trajectory(
        torch,
        nn,
        DataLoader,
        TensorDataset,
        X_dev,
        data.y[development],
        data.X.shape[1],
        len(data.classes),
        str(best["optimizer"]),
        float(best["learning_rate"]),
        float(best["dropout"]),
        "final_development",
        final_run,
        final_config,
        device,
        seed,
        render_learning_curve=True,
    )
    checkpoint_path = final_run / f"epoch_{int(best['epochs']):04d}.pt"
    model, checkpoint = load_model_at_checkpoint(
        torch,
        nn,
        checkpoint_path,
        data.X.shape[1],
        len(data.classes),
        config,
        float(best["dropout"]),
        device,
    )
    batch_size = int(config["training"].get("prediction_batch_size", 4096))
    dev_pred, dev_prob = predict_arrays(
        torch, DataLoader, TensorDataset, model, X_dev, batch_size, device
    )
    # Primera y única consulta al holdout independiente durante esta ejecución.
    ind_pred, ind_prob = predict_arrays(
        torch, DataLoader, TensorDataset, model, X_ind, batch_size, device
    )

    model_artifact = {
        "model_state_dict": checkpoint["model_state_dict"],
        "input_dim": int(data.X.shape[1]),
        "n_classes": int(len(data.classes)),
        "hidden_units": [int(value) for value in config["model"]["hidden_units"]],
        "activation": str(config["model"].get("activation", "tanh")),
        "dropout": float(best["dropout"]),
        "optimizer": str(best["optimizer"]),
        "learning_rate": float(best["learning_rate"]),
        "epochs": int(best["epochs"]),
        "feature_columns": data.features,
        "class_mapping": data.classes,
        "trained_on": "development_only",
    }
    atomic_torch_save(torch, model_artifact, models_dir / "dnn_best_development.pt")
    atomic_torch_save(
        torch,
        {"model_state_dict": checkpoint["model_state_dict"]},
        models_dir / "dnn_best_development_weights.pt",
    )

    tables = output_dir / "tables"
    training_metrics = pd.DataFrame(
        [{"evaluation": "development_training", "n_rows": len(development), **metric_row(data.y[development], dev_pred)}]
    )
    independent_metrics = pd.DataFrame(
        [{"evaluation": "independent_validation", "n_rows": len(independent), **metric_row(data.y[independent], ind_pred)}]
    )
    training_class = class_metrics_table(
        data.y[development], dev_pred, data.classes, "development_training"
    )
    independent_class = class_metrics_table(
        data.y[independent], ind_pred, data.classes, "independent_validation"
    )
    training_confusion = confusion_table(
        data.y[development], dev_pred, data.classes, "development_training"
    )
    independent_confusion = confusion_table(
        data.y[independent], ind_pred, data.classes, "independent_validation"
    )
    training_metrics.to_csv(tables / "dnn_training_metrics.csv", index=False, encoding="utf-8-sig")
    independent_metrics.to_csv(tables / "dnn_independent_metrics.csv", index=False, encoding="utf-8-sig")
    training_class.to_csv(tables / "dnn_training_class_metrics.csv", index=False, encoding="utf-8-sig")
    independent_class.to_csv(tables / "dnn_independent_class_metrics.csv", index=False, encoding="utf-8-sig")
    training_confusion.to_csv(tables / "dnn_training_confusion_matrix.csv", index=False, encoding="utf-8-sig")
    independent_confusion.to_csv(tables / "dnn_independent_confusion_matrix.csv", index=False, encoding="utf-8-sig")
    write_prediction_table(
        tables / "dnn_independent_predictions.csv",
        data,
        independent,
        ind_pred,
        ind_prob,
        "independent_validation",
    )
    return {
        "training_metrics": training_metrics,
        "independent_metrics": independent_metrics,
        "training_class": training_class,
        "independent_class": independent_class,
        "training_confusion": training_confusion,
        "independent_confusion": independent_confusion,
    }


def train_optional_all_modelable(
    torch: Any,
    nn: Any,
    DataLoader: Any,
    TensorDataset: Any,
    data: PreparedData,
    best: dict[str, Any],
    config: dict[str, Any],
    output_dir: Path,
    device: Any,
) -> None:
    if not bool(config.get("outputs", {}).get("train_model_on_all_modelable_after_evaluation", False)):
        return
    all_indices = np.arange(len(data.y), dtype=np.int64)
    preprocessor = build_preprocessor(config)
    X_all = preprocessor.fit_transform(data.X[all_indices]).astype(np.float32, copy=False)
    models_dir = output_dir / "models"
    joblib.dump(preprocessor, models_dir / "all_modelable_preprocessor.joblib")
    final_config = json.loads(json.dumps(config))
    final_config["training"]["max_epochs"] = int(best["epochs"])
    final_config["training"]["evaluation_epochs"] = [int(best["epochs"])]
    run_dir = output_dir / "checkpoints" / "final_all_modelable" / str(best["config_id"])
    train_trajectory(
        torch,
        nn,
        DataLoader,
        TensorDataset,
        X_all,
        data.y,
        data.X.shape[1],
        len(data.classes),
        str(best["optimizer"]),
        float(best["learning_rate"]),
        float(best["dropout"]),
        "final_all_modelable",
        run_dir,
        final_config,
        device,
        int(config["training"].get("random_state", 42)),
    )
    checkpoint = torch_load(
        torch,
        run_dir / f"epoch_{int(best['epochs']):04d}.pt",
        device,
    )
    artifact = {
        "model_state_dict": checkpoint["model_state_dict"],
        "input_dim": int(data.X.shape[1]),
        "n_classes": int(len(data.classes)),
        "hidden_units": [int(value) for value in config["model"]["hidden_units"]],
        "activation": str(config["model"].get("activation", "tanh")),
        "dropout": float(best["dropout"]),
        "optimizer": str(best["optimizer"]),
        "learning_rate": float(best["learning_rate"]),
        "epochs": int(best["epochs"]),
        "feature_columns": data.features,
        "class_mapping": data.classes,
        "trained_on": "all_modelable_after_independent_evaluation",
    }
    atomic_torch_save(torch, artifact, models_dir / "dnn_best_all_modelable.pt")


def dataframe_to_markdown(dataframe: pd.DataFrame) -> str:
    if dataframe.empty:
        return "_Sin datos._"

    def format_cell(value: Any) -> str:
        try:
            is_missing = bool(pd.isna(value))
        except (TypeError, ValueError):
            is_missing = False
        if is_missing:
            return ""
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.6f}"
        return str(value).replace("|", r"\|").replace("\r\n", "<br>").replace("\n", "<br>")

    headers = [format_cell(column) for column in dataframe.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in dataframe.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(format_cell(value) for value in row) + " |")
    return "\n".join(lines)


def write_report(
    data: PreparedData,
    fold_ids: list[int],
    best: dict[str, Any],
    search_summary: pd.DataFrame,
    oof: dict[str, pd.DataFrame],
    final: dict[str, pd.DataFrame],
    config: dict[str, Any],
    output_dir: Path,
    device: Any,
) -> None:
    report_path = output_dir / config.get("outputs", {}).get(
        "report_md", "reports/a4_8_dnn_pytorch_spatial_validation_report.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    architecture = " → ".join(str(value) for value in config["model"]["hidden_units"])
    cv_class_errors = class_error_table(oof["class_metrics"], oof["confusion"])
    training_class_errors = class_error_table(
        final["training_class"],
        final["training_confusion"],
    )
    independent_class_errors = class_error_table(
        final["independent_class"],
        final["independent_confusion"],
    )
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    cv_class_errors.to_csv(
        tables_dir / "dnn_cv_class_errors.csv",
        index=False,
        encoding="utf-8-sig",
    )
    training_class_errors.to_csv(
        tables_dir / "dnn_training_class_errors.csv",
        index=False,
        encoding="utf-8-sig",
    )
    independent_class_errors.to_csv(
        tables_dir / "dnn_independent_class_errors.csv",
        index=False,
        encoding="utf-8-sig",
    )
    error_report_fields = [
        "original_class",
        "class_label",
        "support_real",
        "correct",
        "false_negatives",
        "omission_error_rate",
        "predicted_total",
        "false_positives",
        "commission_error_rate",
        "f1_score",
    ]
    lines = [
        "# A4.8 — DNN PyTorch con validación espacial",
        "",
        "## Diseño",
        "",
        "La DNN reutiliza las filas, folds por cuadrantes y validación independiente congelados por el RF.",
        "La validación independiente no interviene en la búsqueda de hiperparámetros ni en la selección de épocas.",
        "La imputación y estandarización se ajustan exclusivamente con el entrenamiento de cada fold.",
        "",
        "## Configuración",
        "",
        f"- Dispositivo: `{device}`",
        f"- Predictores: **{len(data.features):,}**",
        f"- Clases: **{len(data.classes):,}**",
        f"- Folds: **{len(fold_ids):,}**",
        f"- Capas ocultas: **{architecture}**",
        f"- Activación oculta: **{config['model'].get('activation', 'tanh')}**",
        f"- Mejor configuración: `{json.dumps(best, ensure_ascii=False)}`",
        "",
        "## Mejores resultados de búsqueda",
        "",
        dataframe_to_markdown(search_summary.head(10)),
        "",
        "## Validación cruzada OOF de diagnóstico",
        "",
        dataframe_to_markdown(oof["overall"]),
        "",
        "### Errores por clase en validación OOF",
        "",
        "`false_negatives` y `omission_error_rate` indican clases reales no detectadas; `false_positives` y `commission_error_rate` indican asignaciones incorrectas hacia la clase.",
        "",
        dataframe_to_markdown(cv_class_errors[error_report_fields]),
        "",
        "## Entrenamiento sobre desarrollo",
        "",
        "Estas métricas son diagnósticas y no estiman generalización.",
        "",
        dataframe_to_markdown(final["training_metrics"]),
        "",
        "### Errores por clase en entrenamiento",
        "",
        dataframe_to_markdown(training_class_errors[error_report_fields]),
        "",
        "## Validación independiente",
        "",
        dataframe_to_markdown(final["independent_metrics"]),
        "",
        "### Errores por clase en validación independiente",
        "",
        dataframe_to_markdown(independent_class_errors[error_report_fields]),
        "",
        "## Nota",
        "",
        "Los logits de salida se entrenan con entropía cruzada ponderada. `softmax` se aplica únicamente para producir probabilidades.",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")


def copy_reproducibility_metadata(
    config_path: Path,
    data: PreparedData,
    best: dict[str, Any],
    output_dir: Path,
) -> None:
    metadata = output_dir / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, metadata / "training_config_used.yaml")
    (metadata / "feature_columns.txt").write_text(
        "\n".join(data.features) + "\n", encoding="utf-8"
    )
    (metadata / "class_mapping.json").write_text(
        json.dumps(data.classes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    run_metadata = {
        "prepared_manifest": data.manifest,
        "best_hyperparameters": best,
    }
    (metadata / "training_metadata.json").write_text(
        json.dumps(run_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_existing_report_results(
    output_dir: Path,
) -> tuple[
    pd.DataFrame,
    dict[str, Any],
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
]:
    """Carga resultados terminados para regenerar el reporte sin entrenar."""
    tables = output_dir / "tables"
    metadata = output_dir / "metadata"
    paths = {
        "search_summary": tables / "dnn_search_summary.csv",
        "best": metadata / "best_hyperparameters.json",
        "cv_overall": tables / "dnn_cv_overall_metrics.csv",
        "cv_fold_metrics": tables / "dnn_cv_fold_metrics.csv",
        "cv_class_metrics": tables / "dnn_cv_class_metrics.csv",
        "cv_confusion": tables / "dnn_cv_confusion_matrix.csv",
        "training_metrics": tables / "dnn_training_metrics.csv",
        "independent_metrics": tables / "dnn_independent_metrics.csv",
        "training_class": tables / "dnn_training_class_metrics.csv",
        "independent_class": tables / "dnn_independent_class_metrics.csv",
        "training_confusion": tables / "dnn_training_confusion_matrix.csv",
        "independent_confusion": tables / "dnn_independent_confusion_matrix.csv",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "No se puede regenerar el reporte sin entrenamiento; faltan resultados: "
            f"{missing}"
        )

    search_summary = pd.read_csv(paths["search_summary"], encoding="utf-8-sig")
    best = json.loads(paths["best"].read_text(encoding="utf-8"))
    oof = {
        "overall": pd.read_csv(paths["cv_overall"], encoding="utf-8-sig"),
        "fold_metrics": pd.read_csv(paths["cv_fold_metrics"], encoding="utf-8-sig"),
        "class_metrics": pd.read_csv(paths["cv_class_metrics"], encoding="utf-8-sig"),
        "confusion": pd.read_csv(paths["cv_confusion"], encoding="utf-8-sig"),
    }
    final = {
        "training_metrics": pd.read_csv(paths["training_metrics"], encoding="utf-8-sig"),
        "independent_metrics": pd.read_csv(paths["independent_metrics"], encoding="utf-8-sig"),
        "training_class": pd.read_csv(paths["training_class"], encoding="utf-8-sig"),
        "independent_class": pd.read_csv(paths["independent_class"], encoding="utf-8-sig"),
        "training_confusion": pd.read_csv(paths["training_confusion"], encoding="utf-8-sig"),
        "independent_confusion": pd.read_csv(paths["independent_confusion"], encoding="utf-8-sig"),
    }
    return search_summary, best, oof, final


def main() -> None:
    args = parse_args()
    config_path = args.config.resolve()
    config = read_yaml(config_path)
    output_dir = resolve_path(config["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_logger(output_dir)

    runtime = config.get("runtime", {})
    prepared_dir = resolve_path(config["paths"]["prepared_data_dir"])
    data = load_prepared_data(prepared_dir)
    fold_ids = validate_frozen_splits(data)
    LOGGER.info(
        "Datos preparados: X=%s | clases=%s | folds=%s",
        data.X.shape,
        len(data.classes),
        fold_ids,
    )

    if args.report_only:
        search_summary, best, oof, final = load_existing_report_results(output_dir)
        report_device = f"{runtime.get('device', 'auto')} (reporte regenerado)"
        write_report(
            data,
            fold_ids,
            best,
            search_summary,
            oof,
            final,
            config,
            output_dir,
            report_device,
        )
        LOGGER.info(
            "Reporte DNN regenerado desde resultados existentes; no se ejecutó entrenamiento."
        )
        return

    torch, nn, DataLoader, TensorDataset = import_torch()
    requested_threads = runtime.get("torch_num_threads")
    if requested_threads is not None:
        torch.set_num_threads(int(requested_threads))
    device = choose_device(torch, str(runtime.get("device", "auto")))
    LOGGER.info("PyTorch=%s | dispositivo=%s", torch.__version__, device)
    if device.type == "cuda":
        LOGGER.info(
            "GPU=%s | VRAM=%.2f GiB",
            torch.cuda.get_device_name(device),
            torch.cuda.get_device_properties(device).total_memory / (1024**3),
        )

    _, search_summary, best = run_spatial_search(
        torch,
        nn,
        DataLoader,
        TensorDataset,
        data,
        fold_ids,
        config,
        output_dir,
        device,
    )
    oof = evaluate_best_oof(
        torch,
        nn,
        DataLoader,
        TensorDataset,
        data,
        fold_ids,
        best,
        config,
        output_dir,
        device,
    )
    final = train_final_development_model(
        torch,
        nn,
        DataLoader,
        TensorDataset,
        data,
        best,
        config,
        output_dir,
        device,
    )
    # Esta llamada ocurre después de calcular y guardar la evaluación independiente.
    train_optional_all_modelable(
        torch,
        nn,
        DataLoader,
        TensorDataset,
        data,
        best,
        config,
        output_dir,
        device,
    )
    copy_reproducibility_metadata(config_path, data, best, output_dir)
    write_report(data, fold_ids, best, search_summary, oof, final, config, output_dir, device)
    LOGGER.info("Entrenamiento y evaluación DNN finalizados: %s", output_dir)


if __name__ == "__main__":
    main()
