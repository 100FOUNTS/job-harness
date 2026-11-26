"""Remote mode: the password, the login, the session cookie and the rate limit (no cloudflared, no network)."""
import contextlib
import http.client
import io
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_panel_v3 import PanelBase  # noqa: E402

PASSWORD = "correct horse battery"
CF = {"Cf-Connecting-Ip": "203.0.113.5", "Cf-Ray": "abc123-SYD"}      # what a request through the tunnel carries


class FakeStdin:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


class RemoteServer:
    """The real handler on a free local port with remote mode on, a fresh login guard and a temp password file."""
    def __init__(self, panel, auth_path, guard=None):
        self.panel = panel
        self.stack = contextlib.ExitStack()
        self.auth_path, self.guard = auth_path, guard
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)

    def __enter__(self):
        p = self.panel
        self.stack.enter_context(unittest.mock.patch.object(p, "REMOTE", True))
        self.stack.enter_context(unittest.mock.patch.object(p, "LAN", False))
        self.stack.enter_context(unittest.mock.patch.object(p, "LOGIN_DELAY", 0))
        self.stack.enter_context(unittest.mock.patch.object(p, "SLOW_DELAY", 0))
        self.stack.enter_context(unittest.mock.patch.dict(p.SESSION_CRED, clear=True))
        self.stack.enter_context(unittest.mock.patch.object(p, "LOGIN", self.guard or p.LoginGuard()))
        self.stack.enter_context(unittest.mock.patch.object(p, "auth_file", lambda: self.auth_path))
        self.stack.enter_context(unittest.mock.patch.dict(p.SESSIONS, clear=True))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.srv.shutdown(); self.srv.server_close(); self.stack.close()

    def raw(self, method, path, headers=None, data=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port, timeout=10)
        try:
            c.request(method, path, body=data, headers=headers or {})
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()

    def req(self, method, path, headers=None, body=None):
        return self.raw(method, path, headers, json.dumps(body).encode() if body is not None else None)

    def login(self, password, headers=None):
        form = urllib.parse.urlencode({"password": password}).encode()
        return self.raw("POST", "/login", {"Content-Type": "application/x-www-form-urlencoded", **(headers or CF)}, form)

    def session(self, headers=None):
        code, h, _ = self.login(PASSWORD, headers)
        assert code == 303, code
        return h["Set-Cookie"].split(";")[0]               # jh_sess=<id>


class RemoteBase(PanelBase):
    def setUp(self):
        super().setUp()
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, ignore_errors=True))
        import panel
        self.panel = panel
        self.auth = self.home / ".config" / "job-harness" / "panel_auth.json"
        panel_rec = panel.hash_password(PASSWORD)
        self.auth.parent.mkdir(parents=True)
        self.auth.write_text(json.dumps(panel_rec))

    def server(self, **kw):
        return RemoteServer(self.panel, self.auth, **kw)


class PasswordTests(RemoteBase):
    def run_set(self, tty, answers=(), typed=()):
        import panel
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(sys, "stdin", FakeStdin(tty)), \
                unittest.mock.patch.object(Path, "home", return_value=self.home), \
                unittest.mock.patch("builtins.input", side_effect=list(answers)), \
                unittest.mock.patch("getpass.getpass", side_effect=list(typed)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = panel.set_password()
        return code, out.getvalue(), err.getvalue()

    def test_refuses_without_a_terminal(self):
        self.auth.unlink()
        code, out, err = self.run_set(False, typed=["whatever password"] * 2)
        self.assertEqual(code, 2)
        self.assertIn("interactive terminal", err)
        self.assertFalse(self.auth.exists())

    def test_sets_a_hashed_password_with_private_modes(self):
        self.auth.unlink()
        secret = "an even longer secret"
        code, out, err = self.run_set(True, typed=[secret, secret])
        self.assertEqual(code, 0)
        text = self.auth.read_text()
        self.assertNotIn(secret, text + out + err)                         # never stored or printed
        rec = json.loads(text)
        if hasattr(hashlib, "scrypt"):
            self.assertEqual((rec["algo"], rec["n"], rec["r"], rec["p"], rec["dklen"]), ("scrypt", 2 ** 14, 8, 1, 32))
        else:                                                              # macOS's Python 3.9 (LibreSSL): no scrypt
            self.assertEqual((rec["algo"], rec["iterations"]), ("pbkdf2_sha256", self.panel.PBKDF2_ITERATIONS))
        self.assertEqual(len(bytes.fromhex(rec["salt"])), 16)
        self.assertTrue(self.panel.verify_password(secret, rec))
        if sys.platform != "win32":
            self.assertEqual(stat.S_IMODE(self.auth.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.auth.parent.stat().st_mode), 0o700)

    def test_pbkdf2_fallback_round_trip(self):
        rec = self.panel.hash_password("correct horse battery", algo="pbkdf2_sha256")
        self.assertEqual(rec["algo"], "pbkdf2_sha256")
        self.assertTrue(self.panel.verify_password("correct horse battery", rec))
        self.assertFalse(self.panel.verify_password("wrong horse battery", rec))
        self.assertFalse(self.panel.verify_password("correct horse battery", rec | {"iterations": 10}))   # weakened record: no

    def test_short_or_mismatched_passwords_are_refused(self):
        self.auth.unlink()
        self.assertEqual(self.run_set(True, typed=["short"])[0], 1)
        self.assertEqual(self.run_set(True, typed=["a long enough one", "a different one!!"])[0], 1)
        self.assertFalse(self.auth.exists())

    def test_overwriting_asks_first(self):
        before = self.auth.read_text()
        code, out, _ = self.run_set(True, answers=["n"], typed=["x" * 12, "x" * 12])
        self.assertEqual(code, 1)
        self.assertEqual(self.auth.read_text(), before)
        code, _, _ = self.run_set(True, answers=["y"], typed=["x" * 12, "x" * 12])
        self.assertEqual(code, 0)
        self.assertTrue(self.panel.verify_password("x" * 12, json.loads(self.auth.read_text())))

    def test_hash_round_trip_and_garbage(self):
        p = self.panel
        rec = p.hash_password("some password here")
        self.assertTrue(p.verify_password("some password here", rec))
        self.assertFalse(p.verify_password("some password herf", rec))
        self.assertNotEqual(p.hash_password("some password here")["hash"], rec["hash"])      # new salt every time
        weak = rec | ({"n": 2 ** 40} if rec["algo"] == "scrypt" else {"iterations": 10 ** 12})        # out-of-range cost
        for bad in (None, {}, {"n": "x"}, rec | {"hash": "zz"}, weak, rec | {"salt": 5}):
            self.assertFalse(p.verify_password("some password here", bad))
        self.assertFalse(p.verify_password("\ud800", rec))                  # not encodable: no crash


class TunnelTests(unittest.TestCase):
    def test_parse_tunnel_url(self):
        import panel
        line = "2026-11-26T04:00:00Z INF |  https://quiet-river-9f3a.trycloudflare.com                      |"
        self.assertEqual(panel.parse_tunnel_url(line), "https://quiet-river-9f3a.trycloudflare.com")
        self.assertEqual(panel.parse_tunnel_url("visit HTTPS://Odd-Name.TryCloudflare.com/x"), "https://odd-name.trycloudflare.com")
        self.assertIsNone(panel.parse_tunnel_url("Requesting new quick Tunnel on https://api.trycloudflare.com..."))
        self.assertIsNone(panel.parse_tunnel_url("https://example.com and http://x.trycloudflare.com"))
        self.assertIsNone(panel.parse_tunnel_url("https://trycloudflare.com"))
        self.assertIsNone(panel.parse_tunnel_url(""))

    def fake(self, text, running=True):
        return unittest.mock.Mock(stdout=io.StringIO(text), poll=lambda: None if running else 1)

    def test_read_tunnel_url_finds_it_among_noise(self):
        import panel
        text = "INF Requesting new quick Tunnel on https://api.trycloudflare.com\nINF |  https://a-b-c.trycloudflare.com  |\nmore\n"
        self.assertEqual(panel.read_tunnel_url(self.fake(text), timeout=5), "https://a-b-c.trycloudflare.com")

    def test_read_tunnel_url_failure_shows_the_last_lines(self):
        import panel
        with self.assertRaises(panel.TunnelError) as cm:
            panel.read_tunnel_url(self.fake("ERR failed to dial\nERR no route\n", running=False), timeout=5)
        self.assertIn("no route", str(cm.exception))

    def test_read_tunnel_url_times_out(self):
        import panel
        r, w = os.pipe()
        with os.fdopen(r, "r") as rf, os.fdopen(w, "w") as wf:
            proc = unittest.mock.Mock(stdout=rf, poll=lambda: None)
            wf.write("INF starting\n"); wf.flush()
            t0 = time.time()
            with self.assertRaises(panel.TunnelError) as cm:
                panel.read_tunnel_url(proc, timeout=0.5)
            self.assertLess(time.time() - t0, 5)
            self.assertIn("starting", str(cm.exception))

    def test_start_tunnel_needs_cloudflared(self):
        import panel
        with unittest.mock.patch.object(panel.shutil, "which", return_value=None):
            with self.assertRaises(panel.TunnelError) as cm:
                panel.start_tunnel(8765)
        self.assertIn("brew install cloudflared", str(cm.exception))

    def test_remote_refuses_without_password_or_cloudflared(self):
        import panel
        with tempfile.TemporaryDirectory() as d:
            with unittest.mock.patch.object(panel, "auth_file", lambda: Path(d) / "none.json"):
                with self.assertRaises(SystemExit) as cm:
                    panel.run_remote(0)
                self.assertIn("--set-password", str(cm.exception))
            (Path(d) / "a.json").write_text(json.dumps(panel.hash_password("long enough pw")))
            with unittest.mock.patch.object(panel, "auth_file", lambda: Path(d) / "a.json"), \
                    unittest.mock.patch.object(panel.shutil, "which", return_value=None):
                with self.assertRaises(SystemExit) as cm:
                    panel.run_remote(0)
                self.assertIn("cloudflared", str(cm.exception))
        self.assertFalse(panel.REMOTE)

    def test_remote_and_lan_cannot_be_combined(self):
        import panel
        with unittest.mock.patch.object(sys, "argv", ["panel", "--remote", "--lan"]), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                panel.main()
        self.assertEqual(cm.exception.code, 2)


class RemoteHttpTests(RemoteBase):
    def test_no_session_means_the_login_page(self):
        self.track("seek:1", status="prepared")
        with self.server() as s:
            for path in ("/", "/api/data?slug=ana", "/api/job?slug=ana&key=seek:1", "/files/ana/x.pdf", "/api/visits?slug=ana", "/nope"):
                code, h, body = s.raw("GET", path, CF)
                self.assertEqual((code, h.get("Location")), (303, "/login"), path)
                self.assertNotIn(self.panel.TOKEN.encode(), body)
            self.assertEqual(s.raw("GET", "/favicon.ico", CF)[0], 404)
            code, h, page = s.raw("GET", "/login", CF)
            self.assertEqual(code, 200)
            self.assertIn(b'autocomplete="current-password"', page)
            self.assertNotIn(b"http://", page); self.assertNotIn(b"https://", page); self.assertNotIn(b"<script", page)
            self.assertEqual(h["Cache-Control"], "no-store")
            self.assertEqual(h["X-Frame-Options"], "DENY")

    def test_wrong_password_is_401_and_generic(self):
        with self.server() as s:
            code, h, body = s.login("nope nope nope")
            self.assertEqual(code, 401)
            self.assertNotIn("Set-Cookie", h)
            self.assertIn(b"not right", body)
            self.assertEqual(s.login("")[0], 401)

    def test_sixth_failure_is_429_and_even_the_right_password_waits(self):
        with self.server() as s:
            for _ in range(5):
                self.assertEqual(s.login("wrong wrong")[0], 401)
            code, h, _ = s.login("wrong wrong")
            self.assertEqual(code, 429)
            self.assertGreater(int(h["Retry-After"]), 0)
            self.assertEqual(s.login(PASSWORD)[0], 429)
            self.assertEqual(s.login(PASSWORD, {"Cf-Connecting-Ip": "198.51.100.7"})[0], 303)      # another client is not locked

    def test_global_failures_never_lock_the_right_password_out(self):
        g = self.panel.LoginGuard(total=3)
        with self.server(guard=g) as s:
            for i in range(3):
                self.assertEqual(s.login("wrong wrong", {"Cf-Connecting-Ip": f"198.51.100.{i}"})[0], 401)
            self.assertFalse(g.throttled())                                # 3 is not more than 3
            self.assertEqual(s.login("wrong wrong", {"Cf-Connecting-Ip": "198.51.100.99"})[0], 401)   # still a normal 401, not 429
            self.assertTrue(g.throttled())
            for i in range(20):                                            # an attacker with the address cannot lock the owner out
                self.assertEqual(s.login("wrong wrong", {"Cf-Connecting-Ip": f"192.0.2.{i}"})[0], 401)
            code, h, _ = s.login(PASSWORD, {"Cf-Connecting-Ip": "198.51.100.98"})
            self.assertEqual(code, 303)
            self.assertIn("jh_sess=", h["Set-Cookie"])

    def test_throttled_checks_are_serialised_and_slow(self):
        p = self.panel
        g = p.LoginGuard(total=1)
        with self.server(guard=g) as s, unittest.mock.patch.object(p, "SLOW_DELAY", 0.25):
            s.login("wrong wrong", {"Cf-Connecting-Ip": "198.51.100.1"})
            s.login("wrong wrong", {"Cf-Connecting-Ip": "198.51.100.2"})
            self.assertTrue(g.throttled())
            codes, t0 = [], time.time()
            ts = [threading.Thread(target=lambda i=i: codes.append(s.login("wrong wrong", {"Cf-Connecting-Ip": f"203.0.113.{i}"})[0]))
                  for i in range(4)]
            [t.start() for t in ts]; [t.join() for t in ts]
            self.assertEqual(codes, [401] * 4)
            self.assertGreaterEqual(time.time() - t0, 4 * 0.25 - 0.05)     # one at a time: 4 guesses take at least 4 delays

    def test_password_checks_run_at_most_PW_CHECKS_at_once(self):
        p = self.panel
        running, peak, lock = [0], [0], threading.Lock()

        def slow_verify(password, rec):
            with lock:
                running[0] += 1; peak[0] = max(peak[0], running[0])
            time.sleep(0.05)
            with lock:
                running[0] -= 1
            return False
        with self.server() as s, unittest.mock.patch.object(p, "verify_password", slow_verify):
            ts = [threading.Thread(target=s.login, args=("wrong wrong", {"Cf-Connecting-Ip": f"203.0.113.{i}"})) for i in range(14)]
            [t.start() for t in ts]; [t.join() for t in ts]
        self.assertGreaterEqual(peak[0], 2)
        self.assertLessEqual(peak[0], p.PW_CHECKS)

    def test_a_busy_check_queue_is_429_and_not_counted_as_a_failure(self):
        p = self.panel
        g = p.LoginGuard()
        with self.server(guard=g) as s, unittest.mock.patch.object(p, "PW_WAIT", 0.05):
            held = [p.PW_SLOTS.acquire() for _ in range(p.PW_CHECKS)]
            try:
                code, h, _ = s.login(PASSWORD)
            finally:
                for _ in held:
                    p.PW_SLOTS.release()
            self.assertEqual((code, h["Retry-After"]), (429, "5"))
            self.assertEqual(g.ips["203.0.113.5"], [])
            self.assertEqual(s.login(PASSWORD)[0], 303)

    def test_failures_expire(self):
        g = self.panel.LoginGuard(per_ip=2)
        with unittest.mock.patch.object(self.panel.time, "time", return_value=1000.0):
            self.assertEqual(g.begin("a")[0], 0); self.assertEqual(g.begin("a")[0], 0)
            self.assertGreater(g.begin("a")[0], 0)
        with unittest.mock.patch.object(self.panel.time, "time", return_value=1000.0 + 901):
            self.assertEqual(g.begin("a")[0], 0)

    def test_success_sets_a_secure_session_cookie_and_it_works(self):
        self.track("seek:1", status="prepared")
        with self.server() as s:
            code, h, _ = s.login(PASSWORD)
            self.assertEqual((code, h["Location"]), (303, "/"))
            cookie = h["Set-Cookie"]
            for part in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/", "Max-Age=1209600"):
                self.assertIn(part, cookie)
            sid = cookie.split(";")[0].split("=", 1)[1]
            self.assertGreaterEqual(len(sid), 40)
            self.assertNotIn(sid, list(self.panel.SESSIONS))               # only a hash is kept
            jar = {**CF, "Cookie": f"jh_sess={sid}"}
            code, _, page = s.raw("GET", "/", jar)
            self.assertEqual(code, 200)
            self.assertIn(self.panel.TOKEN.encode(), page)
            data = json.loads(s.raw("GET", "/api/data?slug=ana", jar)[2])
            self.assertEqual((data["local"], data["remote"]), (False, True))
            self.assertEqual(s.raw("GET", "/login", jar)[0], 303)
            self.assertEqual(s.raw("GET", "/", {**CF, "Cookie": "jh_sess=forged"})[0], 303)
            self.assertEqual(s.raw("GET", "/", {**CF, "Cookie": f"jh_panel={self.panel.TOKEN}"})[0], 303)   # the LAN cookie is no session

    def test_changing_the_password_ends_every_session(self):
        p = self.panel
        with self.server() as s:
            cookie = s.session()
            jar = {**CF, "Cookie": cookie}
            self.assertEqual(s.raw("GET", "/api/data?slug=ana", jar)[0], 200)
            self.assertEqual(s.raw("GET", "/api/data?slug=ana", jar)[0], 200)      # (second read: the cached auth file)
            with unittest.mock.patch.object(p, "auth_file", lambda: self.auth):
                p.save_auth(p.hash_password("a brand new password"))
            self.assertEqual(s.raw("GET", "/", jar), (303, unittest.mock.ANY, unittest.mock.ANY))
            self.assertEqual(s.req("POST", "/status", jar | {"X-Panel-Token": p.TOKEN}, {"slug": "ana"})[0], 401)
            self.assertEqual(p.SESSIONS, {})
            self.assertEqual(s.login(PASSWORD)[0], 401)                        # the old password is gone too
            new = s.login("a brand new password")
            self.assertEqual(new[0], 303)
            self.assertEqual(s.raw("GET", "/", {**CF, "Cookie": new[1]["Set-Cookie"].split(";")[0]})[0], 200)

    def test_removing_the_auth_file_ends_sessions(self):
        with self.server() as s:
            jar = {**CF, "Cookie": s.session()}
            self.assertEqual(s.raw("GET", "/", jar)[0], 200)
            self.auth.unlink()
            self.assertEqual(s.raw("GET", "/", jar)[0], 303)

    def test_the_auth_file_is_not_re_read_on_every_request(self):
        p = self.panel
        with self.server() as s:
            jar = {**CF, "Cookie": s.session()}
            with unittest.mock.patch.object(p, "load_auth", wraps=p.load_auth) as la:
                for _ in range(5):
                    self.assertEqual(s.raw("GET", "/api/data?slug=ana", jar)[0], 200)
            self.assertEqual(la.call_count, 0)

    def test_expired_session_is_rejected(self):
        with self.server() as s:
            cookie = s.session()
            self.assertEqual(s.raw("GET", "/", {**CF, "Cookie": cookie})[0], 200)
            for k in list(self.panel.SESSIONS):
                self.panel.SESSIONS[k] = time.time() - 1
            self.assertEqual(s.raw("GET", "/", {**CF, "Cookie": cookie})[0], 303)
            self.assertEqual(self.panel.SESSIONS, {})

    def test_session_lifetime_is_fourteen_days(self):
        with self.server() as s:
            s.session()
            (exp,) = self.panel.SESSIONS.values()
            self.assertAlmostEqual(exp - time.time(), 14 * 24 * 3600, delta=60)

    def test_remote_posts_need_session_and_token(self):
        from tracker import load
        self.track("seek:1", status="prepared")
        post = {"slug": "ana", "key": "seek:1", "status": "applied"}
        with self.server() as s:
            cookie = s.session()
            jar, hdr = {**CF, "Cookie": cookie}, {"X-Panel-Token": self.panel.TOKEN}
            code, _, body = s.req("POST", "/status", CF | hdr, post)
            self.assertEqual(code, 401)                                    # a token alone is no login
            self.assertEqual(json.loads(body)["ok"], False)
            self.assertEqual(s.req("POST", "/status", jar, post)[0], 403)  # a session alone is not enough
            self.assertEqual(s.req("POST", "/status", jar | {"X-Panel-Token": "x"}, post)[0], 403)
            self.assertEqual(load("ana")[0]["status"], "prepared")
            self.assertEqual(s.req("POST", "/status", jar | hdr, post)[0], 200)
            self.assertEqual(load("ana")[0]["status"], "applied")
            self.assertEqual(s.req("PUT", "/status", CF, post)[0], 401)

    def test_open_folder_is_refused_for_remote_clients(self):
        self.track("seek:1", status="prepared")
        with self.server() as s:
            jar = {**CF, "Cookie": s.session(), "X-Panel-Token": self.panel.TOKEN}
            with unittest.mock.patch.object(self.panel, "open_folder") as op:
                code, _, body = s.req("POST", "/open", jar, {"slug": "ana", "key": "seek:1"})
            self.assertEqual(code, 403)
            self.assertFalse(json.loads(body)["ok"])
            op.assert_not_called()

    def test_logout_ends_the_session(self):
        with self.server() as s:
            cookie = s.session()
            jar, hdr = {**CF, "Cookie": cookie}, {"X-Panel-Token": self.panel.TOKEN}
            self.assertEqual(s.req("POST", "/logout", jar, {})[0], 403)    # CSRF: needs the token
            self.assertEqual(s.raw("GET", "/", jar)[0], 200)
            code, h, _ = s.req("POST", "/logout", jar | hdr, {})
            self.assertEqual(code, 200)
            self.assertIn("Max-Age=0", h["Set-Cookie"])
            self.assertEqual(s.raw("GET", "/", jar)[0], 303)
            self.assertEqual(s.req("POST", "/status", jar | hdr, {"slug": "ana"})[0], 401)

    def test_login_body_is_capped(self):
        with self.server() as s:
            code, _, _ = s.raw("POST", "/login", {**CF, "Content-Type": "application/x-www-form-urlencoded"},
                               b"password=" + b"a" * 5000)
            self.assertEqual(code, 413)

    def test_local_requests_are_unchanged_in_remote_mode(self):
        self.track("seek:1", status="prepared")
        with self.server() as s:
            code, h, page = s.raw("GET", "/")                              # no Cloudflare header, Host 127.0.0.1
            self.assertEqual(code, 200)
            self.assertNotIn("Set-Cookie", h)
            data = json.loads(s.raw("GET", "/api/data?slug=ana")[2])
            self.assertEqual((data["local"], data["remote"]), (True, False))
            post = {"slug": "ana", "key": "seek:1", "status": "applied"}
            self.assertEqual(s.req("POST", "/status", None, post)[0], 403)
            self.assertEqual(s.req("POST", "/status", {"X-Panel-Token": self.panel.TOKEN}, post)[0], 200)
            self.assertEqual(s.req("POST", "/status", {"X-Panel-Token": self.panel.TOKEN, "Host": "evil.test"}, post)[0], 401)

    def test_a_foreign_host_counts_as_remote(self):
        with self.server() as s:
            code, h, _ = s.raw("GET", "/", {"Host": "quiet-river.trycloudflare.com"})
            self.assertEqual((code, h["Location"]), (303, "/login"))
            self.assertEqual(s.raw("GET", "/", {"X-Forwarded-For": "1.2.3.4"})[0], 303)

    def test_active_files_are_served_sandboxed(self):
        root = self.tmp / "pkgs" / "ana" / "2026-11-26"
        root.mkdir(parents=True)
        for name in ("a.html", "b.HTM", "c.svg", "d.xhtml", "e.pdf", "f.md"):
            (root / name).write_bytes(b"<script>alert(1)</script>")
        with self.server() as s:
            for name in ("a.html", "b.HTM", "c.svg", "d.xhtml"):
                code, h, body = s.raw("GET", f"/files/ana/2026-11-26/{name}")
                self.assertEqual(code, 200, name)
                self.assertEqual(h["Content-Security-Policy"], "sandbox", name)      # no allow-scripts, no allow-same-origin
                self.assertEqual(h["X-Content-Type-Options"], "nosniff")
            for name in ("e.pdf", "f.md"):
                self.assertNotIn("Content-Security-Policy", s.raw("GET", f"/files/ana/2026-11-26/{name}")[1], name)

    def test_without_remote_mode_nothing_changes(self):
        import panel
        from test_panel_v3 import Server
        with Server(panel, lan=False) as s:
            self.assertEqual(s.req("GET", "/", CF)[0], 200)                # headers mean nothing when remote mode is off
            self.assertEqual(s.req("GET", "/login")[0], 404)


if __name__ == "__main__":
    unittest.main()
