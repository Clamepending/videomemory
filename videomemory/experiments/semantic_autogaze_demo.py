"""Interactive semantic-autogaze heatmap experiment.

Run with:
    uv run streamlit run videomemory/experiments/semantic_autogaze_demo.py

The primary backend is the shared production semantic-autogaze runtime. Optional
CLIP and visual-fallback modes remain here for quick comparison/debugging.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import time
from typing import Iterable, Literal

import cv2
import httpx
import numpy as np
import streamlit as st
from PIL import Image

from videomemory.system.stream_ingestors.semantic_filter import combine_scores, normalize_scores, parse_keywords
from videomemory.system.stream_ingestors.semantic_autogaze_runtime import (
    DEFAULT_CHECKPOINT_PATH,
    GRID as SEMANTIC_AUTOGAZE_GRID,
    INSTALL_COMMAND as SEMANTIC_AUTOGAZE_INSTALL_COMMAND,
    MODEL_NAME as SEMANTIC_AUTOGAZE_MODEL_NAME,
    load_runtime as load_semantic_autogaze_runtime,
)


DEFAULT_KEYWORDS = "person, face, red object"
MAX_WORKING_SIDE = 900
CLIP_INSTALL_COMMAND = "uv pip install torch transformers pillow"
SEMANTIC_AUTOGAZE_BACKEND = f"Semantic Autogaze ({SEMANTIC_AUTOGAZE_MODEL_NAME})"


@dataclass(frozen=True)
class Patch:
    x0: int
    y0: int
    x1: int
    y1: int


def resize_for_working_copy(image_rgb: np.ndarray, max_side: int = MAX_WORKING_SIDE) -> np.ndarray:
    height, width = image_rgb.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale >= 1.0:
        return image_rgb

    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return cv2.resize(image_rgb, new_size, interpolation=cv2.INTER_AREA)


def read_image_bytes(image_bytes: bytes) -> np.ndarray:
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    return np.asarray(image)


def load_image_from_path(path_text: str) -> np.ndarray:
    path = Path(path_text).expanduser()
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image from {path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def fetch_videomemory_frame(base_url: str, io_id: str, mode: Literal["capture", "preview"]) -> np.ndarray:
    base_url = base_url.rstrip("/")
    endpoint = f"{base_url}/api/device/{io_id}/capture" if mode == "capture" else f"{base_url}/api/device/{io_id}/preview"
    response = httpx.request("POST" if mode == "capture" else "GET", endpoint, timeout=10.0)
    response.raise_for_status()
    return read_image_bytes(response.content)


def capture_webcam_frame(camera_index: int, warmup_frames: int = 2) -> np.ndarray:
    capture = cv2.VideoCapture(camera_index)
    if not capture.isOpened():
        raise ValueError(f"Could not open webcam index {camera_index}")

    try:
        frame = None
        for _ in range(max(1, warmup_frames)):
            ok, frame = capture.read()
            if not ok or frame is None:
                raise ValueError(f"Could not read a frame from webcam index {camera_index}")
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    finally:
        capture.release()


def create_sample_image() -> np.ndarray:
    image = np.full((560, 800, 3), 235, dtype=np.uint8)
    cv2.rectangle(image, (40, 80), (300, 360), (60, 130, 220), -1)
    cv2.circle(image, (540, 190), 95, (210, 70, 70), -1)
    cv2.rectangle(image, (500, 310), (740, 500), (70, 160, 80), -1)
    cv2.line(image, (70, 470), (740, 70), (30, 30, 30), 8)
    cv2.putText(image, "red", (485, 205), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(image, "blue", (95, 230), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(image, "green", (555, 420), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3, cv2.LINE_AA)
    return image


def iter_patches(width: int, height: int, patch_size: int, stride: int) -> list[Patch]:
    patches: list[Patch] = []
    patch_size = min(patch_size, width, height)
    for y0 in range(0, max(1, height - patch_size + 1), stride):
        for x0 in range(0, max(1, width - patch_size + 1), stride):
            patches.append(Patch(x0=x0, y0=y0, x1=x0 + patch_size, y1=y0 + patch_size))

    # Ensure the right and bottom edges are covered even when stride does not land there.
    edge_x = max(0, width - patch_size)
    edge_y = max(0, height - patch_size)
    edge_patches = [Patch(edge_x, p.y0, edge_x + patch_size, p.y1) for p in patches]
    edge_patches += [Patch(p.x0, edge_y, p.x1, edge_y + patch_size) for p in patches]
    edge_patches.append(Patch(edge_x, edge_y, edge_x + patch_size, edge_y + patch_size))

    unique = {(p.x0, p.y0, p.x1, p.y1): p for p in patches + edge_patches}
    return list(unique.values())


def iter_grid_patches(width: int, height: int, grid_size: int) -> list[Patch]:
    patches: list[Patch] = []
    for row in range(grid_size):
        y0 = round(row * height / grid_size)
        y1 = round((row + 1) * height / grid_size)
        for col in range(grid_size):
            x0 = round(col * width / grid_size)
            x1 = round((col + 1) * width / grid_size)
            patches.append(Patch(x0=x0, y0=y0, x1=x1, y1=y1))
    return patches


@st.cache_resource(show_spinner=False)
def load_clip_model(model_name: str):
    try:
        from transformers import CLIPModel, CLIPProcessor  # type: ignore
        import torch  # type: ignore
    except ModuleNotFoundError as exc:
        missing_name = exc.name or "torch/transformers"
        raise RuntimeError(
            f"Missing optional dependency '{missing_name}'. Install CLIP dependencies with: {CLIP_INSTALL_COMMAND}"
        ) from exc

    model = CLIPModel.from_pretrained(model_name)
    processor = CLIPProcessor.from_pretrained(model_name)
    device = "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu"
    model.to(device)
    model.eval()
    return model, processor, torch, device


@st.cache_resource(show_spinner=False)
def load_semantic_autogaze_model(checkpoint_path: str, device_name: str):
    checkpoint = Path(checkpoint_path).expanduser() if checkpoint_path else DEFAULT_CHECKPOINT_PATH
    return load_semantic_autogaze_runtime(checkpoint, device_name=device_name)


def score_with_clip(
    image_rgb: np.ndarray,
    patches: list[Patch],
    keywords: list[str],
    *,
    model_name: str,
    batch_size: int,
) -> np.ndarray:
    model, processor, torch, device = load_clip_model(model_name)
    prompts = [f"a photo of {keyword}" for keyword in keywords]
    text_inputs = processor(text=prompts, return_tensors="pt", padding=True).to(device)

    with torch.no_grad():
        text_features = model.get_text_features(**text_inputs)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)

    all_scores: list[np.ndarray] = []
    patch_images = [Image.fromarray(image_rgb[p.y0 : p.y1, p.x0 : p.x1]) for p in patches]
    progress = st.progress(0, text="Scoring patches with CLIP")
    for start in range(0, len(patch_images), batch_size):
        batch_images = patch_images[start : start + batch_size]
        image_inputs = processor(images=batch_images, return_tensors="pt", padding=True).to(device)
        with torch.no_grad():
            image_features = model.get_image_features(**image_inputs)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            scores = image_features @ text_features.T
        all_scores.append(scores.detach().cpu().numpy())
        progress.progress(min(1.0, (start + len(batch_images)) / len(patch_images)), text="Scoring patches with CLIP")
    progress.empty()

    # Map cosine similarity from roughly [-1, 1] into [0, 1] for intuitive sliders.
    return np.clip((np.vstack(all_scores) + 1.0) / 2.0, 0.0, 1.0)


def score_with_semantic_autogaze(
    image_rgb: np.ndarray,
    keywords: list[str],
    *,
    checkpoint_path: str,
    device_name: str,
) -> np.ndarray:
    runtime = load_semantic_autogaze_model(checkpoint_path, device_name)
    return runtime.score_image(image_rgb, keywords)


def score_with_visual_fallback(image_rgb: np.ndarray, patches: list[Patch], keywords: list[str]) -> np.ndarray:
    hsv = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 80, 160)
    scores = np.zeros((len(patches), len(keywords)), dtype=np.float32)

    for patch_index, patch in enumerate(patches):
        patch_rgb = image_rgb[patch.y0 : patch.y1, patch.x0 : patch.x1]
        patch_hsv = hsv[patch.y0 : patch.y1, patch.x0 : patch.x1]
        patch_gray = gray[patch.y0 : patch.y1, patch.x0 : patch.x1]
        patch_edges = edges[patch.y0 : patch.y1, patch.x0 : patch.x1]
        rgb_mean = patch_rgb.astype(np.float32).mean(axis=(0, 1)) / 255.0
        saturation = patch_hsv[:, :, 1].astype(np.float32).mean() / 255.0
        brightness = patch_gray.astype(np.float32).mean() / 255.0
        edge_density = (patch_edges > 0).mean()

        for keyword_index, keyword in enumerate(keywords):
            word = keyword.lower()
            if "red" in word:
                score = rgb_mean[0] - max(rgb_mean[1], rgb_mean[2]) * 0.55
            elif "green" in word:
                score = rgb_mean[1] - max(rgb_mean[0], rgb_mean[2]) * 0.55
            elif "blue" in word:
                score = rgb_mean[2] - max(rgb_mean[0], rgb_mean[1]) * 0.55
            elif "yellow" in word:
                score = min(rgb_mean[0], rgb_mean[1]) - rgb_mean[2] * 0.5
            elif "white" in word or "bright" in word:
                score = brightness
            elif "black" in word or "dark" in word:
                score = 1.0 - brightness
            elif "edge" in word or "line" in word or "text" in word:
                score = min(1.0, edge_density * 8.0)
            else:
                # Generic saliency-like fallback for unknown words.
                score = 0.55 * saturation + 0.45 * min(1.0, edge_density * 8.0)
            scores[patch_index, keyword_index] = float(np.clip(score, 0.0, 1.0))

    return scores


def build_heatmap(
    shape: tuple[int, int],
    patches: list[Patch],
    patch_scores: np.ndarray,
    *,
    threshold: float,
    threshold_mode: Literal["absolute", "percentile"],
) -> tuple[np.ndarray, np.ndarray, float]:
    height, width = shape
    normalized_scores = normalize_scores(patch_scores)
    cutoff = float(np.percentile(normalized_scores, threshold)) if threshold_mode == "percentile" else threshold
    kept_scores = np.where(normalized_scores >= cutoff, normalized_scores, 0.0)

    heatmap = np.zeros((height, width), dtype=np.float32)
    weights = np.zeros((height, width), dtype=np.float32)
    for patch, score in zip(patches, kept_scores):
        heatmap[patch.y0 : patch.y1, patch.x0 : patch.x1] += score
        weights[patch.y0 : patch.y1, patch.x0 : patch.x1] += 1.0

    heatmap = np.divide(heatmap, weights, out=np.zeros_like(heatmap), where=weights > 0)
    heatmap = normalize_scores(heatmap)
    return heatmap, kept_scores, cutoff


def overlay_heatmap(image_rgb: np.ndarray, heatmap: np.ndarray, alpha: float) -> np.ndarray:
    heatmap_uint8 = np.clip(heatmap * 255, 0, 255).astype(np.uint8)
    colored = cv2.applyColorMap(heatmap_uint8, cv2.COLORMAP_TURBO)
    colored = cv2.cvtColor(colored, cv2.COLOR_BGR2RGB)
    return cv2.addWeighted(image_rgb, 1.0 - alpha, colored, alpha, 0)


def draw_top_patches(
    image_rgb: np.ndarray,
    patches: list[Patch],
    scores: np.ndarray,
    *,
    top_k: int,
    cutoff: float,
) -> np.ndarray:
    annotated = image_rgb.copy()
    ranked = np.argsort(scores)[::-1]
    shown = 0
    for patch_index in ranked:
        score = float(scores[patch_index])
        if score <= 0.0 or score < cutoff:
            continue
        patch = patches[patch_index]
        cv2.rectangle(annotated, (patch.x0, patch.y0), (patch.x1, patch.y1), (255, 255, 255), 2)
        cv2.putText(
            annotated,
            f"{score:.2f}",
            (patch.x0 + 4, patch.y0 + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (20, 20, 20),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            annotated,
            f"{score:.2f}",
            (patch.x0 + 4, patch.y0 + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        shown += 1
        if shown >= top_k:
            break
    return annotated


def png_bytes(image_rgb: np.ndarray) -> bytes:
    success, encoded = cv2.imencode(".png", cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR))
    if not success:
        return b""
    return encoded.tobytes()


def render_score_table(patches: list[Patch], scores: np.ndarray, keywords: Iterable[str], kept_scores: np.ndarray) -> None:
    rows = []
    for patch_index in np.argsort(kept_scores)[::-1][:20]:
        patch = patches[int(patch_index)]
        row = {
            "rank_score": round(float(kept_scores[int(patch_index)]), 4),
            "x0": patch.x0,
            "y0": patch.y0,
            "x1": patch.x1,
            "y1": patch.y1,
        }
        for keyword_index, keyword in enumerate(keywords):
            row[keyword] = round(float(scores[int(patch_index), keyword_index]), 4)
        rows.append(row)
    st.dataframe(rows, width="stretch")


def main() -> None:
    st.set_page_config(page_title="Semantic Autogaze Heatmap Demo", layout="wide")
    st.title("Semantic Autogaze Patch Heatmap Demo")
    st.caption(
        "Prototype UI for testing keyword-driven patch relevance before considering frame-filter integration."
    )

    with st.sidebar:
        st.header("Image")
        source = st.radio(
            "Source",
            ["Sample image", "Upload image", "Local image path", "Webcam (OpenCV)", "VideoMemory frame"],
            index=3,
        )
        uploaded_file = None
        local_path = ""
        server_url = "http://localhost:5050"
        io_id = "0"
        frame_mode: Literal["capture", "preview"] = "capture"
        camera_index = 0
        webcam_warmup_frames = 2
        live_refresh = False
        refresh_ms = 1000
        semantic_checkpoint_path = str(DEFAULT_CHECKPOINT_PATH)
        semantic_device = "auto"

        if source == "Upload image":
            uploaded_file = st.file_uploader("Image file", type=["jpg", "jpeg", "png", "webp"])
        elif source == "Local image path":
            local_path = st.text_input("Path", value="")
        elif source == "Webcam (OpenCV)":
            camera_index = st.number_input("Camera index", min_value=0, max_value=20, value=0, step=1)
            webcam_warmup_frames = st.slider("Warmup frames", min_value=1, max_value=10, value=2)
            live_refresh = st.checkbox("Live refresh", value=True)
            refresh_ms = st.slider("Refresh interval ms", min_value=250, max_value=5000, value=1000, step=250)
            st.caption("Uses OpenCV from the machine running Streamlit. Try camera index 1 or 2 if 0 is not your webcam.")
        elif source == "VideoMemory frame":
            server_url = st.text_input("VideoMemory base URL", value=server_url)
            io_id = st.text_input("Device io_id", value=io_id)
            frame_mode = st.radio("Frame endpoint", ["capture", "preview"], horizontal=True)  # type: ignore[assignment]

        st.header("Model")
        backend = st.radio(
            "Patch scorer",
            [SEMANTIC_AUTOGAZE_BACKEND, "CLIP if available", "Visual fallback"],
            help="The trained semantic-autogaze backend uses the shared production runtime.",
        )
        if backend == SEMANTIC_AUTOGAZE_BACKEND:
            st.caption(
                f"Latest delivered model from the handoff: `{SEMANTIC_AUTOGAZE_MODEL_NAME}`. "
                f"Install optional deps if needed: `{SEMANTIC_AUTOGAZE_INSTALL_COMMAND}`"
            )
            semantic_checkpoint_path = st.text_input("Checkpoint path", value=semantic_checkpoint_path)
            semantic_device = st.selectbox("Device", ["auto", "cpu", "mps"], index=0)
        if backend == "CLIP if available":
            st.caption(f"If CLIP falls back, install optional deps: `{CLIP_INSTALL_COMMAND}`")
        clip_model = st.text_input("CLIP model", value="openai/clip-vit-base-patch32", disabled=backend != "CLIP if available")
        clip_batch_size = st.slider("CLIP batch size", min_value=4, max_value=128, value=32, step=4, disabled=backend != "CLIP if available")

        st.header("Patch Settings")
        keywords_text = st.text_area("Keywords", value=DEFAULT_KEYWORDS, height=90)
        patch_size = st.slider("Patch size", min_value=32, max_value=320, value=160, step=16, disabled=backend == SEMANTIC_AUTOGAZE_BACKEND)
        stride = st.slider("Stride", min_value=16, max_value=240, value=80, step=16, disabled=backend == SEMANTIC_AUTOGAZE_BACKEND)
        if backend == SEMANTIC_AUTOGAZE_BACKEND:
            st.caption(f"The trained model emits a fixed {SEMANTIC_AUTOGAZE_GRID}x{SEMANTIC_AUTOGAZE_GRID} patch grid.")
        combine_mode = st.radio("Combine keywords", ["max", "mean", "min", "sum", "softmax"], horizontal=True)

        st.header("Visualization")
        threshold_mode = st.radio("Threshold mode", ["percentile", "absolute"], horizontal=True)
        if threshold_mode == "percentile":
            threshold = st.slider("Keep percentile and above", min_value=0, max_value=99, value=75)
        else:
            threshold = st.slider("Absolute score cutoff", min_value=0.0, max_value=1.0, value=0.55, step=0.01)
        alpha = st.slider("Overlay alpha", min_value=0.0, max_value=1.0, value=0.45, step=0.05)
        top_k = st.slider("Top patch boxes", min_value=0, max_value=50, value=10)

    try:
        if source == "Sample image":
            image_rgb = create_sample_image()
        elif source == "Upload image":
            if uploaded_file is None:
                st.info("Upload an image to start.")
                return
            image_rgb = read_image_bytes(uploaded_file.getvalue())
        elif source == "Local image path":
            if not local_path.strip():
                st.info("Enter a local image path to start.")
                return
            image_rgb = load_image_from_path(local_path)
        elif source == "Webcam (OpenCV)":
            image_rgb = capture_webcam_frame(int(camera_index), warmup_frames=webcam_warmup_frames)
        else:
            image_rgb = fetch_videomemory_frame(server_url, io_id, frame_mode)
    except Exception as exc:
        st.error(f"Could not load image: {exc}")
        return

    image_rgb = resize_for_working_copy(image_rgb)
    keywords = parse_keywords(keywords_text)
    if not keywords:
        st.warning("Enter at least one keyword.")
        return

    height, width = image_rgb.shape[:2]
    if backend == SEMANTIC_AUTOGAZE_BACKEND:
        patches = iter_grid_patches(width, height, SEMANTIC_AUTOGAZE_GRID)
    else:
        patches = iter_patches(width, height, patch_size, stride)

    try:
        if backend == SEMANTIC_AUTOGAZE_BACKEND:
            with st.spinner("Loading/scoring with semantic-autogaze model"):
                scores = score_with_semantic_autogaze(
                    image_rgb,
                    keywords,
                    checkpoint_path=semantic_checkpoint_path,
                    device_name=semantic_device,
                )
            backend_label = SEMANTIC_AUTOGAZE_MODEL_NAME
        elif backend == "CLIP if available":
            scores = score_with_clip(image_rgb, patches, keywords, model_name=clip_model, batch_size=clip_batch_size)
            backend_label = f"CLIP: {clip_model}"
        else:
            scores = score_with_visual_fallback(image_rgb, patches, keywords)
            backend_label = "visual fallback"
    except Exception as exc:
        st.warning(f"{backend} failed, using visual fallback instead: {exc}")
        patches = iter_patches(width, height, patch_size, stride)
        scores = score_with_visual_fallback(image_rgb, patches, keywords)
        backend_label = "visual fallback"

    combined_scores = combine_scores(scores, combine_mode)
    heatmap, kept_scores, cutoff = build_heatmap(
        (height, width),
        patches,
        combined_scores,
        threshold=float(threshold),
        threshold_mode=threshold_mode,  # type: ignore[arg-type]
    )
    overlay = overlay_heatmap(image_rgb, heatmap, alpha)
    annotated_overlay = draw_top_patches(overlay, patches, kept_scores, top_k=top_k, cutoff=cutoff)

    metric_cols = st.columns(4)
    metric_cols[0].metric("Scorer", backend_label)
    metric_cols[1].metric("Patches", f"{len(patches):,}")
    metric_cols[2].metric("Cutoff", f"{cutoff:.3f}")
    metric_cols[3].metric("Kept patches", f"{int((kept_scores > 0).sum()):,}")

    image_cols = st.columns(3)
    image_cols[0].subheader("Input")
    image_cols[0].image(image_rgb, width="stretch")
    image_cols[1].subheader("Heatmap")
    image_cols[1].image(overlay, width="stretch")
    image_cols[2].subheader("Top Patches")
    image_cols[2].image(annotated_overlay, width="stretch")

    st.download_button(
        "Download annotated heatmap PNG",
        data=png_bytes(annotated_overlay),
        file_name="semantic_autogaze_heatmap.png",
        mime="image/png",
    )

    st.subheader("Top Patch Scores")
    render_score_table(patches, scores, keywords, kept_scores)

    if source == "Webcam (OpenCV)" and live_refresh:
        time.sleep(refresh_ms / 1000.0)
        st.rerun()


if __name__ == "__main__":
    main()
