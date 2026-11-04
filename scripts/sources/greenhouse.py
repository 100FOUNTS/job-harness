"""Greenhouse job boards: the public Job Board API of one company (all its open jobs, full text included).

  {"platform": "greenhouse", "board": "<token in boards.greenhouse.io/<token>>", "location": "Perth"}
"""
from __future__ import annotations

import html
import urllib.parse
from typing import Any

from sources import base

NAME, COUNTRY, NEEDS_LOGIN = "greenhouse", "*", False
DESCRIPTION = "Greenhouse company job boards (public Job Board API, one company per search)"
KEYS = "board, name, location, max_age_days"

API = "https://boards-api.greenhouse.io/v1/boards"


def _text(job: dict[str, Any]) -> str:
    return base.guarded(html.unescape(job.get("content") or ""))      # the API sends the HTML entity-escaped


def search(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    board = str(search.get("board", "")).strip()
    if not board:
        return [{"_error": "greenhouse: the search needs a `board`"}]
    code, data = base.get_json(f"{API}/{urllib.parse.quote(board)}/jobs?content=true")
    if code != 200 or not isinstance(data, dict):
        return [{"_error": f"greenhouse {board}: HTTP {code}"}]
    limit, out = base.age_limit(search, max_age_days), []
    for j in data.get("jobs", []):
        place = (j.get("location") or {}).get("name", "")
        listed = j.get("first_published") or j.get("updated_at") or ""
        if not base.recent(listed, limit) or not base.place_ok(search, place, *(o.get("location") or o.get("name", "") for o in j.get("offices", []))):
            continue
        out.append(base.feed_item(
            "greenhouse", board, j["id"], title=j.get("title", ""), company=search.get("name") or j.get("company_name") or board,
            location=place, listed=base.iso(listed), url=j.get("absolute_url", ""),
            classification=", ".join(d.get("name", "") for d in j.get("departments", [])[:1]),
            **base.description_item(_text(j))))
    return out


def detail(job_id: str) -> str:
    board, jid = base.split_id(job_id)
    code, j = base.get_json(f"{API}/{urllib.parse.quote(board)}/jobs/{urllib.parse.quote(jid)}")
    return _text(j) if code == 200 and isinstance(j, dict) else ""


def alive(job_id: str) -> tuple[bool | None, str | None]:
    """A closed job's endpoint answers 404."""
    board, jid = base.split_id(job_id)
    code, j = base.get_json(f"{API}/{urllib.parse.quote(board)}/jobs/{urllib.parse.quote(jid)}")
    if code in (404, 410):
        return False, None
    if code != 200 or not isinstance(j, dict):
        return None, None
    return True, (j.get("application_deadline") or "")[:10] or None
