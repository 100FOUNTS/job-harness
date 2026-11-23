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
  no glyphs that parse as garbage (ligatures ﬁ/ﬂ, U+FFFD, private-use symbols), date ranges joined by an ASCII
  hyphen (a Workday import dropped a date joined by an en dash; reported by ai-job-search)
- cliché and AI-tell phrases ("passionate", "spearheaded", "I am excited", "here is the revised"…): a reader
  discards a letter that sounds generated (list adapted from ApplyPilot's validator); a candidate can allow a
  term with intake.rules.allow_phrases
- .pdf layout, measured from word boxes (pdf.js, via scripts/pdftext.py) instead of eyeballed: a hole in the middle of a page, a
  page that is not the last one ending early, a section heading stranded at the bottom of a page, a last CV page
  with only a few lines

JSON-level warnings (`cv_json_warnings`, run by `job docs build` on the CV JSON before it is built, and by
`job lint <slug> cv.json`). They never fail a build, they are printed:
- an employment type written inside `role` ("Assistant Manager (part-time)", "Barista - Casual"): parsers read it
  as part of the job title and misclassify the job. It belongs in the entry's optional `"type"` field.
- education dates with full month names ("Expected December 2026"): every date in a CV is "Mon YYYY"; the
  generators shorten them anyway, but the source should say it the same way. Bare years are fine.
- a date inside `role`, `org` or a section heading (`projects_heading`): "(freelance until Mar 2026)", "Data and AI
  Projects (Self-Directed Study, 2026)". A parser may read it as the job's date range (Affinda did: a 3-year job
  became 1 month, with invented gaps). Dates live only in `dates`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

import pdftext
from common import load_intake
from facts import extract_text

LIGATURE_FONTS = ("Calibri", "Cambria", "Candara", "Constantia")
CLICHES = ["passionate", "spearheaded", "spearhead", "orchestrated", "championed", "synergy", "go-getter", "self-starter",
           "team player", "proven track record", "results-driven", "detail-oriented", "highly motivated", "cutting-edge",
           "state-of-the-art", "best-in-class", "thrives in", "well-versed in", "i am excited", "i'm excited",
           "i am thrilled", "delve", "leverage my", "tapestry", "dynamic environment"]
AI_TELLS = ["as an ai", "here is the revised", "here is the updated", "here is your", "i have rewritten",
            "i apologize", "as requested", "[insert", "{{", "lorem ipsum"]


def pdf_pages(path: Path) -> int:
    return pdftext.pages(path)


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
    dash = re.search(rf"(?:{MON} )?\d{{4}}\s*[\u2010-\u2015\u2212]\s*(?:(?:{MON} )?\d{{4}}|Present|Current)", text)
    if dash:
        issues.append(f"ATS: date range joined by a Unicode dash, use '-': {dash.group(0)!r}")
    glyphs = sorted({c for c in text if c in "\ufb00\ufb01\ufb02\ufb03\ufb04\ufffd" or 0xE000 <= ord(c) <= 0xF8FF})
    if glyphs:
        issues.append(f"ATS: characters that parse as garbage: {[hex(ord(c)) for c in glyphs]}")
    return issues


# Calibrated on the pdfkit layout (A4, 40pt top/bottom margins): normal gaps are ≤ 27pt, a full page ends ~36pt
# above the bottom margin.
HOLE_PT, EARLY_PT, THIN_LAST = 90, 140, 0.15


def pdf_lines(path: Path) -> list[tuple[float, list[tuple[float, float, str]]]]:
    """Per page: (height, [(top, bottom, text) per line]) from the PDF reader (scripts/pdftext.py)."""
    return pdftext.lines(path)


def layout_issues(path: Path, kind: str) -> list[str]:
    issues = []
    pages = [(h, ls) for h, ls in pdf_lines(path) if ls]
    heading = re.compile(rf"(?i)({'|'.join(HEADINGS.values())}|(professional|career)?\s*(summary|profile)|"
                         r"projects|certifications|languages|referees)")
    for n, (h, ls) in enumerate(pages, 1):
        last = n == len(pages)
        gap = max(((ls[i + 1][0] - ls[i][1], ls[i + 1][2]) for i in range(len(ls) - 1)), default=(0, ""))
        if gap[0] > HOLE_PT:
            issues.append(f"layout: {gap[0]:.0f}pt hole on page {n} before {gap[1][:40]!r}")
        if not last and ls[-1][1] < h - 40 - EARLY_PT:
            issues.append(f"layout: page {n} ends {h - 40 - ls[-1][1]:.0f}pt early (an entry was pushed to the next page)")
        if not last and heading.fullmatch(ls[-1][2].strip()):
            issues.append(f"layout: heading {ls[-1][2]!r} stranded at the bottom of page {n}")
        if last and kind == "cv" and n > 1 and (ls[-1][1] - ls[0][0]) < THIN_LAST * (h - 80):
            issues.append(f"layout: last page has only {len(ls)} lines (cut or tighten)")
    return issues


EMPLOYMENT_TYPES = (r"part[\s-]?time|full[\s-]?time|casual|contract(?:or)?|temp(?:orary)?|fixed[\s-]?term|volunteer(?:ing)?|"
                    r"intern(?:ship)?|permanent|seasonal")
ROLE_TYPE = re.compile(rf"(?i)\(\s*(?:{EMPLOYMENT_TYPES})\b[^)]*\)|[-,|\u2013\u2014]\s*(?:{EMPLOYMENT_TYPES})\s*$")
FULL_MONTH = re.compile(r"(?i)\b(?:january|february|march|april|june|july|august|september|sept|october|november|december)\b")
ENTRY_SECTIONS = ("experience", "entrepreneurship", "projects", "other_employment")
# A month name or abbreviation followed by a year ("Mar 2026", "Sept 2020"), or a bare year 1950-2099. The word
# boundaries keep "ISO 14001" and "Spring Boot 3" out.
_MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_IN_TEXT = re.compile(rf"(?i)\b{_MONTHS}\.?\s+(?:19[5-9]\d|20\d\d)\b|\b(?:19[5-9]\d|20\d\d)\b")


def date_in(text: Any) -> str | None:
    """The first date found inside a role, org or heading, or None."""
    if isinstance(text, str):
        m = DATE_IN_TEXT.search(text)
        if m:
            return m.group(0)
    return None


def cv_json_warnings(cv: Any) -> list[str]:
    """Problems in the CV JSON that the generators cannot fix; warnings only, they never fail a build."""
    if not isinstance(cv, dict):
        return []
    out = []
    for section in ENTRY_SECTIONS:
        entries = cv.get(section)
        for e in entries if isinstance(entries, list) else []:
            role = e.get("role") if isinstance(e, dict) else None
            if isinstance(role, str) and ROLE_TYPE.search(role):
                out.append(f"{section}: employment type inside the role {role!r}: move it to \"type\" "
                           f"(e.g. \"type\": \"Part-time\") and keep the role as the plain job title")
            for field in ("role", "org"):
                found = date_in(e.get(field)) if isinstance(e, dict) else None
                if found:
                    out.append(f"{section}: date {found!r} inside the {field} {e[field]!r}: a parser may read it as the job's date range. "
                               f"Keep dates only in \"dates\"; if the role changed during the job, say so in a bullet or split the entry")
    for key, value in cv.items():
        found = date_in(value) if key.endswith("_heading") else None
        if found:
            out.append(f"{key}: date {found!r} inside the heading {value!r}: a parser may read it as a date range and split the "
                       f"section. Keep dates out of headings; if it matters, say it in a bullet or the entry's \"dates\"")
    for e in cv.get("education") or []:
        when = e[2] if isinstance(e, (list, tuple)) and len(e) > 2 else None
        if isinstance(when, str) and FULL_MONTH.search(when):
            out.append(f"education: date {when!r} uses a full month name; write 'Mon YYYY' (e.g. 'Expected Dec 2026')")
    return out


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
    allowed = {t.lower() for t in rules.get("allow_phrases", [])}
    for term in CLICHES + AI_TELLS:
        if term not in allowed and re.search(rf"(?<!\w){re.escape(term)}(?!\w)" if term[0].isalpha() else re.escape(term), text, re.I):
            issues.append(f"{'generated-text leftover' if term in AI_TELLS else 'cliché'}: '{term}'")
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
        issues += layout_issues(path, kind)
    if kind == "cv" and path.suffix in (".pdf", ".docx"):
        issues += ats_issues(text)
    return {"file": str(path), "ok": not issues, "issues": issues}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("file"); ap.add_argument("--kind", choices=["cv", "letter"], default="cv")
    a = ap.parse_args()
    if a.file.lower().endswith(".json"):                  # the CV JSON itself: warnings only
        try:
            warnings = cv_json_warnings(json.loads(Path(a.file).read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            sys.exit(f"Can't read {a.file}: {e}")
        print(json.dumps({"file": a.file, "ok": True, "warnings": warnings}, ensure_ascii=False, indent=2))
        sys.exit(0)
    try:
        r = lint(a.slug, Path(a.file), a.kind)
    except RuntimeError as e:
        sys.exit(str(e))
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
