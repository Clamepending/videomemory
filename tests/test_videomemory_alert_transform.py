import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


TRANSFORM_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "openclaw-real-home"
    / "hooks"
    / "transforms"
    / "videomemory-alert.mjs"
)


class VideoMemoryAlertTransformTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        temp_path = Path(self.tempdir.name)
        self.hooks_dir = temp_path / "hooks"
        self.transforms_dir = self.hooks_dir / "transforms"
        self.state_dir = self.hooks_dir / "state"
        self.transforms_dir.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)
        self.transform_copy = self.transforms_dir / "videomemory-alert.mjs"
        shutil.copy2(TRANSFORM_PATH, self.transform_copy)
        self.registry_path = self.state_dir / "videomemory-task-actions.json"
        self.session_store_path = temp_path / "sessions.json"
        self.session_store_path.write_text("{}\n", encoding="utf-8")

    def tearDown(self):
        self.tempdir.cleanup()

    def _write_registry(self, entry, *, bot_id="openclaw", io_id="0", task_id="0"):
        registry = {
            "version": 1,
            "tasks": {
                f"{bot_id}|{io_id}|{task_id}": entry,
            },
        }
        self.registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    def _run_transform(self, payload):
        script = """
const modulePath = process.argv[1];
const payload = JSON.parse(process.argv[2]);
const { default: transform } = await import(modulePath);
const result = await transform({ payload });
console.log(JSON.stringify(result));
""".strip()
        env = os.environ.copy()
        env["OPENCLAW_SESSION_STORE_PATH"] = str(self.session_store_path)
        result = subprocess.run(
            [
                "node",
                "--input-type=module",
                "-e",
                script,
                self.transform_copy.resolve().as_uri(),
                json.dumps(payload),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        return json.loads(result.stdout)

    def test_registry_driven_telegram_delivery_uses_external_user_prompt(self):
        self._write_registry(
            {
                "task_id": "0",
                "io_id": "0",
                "bot_id": "openclaw",
                "task_description": "Let me know when someone appears.",
                "trigger_condition": "Watch for a person appearing in the frame.",
                "action_instruction": "Tell me right away when someone is visible.",
                "delivery_mode": "telegram",
                "delivery_source": "telegram",
                "delivery_sender_id": "7248025749",
                "delivery_target": "7248025749",
                "delivery_session_key": "",
                "include_note_frame": False,
                "include_note_video": False,
                "original_request": "Use VideoMemory and let me know every time a person appears.",
            }
        )

        result = self._run_transform(
            {
                "event_id": "vm-test-1",
                "bot_id": "openclaw",
                "io_id": "0",
                "task_id": "0",
                "task_description": "Let me know when someone appears.",
                "note": "1 person is visible in the frame.",
            }
        )

        self.assertEqual(result["kind"], "agent")
        self.assertTrue(result["deliver"])
        self.assertEqual(result["channel"], "telegram")
        self.assertEqual(result["to"], "7248025749")
        self.assertNotIn("sessionKey", result)
        self.assertIn("Your reply will be delivered to the end user automatically.", result["message"])
        self.assertIn(
            "If the trigger condition is satisfied now, reply with exactly one short user-facing alert sentence and nothing else.",
            result["message"],
        )
        self.assertIn(
            "Do not mention Telegram, chat routing, tools, internal context, or that delivery is automatic.",
            result["message"],
        )
        self.assertNotIn("complete the requested action for the user", result["message"])

    def test_registry_driven_session_delivery_omits_heartbeat_owned_session_key(self):
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
            + "\n",
            encoding="utf-8",
        )
        self._write_registry(
            {
                "task_id": "0",
                "io_id": "0",
                "bot_id": "openclaw",
                "task_description": "Let me know when someone appears.",
                "trigger_condition": "Watch for a person appearing in the frame.",
                "action_instruction": "Tell me right away when someone is visible.",
                "delivery_mode": "session",
                "delivery_source": "webchat",
                "delivery_sender_id": "",
                "delivery_target": "",
                "delivery_session_key": "agent:main:main",
                "include_note_frame": False,
                "include_note_video": False,
                "original_request": "Use VideoMemory and tell me here every time a person appears.",
            }
        )

        result = self._run_transform(
            {
                "event_id": "vm-test-2",
                "bot_id": "openclaw",
                "io_id": "0",
                "task_id": "0",
                "task_description": "Let me know when someone appears.",
                "note": "1 person is visible in the frame.",
            }
        )

        self.assertEqual(result["kind"], "agent")
        self.assertFalse(result["deliver"])
        self.assertNotIn("sessionKey", result)


if __name__ == "__main__":
    unittest.main()
