"""Daily runner with Claude + browser. Works on macOS, Windows and Linux.

  python scripts/run_daily.py <slug> [--env JOB_X=value ...]
- random start delay (0–20 min) unless JOB_NO_DELAY=1, so it never runs at the exact same minute
- lock: never two runs at once; STOP file: kill switch; logs per day
- discovery and triage are scripts (no LLM); Claude only judges, writes and applies
"""
from __future__ import annotations

import argparse
import os
import random
import shutil
import time
from typing import TextIO

import osutil
from run_prepare import guarded, py, setup_env, step

TOOLS = ("Agent Bash(python3 scripts/*) Bash(python scripts/*) Bash(py -3 scripts/*) Bash(bin/job *) Bash(./bin/job *) "
         "Bash(pdftoppm *) Read Write Edit Glob Grep mcp__claude-in-chrome__*")


def claude_cmd(slug: str) -> list[str]:
    keep_awake = ["caffeinate", "-i"] if osutil.os_name() == "mac" and shutil.which("caffeinate") else []
    return [*keep_awake, shutil.which("claude") or "claude", "-p", f"/job-daily {slug}", "--chrome",
            "--model", os.environ.get("JOB_MODEL") or "sonnet",     # a cheaper model is enough here
            "--permission-mode", "acceptEdits", "--allowedTools", TOOLS, "--output-format", "text"]


def daily(slug: str, out: TextIO) -> None:
    if os.environ.get("JOB_NO_DELAY") != "1":
        time.sleep(random.randrange(1200))
    step(out, "discover", py("discover", slug))
    step(out, "triage", py("triage", slug))
    step(out, "claude run", claude_cmd(slug))
    step(out, "report", py("report", slug, "--notify"), quiet=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("--env", action="append", default=[], metavar="JOB_X=value")
    a = ap.parse_args()
    setup_env(a.env)
    guarded(a.slug, "daily", daily)


if __name__ == "__main__":
    main()
