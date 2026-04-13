import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HELPER_PATH = (
    Path(__file__).resolve().parent.parent
    / "deploy"
    / "openclaw-real-home"
    / "hooks"
    / "bin"
    / "videomemory-task-helper.mjs"
)


class _TaskHelperHandler(BaseHTTPRequestHandler):
    server_version = "TaskHelperTest/1.0"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        payload = json.loads(body or "{}")

        if self.path == "/api/tasks":
            self.server.requests.append(("POST", self.path, payload))
            self._send_json({"status": "success", "task_id": "3", "io_id": payload.get("io_id", "")})
            return

        self.send_error(404)

    def do_PUT(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        payload = json.loads(body or "{}")

        if self.path == "/api/task/3":
            self.server.requests.append(("PUT", self.path, payload))
            self._send_json({"status": "success", "task_id": "3", "io_id": "net0", "message": "Task updated successfully"})
            return

        self.send_error(404)

    def do_GET(self):
        if self.path == "/api/task/3":
            self.server.requests.append(("GET", self.path, None))
            self._send_json({"task": {"task_id": "3", "io_id": "net0", "bot_id": "openclaw"}})
            return

        self.send_error(404)

    def log_message(self, format, *args):
        return

    def _send_json(self, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class _TaskHelperHttpServer(ThreadingHTTPServer):
    def __init__(self, server_address):
        super().__init__(server_address, _TaskHelperHandler)
        self.requests = []


class VideoMemoryTaskHelperOriginalRequestTests(unittest.TestCase):
    def setUp(self):
        self.registry_dir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.registry_dir.name) / "videomemory-task-actions.json"
        self.session_store_path = Path(self.registry_dir.name) / "sessions.json"
        self.session_store_path.write_text("{}\n")
        self.server = _TaskHelperHttpServer(("127.0.0.1", 0))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.registry_dir.cleanup()

    def _run_helper_raw(self, *args, check=True, extra_env=None):
        env = os.environ.copy()
        env["OPENCLAW_VIDEOMEMORY_REGISTRY_PATH"] = str(self.registry_path)
        env["OPENCLAW_SESSION_STORE_PATH"] = str(self.session_store_path)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["node", str(HELPER_PATH), *args, "--base-url", self.base_url],
            check=check,
            capture_output=True,
            text=True,
            env=env,
        )

    def _run_helper(self, *args, extra_env=None):
        result = self._run_helper_raw(*args, extra_env=extra_env)
        return json.loads(result.stdout)

    def test_create_defaults_original_request_to_trigger_and_action_context(self):
        response = self._run_helper(
            "create",
            "--io-id",
            "net0",
            "--trigger",
            "Watch for a glass of water in the frame.",
            "--action",
            "Search the web for \"hello\" and tell the user the first search result when the glass of water is visible.",
            "--delivery",
            "session",
            "--session-key",
            "agent:main:main",
        )

        self.assertEqual(response["status"], "success")
        registry = json.loads(self.registry_path.read_text())
        entry = registry["tasks"]["openclaw|net0|3"]
        self.assertEqual(
            entry["original_request"],
            'Trigger condition: Watch for a glass of water in the frame.\n'
            'Follow-up action: Search the web for "hello" and tell the user the first search result when the glass of water is visible.',
        )

    def test_update_replaces_stale_original_request_when_action_changes(self):
        self.registry_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": {
                        "openclaw|net0|3": {
                            "task_id": "3",
                            "io_id": "net0",
                            "bot_id": "openclaw",
                            "task_description": "Watch for a glass of water in the frame.",
                            "trigger_condition": "Watch for a glass of water in the frame.",
                            "action_instruction": "Notify the user when a glass of water appears.",
                            "delivery_mode": "session",
                            "delivery_source": "webchat",
                            "delivery_sender_id": "",
                            "delivery_target": "",
                            "delivery_session_key": "agent:main:main",
                            "original_request": "Tell me when you see a glass of water",
                            "created_at": "2026-04-03T22:47:34.841Z",
                            "updated_at": "2026-04-03T22:47:34.841Z",
                        }
                    },
                },
                indent=2,
            )
            + "\n"
        )

        response = self._run_helper(
            "update",
            "--task-id",
            "3",
            "--trigger",
            "Watch for a glass of water in the frame. Add a note only when it appears or disappears.",
            "--action",
            "Search the web for \"hello\" and tell the user the first search result when the glass of water is visible.",
            "--delivery",
            "session",
            "--session-key",
            "agent:main:main",
        )

        self.assertEqual(response["status"], "success")
        registry = json.loads(self.registry_path.read_text())
        entry = registry["tasks"]["openclaw|net0|3"]
        self.assertEqual(
            entry["original_request"],
            'Trigger condition: Watch for a glass of water in the frame. Add a note only when it appears or disappears.\n'
            'Follow-up action: Search the web for "hello" and tell the user the first search result when the glass of water is visible.',
        )
        self.assertEqual(entry["action_instruction"], 'Search the web for "hello" and tell the user the first search result when the glass of water is visible.')

    def test_create_with_include_video_requests_saved_evidence(self):
        response = self._run_helper(
            "create",
            "--io-id",
            "net0",
            "--trigger",
            "Watch for a person waving.",
            "--action",
            "Send me the exact saved triggering clip.",
            "--include-frame",
            "true",
            "--include-video",
            "true",
            "--delivery",
            "session",
            "--session-key",
            "agent:main:main",
        )

        self.assertEqual(response["status"], "success")
        method, path, payload = self.server.requests[0]
        self.assertEqual((method, path), ("POST", "/api/tasks"))
        self.assertTrue(payload["save_note_frames"])
        self.assertTrue(payload["save_note_videos"])

        registry = json.loads(self.registry_path.read_text())
        entry = registry["tasks"]["openclaw|net0|3"]
        self.assertTrue(entry["include_note_frame"])
        self.assertTrue(entry["include_note_video"])

    def test_update_with_explicit_media_flags_updates_task_preferences(self):
        self.registry_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": {
                        "openclaw|net0|3": {
                            "task_id": "3",
                            "io_id": "net0",
                            "bot_id": "openclaw",
                            "task_description": "Watch for a person waving.",
                            "trigger_condition": "Watch for a person waving.",
                            "action_instruction": "Send me the exact saved triggering clip.",
                            "delivery_mode": "session",
                            "delivery_source": "webchat",
                            "delivery_sender_id": "",
                            "delivery_target": "",
                            "delivery_session_key": "agent:main:main",
                            "include_note_frame": True,
                            "include_note_video": True,
                            "original_request": "Send me the saved clip when I wave.",
                            "created_at": "2026-04-03T22:47:34.841Z",
                            "updated_at": "2026-04-03T22:47:34.841Z"
                        }
                    },
                },
                indent=2,
            )
            + "\n"
        )

        response = self._run_helper(
            "update",
            "--task-id",
            "3",
            "--trigger",
            "Watch for a person waving only when the hand first comes up.",
            "--action",
            "Send me the exact saved triggering frame.",
            "--include-frame",
            "true",
            "--include-video",
            "false",
            "--delivery",
            "session",
            "--session-key",
            "agent:main:main",
        )

        self.assertEqual(response["status"], "success")
        self.assertIn(("GET", "/api/task/3", None), self.server.requests)
        put_requests = [req for req in self.server.requests if req[0] == "PUT"]
        self.assertEqual(len(put_requests), 1)
        self.assertTrue(put_requests[0][2]["save_note_frames"])
        self.assertFalse(put_requests[0][2]["save_note_videos"])

        registry = json.loads(self.registry_path.read_text())
        entry = registry["tasks"]["openclaw|net0|3"]
        self.assertTrue(entry["include_note_frame"])
        self.assertFalse(entry["include_note_video"])

    def test_create_telegram_delivery_only_needs_target_chat_id(self):
        response = self._run_helper(
            "create",
            "--io-id",
            "net0",
            "--trigger",
            "Watch for a person in the frame.",
            "--action",
            "Tell Mark when a person is visible.",
            "--delivery",
            "telegram",
            "--to",
            "7248025749",
        )

        self.assertEqual(response["status"], "success")
        registry = json.loads(self.registry_path.read_text())
        entry = registry["tasks"]["openclaw|net0|3"]
        self.assertEqual(entry["delivery_mode"], "telegram")
        self.assertEqual(entry["delivery_target"], "7248025749")

    def test_create_session_delivery_without_real_session_key_fails(self):
        result = self._run_helper_raw(
            "create",
            "--io-id",
            "net0",
            "--trigger",
            "Watch for a person in the frame.",
            "--action",
            "Tell me when a person is visible.",
            "--delivery",
            "session",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stderr)
        self.assertIn("actual originating chat session key", payload["error"])

    def test_create_rejects_heartbeat_owned_main_session_key(self):
        self.session_store_path.write_text(
            json.dumps(
                {
                    "agent:main:main": {
                        "origin": {
                            "provider": "heartbeat",
                        }
                    }
                }
            )
            + "\n"
        )

        result = self._run_helper_raw(
            "create",
            "--io-id",
            "net0",
            "--trigger",
            "Watch for a person in the frame.",
            "--action",
            "Tell me when a person is visible.",
            "--delivery",
            "session",
            "--session-key",
            "agent:main:main",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stderr)
        self.assertIn("heartbeat/internal session", payload["error"])


if __name__ == "__main__":
    unittest.main()
