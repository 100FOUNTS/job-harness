"""Panel: "Maybe worth a look" near misses, and the filter suggestions learned from rescues."""
import contextlib
import datetime
import io
import json
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_core import Base  # noqa: E402

TARGETS = {"exclude_title": ["manager"], "locations_include": [],
           "tracks": [{"id": "software", "primary": True, "title_include": ["software engineer"], "exclude_title": ["intern"],
                       "keywords": {"core": ["python", "react", "api design"], "support": ["sql", "docker"]}},
                      {"id": "data", "title_include": ["data analyst"],
                       "keywords": {"core": ["sql", "power bi"], "support": ["excel", "reporting"]}}]}
NO_MATCH = "title does not match any target track"


class Maybe(Base):
    def setUp(self):
        super().setUp()
        (self.d / "targets.json").write_text(json.dumps(TARGETS), encoding="utf-8")
        self.day = datetime.date.today().isoformat()

    def add(self, n, title, text="", reason=NO_MATCH, day=None, verdict="rejected"):
        from jobdb import connect, record_seen
        record_seen("ana", [{"key": f"seek:{n}", "platform": "seek", "title": title, "company": f"Co{n}", "url": f"u{n}",
                             "teaser": text}], day or self.day)
        with connect("ana") as con:
            con.execute("UPDATE jobs SET verdict=?, reason=? WHERE key=?", (verdict, reason, f"seek:{n}"))

    def test_ranking_threshold_and_exclusions(self):
        import panel
        old = (datetime.date.today() - datetime.timedelta(days=9)).isoformat()
        self.add(1, "Web Developer", "Python, React and API design daily")                  # 2+2+2 = 6
        self.add(2, "Platform Wizard", "Python and SQL with Docker")                         # python 2 + sql 2 (core in "data") + docker 1
        self.add(3, "Office Helper", "Excel and reporting")                                  # 1+1 = 2: under 3
        self.add(4, "Delivery Manager", "Python, React, API design")                         # global exclude_title
        self.add(5, "Intern Developer", "Python, React, API design")                         # per-track exclude_title
        self.add(6, "Old Developer", "Python, React, API design", day=old)                   # outside 7 days
        self.add(7, "Rule Dropped", "Python, React, API design", reason="requirement excluded 'clearance'")
        self.add(8, "Python Hacker", "pythonic REACT")                                       # 2 (python) + 2 (react) = 4
        self.add(9, "Same Score Later", "Python, React and API design daily", day=old)      # also old
        r = panel.maybes("ana")
        self.assertEqual([x["key"] for x in r], ["seek:1", "seek:2", "seek:8"])
        self.assertEqual(r[0]["score"], 6)
        self.assertEqual(r[0]["track"], "software")
        self.assertEqual(r[0]["keywords"], ["api design", "python", "react"])               # core first, then alphabetical
        self.assertEqual(r[1]["score"], 5)                                                   # python 2 + sql 2 + docker 1
        self.assertEqual(r[2]["score"], 4)                                                   # "pythonic": stems of 6+ letters
        self.assertEqual(len(panel.maybes("ana", n=2)), 2)

    def test_words_are_whole_and_distinct(self):
        import panel
        self.add(1, "Dev", "Reactor design, sqlite, reactive. Python python PYTHON")        # only python: 2
        self.add(2, "Dev2", "Sql, SQL and sql")                                              # sql counted once: 2
        self.assertEqual(panel.maybes("ana"), [])

    def test_tracked_and_empty_states(self):
        import panel
        from tracker import add
        self.assertEqual(panel.maybes("ana"), [])                                            # no jobs.db yet
        self.add(1, "Web Developer", "Python, React and API design daily")
        add("ana", {"key": "seek:1", "title": "Web Developer", "url": "u", "platform": "seek"})
        self.assertEqual(panel.maybes("ana"), [])
        self.assertEqual(panel.data("ana")["maybes"], [])

    def test_ties_go_to_the_most_recent(self):
        import panel
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        self.add(1, "Older", "Python and React", day=yesterday)
        self.add(2, "Newer", "Python and React")
        self.assertEqual([x["key"] for x in panel.maybes("ana")], ["seek:2", "seek:1"])

    def test_fast_on_thousands_of_rows(self):
        import time
        import panel
        from jobdb import connect
        self.add(0, "Seed", "x")
        with connect("ana") as con:
            con.executemany("INSERT INTO jobs (key, title, company, url, teaser, description, last_seen, verdict, reason) "
                            "VALUES (?, ?, 'Co', 'u', '', ?, ?, 'rejected', ?)",
                            [(f"x:{i}", f"Role {i}", "lorem ipsum dolor sit amet " * 300 + (" python react sql" if i % 50 == 0 else ""),
                              self.day, NO_MATCH) for i in range(3000)])
        t = time.time()
        r = panel.maybes("ana")
        self.assertLess(time.time() - t, 3)
        self.assertEqual(len(r), 10)


class Phrases(unittest.TestCase):
    def test_derivation(self):
        from suggest import phrase
        for title, want in [("Senior Web/UI Developer - SKA-Low Telescope", "web/ui developer"),
                            ("Business Intelligence Developer", "business intelligence developer"),
                            ("Graduate Hydrologist (Level 2) | Perth", "hydrologist"),
                            ("Junior Data Analyst, Digital Services", "data analyst"),
                            ("Mid Level Contract GIS Officer x2 – Water Corp", "gis officer"),
                            ("Principal Environmental Approvals Planning Officer II", "environmental approvals planning officer"),
                            ("Senior Developer", ""), ("Lead", ""), ("", "")]:
            self.assertEqual(phrase(title), want, title)


class Suggestions(Base):
    def setUp(self):
        super().setUp()
        (self.d / "targets.json").write_text(json.dumps(TARGETS), encoding="utf-8")

    def test_record_dedup_pending_and_clear(self):
        import suggest
        self.assertEqual(suggest.record("ana", "Senior Web/UI Developer - SKA", "seek:1", "software"), "web/ui developer")
        self.assertEqual(suggest.record("ana", "Web/UI Developer (Contract)", "seek:2", "software"), "")        # duplicate
        self.assertEqual(suggest.record("ana", "Software Engineer II", "seek:3", "software"), "")               # already accepted
        self.assertEqual(suggest.record("ana", "Report Writer", "seek:4", "data"), "report writer")
        saved = json.loads((self.d / "suggestions.json").read_text(encoding="utf-8"))
        self.assertEqual([(s["phrase"], s["track"], s["from_key"]) for s in saved["title_include"]],
                         [("web/ui developer", "software", "seek:1"), ("report writer", "data", "seek:4")])
        self.assertIn("date", saved["title_include"][0])
        self.assertEqual(json.loads((self.d / "targets.json").read_text(encoding="utf-8")), TARGETS)            # sealed file untouched
        # once added to targets by the person, it stops being pending by itself
        t = json.loads(json.dumps(TARGETS)); t["tracks"][0]["title_include"].append("web/ui developer")
        (self.d / "targets.json").write_text(json.dumps(t), encoding="utf-8")
        self.assertEqual([s["phrase"] for s in suggest.pending("ana")], ["report writer"])
        self.assertEqual(suggest.clear("ana", "report writer"), 1)
        self.assertEqual(suggest.pending("ana"), [])
        self.assertEqual(suggest.clear("ana"), 1)
        self.assertEqual(suggest.load("ana"), [])

    def test_cli(self):
        import suggest
        suggest.record("ana", "Report Writer", "seek:4", "data")
        with unittest.mock.patch.object(sys, "argv", ["suggest.py", "ana", "list"]), contextlib.redirect_stdout(io.StringIO()) as out:
            suggest.main()
        self.assertIn("report writer", out.getvalue())
        with unittest.mock.patch.object(sys, "argv", ["suggest.py", "ana", "clear", "report writer"]), contextlib.redirect_stdout(io.StringIO()):
            suggest.main()
        self.assertEqual(suggest.load("ana"), [])

    def test_rescue_saves_a_suggestion_with_the_best_track(self):
        import panel
        from jobdb import connect, record_seen
        record_seen("ana", [{"key": "seek:1", "platform": "seek", "title": "Senior Reporting Wizard - Acme", "company": "Acme",
                             "url": "u", "teaser": "Power BI, SQL and Excel reporting"}], datetime.date.today().isoformat())
        with connect("ana") as con:
            con.execute("UPDATE jobs SET verdict='rejected', reason=? WHERE key='seek:1'", (NO_MATCH,))
        done = unittest.mock.Mock(returncode=0, stderr="")
        with unittest.mock.patch.object(panel.subprocess, "run", return_value=done):
            r = panel.rescue("ana", "seek:1")
        self.assertEqual((r["ok"], r["suggested"]), (True, "reporting wizard"))
        self.assertEqual(panel.data("ana")["suggestions"], [{"phrase": "reporting wizard", "track": "data"}])
        from tracker import load
        self.assertEqual(load("ana")[0]["track"], "data")

    def test_status_line(self):
        import suggest
        from status import summary
        self.assertEqual(summary("ana")["filter_suggestions"], "")
        suggest.record("ana", "Report Writer", "seek:4", "data")
        suggest.record("ana", "Web/UI Developer", "seek:5", "software")
        line = summary("ana")["filter_suggestions"]
        self.assertEqual(line, "Filter suggestions from rescues: report writer, web/ui developer — "
                               "add them with Claude (targets need re-approval)")
        import status
        with unittest.mock.patch.object(sys, "argv", ["status.py", "ana"]), contextlib.redirect_stdout(io.StringIO()) as out:
            status.main()
        self.assertIn(line, out.getvalue())


if __name__ == "__main__":
    unittest.main()
