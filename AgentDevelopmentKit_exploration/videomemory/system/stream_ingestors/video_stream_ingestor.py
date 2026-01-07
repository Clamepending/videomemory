"""Video stream ingestor for managing video input streams - Approach 4: Event-Driven with Message Queue."""

import asyncio
import logging
import base64
import json
import os
import time
from typing import Dict, Optional, Any, List
from asyncio import Queue as AsyncQueue
from collections import deque
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService
from google.genai import types as genai_types
import cv2
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logger for this module
logger = logging.getLogger('VideoStreamIngestor')


# Pydantic models for structured output
class TaskUpdate(BaseModel):
    """Model for task update output."""
    task_number: int = Field(..., description="The task number")
    task_note: str = Field(..., description="Updated description/note for the task")
    task_done: bool = Field(..., description="Whether the task is completed")


class SystemAction(BaseModel):
    """Model for system action output."""
    take_action: str = Field(..., description="Description of the action to take")


class VideoIngestorOutput(BaseModel):
    """Model for the complete output structure."""
    task_updates: List[TaskUpdate] = Field(default_factory=list, description="List of task updates")
    system_actions: List[SystemAction] = Field(default_factory=list, description="List of system actions to take")

class VideoStreamIngestor:
    """Manages tasks for a video input stream using event-driven architecture."""
    
    def __init__(self, io_id: str, action_runner: Runner, session_service: Optional[BaseSessionService] = None, app_name: str = "videomemory_app"):
        """Initialize the video stream ingestor.
        
        Args:
            io_id: The unique identifier of the IO stream
            action_runner: The runner for executing actions (see google adk: https://google.github.io/adk-docs/runtime/#key-components-of-the-runtime)
            session_service: The session service used by the runner (required to create sessions)
            app_name: The app name used by the runner (must match the runner's app_name)
        """
        self.io_id = io_id
        self._task_notes: Dict[str, dict] = {}  # task_desc -> task_notes dict
        self._tasks_list: List[Dict] = []  # List of tasks with task_number, task_desc, task_note
        self._frame_queue = AsyncQueue(maxsize=10)
        self._action_queue = AsyncQueue()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._camera: Optional[Any] = None  # Will hold cv2.VideoCapture when started
        
        # History tracking: past 20 model outputs
        self._output_history: deque = deque(maxlen=20)  # Store last 20 model outputs
        
        # Rate limiting: track last request time (max 10 requests per minute = 6 seconds between requests)
        self._last_request_time: float = 0.0
        self._min_request_interval: float = 1.0  # 6 seconds = 10 requests per minute max
        
        # Initialize Google GenAI client
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GOOGLE_API_KEY not found in environment. Multimodal LLM calls will fail.")
            self._genai_client = None
        else:
            try:
                self._genai_client = genai.Client(api_key=api_key)
                logger.info(f"Initialized Google GenAI client for io_id={self.io_id}")
            except Exception as e:
                logger.error(f"Failed to initialize Google GenAI client: {e}")
                self._genai_client = None
        
        # Initialize action router runner for executing actions
        # Use provided action runner or create a new one
        self._action_runner = action_runner
        self._session_service = session_service
        self._action_user_id = f"video_ingestor_{io_id}" # google adk each session requires a user ID but this is just a session foringesting a stream
        self._action_app_name = app_name  # Must match the runner's app_name
        self.session_id = f"video_ingestor_session_{io_id}"
        
        logger.info(f"Initialized for io_id={self.io_id}")
    
    async def start(self):
        """Start the video stream ingestor and all processing loops."""
        if self._running:
            logger.info(f"Already running for io_id={self.io_id}")
            return
        
        # Create session for action runner if session_service is available
        if self._session_service:
            try:
                await self._session_service.create_session(
                    app_name=self._action_app_name,
                    user_id=self._action_user_id,
                    session_id=self.session_id
                )
                logger.info(f"Created session {self.session_id} for io_id={self.io_id}")
            except Exception as e:
                # Session might already exist, which is fine
                logger.debug(f"Session creation for {self.session_id}: {e}")
        else:
            logger.warning(f"No session_service provided. Session {self.session_id} may not exist.")
        
        self._running = True
        logger.info(f"Starting ingestor for io_id={self.io_id}")
        
        # Start all processing loops
        # Note: These tasks run concurrently in the background
        self._tasks = [
            asyncio.create_task(self._capture_loop(), name=f"capture_{self.io_id}"),
            asyncio.create_task(self._process_loop(), name=f"process_{self.io_id}"),
            asyncio.create_task(self._action_loop(), name=f"action_{self.io_id}"),
        ]
        
        logger.info(f"Started {len(self._tasks)} processing loops for io_id={self.io_id}")
        logger.info(f"Task status: {[t.get_name() for t in self._tasks]}")
        
        # Give tasks a moment to start and report any immediate errors
        await asyncio.sleep(0.1)
    
    async def _capture_loop(self):
        """Continuously capture frames from the video stream."""
        try:
            # Get camera index from io_id (simplified - in real implementation, map io_id to camera)
            camera_index = 0  # Default camera
            
            # On macOS, try AVFoundation backend first (better permission handling)
            import platform
            if platform.system() == 'Darwin':  # macOS
                self._camera = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
            else:
                self._camera = cv2.VideoCapture(camera_index)
            
            # Check if camera opened successfully (for all platforms)
            if not self._camera.isOpened():
                error_msg = (
                    f"ERROR: Could not open camera {camera_index} for io_id={self.io_id}\n"
                    f"  This is likely a macOS camera permission issue.\n"
                    f"  To fix:\n"
                    f"  1. Go to System Settings > Privacy & Security > Camera\n"
                    f"  2. Enable camera access for Terminal (or Python/your IDE)\n"
                    f"  3. Restart the application\n"
                    f"  Alternatively, the camera may be in use by another application."
                )
                logger.error(error_msg)
                # Update task notes to indicate camera failure
                for task_desc, task_notes in self._task_notes.items():
                    task_notes["error"] = "Camera access denied. Please grant camera permissions in System Settings."
                return
            
            logger.info(f"Started capture loop for io_id={self.io_id}")
            
            while self._running:
                ret, frame = self._camera.read()
                if ret:
                    # Put frame in queue (non-blocking, will drop if queue full)
                    try:
                        self._frame_queue.put_nowait(frame)
                    except asyncio.QueueFull:
                        # Drop oldest frame if queue is full
                        try:
                            self._frame_queue.get_nowait()
                            self._frame_queue.put_nowait(frame)
                        except asyncio.QueueEmpty:
                            pass
                    
                await asyncio.sleep(0.1)  # 10fps
            
            self._camera.release()
            self._camera = None
            logger.info(f"Stopped capture loop for io_id={self.io_id}")
        except asyncio.CancelledError:
            logger.info(f"Capture loop cancelled for io_id={self.io_id}")
            if self._camera:
                self._camera.release()
                self._camera = None
        except Exception as e:
            logger.error(f"Error in capture loop for io_id={self.io_id}: {e}", exc_info=True)
            self._running = False
    
    async def _process_loop(self):
        """Process frames through ML pipeline and update task notes."""
        try:
            logger.info(f"Started process loop for io_id={self.io_id}")
            
            while self._running:
                try:
                    # Use timeout to allow checking _running flag periodically
                    frame = await asyncio.wait_for(
                        self._frame_queue.get(),
                        timeout=0.5
                    )
                    if frame is None:
                        continue
                    logger.debug(f"Process loop: Frame got from process loop queue for io_id={self.io_id}")
                    
                    # Run ML processing with multimodal LLM
                    results = await self._run_ml_inference(frame)
                    
                    # Store output in history
                    if results:
                        self._output_history.append(results)
                    
                    # Process results: update task notes and queue actions
                    if results:
                        await self._process_ml_results(results)
                            
                except asyncio.TimeoutError:
                    # Timeout allows us to check _running flag
                    continue
                except Exception as e:
                    logger.error(f"Error processing frame for io_id={self.io_id}: {e}", exc_info=True)
                    continue
                    
        except asyncio.CancelledError:
            logger.info(f"Process loop cancelled for io_id={self.io_id}")
        except Exception as e:
            logger.error(f"Error in process loop for io_id={self.io_id}: {e}", exc_info=True)
            self._running = False
    
    async def _action_loop(self):
        """Execute actions based on task conditions."""
        try:
            logger.info(f"Started action loop for io_id={self.io_id}")
            
            while self._running:
                try:
                    # Use timeout to allow checking _running flag periodically
                    action = await asyncio.wait_for(
                        self._action_queue.get(),
                        timeout=0.5
                    )
                    logger.debug(f"Action loop: Action {action} got from action loop queue for io_id={self.io_id}")
                    if action is not None:
                        await self._execute_action(action)
                    
                except asyncio.TimeoutError:
                    # Timeout allows us to check _running flag
                    continue
                except Exception as e:
                    logger.error(f"Error executing action for io_id={self.io_id}: {e}", exc_info=True)
                    continue
                    
        except asyncio.CancelledError:
            logger.info(f"Action loop cancelled for io_id={self.io_id}")
        except Exception as e:
            logger.error(f"Error in action loop for io_id={self.io_id}: {e}", exc_info=True)
    
    def _frame_to_base64(self, frame: Any) -> str:
        """Convert OpenCV frame to base64 encoded image."""
        try:
            _, buffer = cv2.imencode('.jpg', frame)
            return base64.b64encode(buffer).decode('utf-8')
        except Exception as e:
            logger.error(f"Error encoding frame: {e}")
            return ""
    
    def _build_prompt(self) -> str:
        """Build the prompt for the LLM based on tasks and history."""
        # Build tasks section
        tasks_lines = ["<tasks>"]
        for task in self._tasks_list:
            tasks_lines.append("<task>")
            tasks_lines.append(f"<task_number>{task.get('task_number', 0)}</task_number>")
            tasks_lines.append(f"<task_desc>{task.get("task_desc", "")}</task_desc>")
            tasks_lines.append(f"<task_note>{task.get("task_note", "")}</task_note>")
            tasks_lines.append("</task>")
        tasks_lines.append("</tasks>")
        
        # Build history section (only model outputs)
        history_lines = ["<history>"]
        for output in self._output_history:
            history_lines.append("<output>")
            history_lines.append(f"<output_json>{json.dumps(output, default=str)}</output_json>")
            history_lines.append("</output>")
        history_lines.append("</history>")
        
        # Build instructions
        instructions = """<instructions>

You are the video ingestor. Your job is to output two lists of json objects.

The first list is to update task notes when you observe something relevant to a task in the current image. IMPORTANT: If you can provide a meaningful update to a task note based on what you see in the image, you MUST include it. This includes:
- New observations related to the task
- Changes in status or progress
- Updates to counts, positions, or states
- Any relevant information that advances tracking of the task

Use the history of your own outputs to prevent double counting or repeating the same observations. Only update tasks when there's something new or relevant to report. If nothing has changed and there's nothing new to observe, you can return an empty task_updates list.

The second list is for system actions - only include actions if a task explicitly requires taking an action and the conditions are met in the video stream.

Write your output in this format and ONLY this format. Do not write anything but in exactly this format and nothing else.
[{task_number: <task number>, task_note: <new_description>, task_done: <True or False>}, ...], [{take_action: action_description}, ...]

examples:
When you observe a clap for "Count claps" task: [{task_number: 0, task_note: "Clap detected. Total count: 1 clap.", task_done: False}], []

When you observe 4 more claps: [{task_number: 0, task_note: "4 more claps detected. Total count: 5 claps.", task_done: False}], []

When you observe people for "Keep track of number of people": [{task_number: 1, task_note: "Currently 2 people visible in frame.", task_done: False}], []

When the person is not visible: [{task_number: 1, task_note: "1 person was visible, but now no one is visible.", task_done: False}], []

When nothing relevant is observed: [], []

For multiple task updates: [{task_number: 0, task_note: "Clap count: 5", task_done: False}, {task_number: 1, task_note: "2 people visible", task_done: False}], []

When task is complete: [{task_number: 0, task_note: "Task completed - 10 claps counted", task_done: True}], [{take_action: "send notification that clap counting task is complete"}]
</instructions>"""
        
        return "\n".join(tasks_lines) + "\n\n" + "\n".join(history_lines) + "\n\n" + instructions
    
    async def _run_ml_inference(self, frame: Any) -> Optional[Dict[str, Any]]:
        """Run multimodal LLM inference on a frame."""
        if not self._genai_client or not self._tasks_list:
            return None
        
        # Rate limiting: ensure minimum interval between requests
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - time_since_last)
        
        try:
            image_base64 = self._frame_to_base64(frame)
            if not image_base64:
                return None
            
            image_part = types.Part(
                inline_data=types.Blob(
                    data=base64.b64decode(image_base64),
                    mime_type="image/jpeg"
                )
            )
            text_part = types.Part(text=self._build_prompt())
            
            logger.info(f"LLM inference prompt: {self._build_prompt()}")
            
            self._last_request_time = time.time()
            response = self._genai_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[image_part, text_part],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=VideoIngestorOutput.model_json_schema()
                )
            )
            
            output = VideoIngestorOutput(**json.loads(response.text))
            
            logger.info(f"LLM inference output: {output}")
            return {
                "task_updates": [u.model_dump() for u in output.task_updates],
                "system_actions": [a.model_dump() for a in output.system_actions]
            }
        except Exception as e:
            logger.error(f"LLM inference error: {e}", exc_info=True)
            return None
    
    async def _process_ml_results(self, ml_results: Dict[str, Any]):
        """Process ML inference results: update task notes and queue actions."""
        if not ml_results:
            return
        
        # Update tasks
        for update in ml_results.get("task_updates", []):
            task = next((t for t in self._tasks_list if t.get("task_number") == update.get("task_number")), None)
            if task:
                task["task_note"] = update.get("task_note", "")
                task_desc = task.get("task_desc", "")
                if task_desc in self._task_notes:
                    self._task_notes[task_desc]["note"] = update.get("task_note", "")
                    if update.get("task_done"):
                        self._task_notes[task_desc]["done"] = True
        
        # Queue actions
        for action in ml_results.get("system_actions", []):
            if action.get("take_action"):
                await self._action_queue.put(action["take_action"])
    
    async def _execute_action(self, action: str):
        """
        Execute an action using the shared admin agent runner.
        
        Args:
            action: String describing the action to execute
        """
        if not self._action_runner:
            logger.error("Action runner not available. Cannot execute action.")
            return
        
        try:
            content = genai_types.Content(role='user', parts=[genai_types.Part(text=f"Execute this action: {action}")])
            
            async for event in self._action_runner.run_async(
                user_id=self._action_user_id,
                session_id=self.session_id,
                new_message=content
            ):
                if event.is_final_response():
                    if event.content and event.content.parts:
                        logger.info(f"Action result: {event.content.parts[0].text}")
                    break
        except Exception as e:
            logger.error(f"Error executing action: {e}", exc_info=True)
    
    def add_task(self, task_desc: str, task_notes: dict):
        """Add a task to the video stream ingestor.
        
        Args:
            task_desc: Description of the task to be performed
            task_notes: Dictionary to store notes and status for this task (shared reference)
        """
        self._task_notes[task_desc] = task_notes
        
        # Initialize task notes
        task_notes["note"] = "" # want to use a string for simplicity but dictionary is more flexible and is passed by reference
        
        # Add to tasks list with task_number
        # Use the length of tasks_list as the task_number (0-indexed)
        task_number = len(self._tasks_list)
        task_entry = {
            "task_number": task_number,
            "task_desc": task_desc,
            "task_note": task_notes.get("note", "")
        }
        self._tasks_list.append(task_entry)
        
        logger.info(f"Added task {task_number} '{task_desc}' for io_id={self.io_id}")
        
        # Start the ingestor if not already running
        if not self._running:
            # Schedule start in the event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.start())
                else:
                    loop.run_until_complete(self.start())
            except RuntimeError:
                # No event loop running, will need to be started manually
                logger.warning(f"No event loop available. Call start() manually.")
    
    def remove_task(self, task_desc: str):
        """Remove a task from the video stream ingestor.
        
        Args:
            task_desc: Description of the task to be removed
        """
        if task_desc in self._task_notes:
            del self._task_notes[task_desc]
            # Remove from tasks list
            self._tasks_list = [t for t in self._tasks_list if t.get("task_desc") != task_desc]
            # Renumber remaining tasks
            for i, task in enumerate(self._tasks_list):
                task["task_number"] = i
            logger.info(f"Removed task '{task_desc}' for io_id={self.io_id}")
        else:
            logger.warning(f"Task '{task_desc}' not found for io_id={self.io_id}")
        
        # Stop ingestor if no tasks remain (async call)
        if len(self._task_notes) == 0:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.stop())
                else:
                    loop.run_until_complete(self.stop())
            except RuntimeError:
                logger.warning(f"Could not stop ingestor - no event loop")
    
    def edit_task(self, old_task_desc: str, new_task_desc: str):
        """Edit/update a task description in the video stream ingestor.
        
        This preserves the task_notes dictionary while updating the description.
        
        Args:
            old_task_desc: The current description of the task to be edited
            new_task_desc: The new description for the task
        """
        if old_task_desc not in self._task_notes:
            logger.warning(f"Task '{old_task_desc}' not found for io_id={self.io_id}, cannot edit")
            return False
        
        # Get the existing task_notes
        task_notes = self._task_notes[old_task_desc]
        
        # Remove old task description
        del self._task_notes[old_task_desc]
        
        # Add new task description with same task_notes
        self._task_notes[new_task_desc] = task_notes
        
        # Update tasks list
        for task in self._tasks_list:
            if task.get("task_desc") == old_task_desc:
                task["task_desc"] = new_task_desc
                break
        
        logger.info(f"Edited task from '{old_task_desc}' to '{new_task_desc}' for io_id={self.io_id}")
        return True
    
    async def stop(self):
        """Clean shutdown of all loops and tasks."""
        if not self._running:
            logger.info(f"Already stopped for io_id={self.io_id}")
            return
        
        logger.info(f"Stopping ingestor for io_id={self.io_id}")
        
        # 1. Signal shutdown
        self._running = False
        
        # 2. Cancel all tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # 3. Wait for tasks to complete (with timeout)
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Tasks didn't complete within timeout for io_id={self.io_id}")
        
        # 4. Drain queues (prevents memory leaks)
        # Drain frame queue
        drained_frames = 0
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
                drained_frames += 1
            except asyncio.QueueEmpty:
                break
        
        if drained_frames > 0:
            logger.debug(f"Drained {drained_frames} frames from queue for io_id={self.io_id}")
        
        # Drain action queue
        remaining_actions = []
        while not self._action_queue.empty():
            try:
                action = self._action_queue.get_nowait()
                remaining_actions.append(action)
            except asyncio.QueueEmpty:
                break
        
        if remaining_actions:
            logger.info(f"Discarding {len(remaining_actions)} queued actions for io_id={self.io_id}")
        
        # 5. Clear task list
        self._tasks = []
        
        # 6. Release camera if still open
        if self._camera:
            self._camera.release()
            self._camera = None
        
        logger.info(f"Stopped ingestor for io_id={self.io_id}")
