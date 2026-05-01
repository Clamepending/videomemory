"""Low-overhead webcam stream for the shared semantic-autogaze scorer.

Run with:
    uv run python videomemory/experiments/semantic_autogaze_fast_stream.py --cam 0 --port 8502

This is intentionally not Streamlit. It keeps the webcam, model, and text
embeddings hot in one worker loop and serves an MJPEG stream to the browser.
"""

from __future__ import annotations

import argparse
import html
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from flask import Flask, Response, request

from videomemory.system.stream_ingestors.semantic_filter import combine_scores, normalize_scores, parse_keywords
from videomemory.system.stream_ingestors.semantic_autogaze_runtime import GRID, MODEL_NAME, load_runtime


REDUCE_MODES = {"max", "mean", "min", "sum", "softmax"}
THRESHOLD_MODES = {"percentile", "absolute"}


INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Semantic Autogaze Fast Stream</title>
  <style>
    :root { color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #0e1117; color: #f5f5f5; }
    main { display: grid; grid-template-columns: 340px 1fr; min-height: 100vh; }
    aside { padding: 22px; background: #171923; border-right: 1px solid #2b3040; }
    section { padding: 22px; }
    label { display: block; margin: 16px 0 6px; font-weight: 650; }
    input, select, button { box-sizing: border-box; width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #384052; background: #0f1320; color: #fff; }
    input[type="range"] { padding: 0; }
    button { margin-top: 18px; background: #ff4b4b; border: 0; font-weight: 700; cursor: pointer; }
    .metric-grid { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 10px; margin-bottom: 16px; }
    .metric { background: #171923; border: 1px solid #2b3040; border-radius: 10px; padding: 12px; }
    .metric div:first-child { color: #aab; font-size: 12px; text-transform: uppercase; }
    .metric div:last-child { font-size: 24px; font-weight: 800; margin-top: 4px; }
    img { display: block; max-width: 100%; border-radius: 14px; border: 1px solid #2b3040; background: #05060a; }
    code { color: #9ee493; }
    .hint { color: #aab; line-height: 1.4; font-size: 14px; }
  </style>
</head>
<body>
<main>
  <aside>
    <h2>Fast Stream Controls</h2>
    <p class="hint">Persistent camera + model loop. Text embeddings update only when keywords change.</p>
    <label>Keywords</label>
    <input id="keywords" value="person, face, hand">
    <label>Combine keywords</label>
    <select id="reduce">
      <option>max</option><option>mean</option><option>min</option><option>sum</option><option>softmax</option>
    </select>
    <label>Threshold mode</label>
    <select id="thresholdMode" onchange="updateThresholdMode()">
      <option value="absolute">absolute score</option>
      <option value="percentile">percentile</option>
    </select>
    <label><span id="thresholdLabel">Absolute score threshold</span>: <span id="thresholdValue">0.50</span></label>
    <input id="threshold" type="range" min="0" max="1" step="0.01" value="0.50">
    <label>Overlay alpha: <span id="alphaValue">0.45</span></label>
    <input id="alpha" type="range" min="0" max="1" step="0.05" value="0.45">
    <label>Top boxes: <span id="topKValue">10</span></label>
    <input id="topK" type="range" min="0" max="50" value="10">
    <button onclick="applyControls()">Apply</button>
    <p class="hint">If FPS is camera-limited, try lowering camera/display width when launching. 100 fps usually needs a high-FPS camera mode, not just a faster model.</p>
  </aside>
  <section>
    <h1>Semantic Autogaze Fast Stream</h1>
    <div class="metric-grid">
      <div class="metric"><div>Stream FPS</div><div id="fps">-</div></div>
      <div class="metric"><div>Infer ms</div><div id="inferMs">-</div></div>
      <div class="metric"><div>Capture ms</div><div id="captureMs">-</div></div>
      <div class="metric"><div>Encode ms</div><div id="encodeMs">-</div></div>
      <div class="metric"><div>Frame</div><div id="frameSize">-</div></div>
    </div>
    <img id="stream" src="/stream" alt="semantic autogaze stream">
    <p class="hint">Model: <code id="model">semantic-autogaze</code>. Camera: <code id="camera">0</code>. Device: <code id="device">auto</code>.</p>
  </section>
</main>
<script>
function bindValue(id, suffix = "") {
  const el = document.getElementById(id);
  const out = document.getElementById(id + "Value");
  const update = () => { out.textContent = el.value + suffix; };
  el.addEventListener("input", update);
  update();
}
["threshold", "alpha", "topK"].forEach(id => bindValue(id));

function updateThresholdMode() {
  const mode = document.getElementById("thresholdMode").value;
  const threshold = document.getElementById("threshold");
  const label = document.getElementById("thresholdLabel");
  if (mode === "percentile") {
    label.textContent = "Keep percentile and above";
    threshold.min = 0;
    threshold.max = 99;
    threshold.step = 1;
    threshold.value = Math.round(Number(threshold.value) * 100);
  } else {
    label.textContent = "Absolute score threshold";
    threshold.min = 0;
    threshold.max = 1;
    threshold.step = 0.01;
    if (Number(threshold.value) > 1) threshold.value = (Number(threshold.value) / 100).toFixed(2);
  }
  document.getElementById("thresholdValue").textContent = threshold.value;
}

async function applyControls() {
  const thresholdMode = document.getElementById("thresholdMode").value;
  const body = {
    keywords: document.getElementById("keywords").value,
    reduce: document.getElementById("reduce").value,
    threshold_mode: thresholdMode,
    threshold: thresholdMode === "percentile" ? Number(document.getElementById("threshold").value) / 100 : Number(document.getElementById("threshold").value),
    alpha: Number(document.getElementById("alpha").value),
    top_k: Number(document.getElementById("topK").value)
  };
  await fetch("/api/settings", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
}

async function refreshState() {
  const r = await fetch("/api/state");
  const s = await r.json();
  document.getElementById("fps").textContent = s.fps.toFixed(1);
  document.getElementById("inferMs").textContent = s.infer_ms.toFixed(1);
  document.getElementById("captureMs").textContent = s.capture_ms.toFixed(1);
  document.getElementById("encodeMs").textContent = s.encode_ms.toFixed(1);
  document.getElementById("frameSize").textContent = s.frame_width + "x" + s.frame_height;
  document.getElementById("model").textContent = s.model;
  document.getElementById("camera").textContent = s.camera_index;
  document.getElementById("device").textContent = s.device;
  document.getElementById("thresholdMode").value = s.threshold_mode;
}
setInterval(refreshState, 500);
updateThresholdMode();
refreshState();
</script>
</body>
</html>
"""


@dataclass
class StreamState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    keywords: list[str] = field(default_factory=lambda: ["person", "face", "hand"])
    reduce: str = "max"
    threshold_mode: str = "absolute"
    threshold: float = 0.50
    alpha: float = 0.45
    top_k: int = 10
    text_embs: Any = None
    last_jpeg: bytes | None = None
    fps: float = 0.0
    infer_ms: float = 0.0
    capture_ms: float = 0.0
    encode_ms: float = 0.0
    frame_width: int = 0
    frame_height: int = 0
    error: str = ""


def ema(previous: float, current: float, weight: float = 0.12) -> float:
    return current if previous <= 0 else previous * (1.0 - weight) + current * weight


def render_overlay(
    frame_rgb: np.ndarray,
    scores: np.ndarray,
    *,
    threshold: float,
    threshold_mode: str,
    alpha: float,
    top_k: int,
) -> np.ndarray:
    height, width = frame_rgb.shape[:2]
    raw_grid = scores.reshape(GRID, GRID).astype(np.float32)
    display_grid = normalize_scores(raw_grid)
    if threshold_mode == "absolute":
        cutoff = float(threshold)
        keep_grid = raw_grid >= cutoff
    else:
        cutoff = float(np.quantile(raw_grid.flatten(), threshold)) if threshold > 0 else 0.0
        keep_grid = raw_grid >= cutoff
    display_grid = np.where(keep_grid, display_grid, 0.0)

    heat = cv2.resize(display_grid, (width, height), interpolation=cv2.INTER_NEAREST)
    heat = normalize_scores(heat)
    heat_bgr = cv2.applyColorMap(np.clip(heat * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    heat_rgb = cv2.cvtColor(heat_bgr, cv2.COLOR_BGR2RGB)
    overlay = cv2.addWeighted(frame_rgb, 1.0 - alpha, heat_rgb, alpha, 0)

    if threshold > 0:
        keep_mask = cv2.resize(keep_grid.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST).astype(bool)
        dim = (frame_rgb * 0.35).astype(np.uint8)
        overlay = np.where(keep_mask[..., None], overlay, dim)

    if top_k > 0:
        ranked = np.argsort(scores)[::-1][:top_k]
        for patch_index in ranked:
            row = int(patch_index) // GRID
            col = int(patch_index) % GRID
            x0 = round(col * width / GRID)
            y0 = round(row * height / GRID)
            x1 = round((col + 1) * width / GRID)
            y1 = round((row + 1) * height / GRID)
            cv2.rectangle(overlay, (x0, y0), (x1, y1), (255, 255, 255), 1)
    return overlay


def resize_display(frame_bgr: np.ndarray, display_width: int) -> np.ndarray:
    if display_width <= 0:
        return frame_bgr
    height, width = frame_bgr.shape[:2]
    if width <= display_width:
        return frame_bgr
    scale = display_width / width
    display_size = (display_width, max(1, int(height * scale)))
    return cv2.resize(frame_bgr, display_size, interpolation=cv2.INTER_AREA)


def create_app(args: argparse.Namespace, state: StreamState) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return INDEX_HTML.replace("semantic-autogaze", html.escape(MODEL_NAME))

    @app.get("/stream")
    def stream():
        def generate():
            while True:
                with state.lock:
                    jpeg = state.last_jpeg
                if jpeg is None:
                    time.sleep(0.01)
                    continue
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode("ascii")
                    + b"\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
                time.sleep(1.0 / max(1.0, args.stream_fps_cap))

        return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/state")
    def api_state():
        with state.lock:
            return {
                "model": MODEL_NAME,
                "camera_index": args.cam,
                "device": args.device,
                "keywords": state.keywords,
                "reduce": state.reduce,
                "threshold_mode": state.threshold_mode,
                "threshold": state.threshold,
                "alpha": state.alpha,
                "top_k": state.top_k,
                "fps": state.fps,
                "infer_ms": state.infer_ms,
                "capture_ms": state.capture_ms,
                "encode_ms": state.encode_ms,
                "frame_width": state.frame_width,
                "frame_height": state.frame_height,
                "error": state.error,
            }

    @app.post("/api/settings")
    def api_settings():
        payload = request.get_json(force=True, silent=True) or {}
        with state.lock:
            if "keywords" in payload:
                keywords = parse_keywords(str(payload["keywords"]))
                if keywords:
                    state.keywords = keywords
            if "reduce" in payload and payload["reduce"] in REDUCE_MODES:
                state.reduce = payload["reduce"]
            if "threshold_mode" in payload and payload["threshold_mode"] in THRESHOLD_MODES:
                state.threshold_mode = payload["threshold_mode"]
            if "threshold" in payload:
                if state.threshold_mode == "absolute":
                    state.threshold = max(0.0, min(1.0, float(payload["threshold"])))
                else:
                    state.threshold = max(0.0, min(0.99, float(payload["threshold"])))
            if "alpha" in payload:
                state.alpha = max(0.0, min(1.0, float(payload["alpha"])))
            if "top_k" in payload:
                state.top_k = max(0, min(50, int(payload["top_k"])))
            keywords = list(state.keywords)

        # Re-encode outside the lock so the stream does not stall on CLIP text encoding.
        runtime = app.config["runtime_ref"]
        text_embs = runtime.encode_texts(keywords)
        with state.lock:
            state.text_embs = text_embs
        return api_state()

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cam", type=int, default=0)
    parser.add_argument("--cam-w", type=int, default=1280)
    parser.add_argument("--cam-h", type=int, default=720)
    parser.add_argument("--cam-fps", type=int, default=60)
    parser.add_argument("--display-width", type=int, default=960)
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "mps"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--jpeg-quality", type=int, default=75)
    parser.add_argument("--stream-fps-cap", type=float, default=120.0)
    args = parser.parse_args()

    state = StreamState()

    # Load once in the main thread so startup errors surface before Flask serves.
    runtime = load_runtime(device_name=args.device)
    state.text_embs = runtime.encode_texts(state.keywords)

    def worker_with_runtime():
        # Reuse the already-loaded runtime in the worker.
        cap = cv2.VideoCapture(args.cam)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if args.cam_w > 0:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.cam_w)
        if args.cam_h > 0:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.cam_h)
        if args.cam_fps > 0:
            cap.set(cv2.CAP_PROP_FPS, args.cam_fps)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open camera index {args.cam}")

        last_frame_at = time.perf_counter()
        while True:
            capture_start = time.perf_counter()
            ok, frame_bgr = cap.read()
            capture_ms = (time.perf_counter() - capture_start) * 1000.0
            if not ok or frame_bgr is None:
                with state.lock:
                    state.error = "camera read failed"
                time.sleep(0.02)
                continue

            frame_bgr = resize_display(frame_bgr, args.display_width)
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            with state.lock:
                text_embs = state.text_embs
                reduce_mode = state.reduce
                threshold_mode = state.threshold_mode
                threshold = state.threshold
                alpha = state.alpha
                top_k = state.top_k
                keywords = list(state.keywords)

            infer_start = time.perf_counter()
            per_query_scores = runtime.score_image_embeddings(frame_rgb, text_embs)
            combined = combine_scores(per_query_scores, reduce_mode)
            infer_ms = (time.perf_counter() - infer_start) * 1000.0

            overlay = render_overlay(
                frame_rgb,
                combined,
                threshold=threshold,
                threshold_mode=threshold_mode,
                alpha=alpha,
                top_k=top_k,
            )
            now = time.perf_counter()
            dt = max(1e-6, now - last_frame_at)
            last_frame_at = now
            fps = 1.0 / dt

            cv2.putText(
                overlay,
                f"{fps:.1f} fps | infer {infer_ms:.1f} ms | {', '.join(keywords)}",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            encode_start = time.perf_counter()
            ok_jpeg, jpeg = cv2.imencode(
                ".jpg",
                cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR),
                [int(cv2.IMWRITE_JPEG_QUALITY), args.jpeg_quality],
            )
            encode_ms = (time.perf_counter() - encode_start) * 1000.0
            if not ok_jpeg:
                continue

            with state.lock:
                state.last_jpeg = jpeg.tobytes()
                state.fps = ema(state.fps, fps)
                state.infer_ms = ema(state.infer_ms, infer_ms)
                state.capture_ms = ema(state.capture_ms, capture_ms)
                state.encode_ms = ema(state.encode_ms, encode_ms)
                state.frame_width = int(overlay.shape[1])
                state.frame_height = int(overlay.shape[0])
                state.error = ""

    thread = threading.Thread(target=worker_with_runtime, daemon=True)
    thread.start()

    app = create_app(args, state)
    app.config["runtime_ref"] = runtime
    print(f"Fast semantic-autogaze stream: http://{args.host}:{args.port}/", flush=True)
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
