"""Retention for the daily packages: after N days keep only the summary (SUMMARY.md / LISTA.md), remove the documents.

  job cleanup <slug> [--days 15] [--dry]
"""
from __future__ import annotations

import argparse
import shutil
from datetime import date, timedelta

from prepare import SUMMARY_FILES, package_dir


def cleanup(slug: str, days: int, dry: bool) -> list[str]:
    base = package_dir(slug).parent
    limit = (date.today() - timedelta(days=days)).isoformat()
    removed = []
    for day in sorted(p for p in base.iterdir() if p.is_dir() and p.name < limit):
        for item in day.iterdir():
            if item.name in SUMMARY_FILES:
                continue                      # the summary stays forever
            removed.append(str(item))
            if not dry:
                shutil.rmtree(item) if item.is_dir() else item.unlink()
    return removed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("slug")
    ap.add_argument("--days", type=int, default=15); ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    r = cleanup(a.slug, a.days, a.dry)
    print(f"{'would remove' if a.dry else 'removed'} {len(r)} items older than {a.days} days (summary kept)")


if __name__ == "__main__":
    main()
