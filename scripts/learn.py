"""Harness memory: lessons learned while doing the work, so the next candidate does not repeat them.

  job learn log --kind harness|platform|candidate --area seek|linkedin|docs|ats|forms --lesson "..." [--pattern key] [--candidate slug]
  job learn list [--area seek]
  job learn set-status <n|pattern> active|applied|dismissed

Optional fields per line: pattern (short key that groups recurring lessons), status (active by default).
Lessons are public in the repo: write the rule, never a person's data. A harness or platform lesson never carries a
candidate, and one that names a known candidate (name or email) is refused.
`job status --context` shows up to 5 active lessons relevant to the next step.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from common import ROOT, cand_dir, list_candidates, now_iso, read_json

LOG = ROOT / "learn" / "observations.jsonl"
STATUSES = ("active", "applied", "dismissed")


def load_lines() -> list[tuple[str, dict[str, Any]]]:
    """(raw line, parsed) for every lesson; the raw text is kept so a status change rewrites only its own line."""
    out = []
    for line in LOG.read_text().splitlines() if LOG.exists() else []:
        if line.strip():
            out.append((line, json.loads(line)))
    return out


def personal(lesson: str) -> str:
    """A known candidate's name or email found in the text ('' if none)."""
    low = lesson.lower()
    for slug in list_candidates():
        try:
            intake = read_json(cand_dir(slug) / "intake.json", {})
        except Exception:
            continue
        for v in (intake.get("name"), intake.get("email")):
            if isinstance(v, str) and len(v) >= 5 and v.lower() in low:
                return v
    return ""


def relevant(areas: list[str], n: int = 5) -> list[str]:
    """Active, non-personal lessons for these areas (newest first), topped up with the latest others; one line each."""
    rows = [o for _, o in load_lines() if o.get("status", "active") == "active" and not o.get("candidate")]
    rows.reverse()
    pick = [o for o in rows if o["area"] in areas][:n]
    pick += [o for o in rows if o not in pick and o.get("kind") == "harness"][:n - len(pick)]
    return [" ".join(o["lesson"].split())[:220] for o in pick]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("log"); p.add_argument("--kind", required=True, choices=["harness", "platform", "candidate"])
    p.add_argument("--area", required=True); p.add_argument("--lesson", required=True); p.add_argument("--candidate", default="")
    p.add_argument("--pattern", default="")
    p = sub.add_parser("list"); p.add_argument("--area")
    p = sub.add_parser("set-status"); p.add_argument("which", help="line number from `job learn list`, or a pattern")
    p.add_argument("status", choices=STATUSES)
    a = ap.parse_args()
    if a.cmd == "log":
        who = personal(a.lesson) if a.kind != "candidate" else ""
        if who:
            raise SystemExit(f"Lessons are public: remove the personal data ({who!r}) and say the rule instead.")
        o: dict[str, Any] = {"date": now_iso(), "kind": a.kind, "area": a.area, "lesson": a.lesson,
                             "candidate": a.candidate if a.kind == "candidate" else ""}
        if a.pattern:
            o["pattern"] = a.pattern
        o["status"] = "active"
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
        print("logged")
    elif a.cmd == "set-status":
        rows = load_lines()
        hit = [i for i, (_, o) in enumerate(rows) if (str(i + 1) == a.which or o.get("pattern") == a.which)]
        if not hit:
            raise SystemExit(f"No lesson numbered or patterned {a.which!r}: see `job learn list`.")
        text = [raw for raw, _ in rows]
        for i in hit:
            text[i] = json.dumps(rows[i][1] | {"status": a.status}, ensure_ascii=False)
        LOG.write_text("\n".join(text) + "\n")
        print(f"{len(hit)} lesson(s) -> {a.status}")
    else:
        for i, (_, o) in enumerate(load_lines(), 1):
            if not a.area or o["area"] == a.area:
                st = o.get("status", "active")
                print(f"{i}. [{o['area']}]{'' if st == 'active' else f' ({st})'} {o['lesson']}")


if __name__ == "__main__":
    main()
