#!/usr/bin/env python3
"""Simple Flask app for chat interface with admin agent."""

import asyncio
import os
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

# ── System components ─────────────────────────────────────────
io_manager = videomemory.system.IOmanager()
app_name = "videomemory_app"
session_service = DatabaseSessionService(db_url=sessions_db_url)
runner = Runner(
    agent=videomemory.agents.admin_agent,
    app_name=app_name,
    session_service=session_service
)
model_provider = get_VLM_provider()
task_manager = videomemory.system.TaskManager(
    io_manager=io_manager,
    action_runner=runner,
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

# ── Task API ──────────────────────────────────────────────────

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """Get all tasks."""
    try:
        tasks_list = task_manager.list_tasks()
        return jsonify({'tasks': tasks_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/task/<task_id>', methods=['GET'])
def get_task(task_id):
    """Get a specific task by ID."""
    try:
        task = task_manager.get_task(task_id)
        if task is None:
            return jsonify({'error': 'Task not found'}), 404
        return jsonify({'task': task})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
        if platform.system() == 'Darwin':  # macOS
            cap = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
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
            by_category[category].append({
                'io_id': device.get('io_id', ''),
                'name': device.get('name', 'Unknown')
            })
        
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Returning {len(devices_list)} devices: {by_category}")
        
        return jsonify({'devices': by_category})
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in get_devices: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

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
        device_name = device_info.get('name', '')
        
        # Only generate previews for cameras
        if 'camera' not in category:
            # Return a placeholder image or empty response
            return Response(
                response=b'',
                status=204,  # No Content
                mimetype='image/jpeg'
            )
        
        # Try to get frame from active video ingestor first (much faster)
        latest_frame = task_manager.get_latest_frame_for_device(io_id)
        if latest_frame is not None and latest_frame.size > 0:
            # For debugging: show whatever frame we have, even if black
            # But if frame is completely black (mean < 1), try direct capture instead
            # as the ingestor might have an old/stale black frame
            frame_mean = latest_frame.mean()
            if frame_mean < 1:
                # Frame is completely black - try direct capture to get fresh frame
                pass  # Fall through to direct capture
            else:
                # Use ingestor frame (even if somewhat dark, but not pure black)
                _, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return Response(
                    response=buffer.tobytes(),
                    mimetype='image/jpeg',
                    headers={'Cache-Control': 'no-cache, no-store, must-revalidate'}
                )
        
        # Fallback: open camera directly if no active ingestor
        try:
            camera_index = int(io_id)
        except (ValueError, TypeError):
            # Invalid io_id - return 404 to indicate device not found
            return Response(
                response=b'',
                status=404,
                mimetype='image/jpeg'
            )
        
        # Capture preview frame
        frame_data = _get_camera_preview_frame(camera_index)
        if frame_data is None:
            # Camera disconnected or unavailable - return 404 to trigger error handler
            return Response(
                response=b'',
                status=404,
                mimetype='image/jpeg'
            )
        
        return Response(
            response=frame_data,
            mimetype='image/jpeg',
            headers={'Cache-Control': 'no-cache, no-store, must-revalidate'}
        )
    except Exception as e:
        # Device error/disconnected - return 404 to trigger error handler
        return Response(
            response=b'',
            status=404,
            mimetype='image/jpeg'
        )

# ── Settings API ──────────────────────────────────────────────

# Keys that should be masked when returned to the frontend
_SENSITIVE_KEYS = {
    'GOOGLE_API_KEY', 'OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'ANTHROPIC_API_KEY'
}

# All known setting keys (for the settings page)
_KNOWN_SETTINGS = [
    'DISCORD_WEBHOOK_URL',
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
    app.run(debug=True, host='0.0.0.0', port=5050)
