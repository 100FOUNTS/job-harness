"""SmartRecruiters: the public Posting API of one company. The list has no description; detail() reads the posting.

  {"platform": "smartrecruiters", "company": "<company identifier>", "location": "Perth", "country": "au"}

Note: api.smartrecruiters.com/robots.txt disallows generic crawlers (it names LinkedInBot only). The Posting API is the
documented public interface for job boards, and this source makes one list request per search, spaced; if you prefer
to follow robots.txt to the letter, do not use this source.
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from sources import base

NAME, COUNTRY, NEEDS_LOGIN = "smartrecruiters", "*", False
DESCRIPTION = "SmartRecruiters company postings (public Posting API, one company per search)"
KEYS = "company, name, location, country, pages, max_age_days"
DETAIL_DELAY = (0.8, 1.8)

API = "https://api.smartrecruiters.com/v1/companies"
PAGE = 100


def search(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    company = str(search.get("company", "")).strip()
    if not company:
        return [{"_error": "smartrecruiters: the search needs a `company`"}]
    limit, out = base.age_limit(search, max_age_days), []
    for page in range(search.get("pages", 3)):
        q = {"limit": PAGE, "offset": page * PAGE} | ({"country": search["country"]} if search.get("country") else {})
        code, data = base.get_json(f"{API}/{urllib.parse.quote(company)}/postings?{urllib.parse.urlencode(q)}")
        if code != 200 or not isinstance(data, dict):
            return out + [{"_error": f"smartrecruiters {company}: HTTP {code}"}] if not out else out
        for j in data.get("content", []):
            loc = j.get("location") or {}
            place = loc.get("fullLocation") or ", ".join(x for x in (loc.get("city"), loc.get("region")) if x)
            if not base.recent(j.get("releasedDate"), limit) or not base.place_ok(search, place, loc.get("country", "")):
                continue
            out.append(base.feed_item(
                "smartrecruiters", company, j["id"], title=j.get("name", ""),
                company=search.get("name") or (j.get("company") or {}).get("name") or company, location=place,
                listed=base.iso(j.get("releasedDate")),
                url=f"https://jobs.smartrecruiters.com/{urllib.parse.quote(company)}/{j['id']}",
                work_type=(j.get("typeOfEmployment") or {}).get("label", ""), classification=(j.get("function") or {}).get("label", "")))
        if len(data.get("content", [])) < PAGE or (page + 1) * PAGE >= data.get("totalFound", 0):
            break
    return out


def _posting(job_id: str) -> tuple[int, dict[str, Any] | None]:
    company, jid = base.split_id(job_id)
    code, j = base.get_json(f"{API}/{urllib.parse.quote(company)}/postings/{urllib.parse.quote(jid)}")
    return code, j if isinstance(j, dict) else None


def detail(job_id: str) -> str:
    _, j = _posting(job_id)
    secs = ((j or {}).get("jobAd") or {}).get("sections") or {}
    return base.guarded(" ".join((secs.get(k) or {}).get("text", "")
                                 for k in ("jobDescription", "qualifications", "additionalInformation")))


def alive(job_id: str) -> tuple[bool | None, str | None]:
    code, j = _posting(job_id)
    if code in (404, 410):
        return False, None
    return (j.get("active") is not False, None) if j else (None, None)
