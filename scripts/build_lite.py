#!/usr/bin/env python3
"""Zip each skill in lite/ into dist/lite/<name>.zip, ready to upload to claude.ai or Cowork.

  python3 scripts/build_lite.py [--out dist/lite]

Each zip holds the skill folder at its root (<name>/SKILL.md), which is what the upload expects. The checks follow
Anthropic's rules for skills: SKILL.md starts with YAML frontmatter that has `name` (lowercase letters, digits and
hyphens, at most 64 characters, equal to the folder name, no "claude" or "anthropic") and `description` (not empty, at
most 1024 characters, no XML tags).
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LITE = ROOT / "lite"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED = ("claude", "anthropic")
FIXED_TIME = (2026, 1, 1, 0, 0, 0)          # same bytes on every run


def frontmatter(text: str) -> dict[str, str]:
    """The simple `key: value` lines between the first two `---` lines (no YAML library, stdlib only)."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must start with a --- frontmatter line")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ValueError("frontmatter is not closed with ---") from None
    out: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def problems(skill_dir: Path) -> list[str]:
    """Everything wrong with one skill folder (empty list = fine)."""
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return [f"{skill_dir.name}: SKILL.md is missing"]
    try:
        fm = frontmatter(md.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"{skill_dir.name}: {e}"]
    errs = []
    name, desc = fm.get("name", ""), fm.get("description", "")
    if not name:
        errs.append("name is missing")
    else:
        if len(name) > 64 or not NAME_RE.match(name):
            errs.append("name must be lowercase letters, digits and hyphens, at most 64 characters")
        if any(w in name for w in RESERVED):
            errs.append("name cannot contain 'claude' or 'anthropic'")
        if name != skill_dir.name:
            errs.append(f"name '{name}' must equal the folder name '{skill_dir.name}'")
    if not desc:
        errs.append("description is missing")
    else:
        if len(desc) > 1024:
            errs.append(f"description is {len(desc)} characters (limit 1024)")
        if re.search(r"</?[A-Za-z][^>]*>", desc):
            errs.append("description cannot contain XML tags")
    return [f"{skill_dir.name}: {e}" for e in errs]


def skills() -> list[Path]:
    return sorted(p for p in LITE.iterdir() if p.is_dir() and not p.name.startswith("."))


def build(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for d in skills():
        errs = problems(d)
        if errs:
            raise ValueError("; ".join(errs))
        target = out / f"{d.name}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(d.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts and f.name != ".DS_Store":
                    info = zipfile.ZipInfo(f"{d.name}/{f.relative_to(d).as_posix()}", FIXED_TIME)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    z.writestr(info, f.read_bytes())
        made.append(target)
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(ROOT / "dist" / "lite"), help="folder for the zips (default dist/lite)")
    args = ap.parse_args()
    try:
        made = build(Path(args.out))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for m in made:
        print(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
