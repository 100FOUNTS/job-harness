"""Daily summary: what was applied to (company, role, link, CV, fit, summary) and what needs a person.

  job report <slug> [--date YYYY-MM-DD] [--notify]
  → data/<date>/report.md  (+ macOS notification with --notify)
"""
from __future__ import annotations

import argparse
import subprocess
from typing import Any

from common import cand_dir, read_json, run_dir, today
from state import load_state
from tracker import load, quota

LABEL = {"submitted": "✅ Submitted", "dry-run": "🧪 Filled, not sent (dry-run)", "manual-review": "✋ Needs a person",
         "prepared": "📝 Ready for the person to apply (open link → Apply → upload CV + letter)", "skipped": "⏭️ Skipped", "failed": "❌ Failed", "shortlisted": "🔎 Shortlisted"}


def build(slug: str, day: str) -> str:
    st = load_state(slug)
    apps = [a for a in load(slug) if a["date"] == day or a.get("submitted") == day]
    sl = read_json(run_dir(slug, day) / "shortlist.json", {"shortlist": [], "rejected": []})
    jobs = read_json(run_dir(slug, day) / "jobs.json", {"new_jobs": [], "errors": []})
    lines = [f"# Daily report: {slug}, {day}", "",
             f"**Mode:** {st['mode']}  ·  **New jobs found:** {len(jobs['new_jobs'])}  ·  **Shortlisted:** {len(sl['shortlist'])}"
             f"  ·  **Pre-filter rejected:** {len(sl['rejected'])}", ""]
    order = ["submitted", "dry-run", "manual-review", "prepared", "failed", "skipped", "shortlisted"]
    for s in order:
        group = [a for a in apps if a["status"] == s]
        if not group:
            continue
        lines += [f"## {LABEL[s]} ({len(group)})", "", "| Company | Role | Platform | Fit | Summary | Link |", "|---|---|---|---|---|---|"]
        for a in group:
            summ = (a.get("summary") or a.get("reason") or "").replace("|", "/")
            lines.append(f"| {a.get('company') or ''} | {a['title']} | {a['platform']} | {a.get('fit') or ''} | {summ} | [open]({a['url']}) |")
        lines.append("")
    q = quota(slug)
    lines += [f"**Remaining today:** {q['day_left']} · **this week:** {q['week_left']}", ""]
    if jobs.get("errors"):
        lines += ["**Discovery errors:** " + "; ".join(jobs["errors"]), ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("slug"); ap.add_argument("--date")
    ap.add_argument("--notify", action="store_true")
    a = ap.parse_args()
    day = a.date or today()
    md = build(a.slug, day)
    p = run_dir(a.slug, day) / "report.md"
    p.write_text(md)
    print(p)
    if a.notify:
        apps = [x for x in load(a.slug) if x["date"] == day]
        msg = f"{sum(x['status'] == 'submitted' for x in apps)} sent · {sum(x['status'] == 'dry-run' for x in apps)} dry-run · " \
              f"{sum(x['status'] == 'manual-review' for x in apps)} need you"
        subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Job harness: {a.slug}"'])


if __name__ == "__main__":
    main()
