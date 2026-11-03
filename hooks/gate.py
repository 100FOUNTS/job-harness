#!/usr/bin/env python3
"""PreToolUse hook: the rules that must hold even if the agent gets them wrong.

Blocks (exit 2, reason on stderr):
1. Reading secrets (.env, credentials).
2. Hand-editing bookkeeping: state.json, facts.json, tracker.json, jobs.db, approvals/ (only the scripts write them).
3. Human signatures from the agent: `job sign` without --by-agent, any --confirm, or a file that wraps them.
4. Deleting candidate data from the shell, and "delete/remove" clicks in the browser
   (the harness never deletes anything in the person's accounts).
5. Submitting an application in the browser unless a candidate is in mode live with a valid, intact go-live.
6. Reading browser profiles (.browser/, session cookies) and ~/.ssh, ~/.aws.

Asks (permissionDecision "ask": the person approves with one click, nothing is blocked):
7. Changing the harness's own rules: hooks/, bin/, scripts/gates.py, .claude/settings*.json. A job ad aimed at an AI
   cannot silently rewrite them; the person can still approve any change they asked for.

Honest limits: these are pattern checks. They stop mistakes and casual workarounds, not deliberate obfuscation;
the tracker and approval records are what make every action visible afterwards. An "ask" cannot be answered in an
unattended `claude -p` run (the daily schedule), so no rule change happens overnight: that is intended.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", HARNESS))
sys.path.insert(0, str(HARNESS / "scripts"))
for _s in (sys.stdin, sys.stdout, sys.stderr):      # Windows pipes default to cp1252: Claude Code speaks UTF-8
    if hasattr(_s, "reconfigure") and (_s.encoding or "").lower().replace("-", "") != "utf8":
        _s.reconfigure(encoding="utf-8", errors="replace")
JOB_CMD = re.compile(r"(^|[\s;&|(])(\S*/)?job(\.cmd)?\s")

BOOKKEEPING = re.compile(r"candidates/[^/]+/(state\.json|facts\.json|tracker\.json|jobs\.db|approvals/)")
SECRET = re.compile(r"(^|[/\s'\"])\.env(\b|$)|credentials|\.netrc|id_rsa", re.I)
SIGN = re.compile(r"\b(job|gates\.py)\b[^\n;|&]*\bsign\b")
DELETE_SHELL = re.compile(r"\b(rm|rmdir|unlink|trash|shred)\b[^\n;|&]*candidates|git\s+clean", re.I)
SUBMIT = re.compile(r"\b(submit|send)(s|ting|ted|ing)?\b[^.]{0,40}\b(application|applic|cv|resum)|\bsubmit(s|ting|ted)?\b|\bsend(s|ing)? (the |my )?application\b", re.I)
DELETE_UI = re.compile(r"\b(delet|remov)(e|es|ed|ing)\b[^.]{0,40}\b(resum|cv|publication|certification|experience|education|account|search|alert|post)", re.I)


SECRET_DIR = re.compile(r"(^|[/\s'\"=~])\.(browser|ssh|aws)(/|\s*$|['\"]?(\s|$))")
SECRET_DIR_READ = re.compile(r"\b(cat|less|more|head|tail|grep|rg|awk|sed|cut|strings|xxd|od|base64|cp|mv|tar|zip|scp|rsync|sqlite3|source|open)\b")
PROTECTED = re.compile(r"^(hooks/(?!__pycache__)|bin/|scripts/gates\.py$|\.claude/settings(\.local)?\.json$)")
SHELL_SPLIT = re.compile(r"&&|\|\||[;|\n]")
REDIRECT = re.compile(r"(?<![<>&\d])\d?>>?\s*([^\s&|;<>]+)")
WRITE_ALL = {"rm", "mv", "tee", "truncate", "chmod", "unlink", "rmdir"}   # any protected argument is a change
WRITE_LAST = {"cp", "install", "ln"}                                      # only the destination (last argument)


def block(msg: str) -> None:
    print(f"[job-harness gate] {msg}", file=sys.stderr)
    sys.exit(2)


def ask(path: str) -> None:
    reason = f"This changes the harness's own rules ({path}). Approve only if you asked for it."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


def protected(path: str) -> str:
    """The protected path (relative to the project) that `path` names, or ''."""
    p = path.strip("'\"").replace("\\", "/")
    for root in {str(ROOT).replace("\\", "/"), str(ROOT.resolve()).replace("\\", "/")}:
        if p.startswith(root + "/"):
            p = p[len(root) + 1:]
    p = re.sub(r"^(\./)+", "", p)
    return p if PROTECTED.match(p) else ""


def shell_writes(cmd: str) -> str:
    """The first protected path a shell command clearly writes to (redirect, tee, sed -i, cp/mv/rm, git checkout/restore)."""
    for seg in SHELL_SPLIT.split(cmd.replace("\\\n", " ")):
        for m in REDIRECT.finditer(seg):
            if protected(m.group(1)):
                return protected(m.group(1))
        try:
            words = shlex.split(seg)
        except ValueError:
            words = seg.split()
        while words and (words[0] in ("sudo", "command", "env") or re.match(r"\w+=", words[0])):
            words = words[1:]
        if not words:
            continue
        verb, args = Path(words[0]).name, [w for w in words[1:] if not w.startswith("-") or w == "--"]
        if verb in WRITE_LAST:
            args = args[-1:]
        elif verb in ("sed", "perl", "ruby") and any(re.match(r"-\w*i", w) for w in words[1:]):
            pass
        elif verb == "git" and args[:1] in (["checkout"], ["restore"], ["rm"], ["stash"], ["reset"]):
            pass
        elif verb not in WRITE_ALL:
            continue
        for a in args:
            if protected(a):
                return protected(a)
    return ""


def live_allowed() -> bool:
    try:
        from common import list_candidates
        from gates import valid_approval
        from state import load_state
        return any(load_state(s)["mode"] == "live" and valid_approval(s, "go-live")[0] for s in list_candidates())
    except Exception:
        return False


def browser_texts(tool: str, inp: dict) -> list[str]:
    items = inp.get("actions") if tool.endswith("browser_batch") else [{"name": tool, "input": inp}]
    out = []
    for it in items or []:
        i = it.get("input", {}) if isinstance(it, dict) else {}
        out += [str(i.get("action_summary", "")), str(i.get("text", "")) if i.get("action") != "type" else ""]
        if "javascript" in str(it.get("name", tool)):
            out.append(str(i.get("text", "")))
    return [t for t in out if t]


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool, inp = data.get("tool_name", ""), data.get("tool_input", {}) or {}
    touched = ""
    try:                                   # installed as a plugin: other projects are left alone, but `job ...` is always gated
        from common import plugin_mode, workspace
        if plugin_mode() and not workspace(ROOT) and not (tool == "Bash" and JOB_CMD.search(str(inp.get("command", "")))):
            sys.exit(0)
    except ImportError:
        pass

    if tool in ("Read", "Grep", "Glob"):
        target = str(inp.get("file_path") or inp.get("path") or inp.get("pattern") or "").replace("\\", "/")
        if SECRET.search(target):
            block("Do not read secrets. Use `job doctor` to see what is configured.")
        if any(SECRET_DIR.search(str(inp.get(k) or "").replace("\\", "/")) for k in ("file_path", "path", "glob") + (("pattern",) if tool == "Glob" else ())):
            block("Do not read browser profiles or SSH/AWS keys: they hold session cookies and credentials.")
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        fp = str(inp.get("file_path") or inp.get("notebook_path") or "")
        touched = protected(fp)
        if BOOKKEEPING.search(fp):
            block(f"{fp} is bookkeeping: change it through `job state|facts|track|gate`, never by hand.")
        content = str(inp.get("content", "")) + str(inp.get("new_string", ""))
        if re.search(r"\.(sh|py|js|command)$|/bin/", fp) and SIGN.search(content):
            block("Do not write a script that signs approvals: signatures are given by the person.")
    if tool == "Bash":
        cmd = str(inp.get("command", ""))
        slashed = cmd.replace("\\", "/")             # Windows paths
        if SECRET.search(slashed) and re.search(r"\b(cat|less|head|tail|grep|source|env|printenv|open)\b", cmd):
            block("Do not read or dump secrets.")
        if SECRET_DIR.search(slashed) and SECRET_DIR_READ.search(cmd):
            block("Do not read browser profiles or SSH/AWS keys: they hold session cookies and credentials.")
        if SIGN.search(cmd.replace("\\\n", " ")) and ("--by-agent" not in cmd or "--confirm" in cmd):
            block("Human signatures are given by the person: they run `job sign <slug> <id>` in their terminal, "
                  f"or `! {'job' if 'plugins' in HARNESS.parts else 'bin/job'} sign <slug> <id> --confirm <slug>` in Claude Code. "
                  "Show them the command and wait.")
        if DELETE_SHELL.search(cmd):
            block("The harness never deletes candidate data.")
        touched = shell_writes(cmd)
    if tool.startswith("mcp__claude-in-chrome__") and tool.split("__")[-1] in (
            "computer", "form_input", "browser_batch", "javascript_tool"):
        texts = " | ".join(browser_texts(tool, inp))
        if DELETE_UI.search(texts):
            block("The harness never deletes anything in the person's accounts. Tell the user what to delete instead.")
        if SUBMIT.search(texts) and not live_allowed():
            block("Dry-run: do not submit. Leave the form filled, record `job track <slug> set <key> dry-run`, "
                  "and move on. Submitting needs mode live with a signed go-live approval.")
    if touched:
        ask(touched)
    sys.exit(0)


if __name__ == "__main__":
    main()
