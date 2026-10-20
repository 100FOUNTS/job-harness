"""Install the daily run as a macOS LaunchAgent (runs at the hour even after sleep; missed runs run on wake).

  job schedule install <slug> [--hour 9 --minute 0]
  job schedule uninstall <slug>
  job schedule status <slug>
  job schedule run-now <slug>          one run immediately, without the random delay (for testing)
"""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from common import ROOT, cand_dir

LABEL = "com.jobharness.daily.{slug}"


def plist_path(slug: str) -> Path:
    return Path.home() / f"Library/LaunchAgents/{LABEL.format(slug=slug)}.plist"


def plist(slug: str, hour: int, minute: int, runner: str = "prepare") -> str:
    script = ROOT / ("scripts/run_prepare.sh" if runner == "prepare" else "scripts/run_daily.sh")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL.format(slug=slug)}</string>
  <key>ProgramArguments</key><array><string>/bin/zsh</string><string>{script}</string><string>{slug}</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>{minute}</integer></dict>
  <key>StandardOutPath</key><string>{cand_dir(slug)}/logs/launchd.out</string>
  <key>StandardErrorPath</key><string>{cand_dir(slug)}/logs/launchd.err</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{os.environ.get('PATH', '')}</string></dict>
</dict></plist>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["install", "uninstall", "status", "run-now"]); ap.add_argument("slug")
    ap.add_argument("--hour", type=int, default=9); ap.add_argument("--minute", type=int, default=0)
    ap.add_argument("--runner", choices=["prepare", "agent"], default="prepare",
                    help="prepare = scripts only (default); agent = Claude + browser (run_daily.sh)")
    a = ap.parse_args()
    p = plist_path(a.slug)
    uid = str(os.getuid())
    if a.cmd == "install":
        (cand_dir(a.slug) / "logs").mkdir(exist_ok=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(plist(a.slug, a.hour, a.minute, a.runner))
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(p)], capture_output=True)
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(p)], capture_output=True, text=True)
        print(f"installed {p} at {a.hour:02d}:{a.minute:02d} (+0–20 min random)" if r.returncode == 0 else r.stderr)
    elif a.cmd == "uninstall":
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(p)], capture_output=True)
        print(f"unloaded {LABEL.format(slug=a.slug)} (plist kept at {p}; remove it yourself if you want)")
    elif a.cmd == "status":
        r = subprocess.run(["launchctl", "print", f"gui/{uid}/{LABEL.format(slug=a.slug)}"], capture_output=True, text=True)
        print("loaded" if r.returncode == 0 else "not loaded", "·", p if p.exists() else "no plist")
    else:
        env = os.environ | {"JOB_NO_DELAY": "1"}
        subprocess.Popen(["/bin/zsh", str(ROOT / "scripts/run_prepare.sh"), a.slug], env=env)
        print(f"started; log: {cand_dir(a.slug)}/logs/")


if __name__ == "__main__":
    main()
