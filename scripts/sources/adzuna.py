"""Adzuna: the free job-search API (one aggregator for many job boards; au, nz, gb, us, ca, ...).

Needs a free account at developer.adzuna.com: set JOB_ADZUNA_APP_ID and JOB_ADZUNA_APP_KEY (environment or settings.json
`env`). Without them the search returns one `_error` and the daily run goes on. The API gives a short snippet, not the
full ad, and no per-job endpoint: the item's `url` is Adzuna's redirect to the original ad.

  {"platform": "adzuna", "what": "gis analyst", "where": "Perth", "country": "au"}
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from common import setting
from sources import base

NAME, COUNTRY, NEEDS_LOGIN = "adzuna", "*", False
APPLY = ("external", "")                         # Adzuna redirects to the employer or another board
DESCRIPTION = "Adzuna job search API (free key from developer.adzuna.com; au, nz, gb, us, ca...)"
KEYS = "what, where, country (default au), distance, pages"

API = "https://api.adzuna.com/v1/api/jobs"
SETUP = "set JOB_ADZUNA_APP_ID and JOB_ADZUNA_APP_KEY (free account at developer.adzuna.com)"


def keys() -> tuple[str, str]:
    return setting("JOB_ADZUNA_APP_ID", "").strip(), setting("JOB_ADZUNA_APP_KEY", "").strip()


def configured() -> bool:
    return all(keys())


def search(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    app_id, app_key = keys()
    if not (app_id and app_key):
        return [{"_error": "adzuna: " + SETUP}]
    country = str(search.get("country", "au")).lower()
    out: list[dict[str, Any]] = []
    for page in range(1, search.get("pages", 1) + 1):
        q = {"app_id": app_id, "app_key": app_key, "results_per_page": 50, "sort_by": "date",
             "max_days_old": max_age_days, "what": search.get("what", ""), "content-type": "application/json"}
        if search.get("where"):
            q["where"] = search["where"]
        if search.get("distance"):
            q["distance"] = search["distance"]
        code, data = base.get_json(f"{API}/{urllib.parse.quote(country)}/search/{page}?{urllib.parse.urlencode(q)}")
        if code != 200 or not isinstance(data, dict):             # the URL holds the keys: never put it in the error
            return out or [{"_error": f"adzuna {base.label(search)}: HTTP {code}"}]
        for j in data.get("results", []):
            lo, hi = j.get("salary_min"), j.get("salary_max")
            out.append(base.feed_item(
                "adzuna", "", j["id"], title=base.plain(j.get("title", "")), company=(j.get("company") or {}).get("display_name", ""),
                location=(j.get("location") or {}).get("display_name", ""), listed=base.iso(j.get("created")),
                url=j.get("redirect_url", ""), teaser=base.guarded(j.get("description", "")),
                salary=f"{int(lo)}-{int(hi)}" if lo and hi else "", work_type=j.get("contract_time", "") or j.get("contract_type", ""),
                classification=(j.get("category") or {}).get("label", "")))
        if len(data.get("results", [])) < 50:
            break
    return out
