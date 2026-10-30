#!/usr/bin/env python3
"""PreToolUse hook: the rules that must hold even if the agent gets them wrong.

Blocks (exit 2, reason on stderr):
1. Reading secrets (.env, credentials).
2. Hand-editing bookkeeping: state.json, facts.json, tracker.json, jobs.db, approvals/ (only the scripts write them).
3. Human signatures from the agent: `job sign` without --by-agent, any --confirm, or a file that wraps them.
4. Deleting candidate data from the shell, and "delete/remove" clicks in the browser
   (the harness never deletes anything in the person's accounts).
5. Submitting an application in the browser unless a candidate is in mode live with a valid, intact go-live.

Honest limit: these are pattern checks. They stop mistakes and casual workarounds, not deliberate obfuscation;
the tracker and approval records are what make every action visible afterwards.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT / "scripts"))

BOOKKEEPING = re.compile(r"candidates/[^/]+/(state\.json|facts\.json|tracker\.json|jobs\.db|approvals/)")
SECRET = re.compile(r"(^|[/\s'\"])\.env(\b|$)|credentials|\.netrc|id_rsa", re.I)
SIGN = re.compile(r"\b(job|gates\.py)\b[^\n;|&]*\bsign\b")
DELETE_SHELL = re.compile(r"\b(rm|rmdir|unlink|trash|shred)\b[^\n;|&]*candidates|git\s+clean", re.I)
SUBMIT = re.compile(r"\b(submit|send)(s|ting|ted|ing)?\b[^.]{0,40}\b(application|applic|cv|resum)|\bsubmit(s|ting|ted)?\b|\bsend(s|ing)? (the |my )?application\b", re.I)
DELETE_UI = re.compile(r"\b(delet|remov)(e|es|ed|ing)\b[^.]{0,40}\b(resum|cv|publication|certification|experience|education|account|search|alert|post)", re.I)


def block(msg: str) -> None:
    print(f"[job-harness gate] {msg}", file=sys.stderr)
    sys.exit(2)


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

    if tool in ("Read", "Grep", "Glob"):
        target = str(inp.get("file_path") or inp.get("path") or inp.get("pattern") or "")
        if SECRET.search(target):
            block("Do not read secrets. Use `job doctor` to see what is configured.")
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        fp = str(inp.get("file_path", ""))
        if BOOKKEEPING.search(fp):
            block(f"{fp} is bookkeeping: change it through `job state|facts|track|gate`, never by hand.")
        content = str(inp.get("content", "")) + str(inp.get("new_string", ""))
        if re.search(r"\.(sh|py|js|command)$|/bin/", fp) and SIGN.search(content):
            block("Do not write a script that signs approvals: signatures are given by the person.")
    if tool == "Bash":
        cmd = str(inp.get("command", ""))
        if SECRET.search(cmd) and re.search(r"\b(cat|less|head|tail|grep|source|env|printenv|open)\b", cmd):
            block("Do not read or dump secrets.")
        if SIGN.search(cmd.replace("\\\n", " ")) and ("--by-agent" not in cmd or "--confirm" in cmd):
            block("Human signatures are given by the person: they run `job sign <slug> <id>` in their terminal, "
                  "or `! bin/job sign <slug> <id> --confirm <slug>` in Claude Code. Show them the command and wait.")
        if DELETE_SHELL.search(cmd):
            block("The harness never deletes candidate data.")
    if tool.startswith("mcp__claude-in-chrome__") and tool.split("__")[-1] in (
            "computer", "form_input", "browser_batch", "javascript_tool"):
        texts = " | ".join(browser_texts(tool, inp))
        if DELETE_UI.search(texts):
            block("The harness never deletes anything in the person's accounts. Tell the user what to delete instead.")
        if SUBMIT.search(texts) and not live_allowed():
            block("Dry-run: do not submit. Leave the form filled, record `job track <slug> set <key> dry-run`, "
                  "and move on. Submitting needs mode live with a signed go-live approval.")
    sys.exit(0)


if __name__ == "__main__":
    main()
