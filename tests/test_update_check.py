import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import flask_app.app as app_module
from videomemory.system.update_check import build_update_payload, compare_versions


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def _write_test_repo(self, current_version: str) -> tempfile.TemporaryDirectory:
        temp_dir = tempfile.TemporaryDirectory()
        repo_root = Path(temp_dir.name)
        repo_root.joinpath("pyproject.toml").write_text(
            f'[project]\nname = "videomemory"\nversion = "{current_version}"\n',
            encoding="utf-8",
        )
        return temp_dir

    def _write_manifest(self, directory: str, latest_version: str) -> Path:
        manifest_path = Path(directory) / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "latest_version": latest_version,
                    "latest_git_ref": f"v{latest_version}",
                    "release_notes_url": f"https://example.test/v{latest_version}",
                    "update_command": (
                        f"npx -y @clamepending/videomemory relaunch --repo-ref v{latest_version}"
                    ),
                }
            ),
            encoding="utf-8",
        )
        return manifest_path

    def test_compare_versions_handles_multi_digit_patch_versions(self):
        self.assertEqual(compare_versions("0.1.9", "0.1.10"), -1)
        self.assertEqual(compare_versions("v0.1.10", "0.1.10"), 0)
        self.assertEqual(compare_versions("0.2.0", "0.1.10"), 1)

    def test_build_update_payload_detects_available_update_from_local_manifest(self):
        temp_repo = self._write_test_repo("0.1.0")
        self.addCleanup(temp_repo.cleanup)
        manifest_path = self._write_manifest(temp_repo.name, "0.1.1")

        payload = build_update_payload(Path(temp_repo.name), manifest_url=str(manifest_path))

        self.assertEqual(payload["current_version"], "0.1.0")
        self.assertEqual(payload["latest_version"], "0.1.1")
        self.assertTrue(payload["update_available"])
        self.assertEqual(payload["check_error"], "")

    def test_build_update_payload_returns_no_update_for_current_version(self):
        temp_repo = self._write_test_repo("0.1.1")
        self.addCleanup(temp_repo.cleanup)
        manifest_path = self._write_manifest(temp_repo.name, "0.1.1")

        payload = build_update_payload(Path(temp_repo.name), manifest_url=str(manifest_path))

        self.assertEqual(payload["current_version"], "0.1.1")
        self.assertEqual(payload["latest_version"], "0.1.1")
        self.assertFalse(payload["update_available"])

    def test_version_endpoint_uses_manifest_override_and_force_refresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = self._write_manifest(temp_dir, "9.9.9")
            with patch.dict(
                os.environ,
                {"VIDEOMEMORY_UPDATE_MANIFEST_URL": str(manifest_path)},
                clear=False,
            ):
                resp = self.client.get("/api/version?refresh=1")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["latest_version"], "9.9.9")
        self.assertTrue(body["update_available"])
        self.assertIn("npx -y @clamepending/videomemory relaunch", body["update_command"])

    def test_version_endpoint_can_be_disabled(self):
        with patch.dict(os.environ, {"VIDEOMEMORY_UPDATE_CHECK_DISABLED": "1"}, clear=False):
            resp = self.client.get("/api/version?refresh=1")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["update_check_disabled"])
        self.assertIsNone(body["update_available"])
        self.assertEqual(body["check_error"], "update check disabled")


if __name__ == "__main__":
    unittest.main()
