"""Install the daily run: macOS LaunchAgent (runs at the hour even after sleep; missed runs run on wake),
Windows Task Scheduler (schtasks), Linux systemd user timer (a crontab line is printed when systemd is missing).

  job schedule install <slug> [--hour 9 --minute 0]
  job schedule uninstall <slug>
  job schedule status <slug>
  job schedule run-now <slug>          one run immediately, without the random delay (for testing)
  add --print to any of them to see what would be installed or run, without doing it
"""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import osutil
from common import ROOT, cand_dir, setting, today

LABEL = "com.jobharness.daily.{slug}"
TASK = "JobHarness-{slug}"
UNIT = "job-harness-{slug}"


def plist_path(slug: str) -> Path:
    return Path.home() / f"Library/LaunchAgents/{LABEL.format(slug=slug)}.plist"


def job_env() -> dict[str, str]:
    """PATH plus the JOB_* settings of the shell that installs the schedule (e.g. JOB_PACKAGE_DIR), so the
    unattended run behaves like the owner's terminal."""
    env = {"PATH": os.environ.get("PATH", "")} | {k: v for k, v in os.environ.items() if k.startswith("JOB_")}
    if (pkg := setting("JOB_PACKAGE_DIR", "")):                 # also when installed from a shell without it
        env["JOB_PACKAGE_DIR"] = pkg
    return env


def env_xml() -> str:
    return "".join(f"<key>{k}</key><string>{v}</string>" for k, v in sorted(job_env().items()))


def runner_py(runner: str) -> Path:
    return ROOT / "scripts" / ("run_prepare.py" if runner == "prepare" else "run_daily.py")


def run_argv(slug: str, runner: str, with_env: bool = False) -> list[str]:
    """Our own interpreter + runner; Task Scheduler has no environment, so JOB_* travel as --env arguments."""
    env = [x for k, v in sorted(job_env().items()) if k.startswith("JOB_") for x in ("--env", f"{k}={v}")] if with_env else []
    return [*osutil.python(), str(runner_py(runner)), slug, *env]


def sd_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def systemd_units(slug: str, hour: int, minute: int, runner: str) -> dict[Path, str]:
    d = Path.home() / ".config/systemd/user"
    env = "".join(f"Environment={sd_quote(f'{k}={v}')}\n" for k, v in sorted(job_env().items()))
    service = f"[Unit]\nDescription=job-harness daily run ({slug})\n\n[Service]\nType=oneshot\nWorkingDirectory={sd_quote(str(ROOT))}\n" \
              f"ExecStart={' '.join(sd_quote(x) for x in run_argv(slug, runner))}\n{env}"
    timer = f"[Unit]\nDescription=job-harness daily timer ({slug})\n\n[Timer]\nOnCalendar=*-*-* {hour:02d}:{minute:02d}:00\n" \
            "Persistent=true\n\n[Install]\nWantedBy=timers.target\n"
    return {d / f"{UNIT.format(slug=slug)}.service": service, d / f"{UNIT.format(slug=slug)}.timer": timer}


def crontab_line(slug: str, hour: int, minute: int, runner: str) -> str:
    env = " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(job_env().items()) if k.startswith("JOB_"))
    return f"{minute} {hour} * * * cd {shlex.quote(str(ROOT))} && {env + ' ' if env else ''}{shlex.join(run_argv(slug, runner))}"


def plan_install(slug: str, hour: int, minute: int, runner: str, name: str) -> dict:
    """What install would do on this OS: files to write, commands to run ((argv, ignore failure)), where it lives, a note."""
    if name == "mac":
        script = ROOT / ("scripts/run_prepare.sh" if runner == "prepare" else "scripts/run_daily.sh")
        uid = str(os.getuid())
        p = plist_path(slug)
        return {"files": {p: plist(slug, hour, minute, runner)}, "where": str(p), "note": "",
                "cmds": [(["launchctl", "bootout", f"gui/{uid}", str(p)], True), (["launchctl", "bootstrap", f"gui/{uid}", str(p)], False)]}
    if name == "win":
        tr = subprocess.list2cmdline(run_argv(slug, runner, with_env=True))
        return {"files": {}, "where": f"task {TASK.format(slug=slug)}", "note": "",
                "cmds": [(["schtasks", "/Create", "/SC", "DAILY", "/ST", f"{hour:02d}:{minute:02d}", "/TN", TASK.format(slug=slug), "/TR", tr, "/F"], False)]}
    if shutil.which("systemctl"):
        timer = f"{UNIT.format(slug=slug)}.timer"
        return {"files": systemd_units(slug, hour, minute, runner), "where": f"systemd user timer {timer}", "note": "",
                "cmds": [(["systemctl", "--user", "daemon-reload"], False), (["systemctl", "--user", "enable", "--now", timer], False)]}
    return {"files": {}, "cmds": [], "where": "crontab",
            "note": f"systemd was not found. Add this line with `crontab -e`:\n{crontab_line(slug, hour, minute, runner)}"}


def control_argv(action: str, slug: str, name: str) -> list[str]:
    """Command for uninstall / status."""
    if name == "mac":
        target = f"gui/{os.getuid()}/{LABEL.format(slug=slug)}" if action == "status" else f"gui/{os.getuid()}"
        return ["launchctl", "print", target] if action == "status" else ["launchctl", "bootout", target, str(plist_path(slug))]
    if name == "win":
        t = TASK.format(slug=slug)
        return ["schtasks", "/Query", "/TN", t] if action == "status" else ["schtasks", "/Delete", "/TN", t, "/F"]
    timer = f"{UNIT.format(slug=slug)}.timer"
    return ["systemctl", "--user", "is-enabled", timer] if action == "status" else ["systemctl", "--user", "disable", "--now", timer]


def sh(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True)
    except OSError as e:
        return subprocess.CompletedProcess(argv, 127, "", str(e))


def show(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if osutil.os_name() == "win" else shlex.join(argv)


def package_hint(slug: str) -> str:
    from panel import pkg_root
    return f"The package will appear in {pkg_root(slug) / today()} — see it with `job panel`."


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
  <key>EnvironmentVariables</key><dict>{env_xml()}</dict>
</dict></plist>
"""


def install(a: argparse.Namespace, name: str) -> None:
    pl = plan_install(a.slug, a.hour, a.minute, a.runner, name)
    if a.print:
        for path, text in pl["files"].items():
            print(f"# {path}\n{text}")
        for argv, _ in pl["cmds"]:
            print("$", show(argv))
        return print(pl["note"]) if pl["note"] else None
    (cand_dir(a.slug) / "logs").mkdir(exist_ok=True)
    for path, text in pl["files"].items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for argv, ignore in pl["cmds"]:
        r = sh(argv)
        if r.returncode and not ignore:
            return print(r.stderr or r.stdout)
    if pl["note"]:
        return print(pl["note"])
    rand = " (+0–20 min random)" if name == "mac" or a.runner == "agent" else ""
    print(f"installed {pl['where']} at {a.hour:02d}:{a.minute:02d}{rand}\nIt runs every day. {package_hint(a.slug)}\n"
          f"To try it now: job schedule run-now {a.slug}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["install", "uninstall", "status", "run-now"]); ap.add_argument("slug")
    ap.add_argument("--hour", type=int, default=9); ap.add_argument("--minute", type=int, default=0)
    ap.add_argument("--runner", choices=["prepare", "agent"], default="prepare",
                    help="prepare = scripts only (default); agent = Claude + browser (run_daily)")
    ap.add_argument("--print", action="store_true", help="show what would be installed or run, change nothing")
    a = ap.parse_args()
    name = osutil.os_name()
    if a.cmd == "install":
        return install(a, name)
    if a.cmd == "run-now":
        cmd = run_argv(a.slug, a.runner)
        if a.print:
            return print("$", show(cmd), "(JOB_NO_DELAY=1)")
        subprocess.Popen(cmd, env=os.environ | {"JOB_NO_DELAY": "1"})
        return print(f"Started. {package_hint(a.slug)}\nlog: {cand_dir(a.slug)}/logs/")
    argv = control_argv(a.cmd, a.slug, name)
    if a.print:
        return print("$", show(argv))
    r = sh(argv)
    if a.cmd == "uninstall":
        print(f"unloaded {LABEL.format(slug=a.slug)} (plist kept at {plist_path(a.slug)}; remove it yourself if you want)" if name == "mac"
              else f"removed the daily schedule for {a.slug}" + ("" if r.returncode == 0 else f" ({(r.stderr or r.stdout).strip()})"))
    else:
        where = {"mac": plist_path(a.slug), "win": TASK.format(slug=a.slug)}.get(name, UNIT.format(slug=a.slug))
        print("loaded" if r.returncode == 0 else "not loaded", "·", where if name != "mac" or plist_path(a.slug).exists() else "no plist")

if __name__ == "__main__":
    main()
