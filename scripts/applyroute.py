"""How each job is applied for: on the portal itself, or on the employer's own site (and, when known, which system).

  job routes <slug> [--all] [--refresh]       count the board's open jobs by how they are applied for
  job routes <slug> --set <key> --url <apply url> [--gate open|login|captcha|blocked]
                                              record what the Apply button really led to (the form-filler does this)
  job routes <slug> --known <apply url>       what an earlier probe found on that employer's site (so it is not probed twice)
  job routes <slug> --queue                   the board's jobs grouped by what they need: logins (per portal), probe, ready
  job routes <slug> --hosts                   the sites Claude in Chrome has to be allowed on before a run

A route is one of
  quick     applied for on the portal (SEEK's own form, LinkedIn Easy Apply): the form-filler's best-tested path
  external  applied for on the employer's own site; `ats` names the system when it is known (greenhouse, lever, ...)
  unknown   the source cannot say

A probe is the Apply button actually clicked, and what loaded is the gate:
  open     a form with no account in front of it: the form-filler fills it up to the review page
  login    a sign-in or account step first: the person signs in once per portal, then the form-filler goes on
  captcha  a captcha or bot check: left to the person
  blocked  Claude in Chrome was not allowed on that site: allow it and probe again

A class groups the routes by what the person has to do, which is what the count prints:
  quick · open-ats (greenhouse, lever, ashby, workable, smartrecruiters: public forms, usually no account)
  · account-ats (workday, pageup, taleo, icims, ...: usually an account per employer) · company-site · unknown

The route is read where the harness already looks at the ad (triage, one request or none), never by logging in. A source
tells it with `route(job_id)` or the constant `APPLY = (route, ats)`; see docs/ADDING-A-SOURCE.md.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from typing import Any
from urllib.parse import urlparse

import sources
from common import cand_dir
from jobdb import connect

# Host fragment → system. Public application forms first, then the portals that ask for an account per employer.
OPEN_ATS = {"greenhouse": r"greenhouse\.io", "lever": r"lever\.co", "ashby": r"ashbyhq\.com",
            "workable": r"workable\.com", "smartrecruiters": r"smartrecruiters\.com"}
ACCOUNT_ATS = {"workday": r"myworkdayjobs\.com|myworkdaysite\.com|workday\.com", "pageup": r"pageuppeople\.com",
               "taleo": r"taleo\.net", "icims": r"icims\.com", "successfactors": r"successfactors\.(com|eu)|sapsf\.",
               "oracle": r"oraclecloud\.com", "neogov": r"governmentjobs\.com|neogov\.com", "jobvite": r"jobvite\.com",
               "bamboohr": r"bamboohr\.com", "livehire": r"livehire\.com", "dayforce": r"dayforcehcm\.com",
               "employmenthero": r"employmenthero\.com", "elmo": r"elmotalent\.com"}
OPEN, ACCOUNT = tuple(OPEN_ATS), tuple(ACCOUNT_ATS)
CLASSES = ("quick", "open-ats", "account-ats", "company-site", "unknown")
GATES = ("open", "login", "captcha", "blocked")
GATE_LABELS = {"open": "Form ready", "login": "Needs your login", "captcha": "Captcha: yours", "blocked": "Site not allowed in Chrome"}
BASE_HOSTS = ("www.linkedin.com", "www.seek.com.au", "au.seek.com", "jobs.wa.gov.au")
LABELS = {"quick": "Apply on the portal", "open-ats": "Public form (no account usually)",
          "account-ats": "Account per employer", "company-site": "Employer's site (system unknown)", "unknown": "Not known yet"}


def ats_of(url: str) -> str:
    """Name of the application system a URL belongs to ('' when it is not one we know)."""
    host = (urlparse(url).hostname or "").lower()
    for name, rx in {**OPEN_ATS, **ACCOUNT_ATS}.items():
        if re.search(rx, host):
            return name
    return ""


def klass(route: str, ats: str) -> str:
    if route == "quick":
        return "quick"
    if route == "external":
        return "open-ats" if ats in OPEN else "account-ats" if ats in ACCOUNT else "company-site"
    return "unknown"


def detect(platform: str, job_id: str) -> tuple[str, str]:
    """(route, ats) from the job's source: its APPLY constant, else its route(job_id), else ('unknown', '').
    Never raises: a failed request is 'unknown', and unknown is tried again later."""
    src = sources.get(platform)
    if src is None:
        return "unknown", ""
    try:
        if getattr(src, "APPLY", None):
            return tuple(src.APPLY)                                  # type: ignore[return-value]
        if sources.has(platform, "route"):
            r = src.route(job_id)
            return (r[0], r[1]) if r and r[0] in ("quick", "external") else ("unknown", "")
    except Exception:
        pass
    return "unknown", ""


def record(slug: str, key: str, route: str, ats: str = "") -> None:
    with connect(slug) as con:
        con.execute("UPDATE jobs SET apply_route=?, apply_ats=? WHERE key=?", (route, ats, key))


def record_many(slug: str, jobs: list[dict[str, Any]]) -> None:
    """Shortlisted jobs just read by triage: find each one's route once and keep it on the job and in jobs.db."""
    with connect(slug) as con:
        known = {r["key"]: (r["apply_route"] or "") for r in con.execute("SELECT key, apply_route FROM jobs")}
    for j in jobs:
        route, ats = (j.get("apply_route") or "", j.get("apply_ats") or "")
        if not route:
            if known.get(j["key"]) in ("quick", "external"):
                continue
            route, ats = detect(j["platform"], j["id"])
        j["apply_route"], j["apply_ats"] = route, ats
        record(slug, j["key"], route, ats)


def open_jobs(slug: str, everything: bool = False) -> list[dict[str, Any]]:
    """The board's applications still to do (or all but the dropped ones with --all), with their stored route."""
    from tracker import load
    keep = ("prepared", "manual-review") if not everything else None
    apps = [a for a in load(slug) if (a["status"] in keep if keep else a["status"] not in ("skipped", "closed"))]
    with connect(slug, readonly=True) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
        rows = {r["key"]: r for r in con.execute("SELECT * FROM jobs")} if "apply_route" in cols else {}
    return [{"key": a["key"], "platform": a["platform"], "title": a["title"], "company": a.get("company", ""),
             "route": (rows[a["key"]]["apply_route"] if a["key"] in rows else "") or "",
             "ats": (rows[a["key"]]["apply_ats"] if a["key"] in rows else "") or ""} for a in apps]


def count(slug: str, refresh: bool = False, everything: bool = False) -> dict[str, Any]:
    jobs = open_jobs(slug, everything)
    if refresh:
        todo = [j for j in jobs if j["route"] not in ("quick", "external")]
        for n, j in enumerate(todo):
            j["route"], j["ats"] = detect(j["platform"], j["key"].split(":", 1)[1])
            if j["route"] != "unknown":
                record(slug, j["key"], j["route"], j["ats"])
            if n < len(todo) - 1 and sources.get(j["platform"]) and not getattr(sources.get(j["platform"]), "APPLY", None):
                time.sleep(random.uniform(1.0, 2.5))                 # one polite request per job, like a person opening ads
    by_class: dict[str, int] = {c: 0 for c in CLASSES}
    by_platform: dict[str, dict[str, int]] = {}
    by_ats: dict[str, int] = {}
    for j in jobs:
        c = klass(j["route"], j["ats"])
        by_class[c] += 1
        by_platform.setdefault(j["platform"], {c: 0 for c in CLASSES})[c] += 1
        if j["ats"]:
            by_ats[j["ats"]] = by_ats.get(j["ats"], 0) + 1
    return {"open_jobs": len(jobs), "by_class": by_class, "by_platform": by_platform, "by_ats": by_ats,
            "unknown_keys": [j["key"] for j in jobs if klass(j["route"], j["ats"]) == "unknown"]}


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def set_url(slug: str, key: str, url: str, gate: str = "") -> dict[str, str]:
    """What the Apply button really led to (read by the person or the form-filler): the employer's host, the system's name
    when it is one we know, and the gate (open | login | captcha | blocked) when the probe saw it."""
    if gate and gate not in GATES:
        raise SystemExit(f"gate must be one of {', '.join(GATES)}")
    ats, host = ats_of(url), host_of(url)
    with connect(slug) as con:
        if not con.execute("SELECT 1 FROM jobs WHERE key=?", (key,)).fetchone():
            raise SystemExit(f"no job {key} in jobs.db")
        con.execute("UPDATE jobs SET apply_route='external', apply_ats=?, apply_host=?, "
                    "apply_gate=CASE WHEN ? != '' THEN ? ELSE apply_gate END WHERE key=?", (ats, host, gate, gate, key))
    return {"key": key, "route": "external", "ats": ats, "host": host, "gate": gate}


def known(slug: str, url: str) -> dict[str, str]:
    """What an earlier probe found on this employer's host: {host, ats, gate} (gate '' when never probed). A second ad of the
    same employer does not need a second probe."""
    host = host_of(url)
    with connect(slug, readonly=True) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
        row = (con.execute("SELECT apply_ats, apply_gate FROM jobs WHERE apply_host=? AND apply_gate != '' "
                           "ORDER BY last_seen DESC LIMIT 1", (host,)).fetchone() if host and "apply_host" in cols else None)
    return {"host": host, "ats": (row["apply_ats"] if row else "") or ats_of(url), "gate": (row["apply_gate"] if row else "") or ""}


def board(slug: str) -> list[dict[str, Any]]:
    """The jobs still to do, with route, system, host and gate."""
    from tracker import load
    apps = [a for a in load(slug) if a["status"] in ("prepared", "manual-review")]
    with connect(slug, readonly=True) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
        rows = {r["key"]: r for r in con.execute("SELECT * FROM jobs")} if "apply_gate" in cols else {}
    out = []
    for a in apps:
        r = rows.get(a["key"])
        g = lambda c: ((r[c] if r is not None else "") or "")        # noqa: E731
        out.append({"key": a["key"], "platform": a["platform"], "title": a["title"], "company": a.get("company", ""),
                    "route": g("apply_route"), "ats": g("apply_ats"), "host": g("apply_host"), "gate": g("apply_gate")})
    return out


def queue(slug: str) -> dict[str, Any]:
    """What is left for the person and what the harness can do alone: logins grouped by portal (one sign-in per portal, then
    the form-filler continues for every ad of that employer), jobs still to probe, and jobs ready to fill."""
    jobs = board(slug)
    logins: dict[str, dict[str, Any]] = {}
    for j in jobs:
        if j["gate"] == "login":
            g = logins.setdefault(j["host"] or "unknown", {"host": j["host"], "ats": j["ats"], "jobs": []})
            g["jobs"].append(f"{j['company']} — {j['title']} ({j['key']})")
    ready = [j["key"] for j in jobs if j["gate"] == "open" or j["route"] == "quick"]
    to_probe = [j["key"] for j in jobs if j["route"] != "quick" and not j["gate"]]
    return {"open_jobs": len(jobs), "ready_to_fill": len(ready), "to_probe": len(to_probe), "to_probe_keys": to_probe,
            "login_queue": sorted(logins.values(), key=lambda g: -len(g["jobs"])),
            "captcha": [j["key"] for j in jobs if j["gate"] == "captcha"],
            "blocked_hosts": sorted({j["host"] for j in jobs if j["gate"] == "blocked" and j["host"]})}


def hosts_to_allow(slug: str) -> list[str]:
    """Sites Claude in Chrome must be allowed on for the board's jobs: the portals plus every employer host a probe found.
    Chrome asks per site, and a site refused after the Apply click stops that job half way."""
    return sorted(set(BASE_HOSTS) | {j["host"] for j in board(slug) if j["host"]})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--all", action="store_true", help="every job on the board, not only those still to do")
    ap.add_argument("--refresh", action="store_true", help="ask the portals for the jobs whose route is not known yet")
    ap.add_argument("--set", metavar="KEY"); ap.add_argument("--url"); ap.add_argument("--gate", default="")
    ap.add_argument("--known", metavar="URL"); ap.add_argument("--queue", action="store_true"); ap.add_argument("--hosts", action="store_true")
    a = ap.parse_args()
    if not (cand_dir(a.slug) / "jobs.db").exists():
        raise SystemExit(f"no jobs.db for {a.slug}: run `job discover` first")
    if a.set:
        if not a.url:
            raise SystemExit("--set needs --url (the page the Apply button led to)")
        print(json.dumps(set_url(a.slug, a.set, a.url, a.gate), indent=2))
        return
    if a.known:
        print(json.dumps(known(a.slug, a.known), indent=2))
        return
    if a.queue:
        print(json.dumps(queue(a.slug), indent=2, ensure_ascii=False))
        return
    if a.hosts:
        print("\n".join(hosts_to_allow(a.slug)))
        return
    r = count(a.slug, a.refresh, a.all)
    print(json.dumps(r | {"classes": {c: LABELS[c] for c in CLASSES}}, indent=2))


if __name__ == "__main__":
    main()
