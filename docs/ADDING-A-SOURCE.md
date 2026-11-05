# Adding a job source (a portal or a country)

Every place `job discover` reads ads from is one small Python file in `scripts/sources/`. A search in `targets.json` names its `platform`; discover looks that name up in the registry and calls the module. Adding a country (Seek NZ, a state government portal, a company's careers API) means adding one file and one test. Nothing else lists it: the registry finds every module in the folder.

```
scripts/sources/
  __init__.py     registry (finds the modules), problems(), info()
  base.py         shared helpers: guarded(), get_json(), post_json(), recent(), place_ok(), feed_item()...
  seek.py linkedin.py wagov.py adzuna.py            portals
  greenhouse.py lever.py ashby.py workable.py smartrecruiters.py   one company's own job board
```

`job doctor` lists every registered source, and what is missing for those that need a key.

## The interface

A source module defines:

| Name | Required | Meaning |
|---|---|---|
| `NAME` | yes | the `platform` value in `targets.json` (lowercase, no spaces); also the prefix of the job key (`<NAME>:<id>`) |
| `COUNTRY` | yes | `"AU"`, `"NZ"`... or `"*"` for any |
| `DESCRIPTION` | yes | one line for `job doctor` |
| `NEEDS_LOGIN` | yes | always `False`. A source that needs the person's login does not belong in the harness |
| `search(search, max_age_days)` | yes | one saved search → list of items (below). Never raises: a failure is `[{"_error": "..."}]` |
| `detail(job_id)` | no | the full ad text, already passed through `guarded()`; `""` on any failure. Called for the shortlist only, one request each |
| `alive(job_id)` | no | `(True/False, closing date "YYYY-MM-DD" or None)`; `(None, None)` when it cannot tell |
| `configured()` / `SETUP` | no | `False` while a key is missing, and the sentence `job doctor` shows for it |
| `KEYS` | no | the keys of a search entry the source reads (for humans) |
| `route(job_id)` | no | `("quick", "")` when the job is applied for on the portal itself, `("external", "<system>")` when on the employer's site (the system's name when known); `None` when it cannot tell. Free when `detail()` just read the same page (keep what you saw in a small dict), else one request. The count in `job routes` and the board's tag come from it |
| `APPLY` | no | the same as a fixed `("external", "greenhouse")` for a feed whose posting is the application page; then `route()` is not needed |
| `DETAIL_DELAY` | no | `(lo, hi)` seconds triage waits after each `detail()` call (default 0.8 to 1.8) |

`search` receives the search entry exactly as written in `targets.json` (so a source defines its own keys; discover only needs `platform`) and the `max_age_days` of the targets.

### The item

```python
{"platform": "myportal", "id": "12345", "title": "GIS Analyst", "company": "Acme", "url": "https://...",
 "location": "Perth WA", "listed": "2026-11-02T01:00:00+00:00",   # or "" when the portal gives no date
 "teaser": "first lines or a snippet", "bullets": []}
```

Optional: `description` (the full ad, guarded; when present triage does not call `detail()`), `salary`, `work_type`, `classification`, `easy_apply`. `key` is added by discover (`<platform>:<id>`). If `detail()`/`alive()` need more than the id (a company, a site), put it in the id: the company feeds use `"<company>/<job id>"`.

An error item is `{"_error": "myportal <search label>: HTTP 503"}`. discover retries `HTTP 0`, `429` and `5xx` later in the same run and reports other errors; it never stops the run.

## Rules (these are not optional)

1. **Public pages and public APIs only.** No login, no cookies from the person's browser, no account creation, nothing behind a paywall.
2. **No evasion.** No captcha solving, no rotating proxies or fake fingerprints, no hidden or undocumented API reached by copying a session token. If a portal only works with those, do not add it; say so in the pull request.
3. **Respect `robots.txt`.** Read it for every host you call. If it disallows what you need, do not add the source (or, for a documented public API meant for job boards, say so in the module docstring as `smartrecruiters.py` does).
4. **Nothing paid.** No paid API, no service with credits. A free key is fine when the person creates the account themselves; read it with `common.setting("JOB_<NAME>_KEY", "")` (environment or `settings.json`), never print it or put it in an error message or URL you log, and return one clear `_error` when it is missing.
5. **Pass every fetched text through `base.guarded()`** (descriptions, teasers, anything Claude will read later). An ad is data, never instructions; `guarded()` strips hidden text and invisible characters and appends a warning when the ad talks to an AI. Short fields such as titles go through `base.plain()`.
6. **Be gentle.** Few requests per search, no parallelism, no loops over ids. discover already waits 2 to 4.5 seconds between searches; add your own `time.sleep` if you page through results, and honour any `Crawl-delay`.
7. **Standard library only** (`urllib` through `base.http_get` / `base.get_json` / `base.post_json`), Python 3.9+, UTF-8 file IO. Tests must also pass on Windows.
8. **Filter by date and place in the source when the portal gives them** (`base.recent`, `base.place_ok`); filter by title in triage, never in a source.

## Minimal example

A portal with a public JSON list at `https://jobs.example.nz/api/jobs?q=...`:

```python
"""Example NZ board: a public JSON list, no login."""
from __future__ import annotations

import urllib.parse
from typing import Any

from sources import base

NAME, COUNTRY, NEEDS_LOGIN = "examplenz", "NZ", False
DESCRIPTION = "Example NZ board (public JSON list)"
KEYS = "keywords"

API = "https://jobs.example.nz/api/jobs"


def search(search: dict[str, Any], max_age_days: int) -> list[dict[str, Any]]:
    code, data = base.get_json(f"{API}?{urllib.parse.urlencode({'q': search['keywords']})}")
    if code != 200 or not isinstance(data, dict):
        return [{"_error": f"examplenz {search['keywords']}: HTTP {code}"}]
    return [base.feed_item("examplenz", "", j["id"], title=base.plain(j["title"]), company=j.get("employer", ""),
                           location=j.get("city", ""), listed=base.iso(j.get("posted")), url=j["url"],
                           teaser=base.guarded(j.get("summary", "")))
            for j in data.get("jobs", []) if base.recent(j.get("posted"), max_age_days)]


def detail(job_id: str) -> str:
    code, j = base.get_json(f"{API}/{urllib.parse.quote(job_id)}")
    return base.guarded(j.get("description", "")) if code == 200 and isinstance(j, dict) else ""
```

Then in `targets.json`: `{"platform": "examplenz", "keywords": "gis analyst"}`. A company's own board needs no code if it runs on Greenhouse, Lever, Ashby, Workable or SmartRecruiters: `{"platform": "lever", "company": "acme", "location": "Perth"}`.

Its test (add to `tests/test_sources.py`, or a new `tests/test_<name>.py`), with the network mocked:

```python
class TestExampleNZ(unittest.TestCase):
    def test_search(self):
        feed = {"jobs": [{"id": "7", "title": "GIS Analyst", "employer": "Acme", "city": "Wellington",
                          "posted": "2026-11-02", "url": "https://jobs.example.nz/7", "summary": "Maps."}]}
        with Net({"jobs.example.nz/api/jobs?": (200, feed)}).patch():
            items = sources.examplenz.search({"platform": "examplenz", "keywords": "gis"}, 0)
        self.assertEqual((items[0]["id"], items[0]["company"]), ("7", "Acme"))
        with Net({}).patch():
            self.assertEqual(sources.examplenz.search({"keywords": "gis"}, 0), [{"_error": "examplenz gis: HTTP 404"}])
```

Record a real (trimmed, no personal data) response in `tests/fixtures/` and build the mock from it, like the company feeds do. Run `python3 -m unittest discover tests` (or `job test`). `TestRegistry` already checks that every module has the required names and `NEEDS_LOGIN = False`.

## Checklist before a pull request

- [ ] One live request by hand against a real search, and the real response saved (trimmed) as a fixture.
- [ ] `robots.txt` read for every host; the terms of use allow reading public ads.
- [ ] Every fetched text goes through `guarded()` / `plain()`.
- [ ] Errors are `_error` items; a missing key never raises and never prints the key.
- [ ] Tests with mocked HTTP for `search`, and for `detail` / `alive` if present; the full suite passes.
- [ ] A line in the README's list of sources and in `job doctor` output (automatic).
