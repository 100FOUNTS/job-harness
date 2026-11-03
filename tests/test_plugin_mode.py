"""Plugin mode end to end (simulated: common.ROOT under plugins/cache, HOME and JOB_DATA_DIR in temp dirs), and clone
mode unchanged: per-person paths, lessons, Node tools, and schedules that survive a plugin update."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import apply  # noqa: E402
import common  # noqa: E402
import doctor  # noqa: E402
import learn  # noqa: E402
import run_prepare  # noqa: E402
import schedule  # noqa: E402
import setup  # noqa: E402
import sponsors  # noqa: E402

HOME_KEYS = ("JOB_DATA_DIR", "JOB_CANDIDATES_DIR", "JOB_PACKAGE_DIR", "NODE_PATH", "JOB_NODE_MODULES")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.cache = self.tmp / ".claude/plugins/cache/100founts/job-harness/0.2.0"
        (self.cache / "scripts").mkdir(parents=True)
        self.data = self.tmp / "data"
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k not in HOME_KEYS}, clear=True))
        self.stack.enter_context(mock.patch.object(Path, "home", return_value=self.tmp))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(self.stack.close)

    def plugin(self):
        os.environ["JOB_DATA_DIR"] = str(self.data)
        self.stack.enter_context(mock.patch.object(common, "ROOT", self.cache))
        self.assertTrue(common.plugin_mode())

    def candidate(self, slug="ana"):
        d = self.data / "candidates" / slug
        d.mkdir(parents=True)
        (d / "intake.json").write_text(json.dumps({"name": "Ana Tester", "email": "ana@example.com"}))
        return d


class TestPaths(Base):
    def test_clone_paths_are_byte_identical_to_before(self):
        self.assertFalse(common.plugin_mode())
        self.assertEqual(common.browser_dir("ana"), ROOT / ".browser" / "ana")
        self.assertEqual(common.stop_file(), ROOT / "STOP")
        self.assertEqual(sponsors.data_file(), ROOT / "data" / "sponsors.json")
        self.assertEqual(learn.logs(), [ROOT / "learn" / "observations.jsonl"])
        self.assertEqual(common.tools_dir(), ROOT / "templates" / "docs")
        self.assertEqual(common.apply_tools_dir(), ROOT / "apply")
        self.assertIsNone(common.node_env())
        with mock.patch.object(Path, "mkdir"):
            self.assertEqual(apply.profile_dir("ana"), ROOT / ".browser" / "ana")

    def test_plugin_paths_live_in_the_data_dir(self):
        self.plugin()
        self.assertEqual(apply.profile_dir("ana"), self.data / ".browser" / "ana")
        self.assertTrue(apply.profile_dir("ana").is_dir())
        self.assertEqual(sponsors.data_file(), self.data / "data" / "sponsors.json")
        self.assertEqual(common.tools_dir(), self.data / "tools")
        self.assertEqual(common.apply_tools_dir(), self.data / "tools" / "apply")

    def test_stop_file_in_the_data_dir_stops_the_run(self):
        self.plugin()
        self.candidate()
        self.assertFalse(run_prepare.stopped("ana"))
        self.data.joinpath("STOP").write_text("")
        self.assertTrue(run_prepare.stopped("ana"))

    def test_sponsors_import_writes_to_the_data_dir(self):
        self.plugin()
        src = self.tmp / "mig"
        src.mkdir()
        (src / "0060_accredited_sponsors.sql").write_text(
            "insert into accredited_sponsors (a) values\n('ACME PTY LTD','Acme Pty Ltd','2025-01-15'),\n")
        (src / "0087_active_sponsors_reocr.sql").write_text("")
        sponsors._index.cache_clear()
        r = sponsors.import_lists(src)
        self.assertEqual(r["file"], str(self.data / "data" / "sponsors.json"))
        self.assertEqual(sponsors.lookup("Acme")["match"], "likely")
        sponsors._index.cache_clear()

    def test_node_env_points_node_and_esm_at_the_tools_dir(self):
        self.plugin()
        os.environ["NODE_PATH"] = "/other"
        env = common.node_env()
        mods = str(self.data / "tools" / "node_modules")
        self.assertEqual(env["JOB_NODE_MODULES"], mods)
        self.assertEqual(env["NODE_PATH"], mods + os.pathsep + "/other")
        self.assertEqual(common.node_env(common.apply_tools_dir())["JOB_NODE_MODULES"],
                         str(self.data / "tools" / "apply" / "node_modules"))

    def test_remember_root(self):
        common.remember_root()                                   # clone: nothing written anywhere
        self.assertFalse((ROOT / ".harness_root").exists())
        self.plugin()
        common.remember_root()
        f = self.data / ".harness_root"
        self.assertEqual(f.read_text().strip(), str(self.cache))
        with mock.patch.object(Path, "write_text") as w:         # already current: no write
            common.remember_root()
            w.assert_not_called()
        with mock.patch.object(common, "ROOT", self.tmp / "plugins/cache/new"):
            common.remember_root()
        self.assertEqual(f.read_text().strip(), str(self.tmp / "plugins/cache/new"))


class TestLessons(Base):
    def setUp(self):
        super().setUp()
        (self.cache / "learn").mkdir()
        (self.cache / "learn/observations.jsonl").write_text(
            json.dumps({"kind": "harness", "area": "docs", "lesson": "shipped rule", "candidate": ""}) + "\n")

    def run_learn(self, *args):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["learn", *args]), contextlib.redirect_stdout(out):
            learn.main()
        return out.getvalue()

    def test_plugin_reads_both_and_writes_only_the_persons_file(self):
        self.plugin()
        own = self.data / "learn" / "observations.jsonl"
        shipped = (self.cache / "learn/observations.jsonl").read_text()
        self.assertEqual(learn.logs(), [self.cache / "learn/observations.jsonl", own])
        self.run_learn("log", "--kind", "platform", "--area", "seek", "--lesson", "my lesson")
        self.assertEqual((self.cache / "learn/observations.jsonl").read_text(), shipped)
        self.assertEqual([json.loads(l)["lesson"] for l in own.read_text().splitlines()], ["my lesson"])
        self.assertEqual([o["lesson"] for _, o in learn.load_lines()], ["shipped rule", "my lesson"])
        self.assertEqual(learn.relevant(["seek"]), ["my lesson", "shipped rule"])
        listing = self.run_learn("list")
        self.assertIn("1. [docs] shipped rule", listing)
        self.assertIn("2. [seek] my lesson", listing)

    def test_set_status_changes_only_the_persons_lessons(self):
        self.plugin()
        self.run_learn("log", "--kind", "platform", "--area", "seek", "--lesson", "mine")
        shipped = (self.cache / "learn/observations.jsonl").read_text()
        self.assertIn("cannot be changed", self.run_learn("set-status", "1", "dismissed"))
        self.assertEqual((self.cache / "learn/observations.jsonl").read_text(), shipped)
        self.assertIn("1 lesson(s) -> dismissed", self.run_learn("set-status", "2", "dismissed"))
        self.assertEqual(json.loads((self.data / "learn/observations.jsonl").read_text())["status"], "dismissed")

    def test_clone_uses_the_single_repo_file(self):
        log = self.tmp / "obs.jsonl"
        with mock.patch.object(learn, "LOG", log):
            self.run_learn("log", "--kind", "platform", "--area", "seek", "--lesson", "x")
            self.assertEqual(learn.logs(), [log])
        self.assertTrue(log.exists())


class TestSchedule(Base):
    def printed(self, platform, *args, which=None):
        out = io.StringIO()
        with mock.patch.object(sys, "platform", platform), mock.patch("shutil.which", return_value=which), \
                mock.patch("os.getuid", create=True, return_value=501), \
                mock.patch.object(sys, "argv", ["schedule.py", *args, "--print"]), \
                mock.patch("subprocess.run") as run, mock.patch("subprocess.Popen"), contextlib.redirect_stdout(out):
            schedule.main()
        run.assert_not_called()
        return out.getvalue()

    def test_macos_plist_calls_the_launcher_not_the_cache(self):
        self.plugin()
        self.candidate()
        text = self.printed("darwin", "install", "ana", "--hour", "7")
        self.assertIn(f"<string>/bin/sh</string><string>{self.data / 'run.sh'}</string><string>ana</string>", text)
        self.assertNotIn(str(self.cache), text)
        self.assertNotIn("run_prepare.sh", text)
        self.assertIn("<key>Hour</key><integer>7</integer>", text)
        self.assertIn("launchctl bootstrap gui/501", text)
        self.assertFalse((self.data / "run.sh").exists())          # --print writes nothing

    def test_agent_runner_passes_the_flag(self):
        self.plugin()
        self.candidate()
        self.assertIn(f"<string>{self.data / 'run.sh'}</string><string>--agent</string><string>ana</string>",
                      self.printed("darwin", "install", "ana", "--runner", "agent"))

    def test_windows_task_calls_run_cmd(self):
        self.plugin()
        text = self.printed("win32", "install", "ana")
        self.assertIn("schtasks /Create /SC DAILY", text)
        self.assertIn("run.cmd", text)
        self.assertIn(str(self.data), text)
        self.assertNotIn("plugins", text.replace(str(self.data), ""))
        self.assertNotIn("run_prepare.py", text)

    def test_linux_systemd_and_cron_call_run_sh(self):
        self.plugin()
        text = self.printed("linux", "install", "ana", which="/usr/bin/systemctl")
        self.assertIn(f'ExecStart="{self.data / "run.sh"}" "ana"', text)
        self.assertIn(f'WorkingDirectory="{self.data}"', text)
        self.assertNotIn(str(self.cache), text)
        cron = self.printed("linux", "install", "ana")
        self.assertIn(str(self.data / "run.sh"), cron)
        self.assertNotIn(str(self.cache), cron)

    def test_clone_still_points_at_the_repo(self):
        with mock.patch.object(schedule, "cand_dir", return_value=self.tmp):
            text = self.printed("darwin", "install", "ana")
        self.assertIn("<string>/bin/zsh</string>", text)
        self.assertIn(str(ROOT / "scripts/run_prepare.sh"), text)
        self.assertIn("run_prepare.py", self.printed("win32", "install", "ana"))
        self.assertNotIn("run.cmd", self.printed("win32", "install", "ana"))

    def test_run_now_runs_the_code_directly(self):
        self.plugin()
        with mock.patch.object(schedule, "ROOT", self.cache):      # schedule bound ROOT at import
            text = self.printed("linux", "run-now", "ana")
        self.assertIn(str(self.cache / "scripts/run_prepare.py"), text)
        self.assertNotIn("run.sh", text)


@unittest.skipIf(os.name == "nt", "sh launcher")
class TestLauncher(Base):
    def setUp(self):
        super().setUp()
        self.plugin()
        (self.cache / "scripts/run_prepare.py").write_text("import sys; print('ran', *sys.argv[1:])\n")
        (self.cache / "scripts/run_daily.py").write_text("import sys; print('daily', *sys.argv[1:])\n")

    def run_launcher(self, *args):
        return subprocess.run(["sh", str(self.data / "run.sh"), *args], capture_output=True, text=True)

    def test_text_resolves_the_pointer_file(self):
        for name, ptr in (("mac", ".harness_root"), ("linux", ".harness_root"), ("win", ".harness_root")):
            self.assertIn(ptr, schedule.launcher_text(name))
        self.assertIn("run_prepare", schedule.launcher_text("win"))

    def test_runs_the_current_code_and_follows_an_update(self):
        schedule.write_launcher("mac")
        self.assertTrue(os.access(self.data / "run.sh", os.X_OK))
        r = self.run_launcher("ana", "--env", "JOB_X=1")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ran ana --env JOB_X=1"))
        self.assertEqual(self.run_launcher("--agent", "ana").stdout.strip(), "daily ana")
        new = self.tmp / ".claude/plugins/cache/100founts/job-harness/0.3.0"
        (new / "scripts").mkdir(parents=True)
        (new / "scripts/run_prepare.py").write_text("print('new code')\n")
        with mock.patch.object(common, "ROOT", new):
            common.remember_root()                             # what `job setup` / status do after an update
        self.assertEqual(self.run_launcher("ana").stdout.strip(), "new code")

    def test_missing_pointer_or_folder_fails_with_a_clear_line(self):
        schedule.write_launcher("mac")
        (self.data / ".harness_root").unlink()
        r = self.run_launcher("ana")
        self.assertEqual(r.returncode, 1)
        self.assertIn("job setup", r.stderr)
        self.assertIn("missing or gone", (self.data / "launcher.log").read_text())
        (self.data / ".harness_root").write_text(str(self.tmp / "gone") + "\n")
        self.assertEqual(self.run_launcher("ana").returncode, 1)

    def test_install_writes_the_launcher_and_the_pointer(self):
        self.candidate()
        with mock.patch.object(schedule, "sh", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                mock.patch.object(sys, "platform", "linux"), mock.patch("shutil.which", return_value="/usr/bin/systemctl"), \
                mock.patch.object(sys, "argv", ["schedule.py", "install", "ana"]), contextlib.redirect_stdout(io.StringIO()):
            schedule.main()
        self.assertTrue((self.data / "run.sh").is_file())
        self.assertEqual((self.data / ".harness_root").read_text().strip(), str(self.cache))
        self.assertTrue((self.tmp / ".config/systemd/user/job-harness-ana.service").is_file())


class TestSetupTools(Base):
    def fake_npm(self, calls):
        def npm(args, cwd):
            calls.append((args[0], cwd))
            (cwd / "node_modules" / "docx").mkdir(parents=True, exist_ok=True)
            return True
        return npm

    def src(self, body="{}"):
        s = self.tmp / "src"
        s.mkdir(exist_ok=True)
        (s / "package.json").write_text(body)
        (s / "package-lock.json").write_text("{}")
        return s

    def test_plugin_installs_into_the_tools_dir_and_is_idempotent(self):
        self.plugin()
        calls, src, dest = [], self.src(), common.tools_dir()
        with mock.patch.object(setup, "npm", self.fake_npm(calls)), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(setup.step_tools(dest, ("docx",), "Tools", False, ["--omit=optional"], src=src))
            self.assertEqual(calls, [("ci", dest)])
            self.assertEqual((dest / "package.json").read_text(), "{}")
            self.assertTrue((dest / setup.HASH).is_file())
            self.assertTrue(setup.step_tools(dest, ("docx",), "Tools", False, src=src))      # nothing changed: no npm
            self.assertEqual(len(calls), 1)
            (src / "package.json").write_text('{"dependencies": {"docx": "^10"}}')            # an update changed the deps
            self.assertFalse(setup.step_tools(dest, ("docx",), "Tools", True, src=src))      # --check says so, changes nothing
            self.assertEqual(len(calls), 1)
            self.assertTrue(setup.step_tools(dest, ("docx",), "Tools", False, src=src))
            self.assertEqual([c[0] for c in calls], ["ci", "ci"])
            self.assertIn("^10", (dest / "package.json").read_text())

    def test_falls_back_to_install_when_ci_fails(self):
        self.plugin()
        seen = []

        def npm(args, cwd):
            seen.append(args[0])
            (cwd / "node_modules" / "docx").mkdir(parents=True, exist_ok=True)
            return args[0] == "install"
        with mock.patch.object(setup, "npm", npm), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(setup.step_tools(common.tools_dir(), ("docx",), "Tools", False, src=self.src()))
        self.assertEqual(seen, ["ci", "install"])

    def test_clone_installs_in_place_without_copies_or_hash(self):
        folder, calls = self.src(), []
        with mock.patch.object(setup, "npm", self.fake_npm(calls)), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(setup.step_tools(folder, ("docx",), "Tools", False, ["--omit=optional"]))
        self.assertEqual(calls, [("install", folder)])
        self.assertFalse((folder / setup.HASH).exists())

    def test_main_targets_tools_dir_remembers_root_and_apply_goes_to_tools_apply(self):
        self.plugin()
        with mock.patch.object(setup, "step_python", return_value=True), mock.patch.object(setup, "step_node", return_value=True), \
                mock.patch.object(setup, "step_tools") as st, mock.patch.object(setup, "step_playwright") as pw, \
                mock.patch.object(setup, "step_path"), mock.patch.object(setup, "step_package"), \
                mock.patch.object(doctor, "gather", return_value={}), mock.patch.object(doctor, "show", return_value=0), \
                mock.patch.object(sys, "argv", ["setup", "--apply-tools"]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as c:
                setup.main()
        self.assertEqual(c.exception.code, 0)
        self.assertEqual(st.call_args.args[0], self.data / "tools")
        self.assertEqual(st.call_args.kwargs["src"], setup.DOCS)
        pw.assert_called_once()
        self.assertEqual((self.data / ".harness_root").read_text().strip(), str(self.cache))
        calls = []
        with mock.patch.object(setup, "npm", self.fake_npm(calls)), mock.patch("shutil.which", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            setup.step_playwright(False)
        self.assertEqual(calls, [("ci", self.data / "tools" / "apply")] if (setup.APPLY / "package-lock.json").is_file()
                         else [("install", self.data / "tools" / "apply")])

    def test_doctor_looks_in_the_tools_dir(self):
        self.plugin()
        self.assertFalse(doctor.gather()["docx_module"])
        (self.data / "tools/node_modules/docx").mkdir(parents=True)
        (self.data / "tools/apply/node_modules/playwright").mkdir(parents=True)
        with mock.patch.object(doctor, "reach", return_value=False), mock.patch.object(doctor, "chrome_flag", return_value=False):
            r = doctor.gather()
        self.assertTrue(r["docx_module"])
        self.assertTrue(r["playwright (apply/)"])


class TestNodeCalls(Base):
    def test_every_node_call_gets_the_plugin_env(self):
        import docs
        import pdftext
        self.plugin()
        seen = []

        def run(cmd, **kw):
            seen.append((cmd[0], kw.get("env")))
            return subprocess.CompletedProcess(cmd, 0, "1", "")
        with mock.patch("subprocess.run", side_effect=run), mock.patch("shutil.which", return_value="/usr/bin/node"):
            (self.data / "tools/node_modules/pdfjs-dist").mkdir(parents=True)
            pdftext.pages(Path("x.pdf"))
            docs.export_pdf(Path("a.json"), "cv", self.tmp / "a.pdf")
        self.assertEqual(len(seen), 2)
        for exe, env in seen:
            self.assertEqual(exe, "node")
            self.assertEqual(env["JOB_NODE_MODULES"], str(self.data / "tools/node_modules"))

    def test_apply_script_gets_the_apply_modules(self):
        self.plugin()
        captured = {}

        def run(cmd, **kw):
            captured.update(kw)
            return subprocess.CompletedProcess(cmd, 0, '{"outcome": "dry-run"}', "")
        cv, letter = self.tmp / "cv.pdf", self.tmp / "l.pdf"
        cv.write_text(""); letter.write_text("")
        job = {"key": "seek:1", "status": "prepared", "platform": "seek", "cv": str(cv), "letter": str(letter), "title": "T"}
        with mock.patch.object(apply, "load_state", return_value={"mode": "dry-run"}), mock.patch.object(apply, "load", return_value=[job]), \
                mock.patch.object(apply, "set_status"), mock.patch.object(apply, "quota", return_value={}), \
                mock.patch("subprocess.run", side_effect=run):
            apply.apply("ana", True)
        self.assertEqual(captured["env"]["JOB_NODE_MODULES"], str(self.data / "tools/apply/node_modules"))
        self.assertEqual(captured["cwd"], apply.APPLY)


if __name__ == "__main__":
    unittest.main()
