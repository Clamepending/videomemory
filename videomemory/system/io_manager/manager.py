"""IO Manager for tracking and managing camera streams."""

from typing import Dict, List, Optional
from .detection import DeviceDetector


class IOmanager:
    """Manages camera streams and provides consistent io_id references."""
    
    def __init__(self):
        """Initialize the IO manager and scan for available cameras."""
        self._io_streams: Dict[str, Dict] = {}  # io_id -> stream info
        self._last_error: Optional[str] = None
        self._detector = DeviceDetector()
        self._refresh_streams()
    
    def _refresh_streams(self) -> bool:
        """Refresh the list of available cameras and assign IDs.
        
        Uses OpenCV camera indices directly as IO IDs.
        
        Returns:
            True if refresh succeeded, False otherwise
        """
        try:
            streams = self._detector.detect_all()
            camera_list = streams.get("camera", [])
            
            # Track which existing streams are still present
            existing_io_ids = set(self._io_streams.keys())
            current_io_ids = set()
            
            # Process all cameras
            for idx, device_name in camera_list:
                # Use OpenCV index directly as IO ID
                io_id = str(idx)
                current_io_ids.add(io_id)
                
                # Store/update stream information
                self._io_streams[io_id] = {
                    "io_id": io_id,
                    "category": "camera",
                    "name": device_name,
                }
            
            # Remove cameras that are no longer present
            removed_io_ids = existing_io_ids - current_io_ids
            for io_id in removed_io_ids:
                self._io_streams.pop(io_id, None)
            
            return True
        except Exception as e:
            self._last_error = f"Failed to refresh streams: {str(e)}"
            return False
    
    def get_io_id(self, stream_name: str, category: Optional[str] = None) -> Optional[str]:
        """Get the io_id for a camera by name.
        
        Args:
            stream_name: The name of the camera
            category: Optional category (should be "camera" or None)
        
        Returns:
            The io_id if found, None if not found
        """
        if not self._refresh_streams():
            if not self._io_streams:
                raise RuntimeError(
                    f"Failed to get io_id: Unable to refresh streams. "
                    f"Error: {self._last_error}. "
                    f"No cached stream data available."
                )
        
        # Search for camera by name
        for stream_info in self._io_streams.values():
            if stream_info.get("name") == stream_name:
                return stream_info["io_id"]
        
        return None
    
    def get_stream_info(self, io_id: str) -> Optional[Dict]:
        """Get information about a camera stream by io_id.
        
        Args:
            io_id: The unique identifier for the camera (OpenCV index as string)
        
        Returns:
            Dictionary with stream info, or None if not found
        """
        if not self._refresh_streams():
            if not self._io_streams:
                raise RuntimeError(
                    f"Failed to get stream info: Unable to refresh streams. "
                    f"Error: {self._last_error}. "
                    f"No cached stream data available."
                )
        
        return self._io_streams.get(io_id)
    
    def list_all_streams(self, skip_refresh: bool = False) -> List[Dict]:
        """List all available camera streams with their IDs.
        
        Args:
            skip_refresh: If True, skip refresh and return cached streams
        
        Returns:
            List of dictionaries containing camera information
        """
        if not skip_refresh:
            if not self._refresh_streams():
                if not self._io_streams:
                    raise RuntimeError(
                        f"Failed to list streams: Unable to refresh streams. "
                        f"Error: {self._last_error}. "
                        f"No cached stream data available."
                    )
        
        return list(self._io_streams.values())
