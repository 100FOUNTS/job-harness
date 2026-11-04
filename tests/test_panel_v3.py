"""Panel on the phone (--lan token), the calibration view ("What leads to interviews"), red flags and follow-up badges."""
import contextlib
import datetime
import http.client
import io
import json
import os
import sys
import threading
import unittest
import unittest.mock
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_core import Base  # noqa: E402

TODAY = datetime.date.today()


def ago(days):
    return (TODAY - datetime.timedelta(days=days)).isoformat()


class Server:
    """The real handler on a free local port; requests go through http.client so redirects are not followed."""
    def __init__(self, panel, lan):
        self.panel = panel
        self.patch = unittest.mock.patch.object(panel, "LAN", lan)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)

    def __enter__(self):
        self.patch.start()
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.srv.shutdown(); self.srv.server_close(); self.patch.stop()

    def req(self, method, path, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port, timeout=10)
        try:
            c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()


class PanelBase(Base):
    def setUp(self):
        super().setUp()
        env = unittest.mock.patch.dict(os.environ, {"JOB_PACKAGE_DIR": str(self.tmp / "pkgs")})
        env.start(); self.addCleanup(env.stop)

    def track(self, key, fit=60, status=None, **extra):
        from tracker import add, set_status
        add("ana", {"key": key, "title": f"Role {key}", "company": "Co", "url": "u", "platform": key.split(":")[0], "fit": fit,
                    **({"track": "software"} | extra)})
        for st in ([] if status is None else [status] if isinstance(status, str) else status):
            set_status("ana", key, st)

    def backdate(self, key, days, track_submitted=True):
        from tracker import load, save
        apps = load("ana")
        a = next(a for a in apps if a["key"] == key)
        for h in a["history"]:
            h["date"] = ago(days) + "T09:00:00+00:00"
        if track_submitted and a.get("submitted"):
            a["submitted"] = ago(days)
        save("ana", apps)


class LanTokenTests(PanelBase):
    def test_lan_mode_needs_the_token_everywhere(self):
        import panel
        self.track("seek:1", status="prepared")
        with Server(panel, lan=True) as s:
            for path in ("/", "/api/data?slug=ana", "/api/job?slug=ana&key=seek:1", "/files/ana/x.pdf", "/draft?slug=ana&key=seek:1", "/nope"):
                self.assertEqual(s.req("GET", path)[0], 403, path)
            self.assertEqual(s.req("GET", "/?t=not-the-token")[0], 403)
            self.assertEqual(s.req("GET", "/", {"Cookie": "jh_panel=not-the-token"})[0], 403)
            self.assertEqual(s.req("GET", "/", {"Cookie": f"other={panel.TOKEN}"})[0], 403)
            self.assertEqual(s.req("GET", "/", {"X-Panel-Token": panel.TOKEN})[0], 403)          # the POST header is not a login
            body = s.req("GET", "/")[2]
            self.assertNotIn(panel.TOKEN.encode(), body)                                          # the 403 never leaks it

    def test_token_in_the_link_becomes_a_strict_httponly_cookie_and_leaves_the_url(self):
        import panel
        self.track("seek:1", status="prepared")
        with Server(panel, lan=True) as s:
            code, headers, _ = s.req("GET", f"/?t={panel.TOKEN}&slug=ana")
            self.assertEqual(code, 302)
            self.assertEqual(headers["Location"], "/?slug=ana")                                   # t is dropped from the URL
            cookie = headers["Set-Cookie"]
            self.assertIn(f"jh_panel={panel.TOKEN}", cookie)
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=Strict", cookie)
            self.assertEqual(headers["Referrer-Policy"], "no-referrer")
            jar = {"Cookie": f"jh_panel={panel.TOKEN}"}
            code, _, page = s.req("GET", "/?slug=ana", jar)
            self.assertEqual(code, 200)
            self.assertIn(b"Paste a job link", page)
            self.assertEqual(json.loads(s.req("GET", "/api/data?slug=ana", jar)[2])["slug"], "ana")
            self.assertEqual(s.req("GET", "/api/job?slug=ana&key=seek:1", jar)[0], 200)
            self.assertEqual(s.req("GET", "/files/ana/missing.pdf", jar)[0], 404)                 # authorised, just not there
            code, headers, _ = s.req("GET", f"//evil.test/x?t={panel.TOKEN}")
            self.assertEqual(headers["Location"], "/evil.test/x")                                 # never an open redirect

    def test_posts_in_lan_mode_need_cookie_and_header(self):
        import panel
        from tracker import load
        self.track("seek:1", status="prepared")
        jar, hdr = {"Cookie": f"jh_panel={panel.TOKEN}"}, {"X-Panel-Token": panel.TOKEN}
        post = {"slug": "ana", "key": "seek:1", "status": "applied"}
        with Server(panel, lan=True) as s:
            self.assertEqual(s.req("POST", "/status", None, post)[0], 403)
            self.assertEqual(s.req("POST", "/status", jar, post)[0], 403)
            self.assertEqual(s.req("POST", "/status", hdr, post)[0], 403)
            self.assertEqual(load("ana")[0]["status"], "prepared")
            self.assertEqual(s.req("POST", "/status", jar | hdr, post)[0], 200)                   # Host is the LAN address here: fine
            self.assertEqual(s.req("POST", "/status", jar | hdr | {"Host": "192.168.1.5:8765"}, post | {"status": "prepared"})[0], 200)
        self.assertEqual(load("ana")[0]["status"], "prepared")

    def test_local_mode_is_unchanged(self):
        import panel
        self.track("seek:1", status="prepared")
        with Server(panel, lan=False) as s:
            code, headers, page = s.req("GET", "/")
            self.assertEqual(code, 200)                                                            # no token needed on 127.0.0.1
            self.assertNotIn("Set-Cookie", headers)
            self.assertIn(panel.TOKEN.encode(), page)
            self.assertEqual(s.req("GET", "/api/job?slug=ana&key=seek:1")[0], 200)
            post = {"slug": "ana", "key": "seek:1", "status": "applied"}
            self.assertEqual(s.req("POST", "/status", None, post)[0], 403)
            self.assertEqual(s.req("POST", "/status", {"X-Panel-Token": "x"}, post)[0], 403)
            self.assertEqual(s.req("POST", "/status", {"X-Panel-Token": panel.TOKEN, "Host": "evil.test"}, post)[0], 403)   # DNS rebinding
            self.assertEqual(s.req("POST", "/status", {"X-Panel-Token": panel.TOKEN}, post)[0], 200)
            self.assertTrue(json.loads(s.req("GET", "/api/data?slug=ana")[2])["local"])

    def test_open_folder_is_for_the_computer_itself(self):
        import panel
        self.assertTrue(panel.is_local_client("127.0.0.1", "0.0.0.0"))
        self.assertTrue(panel.is_local_client("::1", "::1"))
        self.assertTrue(panel.is_local_client("192.168.1.5", "192.168.1.5"))                      # the LAN link opened on the same computer
        self.assertFalse(panel.is_local_client("192.168.1.23", "192.168.1.5"))
        self.track("seek:1", status="prepared")
        hdr = {"X-Panel-Token": panel.TOKEN}
        with Server(panel, lan=False) as s, unittest.mock.patch.object(panel.Handler, "local_client", return_value=False), \
                unittest.mock.patch("osutil.open_path") as opener:
            code, _, body = s.req("POST", "/open", hdr, {"slug": "ana", "key": "seek:1"})
            self.assertEqual(code, 403)
            self.assertFalse(json.loads(body)["ok"])
            opener.assert_not_called()
            self.assertFalse(json.loads(s.req("GET", "/api/data?slug=ana")[2])["local"])        # the page hides the button

    def test_token_is_fresh_constant_time_and_printed_once(self):
        import panel
        import secrets
        self.assertGreaterEqual(len(panel.TOKEN), 30)
        self.assertTrue(panel.token_ok(panel.TOKEN))
        self.assertFalse(panel.token_ok("")); self.assertFalse(panel.token_ok(None)); self.assertFalse(panel.token_ok(panel.TOKEN + "x"))
        self.assertFalse(panel.token_ok("é" * 40))                                                # non-ASCII input must not raise

        class FakeServer:
            server_port = 8765
            def __init__(self, addr, handler): FakeServer.addr = addr
            def serve_forever(self): raise KeyboardInterrupt

        for lan in (True, False):
            out = io.StringIO()
            with unittest.mock.patch.object(panel, "ThreadingHTTPServer", FakeServer), unittest.mock.patch.object(panel, "LAN", False), \
                    unittest.mock.patch.object(panel, "lan_ip", return_value="192.168.1.5"), unittest.mock.patch("osutil.open_path"), \
                    unittest.mock.patch.object(sys, "argv", ["panel.py", "--no-open", *(["--lan"] if lan else [])]), contextlib.redirect_stdout(out):
                panel.main()
            if lan:
                self.assertEqual(FakeServer.addr[0], "0.0.0.0")
                self.assertEqual(out.getvalue().count(panel.TOKEN), 1)
                self.assertIn(f"http://192.168.1.5:8765/?t={panel.TOKEN}", out.getvalue())
                self.assertIn("anyone on this wifi", out.getvalue().lower())
            else:
                self.assertEqual(FakeServer.addr[0], "127.0.0.1")
                self.assertNotIn(panel.TOKEN, out.getvalue())
                self.assertNotIn("t=", out.getvalue())


class CalibrationTests(PanelBase):
    def build(self, rows):
        """rows: (fit, platform, track, outcome) with outcome interview | rejected | applied (waiting)."""
        from tracker import set_status
        for i, (fit, plat, tr, out) in enumerate(rows):
            key = f"{plat}:{i}"
            self.track(key, fit=fit, track=tr)
            set_status("ana", key, "applied")
            if out != "applied":
                set_status("ana", key, out)

    def test_below_ten_answers_it_is_an_empty_state_with_the_count(self):
        import panel
        from tracker import load
        self.build([(80, "seek", "software", "interview")] * 3 + [(40, "seek", "data", "rejected")] * 2 + [(70, "seek", "data", "applied")] * 5)
        f = panel.funnel("ana", load("ana"))["calibration"]
        self.assertEqual((f["ready"], f["answered"], f["needed"]), (False, 5, 10))
        self.assertNotIn("by_fit", f)

    def test_silence_after_30_days_counts_as_an_answer(self):
        import panel
        from tracker import calibrate, load
        rows = [(80, "seek", "software", "interview")] * 5 + [(40, "seek", "data", "rejected")] * 4 + [(50, "linkedin", "data", "applied")] * 2
        self.build(rows)
        self.assertEqual(calibrate("ana")["total"]["answered"], 9)
        self.backdate("linkedin:9", 31)
        self.backdate("linkedin:10", 12)                                                          # still waiting
        cal = calibrate("ana")
        self.assertEqual((cal["total"]["answered"], cal["total"]["with_outcome"]), (10, 9))        # with_outcome unchanged for `job track calibrate`
        f = panel.funnel("ana", load("ana"))["calibration"]
        self.assertTrue(f["ready"])
        self.assertEqual(f["by_platform"]["linkedin"], {"sent": 2, "with_outcome": 0, "answered": 1, "interviews": 0,
                                                       "interview_rate": 0.0, "answered_rate": 0.0})

    def test_aggregation_per_track_source_and_fit_band(self):
        import panel
        from tracker import load
        rows = ([(85, "seek", "software", "interview")] * 3 + [(70, "seek", "software", "rejected")] * 1
                + [(65, "linkedin", "software", "interview")] * 1 + [(65, "linkedin", "software", "rejected")] * 1
                + [(45, "linkedin", "data", "rejected")] * 3 + [(30, "seek", "data", "rejected")] * 3)
        self.build(rows)
        c = panel.funnel("ana", load("ana"))["calibration"]
        self.assertTrue(c["ready"])
        self.assertEqual(c["answered"], 12)
        self.assertEqual({k: (r["sent"], r["answered"], r["interviews"]) for k, r in c["by_fit"].items()},
                         {"80-100": (3, 3, 3), "60-79": (3, 3, 1), "40-59": (3, 3, 0), "20-39": (3, 3, 0)})
        self.assertEqual({k: (r["answered"], r["interviews"]) for k, r in c["by_track"].items()}, {"software": (6, 4), "data": (6, 0)})
        self.assertEqual({k: (r["answered"], r["interviews"]) for k, r in c["by_platform"].items()}, {"seek": (7, 3), "linkedin": (5, 1)})

    def test_a_clear_score_band_gives_one_plain_suggestion(self):
        import panel
        from tracker import load
        self.build([(80, "seek", "software", "interview")] * 2 + [(70, "seek", "software", "rejected")] * 2
                   + [(45, "seek", "software", "rejected")] * 3 + [(30, "seek", "software", "rejected")] * 3 + [(70, "seek", "software", "interview")])
        hint = panel.funnel("ana", load("ana"))["calibration"]["hint"]
        self.assertIn("scores 60+", hint)
        self.assertIn("applying less below 60", hint)
        self.assertEqual(hint.count("\n"), 0)

    def test_no_suggestion_when_nothing_stands_out(self):
        import panel
        from tracker import load
        rows = [(85, "seek", "software", "interview"), (85, "seek", "software", "rejected")] * 3 + [(30, "linkedin", "software", "interview"), (30, "linkedin", "software", "rejected")] * 3
        self.build(rows)
        self.assertEqual(panel.funnel("ana", load("ana"))["calibration"]["hint"], "")

    def test_a_track_that_clearly_wins_is_named(self):
        import panel
        hint = panel.calibration_hint({
            "by_fit": {"60-79": {"answered": 6, "interviews": 2}, "20-39": {"answered": 6, "interviews": 2}},
            "by_track": {"water": {"answered": 6, "interviews": 4}, "gis": {"answered": 6, "interviews": 0}},
            "by_platform": {"seek": {"answered": 12, "interviews": 4}}})
        self.assertIn("water track", hint)
        self.assertIn("Consider", hint)

    def test_the_page_shows_the_empty_state_and_tables_only_when_ready(self):
        page = (Path(__file__).resolve().parent.parent / "templates" / "panel.html").read_text(encoding="utf-8")
        self.assertIn("What leads to interviews", page)
        self.assertIn("Shows up after ${C.needed} applications with an answer", page)
        self.assertIn("targets change when you approve them", page)


class FlagsAndFollowUpTests(PanelBase):
    def test_follow_up_due_logic(self):
        import panel
        applied = lambda days, **kw: {"status": "applied", "history": [{"date": ago(days) + "T09:00:00", "status": "applied"}], **kw}
        self.assertTrue(panel.follow_up_due(applied(10)))
        self.assertTrue(panel.follow_up_due(applied(25)))
        self.assertFalse(panel.follow_up_due(applied(9)))
        self.assertFalse(panel.follow_up_due({**applied(30), "status": "interview"}))
        self.assertFalse(panel.follow_up_due({**applied(30), "status": "prepared"}))
        chased = applied(30)
        chased["history"].append({"date": ago(2) + "T09:00:00", "status": "applied", "note": "follow-up sent"})   # a newer entry restarts the count
        self.assertFalse(panel.follow_up_due(chased))
        self.assertTrue(panel.follow_up_due({"status": "submitted", "submitted": ago(14), "history": []}))
        self.assertTrue(panel.follow_up_due(applied(5), days=5))

    def test_cards_carry_flags_badge_and_draft_and_absent_fields_are_fine(self):
        import panel
        from tracker import load, save
        self.track("seek:1", status=["prepared", "applied"])              # old, with flags and a draft
        self.track("seek:2", status=["prepared", "applied"])              # old, nothing extra
        self.track("seek:3", status=["prepared"])                         # not sent: no badge even with flags
        self.track("seek:4", status=["prepared", "applied"])              # recent
        for k in ("seek:1", "seek:2"):
            self.backdate(k, 12)
        draft = self.tmp / "followups" / "seek-1.md"
        draft.parent.mkdir(); draft.write_text("Hello, I applied on...", encoding="utf-8")
        apps = load("ana")
        by = {a["key"]: a for a in apps}
        by["seek:1"].update(red_flags=["No salary range", "Asks for 8+ years"], followup_draft=str(draft))
        by["seek:3"].update(red_flags=["Unpaid trial week"])
        by["seek:4"].update(red_flags="not a list", followup_draft=str(self.tmp / "missing.md"))
        save("ana", apps)
        d = {a["key"]: a for a in panel.data("ana")["apps"]}
        self.assertEqual((d["seek:1"]["red_flags"], d["seek:1"]["follow_up"], d["seek:1"]["draft"]),
                         (["No salary range", "Asks for 8+ years"], True, True))
        self.assertEqual((d["seek:2"]["red_flags"], d["seek:2"]["follow_up"], d["seek:2"]["draft"]), ([], True, False))
        self.assertEqual((d["seek:3"]["red_flags"], d["seek:3"]["follow_up"]), (["Unpaid trial week"], False))
        self.assertEqual((d["seek:4"]["red_flags"], d["seek:4"]["follow_up"], d["seek:4"]["draft"]), ([], False, False))   # bad values ignored
        j = panel.detail("ana", "seek:1")
        self.assertEqual(j["red_flags"], ["No salary range", "Asks for 8+ years"])
        self.assertTrue(j["follow_up"])
        self.assertEqual(j["draft_url"], "/draft?slug=ana&key=seek%3A1")
        j2 = panel.detail("ana", "seek:2")
        self.assertEqual((j2["draft_url"], j2["red_flags"]), ("", []))
        self.assertIn("applied for the", j2["draft_text"])                # no draft file: the tracker's generic draft is offered
        self.assertEqual(panel.detail("ana", "seek:4")["draft_text"], "")

    def test_draft_is_served_as_plain_text_only_when_the_tracker_points_to_it(self):
        import panel
        from tracker import load, save
        self.track("seek:1", status=["prepared", "applied"])
        secret = self.tmp / "secret.json"; secret.write_text("{}", encoding="utf-8")
        draft = self.tmp / "d.txt"; draft.write_text("Hi there", encoding="utf-8")
        apps = load("ana"); apps[0]["followup_draft"] = str(draft); save("ana", apps)
        with Server(panel, lan=False) as s:
            code, headers, body = s.req("GET", "/draft?slug=ana&key=seek:1")
            self.assertEqual((code, body), (200, b"Hi there"))
            self.assertTrue(headers["Content-Type"].startswith("text/plain"))
            self.assertEqual(s.req("GET", "/draft?slug=ana&key=seek:99")[0], 404)
            apps = load("ana"); apps[0]["followup_draft"] = str(secret); save("ana", apps)       # not .md/.txt: ignored
            self.assertEqual(s.req("GET", "/draft?slug=ana&key=seek:1")[0], 404)

    def test_relative_draft_paths_resolve_inside_the_package_or_candidate_folder(self):
        import panel
        from tracker import load, save
        self.track("seek:1", status=["prepared", "applied"])
        (self.d / "followups").mkdir()
        (self.d / "followups" / "a.md").write_text("x", encoding="utf-8")
        apps = load("ana"); apps[0]["followup_draft"] = "followups/a.md"; save("ana", apps)
        self.assertEqual(panel.draft_file("ana", load("ana")[0]), (self.d / "followups" / "a.md").resolve())

    def test_the_page_has_the_chip_badge_and_hides_open_folder_off_the_computer(self):
        page = (Path(__file__).resolve().parent.parent / "templates" / "panel.html").read_text(encoding="utf-8")
        for needle in ("⚠ ${a.red_flags.length}", "Follow up</span>", "D.local", "/draft?slug="):
            self.assertIn(needle, page)


if __name__ == "__main__":
    unittest.main()
