"""Rejected ads close to the current targets. Read only; no descriptions in output."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import date, timedelta
from typing import Any

from common import cand_dir, read_json

STOP = set("a an the and or of for in on at to with from by senior junior lead principal chief head manager graduate intern trainee associate ii iii iv".split())
NO_TRACK = "title does not match any target track"


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.lower())


def suggestions(title: str, tracks: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
    tokens = words(title)
    useful = set(tokens) - STOP
    best, shared, score = None, set(), 0
    phrases = [words(p) for t in tracks for p in t.get("title_include", [])]
    if any(p and any(tokens[i:i + len(p)] == p for i in range(len(tokens) - len(p) + 1)) for p in phrases):
        return None, []
    for t in tracks:
        for phrase in t.get("title_include", []):
            match = useful & (set(words(phrase)) - STOP)
            if len(match) > score:
                best, shared, score = t.get("id"), match, len(match)
    if not score:
        return None, []
    covered = {" ".join(p) for p in phrases}
    candidates = {" ".join(tokens[i:i + 2]) for i in range(len(tokens) - 1)
                  if not (set(tokens[i:i + 2]) & STOP) and set(tokens[i:i + 2]) & shared}
    candidates -= covered
    if not candidates:
        candidates = shared - covered
    return best, sorted(candidates)


def nearmiss(slug: str, days: int = 14, top: int = 10) -> dict[str, Any]:
    if days < 0 or top < 1:
        raise ValueError("days must be non-negative and top must be positive")
    targets = read_json(cand_dir(slug) / "targets.json", {})
    out = {"days": days, "years": [], "no_track": [], "exclusions": [], "locations": []}
    db = cand_dir(slug) / "jobs.db"
    if not db.exists():
        return out
    since = (date.today() - timedelta(days=days)).isoformat()
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT title, company, location, reason FROM jobs WHERE verdict='rejected' "
                           "AND last_seen >= ? ORDER BY last_seen DESC, key", (since,)).fetchall()
    finally:
        con.close()
    groups = {"no_track": {}, "exclusions": {}, "locations": {}}

    def count(section, key, fields, title):
        item = groups[section].setdefault(key, dict(fields, count=0, examples=[]))
        item["count"] += 1
        if title not in item["examples"] and len(item["examples"]) < 3:
            item["examples"].append(title)

    for row in rows:
        reason, title = row["reason"] or "", row["title"] or ""
        if reason.startswith(("twin ad", "company excluded", "requirement excluded")):
            continue
        m = re.fullmatch(r"requires (\d+)\+ years \(max \d+\)", reason)
        limit = targets.get("max_years_required")
        if m and limit is not None and int(m[1]) - limit in (1, 2):
            out["years"].append({"title": title, "company": row["company"] or "", "years": int(m[1])})
        elif reason == NO_TRACK or reason.startswith(NO_TRACK + " (not read:"):
            track, terms = suggestions(title, targets.get("tracks", []))
            for term in terms:
                count("no_track", (term, track), {"phrase": term, "track": track}, title)
        elif m := re.fullmatch(r"(?:seniority/title|title) excluded \('(.+)'\)", reason):
            term = m[1].lower()
            count("exclusions", term, {"word": term}, title)
        elif re.fullmatch(r"location '.*'", reason):
            location = row["location"] or reason[len("location '"):-1]
            count("locations", location, {"location": location}, title)
    out["years"] = sorted(out["years"], key=lambda r: (r["years"], r["title"], r["company"]))[:top]
    for section, field in (("no_track", "phrase"), ("exclusions", "word"), ("locations", "location")):
        out[section] = sorted(groups[section].values(), key=lambda r: (-r["count"], r[field], r.get("track") or ""))[:top]
    return out


def summary_lines(slug: str, days: int = 14, top: int = 3) -> list[str]:
    r = nearmiss(slug, days, top)
    lines = []
    if r["years"]:
        lines.append("Years just over: " + "; ".join(f"{x['title']} ({x['company']}, {x['years']} years)" for x in r["years"]))
    if r["no_track"]:
        lines.append("Add this phrase? " + "; ".join(f"{x['phrase']} ({x['count']}, {x['track']})" for x in r["no_track"]))
    return lines


def table(r: dict[str, Any]) -> str:
    lines = [f"Near misses, last {r['days']} days"]
    for title, section in (("Years just over the limit", "years"), ("No track matched, but close", "no_track"),
                           ("Exclusions doing the most work", "exclusions"), ("Location", "locations")):
        lines.append(title + ":")
        for x in r[section]:
            if section == "years":
                lines.append(f"  {x['title']} | {x['company']} | {x['years']} years")
            else:
                label = x.get("phrase", x.get("word", x.get("location")))
                track = f" [{x['track']}]" if section == "no_track" else ""
                examples = " | " + "; ".join(x["examples"]) if section != "locations" else ""
                lines.append(f"  {label}{track}: {x['count']}{examples}")
        if not r[section]:
            lines.append("  None")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug"); ap.add_argument("--days", type=int, default=14); ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.days < 0 or a.top < 1:
        ap.error("days must be non-negative and top must be positive")
    r = nearmiss(a.slug, a.days, a.top)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else table(r))


if __name__ == "__main__":
    main()
