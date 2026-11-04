"""Local panel: every application of a candidate on one page, with the buttons that change its status.

  job panel [--port 8765] [--no-open]      → http://127.0.0.1:8765/  (switch candidate in the page)
  job panel --lan                          also on your phone, over the same wifi: prints http://<this computer's IP>:8765/?t=<token>

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
GET  /draft?slug=&key=          a follow-up draft (.md/.txt) that the tracker entry points to, as plain text
POST /status {slug,key,status}  POST /note {slug,key,text}  POST /rescue {slug,key[,track]}  POST /open {slug,key}
POST /add-link {slug,url[,text,title,company]}   a job found by hand (scripts/addlink.py): read, scored, tracked, package built
Every POST must carry the token the page was served with, so another site open in the browser cannot post to it.
With --lan the server listens on every interface of this computer, so EVERY request (pages, files, API) must carry the
token: first as ?t=<token> (then an HttpOnly SameSite=Strict cookie and a redirect that drops it from the URL), compared in
constant time; without it the answer is 403. The token is new on every run and is printed once, in the link. "Open folder"
only works for a client on the computer itself. Anyone on the wifi who has the link can read and change the board.
JOB_SUPPORT_URL (env or .claude/settings.local.json): the floating "Buy me a coffee" button. Defaults to 100 FOUNTS'
Stripe donation link (they build the harness); point it elsewhere, or set it to "" to hide the button.
"""
from __future__ import annotations

import argparse
import hmac
import http.cookies
import json
import mimetypes
import re
import secrets
import socket
import sqlite3
import subprocess
import threading
import urllib.parse
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


def companies(slug: str, days: int = 60) -> list[dict[str, Any]]:
    """Employers worth contacting, from the ads that QUALIFIED in the last `days` (passed the rules: tracked or
    shortlisted; dropped ads do not count). Ranked by the person's order of value: most qualifying ads, then best
    fit, then sponsor lists (exact > likely > possible). Agencies post under their own name; they are flagged."""
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
    rank = {"exact": 0, "likely": 1, "possible": 2}
    return sorted(out, key=lambda g: (-g["ads"], -(g["best"] or 0), rank.get(g["sponsor"], 3)))[:150]


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

    def local_client(self) -> bool:
        return is_local_client(self.client_address[0], self.connection.getsockname()[0])

    def page_data(self, slug: str) -> dict[str, Any]:
        return data(slug) | {"local": self.local_client(), "lan": LAN}

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
        if LAN and not self.lan_gate(u):
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
            return self.send(200, f.read_bytes(), text_type(f))
        if slug not in cands:
            return self.send(404, b"unknown candidate")
        if u.path == "/":
            page = PAGE.read_text(encoding="utf-8").replace("__DATA__", json.dumps(self.page_data(slug), ensure_ascii=False).replace("</", "<\\/"))
            return self.send(200, page.replace("__TOKEN__", TOKEN).encode())
        if u.path == "/api/data":
            return self.json(self.page_data(slug))
        if u.path == "/api/job":
            return self.json(detail(slug, q.get("key", [""])[0]))
        if u.path == "/draft":
            app = next((a for a in load(slug) if a["key"] == q.get("key", [""])[0]), None)
            f = draft_file(slug, app) if app else None
            return self.send(200, f.read_bytes(), "text/plain; charset=utf-8") if f else self.send(404, b"not found")
        self.send(404, b"not found")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if 0 < length <= MAX_BODY else b""      # read it before any answer: a refusal must not reset the connection
        if LAN:
            allowed = token_ok(self.cookie_token()) and token_ok(self.headers.get("X-Panel-Token"))
        else:
            allowed = token_ok(self.headers.get("X-Panel-Token")) and self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")
        if not allowed:
            return self.send(403, b"forbidden")
        if length > MAX_BODY:
            return self.send(413, b"too large")
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
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
            if self.path == "/open":
                if not self.local_client():             # it would open a folder on the computer, not on the phone
                    return self.json({"ok": False, "error": "Opening the folder only works on the computer that runs the panel."}, 403)
                return self.json(open_folder(slug, key))
        except SystemExit as e:                       # tracker refusals (limits, unknown key) come back as text
            return self.json({"ok": False, "error": str(e)}, 409)
        self.send(404, b"not found")


def text_type(f: Path) -> str:
    """Drafts and notes (.md/.txt) open in the browser as plain text instead of downloading."""
    if f.suffix.lower() in (".md", ".txt"):
        return "text/plain; charset=utf-8"
    return mimetypes.guess_type(f.name)[0] or "application/octet-stream"


def main() -> None:
    global LAN
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765); ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--lan", action="store_true", help="also reachable from your phone on the same wifi (every request needs the link's token)")
    a = ap.parse_args()
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
