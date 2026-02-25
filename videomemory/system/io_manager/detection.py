"""Camera detection using OpenCV."""

import logging
import os
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

logger = logging.getLogger(__name__)


class DeviceDetector:
    """Detects camera devices using OpenCV."""
    
    def __init__(self):
        """Initialize the detector."""
        self.is_mac = platform.system() == 'Darwin'
        self.is_linux = platform.system() == 'Linux'
    
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
                
                import time
                camera_infos = None
                for attempt in range(2):
                    try:
                        camera_infos = list(enumerate_cameras(backend))
                        if camera_infos:
                            break
                    except Exception:
                        if attempt < 1:
                            time.sleep(0.5)
                
                if camera_infos is None:
                    camera_infos = []
                
                logger.debug(f"Found {len(camera_infos)} cameras from enumeration")
                
                for camera_info in camera_infos:
                    if self.is_linux:
                        # On Linux, trust the enumeration -- don't try to open the
                        # camera because the device may already be held by a running
                        # video ingestor, which would cause the open to fail and the
                        # camera to vanish from the list on refresh.
                        cameras.append((camera_info.index, camera_info.name))
                        logger.debug(f"Added camera {camera_info.index}: {camera_info.name}")
                    else:
                        cap = None
                        try:
                            cap = cv2.VideoCapture(camera_info.index, camera_info.backend)
                            if cap.isOpened():
                                cameras.append((camera_info.index, camera_info.name))
                                logger.debug(f"Added camera {camera_info.index}: {camera_info.name}")
                            else:
                                logger.debug(f"Camera {camera_info.index} ({camera_info.name}) could not be opened")
                        except Exception as e:
                            logger.debug(f"Exception verifying camera {camera_info.index} ({camera_info.name}): {e}")
                        finally:
                            if cap is not None:
                                try:
                                    cap.release()
                                except Exception:
                                    pass
                
                logger.debug(f"Returning {len(cameras)} verified cameras")
                return cameras
            except Exception as e:
                logger.debug(f"cv2-enumerate-cameras failed: {e}")
                pass
        
        # Fallback: manual detection
        if self.is_mac:
            cameras = self._detect_cameras_macos_fallback()
            if cameras:
                return cameras
            # Final fallback for macOS when AVFoundation bindings are unavailable:
            # probe OpenCV indices directly with the AVFoundation backend.
            return self._detect_cameras_generic()
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
            logger.debug("AVFoundation Python bindings unavailable; using OpenCV index scan fallback")
        except Exception as e:
            logger.debug(f"AVFoundation camera enumeration failed: {e}")
        
        return cameras
    
    def _detect_cameras_generic(self) -> List[Tuple[int, str]]:
        """Generic camera detection for non-macOS systems.
        
        On Linux, probes V4L2 sysfs to find real capture devices instead of
        blindly iterating indices (which causes noisy FFMPEG/V4L2 errors on
        systems like the Raspberry Pi where many /dev/video* nodes exist for
        ISP/metadata and are not capture devices).
        """
        cameras = []

        if self.is_linux:
            cameras = self._detect_cameras_linux()
            if cameras:
                return cameras
            logger.debug("V4L2 sysfs detection found no cameras, falling back to index scan")

        for idx in range(10):
            cap = None
            try:
                if self.is_mac:
                    cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
                else:
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

    def _detect_cameras_linux(self) -> List[Tuple[int, str]]:
        """Detect capture-capable V4L2 devices on Linux via sysfs + ioctl.
        
        Does NOT open the camera with OpenCV for verification -- the ioctl
        already proves capture capability, and opening would fail when the
        device is already held by a running video ingestor.
        """
        v4l2_sysfs = "/sys/class/video4linux"
        if not os.path.isdir(v4l2_sysfs):
            return []

        cameras = []
        for entry in sorted(os.listdir(v4l2_sysfs)):
            if not entry.startswith("video"):
                continue
            try:
                idx = int(entry[len("video"):])
            except ValueError:
                continue

            dev_path = f"/dev/{entry}"
            if not os.path.exists(dev_path):
                continue

            if not self._is_v4l2_capture_device(dev_path):
                logger.debug(f"Skipping {dev_path}: not a capture device")
                continue

            name = f"Camera {idx}"
            name_file = os.path.join(v4l2_sysfs, entry, "name")
            try:
                with open(name_file, "r") as f:
                    name = f.read().strip() or name
            except OSError:
                pass

            cameras.append((idx, name))
            logger.debug(f"Found capture device {dev_path}: {name}")

        return cameras

    @staticmethod
    def _is_v4l2_capture_device(dev_path: str) -> bool:
        """Check whether a /dev/videoN node supports V4L2_CAP_VIDEO_CAPTURE."""
        import fcntl
        import struct

        VIDIOC_QUERYCAP = 0x80685600
        V4L2_CAP_VIDEO_CAPTURE = 0x00000001
        V4L2_CAP_DEVICE_CAPS = 0x80000000

        try:
            with open(dev_path, "rb") as f:
                buf = bytearray(104)
                fcntl.ioctl(f, VIDIOC_QUERYCAP, buf)
                capabilities = struct.unpack_from("<I", buf, 84)[0]
                if capabilities & V4L2_CAP_DEVICE_CAPS:
                    device_caps = struct.unpack_from("<I", buf, 88)[0]
                    return bool(device_caps & V4L2_CAP_VIDEO_CAPTURE)
                return bool(capabilities & V4L2_CAP_VIDEO_CAPTURE)
        except (OSError, IOError, PermissionError):
            return False
    
    def detect_all(self) -> dict:
        """Detect all available cameras.
        
        Returns:
            dict: A dictionary with "camera" key containing List[Tuple[int, str]]
        """
        return {
            "camera": self.detect_cameras(),
        }
