"""Camera detection using OpenCV."""

import platform
from typing import List, Tuple

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    from cv2_enumerate_cameras import enumerate_cameras
    CV2_ENUMERATE_AVAILABLE = True
except ImportError:
    CV2_ENUMERATE_AVAILABLE = False


class DeviceDetector:
    """Detects camera devices using OpenCV."""
    
    def __init__(self):
        """Initialize the detector."""
        self.is_mac = platform.system() == 'Darwin'
    
    def detect_cameras(self) -> List[Tuple[int, str]]:
        """Detect camera devices using OpenCV indices.
        
        Returns:
            List of tuples (opencv_index, name) where index is the OpenCV camera index
        """
        if not CV2_AVAILABLE:
            return []
        
        # Use cv2-enumerate-cameras library if available (cleanest solution)
        if CV2_ENUMERATE_AVAILABLE:
            try:
                backend = cv2.CAP_AVFOUNDATION if self.is_mac else cv2.CAP_ANY
                cameras = []
                for camera_info in enumerate_cameras(backend):
                    cameras.append((camera_info.index, camera_info.name))
                return cameras
            except Exception:
                # Fallback to manual detection if library fails
                pass
        
        # Fallback: manual detection
        if self.is_mac:
            return self._detect_cameras_macos_fallback()
        else:
            return self._detect_cameras_generic()
    
    def _detect_cameras_macos_fallback(self) -> List[Tuple[int, str]]:
        """Fallback detection for macOS when cv2-enumerate-cameras is not available."""
        cameras = []
        try:
            from AVFoundation import AVCaptureDevice
            av_devices = list(AVCaptureDevice.devicesWithMediaType_("vide") or [])
            
            for idx, device in enumerate(av_devices):
                if device:
                    name = device.localizedName() or f"Camera {idx}"
                    cameras.append((idx, name))
        except ImportError:
            pass
        except Exception:
            pass
        
        return cameras
    
    def _detect_cameras_generic(self) -> List[Tuple[int, str]]:
        """Generic camera detection for non-macOS systems."""
        cameras = []
        # Try first 10 indices
        for idx in range(10):
            cap = None
            try:
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    cameras.append((idx, f"Camera {idx}"))
            except Exception:
                pass
            finally:
                if cap:
                    try:
                        cap.release()
                    except:
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
