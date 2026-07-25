"""Utilidades compartidas para la predicción raster de la Actividad 4.

Este módulo solo carga artefactos congelados y ejecuta inferencia. No contiene
ninguna operación ``fit`` ni modifica los modelos guardados.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def read_config(path: str | Path) -> dict[str, Any]:
    config_path = resolve_path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"No existe YAML: {config_path}")
    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("El YAML debe contener un diccionario.")
    for section in ["shared", "prepare", "predict", "compare"]:
        if section not in config or not isinstance(config[section], dict):
            raise ValueError(f"Falta la sección YAML: {section}")
    return config


def parse_csv_list(value: str | None, cast=str) -> list[Any] | None:
    if value is None:
        return None
    values = [item.strip() for item in value.split(",") if item.strip()]
    return [cast(item) for item in values]


def sanitize_identifier(value: str, prefix_if_needed: str = "b_") -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^0-9a-zA-Z_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise ValueError(f"No se pudo normalizar el identificador: {value!r}")
    if re.match(r"^[0-9]", text):
        text = prefix_if_needed + text
    return text


def read_feature_columns(path: str | Path) -> list[str]:
    feature_path = resolve_path(path)
    if not feature_path.exists():
        raise FileNotFoundError(f"No existe lista de predictores: {feature_path}")
    features = [
        line.strip()
        for line in feature_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    if not features:
        raise ValueError(f"Lista de predictores vacía: {feature_path}")
    duplicated = sorted({value for value in features if features.count(value) > 1})
    if duplicated:
        raise ValueError(f"Predictores duplicados en {feature_path}: {duplicated[:10]}")
    return features


def file_sha256(path: str | Path) -> str:
    source = resolve_path(path)
    digest = hashlib.sha256()
    with source.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quick_file_fingerprint(path: str | Path) -> dict[str, Any]:
    source = resolve_path(path)
    stat = source.stat()
    return {
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def atomic_write_json(payload: Any, path: str | Path) -> None:
    output = resolve_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(output)


def dataframe_to_markdown(dataframe: pd.DataFrame, max_rows: int | None = None) -> str:
    if dataframe.empty:
        return "_Sin datos._"
    display = dataframe if max_rows is None else dataframe.head(max_rows)

    def format_cell(value: Any) -> str:
        try:
            if bool(pd.isna(value)):
                return ""
        except (TypeError, ValueError):
            pass
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.6f}"
        return str(value).replace("|", r"\|").replace("\n", "<br>")

    headers = [format_cell(column) for column in display.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in display.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(format_cell(value) for value in row) + " |")
    return "\n".join(lines)


def load_class_catalog(path: str | Path) -> pd.DataFrame:
    catalog_path = resolve_path(path)
    catalog = pd.read_csv(catalog_path, encoding="utf-8-sig")
    required = {"id_1_propuesta", "nivel_1_propuesta"}
    missing = required - set(catalog.columns)
    if missing:
        raise ValueError(f"Faltan campos en catálogo de clases: {sorted(missing)}")
    catalog = catalog[["id_1_propuesta", "nivel_1_propuesta"]].copy()
    catalog["id_1_propuesta"] = pd.to_numeric(
        catalog["id_1_propuesta"], errors="raise"
    ).astype(int)
    return catalog


def class_style_rows(
    class_catalog: list[dict[str, Any]] | pd.DataFrame,
    style_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Valida la paleta y combina IDs, etiquetas y colores RGB."""
    records = (
        class_catalog.to_dict(orient="records")
        if isinstance(class_catalog, pd.DataFrame)
        else list(class_catalog)
    )
    colors = {
        int(class_id): str(color).strip().upper()
        for class_id, color in (style_config.get("colors", {}) or {}).items()
    }
    class_ids = {int(row["id_1_propuesta"]) for row in records}
    missing = sorted(class_ids - set(colors))
    extra = sorted(set(colors) - class_ids)
    if missing or extra:
        raise ValueError(
            "La paleta no coincide con las clases homologadas. "
            f"Faltantes={missing}; adicionales={extra}."
        )
    rows: list[dict[str, Any]] = []
    for row in sorted(records, key=lambda item: int(item["id_1_propuesta"])):
        class_id = int(row["id_1_propuesta"])
        color = colors[class_id]
        if not re.fullmatch(r"#[0-9A-F]{6}", color):
            raise ValueError(
                f"Color inválido para la clase {class_id}: {color!r}"
            )
        rows.append(
            {
                "id_1_propuesta": class_id,
                "nivel_1_propuesta": str(row["nivel_1_propuesta"]),
                "color_hex": color,
                "red": int(color[1:3], 16),
                "green": int(color[3:5], 16),
                "blue": int(color[5:7], 16),
                "alpha": 255,
            }
        )
    return rows


def _write_qml_style(
    path: Path,
    rows: list[dict[str, Any]],
    nodata: int,
) -> None:
    root = ET.Element(
        "qgis",
        {
            "version": "3.34.0",
            "styleCategories": "Symbology",
        },
    )
    pipe = ET.SubElement(root, "pipe")
    renderer = ET.SubElement(
        pipe,
        "rasterrenderer",
        {
            "type": "paletted",
            "band": "1",
            "opacity": "1",
            "alphaBand": "-1",
        },
    )
    ET.SubElement(renderer, "rasterTransparency")
    palette = ET.SubElement(renderer, "colorPalette")
    ET.SubElement(
        palette,
        "paletteEntry",
        {
            "value": str(nodata),
            "color": "#000000",
            "alpha": "0",
            "label": "Sin datos",
        },
    )
    for row in rows:
        ET.SubElement(
            palette,
            "paletteEntry",
            {
                "value": str(row["id_1_propuesta"]),
                "color": row["color_hex"],
                "alpha": str(row["alpha"]),
                "label": row["nivel_1_propuesta"],
            },
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _write_sld_style(
    path: Path,
    rows: list[dict[str, Any]],
    nodata: int,
    layer_name: str,
) -> None:
    sld = "http://www.opengis.net/sld"
    ogc = "http://www.opengis.net/ogc"
    xlink = "http://www.w3.org/1999/xlink"
    xsi = "http://www.w3.org/2001/XMLSchema-instance"
    ET.register_namespace("", sld)
    ET.register_namespace("ogc", ogc)
    ET.register_namespace("xlink", xlink)
    ET.register_namespace("xsi", xsi)
    root = ET.Element(
        f"{{{sld}}}StyledLayerDescriptor",
        {
            "version": "1.0.0",
            f"{{{xsi}}}schemaLocation": (
                "http://www.opengis.net/sld "
                "http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd"
            ),
        },
    )
    named_layer = ET.SubElement(root, f"{{{sld}}}NamedLayer")
    ET.SubElement(named_layer, f"{{{sld}}}Name").text = layer_name
    user_style = ET.SubElement(named_layer, f"{{{sld}}}UserStyle")
    ET.SubElement(user_style, f"{{{sld}}}Title").text = (
        "Clases homologadas id_1_propuesta"
    )
    feature_style = ET.SubElement(
        user_style,
        f"{{{sld}}}FeatureTypeStyle",
    )
    rule = ET.SubElement(feature_style, f"{{{sld}}}Rule")
    raster_symbolizer = ET.SubElement(
        rule,
        f"{{{sld}}}RasterSymbolizer",
    )
    ET.SubElement(
        raster_symbolizer,
        f"{{{sld}}}Opacity",
    ).text = "1.0"
    color_map = ET.SubElement(
        raster_symbolizer,
        f"{{{sld}}}ColorMap",
        {"type": "values"},
    )
    ET.SubElement(
        color_map,
        f"{{{sld}}}ColorMapEntry",
        {
            "color": "#000000",
            "quantity": str(nodata),
            "label": "Sin datos",
            "opacity": "0",
        },
    )
    for row in rows:
        ET.SubElement(
            color_map,
            f"{{{sld}}}ColorMapEntry",
            {
                "color": row["color_hex"],
                "quantity": str(row["id_1_propuesta"]),
                "label": row["nivel_1_propuesta"],
                "opacity": "1",
            },
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _write_clr_style(
    path: Path,
    rows: list[dict[str, Any]],
    nodata: int,
) -> None:
    lines = [
        "# QGIS Generated Color Map Export File",
        "INTERPOLATION:EXACT",
        f"{nodata},0,0,0,0,Sin datos",
    ]
    lines.extend(
        (
            f"{row['id_1_propuesta']},{row['red']},{row['green']},"
            f"{row['blue']},{row['alpha']},{row['nivel_1_propuesta']}"
        )
        for row in rows
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_class_raster_styles(
    raster_path: str | Path,
    class_catalog: list[dict[str, Any]] | pd.DataFrame,
    style_config: dict[str, Any],
    nodata: int = 0,
) -> dict[str, Any]:
    """Crea estilos laterales y, opcionalmente, una tabla de color interna."""
    output = resolve_path(raster_path)
    if not output.exists():
        raise FileNotFoundError(f"No existe raster para estilizar: {output}")
    rows = class_style_rows(class_catalog, style_config)
    generated: dict[str, Any] = {
        "qml": "",
        "sld": "",
        "clr": "",
        "embedded_colormap": False,
    }
    if bool(style_config.get("write_qml", True)):
        qml_path = output.with_suffix(".qml")
        _write_qml_style(qml_path, rows, nodata)
        generated["qml"] = str(qml_path)
    if bool(style_config.get("write_sld", True)):
        sld_path = output.with_suffix(".sld")
        _write_sld_style(sld_path, rows, nodata, output.stem)
        generated["sld"] = str(sld_path)
    if bool(style_config.get("write_clr", True)):
        clr_path = output.with_suffix(".clr")
        _write_clr_style(clr_path, rows, nodata)
        generated["clr"] = str(clr_path)
    if bool(style_config.get("embed_geotiff_colormap", True)):
        import rasterio

        color_map = {
            nodata: (0, 0, 0, 0),
            **{
                int(row["id_1_propuesta"]): (
                    int(row["red"]),
                    int(row["green"]),
                    int(row["blue"]),
                    int(row["alpha"]),
                )
                for row in rows
            },
        }
        with rasterio.open(output, "r+") as raster:
            if raster.count != 1 or raster.dtypes[0] != "uint8":
                raise ValueError(
                    "La paleta GeoTIFF solo se incrusta en rasters uint8 "
                    "de una banda."
                )
            raster.write_colormap(1, color_map)
            raster.update_tags(
                class_field="id_1_propuesta",
                style_palette="homologated_land_cover_v1",
                **{
                    f"class_{row['id_1_propuesta']}": (
                        f"{row['nivel_1_propuesta']}|{row['color_hex']}"
                    )
                    for row in rows
                },
            )
        generated["embedded_colormap"] = True
    return generated


def normalize_original_classes(values: np.ndarray) -> np.ndarray:
    output: list[int] = []
    for value in np.asarray(values).reshape(-1):
        numeric = float(value)
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise ValueError(f"Clase predicha no válida: {value!r}")
        output.append(int(numeric))
    return np.asarray(output, dtype=np.uint8)


@dataclass
class PredictionResult:
    classes: np.ndarray
    confidence: np.ndarray | None
    confidence_method: str


class FrozenModelRunner:
    """Adaptador de inferencia para un artefacto entrenado solo en desarrollo."""

    def __init__(
        self,
        model_id: str,
        model_config: dict[str, Any],
        expected_features: list[str],
        prediction_batch_size: int,
        dnn_device: str = "auto",
    ) -> None:
        self.model_id = model_id
        self.config = model_config
        self.expected_features = expected_features
        self.prediction_batch_size = int(prediction_batch_size)
        self.adapter = str(model_config["adapter"])
        self.model: Any = None
        self.encoder: Any = None
        self.preprocessor: Any = None
        self.torch: Any = None
        self.device: Any = None
        self.class_values: np.ndarray | None = None
        self.trained_on = str(model_config.get("expected_trained_on", "development_only"))
        self._load(dnn_device)

    @property
    def supports_confidence(self) -> bool:
        return self.adapter == "pytorch_dnn" or hasattr(
            self.model, "predict_proba"
        )

    def _validate_feature_file(self) -> None:
        artifact_features = read_feature_columns(self.config["feature_columns"])
        if artifact_features != self.expected_features:
            raise ValueError(
                f"{self.model_id}: el orden/lista de predictores del artefacto no coincide "
                "con el manifiesto."
            )

    def _load(self, dnn_device: str) -> None:
        self._validate_feature_file()
        artifact_path = resolve_path(self.config["artifact"])
        if not artifact_path.exists():
            raise FileNotFoundError(f"{self.model_id}: no existe modelo {artifact_path}")

        if self.adapter in {"sklearn_bundle", "sklearn_separate"}:
            import joblib

            artifact = joblib.load(artifact_path)
            if self.adapter == "sklearn_bundle":
                if not isinstance(artifact, dict) or "model" not in artifact:
                    raise ValueError(
                        f"{self.model_id}: se esperaba un bundle con clave 'model'."
                    )
                self.model = artifact["model"]
                self.encoder = artifact.get("label_encoder")
                embedded_features = artifact.get("feature_columns")
                if embedded_features is not None and list(embedded_features) != self.expected_features:
                    raise ValueError(
                        f"{self.model_id}: feature_columns incrustadas no coinciden."
                    )
                embedded_scope = str(artifact.get("trained_on", ""))
                if embedded_scope != self.trained_on:
                    raise ValueError(
                        f"{self.model_id}: trained_on={embedded_scope!r}; "
                        f"se exige {self.trained_on!r}."
                    )
            else:
                self.model = artifact
                encoder_path = resolve_path(self.config["label_encoder"])
                if not encoder_path.exists():
                    raise FileNotFoundError(
                        f"{self.model_id}: no existe codificador {encoder_path}"
                    )
                self.encoder = joblib.load(encoder_path)
            return

        if self.adapter != "pytorch_dnn":
            raise ValueError(f"Adaptador no soportado: {self.adapter}")

        import joblib
        try:
            import torch
        except ModuleNotFoundError as error:
            raise ModuleNotFoundError(
                "Para ejecutar el modelo DNN instale PyTorch. La dependencia "
                "'pytorch' está declarada en environment.yml."
            ) from error

        self.torch = torch
        if dnn_device == "auto":
            device_name = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device_name = dnn_device
        self.device = torch.device(device_name)
        try:
            artifact = torch.load(
                artifact_path,
                map_location=self.device,
                weights_only=False,
            )
        except TypeError:
            artifact = torch.load(artifact_path, map_location=self.device)
        if str(artifact.get("trained_on", "")) != self.trained_on:
            raise ValueError(
                f"{self.model_id}: el DNN no está marcado {self.trained_on!r}."
            )
        if list(artifact.get("feature_columns", [])) != self.expected_features:
            raise ValueError(f"{self.model_id}: predictores incrustados no coinciden.")

        nn = torch.nn
        activation_name = str(artifact["activation"]).lower()
        activation_factory = nn.Tanh if activation_name == "tanh" else nn.ReLU
        layers: list[Any] = []
        previous = int(artifact["input_dim"])
        for width in artifact["hidden_units"]:
            layers.append(nn.Linear(previous, int(width)))
            layers.append(activation_factory())
            if float(artifact["dropout"]) > 0:
                layers.append(nn.Dropout(float(artifact["dropout"])))
            previous = int(width)
        layers.append(nn.Linear(previous, int(artifact["n_classes"])))
        self.model = nn.Sequential(*layers).to(self.device)
        self.model.load_state_dict(artifact["model_state_dict"])
        self.model.eval()

        preprocessor_path = resolve_path(self.config["preprocessor"])
        self.preprocessor = joblib.load(preprocessor_path)
        mapping = sorted(artifact["class_mapping"], key=lambda row: int(row["encoded_class"]))
        self.class_values = np.asarray(
            [int(row["original_class"]) for row in mapping],
            dtype=np.uint8,
        )

    def predict(self, X: np.ndarray) -> PredictionResult:
        if self.adapter != "pytorch_dnn":
            model_input = pd.DataFrame(
                X,
                columns=self.expected_features,
                copy=False,
            )
            encoded = np.asarray(self.model.predict(model_input))
            if self.encoder is not None:
                original = self.encoder.inverse_transform(encoded.astype(int))
            else:
                original = encoded
            classes = normalize_original_classes(original)
            if hasattr(self.model, "predict_proba"):
                probabilities = np.asarray(
                    self.model.predict_proba(model_input),
                    dtype=np.float32,
                )
                confidence = probabilities.max(axis=1)
                method = "predict_proba"
            else:
                confidence = None
                method = "not_available_not_calibrated"
            return PredictionResult(classes, confidence, method)

        model_input = pd.DataFrame(
            X,
            columns=self.expected_features,
            copy=False,
        )
        transformed = self.preprocessor.transform(model_input).astype(
            np.float32,
            copy=False,
        )
        predictions: list[np.ndarray] = []
        confidences: list[np.ndarray] = []
        torch = self.torch
        with torch.no_grad():
            for start in range(0, len(transformed), self.prediction_batch_size):
                batch = torch.from_numpy(
                    np.ascontiguousarray(
                        transformed[start : start + self.prediction_batch_size]
                    )
                ).to(self.device)
                probabilities = torch.softmax(self.model(batch), dim=1)
                predictions.append(torch.argmax(probabilities, dim=1).cpu().numpy())
                confidences.append(probabilities.max(dim=1).values.cpu().numpy())
        encoded = np.concatenate(predictions)
        if self.class_values is None:
            raise RuntimeError("DNN sin class_mapping.")
        classes = self.class_values[encoded]
        confidence = np.concatenate(confidences).astype(np.float32)
        return PredictionResult(classes, confidence, "softmax")
