"""Where every candidate is, and the exact next step.

  job status [slug] [--json]
  job status --context        (SessionStart hook: compact text injected when Claude opens)
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from common import cand_dir, list_candidates, read_json, today
from gates import load_all, seals_ok, valid_approval
from state import STAGES, load_state
from tracker import load, quota


def summary(slug: str) -> dict[str, Any]:
    st = load_state(slug)
    pending = [g["id"] for g in load_all(slug) if g["status"] == "pending"]
    allg = load_all(slug)
    latest = {g["type"]: g["id"] for g in allg if g["status"] == "signed"}       # superseded approvals don't count
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
    return {"candidate": slug, "mode": st["mode"], "go_live": live_ok, "limits": st["limits"],
            "stages": {k: v["status"] for k, v in st["stages"].items()},
            "open_questions": [q["question"] for q in st["open_questions"] if q["status"] == "open"],
            "pending_signatures": pending, "broken_seals": broken,
            "today": {s: sum(1 for a in apps if a["date"] == today() and a["status"] == s)
                      for s in ("submitted", "dry-run", "manual-review")},
            "quota": quota(slug), "total_applications": len(apps), "next": nxt}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("slug", nargs="?")
    ap.add_argument("--json", action="store_true"); ap.add_argument("--context", action="store_true")
    a = ap.parse_args()
    slugs = [a.slug] if a.slug else list_candidates()
    data = [summary(s) for s in slugs]
    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=2)); return
    if a.context:
        if not data:
            print("job-harness: no candidates yet. Start with `/job-onboard 0 <slug>`."); return
        print("job-harness status (source of truth: candidates/<slug>/state.json, progress.md, tracker.json):")
    for d in data:
        print(f"• {d['candidate']}: mode={d['mode']} go-live={'yes' if d['go_live'] else 'no'} · "
              f"stages done={sum(v == 'done' for v in d['stages'].values())}/{len(d['stages'])} · "
              f"today: {d['today']} · applications={d['total_applications']}")
        for q in d["open_questions"]:
            print(f"    ? {q}")
        print(f"    Next: {d['next']}")


if __name__ == "__main__":
    main()
