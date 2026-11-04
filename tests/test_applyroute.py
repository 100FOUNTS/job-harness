"""How each job is applied for: the route read from SEEK and LinkedIn, the feeds' constant, jobs.db, the count."""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import applyroute  # noqa: E402
import sources  # noqa: E402
from common import cand_dir  # noqa: E402
from jobdb import connect, record_seen  # noqa: E402
from sources import base  # noqa: E402


class Classify(unittest.TestCase):
    def test_systems_by_host(self):
        for url, ats in (("https://boards.greenhouse.io/acme/jobs/1", "greenhouse"), ("https://jobs.lever.co/acme/x", "lever"),
                         ("https://jobs.ashbyhq.com/acme/1", "ashby"), ("https://apply.workable.com/acme/j/1", "workable"),
                         ("https://acme.wd3.myworkdayjobs.com/en-US/careers/job/1", "workday"),
                         ("https://acme.taleo.net/careersection/x", "taleo"), ("https://careers.acme.com.au/job/1", ""), ("", "")):
            self.assertEqual(applyroute.ats_of(url), ats, url)

    def test_a_host_only_counts_where_it_is_the_host(self):
        self.assertEqual(applyroute.ats_of("https://careers.acme.com/?next=boards.greenhouse.io"), "")

    def test_classes(self):
        self.assertEqual(applyroute.klass("quick", ""), "quick")
        self.assertEqual(applyroute.klass("external", "lever"), "open-ats")
        self.assertEqual(applyroute.klass("external", "workday"), "account-ats")
        self.assertEqual(applyroute.klass("external", ""), "company-site")
        self.assertEqual(applyroute.klass("unknown", ""), "unknown")
        self.assertEqual(applyroute.klass("", ""), "unknown")


class SeekRoute(unittest.TestCase):
    def setUp(self):
        sources.seek._LINK_OUT.clear()

    def gql(self, link_out, content="<p>Python role</p>"):
        calls = []
        def fake(url, payload, headers=None):
            calls.append(payload["query"])
            job = {"isLinkOut": link_out}
            if "content(" in payload["query"]:
                job["content"] = content
            return {"data": {"jobDetails": {"job": job}}}
        return fake, calls

    def test_reading_the_ad_also_tells_the_route_with_no_second_request(self):
        fake, calls = self.gql(True)
        with unittest.mock.patch.object(base, "post_json", fake):
            self.assertIn("Python role", sources.seek.detail("9"))
            self.assertEqual(sources.seek.route("9"), ("external", ""))
        self.assertEqual(len(calls), 1)

    def test_seek_own_form_is_quick(self):
        fake, _ = self.gql(False)
        with unittest.mock.patch.object(base, "post_json", fake):
            self.assertEqual(sources.seek.route("10"), ("quick", ""))

    def test_an_ad_nobody_read_costs_one_request(self):
        fake, calls = self.gql(True)
        with unittest.mock.patch.object(base, "post_json", fake):
            self.assertEqual(sources.seek.route("11"), ("external", ""))
            self.assertEqual(sources.seek.route("11"), ("external", ""))
        self.assertEqual(len(calls), 1)

    def test_a_failed_request_says_nothing(self):
        with unittest.mock.patch.object(base, "post_json", lambda *a, **k: None):
            self.assertIsNone(sources.seek.route("12"))
            self.assertEqual(applyroute.detect("seek", "12"), ("unknown", ""))


class LinkedinRoute(unittest.TestCase):
    ONSITE = '<a data-tracking-control-name="public_jobs_apply-link-onsite">Easy Apply</a>'
    OFFSITE = '<a data-tracking-control-name="public_jobs_apply-link-offsite_contextual-sign-in-modal">Apply</a>'

    def setUp(self):
        sources.linkedin._APPLY.clear()

    def test_the_page_read_for_the_description_also_gives_the_route(self):
        page = '<div class="show-more-less-html__markup">Great job</div><button>' + self.OFFSITE
        calls = []
        with unittest.mock.patch.object(base, "http_get", lambda u: calls.append(u) or (200, page)):
            sources.linkedin.detail("1")
            self.assertEqual(sources.linkedin.route("1"), ("external", ""))
        self.assertEqual(len(calls), 1)

    def test_easy_apply_is_quick(self):
        with unittest.mock.patch.object(base, "http_get", lambda u: (200, "<html>" + self.ONSITE)):
            self.assertEqual(sources.linkedin.route("2"), ("quick", ""))

    def test_a_page_with_no_apply_link_says_nothing(self):
        with unittest.mock.patch.object(base, "http_get", lambda u: (200, "<html>closed</html>")):
            self.assertIsNone(sources.linkedin.route("3"))
        with unittest.mock.patch.object(base, "http_get", lambda u: (429, "")):
            self.assertIsNone(sources.linkedin.route("4"))


class Constants(unittest.TestCase):
    def test_company_feeds_are_their_own_system(self):
        for n in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters"):
            self.assertEqual(applyroute.detect(n, "board/1"), ("external", n))
            self.assertEqual(applyroute.klass(*applyroute.detect(n, "board/1")), "open-ats")

    def test_unknown_source_or_source_without_a_route(self):
        self.assertEqual(applyroute.detect("nowhere", "1"), ("unknown", ""))
        self.assertEqual(applyroute.detect("wagov", "1"), ("unknown", ""))


class Stored(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["JOB_CANDIDATES_DIR"] = str(self.tmp)
        (self.tmp / "ana").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp)
        os.environ.pop("JOB_CANDIDATES_DIR", None)

    def job(self, key, platform="seek", **extra):
        return {"key": key, "id": key.split(":", 1)[1], "platform": platform, "title": "Dev", "company": "Co", "url": "u",
                "tracks": [], "bullets": []} | extra

    def test_an_old_database_gets_the_columns(self):
        con = sqlite3.connect(self.tmp / "ana" / "jobs.db")
        con.executescript("CREATE TABLE jobs (key TEXT PRIMARY KEY, platform TEXT, title TEXT, company TEXT, location TEXT, url TEXT,"
                          " listed TEXT, salary TEXT, work_type TEXT, classification TEXT, search TEXT, teaser TEXT, easy_apply TEXT,"
                          " tracks TEXT, bullets TEXT, description TEXT, first_seen TEXT, last_seen TEXT, times_seen INTEGER DEFAULT 0,"
                          " verdict TEXT, reason TEXT, track TEXT, judged_with TEXT, fit INTEGER, outcome TEXT);"
                          "INSERT INTO jobs (key, platform) VALUES ('seek:1', 'seek');")
        con.commit(); con.close()
        with connect("ana") as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
        self.assertTrue({"apply_route", "apply_ats"} <= cols)

    def test_seeing_the_ad_again_does_not_wipe_the_route(self):
        record_seen("ana", [self.job("seek:1")], "2026-11-01")
        applyroute.record("ana", "seek:1", "quick", "")
        record_seen("ana", [self.job("seek:1")], "2026-11-02")
        with connect("ana", readonly=True) as c:
            self.assertEqual(c.execute("SELECT apply_route FROM jobs").fetchone()[0], "quick")

    def test_record_many_asks_once_and_keeps_the_answer(self):
        record_seen("ana", [self.job("lever:acme/1", "lever"), self.job("seek:2")], "2026-11-01")
        short = [self.job("lever:acme/1", "lever"), self.job("seek:2")]
        asked = []
        def fake(platform, job_id):
            asked.append(platform)
            return ("quick", "")
        with unittest.mock.patch.object(applyroute, "detect", fake):
            applyroute.record_many("ana", short)
            applyroute.record_many("ana", [self.job("lever:acme/1", "lever"), self.job("seek:2")])
        self.assertEqual(asked, ["lever", "seek"])                    # the second run found both already known
        self.assertEqual({j["key"]: j["apply_route"] for j in short}, {"lever:acme/1": "quick", "seek:2": "quick"})

    def test_a_route_that_could_not_be_read_is_asked_again(self):
        record_seen("ana", [self.job("seek:3")], "2026-11-01")
        with unittest.mock.patch.object(applyroute, "detect", lambda p, i: ("unknown", "")):
            applyroute.record_many("ana", [self.job("seek:3")])
        with unittest.mock.patch.object(applyroute, "detect", lambda p, i: ("external", "")) as d:
            applyroute.record_many("ana", [self.job("seek:3")])
        with connect("ana", readonly=True) as c:
            self.assertEqual(c.execute("SELECT apply_route FROM jobs").fetchone()[0], "external")

    def board(self):
        from tracker import add, set_status
        rows = [("seek:1", "seek", "prepared", "quick", ""), ("seek:2", "seek", "prepared", "external", ""),
                ("linkedin:3", "linkedin", "prepared", "external", "workday"), ("lever:a/4", "lever", "prepared", "external", "lever"),
                ("seek:5", "seek", "prepared", "", ""), ("seek:6", "seek", "skipped", "quick", ""),
                ("wagov:7", "wagov", "manual-review", "", "")]
        record_seen("ana", [self.job(k, p) for k, p, *_ in rows], "2026-11-01")
        for k, p, status, route, ats in rows:
            add("ana", {"key": k, "title": "Dev", "company": "Co", "url": "u", "platform": p})
            set_status("ana", k, status)
            if route:
                applyroute.record("ana", k, route, ats)

    def test_count_groups_the_open_jobs(self):
        self.board()
        r = applyroute.count("ana")
        self.assertEqual(r["open_jobs"], 6)                          # the skipped one is not on the board's to-do
        self.assertEqual(r["by_class"], {"quick": 1, "open-ats": 1, "account-ats": 1, "company-site": 1, "unknown": 2})
        self.assertEqual(r["by_ats"], {"workday": 1, "lever": 1})
        self.assertEqual(r["by_platform"]["seek"]["quick"], 1)
        self.assertEqual(sorted(r["unknown_keys"]), ["seek:5", "wagov:7"])

    def test_refresh_only_asks_for_what_is_missing(self):
        self.board()
        asked = []
        def fake(platform, job_id):
            asked.append(f"{platform}:{job_id}")
            return ("quick", "") if platform == "seek" else ("unknown", "")
        with unittest.mock.patch.object(applyroute, "detect", fake), unittest.mock.patch("time.sleep"):
            r = applyroute.count("ana", refresh=True)
        self.assertEqual(sorted(asked), ["seek:5", "wagov:7"])
        self.assertEqual(r["by_class"]["quick"], 2)
        self.assertEqual(r["unknown_keys"], ["wagov:7"])

    def test_the_apply_page_refines_the_system(self):
        self.board()
        out = applyroute.set_url("ana", "seek:2", "https://jobs.lever.co/acme/123")
        self.assertEqual((out["route"], out["ats"], out["host"]), ("external", "lever", "jobs.lever.co"))
        with self.assertRaises(SystemExit):
            applyroute.set_url("ana", "seek:99", "https://x.test")

    def test_a_job_that_left_no_db_row_does_not_break_the_count(self):
        from tracker import add, set_status
        record_seen("ana", [self.job("seek:1")], "2026-11-01")
        add("ana", {"key": "seek:404", "title": "Dev", "company": "Co", "url": "u", "platform": "seek"})
        set_status("ana", "seek:404", "prepared")
        self.assertEqual(applyroute.count("ana")["by_class"]["unknown"], 1)


class Gates(Stored):
    """What the Apply button led to: recorded per job, remembered per employer host, grouped for the person."""
    def seed(self):
        from tracker import add, set_status
        rows = [("linkedin:1", "https://acme.wd3.myworkdayjobs.com/en-US/x/job/1", "login"),
                ("linkedin:2", "https://acme.wd3.myworkdayjobs.com/en-US/x/job/2", "login"),
                ("linkedin:3", "https://careers.beta.com.au/apply/3", "open"), ("seek:4", "", ""),
                ("linkedin:5", "https://hire.gamma.com/x", "captcha"), ("linkedin:6", "https://jobs.delta.com/x", "blocked")]
        record_seen("ana", [self.job(k, k.split(":")[0]) for k, *_ in rows], "2026-11-01")
        for k, url, gate in rows:
            add("ana", {"key": k, "title": f"Role {k}", "company": "Co", "url": "u", "platform": k.split(":")[0]})
            set_status("ana", k, "prepared")
            if url:
                applyroute.set_url("ana", k, url, gate)
        applyroute.record("ana", "seek:4", "external", "")                  # clicked through to an employer's site, not probed yet

    def test_the_probe_is_recorded_with_host_system_and_gate(self):
        self.seed()
        with connect("ana", readonly=True) as c:
            r = c.execute("SELECT apply_route, apply_ats, apply_host, apply_gate FROM jobs WHERE key='linkedin:1'").fetchone()
        self.assertEqual(tuple(r), ("external", "workday", "acme.wd3.myworkdayjobs.com", "login"))

    def test_an_unknown_gate_is_refused(self):
        self.seed()
        with self.assertRaises(SystemExit):
            applyroute.set_url("ana", "linkedin:1", "https://x.test", "maybe")

    def test_a_second_ad_of_the_same_employer_reuses_the_first_probe(self):
        self.seed()
        k = applyroute.known("ana", "https://acme.wd3.myworkdayjobs.com/en-US/x/job/99")
        self.assertEqual((k["host"], k["ats"], k["gate"]), ("acme.wd3.myworkdayjobs.com", "workday", "login"))
        k = applyroute.known("ana", "https://never.seen.test/apply")
        self.assertEqual((k["gate"], k["ats"]), ("", ""))

    def test_a_probe_without_a_gate_does_not_erase_the_gate_found_before(self):
        self.seed()
        applyroute.set_url("ana", "linkedin:3", "https://careers.beta.com.au/apply/3")
        self.assertEqual(applyroute.known("ana", "https://careers.beta.com.au/x")["gate"], "open")

    def test_the_queue_groups_logins_by_portal_and_counts_what_is_left(self):
        self.seed()
        q = applyroute.queue("ana")
        self.assertEqual(q["open_jobs"], 6)
        self.assertEqual(q["ready_to_fill"], 1)
        self.assertEqual([(g["host"], len(g["jobs"])) for g in q["login_queue"]], [("acme.wd3.myworkdayjobs.com", 2)])
        self.assertEqual(q["captcha"], ["linkedin:5"])
        self.assertEqual(q["blocked_hosts"], ["jobs.delta.com"])
        self.assertEqual(q["to_probe_keys"], ["seek:4"])

    def test_the_hosts_to_allow_are_the_portals_plus_the_employers_found(self):
        self.seed()
        h = applyroute.hosts_to_allow("ana")
        for x in ("www.linkedin.com", "www.seek.com.au", "careers.beta.com.au", "jobs.delta.com", "acme.wd3.myworkdayjobs.com"):
            self.assertIn(x, h)

    def test_the_cli_prints_them(self):
        self.seed()
        import contextlib
        import io
        out = io.StringIO()
        with unittest.mock.patch.object(sys, "argv", ["routes", "ana", "--hosts"]), contextlib.redirect_stdout(out):
            applyroute.main()
        self.assertIn("careers.beta.com.au", out.getvalue().split())


class AnswerGaps(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["JOB_CANDIDATES_DIR"] = str(self.tmp)
        (self.tmp / "ana").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp)
        os.environ.pop("JOB_CANDIDATES_DIR", None)

    def test_gaps_lists_the_empty_answers_and_marks_the_sensitive_ones(self):
        import answer
        (self.tmp / "ana" / "answers.json").write_text(json.dumps({"answers": [
            {"match": ["right to work", "authorised to work"], "answer": None},
            {"match": ["notice period"], "answer": "2 weeks"},
            {"match": ["fifo"], "answer": ""},
            {"match": ["require sponsorship"], "answer": None}]}), encoding="utf-8")
        g = answer.gaps("ana")
        self.assertEqual(g, [{"question": "right to work", "sensitive": True}, {"question": "fifo", "sensitive": False},
                             {"question": "require sponsorship", "sensitive": True}])


if __name__ == "__main__":
    unittest.main()
