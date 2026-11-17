"""Plural title exclusions and portal apply flags."""
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


class TestExclusions(unittest.TestCase):
    def test_plural_words(self):
        from triage import xrx
        for word, title in (("manager", "Project Managers"), ("director", "Directors"),
                            ("partner", "Partners"), ("head", "Heads"),
                            ("truck driver", "Truck Drivers"), ("boss", "Bosses"),
                            ("graduate program 2025", "Graduate Program 2025")):
            with self.subTest(title=title):
                self.assertIsNotNone(xrx([word]).search(title))
                self.assertIsNotNone(xrx([word]).search(word))
        for word, title in (("partner", "Partnership"), ("head", "Header"), ("head", "Headland"),
                            ("manager", "Management"), ("truck driver", "Truck Drivership"),
                            ("graduate program 2025", "Graduate Program 2025s")):
            with self.subTest(title=title):
                self.assertIsNone(xrx([word]).search(title))
        self.assertIsNone(xrx([]))

    def test_other_matchers_unchanged(self):
        from triage import rx, judge
        self.assertIsNone(rx(["manager"]).search("Managers"))
        targets = {"exclude_text": ["citizen"], "tracks": [{"id": "a", "title_include": ["officer"]}]}
        self.assertEqual(judge({"title": "Officer", "description": "citizens"}, targets), ("a", "ok"))

    def test_global_and_track_exclusions(self):
        from triage import assign_track, by_description_possible, judge
        track = {"id": "a", "title_include": ["project"], "exclude_title": ["manager"],
                 "description_include": {"words": ["python"], "min": 1}}
        self.assertIsNone(assign_track("Project Managers", [track], "python"))
        self.assertIsNone(assign_track("Managers", [track], "python"))
        self.assertFalse(by_description_possible("Managers", {"tracks": [track]}))
        self.assertEqual(assign_track("Project Officer", [track]), "a")
        targets = {"exclude_title": ["director"], "tracks": [track]}
        self.assertIn("excluded", judge({"title": "Project Directors"}, targets)[1])


class TestEasyApply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"JOB_CANDIDATES_DIR": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        (Path(self.tmp.name) / "ana").mkdir()

    def test_route_updates_and_sightings_preserve_true(self):
        from applyroute import record
        from jobdb import connect, record_seen
        job = {"key": "seek:1", "platform": "seek", "title": "Officer"}
        record_seen("ana", [job], date.today().isoformat())
        record("ana", job["key"], "quick")
        with connect("ana", readonly=True) as con:
            self.assertEqual(con.execute("SELECT easy_apply FROM jobs").fetchone()[0], "True")
        record("ana", job["key"], "external")
        record_seen("ana", [dict(job, easy_apply=False)], date.today().isoformat())
        with connect("ana", readonly=True) as con:
            self.assertEqual(con.execute("SELECT easy_apply FROM jobs").fetchone()[0], "True")

    def test_rebuilt_jobs_have_boolean_flags(self):
        from jobdb import connect, record_seen, rejudge_candidates
        from applyroute import record
        jobs = [{"key": "seek:1"}, {"key": "linkedin:2", "easy_apply": True},
                {"key": "seek:3", "easy_apply": False}]
        record_seen("ana", jobs, date.today().isoformat())
        record("ana", "seek:1", "quick")
        with connect("ana") as con:
            con.execute("UPDATE jobs SET verdict='rejected', reason='title', judged_with='old'")
        got = {j["key"]: j for j in rejudge_candidates("ana", {}, 14)}
        self.assertIs(got["seek:1"]["easy_apply"], True)
        self.assertEqual(got["seek:1"]["apply_route"], "quick")
        self.assertIs(got["linkedin:2"]["easy_apply"], True)
        self.assertIs(got["seek:3"]["easy_apply"], False)

    def test_known_route_on_sighting(self):
        from jobdb import connect, record_seen, restore_routes
        job = {"key": "seek:1", "apply_route": "quick", "easy_apply": False}
        record_seen("ana", [job], date.today().isoformat())
        with connect("ana", readonly=True) as con:
            row = con.execute("SELECT apply_route, easy_apply FROM jobs").fetchone()
            self.assertEqual(tuple(row), ("quick", "True"))
        restore_routes("ana", [job])
        self.assertIs(job["easy_apply"], True)

    def test_prepare_manifest_restores_quick_route(self):
        from applyroute import record
        from jobdb import record_seen
        from prepare import build_one
        base = Path(self.tmp.name) / "ana"
        (base / "letter.json").write_text("{}", encoding="utf-8")
        (base / "cv.pdf").write_bytes(b"cv")
        pkg = base / "package"
        pkg.mkdir()
        job = {"key": "seek:1", "title": "Officer", "platform": "seek", "track": "a", "url": "url"}
        record_seen("ana", [job], date.today().isoformat())
        record("ana", job["key"], "quick")
        targets = {"tracks": [{"id": "a", "letter": "letter.json", "cv_pdf": "cv.pdf"}]}
        with patch.multiple("prepare", fill_letter=lambda *a: {}, build=lambda *a: {"ok": True, "pdf": "letter.pdf"},
                            set_status=lambda *a, **k: None, check_job=lambda *a: [], set_flags=lambda *a: None,
                            notes_for=lambda *a: {}, extract_text=lambda *a: ""):
            item = build_one("ana", targets, pkg, 1, 50, [], {}, job, "Ana", {job["key"]: {}})
        self.assertIs(item["easy_apply"], True)
        self.assertEqual(job["apply_route"], "quick")

    def test_shortlist_known_and_detected_routes(self):
        from applyroute import record
        from jobdb import record_seen
        from triage import record_routes
        jobs = [{"key": "seek:1", "platform": "seek", "id": "1"},
                {"key": "seek:2", "platform": "seek", "id": "2"},
                {"key": "linkedin:3", "platform": "linkedin", "id": "3", "easy_apply": True}]
        record_seen("ana", jobs, date.today().isoformat())
        record("ana", "seek:1", "quick")
        with patch("applyroute.detect", return_value=("quick", "")):
            record_routes("ana", jobs)
        for job in jobs:
            self.assertIs(job["easy_apply"], True)
            self.assertEqual(job["apply_route"], "quick")


if __name__ == "__main__":
    unittest.main()
