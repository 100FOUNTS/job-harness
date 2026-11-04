"""Discover new jobs from the candidate's saved searches, without a browser and without the LLM.

Each search names its `platform`; the portal code lives in scripts/sources/ (one small module per portal, see
docs/ADDING-A-SOURCE.md): seek, linkedin, wagov, adzuna and the company feeds greenhouse, lever, workable,
smartrecruiters, ashby. A handful of requests per day, spaced out, like a person opening their alerts.

  job discover <slug> [--max-age-days 3] [--dry]
  → candidates/<slug>/data/<date>/jobs.json  (new jobs only: tracked ads and ads already rejected under the same
    targets are skipped; every ad found is still recorded as a sighting in jobs.db)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from typing import Any

import sources
from common import cand_dir, keep_previous, read_json, run_dir, save_json
from jobdb import record_seen, settled
from sources.base import GUARD_MARK, guarded, label  # noqa: F401  (prepare imports GUARD_MARK from here)
from tracker import seen_keys


def fetch(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    """Run one saved search through its source (scripts/sources/<platform>.py)."""
    src = sources.get(search.get("platform", ""))
    if src is None:
        return [{"_error": f"unknown platform '{search.get('platform')}' (available: {', '.join(sources.names())})"}]
    return src.search(search, max_age_days)


def detail(platform: str, job_id: str) -> str:
    """Full text of an ad from its source ('' when the source has no detail or the request failed)."""
    return sources.get(platform).detail(job_id) if sources.has(platform, "detail") else ""


def seek_detail(job_id: str) -> str:
    return detail("seek", job_id)


def linkedin_detail(job_id: str) -> str:
    return detail("linkedin", job_id)


def wagov_detail(job_id: str) -> str:
    return detail("wagov", job_id)


def alive(key: str) -> tuple[bool | None, str | None]:
    """Is the ad still open? (True/False, closing date YYYY-MM-DD when the platform says it); None = could not tell
    (or the source cannot say). One or two requests; never raised into the daily run."""
    platform, jid = key.split(":", 1)
    return sources.get(platform).alive(jid) if sources.has(platform, "alive") else (None, None)


# A search that failed for a passing reason (429 rate limit, 5xx, network) is retried after the others, up to
# len(RETRY_WAITS) more rounds; a 4xx other than 429 is a broken search and is not retried. Real failure 2026-11-02:
# LinkedIn answered 429 to 4 of one candidate's searches and the run finished without them.
RETRY_WAITS = [float(x) for x in os.environ.get("JOB_DISCOVER_RETRY_WAITS", "90,300").split(",") if x]
TRANSIENT = re.compile(r"HTTP (0|429|5\d\d)$")


def discover(slug: str, max_age_days: int, dry: bool = False) -> dict[str, Any]:
    targets = read_json(cand_dir(slug) / "targets.json")
    jobs: dict[str, dict[str, Any]] = {}
    pending = [(track["id"], s) for track in targets["tracks"] for s in track["searches"]]
    errors, retried = [], []
    for rnd in range(len(RETRY_WAITS) + 1):
        if rnd:
            time.sleep(RETRY_WAITS[rnd - 1] * random.uniform(1.0, 1.3))
            retried += [label(s) for _, s in pending]
        failed = []
        for track_id, s in pending:
            for j in fetch(s, max_age_days):
                if "_error" in j:
                    if not TRANSIENT.search(j["_error"]):
                        errors.append(j["_error"])
                    elif rnd < len(RETRY_WAITS):
                        failed.append((track_id, s))
                    else:
                        errors.append(f"{j['_error']} (after {rnd} retries)")
                    continue
                key = f"{j['platform']}:{j['id']}"
                if key in jobs:
                    if track_id not in jobs[key]["tracks"]:
                        jobs[key]["tracks"].append(track_id)
                    continue
                jobs[key] = j | {"key": key, "tracks": [track_id], "search": label(s)}
            time.sleep(random.uniform(2.0, 4.5))          # human-like spacing between requests
        pending = failed
        if not pending:
            break
    skip = seen_keys(slug) | settled(slug, targets)
    result = {"date": run_dir(slug).name, "new_jobs": [j for k, j in jobs.items() if k not in skip],
              "already_known": len([k for k in jobs if k in skip]), "errors": errors, "retried": retried}
    if not dry:
        record_seen(slug, jobs.values(), result["date"])
        keep_previous(run_dir(slug) / "jobs.json")
        save_json(run_dir(slug) / "jobs.json", result)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("--max-age-days", type=int)
    ap.add_argument("--dry", action="store_true", help="do not write jobs.json")
    a = ap.parse_args()
    age = a.max_age_days or read_json(cand_dir(a.slug) / "targets.json").get("max_age_days", 3)
    r = discover(a.slug, age, a.dry)
    by = {}
    for j in r["new_jobs"]:
        by[j["platform"]] = by.get(j["platform"], 0) + 1
    print(json.dumps({"new_jobs": len(r["new_jobs"]), "already_known": r["already_known"], "by_platform": by,
                      "retried": r["retried"], "errors": r["errors"]}, indent=2))


if __name__ == "__main__":
    main()
