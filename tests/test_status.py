"""The one-word state per candidate, its pill in the panel, friendly docs errors and lessons in the session context."""
import io
import json
import os
import sys
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_core import ROOT, Base  # noqa: E402


class State(Base):
    def setUp(self):
        super().setUp()
        import state
        for n in range(6):
            state.set_stage("ana", n, "done")

    def label(self):
        from status import summary
        return summary("ana")["state"]

    def test_setting_up_until_onboarding_is_done(self):
        import state
        state.set_stage("ana", 3, "pending")
        s = self.label()
        self.assertEqual(s["label"], "Setting up")
        self.assertIn("/job-onboard 3 ana", s["action"])

    def test_pending_approval_needs_a_decision(self):
        import gates
        gates.request("ana", "targets", ["targets.json"], "ok")
        s = self.label()
        self.assertEqual(s["label"], "Needs your decision")
        self.assertIn("job review ana", s["action"])

    def test_open_question_needs_a_decision(self):
        import state
        st = state.load_state("ana")
        st["open_questions"].append({"id": "q1", "question": "Who issued it?", "blocks": 4, "status": "open", "date": "x"})
        state.save_state("ana", st)
        s = self.label()
        self.assertEqual(s["label"], "Needs your decision")
        self.assertIn("job ask ana list", s["action"])

    def test_run_lock_means_working_and_a_stale_one_does_not(self):
        from run_prepare import lock_path
        lock = lock_path("ana"); lock.parent.mkdir(exist_ok=True); lock.write_text("1", encoding="utf-8")
        self.assertEqual(self.label()["label"], "Working")
        old = lock.stat().st_mtime - 7 * 3600
        os.utime(lock, (old, old))
        self.assertEqual(self.label()["label"], "Up to date")

    def test_ready_when_todays_package_has_items_to_apply(self):
        import tracker
        tracker.add("ana", {"key": "seek:1", "title": "Officer", "company": "Acme", "url": "u", "platform": "seek",
                            "track": "env", "location": "Perth", "summary": "s"})
        self.assertEqual(self.label()["label"], "Ready")
        tracker.set_status("ana", "seek:1", "applied")
        self.assertEqual(self.label()["label"], "Up to date")

    def test_json_and_text_show_the_state_first(self):
        import status
        buf = io.StringIO()
        with unittest.mock.patch.object(sys, "argv", ["status", "ana"]), redirect_stdout(buf):
            status.main()
        self.assertTrue(buf.getvalue().startswith("• ana: Up to date."), buf.getvalue())

    def test_panel_data_carries_the_pill(self):
        import panel
        d = panel.data("ana")
        self.assertEqual(d["state"]["label"], "Up to date")
        self.assertTrue(d["state"]["why"] and d["state"]["action"])
        self.assertIn('id="state"', panel.PAGE.read_text(encoding="utf-8"))

    def test_coffee_button_defaults_to_100founts_and_can_be_hidden(self):
        import panel
        with unittest.mock.patch.object(panel, "setting", lambda name, default: default):
            self.assertTrue(panel.data("ana")["support_url"].startswith("https://donate.stripe.com/"))
        with unittest.mock.patch.dict(os.environ, {"JOB_SUPPORT_URL": ""}):
            self.assertEqual(panel.data("ana")["support_url"], "")


class DocsErrors(Base):
    def test_missing_node_gives_one_line(self):
        import docs
        with unittest.mock.patch("docs.shutil.which", return_value=None):
            with self.assertRaises(SystemExit) as c:
                docs.build("ana", Path("cv.json"), "cv", None, None)
        self.assertEqual(str(c.exception), "Can't build documents: run `job setup` (needs Node.js 20+).")

    def test_missing_node_modules_gives_the_same_line(self):
        import docs
        with unittest.mock.patch("docs.shutil.which", return_value="/usr/bin/node"), \
                unittest.mock.patch("docs.tools_dir", return_value=self.tmp):
            with self.assertRaises(SystemExit) as c:
                docs.need_node()
        self.assertIn("run `job setup`", str(c.exception))


class Lessons(Base):
    def setUp(self):
        super().setUp()
        import learn
        self.log = self.tmp / "obs.jsonl"
        self.patch = unittest.mock.patch.object(learn, "LOG", self.log); self.patch.start()
        rows = [{"kind": "platform", "area": "seek", "lesson": f"seek {i}", "candidate": ""} for i in range(7)]
        rows += [{"kind": "platform", "area": "seek", "lesson": "seek dismissed", "candidate": "", "status": "dismissed"},
                 {"kind": "harness", "area": "docs", "lesson": "docs rule", "candidate": ""},
                 {"kind": "candidate", "area": "seek", "lesson": "about a person", "candidate": "ana"}]
        self.log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def tearDown(self):
        self.patch.stop()
        super().tearDown()

    def test_only_active_public_max_five_and_area_match(self):
        import learn
        got = learn.relevant(["seek"])
        self.assertEqual(len(got), 5)
        self.assertTrue(all(g.startswith("seek ") and "dismissed" not in g for g in got))
        self.assertNotIn("about a person", got)

    def test_falls_back_to_harness_lessons(self):
        import learn
        self.assertEqual(learn.relevant(["nothing"]), ["docs rule"])

    def test_context_prints_lesson_lines(self):
        import status
        buf = io.StringIO()
        with unittest.mock.patch.object(sys, "argv", ["status", "--context"]), redirect_stdout(buf):
            status.main()
        lines = [l for l in buf.getvalue().splitlines() if l.startswith("Lesson:")]
        self.assertTrue(1 <= len(lines) <= 5)

    def test_set_status_by_number_and_pattern_keeps_other_lines(self):
        import learn
        before = self.log.read_text(encoding="utf-8").splitlines()
        with unittest.mock.patch.object(sys, "argv", ["learn", "set-status", "1", "applied"]), redirect_stdout(io.StringIO()):
            learn.main()
        after = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(after[0])["status"], "applied")
        self.assertEqual(after[1:], before[1:])

    def test_log_never_stores_a_candidate_on_harness_lessons_and_refuses_personal_data(self):
        import learn
        with unittest.mock.patch.object(sys, "argv", ["learn", "log", "--kind", "harness", "--area", "docs", "--lesson", "x",
                                                      "--candidate", "ana", "--pattern", "p"]), redirect_stdout(io.StringIO()):
            learn.main()
        last = json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((last["candidate"], last["pattern"], last["status"]), ("", "p", "active"))
        name = json.loads((self.d / "intake.json").read_text(encoding="utf-8"))["name"]
        if len(name) >= 5:
            with unittest.mock.patch.object(sys, "argv", ["learn", "log", "--kind", "harness", "--area", "docs",
                                                          "--lesson", f"{name} hated it"]):
                with self.assertRaises(SystemExit):
                    learn.main()


if __name__ == "__main__":
    unittest.main()
