"""targets_check: the linter flags phrases triage/prepare would never let through or always penalise."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import targets_check  # noqa: E402
from targets_check import check_targets  # noqa: E402


def found(t, level, base=None, **kw):
    return [f for f in check_targets(t, base, **kw) if f["level"] == level]


def T(*tracks, **top):
    return {"tracks": [{"id": i, "title_include": p, **extra} for i, p, extra in tracks], **top}


class TestPhrases(unittest.TestCase):
    def test_excluded_phrase_is_error(self):
        t = T(("a", ["senior engineer", "data analyst"], {"exclude_title": ["analyst"]}), exclude_title=["senior"])
        e = found(t, "error")
        self.assertEqual({(f["track"], f["phrase"]) for f in e}, {("a", "senior engineer"), ("a", "data analyst")})
        self.assertIn("global", [f for f in e if f["phrase"] == "senior engineer"][0]["msg"])
        self.assertIn("track's", [f for f in e if f["phrase"] == "data analyst"][0]["msg"])

    def test_clean_targets_have_no_findings(self):
        self.assertEqual(check_targets(T(("a", ["gis analyst"], {}), ("b", ["water engineer"], {}))), [])

    def test_penalised_phrase_says_the_penalty(self):
        t = T(("env", ["botanist", "hygiene", "chartered engineer", "ecologist", "scientist"], {}),
              ranking={"off_field": ["botanist", "hygien"], "missing_credentials": ["chartered"],
                       "deprioritize": {"terms": ["ecologist"], "points": 5}})
        w = {f["phrase"]: f["msg"] for f in found(t, "warn")}
        self.assertEqual(set(w), {"botanist", "hygiene", "chartered engineer", "ecologist"})
        self.assertIn("-18", w["botanist"]); self.assertIn("-8", w["chartered engineer"]); self.assertIn("-5", w["ecologist"])

    def test_shadowed_phrase_and_info_when_excluded(self):
        t = T(("ai", ["ml engineer"], {}), ("data", ["ml engineer", "data analyst"], {}))
        w = found(t, "warn")
        self.assertEqual([(f["track"], f["phrase"]) for f in w], [("data", "ml engineer")])
        t["tracks"][0]["exclude_title"] = ["ml"]
        self.assertEqual(found(t, "warn"), [])
        self.assertEqual([(f["track"], f["phrase"]) for f in found(t, "info")], [("data", "ml engineer")])

    def test_duplicates(self):
        t = T(("a", ["gis analyst", "GIS Analyst"], {}), ("a", ["x person"], {}))
        self.assertEqual([f["phrase"] for f in found(t, "warn")], ["gis analyst"])
        self.assertEqual([f["track"] for f in found(t, "error")], ["a"])


class TestFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_missing_cv_and_letter(self):
        (self.tmp / "docs").mkdir()
        (self.tmp / "docs/cv.json").write_text("{}")
        t = T(("a", ["gis analyst"], {"cv": "docs/cv.json", "letter": "docs/letter.json"}))
        e = found(t, "error", self.tmp)
        self.assertEqual(len(e), 1); self.assertIn("letter", e[0]["msg"])

    def test_priority(self):
        t = T(("a", ["x one"], {"rank_adjust": 3}), ("b", ["y two"], {}), priority=["a", "zzz"])
        self.assertEqual([f["track"] for f in found(t, "error")], ["zzz"])
        msgs = {f["track"]: f["msg"] for f in found(t, "warn")}
        self.assertIn("rank_adjust", msgs["a"]); self.assertIn("missing from priority", msgs["b"])
        self.assertEqual(found(T(("a", ["x one"], {})), "warn"), [])         # no priority list: nothing to say

    def test_seek_cvs(self):
        t = T(("a", ["x one"], {}), ("b", ["y two"], {}))
        r = check_targets(t, seek={"_note": "n", "a": "a.pdf", "ghost": "g.pdf"})
        self.assertEqual([(f["level"], f["track"]) for f in r], [("error", "ghost"), ("warn", "b")])
        self.assertEqual([f["level"] for f in check_targets(t, seek=None, mode="easy")], ["warn"])
        self.assertEqual(check_targets(t, seek=None, mode="dry-run"), [])

    def test_unmatched_titles_grouped_per_track(self):
        t = T(("a", ["gis analyst", "cartograph", "water engineer"], {}))
        i = found(t, "info", seen_titles=["Senior GIS Analyst", "Cartographer"])
        self.assertEqual(len(i), 1)
        self.assertIn("water engineer", i[0]["msg"]); self.assertNotIn("cartograph;", i[0]["msg"])
        self.assertEqual(found(t, "info", seen_titles=None), [])


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        d = self.tmp / "ana"
        d.mkdir()
        (d / "targets.json").write_text(json.dumps(T(("a", ["gis analyst", "water engineer"], {}),
                                                     ("b", ["gis analyst"], {}))))
        (d / "state.json").write_text(json.dumps({"mode": "dry-run"}))
        con = sqlite3.connect(d / "jobs.db")
        con.execute("CREATE TABLE jobs (key TEXT, title TEXT, last_seen TEXT)")
        con.executemany("INSERT INTO jobs VALUES (?,?,?)", [
            ("1", "GIS Analyst", date.today().isoformat()),
            ("2", "Water Engineer", (date.today() - timedelta(days=90)).isoformat())])
        con.commit(); con.close()
        self.env = {**os.environ, "JOB_CANDIDATES_DIR": str(self.tmp)}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/targets_check.py"), *args], env=self.env,
                              capture_output=True, text=True)

    def test_json_with_and_without_check_word(self):
        for args in (("check", "ana", "--json"), ("ana", "--json")):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.loads(r.stdout)
            self.assertEqual(d["errors"], [])
            self.assertEqual([f["track"] for f in d["warnings"]], ["b"])      # shadowed
            self.assertIn("water engineer", d["info"][0]["msg"])              # only seen 90 days ago

    def test_exit_code_and_text(self):
        (self.tmp / "ana/targets.json").write_text(json.dumps(T(("a", ["x one"], {"cv": "nope.json"}))))
        r = self.run_cli("check", "ana")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.startswith("ERRORS (1)")); self.assertIn("1 errors", r.stdout)

    def test_never_writes(self):
        before = sorted(p.name for p in (self.tmp / "ana").iterdir())
        self.run_cli("check", "ana")
        self.assertEqual(before, sorted(p.name for p in (self.tmp / "ana").iterdir()))


if __name__ == "__main__":
    unittest.main()
