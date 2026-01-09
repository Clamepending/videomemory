"""Debug UI for Video Stream Ingestor - displays current frame, history, and model output."""

import asyncio
import base64
import json
import logging
import threading
import time
from pathlib import Path
from flask import Flask, jsonify, render_template_string, request
import cv2
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from system.stream_ingestors.video_stream_ingestor import VideoStreamIngestor
from system.task_types import Task
from system.logging_config import setup_logging

# Set up logging
setup_logging()
logger = logging.getLogger('DebugUI')

app = Flask(__name__)

# Global ingestor instance
ingestor: VideoStreamIngestor = None
ingestor_thread: threading.Thread = None
ingestor_loop: asyncio.AbstractEventLoop = None

# HTML template for the debug UI
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Video Stream Ingestor Debug UI</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 20px;
        }
        .panel {
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .full-width {
            grid-column: 1 / -1;
        }
        .panel h2 {
            margin-top: 0;
            color: #4CAF50;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 10px;
        }
        #currentFrame {
            max-width: 100%;
            border: 2px solid #ddd;
            border-radius: 4px;
            display: block;
            margin: 10px 0;
        }
        .output-item {
            background: #f9f9f9;
            border-left: 4px solid #4CAF50;
            padding: 10px;
            margin: 10px 0;
            border-radius: 4px;
        }
        .output-item h3 {
            margin: 0 0 10px 0;
            color: #666;
            font-size: 14px;
        }
        .task-update {
            background: #e3f2fd;
            padding: 8px;
            margin: 5px 0;
            border-radius: 4px;
        }
        .system-action {
            background: #fff3e0;
            padding: 8px;
            margin: 5px 0;
            border-radius: 4px;
        }
        .history-item {
            background: #f5f5f5;
            border-left: 3px solid #999;
            padding: 10px;
            margin: 5px 0;
            border-radius: 4px;
            font-size: 12px;
        }
        .status {
            position: fixed;
            top: 20px;
            right: 20px;
            background: #4CAF50;
            color: white;
            padding: 10px 20px;
            border-radius: 20px;
            font-weight: bold;
        }
        .timestamp {
            color: #999;
            font-size: 11px;
            margin-top: 5px;
        }
        pre {
            background: #f5f5f5;
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
            font-size: 11px;
        }
        .no-data {
            color: #999;
            font-style: italic;
        }
        .remove-btn {
            background-color: #f44336;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            margin-left: 10px;
            margin-top: 5px;
        }
        .remove-btn:hover {
            background-color: #d32f2f;
        }
        .remove-btn:active {
            background-color: #b71c1c;
        }
        .task-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }
        .task-header-content {
            flex: 1;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Video Stream Ingestor Debug UI</h1>
        <div class="status" id="status">Running</div>
        
        <div class="grid">
            <div class="panel full-width">
                <h2>Current Frame & Prompt</h2>
                <img id="currentFrame" alt="Current frame" />
                <div class="timestamp" id="frameTimestamp"></div>
            </div>
            
            <div class="panel">
                <h2>Latest Notes for Each Task</h2>
                <div id="latestTaskNotes">
                    <div class="no-data">Waiting for task notes...</div>
                </div>
            </div>
            
            <div class="panel">
                <h2>Output History (Last 20)</h2>
                <div id="history">
                    <div class="no-data">No history yet...</div>
                </div>
            </div>
            
            <div class="panel full-width">
                <h2>Current Prompt</h2>
                <pre id="prompt"></pre>
            </div>
        </div>
    </div>
    
    <script>
        function updateFrameAndPrompt() {
            fetch('/api/frame-and-prompt')
                .then(response => response.json())
                .then(data => {
                    const img = document.getElementById('currentFrame');
                    const timestamp = document.getElementById('frameTimestamp');
                    const promptContainer = document.getElementById('prompt');
                    
                    if (data && data.frame_base64) {
                        img.src = 'data:image/jpeg;base64,' + data.frame_base64;
                        timestamp.textContent = 'Last updated: ' + new Date().toLocaleTimeString();
                    } else {
                        img.src = '';
                        timestamp.textContent = data.error || 'No frame available';
                    }
                    
                    if (data && data.prompt) {
                        promptContainer.textContent = data.prompt;
                    } else {
                        promptContainer.textContent = 'No prompt available yet...';
                    }
                })
                .catch(error => {
                    console.error('Error fetching frame and prompt:', error);
                    const img = document.getElementById('currentFrame');
                    const promptContainer = document.getElementById('prompt');
                    img.src = '';
                    promptContainer.textContent = 'Error loading data...';
                });
        }
        
        function removeTask(taskDesc) {
            if (!confirm('Are you sure you want to remove this task?')) {
                return;
            }
            
            console.log('Removing task:', taskDesc);
            
            fetch('/api/remove-task', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ task_desc: taskDesc })
            })
            .then(response => {
                console.log('Response status:', response.status);
                return response.json();
            })
            .then(data => {
                console.log('Response data:', data);
                if (data.status === 'success') {
                    // Refresh the task list
                    updateLatestTaskNotes();
                } else {
                    alert('Error removing task: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(error => {
                console.error('Error removing task:', error);
                alert('Error removing task: ' + error.message);
            });
        }
        
        // Use event delegation for remove buttons (works with dynamically created buttons)
        document.addEventListener('click', function(e) {
            if (e.target && e.target.classList.contains('remove-btn')) {
                const taskDesc = e.target.getAttribute('data-task-desc');
                if (taskDesc) {
                    removeTask(taskDesc);
                }
            }
        });
        
        function updateLatestTaskNotes() {
            fetch('/api/latest-task-notes')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('latestTaskNotes');
                    if (data && data.tasks && data.tasks.length > 0) {
                        let html = '';
                        data.tasks.forEach((task, index) => {
                            // Escape HTML for display
                            const taskDescEscaped = task.task_desc
                                .replace(/&/g, '&amp;')
                                .replace(/</g, '&lt;')
                                .replace(/>/g, '&gt;')
                                .replace(/"/g, '&quot;')
                                .replace(/'/g, '&#39;');
                            // Escape for HTML attribute (quotes need special handling)
                            const taskDescAttr = task.task_desc
                                .replace(/&/g, '&amp;')
                                .replace(/"/g, '&quot;')
                                .replace(/'/g, '&#39;');
                            
                            html += '<div class="task-update">';
                            html += '<div class="task-header">';
                            html += '<div class="task-header-content">';
                            html += '<strong>Task ' + task.task_number + ':</strong> ' + taskDescEscaped;
                            html += ' <span style="color: #999;">(Done: ' + task.done + ')</span><br>';
                            
                            if (task.latest_note) {
                                const noteContentEscaped = task.latest_note.content
                                    .replace(/&/g, '&amp;')
                                    .replace(/</g, '&lt;')
                                    .replace(/>/g, '&gt;');
                                html += '<div style="margin-top: 5px; padding-left: 10px; border-left: 2px solid #4CAF50;">';
                                html += '<strong>Latest Note:</strong> ' + noteContentEscaped;
                                html += ' <span class="timestamp">(' + task.latest_note.timestamp + ')</span>';
                                html += '</div>';
                            } else {
                                html += '<div style="margin-top: 5px; padding-left: 10px; color: #999; font-style: italic;">';
                                html += 'No notes yet';
                                html += '</div>';
                            }
                            
                            html += '</div>';
                            // Use data attribute instead of onclick for better reliability
                            html += '<button class="remove-btn" data-task-desc="' + taskDescAttr + '">Remove</button>';
                            html += '</div>';
                            html += '</div>';
                        });
                        container.innerHTML = html;
                    } else {
                        container.innerHTML = '<div class="no-data">No tasks available yet...</div>';
                    }
                })
                .catch(error => {
                    console.error('Error fetching latest task notes:', error);
                });
        }
        
        function updateHistory() {
            fetch('/api/history')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('history');
                    if (data && data.history && data.history.length > 0) {
                        let html = '';
                        const totalCount = data.total_count || data.history.length;
                        // Show in reverse order (newest first)
                        for (let i = data.history.length - 1; i >= 0; i--) {
                            const output = data.history[i];
                            // Calculate the actual output number (accounting for the sliding window)
                            const outputNumber = totalCount - (data.history.length - 1 - i);
                            html += '<div class="history-item">';
                            html += '<strong>Output #' + outputNumber + '</strong><br>';
                            
                            if (output.task_updates && output.task_updates.length > 0) {
                                output.task_updates.forEach(update => {
                                    html += 'Task ' + update.task_number + ': ' + update.task_note + '<br>';
                                });
                            }
                            
                            if (output.system_actions && output.system_actions.length > 0) {
                                output.system_actions.forEach(action => {
                                    html += 'Action: ' + action.take_action + '<br>';
                                });
                            }
                            
                            if ((!output.task_updates || output.task_updates.length === 0) && 
                                (!output.system_actions || output.system_actions.length === 0)) {
                                html += '<span class="no-data">No updates</span>';
                            }
                            
                            html += '</div>';
                        }
                        container.innerHTML = html;
                    } else {
                        container.innerHTML = '<div class="no-data">No history yet...</div>';
                    }
                })
                .catch(error => {
                    console.error('Error fetching history:', error);
                });
        }
        
        function updateAll() {
            updateFrameAndPrompt();
            updateLatestTaskNotes();
            updateHistory();
        }
        
        // Update every 500ms for smooth updates
        setInterval(updateAll, 500);
        
        // Initial load
        updateAll();
    </script>
</body>
</html>
"""


def frame_to_base64(frame):
    """Convert OpenCV frame to base64 encoded image."""
    if frame is None:
        return None
    try:
        _, buffer = cv2.imencode('.jpg', frame)
        return base64.b64encode(buffer).decode('utf-8')
    except Exception as e:
        logger.error(f"Error encoding frame: {e}")
        return None


@app.route('/')
def index():
    """Serve the main debug UI page."""
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/frame-and-prompt')
def get_frame_and_prompt():
    """Get the frame and prompt that were used together for the latest model output."""
    global ingestor
    if ingestor is None:
        return jsonify({"error": "Ingestor not initialized"}), 500
    
    # Get the latest output (includes the frame and prompt from the same LLM call)
    latest_output = ingestor.get_latest_output()
    if not latest_output:
        return jsonify({"error": "No output available yet", "frame_base64": None, "prompt": ""}), 200
    
    latest_frame = latest_output.get("frame")
    latest_prompt = latest_output.get("prompt", "")
    
    if latest_frame is None:
        return jsonify({"error": "No frame available", "frame_base64": None, "prompt": latest_prompt or ""}), 200
    
    # Convert frame to base64
    image_base64 = frame_to_base64(latest_frame)
    if image_base64 is None:
        return jsonify({"error": "Failed to encode frame", "frame_base64": None, "prompt": latest_prompt or ""}), 500
    
    return jsonify({
        "frame_base64": image_base64,
        "prompt": latest_prompt or ""
    })


@app.route('/api/latest-output')
def get_latest_output():
    """Get the latest model output (excluding the frame for JSON serialization)."""
    global ingestor
    if ingestor is None:
        return jsonify({"error": "Ingestor not initialized"}), 500
    
    history = ingestor.get_output_history()
    if not history:
        return jsonify({"output": None, "index": 0, "total_count": ingestor.get_total_output_count()})
    
    latest = history[-1]
    # Remove frame and prompt from output for JSON response (frames can't be serialized, prompt is large)
    output_without_metadata = {k: v for k, v in latest.items() if k not in ("frame", "prompt")}
    total_count = ingestor.get_total_output_count()
    return jsonify({
        "output": output_without_metadata,
        "index": len(history),
        "total_count": total_count
    })


@app.route('/api/latest-task-notes')
def get_latest_task_notes():
    """Get the latest note for each task."""
    global ingestor
    if ingestor is None:
        return jsonify({"error": "Ingestor not initialized"}), 500
    
    tasks = ingestor.get_tasks_list()
    if not tasks:
        return jsonify({"tasks": []})
    
    tasks_data = []
    for task in tasks:
        task_dict = {
            "task_number": task.task_number,
            "task_desc": task.task_desc,
            "done": task.done,
            "latest_note": None
        }
        
        # Get the latest note if available
        if task.task_note and len(task.task_note) > 0:
            latest_note_entry = task.task_note[-1]
            # Convert NoteEntry to dict for JSON serialization
            if hasattr(latest_note_entry, 'to_dict'):
                task_dict["latest_note"] = latest_note_entry.to_dict()
            else:
                # Fallback if it's already a dict
                task_dict["latest_note"] = latest_note_entry
        
        tasks_data.append(task_dict)
    
    return jsonify({"tasks": tasks_data})


@app.route('/api/remove-task', methods=['POST'])
def remove_task():
    """Remove a task from the ingestor."""
    global ingestor
    if ingestor is None:
        return jsonify({"status": "error", "message": "Ingestor not initialized"}), 500
    
    data = request.get_json()
    if not data or 'task_desc' not in data:
        return jsonify({"status": "error", "message": "task_desc is required"}), 400
    
    task_desc = data['task_desc']
    
    try:
        # Check if task exists before removing
        tasks = ingestor.get_tasks_list()
        task_exists = any(task.task_desc == task_desc for task in tasks)
        
        if not task_exists:
            return jsonify({"status": "error", "message": f"Task '{task_desc}' not found"}), 404
        
        # Remove the task
        ingestor.remove_task(task_desc)
        
        return jsonify({
            "status": "success",
            "message": f"Task '{task_desc}' removed successfully"
        })
    except Exception as e:
        logger.error(f"Error removing task: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to remove task: {str(e)}"}), 500


@app.route('/api/history')
def get_history():
    """Get the full output history (excluding frames for JSON serialization)."""
    global ingestor
    if ingestor is None:
        return jsonify({"error": "Ingestor not initialized"}), 500
    
    history = ingestor.get_output_history()
    # Remove frames and prompts from history for JSON response
    history_without_metadata = [{k: v for k, v in item.items() if k not in ("frame", "prompt")} for item in history]
    total_count = ingestor.get_total_output_count()
    return jsonify({
        "history": history_without_metadata,
        "count": len(history),
        "total_count": total_count
    })




def run_ingestor_async():
    """Run the video stream ingestor in an async event loop."""
    global ingestor, ingestor_loop
    
    # Create new event loop for this thread
    ingestor_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(ingestor_loop)
    
    async def setup_and_run():
        """Setup and run the ingestor."""
        global ingestor
        
        # Initialize ingestor (same as in main() function)
        ingestor = VideoStreamIngestor(
            camera_index=0,
            action_runner=None,
            session_service=None,
            app_name="videomemory_app"
        )
        
        # Add a test task (same as in main() function)
        task = Task(
            task_number=-1,
            task_desc="keep track of the order of the number of fingers being held up",
            task_note=[],
            done=False
        )
        ingestor.add_task(task)
        logger.info("Task added: count the number of fingers being held up")
        
        task = Task(
            task_number=-1,
            task_desc="keep track of the orientation of phones",
            task_note=[],
            done=False
        )
        ingestor.add_task(task)
        logger.info("Task added: keep track of the orientation of phones")
        
        # Start the ingestor
        await ingestor.start()
        logger.info("Video stream ingestor started in debug UI")
        
        # Keep running until stopped
        try:
            while True:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info("Ingestor loop cancelled")
        finally:
            if ingestor:
                await ingestor.stop()
                logger.info("Video stream ingestor stopped")
    
    try:
        ingestor_loop.run_until_complete(setup_and_run())
    except Exception as e:
        logger.error(f"Error in ingestor async loop: {e}", exc_info=True)
    finally:
        ingestor_loop.close()


def start_ingestor_thread():
    """Start the ingestor in a separate thread."""
    global ingestor_thread
    ingestor_thread = threading.Thread(target=run_ingestor_async, daemon=True)
    ingestor_thread.start()
    logger.info("Started ingestor thread")


def main():
    """Main function to start the debug UI server."""
    logger.info("Starting Video Stream Ingestor Debug UI...")
    
    # Start the ingestor in a background thread
    start_ingestor_thread()
    
    # Give the ingestor a moment to initialize
    time.sleep(2)
    
    # Start Flask server (using port 5001 to avoid conflict with AirPlay on macOS)
    port = 5001
    logger.info(f"Starting Flask server on http://localhost:{port}")
    logger.info(f"Open your browser to http://localhost:{port} to view the debug UI")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

