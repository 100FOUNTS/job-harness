"""Claims registry: every figure in a CV or cover letter must come from facts.json.

Tailored documents are written by the agent; this check makes sure it never invents a number
(a percentage, a dollar amount, a count) that the candidate has not confirmed.

  job facts <slug> show
  job facts <slug> add <id> <value> --text "more than 200 employees trained" --source "CV 2025"
  job facts <slug> verify <file.docx|file.pdf|file.md|file.json>   → ok: true/false + unknown figures
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from common import cand_dir, now_iso, read_json, save_json

NUM = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?[KkMm]?|\d+(?:\.\d+)?\s?%|\b\d[\d,]*(?:\.\d+)?\b")
YEAR = re.compile(r"^(19[5-9]\d|20[0-4]\d)$")
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
DATE = re.compile(rf"\b\d{{1,2}}(st|nd|rd|th)?\s+({MONTHS})[a-z]*\.?\s+\d{{4}}\b|\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b"
                  rf"|\b(ref|reference|job id|id)[:#\s]+[\w-]+", re.I)


def load(slug: str) -> dict[str, Any]:
    return read_json(cand_dir(slug) / "facts.json", {"claims": [], "allow": []})


def norm(tok: str) -> str:
    t = tok.replace(" ", "").replace(",", "").lower()
    return t.rstrip(".")


def extract_text(path: Path) -> str:
    path = Path(path)
    if path.suffix == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        return re.sub(r"<[^>]+>", " ", xml.replace("</w:p>", "\n"))
    if path.suffix == ".pdf":
        return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True).stdout
    if path.suffix == ".json":
        out: list[str] = []

        def walk(x: Any) -> None:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict):
                [walk(v) for k, v in x.items() if not k.startswith("_")]
            elif isinstance(x, list):
                [walk(v) for v in x]
        walk(read_json(path))
        return "\n".join(out)
    return path.read_text()


def known_values(f: dict[str, Any]) -> set[str]:
    vals = {norm(str(c["value"])) for c in f["claims"] if c.get("status", "approved") == "approved"}
    vals |= {norm(str(a)) for a in f.get("allow", [])}
    return vals


def verify(slug: str, path: Path) -> dict[str, Any]:
    f = load(slug)
    known = known_values(f)
    unknown = []
    for m in NUM.finditer(DATE.sub(" ", extract_text(path))):     # dates and reference numbers are not claims
        n = norm(m.group())
        bare = n.lstrip("$").rstrip("%km")
        if YEAR.match(bare) or len(bare.replace(".", "")) < 2:
            continue                       # years and single digits (bullet counts, "3 options") are not claims
        if n in known or bare in known:
            continue
        unknown.append(m.group().strip())
    return {"file": str(path), "ok": not unknown, "unknown_figures": sorted(set(unknown))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    p = sub.add_parser("add"); p.add_argument("id"); p.add_argument("value")
    p.add_argument("--text", required=True); p.add_argument("--source", default="")
    p = sub.add_parser("verify"); p.add_argument("file")
    a = ap.parse_args()
    if a.cmd == "show":
        print(json.dumps(load(a.slug), ensure_ascii=False, indent=2))
    elif a.cmd == "add":
        f = load(a.slug)
        f["claims"] = [c for c in f["claims"] if c["id"] != a.id]
        f["claims"].append({"id": a.id, "value": a.value, "text": a.text, "source": a.source,
                            "status": "approved", "date": now_iso()})
        save_json(cand_dir(a.slug) / "facts.json", f); print(f"claim {a.id} = {a.value}")
    else:
        r = verify(a.slug, Path(a.file))
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
