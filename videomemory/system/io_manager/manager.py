"""IO Manager for tracking and managing camera streams."""

import logging
from typing import Dict, List, Optional
from .detection import DeviceDetector

logger = logging.getLogger('IOmanager')


class IOmanager:
    """Manages camera streams and provides consistent io_id references."""
    
    def __init__(self, db=None):
        """Initialize the IO manager and scan for available cameras.
        
        Args:
            db: Optional TaskDatabase instance for persisting network cameras.
        """
        self._io_streams: Dict[str, Dict] = {}  # io_id -> stream info
        self._network_cameras: Dict[str, Dict] = {}  # io_id -> network camera info
        self._last_error: Optional[str] = None
        self._detector = DeviceDetector()
        self._db = db
        self._load_network_cameras()
        self._refresh_streams()
    
    def _load_network_cameras(self):
        """Load persisted network cameras from the database."""
        if self._db is None:
            return
        try:
            cameras = self._db.load_network_cameras()
            for cam in cameras:
                self._network_cameras[cam['io_id']] = {
                    "io_id": cam['io_id'],
                    "category": "camera",
                    "name": cam['name'],
                    "url": cam['url'],
                    "source": "network",
                }
            if cameras:
                logger.info(f"Loaded {len(cameras)} network camera(s) from database")
        except Exception as e:
            logger.error(f"Failed to load network cameras: {e}")

    def _refresh_streams(self) -> bool:
        """Refresh the list of available local cameras and assign IDs.
        
        Uses OpenCV camera indices directly as IO IDs.
        Network cameras are not affected by refresh.
        
        Returns:
            True if refresh succeeded, False otherwise
        """
        try:
            streams = self._detector.detect_all()
            camera_list = streams.get("camera", [])
            
            # Track which existing local streams are still present
            existing_io_ids = {k for k in self._io_streams.keys()
                               if k not in self._network_cameras}
            current_io_ids = set()
            
            # Process all local cameras
            for idx, device_name in camera_list:
                io_id = str(idx)
                current_io_ids.add(io_id)
                
                self._io_streams[io_id] = {
                    "io_id": io_id,
                    "category": "camera",
                    "name": device_name,
                }
            
            # Remove local cameras that are no longer present
            removed_io_ids = existing_io_ids - current_io_ids
            for io_id in removed_io_ids:
                self._io_streams.pop(io_id, None)
            
            # Ensure network cameras are always present in the streams dict
            self._io_streams.update(self._network_cameras)
            
            return True
        except Exception as e:
            self._last_error = f"Failed to refresh streams: {str(e)}"
            return False
    
    def add_network_camera(self, url: str, name: str = None) -> Dict:
        """Register a network camera (RTSP/HTTP stream).
        
        Args:
            url: The stream URL (e.g. rtsp://admin:pass@192.168.1.50:554/stream1)
            name: Optional display name. Defaults to the URL host.
        
        Returns:
            Dictionary with the new device info including io_id.
        """
        if name is None:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                name = f"Network Camera ({parsed.hostname or url})"
            except Exception:
                name = f"Network Camera ({url})"
        
        if self._db:
            io_id = self._db.get_next_network_camera_id()
        else:
            existing = {k for k in self._network_cameras if k.startswith('net')}
            idx = 0
            while f"net{idx}" in existing:
                idx += 1
            io_id = f"net{idx}"
        
        camera_info = {
            "io_id": io_id,
            "category": "camera",
            "name": name,
            "url": url,
            "source": "network",
        }
        
        self._network_cameras[io_id] = camera_info
        self._io_streams[io_id] = camera_info
        
        if self._db:
            self._db.save_network_camera(io_id, name, url)
        
        logger.info(f"Added network camera: io_id={io_id}, name={name}, url={url}")
        return camera_info
    
    def remove_network_camera(self, io_id: str) -> bool:
        """Remove a network camera.
        
        Args:
            io_id: The io_id of the network camera to remove.
        
        Returns:
            True if removed, False if not found.
        """
        if io_id not in self._network_cameras:
            return False
        
        del self._network_cameras[io_id]
        self._io_streams.pop(io_id, None)
        
        if self._db:
            self._db.delete_network_camera(io_id)
        
        logger.info(f"Removed network camera: io_id={io_id}")
        return True
    
    def is_network_camera(self, io_id: str) -> bool:
        """Check if an io_id refers to a network camera."""
        return io_id in self._network_cameras
    
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
