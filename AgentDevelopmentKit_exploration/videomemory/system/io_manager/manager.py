"""IO Manager for tracking and managing input/output streams."""

import hashlib
from typing import Dict, List, Optional
from system.io_manager.detection import DeviceDetector


class IOmanager:
    """Manages IO streams and provides consistent io_id references."""
    
    def __init__(self):
        """Initialize the IO manager and scan for available streams."""
        self._io_streams: Dict[str, Dict] = {}  # io_id -> stream info
        self._last_error: Optional[str] = None
        self._detector = DeviceDetector()
        self._refresh_streams()
    
    def _get_io_id_from_key(self, stream_key: str) -> str:
        """Generate a deterministic io_id from a stream key using hashing."""
        return hashlib.sha256(stream_key.encode()).hexdigest()[:8]
    
    def _refresh_streams(self) -> bool:
        """Refresh the list of available streams and assign IDs.
        
        Uses deterministic hashing so the same device always gets the same io_id,
        even after reconnection (as long as the device name stays the same).
        
        Returns:
            True if refresh succeeded, False otherwise
        """
        try:
            streams = self._detector.detect_all()
            
            # Create a set of currently detected stream keys
            current_stream_keys = set()
            for category, device_list in streams.items():
                for device_name in device_list:
                    key = f"{category}:{device_name}"
                    current_stream_keys.add(key)
            
            # Track which existing streams are still present (by io_id)
            existing_io_ids = set(self._io_streams.keys())
            current_io_ids = set()
            
            # Process all current streams
            for category, device_list in streams.items():
                for device_name in device_list:
                    key = f"{category}:{device_name}"
                    # Generate deterministic io_id from stream key
                    io_id = self._get_io_id_from_key(key)
                    current_io_ids.add(io_id)
                    
                    # Store/update stream information
                    self._io_streams[io_id] = {
                        "io_id": io_id,
                        "category": category,
                        "name": device_name,
                    }
            
            # Remove streams that are no longer present
            removed_io_ids = existing_io_ids - current_io_ids
            for io_id in removed_io_ids:
                self._io_streams.pop(io_id, None)
            
            return True
        except Exception as e:
            # Log error but don't raise - allow methods to handle gracefully
            self._last_error = f"Failed to refresh streams: {str(e)}"
            return False
    
    def get_io_id(self, stream_name: str, category: Optional[str] = None) -> Optional[str]:
        """Get the io_id for a stream by name.
        
        Automatically refreshes the stream list before searching to ensure
        up-to-date information.
        
        Args:
            stream_name: The name of the stream
            category: Optional category to narrow down the search
        
        Returns:
            The io_id if found, None if not found or if refresh failed.
            Check _last_error for error details if needed.
        
        Raises:
            RuntimeError: If stream refresh fails and no cached data is available
        """
        # Refresh streams before lookup
        if not self._refresh_streams():
            if not self._io_streams:
                raise RuntimeError(
                    f"Failed to get io_id: Unable to refresh streams. "
                    f"Error: {self._last_error}. "
                    f"No cached stream data available."
                )
            # If refresh failed but we have cached data, continue with warning
        
        try:
            if category:
                # Compute io_id directly from stream key
                key = f"{category}:{stream_name}"
                io_id = self._get_io_id_from_key(key)
                # Verify it exists in current streams
                if io_id in self._io_streams:
                    return io_id
                return None
            
            # Search across all categories
            for stream_info in self._io_streams.values():
                if stream_info["name"] == stream_name:
                    return stream_info["io_id"]
            
            return None
        except Exception as e:
            raise RuntimeError(
                f"Device with name '{stream_name}' not found: {str(e)}"
            )
    
    def get_stream_info(self, io_id: str) -> Optional[Dict]:
        """Get information about a stream by io_id.
        
        Automatically refreshes the stream list before lookup to ensure
        up-to-date information.
        
        Args:
            io_id: The unique identifier for the stream
        
        Returns:
            Dictionary with stream info, or None if not found.
            Returns None if refresh failed and stream not in cache.
        
        Raises:
            RuntimeError: If stream refresh fails and no cached data is available
        """
        # Refresh streams before lookup
        if not self._refresh_streams():
            if not self._io_streams:
                raise RuntimeError(
                    f"Failed to get stream info: Unable to refresh streams. "
                    f"Error: {self._last_error}. "
                    f"No cached stream data available."
                )
            # If refresh failed but we have cached data, continue with warning
        
        try:
            return self._io_streams.get(io_id)
        except Exception as e:
            raise RuntimeError(
                f"Device with io_id '{io_id}' not found: {str(e)}"
            )
    
    def list_all_streams(self) -> List[Dict]:
        """List all available streams with their IDs.
        
        Automatically refreshes the stream list before returning to ensure
        up-to-date information.
        
        Returns:
            List of dictionaries containing stream information.
            Returns empty list if refresh fails and no cached data available.
        
        Raises:
            RuntimeError: If stream refresh fails and no cached data is available
        """
        # Refresh streams before listing
        if not self._refresh_streams():
            if not self._io_streams:
                raise RuntimeError(
                    f"Failed to list streams: Unable to refresh streams. "
                    f"Error: {self._last_error}. "
                    f"No cached stream data available."
                )
            # If refresh failed but we have cached data, return cached data with warning
        
        try:
            return list(self._io_streams.values())
        except Exception as e:
            raise RuntimeError(
                f"Error while listing streams: {str(e)}"
            )

