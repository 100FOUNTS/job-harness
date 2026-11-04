"""Lever postings: the public Postings API of one company (all its open jobs, full text included).

  {"platform": "lever", "company": "<token in jobs.lever.co/<token>>", "location": "Perth"}
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from sources import base

NAME, COUNTRY, NEEDS_LOGIN = "lever", "*", False
DESCRIPTION = "Lever company postings (public Postings API, one company per search)"
KEYS = "company, name, location, max_age_days"

API = "https://api.lever.co/v0/postings"


def _text(p: dict[str, Any]) -> str:
    """Intro + the list sections (responsibilities, requirements...) + closing text, as the page shows them."""
    parts = [p.get("description") or ""]
    parts += [f"<h3>{l.get('text', '')}</h3>{l.get('content', '')}" for l in p.get("lists", [])]
    parts.append(p.get("additional") or "")
    return base.guarded(" ".join(parts))


def search(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    company = str(search.get("company", "")).strip()
    if not company:
        return [{"_error": "lever: the search needs a `company`"}]
    code, data = base.get_json(f"{API}/{urllib.parse.quote(company)}?mode=json")
    if code != 200 or not isinstance(data, list):
        return [{"_error": f"lever {company}: HTTP {code}"}]
    limit, out = base.age_limit(search, max_age_days), []
    for p in data:
        cat = p.get("categories") or {}
        places = [cat.get("location", ""), *(cat.get("allLocations") or [])]
        if not base.recent(p.get("createdAt"), limit) or not base.place_ok(search, *places):
            continue
        out.append(base.feed_item(
            "lever", company, p["id"], title=p.get("text", ""), company=search.get("name") or company,
            location=cat.get("location", ""), listed=base.iso(p.get("createdAt")), url=p.get("hostedUrl", ""),
            work_type=cat.get("commitment", ""), classification=cat.get("team", ""), **base.description_item(_text(p))))
    return out


def detail(job_id: str) -> str:
    company, jid = base.split_id(job_id)
    code, p = base.get_json(f"{API}/{urllib.parse.quote(company)}/{urllib.parse.quote(jid)}")
    return _text(p) if code == 200 and isinstance(p, dict) else ""


def alive(job_id: str) -> tuple[bool | None, str | None]:
    """A closed posting answers 404."""
    company, jid = base.split_id(job_id)
    code, p = base.get_json(f"{API}/{urllib.parse.quote(company)}/{urllib.parse.quote(jid)}")
    if code in (404, 410):
        return False, None
    return (True, None) if code == 200 and isinstance(p, dict) else (None, None)
