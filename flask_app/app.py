#!/usr/bin/env python3
"""Flask app for VideoMemory core APIs and UI."""

import asyncio
import os
import re
import sys
import threading
import uuid
from pathlib import Path

# Add parent directory to path so we can import videomemory
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, render_template, request, jsonify, Response, redirect
from dotenv import load_dotenv
import videomemory.system
import videomemory.tools
from videomemory.integrations import OpenClawWakeNotifier
from videomemory.system.logging_config import setup_logging
from videomemory.system.model_providers import get_VLM_provider
from videomemory.system.database import TaskDatabase, get_default_data_dir
import cv2
import platform
from typing import Optional
import logging

flask_logger = logging.getLogger('FlaskApp')

# Load environment variables
load_dotenv()

# Initialize logging
setup_logging()

app = Flask(__name__)

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
openclaw_notifier = OpenClawWakeNotifier.from_env()
task_manager = videomemory.system.TaskManager(
    io_manager=io_manager,
    model_provider=model_provider,
    db=db,
    on_detection_event=openclaw_notifier.notify_task_update,
)

# Set managers in tools
videomemory.tools.tasks.set_managers(io_manager, task_manager)

# Create a persistent event loop in a background thread
# This allows async tasks (like video ingestor) to run continuously
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
        # Wait a moment for the loop to start
        import time
        time.sleep(0.1)
    return background_loop

# Initialize the background loop
background_loop = get_background_loop()

# Store the background loop in a module that video ingestor can access
# This allows the video ingestor to schedule tasks in the persistent loop
import videomemory.system.stream_ingestors.video_stream_ingestor as vsi_module
vsi_module._flask_background_loop = background_loop

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
    """
    try:
        data = request.json
        if not data:
            return jsonify({'status': 'error', 'error': 'Request body must be JSON'}), 400
        
        io_id = data.get('io_id', '').strip()
        task_description = data.get('task_description', '').strip()
        
        if not io_id:
            return jsonify({'status': 'error', 'error': 'io_id is required'}), 400
        if not task_description:
            return jsonify({'status': 'error', 'error': 'task_description is required'}), 400
        
        result = videomemory.tools.tasks.add_task(io_id, task_description)
        
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
    """
    try:
        data = request.json
        if not data:
            return jsonify({'status': 'error', 'error': 'Request body must be JSON'}), 400
        
        new_description = data.get('new_description', '').strip()
        if not new_description:
            return jsonify({'status': 'error', 'error': 'new_description is required'}), 400
        
        result = task_manager.edit_task(task_id, new_description)
        
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
            entry = {
                'io_id': device.get('io_id', ''),
                'name': device.get('name', 'Unknown'),
                'source': device.get('source', 'local'),
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

def _rtmp_url_host() -> str:
    """Host for generated RTMP URLs: from request, env, or placeholder."""
    host = os.environ.get("RTMP_SERVER_HOST", "").strip()
    if host:
        return host.split(":")[0]
    try:
        h = request.host
        if h and h != "localhost" and not h.startswith("127."):
            return h.split(":")[0]
    except Exception:
        pass
    return "YOUR_SERVER_IP"


def _stream_key_from_name(name: str) -> str:
    """Build a safe stream key segment from a user-provided name."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:48] if slug else ""


def _generated_stream_key(data: dict) -> tuple[str, str]:
    """Return (stream_key, display_name) from request payload."""
    requested_device_name = (data.get('device_name') or '').strip()
    requested_name = (data.get('name') or '').strip()
    provided_name = requested_device_name or requested_name
    if requested_device_name and " " in requested_device_name:
        raise ValueError("device_name cannot contain spaces")
    if requested_device_name and not re.match(r"^[A-Za-z0-9_-]+$", requested_device_name):
        raise ValueError("device_name can only contain letters, numbers, underscore, or dash")
    stream_name = _stream_key_from_name(provided_name)
    if stream_name:
        stream_key = f"live/{stream_name}"
        display_name = provided_name
    else:
        stream_key = f"live/phone_{uuid.uuid4().hex[:8]}"
        display_name = f"Network Camera ({stream_key.split('/')[-1]})"
    return stream_key, display_name


@app.route('/api/devices/network/rtmp', methods=['POST'])
def create_rtmp_camera():
    """Create a network camera with a generated RTMP URL for the Android app to push to."""
    try:
        data = request.get_json(silent=True) or {}
        host = _rtmp_url_host()
        try:
            stream_key, name = _generated_stream_key(data)
        except ValueError as ve:
            return jsonify({"status": "error", "error": str(ve)}), 400
        if name.startswith("Network Camera "):
            name = f"RTMP Camera ({stream_key.split('/')[-1]})"
        url = f"rtmp://{host}:1935/{stream_key}"
        camera_info = io_manager.add_network_camera(url, name)
        stream_info = io_manager.get_stream_info(camera_info["io_id"]) or camera_info
        return jsonify({
            "status": "success",
            "device": camera_info,
            "rtmp_url": url,
            "rtsp_pull_url": stream_info.get("pull_url"),
        })
    except Exception as e:
        flask_logger.error(f"Error creating RTMP camera: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/devices/network/srt', methods=['POST'])
def create_srt_camera():
    """Create a network camera with a generated SRT publish URL (low-latency uplink)."""
    try:
        data = request.get_json(silent=True) or {}
        host = _rtmp_url_host()
        try:
            stream_key, name = _generated_stream_key(data)
        except ValueError as ve:
            return jsonify({"status": "error", "error": str(ve)}), 400
        if name.startswith("Network Camera "):
            name = f"SRT Camera ({stream_key.split('/')[-1]})"

        # MediaMTX/SRT convention: streamid encodes publish:path
        srt_url = f"srt://{host}:8890?streamid=publish:{stream_key}"
        camera_info = io_manager.add_network_camera(srt_url, name)
        stream_info = io_manager.get_stream_info(camera_info["io_id"]) or camera_info
        return jsonify({
            "status": "success",
            "device": camera_info,
            "srt_url": srt_url,
            "rtsp_pull_url": stream_info.get("pull_url"),
            "notes": "Use SRT caller mode from the phone/app. VideoMemory will pull via RTSP.",
        })
    except Exception as e:
        flask_logger.error(f"Error creating SRT camera: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/devices/network/whip', methods=['POST'])
def create_whip_camera():
    """Create a network camera for WebRTC/WHIP ingest (very low latency)."""
    try:
        data = request.get_json(silent=True) or {}
        host = _rtmp_url_host()
        scheme = "https" if request.is_secure else "http"
        try:
            stream_key, name = _generated_stream_key(data)
        except ValueError as ve:
            return jsonify({"status": "error", "error": str(ve)}), 400
        if name.startswith("Network Camera "):
            name = f"WHIP Camera ({stream_key.split('/')[-1]})"

        # Store a synthetic 'whip://' source so VideoMemory derives RTSP pull cleanly.
        stored_url = f"whip://{host}:8889/{stream_key}"
        whip_url = f"{scheme}://{host}:8889/{stream_key}/whip"
        camera_info = io_manager.add_network_camera(stored_url, name)
        stream_info = io_manager.get_stream_info(camera_info["io_id"]) or camera_info
        return jsonify({
            "status": "success",
            "device": camera_info,
            "whip_url": whip_url,
            "rtsp_pull_url": stream_info.get("pull_url"),
            "notes": "Use a WHIP-capable WebRTC publisher. For internet deployment, set proper ICE/public host config in MediaMTX.",
        })
    except Exception as e:
        flask_logger.error(f"Error creating WHIP camera: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/devices/network', methods=['POST'])
def add_network_camera():
    """Add a network camera (RTSP/HTTP/RTMP stream). RTMP URLs are converted to RTSP for pulling (SRS-compatible)."""
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'error': 'Request body required'}), 400

    url = data.get('url', '').strip()
    name = data.get('name', '').strip() or None

    if not url:
        return jsonify({'status': 'error', 'error': 'url is required'}), 400

    try:
        camera_info = io_manager.add_network_camera(url, name)
        return jsonify({'status': 'success', 'device': camera_info})
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

    if io_manager.remove_network_camera(io_id):
        return jsonify({'status': 'success', 'message': f'Network camera {io_id} removed'})
    return jsonify({'status': 'error', 'error': f'Network camera {io_id} not found'}), 404


def _get_network_preview_frame(url: str) -> Optional[bytes]:
    """Capture a single preview frame from a network stream URL.

    This path is used by the Devices page; fail fast so one dead stream doesn't
    stall all preview requests.
    """
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


@app.route('/api/device/<io_id>/preview', methods=['GET'])
def get_device_preview(io_id):
    """Get a preview image from a camera device.
    
    Only works for camera devices. Returns a placeholder or error for other devices.
    Tries to use frames from active video ingestors first (faster), falls back to
    opening camera directly if no ingestor is active.
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

        # Try active ingestor frame first for lower latency and less camera churn.
        latest_frame = task_manager.get_latest_frame_for_device(io_id)
        if latest_frame is not None and latest_frame.size > 0:
            frame_mean = latest_frame.mean()
            if frame_mean >= 1:
                _, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return buffer.tobytes()

        pull_url = device_info.get('pull_url') or device_info.get('url')
        if pull_url:
            return _get_network_preview_frame(pull_url)

        try:
            camera_index = int(io_id)
        except (ValueError, TypeError):
            return None
        return _get_camera_preview_frame(camera_index)
    except Exception as e:
        flask_logger.debug(f"Error building preview for {io_id}: {e}")
        return None


@app.route('/api/device/<io_id>/preview/stream', methods=['GET'])
def get_device_preview_stream(io_id):
    """Stream device previews as MJPEG for smoother live debugging."""
    import time

    fps = max(1.0, min(15.0, float(os.getenv("VIDEOMEMORY_PREVIEW_STREAM_FPS", "6"))))
    frame_delay_s = 1.0 / fps
    boundary = "frame"

    def _open_preview_capture(source):
        cap = cv2.VideoCapture()
        if isinstance(source, str) and source.startswith(("rtsp://", "rtsps://", "http://", "https://", "rtmp://", "srt://", "whip://")):
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

    def generate():
        cap = None
        cap_source = None
        try:
            while True:
                frame_data = None

                latest_frame = task_manager.get_latest_frame_for_device(io_id)
                if latest_frame is not None and latest_frame.size > 0 and latest_frame.mean() >= 1:
                    _, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    frame_data = buffer.tobytes()
                else:
                    device_info = io_manager.get_stream_info(io_id)
                    if device_info is not None and 'camera' in (device_info.get('category', '').lower()):
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

                        if cap is None or cap_source != desired_source or not cap.isOpened():
                            if cap is not None:
                                cap.release()
                            cap = _open_preview_capture(desired_source)
                            cap_source = desired_source if cap is not None else None

                        if cap is not None and cap.isOpened():
                            ret, frame = cap.read()
                            if ret and frame is not None and frame.size > 0:
                                if frame.shape[1] > 640 or frame.shape[0] > 480:
                                    frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_LINEAR)
                                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                                frame_data = buffer.tobytes()
                            else:
                                cap.release()
                                cap = None
                                cap_source = None

                if frame_data is not None:
                    yield (
                        b"--" + boundary.encode("ascii") + b"\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Cache-Control: no-cache, no-store, must-revalidate\r\n"
                        b"Pragma: no-cache\r\n"
                        b"Expires: 0\r\n\r\n" +
                        frame_data + b"\r\n"
                    )
                time.sleep(frame_delay_s)
        finally:
            if cap is not None:
                cap.release()

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

# ── Ingestor Debug API ────────────────────────────────────────

@app.route('/api/device/<io_id>/debug/status', methods=['GET'])
def get_ingestor_status(io_id):
    """Check whether an ingestor is running for a device."""
    try:
        has = task_manager.has_ingestor(io_id)
        ingestor = task_manager.get_ingestor(io_id) if has else None
        running = ingestor._running if ingestor else False
        return jsonify({
            'has_ingestor': has,
            'running': running,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/device/<io_id>/debug/frame-and-prompt', methods=['GET'])
def get_ingestor_frame_and_prompt(io_id):
    """Get the latest frame and prompt from a device's ingestor."""
    import base64
    try:
        ingestor = task_manager.get_ingestor(io_id)
        if ingestor is None:
            return jsonify({'error': 'No active ingestor for this device', 'frame_base64': None, 'prompt': ''}), 200
        if not ingestor._running:
            return jsonify({'error': 'Ingestor not running', 'frame_base64': None, 'prompt': ''}), 200
        
        latest_output = ingestor.get_latest_output()
        if not latest_output:
            return jsonify({'error': 'No output available yet', 'frame_base64': None, 'prompt': ''}), 200
        
        latest_frame = latest_output.get('frame')
        latest_prompt = latest_output.get('prompt', '')
        
        if latest_frame is None:
            return jsonify({'error': 'No frame available', 'frame_base64': None, 'prompt': latest_prompt or ''}), 200
        
        # Convert frame to base64
        _, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        image_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return jsonify({
            'frame_base64': image_base64,
            'prompt': latest_prompt or ''
        })
    except Exception as e:
        flask_logger.error(f"Error in debug frame-and-prompt for {io_id}: {e}", exc_info=True)
        return jsonify({'error': str(e), 'frame_base64': None, 'prompt': ''}), 500

@app.route('/api/device/<io_id>/debug/history', methods=['GET'])
def get_ingestor_history(io_id):
    """Get output history from a device's ingestor."""
    try:
        ingestor = task_manager.get_ingestor(io_id)
        if ingestor is None:
            return jsonify({'history': [], 'count': 0, 'total_count': 0}), 200
        
        history = ingestor.get_output_history()
        # Remove frames and prompts for JSON serialization
        history_clean = [{k: v for k, v in item.items() if k not in ('frame', 'prompt')} for item in history]
        total_count = ingestor.get_total_output_count()
        return jsonify({
            'history': history_clean,
            'count': len(history_clean),
            'total_count': total_count
        })
    except Exception as e:
        flask_logger.error(f"Error in debug history for {io_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/device/<io_id>/debug/tasks', methods=['GET'])
def get_ingestor_tasks(io_id):
    """Get tasks from a device's ingestor."""
    try:
        ingestor = task_manager.get_ingestor(io_id)
        if ingestor is None:
            return jsonify({'tasks': []}), 200
        
        tasks = ingestor.get_tasks_list()
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
            "/api/devices/network/rtmp": {
                "post": {
                    "operationId": "add_camera",
                    "summary": "Create an RTMP camera",
                    "description": (
                        "Creates a network camera and returns an RTMP push URL. "
                        "Use this when setting up phone streaming. device_name must not contain spaces."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["device_name"],
                            "properties": {
                                "device_name": {
                                    "type": "string",
                                    "description": "Camera name and stream key suffix (letters, numbers, underscore, dash; no spaces)"
                                },
                            },
                        }}},
                    },
                    "responses": {
                        "200": {"description": "RTMP camera created successfully"},
                        "400": {"description": "Validation error"},
                    },
                }
            },
            "/api/devices/network": {
                "post": {
                    "operationId": "add_network_camera",
                    "summary": "Add a network camera",
                    "description": "Register a network camera by providing its RTSP or HTTP stream URL. The camera will appear in the device list and can be used for tasks.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["url"],
                            "properties": {
                                "url": {"type": "string", "description": "Stream URL (e.g. rtsp://..., http://..., or rtmp://server/live/key for push sources; RTMP is auto-converted to RTSP)"},
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
}

# All known setting keys (for the settings page)
_KNOWN_SETTINGS = [
    'GOOGLE_API_KEY',
    'OPENAI_API_KEY',
    'OPENROUTER_API_KEY',
    'ANTHROPIC_API_KEY',
    'VIDEO_INGESTOR_MODEL',
    'VIDEOMEMORY_OPENCLAW_WEBHOOK_URL',
    'VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN',
    'VIDEOMEMORY_OPENCLAW_WEBHOOK_TIMEOUT_S',
    'VIDEOMEMORY_OPENCLAW_DEDUPE_TTL_S',
    'VIDEOMEMORY_OPENCLAW_MIN_INTERVAL_S',
]


def _reload_openclaw_notifier_from_env() -> None:
    """Refresh OpenClaw notifier config from current environment settings."""
    try:
        updated = OpenClawWakeNotifier.from_env()
        openclaw_notifier.webhook_url = updated.webhook_url
        openclaw_notifier.bearer_token = updated.bearer_token
        openclaw_notifier.timeout_seconds = updated.timeout_seconds
        openclaw_notifier.dedupe_ttl_seconds = updated.dedupe_ttl_seconds
        openclaw_notifier.min_interval_seconds = updated.min_interval_seconds
        openclaw_notifier.enabled = updated.enabled
    except Exception as e:
        flask_logger.warning("Failed to reload OpenClaw notifier settings: %s", e)

def _mask_value(key: str, value: str) -> str:
    """Mask sensitive values, showing only the last 4 characters."""
    if key in _SENSITIVE_KEYS and value and len(value) > 4:
        return '*' * (len(value) - 4) + value[-4:]
    return value

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get all settings. Sensitive values are masked."""
    try:
        result = {}
        for key in _KNOWN_SETTINGS:
            # Check DB first, then fall back to env
            db_val = db.get_setting(key)
            env_val = os.getenv(key, '')
            value = db_val if db_val is not None else env_val
            result[key] = {
                'value': _mask_value(key, value),
                'is_set': bool(value),
                'source': 'database' if db_val is not None else ('env' if env_val else 'unset')
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
        data = request.json
        value = data.get('value', '').strip()
        
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
            _reload_openclaw_notifier_from_env()
            return jsonify({'status': 'cleared', 'key': key})
        
        # Save to DB and update os.environ for immediate effect
        db.set_setting(key, value)
        os.environ[key] = value
        _reload_openclaw_notifier_from_env()
        
        return jsonify({'status': 'saved', 'key': key})
    except Exception as e:
        flask_logger.error(f"Failed to update setting {key}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    port = int(os.getenv('PORT', '5060'))
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
