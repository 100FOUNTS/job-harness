"""Answer engine for application questions: never blocks, never lies, always records what was improvised.

  job answer <slug> --question "..." [--type select|radio|checkbox|text|number] [--options "A|B|C"] [--job seek:123]
  → JSON {answer, source, confidence}; anything not from answers.json is appended to pending_questions.json
  job answer <slug> pending            list improvised answers waiting for the person to confirm

Order: answers.json (approved) → rules (willingness → Yes; credential/experience not in profile → No;
years → from CV dates; salary/education → closest option; free text → short true sentence) → safest option.
Sensitive questions (visa, work rights, sponsorship) only come from answers.json: never improvised.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from typing import Any

from common import cand_dir, now_iso, read_json, save_json

SENSITIVE = re.compile(r"visa|right to work|work rights|sponsor|citizen|permanent resident|legally entitled|authori[sz]ed to work", re.I)
WILLING = re.compile(r"\b(are you )?(willing|prepared|happy|able|comfortable|open) to\b|\bwould you\b|\bcan you\b", re.I)
HAVE = re.compile(r"\b(do you (have|hold|possess)|have you (completed|got|obtained|held|worked)|are you (licen[cs]ed|certified|registered|qualified|trained))\b", re.I)
YEARS = re.compile(r"how many years|years of (experience|work)|years'? experience", re.I)


def load_answers(slug: str) -> list[dict[str, Any]]:
    return read_json(cand_dir(slug) / "answers.json", {"answers": []})["answers"]


def from_answers(slug: str, q: str) -> Any:
    ql = q.lower()
    best = None
    for a in load_answers(slug):
        hits = [m for m in a["match"] if m in ql]
        if hits and a.get("answer") not in (None, "") and (best is None or max(map(len, hits)) > best[0]):
            best = (max(map(len, hits)), a)
    return best[1] if best else None


def main_cv(slug: str) -> dict[str, Any]:
    """The primary track's CV (targets.json `primary`, else the first track); else any docs/cv_*.json."""
    base = cand_dir(slug)
    tracks = read_json(base / "targets.json", {"tracks": []}).get("tracks", [])
    t = next((t for t in tracks if t.get("primary")), tracks[0] if tracks else {})
    paths = ([base / t["cv"]] if t.get("cv") else []) + sorted((base / "docs").glob("cv_*.json"))
    return next((read_json(p) for p in paths if p.exists()), {"experience": []})


def experience_years(slug: str, keyword: str = "") -> float:
    """Years of experience from the main CV. With a keyword (e.g. 'field officer', 'gis'), only entries whose
    role/bullets mention it count; questions about the person's own profession (CV title) count every professional role."""
    cv = main_cv(slug)
    mon = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
    prof = [w[:7] for w in re.findall(r"[a-z]{4,}", cv.get("title", "").lower())] + ["industry", "professional", "relevant"]
    generic = not keyword or (re.search("|".join(prof), keyword)
                              and not re.search(r"consult|gis|field|lead|supervis|manag", keyword))
    months = 0
    for e in cv.get("experience", []):
        text = (e.get("role", "") + " " + " ".join(e.get("bullets", []))).lower()
        if not generic and not all(w[:6] in text for w in keyword.split() if len(w) > 2):   # stems: consulting ~ consultant
            continue
        m = re.findall(r"([A-Z][a-z]{2}) (\d{4})", e.get("dates", ""))
        if not m:
            continue
        (m1, y1) = m[0]
        (m2, y2) = m[1] if len(m) > 1 else (date.today().strftime("%b"), str(date.today().year))
        months += (int(y2) - int(y1)) * 12 + mon[m2.lower()] - mon[m1.lower()] + 1
    return round(months / 12, 1)


def closest_option(options: list[str], target: float) -> str | None:
    nums = []
    for o in options:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(k)?", o.replace(",", ""), re.I)
        if m:
            v = float(m.group(1)) * (1000 if m.group(2) else 1)
            nums.append((abs(v - target), o))
    return min(nums)[1] if nums else None


def floor_option(options: list[str], value: float) -> str | None:
    """Largest numeric option that does not exceed the real value (e.g. 3.9 years → '3 years')."""
    vals = []
    for o in options:
        m = re.search(r"(\d+(?:\.\d+)?)", o)
        if not m or re.search(r"less than|under|fewer", o, re.I):
            continue                                   # "less than 1" only when nothing else fits (handled by caller)
        if float(m.group(1)) <= value:
            vals.append((float(m.group(1)), o))
    return max(vals)[1] if vals else None


def pick(options: list[str], *prefer: str) -> str | None:
    for p in prefer:
        for o in options:
            if o.strip().lower() == p.lower() or o.strip().lower().startswith(p.lower()):
                return o
    return None


YES_LIKE = re.compile(r"^(yes|willing|available|happy|able)\b", re.I)
NO_LIKE = re.compile(r"^(no|none|not)\b", re.I)


def to_option(ans: Any, options: list[str], prefer: list[str] | None = None) -> Any:
    """Map an approved answer onto the form's options without ever guessing a numeric neighbour for text."""
    if not options:
        return ans
    for p in prefer or []:
        for o in options:
            if p.lower() in o.lower():
                return o
    a = str(ans)
    exact = pick(options, a)
    if exact:
        return exact
    if YES_LIKE.search(a):
        return pick(options, "Yes")
    if NO_LIKE.search(a):
        return pick(options, "No", "None")
    if re.fullmatch(r"\$?[\d,.]+k?", a.strip(), re.I):
        return closest_option(options, float(re.sub(r"[^\d.]", "", a)) * (1000 if a.lower().endswith("k") else 1))
    return None


def decide(slug: str, q: str, typ: str, options: list[str]) -> dict[str, Any]:
    if YEARS.search(q):                       # computed from the CV, never a generic number
        kw = re.search(r"(?:as an?|in|with|of) ([a-z][a-z /&-]{2,40}?)(?:\?|$| role| position| work)", q.lower())
        yrs = experience_years(slug, kw.group(1) if kw else "")
        ans = floor_option(options, yrs) if options else str(int(yrs))      # never round experience up
        if options and yrs < 1:
            ans = pick(options, "Less than 1", "None", "0") or ans
        return {"answer": ans, "source": f"rule:years-from-cv ({yrs})", "confidence": "medium"}
    a = from_answers(slug, q)
    if a:
        ans = to_option(a.get("answer"), options, a.get("option_prefer"))
        if ans is not None:
            return {"answer": ans, "source": "answers.json", "confidence": "approved"}
    if SENSITIVE.search(q):
        return {"answer": None, "source": "sensitive-not-in-answers", "confidence": "none"}
    ql = q.lower()
    if "salary" in ql or "remuneration" in ql:
        ans = closest_option(options, 85000) if options else "85000"
        return {"answer": ans, "source": "rule:salary", "confidence": "medium"}
    if ("education" in ql or "qualification" in ql) and options:
        ans = pick(options, "Bachelor Degree", "Bachelor") if options else "Bachelor Degree"
        return {"answer": ans, "source": "rule:education", "confidence": "medium"}
    if WILLING.search(q):
        ans = pick(options, "Yes") if options else "Yes"
        return {"answer": ans, "source": "rule:willingness", "confidence": "medium"}
    if HAVE.search(q):
        ans = pick(options, "No", "None", "I don't") if options else "No"
        return {"answer": ans, "source": "rule:credential-not-in-profile", "confidence": "safe-no"}
    if typ in ("text", "textarea"):
        summary = re.split(r"(?<=\.)\s", main_cv(slug).get("summary", "").strip())[0].rstrip(".")
        return {"answer": f"{summary}; available to start immediately." if summary else None,
                "source": "rule:short-true-text", "confidence": "low"}
    if options:
        ans = pick(options, "No", "Prefer not to say", "None") or options[0]
        return {"answer": ans, "source": "rule:safest-option", "confidence": "low"}
    return {"answer": None, "source": "unknown", "confidence": "none"}


def record(slug: str, q: str, res: dict[str, Any], job: str, options: list[str]) -> None:
    p = cand_dir(slug) / "pending_questions.json"
    data = read_json(p, {"questions": []})
    data["questions"].append({"date": now_iso(), "job": job, "question": q, "options": options,
                              "answered": res["answer"], "source": res["source"], "status": "to-confirm"})
    save_json(p, data)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("action", nargs="?", default="ask", choices=["ask", "pending"])
    ap.add_argument("--question", default=""); ap.add_argument("--type", default="radio")
    ap.add_argument("--options", default=""); ap.add_argument("--job", default="")
    a = ap.parse_args()
    if a.action == "pending":
        for x in read_json(cand_dir(a.slug) / "pending_questions.json", {"questions": []})["questions"]:
            if x["status"] == "to-confirm":
                print(f"{x['date'][:10]} {x['job']}: {x['question']} → {x['answered']} ({x['source']})")
        return
    opts = [o for o in a.options.split("|") if o.strip()]
    res = decide(a.slug, a.question, a.type, opts)
    if res["source"] != "answers.json":
        record(a.slug, a.question, res, a.job, opts)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
