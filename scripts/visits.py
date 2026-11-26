"""Visits: employers to walk into with a CV, on a map, with one funnel per company.

  job visits <slug> cities [--json]                          cities that have qualifying ads (companies and ads each)
  job visits <slug> list [--city Perth] [--track t ...] [--json]   employers of one city, ranked, with place and visit stage
  job visits <slug> locate [--city Perth] [--limit 40]       find the employers' offices on OpenStreetMap (Nominatim)
  job visits <slug> address "Company" "1 St Georges Tce, Perth WA" --city Perth      exact address, geocoded
  job visits <slug> coords "Company" -31.95 115.86 --city Perth [--address "..."]    exact point, no geocoding
  job visits <slug> set "Company" visited --city Perth [--note "left it at reception"]   move it along the funnel
  job visits <slug> import offices.json --city Perth         places from a file (list of {company, address, lat, lon, ...})

The list is the panel's Companies view for one city: ads that QUALIFIED in the last 60 days (a tracker entry, or a
'shortlisted' verdict in jobs.db), grouped by employer. What the person records is kept apart from the ads, in two files
of the candidate's folder, written whole through a temporary file and os.replace (a crash cannot leave half a file) under
one lock: a thread lock (the panel serves several requests at once) plus an inter-process file lock on
candidates/<slug>/.visits.lock (the CLI and the panel server are different processes; fcntl.flock, msvcrt.locking on
Windows). A file that is not JSON is set aside as <name>.bad-<timestamp> (never overwritten, never deleted); one that
cannot be READ (permissions) is reported and left alone; records of the wrong shape are dropped or repaired on load:
- visits.json  per "<employer>|<city>": stage, note, contact and the history of stages (like the tracker's).
- places.json  per "<employer>|<city>": address, lat, lon, how sure we are (exact | approx), zone, note, where it came from.

Stages: todo (the default) > visited (went, left the CV) > received (someone received me) | not_received > interview >
offer, or skip (not going). The funnel counts what was REACHED (stage or history), so a company that went on to an
interview still counts as visited and received. Not received is a visit that did not lead to a conversation.

Geocoding is Nominatim's public service: free, no key, so no credits to burn (the harness uses nothing paid). Its usage
policy asks for a real User-Agent (the project, never a person: no email, no name) and at most one request per second;
both are enforced here across processes (last request time and a query cache in ~/.cache/job-harness/nominatim.json,
under a file lock; positive answers are kept 180 days, "no match" 14 days, errors are never cached). Any network error is an answer (None, nothing stored), never an exception: the page
and the daily run must not break because a map service is down. Company-name searches are only a guess ("approx"); an
address typed by the person is "exact". Python standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from common import HARNESS_VERSION, cand_dir, now_iso, read_json, today

try:                              # POSIX
    import fcntl
except ImportError:               # Windows
    fcntl = None                  # type: ignore[assignment]
try:
    import msvcrt
except ImportError:
    msvcrt = None                 # type: ignore[assignment]

STAGES = ("todo", "visited", "received", "not_received", "interview", "offer", "skip")
LABELS = {"todo": "To visit", "visited": "Went, left my CV", "received": "Someone received me",
          "not_received": "Nobody received me", "interview": "Interview", "offer": "Offer", "skip": "Not going"}
# what each funnel step counts: the company's stage, or any stage in its history, is one of these
FUNNEL = (("Visited", {"visited", "received", "not_received", "interview", "offer"}),
          ("Received", {"received", "interview", "offer"}),
          ("Interview", {"interview", "offer"}),
          ("Offer", {"offer"}))
APPLIED = {"submitted", "applied", "interview", "offer", "hired"}      # tracker statuses that mean the application left
CITIES = ("Perth", "Adelaide", "Sydney", "Melbourne", "Brisbane", "Canberra", "Hobart", "Darwin", "Gold Coast",
          "Sunshine Coast", "Newcastle", "Wollongong", "Geelong", "Townsville", "Cairns", "Toowoomba", "Ballarat",
          "Bendigo", "Launceston", "Mackay", "Rockhampton", "Bunbury", "Mandurah", "Kalgoorlie", "Karratha",
          "Port Hedland", "Geraldton", "Albany")
CITY_RX = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(c) for c in sorted(CITIES, key=len, reverse=True)) + r")(?![A-Za-z])",
                     re.IGNORECASE)
AGENCY_RX = re.compile(r"(?i)recruit|talent|staff|personnel|people(bank)?\b|hays|randstad|hudson|robert half|"
                       r"chandler macleod|paxus|halcyon|sharp ?& ?carter|michael page|adecco|manpower|\bhire")
MAX_TEXT = 2000                  # notes and contacts: a few lines, not a document
MAX_ADDRESS = 300
NOMINATIM = "https://nominatim.openstreetmap.org/search"
MIN_INTERVAL = 1.1               # seconds between two Nominatim requests (its policy is one per second)
GEO_TIMEOUT = 10
GEO_TTL_HIT = 180 * 86400        # a found place is kept 180 days in the query cache
GEO_TTL_MISS = 14 * 86400        # "no match" is kept 14 days
GEO_CACHE_MAX = 5000             # entries kept in the query cache (the oldest go first)

LOCK = threading.Lock()          # visits.json and places.json are rewritten whole: one read-modify-write at a time
_GEO_LOCK = threading.Lock()     # serialises geocoding threads inside one process
_held = threading.local()        # candidate folders this thread already holds the lock of (re-entrant)
_mem_geo: dict[str, Any] = {}    # fallback state when the cache folder cannot be used


class StoreError(OSError):
    """A file of the candidate's folder cannot be read or set aside (permissions, disk). Not bad content: the file is
    left exactly as it is."""


# ---------------------------------------------------------------------------------------------------------- files

def _empty(kind: str) -> dict[str, Any]:
    return {"version": 1, kind: {}}


def _file(slug: str, name: str) -> Path:
    return cand_dir(slug) / name


@contextlib.contextmanager
def _flock(path: Path, strict: bool = True):
    """An exclusive inter-process lock on a sibling lock file (fcntl.flock, or msvcrt.locking on Windows). Yields True
    when held. With strict False a lock file that cannot be opened yields False instead of raising."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(path, "a+b")
    except OSError:
        if strict:
            raise
        yield False
        return
    with fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)      # blocks about 10 s, then raises: try again
                    break
                except OSError:
                    time.sleep(0.05)
        try:
            yield True
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def _locked(slug: str):
    """Every read-modify-write of visits.json / places.json runs inside this: the thread lock (the panel serves several
    requests at once) and the file lock candidates/<slug>/.visits.lock (the CLI is another process). Re-entrant."""
    folder = cand_dir(slug)
    held = getattr(_held, "dirs", None)
    if held is None:
        held = _held.dirs = {}
    if held.get(folder):
        held[folder] += 1
        try:
            yield
        finally:
            held[folder] -= 1
        return
    with LOCK, _flock(folder / ".visits.lock"):
        held[folder] = 1
        try:
            yield
        finally:
            held.pop(folder, None)


def _backup_name(p: Path) -> Path:
    """A name that does not exist yet (<name>.bad-<timestamp>), so a second corruption never overwrites the first."""
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    n = 0
    while True:
        cand = p.with_name(f"{p.name}.bad-{stamp}" + (f"-{n}" if n else ""))
        if not cand.exists():
            return cand
        n += 1


def _str(v: Any) -> str:
    return "" if v is None else v if isinstance(v, str) else str(v)


def _coord(v: Any, limit: float) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and -limit <= x <= limit else None


def _clean_visit(rec: Any) -> dict[str, Any] | None:
    """A visit record with the right shape, or None when it is not a record at all."""
    if not isinstance(rec, dict):
        return None
    out = dict(rec)
    for k in ("company", "city", "note", "contact", "updated"):
        if k in out and not isinstance(out[k], str):
            out[k] = _str(out[k])
    if "stage" in out and out["stage"] not in STAGES:
        out["stage"] = "todo"
    if "history" in out:
        hist = out["history"] if isinstance(out["history"], list) else []
        out["history"] = [{**h, "date": _str(h.get("date")), "note": _str(h.get("note"))}
                          for h in hist if isinstance(h, dict) and h.get("stage") in STAGES]
    return out


def _clean_place(rec: Any) -> dict[str, Any] | None:
    if not isinstance(rec, dict):
        return None
    out = dict(rec)
    for k in ("company", "city", "address", "zone", "note", "source", "updated"):
        if k in out and not isinstance(out[k], str):
            out[k] = _str(out[k])
    if "lat" in out or "lon" in out:
        lat, lon = _coord(out.get("lat"), 90), _coord(out.get("lon"), 180)
        out["lat"], out["lon"] = (lat, lon) if lat is not None and lon is not None else (None, None)
    if "confidence" in out and out["confidence"] not in ("exact", "approx"):
        out["confidence"] = "approx"
    return out


_CLEANERS = {"companies": _clean_visit, "places": _clean_place}


def _load(slug: str, name: str, kind: str) -> dict[str, Any]:
    """The file's content, under the lock. Bad content (not JSON, wrong top-level shape) sets the file aside as
    <name>.bad-<timestamp> and starts empty; records of the wrong shape are dropped or repaired (the original is kept as
    a .bad-<timestamp> copy first). A file that cannot be read at all (OSError, e.g. permissions) is NOT touched: it
    raises StoreError."""
    p = _file(slug, name)
    with _locked(slug):
        try:
            raw = p.read_bytes()
        except FileNotFoundError:
            return _empty(kind)
        except OSError as e:
            raise StoreError(f"cannot read {p}: {e}") from e
        try:
            data = json.loads(raw.decode("utf-8"))
            if not (isinstance(data, dict) and isinstance(data.get(kind), dict)):
                raise ValueError("unexpected shape")
        except (ValueError, RecursionError):
            try:
                os.replace(p, _backup_name(p))
            except OSError as e:
                raise StoreError(f"{p} is not valid JSON and could not be set aside: {e}") from e
            return _empty(kind)
        clean = {}
        for k, rec in data[kind].items():
            c = _CLEANERS[kind](rec)
            if c is not None:
                clean[str(k)] = c
        if clean != data[kind]:
            try:
                _backup_name(p).write_bytes(raw)
                data[kind] = clean
                _write(p, data)
            except OSError as e:
                raise StoreError(f"cannot repair {p}: {e}") from e
        return data


def _write(path: Path, data: dict[str, Any]) -> None:
    """Atomic: write next to the file, then os.replace, so a crash leaves the old file or the new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _save(slug: str, name: str, data: dict[str, Any]) -> None:
    _write(_file(slug, name), data)


# ---------------------------------------------------------------------------------------------------------- names

def city_of(location: str) -> str:
    """The first known Australian city named in an ad's location ('Perth WA', 'Osborne Park, Perth', 'Greater
    Adelaide'), whole words only, any case; '' when none ('Remote', 'Western Australia')."""
    m = CITY_RX.search(location or "")
    if not m:
        return ""
    return next(c for c in CITIES if c.lower() == m.group(1).lower())


def ckey(company: str) -> str:
    """The employer's identity, the same one the panel's Companies view groups by (legal suffixes set aside)."""
    from sponsors import core, normalize
    return core(normalize(company)) or (company or "").strip().upper()


def key_of(company: str, city: str) -> str:
    return f"{ckey(company)}|{city.strip().lower()}"


# ---------------------------------------------------------------------------------------------------------- ads

def _qualifying(slug: str, days: int) -> list[dict[str, Any]]:
    """Ads of the last `days` that qualified (tracked, or shortlisted), each with its city, track, fit and whether the
    person applied. Track and fit come from the tracker when it has the ad, else from jobs.db."""
    from jobdb import connect
    from tracker import load
    if not (cand_dir(slug) / "jobs.db").exists():
        return []
    since = (date.today() - timedelta(days=days)).isoformat()
    with connect(slug, readonly=True) as con:
        rows = con.execute("SELECT key, company, title, location, verdict, fit, last_seen, url, platform, track FROM jobs "
                           "WHERE last_seen >= ? AND company IS NOT NULL AND company != ''", (since,)).fetchall()
    apps = {a["key"]: a for a in load(slug)}
    out = []
    for r in rows:
        a = apps.get(r["key"])
        if a is None and r["verdict"] != "shortlisted":
            continue
        a = a or {}
        reached = {a.get("status")} | {h.get("status") for h in a.get("history", [])}
        fit = a.get("fit") if a.get("fit") is not None else r["fit"]
        out.append({"company": r["company"], "city": city_of(r["location"] or ""), "title": r["title"] or "",
                    "url": r["url"] or "", "fit": fit, "track": a.get("track") or r["track"] or "",
                    "seen": r["last_seen"] or "", "platform": r["platform"] or "", "applied": bool(reached & APPLIED)})
    return out


def cities(slug: str, days: int = 60) -> list[dict[str, Any]]:
    """Cities with qualifying ads: [{'city', 'companies', 'ads'}], most ads first. Ads without a known city are left out."""
    ads: dict[str, int] = {}
    cos: dict[str, set[str]] = {}
    for j in _qualifying(slug, days):
        if j["city"]:
            ads[j["city"]] = ads.get(j["city"], 0) + 1
            cos.setdefault(j["city"], set()).add(ckey(j["company"]))
    return [{"city": c, "companies": len(cos[c]), "ads": n} for c, n in sorted(ads.items(), key=lambda x: (-x[1], x[0]))]


def _track_order(slug: str) -> list[str]:
    return [t.get("id") for t in read_json(_file(slug, "targets.json"), {}).get("tracks", []) if t.get("id")]


def _visit_view(rec: dict[str, Any] | None) -> dict[str, Any]:
    r = rec or {}
    return {"stage": r.get("stage") or "todo", "note": r.get("note") or "", "contact": r.get("contact") or "",
            "updated": r.get("updated") or "", "history": list(r.get("history") or [])}


def _place_view(rec: dict[str, Any] | None) -> dict[str, Any] | None:
    if not rec:
        return None
    return {k: rec.get(k, "" if k in ("address", "zone", "note") else None)
            for k in ("address", "lat", "lon", "confidence", "zone", "note", "source")}


def places(slug: str, city: str, tracks: list[str] | None = None, days: int = 60) -> dict[str, Any]:
    """The employers of one city, best first, each with its ads, its place on the map and its visit record.

    `tracks` keeps only the ads of those tracks (an employer with none left disappears) and ads, best, avg and priority
    are worked out on what is left. The funnel counts the companies shown: To visit = those not skipped; the other four
    steps are reached-semantics (stage or history). `missing` counts the ones without coordinates."""
    from panel import company_priority
    from sponsors import lookup
    city = (city or "").strip()
    if not city:
        found = cities(slug, days)
        city = found[0]["city"] if found else ""
    want = city.lower()
    mine = [j for j in _qualifying(slug, days) if j["city"] and j["city"].lower() == want]
    order = _track_order(slug)
    present = {j["track"] for j in mine if j["track"]}
    track_ids = [t for t in order if t in present] + sorted(present - set(order))
    if tracks:
        mine = [j for j in mine if j["track"] in set(tracks)]
    groups: dict[str, dict[str, Any]] = {}
    for j in mine:
        g = groups.setdefault(ckey(j["company"]), {"company": j["company"], "jobs": []})
        g["jobs"].append(j)
    err = ""
    try:
        visits = _load(slug, "visits.json", "companies")["companies"]
        spots = _load(slug, "places.json", "places")["places"]
    except StoreError as e:                      # unreadable (permissions): show the ads, say why the records are missing
        visits, spots, err = {}, {}, str(e)
    sponsors = {k: lookup(g["company"]) for k, g in groups.items()}
    has_sp = any(sponsors.values())
    out = []
    for k, g in groups.items():
        jobs = sorted(g["jobs"], key=lambda j: (j["fit"] is None, -(j["fit"] or 0), j["title"]))
        fits = [j["fit"] for j in jobs if j["fit"] is not None]
        best, avg = (max(fits), round(sum(fits) / len(fits))) if fits else (None, None)
        by_track: dict[str, dict[str, Any]] = {}
        for j in jobs:
            if j["track"]:
                t = by_track.setdefault(j["track"], {"ads": 0, "best": None})
                t["ads"] += 1
                if j["fit"] is not None and (t["best"] is None or j["fit"] > t["best"]):
                    t["best"] = j["fit"]
        sp = sponsors[k]
        key = f"{k}|{want}"
        out.append({"key": key, "company": g["company"], "agency": bool(AGENCY_RX.search(g["company"])),
                    "ads": len(jobs), "best": best, "avg": avg,
                    "priority": company_priority(len(jobs), avg, sp["match"] if sp else None, has_sp),
                    "by_track": by_track,
                    "jobs": [{x: j[x] for x in ("title", "url", "fit", "track", "seen", "platform", "applied")} for j in jobs],
                    "place": _place_view(spots.get(key)), "visit": _visit_view(visits.get(key))})
    out.sort(key=lambda c: (-c["priority"], -(c["best"] or 0), -c["ads"], c["company"]))
    shown = [c for c in out if c["visit"]["stage"] != "skip"]
    funnel: list[list[Any]] = [["To visit", len(shown)]]
    for label, stages in FUNNEL:
        funnel.append([label, sum(1 for c in shown if _reached(c["visit"], stages))])
    res = {"city": city, "tracks": track_ids, "companies": out, "funnel": funnel,
           "missing": sum(1 for c in out if not c["place"] or c["place"]["lat"] is None or c["place"]["lon"] is None)}
    if err:
        res["error"] = err
    return res


def _reached(visit: dict[str, Any], stages: set[str]) -> bool:
    return visit["stage"] in stages or any(h.get("stage") in stages for h in visit["history"])


# ---------------------------------------------------------------------------------------------------------- visit record

def _text(value: Any, cap: int) -> str:
    return str(value or "").strip()[:cap]


def set_stage(slug: str, company: str, city: str, stage: str, note: str = "") -> dict[str, Any]:
    """Move one employer along the funnel and append it to the history. The note belongs to this step (history); the
    employer's own note and contact are set_details. The same stage again without a note is not added twice (a double
    click)."""
    if stage not in STAGES:
        return {"ok": False, "error": f"stage must be one of {', '.join(STAGES)}", "visit": _visit_view(None)}
    if not (company or "").strip() or not (city or "").strip():
        return {"ok": False, "error": "company and city are required", "visit": _visit_view(None)}
    key, note = key_of(company, city), _text(note, MAX_TEXT)
    with _locked(slug):
        data = _load(slug, "visits.json", "companies")
        rec = data["companies"].setdefault(key, {"company": company.strip(), "city": city.strip(), "stage": "todo",
                                                  "note": "", "contact": "", "updated": "", "history": []})
        if rec.get("stage") != stage or note or not rec["history"]:
            rec["history"].append({"date": now_iso(), "stage": stage, "note": note})
        rec["stage"], rec["updated"] = stage, now_iso()
        _save(slug, "visits.json", data)
    return {"ok": True, "visit": _visit_view(rec)}


def set_details(slug: str, company: str, city: str, note: str | None = None, contact: str | None = None) -> dict[str, Any]:
    """The person's own note and contact for an employer (None leaves a field as it is; each is cut at 2000 characters).
    Not a stage change: no history entry."""
    if not (company or "").strip() or not (city or "").strip():
        return {"ok": False, "error": "company and city are required", "visit": _visit_view(None)}
    key = key_of(company, city)
    with _locked(slug):
        data = _load(slug, "visits.json", "companies")
        rec = data["companies"].setdefault(key, {"company": company.strip(), "city": city.strip(), "stage": "todo",
                                                  "note": "", "contact": "", "updated": "", "history": []})
        if note is not None:
            rec["note"] = _text(note, MAX_TEXT)
        if contact is not None:
            rec["contact"] = _text(contact, MAX_TEXT)
        rec["updated"] = now_iso()
        _save(slug, "visits.json", data)
    return {"ok": True, "visit": _visit_view(rec)}


# ---------------------------------------------------------------------------------------------------------- geocoding

def _geo_dir() -> Path:
    """Where the Nominatim state lives, shared by every process of this user (JOB_HARNESS_CACHE_DIR overrides it)."""
    env = os.environ.get("JOB_HARNESS_CACHE_DIR")
    return Path(env).expanduser() if env else Path.home() / ".cache" / "job-harness"


def _geo_read(path: Path) -> dict[str, Any]:
    """The shared state {'last': epoch of the last request, 'cache': {query: {'t', 'hit'}}}; anything unreadable or
    misshapen is just a cold cache."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        data = None
    data = data if isinstance(data, dict) else {}
    last = data.get("last")
    cache = {}
    for q, e in (data.get("cache") if isinstance(data.get("cache"), dict) else {}).items():
        if isinstance(e, dict) and isinstance(e.get("t"), (int, float)) and not isinstance(e.get("t"), bool):
            hit = e.get("hit")
            if hit is None or (isinstance(hit, dict) and _coord(hit.get("lat"), 90) is not None
                               and _coord(hit.get("lon"), 180) is not None):
                cache[q] = {"t": float(e["t"]), "hit": hit}
    return {"version": 1, "last": float(last) if isinstance(last, (int, float)) and not isinstance(last, bool) else 0.0,
            "cache": cache}


def _geo_save(path: Path, state: dict[str, Any]) -> None:
    cache = state["cache"]
    if len(cache) > GEO_CACHE_MAX:
        state["cache"] = dict(sorted(cache.items(), key=lambda kv: kv[1]["t"])[-GEO_CACHE_MAX:])
    try:
        _write(path, state)
    except OSError:
        pass                                      # a cache that cannot be saved is still just a cache


def _geo_fetch(query: str) -> tuple[bool, dict[str, Any] | None]:
    """(answered, hit): answered False on any error (nothing to cache); True with hit None for 'no match'."""
    url = NOMINATIM + "?" + urllib.parse.urlencode({"format": "jsonv2", "limit": 1, "countrycodes": "au", "q": query})
    req = urllib.request.Request(url, headers={
        "User-Agent": f"job-harness/{HARNESS_VERSION} (+https://github.com/100FOUNTS/job-harness)",
        "Accept-Language": "en-AU,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=GEO_TIMEOUT) as r:
            hits = json.loads(r.read().decode("utf-8", errors="ignore"))
        if not isinstance(hits, list):
            return False, None
        if not hits:
            return True, None
        return True, {"lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]), "display": str(hits[0].get("display_name") or "")}
    except Exception:
        return False, None


def geocode(query: str) -> dict[str, Any] | None:
    """{'lat', 'lon', 'display'} for the best Nominatim match in Australia, or None (no match, no network, any error).
    Answers come from a persistent query cache when they can (found: 180 days, no match: 14 days; errors are never
    cached). Real requests are at most one per MIN_INTERVAL seconds across ALL processes (the last request time lives in
    the shared state file, under a file lock); the User-Agent names the project, never a person."""
    query = (query or "").strip()
    if not query:
        return None
    qkey = " ".join(query.lower().split())
    path = _geo_dir() / "nominatim.json"
    with _GEO_LOCK, _flock(_geo_dir() / "nominatim.lock", strict=False) as shared:
        state = _geo_read(path) if shared else _mem_geo.setdefault("state", {"version": 1, "last": 0.0, "cache": {}})
        now = time.time()
        e = state["cache"].get(qkey)
        if e and 0 <= now - e["t"] < (GEO_TTL_HIT if e["hit"] else GEO_TTL_MISS):
            return dict(e["hit"]) if e["hit"] else None
        wait = MIN_INTERVAL - (now - state["last"])
        if wait > 0:
            time.sleep(min(wait, MIN_INTERVAL))   # (a clock set back must not mean a long sleep)
        try:
            answered, hit = _geo_fetch(query)
        finally:
            state["last"] = time.time()
        if answered:
            state["cache"][qkey] = {"t": state["last"], "hit": hit}
        if shared:
            _geo_save(path, state)
        return hit


def _store_place(slug: str, company: str, city: str, **fields: Any) -> dict[str, Any]:
    key = key_of(company, city)
    with _locked(slug):
        data = _load(slug, "places.json", "places")
        rec = data["places"].setdefault(key, {"company": company.strip(), "city": city.strip(), "address": "", "lat": None,
                                              "lon": None, "source": "", "confidence": "approx", "zone": "", "note": ""})
        rec.update(fields)
        rec["updated"] = today()
        _save(slug, "places.json", data)
    return _place_view(rec) or {}


MAX_KM_FROM_CITY = 80        # a metro area plus its industrial outskirts; farther than this a name match is another place


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


def locate(slug: str, city: str, limit: int = 40) -> dict[str, Any]:
    """Look up the offices of the city's employers that have no coordinates yet (at most `limit`, best first): the
    address when there is one, else "<company>, <city>, Australia". What is found is stored as source 'nominatim',
    confidence 'approx' (a company name is a guess; fix it with set_address). Returns {'found': n, 'missing': [names]}."""
    found, missing = 0, []
    todo = [c for c in places(slug, city)["companies"]
            if not c["place"] or c["place"]["lat"] is None or c["place"]["lon"] is None][:max(0, limit)]
    centre = geocode(f"{city}, Australia") if todo else None   # a name search can land in another town: keep hits near the city
    for c in todo:
        have = c["place"] or {}
        hit = geocode(have["address"] if have.get("address") else f"{c['company']}, {city}, Australia")
        if not hit or (centre and km(centre["lat"], centre["lon"], hit["lat"], hit["lon"]) > MAX_KM_FROM_CITY):
            missing.append(c["company"])
            continue
        _store_place(slug, c["company"], city, lat=hit["lat"], lon=hit["lon"], source=have.get("source") or "nominatim",
                     confidence=have.get("confidence") or "approx",
                     address=have.get("address") or hit.get("display", "")[:MAX_ADDRESS])
        found += 1
    return {"found": found, "missing": missing}


def set_address(slug: str, company: str, city: str, address: str) -> dict[str, Any]:
    """The exact address, typed by the person: geocoded ("Australia" added unless it is there) and stored as source
    'manual', confidence 'exact'. When the lookup fails the address is still stored, without coordinates, and the answer is
    ok False with the reason (the person can pin the point with set_coords)."""
    address = _text(address, MAX_ADDRESS)
    if not address or not (company or "").strip() or not (city or "").strip():
        return {"ok": False, "error": "company, city and address are required", "place": None}
    query = address if re.search(r"\baustralia\b", address, re.I) else f"{address}, Australia"
    hit = geocode(query)
    if hit:
        return {"ok": True, "place": _store_place(slug, company, city, address=address, lat=hit["lat"], lon=hit["lon"],
                                                   source="manual", confidence="exact")}
    place = _store_place(slug, company, city, address=address, lat=None, lon=None, source="manual", confidence="approx")
    return {"ok": False, "error": "Address saved, but it could not be found on the map (no match, or the map service is "
                                  "not reachable). Check it, or set the point by hand.", "place": place}


def set_coords(slug: str, company: str, city: str, lat: Any, lon: Any, address: str = "") -> dict[str, Any]:
    """A point chosen by the person (a tap on the map): stored as source 'manual', confidence 'exact'."""
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return {"ok": False, "error": "lat and lon must be numbers", "place": None}
    if not (-90 <= la <= 90 and -180 <= lo <= 180) or la != la or lo != lo:
        return {"ok": False, "error": "lat must be within -90..90 and lon within -180..180", "place": None}
    if not (company or "").strip() or not (city or "").strip():
        return {"ok": False, "error": "company and city are required", "place": None}
    fields: dict[str, Any] = {"lat": la, "lon": lo, "source": "manual", "confidence": "exact"}
    if address:
        fields["address"] = _text(address, MAX_ADDRESS)
    return {"ok": True, "place": _store_place(slug, company, city, **fields)}


def import_places(slug: str, city: str, path: str | Path) -> dict[str, Any]:
    """Places from a JSON file: a list of {company | name, address, lat, lon, zone, note, confidence}. Entries without
    valid coordinates keep their address only. With coordinates the default confidence is 'exact' (the person supplied
    them); source is 'import'."""
    try:
        items = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"imported": 0, "error": f"cannot read {path}: {e}"}
    if not isinstance(items, list):
        return {"imported": 0, "error": "the file must hold a JSON list"}
    n = 0
    for it in items:
        name = (it.get("company") or it.get("name") or "").strip() if isinstance(it, dict) else ""
        if not name:
            continue
        try:
            lat, lon = float(it["lat"]), float(it["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            lat = lon = None
        conf = it.get("confidence") if it.get("confidence") in ("exact", "approx") else ("exact" if lat is not None else "approx")
        _store_place(slug, name, city, lat=lat, lon=lon, source="import", confidence=conf, address=_text(it.get("address"), MAX_ADDRESS),
                     zone=_text(it.get("zone"), 100), note=_text(it.get("note"), MAX_TEXT))
        n += 1
    return {"imported": n}


# ---------------------------------------------------------------------------------------------------------- CLI

def _default_city(slug: str, city: str | None) -> str:
    if city:
        return city
    found = cities(slug)
    if not found:
        raise SystemExit("No city has qualifying ads yet; pass --city.")
    return found[0]["city"]


def _print_list(res: dict[str, Any]) -> None:
    print(f"{res['city']}: " + ", ".join(f"{k} {n}" for k, n in res["funnel"]) + f"  ({res['missing']} without a location)")
    for i, c in enumerate(res["companies"], 1):
        pl = c["place"]
        where = (pl["address"] or "located") if pl and pl["lat"] is not None else "no location"
        flag = " [agency]" if c["agency"] else ""
        print(f"{i:>3}. {c['company']}{flag}  priority {c['priority']}  ads {c['ads']}  best {c['best']}  "
              f"{LABELS[c['visit']['stage']]}  | {where}")


def main() -> None:
    try:
        _run()
    except StoreError as e:
        raise SystemExit(f"error: {e}")


def _run() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cities"); c.add_argument("--json", action="store_true")
    ls = sub.add_parser("list"); ls.add_argument("--city"); ls.add_argument("--track", nargs="+", action="extend")
    ls.add_argument("--json", action="store_true")
    lo = sub.add_parser("locate"); lo.add_argument("--city"); lo.add_argument("--limit", type=int, default=40)
    ad = sub.add_parser("address"); ad.add_argument("company"); ad.add_argument("address"); ad.add_argument("--city")
    co = sub.add_parser("coords"); co.add_argument("company"); co.add_argument("lat"); co.add_argument("lon")
    co.add_argument("--city"); co.add_argument("--address", default="")
    st = sub.add_parser("set"); st.add_argument("company"); st.add_argument("stage", choices=STAGES)
    st.add_argument("--city"); st.add_argument("--note", default="")
    im = sub.add_parser("import"); im.add_argument("file"); im.add_argument("--city")
    a = ap.parse_args()
    cand_dir(a.slug)
    if a.cmd == "cities":
        res = cities(a.slug)
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print("\n".join(f"{r['city']:<16}{r['companies']:>4} companies  {r['ads']:>4} ads" for r in res) or "No city has qualifying ads yet.")
        return
    city = _default_city(a.slug, a.city)
    if a.cmd == "list":
        res = places(a.slug, city, a.track)
        print(json.dumps(res, ensure_ascii=False, indent=2)) if a.json else _print_list(res)
        return
    if a.cmd == "locate":
        res = locate(a.slug, city, a.limit)
    elif a.cmd == "address":
        res = set_address(a.slug, a.company, city, a.address)
    elif a.cmd == "coords":
        res = set_coords(a.slug, a.company, city, a.lat, a.lon, a.address)
    elif a.cmd == "set":
        res = set_stage(a.slug, a.company, city, a.stage, a.note)
    else:
        res = import_places(a.slug, city, a.file)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res.get("ok") is False or res.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
