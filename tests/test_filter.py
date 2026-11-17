"""Title matching (tolerant phrases), the daily reading budget and the near-miss score."""
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

KW = {"core": ["java", "python"], "support": ["sql", "ci/cd"]}
T = {"locations_include": ["Perth", "WA"], "exclude_title": ["senior"],
     "tracks": [{"id": "sw", "title_include": ["web developer", "full stack developer", "ai engineer"], "keywords": KW},
                {"id": "data", "title_include": ["data integration", "data engineer"], "keywords": KW}]}


class TestPhrases(unittest.TestCase):
    def m(self, phrase, title):
        from triage import prx
        return bool(prx([phrase]).search(title))

    def test_tolerant_matches(self):
        for p, t in (("web developer", "Web/UI Developer"), ("web developer", "Web & Mobile Developer"),
                     ("full stack developer", "Full Stack / Java Developer"), ("full stack developer", "Full-Stack Developer"),
                     ("full-stack", "Senior Full Stack Engineer"), ("data integration", "Data and Integration Specialist"),
                     ("data integration", "Senior Data Integration Specialist"), ("web developer", "WEB DEVELOPER"),
                     ("business intelligence developer", "Business Intelligence Developer"), ("node", "Node Developer")):
            self.assertTrue(self.m(p, t), (p, t))

    def test_strict_matches(self):
        for p, t in (("web developer", "Developer - Web"), ("ai engineer", "Maintenance Engineer"), ("ai engineer", "Email Engineer"),
                     ("node", "Nodes Operator"), ("web developer", "Web Design Content Marketing Lead Developer"),
                     ("data integration", "Database Integration")):
            self.assertFalse(self.m(p, t), (p, t))

    def test_stems(self):
        from triage import prx
        for p, t in (("cartograph", "Cartographer"), ("hydrolog", "Senior Hydrologist"), ("hse*", "HSEQ Advisor"),
                     ("water engineer", "Water Engineering Lead")):
            self.assertTrue(prx([p]).search(t), (p, t))
        for p, t in (("hse", "HSEQ Advisor"), ("node", "Nodes Operator"), ("gis", "Gisborne Officer")):
            self.assertFalse(prx([p]).search(t), (p, t))

    def test_single_word_as_before(self):
        from triage import prx
        self.assertTrue(prx(["gis"]).search("Environmental GIS Officer"))
        self.assertFalse(prx(["gis"]).search("Logistics Officer"))

    def test_exclude_title_unchanged(self):
        from triage import judge
        self.assertEqual(judge({"title": "Web/UI Developer", "location": "Perth WA"}, T)[0], "sw")
        self.assertIsNone(judge({"title": "Senior Web/UI Developer", "location": "Perth WA"}, T)[0])
        t = dict(T, tracks=[dict(T["tracks"][0], exclude_title=["junior"])])
        self.assertIsNone(judge({"title": "Junior Web & Mobile Developer", "location": "Perth WA"}, t)[0])
        self.assertEqual(judge({"title": "Web & Mobile Developer", "location": "Perth WA"}, t)[0], "sw")


class TestBudget(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["JOB_CANDIDATES_DIR"] = str(self.tmp)
        (self.tmp / "ana" / "data" / "2026-01-01").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)
        os.environ.pop("JOB_CANDIDATES_DIR", None)

    def run_triage(self, jobs, **extra):
        import sources
        from triage import triage
        t = json.loads(json.dumps(T)) | extra
        t["tracks"][0]["description_include"] = {"words": ["python"], "min": 2, "titles": ["developer"]}
        (self.tmp / "ana" / "targets.json").write_text(json.dumps(t), encoding="utf-8")
        (self.tmp / "ana" / "data" / "2026-01-01" / "jobs.json").write_text(json.dumps({"new_jobs": jobs}), encoding="utf-8")
        calls = []
        def fake(job_id):
            calls.append(job_id)
            return "We use python and python daily."
        with unittest.mock.patch.object(sources.seek, "detail", fake), unittest.mock.patch.object(
                sources.seek, "route", lambda i: ("quick", "")), unittest.mock.patch("time.sleep"):
            return triage("ana", "2026-01-01", 40), calls

    def test_the_apply_route_is_kept_on_the_shortlisted_job_and_in_jobs_db(self):
        from jobdb import record_seen
        record_seen("ana", [self.job(1, "Python Developer") | {"tracks": []}], "2026-01-01")          # discover has done this by triage time
        out, _ = self.run_triage([self.job(1, "Python Developer")])
        self.assertEqual([(j["apply_route"], j["apply_ats"]) for j in out["shortlist"]], [("quick", "")])
        saved = json.loads((self.tmp / "ana" / "data" / "2026-01-01" / "shortlist.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["shortlist"][0]["apply_route"], "quick")
        from jobdb import connect
        with connect("ana", readonly=True) as con:
            self.assertEqual(con.execute("SELECT apply_route FROM jobs WHERE key='seek:1'").fetchone()[0], "quick")

    def job(self, i, title, listed="2026-01-01", teaser=""):
        return {"key": f"seek:{i}", "id": str(i), "platform": "seek", "title": title, "company": "Co", "location": "Perth WA",
                "listed": listed, "teaser": teaser, "bullets": []}

    def test_budget_respected_and_best_first(self):
        jobs = [self.job(1, "Software Developer", "2026-01-03"), self.job(2, "Platform Developer Trainee", "2026-01-02"),
                self.job(3, "Systems Developer", "2026-01-01", "Java, SQL and CI/CD pipelines"),
                self.job(4, "Content Officer", "2026-01-03")]            # title not claimable by description: never read
        out, calls = self.run_triage(jobs, max_detail_fetches=1)
        self.assertEqual(calls, ["3"])                                    # richest teaser first, despite being the oldest
        self.assertEqual([j["key"] for j in out["shortlist"]], ["seek:3"])
        why = {r["key"]: r["reason"] for r in out["rejected"]}
        self.assertIn("not read: daily reading budget", why["seek:1"])
        self.assertIn("not read: daily reading budget", why["seek:2"])
        self.assertEqual(why["seek:4"], "title does not match any target track")

    def test_direct_matches_do_not_use_budget(self):
        jobs = [self.job(1, "Web/UI Developer"), self.job(2, "Full Stack / Java Developer"), self.job(3, "Systems Developer")]
        out, calls = self.run_triage(jobs, max_detail_fetches=0)
        self.assertEqual(sorted(calls), ["1", "2"])                       # matching titles are read to judge, free of budget
        self.assertEqual(sorted(j["key"] for j in out["shortlist"]), ["seek:1", "seek:2"])
        self.assertEqual(next(r for r in out["rejected"] if r["key"] == "seek:3")["reason"],
                         "title does not match any target track (not read: daily reading budget)")

    def test_default_budget_and_shortlist_cap(self):
        out, calls = self.run_triage([self.job(i, f"Role {i} Developer") for i in range(70)])
        self.assertEqual(len(calls), 40)                                  # stops reading once max_n (40) are shortlisted
        out, calls = self.run_triage([self.job(i, f"Role {i} Developer") for i in range(70)], max_detail_fetches=5)
        self.assertEqual(len(calls), 5)

    def test_near_miss_hits_and_transient_reason(self):
        out, _ = self.run_triage([self.job(1, "Content Officer", teaser="python java and sql"), self.job(2, "Cook")])
        h = {r["key"]: r.get("hits") for r in out["rejected"]}
        self.assertEqual(h, {"seek:1": 3, "seek:2": 0})
        from jobdb import TRANSIENT
        self.assertTrue("title does not match any target track (not read: daily reading budget)".startswith(TRANSIENT))


class TestCompanyBlocklist(unittest.TestCase):
    """Excluded employers: whole-name match after normalisation, dropped in triage and flagged on pasted links."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["JOB_CANDIDATES_DIR"] = str(self.tmp)
        (self.tmp / "ana" / "data" / "2026-01-01").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)
        os.environ.pop("JOB_CANDIDATES_DIR", None)

    def test_normalisation_ignores_case_suffixes_and_punctuation(self):
        from blocklist import matches
        for ad in ("ACME Pty Ltd", "Acme Pty. Ltd.", "The Acme Limited", "acme", "Acme Inc."):
            self.assertEqual(matches(ad, ["Acme"]), "Acme", ad)
        self.assertEqual(matches("Smith and Sons", ["Smith & Sons Pty Ltd"]), "Smith & Sons Pty Ltd")
        self.assertEqual(matches("Caf\u00e9 Rio", ["Cafe Rio"]), "Cafe Rio")

    def test_whole_name_only_no_substring_false_positives(self):
        from blocklist import matches
        self.assertIsNone(matches("Rio Tinto", ["Rio"]))
        self.assertIsNone(matches("Acme Australia", ["Acme"]))
        self.assertIsNone(matches("Macmillan", ["Acme"]))
        self.assertEqual(matches("Rio Tinto Limited", ["Rio Tinto"]), "Rio Tinto")
        self.assertIsNone(matches("", ["Acme"]))
        self.assertIsNone(matches("The Pty Ltd", ["Acme"]))

    def test_add_remove_list_and_duplicates(self):
        import blocklist
        self.assertIn("Blocked", blocklist.add("ana", "Acme Pty Ltd", note="rejected twice"))
        self.assertIn("already", blocklist.add("ana", "ACME"))
        self.assertEqual(blocklist.names("ana"), ["Acme Pty Ltd"])
        self.assertEqual(blocklist.load("ana")[0]["note"], "rejected twice")
        self.assertIn("Unblocked", blocklist.remove("ana", "acme limited"))
        self.assertEqual(blocklist.names("ana"), [])
        with self.assertRaises(SystemExit):
            blocklist.remove("ana", "Acme")
        with self.assertRaises(SystemExit):
            blocklist.add("ana", "  ")

    def test_judge_rejects_with_reason_and_only_for_listed_companies(self):
        from triage import judge
        job = {"title": "Web Developer", "company": "ACME Pty Ltd", "location": "Perth WA"}
        self.assertEqual(judge(job, T)[0], "sw")
        self.assertEqual(judge(job, T | {"exclude_companies": ["Acme"]}), (None, "company excluded ('Acme')"))
        self.assertEqual(judge(job, T | {"exclude_companies": ["Other"]})[0], "sw")

    def test_triage_drops_the_ad_and_the_panel_reason_is_stored(self):
        import blocklist
        from jobdb import connect, record_seen
        from triage import triage
        blocklist.add("ana", "Acme")
        t = json.loads(json.dumps(T))
        (self.tmp / "ana" / "targets.json").write_text(json.dumps(t), encoding="utf-8")
        mk = lambda i, co: {"key": f"seek:{i}", "id": str(i), "platform": "linkedin", "title": "Web Developer", "company": co,
                            "location": "Perth WA", "listed": "2026-01-01", "teaser": "", "bullets": [], "description": "python"}
        jobs = [mk(1, "Acme Pty Ltd"), mk(2, "Rio Tinto")]
        (self.tmp / "ana" / "data" / "2026-01-01" / "jobs.json").write_text(json.dumps({"new_jobs": jobs}), encoding="utf-8")
        record_seen("ana", [j | {"tracks": []} for j in jobs], "2026-01-01")
        with unittest.mock.patch("applyroute.record_many"):
            out = triage("ana", "2026-01-01", 40)
        self.assertEqual([j["key"] for j in out["shortlist"]], ["seek:2"])
        self.assertEqual(out["rejected"][0]["reason"], "company excluded ('Acme')")
        with connect("ana", readonly=True) as con:
            row = con.execute("SELECT verdict, reason FROM jobs WHERE key='seek:1'").fetchone()
        self.assertEqual(tuple(row), ("rejected", "company excluded ('Acme')"))

    def test_with_blocklist_keeps_targets_untouched_when_empty(self):
        import blocklist
        self.assertIs(blocklist.with_blocklist("ana", T), T)
        blocklist.add("ana", "Acme")
        self.assertEqual(blocklist.with_blocklist("ana", T)["exclude_companies"], ["Acme"])

    def test_blocklist_does_not_touch_the_sealed_targets_file(self):
        import blocklist
        p = self.tmp / "ana" / "targets.json"
        p.write_text(json.dumps(T), encoding="utf-8")
        before = p.read_bytes()
        blocklist.add("ana", "Acme")
        self.assertEqual(p.read_bytes(), before)
        self.assertTrue((self.tmp / "ana" / "blocklist.json").exists())


if __name__ == "__main__":
    unittest.main()
