"""Where every candidate is, and the exact next step.

  job status [slug] [--json]
  job status --context        (SessionStart hook: compact text injected when Claude opens)

Each candidate has one state a non-technical person can read at a glance: Setting up · Needs your decision ·
Working · Ready · Up to date (with one sentence and the exact next action).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

from common import cand_dir, list_candidates, plugin_mode, read_json, remember_root, today, workspace
from followup import line as followup_line
from gates import load_all, seals_ok, valid_approval
from learn import relevant
from suggest import line as suggestion_line
from run_prepare import STALE_HOURS, lock_path
from state import STAGES, load_state
from tracker import PENDING, load, quota

# lesson areas (see learn/observations.jsonl) that matter for each state of the work
STATE_AREAS = {"Setting up": ("intake", "docs", "ats", "linkedin", "seek", "seek-alerts", "linkedin-alerts"),
               "Needs your decision": ("review", "docs"),
               "Working": ("seek", "linkedin", "ats", "packages"),
               "Ready": ("packages", "review", "ats", "forms"),
               "Up to date": ("seek", "linkedin", "packages", "ats", "docs")}


def running(slug: str) -> bool:
    """A fresh run.lock means a daily run is going right now; an old one is a crashed run."""
    try:
        return time.time() - lock_path(slug).stat().st_mtime < STALE_HOURS * 3600
    except OSError:
        return False


def work_state(slug: str, pending: list[str], broken: list[str], questions: list[str], first_pending: int | None,
               apps: list[dict[str, Any]]) -> dict[str, str]:
    """One word + one sentence + the exact next action, derived from data that already exists."""
    if running(slug):
        return {"label": "Working", "why": "A run is in progress; it finishes by itself.", "action": "Wait a few minutes, then open the panel: `job panel`"}
    if pending or broken:
        gid = (pending or broken)[0]
        return {"label": "Needs your decision",
                "why": "An approval is waiting for you." if pending else "An approved document changed after you signed it.",
                "action": f"Review the approval: `job review {slug} {gid}`"}
    if questions:
        return {"label": "Needs your decision", "why": f"{len(questions)} question(s) need your answer.",
                "action": f"Read them with `job ask {slug} list` and answer in the Claude session."}
    if first_pending is not None and first_pending <= 5:
        return {"label": "Setting up", "why": f"Onboarding is not finished: next is step {first_pending} ({STAGES[first_pending].split(':')[0].lower()}).",
                "action": f"Continue in Claude: `/job-onboard {first_pending} {slug}`"}
    ready = [a for a in apps if a["status"] in PENDING and a["date"] == today()]
    if ready:
        n = len(ready)
        return {"label": "Ready", "why": f"{n} application{'s are' if n != 1 else ' is'} prepared for you to review and send.",
                "action": "Open the panel: `job panel`"}
    return {"label": "Up to date", "why": "Nothing is waiting for you; the next daily run will bring new jobs.",
            "action": f"Optional: run the daily cycle now with `/job-daily {slug}`"}


def summary(slug: str) -> dict[str, Any]:
    st = load_state(slug)
    pending = [g["id"] for g in load_all(slug) if g["status"] == "pending"]
    allg = load_all(slug)
    # superseded approvals don't count: the newest signed-or-pending one of each type is the one that matters
    latest = {g["type"]: g["id"] for g in allg if g["status"] in ("signed", "pending")}
    broken = [g["id"] for g in allg if g["status"] == "signed" and latest[g["type"]] == g["id"] and not seals_ok(slug, g)[0]]
    live_ok, live_why = valid_approval(slug, "go-live")
    apps = load(slug)
    first_pending = next((int(k) for k, v in sorted(st["stages"].items(), key=lambda x: int(x[0])) if v["status"] != "done"), None)
    if broken:
        nxt = f"Seal broken in {broken}: review what changed, then `job gate request {slug} ...` again."
    elif pending:
        nxt = f"A person must sign: `job review {slug} {pending[0]}` then `job sign {slug} {pending[0]}`."
    elif first_pending is not None and first_pending <= 5:
        nxt = f"Run onboarding stage {first_pending} ({STAGES[first_pending]}): `/job-onboard {first_pending} {slug}`."
    elif st["mode"] == "dry-run" and first_pending == 7:
        nxt = (f"Review the dry-run reports in candidates/{slug}/data/*/report.md; if they look right, "
               f"`job gate request {slug} --type go-live ...` and sign it, then `job state {slug} mode live`.")
    else:
        nxt = f"Daily cycle: `/job-daily {slug}` (or let the 9 am schedule run it)."
    if st["mode"] == "live" and not live_ok:
        nxt = f"⚠️ Mode is live but go-live is not valid ({live_why}): the daily run will behave as dry-run. " + nxt
    questions = [q["question"] for q in st["open_questions"] if q["status"] == "open"]
    state = work_state(slug, pending, broken, questions, first_pending, apps)
    return {"candidate": slug, "state": state, "mode": st["mode"], "go_live": live_ok, "limits": st["limits"],
            "stages": {k: v["status"] for k, v in st["stages"].items()},
            "open_questions": questions,
            "pending_signatures": pending, "broken_seals": broken,
            "today": {s: sum(1 for a in apps if a["date"] == today() and a["status"] == s)
                      for s in ("submitted", "dry-run", "manual-review")},
            "quota": quota(slug), "total_applications": len(apps), "next": nxt, "filter_suggestions": suggestion_line(slug),
            "followups": followup_line(slug)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("slug", nargs="?")
    ap.add_argument("--json", action="store_true"); ap.add_argument("--context", action="store_true")
    a = ap.parse_args()
    remember_root()                       # plugin updates move the code; the schedule's launcher follows this pointer
    if a.context and plugin_mode() and not workspace(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()):
        return
    slugs =[a.slug] if a.slug else list_candidates()
    data = [summary(s) for s in slugs]
    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=2)); return
    if a.context:
        if not data:
            start = "/job-harness:job-start" if plugin_mode() else "/job-onboard 0 <slug>"
            print(f"job-harness: no candidates yet. Start with `{start}`."); return
        print("job-harness status (source of truth: candidates/<slug>/state.json, progress.md, tracker.json):")
    for d in data:
        print(f"• {d['candidate']}: {d['state']['label']}. {d['state']['why']}")
        print(f"    Do this: {d['state']['action']}")
        print(f"    mode={d['mode']} go-live={'yes' if d['go_live'] else 'no'} · "
              f"stages done={sum(v == 'done' for v in d['stages'].values())}/{len(d['stages'])} · "
              f"today: {d['today']} · applications={d['total_applications']}")
        for q in d["open_questions"]:
            print(f"    ? {q}")
        print(f"    Next: {d['next']}")
        if d["filter_suggestions"]:
            print(f"    {d['filter_suggestions']}")
        if d["followups"]:
            print(f"    {d['followups']}")
    if a.context:
        areas = [x for d in data for x in STATE_AREAS[d["state"]["label"]]]
        for l in relevant(list(dict.fromkeys(areas))):
            print(f"Lesson: {l}")


if __name__ == "__main__":
    main()
