"""Profile tab: a candidate's setup at a glance (what is ready, what is missing). Read-only."""
import json
import sys
import unittest

from test_core import Base, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

import candidate_profile as cp  # noqa: E402


def item(p, id_):
    return next(i for i in p["checklist"] if i["id"] == id_)


class TestProfile(Base):
    def put(self, name, data):
        (self.d / name).write_text(json.dumps(data), encoding="utf-8")

    def approve(self, typ, files, status="signed", gid=None):
        import gates
        gid = gid or f"{typ}-01"
        rec = {"id": gid, "type": typ, "status": status, "requested": "2026-11-03T10:00:00+08:00", "description": "t",
               "files": {f: gates.sha(self.d / f) for f in files}, "signed_by": {"by": "agent"}}
        (self.d / "approvals" / f"2026-11-03-{gid}.json").write_text(json.dumps(rec), encoding="utf-8")

    def test_a_new_candidate_shows_what_is_missing_and_how_to_do_it(self):
        p = cp.profile("ana")
        json.dumps(p)                                              # the panel serves it as JSON
        self.assertEqual(item(p, "contact")["status"], "todo")           # the template has no email or phone
        self.assertIn("intake.json", item(p, "contact")["fix"])
        self.assertEqual(item(p, "onboarding")["status"], "todo")
        self.assertIn("/job-onboard", item(p, "onboarding")["fix"])
        self.assertEqual(item(p, "go-live")["status"], "info")           # not sending yet is the default, not a gap
        self.assertEqual(p["progress"]["total"], sum(i["status"] != "info" for i in p["checklist"]))
        self.assertLess(p["progress"]["ok"], p["progress"]["total"])

    def test_every_todo_says_how_to_fix_it(self):
        for i in cp.profile("ana")["checklist"]:
            if i["status"] == "todo":
                self.assertTrue(i["fix"], i["id"])

    def test_contact_complete_turns_the_item_green(self):
        intake = json.loads((self.d / "intake.json").read_text(encoding="utf-8"))
        intake["contact"] |= {"email": "a@example.com", "phone": "0400 000 000"}
        self.put("intake.json", intake)
        self.assertEqual(item(cp.profile("ana"), "contact")["status"], "ok")

    def test_searches_and_the_sources_they_need(self):
        t = json.loads((self.d / "targets.json").read_text(encoding="utf-8"))
        t["tracks"][0]["searches"] = [{"platform": "seek", "keywords": "analyst", "where": None},
                                      {"platform": "linkedin", "keywords": "analyst", "location": "Perth"},
                                      {"platform": "nowhere", "keywords": "x"}]
        self.put("targets.json", t)
        p = cp.profile("ana")
        tr = p["searches"]["tracks"][0]
        self.assertEqual([(s["platform"], s["what"], s["where"]) for s in tr["searches"]],
                         [("seek", "analyst", ""), ("linkedin", "analyst", "Perth"), ("nowhere", "x", "")])
        bad = {s["name"] for s in p["searches"]["sources"] if not (s["known"] and s["configured"])}
        self.assertEqual(bad, {"nowhere"})
        self.assertEqual(item(p, "sources")["status"], "todo")

    def test_a_track_with_no_searches_is_a_todo(self):
        self.assertEqual(item(cp.profile("ana"), "searches")["status"], "todo")

    def test_tracks_may_share_one_master_cv(self):
        t = json.loads((self.d / "targets.json").read_text(encoding="utf-8"))
        t["tracks"] = [dict(t["tracks"][0], id=x, cv="docs/cv_master.json") for x in ("a", "b")]
        self.put("targets.json", t)
        (self.d / "docs").mkdir(exist_ok=True)
        (self.d / "docs" / "cv_master.json").write_text("{}", encoding="utf-8")
        (self.d / "docs" / "cover_letter.json").write_text("{}", encoding="utf-8")
        self.assertEqual(cp.profile("ana")["documents"]["missing"], [])
        self.assertEqual(item(cp.profile("ana"), "documents")["status"], "todo")             # the CV files exist, no master PDF yet
        (self.d / "docs" / "master").mkdir(exist_ok=True)
        (self.d / "docs" / "master" / "Ana_Resume.pdf").write_bytes(b"%PDF")
        self.assertEqual(item(cp.profile("ana"), "documents")["status"], "ok")
        (self.d / "docs" / "cv_master.json").unlink()
        self.assertEqual(cp.profile("ana")["documents"]["missing"], ["docs/cv_master.json"])

    def test_approvals_signed_pending_broken_and_none(self):
        self.approve("master-docs", ["intake.json"])
        self.approve("targets", ["targets.json"], status="pending")
        self.approve("profile-changes", ["facts.json"])
        self.put("facts.json", {"claims": [], "allow": []})                         # changes a sealed file
        got = {a["type"]: a["status"] for a in cp.profile("ana")["approvals"]}
        self.assertEqual(got, {"master-docs": "valid", "profile-changes": "broken", "targets": "pending", "report": "none", "go-live": "none"})
        p = cp.profile("ana")
        self.assertEqual(item(p, "master-docs")["status"], "ok")
        self.assertEqual(item(p, "targets")["status"], "todo")
        self.assertIn("job review ana", item(p, "targets")["fix"])

    def test_go_live_seals_the_targets_so_they_need_no_approval_of_their_own(self):
        self.approve("go-live", ["intake.json", "targets.json"])
        p = cp.profile("ana")
        self.assertEqual(item(p, "targets")["status"], "ok")
        self.assertIn("go-live", item(p, "targets")["detail"])
        self.assertEqual(item(p, "go-live")["status"], "ok")

    def test_empty_answers_are_counted_and_the_sensitive_ones_marked(self):
        self.put("answers.json", {"answers": [{"match": ["right to work"], "answer": None}, {"match": ["notice period"], "answer": "2 weeks"},
                                              {"match": ["fifo"], "answer": ""}]})
        a = cp.profile("ana")["answers"]
        self.assertEqual((a["total"], a["answered"]), (3, 1))
        self.assertEqual([(g["question"], g["sensitive"]) for g in a["unanswered"]], [("right to work", True), ("fifo", False)])
        d = item(cp.profile("ana"), "answers")
        self.assertEqual(d["status"], "todo")
        self.assertIn("2 of 3", d["detail"])
        self.assertIn("1 sensitive", d["detail"])

    def test_improvised_answers_waiting_for_the_person(self):
        self.put("pending_questions.json", {"questions": [{"question": "q", "status": "to-confirm"}, {"question": "r", "status": "confirmed"}]})
        p = cp.profile("ana")
        self.assertEqual(p["answers"]["to_confirm"], 1)
        self.assertEqual(item(p, "confirm")["status"], "todo")

    def test_the_sensitive_answers_are_listed_by_readable_names(self):
        intake = json.loads((self.d / "intake.json").read_text(encoding="utf-8"))
        intake["sensitive_only_if_asked"] = {"_note": "internal", "has_right_to_work": True, "citizen_or_pr": "x"}
        self.put("intake.json", intake)
        self.assertEqual(cp.profile("ana")["rules"]["only_if_asked"], ["citizen or pr", "has right to work"])

    def test_it_never_writes(self):
        before = sorted((p.relative_to(self.d), p.stat().st_mtime_ns) for p in self.d.rglob("*") if p.is_file())
        cp.profile("ana")
        self.assertEqual(before, sorted((p.relative_to(self.d), p.stat().st_mtime_ns) for p in self.d.rglob("*") if p.is_file()))


class TestProfilePanel(Base):
    def test_the_panel_has_a_profile_tab_that_reads_the_endpoint(self):
        import panel
        html = panel.PAGE.read_text(encoding="utf-8")
        self.assertIn('data-view="profile"', html)
        self.assertIn("/api/profile?slug=", html)
        self.assertIn("async function profileView", html)
        self.assertIn('"#perfil": "profile"', html)
        self.assertIn("p: \"profile\"", html)                           # keyboard shortcut P

    def test_the_endpoint_is_documented_and_serves_json(self):
        import panel
        self.assertIn("/api/profile", panel.__doc__)
        import json as _json
        from candidate_profile import profile
        _json.dumps(profile("ana"))


if __name__ == "__main__":
    unittest.main()
