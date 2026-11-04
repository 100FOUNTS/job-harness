"""Red flags: plain warnings about an ad, for the person's eyes. Deterministic: no LLM, no network.

  python scripts/flags.py <slug> [<key>]     recompute and store the flags of one tracked job (or every open one)

Flags never drop an ad and never change its score; they only appear in the daily package, the report and the panel
(tracker field `red_flags`, written by tracker.set_flags). Rules:
- pay: the top of the advertised range is below the candidate's minimum (targets.ranking.min_salary / min_salary_k, else
  intake.preferences.min_salary / salary_expectation), or below the Australian minimum wage;
- unpaid trial / internship, commission-only, a "volunteer" role under a paid-job title;
- upfront fees and scam patterns (pay for training or a kit, bank details, interview by WhatsApp/Telegram, "earn $X a day
  from home", a personal gmail/hotmail address for a company role);
- hidden employer ("our client", confidential) with no stated pay; the same title + company listed again and again (jobs.db).
Nothing here ever talks about visas, work rights or sponsorship.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import date
from typing import Any

from common import cand_dir, read_json
from tracker import PENDING, SENT, load, set_flags

# Australian national minimum wage, per hour (Fair Work Commission, from 1 July 2025). Update it every July.
# Casual loading and award rates are higher; this is only the floor under which an ad is certainly wrong.
AU_MIN_HOURLY = 24.95
HOURS_PER_YEAR = 38 * 52                    # standard 38-hour week: converts hourly/daily/weekly pay to a yearly figure
REPOST_MIN, REPOST_DAYS = 4, 14             # this many ads with the same title+company, seen over at least this many days
PERSONAL_MAIL = ("gmail.com", "googlemail.com", "hotmail.com", "hotmail.com.au", "outlook.com", "live.com", "yahoo.com",
                 "yahoo.com.au", "icloud.com", "aol.com", "protonmail.com", "proton.me", "bigpond.com")

NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
MONEY = re.compile(rf"\$\s?(?P<a>{NUM})\s*(?P<ak>k\b)?(?:\s*(?:-|–|—|to)\s*\$?\s?(?P<b>{NUM})\s*(?P<bk>k\b)?)?(?P<tail>[^$]{{0,40}})", re.I)
UNITS = (("hour", re.compile(r"(?:\bper|\ban?\b|/)\s*(?:hour|hr)\b|\bp\.?h\.?(?!\w)|\bhourly", re.I), HOURS_PER_YEAR),
         ("day", re.compile(r"(?:\bper|\ban?\b|/)\s*day\b|\bp\.?d\.?(?!\w)|\bdaily|\bper diem", re.I), 5 * 52),
         ("week", re.compile(r"(?:\bper|\ban?\b|/)\s*(?:week|wk)\b|\bp\.?w\.?(?!\w)|\bweekly", re.I), 52),
         ("month", re.compile(r"(?:\bper|\ban?\b|/)\s*month\b|\bp\.?m\.?(?!\w)|\bmonthly", re.I), 12),
         ("year", re.compile(r"(?:\bper|\ban?\b|/)\s*(?:annum|year|yr)\b|\bp\.?a\.?(?!\w)|\bannual|\bsuper", re.I), 1))
SANE = {"hour": (10, 300), "day": (80, 3000), "week": (400, 20000), "month": (2000, 50000), "year": (15000, 1500000)}
BIG = re.compile(r"^\s*(?:m\b|mn\b|mil|million|bn\b|billion)", re.I)
PAY_WORDS = re.compile(r"salary|remuneration|package|\bpay\b|\brate\b|\bote\b|base|earn|wage", re.I)
NOT_PAY = re.compile(r"bonus|budget|turnover|revenue|funding|grant|project|valued|contract value|portfolio|sales of", re.I)


def parse_pay(text: str, field: bool = False) -> dict[str, Any] | None:
    """First advertised pay in `text` as {low, high (yearly AUD), unit, raw_low, raw_high}, or None.
    "$85,000 - $95,000", "$90k + super", "$45 per hour", "$40-50/hr", "$400/day". A figure without a unit or a k
    needs a pay word before it (or be a range), so "$2 million budget" and "$500 sign-on" are not pay. `field`: the
    text is the ad's own salary field, so a bare amount counts."""
    for m in MONEY.finditer(text or ""):
        num = lambda s: float(s.replace(",", ""))
        tail = m["tail"]
        if not m["b"] and not m["ak"] and BIG.match(tail):
            continue
        before = text[max(0, m.start() - 40):m.start()]
        if NOT_PAY.search(before):
            continue
        lo = num(m["a"]) * (1000 if m["ak"] or (m["bk"] and num(m["a"]) < 1000) else 1)
        hi = num(m["b"]) * (1000 if m["bk"] else 1) if m["b"] else lo
        lo, hi = min(lo, hi), max(lo, hi)
        found = sorted((hit.start(), u, f) for u, rx, f in UNITS if (hit := rx.search(tail[:28])))
        unit = found[0][1:] if found else None             # the unit written first wins ("$85k + super, 8 hours per day")
        if unit is None:
            if not (m["ak"] or m["bk"] or (lo >= 20000 and (field or m["b"] or PAY_WORDS.search(before)))):
                continue
            unit = ("year", 1)
        name, factor = unit
        if not SANE[name][0] <= hi <= SANE[name][1]:
            continue
        return {"low": lo * factor, "high": hi * factor, "unit": name, "raw_low": lo, "raw_high": hi}
    return None


def money(v: float) -> str:
    return f"${v:,.0f}" if abs(v - round(v)) < 0.005 else f"${v:,.2f}"


def minimum_pay(targets: dict[str, Any], intake: dict[str, Any] | None = None) -> float | None:
    """The candidate's yearly minimum, if they gave one: targets.ranking.min_salary_k, targets.ranking.min_salary,
    intake.preferences.min_salary, then the low end of intake.preferences.salary_expectation. Numbers below 1000 are
    read as an hourly rate."""
    rk, pref = targets.get("ranking") or {}, (intake or {}).get("preferences") or {}
    if isinstance(rk.get("min_salary_k"), (int, float)) and rk["min_salary_k"] > 0:
        return rk["min_salary_k"] * 1000.0
    for v in (rk.get("min_salary"), targets.get("min_salary"), pref.get("min_salary"), pref.get("salary_expectation")):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return float(v) * (HOURS_PER_YEAR if v < 1000 else 1)
        if isinstance(v, str) and re.search(r"\d", v):
            p = parse_pay(v if "$" in v else "$" + v.strip(), field=True)
            if p:
                return p["low"]
    return None


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(parts), re.I)


UNPAID = _rx(r"\bunpaid\s+(?:trial|internship|intern\b|work|position|role|placement|training|period|probation)",
             r"\bunpaid\b[^.]{0,40}\btrial (?:shift|day|period|work)", r"\btrial (?:shift|day|period)s?\b[^.]{0,40}\bunpaid\b",
             r"\bcommission[- ]only\b", r"\bcommission[- ]based only\b", r"\b100% commission\b", r"\bstraight commission\b",
             r"\bno base (?:salary|pay|wage)\b", r"\bpurely commission\b")
VOLUNTEER = _rx(r"\bvolunteer(?:ing)? (?:position|role|basis|work|opportunity|only)\b", r"\b(?:voluntary|volunteer) (?:position|role)\b",
                r"\bthis is a volunteer\b", r"\bunpaid volunteer")
FEES = _rx(r"\bpay(?:ing)? for (?:your |the )?(?:own )?(?:training|uniform|equipment|kit|background check|police check|onboarding)",
           r"\b(?:training|onboarding|registration|application|joining|admin(?:istration)?|processing) fee\b", r"\bstarter kit\b",
           r"\b(?:purchase|buy) (?:your own |a )?(?:starter )?(?:kit|equipment|laptop|stock|inventory)\b",
           r"\b(?:refundable )?(?:security )?deposit (?:is )?required\b", r"\bupfront (?:fee|payment|cost)s?\b")
BANK = _rx(r"\b(?:send|provide|share|email|text|give)\b[^.]{0,30}\b(?:bank (?:account )?(?:details|number|login)|credit card|card (?:number|details)|online banking)\b",
           r"\b(?:bank|card) details (?:to apply|with your application|before|are required)\b")
CHAT = _rx(r"\b(?:whatsapp|telegram|wechat)\b[^.]{0,60}\b(?:interview|apply|application|contact|message|text|chat)\b",
           r"\b(?:interview|apply|application|contact|message|text|chat)\b[^.]{0,60}\b(?:whatsapp|telegram|wechat)\b")
EARN = _rx(r"\bearn(?:ing)?\s+(?:up to |upto |over |around )?\$\s?\d[\d,]*(?:\s*(?:-|to)\s*\$?\s?\d[\d,]*)?\s*(?:k\b)?\s*(?:per|a|each|/)\s*(?:day|week|hour)\b")
HOME = _rx(r"\bfrom home\b", r"\bwork(?:ing)? at home\b", r"\bno experience (?:needed|required|necessary)\b", r"\bonline (?:work|tasks|jobs?)\b", r"\bsimple tasks\b")
HIDDEN_CO = _rx(r"confidential", r"private advertiser", r"anonymous", r"undisclosed", r"not disclosed", r"^\s*(?:n/?a|none|-)?\s*$")
OUR_CLIENT = _rx(r"\bour client\b", r"\bon behalf of (?:our|a) client\b", r"\bour customer\b")
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", re.I)
PRORATA = re.compile(r"pro[- ]?rata|part[- ]time", re.I)


def job_text(job: dict[str, Any]) -> str:
    return " ".join(str(x) for x in [job.get("title", ""), job.get("teaser", ""), " ".join(job.get("bullets") or []),
                                     job.get("description", "")] if x)


def check(job: dict[str, Any], targets: dict[str, Any], intake: dict[str, Any] | None = None, reposts: int = 0) -> list[str]:
    """Red flags for one ad, short human sentences; [] when it looks normal. `intake` adds the person's own salary
    expectation to the minimum; `reposts`: how many ads with this title and company jobs.db holds (see repost_count)."""
    text = job_text(job)
    out: list[str] = []
    pay = parse_pay(job.get("salary") or "", field=True) or parse_pay(text)
    if pay:
        hourly = pay["raw_high"] if pay["unit"] == "hour" else pay["high"] / HOURS_PER_YEAR
        floor = minimum_pay(targets, intake)
        if hourly < AU_MIN_HOURLY and not (pay["unit"] in ("year", "month") and PRORATA.search(text)):
            out.append(f"Pay of about {money(hourly)} an hour is below the Australian minimum wage ({money(AU_MIN_HOURLY)}).")
        elif floor and pay["high"] < floor:
            top = f"{money(pay['raw_high'])} an hour (about {money(pay['high'])} a year)" if pay["unit"] == "hour" else money(pay["high"])
            out.append(f"Pay tops out at {top}, below your minimum of {money(floor)}.")
    if m := UNPAID.search(text):
        out.append(f"Unpaid or commission-only work (\"{m.group(0).strip()}\"): check that this is a paid job.")
    if VOLUNTEER.search(text) and not re.search(r"volunteer|voluntary", job.get("title", ""), re.I):
        out.append("The ad describes a volunteer role under a paid-job title: check that this is a paid job.")
    if m := FEES.search(text):
        out.append(f"Asks you to pay up front (\"{m.group(0).strip()}\"): a common scam sign.")
    if BANK.search(text):
        out.append("Asks for bank or card details before any offer: a common scam sign.")
    if CHAT.search(text):
        out.append("Interview or contact through WhatsApp/Telegram: a common scam sign.")
    if EARN.search(text) and HOME.search(text):
        out.append("Promises a high daily pay for work from home or no experience: a common scam sign.")
    for dom in dict.fromkeys(d.lower() for d in EMAIL.findall(text)):
        if dom in PERSONAL_MAIL:
            out.append(f"Applications go to a personal @{dom} address, not a company one: check the employer.")
            break
    if (HIDDEN_CO.search(job.get("company") or "") or OUR_CLIENT.search(text)) and not pay:
        out.append("Employer is hidden (\"our client\"/confidential) and no pay is stated: find out who is hiring before sharing details.")
    if reposts >= REPOST_MIN:
        out.append(f"The same title and company has been listed {reposts} times: a repost loop or a role that never fills.")
    return list(dict.fromkeys(out))


def repost_count(slug: str, job: dict[str, Any]) -> int:
    """How many ads in jobs.db share this job's title and company (this one included), when there are REPOST_MIN or
    more and they were seen over at least REPOST_DAYS days; otherwise 0."""
    from jobdb import connect
    title, company = (job.get("title") or "").strip().lower(), (job.get("company") or "").strip().lower()
    if not title or not company:
        return 0
    try:
        with connect(slug, readonly=True) as con:
            rows = con.execute("SELECT key, first_seen, last_seen FROM jobs WHERE lower(trim(title))=? AND lower(trim(company))=?",
                               (title, company)).fetchall()
    except sqlite3.Error:
        return 0
    keys = {r["key"] for r in rows} | {job.get("key")}
    days = [d for r in rows for d in (r["first_seen"], r["last_seen"]) if d]
    try:
        span = (date.fromisoformat(max(days)[:10]) - date.fromisoformat(min(days)[:10])).days if days else 0
    except ValueError:
        span = 0
    return len(keys) if len(keys) >= REPOST_MIN and span >= REPOST_DAYS else 0


def check_job(slug: str, job: dict[str, Any], targets: dict[str, Any] | None = None) -> list[str]:
    """check() with the candidate's own files and jobs.db behind it. Never raises: a broken file means no flags."""
    try:
        base = cand_dir(slug)
        return check(job, targets if targets is not None else read_json(base / "targets.json", {}),
                     read_json(base / "intake.json", {}), repost_count(slug, job))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def job_of(slug: str, key: str) -> dict[str, Any]:
    """The ad as jobs.db knows it (full description), else the tracker entry."""
    a = next((x for x in load(slug) if x["key"] == key), None)
    if a is None:
        raise SystemExit(f"{key} not tracked")
    job = {"key": key, "title": a["title"], "company": a.get("company") or "", "teaser": a.get("summary", "")}
    try:
        from jobdb import connect
        with connect(slug, readonly=True) as con:
            row = con.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
            if row:
                job |= {k: row[k] or "" for k in ("title", "company", "salary", "teaser", "description")}
                job["bullets"] = json.loads(row["bullets"] or "[]")
    except (sqlite3.Error, ValueError):
        pass
    return job


def refresh(slug: str, key: str | None = None) -> dict[str, list[str]]:
    """Recompute and store the flags of one tracked job, or of every one still open (not yet applied, or waiting)."""
    keys = [key] if key else [a["key"] for a in load(slug) if a["status"] in PENDING | SENT]
    out = {}
    for k in keys:
        out[k] = check_job(slug, job_of(slug, k))
        set_flags(slug, k, out[k])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("key", nargs="?")
    a = ap.parse_args()
    print(json.dumps(refresh(a.slug, a.key), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
