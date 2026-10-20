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


def candidates_dir() -> Path:
    return Path(os.environ.get("JOB_CANDIDATES_DIR", ROOT / "candidates"))


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
