#!/usr/bin/env python3
"""Simple Flask app for chat interface with admin agent."""

import asyncio
import os
import re
import sys
import threading
import uuid
from pathlib import Path

# Add parent directory to path so we can import videomemory
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
from google.adk.sessions import DatabaseSessionService
from google.adk.runners import Runner
from google.genai import types
import videomemory.agents
import videomemory.system
import videomemory.tools
from videomemory.system.logging_config import setup_logging
from videomemory.system.model_providers import get_VLM_provider
from videomemory.system.database import TaskDatabase, get_default_data_dir
import cv2
import platform
import requests as http_requests
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

sessions_db_url = f"sqlite+aiosqlite:///{data_dir / 'sessions.db'}"
db = TaskDatabase(str(data_dir / 'videomemory.db'))

# Load saved settings into os.environ BEFORE initializing providers
# This allows DB-stored API keys and config to override .env values
db.load_settings_to_env()
# Notifications go to TELEGRAM_CHAT_ID if set, else to the chat where you last messaged the bot (from DB)
videomemory.tools.actions.set_telegram_notification_chat_id_resolver(
    lambda: db.get_setting("TELEGRAM_NOTIFICATION_CHAT_ID")
)

# ── System components ─────────────────────────────────────────
io_manager = videomemory.system.IOmanager(db=db)
app_name = "videomemory_app"
session_service = DatabaseSessionService(db_url=sessions_db_url)
runner = Runner(
    agent=videomemory.agents.admin_agent,
    app_name=app_name,
    session_service=session_service
)
# Dedicated runner for video-ingestor actions (Telegram, Discord, etc.). Uses action_router
# agent so "send telegram notification: ..." is executed directly without going through admin agent.
action_router_runner = Runner(
    agent=videomemory.agents.action_router_agent,
    app_name=app_name,
    session_service=session_service
)
model_provider = get_VLM_provider()
task_manager = videomemory.system.TaskManager(
    io_manager=io_manager,
    action_runner=action_router_runner,
    session_service=session_service,
    app_name=app_name,
    model_provider=model_provider,
    db=db
)

# Set managers in tools
videomemory.tools.tasks.set_managers(io_manager, task_manager)

# Shared user id for admin chat sessions
USER_ID = "user_1"

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

# ── Helper: run async in background loop ─────────────────────

def run_async(coro, timeout=60):
    """Run an async coroutine in the background event loop and return the result."""
    future = asyncio.run_coroutine_threadsafe(coro, background_loop)
    return future.result(timeout=timeout)

# ── Page routes ───────────────────────────────────────────────

@app.route('/')
def index():
    """Render the chat interface."""
    return render_template('index.html')

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

# ── Session API ───────────────────────────────────────────────

@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    """List all admin chat sessions (metadata only)."""
    try:
        sessions = db.list_session_metadata()
        return jsonify({'sessions': sessions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/new', methods=['POST'])
def create_session():
    """Create a new admin chat session."""
    try:
        session_id = f"chat_{uuid.uuid4().hex[:12]}"
        
        async def _create():
            await session_service.create_session(
                app_name=app_name,
                user_id=USER_ID,
                session_id=session_id
            )
        
        run_async(_create())
        db.save_session_metadata(session_id, title='')
        
        return jsonify({'session_id': session_id})
    except Exception as e:
        flask_logger.error(f"Failed to create session: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<session_id>/messages', methods=['GET'])
def get_session_messages(session_id):
    """Get all messages for a session."""
    try:
        async def _get():
            session = await session_service.get_session(
                app_name=app_name,
                user_id=USER_ID,
                session_id=session_id
            )
            return session
        
        session = run_async(_get())
        if session is None:
            return jsonify({'error': 'Session not found'}), 404
        
        messages = []
        for event in session.events:
            if not event.content or not event.content.parts:
                continue
            # Extract text parts only
            text_parts = []
            for part in event.content.parts:
                if hasattr(part, 'text') and part.text:
                    text_parts.append(part.text)
            if not text_parts:
                continue
            
            messages.append({
                'role': 'user' if event.author == 'user' else 'agent',
                'text': ' '.join(text_parts),
                'timestamp': event.timestamp if hasattr(event, 'timestamp') else None
            })
        
        return jsonify({'messages': messages})
    except Exception as e:
        flask_logger.error(f"Failed to get messages for session {session_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    """Delete a chat session."""
    try:
        async def _delete():
            await session_service.delete_session(
                app_name=app_name,
                user_id=USER_ID,
                session_id=session_id
            )
        
        run_async(_delete())
        db.delete_session_metadata(session_id)
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        flask_logger.error(f"Failed to delete session {session_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

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


@app.route('/api/devices/network/rtmp', methods=['POST'])
def create_rtmp_camera():
    """Create a network camera with a generated RTMP URL for the Android app to push to."""
    try:
        data = request.get_json(silent=True) or {}
        requested_device_name = (data.get('device_name') or '').strip()
        requested_name = (data.get('name') or '').strip()
        provided_name = requested_device_name or requested_name
        host = _rtmp_url_host()
        if requested_device_name and " " in requested_device_name:
            return jsonify({
                "status": "error",
                "error": "device_name cannot contain spaces",
            }), 400
        if requested_device_name and not re.match(r"^[A-Za-z0-9_-]+$", requested_device_name):
            return jsonify({
                "status": "error",
                "error": "device_name can only contain letters, numbers, underscore, or dash",
            }), 400
        stream_name = _stream_key_from_name(provided_name)
        if stream_name:
            stream_key = f"live/{stream_name}"
            name = provided_name
        else:
            stream_key = f"live/phone_{uuid.uuid4().hex[:8]}"
            name = f"RTMP Camera ({stream_key.split('/')[-1]})"
        url = f"rtmp://{host}:1935/{stream_key}"
        camera_info = io_manager.add_network_camera(url, name)
        return jsonify({
            "status": "success",
            "device": camera_info,
            "rtmp_url": url,
        })
    except Exception as e:
        flask_logger.error(f"Error creating RTMP camera: {e}", exc_info=True)
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
    try:
        # Get device info
        device_info = io_manager.get_stream_info(io_id)
        if device_info is None:
            return jsonify({'error': 'Device not found'}), 404
        
        category = device_info.get('category', '').lower()
        
        if 'camera' not in category:
            return Response(response=b'', status=204, mimetype='image/jpeg')
        
        # Try to get frame from active video ingestor first (much faster)
        latest_frame = task_manager.get_latest_frame_for_device(io_id)
        if latest_frame is not None and latest_frame.size > 0:
            frame_mean = latest_frame.mean()
            if frame_mean >= 1:
                _, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return Response(
                    response=buffer.tobytes(),
                    mimetype='image/jpeg',
                    headers={'Cache-Control': 'no-cache, no-store, must-revalidate'}
                )
        
        # Fallback: open camera directly (use pull_url for capture; RTMP→RTSP is in io_manager)
        pull_url = device_info.get('pull_url') or device_info.get('url')
        if pull_url:
            frame_data = _get_network_preview_frame(pull_url)
        else:
            try:
                camera_index = int(io_id)
            except (ValueError, TypeError):
                return Response(response=b'', status=404, mimetype='image/jpeg')
            frame_data = _get_camera_preview_frame(camera_index)
        
        if frame_data is None:
            return Response(response=b'', status=404, mimetype='image/jpeg')
        
        return Response(
            response=frame_data,
            mimetype='image/jpeg',
            headers={'Cache-Control': 'no-cache, no-store, must-revalidate'}
        )
    except Exception as e:
        return Response(response=b'', status=404, mimetype='image/jpeg')

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

# ── Action API ─────────────────────────────────────────────────

from videomemory.tools.actions import send_discord_notification, send_telegram_notification

@app.route('/api/actions/discord', methods=['POST'])
def action_send_discord():
    """Send a Discord notification via webhook.
    
    Body (JSON):
        message (str, required): Message content to send.
        username (str, optional): Override the webhook's bot name.
    """
    try:
        data = request.json or {}
        message = data.get('message', '').strip()
        if not message:
            return jsonify({'status': 'error', 'error': 'message is required'}), 400
        
        result = send_discord_notification(
            message=message,
            username=data.get('username'),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/actions/telegram', methods=['POST'])
def action_send_telegram():
    """Send a Telegram notification via Bot API.
    
    Body (JSON):
        message (str, required): Message content to send.
    """
    try:
        data = request.json or {}
        message = data.get('message', '').strip()
        if not message:
            return jsonify({'status': 'error', 'error': 'message is required'}), 400
        
        result = send_telegram_notification(message=message)
        return jsonify(result)
    except Exception as e:
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
                "models and can trigger actions when conditions are detected. This API exposes "
                "the admin agent's tool calls so an external agent can act as a stand-in."
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
            "/api/actions/discord": {
                "post": {
                    "operationId": "send_discord_notification",
                    "summary": "Send a Discord notification",
                    "description": "Sends a message to Discord via the configured webhook (DISCORD_WEBHOOK_URL setting).",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["message"],
                            "properties": {
                                "message": {"type": "string", "description": "Message content"},
                                "username": {"type": "string", "description": "Override bot display name"},
                            },
                        }}},
                    },
                    "responses": {"200": {"description": "Notification sent"}},
                }
            },
            "/api/actions/telegram": {
                "post": {
                    "operationId": "send_telegram_notification",
                    "summary": "Send a Telegram notification",
                    "description": "Sends a message to Telegram via the Bot API (requires TELEGRAM_BOT_TOKEN; optional TELEGRAM_CHAT_ID in env for one-way notifications).",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["message"],
                            "properties": {
                                "message": {"type": "string", "description": "Message content"},
                            },
                        }}},
                    },
                    "responses": {"200": {"description": "Notification sent"}},
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
    'TELEGRAM_BOT_TOKEN',
}

# All known setting keys (for the settings page)
_KNOWN_SETTINGS = [
    'DISCORD_WEBHOOK_URL',
    'TELEGRAM_BOT_TOKEN',
    'GOOGLE_API_KEY',
    'OPENAI_API_KEY',
    'OPENROUTER_API_KEY',
    'ANTHROPIC_API_KEY',
    'VIDEO_INGESTOR_MODEL',
]

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
            return jsonify({'status': 'cleared', 'key': key})
        
        # Save to DB and update os.environ for immediate effect
        db.set_setting(key, value)
        os.environ[key] = value
        
        # Auto-start Telegram polling if the token was just set and isn't running yet
        if key == 'TELEGRAM_BOT_TOKEN':
            _ensure_telegram_polling()
        
        return jsonify({'status': 'saved', 'key': key})
    except Exception as e:
        flask_logger.error(f"Failed to update setting {key}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/test/discord', methods=['POST'])
def test_discord_webhook():
    """Send a test message to the configured Discord webhook."""
    try:
        webhook_url = os.getenv('DISCORD_WEBHOOK_URL', '')
        if not webhook_url:
            return jsonify({'status': 'error', 'message': 'Discord webhook URL is not configured'}), 400
        
        test_payload = {
            'content': 'Test notification from VideoMemory — your webhook is working!',
            'username': 'VideoMemory'
        }
        
        resp = http_requests.post(webhook_url, json=test_payload, timeout=10)
        
        if resp.status_code == 204:
            return jsonify({'status': 'success', 'message': 'Test message sent successfully!'})
        else:
            return jsonify({
                'status': 'error',
                'message': f'Discord returned status {resp.status_code}'
            }), 400
    except http_requests.exceptions.Timeout:
        return jsonify({'status': 'error', 'message': 'Request timed out'}), 504
    except Exception as e:
        flask_logger.error(f"Discord test failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ── Telegram bot info (for "Open in Telegram" link) ─────────────

@app.route('/api/telegram/bot-info', methods=['GET'])
def telegram_bot_info():
    """Return the bot's t.me link if TELEGRAM_BOT_TOKEN is set. Uses Telegram getMe to resolve username."""
    try:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
        if not bot_token:
            return jsonify({'ok': False})
        resp = http_requests.get(
            f'https://api.telegram.org/bot{bot_token}/getMe',
            timeout=5,
        )
        if not resp.ok:
            return jsonify({'ok': False})
        data = resp.json()
        if not data.get('ok'):
            return jsonify({'ok': False})
        username = (data.get('result') or {}).get('username')
        if not username:
            return jsonify({'ok': False})
        return jsonify({
            'ok': True,
            'url': f'https://t.me/{username}',
            'username': username,
        })
    except Exception:
        return jsonify({'ok': False})

# ── Telegram two-way chat (admin agent via Telegram) ───────────

def _get_or_create_telegram_session(chat_id: int) -> str:
    """Get or create an admin-agent session for this Telegram chat. Returns session_id."""
    session_id = f"telegram_{chat_id}"

    async def _ensure():
        session = await session_service.get_session(
            app_name=app_name, user_id=USER_ID, session_id=session_id
        )
        if session is None:
            await session_service.create_session(
                app_name=app_name, user_id=USER_ID, session_id=session_id
            )
            db.save_session_metadata(session_id, title="Telegram")
        return session_id

    return run_async(_ensure(), timeout=15)


def _run_agent_for_message(session_id: str, user_message: str) -> str:
    """Run the admin agent with the given message in the given session; return reply text."""
    content = types.Content(role="user", parts=[types.Part(text=user_message)])
    final_response_text = "No response received"

    async def get_response():
        nonlocal final_response_text
        gen = runner.run_async(
            user_id=USER_ID,
            session_id=session_id,
            new_message=content,
        )
        try:
            async for event in gen:
                if event.is_final_response():
                    if event.content and event.content.parts:
                        final_response_text = event.content.parts[0].text
                    break
        finally:
            await gen.aclose()

    run_async(get_response(), timeout=60)
    return final_response_text


def _send_telegram_message(bot_token: str, chat_id: int, text: str) -> bool:
    """Send a text message to a Telegram chat. Returns True on success."""
    try:
        resp = http_requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        return resp.ok and resp.json().get("ok", False)
    except Exception as e:
        flask_logger.error(f"Telegram sendMessage failed: {e}", exc_info=True)
        return False


def _process_telegram_update(update: dict) -> None:
    """Process one Telegram update: run agent, send reply. Runs in background thread."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        return
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if chat_id is None or not text:
        return
    # Use this chat for one-way notifications (read from DB when TELEGRAM_CHAT_ID is not set)
    try:
        db.set_setting("TELEGRAM_NOTIFICATION_CHAT_ID", str(chat_id))
    except Exception as e:
        flask_logger.debug(f"Could not save Telegram notification chat_id: {e}")
    try:
        session_id = _get_or_create_telegram_session(chat_id)
        reply = _run_agent_for_message(session_id, text)
        # Telegram message length limit is 4096
        if len(reply) > 4096:
            reply = reply[:4093] + "..."
        _send_telegram_message(bot_token, chat_id, reply)
    except Exception as e:
        flask_logger.error(f"Telegram update processing failed: {e}", exc_info=True)
        _send_telegram_message(
            bot_token,
            chat_id,
            f"Sorry, something went wrong: {str(e)[:500]}",
        )


@app.route("/api/telegram/webhook", methods=["POST"])
def telegram_webhook():
    """Receive Telegram updates (set bot webhook to this URL). Returns 200 immediately; processes in background."""
    data = request.get_json(silent=True) or {}
    # Return 200 quickly so Telegram doesn't retry
    threading.Thread(target=_process_telegram_update, args=(data,), daemon=True).start()
    return "", 200


def _telegram_polling_loop():
    """Long-poll Telegram getUpdates and process messages. Run in a daemon thread."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        return
    last_update_id = 0
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    flask_logger.info("Telegram polling started — you can chat with the admin agent via Telegram.")
    while True:
        try:
            resp = http_requests.get(
                url,
                params={"offset": last_update_id, "timeout": 30},
                timeout=35,
            )
            if not resp.ok:
                continue
            data = resp.json()
            if not data.get("ok"):
                continue
            for update in data.get("result", []):
                last_update_id = update.get("update_id", 0) + 1
                _process_telegram_update(update)
        except Exception as e:
            flask_logger.debug(f"Telegram polling error: {e}")
        except Exception:
            break


_telegram_poll_thread = None

def _ensure_telegram_polling():
    """Start the Telegram polling thread if a token is set and it isn't already running."""
    global _telegram_poll_thread
    if _telegram_poll_thread and _telegram_poll_thread.is_alive():
        return
    if not os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        return
    _telegram_poll_thread = threading.Thread(
        target=_telegram_polling_loop,
        daemon=True,
        name="TelegramPolling",
    )
    _telegram_poll_thread.start()

# Start on boot if token is already available
_ensure_telegram_polling()

# ── Chat API ──────────────────────────────────────────────────

@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages."""
    data = request.json
    user_message = data.get('message', '').strip()
    session_id = data.get('session_id', '').strip()
    
    if not user_message:
        return jsonify({'error': 'Message cannot be empty'}), 400
    
    if not session_id:
        return jsonify({'error': 'session_id is required'}), 400
    
    try:
        # Update session title with first message (if still untitled)
        meta = db.get_session_metadata(session_id)
        if meta and not meta['title']:
            title = user_message[:60].strip()
            if len(user_message) > 60:
                title += '...'
            db.update_session_title(session_id, title)
        
        # Run the agent and get response using the background event loop
        content = types.Content(role='user', parts=[types.Part(text=user_message)])
        
        final_response_text = "No response received"
        async def get_response():
            nonlocal final_response_text
            # Use async generator properly with try/finally to ensure cleanup
            gen = runner.run_async(
                user_id=USER_ID,
                session_id=session_id,
                new_message=content
            )
            try:
                async for event in gen:
                    if event.is_final_response():
                        if event.content and event.content.parts:
                            final_response_text = event.content.parts[0].text
                        break
            finally:
                # Properly close the async generator to avoid resource leaks
                await gen.aclose()

        # Run the coroutine in the background loop
        future = asyncio.run_coroutine_threadsafe(get_response(), background_loop)
        future.result(timeout=60)  # 60 second timeout
        
        return jsonify({'response': final_response_text})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, host='0.0.0.0', port=5050, threaded=True)
