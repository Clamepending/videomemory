import unittest
import importlib.util
from pathlib import Path


_URL_UTILS_PATH = (
    Path(__file__).resolve().parents[1]
    / "videomemory"
    / "system"
    / "io_manager"
    / "url_utils.py"
)
_SPEC = importlib.util.spec_from_file_location("videomemory_url_utils", _URL_UTILS_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MODULE)
get_pull_url = _MODULE.get_pull_url
is_snapshot_url = _MODULE.is_snapshot_url


class UrlUtilsTests(unittest.TestCase):
    def test_pass_through(self):
        url = "http://camera.local/stream.mjpeg"
        self.assertEqual(get_pull_url(url), url)
        
        self.assertEqual(
            get_pull_url("rtsp://admin:admin@192.168.1.5:8554/cam"),
            "rtsp://admin:admin@192.168.1.5:8554/cam"
        )

    def test_is_snapshot_url(self):
        self.assertTrue(is_snapshot_url("http://phone.local:8080/snapshot.jpg"))
        self.assertTrue(is_snapshot_url("https://camera.local/api/snapshot"))
        self.assertFalse(is_snapshot_url("http://camera.local/stream.mjpeg"))
        self.assertFalse(is_snapshot_url("rtsp://camera.local/live"))


if __name__ == "__main__":
    unittest.main()
