"""Discover new jobs from the candidate's saved searches, without a browser and without the LLM.

SEEK: public search JSON (same data the site uses). LinkedIn: public guest search HTML.
A handful of requests per day, spaced out, like a person opening their alerts.

  job discover <slug> [--max-age-days 3] [--dry]
  → candidates/<slug>/data/<date>/jobs.json  (new jobs only: already-seen keys are skipped)
"""
from __future__ import annotations

import argparse
import html
import json
import random
import re
import time
import urllib.parse
from typing import Any

import urllib.request

from common import UA, cand_dir, http_get, read_json, run_dir, save_json
from tracker import seen_keys

SEEK_API = "https://www.seek.com.au/api/jobsearch/v5/search"
LI_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"


def seek(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    q = {"siteKey": "AU-Main", "sourcesystem": "houston", "where": search.get("where", "Western Australia WA"),
         "keywords": search["keywords"], "page": 1, "pageSize": search.get("page_size", 30),
         "sortmode": "ListedDate", "daterange": max_age_days}
    code, body = http_get(f"{SEEK_API}?{urllib.parse.urlencode(q)}")
    if code != 200:
        return [{"_error": f"seek {search['keywords']}: HTTP {code}"}]
    out = []
    for j in json.loads(body).get("data", []):
        out.append({
            "platform": "seek", "id": str(j.get("id")), "title": j.get("title", ""),
            "company": (j.get("advertiser") or {}).get("description", ""),
            "location": ", ".join(l.get("label", "") for l in j.get("locations", [])[:1]),
            "listed": j.get("listingDate", ""), "url": f"https://www.seek.com.au/job/{j.get('id')}",
            "teaser": j.get("teaser", ""), "bullets": j.get("bulletPoints", []),
            "salary": j.get("salaryLabel", ""), "work_type": ", ".join(j.get("workTypes", []) or []),
            "classification": ", ".join(c.get("classification", {}).get("description", "")
                                        for c in j.get("classifications", [])[:1]),
        })
    return out


def linkedin(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    q = {"keywords": search["keywords"], "location": search.get("location", "Western Australia, Australia"),
         "f_TPR": f"r{max_age_days * 86400}", "start": 0}
    code, body = http_get(f"{LI_SEARCH}?{urllib.parse.urlencode(q)}")
    if code != 200:
        return [{"_error": f"linkedin {search['keywords']}: HTTP {code}"}]
    out = []
    for card in body.split('<li')[1:]:
        jid = re.search(r"urn:li:jobPosting:(\d+)", card)
        if not jid:
            continue
        def grab(cls: str) -> str:
            m = re.search(rf'class="[^"]*{cls}[^"]*"[^>]*>(.*?)</', card, re.S)
            return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split())) if m else ""
        date = re.search(r'datetime="([^"]+)"', card)
        out.append({"platform": "linkedin", "id": jid.group(1), "title": grab("base-search-card__title"),
                    "company": grab("base-search-card__subtitle"), "location": grab("job-search-card__location"),
                    "listed": date.group(1) if date else "",
                    "url": f"https://www.linkedin.com/jobs/view/{jid.group(1)}/",
                    "easy_apply": "Easy Apply" in card, "teaser": "", "bullets": []})
    return out


def linkedin_detail(job_id: str) -> str:
    """Full description of a LinkedIn job (public guest endpoint). Used for the shortlist only."""
    code, body = http_get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}")
    m = re.search(r"show-more-less-html__markup[^>]*>(.*?)</div>", body, re.S) if code == 200 else None
    return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split())) if m else ""


SEEK_GQL = "https://www.seek.com.au/graphql"


def seek_detail(job_id: str) -> str:
    """Full description of a SEEK job (the job page itself returns 403; the site's GraphQL does not). Shortlist only."""
    q = {"operationName": "jobDetails", "variables": {"jobId": job_id},
         "query": "query jobDetails($jobId: ID!) { jobDetails(id: $jobId) { job { content(platform: WEB) } } }"}
    req = urllib.request.Request(SEEK_GQL, data=json.dumps(q).encode(), headers={
        "User-Agent": UA, "Content-Type": "application/json", "seek-request-brand": "seek", "seek-request-country": "AU"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = json.loads(r.read().decode("utf-8", errors="ignore"))
        content = ((body.get("data") or {}).get("jobDetails") or {}).get("job", {}).get("content") or ""
    except Exception:  # never raised into the daily run
        return ""
    return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", content).split()))


def discover(slug: str, max_age_days: int, dry: bool = False) -> dict[str, Any]:
    targets = read_json(cand_dir(slug) / "targets.json")
    seen = seen_keys(slug)
    jobs: dict[str, dict[str, Any]] = {}
    errors = []
    for track in targets["tracks"]:
        for s in track["searches"]:
            fetch = seek if s["platform"] == "seek" else linkedin
            for j in fetch(s, max_age_days):
                if "_error" in j:
                    errors.append(j["_error"]); continue
                key = f"{j['platform']}:{j['id']}"
                if key in seen:
                    continue
                if key in jobs:
                    if track["id"] not in jobs[key]["tracks"]:
                        jobs[key]["tracks"].append(track["id"])
                    continue
                jobs[key] = j | {"key": key, "tracks": [track["id"]], "search": s["keywords"]}
            time.sleep(random.uniform(2.0, 4.5))          # human-like spacing between requests
    result = {"date": run_dir(slug).name, "new_jobs": list(jobs.values()), "errors": errors}
    if not dry:
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
    print(json.dumps({"new_jobs": len(r["new_jobs"]), "by_platform": by, "errors": r["errors"]}, indent=2))


if __name__ == "__main__":
    main()
