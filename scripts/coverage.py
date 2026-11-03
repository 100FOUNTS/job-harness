"""Keyword coverage: what the ad asks for, checked against the text an ATS reads from the CV. Ideas from ai-job-search
(/apply step 5d) and career-ops (jd-skill-gap.mjs); Jobscan sells the same view as a match percentage.

  job coverage <slug> <cv.pdf|cv.docx> --job <key>     (or --text "ad text") → table + JSON

The terms are the track keywords of targets.json (core and support) that appear in the ad, plus common technologies
(TECH, priority "ad") the track lists do not name: an ad that demands .NET must show .NET as a gap even when .NET is
in no track (real miss: a .NET full-stack role, 2026-11-03). Each one is:
  covered    in the CV text
  have it    not in the CV, but in intake.json (skills, coursework, experience): add it where it truthfully fits
  gap        in neither: leave it out of the CV (never stuff a keyword); the letter can address it honestly
No LLM: the ad's own vocabulary beyond the track keywords is not seen, so a low percentage is a prompt to read the
ad, not a verdict.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import cand_dir, read_json


TECH = [".net", "asp.net", "c#", "entity framework", "vb.net", "golang", "rust", "kotlin", "swift", "scala", "php", "ruby",
        "c++", "matlab", "azure", "gcp", "google cloud", "kubernetes", "terraform", "ansible", "kafka", "rabbitmq", "spark",
        "airflow", "databricks", "snowflake", "power bi", "tableau", "sap", "salesforce", "servicenow", "dynamics 365",
        "sharepoint", "mongodb", "redis", "elasticsearch", "graphql", "vue", "svelte", "django", "flask", "laravel",
        "spring boot", "node.js", "typescript", "react native", "flutter", "ios", "android", "linux", "powershell",
        "jenkins", "github actions", "gitlab", "selenium", "cypress", "playwright", "scada", "plc", "opc ua", "mqtt",
        "arcgis", "qgis", "fme", "pytorch", "tensorflow", "langchain", "openai", "sql server", "oracle", "mysql",
        "postgresql", "kanban", "itil", "togaf", "cissp", "pmp", "prince2"]


def _norm(text: str) -> str:
    return re.sub(r"[-\u2010-\u2015/]", " ", text.lower())            # full-stack = full stack, CI/CD = ci cd


def _has(term: str, text: str) -> bool:
    return bool(re.search(rf"(?<![\w]){re.escape(_norm(term))}", text))


def coverage(slug: str, ad_text: str, cv_text: str, track_id: str | None = None) -> dict[str, Any]:
    from prepare import track_keywords
    base = cand_dir(slug)
    targets = read_json(base / "targets.json")
    tracks = [t for t in targets["tracks"] if track_id in (None, t["id"])] or targets["tracks"]
    ad, cv = _norm(ad_text), _norm(cv_text)
    profile = _norm(json.dumps(read_json(base / "intake.json"), ensure_ascii=False))
    rows, seen = [], set()
    for t in tracks:
        kw = track_keywords(slug, t)
        for prio in ("core", "support"):
            for term in kw[prio]:
                if term in seen or not _has(term, ad):
                    continue
                seen.add(term)
                status = "covered" if _has(term, cv) else "have it" if _has(term, profile) else "gap"
                rows.append({"term": term, "priority": prio, "status": status})
    for term in TECH:
        if term in seen or not _has(term, ad):
            continue
        seen.add(term)
        rows.append({"term": term, "priority": "ad",
                     "status": "covered" if _has(term, cv) else "have it" if _has(term, profile) else "gap"})
    core = [r for r in rows if r["priority"] == "core"]
    pct = round(100 * sum(r["status"] == "covered" for r in rows) / len(rows)) if rows else None
    return {"match_pct": pct, "terms": rows,
            "core_missing": [r["term"] for r in core if r["status"] != "covered"],
            "have_it": [r["term"] for r in rows if r["status"] == "have it"],
            "gaps": [r["term"] for r in rows if r["status"] == "gap"]}


def table(r: dict[str, Any]) -> str:
    lines = [f"Match: {r['match_pct']}%" if r["match_pct"] is not None else "Match: no track keyword in the ad",
             "", "| Term | Priority | Status |", "|---|---|---|"]
    return "\n".join(lines + [f"| {x['term']} | {x['priority']} | {x['status']} |" for x in r["terms"]])


def main() -> None:
    from facts import extract_text
    from jobdb import descriptions
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("cv"); ap.add_argument("--job"); ap.add_argument("--text")
    ap.add_argument("--track"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    ad = a.text or (descriptions(a.slug, [a.job]).get(a.job, "") if a.job else "")
    if not ad:
        raise SystemExit("No ad text: pass --text, or --job <key> for an ad whose description is in jobs.db")
    cv = Path(a.cv) if Path(a.cv).is_absolute() or Path(a.cv).exists() else cand_dir(a.slug) / a.cv
    r = coverage(a.slug, ad, extract_text(cv), a.track)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else table(r))


if __name__ == "__main__":
    main()
