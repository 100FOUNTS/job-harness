"""Document lint: the rules learned the hard way, checked as code before anything is sent.

  job lint <slug> <file.docx|file.pdf> [--kind cv|letter]

Checks
- never_mention terms from intake.rules (e.g. visa, sponsorship) → must not appear
- never_include terms from intake.rules (e.g. practice exercises) → must not appear
- .docx: no tables, text boxes, images, headers/footers (ATS read them badly)
- .docx: fonts with ligatures (Calibri, Cambria) break PDF text extraction ("restora on") → Arial only
- .pdf: page count (CV ≤ 3, letter = 1) and that text extracts at all
- CV, read the way an ATS parser reads it: email and phone near the top, standard headings for experience,
  education and skills (summary before experience), month-year date ranges ("Mar 2019 – Present"),
  no glyphs that parse as garbage (ligatures ﬁ/ﬂ, U+FFFD, private-use symbols)
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


MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
HEADINGS = {"experience": r"(work|professional|relevant)?\s*experience|employment history|career history",
            "education": r"education(\s+(and|&)\s+(qualifications|training|certifications))?|qualifications",
            "skills": r"(key|technical|core)?\s*skills"}


def ats_issues(text: str) -> list[str]:
    """What a parser needs to fill the candidate record without guessing."""
    issues = []
    top = text[:600]
    if not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", top):
        issues.append("ATS: no email in the first lines")
    if not re.search(r"(\+?61|0)[\s-]?\d{1,3}(?:[\s-]?\d{3,4}){2}", top):
        issues.append("ATS: no phone number in the first lines")
    lines = [l.strip() for l in text.splitlines()]
    pos = {}
    for name, rx in HEADINGS.items():
        hit = next((i for i, l in enumerate(lines) if re.fullmatch(rf"(?i){rx}", l)), None)
        if hit is None:
            issues.append(f"ATS: no standard '{name}' heading")
        pos[name] = hit
    summary = next((i for i, l in enumerate(lines) if re.fullmatch(r"(?i)(professional|career)?\s*(summary|profile)", l)), None)
    if summary is not None and pos["experience"] is not None and summary > pos["experience"]:
        issues.append("ATS: summary comes after experience")
    bad_dates = [l for l in lines if re.search(r"\b\d{1,2}/\d{4}\b", l)]      # 03/2019: parsers misread it
    if bad_dates:
        issues.append(f"ATS: numeric dates (use 'Mon YYYY'): {bad_dates[0][:60]!r}")
    if not re.search(rf"(?i){MON} \d{{4}}\s*[–-]\s*({MON} \d{{4}}|Present|Current)", text):
        issues.append("ATS: no month-year date range (e.g. 'Mar 2019 – Jun 2021')")
    glyphs = sorted({c for c in text if c in "\ufb00\ufb01\ufb02\ufb03\ufb04\ufffd" or 0xE000 <= ord(c) <= 0xF8FF})
    if glyphs:
        issues.append(f"ATS: characters that parse as garbage: {[hex(ord(c)) for c in glyphs]}")
    return issues


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
    if kind == "cv" and path.suffix in (".pdf", ".docx"):
        issues += ats_issues(text)
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
