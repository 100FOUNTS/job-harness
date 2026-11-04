"""LinkedIn: the public guest search (HTML cards) and guest job pages. No login; rate limits (429) are retried by discover."""
from __future__ import annotations

import html
import re
import urllib.parse
from typing import Any

from sources import base

NAME, COUNTRY, NEEDS_LOGIN = "linkedin", "*", False
DESCRIPTION = "LinkedIn public guest search (no login; any country)"
KEYS = "keywords, location"
DETAIL_DELAY = (1.5, 3.5)

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
POSTING = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"


def search(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    q = {"keywords": search["keywords"], "location": search.get("location", "Western Australia, Australia"),
         "f_TPR": f"r{max_age_days * 86400}", "start": 0}
    code, body = base.http_get(f"{SEARCH}?{urllib.parse.urlencode(q)}")
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


def detail(job_id: str) -> str:
    """Full description of a LinkedIn job (public guest endpoint). Used for the shortlist only."""
    code, body = base.http_get(POSTING + job_id)
    m = re.search(r"show-more-less-html__markup[^>]*>(.*)</div>\s*<button", body, re.S) if code == 200 else None
    m = m or (re.search(r"show-more-less-html__markup[^>]*>(.*?)</div>", body, re.S) if code == 200 else None)
    return base.guarded(m.group(1)) if m else ""


def alive(job_id: str) -> tuple[bool | None, str | None]:
    """Guest page: 404/410 or the `closed-job` banner ("No longer accepting applications", seen 2026-11-03) → closed."""
    code, body = base.http_get(POSTING + job_id)
    if code in (404, 410):
        return False, None
    if code != 200:
        return None, None
    return 'class="closed-job' not in body, None
