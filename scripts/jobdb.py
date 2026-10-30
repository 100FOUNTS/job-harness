"""Job memory: every ad ever listed for a candidate, one row per ad, in candidates/<slug>/jobs.db (SQLite).

Written by discover (sightings), triage (verdict, reason, full description) and prepare (fit, outcome), so:
- an ad already judged under the same targets.json is not judged again (nor its description fetched again);
- a repost under another title is recognised by its description;
- the market can be read across days (employers, requirements that exclude the person, salaries).

  job db <slug> import            backfill from data/<date>/jobs*.json, shortlist*.json and tracker.json
  job db <slug> stats             what the searches found, why ads were dropped, who hires
  job db <slug> show <key>        one ad with its sightings
  job db <slug> sql "<SELECT>"    read-only query (tables: jobs, sightings)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from common import cand_dir, read_json

FIELDS = ("platform", "title", "company", "location", "url", "listed", "salary", "work_type", "classification",
          "search", "teaser", "easy_apply")
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS jobs (
  key TEXT PRIMARY KEY, {", ".join(f + " TEXT" for f in FIELDS)}, tracks TEXT, bullets TEXT, description TEXT,
  first_seen TEXT, last_seen TEXT, times_seen INTEGER DEFAULT 0,
  verdict TEXT, reason TEXT, track TEXT, judged_with TEXT, fit INTEGER, outcome TEXT);
CREATE TABLE IF NOT EXISTS sightings (key TEXT, day TEXT, PRIMARY KEY (key, day));
"""
# Verdicts worth judging again even under the same targets: they depended on the day, not on the ad
TRANSIENT = ("over shortlist cap", "description unavailable")
REPOST_SIMILARITY = 0.7          # RPS reposted with a longer company blurb: 0.77; same employer, other role: ≤ 0.65


def connect(slug: str, readonly: bool = False) -> sqlite3.Connection:
    p = cand_dir(slug) / "jobs.db"
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True) if readonly else sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    if not readonly:
        con.executescript(SCHEMA)
    return con


def targets_hash(targets: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(targets, sort_keys=True).encode()).hexdigest()[:12]


def record_seen(slug: str, jobs: Iterable[dict[str, Any]], day: str) -> None:
    """One sighting per ad per day; listing fields refreshed, judgement and description kept."""
    with connect(slug) as con:
        for j in jobs:
            vals = {f: str(j.get(f, "") if j.get(f) is not None else "") for f in FIELDS}
            vals |= {"tracks": json.dumps(j.get("tracks", [])), "bullets": json.dumps(j.get("bullets", []))}
            cols = ", ".join(vals)
            con.execute(f"INSERT INTO jobs (key, {cols}, first_seen, last_seen) VALUES (?, {', '.join('?' * len(vals))}, ?, ?) "
                        f"ON CONFLICT(key) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in vals)}, "
                        "first_seen=MIN(first_seen, excluded.first_seen), last_seen=MAX(last_seen, excluded.last_seen)",
                        (j["key"], *vals.values(), day, day))
            con.execute("INSERT OR IGNORE INTO sightings VALUES (?, ?)", (j["key"], day))
            con.execute("UPDATE jobs SET times_seen=(SELECT COUNT(*) FROM sightings WHERE key=?) WHERE key=?", (j["key"], j["key"]))


def settled(slug: str, targets: dict[str, Any]) -> set[str]:
    """Ads rejected under these exact targets for a reason that will not change tomorrow."""
    with connect(slug) as con:
        rows = con.execute("SELECT key, reason FROM jobs WHERE verdict='rejected' AND judged_with=?", (targets_hash(targets),))
        return {r["key"] for r in rows if not r["reason"].startswith(TRANSIENT)}


def descriptions(slug: str, keys: Iterable[str]) -> dict[str, str]:
    keys = list(keys)
    with connect(slug) as con:
        rows = con.execute(f"SELECT key, description FROM jobs WHERE description != '' AND key IN ({','.join('?' * len(keys))})", keys)
        return {r["key"]: r["description"] for r in rows}


def record_triage(slug: str, jobs: list[dict[str, Any]], short: list[dict[str, Any]],
                  rejected: list[dict[str, Any]], targets: dict[str, Any]) -> None:
    desc = {j["key"]: j.get("description", "") for j in jobs}
    h = targets_hash(targets)
    with connect(slug) as con:
        for j in short:
            con.execute("UPDATE jobs SET verdict='shortlisted', reason='ok', track=?, judged_with=?, "
                        "description=COALESCE(NULLIF(?, ''), description) WHERE key=?", (j["track"], h, desc.get(j["key"], ""), j["key"]))
        for r in rejected:
            con.execute("UPDATE jobs SET verdict='rejected', reason=?, judged_with=?, "
                        "description=COALESCE(NULLIF(?, ''), description) WHERE key=?", (r["reason"], h, desc.get(r["key"], ""), r["key"]))


def record_outcome(slug: str, key: str, fit: int | None, outcome: str) -> None:
    with connect(slug) as con:
        con.execute("UPDATE jobs SET fit=COALESCE(?, fit), outcome=? WHERE key=?", (fit, outcome, key))


def similarity(a: str, b: str) -> float:
    """Share of 3-word shingles in common (Jaccard): a reposted ad keeps its text even when the title changes."""
    def shingles(t: str) -> set[tuple[str, ...]]:
        w = re.findall(r"[a-z0-9]+", t.lower())
        return {tuple(w[i:i + 3]) for i in range(len(w) - 2)}
    sa, sb = shingles(a), shingles(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def backfill(slug: str) -> dict[str, int]:
    """Load the dated folders and the tracker written before jobs.db existed. Verdicts are imported as
    judged_with='import', so each ad is judged once more under today's targets before it counts as settled."""
    base = cand_dir(slug)
    n = {"sightings": 0, "verdicts": 0, "descriptions": 0, "tracked": 0}
    for day_dir in sorted(p for p in (base / "data").glob("*") if p.is_dir()):
        for f in sorted(day_dir.glob("jobs*.json")):
            jobs = read_json(f).get("new_jobs", [])
            record_seen(slug, jobs, day_dir.name)
            n["sightings"] += len(jobs)
        for f in sorted(day_dir.glob("shortlist*.json")):
            sl = read_json(f)
            with connect(slug) as con:
                for j in sl.get("shortlist", []):
                    con.execute("UPDATE jobs SET verdict='shortlisted', reason='ok', track=?, judged_with='import', "
                                "description=COALESCE(NULLIF(?, ''), description) WHERE key=?",
                                (j.get("track"), j.get("description", ""), j["key"]))
                    n["descriptions"] += bool(j.get("description"))
                for r in sl.get("rejected", []):
                    con.execute("UPDATE jobs SET verdict='rejected', reason=?, judged_with='import' WHERE key=?", (r["reason"], r["key"]))
                n["verdicts"] += len(sl.get("shortlist", [])) + len(sl.get("rejected", []))
    from tracker import load
    for a in load(slug):
        with connect(slug) as con:
            if not con.execute("SELECT 1 FROM jobs WHERE key=?", (a["key"],)).fetchone():   # tracked before its folder kept it
                record_seen(slug, [a], a.get("date", ""))
            con.execute("UPDATE jobs SET fit=COALESCE(?, fit), outcome=COALESCE(outcome, ?) WHERE key=?",
                        (a.get("fit"), a["status"], a["key"]))
        n["tracked"] += 1
    return n


def stats(slug: str) -> dict[str, Any]:
    with connect(slug, readonly=True) as con:
        q = lambda sql: [tuple(r) for r in con.execute(sql)]
        reasons: dict[str, int] = {}
        for (reason, c) in q("SELECT reason, COUNT(*) FROM jobs WHERE verdict='rejected' GROUP BY reason"):
            k = reason.split(" (")[0].split(" '")[0]
            reasons[k] = reasons.get(k, 0) + c
        return {
            "ads": q("SELECT COUNT(*), SUM(times_seen>1), MAX(times_seen), MIN(first_seen), MAX(last_seen) FROM jobs")[0],
            "by_platform": dict(q("SELECT platform, COUNT(*) FROM jobs GROUP BY platform")),
            "verdicts": dict(q("SELECT COALESCE(verdict, 'not judged'), COUNT(*) FROM jobs GROUP BY 1")),
            "rejection_reasons": dict(sorted(reasons.items(), key=lambda x: -x[1])),
            "requirements_that_exclude": dict(q("SELECT reason, COUNT(*) c FROM jobs WHERE reason LIKE 'requirement excluded%' "
                                                "GROUP BY reason ORDER BY c DESC LIMIT 10")),
            "employers_shortlisted": dict(q("SELECT company, COUNT(*) c FROM jobs WHERE verdict='shortlisted' "
                                            "GROUP BY company ORDER BY c DESC LIMIT 10")),
            "outcomes": dict(q("SELECT outcome, COUNT(*) FROM jobs WHERE outcome IS NOT NULL GROUP BY outcome")),
            "with_salary": q("SELECT COUNT(*) FROM jobs WHERE salary != ''")[0][0],
            "with_description": q("SELECT COUNT(*) FROM jobs WHERE description != ''")[0][0],
        }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("cmd", choices=["import", "stats", "show", "sql"]); ap.add_argument("arg", nargs="?")
    a = ap.parse_args()
    if a.cmd == "import":
        out: Any = backfill(a.slug)
    elif a.cmd == "stats":
        out = stats(a.slug)
    elif a.cmd == "show":
        with connect(a.slug, readonly=True) as con:
            row = con.execute("SELECT * FROM jobs WHERE key=?", (a.arg,)).fetchone()
            out = dict(row) | {"sightings": [r[0] for r in con.execute("SELECT day FROM sightings WHERE key=? ORDER BY day", (a.arg,))]} if row else {}
    else:
        with connect(a.slug, readonly=True) as con:
            out = [dict(r) for r in con.execute(a.arg)]
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
