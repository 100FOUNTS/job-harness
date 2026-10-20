"""Document lint: the rules learned the hard way, checked as code before anything is sent.

  job lint <slug> <file.docx|file.pdf> [--kind cv|letter]

Checks
- never_mention terms from intake.rules (e.g. visa, sponsorship) → must not appear
- never_include terms from intake.rules (e.g. practice exercises) → must not appear
- .docx: no tables, text boxes, images, headers/footers (ATS read them badly)
- .docx: fonts with ligatures (Calibri, Cambria) break PDF text extraction ("restora on") → Arial only
- .pdf: page count (CV ≤ 3, letter = 1) and that text extracts at all
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

from common import load_intake
from facts import extract_text

LIGATURE_FONTS = ("Calibri", "Cambria", "Candara", "Constantia")


def pdf_pages(path: Path) -> int:
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True).stdout
    m = re.search(r"Pages:\s+(\d+)", out)
    return int(m.group(1)) if m else 0


def lint(slug: str, path: Path, kind: str) -> dict[str, Any]:
    rules = load_intake(slug).get("rules", {})
    text = extract_text(path)
    issues: list[str] = []
    for term in rules.get("never_mention", []):
        if re.search(rf"\b{re.escape(term)}\b", text, re.I):
            issues.append(f"forbidden term: '{term}'")
    for term in rules.get("never_include", []):
        if re.search(re.escape(term), text, re.I):
            issues.append(f"must not include: '{term}'")
    if path.suffix == ".docx":
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
            styles = z.read("word/styles.xml").decode("utf-8", "ignore") if "word/styles.xml" in names else ""
        if "<w:tbl>" in xml:
            issues.append("contains tables (ATS risk)")
        if "<w:txbxContent" in xml:
            issues.append("contains text boxes (ATS risk)")
        if any(n.startswith("word/media/") for n in names):
            issues.append("contains images (ATS risk)")
        if any(re.match(r"word/(header|footer)\d*\.xml", n) for n in names):
            issues.append("has header/footer (many ATS skip them)")
        fonts = set(re.findall(r'w:ascii="([^"]+)"', xml + styles))
        bad = [f for f in fonts if f in LIGATURE_FONTS]
        if bad:
            issues.append(f"ligature font {bad}: PDF text breaks ('restora on'); use Arial")
    if path.suffix == ".pdf":
        pages = pdf_pages(path)
        if len(text.split()) < 50:
            issues.append("PDF text does not extract (scanned or image-based?)")
        if kind == "cv" and pages > 3:
            issues.append(f"CV has {pages} pages (max 3)")
        if kind == "letter" and pages != 1:
            issues.append(f"cover letter has {pages} pages (must be 1)")
    return {"file": str(path), "ok": not issues, "issues": issues}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("file"); ap.add_argument("--kind", choices=["cv", "letter"], default="cv")
    a = ap.parse_args()
    r = lint(a.slug, Path(a.file), a.kind)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
