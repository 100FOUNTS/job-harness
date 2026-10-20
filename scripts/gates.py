"""Sealed approvals: what a person approved is bound to the sha256 of the files.

If an approved file changes later, the seal breaks and the approval stops counting
(e.g. editing intake.json after go-live puts the daily run back in dry-run).

  job gate request <slug> --type master-docs|profile-changes|go-live|targets|report --files a b --description "..."
  job gate list <slug>
  job gate verify <slug>
  job review <slug> <id>
  job sign <slug> <id>                 human signature: needs the candidate slug typed in YOUR terminal
  job sign <slug> <id> --confirm <slug> same, from Claude Code with `!` (runs as you, not as the agent)
  job sign <slug> <id> --by-agent --note "User approved in chat: '...'"   only for AGENT_OK types
  job gate reject <slug> <id> --note "..."
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from common import cand_dir, now_iso, read_json, save_json

TYPES = ("master-docs", "profile-changes", "go-live", "targets", "report")
AGENT_OK = {"master-docs", "profile-changes", "go-live", "targets", "report"}  # agent signs ONLY after an explicit OK in
                                                                     # chat, recording the user's exact words in --note


def human_floor() -> set[str]:
    """Types only a person can sign. Default: go-live. An owner who wants to approve everything from the chat sets
    JOB_HUMAN_SIGN="" (or a comma list) in their environment."""
    return {t for t in os.environ.get("JOB_HUMAN_SIGN", "go-live").split(",") if t}


def adir(slug: str) -> Path:
    d = cand_dir(slug) / "approvals"
    d.mkdir(exist_ok=True)
    return d


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_all(slug: str) -> list[dict[str, Any]]:
    return [read_json(p) | {"_path": str(p)} for p in sorted(adir(slug).glob("*.json"))]


def find(slug: str, gid: str) -> dict[str, Any]:
    for g in load_all(slug):
        if g["id"] == gid:
            return g
    raise SystemExit(f"Approval '{gid}' not found. `job gate list {slug}`")


def seals_ok(slug: str, g: dict[str, Any]) -> tuple[bool, list[str]]:
    base = cand_dir(slug)
    broken = [f for f, h in g["files"].items() if not (base / f).exists() or sha(base / f) != h]
    return (not broken), broken


def valid_approval(slug: str, typ: str) -> tuple[bool, str]:
    signed = [g for g in load_all(slug) if g["type"] == typ and g["status"] == "signed"]
    if not signed:
        return False, f"no signed '{typ}' approval"
    g = signed[-1]
    ok, broken = seals_ok(slug, g)
    return (True, g["id"]) if ok else (False, f"'{g['id']}' seal broken by changes in: {', '.join(broken)}")


def request(slug: str, typ: str, files: list[str], description: str) -> str:
    base = cand_dir(slug)
    for f in files:
        if not (base / f).exists():
            raise SystemExit(f"File not found (relative to candidate folder): {f}")
    n = len([g for g in load_all(slug) if g["type"] == typ]) + 1
    gid = f"{typ}-{n:02d}"
    save_json(adir(slug) / f"{now_iso()[:10]}-{gid}.json",
              {"id": gid, "type": typ, "status": "pending", "requested": now_iso(), "description": description,
               "files": {f: sha(base / f) for f in files}, "signed_by": None})
    return gid


def write(g: dict[str, Any]) -> None:
    p = Path(g.pop("_path"))
    save_json(p, g)


def sign(slug: str, gid: str, by_agent: bool, note: str, confirm: str | None) -> None:
    g = find(slug, gid)
    if g["status"] != "pending":
        raise SystemExit(f"{gid} is {g['status']}, not pending")
    ok, broken = seals_ok(slug, g)
    if not ok:
        raise SystemExit(f"Seal already broken ({', '.join(broken)}). Request a new approval.")
    if by_agent:
        if g["type"] in human_floor():
            raise SystemExit(f"'{g['type']}' needs a human signature. Ask the person to run: job sign {slug} {gid}")
        if not note.startswith("User approved in chat:"):
            raise SystemExit('--by-agent needs --note "User approved in chat: \'<their words>\'"')
        g["signed_by"] = {"by": "agent", "note": note, "date": now_iso()}
    else:
        typed = confirm
        if typed is None:
            if not sys.stdin.isatty():
                raise SystemExit("A human signature needs an interactive terminal (or `!` in Claude Code with --confirm).")
            print(json.dumps({k: g[k] for k in ("id", "type", "description", "files")}, indent=2, ensure_ascii=False))
            typed = input(f"Type the candidate slug '{slug}' to sign: ").strip()
        if typed != slug:
            raise SystemExit("Confirmation does not match. Not signed.")
        g["signed_by"] = {"by": "human", "note": note, "date": now_iso()}
    g["status"] = "signed"
    write(g)
    print(f"✅ {gid} signed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("request"); p.add_argument("--type", required=True, choices=TYPES)
    p.add_argument("--files", nargs="+", required=True); p.add_argument("--description", required=True)
    sub.add_parser("list"); sub.add_parser("verify")
    p = sub.add_parser("review"); p.add_argument("id")
    p = sub.add_parser("sign"); p.add_argument("id"); p.add_argument("--by-agent", action="store_true")
    p.add_argument("--note", default=""); p.add_argument("--confirm")
    p = sub.add_parser("reject"); p.add_argument("id"); p.add_argument("--note", default="")
    a = ap.parse_args()

    if a.cmd == "request":
        gid = request(a.slug, a.type, a.files, a.description)
        print(f"Requested {gid}. The person reviews with `job review {a.slug} {gid}` and signs with `job sign {a.slug} {gid}`.")
    elif a.cmd == "list":
        for g in load_all(a.slug):
            ok, _ = seals_ok(a.slug, g)
            print(f"{g['id']:22} {g['status']:9} {'seal ok' if ok else 'SEAL BROKEN'}  {g['description']}")
    elif a.cmd == "verify":
        bad = [(g["id"], seals_ok(a.slug, g)[1]) for g in load_all(a.slug) if g["status"] == "signed" and not seals_ok(a.slug, g)[0]]
        print(json.dumps({"ok": not bad, "broken": bad}, indent=2))
        sys.exit(1 if bad else 0)
    elif a.cmd == "review":
        g = find(a.slug, a.id); ok, broken = seals_ok(a.slug, g); g.pop("_path")
        print(json.dumps(g | {"seal_ok": ok, "broken": broken}, indent=2, ensure_ascii=False))
    elif a.cmd == "sign":
        sign(a.slug, a.id, a.by_agent, a.note, a.confirm)
    elif a.cmd == "reject":
        g = find(a.slug, a.id); g.update(status="rejected", rejected={"note": a.note, "date": now_iso()}); write(g); print("rejected")


if __name__ == "__main__":
    main()
