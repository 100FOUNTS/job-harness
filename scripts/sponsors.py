"""Visa sponsor lists: is the employer of an ad on a Home Affairs list of sponsors? For the person's eyes only.

  job sponsors import --from <noan-agent>/supabase/migrations   → data/sponsors.json (git-ignored)
  job sponsors check "Rio Tinto"                                → exact / possible matches with the list and its date

Sources (FOI releases, read by OCR in the noan-agent project, which documents the method and its error rate):
- accredited sponsors as at 15 Jan 2025 (FA 25/01/01229)            migration 0060
- active Standard Business Sponsors, 31 Oct 2023 and 30 Apr 2025     migration 0087 (re-OCR that replaced 0081/0086)

What a match does NOT say: that this employer sponsors this role, or that it still sponsors today. What a miss does
NOT say: that the employer does not sponsor (the lists are snapshots and OCR loses rows). An ad posted by a
recruitment agency names the agency, not the employer. The package shows the matched legal name so the person
judges. Never written into a CV, letter or form: `intake.rules.never_mention` and `job lint` still apply there.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from common import read_json, save_json, sponsors_file

# migration file → table whose rows are read; every row starts with ('<normalized>','<as printed>','<YYYY-MM-DD>'
DATA: Path | None = None     # override of the data file (tests); None = common.sponsors_file()
SOURCES = {"0060_accredited_sponsors.sql": ("accredited_sponsors", "accredited"),
           "0087_active_sponsors_reocr.sql": ("active_sponsor_lists", "active")}
FORMS = [(r"\bPTY\.?\s*LIMITED\b", "PTY LTD"), (r"\bPROPRIETARY\s+LIMITED\b", "PTY LTD"),
         (r"\bLIMITED\b", "LTD"), (r"\bINCORPORATED\b", "INC")]
# Dropped only to compare an ad's short name ("Rio Tinto") with a legal name ("RIO TINTO SERVICES LTD")
GENERIC = {"PTY", "LTD", "INC", "CO", "CORP", "CORPORATION", "GROUP", "HOLDINGS", "AUSTRALIA", "AUSTRALIAN", "AU",
           "THE", "AND"}
ROW = re.compile(r"^\('((?:[^']|'')*)','((?:[^']|'')*)','(\d{4}-\d{2}-\d{2})'")


def data_file() -> Path:
    return DATA or sponsors_file()


def normalize(raw: str) -> str:
    """Same rule as noan-agent's normalizeSponsorName, so names compare the way that project indexed them."""
    out = "".join(c for c in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(c)).upper()
    for rx, rep in FORMS:
        out = re.sub(rx, rep, out)
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", out).split())


def core(norm: str) -> str:
    return " ".join(w for w in norm.split() if w not in GENERIC)


def import_lists(src: Path) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    for fname, (table, kind) in SOURCES.items():
        inside = False
        for line in (src / fname).read_text(encoding="utf-8").splitlines():
            if line.startswith("insert into "):
                inside = line.startswith(f"insert into {table} ")
                continue
            m = ROW.match(line) if inside else None
            if m:
                e = entries.setdefault(m.group(1), {"name": m.group(2).replace("''", "'"), "lists": []})
                tag = f"{kind} {m.group(3)}"
                if tag not in e["lists"]:
                    e["lists"].append(tag)
    data = {"source": str(src), "lists": sorted({t for e in entries.values() for t in e["lists"]}), "entries": entries}
    save_json(data_file(), data)
    return {"companies": len(entries), "lists": data["lists"], "file": str(data_file())}


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, Any], dict[str, list[str]]]:
    entries = read_json(data_file(), {}).get("entries", {})
    by_core: dict[str, list[str]] = {}
    for norm in entries:
        by_core.setdefault(core(norm), []).append(norm)
    return entries, by_core


def lookup(company: str) -> dict[str, Any] | None:
    """{'match': 'exact'|'likely'|'possible', 'names': [...], 'lists': [...], 'more': n}; None without data or match.
    exact = same legal name; likely = same name once Pty/Ltd/Group/Australia are set aside ("Verse" and VERSE GROUP
    PTY LTD may still be two companies); possible = the ad's name is the start of a listed name (2+ words or 5+
    letters, so "Apex" does not match every APEX ... PTY LTD)."""
    entries, by_core = _index()
    norm = normalize(company or "")
    if not entries or not norm:
        return None
    c = core(norm)
    hits, match = ([norm], "exact") if norm in entries else (by_core.get(c, []), "likely")
    if not hits and (len(c.split()) >= 2 or len(c) >= 5):
        hits, match = [n for k, ns in by_core.items() if k.startswith(c + " ") for n in ns], "possible"
    if not hits:
        return None
    hits.sort(key=lambda n: (max(t.split()[1] for t in entries[n]["lists"]), n), reverse=True)   # newest list first
    lists = sorted({t for n in hits for t in entries[n]["lists"]}, reverse=True)
    return {"match": match, "names": [entries[n]["name"] for n in hits[:2]], "lists": lists, "more": max(0, len(hits) - 2)}


def describe(company: str, lang: str = "en") -> str:
    """One line for the daily package; '' when there is no sponsor data at all."""
    if not _index()[0]:
        return ""
    r = lookup(company)
    es = lang == "es"
    if not r:
        return "no aparece en las listas (no significa que no patrocine)" if es else "not on the lists (that does not mean it does not sponsor)"
    word = ({"exact": "sí", "likely": "probable", "possible": "posible"} if es
            else {"exact": "yes", "likely": "likely", "possible": "possible"})[r["match"]]
    more = (f" +{r['more']} más" if es else f" +{r['more']} more") if r["more"] else ""
    return f"{word}: {' / '.join(r['names'])}{more} ({', '.join(r['lists'])})"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("import"); i.add_argument("--from", dest="src", required=True)
    c = sub.add_parser("check"); c.add_argument("company")
    a = ap.parse_args()
    if a.cmd == "import":
        print(json.dumps(import_lists(Path(a.src).expanduser()), indent=2))
    else:
        print(json.dumps(lookup(a.company) or {"match": None}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
