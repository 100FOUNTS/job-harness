"""Plugin packaging: manifests, data location (clone vs plugin), settings precedence and workspace scoping."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import common  # noqa: E402

CACHE = Path("/home/x/.claude/plugins/cache/100founts/job-harness/0.1.0")


def load(rel):
    return json.loads((ROOT / rel).read_text())


class TestManifests(unittest.TestCase):
    def test_plugin_json(self):
        p = load(".claude-plugin/plugin.json")
        for k in ("name", "version", "description", "author", "homepage", "repository", "license", "keywords"):
            self.assertTrue(p.get(k), k)
        self.assertEqual(p["name"], "job-harness")
        self.assertEqual(p["version"], common.HARNESS_VERSION)
        for s in p["skills"]:
            self.assertTrue(s.startswith("./") and (ROOT / s).is_dir(), s)
        listed = sorted(p["agents"])
        self.assertEqual(listed, sorted(f"./.claude/agents/{f.name}" for f in (ROOT / ".claude/agents").glob("*.md")))
        for a in listed:
            self.assertTrue((ROOT / a).is_file(), a)

    def test_hooks_match_settings(self):
        p, s = load(".claude-plugin/plugin.json")["hooks"], load(".claude/settings.json")["hooks"]
        self.assertEqual(p.keys(), s.keys())
        self.assertEqual(p["PreToolUse"][0]["matcher"], s["PreToolUse"][0]["matcher"])
        for ev in p:
            cmd = p[ev][0]["hooks"][0]["command"]
            self.assertIn('"${CLAUDE_PLUGIN_ROOT}/hooks/py.sh"', cmd)
            self.assertNotIn("CLAUDE_PROJECT_DIR", cmd)

    def test_marketplace_json(self):
        m = load(".claude-plugin/marketplace.json")
        self.assertTrue(m["name"] and m["owner"]["name"])
        (e,) = m["plugins"]
        self.assertEqual((e["name"], e["source"]), ("job-harness", "./"))
        self.assertEqual(e["version"], common.HARNESS_VERSION)

    def test_start_skill(self):
        t = (ROOT / ".claude/skills/job-start/SKILL.md").read_text()
        self.assertIn("name: job-start", t)
        for rule in ("Truthfulness", "Sealed approvals", "Dry-run by default", "Never delete"):
            self.assertIn(rule, t)


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        keys = ("JOB_DATA_DIR", "JOB_CANDIDATES_DIR", "JOB_PACKAGE_DIR")
        self.env = unittest.mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k not in keys}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        import shutil
        shutil.rmtree(self.tmp)

    def as_plugin(self):
        return unittest.mock.patch.object(common, "ROOT", CACHE)

    def home(self):
        return unittest.mock.patch.object(Path, "home", return_value=self.tmp)


class TestDataLocation(Env):
    def test_clone_paths_are_unchanged(self):
        self.assertFalse(common.plugin_mode())
        self.assertEqual(common.data_dir(), ROOT)
        self.assertEqual(common.candidates_dir(), ROOT / "candidates")
        self.assertEqual(common.browser_dir("ana"), ROOT / ".browser" / "ana")
        self.assertEqual(common.stop_file(), ROOT / "STOP")
        self.assertEqual(common.sponsors_file(), ROOT / "data" / "sponsors.json")
        os.environ["JOB_CANDIDATES_DIR"] = str(self.tmp)
        self.assertEqual(common.candidates_dir(), self.tmp)

    def test_plugin_paths_go_to_the_data_dir(self):
        with self.as_plugin(), self.home():
            self.assertTrue(common.plugin_mode())
            self.assertEqual(common.data_dir(), self.tmp / "job-harness-data")
            self.assertEqual(common.candidates_dir(), self.tmp / "job-harness-data" / "candidates")
            self.assertEqual(common.browser_dir("ana"), self.tmp / "job-harness-data" / ".browser" / "ana")
            self.assertEqual(common.stop_file(), self.tmp / "job-harness-data" / "STOP")
            self.assertEqual(common.learn_dir(), self.tmp / "job-harness-data" / "learn")
            os.environ["CLAUDE_PLUGIN_DATA"] = str(self.tmp / "ignored")   # Bash cannot see it: never part of the layout
            self.assertEqual(common.data_dir(), self.tmp / "job-harness-data")
            os.environ["JOB_DATA_DIR"] = str(self.tmp / "mine")
            self.assertEqual(common.candidates_dir(), self.tmp / "mine" / "candidates")

    def test_marketplace_checkout_counts_as_plugin(self):
        with unittest.mock.patch.object(common, "ROOT", Path("/h/.claude/plugins/marketplaces/100founts")):
            self.assertTrue(common.plugin_mode())
        with unittest.mock.patch.object(common, "ROOT", Path("/h/code/plugins/job-harness")):
            self.assertFalse(common.plugin_mode())

    def test_job_data_dir_in_a_clone(self):
        os.environ["JOB_DATA_DIR"] = str(self.tmp)
        self.assertEqual(common.candidates_dir(), self.tmp / "candidates")


class TestSetting(Env):
    def test_precedence(self):
        data, root = self.tmp / "data", self.tmp / "root"
        (root / ".claude").mkdir(parents=True)
        data.mkdir()
        (root / ".claude/settings.local.json").write_text(json.dumps({"env": {"JOB_X": "repo", "JOB_Y": "repo"}}))
        (data / "settings.json").write_text(json.dumps({"env": {"JOB_X": "data", "JOB_Z": "data"}}))
        os.environ["JOB_DATA_DIR"] = str(data)
        with unittest.mock.patch.object(common, "ROOT", root):
            self.assertEqual(common.setting("JOB_X", "d"), "data")      # data dir beats the repo's local settings
            self.assertEqual(common.setting("JOB_Y", "d"), "repo")
            self.assertEqual(common.setting("JOB_W", "d"), "d")
            os.environ["JOB_X"] = "env"
            self.assertEqual(common.setting("JOB_X", "d"), "env")       # environment beats both

    def test_clone_still_reads_local_settings(self):
        root = self.tmp / "root"
        (root / ".claude").mkdir(parents=True)
        (root / ".claude/settings.local.json").write_text(json.dumps({"env": {"JOB_X": "repo"}}))
        with unittest.mock.patch.object(common, "ROOT", root):
            self.assertEqual(common.setting("JOB_X", "d"), "repo")


class TestWorkspace(Env):
    def test_clone(self):
        self.assertTrue(common.workspace(ROOT))
        self.assertFalse(common.workspace(self.tmp))
        (self.tmp / ".job-harness").touch()
        self.assertFalse(common.workspace(self.tmp))   # the marker only matters for plugin installs

    def test_plugin(self):
        with self.as_plugin(), self.home():
            data = self.tmp / "job-harness-data"
            self.assertFalse(common.workspace(self.tmp))
            self.assertFalse(common.workspace(data))                       # not created yet
            data.mkdir()
            self.assertTrue(common.workspace(data))
            self.assertTrue(common.workspace(data / "candidates" / "ana"))
            other = self.tmp / "other"
            other.mkdir()
            self.assertFalse(common.workspace(other))                      # an unrelated project stays untouched
            (other / ".job-harness").touch()
            self.assertTrue(common.workspace(other))

    def test_init_creates_marker(self):
        os.environ["JOB_DATA_DIR"] = str(self.tmp / "d")
        import runpy
        with unittest.mock.patch.object(sys, "argv", ["common.py", "init"]), \
                unittest.mock.patch.object(common, "ROOT", CACHE), contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(ROOT / "scripts/common.py"), run_name="__main__")
        self.assertTrue((self.tmp / "d" / ".job-harness").exists())


if __name__ == "__main__":
    unittest.main()
