import asyncio
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import cv2
import numpy as np

import flask_app.app as app_module
from videomemory.system.stream_ingestors.video_stream_ingestor import VideoStreamIngestor


def _make_test_jpeg() -> bytes:
    frame = np.zeros((24, 32, 3), dtype=np.uint8)
    frame[:, :] = (40, 180, 90)
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("Failed to encode test JPEG")
    return encoded.tobytes()


class _SnapshotHandler(BaseHTTPRequestHandler):
    snapshot_bytes = _make_test_jpeg()
    request_count = 0

    def do_GET(self):
        type(self).request_count += 1
        if self.path.split("?", 1)[0] != "/snapshot.jpg":
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(self.snapshot_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(self.snapshot_bytes)

    def log_message(self, format, *args):
        return


class _SnapshotTestServer:
    def __enter__(self):
        _SnapshotHandler.request_count = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _SnapshotHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.url = f"http://{host}:{port}/snapshot.jpg"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class SnapshotApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_add_network_camera_accepts_snapshot_url(self):
        snapshot_url = "http://127.0.0.1:8080/snapshot.jpg"

        with patch.object(
            app_module.io_manager,
            "add_network_camera",
            return_value={"io_id": "net0", "name": "Phone Camera", "pull_url": snapshot_url},
        ) as mock_add:
            resp = self.client.post(
                "/api/devices/network",
                json={"url": snapshot_url, "name": "Phone Camera"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["device"]["pull_url"], snapshot_url)
        mock_add.assert_called_once_with(snapshot_url, "Phone Camera")

    def test_preview_endpoint_fetches_snapshot_url(self):
        with _SnapshotTestServer() as snapshot_server:
            with (
                patch.object(
                    app_module.io_manager,
                    "get_stream_info",
                    return_value={"category": "camera", "pull_url": snapshot_server.url},
                ),
                patch.object(app_module.task_manager, "get_latest_frame_for_device", return_value=None),
            ):
                resp = self.client.get("/api/device/net0/preview")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "image/jpeg")
        self.assertGreater(len(resp.data), 0)
        self.assertGreater(_SnapshotHandler.request_count, 0)

    def test_preview_stream_endpoint_emits_mjpeg_for_snapshot_url(self):
        with _SnapshotTestServer() as snapshot_server:
            with (
                patch.object(
                    app_module.io_manager,
                    "get_stream_info",
                    return_value={"category": "camera", "pull_url": snapshot_server.url},
                ),
                patch.object(app_module.task_manager, "get_latest_frame_for_device", return_value=None),
            ):
                resp = self.client.get("/api/device/net0/preview/stream", buffered=False)
                try:
                    first_chunk = next(resp.response)
                finally:
                    resp.close()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "multipart/x-mixed-replace")
        self.assertIn(b"--frame", first_chunk)
        self.assertIn(b"Content-Type: image/jpeg", first_chunk)

    def test_openapi_documents_snapshot_url_support(self):
        resp = self.client.get("/openapi.json")
        self.assertEqual(resp.status_code, 200)

        body = resp.get_json()
        description = body["paths"]["/api/devices/network"]["post"]["description"]
        url_description = (
            body["paths"]["/api/devices/network"]["post"]["requestBody"]["content"]["application/json"]["schema"][
                "properties"
            ]["url"]["description"]
        )

        self.assertIn("snapshot", description.lower())
        self.assertIn("snapshot", url_description.lower())


class SnapshotIngestorTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_source_reads_single_frame(self):
        with _SnapshotTestServer() as snapshot_server:
            ingestor = VideoStreamIngestor(snapshot_server.url, model_provider=object())
            try:
                self.assertTrue(ingestor._open_camera())
                ret, frame = ingestor._read_latest_frame()
            finally:
                ingestor._release_camera()

        self.assertTrue(ret)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape[:2], (24, 32))

    async def test_snapshot_source_capture_loop_updates_latest_frame(self):
        with _SnapshotTestServer() as snapshot_server:
            ingestor = VideoStreamIngestor(snapshot_server.url, model_provider=object())
            await ingestor.start()
            try:
                latest_frame = None
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline:
                    latest_frame = ingestor.get_latest_frame()
                    if latest_frame is not None:
                        break
                    await asyncio.sleep(0.05)
            finally:
                await ingestor.stop()

        self.assertIsNotNone(latest_frame)
        self.assertEqual(latest_frame.shape[:2], (480, 640))
        self.assertGreater(_SnapshotHandler.request_count, 0)
        self.assertIsNone(ingestor._snapshot_client)


if __name__ == "__main__":
    unittest.main()
