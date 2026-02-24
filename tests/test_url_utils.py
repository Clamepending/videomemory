import os
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


class UrlUtilsTests(unittest.TestCase):
    def test_rtmp_to_rtsp(self):
        self.assertEqual(
            get_pull_url("rtmp://example.com:1935/live/frontdoor"),
            "rtsp://example.com:8554/live/frontdoor",
        )

    def test_srt_streamid_publish_to_rtsp(self):
        self.assertEqual(
            get_pull_url("srt://example.com:8890?streamid=publish:live/frontdoor"),
            "rtsp://example.com:8554/live/frontdoor",
        )

    def test_whip_scheme_to_rtsp(self):
        self.assertEqual(
            get_pull_url("whip://example.com:8889/live/frontdoor"),
            "rtsp://example.com:8554/live/frontdoor",
        )

    def test_http_whip_endpoint_to_rtsp(self):
        self.assertEqual(
            get_pull_url("http://example.com:8889/live/frontdoor/whip"),
            "rtsp://example.com:8554/live/frontdoor",
        )

    def test_non_whip_http_unchanged(self):
        url = "http://camera.local/stream.mjpeg"
        self.assertEqual(get_pull_url(url), url)

    def test_respects_custom_rtsp_port(self):
        old = os.environ.get("VIDEOMEMORY_RTSP_PULL_PORT")
        os.environ["VIDEOMEMORY_RTSP_PULL_PORT"] = "9554"
        try:
            self.assertEqual(
                get_pull_url("srt://example.com:8890?streamid=publish:live/frontdoor"),
                "rtsp://example.com:9554/live/frontdoor",
            )
        finally:
            if old is None:
                os.environ.pop("VIDEOMEMORY_RTSP_PULL_PORT", None)
            else:
                os.environ["VIDEOMEMORY_RTSP_PULL_PORT"] = old


if __name__ == "__main__":
    unittest.main()
