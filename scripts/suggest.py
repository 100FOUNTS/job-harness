"""Filter suggestions learned from rescues, and the near-miss keyword matching the panel's "Maybe worth a look" uses.

  python3 scripts/suggest.py <slug> list              pending title phrases (rescued ads the filter had dropped)
  python3 scripts/suggest.py <slug> clear [phrase]    forget one phrase, or all of them (after adding them to targets.json)

When the person rescues an ad dropped only because its title matched no track, the role phrase of that title is stored
in candidates/<slug>/suggestions.json: {"title_include": [{"phrase", "track", "from_key", "date"}]}. targets.json is
sealed and needs the person's approval, so nothing here edits it: Claude proposes the phrases, the person approves.
"""
from __future__ import annotations

import argparse
import re
from datetime import date
from typing import Any

from common import cand_dir, read_json, save_json

LEVEL_WORDS = {"senior", "sr", "junior", "jr", "lead", "graduate", "grad", "intermediate", "principal", "mid", "mid-level",
               "entry", "entry-level", "trainee", "contract", "contractor", "temporary", "temp", "casual", "permanent",
               "part-time", "full-time", "parttime", "fulltime", "fixed-term", "level", "i", "ii", "iii", "iv", "x1", "x2",
               "x3", "x4", "x5"}
GENERIC = {"developer", "engineer", "officer", "analyst", "manager", "assistant", "coordinator", "specialist", "consultant",
           "advisor", "adviser", "administrator", "technician", "scientist", "designer", "support", "planner", "lead"}
SEPARATORS = re.compile(r"\s+[-–—|]\s+|[,:;(]|\s+/\s+|\s+@\s+| at ")
NOISE = re.compile(r"\b(level\s*\d+|l\d|\d+\s*(?:-\s*)?(?:month|mth|year|yr)s?|fixed[ -]term|full[ -]time|part[ -]time|"
                   r"entry[ -]level|mid[ -]level|\d+(?:\.\d+)?\s*fte)\b", re.I)
MAX_WORDS = 4
MIN_SCORE = 3


def path(slug: str):
    return cand_dir(slug) / "suggestions.json"


def phrase(title: str) -> str:
    """The core role phrase of an ad title: lower-case, without seniority/level words, location or department suffixes
    (after ' - ', ' | ', ' – ' or a comma) and at most four words. "" when nothing specific is left."""
    t = re.sub(r"\([^)]*\)", " ", title or "").lower()
    t = SEPARATORS.split(t)[0]
    t = NOISE.sub(" ", t)
    words = [w.strip(" .,;:!?*&+_\"'") for w in t.split()]
    words = [w for w in words if w and w not in LEVEL_WORDS and not re.fullmatch(r"x\d+|\d+", w)]
    out = " ".join(words[:MAX_WORDS]).strip()
    if not out or (len(words) == 1 and out in GENERIC):
        return ""
    return out


def keyword_regex(term: str) -> str:
    """Word-boundary pattern for a keyword. Stems are common in targets ("hydrolog"), so a keyword of 6+ letters may
    continue ("hydrology"); short ones ("gis", "sql") must end at a word boundary."""
    core = re.escape(term.lower().strip())
    return r"(?<![\w])" + core + (r"\w*" if len(term.strip()) >= 6 and term.strip()[-1].isalpha() else r"(?![\w])")


def keyword_weights(targets: dict[str, Any]) -> dict[str, dict[str, int]]:
    """track id → {keyword: weight}, core = 2, support = 1."""
    out: dict[str, dict[str, int]] = {}
    for t in targets.get("tracks", []):
        kw = t.get("keywords") or {}
        w = {k.lower().strip(): 1 for k in kw.get("support", []) if k.strip()}
        w |= {k.lower().strip(): 2 for k in kw.get("core", []) if k.strip()}
        out[t["id"]] = w
    return out


def compile_terms(terms: list[str]) -> re.Pattern[str] | None:
    """One pass over the text: one capture group per term, longest terms first."""
    ordered = sorted(set(terms), key=lambda x: (-len(x), x))
    return re.compile("|".join(f"({keyword_regex(x)})" for x in ordered), re.I) if ordered else None


class Matcher:
    """Finds which keywords of which track appear in a text (compile once, use for thousands of ads)."""
    def __init__(self, targets: dict[str, Any]):
        self.weights = keyword_weights(targets)
        self.terms = sorted({k for w in self.weights.values() for k in w}, key=lambda x: (-len(x), x))
        self.rx = compile_terms(self.terms)

    def found(self, text: str) -> set[str]:
        return {self.terms[m.lastindex - 1] for m in self.rx.finditer(text)} if self.rx else set()

    def score(self, found: set[str]) -> int:
        """Distinct keywords across all tracks; a keyword in several tracks counts once, at its highest weight."""
        return sum(max(w.get(k, 0) for w in self.weights.values()) for k in found)

    def best_track(self, found: set[str]) -> str:
        """The track whose keywords hit most (weighted); '' when none hit. Ties go to the earlier (higher priority) track."""
        best, top = "", 0
        for tid, w in self.weights.items():
            s = sum(w.get(k, 0) for k in found)
            if s > top:
                best, top = tid, s
        return best

    def chips(self, found: set[str], n: int = 4) -> list[str]:
        return sorted(found, key=lambda k: (-max(w.get(k, 0) for w in self.weights.values()), k))[:n]


def load(slug: str) -> list[dict[str, Any]]:
    return read_json(path(slug), {}).get("title_include", [])


def pending(slug: str) -> list[dict[str, Any]]:
    """Suggestions still worth acting on: those already added to a track's title_include drop out by themselves."""
    targets = read_json(cand_dir(slug) / "targets.json", {})
    have = {x.lower().strip() for t in targets.get("tracks", []) for x in t.get("title_include", [])}
    return [s for s in load(slug) if s["phrase"].lower() not in have]


def record(slug: str, title: str, key: str, track: str) -> str:
    """Remember the phrase of a rescued title. Returns the phrase ("" when nothing usable or already suggested)."""
    p = phrase(title)
    if not p:
        return ""
    have = load(slug)
    targets = read_json(cand_dir(slug) / "targets.json", {})
    covered = {x.lower().strip() for t in targets.get("tracks", []) for x in t.get("title_include", [])}
    if p in covered or any(s["phrase"] == p for s in have):
        return ""
    have.append({"phrase": p, "track": track, "from_key": key, "date": date.today().isoformat()})
    save_json(path(slug), {"title_include": have})
    return p


def clear(slug: str, which: str | None = None) -> int:
    have = load(slug)
    keep = [s for s in have if which and s["phrase"] != which.lower().strip()]
    if len(keep) != len(have):
        save_json(path(slug), {"title_include": keep})
    return len(have) - len(keep)


def line(slug: str) -> str:
    """The one line status shows when there is something pending ("" otherwise)."""
    ph = [s["phrase"] for s in pending(slug)]
    return (f"Filter suggestions from rescues: {', '.join(ph)} — add them with Claude (targets need re-approval)") if ph else ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("cmd", choices=["list", "clear"]); ap.add_argument("phrase", nargs="?")
    a = ap.parse_args()
    if a.cmd == "list":
        rows = pending(a.slug)
        for s in rows:
            print(f"{s['phrase']}  (track {s['track'] or '?'}, from {s['from_key']}, {s['date']})")
        if not rows:
            print("No pending suggestions.")
    else:
        print(f"Cleared {clear(a.slug, a.phrase)} suggestion(s).")


if __name__ == "__main__":
    main()
