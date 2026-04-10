"""Video stream ingestor for managing video input streams - Approach 4: Event-Driven with Message Queue."""

import asyncio
import logging
import base64
import json
import os
import platform
import re
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple
from collections import deque
import cv2
import httpx
import numpy as np
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict
from dotenv import load_dotenv

from ..task_types import NoteEntry, Task
from ..model_providers import BaseModelProvider, get_VLM_provider
from ..io_manager.url_utils import is_snapshot_url

# Load environment variables
load_dotenv()

# Set up logger for this module
logger = logging.getLogger('VideoStreamIngestor')

_flask_background_loop: Optional[asyncio.AbstractEventLoop] = None
_background_loop_thread: Optional[threading.Thread] = None
_background_loop_lock = threading.Lock()


def _run_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Run a persistent event loop in a daemon thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def get_background_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Return a running background loop, creating a fallback one if needed."""
    global _flask_background_loop, _background_loop_thread

    loop = _flask_background_loop
    if loop is not None and not loop.is_closed() and loop.is_running():
        return loop

    with _background_loop_lock:
        loop = _flask_background_loop
        if loop is not None and not loop.is_closed() and loop.is_running():
            return loop

        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=_run_background_loop,
            args=(loop,),
            daemon=True,
            name="VideoMemoryBackgroundLoop",
        )
        thread.start()

        deadline = time.monotonic() + 0.5
        while not loop.is_running() and time.monotonic() < deadline:
            time.sleep(0.01)

        if not loop.is_running():
            logger.error("Failed to start fallback background event loop")
            try:
                loop.close()
            except Exception:
                pass
            return None

        _flask_background_loop = loop
        _background_loop_thread = thread
        logger.info("Started fallback background event loop for VideoStreamIngestor")
        return loop

# Pydantic models for structured output
class TaskUpdate(BaseModel):
    """Model for task update output."""
    model_config = ConfigDict(extra="forbid")
    task_number: int = Field(..., description="The task number")
    task_note: str = Field(..., description="Updated description/note for the task")
    task_done: bool = Field(..., description="Whether the task is completed")


class VideoIngestorOutput(BaseModel):
    """Model for the complete output structure."""
    model_config = ConfigDict(extra="forbid")
    task_updates: List[TaskUpdate] = Field(default_factory=list, description="List of task updates")


VLM_INGESTOR_PROMPT_INSTRUCTIONS = """<instructions>

You are a video ingestor. Output one JSON object containing task_updates.

When task_newest_note is "None", you MUST ALWAYS output at least one task_update. Describe what you see in the image relevant to the task. NEVER return {"task_updates": []} when the newest note is "None".


CRITICAL: Any change in count, quantity, or state MUST be reported, including:
- Changes from a non-zero count to zero
- Changes from zero to a non-zero count
- Any numerical change in counts or quantities
- Changes in status, positions, or states

Include updates for:
- New observations related to the task
- Changes in status, counts, positions, or states (including transitions to/from zero)
- Progress that advances task tracking

Output format (JSON only, nothing else):
{"task_updates": [{task_number: <number>, task_note: <description>, task_done: <true/false>}, ...]}

Examples:
First observation (newest_note is None): {"task_updates": [{task_number: 0, task_note: "No people visible in frame.", task_done: false}]}

When you observe a clap for "Count claps" task: {"task_updates": [{task_number: 0, task_note: "Clap detected. Total count: 1 clap.", task_done: false}]}

When you observe 4 more claps (building on previous count): {"task_updates": [{task_number: 0, task_note: "4 more claps detected. Total count: 5 claps.", task_done: false}]}

When you observe people for "Keep track of number of people": {"task_updates": [{task_number: 1, task_note: "Currently 2 people visible in frame.", task_done: false}]}

When only 1 person is visible: {"task_updates": [{task_number: 1, task_note: "1 person is visible in frame.", task_done: false}]}

When the person leaves the frame: {"task_updates": [{task_number: 1, task_note: "Person left frame. Now 0 people visible.", task_done: false}]}

When tracking counts and the count changes to zero (e.g., most recent note says "1 item" but image shows 0): {"task_updates": [{task_number: 0, task_note: "No items visible. Count is now 0.", task_done: false}]}

When tracking counts and the count changes from zero to non-zero (e.g., most recent note says "0 items" but image shows 2): {"task_updates": [{task_number: 0, task_note: "2 items are now visible.", task_done: false}]}

When task_newest_note is "None" (first observation): {"task_updates": [{task_number: 0, task_note: "Initial observation: 1 person visible in frame.", task_done: false}]}

When there is no new information and the task notes perfectly match the image (and newest note is NOT "None"): {"task_updates": []}

For multiple task updates: {"task_updates": [{task_number: 0, task_note: "Clap count: 5", task_done: false}, {task_number: 1, task_note: "2 people visible", task_done: false}]}

When task is complete: {"task_updates": [{task_number: 0, task_note: "Task completed - 10 claps counted", task_done: true}]}
</instructions>"""


def build_video_ingestor_prompt(
    tasks: List[Task],
    *,
    context_label: Optional[Any] = None,
    include_done: bool = False,
) -> str:
    """Build the canonical VLM prompt for a set of tasks.

    Args:
        tasks: Task objects to include in the prompt.
        context_label: Optional label used in prompt-size warning logs.
        include_done: When true, include completed tasks as a fallback context.
    """
    selected_tasks = list(tasks) if include_done else [task for task in tasks if not task.done]
    if not selected_tasks:
        return ""

    tasks_lines = ["<tasks>"]
    for task in selected_tasks:
        tasks_lines.append("<task>")
        tasks_lines.append(f"<task_number>{task.task_number}</task_number>")
        tasks_lines.append(f"<task_desc>{task.task_desc}</task_desc>")

        newest_note = task.task_note[-1] if task.task_note else NoteEntry(content="None", timestamp=time.time())
        note_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest_note.timestamp))
        tasks_lines.append(
            f"<task_newest_note timestamp=\"{note_time}\">{newest_note.content}</task_newest_note>"
        )
        tasks_lines.append("</task>")
    tasks_lines.append("</tasks>")

    prompt_so_far = "\n".join(tasks_lines)
    prompt_size_chars = len(prompt_so_far)
    if prompt_size_chars > 10000:
        context_suffix = f" (camera={context_label})" if context_label is not None else ""
        logger.warning("Prompt is getting large: %s characters%s", prompt_size_chars, context_suffix)

    return prompt_so_far + "\n\n" + VLM_INGESTOR_PROMPT_INSTRUCTIONS

class VideoStreamIngestor:
    """Manages tasks for a video input stream using event-driven architecture."""

    DEFAULT_FRAME_DIFF_THRESHOLD = 3.0
    FRAME_DIFF_THRESHOLD_UNIT = "average_pixel_difference_0_to_255"
    
    def __init__(self, camera_source, model_provider: BaseModelProvider, target_resolution: Optional[tuple[int, int]] = (640, 480), on_task_updated=None, on_detection_event=None):
        """Initialize the video stream ingestor.
        
        Args:
            camera_source: Either an int (local OpenCV camera index) or a str
                          (network stream URL, e.g. rtsp://... or http://...).
            target_resolution: Target resolution (width, height) to resize frames to for VLM processing.
                              Default is (640, 480) for lower bandwidth and faster processing.
            model_provider: Model provider instance for ML inference.
            on_task_updated: Optional callback(task, new_note) called when a task is modified by the ingestor.
            on_detection_event: Optional callback(task, new_note) called for task_updates emitted by VLM inference.
        """
        self.camera_source = camera_source
        self.is_network_stream = isinstance(camera_source, str)
        self.is_snapshot_source = self.is_network_stream and is_snapshot_url(camera_source)
        # Keep camera_index for backward compat in logging/session naming
        self.camera_index = camera_source
        self._tasks_list: List[Task] = []  # List of Task objects (shared by reference with task_manager)
        self._running = False
        self._loop: Optional[asyncio.Task] = None
        self._camera: Optional[Any] = None  # Will hold cv2.VideoCapture when started
        self._snapshot_client: Optional[httpx.Client] = None
        self._latest_frame: Optional[Any] = None  # Store latest frame for debugging
        self._latest_frame_timestamp: Optional[float] = None
        self._target_resolution = target_resolution # Default to 640x480
        self._keep_alive_without_tasks = False
        
        # History tracking: past 20 model outputs (each dict includes the frame that produced it)
        self._output_history: deque = deque(maxlen=20)  # Store last 20 model outputs
        self._total_output_count: int = 0  # Track total number of outputs processed (for debugging)
        self._process_loop_ticks: int = 0
        self._latest_inference_error: Optional[Dict[str, Any]] = None
        
        # Frame deduplication: skip VLM calls when the average pixel difference stays below threshold
        self._last_processed_frame: Optional[Any] = None  # Last frame sent to VLM
        self._frame_diff_threshold: float = self.DEFAULT_FRAME_DIFF_THRESHOLD  # Mean absolute pixel difference threshold (0-255 scale)
        self._frames_skipped: int = 0  # Total frames skipped (lifetime)
        self._consecutive_skips: int = 0  # Frames skipped since last VLM call (for UI)
        
        # Frame capture failure tracking (for network stream reconnection)
        self._consecutive_capture_failures: int = 0
        self._max_capture_failures: int = 30 if isinstance(camera_source, str) else 10
        
        # Store model provider (already initialized in __init__)
        self._model_provider = model_provider
        if hasattr(self._model_provider, '_client') and self._model_provider._client is None:
            logger.warning(f"Model provider {type(self._model_provider).__name__} failed to initialize. Multimodal LLM calls will fail.")
        
        # Callback for persisting task changes (set by TaskManager)
        self._on_task_updated = on_task_updated
        self._on_detection_event = on_detection_event
        
        logger.info(f"Initialized for camera index={self.camera_index}")

    def _local_camera_error_message(self) -> str:
        """Return a platform-appropriate message for local camera open failures."""
        if platform.system() == "Darwin":
            return (
                f"ERROR: Could not open camera {self.camera_source} for camera index={self.camera_index}\n"
                f"  This is likely a macOS camera permission issue.\n"
                f"  To fix:\n"
                f"  1. Go to System Settings > Privacy & Security > Camera\n"
                f"  2. Enable camera access for Terminal (or Python/your IDE)\n"
                f"  3. Restart the application\n"
                f"  Alternatively, the camera may be in use by another application."
            )

        device_hint = (
            f"/dev/video{self.camera_source}"
            if isinstance(self.camera_source, int)
            else str(self.camera_source)
        )
        return (
            f"ERROR: Could not open local camera {self.camera_source} for camera index={self.camera_index}\n"
            f"  On {platform.system()}, this usually means the device is busy, disconnected, or not readable by the current user.\n"
            f"  Device hint: {device_hint}\n"
            f"  Check:\n"
            f"  1. The camera is still connected and listed in /dev/video*\n"
            f"  2. No other app is exclusively holding the device\n"
            f"  3. The current user can read the device"
        )

    def _local_camera_error_note(self) -> str:
        """Return a short task note for local camera open failures."""
        if platform.system() == "Darwin":
            return "Camera access denied. Please grant camera permissions in System Settings."
        return "Local camera could not be opened. It may be busy, disconnected, or temporarily unavailable."

    def set_model_provider(self, model_provider: BaseModelProvider) -> None:
        """Swap the model provider used for future inference calls."""
        self._model_provider = model_provider
        if hasattr(self._model_provider, '_client') and self._model_provider._client is None:
            logger.warning(
                "Model provider %s is not initialized after hot-reload; inference calls may fail.",
                type(self._model_provider).__name__,
            )

    def _build_inference_error_info(self, error: Exception) -> Dict[str, Any]:
        """Build a small debug payload describing the latest inference failure."""
        message = str(error).strip()
        lowered = message.lower()
        status_code = None
        retry_delay_seconds = None

        status_match = re.match(r"^\s*(\d{3})\b", message)
        if status_match:
            try:
                status_code = int(status_match.group(1))
            except ValueError:
                status_code = None

        retry_match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", lowered)
        if retry_match:
            try:
                retry_delay_seconds = float(retry_match.group(1))
            except ValueError:
                retry_delay_seconds = None

        user_message = f"Model call failed: {message}"
        if "resource_exhausted" in lowered or "quota exceeded" in lowered:
            user_message = "Model quota exceeded. VideoMemory is still running, but new VLM updates are paused until quota resets or you switch models."
            if retry_delay_seconds is not None:
                user_message += f" Retry in about {int(round(retry_delay_seconds))}s."
        elif status_code == 429:
            user_message = "Model rate limit hit. VideoMemory is still running, but new VLM updates are temporarily paused."
            if retry_delay_seconds is not None:
                user_message += f" Retry in about {int(round(retry_delay_seconds))}s."
        elif status_code and status_code >= 500:
            user_message = "The model provider returned a server error. VideoMemory will keep capturing frames and retry automatically."
        elif "connect" in lowered or "timeout" in lowered or "network" in lowered:
            user_message = "VideoMemory could not reach the model provider. It will keep capturing frames and retry automatically."

        return {
            "timestamp": time.time(),
            "message": message,
            "user_message": user_message,
            "status_code": status_code,
            "retry_delay_seconds": retry_delay_seconds,
            "error_type": type(error).__name__,
        }
 
    async def start(self):
        """Start the video stream ingestor and all processing loops."""
        logger.debug(f"[DEBUG] VideoStreamIngestor.start: Called for camera_index={self.camera_index}")
        
        if self._running:
            logger.info(f"Already running for camera index={self.camera_index}")
            return
        
        self._running = True
        logger.info(f"Starting ingestor for camera index={self.camera_index}")
        
        self._loop = asyncio.create_task(self._capture_loop(), name=f"capture_{self.camera_index}")
        
        logger.info(f"Started capture loop for camera index={self.camera_index}")
        
        # Give tasks a moment to start and report any immediate errors
        await asyncio.sleep(0.1)
    
    def _open_camera(self) -> bool:
        """Open the camera (local or network). Returns True on success."""
        self._release_camera()

        if self.is_snapshot_source:
            if self._snapshot_client is None:
                timeout = httpx.Timeout(
                    connect=float(os.environ.get("VIDEOMEMORY_SNAPSHOT_CONNECT_TIMEOUT_S", "5.0")),
                    read=float(os.environ.get("VIDEOMEMORY_SNAPSHOT_READ_TIMEOUT_S", "5.0")),
                    write=5.0,
                    pool=5.0,
                )
                self._snapshot_client = httpx.Client(timeout=timeout, follow_redirects=True)
            return True

        if self.is_network_stream:
            if not os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS"):
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|"
                    "max_delay;500000|reorder_queue_size;0"
                )
            self._camera = cv2.VideoCapture()
            if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
                self._camera.set(
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    float(os.environ.get("VIDEOMEMORY_STREAM_OPEN_TIMEOUT_MS", "5000")),
                )
            if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
                self._camera.set(
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    float(os.environ.get("VIDEOMEMORY_STREAM_READ_TIMEOUT_MS", "5000")),
                )
            if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
                self._camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if hasattr(cv2, "CAP_FFMPEG"):
                self._camera.open(self.camera_source, cv2.CAP_FFMPEG)
            else:
                self._camera.open(self.camera_source)
        else:
            if platform.system() == 'Darwin':
                self._camera = cv2.VideoCapture(self.camera_source, cv2.CAP_AVFOUNDATION)
            elif platform.system() == 'Linux':
                self._camera = cv2.VideoCapture(self.camera_source, cv2.CAP_V4L2)
            else:
                self._camera = cv2.VideoCapture(self.camera_source)
        opened = self._camera.isOpened()
        if not opened:
            self._release_camera()
        return opened

    def _release_camera(self):
        """Release current capture handle if open."""
        if self._camera:
            self._camera.release()
            self._camera = None
        if self._snapshot_client is not None:
            self._snapshot_client.close()
            self._snapshot_client = None

    def _append_note_to_tasks(self, content: str):
        """Append a note to all tracked tasks."""
        for task in self._tasks_list:
            task.task_note.append(NoteEntry(content=content))

    async def _ensure_camera_open(self) -> bool:
        """Open camera, with retry behavior for network streams."""
        opened = await asyncio.to_thread(self._open_camera)
        if opened:
            return True

        if self.is_network_stream:
            note_content = f"Could not connect to network camera at {self.camera_source}. Check URL and that camera is online."
            logger.warning(
                "Could not open network stream at startup: %s. Will keep retrying until it becomes available.",
                self.camera_source,
            )
            self._append_note_to_tasks(note_content)
            reconnect_interval = float(os.environ.get("VIDEOMEMORY_NETWORK_RETRY_SECONDS", "2.0"))
            while self._running and not opened:
                await asyncio.sleep(reconnect_interval)
                opened = await asyncio.to_thread(self._open_camera)
                if opened:
                    logger.info(f"Connected to network stream after retry: {self.camera_source}")
                    return True
            return False

        local_retry_count = max(0, int(os.environ.get("VIDEOMEMORY_LOCAL_CAMERA_OPEN_RETRY_COUNT", "10")))
        local_retry_interval = max(0.0, float(os.environ.get("VIDEOMEMORY_LOCAL_CAMERA_RETRY_SECONDS", "0.5")))

        for attempt in range(1, local_retry_count + 1):
            if not self._running:
                return False
            logger.warning(
                "Local camera open failed for camera index=%s; retrying (%s/%s) in %.2fs",
                self.camera_index,
                attempt,
                local_retry_count,
                local_retry_interval,
            )
            await asyncio.sleep(local_retry_interval)
            opened = await asyncio.to_thread(self._open_camera)
            if opened:
                logger.info(
                    "Opened local camera %s after retry %s/%s",
                    self.camera_index,
                    attempt,
                    local_retry_count,
                )
                return True

        logger.error(self._local_camera_error_message())
        self._append_note_to_tasks(self._local_camera_error_note())
        return False

    async def _reconnect_network_stream(self) -> bool:
        """Reconnect network stream after repeated read failures."""
        self._release_camera()
        await asyncio.sleep(2.0)
        reopened = await asyncio.to_thread(self._open_camera)
        if reopened:
            logger.info(f"Reconnected to network stream: {self.camera_source}")
        else:
            logger.error(f"Failed to reconnect to {self.camera_source}, will retry...")
        return reopened

    def _read_latest_frame(self) -> Tuple[bool, Optional[Any]]:
        """Read the freshest available frame from the current capture.

        For network streams, drain any buffered frames with non-blocking grab()
        and only decode the last one.
        """
        if self.is_snapshot_source:
            client = self._snapshot_client
            if client is None:
                return False, None
            response = client.get(
                str(self.camera_source),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                },
            )
            response.raise_for_status()
            array = np.frombuffer(response.content, dtype=np.uint8)
            frame = cv2.imdecode(array, cv2.IMREAD_COLOR)
            if frame is None or frame.size == 0:
                return False, None
            return True, frame

        if self._camera is None:
            return False, None

        if not self.is_network_stream:
            return self._camera.read()

        # Grab (skip) buffered frames, then decode only the last one.
        for _ in range(30):
            t0 = time.monotonic()
            self._camera.grab()
            if time.monotonic() - t0 > 0.005:
                break  # Blocked = caught up to live
        return self._camera.retrieve()

    def _frame_capture(self) -> Optional[Any]:
        """Capture, validate, and resize a single frame from the camera.

        Synchronous — reads directly from the cv2.VideoCapture handle.
        The capture loop calls this via asyncio.to_thread().

        Returns the processed frame (resized to target resolution), or None
        if no valid frame could be read.
        """
        ret, current_frame = self._read_latest_frame()
        if not ret:
            self._consecutive_capture_failures += 1
            return None

        self._consecutive_capture_failures = 0

        if current_frame is None or current_frame.size == 0:
            logger.debug(f"Invalid frame from camera source={self.camera_source}")
            return None

        if current_frame.shape[1] != self._target_resolution[0] or current_frame.shape[0] != self._target_resolution[1]:
            current_frame = cv2.resize(current_frame, self._target_resolution, interpolation=cv2.INTER_LINEAR)

        if current_frame.size > 0:
            self._latest_frame = current_frame.copy()
            self._latest_frame_timestamp = time.time()

        return current_frame

    def _VLM_processing(self, frame) -> Optional[Dict[str, Any]]:
        """Run VLM processing on a single frame: dedup, prompt, inference, result handling.

        Synchronous — calls the model provider's _sync_generate_content directly.
        Reusable from both the live capture loop (via asyncio.to_thread) and
        offline scripts (called directly).

        Args:
            frame: OpenCV frame (already resized to target resolution), or None.

        Returns:
            Results dict with task_updates, processing_time_ms, prompt, and frame
            if VLM was called and returned results. None if skipped (no frame,
            no tasks, duplicate frame, or inference error).
        """
        if frame is None or not self._tasks_list:
            return None

        self._process_loop_ticks += 1

        if self._process_loop_ticks % 100 == 0:
            frame_mean = frame.mean()
            logger.debug(
                f"Camera index={self.camera_index}: frame shape={frame.shape}, "
                f"mean={frame_mean:.2f}, min={frame.min()}, max={frame.max()}"
            )

        if self._is_frame_duplicate(frame):
            self._frames_skipped += 1
            self._consecutive_skips += 1
            if self._frames_skipped % 100 == 1:
                logger.info(
                    "Skipping duplicate frames [camera=%s]: %d total skipped (diff < %.1f). "
                    "If the scene is static, the model won't be called.",
                    self.camera_index,
                    self._frames_skipped,
                    self._frame_diff_threshold,
                )
            if self._output_history:
                output = {**self._output_history[-1], "skipped": True}
                self._output_history.append(output)
                return output
            logger.debug(
                "Skipping duplicate frame before any successful VLM output exists [camera=%s]",
                self.camera_index,
            )
            return None

        prompt = self._build_prompt()
        image_base64 = self._frame_to_base64(frame)
        if not image_base64:
            return None

        t0 = time.time()
        if self._total_output_count == 0:
            logger.info("First VLM inference attempt [camera=%s] (base_url from provider env)", self.camera_index)

        try:
            response: VideoIngestorOutput = self._model_provider._sync_generate_content(
                image_base64=image_base64,
                prompt=prompt,
                response_model=VideoIngestorOutput,
                usage_context={"source": "task_ingestor"},
            )
            results = response.model_dump()
            self._latest_inference_error = None
        except Exception as e:
            import httpx
            self._latest_inference_error = self._build_inference_error_info(e)
            if isinstance(e, (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
                logger.warning(
                    "LLM inference network error (will skip this frame) [camera=%s]: %s: %s.",
                    self.camera_index, type(e).__name__, e,
                )
            else:
                logger.error(f"LLM inference error [camera={self.camera_index}]: {e}", exc_info=True)
            results = None

        self._last_processed_frame = frame.copy()
        self._consecutive_skips = 0

        if results:
            results["processing_time_ms"] = round((time.time() - t0) * 1000)
            results["timestamp"] = time.time()
            results["frame"] = frame.copy()
            results["prompt"] = prompt
            self._output_history.append(results)
            self._total_output_count += 1
            self._process_ml_results(results)

        return results

    async def _capture_loop(self):
        """Capture frames and run VLM processing in a single loop.

        When no tasks are assigned the loop still grabs frames (keeping
        ``_latest_frame`` fresh for the UI) but skips the expensive VLM
        inference entirely.
        """
        try:
            if not await self._ensure_camera_open():
                return

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

            logger.info(f"Started capture loop for camera source={self.camera_source}")

            # Warm up local/OpenCV cameras by reading a few frames.
            # Snapshot sources do not keep an open cv2 capture handle.
            if self._camera is not None:
                for _ in range(5):
                    ret, _ = await asyncio.to_thread(self._camera.read)
                    if ret:
                        break
                    await asyncio.sleep(0.1)

            self._consecutive_capture_failures = 0

            while self._running:
                try:
                    frame = await asyncio.to_thread(self._frame_capture)
                    if frame is None:
                        if self.is_network_stream and self._consecutive_capture_failures >= self._max_capture_failures:
                            reopened = await self._reconnect_network_stream()
                            if reopened:
                                self._consecutive_capture_failures = 0
                        await asyncio.sleep(0.05)
                        continue
                    await asyncio.to_thread(self._VLM_processing, frame)
                except Exception as e:
                    logger.error(f"Error in capture/process loop for camera index={self.camera_index}: {e}", exc_info=True)
                    await asyncio.sleep(0.1)

            logger.info(f"Stopped capture loop for camera index={self.camera_index}")

        except asyncio.CancelledError:
            logger.info(f"Capture loop cancelled for camera index={self.camera_index}")
        except Exception as e:
            logger.error(f"Error in capture loop for camera index={self.camera_index}: {e}", exc_info=True)
            self._running = False
        finally:
            self._running = False
            current_task = asyncio.current_task()
            if self._loop is current_task:
                self._loop = None
            self._release_camera()
    
    def _is_frame_duplicate(self, frame: Any) -> bool:
        """Check if a frame is effectively identical to the last processed frame.
        
        Uses mean absolute pixel difference on the 0-255 pixel scale.
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
            frame_bytes = self._frame_to_jpeg_bytes(frame)
            if not frame_bytes:
                return ""
            return base64.b64encode(frame_bytes).decode('utf-8')
        except Exception as e:
            logger.error(f"Error encoding frame: {e}")
            return ""

    def _frame_to_jpeg_bytes(self, frame: Any, quality: int = 85) -> bytes:
        """Convert OpenCV frame to JPEG bytes."""
        if frame is None:
            return b""
        success, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not success:
            return b""
        return buffer.tobytes()
    
    def _build_prompt(self) -> str:
        """Build the prompt for the LLM based on tasks and history."""
        return build_video_ingestor_prompt(self._tasks_list, context_label=self.camera_index)

    def _schedule_stop_if_idle(self) -> None:
        if len(self._tasks_list) != 0:
            return
        if self._keep_alive_without_tasks:
            logger.info(
                "Keeping ingestor alive without tasks for camera index=%s",
                self.camera_index,
            )
            return
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self.stop())
        except RuntimeError:
            bg_loop = get_background_loop()
            if bg_loop and bg_loop.is_running():
                asyncio.run_coroutine_threadsafe(self.stop(), bg_loop)
            else:
                logger.warning("Could not stop ingestor - no event loop")

    def _prune_completed_tasks(self) -> None:
        active_tasks = [task for task in self._tasks_list if not task.done]
        removed = len(self._tasks_list) - len(active_tasks)
        if removed <= 0:
            return
        self._tasks_list = active_tasks
        for i, task in enumerate(self._tasks_list):
            task.task_number = i
        logger.info(
            "Pruned %s completed task(s) for camera index=%s",
            removed,
            self.camera_index,
        )
        self._schedule_stop_if_idle()
    
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
                    response_model=VideoIngestorOutput,
                    usage_context={"source": "task_ingestor"},
                )
            
            # Time the API call
            api_call_start = time.time()
            # Run the blocking call in a thread pool to avoid blocking the event loop
            response: VideoIngestorOutput = await asyncio.to_thread(_sync_generate_content)
            api_call_time = time.time() - api_call_start
            n_updates = len(response.task_updates)
            logger.debug(f"API call [camera={self.camera_index}]: generate_content took {api_call_time:.3f}s")
            if n_updates > 0:
                logger.info(
                    "LLM returned %d task_update(s) [camera=%s]: %s",
                    n_updates,
                    self.camera_index,
                    [(u.task_number, u.task_note[:50] + "..." if len(u.task_note) > 50 else u.task_note) for u in response.task_updates],
                )
            else:
                logger.debug(
                    "LLM returned empty task_updates [camera=%s] (model saw no change from newest notes)",
                    self.camera_index,
                )

            # Providers return a validated Pydantic model instance.
            return response.model_dump()
        except Exception as e:
            # Handle network errors gracefully - these can happen due to connection issues
            # but shouldn't crash the entire processing loop
            import httpx
            if isinstance(e, (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
                logger.warning(
                    "LLM inference network error (will skip this frame) [camera=%s]: %s: %s. "
                    "If using Docker, ensure VLM base URL is reachable (e.g. host IP, not localhost).",
                    self.camera_index,
                    type(e).__name__,
                    e,
                )
            else:
                logger.error(f"LLM inference error [camera={self.camera_index}]: {e}", exc_info=True)
            return None
    
    def _process_ml_results(self, ml_results: Dict[str, Any]):
        """Process ML inference results: update task notes and queue actions."""
        if not ml_results:
            return

        task_updates = ml_results.get("task_updates", [])
        note_frame_bytes = self._frame_to_jpeg_bytes(ml_results.get("frame"))
        available_task_numbers = [t.task_number for t in self._tasks_list]
        completed_task_seen = False

        # Update tasks - append new notes instead of overwriting
        for update in task_updates:
            raw_task_num = update.get("task_number")
            # Coerce to int (model may return string "0" instead of int 0)
            try:
                task_num = int(raw_task_num) if raw_task_num is not None else None
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid task_number from model: %r (type=%s). Available: %s",
                    raw_task_num,
                    type(raw_task_num).__name__,
                    available_task_numbers,
                )
                continue

            task = next((t for t in self._tasks_list if t.task_number == task_num), None)
            if not task:
                logger.warning(
                    "No task matched task_number=%s. Available task_numbers: %s [camera=%s]",
                    task_num,
                    available_task_numbers,
                    self.camera_index,
                )
                continue

            new_note_content = update.get("task_note", "")
            new_note = None

            # Append new note entry with current timestamp
            if new_note_content:  # Only append if there's actual content
                new_note = NoteEntry(content=new_note_content, frame_bytes=note_frame_bytes or None)
                task.task_note.append(new_note)

            # Update done status
            if update.get("task_done"):
                task.done = True
                completed_task_seen = True

            # Persist changes via callback
            if self._on_task_updated and (new_note or update.get("task_done")):
                try:
                    self._on_task_updated(task, new_note)
                except Exception as e:
                    logger.error(f"Failed to persist task update: {e}")
            if self._on_detection_event and (new_note or update.get("task_done")):
                try:
                    self._on_detection_event(task, new_note)
                except Exception as e:
                    logger.error(f"Failed to emit detection event: {e}")
        if completed_task_seen:
            self._prune_completed_tasks()
        
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
        self.ensure_started()
    
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
        self._schedule_stop_if_idle()
    
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
        
        # 2. Cancel the loop
        if self._loop and not self._loop.done():
            self._loop.cancel()
            try:
                await asyncio.wait_for(self._loop, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        
        self._loop = None

        # 5. Release camera if still open
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

    def get_latest_inference_error(self) -> Optional[Dict[str, Any]]:
        """Return the latest inference error for debug surfaces."""
        if self._latest_inference_error is None:
            return None
        return dict(self._latest_inference_error)

    def get_latest_frame_timestamp(self) -> Optional[float]:
        """Return when the latest frame was captured."""
        return self._latest_frame_timestamp
    
    def get_total_output_count(self) -> int:
        """Get the total number of outputs processed (for debugging)."""
        return self._total_output_count

    def set_keep_alive_without_tasks(self, keep_alive: bool) -> bool:
        """Control whether the ingestor should keep reading frames with zero tasks."""
        self._keep_alive_without_tasks = bool(keep_alive)
        logger.info(
            "Set keep_alive_without_tasks=%s for camera index=%s",
            self._keep_alive_without_tasks,
            self.camera_index,
        )
        return self._keep_alive_without_tasks

    def ensure_started(self) -> None:
        """Start the ingestor if needed using the active event loop strategy."""
        if self._running and self._loop is not None and self._loop.done():
            logger.warning(
                "Detected stale running state for camera index=%s; clearing finished capture task",
                self.camera_index,
            )
            self._running = False
            self._loop = None

        if self._running:
            logger.debug(
                "[DEBUG] VideoStreamIngestor.ensure_started: Ingestor already running for camera_index=%s",
                self.camera_index,
            )
            return

        logger.debug(
            "[DEBUG] VideoStreamIngestor.ensure_started: scheduling start() for camera_index=%s",
            self.camera_index,
        )

        async def start_with_error_handling():
            try:
                await self.start()
            except Exception as e:
                logger.error(
                    "[ERROR] VideoStreamIngestor.start_with_error_handling: Error in start(): %s",
                    e,
                    exc_info=True,
                )

        try:
            asyncio.get_running_loop()
            asyncio.create_task(start_with_error_handling())
        except RuntimeError:
            # Not inside an async context — use the shared background loop.
            bg_loop = get_background_loop()
            if bg_loop and bg_loop.is_running():
                asyncio.run_coroutine_threadsafe(start_with_error_handling(), bg_loop)
                logger.debug(
                    "[DEBUG] VideoStreamIngestor.ensure_started: Scheduled start() on Flask background loop"
                )
            else:
                logger.warning("No event loop available. Could not start ingestor automatically.")

    def get_dedup_status(self) -> Dict[str, Any]:
        """Get frame deduplication status for UI display.
        
        Returns:
            dict with frames_skipped (lifetime), consecutive_skips (since last VLM call),
            and the active average-pixel-difference threshold.
        """
        return {
            "frames_skipped": self._frames_skipped,
            "consecutive_skips": self._consecutive_skips,
            "average_pixel_diff_threshold": float(self._frame_diff_threshold),
            "frame_diff_threshold": float(self._frame_diff_threshold),
            "threshold_unit": self.FRAME_DIFF_THRESHOLD_UNIT,
        }

    def get_frame_diff_threshold(self) -> float:
        """Return the active average-pixel-difference threshold."""
        return float(self._frame_diff_threshold)

    def set_frame_diff_threshold(self, threshold: float) -> float:
        """Update the duplicate-frame threshold for future VLM calls."""
        try:
            threshold_value = float(threshold)
        except (TypeError, ValueError) as exc:
            raise ValueError("Average pixel difference threshold must be numeric") from exc

        threshold_value = max(0.0, min(255.0, threshold_value))
        self._frame_diff_threshold = threshold_value
        logger.info(
            "Updated average pixel difference threshold [camera=%s] to %.2f",
            self.camera_index,
            threshold_value,
        )
        return threshold_value
    
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
        camera_source=0,
        model_provider=model_provider,
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
