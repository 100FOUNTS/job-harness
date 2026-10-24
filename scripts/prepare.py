"""Prepare mode: pick the most valuable new jobs and build ready-to-upload documents. No browser, no LLM.

  job prepare <slug> [--max 15]
  → for the top jobs of today's shortlist: tracker status `prepared`, CV (track master) + cover letter
    (template filled with company, role, source and the job's matching skills), checked with lint + facts,
    and a daily package ~/job-packages/<slug>/<date>/ with numbered folders, a summary (SUMMARY.md) and index.html.

Ranking (deterministic, see score()): compatibility (the track's core/support keywords found in the ad) + probability
(title level, years asked, and the person's own `ranking` block in targets.json) + recency.
Same ad on both platforms is prepared once. The person opens each link, clicks Apply and uploads the two PDFs.
"""
from __future__ import annotations

import argparse
import html
import os
import json
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from common import cand_dir, read_json, run_dir, save_json, today
from docs import build
from tracker import add, load, set_status
from triage import dedupe_key

# Everything about the person (keywords, fields they are not in, credentials they lack, preferred places) lives in
# their targets.json; only rules that hold for any candidate are written here.
LEVEL_ADJ = [
    (r"\b(graduate|junior|entry|assistant|technician|trainee|cadet|intern)\b", 18, "entry"),
    (r"\b(officer|coordinator|support)\b", 10, "officer"),
    (r"\bsenior\b", -15, "senior"),
    (r"\bprincipal\b", -25, "principal"),
    (r"\b(team leader|lead)\b", -25, "lead"),
    (r"\bspecialist\b", -5, "specialist"),
]
WATCH = ("off_field", "no_credential", "no_licence", "senior_salary", "lead")
# What the person reads in the daily package. intake.ui_language picks the set (default en).
LABELS = {
    "en": {"entry": "entry-level role", "officer": "officer/coordinator level", "senior": "senior", "principal": "principal",
           "lead": "leadership role", "specialist": "specialist", "off_field": "different specialty",
           "no_credential": "asks for a credential not in the profile", "no_licence": "asks for a licence not in the profile",
           "secondary_location": "secondary location", "senior_salary": "senior-level salary", "years": "asks for {n}+ years",
           "years_long": "asks for {n}+ years of experience", "residency": "check residency/citizenship requirements",
           "senior_title": "senior/principal role", "graduate": "graduate program: check eligibility",
           "high": "high", "medium": "medium", "low": "low", "score": "score", "check_ad": "check the ad",
           "how_li_easy": "LinkedIn Easy Apply", "how_li": "LinkedIn → Apply (may lead to the employer's site)",
           "how_seek": "SEEK → Quick apply (or the employer's site, as the ad says)",
           "title": "Applications", "howto": "How to apply: open the link → Apply → upload the CV and letter from the folder with the same number.",
           "what": "What it is", "fits": "Why it fits", "odds": "Odds", "watch": "Watch out", "apply": "How to apply",
           "ad": "Ad", "folder": "Folder", "open_ad": "Open ad", "upload": "Upload the CV and cover letter in this folder.",
           "summary_file": "SUMMARY.md", "readme_file": "README.md"},
    "es": {"entry": "cargo de entrada", "officer": "nivel officer/coordinator", "senior": "senior", "principal": "principal",
           "lead": "jefatura", "specialist": "specialist", "off_field": "otra especialidad",
           "no_credential": "pide una certificación que no tiene", "no_licence": "pide una licencia que no tiene",
           "secondary_location": "ubicación secundaria", "senior_salary": "sueldo de nivel senior", "years": "pide {n}+ años",
           "years_long": "pide {n}+ años de experiencia", "residency": "revisar requisitos de residencia/ciudadanía",
           "senior_title": "cargo senior/principal", "graduate": "programa de graduados: revisar elegibilidad",
           "high": "alta", "medium": "media", "low": "baja", "score": "puntaje", "check_ad": "revisar el aviso",
           "how_li_easy": "LinkedIn Easy Apply", "how_li": "LinkedIn → Apply (puede llevar a la web de la empresa)",
           "how_seek": "SEEK → Quick apply (o web de la empresa, según el aviso)",
           "title": "Postulaciones", "howto": "Cómo postular: abrir el link → Apply → subir el CV y la carta de la carpeta con el mismo número.",
           "what": "Qué es", "fits": "Por qué calza", "odds": "Probabilidad", "watch": "Ojo", "apply": "Cómo postular",
           "ad": "Aviso", "folder": "Carpeta", "open_ad": "Abrir aviso", "upload": "Subir el CV y la carta de esta carpeta.",
           "summary_file": "LISTA.md", "readme_file": "LEEME.md"},
}
SUMMARY_FILES = {v["summary_file"] for v in LABELS.values()}


def labels(slug: str) -> dict[str, str]:
    lang = read_json(cand_dir(slug) / "intake.json", {}).get("ui_language", "en") if slug else "en"
    return LABELS.get(lang, LABELS["en"])


def words_rx(words: list[str]) -> str | None:
    return r"\b(" + "|".join(re.escape(w) for w in words) + r")" if words else None


def track_keywords(slug: str, track: dict[str, Any]) -> dict[str, list[str]]:
    """targets.json track `keywords` {core, support}; without them, the terms of the track CV's skills list."""
    if track.get("keywords"):
        return {"core": track["keywords"].get("core", []), "support": track["keywords"].get("support", [])}
    cv = read_json(cand_dir(slug) / track.get("cv", ""), {}) if track.get("cv") else {}
    terms = []
    for row in cv.get("skills", []):
        text = row[1] if isinstance(row, list) and len(row) > 1 else str(row)
        terms += [t.strip().lower() for t in re.split(r"[,;()/]", text) if 2 < len(t.strip()) < 30]
    return {"core": sorted(set(terms)), "support": []}


def score(job: dict[str, Any], targets: dict[str, Any], slug: str = "") -> tuple[int, list[str], dict[str, Any]]:
    """Total 0–100 = compatibility (track keywords in the ad) + probability (title level, years asked, the person's
    off-field titles, credentials they lack, preferred places, senior-level salary) + recency.
    Returns (score, keyword hits, {"prob": high|medium|low, "why": [reason codes]})."""
    from triage import min_years_required
    rk = targets.get("ranking", {})
    title = job.get("title", "")
    text = " ".join([title, job.get("teaser", ""), " ".join(job.get("bullets", [])), job.get("description", "")]).lower()
    track = next((t for t in targets["tracks"] if t["id"] == job["track"]), {})
    kw = track_keywords(slug, track)
    found = lambda ws: [w for w in ws if re.search(rf"\b{re.escape(w)}", text)]
    core, support = found(kw["core"]), found(kw["support"])
    fit = min(55, 7 * len(core) + 3 * len(support))
    prob, why = 0, []
    adj = list(LEVEL_ADJ)
    if (r := words_rx(rk.get("off_field", []))):
        adj.append((r + r"\w*\b", -18, "off_field"))
    for pat, pts, label in adj:
        if re.search(pat, title, re.I):
            prob += pts; why.append(label)
    if rk.get("licence_required") and re.search(rk["licence_required"], text, re.I):
        prob -= 6; why.append("no_licence")
    if (r := words_rx(rk.get("missing_credentials", []))) and re.search(r + r"\b", text, re.I):
        prob -= 8; why.append("no_credential")
    yrs = min_years_required(text)
    if yrs is not None:
        prob += {1: 6, 2: 6, 3: 2, 4: -8}.get(yrs, -15 if yrs >= 5 else 0)
        why.append(f"years:{yrs}")
    loc = job.get("location", "")
    if (r := words_rx(rk.get("preferred_locations", []))) and re.search(r + r"\b", loc, re.I):
        prob += 6
    elif (r := words_rx(rk.get("secondary_locations", []))) and re.search(r + r"\b", loc, re.I):
        prob += 3                                          # second choice: behind preferred, ahead of anywhere else
    m = re.findall(r"\$?\s?(\d{2,3})(?:,000|k)", job.get("salary", "") or "", re.I)
    if m and min(int(x) for x in m) >= rk.get("senior_salary_from_k", 150):   # a range is judged by its floor
        prob -= 10; why.append("senior_salary")
    rec = 0
    try:
        rec = {0: 6, 1: 3}.get((date.today() - date.fromisoformat(job.get("listed", "")[:10])).days, 0)
    except ValueError:
        pass
    total = max(0, min(100, 30 + fit + prob + rec))
    label = "high" if prob >= 10 else "medium" if prob >= -5 else "low"
    return total, core + support, {"prob": label, "why": why}           # codes; LABELS turns them into words


STOP = {"and", "or", "the", "with", "for", "from", "into", "that", "this", "your", "our", "their", "across", "within"}


def focus_phrases(hits: list[str], job: dict[str, Any], track: dict[str, Any], role: str, n: int = 3) -> list[str]:
    """The ad's own wording for the track's core keywords it mentions: "GIS", "hydrology" (from the stem "hydrolog"),
    "spatial information" (an adjective takes the ad's next word, or is dropped). Words in the role title are skipped."""
    core = set(track.get("keywords", {}).get("core", hits))
    text = " ".join([job.get("title", ""), job.get("teaser", ""), " ".join(job.get("bullets", [])), job.get("description", "")])
    out: list[str] = []
    for h in [h for h in hits if h in core]:
        m = re.search(rf"\b{re.escape(h)}\b", text, re.I) or re.search(rf"\b{re.escape(h)}[\w-]*", text, re.I)
        if not m:
            continue
        phrase = m.group()
        tail = phrase[len(h):].lower()
        if tail in ("s", "es"):                           # "audits", "compliances": the keyword itself reads better
            phrase = phrase[:len(h)]
        elif re.fullmatch(r"(or|er)s?", tail):            # "auditors" is a person, not a skill
            continue
        if " " not in phrase and re.search(r"(al|ic|ed)$", phrase, re.I):     # adjective: needs its noun
            nxt = re.match(r"\s+([A-Za-z][\w-]{3,})", text[m.end():])
            if not nxt or nxt.group(1).lower() in STOP:
                continue
            phrase += " " + nxt.group(1)
        acronym = any(re.search(r"[A-Z]", w[1:]) for w in phrase.split())
        if not acronym or (phrase.isupper() and len(phrase.replace(" ", "")) > 5):
            phrase = phrase.lower()                       # keep GIS, ArcGIS, ISO 14001; not "Environmental Management"
        low = phrase.lower()
        if low in role.lower() or any(low in o.lower() or o.lower() in low for o in out):
            continue
        out.append(phrase)
        if len(out) == n:
            break
    return out


def fill_letter(tpl: dict[str, Any], job: dict[str, Any], hits: list[str], track: dict[str, Any] | None = None) -> dict[str, Any]:
    l = json.loads(json.dumps(tpl))
    l.pop("_instrucciones", None)
    track = track or {}
    company = job.get("company") or "your organisation"
    # "(12 Month Fixed Term)", "- 6 month contract": contract notes are not part of the role, and their numbers
    # would fail the facts check
    role = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", job["title"].split(" | ")[0])   # "Role | Site | 8/6 Roster"
    role = re.sub(r"\s*[-–|]\s*\d+\s*(month|mth|year|yr|week)\w*.*$", "", role, flags=re.I).strip() or job["title"]
    source = "SEEK" if job["platform"] == "seek" else "LinkedIn"
    focus = focus_phrases(hits, job, track, role)
    strengths = track.get("letter_strengths", "practical experience, careful documentation and a reliable approach")
    l["date"] = date.today().strftime("%-d %B %Y")
    l["recipient"] = ["Hiring Manager", company, job.get("location", "")]
    l["salutation"] = "Dear Hiring Manager"
    l["re"] = f"Re: {role}"
    l["sign_off"] = "Yours faithfully"
    p = l["paragraphs"]
    for k, v in list(p.items()):
        p[k] = (v.replace("{{position}}", role).replace("{{company}}", company).replace("{{source}}", source)
                 .replace("{{team_or_projects}}", "your team"))
    if focus:
        joined = focus[0] if len(focus) == 1 else ", ".join(focus[:-1]) + " and " + focus[-1]
        lead = f"The {role} role at {company}, with its focus on {joined}, matches the work I have done and want to keep doing."
    else:
        lead = (f"The {role} role at {company} is the kind of {track.get('letter_focus_fallback', 'work')} "
                f"I have done and want to keep doing.")
    p["why_company"] = f"{lead} I would bring {strengths}."
    return l


def notes_for(job: dict[str, Any], hits: list[str], odds: dict[str, Any] | None = None, slug: str = "") -> dict[str, str]:
    """Plain-language summary for the person: what the role is, why it fits, odds, what to watch, how to apply."""
    from triage import min_years_required
    L = labels(slug)
    text = " ".join([job.get("teaser", ""), " ".join(job.get("bullets", [])), job.get("description", "")])
    first = re.split(r"(?<=[.!?])\s", (job.get("teaser") or job.get("description") or "").strip())[0][:220]
    watch = []
    yrs = min_years_required(text)
    if yrs:
        watch.append(L["years_long"].format(n=yrs))
    if re.search(r"permanent residen|residency|citizen|security clearance", text, re.I):   # not "our residents"
        watch.append(L["residency"])
    if re.search(r"\b(senior|principal|lead)\b", job["title"], re.I):
        watch.append(L["senior_title"])
    if re.search(r"graduate", job["title"], re.I):
        watch.append(L["graduate"])
    how = (L["how_li_easy"] if job.get("easy_apply") else L["how_li"]) if job["platform"] == "linkedin" else L["how_seek"]
    odds = odds or {}
    watch += [L[w] for w in odds.get("why", []) if w in WATCH]
    return {"role": first or job["title"], "fits": ", ".join(hits[:5]) or L["check_ad"],
            "prob": L.get(odds.get("prob", ""), ""), "watch": "; ".join(watch) or "—", "how": how}


def primary_track(targets: dict[str, Any]) -> dict[str, Any]:
    return next((t for t in targets["tracks"] if t.get("primary")), targets["tracks"][0])


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:40]


def package_dir(slug: str, day: str | None = None) -> Path:
    """Daily package for the person: $JOB_PACKAGE_DIR (default ~/job-packages)/<slug>/<YYYY-MM-DD>/.
    Keep it outside ~/Documents on macOS: launchd jobs cannot write there."""
    d = Path(os.environ.get("JOB_PACKAGE_DIR", Path.home() / "job-packages")) / slug / (day or today())
    d.mkdir(parents=True, exist_ok=True)
    return d


def prepare(slug: str, max_n: int, requeue: list[str] | None = None) -> list[dict[str, Any]]:
    base = cand_dir(slug)
    targets = read_json(base / "targets.json")
    tracks = {t["id"]: t for t in targets["tracks"]}
    tracked = {a["key"]: a for a in load(slug)}
    seen = set(tracked) - set(requeue or [])
    short = [j for j in read_json(run_dir(slug) / "shortlist.json")["shortlist"] if j["key"] not in seen]
    for k in requeue or []:                     # previously skipped jobs the person wants back
        a = tracked.get(k)
        if a and k not in {j["key"] for j in short}:
            short.append({"key": k, "id": k.split(":", 1)[1], "platform": a["platform"], "title": a["title"],
                          "company": a.get("company", ""), "url": a["url"], "location": a.get("location", ""),
                          "track": a.get("track") or primary_track(targets)["id"], "listed": a.get("date", ""), "teaser": a.get("summary", "")})
    done = {dedupe_key(a.get("title", ""), a.get("company") or "") for a in tracked.values() if a["key"] in seen}
    ranked = []
    for sc, j in sorted(((score(j, targets, slug), j) for j in short), key=lambda x: x[0][0], reverse=True):
        dk = dedupe_key(j.get("title", ""), j.get("company") or "")
        if dk not in done and len(ranked) < max_n:
            done.add(dk); ranked.append((sc, j))
    pkg = package_dir(slug)
    intake = read_json(base / "intake.json")
    first_last = intake["name"].replace(" ", "_")
    manifest = pkg / "items.json"
    out = read_json(manifest, {"items": []})["items"]
    start = max([x["n"] for x in out], default=0)
    ranked = ranked[:max(0, max_n - len(out))]            # --max is per day: a second run only tops the package up
    for i, ((fit, hits, odds), j) in enumerate(ranked, start + 1):
        track = tracks[j["track"]]
        d = pkg / f"{i:02d}_{safe(j.get('company') or 'company')}_{safe(j['title'])}"
        d.mkdir(exist_ok=True)
        letter_json = d / "letter.json"
        save_json(letter_json, fill_letter(read_json(base / track["letter"]), j, hits, track))
        r = build(slug, letter_json, "letter", d, f"{first_last}_Cover_Letter")
        cv_src = base / track.get("cv_pdf", f"docs/master/{first_last}_Resume.pdf")
        cv = d / f"{first_last}_Resume.pdf"
        shutil.copy(cv_src, cv)
        summary = f"{j['track']} · matches: {', '.join(hits[:5]) or '—'}"
        if j["key"] not in tracked:
            add(slug, {"key": j["key"], "title": j["title"], "company": j.get("company"), "url": j["url"],
                       "platform": j["platform"], "track": j["track"], "location": j.get("location", ""), "fit": fit,
                       "summary": summary})
        if r["ok"]:
            set_status(slug, j["key"], "prepared", cv=str(cv), letter=r["pdf"], summary=summary)
        else:
            set_status(slug, j["key"], "manual-review", reason=f"letter check failed: {r['problems']}")
        out.append({"notes": notes_for(j, hits, odds, slug), "n": i, "key": j["key"], "title": j["title"], "company": j.get("company", ""), "url": j["url"],
                    "platform": j["platform"], "location": j.get("location", ""), "fit": fit, "track": j["track"],
                    "dir": d.name, "ok": r["ok"], "easy_apply": j.get("easy_apply")})
    save_json(manifest, {"items": out})
    write_index(pkg, out, slug)
    return [x for x in out if x["n"] > start]


def write_index(pkg: Path, items: list[dict[str, Any]], slug: str) -> None:
    day, L = pkg.name, labels(slug)
    cards, md = [], [f"# {L['title']} · {day} ({len(items)})", "", L["howto"], ""]
    for x in items:
        n = x.get("notes") or {"role": x["title"], "fits": "", "watch": "—", "how": x["platform"]}
        prob = f"{n['prob']} ({L['score']} {x['fit']})" if n.get("prob") else f"{L['score']} {x['fit']}"
        md += [f"## {x['n']}. {x['title']} — {x['company']}", f"- **{L['what']}:** {n['role']}", f"- **{L['fits']}:** {n['fits']}",
               f"- **{L['odds']}:** {prob}", f"- **{L['watch']}:** {n['watch']}", f"- **{L['apply']}:** {n['how']}",
               f"- **{L['ad']}:** {x['url']}", f"- **{L['folder']}:** `{x['dir']}`", ""]
        (pkg / x["dir"]).mkdir(exist_ok=True)
        (pkg / x["dir"] / L["readme_file"]).write_text(
            f"# {x['title']} — {x['company']}\n\n- {L['what']}: {n['role']}\n- {L['fits']}: {n['fits']}\n- {L['odds']}: {prob}\n"
            f"- {L['watch']}: {n['watch']}\n- {L['apply']}: {n['how']}\n- {L['ad']}: {x['url']}\n\n{L['upload']}\n")
        cards.append(f"<li style='margin-bottom:14px'><b>{x['n']}. {html.escape(x['title'])}</b> — {html.escape(x['company'])}"
                     f"<br><i>{html.escape(n['role'])}</i><br>✅ {html.escape(n['fits'])}<br>🎯 {L['odds']}: {html.escape(prob)}"
                     f"<br>⚠️ {html.escape(n['watch'])}"
                     f"<br>📝 {html.escape(n['how'])} · <a href='{x['url']}'>{L['open_ad']}</a> · <a href='{x['dir']}/'>{L['folder']}</a></li>")
    pkg.joinpath(L["summary_file"]).write_text("\n".join(md))
    pkg.joinpath("index.html").write_text(
        f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>{L['title']} {day}</title>"
        f"<body style='font-family:system-ui;max-width:760px;margin:auto;padding:16px'><h2>{L['title']} · {day}</h2>"
        f"<p>{html.escape(L['howto'])}</p>"
        f"<ol style='list-style:none;padding:0;line-height:1.45'>{''.join(cards)}</ol></body>")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug"); ap.add_argument("--max", type=int, default=15, help="jobs per day (a later run the same day only tops up)")
    ap.add_argument("--requeue", nargs="*", default=[], help="tracker keys previously skipped to prepare anyway")
    a = ap.parse_args()
    items = prepare(a.slug, a.max, a.requeue)
    print(json.dumps({"prepared": len(items), "package": str(package_dir(a.slug)),
                      "jobs": [f"{x['n']}. {x['title']} — {x['company']} (fit {x['fit']})" for x in items]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
