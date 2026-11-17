"""Near misses from recorded pre-filter reasons."""
import contextlib
import datetime
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_core import Base


class NearMiss(Base):
    def setUp(self):
        super().setUp()
        targets = {"max_years_required": 5, "tracks": [
            {"id": "data", "title_include": ["data analyst"]},
            {"id": "water", "title_include": ["water engineer"]}]}
        (self.d / "targets.json").write_text(json.dumps(targets), encoding="utf-8")

    def setUp(self):
        super().setUp()
        self.targets = {"max_years_required": 5, "exclude_title": ["manager"],
                        "tracks": [{"id": "data", "title_include": ["data analyst"]},
                                   {"id": "water", "title_include": ["water engineer"]}]}
        (self.d / "targets.json").write_text(json.dumps(self.targets), encoding="utf-8")

    def add(self, n, title, reason, day=None, verdict="rejected", location="Sydney"):
        from jobdb import connect, record_seen
        record_seen("ana", [{"key": f"seek:{n}", "title": title, "company": "Co", "platform": "seek", "url": "u",
                             "location": location}], day or datetime.date.today().isoformat())
        with connect("ana") as con:
            con.execute("UPDATE jobs SET verdict=?, reason=?, description=? WHERE key=?",
                        (verdict, reason, "SECRET DESCRIPTION", f"seek:{n}"))

    def test_years_window_current_limit_and_hard_rejects(self):
        import nearmiss
        for n in range(6, 9):
            self.add(n, f"Role {n}", f"requires {n}+ years (max 4)")
        self.add(10, "Old", "requires 6+ years (max 5)",
                 (datetime.date.today() - datetime.timedelta(days=15)).isoformat())
        self.add(11, "Boundary", "requires 6+ years (max 5)",
                 (datetime.date.today() - datetime.timedelta(days=14)).isoformat())
        for n, reason in enumerate(("twin ad requires 6+ years (max 5)", "company excluded ('Co')",
                                    "requirement excluded ('clearance')"), 20):
            self.add(n, "Data scientist", reason)
        r = nearmiss.nearmiss("ana")
        self.assertEqual([x["years"] for x in r["years"]], [6, 6, 7])
        self.assertEqual(r["no_track"], [])
        self.assertNotIn("SECRET", json.dumps(r))

    def test_partial_whole_words_grouping_and_examples(self):
        import nearmiss
        reason = nearmiss.NO_TRACK
        for n in range(4):
            self.add(n, "DATA Scientist " + chr(65 + n), reason)
        self.add(8, "Database administrator", reason)
        self.add(9, "Senior consultant", reason)
        self.add(10, "Water modeller", reason + " (not read: daily reading budget)")
        self.add(11, "Data scientist", reason, verdict="shortlisted")
        rows = nearmiss.nearmiss("ana")["no_track"]
        self.assertEqual(rows[0]["phrase"], "data scientist")
        self.assertEqual((rows[0]["count"], rows[0]["track"], len(rows[0]["examples"])), (4, "data", 3))
        self.assertEqual(rows[1]["phrase"], "water modeller")
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(nearmiss.nearmiss("ana", top=1)["no_track"]), 1)
        self.assertEqual(nearmiss.suggestions("Data analyst", [{"id": "data", "title_include": ["data analyst"]},
                                                          {"id": "water", "title_include": ["water engineer"]}])[1], [])

    def test_exclusion_and_location_counts(self):
        import nearmiss
        self.add(1, "Manager A", "seniority/title excluded ('Manager')")
        self.add(2, "Manager B", "seniority/title excluded ('MANAGER')")
        self.add(3, "Role", "location 'Sydney'")
        self.add(4, "Twin", "twin ad location 'Sydney'")
        r = nearmiss.nearmiss("ana")
        self.assertEqual(r["exclusions"], [{"word": "manager", "count": 2, "examples": ["Manager A", "Manager B"]}])
        self.assertEqual(r["locations"][0]["count"], 1)
        self.assertEqual(nearmiss.summary_lines("ana"), [])

    def test_read_only_missing_db_cli_and_summary(self):
        import nearmiss
        self.assertEqual(nearmiss.summary_lines("ana"), [])
        self.assertFalse((self.d / "jobs.db").exists())
        self.add(1, "Data scientist", nearmiss.NO_TRACK)
        self.add(2, "Analyst", "requires 6+ years (max 5)")
        before = (self.d / "jobs.db").read_bytes()
        with patch.object(sys, "argv", ["nearmiss", "ana", "--json", "--top", "1"]), contextlib.redirect_stdout(io.StringIO()) as buf:
            nearmiss.main()
        self.assertEqual(json.loads(buf.getvalue())["years"][0]["years"], 6)
        self.assertEqual((self.d / "jobs.db").read_bytes(), before)
        self.assertEqual(len(nearmiss.summary_lines("ana")), 2)
        self.assertIn("No track matched", nearmiss.table(nearmiss.nearmiss("ana")))
        self.assertNotIn("SECRET", nearmiss.table(nearmiss.nearmiss("ana")))

    def test_report_monday_and_failure_guard(self):
        import report
        with patch("nearmiss.summary_lines", return_value=["Advice"]) as summary:
            self.assertIn("Advice", report.build("ana", "2026-11-16"))
            summary.assert_called_once_with("ana")
            summary.reset_mock()
            self.assertNotIn("Advice", report.build("ana", "2026-11-17"))
            summary.assert_not_called()
        with patch("nearmiss.summary_lines", side_effect=RuntimeError("bad")):
            self.assertIn("Daily report", report.build("ana", "2026-11-16"))


if __name__ == "__main__":
    unittest.main()
