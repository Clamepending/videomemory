import json
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "openclaw-plugin"
MARKETPLACE_SKILL = REPO_ROOT / "clawhub-skill" / "videomemory" / "SKILL.md"


class OpenClawPackageScaffoldTests(unittest.TestCase):
    def test_package_json_exposes_openclaw_artifacts(self):
        package = json.loads((PLUGIN_ROOT / "package.json").read_text())

        self.assertIn("bin", package)
        for relative_path in package["bin"].values():
            self.assertTrue((PLUGIN_ROOT / relative_path).exists(), relative_path)
        self.assertIn("openclaw", package)
        self.assertIn("./index.mjs", package["openclaw"]["extensions"])
        self.assertIn("./hooks/videomemory-startup", package["openclaw"]["hooks"])
        self.assertEqual(package["openclaw"]["compat"]["pluginApi"], ">=2026.2.2-0 <2027.0.0")
        self.assertEqual(package["name"], "@clamepending/videomemory")

    def test_package_files_include_plugin_runtime_assets(self):
        package = json.loads((PLUGIN_ROOT / "package.json").read_text())
        packaged = set(package["files"])
        self.assertEqual(packaged, {"README.md", "bundled", "cli.mjs", "hooks", "index.mjs", "openclaw.plugin.json", "skills", "src"})
        self.assertTrue((PLUGIN_ROOT / "openclaw.plugin.json").exists())
        self.assertTrue(MARKETPLACE_SKILL.exists())

    def test_package_runs_bundled_scripts_instead_of_remote_main(self):
        shared = (PLUGIN_ROOT / "src" / "shared.mjs").read_text()
        self.assertIn("SCRIPT_PATHS", shared)
        self.assertIn("bundled", shared)
        self.assertNotIn("raw.githubusercontent.com", shared)

    def test_bundled_scripts_match_repo_sources(self):
        script_pairs = [
            ("docs/openclaw-bootstrap.sh", "bundled/openclaw-bootstrap.sh"),
            ("docs/relaunch-videomemory.sh", "bundled/relaunch-videomemory.sh"),
        ]
        for source, bundled in script_pairs:
            self.assertEqual(
                (REPO_ROOT / source).read_text(),
                (PLUGIN_ROOT / bundled).read_text(),
                bundled,
            )

    def test_marketplace_skill_uses_published_cli(self):
        skill_text = MARKETPLACE_SKILL.read_text()
        self.assertIn('"emoji":"camera"', skill_text)
        self.assertNotIn('"package"', skill_text)
        self.assertNotIn('"bins"', skill_text)
        self.assertNotIn('"requires"', skill_text)
        self.assertIn("openclaw plugins install @clamepending/videomemory@0.1.5", skill_text)
        self.assertIn("npx -y @clamepending/videomemory@0.1.5 onboard --safe", skill_text)
        self.assertIn("npx -y @clamepending/videomemory@0.1.5 relaunch", skill_text)
        self.assertNotIn("npm install", skill_text)
        self.assertIn("--explain", skill_text)
        self.assertIn("send me the UI", skill_text)

    def test_marketplace_skill_is_instruction_only(self):
        scripts_dir = MARKETPLACE_SKILL.parent / "scripts"
        self.assertFalse(any(scripts_dir.glob("*")))

    def test_cli_can_explain_safe_onboarding_without_changes(self):
        result = subprocess.run(
            [
                "node",
                str(PLUGIN_ROOT / "cli.mjs"),
                "onboard",
                "--safe",
                "--repo-ref",
                "v-test",
                "--explain",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("Mode: safe", result.stdout)
        self.assertIn("Will not copy model provider API keys", result.stdout)
        self.assertIn("Will not install or configure Tailscale", result.stdout)
        self.assertIn("No changes were made", result.stdout)


if __name__ == "__main__":
    unittest.main()
