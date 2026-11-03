"""Daily runner in prepare mode: scripts only (no LLM, no browser). Works on macOS, Windows and Linux.

  python scripts/run_prepare.py <slug> [--env JOB_X=value ...]
  discover → triage → prepare (top jobs, documents, package) → apply (modes easy/full) → sweep → cleanup → report + notification.
A step that fails is logged and the run continues. A STOP file (repo or candidate) turns the run off; one run at a time per candidate.
Everything goes to candidates/<slug>/logs/<date>.log.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

import osutil
from common import ROOT, cand_dir, read_json, setting, stop_file, today

STALE_HOURS = 6
UNIX_PATH = [str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"]


def say(out: TextIO, text: str) -> None:
    print(text, file=out, flush=True)


def stamp() -> str:
    return datetime.now().strftime("%a %d %b %Y %H:%M:%S")


def setup_env(pairs: list[str]) -> None:
    """Unattended runs get a small PATH of their own on macOS/Linux, UTF-8 for every child, and the JOB_* settings given with --env."""
    if osutil.os_name() != "win":
        os.environ["PATH"] = os.pathsep.join([*UNIX_PATH, os.environ.get("PATH", "")])
    os.environ["PYTHONUTF8"] = "1"
    for pair in pairs:
        key, _, value = pair.partition("=")
        if key.startswith("JOB_"):
            os.environ[key] = value


def stopped(slug: str) -> bool:
    return stop_file().exists() or (cand_dir(slug) / "STOP").exists()


def lock_path(slug: str) -> Path:
    return cand_dir(slug) / "logs" / "run.lock"


def acquire(path: Path, stale_hours: float = STALE_HOURS) -> bool:
    """Portable lock: create the file exclusively; a lock older than stale_hours is a crashed run and is taken over."""
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime < stale_hours * 3600:
                    return False
                path.unlink()
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    return False


def py(script: str, *args: str) -> list[str]:
    return [*osutil.python(), str(ROOT / "scripts" / f"{script}.py"), *args]


def step(out: TextIO, label: str, cmd: list[str], quiet: bool = False, cwd: Path = ROOT) -> bool:
    out.flush()
    try:
        ok = subprocess.run(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT).returncode == 0
    except OSError:
        ok = False
    if not ok and not quiet:
        say(out, f"{label} failed")
    return ok


def guarded(slug: str, name: str, body: Callable[[str, TextIO], None]) -> None:
    logs = cand_dir(slug) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / f"{today()}.log", "a", buffering=1, encoding="utf-8") as out:
        say(out, f"=== {stamp()} {name} start ({slug})")
        if stopped(slug):
            return say(out, "STOP file present, exiting")
        lock = lock_path(slug)
        if not acquire(lock):
            return say(out, "another run is active, exiting")
        try:
            body(slug, out)
        finally:
            lock.unlink(missing_ok=True)
        say(out, f"=== {stamp()} {name} end")


def mode_of(slug: str) -> str:
    try:
        return str(read_json(cand_dir(slug) / "state.json", {}).get("mode", ""))
    except (ValueError, OSError):
        return ""


def prepare(slug: str, out: TextIO) -> None:
    step(out, "discover", py("discover", slug))
    step(out, "triage", py("triage", slug, "--max", "40"))
    step(out, "prepare", py("prepare", slug, "--max", setting("JOB_PREPARE_MAX", "15") or "15"))
    if mode_of(slug) in ("easy", "full"):
        step(out, "apply", py("apply", slug))
    step(out, "sweep", py("tracker", slug, "sweep"))
    step(out, "cleanup", py("cleanup", slug, "--days", "15"))
    step(out, "report", py("report", slug, "--notify"), quiet=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("--env", action="append", default=[], metavar="JOB_X=value")
    a = ap.parse_args()
    setup_env(a.env)
    guarded(a.slug, "prepare", prepare)


if __name__ == "__main__":
    main()
