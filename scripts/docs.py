"""Build a CV or cover letter from its JSON, export the PDF and check it (lint + facts).

  job docs <slug> build <file.json> --kind cv|letter [--out DIR] [--name First_Last_Resume]
  → <DIR>/<name>.docx and .pdf, then lint and facts verify on both (exit 1 if anything fails)

The generators (templates/docs/*.js, docx-js) encode the layout lessons: one column, no tables,
no header/footer, Arial (ligature fonts break the PDF text), explicit spacers (Pages ignores
"space before"). The PDF is generated headless from the same JSON with pdfkit (templates/docs/generar_pdf.js).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from common import ROOT, cand_dir
from facts import verify
from lint import lint

GEN = {"cv": ROOT / "templates/docs/generar_cv.js", "letter": ROOT / "templates/docs/generar_carta.js"}


def export_pdf(src: Path, kind: str, pdf: Path) -> Path | None:
    """PDF straight from the JSON with pdfkit (headless). Pages via osascript hung on an unseen dialog
    during an unattended run, so the daily cycle never depends on a GUI app."""
    r = subprocess.run(["node", str(ROOT / "templates/docs/generar_pdf.js"), kind, str(src), str(pdf)],
                       capture_output=True, text=True, timeout=60, cwd=ROOT / "templates/docs")
    return pdf if r.returncode == 0 and pdf.exists() else None


def build(slug: str, src: Path, kind: str, out: Path | None, name: str | None) -> dict:
    src = (src if src.is_absolute() else cand_dir(slug) / src).resolve()
    out = (out or src.parent).resolve()          # the generator runs in templates/docs: paths must be absolute
    out.mkdir(parents=True, exist_ok=True)
    docx = out / f"{name or src.stem}.docx"
    r = subprocess.run(["node", str(GEN[kind]), str(src), str(docx)], capture_output=True, text=True,
                       cwd=GEN[kind].parent)
    if r.returncode != 0:
        raise SystemExit(f"generator failed: {r.stderr[-800:]}")
    pdf = export_pdf(src, kind, docx.with_suffix(".pdf"))
    checks = [lint(slug, docx, kind), verify(slug, docx)]
    if pdf:
        checks += [lint(slug, pdf, kind), verify(slug, pdf)]
    return {"docx": str(docx), "pdf": str(pdf) if pdf else None, "ok": all(c["ok"] for c in checks),
            "problems": [c for c in checks if not c["ok"]]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build"); p.add_argument("file"); p.add_argument("--kind", choices=["cv", "letter"], required=True)
    p.add_argument("--out"); p.add_argument("--name")
    a = ap.parse_args()
    r = build(a.slug, Path(a.file), a.kind, Path(a.out) if a.out else None, a.name)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
