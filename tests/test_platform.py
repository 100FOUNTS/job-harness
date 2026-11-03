"""Windows / Linux / macOS differences: all mocked, nothing touches the real OS."""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_core import Base, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import osutil  # noqa: E402


def on(platform):
    return mock.patch.object(sys, "platform", platform)


def ok(rc=0):
    return mock.Mock(returncode=rc, stdout="", stderr="")


class TestOsutil(unittest.TestCase):
    def test_python_is_current_interpreter(self):
        self.assertEqual(osutil.python(), [sys.executable])

    def test_open_path_per_os(self):
        for platform, cmd in (("darwin", "open"), ("linux", "xdg-open")):
            with on(platform), mock.patch("subprocess.run", return_value=ok()) as run:
                self.assertTrue(osutil.open_path("/x/y"))
                self.assertEqual(run.call_args[0][0], [cmd, "/x/y"])
        with on("win32"), mock.patch.object(os, "startfile", create=True) as start:
            self.assertTrue(osutil.open_path("C:\\x"))
            start.assert_called_once_with("C:\\x")

    def test_open_path_never_raises(self):
        with on("linux"), mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(osutil.open_path("/x"))
        with on("win32"), mock.patch.object(os, "startfile", create=True, side_effect=OSError):
            self.assertFalse(osutil.open_path("C:\\x"))

    def test_notify_mac_passes_text_as_arguments(self):
        title, msg = 'Job "harness": ana', 'say "hi" \\ 3 sent'
        with on("darwin"):
            argv, env = osutil.notify_command(title, msg)
        self.assertEqual(argv[0], "osascript")
        self.assertEqual(argv[-2:], [title, msg])
        self.assertNotIn(msg, " ".join(argv[:-2]))
        self.assertIsNone(env)

    def test_notify_windows_uses_powershell_with_env_text(self):
        with on("win32"):
            argv, env = osutil.notify_command("T", "2 sent")
        self.assertEqual(argv[:3], ["powershell", "-NoProfile", "-NonInteractive"])
        self.assertIn("ToastNotificationManager", argv[-1])
        self.assertIn("NotifyIcon", argv[-1])
        self.assertEqual(env, {"JOB_NOTIFY_TITLE": "T", "JOB_NOTIFY_MSG": "2 sent"})

    def test_notify_linux_needs_notify_send(self):
        with on("linux"), mock.patch("shutil.which", return_value="/usr/bin/notify-send"):
            self.assertEqual(osutil.notify_command("T", "m")[0], ["notify-send", "T", "m"])
        with on("linux"), mock.patch("shutil.which", return_value=None):
            self.assertIsNone(osutil.notify_command("T", "m"))
            self.assertFalse(osutil.notify("T", "m"))

    def test_notify_returns_false_when_the_tool_fails(self):
        with on("darwin"), mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(osutil.notify("T", "m"))

    def test_chrome_mac_uses_open(self):
        with on("darwin"), mock.patch("subprocess.Popen") as popen:
            self.assertTrue(osutil.open_chrome("https://x", "/p"))
        self.assertEqual(popen.call_args[0][0], ["open", "-na", "Google Chrome", "--args", "--user-data-dir=/p", "https://x"])

    def test_chrome_windows_install_paths(self):
        tmp = Path(tempfile.mkdtemp())
        exe = tmp / "pf86/Google/Chrome/Application/chrome.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        env = {"ProgramFiles": str(tmp / "pf"), "ProgramFiles(x86)": str(tmp / "pf86")}
        with on("win32"), mock.patch.dict(os.environ, env), mock.patch("subprocess.Popen") as popen:
            os.environ.pop("LocalAppData", None)
            self.assertTrue(osutil.open_chrome("https://x", "C:\\p"))
        self.assertEqual(popen.call_args[0][0], [str(exe), "--user-data-dir=C:\\p", "https://x"])

    def test_chrome_linux_tries_known_names_and_missing_is_false(self):
        found = {"chromium": "/usr/bin/chromium"}
        with on("linux"), mock.patch("shutil.which", side_effect=found.get), mock.patch("subprocess.Popen") as popen:
            self.assertTrue(osutil.open_chrome("https://x", "/p"))
        self.assertEqual(popen.call_args[0][0], ["/usr/bin/chromium", "--user-data-dir=/p", "https://x"])
        with on("linux"), mock.patch("shutil.which", return_value=None), mock.patch("subprocess.Popen") as popen:
            self.assertFalse(osutil.open_chrome("https://x", "/p"))
            popen.assert_not_called()


class TestSchedulePrint(Base):
    def printed(self, platform, *args, which=None):
        import schedule
        out = io.StringIO()
        with on(platform), mock.patch("shutil.which", return_value=which), mock.patch("sys.argv", ["schedule.py", *args, "--print"]), \
                mock.patch("subprocess.run") as run, mock.patch("subprocess.Popen") as popen, contextlib.redirect_stdout(out):
            schedule.main()
        run.assert_not_called()
        popen.assert_not_called()
        return out.getvalue()

    def test_macos_keeps_the_launchd_plist_on_the_sh_wrapper(self):
        with mock.patch("os.getuid", create=True, return_value=501):
            text = self.printed("darwin", "install", "ana", "--hour", "7", "--minute", "30")
        self.assertIn("com.jobharness.daily.ana.plist", text)
        self.assertIn("<string>/bin/zsh</string>", text)
        self.assertIn("scripts/run_prepare.sh", text)
        self.assertIn("<key>Hour</key><integer>7</integer>", text)
        self.assertIn("launchctl bootstrap gui/501", text)

    def test_windows_creates_a_daily_task(self):
        text = self.printed("win32", "install", "ana", "--hour", "7", "--minute", "5")
        self.assertIn("schtasks /Create /SC DAILY /ST 07:05 /TN JobHarness-ana /TR", text)
        self.assertIn("run_prepare.py", text)
        self.assertTrue(text.rstrip().endswith("/F"))

    def test_linux_systemd_timer(self):
        text = self.printed("linux", "install", "ana", "--hour", "6", "--minute", "15", which="/usr/bin/systemctl")
        self.assertIn(".config/systemd/user/job-harness-ana.service", text)
        self.assertIn("OnCalendar=*-*-* 06:15:00", text)
        self.assertIn("run_prepare.py", text)
        self.assertIn("systemctl --user enable --now job-harness-ana.timer", text)

    def test_linux_without_systemd_prints_crontab_line(self):
        text = self.printed("linux", "install", "ana", "--hour", "6", "--minute", "15")
        self.assertIn("crontab -e", text)
        self.assertRegex(text, r"15 6 \* \* \* cd .*run_prepare\.py ana")

    def test_agent_runner_points_at_run_daily(self):
        self.assertIn("run_daily.py", self.printed("win32", "install", "ana", "--runner", "agent"))

    def test_run_now_uses_our_interpreter_not_zsh(self):
        text = self.printed("linux", "run-now", "ana")
        self.assertIn(sys.executable, text)
        self.assertIn("run_prepare.py ana", text)
        self.assertNotIn("zsh", text)

    def test_status_and_uninstall_commands(self):
        self.assertIn("schtasks /Query /TN JobHarness-ana", self.printed("win32", "status", "ana"))
        self.assertIn("schtasks /Delete /TN JobHarness-ana /F", self.printed("win32", "uninstall", "ana"))
        self.assertIn("systemctl --user disable --now job-harness-ana.timer", self.printed("linux", "uninstall", "ana"))


class TestRunPrepare(Base):
    def setUp(self):
        super().setUp()
        import run_prepare
        self.rp = run_prepare
        self.log = self.d / "logs" / f"{run_prepare.today()}.log"
        env = mock.patch.dict(os.environ, {"JOB_PREPARE_MAX": "7"})
        env.start()
        self.addCleanup(env.stop)
        root = mock.patch.object(run_prepare, "ROOT", self.tmp / "no-repo-stop")
        root.start()
        self.addCleanup(root.stop)

    def run_it(self, results=None):
        calls = []

        def fake(cmd, **kw):
            calls.append([Path(cmd[1]).stem, *cmd[2:]])
            return ok((results or {}).get(Path(cmd[1]).stem, 0))
        with mock.patch.object(self.rp.subprocess, "run", side_effect=fake):
            self.rp.guarded("ana", "prepare", self.rp.prepare)
        return calls, self.log.read_text()

    def test_steps_run_in_order_and_failures_do_not_stop_the_run(self):
        calls, log = self.run_it({"discover": 1, "prepare": 2})
        self.assertEqual([c[0] for c in calls], ["discover", "triage", "prepare", "tracker", "cleanup", "report"])
        self.assertEqual(calls[2], ["prepare", "ana", "--max", "7"])
        self.assertEqual(calls[1], ["triage", "ana", "--max", "40"])
        self.assertEqual(calls[3], ["tracker", "ana", "sweep"])
        self.assertEqual(calls[5], ["report", "ana", "--notify"])
        self.assertIn("discover failed", log)
        self.assertIn("prepare failed", log)
        self.assertNotIn("triage failed", log)
        self.assertIn("prepare end", log)

    def test_apply_only_in_easy_or_full_mode(self):
        (self.d / "state.json").write_text(json.dumps({"mode": "easy"}))
        calls, _ = self.run_it({"apply": 1})
        self.assertEqual([c[0] for c in calls][3], "apply")
        self.assertEqual(len(calls), 7)
        (self.d / "state.json").write_text(json.dumps({"mode": "dry-run"}))
        calls, _ = self.run_it()
        self.assertNotIn("apply", [c[0] for c in calls])

    def test_a_missing_script_runner_counts_as_a_failed_step(self):
        with mock.patch.object(self.rp.subprocess, "run", side_effect=FileNotFoundError):
            self.rp.guarded("ana", "prepare", self.rp.prepare)
        self.assertIn("discover failed", self.log.read_text())
        self.assertNotIn("report failed", self.log.read_text())

    def test_stop_file_in_candidate_or_repo(self):
        (self.d / "STOP").write_text("")
        calls, log = self.run_it()
        self.assertEqual(calls, [])
        self.assertIn("STOP file present", log)
        (self.d / "STOP").unlink()
        (self.tmp / "no-repo-stop").mkdir()
        (self.tmp / "no-repo-stop/STOP").write_text("")
        calls, _ = self.run_it()
        self.assertEqual(calls, [])

    def test_lock_blocks_a_second_run_and_is_released(self):
        lock = self.rp.lock_path("ana")
        lock.parent.mkdir(exist_ok=True)
        lock.write_text("1")
        calls, log = self.run_it()
        self.assertEqual(calls, [])
        self.assertIn("another run is active", log)
        self.assertTrue(lock.exists())
        lock.unlink()
        calls, _ = self.run_it()
        self.assertTrue(calls)
        self.assertFalse(lock.exists())

    def test_stale_lock_is_taken_over(self):
        lock = self.rp.lock_path("ana")
        lock.parent.mkdir(exist_ok=True)
        lock.write_text("1")
        old = time.time() - (self.rp.STALE_HOURS + 1) * 3600
        os.utime(lock, (old, old))
        calls, _ = self.run_it()
        self.assertTrue(calls)

    def test_env_pairs_only_accept_job_settings(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            self.rp.setup_env(["JOB_PACKAGE_DIR=C:\\My Docs", "EVIL=1"])
            self.assertEqual(os.environ["JOB_PACKAGE_DIR"], "C:\\My Docs")
            self.assertNotIn("EVIL", os.environ)
            self.assertEqual(os.environ["PYTHONUTF8"], "1")
            os.environ.pop("JOB_PACKAGE_DIR")
            os.environ.pop("PYTHONUTF8")


class TestRunDaily(unittest.TestCase):
    def test_claude_command_keeps_flags_and_extends_allowed_tools(self):
        import run_daily
        with on("linux"), mock.patch("shutil.which", side_effect={"claude": "/bin/claude"}.get), mock.patch.dict(os.environ, {"JOB_MODEL": ""}):
            cmd = run_daily.claude_cmd("ana")
        self.assertEqual(cmd[:4], ["/bin/claude", "-p", "/job-daily ana", "--chrome"])
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "acceptEdits")
        tools = cmd[cmd.index("--allowedTools") + 1]
        for t in ("Bash(python3 scripts/*)", "Bash(python scripts/*)", "Bash(py -3 scripts/*)", "Bash(bin/job *)", "mcp__claude-in-chrome__*"):
            self.assertIn(t, tools)

    def test_mac_keeps_awake(self):
        import run_daily
        with on("darwin"), mock.patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}"):
            self.assertEqual(run_daily.claude_cmd("ana")[:2], ["caffeinate", "-i"])


if __name__ == "__main__":
    unittest.main()
