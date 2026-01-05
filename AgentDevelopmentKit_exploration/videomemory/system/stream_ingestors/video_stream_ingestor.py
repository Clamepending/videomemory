"""Video stream ingestor for managing video input streams - Approach 4: Event-Driven with Message Queue."""

import asyncio
import logging
from typing import Dict, Optional, Any
from asyncio import Queue as AsyncQueue
from tools.output_actions import take_output_action
import cv2

# Set up logger for this module
logger = logging.getLogger('VideoStreamIngestor')

class VideoStreamIngestor:
    """Manages tasks for a video input stream using event-driven architecture."""
    
    def __init__(self, io_id: str):
        """Initialize the video stream ingestor.
        
        Args:
            io_id: The unique identifier of the IO stream
        """
        self.io_id = io_id
        self._task_notes: Dict[str, dict] = {}  # task_desc -> task_notes dict
        self._frame_queue = AsyncQueue(maxsize=10)
        self._action_queue = AsyncQueue()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._camera: Optional[Any] = None  # Will hold cv2.VideoCapture when started
        logger.info(f"Initialized for io_id={self.io_id}")
    
    async def start(self):
        """Start the video stream ingestor and all processing loops."""
        if self._running:
            logger.info(f"Already running for io_id={self.io_id}")
            return
        
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
                    # Use DEBUG level for frequent frame processing messages
                    logger.debug(f"Process loop: Frame got from process loop queue for io_id={self.io_id}")
                    # Run ML processing (placeholder - replace with actual ML model)
                    results = await self._run_ml_inference(frame, self._task_notes)
                    
                    # Update task_notes for all active tasks
                    for task_desc, task_notes in self._task_notes.items():
                        await self._update_task_notes(task_desc, task_notes, results)
                        
                        # Check if action should be triggered
                        action = await self._check_action_conditions(task_desc, task_notes, results)
                        if action:
                            await self._action_queue.put(action)
                            
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
    
    async def _run_ml_inference(self, frame: Any, task_notes: dict) -> Dict[str, Any]:
        """Run ML inference on a frame (placeholder for custom ML architecture).
        
        Args:
            frame: The frame to process (numpy array or mock dict)
            task_notes: The shared task_notes dictionary (maps task_desc to task_notes)
        Returns:
            Dictionary with ML inference results
        """
        # TODO: Replace with actual ML model inference
        # This is a placeholder that simulates ML processing
        
        # For now, return mock results
        # In real implementation, this would:
        # 1. Preprocess frame
        # 2. Run through ML model
        # 3. Post-process results
        # 4. Return structured results
        
        await asyncio.sleep(0.07)  # Simulate processing time
        
        return {
            "task description": "count number of claps and then send an email to example@hotmail.com",
            "new note content": "This is a new note. currently 1 clap",
            "Action to take": None,
        }
    
    async def _update_task_notes(self, task_desc: str, task_notes: dict, ml_results: Dict[str, Any]):
        """Update task notes based on ML results.
        
        Args:
            task_desc: Description of the task
            task_notes: The shared task_notes dictionary
            ml_results: Results from ML inference
        """
        # TODO: Uncomment when ML model is implemented. Want to test with just 1 task and test task_notes updating
        # if task_desc != ml_results["task description"]:
        #     return
        # task_notes is already the dictionary for this specific task (shared reference)
        # So we update it directly, not task_notes[task_desc]
        task_notes["note"] = ml_results["new note content"]
    
    async def _check_action_conditions(self, task_desc: str, task_notes: dict, ml_results: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Check if an action should be triggered based on task conditions.
        
        Args:
            task_desc: Description of the task
            task_notes: The shared task_notes dictionary
            ml_results: Results from ML inference
        
        Returns:
            Action dictionary if action should be triggered, None otherwise
        """
        if task_desc != ml_results["task description"]:
            return
        if ml_results["Action to take"] != None:
            return ml_results["Action to take"]
        return None
    
    async def _execute_action(self, action: str):
        """Execute an action (e.g., call take_output_action).
        
        Args:
            action: Dictionary describing the action to execute
        """
        try:
            result = await take_output_action(action)
            logger.info(f"Action result: {result}")
        except Exception as e:
            logger.error(f"Error calling take_output_action: {e}", exc_info=True)
    
    def add_task(self, task_desc: str, task_notes: dict):
        """Add a task to the video stream ingestor.
        
        Args:
            task_desc: Description of the task to be performed
            task_notes: Dictionary to store notes and status for this task (shared reference)
        """
        self._task_notes[task_desc] = task_notes
        
        # Initialize task notes
        task_notes["note"] = "" # want to use a string for simplicity but dictionary is more flexible and is passed by reference
        
        logger.info(f"Added task '{task_desc}' for io_id={self.io_id}")
        
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
