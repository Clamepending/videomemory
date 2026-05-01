# Semantic Autogaze Heatmap Demo

Small Streamlit experiment for trying keyword-driven patch relevance heatmaps before wiring anything into the VideoMemory frame filtering pipeline. The default scorer is the latest delivered `semantic-autogaze` model from the handoff: `v0.6.0-phase19-pi-demo` / `phase19b_convnext_atto_perquery_best_v060.pt`.

## Run

```bash
uv run streamlit run videomemory/experiments/semantic_autogaze_demo.py
```

The app supports five image sources:

- generated sample image
- uploaded image
- local image path
- local webcam via OpenCV, with optional live refresh
- a VideoMemory frame from `http://localhost:5050/api/device/{io_id}/capture` or `/preview`

## Trained Semantic Autogaze Scorer

The trained backend needs optional model dependencies:

```bash
uv pip install torch timm open_clip_torch
```

On first use, the app downloads the v0.6.0 checkpoint to:

```text
~/.cache/videomemory/semantic-autogaze/phase19b_convnext_atto_perquery_best_v060.pt
```

It first tries the release URL, then falls back to authenticated `gh release download` for private repo access.

This scorer emits a fixed `14x14` relevance grid, so the patch size and stride sliders are disabled for that backend.

## Optional CLIP Scorer

The demo has no new required project dependencies. If `torch` and `transformers` are available, choose **CLIP if available** in the sidebar and it will score each patch against prompts like `a photo of person`.

One local setup option:

```bash
uv pip install torch transformers pillow
```

If CLIP cannot load, the app falls back to a visual heuristic that is useful for exercising patch size, stride, threshold, blur, and overlay controls, but it is not a semantic model.

## Webcam Realtime Testing

Choose **Webcam (OpenCV)** as the image source. The app opens a local camera by index, reads one fresh frame per Streamlit rerun, and optionally auto-refreshes on a timer.

If the wrong camera opens, try camera index `1` or `2`. Lower patch counts help live refresh feel responsive, so start with a larger stride such as `160` while testing.

## Fast Webcam Stream

For realistic framerate testing, use the lower-overhead Flask/MJPEG demo instead of Streamlit:

```bash
uv run python videomemory/experiments/semantic_autogaze_fast_stream.py --cam 0 --port 8502
```

Then open `http://127.0.0.1:8502/`.

This path keeps the model and camera open, reuses text embeddings until keywords change, and reports stream FPS plus capture/inference/JPEG timing. On a MacBook, the model can be much faster than on a Pi, but the final live FPS may still be limited by the webcam mode and browser MJPEG rendering.

## Controls To Try

- **Keywords**: comma or newline separated text labels.
- **Patch size / stride**: controls the grid resolution and compute cost.
- **Combine keywords**: `max` highlights patches matching any keyword, `mean` favors patches matching all keywords.
- **Threshold mode**: percentile is usually easier when score calibration is unknown; absolute is useful once a model has stable scores.
- **Top patch boxes**: shows the highest scoring patches that survive the threshold.

## Production Integration

The production code now lives outside this experiments folder:

- Runtime/checkpoint loading: `videomemory/system/stream_ingestors/semantic_autogaze_runtime.py`
- Ingestor filter wrapper and shared scoring helpers: `videomemory/system/stream_ingestors/semantic_filter.py`

Keep this directory focused on manual demos and one-off experiments.
