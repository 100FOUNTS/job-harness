"""What is available on this machine for the harness, and the exact command to fix what is missing (never prints secrets).

  job doctor [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import pdftext
from common import ROOT, UA, setting

DOCS = ROOT / "templates/docs"
MIN_PY, MIN_NODE = (3, 9), 20


def check(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


def os_name() -> str:
    return {"Darwin": "mac", "Windows": "windows"}.get(platform.system(), "linux")


def package_dir() -> Path:
    return Path(setting("JOB_PACKAGE_DIR", str(Path.home() / "job-packages"))).expanduser()


def node_version() -> int:
    try:
        out = subprocess.run(["node", "-v"], capture_output=True, text=True, timeout=15).stdout
        return int(re.match(r"v(\d+)", out.strip()).group(1))
    except Exception:
        return 0


def writable(d: Path) -> bool:
    while not d.exists() and d != d.parent:
        d = d.parent
    return os.access(d, os.W_OK)


def reach(url: str) -> bool:
    try:
        urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15).close()
        return True
    except Exception:
        return False


def install_hint(tool: str) -> str:
    o = os_name()
    return {
        "node": {"mac": "brew install node   (or the LTS installer from https://nodejs.org)",
                 "windows": "winget install OpenJS.NodeJS.LTS",
                 "linux": "install Node.js 20+ from https://nodejs.org (or: sudo apt install nodejs npm / sudo dnf install nodejs)"},
        "python": {"mac": "brew install python   (or https://www.python.org/downloads/)",
                   "windows": "winget install Python.Python.3.12",
                   "linux": "sudo apt install python3   (or: sudo dnf install python3)"},
    }[tool][o]


def chrome_flag() -> bool:
    try:
        return "--chrome" in subprocess.run(["claude", "--help"], capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return False


def gather() -> dict:
    nv, mods = node_version(), {m: (DOCS / "node_modules" / m).exists() for m in ("docx", "pdfkit", "pdfjs-dist")}
    pkg = package_dir()
    plists = sorted(p.name for p in (Path.home() / "Library/LaunchAgents").glob("com.jobharness.daily.*.plist"))
    return {
        "python": ".".join(map(str, sys.version_info[:3])),
        "python_ok": sys.version_info[:2] >= MIN_PY,
        "node": bool(shutil.which("node")),
        "node_major": nv,
        "node_ok": nv >= MIN_NODE,
        "docx_module": mods["docx"],
        "pdfkit_module (headless PDF)": mods["pdfkit"],
        "pdfjs_module": mods["pdfjs-dist"],
        "pdf_reader": "pdf.js" if pdftext.node_ready() else "poppler" if pdftext.poppler_ready() else None,
        "pdftotext/pdfinfo (fallback)": pdftext.poppler_ready(),
        "package_dir": str(pkg),
        "package_dir_writable": writable(pkg),
        "claude_cli": bool(shutil.which("claude")),
        "claude --chrome flag": chrome_flag(),
        "playwright (apply/)": (ROOT / "apply/node_modules/playwright").exists(),
        "launchd schedules": plists,
        "network: seek search": reach("https://www.seek.com.au/"),
    }


def report(r: dict) -> tuple[list[tuple[bool, str, str]], list[tuple[bool, str, str]]]:
    """(ok, what, fix) for the required and the optional checks."""
    node_fix = install_hint("node")
    docs_ok = r["docx_module"] and r["pdfkit_module (headless PDF)"] and r["pdfjs_module"]
    required = [
        (r["python_ok"], f"Python {r['python']} (3.9 or newer)", install_hint("python")),
        (r["node_ok"], f"Node.js {r['node_major']} (20 or newer)" if r["node"] else "Node.js (20 or newer)", node_fix),
        (docs_ok, "Document tools installed (templates/docs/node_modules)", "job setup"),
        (bool(r["pdf_reader"]), f"PDF reader works ({r['pdf_reader']})" if r["pdf_reader"] else "PDF reader works", "job setup"),
        (r["package_dir_writable"], f"Can write to the package folder {r['package_dir']}",
         "pick a folder you own: set JOB_PACKAGE_DIR in .claude/settings.local.json"),
    ]
    optional = [
        (r["claude_cli"], "Claude Code (onboarding, judgment steps)", "npm install -g @anthropic-ai/claude-code"),
        (r["claude --chrome flag"], "Claude in Chrome (profile/alerts stages, LinkedIn extraction; connect with /chrome in Claude Code)",
         "install Claude Code, then run /chrome in it"),
        (r["playwright (apply/)"], "Playwright (only for SEEK Quick Apply)", "job setup --apply-tools"),
        (r["network: seek search"], "Network to SEEK", "check your internet connection"),
    ]
    return required, optional


def mark(ok: bool, optional: bool = False) -> str:
    sym = ("✓", "-" if optional else "✗")
    enc = sys.stdout.encoding or "ascii"
    try:
        "✓✗".encode(enc)
    except UnicodeEncodeError:
        sym = ("ok", "-" if optional else "x")
    return sym[0] if ok else sym[1]


def show(r: dict) -> int:
    required, optional = report(r)
    for title, rows, opt in (("Required", required, False), ("Optional", optional, True)):
        print(title)
        for ok, what, fix in rows:
            print(f"  {mark(ok, opt)} {what}" + ("" if ok else f"\n      fix: {fix}"))
        print()
    bad = sum(not ok for ok, _, _ in required)
    print("Ready to prepare applications" if not bad else f"{bad} thing{'s' if bad > 1 else ''} to fix first")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args()
    r = gather()
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        show(r)


if __name__ == "__main__":
    main()
