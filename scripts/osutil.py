"""The few things that differ per OS: opening a file or URL, a desktop notification, Chrome, our own interpreter.

Every function is best-effort: it returns False instead of raising, so a missing tool never stops a daily run.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

TOAST = r"""
$title = $env:JOB_NOTIFY_TITLE; $msg = $env:JOB_NOTIFY_MSG
try {
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
  $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
  $text = $xml.GetElementsByTagName('text')
  $text.Item(0).AppendChild($xml.CreateTextNode($title)) | Out-Null
  $text.Item(1).AppendChild($xml.CreateTextNode($msg)) | Out-Null
  $app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
} catch {
  Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing
  $n = New-Object System.Windows.Forms.NotifyIcon
  $n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true
  $n.ShowBalloonTip(5000, $title, $msg, [System.Windows.Forms.ToolTipIcon]::Info)
  Start-Sleep -Seconds 6; $n.Dispose()
}
"""


def os_name() -> str:
    return "mac" if sys.platform == "darwin" else "win" if sys.platform.startswith("win") else "linux"


def python() -> list[str]:
    """argv prefix for our own scripts: the interpreter that is running now (python3 does not exist on Windows)."""
    return [sys.executable or "python3"]


def _run(cmd: list[str], env: dict | None = None) -> bool:
    try:
        return subprocess.run(cmd, check=False, capture_output=True, env=env, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def open_path(target: str | Path) -> bool:
    """Open a folder, a file or a URL with the OS default app."""
    target = str(target)
    try:
        if os_name() == "win":
            os.startfile(target)  # type: ignore[attr-defined]
            return True
    except OSError:
        return False
    return _run(["open" if os_name() == "mac" else "xdg-open", target])


def notify_command(title: str, msg: str) -> tuple[list[str], dict | None] | None:
    """(argv, extra env) for a desktop notification on this OS, or None when no tool is available."""
    name = os_name()
    if name == "mac":
        return ["osascript", "-e", "on run argv", "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
                "-e", "end run", title, msg], None
    if name == "win":
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", TOAST], {"JOB_NOTIFY_TITLE": title, "JOB_NOTIFY_MSG": msg}
    return (["notify-send", title, msg], None) if shutil.which("notify-send") else None


def notify(title: str, msg: str) -> bool:
    cmd = notify_command(title, msg)
    if not cmd:
        return False
    argv, extra = cmd
    return _run(argv, os.environ | extra if extra else None)


def chrome_path() -> str | None:
    name = os_name()
    if name == "mac":
        return "Google Chrome"
    if name == "win":
        bases = [os.environ.get(v) for v in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData")]
        found = [Path(b) / "Google/Chrome/Application/chrome.exe" for b in bases if b]
        return next((str(p) for p in found if p.is_file()), None)
    return next((p for c in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser") if (p := shutil.which(c))), None)


def open_chrome(url: str, user_data_dir: str | Path) -> bool:
    """The person's own Chrome with a dedicated profile folder (so they log in once and it stays separate)."""
    chrome = chrome_path()
    if not chrome:
        return False
    args = [f"--user-data-dir={user_data_dir}", url]
    cmd = ["open", "-na", chrome, "--args", *args] if os_name() == "mac" else [chrome, *args]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
