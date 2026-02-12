#!/usr/bin/env python3
"""Simple Flask app for chat interface with admin agent."""

import asyncio
import os
import sys
import threading
from pathlib import Path

# Add parent directory to path so we can import videomemory
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types
import videomemory.agents
import videomemory.system
import videomemory.tools
from videomemory.system.logging_config import setup_logging
from videomemory.system.model_providers import get_VLM_provider
import cv2
import platform
from typing import Optional

# Load environment variables
load_dotenv()

# Initialize logging
setup_logging()

app = Flask(__name__)

# Initialize system components (similar to main.py)
io_manager = videomemory.system.IOmanager()
app_name = "videomemory_app"
session_service = InMemorySessionService()
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
    model_provider=model_provider
)

# Set managers in tools
videomemory.tools.tasks.set_managers(io_manager, task_manager)

# Create admin session
USER_ID = "user_1"
SESSION_ID = "admin_session"

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

# Initialize session at startup using the background loop
def init_session():
    """Initialize the admin session in the background loop."""
    async def _init():
        await session_service.create_session(
            app_name=app_name,
            user_id=USER_ID,
            session_id=SESSION_ID
        )
    asyncio.run_coroutine_threadsafe(_init(), background_loop).result()

init_session()

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

def _get_camera_preview_frame(camera_index: int) -> Optional[bytes]:
    """Capture a preview frame from a camera.
    
    Args:
        camera_index: The index of the camera
        
    Returns:
        JPEG image bytes, or None if capture failed
    """
    cap = None
    try:
        if platform.system() == 'Darwin':  # macOS
            cap = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
        else:
            cap = cv2.VideoCapture(camera_index)
        
        if not cap.isOpened():
            return None
        
        # Set a short timeout
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        # Read a few frames to let camera stabilize
        for _ in range(3):
            ret, frame = cap.read()
            if not ret:
                continue
        
        # Get the final frame
        ret, frame = cap.read()
        if not ret or frame is None:
            return None
        
        # Encode as JPEG
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buffer.tobytes()
    except Exception:
        return None
    finally:
        if cap is not None:
            cap.release()

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get all input devices."""
    try:
        devices_list = io_manager.list_all_streams()
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
        return jsonify({'devices': by_category})
    except Exception as e:
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
        if latest_frame is not None:
            # Encode frame from ingestor
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
            return Response(
                response=b'',
                status=500,
                mimetype='image/jpeg'
            )
        
        # Capture preview frame
        frame_data = _get_camera_preview_frame(camera_index)
        if frame_data is None:
            # Return 500 to trigger img.onerror handler
            return Response(
                response=b'',
                status=500,
                mimetype='image/jpeg'
            )
        
        return Response(
            response=frame_data,
            mimetype='image/jpeg',
            headers={'Cache-Control': 'no-cache, no-store, must-revalidate'}
        )
    except Exception as e:
        # Return 500 to trigger img.onerror handler
        return Response(
            response=b'',
            status=500,
            mimetype='image/jpeg'
        )

@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages."""
    data = request.json
    user_message = data.get('message', '').strip()
    
    if not user_message:
        return jsonify({'error': 'Message cannot be empty'}), 400
    
    try:
        # Run the agent and get response using the background event loop
        content = types.Content(role='user', parts=[types.Part(text=user_message)])
        
        final_response_text = "No response received"
        async def get_response():
            nonlocal final_response_text
            # Use async generator properly with try/finally to ensure cleanup
            gen = runner.run_async(
                user_id=USER_ID,
                session_id=SESSION_ID,
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
