"""Ashby job boards: the public Job Posting API of one company (all its listed jobs, full text included).

  {"platform": "ashby", "board": "<token in jobs.ashbyhq.com/<token>>", "location": "Perth"}
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from sources import base

NAME, COUNTRY, NEEDS_LOGIN = "ashby", "*", False
APPLY = ("external", "ashby")                    # the public posting is the application page: no account usually
DESCRIPTION = "Ashby company job boards (public Job Posting API, one company per search)"
KEYS = "board, name, location, max_age_days"

API = "https://api.ashbyhq.com/posting-api/job-board"


def _feed(board: str) -> tuple[int, list[dict[str, Any]]]:
    code, data = base.get_json(f"{API}/{urllib.parse.quote(board)}?includeCompensation=true")
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return code, jobs if isinstance(jobs, list) else []


def _text(j: dict[str, Any]) -> str:
    return base.guarded(j.get("descriptionHtml") or j.get("descriptionPlain") or "")


def search(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    board = str(search.get("board", "")).strip()
    if not board:
        return [{"_error": "ashby: the search needs a `board`"}]
    code, jobs = _feed(board)
    if code != 200:
        return [{"_error": f"ashby {board}: HTTP {code}"}]
    limit, out = base.age_limit(search, max_age_days), []
    for j in jobs:
        if j.get("isListed") is False:
            continue
        places = [j.get("location", ""), *(s.get("location", "") for s in j.get("secondaryLocations") or [])]
        if not base.recent(j.get("publishedAt"), limit) or not base.place_ok(search, *places):
            continue
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        out.append(base.feed_item(
            "ashby", board, j["id"], title=j.get("title", ""), company=search.get("name") or board,
            location=j.get("location", "") + (", Remote" if j.get("isRemote") and "emote" not in j.get("location", "") else ""),
            listed=base.iso(j.get("publishedAt")), url=j.get("jobUrl", ""), salary=comp,
            work_type=j.get("employmentType", ""), classification=j.get("department", ""), **base.description_item(_text(j))))
    return out


def _find(job_id: str) -> tuple[int, dict[str, Any] | None]:
    board, jid = base.split_id(job_id)
    code, jobs = _feed(board)
    return code, next((j for j in jobs if j.get("id") == jid), None)


def detail(job_id: str) -> str:
    code, j = _find(job_id)
    return _text(j) if j else ""


def alive(job_id: str) -> tuple[bool | None, str | None]:
    """The API has no per-job endpoint: the job is open while the board still lists it."""
    code, j = _find(job_id)
    if code != 200:
        return (False, None) if code in (404, 410) else (None, None)
    return (j is not None and j.get("isListed") is not False), None
