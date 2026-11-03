"""Get this machine ready for the harness in one command. Safe to run again; installs no system software.

  job setup [--check] [--apply-tools]

  checks Python and Node.js (and prints the install command for your system if one is missing)
  npm install in templates/docs (document tools + PDF reader); as a plugin, into <data dir>/tools instead (a plugin
  update replaces the code folder, not this one; re-running notices a changed package.json and reinstalls)
  puts `job` on your PATH (macOS/Linux: a link in ~/.local/bin; Windows: how to run bin\\job.cmd)
  creates the package folder (JOB_PACKAGE_DIR, default ~/job-packages)
  --apply-tools  also installs Playwright in apply/ (only for scripted SEEK Quick Apply)
  --check        change nothing, only report
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import doctor
from common import ROOT, apply_tools_dir, data_dir, plugin_mode, remember_root, tools_dir

DOCS, APPLY = ROOT / "templates/docs", ROOT / "apply"      # where the code and package.json live
HASH = ".package.hash"
DOC_MODULES = ("docx", "pdfkit", "pdfjs-dist")


def say(ok: bool, msg: str, optional: bool = False) -> bool:
    print(f"{doctor.mark(ok, optional)} {msg}")
    return ok


def npm(args: list[str], cwd: Path) -> bool:
    exe = shutil.which("npm")
    return bool(exe) and subprocess.run([exe, *args], cwd=cwd).returncode == 0


def step_python() -> bool:
    ok = sys.version_info[:2] >= doctor.MIN_PY
    return say(ok, f"Python {sys.version.split()[0]}" if ok else
               f"Python {sys.version.split()[0]} is too old (need 3.9+). Install: {doctor.install_hint('python')}")


def step_node() -> bool:
    v = doctor.node_version()
    if v >= doctor.MIN_NODE and shutil.which("npm"):
        return say(True, f"Node.js {v}")
    why = "not found" if not v else f"{v} is too old (need 20+)" if v < doctor.MIN_NODE else "npm is missing"
    return say(False, f"Node.js {why}. Install it, open a new terminal and run `job setup` again:\n    {doctor.install_hint('node')}")


def pkg_hash(src: Path) -> str:
    h = hashlib.sha256()
    for name in ("package.json", "package-lock.json"):
        if (src / name).is_file():
            h.update((src / name).read_bytes())
    return h.hexdigest()


def step_tools(folder: Path, modules: tuple[str, ...], what: str, check: bool, extra: list[str] | None = None,
               src: Path | None = None) -> bool:
    """Install the Node deps of `src` (package.json + lock) into `folder`. folder == src is a clone (npm install in
    place). Otherwise (plugin) the package files are copied to folder, and a hash of them tells a later run that an
    update changed the dependencies."""
    src = src or folder
    hf = folder / HASH
    stale = folder != src and (not hf.is_file() or hf.read_text().strip() != pkg_hash(src))
    if all((folder / "node_modules" / m).exists() for m in modules) and not stale:
        return say(True, f"{what} installed")
    if check:
        return say(False, f"{what} " + ("out of date" if stale and (folder / "node_modules").exists() else "not installed")
                   + " (`job setup` installs it)")
    print(f"... installing {what} (a minute or two)")
    args = ["--no-audit", "--no-fund", *(extra or [])]
    if folder == src:
        ok = npm(["install", *args], folder)
    else:
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("package.json", "package-lock.json"):
            if (src / name).is_file():
                shutil.copyfile(src / name, folder / name)
        ok = (src / "package-lock.json").is_file() and npm(["ci", *args], folder) or npm(["install", *args], folder)
        if ok:
            hf.write_text(pkg_hash(src) + "\n")
    return say(ok, f"{what} installed" if ok else f"{what}: npm install failed in {folder} (check your internet connection and retry)")


def step_playwright(check: bool) -> bool:
    dest = apply_tools_dir()
    if check:
        return say((dest / "node_modules/playwright").exists(), "Playwright (apply/)", optional=True)
    if not step_tools(dest, ("playwright",), "Playwright", False, src=APPLY):
        return False
    npx = shutil.which("npx")
    ok = bool(npx) and subprocess.run([npx, "playwright", "install", "chromium"], cwd=dest).returncode == 0
    return say(ok, "Chromium for Playwright installed" if ok else "Chromium for Playwright failed: run `npx playwright install chromium` in apply/")


def rc_hint(bin_dir: Path) -> str:
    shell = Path(os.environ.get("SHELL", "")).name
    line = 'export PATH="$HOME/.local/bin:$PATH"'
    if shell == "fish":
        return "fish_add_path ~/.local/bin"
    rc = {"zsh": "~/.zshrc", "bash": "~/.bashrc"}.get(shell, "your shell's startup file")
    return f"echo '{line}' >> {rc}   then open a new terminal"


def step_path(check: bool) -> bool:
    if plugin_mode():                     # the plugin's bin/ is on Claude Code's PATH; a link into the cache would break on update
        return say(True, "`job` is available inside Claude Code (plugin)")
    job = ROOT / "bin/job"
    if os.name == "nt":
        cmd = ROOT / "bin" / "job.cmd"
        run = cmd if cmd.exists() else f"python {job}"
        return say(True, f"On Windows run: {run} doctor\n    To type just `job` anywhere, add this folder to PATH (Start menu: \"environment variables\" > Path > New):\n    {ROOT / 'bin'}")
    bin_dir = Path.home() / ".local/bin"
    link = bin_dir / "job"
    if link.is_symlink() and link.resolve() == job.resolve():
        ok = say(True, f"`job` link in {bin_dir}")
    elif link.exists() or link.is_symlink():
        return say(False, f"{link} already exists and is not this harness; remove it or link {job} somewhere on your PATH yourself")
    elif check:
        ok = say(False, f"`job` is not on your PATH (`job setup` links it in {bin_dir})")
    else:
        bin_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(job, os.X_OK):
            job.chmod(job.stat().st_mode | 0o755)
        link.symlink_to(job)
        ok = say(True, f"linked `job` in {bin_dir}")
    if ok and str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"  {bin_dir} is not on your PATH yet. Run once: {rc_hint(bin_dir)}")
    return ok


def step_package(check: bool) -> bool:
    pkg = doctor.package_dir()
    if pkg.exists():
        return say(True, f"Package folder {pkg}")
    if check:
        return say(False, f"Package folder {pkg} does not exist yet (`job setup` creates it)")
    try:
        pkg.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return say(False, f"Can't create the package folder {pkg}: {e.strerror}. Set JOB_PACKAGE_DIR in .claude/settings.local.json to a folder you own")
    return say(True, f"Created the package folder {pkg}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="change nothing, only report")
    ap.add_argument("--apply-tools", action="store_true", help="also install Playwright for SEEK Quick Apply (apply/)")
    a = ap.parse_args()
    if not a.check:
        remember_root()                 # plugin: schedules find the current code through <data dir>/.harness_root
    ok = step_python()
    node = ok and step_node()
    if not node and not a.check:
        sys.exit(1)
    if node:
        step_tools(tools_dir(), DOC_MODULES, "Document tools and PDF reader", a.check, ["--omit=optional"], src=DOCS)
    if a.apply_tools and node:
        step_playwright(a.check)
    step_path(a.check)
    step_package(a.check)
    print()
    bad = doctor.show(doctor.gather())
    if not bad:
        print(f"\nNext: open Claude Code in {data_dir()} and type /job-harness:job-start" if plugin_mode()
              else "\nNext: open Claude Code in this folder and type /job-onboard 0 <your-name>")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
