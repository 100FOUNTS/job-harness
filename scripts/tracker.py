"""Application tracker: one record per job, so nothing is applied to twice and limits hold.

candidates/<slug>/tracker.json is bookkeeping: only this script writes it (the hook blocks hand edits).

Statuses: shortlisted → prepared → dry-run (filled, not sent) | submitted | manual-review | skipped | failed | closed
  applied   = the person sent it by hand (does not count towards the automation limits; submitted does)
  closed    = the ad closed before anyone applied (job track <slug> sweep)
  after applying: interview → offer → hired, or rejected | no-response | withdrawn (job track <slug> set <key> <status>)

  job track <slug> add --key seek:123 --title ... --company ... --url ... --platform seek --track environmental
  job track <slug> set <key> <status> [--note "..."] [--fit 82] [--cv path] [--letter path] [--summary "..."]
  job track <slug> list [--date YYYY-MM-DD] [--status submitted]
  job track <slug> quota [--platform seek]      → how many more can be submitted today/this week
  job track <slug> csv                          → tracker.csv for a spreadsheet
  job track <slug> followups [--days 10]        sent and quiet for N days: who to chase (and what to say)
  job track <slug> calibrate                    does the fit score predict interviews? (needs outcomes)
  job track <slug> sweep [--dry]                not yet applied and the ad has closed → closed (one request per ad)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from typing import Any

from common import cand_dir, now_iso, read_json, save_json, today

STATUSES = ("shortlisted", "prepared", "dry-run", "submitted", "applied", "manual-review", "skipped", "failed", "closed",
            "interview", "offer", "hired", "rejected", "no-response", "withdrawn")
COUNTS_TOWARDS_LIMIT = {"submitted"}
SENT = {"submitted", "applied"}                              # the application left: waiting for the employer
OUTCOMES = {"interview", "offer", "hired", "rejected", "no-response", "withdrawn"}
PENDING = {"shortlisted", "prepared", "dry-run", "manual-review"}   # nobody has applied yet


def path(slug: str):
    return cand_dir(slug) / "tracker.json"


def load(slug: str) -> list[dict[str, Any]]:
    return read_json(path(slug), {"applications": []})["applications"]


def save(slug: str, apps: list[dict[str, Any]]) -> None:
    save_json(path(slug), {"applications": apps})


def seen_keys(slug: str) -> set[str]:
    return {a["key"] for a in load(slug)}


def add(slug: str, rec: dict[str, Any]) -> dict[str, Any]:
    apps = load(slug)
    if any(a["key"] == rec["key"] for a in apps):
        raise SystemExit(f"{rec['key']} already tracked")
    rec = rec | {"status": "shortlisted", "date": today(), "history": [{"date": now_iso(), "status": "shortlisted"}]}
    apps.append(rec)
    save(slug, apps)
    return rec


def set_status(slug: str, key: str, status: str, **fields: Any) -> dict[str, Any]:
    if status not in STATUSES:
        raise SystemExit(f"status must be one of {STATUSES}")
    apps = load(slug)
    for a in apps:
        if a["key"] == key:
            if status == "submitted":
                q = quota(slug, a.get("platform"))
                if q["platform_left"] <= 0 or q["day_left"] <= 0 or q["week_left"] <= 0:
                    raise SystemExit(f"Limit reached, not marking as submitted: {q}")
            a["status"] = status
            a.update({k: v for k, v in fields.items() if v not in (None, "")})
            a["history"].append({"date": now_iso(), "status": status, "note": fields.get("note") or ""})
            if status in SENT:
                a["submitted"] = a.get("submitted") or today()
            save(slug, apps)
            return a
    raise SystemExit(f"{key} not tracked")


def set_note(slug: str, key: str, text: str) -> dict[str, Any]:
    """The person's own notes on one application (the panel's Notes box). Not a status change: no history entry."""
    apps = load(slug)
    for a in apps:
        if a["key"] == key:
            a["notes"] = text.strip()[:4000]
            save(slug, apps)
            return a
    raise SystemExit(f"{key} not tracked")


def quota(slug: str, platform: str | None = None) -> dict[str, Any]:
    from state import load_state
    lim = load_state(slug)["limits"]
    apps = [a for a in load(slug) if a["status"] in COUNTS_TOWARDS_LIMIT]
    t = today()
    week_start = (date.today() - timedelta(days=6)).isoformat()
    day = [a for a in apps if a.get("submitted") == t]
    week = [a for a in apps if a.get("submitted", "") >= week_start]
    plat = [a for a in day if platform and a.get("platform") == platform]
    return {"day_left": lim["per_day"] - len(day), "week_left": lim["per_week"] - len(week),
            "platform_left": lim["per_platform"] - len(plat) if platform else lim["per_platform"]}


def sent_date(a: dict[str, Any]) -> str:
    return a.get("submitted") or next((h["date"][:10] for h in a["history"] if h["status"] in SENT), "")


def followups(slug: str, days: int = 10) -> list[dict[str, Any]]:
    """Sent, no answer for `days`: chase once (a short message to the recruiter or the hiring contact on LinkedIn,
    or a reply to the confirmation email); after 30 quiet days mark it no-response. Drafts only, never sent."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    stale = (date.today() - timedelta(days=30)).isoformat()
    out = []
    for a in load(slug):
        sd = sent_date(a)
        if a["status"] in SENT and sd and sd <= cutoff:
            chased = any(h["status"] in SENT and "follow-up" in (h.get("note") or "") for h in a["history"])
            out.append({"key": a["key"], "company": a.get("company"), "title": a["title"], "sent": sd,
                        "action": "mark no-response" if sd <= stale else ("waiting (already chased)" if chased else "follow up"),
                        "draft": f"Hello, I applied for the {a['title']} role on {sd} and remain very interested. "
                                 f"Is there an update on the timeline? Happy to provide anything else you need."})
    return out


def calibrate(slug: str) -> dict[str, Any]:
    """Interview rate by fit band, track and platform, over applications with a known outcome. Advisory only:
    under ~10 outcomes the numbers mean little, and nothing here changes targets.json by itself."""
    done = [a for a in load(slug) if a["status"] in OUTCOMES or a["status"] in SENT]
    def row(group):
        got = [a for a in group if any(h["status"] in ("interview", "offer", "hired") for h in a["history"])]
        known = [a for a in group if a["status"] in OUTCOMES]
        return {"sent": len(group), "with_outcome": len(known), "interviews": len(got),
                "interview_rate": round(len(got) / len(group), 2) if group else None}
    def by(fn):
        groups: dict[str, list] = {}
        for a in done:
            groups.setdefault(fn(a), []).append(a)
        return {k: row(v) for k, v in sorted(groups.items())}
    band = lambda a: "unknown" if a.get("fit") is None else f"{min(a['fit'] // 20 * 20, 80)}-{min(a['fit'] // 20 * 20, 80) + 19 if a['fit'] < 80 else 100}"
    total = row(done)
    return {"total": total, "by_fit": by(band), "by_track": by(lambda a: a.get("track") or "?"),
            "by_platform": by(lambda a: a.get("platform") or "?"),
            "note": "fewer than 10 outcomes: too early to change the ranking" if total["with_outcome"] < 10 else
                    "compare the interview rate across fit bands: if high-fit does not beat low-fit, the ranking needs work"}


def sweep(slug: str, dry: bool = False) -> list[dict[str, Any]]:
    """Ads nobody has applied to yet that have since closed → status closed. Unknown answers leave the ad alone."""
    import random, time
    from discover import alive
    since = (date.today() - timedelta(days=30)).isoformat()
    out = []
    for a in load(slug):
        if a["status"] not in PENDING or a["date"] < since:      # older pending ads are left as they are
            continue
        time.sleep(random.uniform(1.0, 2.5))
        state, _ = alive(a["key"])
        if state is False:
            out.append({"key": a["key"], "title": a["title"], "company": a.get("company"), "was": a["status"]})
            if not dry:
                set_status(slug, a["key"], "closed", note="ad closed (sweep)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    for k in ("key", "title", "company", "url", "platform", "track"):
        p.add_argument(f"--{k}", required=k in ("key", "title", "url", "platform"))
    p.add_argument("--location", default=""); p.add_argument("--fit", type=int); p.add_argument("--summary", default="")
    p = sub.add_parser("set"); p.add_argument("key"); p.add_argument("status", choices=STATUSES)
    for k in ("note", "cv", "letter", "summary", "reason"):
        p.add_argument(f"--{k}", default="")
    p.add_argument("--fit", type=int)
    p = sub.add_parser("list"); p.add_argument("--date"); p.add_argument("--status")
    p = sub.add_parser("quota"); p.add_argument("--platform")
    sub.add_parser("csv")
    p = sub.add_parser("followups"); p.add_argument("--days", type=int, default=10)
    sub.add_parser("calibrate")
    p = sub.add_parser("sweep"); p.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    if a.cmd == "add":
        rec = {k: getattr(a, k) for k in ("key", "title", "company", "url", "platform", "track", "location", "fit", "summary")}
        print(json.dumps(add(a.slug, rec), ensure_ascii=False))
    elif a.cmd == "set":
        r = set_status(a.slug, a.key, a.status, note=a.note, cv=a.cv, letter=a.letter, summary=a.summary,
                       reason=a.reason, fit=a.fit)
        print(f"{r['key']} → {r['status']}")
    elif a.cmd == "list":
        for x in load(a.slug):
            if (a.date and x["date"] != a.date) or (a.status and x["status"] != a.status):
                continue
            print(f"{x['date']}  {x['status']:13} {x['platform']:8} {x.get('company') or '':30.30} {x['title']:45.45} {x['url']}")
    elif a.cmd == "quota":
        print(json.dumps(quota(a.slug, a.platform)))
    elif a.cmd == "followups":
        print(json.dumps(followups(a.slug, a.days), ensure_ascii=False, indent=2))
    elif a.cmd == "calibrate":
        print(json.dumps(calibrate(a.slug), ensure_ascii=False, indent=2))
    elif a.cmd == "sweep":
        print(json.dumps(sweep(a.slug, a.dry), ensure_ascii=False, indent=2))
    else:
        out = cand_dir(a.slug) / "tracker.csv"
        cols = ["date", "status", "platform", "company", "title", "track", "fit", "url", "submitted", "summary", "reason"]
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(load(a.slug))
        print(out)


if __name__ == "__main__":
    main()
