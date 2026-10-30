"""Deterministic pre-filter: cheap rules first, so the LLM only reads jobs worth judging.

  job triage <slug> [--date YYYY-MM-DD] [--max 40]
  → data/<date>/shortlist.json  {shortlist: [...], rejected: [{key, title, reason}]}

Rules (all from targets.json):
- title must match one track's `title_include` → that track is assigned (first match wins, tracks in priority order)
- title must not match `exclude_title` (seniority the candidate is not targeting)
- text must not match `exclude_text` (citizenship/PR/clearance requirements)
- location must match `locations_include`
Shortlisted jobs get their full description (LinkedIn guest page, SEEK GraphQL; one request each, spaced) and are re-judged.
A description already in jobs.db is reused instead of fetched again. Every verdict, reason and description goes to jobs.db.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from typing import Any

from common import cand_dir, keep_previous, read_json, run_dir, save_json
from jobdb import descriptions, record_triage


def rx(words: list[str]) -> re.Pattern[str] | None:
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I) if words else None


def assign_track(title: str, tracks: list[dict[str, Any]], text: str = "") -> str | None:
    """First track (priority order) whose title_include matches and whose own exclude_title does not.
    Then `description_include` {words, min, titles}: a generic title (e.g. "Fire Planning Officer") whose ad
    mentions the track's words at least `min` times."""
    for t in tracks:
        r, ex = rx(t.get("title_include", [])), rx(t.get("exclude_title", []))
        if r and r.search(title) and not (ex and ex.search(title)):
            return t["id"]
    for t in tracks:
        di, ex = t.get("description_include"), rx(t.get("exclude_title", []))
        if not di or (ex and ex.search(title)) or not (rx(di.get("titles", [])) or re.compile("")).search(title):
            continue
        if len(rx(di["words"]).findall(text)) >= di.get("min", 3):
            return t["id"]
    return None


YEARS_REQ = re.compile(r"(?:minimum|min\.?|at least|over|more than)?\s*(\d{1,2})\s*(?:\+|-|–|to)?\s*(\d{1,2})?\s*\+?\s*years?(?:'|’)?\s*(?:of\s+)?(?:\w+\s+){0,4}?experience", re.I)


def min_years_required(text: str) -> int | None:
    """Smallest 'N years experience' requirement in the ad (for '3-5 years' → 3). None if not stated."""
    vals = [int(m.group(1)) for m in YEARS_REQ.finditer(text) if 0 < int(m.group(1)) < 30]
    return min(vals) if vals else None


def judge(job: dict[str, Any], targets: dict[str, Any]) -> tuple[str | None, str]:
    title = job.get("title", "")
    text = " ".join([title, job.get("teaser", ""), " ".join(job.get("bullets", [])), job.get("description", "")])
    ex_title, ex_text, loc = rx(targets.get("exclude_title", [])), rx(targets.get("exclude_text", [])), rx(targets.get("locations_include", []))
    # "Scientist to Associate Director": a seniority range is judged by its entry point, not its ceiling
    lead = re.split(r"\s+to\s+", title, maxsplit=1, flags=re.I)[0]
    if ex_title and (m := ex_title.search(lead)):
        return None, f"seniority/title excluded ('{m.group()}')"
    if ex_text and (m := ex_text.search(text)):
        return None, f"requirement excluded ('{m.group()}')"
    my = targets.get("max_years_required")
    req = min_years_required(text)
    if my is not None and req is not None and req > my:
        return None, f"requires {req}+ years (max {my})"
    if loc and job.get("location") and not loc.search(job["location"]):
        return None, f"location '{job['location']}'"
    track = assign_track(title, targets["tracks"], text)
    if not track:
        return None, "title does not match any target track"
    return track, "ok"


GENERIC_ORG = {"the", "of", "and", "shire", "city", "town", "department", "dept", "council", "government", "group", "pty", "ltd"}


# Title tails that only say where, how long or how senior: the same ad reposted, not a different role
NOISE_TAIL = re.compile(r"\b(perth|wa|western australia|adelaide|sa|regional|remote|metro|based|fifo|dido|roster|\d+\s*:\s*\d+"
                        r"|contract|month|year|fixed[- ]term|permanent|full[- ]time|part[- ]time|hybrid|immediate start)\b|\bto\b", re.I)


def dedupe_key(title: str, company: str) -> str:
    """Same ad posted on both platforms or twice by the same employer: normalised title + first company word.
    Tails after " - " stay unless they are only place/term/seniority noise: "Environmental Consultant – Contaminated
    Lands" and "Environmental Consultant - Environmental Approvals" at WSP are different roles."""
    head, *tails = re.split(r"\s+[-–|]\s+", title)
    keep = [t for t in tails if not NOISE_TAIL.search(t)]
    words = [w for w in re.findall(r"[a-z]+", company.lower()) if w not in GENERIC_ORG]
    return re.sub(r"[^a-z]+", " ", " ".join([head] + keep).lower()).strip() + "|" + (words or [""])[0]


def by_description_possible(title: str, targets: dict[str, Any]) -> bool:
    """A title that a track's `description_include` could still claim once the full ad is read."""
    for t in targets["tracks"]:
        di, ex = t.get("description_include"), rx(t.get("exclude_title", []))
        if di and not (ex and ex.search(title)) and (not di.get("titles") or rx(di["titles"]).search(title)):
            return True
    return False


def triage(slug: str, day: str | None, max_n: int) -> dict[str, Any]:
    from discover import linkedin_detail, seek_detail
    targets = read_json(cand_dir(slug) / "targets.json")
    jobs = read_json(run_dir(slug, day) / "jobs.json")["new_jobs"]
    known = descriptions(slug, [j["key"] for j in jobs])        # fetched on an earlier day: no second request
    for j in jobs:
        j["description"] = j.get("description") or known.get(j["key"], "")
    short, rejected = [], []
    for j in sorted(jobs, key=lambda x: x.get("listed", ""), reverse=True):
        track, why = judge(j, targets)
        maybe = why.startswith("title does not match") and by_description_possible(j.get("title", ""), targets)
        if (track or maybe) and len(short) < max_n:
            if j["platform"] == "seek" and not j.get("description"):
                j["description"] = seek_detail(j["id"])          # empty on failure: teaser + bullets still judged
                time.sleep(random.uniform(0.8, 1.8))
                track, why = judge(j, targets)
            elif j["platform"] == "linkedin" and not j.get("description"):
                j["description"] = linkedin_detail(j["id"])
                time.sleep(random.uniform(1.5, 3.5))
                track, why = judge(j, targets)            # re-check with the full text
                if track and not j["description"]:
                    track, why = None, "description unavailable (LinkedIn rate limit): retry tomorrow"
            if track:
                short.append(j | {"track": track}); continue
        rejected.append({"key": j["key"], "title": j.get("title"), "company": j.get("company"),
                         "reason": why if not track else "over shortlist cap"})
    # The same ad on the other platform can be shorter (SEEK often drops the eligibility paragraph LinkedIn keeps):
    # a twin excluded for a requirement takes its shortlisted copy with it.
    # Remembered across days: the readable twin may not be readable tomorrow (LinkedIn 429).
    barred_file = cand_dir(slug) / "barred.json"
    barred = read_json(barred_file, {})
    barred.update({dedupe_key(r["title"] or "", r["company"] or ""): r["reason"] for r in rejected
                   if r["reason"].startswith("requirement excluded")})
    save_json(barred_file, barred)
    for j in [j for j in short if dedupe_key(j.get("title", ""), j.get("company", "")) in barred]:
        short.remove(j)
        rejected.append({"key": j["key"], "title": j.get("title"), "company": j.get("company"),
                         "reason": "twin ad " + barred[dedupe_key(j.get("title", ""), j.get("company", ""))]})
    out = {"shortlist": short, "rejected": rejected}
    record_triage(slug, jobs, short, rejected, targets)
    keep_previous(run_dir(slug, day) / "shortlist.json")
    save_json(run_dir(slug, day) / "shortlist.json", out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("--date"); ap.add_argument("--max", type=int, default=40)
    a = ap.parse_args()
    r = triage(a.slug, a.date, a.max)
    reasons: dict[str, int] = {}
    for x in r["rejected"]:
        k = x["reason"].split(" (")[0].split(" '")[0]
        reasons[k] = reasons.get(k, 0) + 1
    print(json.dumps({"shortlist": len(r["shortlist"]), "rejected": len(r["rejected"]), "reasons": reasons,
                      "shortlisted": [f"{j['track']}: {j['title']} — {j.get('company', '')}" for j in r["shortlist"]]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
