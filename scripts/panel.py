"""Local panel: every application of a candidate on one page, with the buttons that change its status.

  job panel [--port 8765] [--no-open]      → http://127.0.0.1:8765/  (switch candidate in the page)
  job panel --lan                          also on your phone, over the same wifi: prints http://<this computer's IP>:8765/?t=<token>
  job panel --set-password                 once, in your own terminal: the password for remote mode (stored as a scrypt hash, 0600)
  job panel --remote [--port 8765]         also on your phone away from home, through a free Cloudflare quick tunnel (cloudflared)

Python standard library only, bound to 127.0.0.1 (nothing outside this Mac can reach it), no accounts, no database of
its own: it reads tracker.json, the daily packages (items.json) and jobs.db, and writes through the tracker's own
functions (set_status, set_note), the same rules as `job track` (limits, history). Ideas from Huntr/Teal (board, notes,
drag between columns), career-ops web (Today), Jobscan and LinkedIn Job Match (why a job fits or was dropped).

Views: Tablero (board), Embudo (funnel and calibration), Empresas (who publishes most, best fits, sponsor lists: the
employers worth contacting in person), Descartados (dropped ads with the rule that dropped them, a 'maybe worth a look' list of near misses, and the
filter suggestions learned from rescues).
GET  /?slug=<s>                 the page, with the board data embedded
GET  /api/job?slug=&key=        one application in full: description, keyword coverage, documents, history, notes
GET  /files/<slug>/<path>       a file from the candidate's package folder (CV, letter)
GET  /api/data?slug=            the board data again (the page refreshes itself after adding a link)
GET  /api/profile?slug=         the candidate's setup at a glance (candidate_profile.py), read when the Profile tab opens
GET  /draft?slug=&key=          a follow-up draft (.md/.txt) that the tracker entry points to, as plain text
GET  /api/visits?slug=&city=&tracks=   companies to visit in person in a city (scripts/visits.py): map pins, ranking, visit funnel
POST /status {slug,key,status}  POST /note {slug,key,text}  POST /rescue {slug,key[,track]}  POST /open {slug,key}
POST /visit {slug,company,city,stage[,note]}  POST /visit-details {slug,company,city[,note,contact]}
POST /visit-address {slug,company,city[,address | lat,lon[,address]]}   (the address is geocoded, outside the write lock)
GET  /login  POST /login {password}  POST /logout   (remote mode only)
POST /add-link {slug,url[,text,title,company]}   a job found by hand (scripts/addlink.py): read, scored, tracked, package built
Every POST must carry the token the page was served with, so another site open in the browser cannot post to it.
With --lan the server listens on every interface of this computer, so EVERY request (pages, files, API) must carry the
token: first as ?t=<token> (then an HttpOnly SameSite=Strict cookie and a redirect that drops it from the URL), compared in
constant time; without it the answer is 403. The token is new on every run and is printed once, in the link. "Open folder"
only works for a client on the computer itself. Anyone on the wifi who has the link can read and change the board.
Remote mode (--remote): the server still listens on 127.0.0.1 only; cloudflared publishes it at a random
https://<words>.trycloudflare.com address (no account, new address on every start) and the computer has to stay on, awake
and online. A request is REMOTE when it carries a Cf-Connecting-Ip / Cf-Ray / X-Forwarded-For header or its Host is not
127.0.0.1/localhost; requests from the computer itself behave exactly as before. Every remote request needs a session:
GET /login (form) -> POST /login with the password (scrypt hash in ~/.config/job-harness/panel_auth.json, set with
'job panel --set-password' in a real terminal; an AI agent cannot set it) -> a random server-side session cookie (HttpOnly,
Secure, SameSite=Lax, 14 days) and, on every POST, the X-Panel-Token as well. A session is bound to the password it was
created with: changing the password (job panel --set-password) ends every session. Failed logins are rate limited per client
IP (5 per 15 minutes, then 429). Because a tunnel hides IPs there is no global lockout (that would let anyone who has the
address lock the owner out); instead, once more than 30 logins failed in the last hour across all clients, every password
check is serialised and takes about 2 s (at most ~1800 guesses an hour overall) while the right password still logs in.
Concurrent password checks are bounded at all times. The counters live in memory only: restarting the panel clears all of
them (and every session). Files under /files/ that a browser could run (.html, .svg...) are served with
'Content-Security-Policy: sandbox', so they cannot run script or read the panel. "Open folder" is refused for remote clients.
Anyone who has the address AND the password can read and change the whole board: keep both private.
JOB_SUPPORT_URL (env or .claude/settings.local.json): the floating "Buy me a coffee" button. Defaults to 100 FOUNTS'
Stripe donation link (they build the harness); point it elsewhere, or set it to "" to hide the button.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.cookies
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import deque
from datetime import date, datetime, timedelta
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import osutil
import suggest
from common import cand_dir, list_candidates, read_json, setting
from status import summary
from tracker import OUTCOMES, PENDING, SENT, calibrate, followups, load, sent_date, set_note, set_status

TOKEN = secrets.token_urlsafe(24)         # new on every run
LAN = False                               # --lan: listening beyond 127.0.0.1, so every request needs the token
REMOTE = False                            # --remote: published through a tunnel; remote requests need a password session
COOKIE = "jh_panel"
MAX_BODY = 2_000_000                      # a pasted ad is text: far less than this
WRITE = threading.Lock()                  # the tracker file is rewritten whole: one POST at a time (a double click must not corrupt it)
SUPPORT_URL = "https://donate.stripe.com/4gM28t7b1g0kgHd5YE4wM00"
PAGE = Path(__file__).resolve().parent.parent / "templates" / "panel.html"
COLUMNS = [("todo", PENDING), ("sent", SENT), ("interview", {"interview"}), ("offer", {"offer", "hired"}),
           ("closed", {"closed", "rejected", "no-response", "withdrawn"})]
DROP_STATUS = {"todo": "prepared", "sent": "applied", "interview": "interview", "offer": "offer", "closed": "closed"}


def pkg_root(slug: str) -> Path:
    return Path(setting("JOB_PACKAGE_DIR", str(Path.home() / "job-packages"))) / slug


def column(status: str) -> str | None:
    return next((cid for cid, sts in COLUMNS if status in sts), None)


def package_items(slug: str) -> dict[str, dict[str, Any]]:
    """key → the package entry (notes, folder) from every daily package still on disk."""
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(pkg_root(slug).glob("*/items.json")):
        for x in read_json(f, {"items": []})["items"]:
            out[x["key"]] = x | {"day": f.parent.name}
    return out


def job_dir(slug: str, app: dict[str, Any], item: dict[str, Any] | None) -> Path | None:
    """The application's package folder: from items.json, else the folder its CV lives in."""
    if item and item.get("dir"):
        d = pkg_root(slug) / item["day"] / item["dir"]
        if d.is_dir():
            return d
    cv = Path(app.get("cv") or "")
    if cv.name and cv.exists() and pkg_root(slug) in cv.resolve().parents:
        return cv.parent.parent if cv.parent.name in ("tailored", "generic") else cv.parent
    return None


def ads(slug: str, keys: list[str]) -> dict[str, dict[str, Any]]:
    db = cand_dir(slug) / "jobs.db"
    if not db.exists() or not keys:
        return {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    q = ",".join("?" * len(keys))
    rows = {r["key"]: dict(r) for r in con.execute(f"SELECT * FROM jobs WHERE key IN ({q})", keys)}
    con.close()
    return rows


@lru_cache(maxsize=512)
def _cv_text(path: str, mtime: float) -> str:
    from facts import extract_text
    return extract_text(Path(path))


def cv_text(path: str | None) -> str:
    p = Path(path or "")
    return _cv_text(str(p), p.stat().st_mtime) if p.name and p.exists() else ""


def closes_of(app: dict[str, Any], item: dict[str, Any]) -> str:
    if app.get("closes"):
        return app["closes"]
    watch = ((item.get("notes") or {}).get("watch") or "")
    return next((w.split()[-1] for w in watch.split("; ") if w.startswith(("cierra el", "closes"))), "")


def cover(slug: str, app: dict[str, Any], ad: dict[str, Any]) -> dict[str, Any] | None:
    from coverage import coverage
    text = " ".join(filter(None, [ad.get("title"), ad.get("teaser"), ad.get("description")]))
    cv = cv_text(app.get("cv"))
    if not (text.strip() and cv):
        return None
    try:
        return coverage(slug, text, cv, app.get("track"))
    except Exception:                                     # never break the page over one ad
        return None


def reached(app: dict[str, Any], statuses: set[str]) -> bool:
    return app["status"] in statuses or any(h["status"] in statuses for h in app.get("history", []))


MIN_ANSWERED = 10                 # applications with an answer before the numbers mean anything
PLATFORM_NAME = {"seek": "SEEK", "linkedin": "LinkedIn", "wagov": "WA Government Jobs", "link": "links you pasted"}
FOLLOW_UP_DAYS = 10


def follow_up_due(app: dict[str, Any], days: int = FOLLOW_UP_DAYS, now: date | None = None) -> bool:
    """Sent (applied/submitted) and nothing newer in the history for `days` days. A chase marked in the history
    (a new 'applied' entry) starts the count again."""
    if app.get("status") not in SENT:
        return False
    hist = app.get("history") or []
    last = (hist[-1].get("date") or "")[:10] if hist else sent_date(app)
    return bool(last) and last <= ((now or date.today()) - timedelta(days=days)).isoformat()


def draft_file(slug: str, app: dict[str, Any]) -> Path | None:
    """The follow-up draft the tracker entry points to (`followup_draft`, .md or .txt; absolute, or relative to the
    package folder or the candidate's folder), if it exists. Anything else is ignored."""
    raw = app.get("followup_draft")
    if not isinstance(raw, str) or not raw.strip():
        return None
    p = Path(raw.strip())
    for f in ([p] if p.is_absolute() else [pkg_root(slug) / p, cand_dir(slug) / p]):
        if f.suffix.lower() in (".md", ".txt") and f.is_file():
            return f.resolve()
    return None


def red_flags_of(app: dict[str, Any]) -> list[str]:
    raw = app.get("red_flags")
    return [str(x).strip() for x in raw if str(x).strip()] if isinstance(raw, list) else []


def calibration_hint(cal: dict[str, Any]) -> str:
    """One plain sentence when a score band, track or source clearly outperforms; '' otherwise. A suggestion only:
    targets.json is sealed by an approval and nothing here touches it."""
    def lo_of(band: str) -> int | None:
        return int(band.split("-")[0]) if band[:1].isdigit() else None
    bands = [(lo_of(b), r) for b, r in cal["by_fit"].items() if lo_of(b) is not None]
    best = None
    for cut in (40, 60, 80):
        hi = [r for lo, r in bands if lo >= cut]
        low = [r for lo, r in bands if lo < cut]
        ha, la = sum(r["answered"] for r in hi), sum(r["answered"] for r in low)
        hg, lg = sum(r["interviews"] for r in hi), sum(r["interviews"] for r in low)
        if ha < 3 or la < 3 or not hg:
            continue
        hr, lr = hg / ha, lg / la
        if hr - lr >= 0.15 and (lr == 0 or hr >= 2 * lr) and (best is None or hr - lr > best[0]):
            best = (hr - lr, cut, hr, lr)
    if best:
        _, cut, hr, lr = best
        return (f"Interviews come from scores {cut}+ ({round(hr * 100)}% of the answers, against {round(lr * 100)}% below {cut}). "
                f"Consider applying less below {cut}.")
    for key in ("by_track", "by_platform"):
        rows = cal[key]
        pool = {k: r for k, r in rows.items() if r["answered"] >= 3 and r["interviews"]}
        if not pool:
            continue
        k = max(pool, key=lambda n: pool[n]["interviews"] / pool[n]["answered"])
        rest = [x for kk, x in rows.items() if kk != k]
        ra, rg = sum(x["answered"] for x in rest), sum(x["interviews"] for x in rest)
        hr, lr = pool[k]["interviews"] / pool[k]["answered"], (rg / ra if ra else 0)
        if ra >= 3 and hr - lr >= 0.15 and (lr == 0 or hr >= 2 * lr):
            what = f"the {k} track" if key == "by_track" else PLATFORM_NAME.get(k, k)
            return (f"Interviews come mostly from {what} ({round(hr * 100)}% of the answers, against {round(lr * 100)}% "
                    f"for the rest). Consider spending more time there.")
    return ""


def calibration(cal: dict[str, Any]) -> dict[str, Any]:
    n = cal["total"]["answered"]
    out: dict[str, Any] = {"answered": n, "needed": MIN_ANSWERED, "ready": n >= MIN_ANSWERED}
    if out["ready"]:
        out |= {"by_fit": cal["by_fit"], "by_track": cal["by_track"], "by_platform": cal["by_platform"],
                "hint": calibration_hint(cal)}
    return out


def funnel(slug: str, apps: list[dict[str, Any]]) -> dict[str, Any]:
    board = [a for a in apps if column(a["status"]) or a["status"] in ("skipped",) and reached(a, SENT)]
    prepared = [a for a in board if reached(a, PENDING | SENT)]
    sent = [a for a in board if reached(a, SENT)]
    interview = [a for a in sent if reached(a, {"interview", "offer", "hired"})]
    offer = [a for a in sent if reached(a, {"offer", "hired"})]
    waits = []
    for a in sent:
        sd = next((h["date"][:10] for h in a["history"] if h["status"] in SENT), None)
        od = next((h["date"][:10] for h in a["history"] if h["status"] in OUTCOMES), None)
        if sd and od:
            waits.append((date.fromisoformat(od) - date.fromisoformat(sd)).days)
    cal = calibrate(slug)
    return {"stages": [["Prepared", len(prepared)], ["Applied", len(sent)], ["Interview", len(interview)],
                       ["Offer", len(offer)]],
            "known": cal["total"]["with_outcome"], "by_fit": cal["by_fit"], "by_track": cal["by_track"],
            "by_platform": cal["by_platform"], "calibration": calibration(cal), "avg_wait": round(sum(waits) / len(waits)) if waits else None}


def dropped(slug: str, days: int = 7) -> list[dict[str, Any]]:
    """Ads the rules dropped in the last `days`, with the reason (LinkedIn's "why not recommended")."""
    db = cand_dir(slug) / "jobs.db"
    if not db.exists():
        return []
    since = (date.today() - timedelta(days=days)).isoformat()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("SELECT key, title, company, location, url, reason, last_seen, platform FROM jobs "
                       "WHERE verdict='rejected' AND last_seen >= ? ORDER BY last_seen DESC, title LIMIT 400",
                       (since,)).fetchall()
    con.close()
    tracked = {a["key"] for a in load(slug)}
    cols = ("key", "title", "company", "location", "url", "reason", "day", "platform")
    return [dict(zip(cols, r)) for r in rows if r[0] not in tracked]


def dropped_by_you(apps: list[dict[str, Any]], days: int = 30) -> list[dict[str, Any]]:
    """Ads the person dropped (status skipped) in the last `days`, newest first, so they can be restored. The day is that
    of the skip in the history. Ads the rescue flow parks as skipped ('rescued: waiting for its package') are not drops."""
    since = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for a in apps:
        if a["status"] != "skipped":
            continue
        skip = next((h for h in reversed(a.get("history", [])) if h["status"] == "skipped"), None)
        if not skip or skip["date"][:10] < since:
            continue
        said = (skip.get("note") or a.get("reason") or "")
        if said.startswith("rescued:") or (not skip.get("note") and (a.get("reason") or "").startswith("rescued:")):
            continue
        note = skip.get("note") or ""
        out.append({"key": a["key"], "title": a["title"], "company": a.get("company") or "", "url": a["url"],
                    "fit": a.get("fit"), "day": skip["date"][:10], "when": skip["date"],
                    "note": "" if note in ("", "from the panel", "dropped from the panel") else note})
    out.sort(key=lambda r: r["when"], reverse=True)
    return out


def maybes(slug: str, days: int = 7, n: int = 10) -> list[dict[str, Any]]:
    """Ads dropped ONLY because their title matched no track, ranked by how many of the tracks' keywords (core 2,
    support 1) their text still contains: the near misses worth a second look. Needs a score of 3+; titles the global or
    a track's exclude_title rejects stay out. Narrowed in SQL first (reason, date), then scored in one regex pass."""
    db = cand_dir(slug) / "jobs.db"
    if not db.exists():
        return []
    targets = read_json(cand_dir(slug) / "targets.json", {})
    m = suggest.Matcher(targets)
    if not m.rx:
        return []
    ex = [re.compile(r"\b(" + "|".join(re.escape(w) for w in ws) + r")\b", re.I)
          for ws in [targets.get("exclude_title", []), *[t.get("exclude_title", []) for t in targets.get("tracks", [])]] if ws]
    since = (date.today() - timedelta(days=days)).isoformat()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("SELECT key, title, company, url, last_seen, teaser, bullets, substr(description, 1, 6000) FROM jobs "
                       "WHERE verdict='rejected' AND reason LIKE 'title does not match%' AND last_seen >= ? "
                       "ORDER BY last_seen DESC LIMIT 3000", (since,)).fetchall()
    con.close()
    tracked = {a["key"] for a in load(slug)}
    out = []
    for key, title, company, url, seen, teaser, bullets, desc in rows:
        if key in tracked or not title or any(x.search(title) for x in ex):
            continue
        found = m.found(" ".join(filter(None, [title, teaser, bullets, desc])))      # SQL keeps the first 6000 characters: an ad's opening says what it is
        score = m.score(found)
        if score >= suggest.MIN_SCORE:
            out.append({"key": key, "title": title, "company": company or "", "url": url or "", "day": seen, "score": score,
                        "keywords": m.chips(found), "track": m.best_track(found)})
    out.sort(key=lambda r: (r["score"], r["day"]), reverse=True)
    return out[:n]


SPONSOR_POINTS = {"exact": 100, "likely": 70, "possible": 35}


def company_priority(ads: int, avg: float | None, sponsor: str | None, has_sponsor_data: bool = True) -> int:
    """How worth contacting an employer is, 0 to 100, from three things: the average score of its qualifying ads (half),
    how many there are (a third, full marks from 5 ads so one busy employer or agency cannot bury a better one), and the
    sponsor lists (a fifth). Without sponsor data the other two share the weight. The best score is shown, not ranked on.
    templates/panel.html repeats this formula to rank again after the filters."""
    qty = min(ads, 5) / 5 * 100
    a = avg or 0
    if not has_sponsor_data:
        return round(a * 0.65 + qty * 0.35)
    return round(a * 0.5 + qty * 0.3 + SPONSOR_POINTS.get(sponsor or "", 0) * 0.2)


def companies(slug: str, days: int = 60) -> list[dict[str, Any]]:
    """Employers worth contacting, from the ads that QUALIFIED in the last `days` (passed the rules: tracked or
    shortlisted; dropped ads do not count). Ranked by `company_priority`: average score, number of qualifying ads and
    sponsor list match. Each carries its best score too. Agencies post under their own name; they are flagged."""
    from sponsors import lookup, normalize, core
    db = cand_dir(slug) / "jobs.db"
    if not db.exists():
        return []
    since = (date.today() - timedelta(days=days)).isoformat()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("SELECT key, company, title, location, verdict, fit, last_seen, url, platform, track FROM jobs "
                       "WHERE last_seen >= ? AND company IS NOT NULL AND company != ''", (since,)).fetchall()
    con.close()
    apps = {a["key"]: a for a in load(slug)}
    fits = {k: a.get("fit") for k, a in apps.items()}
    groups: dict[str, dict[str, Any]] = {}
    for key, company, title, location, verdict, fit, seen, url, platform, track in rows:
        if key not in fits and verdict != "shortlisted":       # only ads that qualified count
            continue
        g = groups.setdefault(core(normalize(company)) or company.upper(),
                              {"company": company, "ads": 0, "best": None, "titles": [], "last": "",
                               "cities": set(), "best_url": "", "jobs": []})
        g["ads"] += 1
        f = fits.get(key, fit)
        city = next((c for c in ("Perth", "Adelaide") if c.lower() in (location or "").lower()), "")
        g["jobs"].append({"fit": f, "platform": platform, "track": (apps.get(key) or {}).get("track") or track or "",
                          "city": city, "title": title, "url": url, "seen": seen})
        if f is not None and (g["best"] is None or f > g["best"]):
            g["best"], g["best_url"] = f, url
        if title and title not in g["titles"]:
            g["titles"].append(title)
        g["last"] = max(g["last"], seen or "")
        g["cities"].update(c for c in ("Perth", "Adelaide") if c.lower() in (location or "").lower())
    agency = re.compile(r"(?i)recruit|talent|staff|personnel|people(bank)?\b|hays|randstad|hudson|robert half|"
                        r"chandler macleod|paxus|halcyon|sharp ?& ?carter|michael page|adecco|manpower|\bhire")
    out = []
    for g in groups.values():
        sp = lookup(g["company"])
        g["agency"] = bool(agency.search(g["company"]))
        out.append(g | {"titles": g["titles"][:4], "cities": sorted(g["cities"]),
                        "sponsor": sp["match"] if sp else None,
                        "sponsor_name": sp["names"][0] if sp else "", "sponsor_lists": sp["lists"] if sp else []})
    has_sp = any(g["sponsor"] for g in out)
    for g in out:
        fs = [j["fit"] for j in g["jobs"] if j["fit"] is not None]
        g["avg"] = round(sum(fs) / len(fs)) if fs else None
        g["priority"] = company_priority(g["ads"], g["avg"], g["sponsor"], has_sp)
    return sorted(out, key=lambda g: (-g["priority"], -(g["best"] or 0), -g["ads"]))[:150]


def sponsor_of(company: str) -> dict[str, str]:
    """How the company matches the visa sponsor lists, for the board card's icon (the person's eyes only): 'exact', 'likely'
    or 'possible' plus the listed name; empty without data or a match."""
    from sponsors import lookup
    sp = lookup(company)
    return {"sponsor_match": sp["match"], "sponsor_name": sp["names"][0]} if sp else {"sponsor_match": "", "sponsor_name": ""}


def route_of(ad: dict[str, Any]) -> dict[str, str]:
    """How the job is applied for, for the card's tag: quick | open-ats | account-ats | company-site | unknown,
    and what the Apply button led to when a probe saw it: open | login | captcha | blocked (applyroute.py)."""
    from applyroute import klass
    return {"apply": klass(ad.get("apply_route") or "", ad.get("apply_ats") or ""), "apply_ats": ad.get("apply_ats") or "",
            "apply_gate": ad.get("apply_gate") or ""}


def data(slug: str) -> dict[str, Any]:
    items = package_items(slug)
    all_apps = load(slug)
    board = [a for a in all_apps if column(a["status"])]
    jobs = ads(slug, [a["key"] for a in board])
    today, soon = date.today().isoformat(), (date.today() + timedelta(days=3)).isoformat()
    apps = []
    for a in board:
        it, ad = items.get(a["key"], {}), jobs.get(a["key"], {})
        n = it.get("notes") or {}
        c = cover(slug, a, ad) if column(a["status"]) == "todo" else None
        sent = a.get("submitted") or next((h["date"][:10] for h in a["history"] if h["status"] in SENT), "")
        apps.append({"key": a["key"], "title": a["title"], "company": a.get("company") or "", "url": a["url"],
                     "platform": a["platform"], "status": a["status"], "col": column(a["status"]), "fit": a.get("fit"),
                     "track": a.get("track") or "", "location": a.get("location") or "", "date": a["date"],
                     "sent": sent, "closes": closes_of(a, it), "sponsor": n.get("sponsor", ""),
                     "match": c["match_pct"] if c else None, "gaps": (c or {}).get("gaps", [])[:3],
                     "have_it": (c or {}).get("have_it", [])[:3],
                     "tailored": any("tailored" in (h.get("note") or "") for h in a["history"]),
                     "has_folder": job_dir(slug, a, it) is not None, "notes": bool(a.get("notes")),
                     "red_flags": red_flags_of(a), "follow_up": follow_up_due(a), "draft": draft_file(slug, a) is not None,
                     "new": a["date"] == today, **sponsor_of(a.get("company") or ""), **route_of(ad)})
    pending_answers = len(read_json(cand_dir(slug) / "pending_questions.json", {"questions": []}).get("questions", []))
    return {"slug": slug, "name": read_json(cand_dir(slug) / "intake.json")["name"], "apps": apps,
            "state": summary(slug)["state"],
            "today": {"to_apply": sum(a["col"] == "todo" for a in apps), "new": sum(a["new"] for a in apps),
                      "closing_soon": [a["key"] for a in apps if a["col"] == "todo" and a["closes"]
                                       and today <= a["closes"] <= soon],
                      "followups": [f for f in followups(slug) if f["action"] != "waiting (already chased)"],
                      "pending_answers": pending_answers},
            "funnel": funnel(slug, all_apps), "dropped": dropped(slug),
            "dropped_by_you": dropped_by_you(all_apps), "maybes": maybes(slug),
            "suggestions": [{"phrase": x["phrase"], "track": x["track"]} for x in suggest.pending(slug)], "companies": companies(slug),
            "candidates": list_candidates(), "support_url": setting("JOB_SUPPORT_URL", SUPPORT_URL),
            "generated": datetime.now().strftime("%H:%M")}


def detail(slug: str, key: str) -> dict[str, Any]:
    from sponsors import describe
    from triage import min_years_required
    app = next((a for a in load(slug) if a["key"] == key), None)
    if not app:
        return {"error": "That application is no longer in the tracker."}
    it = package_items(slug).get(key, {})
    ad = ads(slug, [key]).get(key, {})
    d = job_dir(slug, app, it)
    docs = []
    if d:
        for f in sorted([*d.glob("*.pdf"), *d.glob("*.docx"), *d.glob("tailored/*.md")]):
            rel = f.relative_to(pkg_root(slug))
            docs.append({"name": f.name, "url": "/files/" + urllib.parse.quote(f"{slug}/{rel}"),
                         "kind": "cv" if "Resume" in f.name else "letter" if "Cover" in f.name else "notes",
                         "pdf": f.suffix == ".pdf"})
    c = cover(slug, app, ad)
    desc = ad.get("description") or ad.get("teaser") or ""
    lang = read_json(cand_dir(slug) / "intake.json").get("ui_language", "en")
    return {"key": key, "title": app["title"], "company": app.get("company") or "", "url": app["url"],
            "location": app.get("location") or "", "platform": app["platform"], "status": app["status"],
            "col": column(app["status"]), "fit": app.get("fit"), "track": app.get("track") or "",
            "salary": ad.get("salary") or "", "closes": closes_of(app, it), "years": min_years_required(desc),
            "how": (it.get("notes") or {}).get("how", ""), "sponsor": describe(app.get("company") or "", lang),
            "coverage": c, "description": desc, "summary": app.get("summary") or "",
            "history": [{"date": h["date"][:10], "status": h["status"], "note": h.get("note") or ""}
                        for h in reversed(app.get("history", []))],
            "notes": app.get("notes") or "", "docs": docs, "has_folder": d is not None,
            "tailored": bool(d and (d / "tailored").is_dir()),
            "red_flags": red_flags_of(app), "follow_up": follow_up_due(app),
            "draft_url": f"/draft?slug={urllib.parse.quote(slug)}&key={urllib.parse.quote(key)}" if draft_file(slug, app) else "",
            "draft_text": next((f["draft"] for f in followups(slug) if f["key"] == key), "") if follow_up_due(app) else ""}


def rescue(slug: str, key: str, pick: str | None = None) -> dict[str, Any]:
    """An ad the rules dropped that the person wants: track it and build its package now (job prepare --only).
    If it was dropped only for its title, the track is the one picked (else the one with most keyword hits) and the
    title's role phrase is saved as a filter suggestion (suggestions.json); targets.json is never touched."""
    from tracker import add
    con = sqlite3.connect(f"file:{cand_dir(slug) / 'jobs.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
    con.close()
    if not row:
        return {"ok": False, "error": "That ad is not in the job memory."}
    targets = read_json(cand_dir(slug) / "targets.json")
    track = row["track"] or next((t["id"] for t in targets["tracks"] if t.get("primary")), targets["tracks"][0]["id"])
    suggested = ""
    if (row["reason"] or "").startswith("title does not match"):
        m = suggest.Matcher(targets)
        text = " ".join(filter(None, [row["title"], row["teaser"], row["bullets"], row["description"]]))
        track = pick if pick in m.weights else m.best_track(m.found(text)) or track
        suggested = suggest.record(slug, row["title"], key, track)
    if key not in {a["key"] for a in load(slug)}:
        add(slug, {"key": key, "title": row["title"], "company": row["company"], "url": row["url"], "platform": row["platform"],
                   "track": track, "location": row["location"] or "", "summary": "rescued from the panel"})
        set_status(slug, key, "skipped", reason="rescued: waiting for its package")
    r = subprocess.run([*osutil.python(), str(Path(__file__).parent / "prepare.py"), slug, "--max", "99", "--requeue", key, "--only"],
                       capture_output=True, encoding="utf-8", timeout=300)
    return {"ok": r.returncode == 0, "error": r.stderr[-300:] if r.returncode else "", "suggested": suggested}


def open_folder(slug: str, key: str) -> dict[str, Any]:
    app = next((a for a in load(slug) if a["key"] == key), None)
    d = job_dir(slug, app, package_items(slug).get(key)) if app else None
    if not d:
        return {"ok": False, "error": "This application has no package folder."}
    osutil.open_path(d)          # the package folder: the CV and letter to upload
    return {"ok": True, "path": str(d)}


def token_ok(candidate: str | None) -> bool:
    """The run's token, compared in constant time."""
    return bool(candidate) and hmac.compare_digest(str(candidate).encode("utf-8"), TOKEN.encode("utf-8"))


def is_local_client(client_ip: str, server_ip: str) -> bool:
    """A client on the computer running the panel: loopback, or its own address (the LAN link opened on that computer)."""
    return client_ip in ("127.0.0.1", "::1") or client_ip.startswith("::ffff:127.") or client_ip == server_ip


def lan_ip() -> str:
    """This computer's address on the local network (no packet is sent: a UDP socket only picks the route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------------------------------------------------------------
# Remote mode: password, sessions, login rate limit, tunnel
# ---------------------------------------------------------------------------------------------------------------------
SESSION_COOKIE = "jh_sess"
SESSION_TTL = 14 * 24 * 3600              # absolute: a session never lives longer than this
LOGIN_BODY_MAX = 4096
LOGIN_DELAY = 0.5                         # seconds of sleep on every failed login
SLOW_DELAY = 2.0                          # while the global failure count is exceeded: every password check waits this long, one at a time
PW_CHECKS = 4                             # most scrypt checks running at once (each takes ~16 MiB and some tens of ms)
PW_WAIT = 20.0                            # seconds a login may queue for a password-check slot before it is told to retry
MIN_PASSWORD = 10
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
PROXY_HEADERS = ("Cf-Connecting-Ip", "Cf-Ray", "X-Forwarded-For")      # what a request through the tunnel carries
TUNNEL_TIMEOUT = 40.0
CLOUDFLARED_HELP = ("cloudflared is not installed. macOS: brew install cloudflared. Other systems: "
                    "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")


def auth_file() -> Path:
    return Path.home() / ".config" / "job-harness" / "panel_auth.json"


PBKDF2_ITERATIONS = 600_000                # OWASP's figure for PBKDF2-HMAC-SHA256


def hash_password(password: str, salt: bytes | None = None, algo: str | None = None) -> dict[str, Any]:
    """scrypt when this Python has it; PBKDF2-HMAC-SHA256 otherwise (macOS's own Python 3.9 is built on LibreSSL, which
    has no scrypt). The record says which, so a password set with one still verifies after a Python upgrade."""
    salt = salt or os.urandom(16)
    algo = algo or ("scrypt" if hasattr(hashlib, "scrypt") else "pbkdf2_sha256")
    if algo == "scrypt":
        return {"version": 1, "algo": "scrypt", **SCRYPT, "salt": salt.hex(),
                "hash": hashlib.scrypt(password.encode("utf-8"), salt=salt, **SCRYPT).hex()}
    return {"version": 1, "algo": "pbkdf2_sha256", "iterations": PBKDF2_ITERATIONS, "salt": salt.hex(),
            "hash": hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS).hex()}


def verify_password(password: str, rec: dict[str, Any] | None) -> bool:
    """Constant-time check against a stored record; anything malformed (or scrypt on a Python without it) is simply 'no'."""
    try:
        want, salt = bytes.fromhex(rec["hash"]), bytes.fromhex(rec["salt"])     # type: ignore[index]
        if rec.get("algo", "scrypt") == "pbkdf2_sha256":                         # type: ignore[union-attr]
            it = int(rec["iterations"])                                          # type: ignore[index]
            if not 100_000 <= it <= 10_000_000:
                return False
            got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, it)
        else:
            params = {k: int(rec[k]) for k in ("n", "r", "p", "dklen")}        # type: ignore[index]
            if not (2 <= params["n"] <= 2 ** 16 and 1 <= params["r"] <= 16 and 1 <= params["p"] <= 4 and 16 <= params["dklen"] <= 64):
                return False
            got = hashlib.scrypt(password.encode("utf-8"), salt=salt, **params)
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return False
    return hmac.compare_digest(got, want)


def load_auth() -> dict[str, Any] | None:
    try:
        rec = json.loads(auth_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("hash") and rec.get("salt") else None


def save_auth(rec: dict[str, Any]) -> None:
    f = auth_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(f.parent, 0o700)
    tmp = f.with_name(f.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(rec, fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, f)


def set_password() -> int:
    """'job panel --set-password'. Only from a person at a terminal: an AI agent (no TTY) cannot set it. The password is
    never printed or stored, only its salted scrypt hash."""
    if not sys.stdin.isatty():
        print("Refusing: the panel password can only be set from an interactive terminal, by you. "
              "Open a terminal yourself and run: job panel --set-password", file=sys.stderr)
        return 2
    import getpass
    if load_auth() and input("A panel password is already set. Replace it? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Kept the existing password.")
        return 1
    first = getpass.getpass("New panel password (min %d characters): " % MIN_PASSWORD)
    if len(first) < MIN_PASSWORD:
        print(f"Too short: use at least {MIN_PASSWORD} characters (a few words together work well).", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat it: ") != first:
        print("The two entries differ. Nothing was saved.", file=sys.stderr)
        return 1
    save_auth(hash_password(first))
    print(f"Password saved (hashed) in {auth_file()}. Now run: job panel --remote")
    return 0


SESSIONS: dict[str, float] = {}           # sha256(session id) -> expiry; in memory only, gone when the panel stops
SESSION_CRED: dict[str, str] = {}         # sha256(session id) -> fingerprint of the password record it was created with
SESSIONS_LOCK = threading.Lock()
_AUTH_CACHE: dict[str, Any] = {"key": None, "rec": None}


def _sid_key(sid: str) -> str:
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


def cred_id(rec: dict[str, Any] | None) -> str | None:
    """Fingerprint of a stored password record (salt + hash): it changes whenever the password does."""
    return hashlib.sha256(f"{rec['salt']}:{rec['hash']}".encode("utf-8")).hexdigest() if rec else None


def current_auth() -> dict[str, Any] | None:
    """load_auth() with a cache keyed on the file's identity and mtime, so a request does not re-read it every time
    but a changed password is seen at once."""
    f = auth_file()
    try:
        st = f.stat()
        key: Any = (str(f), st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(f), None)
    with SESSIONS_LOCK:
        if _AUTH_CACHE["key"] == key:
            return _AUTH_CACHE["rec"]
    rec = load_auth() if key[1] is not None else None
    with SESSIONS_LOCK:
        _AUTH_CACHE.update(key=key, rec=rec)
    return rec


def new_session(rec: dict[str, Any] | None = None) -> str:
    """A new session bound to the password record `rec` (the one the login was checked against; default: the current one)."""
    cred = cred_id(rec or current_auth())
    if not cred:
        raise ValueError("no password is set")
    sid = secrets.token_urlsafe(32)
    with SESSIONS_LOCK:
        now = time.time()
        for k in [k for k, exp in SESSIONS.items() if exp <= now]:
            del SESSIONS[k]
        for k in [k for k in SESSION_CRED if k not in SESSIONS]:
            del SESSION_CRED[k]
        SESSIONS[_sid_key(sid)] = now + SESSION_TTL
        SESSION_CRED[_sid_key(sid)] = cred
    return sid


def session_valid(sid: str | None) -> bool:
    if not sid:
        return False
    cred = cred_id(current_auth())
    k = _sid_key(sid)
    with SESSIONS_LOCK:
        exp = SESSIONS.get(k)
        if exp is None:
            return False
        if exp <= time.time() or not cred or not hmac.compare_digest(SESSION_CRED.get(k, ""), cred):
            del SESSIONS[k]                                   # expired, or the password changed since the login
            SESSION_CRED.pop(k, None)
            return False
        return True


def end_session(sid: str | None) -> None:
    if sid:
        with SESSIONS_LOCK:
            SESSIONS.pop(_sid_key(sid), None)
            SESSION_CRED.pop(_sid_key(sid), None)


class LoginGuard:
    """Failed-login limits. Per client IP: more than `per_ip` failures in `per_ip_window` seconds -> 429. Across all clients
    (a tunnel can hide the IP) there is no lockout, only throttling: while more than `total` failures happened in the last
    `total_window` seconds, `throttled()` is true and the caller slows every password check down. An attempt is counted
    BEFORE the password is checked (so a burst of parallel guesses cannot slip past) and taken back on success. In memory
    only: restarting the panel clears everything."""

    def __init__(self, per_ip: int = 5, per_ip_window: int = 900, total: int = 30, total_window: int = 3600) -> None:
        self.per_ip, self.per_ip_window, self.total, self.total_window = per_ip, per_ip_window, total, total_window
        self.ips: dict[str, list[tuple[float, int]]] = {}
        self.all: list[tuple[float, int]] = []
        self.n = 0
        self.lock = threading.Lock()

    @staticmethod
    def _wait(rows: list[tuple[float, int]], limit: int, window: int, now: float) -> int:
        rows[:] = [r for r in rows if r[0] > now - window]
        return max(1, int(rows[0][0] + window - now) + 1) if len(rows) >= limit else 0

    def begin(self, ip: str) -> tuple[int, int]:
        """(seconds to wait, attempt id): wait > 0 means refused (429) and nothing is counted."""
        with self.lock:
            now = time.time()
            mine = self.ips.setdefault(ip, [])
            wait = self._wait(mine, self.per_ip, self.per_ip_window, now)
            if wait:
                return wait, 0
            self.n += 1
            mine.append((now, self.n))
            self.all.append((now, self.n))
            self.all[:] = [r for r in self.all if r[0] > now - self.total_window]
            if len(self.ips) > 5000:                      # bounded memory against many spoofed addresses
                self.ips = {k: v for k, v in self.ips.items() if v and v[-1][0] > now - self.per_ip_window}
            return 0, self.n

    def throttled(self) -> bool:
        """True while the failures of the last hour, across all clients, exceed the total."""
        with self.lock:
            now = time.time()
            self.all[:] = [r for r in self.all if r[0] > now - self.total_window]
            return len(self.all) > self.total

    def success(self, ip: str, attempt: int) -> None:
        with self.lock:
            self.ips[ip] = [r for r in self.ips.get(ip, []) if r[1] != attempt]
            self.all = [r for r in self.all if r[1] != attempt]


PW_SLOTS = threading.BoundedSemaphore(PW_CHECKS)     # password checks running at once, always
PW_SERIAL = threading.BoundedSemaphore(1)            # ... and one at a time, each after a pause, while throttled


def check_password(password: str, rec: dict[str, Any] | None, slow: bool) -> bool | None:
    """verify_password under the concurrency bounds. slow (the global failure count is exceeded): one check at a time, each
    after SLOW_DELAY, so the whole panel allows ~3600/SLOW_DELAY guesses an hour. None: no slot within PW_WAIT (busy)."""
    serial = False
    try:
        if slow:
            if not PW_SERIAL.acquire(timeout=PW_WAIT):
                return None
            serial = True
            time.sleep(SLOW_DELAY)
        if not PW_SLOTS.acquire(timeout=PW_WAIT):
            return None
        try:
            return verify_password(password, rec)
        finally:
            PW_SLOTS.release()
    finally:
        if serial:
            PW_SERIAL.release()


LOGIN = LoginGuard()

LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Job panel: sign in</title>
<style>
:root { --ground: #eef1f3; --surface: #fff; --ink: #18232b; --muted: #5a6872; --line: #c9d2d8; --accent: #1f5b8f; --accent-ink: #fff; --err: #a32020; color-scheme: light dark; }
@media (prefers-color-scheme: dark) { :root { --ground: #0f1519; --surface: #172026; --ink: #e6ecef; --muted: #9aa8b1; --line: #2c3a43; --accent: #7fb3dd; --accent-ink: #0f1519; --err: #ff9b9b; } }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px; background: var(--ground); color: var(--ink); font: 16px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { width: 100%; max-width: 360px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 24px; }
h1 { margin: 0 0 4px; font-size: 20px; }
p { margin: 0 0 16px; color: var(--muted); font-size: 14px; }
label { display: block; font-size: 14px; margin-bottom: 6px; }
input { width: 100%; padding: 12px; font-size: 16px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: var(--ink); }
button { width: 100%; margin-top: 14px; padding: 12px; font-size: 16px; font-weight: 600; border: 0; border-radius: 8px; background: var(--accent); color: var(--accent-ink); cursor: pointer; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.err { color: var(--err); margin: 0 0 12px; }
</style></head>
<body><main>
<h1>Job panel</h1>
<p>Enter the panel password.</p>
__ERROR__
<form method="post" action="/login">
<label for="p">Password</label>
<input id="p" name="password" type="password" autocomplete="current-password" autofocus required>
<button type="submit">Sign in</button>
</form>
</main></body></html>
"""


def login_page(error: str = "") -> bytes:
    msg = f'<p class="err" role="alert">{error}</p>' if error else ""
    return LOGIN_PAGE.replace("__ERROR__", msg).encode("utf-8")


def parse_tunnel_url(line: str) -> str | None:
    """The https://<words>.trycloudflare.com address in a line of cloudflared's output (not its api.trycloudflare.com)."""
    for m in re.finditer(r"https://([a-z0-9][a-z0-9-]*)\.trycloudflare\.com\b", line, re.I):
        if m.group(1).lower() != "api":
            return m.group(0).lower()
    return None


class TunnelError(RuntimeError):
    pass


def read_tunnel_url(proc: Any, timeout: float = TUNNEL_TIMEOUT) -> str:
    """Read cloudflared's output in a thread until its address appears (it keeps draining afterwards so the pipe never
    fills). Raises TunnelError with the last lines when it ends or the timeout passes without one."""
    found, box, tail = threading.Event(), {"url": None}, deque(maxlen=12)

    def pump() -> None:
        try:
            for line in iter(proc.stdout.readline, ""):
                line = line.rstrip()
                if line:
                    tail.append(line)
                if not box["url"]:
                    box["url"] = parse_tunnel_url(line)
                    if box["url"]:
                        found.set()
        except (ValueError, OSError):
            pass
        found.set()                                       # the stream ended

    threading.Thread(target=pump, daemon=True).start()
    found.wait(timeout)
    if box["url"]:
        return box["url"]                                 # type: ignore[return-value]
    raise TunnelError("cloudflared gave no address" + (" in %d s" % timeout if proc.poll() is None else " and stopped")
                      + ". Its last lines:\n  " + "\n  ".join(tail))


def stop_process(p: Any) -> None:
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


def start_tunnel(port: int, timeout: float = TUNNEL_TIMEOUT) -> tuple[Any, str]:
    exe = shutil.which("cloudflared")
    if not exe:
        raise TunnelError(CLOUDFLARED_HELP)
    proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    try:
        return proc, read_tunnel_url(proc, timeout)
    except BaseException:
        stop_process(proc)
        raise


def keep_awake() -> Any:
    """macOS: stop the Mac from idle-sleeping while the panel runs (best effort)."""
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        try:
            return subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return None
    return None


class BadInput(ValueError):
    pass


def text_in(body: dict[str, Any], name: str, cap: int, required: bool = False) -> str | None:
    """A string field of a POST body: None when absent (unless required), an error for a non-string or a too long one."""
    v = body.get(name)
    if v is None:
        if required:
            raise BadInput(f"{name} is required.")
        return None
    if not isinstance(v, str):
        raise BadInput(f"{name} must be text.")
    v = v.strip()
    if required and not v:
        raise BadInput(f"{name} is required.")
    if len(v) > cap:
        raise BadInput(f"{name} is too long (at most {cap} characters).")
    return v


def number_in(body: dict[str, Any], name: str, lo: float, hi: float) -> float:
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise BadInput(f"{name} must be a number.")
    try:
        x = float(v)
    except ValueError:
        raise BadInput(f"{name} must be a number.") from None
    if not math.isfinite(x) or not lo <= x <= hi:
        raise BadInput(f"{name} must be between {lo:g} and {hi:g}.")
    return x


def visits_get(slug: str, q: dict[str, list[str]]) -> dict[str, Any]:
    """GET /api/visits: the city's companies (visits.places) plus the list of cities."""
    import visits
    city = (q.get("city", [""])[0] or "").strip()
    if len(city) > 80:
        raise BadInput("city is too long (at most 80 characters).")
    tracks = [t.strip() for t in (q.get("tracks", [""])[0] or "").split(",") if t.strip()]
    if len(tracks) > 30 or any(len(t) > 60 for t in tracks):
        raise BadInput("tracks is not valid.")
    cities = visits.cities(slug)
    city = city or (cities[0]["city"] if cities else "")
    if not city:
        return {"city": "", "tracks": [], "companies": [], "funnel": [], "missing": 0, "cities": cities}
    return dict(visits.places(slug, city, tracks or None)) | {"cities": cities}


def visits_post(path: str, slug: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST /visit, /visit-details, /visit-address. Geocoding happens here, outside WRITE (visits has its own lock)."""
    import visits
    company, city = text_in(body, "company", 200, True), text_in(body, "city", 80, True)
    assert company and city
    if path == "/visit":
        return visits.set_stage(slug, company, city, text_in(body, "stage", 40, True), text_in(body, "note", 2000) or "")
    if path == "/visit-details":
        return visits.set_details(slug, company, city, note=text_in(body, "note", 2000), contact=text_in(body, "contact", 2000))
    address = text_in(body, "address", 300)
    if body.get("lat") is not None or body.get("lon") is not None:
        if body.get("lat") is None or body.get("lon") is None:
            raise BadInput("lat and lon go together.")
        return visits.set_coords(slug, company, city, number_in(body, "lat", -90, 90), number_in(body, "lon", -180, 180), address or "")
    if not address:
        raise BadInput("address (or lat and lon) is required.")
    return visits.set_address(slug, company, city, address)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a: Any) -> None:  # quiet: also keeps the token (in the first request's URL) out of any log
        pass

    def send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8", headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj: Any, code: int = 200) -> None:
        self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def cookie_token(self) -> str:
        try:
            c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return ""
        return c[COOKIE].value if COOKIE in c else ""

    def cookie_value(self, name: str) -> str:
        try:
            c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return ""
        return c[name].value if name in c else ""

    def is_remote(self) -> bool:
        """--remote only: the request came through the tunnel (it carries one of Cloudflare's headers) or is addressed to
        a host that is not this computer. Anything unclear counts as remote. Local requests are not affected by remote mode."""
        if not REMOTE:
            return False
        if any(self.headers.get(h) is not None for h in PROXY_HEADERS):
            return True
        return self.headers.get("Host", "").split(":")[0].lower() not in ("127.0.0.1", "localhost")

    def session_ok(self) -> bool:
        return session_valid(self.cookie_value(SESSION_COOKIE))

    def client_key(self) -> str:
        return (self.headers.get("Cf-Connecting-Ip") or self.client_address[0])[:64]

    def local_client(self) -> bool:
        if self.is_remote():                      # the tunnel connects from this computer: the socket says nothing here
            return False
        return is_local_client(self.client_address[0], self.connection.getsockname()[0])

    def page_data(self, slug: str) -> dict[str, Any]:
        return data(slug) | {"local": self.local_client(), "lan": LAN, "remote": self.is_remote()}

    def remote_gate(self, path: str) -> bool:
        """--remote, remote request, GET. True when it may go on. The login form and a favicon 404 are the only open paths."""
        if path == "/login":
            if self.session_ok():
                self.send(303, b"", headers={"Location": "/"})
            else:
                self.send(200, login_page())
            return False
        if path == "/favicon.ico":
            self.send(404, b"")
            return False
        if not self.session_ok():
            self.send(303, b"", headers={"Location": "/login"})
            return False
        return True

    def post_login(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            length = 0
        if length > LOGIN_BODY_MAX:
            self.rfile.read(min(length, 65536))        # a refusal must not reset the connection before the client has sent it all
            self.close_connection = True
            return self.send(413, b"too large")
        raw = self.rfile.read(length) if length > 0 else b""
        ip = self.client_key()
        wait, attempt = LOGIN.begin(ip)
        if wait:
            return self.send(429, login_page("Too many attempts. Try again later."), headers={"Retry-After": str(wait)})
        password = urllib.parse.parse_qs(raw.decode("utf-8", "replace")).get("password", [""])[0]
        rec = current_auth()
        ok = check_password(password, rec, LOGIN.throttled()) if password else False
        if ok is None:                                 # too many checks queued: not a failed guess
            LOGIN.success(ip, attempt)
            return self.send(429, login_page("Too many attempts. Try again later."), headers={"Retry-After": "5"})
        if ok:
            LOGIN.success(ip, attempt)
            sid = new_session(rec)
            return self.send(303, b"", headers={"Location": "/", "Set-Cookie":
                                                f"{SESSION_COOKIE}={sid}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}"})
        time.sleep(LOGIN_DELAY)
        self.send(401, login_page("That password is not right."))

    def other_method(self) -> None:
        """PUT, DELETE and the rest are not supported; from a remote client without a session they are 401, never a hint."""
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            n = 0
        if 0 < n <= MAX_BODY:
            self.rfile.read(n)                         # answer only after the body is read: no connection reset
        self.close_connection = True
        if self.is_remote() and not self.session_ok():
            return self.json({"ok": False, "error": "Login required."}, 401)
        self.send(405, b"method not allowed")

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = other_method

    def lan_gate(self, u: urllib.parse.ParseResult) -> bool:
        """--lan only. True when the request may go on. A valid ?t=<token> is turned into the cookie and a redirect to the
        same address without it (the token does not stay in the URL bar or the history); anything else is 403."""
        t = urllib.parse.parse_qs(u.query).get("t", [""])[0]
        if t:
            if not token_ok(t):
                self.send(403, b"forbidden")
                return False
            rest = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(u.query) if k != "t"])
            where = "/" + u.path.lstrip("/") + (f"?{rest}" if rest else "")
            self.send(302, b"", headers={"Location": where, "Set-Cookie": f"{COOKIE}={TOKEN}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400"})
            return False
        if not token_ok(self.cookie_token()):
            self.send(403, b"forbidden: open the link that 'job panel --lan' printed")
            return False
        return True

    def do_GET(self) -> None:
        u = urllib.parse.urlparse(self.path)
        if self.is_remote():
            if not self.remote_gate(u.path):
                return
        elif LAN and not self.lan_gate(u):
            return
        q = urllib.parse.parse_qs(u.query)
        cands = list_candidates()
        first = ([c for c in cands if c != "example"] or cands or [""])[0]      # the fictional sample only when it is alone
        slug = q.get("slug", [first])[0]
        if u.path.startswith("/files/"):
            rel = Path(urllib.parse.unquote(u.path[len("/files/"):]))
            if not rel.parts or rel.parts[0] not in cands:
                return self.send(404, b"not found")
            root = pkg_root(rel.parts[0]).resolve()
            f = (root / Path(*rel.parts[1:])).resolve()
            if root not in f.parents or not f.is_file():
                return self.send(404, b"not found")
            return self.send(200, f.read_bytes(), text_type(f),
                             {"Content-Security-Policy": "sandbox"} if f.suffix.lower() in ACTIVE_SUFFIXES else None)
        if slug not in cands:
            return self.send(404, b"unknown candidate")
        if u.path == "/":
            page = PAGE.read_text(encoding="utf-8").replace("__DATA__", json.dumps(self.page_data(slug), ensure_ascii=False).replace("</", "<\\/"))
            return self.send(200, page.replace("__TOKEN__", TOKEN).encode())
        if u.path == "/api/data":
            return self.json(self.page_data(slug))
        if u.path == "/api/job":
            return self.json(detail(slug, q.get("key", [""])[0]))
        if u.path == "/api/profile":
            from candidate_profile import profile
            return self.json(profile(slug))
        if u.path == "/api/visits":
            try:
                return self.json(visits_get(slug, q))
            except BadInput as e:
                return self.json({"ok": False, "error": str(e)}, 400)
            except Exception as e:                    # never a stack trace to the page
                return self.json({"ok": False, "error": f"Could not load the visits ({e.__class__.__name__})."}, 500)
        if u.path == "/draft":
            app = next((a for a in load(slug) if a["key"] == q.get("key", [""])[0]), None)
            f = draft_file(slug, app) if app else None
            return self.send(200, f.read_bytes(), "text/plain; charset=utf-8") if f else self.send(404, b"not found")
        self.send(404, b"not found")

    def do_POST(self) -> None:
        remote = self.is_remote()
        if remote and self.path.split("?", 1)[0] == "/login":
            return self.post_login()
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if 0 < length <= MAX_BODY else b""      # read it before any answer: a refusal must not reset the connection
        if remote:
            if not self.session_ok():
                return self.json({"ok": False, "error": "Login required."}, 401)
            allowed = token_ok(self.headers.get("X-Panel-Token"))
        elif LAN:
            allowed = token_ok(self.cookie_token()) and token_ok(self.headers.get("X-Panel-Token"))
        else:
            allowed = token_ok(self.headers.get("X-Panel-Token")) and self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")
        if not allowed:
            return self.send(403, b"forbidden")
        if length > MAX_BODY:
            return self.send(413, b"too large")
        if self.path == "/logout":
            end_session(self.cookie_value(SESSION_COOKIE))
            return self.send(200, b'{"ok": true}', "application/json; charset=utf-8",
                             {"Set-Cookie": f"{SESSION_COOKIE}=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0"})
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self.send(400, b"bad request")
        if not isinstance(body, dict):
            return self.send(400, b"bad request")
        slug, key = body.get("slug"), body.get("key")
        if slug not in list_candidates():
            return self.send(404, b"unknown candidate")
        try:
            if self.path == "/status":
                status = DROP_STATUS.get(body.get("column"), body.get("status"))
                with WRITE:
                    set_status(slug, key, status, note=body.get("note") or "from the panel")
                return self.json({"ok": True, "status": status})
            if self.path == "/note":
                with WRITE:
                    set_note(slug, key, body.get("text") or "")
                return self.json({"ok": True})
            if self.path == "/rescue":
                return self.json(rescue(slug, key, body.get("track")))
            if self.path == "/add-link":
                import addlink
                try:       # the page is downloaded outside the lock; only the writes inside it
                    return self.json(addlink.add_link(slug, str(body.get("url") or ""), str(body.get("text") or ""),
                                                      str(body.get("title") or ""), str(body.get("company") or ""), lock=WRITE))
                except Exception as e:                    # never a stack trace to the page
                    return self.json({"ok": False, "error": f"Could not add it ({e.__class__.__name__}). Try pasting the text of the ad."})
            if self.path in ("/visit", "/visit-details", "/visit-address"):
                try:
                    return self.json(visits_post(self.path, slug, body))
                except BadInput as e:
                    return self.json({"ok": False, "error": str(e)}, 400)
                except Exception as e:                # never a stack trace to the page
                    return self.json({"ok": False, "error": f"Could not save it ({e.__class__.__name__})."}, 500)
            if self.path == "/open":
                if not self.local_client():             # it would open a folder on the computer, not on the phone
                    return self.json({"ok": False, "error": "Opening the folder only works on the computer that runs the panel."}, 403)
                return self.json(open_folder(slug, key))
        except SystemExit as e:                       # tracker refusals (limits, unknown key) come back as text
            return self.json({"ok": False, "error": str(e)}, 409)
        self.send(404, b"not found")


ACTIVE_SUFFIXES = (".html", ".htm", ".xhtml", ".xht", ".svg")      # a browser runs script in these: serve them sandboxed (opaque origin)


def text_type(f: Path) -> str:
    """Drafts and notes (.md/.txt) open in the browser as plain text instead of downloading."""
    if f.suffix.lower() in (".md", ".txt"):
        return "text/plain; charset=utf-8"
    return mimetypes.guess_type(f.name)[0] or "application/octet-stream"


def run_remote(port: int) -> None:
    """--remote: the server on 127.0.0.1 only, published by a cloudflared quick tunnel. Everything started here is stopped
    on the way out (Ctrl+C, SIGTERM, or the tunnel dying)."""
    global REMOTE
    if not load_auth():
        sys.exit("No panel password is set. Open a terminal yourself and run: job panel --set-password   (then run this again)")
    if not shutil.which("cloudflared"):
        sys.exit(CLOUDFLARED_HELP)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    REMOTE = True
    tunnel = awake = None
    stop, died = threading.Event(), []

    def on_term(*_: Any) -> None:
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, on_term)
    except ValueError:                                    # not the main thread (tests)
        pass
    try:
        print("Starting the tunnel (up to 40 s)...", flush=True)
        try:
            tunnel, url = start_tunnel(srv.server_port)
        except (TunnelError, OSError) as e:
            print(f"Could not start the tunnel: {e}", file=sys.stderr)
            sys.exit(1)
        awake = keep_awake()

        def watch() -> None:
            while not stop.wait(2):
                if tunnel.poll() is not None:
                    died.append(1)
                    srv.shutdown()
                    return

        threading.Thread(target=watch, daemon=True).start()
        print(f"\n  Remote panel: {url}/\n  Open it on your phone and sign in with your panel password. (Ctrl+C to stop)\n")
        print("Warning: anyone who has this address AND the password can read and change your whole board (names, employers, "
              "CVs, letters, tracker). Keep both private. This computer must stay on, awake and online. The address "
              "changes every time you start remote mode, and it stops working when you stop the panel.", flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        if died:
            print("The tunnel stopped. Start remote mode again to get a new address.", file=sys.stderr)
            sys.exit(1)
    finally:
        stop.set()
        stop_process(tunnel)
        stop_process(awake)
        srv.server_close()


def main() -> None:
    global LAN
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765); ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--lan", action="store_true", help="also reachable from your phone on the same wifi (every request needs the link's token)")
    ap.add_argument("--remote", action="store_true",
                    help="reachable from your phone anywhere through a free Cloudflare quick tunnel (needs cloudflared and a password; not with --lan)")
    ap.add_argument("--set-password", action="store_true",
                    help="set the password for --remote (run it yourself in a terminal; it is stored hashed)")
    a = ap.parse_args()
    if a.set_password:
        sys.exit(set_password())
    if a.remote and a.lan:
        ap.error("--remote and --lan cannot be used together")
    if a.remote:
        return run_remote(a.port)
    LAN = a.lan
    srv = ThreadingHTTPServer(("0.0.0.0" if LAN else "127.0.0.1", a.port), Handler)
    if LAN:
        print(f"panel on your wifi: http://{lan_ip()}:{srv.server_port}/?t={TOKEN}  (Ctrl+C to stop)")
        print("Warning: anyone on this wifi who has that link can see your whole board (names, employers, CVs, letters) and change it. "
              "Do not share it. It stops working when you stop the panel. The 'open folder' button only works on this computer.")
    else:
        url = f"http://127.0.0.1:{a.port}/"
        print(f"panel: {url}  (Ctrl+C to stop)")
        if not a.no_open:
            osutil.open_path(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
