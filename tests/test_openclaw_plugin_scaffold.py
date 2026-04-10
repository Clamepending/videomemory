import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "openclaw-plugin"
MARKETPLACE_SKILL = REPO_ROOT / "clawhub-skill" / "videomemory" / "SKILL.md"


class OpenClawPluginScaffoldTests(unittest.TestCase):
    def test_package_json_references_existing_entrypoints(self):
        package = json.loads((PLUGIN_ROOT / "package.json").read_text())
        openclaw = package["openclaw"]

        for relative_path in openclaw["extensions"]:
            self.assertTrue((PLUGIN_ROOT / relative_path).exists(), relative_path)

        self.assertTrue((PLUGIN_ROOT / openclaw["setupEntry"]).exists())
        self.assertIn("bin", package)
        for relative_path in package["bin"].values():
            self.assertTrue((PLUGIN_ROOT / relative_path).exists(), relative_path)

    def test_manifest_references_existing_skill_root(self):
        manifest = json.loads((PLUGIN_ROOT / "openclaw.plugin.json").read_text())
        self.assertEqual(manifest["id"], "videomemory")

        for relative_path in manifest["skills"]:
            self.assertTrue((PLUGIN_ROOT / relative_path).exists(), relative_path)

        self.assertIn("configSchema", manifest)

    def test_bundled_assets_exist(self):
        self.assertTrue((PLUGIN_ROOT / "skills" / "videomemory" / "SKILL.md").exists())
        self.assertTrue((PLUGIN_ROOT / "bin" / "openclaw-videomemory-task-helper.mjs").exists())
        self.assertTrue((PLUGIN_ROOT / "transforms" / "videomemory-alert.mjs").exists())
        self.assertTrue(MARKETPLACE_SKILL.exists())

    def test_marketplace_skill_installs_the_package_cli(self):
        skill_text = MARKETPLACE_SKILL.read_text()
        self.assertIn('"package":"@clamepending/videomemory"', skill_text)
        self.assertIn('"bins":["videomemory-openclaw"]', skill_text)
        self.assertIn("videomemory-openclaw onboard", skill_text)


if __name__ == "__main__":
    unittest.main()
