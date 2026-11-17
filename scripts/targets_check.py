"""Read-only linter for candidates/<slug>/targets.json, using the same matchers as triage and prepare.

  job targets check <slug> [--days 30] [--json]

errors   a title_include phrase no ad can pass; duplicate track ids; missing cv/letter files; unknown ids in priority or seek_cvs.json
warnings accepted-but-penalised phrases (ranking.off_field / missing_credentials / deprioritize), phrases shadowed by an
         earlier track, duplicate phrases, tracks missing from priority or seek_cvs.json, rank_adjust overridden by priority
info     phrases that matched no ad title in jobs.db in the last --days days
Exit code 1 if there is any error. Writes nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date, timedelta
from typing import Any

from common import cand_dir, read_json
from prepare import words_rx
from triage import prx, rx


def plain(phrase: str) -> str:
    """The text of a phrase as an ad title would carry it (a trailing "*" is only a matcher hint)."""
    return phrase.strip().rstrip("*").strip()


def check_targets(targets: dict[str, Any], base: Any = None, seek: dict[str, Any] | None = None, mode: str = "",
                  seen_titles: list[str] | None = None) -> list[dict[str, str]]:
    """Findings [{level, track, phrase, msg, fix}] for one targets dict. `base`: candidate dir (file checks);
    `seek`: seek_cvs.json (None = absent); `seen_titles`: recent ad titles (None = no jobs.db)."""
    out: list[dict[str, str]] = []

    def add(level: str, track: str, phrase: str, msg: str, fix: str) -> None:
        out.append({"level": level, "track": track, "phrase": phrase, "msg": msg, "fix": fix})

    tracks = [t for t in targets.get("tracks", []) if isinstance(t, dict)]
    rk = targets.get("ranking") or {}
    dp = rk.get("deprioritize") or {}
    g_ex = rx(targets.get("exclude_title", []))
    off, cred, dep = (words_rx(rk.get("off_field", [])), words_rx(rk.get("missing_credentials", [])), words_rx(dp.get("terms", [])))
    pens = [("ranking.off_field", -18, off and re.compile(off + r"\w*\b", re.I)),
            ("ranking.missing_credentials", -8, cred and re.compile(cred + r"\b", re.I)),
            ("ranking.deprioritize", -abs(int(dp.get("points", 8))), dep and re.compile(dep + r"\b", re.I))]

    ids = [t.get("id", "") for t in tracks]
    for i in sorted({i for i in ids if ids.count(i) > 1}):
        add("error", i, "", f"track id '{i}' appears {ids.count(i)} times", "give each track a unique id")

    for n, t in enumerate(tracks):
        tid, own_ex = t.get("id", f"#{n}"), rx(t.get("exclude_title", []))
        phrases = [p for p in t.get("title_include", []) if isinstance(p, str) and p.strip()]
        low = [p.strip().lower() for p in phrases]
        dups = {}
        for p in phrases:
            if low.count(p.strip().lower()) > 1:
                dups.setdefault(p.strip().lower(), p)
        for p in dups.values():
            add("warn", tid, p, "duplicate phrase in this track", "remove the repeat")
        for p in dict.fromkeys(phrases):
            txt = plain(p)
            lead = re.split(r"\s+to\s+", txt, maxsplit=1, flags=re.I)[0]        # as judge() does: a range is judged by its entry point
            if g_ex and (m := g_ex.search(lead)):
                add("error", tid, p, f"rejected by the global exclude_title ('{m.group()}'): no ad can pass",
                    f"drop the phrase or '{m.group()}' from exclude_title")
            elif own_ex and (m := own_ex.search(txt)):
                add("error", tid, p, f"rejected by this track's exclude_title ('{m.group()}'): no ad can pass",
                    f"drop the phrase or '{m.group()}' from the track's exclude_title")
            for name, pts, pat in pens:
                if pat and pat.search(txt):
                    add("warn", tid, p, f"matches {name}: accepted but always {pts} points",
                        f"drop the phrase or the {name} term, or accept the penalty")
            for e in tracks[:n]:                                # triage gives an ad to the FIRST track that matches
                er = prx([q for q in e.get("title_include", []) if isinstance(q, str)])
                if not er or not er.search(txt):
                    continue
                ex = rx(e.get("exclude_title", []))
                if ex and ex.search(txt):
                    add("info", tid, p, f"matched by track '{e.get('id')}' but its exclude_title rejects it: still reaches this track",
                        "nothing to do")
                else:
                    add("warn", tid, p, f"shadowed by earlier track '{e.get('id')}': this track never receives these ads",
                        f"move the phrase to '{e.get('id')}', reorder the tracks or add it to that track's exclude_title")
                break
        for k in ("cv", "letter"):
            if base is not None and t.get(k) and not (base / t[k]).is_file():
                add("error", tid, "", f"{k} file '{t[k]}' does not exist", f"create it or fix the path in the track's `{k}`")

    known = set(ids)
    if isinstance(targets.get("priority"), list):
        pr = [x for x in targets["priority"] if isinstance(x, str)]
        for x in dict.fromkeys(pr):
            if x not in known:
                add("error", x, "", "priority names an unknown track", "fix the id or remove it from priority")
        for t in tracks:
            if t.get("id") not in pr:
                add("warn", t.get("id", ""), "", "track missing from priority", "add it to priority (highest first)")
            elif t.get("rank_adjust"):
                add("warn", t.get("id", ""), "", f"explicit rank_adjust ({t['rank_adjust']}) is ignored: priority wins",
                    "remove rank_adjust from the track")
    if seek is not None:
        keys = {k for k in seek if not k.startswith("_")}
        for k in sorted(keys - known):
            add("error", k, "", "seek_cvs.json names an unknown track", "fix the id or remove the entry")
        for i in ids:
            if i not in keys:
                add("warn", i, "", "no saved SEEK resumé in seek_cvs.json: `job apply` leaves these ads for the person",
                    "add the track's resumé file name to seek_cvs.json")
    elif mode in ("easy", "full"):
        add("warn", "", "", f"mode is '{mode}' but seek_cvs.json is missing",
            "create seek_cvs.json ({track: resumé file name saved on SEEK})")

    if seen_titles is not None:
        for t in tracks:
            miss = [p for p in dict.fromkeys(t.get("title_include", [])) if isinstance(p, str) and p.strip()
                    and not any(prx([p]).search(x) for x in seen_titles)]
            if miss:
                add("info", t.get("id", ""), "", f"no ad title in the period matched {len(miss)}: " + "; ".join(miss),
                    "keep, widen or drop them")
    return out


def recent_titles(slug: str, days: int) -> list[str] | None:
    if not (cand_dir(slug) / "jobs.db").is_file():
        return None
    from jobdb import connect
    try:
        with connect(slug, readonly=True) as con:
            cut = (date.today() - timedelta(days=days)).isoformat()
            return [r[0] for r in con.execute("SELECT DISTINCT title FROM jobs WHERE last_seen >= ? AND title IS NOT NULL", (cut,))]
    except sqlite3.Error:
        return None


def run(slug: str, days: int = 30) -> dict[str, list[dict[str, str]]]:
    base = cand_dir(slug)
    targets = read_json(base / "targets.json", None)
    if not isinstance(targets, dict):
        raise SystemExit(f"no readable targets.json for '{slug}'")
    mode = (read_json(base / "state.json", {}) or {}).get("mode", "")
    seek = read_json(base / "seek_cvs.json", {}) if (base / "seek_cvs.json").is_file() else None
    found = check_targets(targets, base, seek if isinstance(seek, dict) else None, mode, recent_titles(slug, days))
    return {"errors": [f for f in found if f["level"] == "error"], "warnings": [f for f in found if f["level"] == "warn"],
            "info": [f for f in found if f["level"] == "info"]}


def line(f: dict[str, str]) -> str:
    who = f"[{f['track']}] " if f["track"] else ""
    ph = f"\"{f['phrase']}\": " if f["phrase"] else ""
    return f"  {who}{ph}{f['msg']}\n      fix: {f['fix']}"


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "check":
        argv = argv[1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("--days", type=int, default=30); ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = run(a.slug, a.days)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        for title, key in (("ERRORS", "errors"), ("WARNINGS", "warnings"), ("INFO", "info")):
            if r[key]:
                print(f"{title} ({len(r[key])})")
                print("\n".join(line(f) for f in r[key]) + "\n")
        print(f"{len(r['errors'])} errors, {len(r['warnings'])} warnings, {len(r['info'])} info")
    sys.exit(1 if r["errors"] else 0)


if __name__ == "__main__":
    main()
