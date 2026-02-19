"""Video stream ingestor for managing video input streams - Approach 4: Event-Driven with Message Queue."""

import asyncio
import logging
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Any, List
from asyncio import Queue as AsyncQueue
from collections import deque
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService
from google.genai import types as genai_types
import cv2
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict
from dotenv import load_dotenv

from ..task_types import NoteEntry, Task
from ..model_providers import BaseModelProvider, get_VLM_provider

# Load environment variables
load_dotenv()

# Set up logger for this module
logger = logging.getLogger('VideoStreamIngestor')

# Pydantic models for structured output
class TaskUpdate(BaseModel):
    """Model for task update output."""
    model_config = ConfigDict(extra="forbid")
    task_number: int = Field(..., description="The task number")
    task_note: str = Field(..., description="Updated description/note for the task")
    task_done: bool = Field(..., description="Whether the task is completed")


class SystemAction(BaseModel):
    """Model for system action output."""
    model_config = ConfigDict(extra="forbid")
    take_action: str = Field(..., description="Description of the action to take")


class VideoIngestorOutput(BaseModel):
    """Model for the complete output structure."""
    model_config = ConfigDict(extra="forbid")
    task_updates: List[TaskUpdate] = Field(default_factory=list, description="List of task updates")
    system_actions: List[SystemAction] = Field(default_factory=list, description="List of system actions to take")

class VideoStreamIngestor:
    """Manages tasks for a video input stream using event-driven architecture."""
    
    def __init__(self, camera_source, action_runner: Runner, model_provider: BaseModelProvider, session_service: Optional[BaseSessionService] = None, app_name: str = "videomemory_app", target_resolution: Optional[tuple[int, int]] = (640, 480), on_task_updated=None):
        """Initialize the video stream ingestor.
        
        Args:
            camera_source: Either an int (local OpenCV camera index) or a str
                          (network stream URL, e.g. rtsp://... or http://...).
            action_runner: The runner for executing actions (see google adk: https://google.github.io/adk-docs/runtime/#key-components-of-the-runtime)
            session_service: The session service used by the runner (required to create sessions)
            app_name: The app name used by the runner (must match the runner's app_name)
            target_resolution: Target resolution (width, height) to resize frames to for VLM processing.
                              Default is (640, 480) for lower bandwidth and faster processing.
            model_provider: Model provider instance for ML inference.
            on_task_updated: Optional callback(task, new_note) called when a task is modified by the ingestor.
        """
        self.camera_source = camera_source
        self.is_network_stream = isinstance(camera_source, str)
        # Keep camera_index for backward compat in logging/session naming
        self.camera_index = camera_source
        self._tasks_list: List[Task] = []  # List of Task objects (shared by reference with task_manager)
        self._action_queue = AsyncQueue()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._camera: Optional[Any] = None  # Will hold cv2.VideoCapture when started
        self._latest_frame: Optional[Any] = None  # Store latest frame for debugging
        self._target_resolution = target_resolution # Default to 640x480
        
        # History tracking: past 20 model outputs (each dict includes the frame that produced it)
        self._output_history: deque = deque(maxlen=20)  # Store last 20 model outputs
        self._total_output_count: int = 0  # Track total number of outputs processed (for debugging)
        
        # Frame deduplication: skip VLM calls when the frame hasn't changed
        self._last_processed_frame: Optional[Any] = None  # Last frame sent to VLM
        self._frame_diff_threshold: float = 3.0  # Mean absolute pixel difference threshold (0-255 scale)
        self._frames_skipped: int = 0  # Counter for debugging
        
        # # Rate limiting: track last request time (max 10 requests per minute = 6 seconds between requests)
        # self._last_request_time: float = 0.0
        # self._min_request_interval: float = 0.1  # 600 requests per minute max
        
        # Store model provider (already initialized in __init__)
        self._model_provider = model_provider
        if hasattr(self._model_provider, '_client') and self._model_provider._client is None:
            logger.warning(f"Model provider {type(self._model_provider).__name__} failed to initialize. Multimodal LLM calls will fail.")
        
        # Initialize action router runner for executing actions
        # Use provided action runner or create a new one
        self._action_runner = action_runner
        self._session_service = session_service
        self._action_user_id = f"video_ingestor_{self.camera_index}" # google adk each session requires a user ID but this is just a session foringesting a stream
        self._action_app_name = app_name  # Must match the runner's app_name
        self.session_id = f"video_ingestor_session_{self.camera_index}"
        
        # Callback for persisting task changes (set by TaskManager)
        self._on_task_updated = on_task_updated
        
        logger.info(f"Initialized for camera index={self.camera_index}")
 
    async def start(self):
        """Start the video stream ingestor and all processing loops."""
        logger.debug(f"[DEBUG] VideoStreamIngestor.start: Called for camera_index={self.camera_index}")
        
        if self._running:
            logger.info(f"Already running for camera index={self.camera_index}")
            return
        
        # Create session for action runner if session_service is available
        if self._session_service:
            logger.debug(f"[DEBUG] VideoStreamIngestor.start: About to create session {self.session_id}")
            try:
                await self._session_service.create_session(
                    app_name=self._action_app_name,
                    user_id=self._action_user_id,
                    session_id=self.session_id
                )
                logger.info(f"Created session {self.session_id} for camera index={self.camera_index}")
            except Exception as e:
                # Check if it's a network error
                import httpx
                if isinstance(e, (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
                    logger.error(f"[ERROR] VideoStreamIngestor.start: Network error creating session {self.session_id}: {type(e).__name__}: {e}", exc_info=True)
                else:
                    # Session might already exist, which is fine
                    logger.debug(f"Session creation for {self.session_id}: {e}")
        else:
            logger.warning(f"No session_service provided. Session {self.session_id} may not exist.")
        
        self._running = True
        logger.info(f"Starting ingestor for camera index={self.camera_index}")
        
        # Start all processing loops
        # Note: These tasks run concurrently in the background
        self._tasks = [
            asyncio.create_task(self._process_input(), name=f"process_input_{self.camera_index}"),
            asyncio.create_task(self._action_loop(), name=f"action_{self.camera_index}"),
        ]
        
        logger.info(f"Started {len(self._tasks)} processing loops for camera index={self.camera_index}")
        logger.info(f"Task status: {[t.get_name() for t in self._tasks]}")
        
        # Give tasks a moment to start and report any immediate errors
        await asyncio.sleep(0.1)
    
    def _open_camera(self) -> bool:
        """Open the camera (local or network). Returns True on success."""
        if self.is_network_stream:
            self._camera = cv2.VideoCapture(self.camera_source)
        else:
            import platform
            if platform.system() == 'Darwin':
                self._camera = cv2.VideoCapture(self.camera_source, cv2.CAP_AVFOUNDATION)
            elif platform.system() == 'Linux':
                self._camera = cv2.VideoCapture(self.camera_source, cv2.CAP_V4L2)
            else:
                self._camera = cv2.VideoCapture(self.camera_source)
        return self._camera.isOpened()

    async def _process_input(self):
        """Unified loop that captures frames and processes them through ML pipeline."""
        try:
            opened = await asyncio.to_thread(self._open_camera)
            
            if not opened:
                if self.is_network_stream:
                    error_msg = (
                        f"ERROR: Could not open network stream: {self.camera_source}\n"
                        f"  Check that the URL is correct and the camera is online.\n"
                        f"  Common issues: wrong IP, wrong port, camera offline, auth required."
                    )
                    note_content = f"Could not connect to network camera at {self.camera_source}. Check URL and that camera is online."
                else:
                    error_msg = (
                        f"ERROR: Could not open camera {self.camera_source} for camera index={self.camera_index}\n"
                        f"  This is likely a macOS camera permission issue.\n"
                        f"  To fix:\n"
                        f"  1. Go to System Settings > Privacy & Security > Camera\n"
                        f"  2. Enable camera access for Terminal (or Python/your IDE)\n"
                        f"  3. Restart the application\n"
                        f"  Alternatively, the camera may be in use by another application."
                    )
                    note_content = "Camera access denied. Please grant camera permissions in System Settings."
                logger.error(error_msg)
                for task in self._tasks_list:
                    error_note = NoteEntry(content=note_content)
                    task.task_note.append(error_note)
                return
            
            # Log which camera we're actually using
            if self.is_network_stream:
                logger.info(f"Connected to network stream: {self.camera_source}")
            else:
                try:
                    from cv2_enumerate_cameras import enumerate_cameras
                    enum_cams = list(enumerate_cameras(cv2.CAP_AVFOUNDATION))
                    for c in enum_cams:
                        if c.index == self.camera_source:
                            logger.info(f"Opening camera index={self.camera_source}: {c.name} (unique ID: {c.path})")
                            break
                except Exception:
                    logger.info(f"Opening camera index={self.camera_source} (could not verify device name)")
            
            logger.info(f"Started process input loop for camera source={self.camera_source}")
            
            # Warm up camera by reading a few frames (especially important for USB cameras)
            for _ in range(5):
                ret, _ = await asyncio.to_thread(self._camera.read)
                if ret:
                    break
                await asyncio.sleep(0.1)
            
            consecutive_failures = 0
            max_consecutive_failures = 30 if self.is_network_stream else 10
            
            while self._running:
                try:
                    # Capture frame from camera
                    ret, current_frame = await asyncio.to_thread(self._camera.read)
                    if not ret:
                        consecutive_failures += 1
                        if self.is_network_stream and consecutive_failures >= max_consecutive_failures:
                            logger.warning(f"Network stream {self.camera_source}: {consecutive_failures} consecutive failures, attempting reconnect...")
                            if self._camera:
                                self._camera.release()
                            await asyncio.sleep(2.0)
                            reopened = await asyncio.to_thread(self._open_camera)
                            if reopened:
                                logger.info(f"Reconnected to network stream: {self.camera_source}")
                                consecutive_failures = 0
                            else:
                                logger.error(f"Failed to reconnect to {self.camera_source}, will retry...")
                            continue
                        logger.debug(f"Failed to read frame from camera source={self.camera_source}")
                        await asyncio.sleep(0.1)
                        continue
                    
                    consecutive_failures = 0
                    
                    # Validate frame
                    if current_frame is None or current_frame.size == 0:
                        logger.debug(f"Invalid frame from camera source={self.camera_source}")
                        continue
                    
                    # Resize frame to target resolution if needed
                    if current_frame.shape[1] != self._target_resolution[0] or current_frame.shape[0] != self._target_resolution[1]:
                        current_frame = cv2.resize(current_frame, self._target_resolution, interpolation=cv2.INTER_LINEAR)
                    
                    # Always update latest frame for preview (show whatever we get, even if black)
                    if current_frame.size > 0:
                        self._latest_frame = current_frame.copy()
                    
                    # Log frame info periodically for debugging (every 100 frames)
                    if self._total_output_count % 100 == 0:
                        frame_mean = current_frame.mean()
                        logger.debug(
                            f"Camera index={self.camera_index}: frame shape={current_frame.shape}, "
                            f"mean={frame_mean:.2f}, min={current_frame.min()}, max={current_frame.max()}"
                        )
                    
                    # Skip VLM call if the frame is effectively identical to the last one we processed
                    if self._is_frame_duplicate(current_frame):
                        self._frames_skipped += 1
                        if self._frames_skipped % 50 == 1:
                            logger.debug(
                                f"Camera index={self.camera_index}: skipping duplicate frame "
                                f"(total skipped: {self._frames_skipped})"
                            )
                        await asyncio.sleep(0.1)
                        continue
                    
                    # Build prompt before inference so we can store it with the output
                    prompt = self._build_prompt()
                    
                    # Run ML processing with multimodal LLM
                    results = await self._run_ml_inference(current_frame, prompt)
                    
                    # Remember this frame as the last one we sent to the VLM
                    self._last_processed_frame = current_frame.copy()
                    
                    # Store output in history with its corresponding frame and prompt
                    if results:
                        # Add frame and prompt to the output dict
                        results["frame"] = current_frame.copy()
                        results["prompt"] = prompt
                        self._output_history.append(results)
                        self._total_output_count += 1
                        
                        # Process results: update task notes and queue actions
                        await self._process_ml_results(results)
                            
                except Exception as e:
                    logger.error(f"Error processing frame for camera index={self.camera_index}: {e}", exc_info=True)
                    continue
            
            # Cleanup camera
            if self._camera:
                self._camera.release()
                self._camera = None
            logger.info(f"Stopped process input loop for camera index={self.camera_index}")
                    
        except asyncio.CancelledError:
            logger.info(f"Process input loop cancelled for camera index={self.camera_index}")
            if self._camera:
                self._camera.release()
                self._camera = None
        except Exception as e:
            logger.error(f"Error in process input loop for camera index={self.camera_index}: {e}", exc_info=True)
            self._running = False
            if self._camera:
                self._camera.release()
                self._camera = None
    
    async def _action_loop(self):
        """Execute actions based on task conditions."""
        try:
            logger.info(f"Started action loop for camera index={self.camera_index}")
            
            while self._running:
                try:
                    # Use timeout to allow checking _running flag periodically
                    action = await asyncio.wait_for(
                        self._action_queue.get(),
                        timeout=0.5
                    )
                    logger.debug(f"Action loop: Action {action} got from action loop queue for camera index={self.camera_index}")
                    if action is not None:
                        await self._execute_action(action)
                    
                except asyncio.TimeoutError:
                    # Timeout allows us to check _running flag
                    continue
                except Exception as e:
                    logger.error(f"Error executing action for camera index={self.camera_index}: {e}", exc_info=True)
                    continue
                    
        except asyncio.CancelledError:
            logger.info(f"Action loop cancelled for camera index={self.camera_index}")
        except Exception as e:
            logger.error(f"Error in action loop for camera index={self.camera_index}: {e}", exc_info=True)
    
    def _is_frame_duplicate(self, frame: Any) -> bool:
        """Check if a frame is effectively identical to the last processed frame.
        
        Uses mean absolute pixel difference — very fast (single numpy op).
        Returns True if the frame should be skipped.
        """
        import numpy as np
        if self._last_processed_frame is None:
            return False
        if frame.shape != self._last_processed_frame.shape:
            return False
        diff = np.abs(frame.astype(np.int16) - self._last_processed_frame.astype(np.int16)).mean()
        return diff < self._frame_diff_threshold
    
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
            tasks_lines.append(f"<task_number>{task.task_number}</task_number>")
            tasks_lines.append(f"<task_desc>{task.task_desc}</task_desc>")
            
            # most recent note
            if task.task_note:
                newest_note = task.task_note[-1]
            else:
                newest_note = NoteEntry(content="None", timestamp=time.time())
            tasks_lines.append(f"<task_newest_note timestamp=\"{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest_note.timestamp))}\">{newest_note.content}</task_newest_note>")
            
            # # Build note history section
            # # Only include the last 3 task notes to prevent prompt from growing too large
            # # Full history is still maintained in task.task_note for system use
            # notes_list = task.task_note
            # recent_notes = list(notes_list)[-3:] if notes_list else []  # Get last 3 notes
            
            # tasks_lines.append("<task_notes_history>")
            # if recent_notes:
            #     for note_entry in recent_notes:
            #         assert isinstance(note_entry, NoteEntry), "Note entry must be a NoteEntry object"
            #         time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(note_entry.timestamp))
            #         tasks_lines.append(f"<note timestamp=\"{time_str}\">{note_entry.content}</note>")
            # else:
            #     tasks_lines.append("<note timestamp=\"N/A\">No notes yet</note>")
            # tasks_lines.append("</task_notes_history>")
            
            tasks_lines.append("</task>")
        tasks_lines.append("</tasks>")
        
        # # Build most recent notes section for easy comparison
        # most_recent_lines = ["<most_recent_notes>"]
        # for task in self._tasks_list:
        #     notes_list = task.task_note
        #     if notes_list:
        #         newest_note = notes_list[-1]
        #         assert isinstance(newest_note, NoteEntry), "Note entry must be a NoteEntry object"
        #         time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest_note.timestamp))
        #         most_recent_lines.append(f"<task_{task.task_number}_newest_note timestamp=\"{time_str}\">{newest_note.content}</task_{task.task_number}_newest_note>")
        #     else:
        #         most_recent_lines.append(f"<task_{task.task_number}_newest_note>No notes yet</task_{task.task_number}_newest_note>")
        # most_recent_lines.append("</most_recent_notes>")
        
        # # Build history section (only model outputs, excluding frames and prompts)
        # # Only include the last 4 historical actions for the model prompt
        # history_lines = ["<history>"]
        # recent_history = list(self._output_history)[-4:]  # Get last 4 items
        # for output in recent_history:
        #     # Create a copy without the frame and prompt for the prompt
        #     output_for_prompt = {k: v for k, v in output.items() if k not in ("frame", "prompt")}
        #     history_lines.append("<output>")
        #     history_lines.append(f"<output_json>{json.dumps(output_for_prompt, default=str)}</output_json>")
        #     history_lines.append("</output>")
        # history_lines.append("</history>")
        
        # # Log prompt size for debugging (warn if getting very large)
        # prompt_so_far = "\n".join(tasks_lines) + "\n\n" + "\n".join(history_lines)
        # prompt_so_far = "\n".join(tasks_lines) + "\n\n" + "\n".join(most_recent_lines)
        prompt_so_far = "\n".join(tasks_lines)
        prompt_size_chars = len(prompt_so_far)
        if prompt_size_chars > 10000:  # Warn if prompt exceeds 10k characters
            logger.warning(f"Prompt is getting large: {prompt_size_chars} characters (camera={self.camera_index})")
        
        # Build instructions
        instructions = """<instructions>

You are a video ingestor. Output two JSON lists: task_updates and system_actions.

TASK_UPDATES: Add a task update IF AND ONLY IF there is something NEW or DIFFERENT in the imagefrom the most recent note for the task. Check the <task_newest_note> section - if the image matches the newest note for a task exactly, do NOT include that task in your updates (return empty list [] for no updates).

CRITICAL: Any change in count, quantity, or state MUST be reported, including:
- Changes from a non-zero count to zero
- Changes from zero to a non-zero count
- Any numerical change in counts or quantities
- Changes in status, positions, or states

Include updates for:
- New observations related to the task
- Changes in status, counts, positions, or states (including transitions to/from zero)
- Progress that advances task tracking

SYSTEM_ACTIONS: Only include if a task requires an action and conditions are met.

Output format (JSON only, nothing else):
[{task_number: <number>, task_note: <description>, task_done: <true/false>}, ...], [{take_action: <description>}, ...]

Examples:
When you observe a clap for "Count claps" task: [{task_number: 0, task_note: "Clap detected. Total count: 1 clap.", task_done: false}], []

When you observe 4 more claps (building on previous count): [{task_number: 0, task_note: "4 more claps detected. Total count: 5 claps.", task_done: false}], []

When you observe people for "Keep track of number of people": [{task_number: 1, task_note: "Currently 2 people visible in frame.", task_done: false}], []

When only 1 person is visible: [{task_number: 1, task_note: "1 person is visible in frame.", task_done: false}], []

When the person leaves the frame: [{task_number: 1, task_note: "Person left frame. Now 0 people visible.", task_done: false}], []

When tracking counts and the count changes to zero (e.g., most recent note says "1 item" but image shows 0): [{task_number: 0, task_note: "No items visible. Count is now 0.", task_done: false}], []

When tracking counts and the count changes from zero to non-zero (e.g., most recent note says "0 items" but image shows 2): [{task_number: 0, task_note: "2 items are now visible.", task_done: false}], []

When there is no new information and the task notes perfectly match the image (or same as newest note): [], []

For multiple task updates: [{task_number: 0, task_note: "Clap count: 5", task_done: false}, {task_number: 1, task_note: "2 people visible", task_done: false}], []

When task is complete: [{task_number: 0, task_note: "Task completed - 10 claps counted", task_done: true}], [{take_action: "send notification that clap counting task is complete"}]
</instructions>"""
        
        # return "\n".join(tasks_lines) + "\n\n" + "\n".join(history_lines) + "\n\n" + instructions
        # return "\n".join(tasks_lines) + "\n\n" + "\n".join(most_recent_lines) + "\n\n" + instructions
        return "\n".join(tasks_lines) + "\n\n" + instructions
    
    async def _run_ml_inference(self, frame: Any, prompt: str) -> Optional[Dict[str, Any]]:
        """Run multimodal LLM inference on a frame with the given prompt."""
        if not self._model_provider or not self._tasks_list:
            return None
        
        try:
            image_base64 = self._frame_to_base64(frame)
            if not image_base64:
                return None
            
            # Wrap synchronous API call in asyncio.to_thread to prevent blocking
            # This avoids connection pool issues when multiple frames are processed concurrently
            
            def _sync_generate_content():
                """Synchronous wrapper for generate_content to run in thread pool."""
                return self._model_provider._sync_generate_content(
                    image_base64=image_base64,
                    prompt=prompt,
                    response_model=VideoIngestorOutput
                )
            
            # Time the API call
            api_call_start = time.time()
            # Run the blocking call in a thread pool to avoid blocking the event loop
            response: VideoIngestorOutput = await asyncio.to_thread(_sync_generate_content)
            api_call_time = time.time() - api_call_start
            logger.debug(f"API call [camera={self.camera_index}]: generate_content took {api_call_time:.3f}s")

            # Providers return a validated Pydantic model instance.
            # logger.info(f"LLM inference prompt: {self._build_prompt()}")
            # logger.info(f"LLM inference output: {output}")
            return response.model_dump()
        except Exception as e:
            # Handle network errors gracefully - these can happen due to connection issues
            # but shouldn't crash the entire processing loop
            import httpx
            if isinstance(e, (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
                logger.warning(f"LLM inference network error (will skip this frame): {type(e).__name__}: {e}")
            else:
                logger.error(f"LLM inference error: {e}", exc_info=True)
            return None
    
    async def _process_ml_results(self, ml_results: Dict[str, Any]):
        """Process ML inference results: update task notes and queue actions."""
        if not ml_results:
            return
        
        # Update tasks - append new notes instead of overwriting
        for update in ml_results.get("task_updates", []):
            task = next((t for t in self._tasks_list if t.task_number == update.get("task_number")), None)
            if task:
                new_note_content = update.get("task_note", "")
                new_note = None
                
                # Append new note entry with current timestamp
                if new_note_content:  # Only append if there's actual content
                    new_note = NoteEntry(content=new_note_content)
                    task.task_note.append(new_note)
                
                # Update done status
                if update.get("task_done"):
                    task.done = True
                
                # Persist changes via callback
                if self._on_task_updated and (new_note or update.get("task_done")):
                    try:
                        self._on_task_updated(task, new_note)
                    except Exception as e:
                        logger.error(f"Failed to persist task update: {e}")
        
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
    
    def add_task(self, task: Task):
        """Add a task to the video stream ingestor.
        
        Args:
            task: Task object (shared by reference with task_manager)
        """
        logger.debug(f"[DEBUG] VideoStreamIngestor.add_task: Called for task '{task.task_desc}', camera_index={self.camera_index}")
        
        # Set task number if not already set
        task.task_number = len(self._tasks_list)
        
        self._tasks_list.append(task)
        
        logger.info(f"Added task {task.task_number} '{task.task_desc}' for camera index={self.camera_index}")
        
        # Start the ingestor if not already running
        if not self._running:
            logger.debug(f"[DEBUG] VideoStreamIngestor.add_task: Ingestor not running, scheduling start()")

            async def start_with_error_handling():
                try:
                    await self.start()
                except Exception as e:
                    logger.error(f"[ERROR] VideoStreamIngestor.start_with_error_handling: Error in start(): {e}", exc_info=True)

            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(start_with_error_handling())
            except RuntimeError:
                # Not inside an async context — use the Flask background loop if available
                bg_loop = getattr(sys.modules[__name__], '_flask_background_loop', None)
                if bg_loop and bg_loop.is_running():
                    asyncio.run_coroutine_threadsafe(start_with_error_handling(), bg_loop)
                    logger.debug(f"[DEBUG] VideoStreamIngestor.add_task: Scheduled start() on Flask background loop")
                else:
                    logger.warning(f"No event loop available. Call start() manually.")
        else:
            logger.debug(f"[DEBUG] VideoStreamIngestor.add_task: Ingestor already running, skipping start()")
    
    def remove_task(self, task_desc: str):
        """Remove a task from the video stream ingestor.
        
        Args:
            task_desc: Description of the task to be removed
        """
        # Find and remove task from tasks list
        task_found = False
        for task in self._tasks_list:
            if task.task_desc == task_desc:
                self._tasks_list.remove(task)
                task_found = True
                break
        
        if task_found:
            # Renumber remaining tasks
            for i, task in enumerate(self._tasks_list):
                task.task_number = i
            logger.info(f"Removed task '{task_desc}' for camera index={self.camera_index}")
        else:
            logger.warning(f"Task '{task_desc}' not found for camera index={self.camera_index}")
        
        # Stop ingestor if no tasks remain (async call)
        if len(self._tasks_list) == 0:
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(self.stop())
            except RuntimeError:
                bg_loop = getattr(sys.modules[__name__], '_flask_background_loop', None)
                if bg_loop and bg_loop.is_running():
                    asyncio.run_coroutine_threadsafe(self.stop(), bg_loop)
                else:
                    logger.warning(f"Could not stop ingestor - no event loop")
    
    def edit_task(self, old_task_desc: str, new_task_desc: str):
        """Edit/update a task description in the video stream ingestor.
        
        This preserves the task notes list while updating the description.
        
        Args:
            old_task_desc: The current description of the task to be edited
            new_task_desc: The new description for the task
        """
        # Find task in tasks list
        task = None
        for t in self._tasks_list:
            if t.task_desc == old_task_desc:
                task = t
                break
        
        if task is None:
            logger.warning(f"Task '{old_task_desc}' not found for camera index={self.camera_index}, cannot edit")
            return False
        
        # Update task description (notes are already in the task object, so they're preserved)
        task.task_desc = new_task_desc
        
        logger.info(f"Edited task from '{old_task_desc}' to '{new_task_desc}' for camera index={self.camera_index}")
        return True
    
    async def stop(self):
        """Clean shutdown of all loops and tasks."""
        if not self._running:
            logger.info(f"Already stopped for camera index={self.camera_index}")
            return
        
        logger.info(f"Stopping ingestor for camera index={self.camera_index}")
        
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
                logger.warning(f"Tasks didn't complete within timeout for camera index={self.camera_index}")
        
        # 4. Drain queues (prevents memory leaks)
        # Drain action queue
        remaining_actions = []
        while not self._action_queue.empty():
            try:
                action = self._action_queue.get_nowait()
                remaining_actions.append(action)
            except asyncio.QueueEmpty:
                break
        
        if remaining_actions:
            logger.info(f"Discarding {len(remaining_actions)} queued actions for camera index={self.camera_index}")
        
        # 5. Clear task list
        self._tasks = []
        
        # 6. Release camera if still open
        if self._camera:
            self._camera.release()
            self._camera = None
        
        logger.info(f"Stopped ingestor for camera index={self.camera_index}")
    
    
    def get_tasks_list(self) -> List[Task]:
        """Get the current tasks list as Task objects."""
        return self._tasks_list
    
    def get_output_history(self) -> List[Dict]:
        """Get the output history (each dict includes frame and prompt from the same LLM call)."""
        return list(self._output_history)
    
    def get_latest_output(self) -> Optional[Dict]:
        """Get the latest LLM output (includes frame and prompt from the same LLM call)."""
        return self._output_history[-1] if self._output_history else None
    
    def get_total_output_count(self) -> int:
        """Get the total number of outputs processed (for debugging)."""
        return self._total_output_count
    
    def get_latest_frame(self) -> Optional[Any]:
        """Get the latest captured frame.
        
        Returns:
            Latest frame as numpy array, or None if no frame available
        """
        return self._latest_frame.copy() if self._latest_frame is not None else None



# --- code the test the video ingestor standalone by calling just this script ---

def print_current_tasks(ingestor: VideoStreamIngestor):
    """Print the current state of all tasks."""
    tasks = ingestor.get_tasks_list()
    if tasks:
        print("=" * 60)
        print("CURRENT TASKS:")
        print("=" * 60)
        for task in tasks:
            status = "✓ DONE" if task.done else "⏳ ACTIVE"
            print(f"  [{task.task_number}] {status} - {task.task_desc}")
            
            # Print note history
            notes_history = task.task_note
            if notes_history:
                print(f"      Note History ({len(notes_history)} entries):")
                for note_entry in notes_history:
                    assert isinstance(note_entry, NoteEntry), "Note entry must be a NoteEntry object"
                    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(note_entry.timestamp))
                    content = note_entry.content
                    print(f"        [{time_str}] {content}")
        print("=" * 60)
    else:
        print("No tasks currently active.")

async def main():
    """Main function to run the video stream ingestor."""
    model_provider = get_VLM_provider()
    ingestor = VideoStreamIngestor(
        camera_index=0,
        action_runner=None,
        model_provider=model_provider,
        session_service=None,
        app_name="videomemory_app"
    )
    
    task = Task(
        task_number=-1,
        task_desc="keep track of the order of the number of fingers being held up",
        task_note=[],
        done=False
    )
    ingestor.add_task(task)
    print("Task added: keep track of the order of the number of fingers being held up")
    
    await ingestor.start()
    print("Video stream ingestor started.\n")
    
    try:
        last_output_count = 0
        cycle_count = 0
        while True:
            cycle_count += 1
            print("\n" + "-" * 60)
            print(f"CYCLE #{cycle_count}")
            print("-" * 60)
            
            # Print current tasks periodically
            print_current_tasks(ingestor)
            
            # Check for new outputs
            current_history = ingestor.get_output_history()
            if len(current_history) > last_output_count:
                output = current_history[-1]
                print(f"\n[New Response #{len(current_history)}]")
                
                for update in output.get("task_updates", []):
                    print(f"  Task {update.get('task_number')}: {update.get('task_note')}")
                
                for action in output.get("system_actions", []):
                    print(f"  Action: {action.get('take_action')}")
                
                last_output_count = len(current_history)
            
            await asyncio.sleep(2.0)  # Check every 2 seconds
            
    except KeyboardInterrupt:
        print("\nStopping video stream ingestor...")
        await ingestor.stop()
        print("Stopped.")


if __name__ == "__main__":
    from system.logging_config import setup_logging
    setup_logging()
    asyncio.run(main())