"""Read PDFs without Poppler: Node + pdf.js (templates/docs/pdftext.js), Poppler only as a fallback.

  pages(path) -> int     lines(path) -> [(height, [(top, bottom, text)])]     text(path) -> str
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

from common import ROOT

DOCS = ROOT / "templates/docs"
NO_READER = "Can't read PDFs: run `job setup` (needs Node.js)"


def node_ready() -> bool:
    return bool(shutil.which("node")) and (DOCS / "node_modules/pdfjs-dist").exists()


def poppler_ready() -> bool:
    return bool(shutil.which("pdftotext") and shutil.which("pdfinfo"))


def _node(path: Path, mode: str) -> str:
    r = subprocess.run(["node", str(DOCS / "pdftext.js"), str(path), mode], capture_output=True, text=True,
                       timeout=120, cwd=DOCS)
    return r.stdout if r.returncode == 0 else ""      # a corrupt or missing file reads as empty, like Poppler


def _poppler(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def pages(path: Path) -> int:
    if node_ready():
        return int(_node(path, "--pages").strip() or 0)
    if poppler_ready():
        m = re.search(r"Pages:\s+(\d+)", _poppler(["pdfinfo", str(path)]))
        return int(m.group(1)) if m else 0
    raise RuntimeError(NO_READER)


def _bbox_pages(out: str) -> list[tuple[float, list[tuple[float, float, str]]]]:
    res = []
    for pg in re.finditer(r'<page width="[\d.]+" height="([\d.]+)">(.*?)</page>', out, re.S):
        rows: dict[int, list[tuple[float, str]]] = {}
        for m in re.finditer(r'<word xMin="[\d.]+" yMin="([\d.]+)" xMax="[\d.]+" yMax="([\d.]+)">(.*?)</word>', pg.group(2)):
            rows.setdefault(round(float(m.group(1))), []).append((float(m.group(2)), html.unescape(m.group(3))))
        res.append((float(pg.group(1)), [(y, max(b for b, _ in rows[y]), " ".join(w for _, w in rows[y]))
                                         for y in sorted(rows)]))
    return res


def lines(path: Path) -> list[tuple[float, list[tuple[float, float, str]]]]:
    """Per page: (height, [(top, bottom, text) per line]), top-down."""
    if node_ready():
        return [(p["height"], [(l["top"], l["bottom"], l["text"]) for l in p["lines"]])
                for p in json.loads(_node(path, "--lines") or "[]")]
    if poppler_ready():
        return _bbox_pages(_poppler(["pdftotext", "-bbox", str(path), "-"]))
    raise RuntimeError(NO_READER)


def text(path: Path) -> str:
    if node_ready():
        return _node(path, "--text")
    if poppler_ready():
        return _poppler(["pdftotext", "-layout", str(path), "-"])
    raise RuntimeError(NO_READER)
