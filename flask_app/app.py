#!/usr/bin/env python3
"""Flask app for VideoMemory core APIs and UI."""

import asyncio
import base64
import csv
import hashlib
import io
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Add parent directory to path so we can import videomemory
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, render_template, request, jsonify, Response, redirect, send_file, url_for
from dotenv import load_dotenv
import videomemory.system
import videomemory.tools
from videomemory.system.logging_config import setup_logging
from videomemory.system.model_providers import get_VLM_provider
from videomemory.system.stream_ingestors.video_stream_ingestor import build_video_ingestor_prompt
from videomemory.system.model_providers.factory import (
    choose_default_model_for_available_keys,
    get_required_api_key_env,
    get_supported_model_names,
    normalize_model_name,
    validate_model_name,
)
from videomemory.system.database import TaskDatabase, get_default_data_dir
from videomemory.system.openclaw_integration import OpenClawWebhookDispatcher
from videomemory.system.usage import build_usage_dashboard_payload
from videomemory.system.update_check import DEFAULT_UPDATE_MANIFEST_URL, build_update_payload
import cv2
import platform
from typing import Any, Dict, List, Optional
import logging
import numpy as np
import requests
import httpx
from pydantic import BaseModel, Field
from videomemory.system.io_manager.url_utils import is_snapshot_url

flask_logger = logging.getLogger('FlaskApp')

# Load environment variables
load_dotenv()

# Initialize logging
setup_logging()

REPO_ROOT = Path(__file__).resolve().parent.parent
app = Flask(__name__)
_version_cache_lock = threading.Lock()
_version_cache: Dict[str, Any] = {
    "expires_at": 0.0,
    "payload": None,
}


def _apply_no_store_headers(response: Response) -> Response:
    """Prevent browsers from caching live debug UI pages and payloads."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_version_payload(force_refresh: bool = False) -> Dict[str, Any]:
    """Return a cached, offline-safe update-check payload for the header UI."""
    if _env_truthy("VIDEOMEMORY_UPDATE_CHECK_DISABLED"):
        payload = build_update_payload(REPO_ROOT, manifest_url="")
        payload["update_check_disabled"] = True
        return payload

    now = time.time()
    cache_ttl_s = max(0.0, _float_env("VIDEOMEMORY_UPDATE_CACHE_TTL_S", 600.0))
    with _version_cache_lock:
        cached_payload = _version_cache.get("payload")
        if (
            not force_refresh
            and cached_payload is not None
            and now < float(_version_cache.get("expires_at") or 0.0)
        ):
            return dict(cached_payload)

    manifest_url = os.environ.get("VIDEOMEMORY_UPDATE_MANIFEST_URL", DEFAULT_UPDATE_MANIFEST_URL)
    fetch_timeout_s = max(0.1, _float_env("VIDEOMEMORY_UPDATE_TIMEOUT_S", 2.0))
    payload = build_update_payload(
        REPO_ROOT,
        manifest_url=manifest_url,
        fetch_timeout_s=fetch_timeout_s,
    )

    with _version_cache_lock:
        _version_cache["payload"] = dict(payload)
        _version_cache["expires_at"] = time.time() + cache_ttl_s

    return payload


@app.after_request
def add_no_store_headers_for_debug_routes(response: Response) -> Response:
    """Ensure the debug UI and its polling APIs always reflect the current deploy."""
    path = request.path or ""
    if (path.startswith("/device/") and path.endswith("/debug")) or (
        path.startswith("/api/device/") and "/debug/" in path
    ):
        return _apply_no_store_headers(response)
    return response


# Create a persistent event loop in a background thread before TaskManager startup.
# Persisted active tasks may resume during TaskManager initialization, so the
# ingestor module needs a running loop available immediately.
background_loop = None
background_thread = None


def run_background_loop(loop):
    """Run the event loop in a background thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def get_background_loop():
    """Get or create the background event loop."""
    global background_loop, background_thread
    if background_loop is None or background_loop.is_closed():
        background_loop = asyncio.new_event_loop()
        background_thread = threading.Thread(
            target=run_background_loop,
            args=(background_loop,),
            daemon=True,
            name="FlaskBackgroundEventLoop"
        )
        background_thread.start()
        time.sleep(0.1)
    return background_loop


# Initialize the background loop and expose it to the ingestor module before
# any tasks are resumed from the database.
background_loop = get_background_loop()
import videomemory.system.stream_ingestors.video_stream_ingestor as vsi_module
vsi_module._flask_background_loop = background_loop

# ── Database setup ────────────────────────────────────────────
data_dir = get_default_data_dir()
data_dir.mkdir(parents=True, exist_ok=True)

db = TaskDatabase(str(data_dir / 'videomemory.db'))

# Load saved settings into os.environ BEFORE initializing providers
# This allows DB-stored API keys and config to override .env values
db.load_settings_to_env()

# ── System components ─────────────────────────────────────────
io_manager = videomemory.system.IOmanager(db=db)
model_provider = get_VLM_provider()
openclaw_dispatcher = OpenClawWebhookDispatcher()
task_manager = videomemory.system.TaskManager(
    io_manager=io_manager,
    model_provider=model_provider,
    db=db,
    on_detection_event=openclaw_dispatcher.dispatch_task_update,
    on_model_usage=db.save_model_usage_event,
)

# Set managers in tools
videomemory.tools.tasks.set_managers(io_manager, task_manager)

# Per-device preview stream FPS state (used by Devices page UI).
_preview_fps_lock = threading.Lock()
_preview_fps_state = {}
_direct_camera_capture_locks_guard = threading.Lock()
_direct_camera_capture_locks: Dict[str, threading.Lock] = {}
_capture_cleanup_lock = threading.Lock()
_last_capture_cleanup_at = 0.0
_local_preview_ingestor_lock = threading.Lock()
_local_preview_ingestor_leases: Dict[str, int] = {}


def _record_preview_frame(io_id: str) -> None:
    import time
    now = time.monotonic()
    with _preview_fps_lock:
        state = _preview_fps_state.get(io_id)
        if state is None:
            _preview_fps_state[io_id] = {
                "window_start": now,
                "frames": 1,
                "fps": 0.0,
                "last_frame_at": now,
            }
            return

        state["frames"] += 1
        state["last_frame_at"] = now
        elapsed = now - state["window_start"]
        if elapsed >= 1.0:
            instant_fps = state["frames"] / max(0.001, elapsed)
            state["fps"] = (state["fps"] * 0.7 + instant_fps * 0.3) if state["fps"] > 0 else instant_fps
            state["window_start"] = now
            state["frames"] = 0


def _get_preview_fps(io_id: str) -> float:
    import time
    now = time.monotonic()
    with _preview_fps_lock:
        state = _preview_fps_state.get(io_id)
        if not state:
            return 0.0
        last_age = now - state.get("last_frame_at", 0.0)
        if last_age > 3.0:
            return 0.0
        return float(state.get("fps", 0.0))


def _get_direct_camera_capture_lock(io_id: str) -> threading.Lock:
    """Return a per-device lock for ad hoc local-camera capture requests.

    Local USB cameras often reject overlapping opens from parallel Flask
    requests. Serializing direct capture keeps `/api/device/.../preview` and
    `/api/caption_frame` from racing each other when no ingestor is already
    holding fresh frames for reuse.
    """
    device_key = str(io_id or "")
    with _direct_camera_capture_locks_guard:
        lock = _direct_camera_capture_locks.get(device_key)
        if lock is None:
            lock = threading.Lock()
            _direct_camera_capture_locks[device_key] = lock
        return lock


def _device_has_active_tasks(io_id: str) -> bool:
    """Return whether a device currently has any active tasks."""
    try:
        return any(task.get("status") == "active" for task in task_manager.list_tasks(io_id))
    except Exception as e:
        flask_logger.debug("Failed to inspect active tasks for %s: %s", io_id, e, exc_info=True)
        return False


def _is_local_camera_device(device_info: Optional[Dict[str, Any]]) -> bool:
    """Return whether a device entry represents a directly-opened local camera."""
    if not device_info:
        return False
    if device_info.get("source") == "network":
        return False
    return not bool(device_info.get("pull_url") or device_info.get("url"))


def _wait_for_ingestor_frame(
    io_id: str,
    wait_timeout_s: float,
    *,
    minimum_mean: Optional[float] = 1.0,
) -> Optional[np.ndarray]:
    """Poll a shared ingestor briefly for its latest frame."""
    deadline = time.monotonic() + max(0.0, wait_timeout_s)
    while True:
        latest_frame = task_manager.get_latest_frame_for_device(io_id)
        if latest_frame is not None and latest_frame.size > 0:
            if minimum_mean is None or latest_frame.mean() >= minimum_mean:
                return latest_frame
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


def _acquire_local_preview_ingestor(
    io_id: str,
    device_info: Optional[Dict[str, Any]],
) -> Optional[Any]:
    """Acquire a shared ingestor lease for a local camera preview/capture."""
    if not _is_local_camera_device(device_info):
        return None

    with _local_preview_ingestor_lock:
        _local_preview_ingestor_leases[io_id] = _local_preview_ingestor_leases.get(io_id, 0) + 1
        ingestor = task_manager.ensure_device_ingestor(io_id, keep_alive_without_tasks=True)
        if ingestor is not None:
            return ingestor

        remaining_leases = _local_preview_ingestor_leases.get(io_id, 0) - 1
        if remaining_leases > 0:
            _local_preview_ingestor_leases[io_id] = remaining_leases
        else:
            _local_preview_ingestor_leases.pop(io_id, None)
        return None


def _release_local_preview_ingestor(io_id: str) -> None:
    """Release a shared ingestor lease held by a local camera preview/capture."""
    with _local_preview_ingestor_lock:
        lease_count = _local_preview_ingestor_leases.get(io_id, 0)
        if lease_count <= 0:
            return
        if lease_count > 1:
            _local_preview_ingestor_leases[io_id] = lease_count - 1
            return

        _local_preview_ingestor_leases.pop(io_id, None)
        ingestor = task_manager.get_ingestor(io_id)
        if ingestor is None:
            return

        try:
            ingestor.set_keep_alive_without_tasks(False)
        except Exception as e:
            flask_logger.debug(
                "Failed to reset keep_alive_without_tasks for local preview %s: %s",
                io_id,
                e,
                exc_info=True,
            )

        if not _device_has_active_tasks(io_id):
            task_manager.release_device_ingestor(io_id)


def _get_saved_capture_dir() -> Path:
    capture_dir = data_dir / "captures"
    capture_dir.mkdir(parents=True, exist_ok=True)
    return capture_dir


def _is_valid_capture_id(capture_id: str) -> bool:
    token = str(capture_id or "").strip()
    return bool(token) and all(ch.isalnum() or ch in {"-", "_"} for ch in token)


def _maybe_cleanup_saved_captures() -> None:
    """Best-effort pruning of old saved captures to avoid unbounded growth."""
    global _last_capture_cleanup_at

    now = time.time()
    with _capture_cleanup_lock:
        if now - _last_capture_cleanup_at < 60:
            return
        _last_capture_cleanup_at = now

    capture_dir = _get_saved_capture_dir()
    try:
        retention_s = max(0, int(os.getenv("VIDEOMEMORY_CAPTURE_RETENTION_SECONDS", "86400")))
    except ValueError:
        retention_s = 86400
    try:
        max_files = max(1, int(os.getenv("VIDEOMEMORY_CAPTURE_MAX_FILES", "200")))
    except ValueError:
        max_files = 200

    capture_files = sorted(
        capture_dir.glob("*.jpg"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    cutoff = now - retention_s if retention_s > 0 else None
    for index, path in enumerate(capture_files):
        should_delete = index >= max_files
        if cutoff is not None:
            try:
                should_delete = should_delete or path.stat().st_mtime < cutoff
            except FileNotFoundError:
                continue
        if not should_delete:
            continue
        try:
            path.unlink(missing_ok=True)
        except Exception:
            flask_logger.debug("Failed pruning saved capture %s", path, exc_info=True)


def _save_device_capture(io_id: str, frame_bytes: bytes, *, source: str) -> Dict[str, Any]:
    """Persist one fresh capture so chat integrations can fetch/send it later."""
    _maybe_cleanup_saved_captures()
    capture_dir = _get_saved_capture_dir()
    safe_io_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(io_id or "device")).strip("-_")
    safe_io_id = safe_io_id or "device"
    capture_id = f"{safe_io_id}-{int(time.time() * 1000)}-{os.urandom(4).hex()}"
    file_path = capture_dir / f"{capture_id}.jpg"
    file_path.write_bytes(frame_bytes)
    return {
        "capture_id": capture_id,
        "file_path": file_path,
        "source": source,
        "bytes": len(frame_bytes),
    }


def _get_latest_persisted_debug_snapshot(io_id: str) -> Optional[Dict[str, Any]]:
    """Load the newest persisted note-backed frame for a device, if available."""
    latest_task = None
    latest_note = None

    for task in task_manager.get_task_objects(io_id):
        for note in getattr(task, "task_note", []) or []:
            note_id = getattr(note, "note_id", None)
            frame_path = getattr(note, "frame_path", None)
            if note_id is None or not frame_path:
                continue
            if latest_note is None or note_id > latest_note.note_id:
                latest_task = task
                latest_note = note

    if latest_note is None:
        return None

    frame_path = db.get_note_frame_path(latest_note.note_id)
    if frame_path is None or not frame_path.exists():
        return None

    try:
        frame_bytes = frame_path.read_bytes()
    except OSError as exc:
        flask_logger.warning("Failed to read persisted debug frame for io_id=%s note_id=%s: %s", io_id, latest_note.note_id, exc)
        return None

    return {
        "task": latest_task,
        "note": latest_note,
        "frame_bytes": frame_bytes,
    }


def _build_device_debug_prompt(io_id: str, ingestor: Optional[Any] = None) -> str:
    """Return the canonical debug prompt for a device when task context exists."""
    tasks = []
    if ingestor is not None:
        try:
            tasks = ingestor.get_tasks_list() or []
        except Exception:
            tasks = []
    if not tasks:
        tasks = task_manager.get_task_objects(io_id)
    if not tasks:
        return ""

    prompt = build_video_ingestor_prompt(tasks, context_label=io_id)
    if prompt:
        return prompt
    return build_video_ingestor_prompt(tasks, context_label=io_id, include_done=True)

# ── Page routes ───────────────────────────────────────────────

@app.route('/')
def index():
    """Redirect to the device-focused UI."""
    return redirect('/devices')

@app.route('/tasks')
def tasks():
    """Render the tasks page."""
    return render_template('tasks.html')

@app.route('/task/<task_id>')
def task_detail(task_id):
    """Render the task detail page."""
    return render_template('task_detail.html', task_id=task_id)

@app.route('/devices')
def devices():
    """Render the devices page."""
    return render_template('devices.html')

@app.route('/settings')
def settings_page():
    """Render the settings page."""
    return render_template('settings.html')

@app.route('/usage')
def usage_page():
    """Render the usage page."""
    return render_template('usage.html')

@app.route('/storage')
def storage_page():
    """Render the storage page."""
    return render_template('storage.html')

@app.route('/documentation')
def documentation_page():
    """Render the documentation page."""
    return render_template('documentation.html')


@app.route('/openclaw/skill.md')
def openclaw_skill():
    """Serve the OpenClaw skill document over plain HTTP."""
    skill_path = Path(__file__).parent.parent / 'docs' / 'openclaw-skill.md'
    return send_file(skill_path, mimetype='text/markdown')


@app.route('/openclaw/videomemory-task-helper.mjs')
def openclaw_task_helper():
    """Serve the OpenClaw helper used for split trigger/action task setup."""
    helper_path = Path(__file__).parent.parent / 'docs' / 'openclaw-videomemory-task-helper.mjs'
    return send_file(helper_path, mimetype='text/javascript')


@app.route('/openclaw/bootstrap.sh')
def openclaw_bootstrap():
    """Serve the one-shot bootstrap script for existing OpenClaw installs."""
    script_path = Path(__file__).parent.parent / 'docs' / 'openclaw-bootstrap.sh'
    return send_file(script_path, mimetype='text/x-shellscript')


@app.route('/openclaw/install-videomemory.sh')
def openclaw_install_videomemory():
    """Serve the host-side VideoMemory installer used before Dockerized OpenClaw onboarding."""
    script_path = Path(__file__).parent.parent / 'docs' / 'install-videomemory.sh'
    return send_file(script_path, mimetype='text/x-shellscript')


@app.route('/openclaw/relaunch-videomemory.sh')
def openclaw_relaunch_videomemory():
    """Serve the host-side relaunch script used for upgrade + restart flows."""
    script_path = Path(__file__).parent.parent / 'docs' / 'relaunch-videomemory.sh'
    return send_file(script_path, mimetype='text/x-shellscript')

@app.route('/device/<io_id>/debug')
def device_debug(io_id):
    """Render the ingestor debug page for a device."""
    return render_template('ingestor_debug.html', io_id=io_id)

# ── Task API ──────────────────────────────────────────────────

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """List all tasks, optionally filtered by io_id.
    
    Query params:
        io_id (optional): Filter tasks to a specific input device.
    """
    try:
        io_id = request.args.get('io_id', None)
        tasks_list = task_manager.list_tasks(io_id)
        return jsonify({'status': 'success', 'tasks': tasks_list, 'count': len(tasks_list)})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/tasks', methods=['POST'])
def create_task():
    """Add a new task for an input device.
    
    Body (JSON):
        io_id (str, required): The unique identifier of the input device.
        task_description (str, required): A description of the task to perform.
        bot_id (str, optional): Identifier of the bot that created this task (multi-bot / debug).
    """
    try:
        data = request.json
        if not data:
            return jsonify({'status': 'error', 'error': 'Request body must be JSON'}), 400
        
        io_id = data.get('io_id', '').strip()
        task_description = data.get('task_description', '').strip()
        bot_id = data.get('bot_id', '').strip() or None
        save_note_frames = _coerce_optional_boolean_request_value(data.get('save_note_frames'))
        save_note_videos = _coerce_optional_boolean_request_value(data.get('save_note_videos'))
        semantic_filter_config, semantic_filter_error = _parse_task_semantic_filter_config(data)
        
        if not io_id:
            return jsonify({'status': 'error', 'error': 'io_id is required'}), 400
        if not task_description:
            return jsonify({'status': 'error', 'error': 'task_description is required'}), 400
        if semantic_filter_error:
            return jsonify({'status': 'error', 'error': semantic_filter_error}), 400

        provider_error = _build_task_creation_model_error()
        if provider_error is not None:
            body, status_code = provider_error
            return jsonify(body), status_code
        
        result = videomemory.tools.tasks.add_task(
            io_id,
            task_description,
            bot_id=bot_id,
            save_note_frames=save_note_frames,
            save_note_videos=save_note_videos,
            semantic_filter_config=semantic_filter_config,
        )
        
        if result.get('status') == 'error':
            return jsonify(result), 400
        return jsonify(result), 201
    except Exception as e:
        flask_logger.error(f"Failed to create task: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/task/<task_id>', methods=['GET'])
def get_task(task_id):
    """Get detailed information about a specific task including notes and status."""
    try:
        task = task_manager.get_task(task_id)
        if task is None:
            return jsonify({'status': 'error', 'error': 'Task not found'}), 404
        return jsonify({'status': 'success', 'task': task})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/task/<task_id>', methods=['PUT'])
def update_task(task_id):
    """Edit/update a task's description.
    
    Body (JSON):
        new_description (str, required): The new description for the task.
        save_note_frames (bool, optional): Optional per-task override for saving note frames.
        save_note_videos (bool, optional): Optional per-task override for saving note videos.
    """
    try:
        data = request.json
        if not data:
            return jsonify({'status': 'error', 'error': 'Request body must be JSON'}), 400
        
        new_description = data.get('new_description', '').strip()
        save_note_frames = _coerce_optional_boolean_request_value(data.get('save_note_frames'))
        save_note_videos = _coerce_optional_boolean_request_value(data.get('save_note_videos'))
        if not new_description:
            return jsonify({'status': 'error', 'error': 'new_description is required'}), 400
        
        result = task_manager.edit_task(
            task_id,
            new_description,
            save_note_frames=save_note_frames,
            save_note_videos=save_note_videos,
        )
        
        if result.get('status') == 'error':
            return jsonify(result), 404 if 'not found' in result.get('message', '').lower() else 400
        return jsonify(result)
    except Exception as e:
        flask_logger.error(f"Failed to edit task {task_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/task/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    """Permanently delete a task and all its notes."""
    try:
        success = task_manager.remove_task(task_id)
        
        if success:
            return jsonify({
                'status': 'success',
                'message': f"Task '{task_id}' removed successfully",
                'task_id': task_id,
            })
        else:
            return jsonify({
                'status': 'error',
                'error': f"Task '{task_id}' not found",
                'task_id': task_id,
            }), 404
    except Exception as e:
        flask_logger.error(f"Failed to delete task {task_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/task/<task_id>/stop', methods=['POST'])
def stop_task_endpoint(task_id):
    """Stop a running task. The task is marked as done and its video processing
    is stopped, but the task and all its notes remain visible."""
    try:
        result = task_manager.stop_task(task_id)
        
        if result.get('status') == 'error':
            return jsonify(result), 404 if 'not found' in result.get('message', '').lower() else 400
        return jsonify(result)
    except Exception as e:
        flask_logger.error(f"Failed to stop task {task_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/task-note/<int:note_id>/frame', methods=['GET'])
def get_task_note_frame(note_id):
    """Serve the stored frame associated with a task note, if available."""
    try:
        frame_path = db.get_note_frame_path(note_id)
        if frame_path is None or not frame_path.exists():
            return Response(status=404)
        return send_file(
            frame_path,
            mimetype='image/jpeg',
            conditional=True,
            max_age=0,
        )
    except Exception as e:
        flask_logger.error(f"Failed to load task note frame {note_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/task-note/<int:note_id>/video', methods=['GET'])
def get_task_note_video(note_id):
    """Serve the stored evidence clip associated with a task note, if available."""
    try:
        video_path = db.get_note_video_path(note_id)
        if video_path is None or not video_path.exists():
            return Response(status=404)
        mimetype = 'video/mp4' if video_path.suffix.lower() == '.mp4' else 'video/x-msvideo'
        return send_file(
            video_path,
            mimetype=mimetype,
            conditional=True,
            max_age=0,
        )
    except Exception as e:
        flask_logger.error(f"Failed to load task note video {note_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500

# ── Device API ────────────────────────────────────────────────

def _get_camera_preview_frame(camera_index: int) -> Optional[bytes]:
    """Capture a preview frame from a camera.
    
    Shows whatever frame the camera produces, including black frames.
    This is useful for debugging device connections.
    
    Args:
        camera_index: The index of the camera
        
    Returns:
        JPEG image bytes, or None if capture failed (device disconnected/unavailable)
    """
    cap = None
    try:
        if platform.system() == 'Darwin':
            cap = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
        elif platform.system() == 'Linux':
            cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
        else:
            cap = cv2.VideoCapture(camera_index)
        
        if not cap.isOpened():
            return None  # Device not available
        
        # Read a few frames first to let camera initialize
        # Some cameras (especially built-in ones) produce black frames initially
        import time
        frame = None
        
        # Read initial frames without setting resolution first (avoids reset)
        for _ in range(3):
            ret, test_frame = cap.read()
            if ret and test_frame is not None and test_frame.size > 0:
                frame = test_frame
            time.sleep(0.05)
        
        # Now try to set resolution if we got a frame
        # Setting resolution can cause cameras to reset, so we do it after initial frames
        if frame is not None:
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                # Read a few more frames after setting resolution (camera may reset)
                for _ in range(5):
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None and test_frame.size > 0:
                        frame = test_frame  # Use latest frame
                    time.sleep(0.05)
            except Exception:
                pass  # Some cameras don't support setting resolution
        
        # If we still don't have a frame, try one more time
        if frame is None:
            ret, frame = cap.read()
            if not ret or frame is None or frame.size == 0:
                return None  # Device disconnected or not responding
        
        # Resize frame if needed (in case resolution setting didn't work)
        if frame.shape[1] > 640 or frame.shape[0] > 480:
            frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_LINEAR)
        
        # Show whatever frame we got, even if it's black (for debugging)
        # Encode as JPEG
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buffer.tobytes()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Error capturing preview from camera {camera_index}: {e}")
        return None  # Device error/disconnected
    finally:
        if cap is not None:
            cap.release()

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get all input devices."""
    try:
        # Force refresh by calling _refresh_streams directly
        # This ensures we get the latest devices even if they were just plugged in
        refresh_success = io_manager._refresh_streams()
        if not refresh_success:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Device refresh had issues: {io_manager._last_error}")
        
        # Skip refresh in list_all_streams since we just refreshed
        devices_list = io_manager.list_all_streams(skip_refresh=True)
        
        # Organize by category
        by_category = {}
        for device in devices_list:
            category = device.get('category', 'unknown')
            if category not in by_category:
                by_category[category] = []
            ingestor = task_manager.get_ingestor(device.get('io_id', ''))
            ingestor_running = bool(ingestor and getattr(ingestor, '_running', False))
            ingestor_state = 'running' if ingestor_running else ('stopped' if ingestor is not None else 'idle')
            entry = {
                'io_id': device.get('io_id', ''),
                'name': device.get('name', 'Unknown'),
                'source': device.get('source', 'local'),
                'ingestor_running': ingestor_running,
                'ingestor_state': ingestor_state,
            }
            if device.get('url'):
                entry['url'] = device['url']
            by_category[category].append(entry)
        
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Returning {len(devices_list)} devices: {by_category}")
        
        return jsonify({'devices': by_category})
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in get_devices: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500



@app.route('/api/devices/network', methods=['POST'])
def add_network_camera():
    """Add a network camera (RTSP or HTTP snapshot/stream)."""
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'error': 'Request body required'}), 400

    url = data.get('url', '').strip()
    name = data.get('name', '').strip() or None

    if not url:
        return jsonify({'status': 'error', 'error': 'url is required'}), 400

    parsed = urlparse(url)
    allowed_schemes = {'rtsp', 'rtsps', 'http', 'https'}
    if parsed.scheme.lower() not in allowed_schemes:
        return jsonify({
            'status': 'error',
            'error': "Invalid url: scheme must be one of rtsp, rtsps, http, https"
        }), 400
    if parsed.scheme.lower() in allowed_schemes and not parsed.netloc:
        return jsonify({'status': 'error', 'error': 'Invalid url: missing host'}), 400

    try:
        camera_info = io_manager.add_network_camera(url, name)
        response_body = {'status': 'success', 'device': camera_info}
        try:
            task_manager.ensure_device_ingestor(camera_info["io_id"])
        except Exception as warm_exc:
            flask_logger.warning(
                "Network camera %s was added, but its warm preview ingestor did not start yet: %s",
                camera_info.get("io_id"),
                warm_exc,
                exc_info=True,
            )
            response_body["warning"] = (
                "Camera saved, but the background preview reader could not start yet. "
                "The preview will retry automatically the next time you open the device."
            )
        return jsonify(response_body)
    except Exception as e:
        flask_logger.error(f"Error adding network camera: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/devices/network/<io_id>', methods=['DELETE'])
def remove_network_camera(io_id):
    """Remove a network camera."""
    # Stop any active tasks for this device first
    active_tasks = [t for t in task_manager.list_tasks(io_id) if t.get('status') == 'active']
    for t in active_tasks:
        task_manager.stop_task(t['task_id'])

    task_manager.release_device_ingestor(io_id)

    if io_manager.remove_network_camera(io_id):
        return jsonify({'status': 'success', 'message': f'Network camera {io_id} removed'})
    return jsonify({'status': 'error', 'error': f'Network camera {io_id} not found'}), 404


def _get_network_preview_frame(url: str) -> Optional[bytes]:
    """Capture a single preview frame from a network stream URL.

    This path is used by the Devices page; fail fast so one dead stream doesn't
    stall all preview requests.
    """
    if is_snapshot_url(url):
        try:
            response = requests.get(
                url,
                timeout=(
                    float(os.environ.get("VIDEOMEMORY_PREVIEW_SNAPSHOT_CONNECT_TIMEOUT_S", "2.5")),
                    float(os.environ.get("VIDEOMEMORY_PREVIEW_SNAPSHOT_READ_TIMEOUT_S", "2.5")),
                ),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                },
            )
            response.raise_for_status()
            frame_array = cv2.imdecode(
                np.frombuffer(response.content, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            if frame_array is None or frame_array.size == 0:
                return None
            if frame_array.shape[1] > 640 or frame_array.shape[0] > 480:
                frame_array = cv2.resize(frame_array, (640, 480), interpolation=cv2.INTER_LINEAR)
            _, buffer = cv2.imencode('.jpg', frame_array, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return buffer.tobytes()
        except Exception as e:
            flask_logger.debug(f"Error fetching snapshot preview from {url}: {e}")
            return None

    cap = None
    try:
        # Favor low-latency RTSP reads for preview snapshots.
        if not os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS"):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|"
                "max_delay;500000|reorder_queue_size;0"
            )
        open_timeout_ms = int(os.environ.get("VIDEOMEMORY_PREVIEW_OPEN_TIMEOUT_MS", "2500"))
        read_timeout_ms = int(os.environ.get("VIDEOMEMORY_PREVIEW_READ_TIMEOUT_MS", "2500"))
        drain_seconds = float(os.environ.get("VIDEOMEMORY_PREVIEW_DRAIN_SECONDS", "0.35"))
        cap = cv2.VideoCapture()
        if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, float(open_timeout_ms))
        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, float(read_timeout_ms))
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        opened = cap.open(url, cv2.CAP_FFMPEG) if hasattr(cv2, "CAP_FFMPEG") else cap.open(url)
        if not opened or not cap.isOpened():
            return None

        # Drain buffered frames briefly and keep the newest one.
        frame = None
        import time
        deadline = time.monotonic() + max(0.05, drain_seconds)
        while time.monotonic() < deadline:
            ret, test_frame = cap.read()
            if ret and test_frame is not None and test_frame.size > 0:
                frame = test_frame
                continue
            time.sleep(0.01)
        if frame is None:
            return None
        if frame.shape[1] > 640 or frame.shape[0] > 480:
            frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_LINEAR)
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buffer.tobytes()
    except Exception as e:
        flask_logger.debug(f"Error capturing preview from network stream {url}: {e}")
        return None
    finally:
        if cap is not None:
            cap.release()


def _ensure_network_camera_ingestor(
    io_id: str,
    device_info: Optional[Dict[str, Any]],
    *,
    wait_timeout_s: float = 0.0,
) -> Optional[np.ndarray]:
    """Warm a background ingestor for a network camera and optionally wait for a frame."""
    if device_info is None or _is_local_camera_device(device_info):
        return None

    try:
        task_manager.ensure_device_ingestor(io_id)
    except Exception as e:
        flask_logger.debug("Error warming network camera ingestor for %s: %s", io_id, e, exc_info=True)
        return None

    if wait_timeout_s <= 0:
        return None

    return _wait_for_ingestor_frame(io_id, wait_timeout_s, minimum_mean=1.0)


@app.route('/api/device/<io_id>/preview', methods=['GET'])
def get_device_preview(io_id):
    """Get a preview image from a camera device.
    
    Only works for camera devices. Returns a placeholder or error for other devices.
    Tries to use frames from active video ingestors first and, for local cameras,
    briefly warms a shared ingestor instead of opening the device independently.
    """
    frame_data = _get_device_preview_frame_bytes(io_id)
    if frame_data is None:
        return Response(response=b'', status=404, mimetype='image/jpeg')
    return Response(
        response=frame_data,
        mimetype='image/jpeg',
        headers={'Cache-Control': 'no-cache, no-store, must-revalidate'}
    )


def _get_device_preview_frame_bytes(io_id: str) -> Optional[bytes]:
    """Return the latest JPEG preview frame for a camera device."""
    try:
        device_info = io_manager.get_stream_info(io_id)
        if device_info is None:
            return None

        category = device_info.get('category', '').lower()
        if 'camera' not in category:
            return None

        is_local_camera = _is_local_camera_device(device_info)
        local_preview_warmup_s = max(
            0.0,
            float(os.getenv("VIDEOMEMORY_LOCAL_PREVIEW_WARMUP_S", "1.0")),
        )

        # Try active ingestor frame first for lower latency and less camera churn.
        latest_frame = task_manager.get_latest_frame_for_device(io_id)
        if (
            latest_frame is None or latest_frame.size == 0 or (
                not is_local_camera and latest_frame.mean() < 1
            )
        ) and not is_local_camera:
            latest_frame = _ensure_network_camera_ingestor(
                io_id,
                device_info,
                wait_timeout_s=max(
                    0.0,
                    float(os.getenv("VIDEOMEMORY_NETWORK_PREVIEW_WARMUP_S", "0.75")),
                ),
            )
        elif latest_frame is None or latest_frame.size == 0:
            preview_ingestor = _acquire_local_preview_ingestor(io_id, device_info) if is_local_camera else None
            try:
                if preview_ingestor is not None:
                    latest_frame = _wait_for_ingestor_frame(
                        io_id,
                        local_preview_warmup_s,
                        minimum_mean=None,
                    )
            finally:
                if preview_ingestor is not None:
                    _release_local_preview_ingestor(io_id)

        if latest_frame is not None and latest_frame.size > 0:
            if is_local_camera or latest_frame.mean() >= 1:
                _, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return buffer.tobytes()

        pull_url = device_info.get('pull_url') or device_info.get('url')
        if pull_url:
            return _get_network_preview_frame(pull_url)

        return None
    except Exception as e:
        flask_logger.debug(f"Error building preview for {io_id}: {e}")
        return None


def _capture_device_frame_bytes(io_id: str) -> tuple[Optional[bytes], Optional[str], Optional[Dict[str, Any]]]:
    """Return a fresh or near-live JPEG frame for a camera device.

    This is stricter than the preview endpoint: it prefers a currently running
    ingestor frame when available, otherwise it performs a direct capture from
    the device or network source and returns JPEG bytes plus a source label.
    """
    try:
        device_info = io_manager.get_stream_info(io_id)
        if device_info is None:
            return None, None, None

        category = device_info.get('category', '').lower()
        if 'camera' not in category:
            return None, None, device_info

        is_local_camera = _is_local_camera_device(device_info)
        local_capture_warmup_s = max(
            0.0,
            float(os.getenv("VIDEOMEMORY_LOCAL_PREVIEW_WARMUP_S", "1.0")),
        )

        latest_frame = task_manager.get_latest_frame_for_device(io_id)
        if latest_frame is not None and latest_frame.size > 0 and (
            is_local_camera or latest_frame.mean() >= 1
        ):
            _, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            return buffer.tobytes(), "ingestor_live", device_info

        pull_url = device_info.get('pull_url') or device_info.get('url')
        if pull_url:
            frame_bytes = _get_network_preview_frame(pull_url)
            source = "network_snapshot" if is_snapshot_url(pull_url) else "network_stream"
            return frame_bytes, source, device_info

        preview_ingestor = _acquire_local_preview_ingestor(io_id, device_info) if is_local_camera else None
        try:
            if preview_ingestor is not None:
                latest_frame = _wait_for_ingestor_frame(
                    io_id,
                    local_capture_warmup_s,
                    minimum_mean=None,
                )
                if latest_frame is not None and latest_frame.size > 0:
                    _, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    return buffer.tobytes(), "shared_ingestor_warm", device_info
        finally:
            if preview_ingestor is not None:
                _release_local_preview_ingestor(io_id)

        return None, None, device_info
    except Exception as e:
        flask_logger.debug("Error capturing fresh frame for %s: %s", io_id, e, exc_info=True)
        return None, None, None


@app.route('/api/device/<io_id>/preview/stream', methods=['GET'])
def get_device_preview_stream(io_id):
    """Stream device previews as MJPEG for smoother live debugging."""
    import time

    fps = max(1.0, min(20.0, float(os.getenv("VIDEOMEMORY_PREVIEW_STREAM_FPS", "10"))))
    frame_delay_s = 1.0 / fps
    boundary = "frame"
    max_grabs = max(1, int(os.getenv("VIDEOMEMORY_PREVIEW_MAX_GRABS", "8")))
    drain_ms = max(0.0, float(os.getenv("VIDEOMEMORY_PREVIEW_DRAIN_MS", "80")))
    warmup_seconds = max(0.0, float(os.getenv("VIDEOMEMORY_NETWORK_PREVIEW_WARMUP_S", "0.75")))
    local_warmup_seconds = max(0.0, float(os.getenv("VIDEOMEMORY_LOCAL_PREVIEW_WARMUP_S", "1.0")))

    def _open_preview_capture(source):
        cap = cv2.VideoCapture()
        if isinstance(source, str) and source.startswith(("rtsp://", "rtsps://", "http://", "https://")):
            if not os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS"):
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|"
                    "max_delay;500000|reorder_queue_size;0"
                )
            open_timeout_ms = int(os.environ.get("VIDEOMEMORY_PREVIEW_OPEN_TIMEOUT_MS", "2500"))
            read_timeout_ms = int(os.environ.get("VIDEOMEMORY_PREVIEW_READ_TIMEOUT_MS", "2500"))
            if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, float(open_timeout_ms))
            if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, float(read_timeout_ms))
            if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            opened = cap.open(source, cv2.CAP_FFMPEG) if hasattr(cv2, "CAP_FFMPEG") else cap.open(source)
        else:
            try:
                camera_index = int(source)
            except (TypeError, ValueError):
                cap.release()
                return None
            if platform.system() == 'Darwin':
                opened = cap.open(camera_index, cv2.CAP_AVFOUNDATION)
            elif platform.system() == 'Linux':
                opened = cap.open(camera_index, cv2.CAP_V4L2)
            else:
                opened = cap.open(camera_index)
            if opened:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not opened or not cap.isOpened():
            cap.release()
            return None
        return cap

    def _read_latest_frame(cap):
        """Read the newest available frame, dropping buffered stale frames first."""
        if cap is None or not cap.isOpened():
            return None

        import time
        deadline = time.monotonic() + (drain_ms / 1000.0)
        grabs = 0
        grabbed_any = False

        # Drain backlog quickly so preview stays near-live instead of lagging.
        while grabs < max_grabs and time.monotonic() < deadline:
            ok = cap.grab()
            if not ok:
                break
            grabbed_any = True
            grabs += 1

        if grabbed_any:
            ret, frame = cap.retrieve()
        else:
            ret, frame = cap.read()

        if not ret or frame is None or frame.size == 0:
            return None
        return frame

    def generate():
        cap = None
        cap_source = None
        warmup_deadline = None
        local_preview_acquired = False
        local_camera = False
        try:
            initial_device_info = io_manager.get_stream_info(io_id)
            if initial_device_info is not None and not _is_local_camera_device(initial_device_info):
                _ensure_network_camera_ingestor(io_id, initial_device_info, wait_timeout_s=0.0)
                if warmup_seconds > 0:
                    warmup_deadline = time.monotonic() + warmup_seconds
            elif initial_device_info is not None and 'camera' in (initial_device_info.get('category', '').lower()):
                local_camera = True
                local_preview_acquired = _acquire_local_preview_ingestor(io_id, initial_device_info) is not None
                if local_preview_acquired and local_warmup_seconds > 0:
                    warmup_deadline = time.monotonic() + local_warmup_seconds

            while True:
                loop_started = time.monotonic()
                frame_data = None

                latest_frame = task_manager.get_latest_frame_for_device(io_id)
                if latest_frame is not None and latest_frame.size > 0 and (
                    local_camera or latest_frame.mean() >= 1
                ):
                    if cap is not None:
                        cap.release()
                        cap = None
                        cap_source = None
                    _, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    frame_data = buffer.tobytes()
                else:
                    device_info = io_manager.get_stream_info(io_id)
                    if device_info is not None and 'camera' in (device_info.get('category', '').lower()):
                        local_camera = _is_local_camera_device(device_info)
                        if warmup_deadline is not None and time.monotonic() < warmup_deadline:
                            time.sleep(min(0.05, frame_delay_s))
                            continue
                        if local_camera:
                            if not local_preview_acquired:
                                local_preview_acquired = _acquire_local_preview_ingestor(io_id, device_info) is not None
                                if local_preview_acquired and local_warmup_seconds > 0:
                                    warmup_deadline = time.monotonic() + local_warmup_seconds
                            time.sleep(frame_delay_s)
                            continue
                        pull_url = device_info.get('pull_url') or device_info.get('url')
                        if pull_url:
                            desired_source = pull_url
                        else:
                            try:
                                desired_source = int(io_id)
                            except (TypeError, ValueError):
                                desired_source = None
                        if desired_source is None:
                            time.sleep(frame_delay_s)
                            continue

                        if isinstance(desired_source, str) and is_snapshot_url(desired_source):
                            frame_data = _get_network_preview_frame(desired_source)
                        else:
                            if cap is None or cap_source != desired_source or not cap.isOpened():
                                if cap is not None:
                                    cap.release()
                                cap = _open_preview_capture(desired_source)
                                cap_source = desired_source if cap is not None else None

                            if cap is not None and cap.isOpened():
                                frame = _read_latest_frame(cap)
                                if frame is not None:
                                    if frame.shape[1] > 640 or frame.shape[0] > 480:
                                        frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_LINEAR)
                                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                                    frame_data = buffer.tobytes()
                                else:
                                    cap.release()
                                    cap = None
                                    cap_source = None

                if frame_data is not None:
                    _record_preview_frame(io_id)
                    yield (
                        b"--" + boundary.encode("ascii") + b"\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Cache-Control: no-cache, no-store, must-revalidate\r\n"
                        b"Pragma: no-cache\r\n"
                        b"Expires: 0\r\n\r\n" +
                        frame_data + b"\r\n"
                    )
                elapsed = time.monotonic() - loop_started
                sleep_for = frame_delay_s - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)
        finally:
            if cap is not None:
                cap.release()
            if local_preview_acquired:
                _release_local_preview_ingestor(io_id)

    return Response(
        generate(),
        mimetype=f"multipart/x-mixed-replace; boundary={boundary}",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",
        },
    )


@app.route('/api/device/<io_id>/capture', methods=['POST'])
def capture_device_frame(io_id):
    """Take a fresh capture for a camera device.

    Default response is image/jpeg bytes so shell clients can simply write the
    response to a file. Pass ?format=json to receive metadata including a
    fetchable capture URL and the local saved path.
    """
    response_format = str(request.args.get("format", "image")).strip().lower()
    if response_format not in {"image", "jpeg", "json"}:
        return jsonify({
            'status': 'error',
            'error': "format must be one of image, jpeg, json",
        }), 400

    frame_bytes, capture_source, device_info = _capture_device_frame_bytes(io_id)
    if frame_bytes is None:
        device_info = device_info or {}
        return jsonify({
            'status': 'error',
            'error': 'No fresh frame available for this device',
            'io_id': io_id,
            'device': {
                'name': device_info.get('name', ''),
                'source': device_info.get('source', ''),
                'url': _public_ingest_url(device_info.get('url', '')) if device_info.get('url') else '',
                'pull_url': device_info.get('pull_url', ''),
            },
            'hint': 'Ensure the camera is connected and actively producing frames before retrying the capture.',
        }), 404

    capture_record = _save_device_capture(io_id, frame_bytes, source=capture_source or "capture")
    capture_url = url_for('get_saved_capture', capture_id=capture_record["capture_id"])

    if response_format == "json":
        return jsonify({
            'status': 'success',
            'io_id': io_id,
            'capture_id': capture_record['capture_id'],
            'capture_url': capture_url,
            'local_path': str(capture_record['file_path']),
            'mime_type': 'image/jpeg',
            'bytes': capture_record['bytes'],
            'source': capture_record['source'],
        })

    response = send_file(
        capture_record['file_path'],
        mimetype='image/jpeg',
        conditional=True,
        max_age=0,
    )
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['Location'] = capture_url
    response.headers['X-VideoMemory-Capture-Id'] = capture_record['capture_id']
    response.headers['X-VideoMemory-Capture-Path'] = str(capture_record['file_path'])
    response.headers['X-VideoMemory-Capture-Source'] = capture_record['source']
    return response


@app.route('/api/captures/<capture_id>', methods=['GET'])
def get_saved_capture(capture_id):
    """Fetch a previously saved fresh capture."""
    if not _is_valid_capture_id(capture_id):
        return jsonify({'status': 'error', 'error': 'Invalid capture id'}), 400

    capture_path = _get_saved_capture_dir() / f"{capture_id}.jpg"
    if not capture_path.exists():
        return jsonify({'status': 'error', 'error': 'Capture not found'}), 404

    return send_file(
        capture_path,
        mimetype='image/jpeg',
        conditional=True,
        max_age=0,
    )


@app.route('/api/device/<io_id>/preview/fps', methods=['GET'])
def get_device_preview_fps(io_id):
    """Return server-measured preview stream FPS for a device."""
    fps = _get_preview_fps(io_id)
    response = jsonify({"io_id": io_id, "fps": round(fps, 2), "active": fps > 0})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ── Ingestor Debug API ────────────────────────────────────────

@app.route('/api/device/<io_id>/debug/status', methods=['GET'])
def get_ingestor_status(io_id):
    """Check whether an ingestor is running for a device."""
    try:
        ingestor = (
            task_manager.peek_ingestor(io_id)
            if hasattr(task_manager, 'peek_ingestor')
            else task_manager.get_ingestor(io_id)
        )
        has = ingestor is not None
        running = ingestor._running if ingestor else False
        has_debug_artifact = _get_latest_persisted_debug_snapshot(io_id) is not None
        latest_inference_error = ingestor.get_latest_inference_error() if ingestor is not None else None
        device_info = io_manager.get_stream_info(io_id)
        semantic_preview_available = bool(device_info and 'camera' in (device_info.get('category', '').lower()))
        return jsonify({
            'has_ingestor': has,
            'running': running,
            'has_debug_artifact': has_debug_artifact,
            'latest_inference_error': latest_inference_error,
            'semantic_preview_available': semantic_preview_available,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/device/<io_id>/debug/frame-skip-threshold', methods=['GET', 'PUT'])
def ingestor_frame_skip_threshold(io_id):
    """Get or update the live frame-skip threshold for a device ingestor."""
    try:
        if io_manager.get_stream_info(io_id) is None:
            return jsonify({'error': 'Device not found'}), 404

        if request.method == 'GET':
            return jsonify(task_manager.get_ingestor_frame_skip_threshold(io_id))

        data = request.get_json(silent=True) or {}
        raw_value = data.get('value', data.get('frame_diff_threshold'))
        if raw_value is None:
            return jsonify({'error': 'value is required'}), 400

        try:
            threshold = float(raw_value)
        except (TypeError, ValueError):
            return jsonify({'error': 'value must be numeric'}), 400

        if threshold < 0 or threshold > 255:
            return jsonify({'error': 'value must be between 0 and 255'}), 400

        result = task_manager.set_ingestor_frame_skip_threshold(io_id, threshold)
        return jsonify(result)
    except Exception as e:
        flask_logger.error(f"Error updating frame-skip threshold for {io_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/device/<io_id>/debug/semantic-filter', methods=['GET', 'PUT'])
def ingestor_semantic_filter(io_id):
    """Get or update optional semantic frame-filter settings for a device ingestor."""
    try:
        if io_manager.get_stream_info(io_id) is None:
            return jsonify({'error': 'Device not found'}), 404

        if request.method == 'GET':
            return jsonify(task_manager.get_ingestor_semantic_filter_config(io_id))

        data = request.get_json(silent=True) or {}
        threshold_mode = str(data.get('threshold_mode', 'absolute')).strip().lower()
        if threshold_mode not in {'absolute', 'percentile'}:
            return jsonify({'error': 'threshold_mode must be absolute or percentile'}), 400
        reduce = str(data.get('reduce', 'max')).strip().lower()
        if reduce not in {'max', 'mean', 'min', 'sum', 'softmax'}:
            return jsonify({'error': 'reduce must be max, mean, min, sum, or softmax'}), 400
        ensemble = str(data.get('ensemble', 'off')).strip().lower()
        if ensemble not in {'off', 'hflip', 'hvflip'}:
            return jsonify({'error': 'ensemble must be off, hflip, or hvflip'}), 400
        try:
            threshold = float(data.get('threshold', 0.5))
        except (TypeError, ValueError):
            return jsonify({'error': 'threshold must be numeric'}), 400
        max_threshold = 1.0 if threshold_mode == 'absolute' else 0.99
        if threshold < 0 or threshold > max_threshold:
            return jsonify({'error': f'threshold must be between 0 and {max_threshold}'}), 400
        try:
            smoothing = float(data.get('smoothing', 0.0))
        except (TypeError, ValueError):
            return jsonify({'error': 'smoothing must be numeric'}), 400
        if smoothing < 0 or smoothing > 0.95:
            return jsonify({'error': 'smoothing must be between 0 and 0.95'}), 400

        result = task_manager.set_ingestor_semantic_filter_config(io_id, {
            'enabled': bool(data.get('enabled', False)),
            'keywords': str(data.get('keywords', '') or ''),
            'threshold': threshold,
            'threshold_mode': threshold_mode,
            'reduce': reduce,
            'smoothing': smoothing,
            'ensemble': ensemble,
        })
        return jsonify(result)
    except Exception as e:
        flask_logger.error(f"Error updating semantic filter for {io_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/device/<io_id>/debug/semantic-preview/status', methods=['GET'])
def ingestor_semantic_preview_status(io_id):
    """Return lightweight realtime semantic-preview status for the debug UI."""
    try:
        def _default_chunk_queue_status() -> Dict[str, Any]:
            try:
                chunk_seconds = float(os.getenv("VIDEOMEMORY_VIDEO_CHUNK_SECONDS", "2.0"))
            except (TypeError, ValueError):
                chunk_seconds = 2.0
            try:
                max_frames = int(os.getenv("VIDEOMEMORY_VIDEO_CHUNK_SUBSAMPLE_FRAMES", "9"))
            except (TypeError, ValueError):
                max_frames = 9
            try:
                max_queue = int(os.getenv("VIDEOMEMORY_VIDEO_CHUNK_QUEUE_MAXSIZE", "10"))
            except (TypeError, ValueError):
                max_queue = 10
            return {
                'video_chunk_seconds': max(0.1, chunk_seconds),
                'video_chunk_subsample_frames': max(1, max_frames),
                'video_chunk_queue_maxsize': max(1, max_queue),
                'queued_chunks': 0,
                'oldest_queued_chunk_age_ms': None,
                'newest_queued_chunk_age_ms': None,
                'queued_chunk_frame_counts': [],
            }

        def _default_semantic_frame_queue_status() -> Dict[str, Any]:
            try:
                semantic_queue = int(os.getenv("VIDEOMEMORY_SEMANTIC_FRAME_QUEUE_MAXSIZE", "3"))
            except (TypeError, ValueError):
                semantic_queue = 3
            return {
                'semantic_frame_queue_maxsize': max(1, semantic_queue),
                'queued_semantic_frames': 0,
                'oldest_queued_semantic_frame_age_ms': None,
                'newest_queued_semantic_frame_age_ms': None,
                'dropped_semantic_frames': 0,
            }

        ingestor = (
            task_manager.peek_ingestor(io_id)
            if hasattr(task_manager, 'peek_ingestor')
            else task_manager.get_ingestor(io_id)
        )
        if ingestor is None:
            return jsonify({
                'has_ingestor': False,
                'running': False,
                'has_frame': False,
                'has_frame_diff_frame': False,
                'has_heatmap': False,
                'has_semantic_pass_frame': False,
                'frame_age_ms': None,
                'frame_diff_age_ms': None,
                'semantic_pass_age_ms': None,
                'dedup_status': None,
                'chunk_queue': _default_chunk_queue_status(),
                'semantic_frame_queue': _default_semantic_frame_queue_status(),
                'semantic_filter': task_manager.get_ingestor_semantic_filter_config(io_id),
            }), 200

        latest_frame = ingestor.get_latest_frame() if hasattr(ingestor, 'get_latest_frame') else None
        latest_heatmap = (
            ingestor.get_latest_semantic_filter_heatmap()
            if hasattr(ingestor, 'get_latest_semantic_filter_heatmap')
            else None
        )
        latest_semantic_pass = (
            ingestor.get_latest_semantic_pass_frame()
            if hasattr(ingestor, 'get_latest_semantic_pass_frame')
            else None
        )
        latest_frame_diff = (
            ingestor.get_latest_frame_diff_frame()
            if hasattr(ingestor, 'get_latest_frame_diff_frame')
            else None
        )
        latest_frame_timestamp = (
            ingestor.get_latest_frame_timestamp()
            if hasattr(ingestor, 'get_latest_frame_timestamp')
            else None
        )
        latest_frame_diff_timestamp = (
            ingestor.get_latest_frame_diff_timestamp()
            if hasattr(ingestor, 'get_latest_frame_diff_timestamp')
            else None
        )
        latest_semantic_pass_timestamp = (
            ingestor.get_latest_semantic_pass_timestamp()
            if hasattr(ingestor, 'get_latest_semantic_pass_timestamp')
            else None
        )
        frame_age_ms = None
        if latest_frame_timestamp is not None:
            frame_age_ms = max(0.0, (time.time() - latest_frame_timestamp) * 1000.0)
        frame_diff_age_ms = None
        if latest_frame_diff_timestamp is not None:
            frame_diff_age_ms = max(0.0, (time.time() - latest_frame_diff_timestamp) * 1000.0)
        semantic_pass_age_ms = None
        if latest_semantic_pass_timestamp is not None:
            semantic_pass_age_ms = max(0.0, (time.time() - latest_semantic_pass_timestamp) * 1000.0)
        semantic_status = (
            ingestor.get_semantic_filter_status()
            if hasattr(ingestor, 'get_semantic_filter_status')
            else None
        )
        semantic_result_age_ms = None
        if semantic_status and semantic_status.get('latest_evaluation_timestamp') is not None:
            semantic_result_age_ms = max(
                0.0,
                (time.time() - float(semantic_status['latest_evaluation_timestamp'])) * 1000.0,
            )
        return jsonify({
            'has_ingestor': True,
            'running': bool(getattr(ingestor, '_running', False)),
            'has_frame': latest_frame is not None and getattr(latest_frame, 'size', 0) > 0,
            'has_frame_diff_frame': latest_frame_diff is not None and getattr(latest_frame_diff, 'size', 0) > 0,
            'has_heatmap': latest_heatmap is not None and getattr(latest_heatmap, 'size', 0) > 0,
            'has_semantic_pass_frame': latest_semantic_pass is not None and getattr(latest_semantic_pass, 'size', 0) > 0,
            'frame_age_ms': frame_age_ms,
            'frame_diff_age_ms': frame_diff_age_ms,
            'semantic_pass_age_ms': semantic_pass_age_ms,
            'semantic_result_age_ms': semantic_result_age_ms,
            'dedup_status': ingestor.get_dedup_status() if hasattr(ingestor, 'get_dedup_status') else None,
            'chunk_queue': ingestor.get_chunk_queue_status() if hasattr(ingestor, 'get_chunk_queue_status') else None,
            'semantic_frame_queue': ingestor.get_semantic_frame_queue_status() if hasattr(ingestor, 'get_semantic_frame_queue_status') else None,
            'semantic_filter': semantic_status,
        })
    except Exception as e:
        flask_logger.error(f"Error reading semantic preview status for {io_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/device/<io_id>/debug/semantic-preview/stream', methods=['GET'])
def ingestor_semantic_preview_stream(io_id):
    """Stream the latest semantic-filter overlay for fast local tuning."""
    fps = max(1.0, min(60.0, float(os.getenv("VIDEOMEMORY_SEMANTIC_PREVIEW_FPS", "24"))))
    frame_delay_s = 1.0 / fps
    idle_delay_s = min(0.02, frame_delay_s)
    max_width = max(320, min(1280, int(os.getenv("VIDEOMEMORY_SEMANTIC_PREVIEW_MAX_WIDTH", "640"))))
    jpeg_quality = max(35, min(95, int(os.getenv("VIDEOMEMORY_SEMANTIC_PREVIEW_JPEG_QUALITY", "68"))))
    heatmap_stale_after_s = max(
        0.5,
        float(os.getenv("VIDEOMEMORY_SEMANTIC_PREVIEW_HEATMAP_STALE_AFTER_S", "2.0")),
    )
    fallback_to_raw = str(request.args.get("fallback_raw", "1")).strip().lower() not in {"0", "false", "no", "off"}
    boundary = "frame"
    device_info = io_manager.get_stream_info(io_id)
    local_preview_acquired = False
    if device_info is not None and not _is_local_camera_device(device_info):
        _ensure_network_camera_ingestor(io_id, device_info, wait_timeout_s=0.0)
    elif device_info is not None and 'camera' in (device_info.get('category', '').lower()):
        local_preview_acquired = _acquire_local_preview_ingestor(io_id, device_info) is not None

    def _placeholder_frame(message: str) -> Any:
        frame = np.zeros((480, 854, 3), dtype=np.uint8)
        cv2.putText(frame, "Semantic Preview", (28, 52), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (25, 195, 125), 2, cv2.LINE_AA)
        y = 112
        for line in message.split("\n"):
            cv2.putText(frame, line, (28, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (220, 220, 220), 1, cv2.LINE_AA)
            y += 34
        return frame

    def _latest_preview_frame() -> tuple[Optional[Any], Optional[str]]:
        ingestor = (
            task_manager.peek_ingestor(io_id)
            if hasattr(task_manager, 'peek_ingestor')
            else task_manager.get_ingestor(io_id)
        )
        if ingestor is None:
            bucket = int(time.monotonic())
            return (
                _placeholder_frame("No active ingestor is running.\nCreate/start a task to see the live semantic heatmap."),
                f"placeholder:no-ingestor:{bucket}",
            )
        frame = ingestor.get_latest_frame() if hasattr(ingestor, 'get_latest_frame') else None
        frame_timestamp = (
            ingestor.get_latest_frame_timestamp()
            if hasattr(ingestor, 'get_latest_frame_timestamp')
            else None
        )
        heatmap = (
            ingestor.get_latest_semantic_filter_heatmap()
            if hasattr(ingestor, 'get_latest_semantic_filter_heatmap')
            else None
        )
        if heatmap is not None and getattr(heatmap, 'size', 0) > 0:
            status = (
                ingestor.get_semantic_filter_status()
                if hasattr(ingestor, 'get_semantic_filter_status')
                else {}
            )
            semantic_timestamp = status.get('latest_evaluation_timestamp')
            heatmap_is_stale = (
                frame is not None
                and frame_timestamp is not None
                and semantic_timestamp is not None
                and (float(frame_timestamp) - float(semantic_timestamp)) > heatmap_stale_after_s
            )
            if not heatmap_is_stale or not fallback_to_raw:
                marker = semantic_timestamp or status.get('evaluations')
                return heatmap, f"heatmap:{marker}"
        if frame is not None and getattr(frame, 'size', 0) > 0:
            if not fallback_to_raw:
                bucket = int(time.monotonic())
                return (
                    _placeholder_frame("Waiting for semantic-filter output.\nFrame-diff may be skipping current frames."),
                    f"placeholder:no-semantic:{bucket}",
                )
            marker = frame_timestamp if frame_timestamp is not None else time.monotonic()
            return frame, f"frame:{marker}"
        bucket = int(time.monotonic())
        return (
            _placeholder_frame("Ingestor is running, but no frame is available yet.\nIf this persists, the camera capture path is not returning frames."),
            f"placeholder:no-frame:{bucket}",
        )

    def generate():
        last_marker = None
        try:
            while True:
                started_at = time.monotonic()
                frame, marker = _latest_preview_frame()
                sent_frame = False
                if frame is not None and marker != last_marker:
                    height, width = frame.shape[:2]
                    if width > max_width:
                        scale = max_width / float(width)
                        frame = cv2.resize(
                            frame,
                            (max_width, max(1, int(height * scale))),
                            interpolation=cv2.INTER_AREA,
                        )
                    ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
                    if ok:
                        last_marker = marker
                        sent_frame = True
                        yield (
                            b"--" + boundary.encode("ascii") + b"\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"X-Frame-Marker: " + str(marker).encode("utf-8", errors="replace") + b"\r\n"
                            b"Cache-Control: no-cache, no-store, must-revalidate\r\n"
                            b"Pragma: no-cache\r\n"
                            b"Expires: 0\r\n\r\n" +
                            buffer.tobytes() + b"\r\n"
                        )
                elapsed = time.monotonic() - started_at
                target_delay = frame_delay_s if sent_frame else idle_delay_s
                time.sleep(max(0.005, target_delay - elapsed))
        finally:
            if local_preview_acquired:
                _release_local_preview_ingestor(io_id)

    response = Response(
        generate(),
        mimetype=f"multipart/x-mixed-replace; boundary={boundary}",
        direct_passthrough=True,
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route('/api/device/<io_id>/debug/semantic-pass/stream', methods=['GET'])
def ingestor_semantic_pass_stream(io_id):
    """Stream raw frames that passed semantic filtering."""
    fps = max(1.0, min(60.0, float(os.getenv("VIDEOMEMORY_SEMANTIC_PASS_PREVIEW_FPS", "24"))))
    frame_delay_s = 1.0 / fps
    idle_delay_s = min(0.02, frame_delay_s)
    max_width = max(320, min(1280, int(os.getenv("VIDEOMEMORY_SEMANTIC_PASS_PREVIEW_MAX_WIDTH", "640"))))
    jpeg_quality = max(35, min(95, int(os.getenv("VIDEOMEMORY_SEMANTIC_PASS_PREVIEW_JPEG_QUALITY", "72"))))
    boundary = "frame"
    device_info = io_manager.get_stream_info(io_id)
    local_preview_acquired = False
    if device_info is not None and not _is_local_camera_device(device_info):
        _ensure_network_camera_ingestor(io_id, device_info, wait_timeout_s=0.0)
    elif device_info is not None and 'camera' in (device_info.get('category', '').lower()):
        local_preview_acquired = _acquire_local_preview_ingestor(io_id, device_info) is not None

    def _placeholder_frame(message: str) -> Any:
        frame = np.zeros((480, 854, 3), dtype=np.uint8)
        cv2.putText(frame, "Semantic Output", (28, 52), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (25, 195, 125), 2, cv2.LINE_AA)
        y = 112
        for line in message.split("\n"):
            cv2.putText(frame, line, (28, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (220, 220, 220), 1, cv2.LINE_AA)
            y += 34
        return frame

    def _latest_preview_frame() -> tuple[Optional[Any], Optional[str]]:
        ingestor = (
            task_manager.peek_ingestor(io_id)
            if hasattr(task_manager, 'peek_ingestor')
            else task_manager.get_ingestor(io_id)
        )
        if ingestor is None:
            bucket = int(time.monotonic())
            return (
                _placeholder_frame("No active preview ingestor is running yet.\nOpen the raw live feed or create a task to start capture."),
                f"placeholder:no-ingestor:{bucket}",
            )
        frame = (
            ingestor.get_latest_semantic_pass_frame()
            if hasattr(ingestor, 'get_latest_semantic_pass_frame')
            else None
        )
        timestamp = (
            ingestor.get_latest_semantic_pass_timestamp()
            if hasattr(ingestor, 'get_latest_semantic_pass_timestamp')
            else None
        )
        if frame is not None and getattr(frame, 'size', 0) > 0:
            marker = timestamp if timestamp is not None else time.monotonic()
            return frame, f"semantic-pass:{marker}"
        bucket = int(time.monotonic())
        return (
            _placeholder_frame("No frames have passed semantic filtering yet.\nUse the heatmap and threshold controls to tune this stage."),
            f"placeholder:no-semantic-pass:{bucket}",
        )

    def generate():
        last_marker = None
        try:
            while True:
                started_at = time.monotonic()
                frame, marker = _latest_preview_frame()
                sent_frame = False
                if frame is not None and marker != last_marker:
                    height, width = frame.shape[:2]
                    if width > max_width:
                        scale = max_width / float(width)
                        frame = cv2.resize(
                            frame,
                            (max_width, max(1, int(height * scale))),
                            interpolation=cv2.INTER_AREA,
                        )
                    ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
                    if ok:
                        last_marker = marker
                        sent_frame = True
                        yield (
                            b"--" + boundary.encode("ascii") + b"\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"X-Frame-Marker: " + str(marker).encode("utf-8", errors="replace") + b"\r\n"
                            b"Cache-Control: no-cache, no-store, must-revalidate\r\n"
                            b"Pragma: no-cache\r\n"
                            b"Expires: 0\r\n\r\n" +
                            buffer.tobytes() + b"\r\n"
                        )
                elapsed = time.monotonic() - started_at
                target_delay = frame_delay_s if sent_frame else idle_delay_s
                time.sleep(max(0.005, target_delay - elapsed))
        finally:
            if local_preview_acquired:
                _release_local_preview_ingestor(io_id)

    response = Response(
        generate(),
        mimetype=f"multipart/x-mixed-replace; boundary={boundary}",
        direct_passthrough=True,
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route('/api/device/<io_id>/debug/frame-diff/stream', methods=['GET'])
def ingestor_frame_diff_stream(io_id):
    """Stream the latest frame that passed frame-difference filtering."""
    fps = max(1.0, min(60.0, float(os.getenv("VIDEOMEMORY_FRAME_DIFF_PREVIEW_FPS", "24"))))
    frame_delay_s = 1.0 / fps
    idle_delay_s = min(0.02, frame_delay_s)
    max_width = max(320, min(1280, int(os.getenv("VIDEOMEMORY_FRAME_DIFF_PREVIEW_MAX_WIDTH", "640"))))
    jpeg_quality = max(35, min(95, int(os.getenv("VIDEOMEMORY_FRAME_DIFF_PREVIEW_JPEG_QUALITY", "72"))))
    boundary = "frame"
    device_info = io_manager.get_stream_info(io_id)
    local_preview_acquired = False
    if device_info is not None and not _is_local_camera_device(device_info):
        _ensure_network_camera_ingestor(io_id, device_info, wait_timeout_s=0.0)
    elif device_info is not None and 'camera' in (device_info.get('category', '').lower()):
        local_preview_acquired = _acquire_local_preview_ingestor(io_id, device_info) is not None

    def _placeholder_frame(message: str) -> Any:
        frame = np.zeros((480, 854, 3), dtype=np.uint8)
        cv2.putText(frame, "Frame-Diff Output", (28, 52), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (25, 195, 125), 2, cv2.LINE_AA)
        y = 112
        for line in message.split("\n"):
            cv2.putText(frame, line, (28, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (220, 220, 220), 1, cv2.LINE_AA)
            y += 34
        return frame

    def _latest_preview_frame() -> tuple[Optional[Any], Optional[str]]:
        ingestor = (
            task_manager.peek_ingestor(io_id)
            if hasattr(task_manager, 'peek_ingestor')
            else task_manager.get_ingestor(io_id)
        )
        if ingestor is None:
            bucket = int(time.monotonic())
            return (
                _placeholder_frame("No active preview ingestor is running yet.\nOpen the raw live feed or create a task to start capture."),
                f"placeholder:no-ingestor:{bucket}",
            )
        frame = (
            ingestor.get_latest_frame_diff_frame()
            if hasattr(ingestor, 'get_latest_frame_diff_frame')
            else None
        )
        timestamp = (
            ingestor.get_latest_frame_diff_timestamp()
            if hasattr(ingestor, 'get_latest_frame_diff_timestamp')
            else None
        )
        if frame is not None and getattr(frame, 'size', 0) > 0:
            marker = timestamp if timestamp is not None else time.monotonic()
            return frame, f"frame-diff:{marker}"
        bucket = int(time.monotonic())
        return (
            _placeholder_frame("Waiting for a frame to pass frame-diff.\nRaise/lower the threshold to tune this stage."),
            f"placeholder:no-frame-diff:{bucket}",
        )

    def generate():
        last_marker = None
        try:
            while True:
                started_at = time.monotonic()
                frame, marker = _latest_preview_frame()
                sent_frame = False
                if frame is not None and marker != last_marker:
                    height, width = frame.shape[:2]
                    if width > max_width:
                        scale = max_width / float(width)
                        frame = cv2.resize(
                            frame,
                            (max_width, max(1, int(height * scale))),
                            interpolation=cv2.INTER_AREA,
                        )
                    ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
                    if ok:
                        last_marker = marker
                        sent_frame = True
                        yield (
                            b"--" + boundary.encode("ascii") + b"\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"X-Frame-Marker: " + str(marker).encode("utf-8", errors="replace") + b"\r\n"
                            b"Cache-Control: no-cache, no-store, must-revalidate\r\n"
                            b"Pragma: no-cache\r\n"
                            b"Expires: 0\r\n\r\n" +
                            buffer.tobytes() + b"\r\n"
                        )
                elapsed = time.monotonic() - started_at
                target_delay = frame_delay_s if sent_frame else idle_delay_s
                time.sleep(max(0.005, target_delay - elapsed))
        finally:
            if local_preview_acquired:
                _release_local_preview_ingestor(io_id)

    response = Response(
        generate(),
        mimetype=f"multipart/x-mixed-replace; boundary={boundary}",
        direct_passthrough=True,
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route('/api/device/<io_id>/debug/frame-and-prompt', methods=['GET'])
def get_ingestor_frame_and_prompt(io_id):
    """Get the latest frame and prompt from a device's ingestor."""
    try:
        ingestor = (
            task_manager.peek_ingestor(io_id)
            if hasattr(task_manager, 'peek_ingestor')
            else task_manager.get_ingestor(io_id)
        )
        latest_output = ingestor.get_latest_output() if ingestor is not None else None
        latest_model_input = (
            ingestor.get_latest_model_input()
            if ingestor is not None and hasattr(ingestor, 'get_latest_model_input')
            else None
        )
        latest_error = ingestor.get_latest_inference_error() if ingestor is not None else None
        dedup = ingestor.get_dedup_status() if ingestor is not None else None
        semantic_status = (
            ingestor.get_semantic_filter_status()
            if ingestor is not None and hasattr(ingestor, 'get_semantic_filter_status')
            else None
        )
        semantic_heatmap = (
            ingestor.get_latest_semantic_filter_heatmap()
            if ingestor is not None and hasattr(ingestor, 'get_latest_semantic_filter_heatmap')
            else None
        )
        semantic_heatmap_base64 = None
        if semantic_heatmap is not None and getattr(semantic_heatmap, "size", 0) > 0:
            _, heatmap_buffer = cv2.imencode('.jpg', semantic_heatmap, [cv2.IMWRITE_JPEG_QUALITY, 85])
            semantic_heatmap_base64 = base64.b64encode(heatmap_buffer).decode('utf-8')
        prompt = _build_device_debug_prompt(io_id, ingestor=ingestor)
        latest_output_timestamp = None
        if latest_output:
            latest_output_timestamp = latest_output.get('timestamp')
        latest_error_timestamp = latest_error.get('timestamp') if latest_error else None

        model_input = latest_model_input or latest_output
        latest_error_is_newer = (
            latest_error_timestamp is not None
            and latest_output_timestamp is not None
            and latest_error_timestamp >= latest_output_timestamp
        )
        if latest_error_is_newer:
            model_input = None
        if model_input:
            output_frame = model_input.get('frame')
            latest_prompt = model_input.get('prompt') or prompt
            if output_frame is not None:
                _, buffer = cv2.imencode('.jpg', output_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                image_base64 = base64.b64encode(buffer).decode('utf-8')
                chunk = model_input.get('chunk') or {}
                sampled_frame_count = chunk.get('sampled_frame_count')
                source_label = 'Showing exact image sent to the model provider'
                if sampled_frame_count and int(sampled_frame_count) > 1:
                    source_label = f'Showing exact tiled contact sheet sent to the model provider ({sampled_frame_count} frames)'
                if ingestor is not None and not ingestor._running:
                    source_label += ' from before the ingestor stopped'
                return jsonify({
                    'frame_base64': image_base64,
                    'prompt': latest_prompt or '',
                    'dedup_status': dedup,
                    'semantic_filter': semantic_status,
                    'semantic_heatmap_base64': semantic_heatmap_base64,
                    'source': 'model_input',
                    'source_label': source_label,
                    'chunk': chunk,
                    'inference_error': latest_error,
                })

        persisted_snapshot = _get_latest_persisted_debug_snapshot(io_id)
        if persisted_snapshot is not None:
            note = persisted_snapshot['note']
            task = persisted_snapshot['task']
            note_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(note.timestamp))
            prompt_notice_parts = []
            if latest_error and latest_error.get('user_message'):
                prompt_notice_parts.append(latest_error['user_message'])
            if prompt:
                prompt_notice_parts.append('Prompt reconstructed from current task context. Showing the most recent note-backed VLM frame.')
            return jsonify({
                'frame_base64': base64.b64encode(persisted_snapshot['frame_bytes']).decode('utf-8'),
                'prompt': prompt or '',
                'prompt_notice': '\n\n'.join(prompt_notice_parts),
                'dedup_status': dedup,
                'semantic_filter': semantic_status,
                'semantic_heatmap_base64': semantic_heatmap_base64,
                'source': 'persisted_note_frame',
                'source_label': f'Showing most recent note-backed frame from {note_time}',
                'note_content': note.content,
                'note_id': note.note_id,
                'task_desc': getattr(task, 'task_desc', ''),
                'inference_error': latest_error,
            })

        if ingestor is None:
            error = 'No active ingestor or persisted debug frame for this device'
        elif not ingestor._running:
            error = 'Ingestor not running and no persisted debug frame is available'
        elif not latest_output:
            error = 'No model provider input has been recorded yet'
        else:
            error = 'Last VLM call did not include a frame'

        return jsonify({
            'error': error,
            'frame_base64': None,
            'prompt': prompt or '',
            'dedup_status': dedup,
            'semantic_filter': semantic_status,
            'semantic_heatmap_base64': semantic_heatmap_base64,
            'inference_error': latest_error,
        }), 200
    except Exception as e:
        flask_logger.error(f"Error in debug frame-and-prompt for {io_id}: {e}", exc_info=True)
        return jsonify({'error': str(e), 'frame_base64': None, 'prompt': ''}), 500

@app.route('/api/device/<io_id>/debug/history', methods=['GET'])
def get_ingestor_history(io_id):
    """Get output history from a device's ingestor."""
    try:
        ingestor = (
            task_manager.peek_ingestor(io_id)
            if hasattr(task_manager, 'peek_ingestor')
            else task_manager.get_ingestor(io_id)
        )
        if ingestor is None:
            return jsonify({'history': [], 'count': 0, 'total_count': 0}), 200
        
        history = ingestor.get_output_history()
        # Remove frames and prompts for JSON serialization
        history_clean = [{k: v for k, v in item.items() if k not in ('frame', 'prompt')} for item in history]
        total_count = ingestor.get_total_output_count()
        return jsonify({
            'history': history_clean,
            'count': len(history_clean),
            'total_count': total_count,
            'latest_inference_error': ingestor.get_latest_inference_error(),
        })
    except Exception as e:
        flask_logger.error(f"Error in debug history for {io_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/device/<io_id>/debug/tasks', methods=['GET'])
def get_ingestor_tasks(io_id):
    """Get tasks from a device's ingestor."""
    try:
        ingestor = (
            task_manager.peek_ingestor(io_id)
            if hasattr(task_manager, 'peek_ingestor')
            else task_manager.get_ingestor(io_id)
        )
        tasks = ingestor.get_tasks_list() if ingestor is not None else []
        if not tasks:
            tasks = (
                task_manager.peek_task_objects(io_id)
                if hasattr(task_manager, 'peek_task_objects')
                else task_manager.get_task_objects(io_id)
            )
        tasks_data = []
        for task in tasks:
            task_dict = {
                'task_number': task.task_number,
                'task_id': task.task_id,
                'task_desc': task.task_desc,
                'done': task.done,
                'latest_note': None
            }
            if task.task_note and len(task.task_note) > 0:
                latest_note_entry = task.task_note[-1]
                if hasattr(latest_note_entry, 'to_dict'):
                    task_dict['latest_note'] = latest_note_entry.to_dict()
                else:
                    task_dict['latest_note'] = latest_note_entry
            tasks_data.append(task_dict)
        return jsonify({'tasks': tasks_data})
    except Exception as e:
        flask_logger.error(f"Error in debug tasks for {io_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/caption_frame', methods=['POST'])
def caption_frame():
    """Run one-off VLM caption/query on the latest frame for a specific device.

    Body (JSON):
        prompt (str, required): Natural-language instruction for the model.
        io_id (str, required): Device id.
    """
    class OneOffFrameAnalysis(BaseModel):
        analysis: str = Field(..., description="Model output for the requested frame analysis")

    try:
        data = request.get_json(silent=True) or {}
        prompt = str(data.get('prompt', '')).strip()
        io_id = str(data.get('io_id', '')).strip()

        if not prompt:
            return jsonify({'status': 'error', 'error': 'prompt is required'}), 400
        if not io_id:
            return jsonify({'status': 'error', 'error': 'io_id is required'}), 400

        device_info = io_manager.get_stream_info(io_id) or {}
        frame_bytes = _get_device_preview_frame_bytes(io_id)
        if frame_bytes is None:
            return jsonify({
                'status': 'error',
                'error': 'No frame available for this device',
                'io_id': io_id,
                'device': {
                    'name': device_info.get('name', ''),
                    'source': device_info.get('source', ''),
                    'url': _public_ingest_url(device_info.get('url', '')) if device_info.get('url') else '',
                    'pull_url': device_info.get('pull_url', ''),
                },
                'hint': 'Ensure the camera is actively publishing and the stream codec is supported (H.264 + AAC).',
            }), 404

        import base64
        image_base64 = base64.b64encode(frame_bytes).decode('utf-8')
        frame_sha256 = hashlib.sha256(frame_bytes).hexdigest()
        active_provider = getattr(task_manager, "_model_provider", None) or model_provider
        provider_name = type(active_provider).__name__
        flask_logger.info(
            "caption_frame request io_id=%s prompt_chars=%d frame_bytes=%d frame_sha256=%s provider=%s",
            io_id,
            len(prompt),
            len(frame_bytes),
            frame_sha256[:12],
            provider_name,
        )

        response = active_provider._sync_generate_content(
            image_base64=image_base64,
            prompt=prompt,
            response_model=OneOffFrameAnalysis,
            usage_context={'source': 'caption_frame'},
        )
        analysis = str(getattr(response, 'analysis', '')).strip()
        if not analysis:
            return jsonify({
                'status': 'error',
                'error': 'Model returned empty analysis',
                'io_id': io_id,
                'model_provider': provider_name,
                'frame_sha256': frame_sha256,
                'frame_bytes': len(frame_bytes),
            }), 502

        return jsonify({
            'status': 'success',
            'io_id': io_id,
            'prompt': prompt,
            'analysis': analysis,
            'model_provider': provider_name,
            'frame_sha256': frame_sha256,
            'frame_bytes': len(frame_bytes),
        })
    except Exception as e:
        flask_logger.error("Error in /api/caption_frame: %s", e, exc_info=True)
        provider_name = type(getattr(task_manager, "_model_provider", None) or model_provider).__name__
        body, status_code = _build_caption_frame_provider_error(e, provider_name=provider_name)
        return jsonify(body), status_code


_USAGE_RANGE_SECONDS = {
    'day': 24 * 60 * 60,
    'week': 7 * 24 * 60 * 60,
    'month': 30 * 24 * 60 * 60,
}


def _normalize_usage_range(range_key: Optional[str]) -> str:
    normalized = str(range_key or '').strip().lower()
    return normalized if normalized in _USAGE_RANGE_SECONDS else 'month'


def _build_usage_payload(range_key: Optional[str]) -> dict[str, Any]:
    """Build the usage dashboard payload for the requested range."""
    from datetime import datetime
    import time

    normalized_range = _normalize_usage_range(range_key)
    now_ts = time.time()
    start_ts = now_ts - _USAGE_RANGE_SECONDS[normalized_range]
    events = db.list_model_usage_events(start_at=start_ts, end_at=now_ts, newest_first=False)
    recent_events = db.list_model_usage_events(start_at=start_ts, end_at=now_ts, newest_first=True, limit=200)
    now_dt = datetime.fromtimestamp(now_ts).astimezone()
    return build_usage_dashboard_payload(
        events,
        range_key=normalized_range,
        recent_events=recent_events,
        now=now_dt,
    )


@app.route('/api/usage', methods=['GET'])
def get_usage_data():
    """Return usage summary, buckets, and recent events for the Usage page."""
    try:
        payload = _build_usage_payload(request.args.get('range'))
        return jsonify(payload)
    except Exception as e:
        flask_logger.error("Error loading usage data: %s", e, exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/usage/export.csv', methods=['GET'])
def export_usage_csv():
    """Export raw usage events as CSV for the selected time range."""
    try:
        import time

        normalized_range = _normalize_usage_range(request.args.get('range'))
        now_ts = time.time()
        start_ts = now_ts - _USAGE_RANGE_SECONDS[normalized_range]
        rows = db.list_model_usage_events(start_at=start_ts, end_at=now_ts, newest_first=True)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            'timestamp',
            'provider_name',
            'model_name',
            'api_model_name',
            'source',
            'input_tokens',
            'output_tokens',
            'total_tokens',
            'estimated_cost_usd',
            'latency_ms',
            'was_success',
        ])
        for row in rows:
            writer.writerow([
                row.get('created_at'),
                row.get('provider_name'),
                row.get('model_name'),
                row.get('api_model_name'),
                row.get('source'),
                row.get('input_tokens'),
                row.get('output_tokens'),
                row.get('total_tokens'),
                row.get('estimated_cost_usd'),
                row.get('latency_ms'),
                row.get('was_success'),
            ])

        return Response(
            buffer.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename="videomemory-usage-{normalized_range}.csv"',
                'Cache-Control': 'no-cache, no-store, must-revalidate',
            },
        )
    except Exception as e:
        flask_logger.error("Error exporting usage CSV: %s", e, exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/storage', methods=['GET'])
def get_storage_data():
    """Return storage usage breakdown for the Storage page."""
    try:
        payload = db.get_storage_snapshot()
        payload['status'] = 'success'
        payload['generated_at'] = time.time()
        return jsonify(payload)
    except Exception as e:
        flask_logger.error("Error loading storage data: %s", e, exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ── Health & OpenAPI ──────────────────────────────────────────

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint. Returns system status."""
    try:
        device_count = len(io_manager.list_all_streams())
    except Exception:
        device_count = -1
    
    try:
        task_count = len(task_manager.list_tasks())
    except Exception:
        task_count = -1
    
    return jsonify({
        'status': 'ok',
        'service': 'videomemory',
        'devices_detected': device_count,
        'active_tasks': task_count,
    })


@app.route('/api/version', methods=['GET'])
def version_check():
    """Return current app version plus best-effort latest release info."""
    force_refresh = request.args.get("refresh", "").strip().lower() in {"1", "true", "yes"}
    response = jsonify(_get_version_payload(force_refresh=force_refresh))
    return _apply_no_store_headers(response)


@app.route('/healthz', methods=['GET'])
def healthz():
    """Shallow health endpoint for HTTP clients that probe /healthz."""
    return jsonify({'status': 'ok', 'service': 'videomemory'})

@app.route('/openapi.json', methods=['GET'])
def openapi_spec():
    """Serve the OpenAPI 3.1 specification for this API."""
    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "VideoMemory API",
            "version": "1.0.0",
            "description": (
                "VideoMemory is a video monitoring system that lets you create tasks for "
                "camera input devices. The system analyses video streams using vision-language "
                "models and records task updates when conditions are detected. This API exposes "
                "the core ingestion and task-management capabilities for external agents."
            ),
        },
        "servers": [{"url": "http://localhost:5050", "description": "Local dev server"}],
        "paths": {
            "/api/health": {
                "get": {
                    "operationId": "health_check",
                    "summary": "Health check",
                    "description": "Returns system status including device and task counts.",
                    "responses": {
                        "200": {
                            "description": "System is running",
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string", "example": "ok"},
                                    "service": {"type": "string", "example": "videomemory"},
                                    "devices_detected": {"type": "integer"},
                                    "active_tasks": {"type": "integer"},
                                },
                            }}},
                        }
                    },
                }
            },
            "/api/version": {
                "get": {
                    "operationId": "version_check",
                    "summary": "Check VideoMemory app version",
                    "description": "Returns the running app version and best-effort latest release metadata.",
                    "parameters": [
                        {
                            "name": "refresh",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "boolean"},
                            "description": "Bypass the cached update-check result.",
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Version and update-check status",
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {
                                    "current_version": {"type": "string", "example": "0.1.1"},
                                    "latest_version": {"type": "string", "example": "0.1.2"},
                                    "update_available": {"type": ["boolean", "null"]},
                                    "release_notes_url": {"type": "string"},
                                    "update_command": {"type": "string"},
                                    "check_error": {"type": "string"},
                                },
                            }}},
                        }
                    },
                }
            },
            "/api/devices": {
                "get": {
                    "operationId": "list_devices",
                    "summary": "List input devices",
                    "description": "Lists all available input devices (cameras, etc.) with their io_ids, organized by category.",
                    "responses": {
                        "200": {
                            "description": "Devices grouped by category",
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {
                                    "devices": {
                                        "type": "object",
                                        "description": "Devices organized by category name",
                                        "additionalProperties": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "io_id": {"type": "string", "description": "Unique device identifier (use this in add_task)"},
                                                    "name": {"type": "string"},
                                                },
                                            },
                                        },
                                    }
                                },
                            }}},
                        }
                    },
                }
            },
            "/api/device/{io_id}/preview": {
                "get": {
                    "operationId": "get_device_preview",
                    "summary": "Fetch the latest preview image for a device",
                    "description": (
                        "Returns the latest available JPEG frame for the specified camera device. "
                        "Use this for requests like 'send me a picture/photo of the camera' or "
                        "'show me the current frame'."
                    ),
                    "parameters": [{
                        "name": "io_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Device identifier from GET /api/devices",
                    }],
                    "responses": {
                        "200": {
                            "description": "JPEG preview bytes",
                            "content": {
                                "image/jpeg": {
                                    "schema": {"type": "string", "format": "binary"},
                                }
                            },
                        },
                        "404": {"description": "No frame is currently available for the specified device"},
                    },
                }
            },
            "/api/device/{io_id}/capture": {
                "post": {
                    "operationId": "capture_device_frame",
                    "summary": "Take a fresh capture for a device",
                    "description": (
                        "Captures a fresh JPEG frame for the specified camera device. "
                        "By default the endpoint returns image/jpeg bytes so shell tools can "
                        "write the file directly. Pass ?format=json to receive capture metadata "
                        "including a fetchable capture URL and the local saved path."
                    ),
                    "parameters": [
                        {
                            "name": "io_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Device identifier from GET /api/devices",
                        },
                        {
                            "name": "format",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "enum": ["image", "jpeg", "json"]},
                            "description": "Response format. Default is image/jpeg bytes.",
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Fresh capture bytes or metadata",
                            "content": {
                                "image/jpeg": {
                                    "schema": {"type": "string", "format": "binary"},
                                },
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string"},
                                            "io_id": {"type": "string"},
                                            "capture_id": {"type": "string"},
                                            "capture_url": {"type": "string"},
                                            "local_path": {"type": "string"},
                                            "mime_type": {"type": "string"},
                                            "bytes": {"type": "integer"},
                                            "source": {"type": "string"},
                                        },
                                    }
                                },
                            },
                        },
                        "404": {"description": "No fresh capture is currently available for the specified device"},
                    },
                }
            },
            "/api/captures/{capture_id}": {
                "get": {
                    "operationId": "get_saved_capture",
                    "summary": "Download a previously saved fresh capture",
                    "parameters": [{
                        "name": "capture_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Capture identifier returned by POST /api/device/{io_id}/capture?format=json",
                    }],
                    "responses": {
                        "200": {
                            "description": "JPEG capture bytes",
                            "content": {
                                "image/jpeg": {
                                    "schema": {"type": "string", "format": "binary"},
                                }
                            },
                        },
                        "404": {"description": "Capture not found"},
                    },
                }
            },
            "/api/caption_frame": {
                "post": {
                    "operationId": "caption_frame",
                    "summary": "Caption/query the latest frame for a device",
                    "description": (
                        "Runs a one-off vision-language query on the latest available frame "
                        "for the specified device."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["prompt", "io_id"],
                            "properties": {
                                "prompt": {"type": "string", "description": "Natural-language instruction for the model"},
                                "io_id": {"type": "string", "description": "Device identifier from GET /api/devices"},
                            },
                        }}},
                    },
                    "responses": {
                        "200": {"description": "Caption/query result returned"},
                        "400": {"description": "Validation error"},
                        "404": {"description": "No frame available for the specified device"},
                    },
                }
            },
            "/api/tasks": {
                "get": {
                    "operationId": "list_tasks",
                    "summary": "List all tasks",
                    "description": "Lists all tasks, optionally filtered by io_id.",
                    "parameters": [{
                        "name": "io_id",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                        "description": "Filter tasks to a specific input device.",
                    }],
                    "responses": {
                        "200": {
                            "description": "List of tasks",
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string"},
                                    "tasks": {"type": "array", "items": {"$ref": "#/components/schemas/TaskSummary"}},
                                    "count": {"type": "integer"},
                                },
                            }}},
                        }
                    },
                },
                "post": {
                    "operationId": "add_task",
                    "summary": "Add a new task",
                    "description": (
                        "Creates a new monitoring task for an input device. The system will start "
                        "analysing the video feed according to the task description. "
                        "First call GET /api/devices to find the io_id of the camera you want to use."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["io_id", "task_description"],
                            "properties": {
                                "io_id": {"type": "string", "description": "Device identifier from GET /api/devices"},
                                "task_description": {"type": "string", "description": "What to monitor for, e.g. 'Count the number of people entering the room'"},
                                "bot_id": {"type": "string", "description": "Optional identifier of the bot that created this task (multi-bot / debug)."},
                                "save_note_frames": {"type": "boolean", "description": "Optional per-task override for saving a frame with each task note."},
                                "save_note_videos": {"type": "boolean", "description": "Optional per-task override for saving an evidence clip with each task note."},
                                "semantic_filter_keywords": {
                                    "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                                    "description": "Optional keywords required by the device-level semantic filter before frames are sent to the VLM. Alias: required_keywords.",
                                },
                                "semantic_filter_threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                                "semantic_filter_threshold_mode": {"type": "string", "enum": ["absolute", "percentile"], "default": "absolute"},
                                "semantic_filter_reduce": {"type": "string", "enum": ["max", "mean", "min", "sum", "softmax"], "default": "max"},
                                "semantic_filter_smoothing": {"type": "number", "minimum": 0, "maximum": 0.95, "default": 0.0},
                                "semantic_filter_ensemble": {"type": "string", "enum": ["off", "hflip", "hvflip"], "default": "off"},
                            },
                        }}},
                    },
                    "responses": {
                        "201": {"description": "Task created successfully"},
                        "400": {"description": "Validation error or device not found"},
                    },
                },
            },
            "/api/task/{task_id}": {
                "get": {
                    "operationId": "get_task_info",
                    "summary": "Get task details",
                    "description": "Gets detailed information about a task including its notes (observations from the video analysis) and current status.",
                    "parameters": [{"name": "task_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Task details with notes"},
                        "404": {"description": "Task not found"},
                    },
                },
                "put": {
                    "operationId": "edit_task",
                    "summary": "Edit a task's description",
                    "description": (
                        "Updates a task's description. The task keeps running with the same notes "
                        "and status. Useful for amending tasks, e.g. adding an action trigger: "
                        "'Count claps' -> 'Count claps and send email to user@test.com when it reaches 5'."
                    ),
                    "parameters": [{"name": "task_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["new_description"],
                            "properties": {
                                "new_description": {"type": "string", "description": "The updated task description"},
                                "save_note_frames": {"type": "boolean", "description": "Optional per-task override for saving a frame with each task note."},
                                "save_note_videos": {"type": "boolean", "description": "Optional per-task override for saving an evidence clip with each task note."},
                            },
                        }}},
                    },
                    "responses": {
                        "200": {"description": "Task updated successfully"},
                        "404": {"description": "Task not found"},
                    },
                },
                "delete": {
                    "operationId": "remove_task",
                    "summary": "Permanently delete a task",
                    "description": "Permanently deletes a task and all its notes. Use POST /api/task/{task_id}/stop instead if you just want to stop it while keeping history.",
                    "parameters": [{"name": "task_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Task deleted"},
                        "404": {"description": "Task not found"},
                    },
                },
            },
            "/api/task/{task_id}/stop": {
                "post": {
                    "operationId": "stop_task",
                    "summary": "Stop a running task",
                    "description": "Stops a running task. The task is marked as done and video processing stops, but the task and all its notes remain visible in the tasks list.",
                    "parameters": [{"name": "task_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Task stopped"},
                        "404": {"description": "Task not found"},
                    },
                }
            },
            "/api/task-note/{note_id}/frame": {
                "get": {
                    "operationId": "get_task_note_frame",
                    "summary": "Fetch saved note frame",
                    "description": "Returns the exact saved frame associated with a task note when frame evidence was stored.",
                    "parameters": [{"name": "note_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"description": "JPEG frame bytes"},
                        "404": {"description": "No saved frame for this note"},
                    },
                }
            },
            "/api/task-note/{note_id}/video": {
                "get": {
                    "operationId": "get_task_note_video",
                    "summary": "Fetch saved note video",
                    "description": "Returns the exact saved evidence clip associated with a task note when video evidence was stored.",
                    "parameters": [{"name": "note_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"description": "Video clip bytes"},
                        "404": {"description": "No saved video for this note"},
                    },
                }
            },
            "/api/storage": {
                "get": {
                    "operationId": "get_storage_data",
                    "summary": "Summarize storage usage",
                    "description": "Returns storage totals for note media, database files, logs, and the overall VideoMemory workspace.",
                    "responses": {
                        "200": {"description": "Storage summary and per-task breakdown"},
                    },
                }
            },
            "/api/devices/network": {
                "post": {
                    "operationId": "add_network_camera",
                    "summary": "Add a network camera",
                    "description": "Register a network camera by providing its RTSP URL, MJPEG stream URL, or HTTP snapshot URL. The camera will appear in the device list and can be used for tasks.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["url"],
                            "properties": {
                                "url": {"type": "string", "description": "Camera URL (e.g. rtsp://..., rtsps://..., http://camera/stream.mjpeg, or http://phone:8080/snapshot.jpg)"},
                                "name": {"type": "string", "description": "Optional display name for the camera"},
                            },
                        }}},
                    },
                    "responses": {
                        "200": {"description": "Camera added successfully"},
                        "400": {"description": "Validation error"},
                    },
                }
            },
            "/api/devices/network/{io_id}": {
                "delete": {
                    "operationId": "remove_network_camera",
                    "summary": "Remove a network camera",
                    "description": "Removes a previously added network camera. Active tasks for the camera will be stopped first.",
                    "parameters": [{"name": "io_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Camera removed"},
                        "404": {"description": "Camera not found"},
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "TaskSummary": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "task_desc": {"type": "string"},
                        "io_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["active", "done", "terminated"]},
                        "done": {"type": "boolean"},
                        "bot_id": {"type": "string", "description": "Optional bot that created this task (multi-bot / debug)."},
                    },
                },
            }
        },
    }
    return jsonify(spec)

# ── Settings API ──────────────────────────────────────────────

# Keys that should be masked when returned to the frontend
_SENSITIVE_KEYS = {
    'GOOGLE_API_KEY', 'OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'ANTHROPIC_API_KEY',
    'VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN',
    'VIDEOMEMORY_SIMPLEAGENT_OPENAI_API_KEY',
    'VIDEOMEMORY_SIMPLEAGENT_ANTHROPIC_API_KEY',
    'VIDEOMEMORY_SIMPLEAGENT_GOOGLE_API_KEY',
    'VIDEOMEMORY_SIMPLEAGENT_TELEGRAM_BOT_TOKEN',
}

# Models that use local vLLM (no cloud API)
_LOCAL_VLLM_MODELS = {'local-vllm'}

_BOOLEAN_TRUE_VALUES = {'1', 'true', 'yes', 'on'}
_BOOLEAN_FALSE_VALUES = {'0', 'false', 'no', 'off'}
_DEFAULT_SETTINGS = {
    'VIDEOMEMORY_SAVE_NOTE_FRAMES': '1',
    'VIDEOMEMORY_SAVE_NOTE_VIDEOS': '0',
    'VIDEOMEMORY_VIDEO_CHUNK_SECONDS': '2.0',
    'VIDEOMEMORY_VIDEO_CHUNK_SUBSAMPLE_FRAMES': '9',
    'VIDEOMEMORY_VIDEO_CHUNK_QUEUE_MAXSIZE': '10',
    'VIDEOMEMORY_SEMANTIC_FRAME_QUEUE_MAXSIZE': '3',
}

# All known setting keys (for the settings page)
_KNOWN_SETTINGS = [
    'GOOGLE_API_KEY',
    'OPENAI_API_KEY',
    'OPENROUTER_API_KEY',
    'ANTHROPIC_API_KEY',
    'VIDEO_INGESTOR_MODEL',
    'VIDEOMEMORY_SELF_BASE_URL',
    'VIDEOMEMORY_SAVE_NOTE_FRAMES',
    'VIDEOMEMORY_SAVE_NOTE_VIDEOS',
    'VIDEOMEMORY_VIDEO_CHUNK_SECONDS',
    'VIDEOMEMORY_VIDEO_CHUNK_SUBSAMPLE_FRAMES',
    'VIDEOMEMORY_VIDEO_CHUNK_QUEUE_MAXSIZE',
    'VIDEOMEMORY_SEMANTIC_FRAME_QUEUE_MAXSIZE',
    'LOCAL_MODEL_BASE_URL',
    'VIDEOMEMORY_OPENCLAW_WEBHOOK_URL',
    'VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN',
    'VIDEOMEMORY_OPENCLAW_WEBHOOK_TIMEOUT_S',
    'VIDEOMEMORY_OPENCLAW_DEDUPE_TTL_S',
    'VIDEOMEMORY_OPENCLAW_MIN_INTERVAL_S',
    'VIDEOMEMORY_OPENCLAW_BOT_ID',
    'VIDEOMEMORY_SIMPLEAGENT_BASE_URL',
    'VIDEOMEMORY_SIMPLEAGENT_OPENAI_API_KEY',
    'VIDEOMEMORY_SIMPLEAGENT_ANTHROPIC_API_KEY',
    'VIDEOMEMORY_SIMPLEAGENT_GOOGLE_API_KEY',
    'VIDEOMEMORY_SIMPLEAGENT_TELEGRAM_BOT_TOKEN',
]

_MODEL_RUNTIME_KEYS = {
    'GOOGLE_API_KEY',
    'OPENAI_API_KEY',
    'OPENROUTER_API_KEY',
    'ANTHROPIC_API_KEY',
    'VIDEO_INGESTOR_MODEL',
    'LOCAL_MODEL_BASE_URL',
}

_VIDEO_CHUNK_RUNTIME_KEYS = {
    'VIDEOMEMORY_VIDEO_CHUNK_SECONDS',
    'VIDEOMEMORY_VIDEO_CHUNK_SUBSAMPLE_FRAMES',
    'VIDEOMEMORY_VIDEO_CHUNK_QUEUE_MAXSIZE',
    'VIDEOMEMORY_SEMANTIC_FRAME_QUEUE_MAXSIZE',
}


def _current_ingestor_model_name() -> str:
    """Return the normalized effective ingestor model name."""
    return normalize_model_name(os.getenv('VIDEO_INGESTOR_MODEL')) or 'local-vllm'


def _selected_ingestor_model_name_from_settings() -> str:
    """Return the selected model using the same precedence as the Settings UI."""
    selected_value, _ = _get_effective_setting_value_and_source('VIDEO_INGESTOR_MODEL')
    return normalize_model_name(selected_value) or 'local-vllm'


def _build_task_creation_model_error() -> Optional[tuple[dict, int]]:
    """Return an actionable error when task creation would use an unconfigured model."""
    model_name = _selected_ingestor_model_name_from_settings()
    required_setting = get_required_api_key_env(model_name)
    if not required_setting:
        return None

    required_value, _ = _get_effective_setting_value_and_source(required_setting)
    if str(required_value or '').strip():
        return None

    body = {
        'status': 'error',
        'error': f"Model '{model_name}' requires {required_setting}, but it is not configured.",
        'hint': (
            f"Open the Settings tab and save a valid {required_setting}, or switch "
            "VIDEO_INGESTOR_MODEL to another configured model before creating monitoring tasks."
        ),
        'current_model': model_name,
        'required_setting': required_setting,
        'settings_url': '/settings',
    }

    suggested_model = choose_default_model_for_available_keys()
    if suggested_model and suggested_model != model_name:
        suggested_key = get_required_api_key_env(suggested_model)
        body['suggested_model'] = suggested_model
        if suggested_key:
            body['suggested_required_setting'] = suggested_key

    return body, 503


def _looks_like_invalid_api_key_error(message: str) -> bool:
    """Best-effort detection for upstream auth failures caused by bad API keys."""
    normalized = str(message or '').strip().lower()
    if not normalized:
        return False

    key_markers = (
        'invalid x-api-key',
        'invalid api key',
        'invalid api-key',
        'incorrect api key',
        'incorrect api-key',
        'authentication_error',
        'invalid authentication',
    )
    if any(marker in normalized for marker in key_markers):
        return True

    return '401' in normalized and ('key' in normalized or 'auth' in normalized)


def _build_caption_frame_provider_error(exc: Exception, *, provider_name: str) -> tuple[dict, int]:
    """Turn provider/configuration failures into actionable API errors."""
    model_name = _current_ingestor_model_name()
    message = str(exc).strip() or exc.__class__.__name__
    required_setting = get_required_api_key_env(model_name)

    if model_name == 'local-vllm':
        base_url = (os.getenv('LOCAL_MODEL_BASE_URL') or os.getenv('VLLM_LOCAL_URL') or 'http://localhost:8100').rstrip('/')
        if isinstance(exc, httpx.ConnectError) or 'connection refused' in message.lower() or base_url in message:
            suggested_model = choose_default_model_for_available_keys()
            body = {
                'status': 'error',
                'error': f"VideoMemory is configured to use local-vllm at {base_url}, but that server is not reachable.",
                'hint': f"Start the local vLLM server at {base_url}, or set VIDEO_INGESTOR_MODEL to a configured cloud model.",
                'current_model': model_name,
                'model_provider': provider_name,
                'local_model_base_url': base_url,
            }
            if suggested_model:
                suggested_key = get_required_api_key_env(suggested_model)
                body['suggested_model'] = suggested_model
                if suggested_key:
                    body['required_setting'] = suggested_key
                    body['hint'] = (
                        f"{suggested_key} is available, so setting VIDEO_INGESTOR_MODEL to '{suggested_model}' "
                        f"should use the cloud provider immediately."
                    )
            else:
                body['required_setting'] = 'OPENAI_API_KEY | GOOGLE_API_KEY | ANTHROPIC_API_KEY | OPENROUTER_API_KEY'
            return body, 503

    if required_setting:
        normalized_message = message.lower()
        invalid_key = _looks_like_invalid_api_key_error(message)
        missing_or_invalid_key = (
            invalid_key
            or 'api key' in normalized_message
            or 'not initialized' in normalized_message
            or required_setting.lower() in normalized_message
        )
        if missing_or_invalid_key:
            if invalid_key:
                error = f"Model '{model_name}' requires a valid {required_setting}, but the configured key was rejected by the provider."
            else:
                error = f"Model '{model_name}' requires {required_setting}, but it is not configured."
            return {
                'status': 'error',
                'error': error,
                'hint': f"Save a valid {required_setting} in Settings or switch VIDEO_INGESTOR_MODEL to another configured model.",
                'current_model': model_name,
                'model_provider': provider_name,
                'required_setting': required_setting,
            }, 503

    return {
        'status': 'error',
        'error': message,
        'current_model': model_name,
        'model_provider': provider_name,
    }, 500


def _coerce_boolean_setting(value, *, default: bool) -> bool:
    """Parse a boolean-ish setting value while preserving sensible defaults."""
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized in _BOOLEAN_TRUE_VALUES:
        return True
    if normalized in _BOOLEAN_FALSE_VALUES:
        return False
    return default


def _coerce_optional_boolean_request_value(value) -> Optional[bool]:
    """Parse an optional boolean field from JSON requests."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if normalized in _BOOLEAN_TRUE_VALUES:
        return True
    if normalized in _BOOLEAN_FALSE_VALUES:
        return False
    return None


def _coerce_semantic_keywords(value) -> str:
    """Normalize semantic keyword input from task creation helpers."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _parse_task_semantic_filter_config(data: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Build optional semantic-filter settings supplied during task creation."""

    nested = data.get("semantic_filter")
    if nested is not None and not isinstance(nested, dict):
        return None, "semantic_filter must be an object when provided"
    nested_config = nested if isinstance(nested, dict) else {}

    keywords = _coerce_semantic_keywords(
        data.get(
            "semantic_filter_keywords",
            data.get("required_keywords", data.get("semantic_keywords", nested_config.get("keywords"))),
        )
    )
    if not keywords:
        return {
            "enabled": False,
            "keywords": "",
            "threshold": 0.5,
            "threshold_mode": "absolute",
            "reduce": "max",
            "smoothing": 0.0,
            "ensemble": "off",
        }, None

    threshold_mode = str(
        data.get("semantic_filter_threshold_mode", nested_config.get("threshold_mode", "absolute"))
    ).strip().lower()
    if threshold_mode not in {'absolute', 'percentile'}:
        return None, "semantic_filter_threshold_mode must be absolute or percentile"

    reduce = str(data.get("semantic_filter_reduce", nested_config.get("reduce", "max"))).strip().lower()
    if reduce not in {'max', 'mean', 'min', 'sum', 'softmax'}:
        return None, "semantic_filter_reduce must be max, mean, min, sum, or softmax"

    ensemble = str(data.get("semantic_filter_ensemble", nested_config.get("ensemble", "off"))).strip().lower()
    if ensemble not in {'off', 'hflip', 'hvflip'}:
        return None, "semantic_filter_ensemble must be off, hflip, or hvflip"

    try:
        threshold = float(data.get("semantic_filter_threshold", nested_config.get("threshold", 0.5)))
    except (TypeError, ValueError):
        return None, "semantic_filter_threshold must be numeric"
    max_threshold = 1.0 if threshold_mode == 'absolute' else 0.99
    if threshold < 0 or threshold > max_threshold:
        return None, f"semantic_filter_threshold must be between 0 and {max_threshold}"

    try:
        smoothing = float(data.get("semantic_filter_smoothing", nested_config.get("smoothing", 0.0)))
    except (TypeError, ValueError):
        return None, "semantic_filter_smoothing must be numeric"
    if smoothing < 0 or smoothing > 0.95:
        return None, "semantic_filter_smoothing must be between 0 and 0.95"

    return {
        "enabled": True,
        "keywords": keywords,
        "threshold": threshold,
        "threshold_mode": threshold_mode,
        "reduce": reduce,
        "smoothing": smoothing,
        "ensemble": ensemble,
    }, None


def _get_effective_setting_value_and_source(key: str) -> tuple[str, str]:
    """Resolve a setting from DB/env/default and report the source."""
    db_val = db.get_setting(key)
    if db_val is not None:
        return db_val, 'database'

    env_val = os.getenv(key, '')
    if env_val:
        return env_val, 'env'

    if key in _DEFAULT_SETTINGS:
        return _DEFAULT_SETTINGS[key], 'default'

    return '', 'unset'


def _apply_runtime_setting_change(changed_key: str) -> None:
    """Apply in-process runtime reloads needed for a changed setting key."""
    if changed_key in _MODEL_RUNTIME_KEYS:
        model_name = os.getenv('VIDEO_INGESTOR_MODEL', '').strip() or None
        reload_result = task_manager.reload_model_provider(model_name=model_name)
        flask_logger.info(
            "Applied model runtime settings update for %s using %s (ingestors=%d)",
            changed_key,
            reload_result.get('provider'),
            reload_result.get('updated_ingestors', 0),
        )
    if changed_key in _VIDEO_CHUNK_RUNTIME_KEYS:
        reload_result = task_manager.reload_video_chunk_settings()
        flask_logger.info(
            "Applied video chunk runtime settings update for %s (ingestors=%d)",
            changed_key,
            reload_result.get('updated_ingestors', 0),
        )

def _mask_value(key: str, value: str) -> str:
    """Mask sensitive values, showing only the last 4 characters."""
    if key in _SENSITIVE_KEYS and value and len(value) > 4:
        return '*' * (len(value) - 4) + value[-4:]
    return value

@app.route('/api/vllm/status', methods=['GET'])
def get_vllm_status():
    """Check if local vLLM server is reachable.
    
    vLLM can take 1–2 min to load models; we retry with longer timeout.
    """
    import urllib.request
    import time
    base_url = (
        os.getenv('LOCAL_MODEL_BASE_URL') or
        os.getenv('VLLM_LOCAL_URL') or
        'http://localhost:8100'
    ).rstrip('/')
    url = f'{base_url}/v1/models'
    timeout = 15  # vLLM model loading can be slow
    for attempt in range(3):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return jsonify({'active': True, 'url': base_url})
        except Exception:
            if attempt < 2:
                time.sleep(3)  # Wait before retry (vLLM may still be starting)
    return jsonify({'active': False, 'url': base_url})


@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get all settings. Sensitive values are masked."""
    try:
        result = {}
        for key in _KNOWN_SETTINGS:
            value, source = _get_effective_setting_value_and_source(key)
            if key == 'VIDEO_INGESTOR_MODEL':
                value = normalize_model_name(value) or value
            result[key] = {
                'value': _mask_value(key, value),
                'is_set': bool(value),
                'source': source,
            }
        # Add model provider type for UI indicator (local vLLM vs cloud)
        model_name = normalize_model_name(result.get('VIDEO_INGESTOR_MODEL', {}).get('value')) or 'local-vllm'
        result['_model_provider_type'] = {
            'type': 'local' if model_name in _LOCAL_VLLM_MODELS else 'cloud',
            'model': model_name,
        }
        return jsonify({'settings': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/<key>', methods=['PUT'])
def update_setting(key):
    """Update a single setting."""
    if key not in _KNOWN_SETTINGS:
        return jsonify({'error': f'Unknown setting: {key}'}), 400
    
    try:
        data = request.get_json(silent=True) or {}
        raw_value = data.get('value', '')
        if key in {'VIDEOMEMORY_SAVE_NOTE_FRAMES', 'VIDEOMEMORY_SAVE_NOTE_VIDEOS'}:
            value = '1' if _coerce_boolean_setting(raw_value, default=True) else '0'
        elif key == 'VIDEOMEMORY_VIDEO_CHUNK_SECONDS':
            try:
                seconds = max(0.1, float(raw_value))
            except (TypeError, ValueError):
                return jsonify({'error': 'Chunk length must be numeric'}), 400
            value = str(seconds)
        elif key in {'VIDEOMEMORY_VIDEO_CHUNK_SUBSAMPLE_FRAMES', 'VIDEOMEMORY_VIDEO_CHUNK_QUEUE_MAXSIZE', 'VIDEOMEMORY_SEMANTIC_FRAME_QUEUE_MAXSIZE'}:
            try:
                count = max(1, int(raw_value))
            except (TypeError, ValueError):
                return jsonify({'error': 'Value must be a whole number'}), 400
            value = str(count)
        elif key == 'VIDEO_INGESTOR_MODEL':
            try:
                value = validate_model_name(raw_value)
                value = '' if value is None else value
            except ValueError as exc:
                return jsonify({'error': str(exc), 'supported_models': get_supported_model_names()}), 400
        else:
            value = '' if raw_value is None else str(raw_value).strip()
        
        if not value:
            # Clear the setting from DB (fall back to .env)
            db.delete_setting(key)
            # Remove from environ too so .env value is used
            os.environ.pop(key, None)
            # Reload from .env
            from dotenv import dotenv_values
            env_vals = dotenv_values()
            if key in env_vals:
                os.environ[key] = env_vals[key]
            _apply_runtime_setting_change(key)
            return jsonify({'status': 'cleared', 'key': key})
        
        # Save to DB and update os.environ for immediate effect
        db.set_setting(key, value)
        os.environ[key] = value
        _apply_runtime_setting_change(key)
        
        return jsonify({'status': 'saved', 'key': key})
    except Exception as e:
        flask_logger.error(f"Failed to update setting {key}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    port = int(os.getenv('PORT', '5050'))
    host = os.getenv('HOST', '0.0.0.0')
    ssl_adhoc = os.getenv('SSL_ADHOC', '0') == '1'
    ssl_cert = os.getenv('SSL_CERT_FILE', '').strip()
    ssl_key = os.getenv('SSL_KEY_FILE', '').strip()

    ssl_context = None
    if ssl_adhoc:
        ssl_context = 'adhoc'
    elif ssl_cert and ssl_key:
        ssl_context = (ssl_cert, ssl_key)

    proto = 'https' if ssl_context else 'http'
    bind_host = host if host not in ('0.0.0.0', '::') else 'localhost'
    print(f"VideoMemory UI: {proto}://{bind_host}:{port}/devices")
    print(f"VideoMemory API health: {proto}://{bind_host}:{port}/api/health")

    app.run(debug=debug, host=host, port=port, threaded=True, ssl_context=ssl_context)
