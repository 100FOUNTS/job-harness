"""Shared helpers: candidate paths, JSON, HTTP and dates.

Standard library only, so every script runs from cron/launchd without installing anything.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HARNESS_VERSION = "0.1.0"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def plugin_mode() -> bool:
    """True when the harness runs from Claude Code's plugin cache (installed from a marketplace), not from a clone.
    Decided by the path alone: hooks get CLAUDE_PLUGIN_ROOT but the Bash tool does not, and both must agree."""
    parts = ROOT.parts
    return any(a == "plugins" and b in ("cache", "marketplaces") for a, b in zip(parts, parts[1:]))


def data_dir() -> Path:
    """Where the person's data lives. JOB_DATA_DIR; else ~/job-harness-data when installed as a plugin (outside the
    plugin code, so updates never touch it, and not in ${CLAUDE_PLUGIN_DATA}, which Claude deletes on uninstall and
    which the Bash tool cannot see); else, in a clone, the repo itself (today's layout)."""
    if os.environ.get("JOB_DATA_DIR"):
        return Path(os.environ["JOB_DATA_DIR"]).expanduser()
    return Path.home() / "job-harness-data" if plugin_mode() else ROOT


def setting(name: str, default: str) -> str:
    """A JOB_* setting: the environment first, then <data dir>/settings.json `env` (plugin users), then the repo's
    .claude/settings.local.json `env` (so a run started from another folder or a schedule installed from a plain
    shell still honours the owner's choice), then default."""
    if name in os.environ:
        return os.environ[name]
    for f in (data_dir() / "settings.json", ROOT / ".claude/settings.local.json"):
        env = read_json(f, {}).get("env", {})
        if name in env:
            return str(env[name])
    return default


def workspace(project_dir: Any) -> bool:
    """Is this Claude project a job-harness workspace? Clone: the repo folder. Plugin: the data folder (or inside it),
    or any folder holding a `.job-harness` marker file."""
    p = Path(project_dir or ".").expanduser().resolve()
    if not plugin_mode():
        return p == ROOT.resolve()
    d = data_dir().resolve()
    return (p / ".job-harness").exists() or d.exists() and (p == d or d in p.parents)


def candidates_dir() -> Path:
    return Path(os.environ.get("JOB_CANDIDATES_DIR", data_dir() / "candidates"))


def browser_dir(slug: str) -> Path:
    """Scripted-apply browser profile (session cookies): per person, never in the plugin code."""
    return data_dir() / ".browser" / slug


def stop_file() -> Path:
    return data_dir() / "STOP"


def sponsors_file() -> Path:
    return data_dir() / "data" / "sponsors.json"


def learn_dir() -> Path:
    return data_dir() / "learn"


def cand_dir(slug: str) -> Path:
    d = candidates_dir() / slug
    if not d.exists():
        raise SystemExit(f"Candidate '{slug}' does not exist in {candidates_dir()}. Use: job new <slug>")
    return d


def list_candidates() -> list[str]:
    base = candidates_dir()
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "intake.json").exists()) if base.exists() else []


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        if default is not None:
            return default
        raise SystemExit(f"Missing file: {path}")
    return json.loads(path.read_text())


def save_json(path: Path, data: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return path


def load_intake(slug: str) -> dict[str, Any]:
    return read_json(cand_dir(slug) / "intake.json")


def today() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def run_dir(slug: str, day: str | None = None) -> Path:
    """Dated data folder: candidates/<slug>/data/YYYY-MM-DD/."""
    d = cand_dir(slug) / "data" / (day or today())
    d.mkdir(parents=True, exist_ok=True)
    return d


def keep_previous(path: Path) -> None:
    """A second run on the same day must not erase the first: the earlier file becomes <name>.<HHMMSS>.json."""
    path = Path(path)
    if path.exists():
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%H%M%S")
        path.rename(path.with_name(f"{path.stem}.{stamp}{path.suffix}"))


def http_get(url: str, timeout: int = 25) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-AU,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        return e.code, ""
    except Exception as e:  # network errors are reported, never raised into the daily run
        return 0, str(e)


def emit(data: Any, as_json: bool) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2) if as_json else data)


if __name__ == "__main__":  # python3 scripts/common.py where|init
    import sys
    if sys.argv[1:] == ["init"]:
        data_dir().mkdir(parents=True, exist_ok=True)
        (data_dir() / ".job-harness").touch()
    print(f"mode: {'plugin' if plugin_mode() else 'clone'}\ndata: {data_dir()}\ncandidates: {candidates_dir()}")
