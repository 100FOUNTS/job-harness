"""Companies the candidate does not want (rejected before, or simply no): their ads are dropped in triage.

  job block <slug> add "Company" [--note "why"]
  job block <slug> remove "Company"
  job block <slug> list

Stored in candidates/<slug>/blocklist.json. It is a preference, not an approval: it is not sealed, so changing it never
breaks the `targets` or `go-live` seals and needs no signature.

Matching is by WHOLE normalised name, never by substring: both names are lower-cased, accents and punctuation removed,
"&" read as "and", and legal filler words dropped (pty, ltd, limited, inc, llc, plc, the, and...). So "ACME Pty Ltd"
matches "Acme", but "Rio" does not block "Rio Tinto" and "Acme" does not block "Acme Australia" (add both to block both).
"""
from __future__ import annotations

import argparse
import re
import unicodedata
from typing import Any

from common import cand_dir, read_json, save_json, today

FILLER = {"the", "and", "pty", "ltd", "limited", "proprietary", "inc", "incorporated", "llc", "llp", "lp", "plc", "corp",
          "corporation", "co", "company"}


def normalise(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower().replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", s)
    return " ".join([w for w in words if w not in FILLER] or words)    # a name made only of filler keeps its words


def load(slug: str) -> list[dict[str, Any]]:
    return read_json(cand_dir(slug) / "blocklist.json", {"companies": []})["companies"]


def names(slug: str) -> list[str]:
    return [c["name"] for c in load(slug)]


def matches(company: str, blocked: list[str]) -> str | None:
    """The blocked name that is the same company as `company`, else None."""
    key = normalise(company)
    return next((b for b in blocked if normalise(b) == key), None) if key else None


def with_blocklist(slug: str, targets: dict[str, Any]) -> dict[str, Any]:
    """targets plus `exclude_companies` for triage.judge. Left untouched when the list is empty, so a candidate who
    never blocks anyone keeps the same jobs.db judgement hash; changing the list re-judges earlier company rejections."""
    blocked = names(slug)
    return targets | {"exclude_companies": blocked} if blocked else targets


def add(slug: str, company: str, note: str = "") -> str:
    company = company.strip()
    if not normalise(company):
        raise SystemExit("Give a company name.")
    items = load(slug)
    old = next((c for c in items if normalise(c["name"]) == normalise(company)), None)
    if old:
        old["note"] = note or old.get("note", "")
        msg = f"'{old['name']}' was already blocked."
    else:
        items.append({"name": company, "note": note, "added": today()})
        msg = f"Blocked '{company}': its ads are dropped from the next triage on."
    save_json(cand_dir(slug) / "blocklist.json", {"companies": items})
    return msg


def remove(slug: str, company: str) -> str:
    items = load(slug)
    keep = [c for c in items if normalise(c["name"]) != normalise(company)]
    if len(keep) == len(items):
        raise SystemExit(f"'{company}' is not on the list. `job block {slug} list`")
    save_json(cand_dir(slug) / "blocklist.json", {"companies": keep})
    return f"Unblocked '{company}'."


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add"); p.add_argument("company"); p.add_argument("--note", default="")
    p = sub.add_parser("remove"); p.add_argument("company")
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "add":
        print(add(a.slug, a.company, a.note))
    elif a.cmd == "remove":
        print(remove(a.slug, a.company))
    else:
        items = load(a.slug)
        for c in items:
            print(f"{c['name']}  ({c.get('added', '')}){'  - ' + c['note'] if c.get('note') else ''}")
        if not items:
            print("No companies blocked.")


if __name__ == "__main__":
    main()
