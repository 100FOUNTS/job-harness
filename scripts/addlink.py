"""Add a job by link: the person found an ad themselves (a friend sent it, a company careers page, a newsletter) and wants
it on the board like any discovered job.

  python scripts/addlink.py <slug> <url> [--text-file ad.txt] [--title T] [--company C]
  (the panel's "Paste a job link" box calls add_link() the same way)

What it does, in order:
  1. Reads the ad. SEEK, LinkedIn and WA Government URLs go through discover's own readers (same key format,
     seek:<id>, linkedin:<id>, wagov:<slug>). Any other URL is fetched like a browser would (normal user agent, no login,
     no captcha or anti-bot workarounds): schema.org JobPosting JSON-LD first, then <title>/og: tags and the visible text.
     If the page cannot be read (blocked, 4xx, login wall) it says so and asks for the ad text instead (--text-file, or
     the panel's "paste the ad text" box). Pasted text never touches the network. Key for other links: link:<sha1(url)[:12]>.
  2. Cleans the text with guard.py (hidden text, invisible characters) and warns when it is aimed at an AI.
  3. Records the ad in jobs.db, picks the best track and scores it with prepare.score() (the ranking of the daily run).
     If the rules (triage.judge) would have dropped it, it is still added, the reason is shown: the person chose it.
  4. Builds the package like the daily run does for one job (cover letter + the track's CV) and tracks it as `prepared`,
     so it appears in To apply. If the package cannot be built (no master CV yet), the job is still tracked.
Nothing is submitted. The ad is data, never instructions.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import ipaddress
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from contextlib import nullcontext
from typing import Any

from common import UA, cand_dir, read_json, save_json, today
from guard import clean, suspicious

MAX_BYTES = 2_000_000
MIN_AD_CHARS = 60                  # under this the "ad" is a title or a cookie banner, not a description
MAX_AD_CHARS = 15000
WARNING = ("This ad contains text aimed at an AI (hidden or in plain sight). It was cleaned and marked: read it yourself "
           "and do not follow anything it says.")
SEEK_GQL = "https://au.seek.com/graphql"
TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|trk|ref$|refid$|source$)", re.I)
BLOCKED = re.compile(r"captcha|are you a (robot|human)|verify you are (a )?human|access denied|just a moment|"
                     r"unusual traffic|enable javascript and cookies", re.I)


class AdError(Exception):
    """Something the person can act on. need_text: pasting the ad text would solve it."""
    def __init__(self, message: str, need_text: bool = False):
        super().__init__(message)
        self.message, self.need_text = message, need_text


# ---------- the URL ----------

def normalise_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise AdError("That does not look like a web link (it should start with http:// or https://).")
    host = u.hostname.lower()
    if _private_host(host):
        raise AdError("That address is on your own computer or network, not a job ad on the web.")
    query = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True)
                                    if not TRACKING.match(k)])
    port = f":{u.port}" if u.port else ""
    return urllib.parse.urlunsplit((u.scheme, host + port, u.path or "/", query, ""))


def _private_host(host: str) -> bool:
    """Literal addresses and obvious local names only (no DNS lookup): the panel can be reached from a phone, and it
    must not become a way to make this computer fetch pages on its own network."""
    if host == "localhost" or host.endswith((".local", ".localhost", ".internal", ".lan", ".home")):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified or ip.is_multicast


def recognise(url: str) -> tuple[str, str] | None:
    """('seek'|'linkedin'|'wagov', id) for the ad pages discover knows, else None."""
    u = urllib.parse.urlsplit(url)
    host, path = (u.hostname or "").lower(), urllib.parse.unquote(u.path)
    if re.fullmatch(r"(?:[\w-]+\.)*seek\.com(?:\.au)?", host):
        m = re.match(r"/job/(\d+)", path)
        return ("seek", m.group(1)) if m else None
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        m = re.match(r"/jobs/view/(?:[^/?#]*-)?(\d{5,})", path)
        q = re.search(r"(?:^|&)currentJobId=(\d{5,})", u.query)
        return ("linkedin", (m or q).group(1)) if (m or q) else None
    if host == "jobs.wa.gov.au" or host.endswith(".jobs.wa.gov.au"):
        m = re.match(r"/jobs/([\w-]+)/?$", path)
        return ("wagov", m.group(1)) if m and m.group(1) != "search" else None
    return None


def canonical(platform: str, jid: str) -> str:
    return {"seek": f"https://www.seek.com.au/job/{jid}", "linkedin": f"https://www.linkedin.com/jobs/view/{jid}/",
            "wagov": f"https://search.jobs.wa.gov.au/jobs/{jid}"}[platform]


def link_key(url: str, text: str = "") -> str:
    return "link:" + hashlib.sha1((url or text[:2000]).encode("utf-8")).hexdigest()[:12]


def key_for(url: str, text: str = "") -> str:
    """The key the ad will have, known before anything is fetched (to refuse a duplicate early)."""
    rec = recognise(url) if url else None
    return f"{rec[0]}:{rec[1]}" if rec else link_key(url, text)


# ---------- reading text ----------

def guard_text(raw: str) -> tuple[str, bool]:
    """Raw ad HTML or text → (plain text a reader sees, was something aimed at an AI). The mark is appended like discover does."""
    from prepare import GUARD_MARK
    text, flags = clean(raw)
    bad = suspicious(flags)
    return (f"{text} {GUARD_MARK}" if bad and text else text)[:MAX_AD_CHARS], bad


def _unescape_html(s: str) -> str:
    return html.unescape(s) if "&lt;" in s and "<" not in s else s       # some sites escape the markup inside the JSON


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
                                               "Accept-Language": "en-AU,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            final = r.geturl() if hasattr(r, "geturl") else url
            if final and _private_host((urllib.parse.urlsplit(final).hostname or "").lower()):
                raise AdError("That link redirects to an address on your own network.")
            raw = r.read(MAX_BYTES + 1)
            charset = (r.headers.get_content_charset() if hasattr(r.headers, "get_content_charset") else None) or "utf-8"
    except AdError:
        raise
    except urllib.error.HTTPError as e:
        why = "needs a login or blocks automatic readers" if e.code in (401, 403, 429, 999) else "did not give the page"
        raise AdError(f"The site {why} (HTTP {e.code}). Paste the text of the ad instead.", need_text=True)
    except (urllib.error.URLError, OSError, ValueError):
        raise AdError("Could not reach that link. Check it, or paste the text of the ad instead.", need_text=True)
    try:
        return raw[:MAX_BYTES].decode(charset, errors="replace")
    except LookupError:
        return raw[:MAX_BYTES].decode("utf-8", errors="replace")


LD_JSON = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)


def _walk(o: Any):
    if isinstance(o, list):
        for x in o:
            yield from _walk(x)
    elif isinstance(o, dict):
        yield o
        for x in o.get("@graph", []) if isinstance(o.get("@graph"), list) else []:
            yield from _walk(x)


def job_posting(raw: str) -> dict[str, Any] | None:
    """The first schema.org JobPosting in the page's JSON-LD blocks."""
    for m in LD_JSON.finditer(raw):
        try:
            data = json.loads(m.group(1).strip().removeprefix("<!--").removesuffix("-->"), strict=False)
        except ValueError:
            continue
        for o in _walk(data):
            t = o.get("@type")
            if "JobPosting" in (t if isinstance(t, list) else [t]):
                return o
    return None


def _name(v: Any) -> str:
    if isinstance(v, list):
        return _name(v[0]) if v else ""
    return str(v.get("name") or "") if isinstance(v, dict) else str(v or "")


def _place(ld: dict[str, Any]) -> str:
    parts: list[str] = []
    locs = ld.get("jobLocation")
    for loc in locs if isinstance(locs, list) else [locs]:
        addr = loc.get("address") if isinstance(loc, dict) else loc
        if isinstance(addr, dict):
            bits = [str(addr.get(k) or "") for k in ("addressLocality", "addressRegion")]
        else:
            bits = [str(addr or "")]
        parts += [b for b in bits if b and b not in parts]
    if str(ld.get("jobLocationType") or "").upper() == "TELECOMMUTE" and "Remote" not in parts:
        parts.append("Remote")
    return ", ".join(parts)


def _salary(ld: dict[str, Any]) -> str:
    base = ld.get("baseSalary")
    v = base.get("value") if isinstance(base, dict) else None
    if not isinstance(v, dict):
        return ""
    lo, hi = v.get("minValue"), v.get("maxValue")
    nums = [f"${float(x):,.0f}" for x in (lo, hi) if isinstance(x, (int, float)) or str(x or "").replace(".", "", 1).isdigit()]
    return " - ".join(dict.fromkeys(nums)) + (f" {str(v.get('unitText')).lower()}" if nums and v.get("unitText") else "")


def meta(raw: str, name: str) -> str:
    for pat in (rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)["\']',
                rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(name)}["\']'):
        m = re.search(pat, raw, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def from_page(url: str, raw: str) -> dict[str, Any]:
    """Page HTML → job fields: JobPosting JSON-LD, else <title>/og: tags plus the visible text."""
    ld = job_posting(raw)
    job: dict[str, Any] = {"title": "", "company": "", "location": "", "listed": "", "closes": "", "salary": "", "description": ""}
    bad = False
    if ld:
        desc, bad = guard_text(_unescape_html(str(ld.get("description") or "")))
        job |= {"title": html.unescape(str(ld.get("title") or ld.get("name") or "")).strip(),
                "company": html.unescape(_name(ld.get("hiringOrganization"))).strip(), "location": _place(ld),
                "listed": str(ld.get("datePosted") or "")[:10], "closes": str(ld.get("validThrough") or "")[:10],
                "salary": _salary(ld), "description": desc}
    if len(job["description"]) < MIN_AD_CHARS:             # no usable JSON-LD: what a reader sees
        body = re.sub(r"<(nav|header|footer|aside|form|svg)\b.*?</\1\s*>", " ", raw, flags=re.I | re.S)
        text, bad2 = guard_text(body)
        if BLOCKED.search(raw) and len(text) < 800:
            raise AdError("The site is asking for a captcha or a login before showing the ad. Paste the text of the ad instead.",
                          need_text=True)
        extra = meta(raw, "og:description")
        job["description"] = text if len(text) >= MIN_AD_CHARS else guard_text(extra)[0]
        bad = bad or bad2
        title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        job["title"] = job["title"] or meta(raw, "og:title") or (" ".join(html.unescape(title.group(1)).split()) if title else "")
        job["company"] = job["company"] or meta(raw, "og:site_name")
    if not job["title"] or len(job["description"]) < MIN_AD_CHARS:
        raise AdError("I could not find the ad on that page (it may load only in a browser, or need a login). "
                      "Paste the text of the ad instead.", need_text=True)
    return job | {"warn": bad}


def from_text(text: str, title: str = "", company: str = "") -> dict[str, Any]:
    desc, bad = guard_text(text)
    if len(desc) < MIN_AD_CHARS:
        raise AdError("That text is too short to be a job ad.", need_text=True)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return {"title": (title or first)[:140].strip(), "company": company.strip(), "location": "", "listed": "", "closes": "",
            "salary": "", "description": desc, "warn": bad}


# ---------- SEEK, LinkedIn, WA Government: discover's readers + the metadata they do not return ----------

def _seek_meta(jid: str) -> dict[str, Any]:
    q = {"operationName": "jobDetails", "variables": {"jobId": jid}, "query":
         "query jobDetails($jobId: ID!) { jobDetails(id: $jobId) { job { title advertiser { name } location { label } "
         "salary { label } listedAt { dateTimeUtc } expiresAt { dateTimeUtc } content(platform: WEB) } } }"}
    req = urllib.request.Request(SEEK_GQL, data=json.dumps(q).encode(), headers={
        "User-Agent": UA, "Content-Type": "application/json", "seek-request-brand": "seek", "seek-request-country": "AU"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return ((json.loads(r.read().decode("utf-8", errors="ignore")).get("data") or {}).get("jobDetails") or {}).get("job") or {}
    except Exception:
        return {}


def from_seek(jid: str) -> dict[str, Any]:
    import discover
    m = _seek_meta(jid)
    desc = discover.seek_detail(jid) or guard_text(m.get("content") or "")[0]
    if not m.get("title") or not desc:
        raise AdError("SEEK did not show me that ad (it may have closed). Paste the text of the ad instead.", need_text=True)
    return {"title": m["title"], "company": (m.get("advertiser") or {}).get("name") or "",
            "location": (m.get("location") or {}).get("label") or "", "salary": (m.get("salary") or {}).get("label") or "",
            "listed": ((m.get("listedAt") or {}).get("dateTimeUtc") or "")[:10],
            "closes": ((m.get("expiresAt") or {}).get("dateTimeUtc") or "")[:10], "description": desc}


def from_linkedin(jid: str) -> dict[str, Any]:
    import discover
    from common import http_get
    code, page = http_get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}")

    def grab(cls: str) -> str:
        m = re.search(rf'class="[^"]*{cls}[^"]*"[^>]*>(.*?)</', page, re.S)
        return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split())) if m else ""
    desc = discover.linkedin_detail(jid) if code == 200 else ""
    title = grab("top-card-layout__title") if code == 200 else ""
    if not title or not desc:
        raise AdError("LinkedIn did not show me that ad without signing in (or it has closed). Paste the text of the ad instead.",
                      need_text=True)
    return {"title": title, "company": grab("topcard__org-name-link") or grab("topcard__flavor"),
            "location": grab("topcard__flavor--bullet"), "description": desc, "listed": today(), "closes": "", "salary": ""}


def from_wagov(jid: str) -> dict[str, Any]:
    import discover
    code, ld, closes = discover.wagov_page(jid)
    desc = discover.wagov_detail(jid) if code == 200 else ""
    if not ld.get("title") or not desc:
        raise AdError("WA Government Jobs did not show me that ad (it may have closed). Paste the text of the ad instead.", need_text=True)
    org = _name(ld.get("hiringOrganization"))
    if not org or org.lower() == "wa government jobs":         # the portal, not the agency: the ad usually names the agency
        m = re.search(r"\b((?:Department|Office|Commission|Authority) of [A-Z][\w&' -]{2,40}?|[A-Z][\w&' ]{2,30}? (?:Department|Authority|Commission))\b", desc)
        org = m.group(1).strip() if m else "WA Government"
    return {"title": html.unescape(ld["title"]).strip(), "company": org, "location": _place(ld),
            "listed": str(ld.get("datePosted") or "")[:10], "closes": closes or str(ld.get("validThrough") or "")[:10],
            "salary": _salary(ld), "description": desc}


def fetch_job(url: str, text: str = "", title: str = "", company: str = "") -> dict[str, Any]:
    """The ad as a job dict (key, platform, id, title, company, url, description, ...). Raises AdError."""
    url = normalise_url(url)
    if not url and not (text or "").strip():
        raise AdError("Paste a job link, or the text of the ad.")
    rec = recognise(url) if url else None
    if (text or "").strip():                                  # the person gave the text: no network at all
        job = from_text(text, title, company)
    elif rec:
        job = {"seek": from_seek, "linkedin": from_linkedin, "wagov": from_wagov}[rec[0]](rec[1])
        from prepare import GUARD_MARK
        job["warn"] = GUARD_MARK in job["description"]
    else:
        job = from_page(url, fetch_html(url))
    if title.strip():
        job["title"] = title.strip()
    if company.strip():
        job["company"] = company.strip()
    platform = rec[0] if rec else "link"
    host = (urllib.parse.urlsplit(url).hostname or "").removeprefix("www.") if url else ""
    out_url = canonical(*rec) if rec else url
    return job | {"key": key_for(url, text), "platform": platform, "id": (rec[1] if rec else link_key(url, text)[5:]),
                  "url": out_url, "teaser": "", "bullets": [], "easy_apply": False,
                  **({"source": host} if platform == "link" and host else {})}


# ---------- scoring, jobs.db, tracker, package ----------

def rank(slug: str, job: dict[str, Any], targets: dict[str, Any]) -> tuple[str, int, list[str], dict[str, Any], str]:
    """(best track, score, keyword hits, odds, why the rules would drop it or ''). Same score() as the daily ranking;
    the track is the one where the ad scores highest (the one the rules assign wins a tie)."""
    import prepare
    import triage
    if not targets.get("tracks"):
        raise AdError("This candidate has no target tracks yet (targets.json).")
    judged, why = triage.judge(job, targets)
    best = None
    for t in targets["tracks"]:
        fit, hits, odds = prepare.score(job | {"track": t["id"]}, targets, slug)
        if best is None or (fit, t["id"] == judged) > (best[1], best[0] == judged):
            best = (t["id"], fit, hits, odds)
    return best[0], best[1], best[2], best[3], "" if judged else why


def remember(slug: str, job: dict[str, Any], track: str, fit: int, reason: str, targets: dict[str, Any]) -> None:
    from jobdb import connect, record_outcome, record_seen, targets_hash
    record_seen(slug, [job | {"tracks": [track]}], today())
    with connect(slug) as con:
        con.execute("UPDATE jobs SET description=?, verdict='shortlisted', reason=?, track=?, judged_with=? WHERE key=?",
                    (job["description"], f"added from a link{': ' + reason if reason else ''}", track, targets_hash(targets), job["key"]))
    record_outcome(slug, job["key"], fit, "prepared")


def add_link(slug: str, url: str = "", text: str = "", title: str = "", company: str = "", lock: Any = None) -> dict[str, Any]:
    """Read the ad, score it, track it as prepared and build its package. `lock` (a context manager) is held only while
    files are written, not while the page is downloaded. Never raises for things the person can fix: {"ok": False, "error"}."""
    import prepare
    from tracker import add, load, seen_keys, set_status
    try:
        cand_dir(slug)
        clean_url = normalise_url(url)
        existing = next((a for a in load(slug) if a["key"] == key_for(clean_url, text)), None)
        if existing:
            return {"ok": False, "key": existing["key"], "error": f"Already on your board: {existing['title']} ({existing['status']})."}
        job = fetch_job(url, text, title, company)
        targets = read_json(cand_dir(slug) / "targets.json")
        track, fit, hits, odds, dropped_by = rank(slug, job, targets)
    except AdError as e:
        return {"ok": False, "error": e.message, "need_text": e.need_text}
    job = job | {"track": track}
    summary = f"{track} · matches: {', '.join(hits[:5]) or '—'}"
    note = "added from a pasted link"
    package, package_error = False, ""
    with (lock if lock is not None else nullcontext()):
        remember(slug, job, track, fit, dropped_by, targets)
        pkg = prepare.package_dir(slug)
        manifest = pkg / "items.json"
        items = read_json(manifest, {"items": []})["items"]
        first_last = read_json(cand_dir(slug) / "intake.json")["name"].replace(" ", "_")
        try:
            item = prepare.build_one(slug, targets, pkg, max([x["n"] for x in items], default=0) + 1, fit, hits, odds, job,
                                     first_last, {a["key"]: a for a in load(slug)}, note=note)
            items.append(item)
            save_json(manifest, {"items": items})
            prepare.write_index(pkg, items, slug)
            package = bool(item["ok"])
            package_error = "" if package else "The cover letter did not pass its checks: see the application's history."
        except (Exception, SystemExit) as e:        # no master CV yet, no Node for the letter...: the job is still worth tracking
            package_error = str(e) or e.__class__.__name__
        if job["key"] not in seen_keys(slug):
            add(slug, {"key": job["key"], "title": job["title"], "company": job["company"], "url": job["url"],
                       "platform": job["platform"], "track": track, "location": job["location"], "fit": fit, "summary": summary,
                       **({"closes": job["closes"]} if job.get("closes") else {})})
        if next(a for a in load(slug) if a["key"] == job["key"])["status"] == "shortlisted":
            set_status(slug, job["key"], "prepared", summary=summary, note=f"{note}; package not built")
    res: dict[str, Any] = {"ok": True, "key": job["key"], "title": job["title"], "company": job["company"], "score": fit,
                           "track": track, "platform": job["platform"], "package": package}
    if job.get("warn"):
        res["warning"] = WARNING
    if dropped_by:
        res["rules"] = f"Your rules would have dropped this ad ({dropped_by}). Added anyway, because you chose it."
    if package_error:
        res["package_error"] = package_error
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("url", nargs="?", default="")
    ap.add_argument("--text-file", help="the text of the ad (when the page cannot be fetched)")
    ap.add_argument("--title", default=""); ap.add_argument("--company", default="")
    a = ap.parse_args()
    text = open(a.text_file, encoding="utf-8").read() if a.text_file else ""
    r = add_link(a.slug, a.url, text, a.title, a.company)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
