"""Application tracker: one record per job, so nothing is applied to twice and limits hold.

candidates/<slug>/tracker.json is bookkeeping: only this script writes it (the hook blocks hand edits).

Statuses: shortlisted → prepared → dry-run (filled, not sent) | submitted | manual-review | skipped | failed

  job track <slug> add --key seek:123 --title ... --company ... --url ... --platform seek --track environmental
  job track <slug> set <key> <status> [--note "..."] [--fit 82] [--cv path] [--letter path] [--summary "..."]
  job track <slug> list [--date YYYY-MM-DD] [--status submitted]
  job track <slug> quota [--platform seek]      → how many more can be submitted today/this week
  job track <slug> csv                          → tracker.csv for a spreadsheet
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from typing import Any

from common import cand_dir, now_iso, read_json, save_json, today

STATUSES = ("shortlisted", "prepared", "dry-run", "submitted", "manual-review", "skipped", "failed")
COUNTS_TOWARDS_LIMIT = {"submitted"}


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
            if status == "submitted":
                a["submitted"] = today()
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
    else:
        out = cand_dir(a.slug) / "tracker.csv"
        cols = ["date", "status", "platform", "company", "title", "track", "fit", "url", "submitted", "summary", "reason"]
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(load(a.slug))
        print(out)


if __name__ == "__main__":
    main()
