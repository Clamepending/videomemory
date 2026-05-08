"""Quantized DINOv2-small plus CLIP-text adapter runtime for semantic filtering.

The hot path is intentionally small:
  RGB frame -> DINOv2-small dynamic-int8 ONNX -> adapter query dot product.

CLIP text encoding is cached by ``SemanticFrameFilter`` and only runs when the
keyword set changes.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np


DEFAULT_DINO_MODEL = "facebook/dinov2-small"
DEFAULT_CLIP_MODEL = "openai/clip-vit-base-patch16"
DEFAULT_MODEL_DIR = Path.home() / ".cache" / "videomemory" / "dino-clip-adapter"
DEFAULT_FP32_ONNX = DEFAULT_MODEL_DIR / "dinov2_small_224_last_hidden.onnx"
DEFAULT_INT8_ONNX = DEFAULT_MODEL_DIR / "dinov2_small_224_last_hidden_dynamic_int8.onnx"
LOCAL_DINOEXP_ADAPTER = Path("/Users/mark/Desktop/projects/dinoexp/models/clip_text_to_dino_adapter_coco_3k.pt")
DEFAULT_CACHE_ADAPTER = DEFAULT_MODEL_DIR / "clip_text_to_dino_adapter_coco_3k.pt"
INSTALL_COMMAND = "uv pip install torch transformers onnxruntime"
MODEL_NAME = "dinov2-small-clip-adapter-int8-onnx"
GRID = 16

IM_MEAN = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
IM_STD = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)


@dataclass(frozen=True)
class AdapterWeights:
    ln_weight: np.ndarray
    ln_bias: np.ndarray
    linear_weight: np.ndarray
    linear_bias: np.ndarray
    logit_scale: float
    config: Dict[str, Any]


class TextEncoder:
    """Lazy CLIP text encoder used to form adapter queries."""

    def __init__(self, model_name: str, device_name: str) -> None:
        try:
            import torch
            import torch.nn.functional as functional
            from transformers import CLIPModel, CLIPProcessor
        except ModuleNotFoundError as exc:
            missing_name = exc.name or "torch/transformers"
            raise RuntimeError(
                f"Missing optional dependency '{missing_name}'. Install the DINO/CLIP backend with: {INSTALL_COMMAND}"
            ) from exc

        self.torch = torch
        self.functional = functional
        self.device = _select_torch_device(torch, device_name)
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.model = CLIPModel.from_pretrained(model_name, use_safetensors=True).to(self.device).eval()

    def encode(self, keywords: list[str]) -> np.ndarray:
        inputs = self.processor(text=keywords, return_tensors="pt", padding=True, truncation=True).to(self.device)
        with self.torch.inference_mode():
            outputs = self.model.text_model(**inputs)
            features = self.model.text_projection(outputs.pooler_output)
            features = self.functional.normalize(features, dim=-1)
        return features.detach().cpu().numpy().astype(np.float32)


class DinoClipAdapterRuntime:
    """Loaded DINO ONNX session plus CLIP-text adapter."""

    def __init__(
        self,
        *,
        adapter_path: Path,
        onnx_path: Path,
        fp32_onnx_path: Path,
        dino_model: str = DEFAULT_DINO_MODEL,
        clip_model: str = DEFAULT_CLIP_MODEL,
        dino_size: int = 224,
        text_device: str = "auto",
        ort_threads: int = 4,
        export_if_missing: bool = False,
        force_export: bool = False,
    ) -> None:
        self.adapter_path = adapter_path.expanduser().resolve()
        self.onnx_path = onnx_path.expanduser().resolve()
        self.fp32_onnx_path = fp32_onnx_path.expanduser().resolve()
        self.adapter = load_adapter(self.adapter_path)
        self.dino_model = self.adapter.config.get("dino_model") or dino_model
        self.clip_model = self.adapter.config.get("clip_model") or clip_model
        self.dino_size = int(self.adapter.config.get("dino_size") or dino_size)

        if force_export or not self.onnx_path.exists():
            if not export_if_missing:
                raise RuntimeError(f"Missing quantized DINO ONNX model at {self.onnx_path}")
            export_and_quantize_dino(
                dino_model=self.dino_model,
                dino_size=self.dino_size,
                fp32_path=self.fp32_onnx_path,
                int8_path=self.onnx_path,
                force=force_export,
            )

        self.session = create_onnx_session(self.onnx_path, ort_threads)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.provider = ",".join(self.session.get_providers())
        self.text_encoder = TextEncoder(self.clip_model, text_device)
        self.grid_size = GRID

    @property
    def model_name(self) -> str:
        return MODEL_NAME

    def encode_texts(self, keywords: list[str]) -> np.ndarray:
        if not keywords:
            return np.zeros((0, int(self.adapter.linear_bias.shape[0])), dtype=np.float32)
        text_features = self.text_encoder.encode(keywords)
        return adapter_query(self.adapter, text_features)

    def score_image_embeddings(self, image_rgb: np.ndarray, text_embeddings: np.ndarray) -> np.ndarray:
        query = np.atleast_2d(np.asarray(text_embeddings, dtype=np.float32))
        if query.size == 0:
            return np.zeros((0, 0), dtype=np.float32)

        pixel_values = preprocess_dino_rgb(image_rgb, self.dino_size)
        hidden = self.session.run([self.output_name], {self.input_name: pixel_values})[0]
        patches = np.asarray(hidden[:, 1:, :], dtype=np.float32)
        patches = l2_normalize(patches[0], axis=-1)
        self.grid_size = infer_square_grid(int(patches.shape[0]))

        logits = patches @ query.T
        return sigmoid(logits * self.adapter.logit_scale).astype(np.float32)


_RUNTIME_LOCK = threading.Lock()
_RUNTIME_CACHE: Dict[Tuple[str, str, str, str, int, str, int], DinoClipAdapterRuntime] = {}


def load_runtime(
    checkpoint_path: Optional[Path] = None,
    device_name: str = "auto",
    *,
    onnx_path: Optional[Path] = None,
    fp32_onnx_path: Optional[Path] = None,
    ort_threads: Optional[int] = None,
    export_if_missing: Optional[bool] = None,
    force_export: Optional[bool] = None,
) -> DinoClipAdapterRuntime:
    """Load and cache the DINO/CLIP adapter runtime."""

    adapter = resolve_adapter_path(str(checkpoint_path) if checkpoint_path else None).expanduser().resolve()
    onnx = resolve_onnx_path(str(onnx_path) if onnx_path else None).expanduser().resolve()
    fp32 = Path(os.environ.get("VIDEOMEMORY_DINO_FP32_ONNX", str(fp32_onnx_path or DEFAULT_FP32_ONNX))).expanduser().resolve()
    threads = int(os.environ.get("VIDEOMEMORY_DINO_ORT_THREADS", str(ort_threads if ort_threads is not None else 4)))
    should_export = _env_truthy("VIDEOMEMORY_DINO_EXPORT_IF_MISSING") if export_if_missing is None else export_if_missing
    should_force_export = _env_truthy("VIDEOMEMORY_DINO_FORCE_EXPORT") if force_export is None else force_export
    dino_model = os.environ.get("VIDEOMEMORY_DINO_MODEL", DEFAULT_DINO_MODEL)
    clip_model = os.environ.get("VIDEOMEMORY_CLIP_TEXT_MODEL", DEFAULT_CLIP_MODEL)
    dino_size = int(os.environ.get("VIDEOMEMORY_DINO_SIZE", "224"))

    key = (str(adapter), str(onnx), str(fp32), dino_model, dino_size, device_name, threads)
    with _RUNTIME_LOCK:
        runtime = _RUNTIME_CACHE.get(key)
        if runtime is None or should_force_export:
            runtime = DinoClipAdapterRuntime(
                adapter_path=adapter,
                onnx_path=onnx,
                fp32_onnx_path=fp32,
                dino_model=dino_model,
                clip_model=clip_model,
                dino_size=dino_size,
                text_device=device_name,
                ort_threads=threads,
                export_if_missing=should_export,
                force_export=should_force_export,
            )
            _RUNTIME_CACHE[key] = runtime
        return runtime


def resolve_adapter_path(path_text: Optional[str]) -> Path:
    if path_text:
        return Path(path_text)
    env_path = os.environ.get("VIDEOMEMORY_DINO_CLIP_ADAPTER")
    if env_path:
        return Path(env_path)
    if DEFAULT_CACHE_ADAPTER.exists():
        return DEFAULT_CACHE_ADAPTER
    if LOCAL_DINOEXP_ADAPTER.exists():
        return LOCAL_DINOEXP_ADAPTER
    return DEFAULT_CACHE_ADAPTER


def resolve_onnx_path(path_text: Optional[str]) -> Path:
    if path_text:
        return Path(path_text)
    env_path = os.environ.get("VIDEOMEMORY_DINO_ONNX")
    if env_path:
        return Path(env_path)
    return DEFAULT_INT8_ONNX


def load_adapter(path: Path) -> AdapterWeights:
    try:
        import torch
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"Missing optional dependency 'torch'. Install the DINO/CLIP backend with: {INSTALL_COMMAND}"
        ) from exc

    if not path.exists():
        raise RuntimeError(f"Adapter checkpoint not found: {path}")
    checkpoint = torch.load(str(path), map_location="cpu", weights_only=False)
    state = checkpoint["adapter"]
    logit_scale = float(state["logit_scale"].detach().cpu().item())
    return AdapterWeights(
        ln_weight=state["proj.0.weight"].detach().cpu().numpy().astype(np.float32),
        ln_bias=state["proj.0.bias"].detach().cpu().numpy().astype(np.float32),
        linear_weight=state["proj.1.weight"].detach().cpu().numpy().astype(np.float32),
        linear_bias=state["proj.1.bias"].detach().cpu().numpy().astype(np.float32),
        logit_scale=float(np.clip(logit_scale, 1.0, 100.0)),
        config=dict(checkpoint.get("config", {}) or {}),
    )


def adapter_query(adapter: AdapterWeights, text_features: np.ndarray) -> np.ndarray:
    x = np.atleast_2d(np.asarray(text_features, dtype=np.float32))
    mean = x.mean(axis=1, keepdims=True)
    var = np.mean((x - mean) ** 2, axis=1, keepdims=True)
    x = ((x - mean) / np.sqrt(var + 1e-5)) * adapter.ln_weight + adapter.ln_bias
    x = x @ adapter.linear_weight.T + adapter.linear_bias
    return l2_normalize(x, axis=-1).astype(np.float32)


def preprocess_dino_rgb(frame_rgb: np.ndarray, size: int) -> np.ndarray:
    resized = cv2.resize(frame_rgb, (size, size), interpolation=cv2.INTER_AREA)
    rgb = resized.astype(np.float32) / 255.0
    rgb = (rgb - IM_MEAN) / IM_STD
    return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None, :, :, :].astype(np.float32))


def create_onnx_session(path: Path, threads: int):
    try:
        import onnxruntime as ort
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"Missing optional dependency 'onnxruntime'. Install the DINO/CLIP backend with: {INSTALL_COMMAND}"
        ) from exc

    options = ort.SessionOptions()
    if threads > 0:
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def export_and_quantize_dino(
    *,
    dino_model: str,
    dino_size: int,
    fp32_path: Path,
    int8_path: Path,
    force: bool,
) -> None:
    try:
        import torch
        from onnxruntime.quantization import QuantType, quantize_dynamic
        from transformers import AutoModel
    except ModuleNotFoundError as exc:
        missing_name = exc.name or "torch/transformers/onnxruntime"
        raise RuntimeError(
            f"Missing optional dependency '{missing_name}'. Install the DINO/CLIP backend with: {INSTALL_COMMAND}"
        ) from exc

    fp32_path.parent.mkdir(parents=True, exist_ok=True)
    int8_path.parent.mkdir(parents=True, exist_ok=True)

    if force or not fp32_path.exists():
        try:
            model = AutoModel.from_pretrained(dino_model, attn_implementation="eager").eval()
        except TypeError:
            model = AutoModel.from_pretrained(dino_model).eval()

        class DinoLastHidden(torch.nn.Module):
            def __init__(self, wrapped):
                super().__init__()
                self.wrapped = wrapped

            def forward(self, pixel_values):
                return self.wrapped(pixel_values=pixel_values).last_hidden_state

        wrapper = DinoLastHidden(model).eval()
        dummy = torch.randn(1, 3, dino_size, dino_size, dtype=torch.float32)
        with torch.inference_mode():
            torch.onnx.export(
                wrapper,
                (dummy,),
                str(fp32_path),
                input_names=["pixel_values"],
                output_names=["last_hidden_state"],
                opset_version=17,
                do_constant_folding=True,
                dynamo=False,
            )

    if force or not int8_path.exists():
        quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QInt8)


def l2_normalize(values: np.ndarray, axis: int) -> np.ndarray:
    return values / np.maximum(np.linalg.norm(values, axis=axis, keepdims=True), 1e-8)


def sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -60.0, 60.0)))


def infer_square_grid(patch_count: int) -> int:
    grid_size = int(round(float(patch_count) ** 0.5))
    if grid_size * grid_size != patch_count:
        raise ValueError(f"Cannot reshape {patch_count} patches into a square DINO grid")
    return grid_size


def _select_torch_device(torch, device_name: str):
    if device_name == "auto":
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(device_name)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
