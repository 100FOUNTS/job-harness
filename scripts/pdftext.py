"""Read PDFs without Poppler: Node + pdf.js (templates/docs/pdftext.js), Poppler only as a fallback.

  pages(path) -> int     lines(path) -> [(height, [(top, bottom, text)])]     text(path) -> str
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
from pathlib import Path

from common import ROOT, data_dir, node_env, tools_dir

DOCS = ROOT / "templates/docs"
NO_READER = "Can't read PDFs: run `job setup` (needs Node.js)"


def node_ready() -> bool:
    return bool(shutil.which("node")) and (tools_dir() / "node_modules/pdfjs-dist").exists()


def poppler_ready() -> bool:
    return bool(shutil.which("pdftotext") and shutil.which("pdfinfo"))


def _node(path: Path, mode: str) -> str:
    r = subprocess.run(["node", str(DOCS / "pdftext.js"), str(path), mode], capture_output=True, encoding="utf-8",
                       timeout=120, cwd=DOCS, env=node_env())
    return r.stdout if r.returncode == 0 else ""      # a corrupt or missing file reads as empty, like Poppler


def _poppler(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, encoding="utf-8").stdout


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


def _cached(path: Path) -> Path | None:
    """The text of a PDF is kept per (path, size, mtime): the panel reads dozens of CVs on every load."""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    key = hashlib.sha1(f"{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()
    return data_dir() / ".cache" / "pdftext" / f"{key}.txt"


def text(path: Path) -> str:
    if node_ready():
        c = _cached(path)
        if c and c.exists():
            return c.read_text(encoding="utf-8")
        out = _node(path, "--text")
        if c and out:
            try:
                c.parent.mkdir(parents=True, exist_ok=True); c.write_text(out, encoding="utf-8")
            except OSError:
                pass
        return out
    if poppler_ready():
        return _poppler(["pdftotext", "-layout", str(path), "-"])
    raise RuntimeError(NO_READER)
