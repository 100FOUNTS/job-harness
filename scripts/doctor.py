"""What is available on this machine for the harness (never prints secrets).

  job doctor
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from common import ROOT


def check(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


def main() -> None:
    plists = sorted(p.name for p in (Path.home() / "Library/LaunchAgents").glob("com.jobharness.daily.*.plist"))
    r = {
        "node": bool(shutil.which("node")),
        "docx_module": (ROOT / "templates/docs/node_modules/docx").exists(),
        "pdfkit_module (headless PDF)": (ROOT / "templates/docs/node_modules/pdfkit").exists(),
        "pdftotext/pdfinfo (lint)": bool(shutil.which("pdftotext") and shutil.which("pdfinfo")),
        "claude_cli": bool(shutil.which("claude")),
        "claude --chrome flag": check(["sh", "-c", "claude --help | grep -q -- --chrome"]),
        "launchd schedules": plists,
        "network: seek search": check(["curl", "-s", "-o", "/dev/null", "-m", "15", "-w", "%{http_code}",
                                       "https://www.seek.com.au/"]),
    }
    print(json.dumps(r, indent=2))
    print("Note: Claude in Chrome must be connected (`/chrome` in Claude Code) for the apply step.")


if __name__ == "__main__":
    main()
