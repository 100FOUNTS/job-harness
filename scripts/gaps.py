"""Skill gaps across many ads: coverage.py's per-ad check (covered / have it / gap), added up over the ads that matter.

  job gaps <slug> [--days 30] [--track <id>] [--json]

Ads counted (seen in the last --days): shortlisted or tracked ads (not skipped by the person) and the near misses of the
panel's "Maybe worth a look" (dropped only because the title matched no track, but their text fits). Ads dropped for a
hard requirement (citizenship, clearance, seniority, years, location) are left out: they say nothing about skills.
Each ad is checked against the master CV of its own track (the PDF an ATS reads; the track's CV json if no PDF is built).

  have it   the person has it (intake.json) but the CV does not say it: a quick win, add it where it truthfully fits
  gap       in neither: a learning candidate (course, certificate, project). Never a keyword to stuff into the CV
  covered   already in the CV

Terms in fewer than 2 ads are ignored. No LLM, no network.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from common import cand_dir, read_json
from coverage import _has, _norm, profile_text, status_of, vocabulary

MIN_ADS = 2
HARD = ("requirement excluded", "seniority/title excluded", "requires ", "location ")   # triage.judge reasons: not about skills
TOP_EXAMPLES = 5                                                                          # terms that get example titles


def cv_path(slug: str, track: dict[str, Any]) -> Path | None:
    """The track's master CV: its PDF, else docs/master/<First_Last>_Resume.pdf, else the track's CV json."""
    base = cand_dir(slug)
    name = read_json(base / "intake.json", {}).get("name", "").replace(" ", "_")
    for rel in (track.get("cv_pdf"), f"docs/master/{name}_Resume.pdf" if name else None, track.get("cv")):
        if rel and (base / rel).is_file():
            return base / rel
    return None


def cv_texts(slug: str, targets: dict[str, Any]) -> dict[str, str]:
    from facts import extract_text
    out: dict[str, str] = {}
    for t in targets.get("tracks", []):
        p = cv_path(slug, t)
        if p:
            try:
                out[t["id"]] = _norm(extract_text(p))
            except Exception:                       # an unreadable CV must not hide the others
                pass
    return out


def relevant_ads(slug: str, days: int = 30, track: str | None = None) -> list[dict[str, Any]]:
    """[{key, title, track, text, day, kind}]: shortlisted/tracked ads plus near misses, minus hard-requirement drops."""
    from tracker import load
    db = cand_dir(slug) / "jobs.db"
    if not db.exists():
        return []
    targets = read_json(cand_dir(slug) / "targets.json", {})
    default = next((t["id"] for t in targets.get("tracks", []) if t.get("primary")), (targets.get("tracks") or [{}])[0].get("id"))
    apps = {a["key"]: a for a in load(slug)}
    since = (date.today() - timedelta(days=days)).isoformat()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT key, title, track, verdict, reason, last_seen, teaser, bullets, description FROM jobs "
                       "WHERE last_seen >= ? ORDER BY last_seen DESC", (since,)).fetchall()
    con.close()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        app = apps.get(r["key"])
        if not ((app and app["status"] != "skipped") or r["verdict"] == "shortlisted"):
            continue
        if r["verdict"] == "rejected" and (r["reason"] or "").startswith(HARD):
            continue
        out[r["key"]] = {"key": r["key"], "title": r["title"] or "", "day": r["last_seen"], "kind": "relevant",
                         "track": (app or {}).get("track") or r["track"] or default,
                         "text": " ".join(filter(None, [r["title"], r["teaser"], r["bullets"], r["description"]]))}
    near = _near_misses(slug, days)
    if near:
        text = {r["key"]: " ".join(filter(None, [r["title"], r["teaser"], r["bullets"], r["description"]])) for r in rows}
        for m in near:
            if m["key"] not in out and m["key"] in text:
                out[m["key"]] = {"key": m["key"], "title": m["title"], "day": m["day"], "kind": "near miss",
                                 "track": m["track"] or default, "text": text[m["key"]]}
    return [a for a in out.values() if track in (None, a["track"])]


def _near_misses(slug: str, days: int) -> list[dict[str, Any]]:
    try:
        import panel
        return panel.maybes(slug, days=days, n=10 ** 6)
    except Exception:                               # the near-miss list is a bonus: never break the command over it
        return []


def gaps(slug: str, days: int = 30, track: str | None = None) -> dict[str, Any]:
    targets = read_json(cand_dir(slug) / "targets.json", {})
    cvs = cv_texts(slug, targets)
    ads = relevant_ads(slug, days, track)
    profile = profile_text(slug)
    vocab: dict[str | None, list[tuple[str, str]]] = {}
    terms: dict[str, dict[str, Any]] = {}
    checked = 0
    for ad in ads:
        cv = cvs.get(ad["track"]) if ad["track"] in cvs else next(iter(cvs.values()), None)
        if cv is None:
            continue
        checked += 1
        text = _norm(ad["text"])
        for term, prio in vocab.setdefault(ad["track"], vocabulary(slug, ad["track"])):
            if not _has(term, text):
                continue
            t = terms.setdefault(term, {"term": term, "priority": prio, "ads": 0, "not_in_cv": 0, "status": "covered", "examples": []})
            t["ads"] += 1
            st = status_of(term, cv, profile)
            if st != "covered":
                t["not_in_cv"] += 1
                t["status"] = st
            if len(t["examples"]) < 2 and ad["title"] not in t["examples"]:
                t["examples"].append(ad["title"])
    rows = sorted((t for t in terms.values() if t["ads"] >= MIN_ADS), key=lambda t: (-t["ads"], t["term"]))
    for t in rows:
        t["pct"] = round(100 * t["ads"] / checked)
    by = lambda s: [t for t in rows if t["status"] == s]
    return {"days": days, "track": track, "ads": checked, "near_misses": sum(a["kind"] == "near miss" for a in ads),
            "have_it": by("have it"), "gaps": by("gap"), "covered": by("covered")}


def _section(title: str, hint: str, rows: list[dict[str, Any]], total: int) -> list[str]:
    if not rows:
        return []
    lines = ["", f"## {title}", hint, "", "| Term | Ads | % | Example titles |", "|---|---|---|---|"]
    for i, t in enumerate(rows):
        ex = "; ".join(t["examples"]) if i < TOP_EXAMPLES else ""
        lines.append(f"| {t['term']} | {t['ads']} of {total} | {t['pct']}% | {ex} |")
    return lines


def table(r: dict[str, Any]) -> str:
    if not r["ads"]:
        return f"No relevant ads with a readable CV in the last {r['days']} days (needs jobs.db and a master CV per track)."
    head = f"Skill gaps over {r['ads']} relevant ads, last {r['days']} days" + \
           (f", track {r['track']}" if r["track"] else "") + (f" ({r['near_misses']} near misses)" if r["near_misses"] else "")
    lines = [head]
    lines += _section("Have it, not in the CV (quick win)", "Add each only where it truthfully fits: the ads ask for it and you have it.",
                      r["have_it"], r["ads"])
    lines += _section("Gap (learning candidates)", "Not in your CV or your intake. A course, certificate or project is the way in; "
                      "do not add the word to the CV until it is true.", r["gaps"], r["ads"])
    if r["covered"]:
        lines += ["", "Already in your CV: " + ", ".join(f"{t['term']} ({t['ads']})" for t in r["covered"][:12])]
    if not (r["have_it"] or r["gaps"]):
        lines += ["", f"No term missing from the CV appears in {MIN_ADS}+ ads."]
    return "\n".join(lines)


def report_lines(slug: str, day: str, min_ads: int = 10, top: int = 3) -> list[str]:
    """A few lines for the daily report: Mondays only, and only with at least `min_ads` relevant ads in the last 30 days."""
    try:
        if date.fromisoformat(day).weekday() != 0:
            return []
        r = gaps(slug)
    except Exception:
        return []
    if r["ads"] < min_ads or not (r["have_it"] or r["gaps"]):
        return []
    lines = [f"## 🎯 Skill gaps (weekly, {r['ads']} relevant ads, last {r['days']} days)", ""]
    for label, rows in (("Have it, not in your CV (add where true)", r["have_it"]), ("Gaps (worth learning)", r["gaps"])):
        if rows:
            lines.append(f"- **{label}:** " + ", ".join(f"{t['term']} ({t['ads']} ads)" for t in rows[:top]))
    return lines + [f"- Full list: `job gaps {slug}`", ""]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("--days", type=int, default=30); ap.add_argument("--track")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = gaps(a.slug, a.days, a.track)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else table(r))


if __name__ == "__main__":
    main()
