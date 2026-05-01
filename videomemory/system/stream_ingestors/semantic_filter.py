"""Optional semantic frame filtering for video ingestors."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

import cv2
import numpy as np

from .semantic_autogaze_runtime import GRID, MODEL_NAME, load_runtime


logger = logging.getLogger("VideoStreamIngestor")

ThresholdMode = Literal["absolute", "percentile"]
ReduceMode = Literal["max", "mean", "min", "sum", "softmax"]
EnsembleMode = Literal["off", "hflip", "hvflip"]


@dataclass(frozen=True)
class SemanticFilterConfig:
    enabled: bool = False
    keywords: str = ""
    threshold: float = 0.5
    threshold_mode: ThresholdMode = "absolute"
    reduce: ReduceMode = "max"
    smoothing: float = 0.0
    ensemble: EnsembleMode = "off"


@dataclass(frozen=True)
class SemanticFilterResult:
    should_keep: bool
    score: float
    threshold: float
    threshold_mode: ThresholdMode
    reduce: ReduceMode
    smoothing: float
    ensemble: EnsembleMode
    keywords: List[str]
    inference_ms: float
    overlay_frame: Optional[Any]
    error: Optional[str] = None


@dataclass(frozen=True)
class SemanticScore:
    per_keyword_scores: np.ndarray
    combined_scores: np.ndarray
    score: float
    cutoff: float
    should_keep: bool


def parse_keywords(text: str) -> List[str]:
    return [part.strip() for part in str(text or "").replace("\n", ",").split(",") if part.strip()]


def normalize_scores(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    minimum = float(values.min())
    maximum = float(values.max())
    if maximum <= minimum:
        return np.zeros_like(values)
    return (values - minimum) / (maximum - minimum)


def combine_scores(scores: np.ndarray, mode: str) -> np.ndarray:
    if scores.shape[1] == 0:
        return np.zeros(scores.shape[0], dtype=np.float32)
    if mode == "mean":
        return scores.mean(axis=1)
    if mode == "min":
        return scores.min(axis=1)
    if mode == "sum":
        return normalize_scores(scores.sum(axis=1))
    if mode == "softmax":
        shifted = scores - scores.max(axis=1, keepdims=True)
        weights = np.exp(shifted)
        weights = weights / np.maximum(weights.sum(axis=1, keepdims=True), 1e-8)
        return (weights * scores).sum(axis=1)
    return scores.max(axis=1)


def unflip_patch_scores(scores: np.ndarray, *, horizontal: bool = False, vertical: bool = False) -> np.ndarray:
    """Map flipped-frame patch scores back to the original camera orientation."""

    if scores.size == 0:
        return scores
    query_count = scores.shape[1]
    grid = scores.reshape(GRID, GRID, query_count)
    if horizontal:
        grid = np.flip(grid, axis=1)
    if vertical:
        grid = np.flip(grid, axis=0)
    return grid.reshape(GRID * GRID, query_count)


def ensemble_per_keyword_scores(runtime, frame_rgb: Any, text_embeddings, ensemble: str) -> np.ndarray:
    """Average original and flipped-frame scores for more stable heatmaps."""

    variants = [(frame_rgb, False, False)]
    if ensemble in {"hflip", "hvflip"}:
        variants.append((np.ascontiguousarray(np.flip(frame_rgb, axis=1)), True, False))
    if ensemble == "hvflip":
        variants.append((np.ascontiguousarray(np.flip(frame_rgb, axis=0)), False, True))

    aligned_scores = []
    for variant_rgb, horizontal, vertical in variants:
        scores = runtime.score_image_embeddings(variant_rgb, text_embeddings)
        aligned_scores.append(unflip_patch_scores(scores, horizontal=horizontal, vertical=vertical))
    return np.mean(aligned_scores, axis=0).astype(np.float32)


def evaluate_threshold(scores: np.ndarray, config: SemanticFilterConfig) -> tuple[float, bool]:
    """Return the effective cutoff and whether any patch passes it."""

    if scores.size == 0:
        return 0.0, False
    if config.threshold_mode == "absolute":
        cutoff = config.threshold
    else:
        cutoff = float(np.quantile(scores, config.threshold)) if config.threshold > 0 else 0.0
    return cutoff, bool((scores >= cutoff).any())


def smooth_scores(current_scores: np.ndarray, previous_scores: Optional[np.ndarray], smoothing: float) -> np.ndarray:
    """Apply temporal EMA smoothing to patch scores."""

    alpha = max(0.0, min(0.95, float(smoothing)))
    if alpha <= 0 or previous_scores is None or previous_scores.shape != current_scores.shape:
        return current_scores
    return (alpha * previous_scores) + ((1.0 - alpha) * current_scores)


def score_frame(runtime, frame: Any, text_embeddings, config: SemanticFilterConfig) -> SemanticScore:
    """Score a BGR frame and apply the semantic filter decision."""

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    per_keyword_scores = ensemble_per_keyword_scores(runtime, frame_rgb, text_embeddings, config.ensemble)
    combined_scores = combine_scores(per_keyword_scores, config.reduce)
    score = float(combined_scores.max()) if combined_scores.size else 0.0
    cutoff, should_keep = evaluate_threshold(combined_scores, config)
    return SemanticScore(
        per_keyword_scores=per_keyword_scores,
        combined_scores=combined_scores,
        score=score,
        cutoff=cutoff,
        should_keep=should_keep,
    )


def coerce_config(config: Dict[str, Any]) -> SemanticFilterConfig:
    threshold_mode = str(config.get("threshold_mode", "absolute")).strip().lower()
    if threshold_mode not in {"absolute", "percentile"}:
        threshold_mode = "absolute"

    reduce = str(config.get("reduce", "max")).strip().lower()
    if reduce not in {"max", "mean", "min", "sum", "softmax"}:
        reduce = "max"

    ensemble = str(config.get("ensemble", "off")).strip().lower()
    if ensemble not in {"off", "hflip", "hvflip"}:
        ensemble = "off"

    try:
        threshold = float(config.get("threshold", 0.5))
    except (TypeError, ValueError):
        threshold = 0.5
    threshold = max(0.0, min(1.0 if threshold_mode == "absolute" else 0.99, threshold))

    try:
        smoothing = float(config.get("smoothing", 0.0))
    except (TypeError, ValueError):
        smoothing = 0.0
    smoothing = max(0.0, min(0.95, smoothing))

    return SemanticFilterConfig(
        enabled=bool(config.get("enabled", False)),
        keywords=str(config.get("keywords", "") or ""),
        threshold=threshold,
        threshold_mode=threshold_mode,  # type: ignore[arg-type]
        reduce=reduce,  # type: ignore[arg-type]
        smoothing=smoothing,
        ensemble=ensemble,  # type: ignore[arg-type]
    )


class SemanticFrameFilter:
    """Lazy wrapper around the released semantic-autogaze scorer."""

    def __init__(self, config: Optional[SemanticFilterConfig] = None):
        self._config = config or SemanticFilterConfig()
        self._runtime = None
        self._text_embeddings = None
        self._encoded_keywords: List[str] = []
        self._smoothed_scores: Optional[np.ndarray] = None

    @property
    def config(self) -> SemanticFilterConfig:
        return self._config

    def update_config(self, config: SemanticFilterConfig) -> None:
        current = self._config
        if parse_keywords(config.keywords) != self._encoded_keywords:
            self._text_embeddings = None
            self._encoded_keywords = []
            self._smoothed_scores = None
        elif config.reduce != current.reduce or config.smoothing <= 0:
            self._smoothed_scores = None
        self._config = config

    def score(self, frame: Any) -> SemanticFilterResult:
        started_at = time.time()
        config = self._config
        keywords = parse_keywords(config.keywords)
        if not config.enabled or not keywords:
            return SemanticFilterResult(
                should_keep=True,
                score=0.0,
                threshold=config.threshold,
                threshold_mode=config.threshold_mode,
                reduce=config.reduce,
                smoothing=config.smoothing,
                ensemble=config.ensemble,
                keywords=keywords,
                inference_ms=0.0,
                overlay_frame=None,
            )

        try:
            runtime = self._get_runtime()
            embeddings = self._get_text_embeddings(runtime, keywords)
            scored_frame = score_frame(runtime, frame, embeddings, config)
            combined_scores = smooth_scores(scored_frame.combined_scores, self._smoothed_scores, config.smoothing)
            self._smoothed_scores = combined_scores.copy()
            score = float(combined_scores.max()) if combined_scores.size else 0.0
            cutoff, should_keep = evaluate_threshold(combined_scores, config)
            overlay = render_semantic_overlay(
                frame,
                combined_scores,
                threshold=config.threshold,
                threshold_mode=config.threshold_mode,
            )
            return SemanticFilterResult(
                should_keep=should_keep,
                score=score,
                threshold=cutoff,
                threshold_mode=config.threshold_mode,
                reduce=config.reduce,
                smoothing=config.smoothing,
                ensemble=config.ensemble,
                keywords=keywords,
                inference_ms=(time.time() - started_at) * 1000.0,
                overlay_frame=overlay,
            )
        except Exception as exc:
            message = str(exc)
            logger.error("Semantic frame filter failed; allowing frame through: %s", message, exc_info=True)
            return SemanticFilterResult(
                should_keep=True,
                score=0.0,
                threshold=config.threshold,
                threshold_mode=config.threshold_mode,
                reduce=config.reduce,
                smoothing=config.smoothing,
                ensemble=config.ensemble,
                keywords=keywords,
                inference_ms=(time.time() - started_at) * 1000.0,
                overlay_frame=None,
                error=message,
            )

    def _get_runtime(self):
        if self._runtime is None:
            self._runtime = load_runtime(device_name="auto")
        return self._runtime

    def _get_text_embeddings(self, runtime, keywords: List[str]):
        if self._text_embeddings is None or keywords != self._encoded_keywords:
            self._text_embeddings = runtime.encode_texts(keywords)
            self._encoded_keywords = list(keywords)
        return self._text_embeddings


def render_semantic_overlay(
    frame_bgr: Any,
    scores: np.ndarray,
    *,
    threshold: float,
    threshold_mode: str,
    alpha: float = 0.45,
) -> Any:
    height, width = frame_bgr.shape[:2]
    raw_grid = scores.reshape(GRID, GRID).astype(np.float32)
    display_grid = normalize_scores(raw_grid)
    if threshold_mode == "absolute":
        keep_grid = raw_grid >= float(threshold)
    else:
        cutoff = float(np.quantile(raw_grid.flatten(), threshold)) if threshold > 0 else 0.0
        keep_grid = raw_grid >= cutoff
    display_grid = np.where(keep_grid, 0.62 + (0.38 * display_grid), 0.18 + (0.22 * display_grid))

    heat = cv2.resize(display_grid, (width, height), interpolation=cv2.INTER_NEAREST)
    heat_bgr = cv2.applyColorMap(np.clip(heat * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    overlay = cv2.addWeighted(frame_bgr, 1.0 - alpha, heat_bgr, alpha, 0)
    for col in range(1, GRID):
        x = round(col * width / GRID)
        cv2.line(overlay, (x, 0), (x, height), (255, 255, 255), 1, cv2.LINE_AA)
    for row in range(1, GRID):
        y = round(row * height / GRID)
        cv2.line(overlay, (0, y), (width, y), (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(
        overlay,
        f"{MODEL_NAME} semantic filter",
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return overlay
