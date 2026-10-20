"""Candidate state: stages, run mode (dry-run/live), limits and open questions.

candidates/<slug>/state.json is harness bookkeeping: only this script writes it (the hook blocks
hand edits). The narrative context lives in progress.md.

  job state <slug> show
  job state <slug> stage <n> --status done|pending [--summary "..."]
  job state <slug> mode dry-run|live          (live needs a signed, intact go-live approval)
  job state <slug> limits --per-platform 5 --per-day 10 --per-week 40
  job ask <slug> add "Who issued the First Aid certificate?" --blocks 4
  job ask <slug> list
  job ask <slug> close <id> --answer "..."
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from common import HARNESS_VERSION, cand_dir, now_iso, read_json, save_json

STAGES = {
    0: "Intake: read the candidate folder",
    1: "Profile and gaps: intake.json, inconsistencies, questions",
    2: "Target tracks: role titles, keywords, exclusions",
    3: "Master documents: one CV per track + cover letter",
    4: "Platform profiles: audit, proposal, apply approved changes",
    5: "Alerts: saved searches per track",
    6: "Daily cycle in dry-run",
    7: "Go-live: automatic submissions within limits",
}
MODES = ("prepare", "easy", "full", "dry-run", "live")
# prepare = scripts pick + build docs, the person applies · easy = prepare + scripted SEEK Quick Apply (job apply)
# full = easy + company-site forms without account creation (agent, Claude in Chrome) · dry-run/live = legacy agent modes


def default_state(slug: str) -> dict[str, Any]:
    return {"candidate": slug, "harness_version": HARNESS_VERSION, "mode": "dry-run",
            "limits": {"per_platform": 5, "per_day": 10, "per_week": 40},
            "stages": {str(k): {"name": v, "status": "pending"} for k, v in STAGES.items()},
            "open_questions": [], "history": []}


def load_state(slug: str) -> dict[str, Any]:
    p = cand_dir(slug) / "state.json"
    return read_json(p) if p.exists() else default_state(slug)


def save_state(slug: str, st: dict[str, Any]) -> None:
    st["harness_version"] = HARNESS_VERSION
    save_json(cand_dir(slug) / "state.json", st)


def event(st: dict[str, Any], kind: str, detail: str) -> None:
    st["history"].append({"date": now_iso(), "event": kind, "detail": detail})


def set_stage(slug: str, n: int, status: str, summary: str = "") -> dict[str, Any]:
    st = load_state(slug)
    e = st["stages"].setdefault(str(n), {"name": STAGES.get(n, "?"), "status": "pending"})
    e.update(status=status, updated=now_iso())
    if summary:
        e["summary"] = summary
    event(st, "stage", f"{n} → {status}" + (f": {summary}" if summary else ""))
    save_state(slug, st)
    return st


def set_mode(slug: str, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise SystemExit(f"mode must be one of {MODES}")
    if mode == "live":
        from gates import valid_approval
        ok, why = valid_approval(slug, "go-live")
        if not ok:
            raise SystemExit(f"Cannot switch to live: {why}. Request it with `job gate request {slug} --type go-live ...` "
                             "and have the person sign it.")
    st = load_state(slug)
    st["mode"] = mode
    event(st, "mode", mode)
    save_state(slug, st)
    return st


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    p = sub.add_parser("stage"); p.add_argument("n", type=int); p.add_argument("--status", required=True,
                                                                              choices=["pending", "in-progress", "done", "blocked"])
    p.add_argument("--summary", default="")
    p = sub.add_parser("mode"); p.add_argument("mode", choices=MODES)
    p = sub.add_parser("limits")
    for k in ("per-platform", "per-day", "per-week"):
        p.add_argument(f"--{k}", type=int)
    p = sub.add_parser("ask"); p.add_argument("action", choices=["add", "list", "close"]); p.add_argument("rest", nargs="*")
    p.add_argument("--blocks", type=int); p.add_argument("--answer", default="")
    a = ap.parse_args()

    if a.cmd == "show":
        print(json.dumps(load_state(a.slug), ensure_ascii=False, indent=2))
    elif a.cmd == "stage":
        set_stage(a.slug, a.n, a.status, a.summary); print(f"stage {a.n} → {a.status}")
    elif a.cmd == "mode":
        set_mode(a.slug, a.mode); print(f"mode → {a.mode}")
    elif a.cmd == "limits":
        st = load_state(a.slug)
        for k in ("per_platform", "per_day", "per_week"):
            v = getattr(a, k)
            if v is not None:
                st["limits"][k] = v
        event(st, "limits", json.dumps(st["limits"])); save_state(a.slug, st); print(st["limits"])
    elif a.cmd == "ask":
        st = load_state(a.slug)
        qs = st["open_questions"]
        if a.action == "add":
            q = {"id": f"q{len(qs) + 1}", "question": " ".join(a.rest), "blocks": a.blocks, "status": "open", "date": now_iso()}
            qs.append(q); event(st, "ask", q["question"]); save_state(a.slug, st); print(q["id"])
        elif a.action == "list":
            for q in qs:
                if q["status"] == "open":
                    print(f"{q['id']}  {q['question']}" + (f"  (blocks stage {q['blocks']})" if q.get("blocks") is not None else ""))
        else:
            for q in qs:
                if q["id"] == (a.rest[0] if a.rest else ""):
                    q.update(status="closed", answer=a.answer, closed=now_iso())
            save_state(a.slug, st); print("closed")


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    main()
