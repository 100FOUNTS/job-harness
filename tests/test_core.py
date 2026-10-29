"""Every check here comes from a real failure or a hard rule of the harness."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["JOB_CANDIDATES_DIR"] = str(self.tmp)
        d = self.tmp / "ana"
        shutil.copytree(ROOT / "templates/candidate", d)
        (d / "approvals").mkdir()
        intake = json.loads((d / "intake.json").read_text())
        intake["rules"]["never_include"] = ["Practice Project"]
        (d / "intake.json").write_text(json.dumps(intake))
        (d / "facts.json").write_text(json.dumps({"claims": [{"id": "x", "value": "98.6%", "text": "t", "status": "approved"}],
                                                  "allow": ["14001"]}))
        self.d = d

    def tearDown(self):
        shutil.rmtree(self.tmp)
        os.environ.pop("JOB_CANDIDATES_DIR", None)


class TestFacts(Base):
    def test_invented_figure_is_caught(self):
        from facts import verify
        f = self.d / "cv.md"
        f.write_text("Removed 98.6% COD under ISO 14001 in 2022. Improved efficiency by 25%.")
        r = verify("ana", f)
        self.assertFalse(r["ok"])
        self.assertEqual(r["unknown_figures"], ["25%"])

    def test_known_figures_years_and_small_counts_pass(self):
        from facts import verify
        f = self.d / "cv.md"
        f.write_text("98.6% COD, ISO 14001, 2019 – 2026, three options and 3 sites. 17 October 2026. Re: Officer, Ref: 4471")
        self.assertTrue(verify("ana", f)["ok"])


class TestLint(Base):
    def test_forbidden_terms(self):
        from lint import lint
        f = self.d / "letter.md"
        f.write_text("I would need visa sponsorship. See my Practice Project.")
        issues = " ".join(lint("ana", f, "letter")["issues"])
        self.assertIn("sponsorship", issues)
        self.assertIn("Practice Project", issues)

    def test_ligature_font_in_docx_is_flagged(self):
        import zipfile
        from lint import lint
        f = self.d / "cv.docx"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("word/document.xml", '<w:document><w:r><w:rFonts w:ascii="Calibri"/><w:t>Hello</w:t></w:r></w:document>')
        self.assertTrue(any("ligature" in i for i in lint("ana", f, "cv")["issues"]))


class TestTriage(unittest.TestCase):
    T = {"exclude_title": ["senior"], "exclude_text": ["australian citizen"], "locations_include": ["WA", "Perth"],
         "tracks": [{"id": "gis", "title_include": ["gis", "geospatial"], "exclude_title": ["specialist"]},
                    {"id": "env", "title_include": ["environmental"]}]}

    def test_track_priority_and_track_exclusion(self):
        from triage import judge
        self.assertEqual(judge({"title": "Environmental GIS Officer", "location": "Perth WA"}, self.T)[0], "gis")
        self.assertIsNone(judge({"title": "Geospatial Specialist", "location": "Perth WA"}, self.T)[0])
        self.assertEqual(judge({"title": "Environmental Officer", "location": "Perth WA"}, self.T)[0], "env")

    def test_years_rule(self):
        from triage import judge
        t = dict(self.T, max_years_required=5)
        ok = {"title": "Environmental Officer", "location": "Perth WA", "teaser": "3-5 years experience required"}
        too = {"title": "Environmental Officer", "location": "Perth WA", "teaser": "minimum 7 years experience"}
        self.assertEqual(judge(ok, t)[0], "env")
        self.assertIsNone(judge(too, t)[0])

    def test_exclusions(self):
        from triage import judge
        self.assertIsNone(judge({"title": "Senior Environmental Engineer", "location": "Perth WA"}, self.T)[0])
        self.assertIsNone(judge({"title": "Environmental Officer", "location": "Perth WA",
                                 "teaser": "Must be an Australian citizen"}, self.T)[0])
        self.assertIsNone(judge({"title": "Environmental Officer", "location": "Sydney NSW"}, self.T)[0])


class TestTrackerLimits(Base):
    def test_limit_blocks_extra_submission(self):
        from state import default_state, save_state
        from tracker import add, set_status
        st = default_state("ana"); st["limits"] = {"per_platform": 1, "per_day": 5, "per_week": 10}; save_state("ana", st)
        for k in ("seek:1", "seek:2"):
            add("ana", {"key": k, "title": "t", "url": "u", "platform": "seek"})
        set_status("ana", "seek:1", "submitted")
        with self.assertRaises(SystemExit):
            set_status("ana", "seek:2", "submitted")

    def test_no_duplicates(self):
        from tracker import add
        add("ana", {"key": "seek:1", "title": "t", "url": "u", "platform": "seek"})
        with self.assertRaises(SystemExit):
            add("ana", {"key": "seek:1", "title": "t", "url": "u", "platform": "seek"})


class TestGatesAndMode(Base):
    def test_live_needs_signed_intact_go_live(self):
        from gates import request, sign
        from state import default_state, save_state, set_mode
        save_state("ana", default_state("ana"))
        with self.assertRaises(SystemExit):
            set_mode("ana", "live")
        gid = request("ana", "go-live", ["intake.json"], "go")
        with self.assertRaises(SystemExit):                 # default: only a person signs go-live
            sign("ana", gid, by_agent=True, note="User approved in chat: 'yes, go live'", confirm=None)
        os.environ["JOB_HUMAN_SIGN"] = ""                   # owner opted in to approving everything from the chat
        try:
            with self.assertRaises(SystemExit):
                sign("ana", gid, by_agent=True, note="looks good to me", confirm=None)   # must record the user's words
            sign("ana", gid, by_agent=True, note="User approved in chat: 'yes, go live'", confirm=None)
        finally:
            os.environ.pop("JOB_HUMAN_SIGN")
        set_mode("ana", "live")
        (self.d / "intake.json").write_text("{}")          # edit after approval → seal broken
        from gates import valid_approval
        self.assertFalse(valid_approval("ana", "go-live")[0])


class TestHook(Base):
    def run_hook(self, payload):
        env = os.environ | {"CLAUDE_PROJECT_DIR": str(ROOT)}
        return subprocess.run([sys.executable, str(ROOT / "hooks/gate.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env).returncode

    def test_blocks_agent_human_signature(self):
        self.assertEqual(self.run_hook({"tool_name": "Bash", "tool_input": {"command": "bin/job sign ana go-live-01"}}), 2)
        self.assertEqual(self.run_hook({"tool_name": "Bash", "tool_input": {"command": "bin/job sign ana go-live-01 --confirm ana"}}), 2)
        self.assertEqual(self.run_hook({"tool_name": "Bash", "tool_input": {"command": "bin/job sign ana report-01 --by-agent --note x"}}), 0)

    def test_blocks_bookkeeping_edit_and_secrets_and_delete(self):
        self.assertEqual(self.run_hook({"tool_name": "Edit", "tool_input": {"file_path": "/x/candidates/ana/tracker.json"}}), 2)
        self.assertEqual(self.run_hook({"tool_name": "Read", "tool_input": {"file_path": "/x/.env"}}), 2)
        self.assertEqual(self.run_hook({"tool_name": "Bash", "tool_input": {"command": "rm -rf candidates/ana/data"}}), 2)

    def test_submit_blocked_in_dry_run_and_delete_clicks_blocked(self):
        click = lambda s: {"tool_name": "mcp__claude-in-chrome__computer", "tool_input": {"action": "left_click", "action_summary": s}}
        self.assertEqual(self.run_hook(click("Submits the application on SEEK")), 2)
        self.assertEqual(self.run_hook(click("Deletes the old resumé")), 2)
        self.assertEqual(self.run_hook(click("Opens the Quick apply form")), 0)
        batch = {"tool_name": "mcp__claude-in-chrome__browser_batch",
                 "tool_input": {"actions": [{"name": "computer", "input": {"action": "left_click", "action_summary": "Clicks Submit"}}]}}
        self.assertEqual(self.run_hook(batch), 2)


if __name__ == "__main__":
    unittest.main()


class TestAnswerEngine(Base):
    def setUp(self):
        super().setUp()
        (self.d / "answers.json").write_text(json.dumps({"answers": [
            {"match": ["right to work"], "answer": "Yes", "option_prefer": ["restrictions on work hours"]},
            {"match": ["medical"], "answer": "Willing to undertake"}]}))
        (self.d / "docs").mkdir()
        (self.d / "docs" / "cv_environmental.json").write_text(json.dumps({"title": "Environmental Engineer", "experience": [
            {"role": "Environmental Consultant", "dates": "Jan 2021 – Oct 2021", "bullets": []},
            {"role": "Project Engineer", "dates": "Dec 2021 – May 2022", "bullets": []}]}))

    def test_rules(self):
        from answer import decide
        rtw = decide("ana", "Which statement best describes your right to work?", "select",
                     ["I'm an Australian citizen", "I have a temporary visa with restrictions on work hours (e.g. student visa)",
                      "I require sponsorship to work for a new employer (e.g. 482, 457)"])
        self.assertIn("restrictions on work hours", rtw["answer"])              # never the numeric neighbour
        self.assertEqual(decide("ana", "Are you willing to undergo a medical check?", "radio", ["Yes", "No"])["answer"], "Yes")
        self.assertEqual(decide("ana", "Have you completed a 4WD training course?", "radio", ["Yes", "No"])["answer"], "No")
        self.assertEqual(decide("ana", "How many years of experience as an environmental engineer?", "select",
                                ["Less than 1 year", "1 year", "2 years"])["answer"], "1 year")   # 1.3 → floor
        self.assertIsNone(decide("ana", "Will you require visa sponsorship?", "radio", ["Yes", "No"])["answer"])  # sensitive


class TestRanking(unittest.TestCase):
    T = {"tracks": [{"id": "env", "keywords": {"core": ["monitoring", "sampling", "compliance", "approvals"], "support": []}},
                    {"id": "gis", "title_include": ["gis"],
                     "description_include": {"words": ["gis", "arcgis", "spatial"], "min": 3, "titles": ["officer"]}}],
         "ranking": {"off_field": ["geotechnical"], "preferred_locations": ["Perth"]}}

    def test_reachable_roles_rank_above_senior_and_off_field(self):
        from prepare import dedupe_key, score
        base = {"track": "env", "location": "Perth WA", "listed": "",
                "description": "Environmental monitoring, sampling, compliance reporting and approvals for mining sites."}
        tech = score(base | {"title": "Environmental Technician"}, self.T)
        lead = score(base | {"title": "Team Leader - Environmental Approvals"}, self.T)
        geo = score(base | {"title": "Geotechnical Engineer – Tailings"}, self.T)
        far = score(base | {"title": "Environmental Officer", "description": base["description"] + " Minimum 5 years experience."}, self.T)
        self.assertEqual(tech[2]["prob"], "high")
        self.assertGreater(tech[0], lead[0]); self.assertGreater(tech[0], geo[0]); self.assertGreater(tech[0], far[0])
        self.assertEqual(lead[2]["prob"], "low")
        self.assertEqual(dedupe_key("Environmental Technician (12 Month)", "Yara International"),
                         dedupe_key("Environmental Technician (12 Month)", "Yara Pilbara Fertilisers"))

    def test_letter_uses_the_ads_wording_not_raw_keywords(self):
        # A letter once said "with its focus on gis, spatial" and "with its focus on compliance, mining, audit"
        from prepare import fill_letter
        track = {"keywords": {"core": ["gis", "spatial", "hydrolog", "audit", "compliance"], "support": ["field"]},
                 "letter_focus_fallback": "spatial work"}
        tpl = {"paragraphs": {"why_company": ""}}
        job = {"title": "Land Officer | Bentley | 8/6 Roster", "company": "Example Power", "platform": "seek",
               "description": "Use GIS to interpret spatial and land information. Hydrology studies. Work with auditors. Field work."}
        why = fill_letter(tpl, job, ["gis", "spatial", "hydrolog", "audit", "field"], track)["paragraphs"]["why_company"]
        self.assertIn("The Land Officer role at Example Power, with its focus on GIS and hydrology, matches", why)
        none = fill_letter(tpl, job | {"description": ""}, [], track)["paragraphs"]["why_company"]
        self.assertIn("is the kind of spatial work I have done", none)
        # Tech names keep their own spelling even when the ad writes "java, typescript"
        sw = {"keywords": {"core": ["java", "typescript"]}, "keyword_display": {"java": "Java", "typescript": "TypeScript"}}
        why = fill_letter(tpl, {"title": "Developer", "company": "Demo", "platform": "seek",
                                "description": "Skills: java, typescript."}, ["java", "typescript"], sw)["paragraphs"]["why_company"]
        self.assertIn("with its focus on Java and TypeScript, matches", why)

    def test_track_by_description_and_seniority_range(self):
        from triage import assign_track, judge
        self.assertEqual(assign_track("Fire Planning Officer", self.T["tracks"], "GIS mapping, ArcGIS and spatial data"), "gis")
        self.assertIsNone(assign_track("Fire Planning Officer", self.T["tracks"], "fire behaviour and burns"))
        t = {"exclude_title": ["director"], "tracks": [{"id": "env", "title_include": ["contaminated"]}]}
        self.assertEqual(judge({"title": "Contaminated Land - Scientist to Associate Director"}, t)[0], "env")


class TestPrivacy(unittest.TestCase):
    def test_only_the_fictional_candidate_is_tracked(self):
        r = subprocess.run(["git", "ls-files", "candidates", ".browser"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode:                                   # not a git checkout: nothing can be published from here
            self.skipTest("not a git repository")
        leaked = [f for f in r.stdout.split() if not f.startswith("candidates/example/")]
        self.assertEqual(leaked, [], "personal candidate data is tracked by git")
