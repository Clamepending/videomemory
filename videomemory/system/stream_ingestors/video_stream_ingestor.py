"""Video stream ingestor for managing video input streams - Approach 4: Event-Driven with Message Queue."""

import asyncio
import logging
import os
import platform
import re
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple
from collections import deque
import cv2
import httpx
import numpy as np
from dotenv import load_dotenv

from ..task_types import NoteEntry, Task
from ..model_providers import BaseModelProvider, get_VLM_provider
from ..io_manager.url_utils import is_snapshot_url
from .prompting import (
    TaskUpdate,
    VideoIngestorOutput,
    VLM_INGESTOR_PROMPT_INSTRUCTIONS,
    build_video_ingestor_prompt,
)
from . import background_loop as _background_loop
from .evidence import build_evidence_clip_frames, sample_evidence_frame
from .frame_utils import (
    build_chunk_metadata,
    build_frame_contact_sheet,
    frame_to_base64,
    frame_to_jpeg_bytes,
    is_chunk_complete,
    mean_absolute_frame_difference,
    normalize_frames,
    subsample_frames,
)
from .semantic_autogaze_runtime import MODEL_NAME as SEMANTIC_AUTOGAZE_MODEL_NAME
from .semantic_filter import SemanticFilterResult, SemanticFrameFilter, coerce_config

# Load environment variables
load_dotenv()

# Set up logger for this module
logger = logging.getLogger('VideoStreamIngestor')

_flask_background_loop: Optional[asyncio.AbstractEventLoop] = None


_run_background_loop = _background_loop._run_background_loop


def get_background_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Return a running background loop, creating a fallback one if needed.

    Keep this wrapper so callers can still set
    ``video_stream_ingestor._flask_background_loop`` directly.
    """

    global _flask_background_loop
    loop = _background_loop.get_background_loop(_flask_background_loop)
    if loop is not None:
        _flask_background_loop = loop
    return loop

class VideoStreamIngestor:
    """Manages tasks for a video input stream using event-driven architecture."""

    DEFAULT_FRAME_DIFF_THRESHOLD = 5.0
    FRAME_DIFF_THRESHOLD_UNIT = "average_pixel_difference_0_to_255"
    DEFAULT_EVIDENCE_CLIP_FPS = 6.0
    DEFAULT_EVIDENCE_CLIP_PREROLL_SECONDS = 4.0
    DEFAULT_EVIDENCE_CLIP_END_HOLD_SECONDS = 1.0
    DEFAULT_VIDEO_CHUNK_SECONDS = 2.0
    DEFAULT_VIDEO_CHUNK_SUBSAMPLE_FRAMES = 9
    DEFAULT_VIDEO_CHUNK_QUEUE_MAXSIZE = 10
    DEFAULT_SEMANTIC_FRAME_QUEUE_MAXSIZE = 3
    
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
        self._chunk_processor_task: Optional[asyncio.Task] = None
        self._chunk_queue: Optional[asyncio.Queue] = None
        self._semantic_processor_task: Optional[asyncio.Task] = None
        self._semantic_frame_queue: Optional[asyncio.Queue] = None
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
        self._latest_model_input: Optional[Dict[str, Any]] = None
        self._queued_chunk_created_at: deque = deque()
        self._queued_chunk_frame_counts: deque = deque()
        self._queued_semantic_frame_created_at: deque = deque()
        self._semantic_queue_frames_dropped: int = 0

        evidence_clip_fps = float(os.getenv("VIDEOMEMORY_NOTE_VIDEO_FPS", self.DEFAULT_EVIDENCE_CLIP_FPS))
        evidence_clip_preroll_seconds = float(
            os.getenv("VIDEOMEMORY_NOTE_VIDEO_PREROLL_SECONDS", self.DEFAULT_EVIDENCE_CLIP_PREROLL_SECONDS)
        )
        evidence_clip_end_hold_seconds = float(
            os.getenv("VIDEOMEMORY_NOTE_VIDEO_END_HOLD_SECONDS", self.DEFAULT_EVIDENCE_CLIP_END_HOLD_SECONDS)
        )
        self._evidence_clip_fps = max(1.0, evidence_clip_fps)
        self._evidence_clip_preroll_seconds = max(1.0, evidence_clip_preroll_seconds)
        self._evidence_clip_end_hold_seconds = max(0.0, evidence_clip_end_hold_seconds)
        self._evidence_clip_sample_interval_s = 1.0 / self._evidence_clip_fps
        self._evidence_frame_buffer: deque = deque(
            maxlen=max(2, int(round(self._evidence_clip_fps * self._evidence_clip_preroll_seconds)))
        )
        self._last_evidence_buffer_sample_at: float = 0.0
        
        # Frame deduplication: skip VLM calls when the average pixel difference stays below threshold
        self._last_diff_reference_frame: Optional[Any] = None
        self._latest_frame_diff_frame: Optional[Any] = None
        self._latest_frame_diff_timestamp: Optional[float] = None
        self._frame_diff_threshold: float = self.DEFAULT_FRAME_DIFF_THRESHOLD  # Mean absolute pixel difference threshold (0-255 scale)
        self._frames_skipped: int = 0  # Total frames skipped (lifetime)
        self._consecutive_skips: int = 0  # Frames skipped since last VLM call (for UI)
        self._load_video_chunk_settings_from_env()
        self._semantic_filter = SemanticFrameFilter()
        self._semantic_frames_skipped: int = 0
        self._semantic_consecutive_skips: int = 0
        self._latest_semantic_filter_result: Optional[SemanticFilterResult] = None
        self._latest_semantic_pass_frame: Optional[Any] = None
        self._latest_semantic_pass_timestamp: Optional[float] = None
        self._semantic_evaluations: int = 0
        self._latest_semantic_filter_timestamp: Optional[float] = None
        self._semantic_filter_fps_ema: float = 0.0
        self._semantic_frame_queue_maxsize = max(
            1,
            int(os.getenv("VIDEOMEMORY_SEMANTIC_FRAME_QUEUE_MAXSIZE", self.DEFAULT_SEMANTIC_FRAME_QUEUE_MAXSIZE)),
        )
        self._semantic_preview_refresh_seconds = max(
            0.1,
            float(os.getenv("VIDEOMEMORY_SEMANTIC_PREVIEW_REFRESH_SECONDS", "0.1")),
        )
        self._semantic_refresh_during_frame_diff_skips = (
            os.getenv("VIDEOMEMORY_SEMANTIC_REFRESH_DURING_FRAME_DIFF_SKIPS", "").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        
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

    def _load_video_chunk_settings_from_env(self) -> None:
        """Load chunking knobs from environment-backed settings."""

        self._video_chunk_seconds = max(
            0.1,
            float(os.getenv("VIDEOMEMORY_VIDEO_CHUNK_SECONDS", self.DEFAULT_VIDEO_CHUNK_SECONDS)),
        )
        self._video_chunk_subsample_frames = max(
            1,
            int(os.getenv("VIDEOMEMORY_VIDEO_CHUNK_SUBSAMPLE_FRAMES", self.DEFAULT_VIDEO_CHUNK_SUBSAMPLE_FRAMES)),
        )
        self._video_chunk_queue_maxsize = max(
            1,
            int(os.getenv("VIDEOMEMORY_VIDEO_CHUNK_QUEUE_MAXSIZE", self.DEFAULT_VIDEO_CHUNK_QUEUE_MAXSIZE)),
        )
        self._semantic_frame_queue_maxsize = max(
            1,
            int(os.getenv("VIDEOMEMORY_SEMANTIC_FRAME_QUEUE_MAXSIZE", self.DEFAULT_SEMANTIC_FRAME_QUEUE_MAXSIZE)),
        )

    def reload_video_chunk_settings(self) -> Dict[str, Any]:
        """Reload chunking settings for active ingestors."""

        self._load_video_chunk_settings_from_env()
        if self._chunk_queue is not None and hasattr(self._chunk_queue, "_maxsize"):
            self._chunk_queue._maxsize = self._video_chunk_queue_maxsize
        if self._semantic_frame_queue is not None and hasattr(self._semantic_frame_queue, "_maxsize"):
            self._semantic_frame_queue._maxsize = self._semantic_frame_queue_maxsize
        while len(self._queued_chunk_created_at) > self._video_chunk_queue_maxsize:
            self._queued_chunk_created_at.popleft()
        while len(self._queued_chunk_frame_counts) > self._video_chunk_queue_maxsize:
            self._queued_chunk_frame_counts.popleft()
        while len(self._queued_semantic_frame_created_at) > self._semantic_frame_queue_maxsize:
            self._queued_semantic_frame_created_at.popleft()
        return self.get_video_chunk_settings()

    def get_video_chunk_settings(self) -> Dict[str, Any]:
        """Return active video chunking settings."""

        return {
            "video_chunk_seconds": float(self._video_chunk_seconds),
            "video_chunk_subsample_frames": int(self._video_chunk_subsample_frames),
            "video_chunk_queue_maxsize": int(self._video_chunk_queue_maxsize),
            "semantic_frame_queue_maxsize": int(self._semantic_frame_queue_maxsize),
        }

    def get_chunk_queue_status(self) -> Dict[str, Any]:
        """Return current VLM chunk queue backlog stats for debug UI."""

        queue_size = self._chunk_queue.qsize() if self._chunk_queue is not None else 0
        oldest_age_ms = None
        newest_age_ms = None
        now = time.time()
        if self._queued_chunk_created_at:
            oldest_age_ms = max(0.0, (now - float(self._queued_chunk_created_at[0])) * 1000.0)
            newest_age_ms = max(0.0, (now - float(self._queued_chunk_created_at[-1])) * 1000.0)
        return {
            **self.get_video_chunk_settings(),
            "queued_chunks": int(queue_size),
            "oldest_queued_chunk_age_ms": oldest_age_ms,
            "newest_queued_chunk_age_ms": newest_age_ms,
            "queued_chunk_frame_counts": list(self._queued_chunk_frame_counts),
        }

    def get_semantic_frame_queue_status(self) -> Dict[str, Any]:
        """Return current semantic frame queue backlog stats for debug UI."""

        queue_size = self._semantic_frame_queue.qsize() if self._semantic_frame_queue is not None else 0
        oldest_age_ms = None
        newest_age_ms = None
        now = time.time()
        if self._queued_semantic_frame_created_at:
            oldest_age_ms = max(0.0, (now - float(self._queued_semantic_frame_created_at[0])) * 1000.0)
            newest_age_ms = max(0.0, (now - float(self._queued_semantic_frame_created_at[-1])) * 1000.0)
        return {
            "semantic_frame_queue_maxsize": int(self._semantic_frame_queue_maxsize),
            "queued_semantic_frames": int(queue_size),
            "oldest_queued_semantic_frame_age_ms": oldest_age_ms,
            "newest_queued_semantic_frame_age_ms": newest_age_ms,
            "dropped_semantic_frames": int(self._semantic_queue_frames_dropped),
        }

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
        logger.debug("VideoStreamIngestor.start called for camera_index=%s", self.camera_index)
        
        if self._running:
            logger.info(f"Already running for camera index={self.camera_index}")
            return
        
        self._running = True
        logger.info(f"Starting ingestor for camera index={self.camera_index}")
        
        self._chunk_queue = asyncio.Queue(maxsize=self._video_chunk_queue_maxsize)
        self._chunk_processor_task = asyncio.create_task(
            self._chunk_processing_loop(),
            name=f"chunk_processor_{self.camera_index}",
        )
        self._semantic_frame_queue = asyncio.Queue(maxsize=self._semantic_frame_queue_maxsize)
        self._semantic_processor_task = asyncio.create_task(
            self._semantic_frame_processing_loop(),
            name=f"semantic_processor_{self.camera_index}",
        )
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
            self._record_evidence_frame(current_frame)

        return current_frame

    def _VLM_processing(
        self,
        frames,
    ) -> Optional[Dict[str, Any]]:
        """Run VLM processing on a motion-triggered frame chunk.

        Synchronous — calls the model provider's _sync_generate_content directly.
        The capture loop decides whether a chunk contains enough motion to send,
        but the chunk itself contains frames from the whole time window.

        Returns:
            Results dict with task_updates, processing_time_ms, prompt, and frame
            if VLM was called and returned results. None if skipped.
        """
        if frames is None or not self._tasks_list:
            return None

        frames = normalize_frames(frames)
        if not frames:
            return None

        self._process_loop_ticks += 1
        self._log_periodic_frame_debug(frames[-1])

        model_input = self._prepare_model_input(frames)
        if model_input is None:
            return None
        sampled_frames, model_frame, prompt, image_base64 = model_input

        t0 = time.time()
        if self._total_output_count == 0:
            logger.info("First VLM inference attempt [camera=%s] (base_url from provider env)", self.camera_index)

        self._record_model_input_attempt(
            model_frame=model_frame,
            sampled_frames=sampled_frames,
            raw_frame_count=len(frames),
            prompt=prompt,
        )
        results = self._call_model(image_base64, prompt)
        self._consecutive_skips = 0

        if results:
            self._record_vlm_results(
                results,
                model_frame=model_frame,
                sampled_frames=sampled_frames,
                raw_frame_count=len(frames),
                prompt=prompt,
                started_at=t0,
            )

        return results

    def _record_model_input_attempt(
        self,
        *,
        model_frame: Any,
        sampled_frames: List[Any],
        raw_frame_count: int,
        prompt: str,
    ) -> None:
        """Store the exact model input image before the provider call returns."""

        self._latest_model_input = {
            "timestamp": time.time(),
            "frame": model_frame.copy(),
            "evidence_frame": sampled_frames[-1].copy(),
            "prompt": prompt,
            "chunk": build_chunk_metadata(
                duration_seconds=self._video_chunk_seconds,
                sampled_frame_count=len(sampled_frames),
                raw_frame_count=raw_frame_count,
            ),
        }

    def _log_periodic_frame_debug(self, frame: Any) -> None:
        """Log occasional low-level frame stats for capture debugging."""

        if self._process_loop_ticks % 100 != 0:
            return
        frame_mean = frame.mean()
        logger.debug(
            f"Camera index={self.camera_index}: frame shape={frame.shape}, "
            f"mean={frame_mean:.2f}, min={frame.min()}, max={frame.max()}"
        )

    def _prepare_model_input(
        self,
        frames: List[Any],
    ) -> Optional[Tuple[List[Any], Any, str, str]]:
        """Build a contact sheet from every valid chunk frame and encode it."""

        sampled_frames = subsample_frames(normalize_frames(frames), self._video_chunk_subsample_frames)
        model_frame = build_frame_contact_sheet(sampled_frames, output_size=self._target_resolution)
        if model_frame is None:
            return None

        prompt = self._build_prompt(
            frame_count=len(sampled_frames),
        )
        image_base64 = self._frame_to_base64(model_frame)
        if not image_base64:
            return None

        return sampled_frames, model_frame, prompt, image_base64

    def _call_model(self, image_base64: str, prompt: str) -> Optional[Dict[str, Any]]:
        """Call the configured VLM provider and normalize inference errors."""

        try:
            response: VideoIngestorOutput = self._model_provider._sync_generate_content(
                image_base64=image_base64,
                prompt=prompt,
                response_model=VideoIngestorOutput,
                usage_context={"source": "task_ingestor"},
            )
            self._latest_inference_error = None
            return response.model_dump()
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
            return None

    def _record_vlm_results(
        self,
        results: Dict[str, Any],
        *,
        model_frame: Any,
        sampled_frames: List[Any],
        raw_frame_count: int,
        prompt: str,
        started_at: float,
    ) -> None:
        """Attach debug metadata, store history, and apply task updates."""

        results["processing_time_ms"] = round((time.time() - started_at) * 1000)
        results["timestamp"] = time.time()
        results["frame"] = model_frame.copy()
        results["evidence_frame"] = sampled_frames[-1].copy()
        results["prompt"] = prompt
        results["chunk"] = build_chunk_metadata(
            duration_seconds=self._video_chunk_seconds,
            sampled_frame_count=len(sampled_frames),
            raw_frame_count=raw_frame_count,
        )
        self._output_history.append(results)
        self._total_output_count += 1
        self._process_ml_results(results)

    async def _chunk_processing_loop(self) -> None:
        """Process completed chunks sequentially while capture continues."""

        while self._running:
            queue = self._chunk_queue
            if queue is None:
                await asyncio.sleep(0.1)
                continue
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=0.2)
                if self._queued_chunk_created_at:
                    self._queued_chunk_created_at.popleft()
                if self._queued_chunk_frame_counts:
                    self._queued_chunk_frame_counts.popleft()
            except asyncio.TimeoutError:
                continue
            try:
                await asyncio.to_thread(
                    self._VLM_processing,
                    chunk,
                )
            except Exception as e:
                logger.error(
                    "Error processing video chunk for camera index=%s: %s",
                    self.camera_index,
                    e,
                    exc_info=True,
                )
            finally:
                queue.task_done()

    async def _semantic_frame_processing_loop(self) -> None:
        """Score frame-diff outputs without blocking capture."""

        chunk_frames: List[Any] = []
        chunk_has_motion = False
        chunk_start_monotonic = time.monotonic()

        while self._running:
            queue = self._semantic_frame_queue
            if queue is None:
                await asyncio.sleep(0.05)
                continue
            try:
                frame, frame_monotonic = await asyncio.wait_for(queue.get(), timeout=0.2)
                if self._queued_semantic_frame_created_at:
                    self._queued_semantic_frame_created_at.popleft()
            except asyncio.TimeoutError:
                if chunk_frames and chunk_has_motion and is_chunk_complete(
                    chunk_start_monotonic,
                    time.monotonic(),
                    self._video_chunk_seconds,
                ):
                    self._enqueue_frame_chunk(chunk_frames)
                    chunk_frames = []
                    chunk_has_motion = False
                    chunk_start_monotonic = time.monotonic()
                continue
            try:
                semantic_result = self._apply_semantic_filter(frame)
                if not semantic_result.should_keep:
                    self._record_semantic_skip()
                    continue

                if self._tasks_list:
                    if not chunk_frames:
                        chunk_start_monotonic = frame_monotonic
                    chunk_frames.append(frame.copy())
                    chunk_has_motion = True
                    if is_chunk_complete(chunk_start_monotonic, frame_monotonic, self._video_chunk_seconds):
                        self._enqueue_frame_chunk(chunk_frames)
                        chunk_frames = []
                        chunk_has_motion = False
                        chunk_start_monotonic = frame_monotonic
                else:
                    chunk_frames = []
                    chunk_has_motion = False
                    chunk_start_monotonic = frame_monotonic
            except Exception:
                logger.error(
                    "Error in semantic frame processing loop [camera=%s]",
                    self.camera_index,
                    exc_info=True,
                )
            finally:
                queue.task_done()

        if chunk_frames and chunk_has_motion:
            self._enqueue_frame_chunk(chunk_frames)

    def _semantic_filter_is_active(self) -> bool:
        """Return whether frames need the local semantic scorer before chunking."""

        config = self._semantic_filter.config
        return bool(config.enabled and config.keywords.strip())

    def _enqueue_semantic_frame(self, frame: Any, frame_monotonic: Optional[float] = None) -> None:
        """Queue one frame-diff output for semantic scoring, dropping stale backlog."""

        queue = self._semantic_frame_queue
        if queue is None:
            return

        item = (frame.copy(), frame_monotonic if frame_monotonic is not None else time.monotonic())
        try:
            queue.put_nowait(item)
            self._queued_semantic_frame_created_at.append(time.time())
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.task_done()
                if self._queued_semantic_frame_created_at:
                    self._queued_semantic_frame_created_at.popleft()
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(item)
            self._queued_semantic_frame_created_at.append(time.time())
            self._semantic_queue_frames_dropped += 1

    def _clear_semantic_frame_queue(self) -> None:
        """Drop queued semantic work when filter settings change."""

        queue = self._semantic_frame_queue
        if queue is None:
            self._queued_semantic_frame_created_at.clear()
            return
        while True:
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                break
        self._queued_semantic_frame_created_at.clear()

    def _enqueue_frame_chunk(self, frames: List[Any]) -> None:
        """Queue a completed motion-triggered chunk without blocking capture."""

        if not frames or not self._tasks_list:
            return

        queue = self._chunk_queue
        if queue is None:
            return

        chunk = [frame.copy() for frame in frames]
        try:
            queue.put_nowait(chunk)
            self._queued_chunk_created_at.append(time.time())
            self._queued_chunk_frame_counts.append(len(chunk))
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.task_done()
                if self._queued_chunk_created_at:
                    self._queued_chunk_created_at.popleft()
                if self._queued_chunk_frame_counts:
                    self._queued_chunk_frame_counts.popleft()
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(chunk)
            self._queued_chunk_created_at.append(time.time())
            self._queued_chunk_frame_counts.append(len(chunk))
            logger.warning(
                "Dropped oldest queued video chunk for camera=%s because inference is behind capture",
                self.camera_index,
            )

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
            chunk_frames: List[Any] = []
            chunk_has_motion = False
            chunk_start_monotonic = time.monotonic()

            while self._running:
                try:
                    frame = await asyncio.to_thread(self._frame_capture)
                    if frame is None:
                        await self._handle_missing_frame()
                        continue

                    now_monotonic = time.monotonic()
                    if not self._tasks_list:
                        self._update_filter_preview(frame)
                        chunk_frames = []
                        chunk_has_motion = False
                        chunk_start_monotonic = now_monotonic
                        await asyncio.sleep(0.05)
                        continue

                    chunk_has_motion = self._add_frame_to_chunk(chunk_frames, frame, now_monotonic) or chunk_has_motion

                    if is_chunk_complete(chunk_start_monotonic, now_monotonic, self._video_chunk_seconds):
                        if chunk_has_motion:
                            self._enqueue_frame_chunk(chunk_frames)
                        chunk_frames = []
                        chunk_has_motion = False
                        chunk_start_monotonic = now_monotonic
                except Exception as e:
                    logger.error(f"Error in capture/process loop for camera index={self.camera_index}: {e}", exc_info=True)
                    await asyncio.sleep(0.1)

            if chunk_frames and chunk_has_motion:
                self._enqueue_frame_chunk(chunk_frames)

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

    async def _handle_missing_frame(self) -> None:
        """Handle capture failures and reconnect network streams when needed."""

        if self.is_network_stream and self._consecutive_capture_failures >= self._max_capture_failures:
            reopened = await self._reconnect_network_stream()
            if reopened:
                self._consecutive_capture_failures = 0
        await asyncio.sleep(0.05)

    def _add_frame_to_chunk(self, chunk_frames: List[Any], frame: Any, frame_monotonic: Optional[float] = None) -> bool:
        """Append a frame and return whether it crossed the motion threshold."""

        if self._is_frame_duplicate(frame):
            self._record_duplicate_skip()
            if self._semantic_refresh_during_frame_diff_skips and self._semantic_preview_needs_refresh():
                semantic_result = self._apply_semantic_filter(frame)
                if not semantic_result.should_keep:
                    self._record_semantic_skip()
            chunk_frames.append(frame.copy())
            return False

        self._remember_frame_for_diff(frame)
        if self._semantic_filter_is_active():
            self._enqueue_semantic_frame(frame, frame_monotonic)
            return False

        chunk_frames.append(frame.copy())
        return True

    def _is_frame_duplicate(self, frame: Any) -> bool:
        """Check if a frame is effectively identical to the last processed frame.
        
        Uses mean absolute pixel difference on the 0-255 pixel scale.
        Returns True if the frame should be skipped.
        """
        if self._last_diff_reference_frame is None:
            return False
        if frame.shape != self._last_diff_reference_frame.shape:
            return False
        diff = mean_absolute_frame_difference(frame, self._last_diff_reference_frame)
        return diff < self._frame_diff_threshold

    def _remember_frame_for_diff(self, frame: Any) -> None:
        """Update the frame-diff reference after a frame passes motion filtering."""

        self._last_diff_reference_frame = frame.copy()
        self._latest_frame_diff_frame = frame.copy()
        self._latest_frame_diff_timestamp = time.time()

    def _record_duplicate_skip(self) -> None:
        """Record a frame-diff skip for UI/debug counters."""

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

    def _apply_semantic_filter(self, frame: Any) -> SemanticFilterResult:
        """Run the optional semantic filter after pixel-diff filtering."""

        previous_timestamp = self._latest_semantic_filter_timestamp
        now = time.time()
        result = self._semantic_filter.score(frame)
        self._latest_semantic_filter_result = result
        self._latest_semantic_filter_timestamp = now
        self._semantic_evaluations += 1
        if previous_timestamp is not None and now > previous_timestamp:
            instant_fps = 1.0 / max(now - previous_timestamp, 1e-6)
            self._semantic_filter_fps_ema = (
                instant_fps
                if self._semantic_filter_fps_ema <= 0
                else (0.85 * self._semantic_filter_fps_ema) + (0.15 * instant_fps)
            )
        if result.should_keep:
            self._semantic_consecutive_skips = 0
            if self._semantic_filter.config.enabled and self._semantic_filter.config.keywords.strip():
                self._latest_semantic_pass_frame = frame.copy()
                self._latest_semantic_pass_timestamp = now
        return result

    def _record_semantic_skip(self) -> None:
        """Record a semantic-filter skip for UI/debug counters."""

        self._semantic_frames_skipped += 1
        self._semantic_consecutive_skips += 1
        result = self._latest_semantic_filter_result
        if self._semantic_frames_skipped % 25 == 1:
            logger.info(
                "Skipping semantically irrelevant frames [camera=%s]: %d total skipped "
                "(score %.3f, threshold %.3f, keywords=%s)",
                self.camera_index,
                self._semantic_frames_skipped,
                result.score if result else 0.0,
                result.threshold if result else 0.0,
                ", ".join(result.keywords) if result else "",
            )

    def _semantic_preview_needs_refresh(self) -> bool:
        """Return whether debug preview should refresh semantic scoring despite frame-diff skips."""

        if not self._semantic_filter.config.enabled or not self._semantic_filter.config.keywords.strip():
            return False
        if self._latest_semantic_filter_timestamp is None:
            return True
        return (time.time() - self._latest_semantic_filter_timestamp) >= self._semantic_preview_refresh_seconds

    def _update_filter_preview(self, frame: Any) -> None:
        """Update frame-diff and semantic state for debug preview without VLM work."""

        if self._is_frame_duplicate(frame):
            self._record_duplicate_skip()
            if not (
                self._semantic_refresh_during_frame_diff_skips
                and self._semantic_preview_needs_refresh()
            ):
                return
            if self._semantic_filter_is_active():
                self._enqueue_semantic_frame(frame)
            return
        self._remember_frame_for_diff(frame)
        if self._semantic_filter_is_active():
            self._enqueue_semantic_frame(frame)

    def _frame_to_base64(self, frame: Any) -> str:
        """Convert OpenCV frame to base64 encoded image."""
        return frame_to_base64(frame)

    def _frame_to_jpeg_bytes(self, frame: Any, quality: int = 85) -> bytes:
        """Convert OpenCV frame to JPEG bytes."""
        return frame_to_jpeg_bytes(frame, quality=quality)

    def _record_evidence_frame(self, frame: Any) -> None:
        """Sample frames into a small rolling buffer for note evidence clips."""
        self._last_evidence_buffer_sample_at = sample_evidence_frame(
            self._evidence_frame_buffer,
            frame,
            last_sample_at=self._last_evidence_buffer_sample_at,
            sample_interval_s=self._evidence_clip_sample_interval_s,
        )

    def _build_evidence_clip_frames(self, trigger_frame: Any) -> List[Any]:
        """Build a short preroll evidence clip ending on the trigger frame."""
        return build_evidence_clip_frames(
            self._evidence_frame_buffer,
            trigger_frame,
            fps=self._evidence_clip_fps,
            end_hold_seconds=self._evidence_clip_end_hold_seconds,
        )
    
    def _build_prompt(
        self,
        *,
        frame_count: int = 1,
    ) -> str:
        """Build the prompt for the LLM based on tasks and history."""
        visual_context = None
        if frame_count > 1:
            visual_context = (
                f"The attached image is a chronological contact sheet of {frame_count} "
                f"frames from one {self._video_chunk_seconds:.2f}s video chunk. "
                "Frame labels count upward in time from earliest to latest. "
                f"If more than {self._video_chunk_subsample_frames} frames were available, "
                "these frames were evenly sampled from the chunk. "
                "Use all frames to detect short actions or state changes that may appear in only one frame."
            )
        return build_video_ingestor_prompt(
            self._tasks_list,
            context_label=self.camera_index,
            visual_context=visual_context,
        )

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
    
    def _process_ml_results(self, ml_results: Dict[str, Any]):
        """Process ML inference results: update task notes and queue actions."""
        if not ml_results:
            return

        task_updates = ml_results.get("task_updates", [])
        note_frame = ml_results.get("frame")
        evidence_frame = ml_results.get("evidence_frame")
        if evidence_frame is None:
            evidence_frame = note_frame
        note_frame_bytes = self._frame_to_jpeg_bytes(note_frame)
        note_video_frames = self._build_evidence_clip_frames(evidence_frame)
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
                new_note = NoteEntry(
                    content=new_note_content,
                    frame_bytes=note_frame_bytes or None,
                    video_frames=note_video_frames or None,
                    video_fps=self._evidence_clip_fps if note_video_frames else None,
                )
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
        logger.debug(
            "VideoStreamIngestor.add_task called for task %r, camera_index=%s",
            task.task_desc,
            self.camera_index,
        )
        
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

        if self._chunk_processor_task and not self._chunk_processor_task.done():
            self._chunk_processor_task.cancel()
            try:
                await asyncio.wait_for(self._chunk_processor_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._chunk_processor_task = None
        self._chunk_queue = None

        if self._semantic_processor_task and not self._semantic_processor_task.done():
            self._semantic_processor_task.cancel()
            try:
                await asyncio.wait_for(self._semantic_processor_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._semantic_processor_task = None
        self._semantic_frame_queue = None
        self._queued_semantic_frame_created_at.clear()

        self._release_camera()
        
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

    def get_latest_model_input(self) -> Optional[Dict[str, Any]]:
        """Return the latest exact image/prompt sent to the model provider."""

        if self._latest_model_input is None:
            return None
        return dict(self._latest_model_input)

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
                "VideoStreamIngestor.ensure_started: ingestor already running for camera_index=%s",
                self.camera_index,
            )
            return

        logger.debug(
            "VideoStreamIngestor.ensure_started: scheduling start() for camera_index=%s",
            self.camera_index,
        )

        async def start_with_error_handling():
            try:
                await self.start()
            except Exception as e:
                logger.error(
                    "VideoStreamIngestor.start_with_error_handling: error in start(): %s",
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
                    "VideoStreamIngestor.ensure_started: scheduled start() on background loop"
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

    def get_semantic_filter_status(self) -> Dict[str, Any]:
        """Return semantic frame-filter config and latest scoring status."""

        config = self._semantic_filter.config
        result = self._latest_semantic_filter_result
        payload: Dict[str, Any] = {
            "enabled": config.enabled,
            "keywords": config.keywords,
            "threshold": float(config.threshold),
            "threshold_mode": config.threshold_mode,
            "reduce": config.reduce,
            "smoothing": float(config.smoothing),
            "ensemble": config.ensemble,
            "frames_skipped": self._semantic_frames_skipped,
            "consecutive_skips": self._semantic_consecutive_skips,
            "evaluations": self._semantic_evaluations,
            "latest_evaluation_timestamp": self._latest_semantic_filter_timestamp,
            "evaluation_fps": float(self._semantic_filter_fps_ema),
            "model": SEMANTIC_AUTOGAZE_MODEL_NAME,
        }
        if result is not None:
            payload.update(
                {
                    "last_score": float(result.score),
                    "last_threshold": float(result.threshold),
                    "last_should_keep": bool(result.should_keep),
                    "last_keywords": result.keywords,
                    "last_inference_ms": float(result.inference_ms),
                    "last_error": result.error,
                    "has_heatmap": result.overlay_frame is not None,
                }
            )
        return payload

    def get_semantic_filter_config(self) -> Dict[str, Any]:
        """Return the active semantic-filter configuration."""

        return self.get_semantic_filter_status()

    def set_semantic_filter_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Update the optional semantic-filter configuration."""

        current = self._semantic_filter.config
        merged = {
            "enabled": current.enabled,
            "keywords": current.keywords,
            "threshold": current.threshold,
            "threshold_mode": current.threshold_mode,
            "reduce": current.reduce,
            "smoothing": current.smoothing,
            "ensemble": current.ensemble,
        }
        merged.update(config)
        next_config = coerce_config(merged)
        self._semantic_filter.update_config(next_config)
        self._clear_semantic_frame_queue()
        self._latest_semantic_pass_frame = None
        self._latest_semantic_pass_timestamp = None
        if next_config.enabled and next_config.keywords.strip():
            preview_frame = self._latest_frame_diff_frame
            if preview_frame is not None:
                semantic_result = self._apply_semantic_filter(preview_frame)
                if not semantic_result.should_keep:
                    self._record_semantic_skip()
        logger.info(
            "Updated semantic filter [camera=%s]: enabled=%s keywords=%r threshold=%.3f mode=%s reduce=%s smoothing=%.2f ensemble=%s",
            self.camera_index,
            next_config.enabled,
            next_config.keywords,
            next_config.threshold,
            next_config.threshold_mode,
            next_config.reduce,
            next_config.smoothing,
            next_config.ensemble,
        )
        return self.get_semantic_filter_status()

    def get_latest_semantic_filter_heatmap(self) -> Optional[Any]:
        """Return the latest semantic-filter heatmap overlay frame."""

        result = self._latest_semantic_filter_result
        if result is None or result.overlay_frame is None:
            return None
        return result.overlay_frame.copy()

    def get_latest_semantic_pass_frame(self) -> Optional[Any]:
        """Return the latest raw frame that passed semantic filtering."""

        return self._latest_semantic_pass_frame.copy() if self._latest_semantic_pass_frame is not None else None

    def get_latest_semantic_pass_timestamp(self) -> Optional[float]:
        """Return timestamp for the latest semantic pass output frame."""

        return self._latest_semantic_pass_timestamp

    def get_latest_frame_diff_frame(self) -> Optional[Any]:
        """Return the latest frame that passed the frame-diff filter."""

        return self._latest_frame_diff_frame.copy() if self._latest_frame_diff_frame is not None else None

    def get_latest_frame_diff_timestamp(self) -> Optional[float]:
        """Return timestamp for the latest frame-diff output frame."""

        return self._latest_frame_diff_timestamp

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
