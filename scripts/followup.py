"""Follow-up drafts: a short, polite email for every application that has been quiet for a while. Nothing is ever sent.

  python scripts/followup.py <slug> due [--days 10]     applications to chase (sent, no reply, quiet for N days)
  python scripts/followup.py <slug> draft <key>         write followup.md next to that job's CV and letter
  python scripts/followup.py <slug> draft-all           a draft for every due application that has none yet

due(): status applied/submitted, last status change at least `days` days ago (and no more than MAX_DAYS: older ones are
for `job track <slug> followups`, which suggests marking them no-response). A reply, interview or rejection changes
the status, so it drops out by itself. The draft is a fixed template: the role title, the company, the date applied and
the candidate's name and contact from intake.json, nothing else. The path is recorded in the tracker (`followup_draft`).
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from common import cand_dir, read_json
from tracker import SENT, load, sent_date, set_followup

MAX_DAYS = 30


def last_change(a: dict[str, Any]) -> date | None:
    """Date of the last status change (the tracker history), else the day the application was added."""
    for raw in ((a.get("history") or [{}])[-1].get("date"), a.get("date")):
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
    return None


def due(slug: str, days: int = 10, today: date | None = None) -> list[dict[str, Any]]:
    """Tracker entries that were sent, have not moved for `days`..MAX_DAYS days and are still waiting for an answer."""
    today = today or date.today()
    out = []
    for a in load(slug):
        d = last_change(a)
        if a["status"] in SENT and d and d <= today - timedelta(days=days) and (today - d).days <= max(MAX_DAYS, days):
            out.append(a)
    return out


def banned(slug: str) -> re.Pattern[str] | None:
    words = [w for w in read_json(cand_dir(slug) / "intake.json", {}).get("rules", {}).get("never_mention", []) if w]
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + ")", re.I) if words else None


def pretty(d: str) -> str:
    try:
        x = date.fromisoformat(d[:10])
        return f"{x.day} {x:%B %Y}"
    except ValueError:
        return ""


def text_of(slug: str, a: dict[str, Any]) -> str:
    """The draft. Deterministic; a title or company that contains a word the person never mentions is left out."""
    intake = read_json(cand_dir(slug) / "intake.json", {})
    bad = banned(slug)
    ok = lambda s: bool(s) and not (bad and bad.search(s))
    role = a["title"].split(" | ")[0].strip()
    role = role if ok(role) else ""
    company = a.get("company") or ""
    company = company if ok(company) else ""
    when = pretty(sent_date(a))
    what = f"the {role} role" if role else "the role"
    contact = intake.get("contact") or {}
    sign = [x for x in (intake.get("name"), contact.get("email"), contact.get("phone")) if x]
    return "\n".join([
        f"Subject: Following up: {role or 'my application'}", "",
        f"Hello {company + ' ' if company else ''}hiring team,".replace("  ", " "), "",
        f"I applied for {what}{' at ' + company if company else ''}{' on ' + when if when else ''} and wanted to check in. "
        "I remain very interested and would be glad to provide anything else you need.", "",
        "If there is an update on the timeline, I would appreciate hearing it.", "",
        "Thank you for your time.", "",
        "Kind regards,", *sign, ""])


def folder(slug: str, a: dict[str, Any]) -> Path:
    """The job's own folder in the daily package (where its CV and letter are); else a followups folder of today's package."""
    for k in ("letter", "cv"):
        if a.get(k) and Path(a[k]).parent.is_dir():
            return Path(a[k]).parent
    from prepare import package_dir, safe
    d = package_dir(slug) / "followups" / f"{safe(a.get('company') or 'company')}_{safe(a['title'])}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def draft(slug: str, key: str) -> Path:
    """Write followup.md for one tracked application and record it in the tracker. Never sends anything."""
    a = next((x for x in load(slug) if x["key"] == key), None)
    if a is None:
        raise SystemExit(f"{key} not tracked")
    p = folder(slug, a) / "followup.md"
    head = (f"<!-- Draft only, nothing has been sent. Send it yourself to the recruiter or hiring contact "
            f"(see the ad: {a['url']}) or as a reply to the confirmation email. -->\n\n")
    p.write_text(head + text_of(slug, a), encoding="utf-8")
    set_followup(slug, key, str(p))
    return p


def draft_all(slug: str, days: int = 10) -> list[Path]:
    """Drafts for the due applications that have none (or whose file is gone). One failure never stops the rest."""
    out = []
    for a in due(slug, days):
        if a.get("followup_draft") and Path(a["followup_draft"]).is_file():
            continue
        try:
            out.append(draft(slug, a["key"]))
        except (OSError, SystemExit, KeyError, ValueError):
            continue
    return out


def line(slug: str, days: int = 10) -> str:
    """One sentence for status and the report, "" when nothing is due."""
    items = due(slug, days)
    if not items:
        return ""
    ready = sum(1 for a in items if a.get("followup_draft") and Path(a["followup_draft"]).is_file())
    n = len(items)
    tail = ("drafts ready in the package" if ready == n else f"{ready} draft{'s' if ready != 1 else ''} ready in the package, "
            "the rest come with the next daily run" if ready else "drafts come with the next daily run")
    return f"{n} follow-up{'s' if n != 1 else ''} due: {tail}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("cmd", choices=["due", "draft", "draft-all"]); ap.add_argument("key", nargs="?")
    ap.add_argument("--days", type=int, default=10)
    a = ap.parse_args()
    if a.cmd == "due":
        print(json.dumps([{"key": x["key"], "company": x.get("company"), "title": x["title"], "applied": sent_date(x),
                           "draft": x.get("followup_draft")} for x in due(a.slug, a.days)], ensure_ascii=False, indent=2))
    elif a.cmd == "draft":
        if not a.key:
            ap.error("draft needs a key")
        print(draft(a.slug, a.key))
    else:
        print(json.dumps([str(p) for p in draft_all(a.slug, a.days)], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
