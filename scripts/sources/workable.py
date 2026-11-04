"""Workable accounts: the public widget feed of one company. The feed carries only part of the ad (no requirements), so
the teaser comes from it and detail() reads the per-job endpoint (description + requirements + benefits).

  {"platform": "workable", "account": "<token in apply.workable.com/<token>>", "location": "Australia"}
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from sources import base

NAME, COUNTRY, NEEDS_LOGIN = "workable", "*", False
DESCRIPTION = "Workable company jobs (public widget feed, one company per search)"
KEYS = "account, name, location, max_age_days"
DETAIL_DELAY = (0.8, 1.8)

API = "https://apply.workable.com/api/v1"


def _places(j: dict[str, Any]) -> list[str]:
    own = [", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)]
    return own + [", ".join(x for x in (l.get("city"), l.get("region"), l.get("country")) if x) for l in j.get("locations") or []]


def search(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    account = str(search.get("account", "")).strip()
    if not account:
        return [{"_error": "workable: the search needs an `account`"}]
    code, data = base.get_json(f"{API}/widget/accounts/{urllib.parse.quote(account)}?details=true")
    if code != 200 or not isinstance(data, dict):
        return [{"_error": f"workable {account}: HTTP {code}"}]
    limit, out = base.age_limit(search, max_age_days), []
    for j in data.get("jobs", []):
        places = _places(j)
        listed = j.get("published_on") or j.get("created_at") or ""
        if not base.recent(listed, limit) or not base.place_ok(search, *places):
            continue
        out.append(base.feed_item(
            "workable", account, j["shortcode"], title=j.get("title", ""), company=search.get("name") or data.get("name") or account,
            location=places[0], listed=base.iso(listed), url=j.get("url") or j.get("shortlink", ""),
            teaser=base.guarded(j.get("description") or "").replace(base.GUARD_MARK, "").strip()[:300],
            work_type=j.get("employment_type", ""), classification=j.get("department", "")))
    return out


def _job(job_id: str) -> tuple[int, dict[str, Any] | None]:
    account, code_ = base.split_id(job_id)
    code, j = base.get_json(f"{API}/accounts/{urllib.parse.quote(account)}/jobs/{urllib.parse.quote(code_)}")
    return code, j if isinstance(j, dict) else None


def detail(job_id: str) -> str:
    code, j = _job(job_id)
    return base.guarded(" ".join(j.get(k) or "" for k in ("description", "requirements", "benefits"))) if j else ""


def alive(job_id: str) -> tuple[bool | None, str | None]:
    code, j = _job(job_id)
    if code in (404, 410):
        return False, None
    return (j.get("state") in (None, "published"), None) if j else (None, None)
