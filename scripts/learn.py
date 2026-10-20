"""Harness memory: lessons learned while doing the work, so the next candidate does not repeat them.

  job learn log --kind harness|platform|candidate --area seek|linkedin|docs|ats|forms --lesson "..." [--candidate slug]
  job learn list [--area seek]
"""
from __future__ import annotations

import argparse
import json

from common import ROOT, now_iso

LOG = ROOT / "learn" / "observations.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("log"); p.add_argument("--kind", required=True, choices=["harness", "platform", "candidate"])
    p.add_argument("--area", required=True); p.add_argument("--lesson", required=True); p.add_argument("--candidate", default="")
    p = sub.add_parser("list"); p.add_argument("--area")
    a = ap.parse_args()
    if a.cmd == "log":
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps({"date": now_iso(), "kind": a.kind, "area": a.area, "lesson": a.lesson,
                                "candidate": a.candidate}, ensure_ascii=False) + "\n")
        print("logged")
    else:
        for line in LOG.read_text().splitlines() if LOG.exists() else []:
            o = json.loads(line)
            if not a.area or o["area"] == a.area:
                print(f"[{o['area']}] {o['lesson']}")


if __name__ == "__main__":
    main()
