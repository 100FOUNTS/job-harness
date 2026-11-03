"""The hook's guards run as a real subprocess, from outside the repo, the way Claude Code runs them."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_hook(payload, cwd=None):
    env = os.environ | {"CLAUDE_PROJECT_DIR": str(ROOT)}
    return subprocess.run([sys.executable, str(ROOT / "hooks/gate.py")], input=json.dumps(payload),
                          capture_output=True, encoding="utf-8", env=env, cwd=cwd or tempfile.gettempdir())


def bash(cmd):
    return run_hook({"tool_name": "Bash", "tool_input": {"command": cmd}})


def decision(r):
    return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] if r.stdout.strip() else None


class TestProtectedRules(unittest.TestCase):
    def assertAsks(self, r):
        self.assertEqual((r.returncode, decision(r)), (0, "ask"), r.stderr)
        self.assertIn("harness's own rules", json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"])

    def assertFree(self, r):
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), r.stderr)

    def test_editing_protected_files_asks(self):
        for tool in ("Edit", "Write", "MultiEdit"):
            self.assertAsks(run_hook({"tool_name": tool, "tool_input": {"file_path": "hooks/gate.py"}}))
        self.assertAsks(run_hook({"tool_name": "Edit", "tool_input": {"file_path": str(ROOT / "scripts/gates.py")}}))
        self.assertAsks(run_hook({"tool_name": "Write", "tool_input": {"file_path": "./.claude/settings.json"}}))
        self.assertAsks(run_hook({"tool_name": "Edit", "tool_input": {"file_path": str(ROOT / ".claude/settings.local.json")}}))
        self.assertAsks(run_hook({"tool_name": "Write", "tool_input": {"file_path": "bin/job"}}))

    def test_shell_writes_to_protected_files_ask(self):
        for cmd in ("echo x > scripts/gates.py", "echo x >> ./hooks/gate.py", "printf y | tee .claude/settings.json",
                    "sed -i '' 's/a/b/' hooks/gate.py", "sed -i s/a/b/ bin/job", "cp /tmp/evil.py hooks/gate.py",
                    "mv /tmp/x scripts/gates.py", "rm hooks/gate.py", "git checkout -- scripts/gates.py",
                    "git restore hooks/gate.py", f"echo x > {ROOT}/hooks/py.sh", "ls && echo x>bin/job"):
            self.assertAsks(bash(cmd))

    def test_reading_and_unrelated_edits_stay_free(self):
        self.assertFree(run_hook({"tool_name": "Read", "tool_input": {"file_path": "hooks/gate.py"}}))
        self.assertFree(run_hook({"tool_name": "Edit", "tool_input": {"file_path": "scripts/lint.py"}}))
        self.assertFree(run_hook({"tool_name": "Edit", "tool_input": {"file_path": "/elsewhere/hooks/x.py"}}))
        for cmd in ("cat hooks/gate.py", "cp hooks/gate.py /tmp/copy.py", "grep -n sign scripts/gates.py",
                    "bin/job status ana 2>&1", "python3 scripts/status.py > /dev/null", "echo hi > /tmp/out.txt"):
            self.assertFree(bash(cmd))

    def test_existing_blocks_win_over_ask(self):
        self.assertEqual(bash("echo x > scripts/gates.py; bin/job sign ana go-live-01").returncode, 2)


class TestSecretReads(unittest.TestCase):
    def test_browser_ssh_aws_reads_blocked(self):
        for path in (".browser/x/Default/Cookies", str(ROOT / ".browser/ana/Default/Cookies"), "~/.ssh/config",
                     "/home/u/.aws/credentials"):
            self.assertEqual(run_hook({"tool_name": "Read", "tool_input": {"file_path": path}}).returncode, 2, path)
        self.assertEqual(run_hook({"tool_name": "Grep", "tool_input": {"pattern": "x", "path": ".browser/ana"}}).returncode, 2)
        self.assertEqual(run_hook({"tool_name": "Glob", "tool_input": {"pattern": ".browser/**/Cookies"}}).returncode, 2)
        for cmd in ("cat ~/.ssh/id_rsa", "cat ~/.ssh/config", "head -c 100 .browser/ana/Default/Cookies",
                    "cp .browser/ana/Default/Cookies /tmp/c", "less ~/.aws/config"):
            self.assertEqual(bash(cmd).returncode, 2, cmd)

    def test_normal_flow_untouched(self):
        for cmd in ("bin/job apply ana login seek", "bin/job doctor", "cat .gitignore", "git status"):
            self.assertEqual(bash(cmd).returncode, 0, cmd)


class TestExistingBehaviours(unittest.TestCase):
    def test_core_rules_still_hold(self):
        self.assertEqual(bash("bin/job sign ana go-live-01").returncode, 2)
        self.assertEqual(bash("bin/job sign ana go-live-01 --confirm ana").returncode, 2)
        self.assertEqual(bash("bin/job sign ana report-01 --by-agent --note x").returncode, 0)
        self.assertEqual(bash("rm -rf candidates/ana/data").returncode, 2)
        self.assertEqual(run_hook({"tool_name": "Edit", "tool_input": {"file_path": "/x/candidates/ana/tracker.json"}}).returncode, 2)
        self.assertEqual(run_hook({"tool_name": "Read", "tool_input": {"file_path": "/x/.env"}}).returncode, 2)

    def test_garbage_input_does_not_crash(self):
        env = os.environ | {"CLAUDE_PROJECT_DIR": str(ROOT)}
        r = subprocess.run([sys.executable, str(ROOT / "hooks/gate.py")], input="not json", capture_output=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 0)


class TestSuggestedCommandsExist(unittest.TestCase):
    def test_every_job_subcommand_in_gate_messages_exists(self):
        job = (ROOT / "bin/job").read_text(encoding="utf-8")
        direct = set(re.findall(r'"(\w+)":\s*"\w+\.py"', job.split("DIRECT = ")[1].split("}")[0]))
        dispatched = set(re.findall(r'cmd == "(\w+)"', job))
        for tup in re.findall(r'cmd in \(([^)]*)\)', job):
            dispatched |= set(re.findall(r'"(\w+)"', tup))
        known = direct | dispatched
        self.assertTrue({"sign", "gate", "state", "facts", "track", "doctor", "review"} <= known, known)
        for src in ("hooks/gate.py", "scripts/gates.py", "scripts/status.py", "scripts/state.py"):
            for group in re.findall(r"(?:`(?:! )?(?:bin/)?|bin/)job ((?:[a-z]+\|)*[a-z]+)\b", (ROOT / src).read_text(encoding="utf-8")):
                for sub in group.split("|"):
                    self.assertIn(sub, known, f"{src} suggests `job {sub}`")

    def test_bin_job_dispatches_to_existing_scripts(self):
        job = (ROOT / "bin/job").read_text(encoding="utf-8")
        for script in re.findall(r'"(\w+\.py)"', job):
            self.assertTrue((ROOT / "scripts" / script).exists(), script)


class TestLauncher(unittest.TestCase):
    @unittest.skipUnless(shutil.which("sh"), "sh not available")
    def test_py_sh_finds_an_interpreter(self):
        r = subprocess.run(["sh", str(ROOT / "hooks/py.sh"), "-c", "print(6*7)"], capture_output=True, encoding="utf-8")      # no quotes: sh on Windows eats them
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "42"), r.stderr)

    @unittest.skipUnless(shutil.which("sh"), "sh not available")
    def test_py_sh_runs_the_hook(self):
        env = os.environ | {"CLAUDE_PROJECT_DIR": str(ROOT)}
        payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x/.env"}})
        r = subprocess.run(["sh", str(ROOT / "hooks/py.sh"), str(ROOT / "hooks/gate.py")], input=payload,
                           capture_output=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 2)

    def test_settings_point_to_the_launcher_and_files_exist(self):
        s = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
        cmds = [h["command"] for ev in s["hooks"].values() for g in ev for h in g["hooks"]]
        self.assertTrue(cmds and all("hooks/py.sh" in c for c in cmds), cmds)
        self.assertIn("Read(./.browser/**)", s["permissions"]["deny"])
        self.assertIn("Edit(./hooks/**)", s["permissions"]["ask"])


class TestApprovalEvidence(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["JOB_CANDIDATES_DIR"] = str(self.tmp)
        shutil.copytree(ROOT / "templates/candidate", self.tmp / "ana")
        (self.tmp / "ana/approvals").mkdir()
        (self.tmp / "ana/facts.json").write_text(json.dumps({"claims": [], "allow": []}), encoding="utf-8")
        (self.tmp / "ana/cv.md").write_text("Environmental engineer. Reduced waste by 77%.", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp)
        os.environ.pop("JOB_CANDIDATES_DIR", None)

    def test_version_recorded_and_checklist_shows_changes(self):
        import gates
        from common import HARNESS_VERSION
        gid = gates.request("ana", "master-docs", ["cv.md"], "cv")
        g = gates.find("ana", gid)
        self.assertEqual(g["harness_version"], HARNESS_VERSION)
        text = gates.checklist("ana", g)
        self.assertIn("✓ cv.md: unchanged", text)
        self.assertIn("✗", text)                          # 77% is not in facts.json
        (self.tmp / "ana/cv.md").write_text("edited", encoding="utf-8")
        self.assertIn("✗ cv.md: CHANGED", gates.checklist("ana", g))
        gates.request("ana", "report", ["cv.md"], "r")
        old = gates.find("ana", gid)
        old.pop("harness_version"); old.pop("_path")
        self.assertIn("unknown", gates.checklist("ana", old))   # approvals from before the field still render

    def test_signature_records_version(self):
        import gates
        from common import HARNESS_VERSION
        gid = gates.request("ana", "report", ["cv.md"], "r")
        gates.sign("ana", gid, True, "User approved in chat: 'ok'", None)
        self.assertEqual(gates.find("ana", gid)["signed_by"]["harness_version"], HARNESS_VERSION)


if __name__ == "__main__":
    unittest.main()
