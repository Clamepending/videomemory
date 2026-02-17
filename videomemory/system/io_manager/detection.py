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
                
                # Try enumeration up to 2 times (USB cameras may need a moment to be recognized)
                import time
                camera_infos = None
                for attempt in range(2):
                    try:
                        camera_infos = list(enumerate_cameras(backend))
                        if camera_infos:
                            break
                    except Exception:
                        if attempt < 1:
                            time.sleep(0.5)  # Wait a bit for USB cameras to be recognized
                
                if camera_infos is None:
                    camera_infos = []
                
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Found {len(camera_infos)} cameras from enumeration")
                
                for camera_info in camera_infos:
                    # Simple verification: just check if camera can be opened
                    # Don't require frame reading - camera might be in use or initializing
                    cap = None
                    try:
                        cap = cv2.VideoCapture(camera_info.index, camera_info.backend)
                        if cap.isOpened():
                            # Camera can be opened - include it
                            # Don't require frame reading (camera might be in use)
                            cameras.append((camera_info.index, camera_info.name))
                            logger.debug(f"Added camera {camera_info.index}: {camera_info.name}")
                        else:
                            logger.debug(f"Camera {camera_info.index} ({camera_info.name}) could not be opened")
                    except Exception as e:
                        logger.debug(f"Exception verifying camera {camera_info.index} ({camera_info.name}): {e}")
                        # Skip if camera can't be opened at all
                        pass
                    finally:
                        if cap is not None:
                            try:
                                cap.release()
                            except Exception:
                                pass
                
                logger.debug(f"Returning {len(cameras)} verified cameras")
                return cameras
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"cv2-enumerate-cameras failed: {e}")
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
                    # Simple verification: just check if camera can be opened
                    cap = None
                    try:
                        cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
                        if cap.isOpened():
                            # Camera can be opened - include it
                            cameras.append((idx, name))
                    except Exception:
                        pass  # Skip if can't open
                    finally:
                        if cap is not None:
                            try:
                                cap.release()
                            except Exception:
                                pass
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
