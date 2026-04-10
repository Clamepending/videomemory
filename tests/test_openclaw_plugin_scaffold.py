import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "openclaw-plugin"
MARKETPLACE_SKILL = REPO_ROOT / "clawhub-skill" / "videomemory" / "SKILL.md"


class OpenClawPackageScaffoldTests(unittest.TestCase):
    def test_package_json_exposes_only_the_cli_artifact(self):
        package = json.loads((PLUGIN_ROOT / "package.json").read_text())

        self.assertIn("bin", package)
        for relative_path in package["bin"].values():
            self.assertTrue((PLUGIN_ROOT / relative_path).exists(), relative_path)
        self.assertNotIn("openclaw", package)
        self.assertEqual(package["name"], "@clamepending/videomemory")

    def test_package_files_exclude_plugin_runtime_assets(self):
        package = json.loads((PLUGIN_ROOT / "package.json").read_text())
        packaged = set(package["files"])
        self.assertEqual(packaged, {"README.md", "cli.mjs", "src"})
        self.assertFalse((PLUGIN_ROOT / "openclaw.plugin.json").exists())
        self.assertTrue(MARKETPLACE_SKILL.exists())

    def test_marketplace_skill_installs_the_package_cli(self):
        skill_text = MARKETPLACE_SKILL.read_text()
        self.assertIn('"package":"@clamepending/videomemory"', skill_text)
        self.assertIn('"bins":["videomemory-openclaw"]', skill_text)
        self.assertIn("videomemory-openclaw onboard", skill_text)
        self.assertIn("host CLI", skill_text)


if __name__ == "__main__":
    unittest.main()
