"""WA public sector (search.jobs.wa.gov.au): server-rendered results + JSON-LD on each ad. Measured 2026-11-03: of 113
open WA government ads in digital, environment, GIS and data, only 44 could be found on SEEK."""
from __future__ import annotations

import html
import json
import random
import re
import time
import urllib.parse
from typing import Any

from sources import base

NAME, COUNTRY, NEEDS_LOGIN = "wagov", "AU", False
DESCRIPTION = "WA Government Jobs (every state agency; search.jobs.wa.gov.au)"
KEYS = "keywords, pages"
DETAIL_DELAY = (0.8, 1.8)

SITE = "https://search.jobs.wa.gov.au"
FIELD = re.compile(r'aria-label="([^"]+)" title="[^"]*"></i>\s*<span[^>]*>\s*(.*?)\s*</span>', re.S)


def search(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    """The listing has no date: recency comes from the ad page (page()) and repeats are dropped by jobs.db."""
    out: list[dict[str, Any]] = []
    for page in range(1, search.get("pages", 2) + 1):
        code, body = base.http_get(f"{SITE}/jobs/search?{urllib.parse.urlencode({'query': search['keywords'], 'page': page})}")
        if code != 200:
            return out + [{"_error": f"wagov {search['keywords']}: HTTP {code}"}] if not out else out
        cards = re.findall(r'<article class="col-12 job-search-results-card-col".*?</article>', body, re.S)
        for card in cards:
            link = re.search(r'id="link_job_title[^"]*" href="([^"]+)">(.*?)</a>', card, re.S)
            if not link:
                continue
            f = {k: html.unescape(" ".join(v.split())) for k, v in FIELD.findall(card)}
            jid = link.group(1).rstrip("/").rsplit("/", 1)[-1]
            place = f.get("Location Description", "")
            out.append({"platform": "wagov", "id": jid, "title": html.unescape(link.group(2)).strip(),
                        "company": f.get("Department", ""), "location": f"{place}, WA" if place else "Western Australia",
                        "listed": "", "url": link.group(1), "teaser": f.get("Branch", ""), "bullets": [],
                        "salary": f.get("Salary range", ""), "work_type": f.get("Employment type", ""),
                        "classification": f.get("Occupation", "")})
        if len(cards) < 20:
            break
        time.sleep(random.uniform(1.5, 3.0))
    return out


def department(body: str) -> str:
    """The agency named on the ad page ("Department" field; the JSON-LD only says "WA Government Jobs")."""
    m = (re.search(r'aria-label="Department"[^>]*></i>\s*<span[^>]*>\s*(.*?)\s*</span>', body, re.S)
         or re.search(r'"departments":\s*\["([^"]+)"', body))
    return html.unescape(" ".join(m.group(1).split())) if m else ""


def page(job_id: str) -> tuple[int, dict[str, Any], str]:
    """(HTTP status, the ad's JSON-LD JobPosting, closing date YYYY-MM-DD or ''). The JobPosting gets a `department` key."""
    code, body = base.http_get(f"{SITE}/jobs/{job_id}")
    m = re.search(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', body, re.S) if code == 200 else None
    try:
        ld = json.loads(m.group(1)) if m else {}
    except ValueError:
        ld = {}
    if ld and (dept := department(body)):
        ld["department"] = dept
    close = re.search(r"Closing at:\s*([A-Z][a-z]{2} \d{1,2} \d{4})", body)
    closes = time.strftime("%Y-%m-%d", time.strptime(close.group(1), "%b %d %Y")) if close else None
    return code, ld, closes or ""


def detail(job_id: str) -> str:
    """Full description of a WA Government ad (its JSON-LD JobPosting). Shortlist only."""
    code, ld, _ = page(job_id)
    return base.guarded(ld.get("description", "")) if code == 200 else ""


def alive(job_id: str) -> tuple[bool | None, str | None]:
    code, _, closes = page(job_id)
    if code in (404, 410):
        return False, None
    if code != 200:
        return None, None
    return not (closes and closes < time.strftime("%Y-%m-%d")), closes or None
