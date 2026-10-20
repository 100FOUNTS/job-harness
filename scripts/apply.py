"""Scripted applying (modes easy/full): submits prepared SEEK Quick Apply jobs with Playwright. No LLM.

  job apply <slug> [--dry]           apply to today's `prepared` SEEK jobs within quota
  job login <slug> seek              open the dedicated Chrome profile on SEEK's login page (once, by the person)

Effective submission requires: state.mode in (easy, full) AND a valid go-live AND not --dry.
Otherwise the form is filled up to the review step (dry-run). LinkedIn Easy Apply: not automated (account risk).
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import time
from pathlib import Path

from common import ROOT, cand_dir, today
from gates import valid_approval
from state import load_state
from tracker import load, quota, set_status

APPLY = ROOT / "apply"


def profile_dir(slug: str) -> Path:
    d = ROOT / ".browser" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def login(slug: str, site: str) -> None:
    url = {"seek": "https://www.seek.com.au/oauth/login", "linkedin": "https://www.linkedin.com/login"}[site]
    subprocess.Popen(["open", "-na", "Google Chrome", "--args", f"--user-data-dir={profile_dir(slug)}", url])
    print(f"Chrome opened with the dedicated profile ({profile_dir(slug)}). The person logs in once; then close that window.")


def apply(slug: str, force_dry: bool) -> list[dict]:
    st = load_state(slug)
    live = st["mode"] in ("easy", "full") and valid_approval(slug, "go-live")[0] and not force_dry
    results = []
    jobs = [a for a in load(slug) if a["status"] == "prepared" and a["platform"] == "seek"
            and Path(a.get("cv", "")).is_file() and Path(a.get("letter", "")).is_file()]
    for a in jobs:
        q = quota(slug, "seek")
        if live and (q["platform_left"] <= 0 or q["day_left"] <= 0 or q["week_left"] <= 0):
            break
        job_id = a["key"].split(":", 1)[1]
        r = subprocess.run(["node", str(APPLY / "apply_seek.js"), slug, job_id, a["cv"], a["letter"],
                            "submit" if live else "dry", str(profile_dir(slug)), a["key"]],
                           capture_output=True, text=True, cwd=APPLY, timeout=600)
        try:
            res = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            res = {"outcome": "failed", "note": (r.stderr or r.stdout)[-300:]}
        status = {"submitted": "submitted", "dry-run": "dry-run", "needs-login": "prepared"}.get(res["outcome"], "manual-review")
        if res["outcome"] != "needs-login":
            set_status(slug, a["key"], status, note=res.get("note", ""),
                       reason="" if status in ("submitted", "dry-run") else res.get("note", ""))
        results.append({"key": a["key"], "company": a.get("company"), "title": a["title"], **res})
        if res["outcome"] == "needs-login":
            break
        if live and status == "submitted":
            time.sleep(random.uniform(240, 720))          # 4–12 min between submissions
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("action", nargs="?", default="run", choices=["run", "login"])
    ap.add_argument("site", nargs="?", default="seek"); ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.action == "login":
        login(a.slug, a.site); return
    res = apply(a.slug, a.dry)
    print(json.dumps([{k: r.get(k) for k in ("company", "title", "outcome", "note")} for r in res], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
