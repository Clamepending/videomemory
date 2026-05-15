"""Local binary visual monitor runtime.

This module is intentionally separate from the general VLM provider stack.
Binary monitors answer one question per frame: is this visual criterion true?
They are meant for fast local done/not-done task completion, not rich captioning.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
import threading
import time
import types
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional

import cv2

logger = logging.getLogger("BinaryMonitor")

DEFAULT_FASTVLM_BINARY_MODEL = "mlx-community/FastVLM-0.5B-bf16"
DEFAULT_FASTVLM_BINARY_RESIZE = 256
DEFAULT_FASTVLM_BINARY_THRESHOLD = 0.7
DEFAULT_FASTVLM_BINARY_REQUIRED_HITS = 4
DEFAULT_FASTVLM_BINARY_WINDOW = 5
DEFAULT_FASTVLM_BINARY_THRESHOLD_MODE = "adaptive"
DEFAULT_FASTVLM_BINARY_ADAPTIVE_Z = 3.0
DEFAULT_FASTVLM_BINARY_ADAPTIVE_MIN_SAMPLES = 10
DEFAULT_FASTVLM_BINARY_ADAPTIVE_WINDOW = 10
DEFAULT_FASTVLM_BINARY_ADAPTIVE_FLOOR = 0.5


@dataclass(frozen=True)
class BinaryMonitorScore:
    answer: str
    p_true: float
    p_false: float
    raw_text: str
    inference_ms: float
    model: str
    resize: int
    error: Optional[str] = None


@dataclass(frozen=True)
class BinaryMonitorDecision:
    task_id: str
    criterion: str
    score: BinaryMonitorScore
    threshold: float
    required_hits: int
    window: int
    hits: int
    done: bool
    threshold_mode: str = "fixed"
    effective_threshold: float = DEFAULT_FASTVLM_BINARY_THRESHOLD
    baseline_mean: Optional[float] = None
    baseline_variance: Optional[float] = None
    baseline_stddev: Optional[float] = None
    baseline_samples: int = 0
    adaptive_ready: bool = False
    calibrating: bool = False
    adaptive_z: float = DEFAULT_FASTVLM_BINARY_ADAPTIVE_Z
    adaptive_floor: float = DEFAULT_FASTVLM_BINARY_ADAPTIVE_FLOOR


class FastVLMBinaryRuntime:
    """Forced True/False FastVLM scorer using the stock MLX-VLM generator path."""

    def __init__(self, model_name: Optional[str] = None) -> None:
        self.model_name = model_name or os.getenv("VIDEOMEMORY_FASTVLM_MODEL", DEFAULT_FASTVLM_BINARY_MODEL)
        self.model = None
        self.processor = None
        self.config = None
        self.true_token_id: Optional[int] = None
        self.false_token_id: Optional[int] = None
        self._loaded = False
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._loaded

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            from mlx_vlm import load
            from mlx_vlm.utils import load_config

            logger.info("Loading FastVLM binary monitor model: %s", self.model_name)
            started = time.perf_counter()
            self.model, self.processor = load(self.model_name)
            self._patch_fastvlm_quantized_embedding_cast()
            self.config = load_config(self.model_name)
            tokenizer = self._tokenizer()
            true_ids = tokenizer.encode("True", add_special_tokens=False)
            false_ids = tokenizer.encode("False", add_special_tokens=False)
            if len(true_ids) != 1 or len(false_ids) != 1:
                raise RuntimeError(
                    f"Expected single-token True/False, got True={true_ids} False={false_ids}"
                )
            self.true_token_id = int(true_ids[0])
            self.false_token_id = int(false_ids[0])
            self._loaded = True
            logger.info("Loaded FastVLM binary monitor in %.2fs", time.perf_counter() - started)

    def _patch_fastvlm_quantized_embedding_cast(self) -> None:
        if self.model is None or not hasattr(self.model, "vision_tower"):
            return
        try:
            import mlx.core as mx
            from mlx_vlm.models.base import InputEmbeddingsFeatures
        except Exception:
            return
        embed_tokens = getattr(getattr(self.model.language_model, "model", None), "embed_tokens", None)
        embed_weight = getattr(embed_tokens, "weight", None)
        if embed_weight is None or mx.issubdtype(embed_weight.dtype, mx.floating):
            return

        def get_input_embeddings_safe(model, input_ids=None, pixel_values=None, mask=None, **kwargs):
            if pixel_values is None:
                return InputEmbeddingsFeatures(inputs_embeds=model.language_model.model.embed_tokens(input_ids))
            cached = kwargs.get("cached_image_features", None)
            if cached is not None:
                image_features = cached
            else:
                if not mx.issubdtype(pixel_values.dtype, mx.floating):
                    pixel_values = pixel_values.astype(mx.float32)
                _, image_features, _ = model.vision_tower(pixel_values.transpose(0, 2, 3, 1))
                batch, height, width, channels = image_features.shape
                image_features = image_features.reshape(batch, height * width, channels)
                image_features = model.mm_projector(image_features)
            final_inputs_embeds = model.prepare_inputs_for_multimodal(image_features, input_ids, mask)
            return InputEmbeddingsFeatures(inputs_embeds=final_inputs_embeds)

        self.model.get_input_embeddings = types.MethodType(get_input_embeddings_safe, self.model)

    def _tokenizer(self):
        if self.processor is None:
            raise RuntimeError("FastVLM processor is not loaded")
        return self.processor.tokenizer if hasattr(self.processor, "tokenizer") else self.processor

    def score_bgr_frame(self, frame_bgr: Any, criterion: str, resize: Optional[int] = None) -> BinaryMonitorScore:
        self.ensure_loaded()
        from PIL import Image

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame_rgb)
        return self.score_image(image, criterion, resize=resize)

    def score_image(self, image: Any, criterion: str, resize: Optional[int] = None) -> BinaryMonitorScore:
        self.ensure_loaded()
        if self.true_token_id is None or self.false_token_id is None:
            raise RuntimeError("True/False token ids are not initialized")
        with self._lock:
            return self._score_image_locked(image, criterion.strip(), resize=resize)

    def _score_image_locked(self, image: Any, criterion: str, resize: Optional[int]) -> BinaryMonitorScore:
        import mlx.core as mx
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        if self.model is None or self.processor is None or self.config is None:
            raise RuntimeError("FastVLM model is not loaded")

        true_id = self.true_token_id
        false_id = self.false_token_id
        image_processor = getattr(self.processor, "image_processor", None)
        old_processor_size = getattr(image_processor, "size", None) if image_processor is not None else None
        old_crop_size = getattr(image_processor, "crop_size", None) if image_processor is not None else None
        resize = int(resize or DEFAULT_FASTVLM_BINARY_RESIZE)

        def restrict_to_binary(_tokens, logits):
            mask = mx.full(logits.shape, -1e9, dtype=logits.dtype)
            mask[:, true_id] = logits[:, true_id]
            mask[:, false_id] = logits[:, false_id]
            return mask

        prompt = apply_chat_template(
            self.processor,
            self.config,
            f"Criterion: {criterion}\nAnswer True or False.",
            num_images=1,
        )

        temp_path = None
        started = time.perf_counter()
        try:
            if image_processor is not None and resize:
                image_processor.size = {"shortest_edge": resize}
                image_processor.crop_size = {"height": resize, "width": resize}
            with tempfile.NamedTemporaryFile(prefix="videomemory_fastvlm_", suffix=".jpg", delete=False) as f:
                temp_path = f.name
                image.convert("RGB").save(f, format="JPEG", quality=85, optimize=True)

            generated = generate(
                self.model,
                self.processor,
                prompt,
                image=[temp_path],
                resize_shape=(resize, resize),
                max_tokens=1,
                temperature=0.0,
                logits_processors=[restrict_to_binary],
                verbose=False,
            )
            tokenizer = self._tokenizer()
            raw_text = (generated.text or "").strip()
            token = int(generated.token) if generated.token is not None else None
            answer = tokenizer.decode([token]).strip() if token is not None else raw_text
            true_mass = 0.5
            false_mass = 0.5
            if generated.logprobs is not None:
                true_mass = float(mx.exp(generated.logprobs[true_id]).item())
                false_mass = float(mx.exp(generated.logprobs[false_id]).item())
            denom = max(true_mass + false_mass, 1e-12)
            p_true = true_mass / denom
            p_false = false_mass / denom
            if answer not in {"True", "False"}:
                answer = "True" if p_true >= p_false else "False"
            return BinaryMonitorScore(
                answer=answer,
                p_true=float(p_true),
                p_false=float(p_false),
                raw_text=raw_text,
                inference_ms=(time.perf_counter() - started) * 1000.0,
                model=self.model_name,
                resize=resize,
            )
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            if image_processor is not None:
                image_processor.size = old_processor_size
                image_processor.crop_size = old_crop_size


class BinaryFrameMonitor:
    """Applies a binary scorer with per-task temporal voting."""

    def __init__(self, runtime: Optional[FastVLMBinaryRuntime] = None) -> None:
        self.runtime = runtime or FastVLMBinaryRuntime()
        self._votes: Dict[str, Deque[bool]] = {}
        self._probability_history: Dict[str, Deque[float]] = {}
        self.reload_settings_from_env(reset_votes=False)

    def reload_settings_from_env(self, *, reset_votes: bool = True) -> Dict[str, Any]:
        """Reload threshold/voting knobs from environment-backed settings."""

        self.threshold_mode = _env_choice(
            "VIDEOMEMORY_FASTVLM_THRESHOLD_MODE",
            DEFAULT_FASTVLM_BINARY_THRESHOLD_MODE,
            {"adaptive", "fixed"},
        )
        self.threshold = _env_float("VIDEOMEMORY_FASTVLM_THRESHOLD", DEFAULT_FASTVLM_BINARY_THRESHOLD, 0.0, 1.0)
        self.resize = _env_int("VIDEOMEMORY_FASTVLM_VISION_SIZE", DEFAULT_FASTVLM_BINARY_RESIZE, 64, 2048)
        self.required_hits = _env_int("VIDEOMEMORY_FASTVLM_REQUIRED_HITS", DEFAULT_FASTVLM_BINARY_REQUIRED_HITS, 1, 30)
        self.window = _env_int("VIDEOMEMORY_FASTVLM_WINDOW", DEFAULT_FASTVLM_BINARY_WINDOW, 1, 30)
        self.required_hits = min(self.required_hits, self.window)
        self.adaptive_z = _env_float(
            "VIDEOMEMORY_FASTVLM_ADAPTIVE_Z",
            DEFAULT_FASTVLM_BINARY_ADAPTIVE_Z,
            0.0,
            10.0,
        )
        self.adaptive_min_samples = _env_int(
            "VIDEOMEMORY_FASTVLM_ADAPTIVE_MIN_SAMPLES",
            DEFAULT_FASTVLM_BINARY_ADAPTIVE_MIN_SAMPLES,
            2,
            1000,
        )
        # Kept as a reported setting for compatibility; adaptive mode now freezes after calibration.
        self.adaptive_window = self.adaptive_min_samples
        self.adaptive_floor = _env_float(
            "VIDEOMEMORY_FASTVLM_ADAPTIVE_FLOOR",
            DEFAULT_FASTVLM_BINARY_ADAPTIVE_FLOOR,
            0.0,
            1.0,
        )
        if reset_votes:
            self._votes.clear()
            self._probability_history.clear()
        return self.get_settings()

    def get_settings(self) -> Dict[str, Any]:
        """Return the active threshold/voting knobs."""

        return {
            "threshold_mode": str(self.threshold_mode),
            "threshold": float(self.threshold),
            "required_hits": int(self.required_hits),
            "window": int(self.window),
            "resize": int(self.resize),
            "adaptive_z": float(self.adaptive_z),
            "adaptive_min_samples": int(self.adaptive_min_samples),
            "adaptive_window": int(self.adaptive_window),
            "adaptive_floor": float(self.adaptive_floor),
        }

    def reset_task(self, task_id: str) -> None:
        task_key = str(task_id)
        self._votes.pop(task_key, None)
        self._probability_history.pop(task_key, None)

    def score_task(self, frame_bgr: Any, task: Any) -> BinaryMonitorDecision:
        task_id = str(task.task_id)
        score = self.runtime.score_bgr_frame(frame_bgr, str(task.task_desc), resize=self.resize)
        probability_history = self._probability_history.setdefault(task_id, deque(maxlen=self.adaptive_min_samples))
        baseline_samples, baseline_mean, baseline_variance, baseline_stddev = _probability_stats(probability_history)
        adaptive_ready = self.threshold_mode == "adaptive" and baseline_samples >= self.adaptive_min_samples
        calibrating = self.threshold_mode == "adaptive" and not adaptive_ready
        if adaptive_ready and baseline_mean is not None and baseline_stddev is not None:
            effective_threshold = max(
                self.adaptive_floor,
                min(1.0, baseline_mean + (self.adaptive_z * baseline_stddev)),
            )
            hit = score.p_true > effective_threshold
        elif calibrating:
            probability_history.append(float(score.p_true))
            baseline_samples, baseline_mean, baseline_variance, baseline_stddev = _probability_stats(probability_history)
            if baseline_mean is not None and baseline_stddev is not None:
                effective_threshold = max(
                    self.adaptive_floor,
                    min(1.0, baseline_mean + (self.adaptive_z * baseline_stddev)),
                )
            else:
                effective_threshold = self.threshold
            hit = False
        else:
            effective_threshold = self.threshold
            hit = score.p_true >= effective_threshold

        history = self._votes.setdefault(task_id, deque(maxlen=self.window))
        history.append(hit)
        hits = sum(1 for value in history if value)
        return BinaryMonitorDecision(
            task_id=task_id,
            criterion=str(task.task_desc),
            score=score,
            threshold=self.threshold,
            required_hits=self.required_hits,
            window=self.window,
            hits=hits,
            done=hits >= self.required_hits,
            threshold_mode=self.threshold_mode,
            effective_threshold=float(effective_threshold),
            baseline_mean=baseline_mean,
            baseline_variance=baseline_variance,
            baseline_stddev=baseline_stddev,
            baseline_samples=baseline_samples,
            adaptive_ready=adaptive_ready,
            calibrating=calibrating,
            adaptive_z=float(self.adaptive_z),
            adaptive_floor=float(self.adaptive_floor),
        )


def _probability_stats(values: Deque[float]) -> tuple[int, Optional[float], Optional[float], Optional[float]]:
    samples = len(values)
    if samples == 0:
        return 0, None, None, None
    mean = sum(values) / samples
    variance = sum((value - mean) ** 2 for value in values) / samples
    return samples, float(mean), float(variance), float(math.sqrt(variance))


def _env_float(key: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_int(key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_choice(key: str, default: str, choices: set[str]) -> str:
    value = str(os.getenv(key, default) or default).strip().lower()
    return value if value in choices else default
