import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from videomemory.system.io_manager import detection as detection_module


class DeviceDetectorMacOSTests(unittest.TestCase):
    def test_detect_cameras_uses_enumeration_without_opening_devices_on_macos(self):
        detector = detection_module.DeviceDetector()
        detector.is_mac = True
        detector.is_linux = False

        fake_cv2 = SimpleNamespace(CAP_AVFOUNDATION=1200, CAP_ANY=0, VideoCapture=MagicMock())
        fake_cameras = [
            SimpleNamespace(index=0, name="FaceTime HD Camera", backend=1200),
            SimpleNamespace(index=1, name="OBS Virtual Camera", backend=1200),
        ]

        with (
            patch.object(detection_module, "CV2_AVAILABLE", True),
            patch.object(detection_module, "CV2_ENUMERATE_AVAILABLE", True),
            patch.object(detection_module, "cv2", fake_cv2),
            patch.object(detection_module, "enumerate_cameras", return_value=fake_cameras, create=True),
        ):
            result = detector.detect_cameras()

        self.assertEqual(result, [(0, "FaceTime HD Camera"), (1, "OBS Virtual Camera")])
        fake_cv2.VideoCapture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
