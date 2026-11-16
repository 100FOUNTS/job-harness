"""job gaps: terms the relevant ads ask for, counted across ads and checked against each track's master CV."""
import contextlib
import datetime
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_core import Base  # noqa: E402

TARGETS = {"exclude_title": [], "locations_include": [],
           "tracks": [{"id": "data", "primary": True, "title_include": ["data analyst"], "cv": "docs/cv_data.json",
                       "keywords": {"core": ["sql", "excel"], "support": ["reporting"]}},
                      {"id": "gis", "title_include": ["gis analyst"], "cv": "docs/cv_gis.json",
                       "keywords": {"core": ["arcgis"], "support": []}}]}
NO_MATCH = "title does not match any target track"


class Gaps(Base):
    def setUp(self):
        super().setUp()
        (self.d / "targets.json").write_text(json.dumps(TARGETS), encoding="utf-8")
        intake = json.loads((self.d / "intake.json").read_text(encoding="utf-8"))
        intake["skills"] = ["Tableau", "Excel"]
        (self.d / "intake.json").write_text(json.dumps(intake), encoding="utf-8")
        (self.d / "docs").mkdir(exist_ok=True)
        (self.d / "docs/cv_data.json").write_text(json.dumps({"summary": "SQL and Excel analyst"}), encoding="utf-8")
        (self.d / "docs/cv_gis.json").write_text(json.dumps({"summary": "ArcGIS mapping"}), encoding="utf-8")
        self.day = datetime.date.today().isoformat()

    def add(self, n, title, text, verdict="shortlisted", reason="ok", track="data", day=None):
        from jobdb import connect, record_seen
        record_seen("ana", [{"key": f"seek:{n}", "platform": "seek", "title": title, "company": f"Co{n}", "url": f"u{n}"}],
                    day or self.day)
        with connect("ana") as con:
            con.execute("UPDATE jobs SET verdict=?, reason=?, track=?, description=? WHERE key=?",
                        (verdict, reason, track, text, f"seek:{n}"))

    def fixture(self):
        old = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
        self.add(1, "Data Analyst A", "Power BI, Tableau and SQL daily")
        self.add(2, "Data Analyst B", "Power BI and tableau; Excel; Kafka once")
        self.add(3, "Data Analyst C", "Power BI reporting, SQL")
        self.add(4, "Citizen Analyst", "Power BI, Power BI. Kafka", verdict="rejected", reason="requirement excluded 'clearance'")
        self.add(5, "Old Analyst", "Power BI, Tableau", day=old)
        self.add(6, "GIS Analyst", "ArcGIS and Power BI", track="gis")

    def terms(self, r, *sections):
        return [t["term"] for s in sections for t in r[s]]

    def test_counts_statuses_and_exclusions(self):
        import gaps
        self.fixture()
        r = gaps.gaps("ana")
        self.assertEqual(r["ads"], 4)                                  # 1, 2, 3 and 6; dropped and old ads out
        pbi = next(t for t in r["gaps"] if t["term"] == "power bi")
        self.assertEqual((pbi["ads"], pbi["pct"], pbi["status"]), (4, 100, "gap"))
        self.assertEqual(len(pbi["examples"]), 2)
        tab = next(t for t in r["have_it"] if t["term"] == "tableau")  # in intake, not in the CV
        self.assertEqual(tab["ads"], 2)
        self.assertNotIn("kafka", self.terms(r, "gaps", "have_it", "covered"))     # one live ad only
        self.assertEqual(next(t for t in r["covered"] if t["term"] == "sql")["ads"], 2)
        self.assertNotIn("arcgis", self.terms(r, "gaps", "have_it", "covered"))    # one ad: under the minimum

    def test_each_ad_is_checked_against_its_own_track_cv(self):
        import gaps
        self.add(1, "GIS A", "ArcGIS, SQL", track="gis")
        self.add(2, "GIS B", "ArcGIS, SQL", track="gis")
        self.add(3, "Data A", "ArcGIS, SQL", track="data")
        self.add(4, "Data B", "ArcGIS, SQL", track="data")
        r = gaps.gaps("ana")
        arc = next(t for t in r["gaps"] + r["covered"] + r["have_it"] if t["term"] == "arcgis")
        self.assertEqual((arc["ads"], arc["not_in_cv"]), (4, 2))       # the gis CV has it, the data CV does not
        self.assertEqual(arc["status"], "gap")
        only = gaps.gaps("ana", track="gis")
        self.assertEqual(only["ads"], 2)
        self.assertEqual(next(t for t in only["covered"] if t["term"] == "arcgis")["not_in_cv"], 0)

    def test_skipped_by_the_person_is_out_and_tracked_is_in(self):
        import gaps
        from tracker import add, set_status
        self.add(1, "A", "Power BI", verdict="rejected", reason="over shortlist cap")
        self.add(2, "B", "Power BI", verdict="rejected", reason="over shortlist cap")
        self.add(3, "C", "Power BI")
        for n in (1, 2):
            add("ana", {"key": f"seek:{n}", "title": "x", "url": "u", "platform": "seek", "track": "data"})
        set_status("ana", "seek:2", "skipped")
        self.assertEqual(gaps.gaps("ana")["ads"], 2)                   # 1 (tracked) and 3 (shortlisted)

    def test_near_misses_are_included(self):
        import gaps
        self.add(1, "Data Analyst", "Power BI and SQL")
        self.add(2, "Reporting Wizard", "SQL, Excel, reporting, Power BI", verdict="rejected", reason=NO_MATCH)
        r = gaps.gaps("ana")
        self.assertEqual((r["ads"], r["near_misses"]), (2, 1))

    def test_no_db_and_output(self):
        import gaps
        self.assertIn("No relevant ads", gaps.table(gaps.gaps("ana")))
        self.fixture()
        out = gaps.table(gaps.gaps("ana"))
        self.assertIn("## Have it, not in the CV (quick win)", out)
        self.assertIn("## Gap (learning candidates)", out)
        self.assertIn("| power bi | 4 of 4 | 100% |", out)
        self.assertIn("do not add the word to the CV until it is true", out)
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            sys.argv = ["gaps", "ana", "--json"]
            gaps.main()
        self.assertEqual(json.loads(buf.getvalue())["ads"], 4)

    def test_report_rule_monday_and_enough_ads(self):
        import gaps
        self.fixture()
        monday = datetime.date(2026, 11, 16).isoformat()
        tuesday = datetime.date(2026, 11, 17).isoformat()
        self.assertEqual(gaps.report_lines("ana", monday), [])         # 4 ads: under 10
        for n in range(10, 18):
            self.add(n, f"Data Analyst {n}", "Power BI and Tableau")
        lines = gaps.report_lines("ana", monday)
        self.assertTrue(any("power bi" in x for x in lines))
        self.assertTrue(any("tableau" in x for x in lines))
        self.assertLessEqual(len(lines), 6)
        self.assertEqual(gaps.report_lines("ana", tuesday), [])        # weekly


if __name__ == "__main__":
    unittest.main()
