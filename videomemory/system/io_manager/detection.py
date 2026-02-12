"""Camera detection using OpenCV."""

import platform
import os
import sys
from contextlib import contextmanager
from typing import List, Tuple
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


@contextmanager
def suppress_stderr():
    """Context manager to suppress stderr output."""
    with open(os.devnull, 'w') as devnull:
        old_stderr = sys.stderr
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stderr = old_stderr


class DeviceDetector:
    """Detects camera devices using OpenCV."""
    
    def __init__(self):
        """Initialize the detector."""
        self.is_mac = platform.system() == 'Darwin'
        self.num_max_cameras = 10
        # OpenCV warnings are suppressed via stderr redirection in detect_cameras()
    
    def detect_cameras(self) -> List[Tuple[int, str]]:
        """Detect camera devices using OpenCV indices.
        
        Returns:
            List of tuples (index, name) where index is the OpenCV camera index
        """
        cameras = []
        if not CV2_AVAILABLE:
            return cameras
        
        # Get system camera names for better naming (optional)
        system_camera_names = self._get_system_camera_names()
        
        for idx in range(self.num_max_cameras):
            cap = None
            try:
                # Suppress OpenCV warnings during camera detection
                with suppress_stderr():
                    if self.is_mac:
                        cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
                    else:
                        cap = cv2.VideoCapture(idx)
                
                if cap.isOpened():
                    # Use system name if available, otherwise generic name
                    if idx < len(system_camera_names):
                        name = system_camera_names[idx]
                    else:
                        name = f"Camera {idx}"
                    
                    cameras.append((idx, name))
                
                # Always release the capture, even if it didn't open successfully
                if cap:
                    cap.release()
            except Exception:
                # Release on exception too
                if cap:
                    try:
                        cap.release()
                    except:
                        pass
        
        return cameras
    
    def _get_system_camera_names(self) -> List[str]:
        """Get camera names from system (optional, for better naming)."""
        import subprocess
        cameras = []
        
        if self.is_mac:
            try:
                result = subprocess.run(
                    ["system_profiler", "SPCameraDataType"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'Camera' in line or 'iSight' in line:
                            parts = line.split(':')
                            if len(parts) >= 2:
                                cameras.append(parts[1].strip())
            except Exception:
                pass
        
        return cameras
    
    def detect_all(self) -> dict:
        """Detect all available cameras.
        
        Returns:
            dict: A dictionary with "camera" key containing List[Tuple[int, str]]
        """
        return {
            "camera": self.detect_cameras(),
        }
