"""Local panel: every application of a candidate on one page, with the buttons that change its status.

  job panel [--port 8765] [--no-open]      → http://127.0.0.1:8765/  (switch candidate in the page)

Python standard library only, bound to 127.0.0.1 (nothing outside this Mac can reach it), no accounts, no database of
its own: it reads tracker.json, the daily packages (items.json) and jobs.db, and writes through the tracker's own
functions (set_status, set_note), the same rules as `job track` (limits, history). Ideas from Huntr/Teal (board, notes,
drag between columns), career-ops web (Today), Jobscan and LinkedIn Job Match (why a job fits or was dropped).

Views: Tablero (board), Embudo (funnel and calibration), Empresas (who publishes most, best fits, sponsor lists: the
employers worth contacting in person), Descartados (dropped ads with the rule that dropped them).
GET  /?slug=<s>                 the page, with the board data embedded
GET  /api/job?slug=&key=        one application in full: description, keyword coverage, documents, history, notes
GET  /files/<slug>/<path>       a file from the candidate's package folder (CV, letter)
POST /status {slug,key,status}  POST /note {slug,key,text}  POST /rescue {slug,key}  POST /open {slug,key}
Every POST must carry the token the page was served with, so another site open in the browser cannot post to it.
JOB_SUPPORT_URL (env or .claude/settings.local.json): a "Buy me a coffee" link, e.g. a Stripe Payment Link where the
customer chooses the amount; the floating button only shows when it is set.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import secrets
import sqlite3
import subprocess
import urllib.parse
from datetime import date, datetime, timedelta
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import osutil
from common import cand_dir, list_candidates, read_json, setting
from status import summary
from tracker import OUTCOMES, PENDING, SENT, calibrate, followups, load, set_note, set_status

TOKEN = secrets.token_urlsafe(24)
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
            "by_platform": cal["by_platform"], "avg_wait": round(sum(waits) / len(waits)) if waits else None}


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
                     "new": a["date"] == today})
    pending_answers = len(read_json(cand_dir(slug) / "pending_questions.json", {"questions": []}).get("questions", []))
    return {"slug": slug, "name": read_json(cand_dir(slug) / "intake.json")["name"], "apps": apps,
            "state": summary(slug)["state"],
            "today": {"to_apply": sum(a["col"] == "todo" for a in apps), "new": sum(a["new"] for a in apps),
                      "closing_soon": [a["key"] for a in apps if a["col"] == "todo" and a["closes"]
                                       and today <= a["closes"] <= soon],
                      "followups": [f for f in followups(slug) if f["action"] != "waiting (already chased)"],
                      "pending_answers": pending_answers},
            "funnel": funnel(slug, all_apps), "dropped": dropped(slug), "companies": companies(slug),
            "candidates": list_candidates(), "support_url": setting("JOB_SUPPORT_URL", ""),
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
            "tailored": bool(d and (d / "tailored").is_dir())}


def rescue(slug: str, key: str) -> dict[str, Any]:
    """An ad the rules dropped that the person wants: track it and build its package now (job prepare --only)."""
    from tracker import add
    con = sqlite3.connect(f"file:{cand_dir(slug) / 'jobs.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
    con.close()
    if not row:
        return {"ok": False, "error": "That ad is not in the job memory."}
    targets = read_json(cand_dir(slug) / "targets.json")
    track = row["track"] or next((t["id"] for t in targets["tracks"] if t.get("primary")), targets["tracks"][0]["id"])
    if key not in {a["key"] for a in load(slug)}:
        add(slug, {"key": key, "title": row["title"], "company": row["company"], "url": row["url"], "platform": row["platform"],
                   "track": track, "location": row["location"] or "", "summary": "rescued from the panel"})
        set_status(slug, key, "skipped", reason="rescued: waiting for its package")
    r = subprocess.run([*osutil.python(), str(Path(__file__).parent / "prepare.py"), slug, "--max", "99", "--requeue", key, "--only"],
                       capture_output=True, encoding="utf-8", timeout=300)
    return {"ok": r.returncode == 0, "error": r.stderr[-300:] if r.returncode else ""}


def open_folder(slug: str, key: str) -> dict[str, Any]:
    app = next((a for a in load(slug) if a["key"] == key), None)
    d = job_dir(slug, app, package_items(slug).get(key)) if app else None
    if not d:
        return {"ok": False, "error": "This application has no package folder."}
    osutil.open_path(d)          # the package folder: the CV and letter to upload
    return {"ok": True, "path": str(d)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a: Any) -> None:  # quiet
        pass

    def send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj: Any, code: int = 200) -> None:
        self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        cands = list_candidates()
        slug = q.get("slug", [cands[0] if cands else ""])[0]
        if u.path.startswith("/files/"):
            rel = Path(urllib.parse.unquote(u.path[len("/files/"):]))
            if not rel.parts or rel.parts[0] not in cands:
                return self.send(404, b"not found")
            root = pkg_root(rel.parts[0]).resolve()
            f = (root / Path(*rel.parts[1:])).resolve()
            if root not in f.parents or not f.is_file():
                return self.send(404, b"not found")
            return self.send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        if slug not in cands:
            return self.send(404, b"unknown candidate")
        if u.path == "/":
            page = PAGE.read_text(encoding="utf-8").replace("__DATA__", json.dumps(data(slug), ensure_ascii=False).replace("</", "<\\/"))
            return self.send(200, page.replace("__TOKEN__", TOKEN).encode())
        if u.path == "/api/job":
            return self.json(detail(slug, q.get("key", [""])[0]))
        self.send(404, b"not found")

    def do_POST(self) -> None:
        if self.headers.get("X-Panel-Token") != TOKEN or self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
            return self.send(403, b"forbidden")
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        slug, key = body.get("slug"), body.get("key")
        if slug not in list_candidates():
            return self.send(404, b"unknown candidate")
        try:
            if self.path == "/status":
                status = DROP_STATUS.get(body.get("column"), body.get("status"))
                set_status(slug, key, status, note=body.get("note") or "from the panel")
                return self.json({"ok": True, "status": status})
            if self.path == "/note":
                set_note(slug, key, body.get("text") or "")
                return self.json({"ok": True})
            if self.path == "/rescue":
                return self.json(rescue(slug, key))
            if self.path == "/open":
                return self.json(open_folder(slug, key))
        except SystemExit as e:                       # tracker refusals (limits, unknown key) come back as text
            return self.json({"ok": False, "error": str(e)}, 409)
        self.send(404, b"not found")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765); ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
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
