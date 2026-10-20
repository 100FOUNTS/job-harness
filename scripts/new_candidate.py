"""Create a candidate folder from templates/candidate.

  job new <slug> --name "Full Name" [--source-dir "/path/with/cv/and/letters"]
"""
from __future__ import annotations

import argparse
import shutil

from common import ROOT, candidates_dir, read_json, save_json
from state import default_state, save_state


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("slug"); ap.add_argument("--name", required=True)
    ap.add_argument("--source-dir", default="")
    a = ap.parse_args()
    d = candidates_dir() / a.slug
    if d.exists():
        raise SystemExit(f"{d} already exists")
    shutil.copytree(ROOT / "templates/candidate", d)
    intake = read_json(d / "intake.json")
    intake["name"] = a.name
    intake["source_dir"] = a.source_dir
    save_json(d / "intake.json", intake)
    for sub in ("docs", "data", "approvals"):
        (d / sub).mkdir(exist_ok=True)
    save_state(a.slug, default_state(a.slug))
    print(f"Created {d}. Next: `/job-onboard 0 {a.slug}`")


if __name__ == "__main__":
    main()
