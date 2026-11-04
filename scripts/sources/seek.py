"""SEEK Australia: the public search JSON the site itself uses; descriptions and expiry through the site's GraphQL."""
from __future__ import annotations

import json
import urllib.parse
from typing import Any

from sources import base

NAME, COUNTRY, NEEDS_LOGIN = "seek", "AU", False
DESCRIPTION = "SEEK Australia (public search JSON, GraphQL for the full ad)"
KEYS = "keywords, where, page_size"
DETAIL_DELAY = (0.8, 1.8)

API = "https://www.seek.com.au/api/jobsearch/v5/search"
GQL = "https://au.seek.com/graphql"            # www.seek.com.au/graphql now answers 308, which urllib does not follow on a POST
HEADERS = {"seek-request-brand": "seek", "seek-request-country": "AU"}
_LINK_OUT: dict[str, bool] = {}                  # job id → "applied for on the employer's site", noted while reading the ad


def search(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    q = {"siteKey": "AU-Main", "sourcesystem": "houston", "where": search.get("where", "Western Australia WA"),
         "keywords": search["keywords"], "page": 1, "pageSize": search.get("page_size", 30),
         "sortmode": "ListedDate", "daterange": max_age_days}
    code, body = base.http_get(f"{API}?{urllib.parse.urlencode(q)}")
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


def detail(job_id: str) -> str:
    """Full description of a SEEK job (the job page itself returns 403; the site's GraphQL does not). Shortlist only."""
    q = {"operationName": "jobDetails", "variables": {"jobId": job_id},
         "query": "query jobDetails($jobId: ID!) { jobDetails(id: $jobId) { job { content(platform: WEB) isLinkOut } } }"}
    body = base.post_json(GQL, q, HEADERS) or {}
    job = ((body.get("data") or {}).get("jobDetails") or {}).get("job") or {}
    if isinstance(job.get("isLinkOut"), bool):
        _LINK_OUT[job_id] = job["isLinkOut"]
    return base.guarded(job.get("content") or "")


def route(job_id: str) -> tuple[str, str] | None:
    """How the ad is applied for: SEEK's own form ("quick") or the employer's site ("external"). Free when detail()
    just read the ad; otherwise one GraphQL request. None = could not tell."""
    if job_id not in _LINK_OUT:
        q = {"operationName": "jobDetails", "variables": {"jobId": job_id},
             "query": "query jobDetails($jobId: ID!) { jobDetails(id: $jobId) { job { isLinkOut } } }"}
        job = ((base.post_json(GQL, q, HEADERS) or {}).get("data") or {}).get("jobDetails") or {}
        flag = (job.get("job") or {}).get("isLinkOut")
        if not isinstance(flag, bool):
            return None
        _LINK_OUT[job_id] = flag
    return ("external", "") if _LINK_OUT[job_id] else ("quick", "")


def alive(job_id: str) -> tuple[bool | None, str | None]:
    """GraphQL isExpired/status/expiresAt (no job → closed). One request."""
    q = {"operationName": "jobDetails", "variables": {"jobId": job_id}, "query":
         "query jobDetails($jobId: ID!) { jobDetails(id: $jobId) { job { isExpired status expiresAt { dateTimeUtc } } } }"}
    data = (base.post_json(GQL, q, HEADERS) or {}).get("data") or {}
    if "jobDetails" not in data:
        return None, None
    job = (data["jobDetails"] or {}).get("job")
    if not job:
        return False, None
    closes = ((job.get("expiresAt") or {}).get("dateTimeUtc") or "")[:10] or None
    return not (job.get("isExpired") or (job.get("status") or "Active") != "Active"), closes
