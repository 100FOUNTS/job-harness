"""A candidate's setup at a glance, for the panel's Profile tab: who, where their files are, which searches run, which rules apply,
what is approved and what is still missing. Read-only: it never writes and never calls the network.

  job profile <slug>        the same data as JSON (what the panel shows)

`checklist` is the answer to "is this candidate ready?": each item is ok, todo (something the harness or the person still has to
do, with the command that does it) or info (worth knowing, not a gap).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import sources
from common import cand_dir, read_json, setting, sponsors_file

APPROVALS = ("master-docs", "profile-changes", "targets", "report", "go-live")
SETUP_STAGES = 6                              # onboarding stages 0 to 5; 6 and 7 are the first daily runs and the go-live review


def package_dir(slug: str) -> Path:
    return Path(setting("JOB_PACKAGE_DIR", str(Path.home() / "job-packages"))) / slug


def approvals(slug: str) -> list[dict[str, Any]]:
    """The newest approval of each type: valid (signed and intact), broken (signed, then a sealed file changed), pending or none."""
    import gates
    allg = gates.load_all(slug)
    out = []
    for typ in APPROVALS:
        mine = [g for g in allg if g["type"] == typ and g["status"] in ("signed", "pending")]
        if not mine:
            out.append({"type": typ, "status": "none", "id": "", "date": ""})
            continue
        g = mine[-1]
        if g["status"] == "pending":
            out.append({"type": typ, "status": "pending", "id": g["id"], "date": (g.get("requested") or "")[:10]})
            continue
        ok, broken = gates.seals_ok(slug, g)
        by = (g.get("signed_by") or {}).get("by", "")
        out.append({"type": typ, "status": "valid" if ok else "broken", "id": g["id"], "broken": broken, "files": sorted(g["files"]),
                    "date": (g.get("signed_at") or g.get("requested") or "")[:10], "by": by})
    return out


def searches(targets: dict[str, Any]) -> dict[str, Any]:
    tracks, used = [], set()
    for t in targets.get("tracks", []):
        ss = [{"platform": s.get("platform", ""), "what": next((str(s[k]) for k in ("keywords", "board", "company", "account", "what") if s.get(k)), ""),
               "where": s.get("location") or s.get("where") or ""} for s in t.get("searches", [])]
        used |= {s["platform"] for s in ss}
        di = t.get("description_include") or {}
        tracks.append({"id": t.get("id", ""), "title_phrases": len(t.get("title_include", [])), "excluded_titles": t.get("exclude_title") or [],
                       "description_fallback": bool(di), "keywords": len((t.get("keywords") or {}).get("core", [])),
                       "searches": ss})
    srcs = []
    for name in sorted(used):
        m = sources.get(name)
        srcs.append({"name": name, "known": m is not None, "configured": bool(m and sources.configured(m)),
                     "setup": getattr(m, "SETUP", "") if m else f"no source called '{name}'"})
    return {"tracks": tracks, "sources": srcs, "locations": targets.get("locations_include", []),
            "excluded_titles": targets.get("exclude_title", []), "excluded_text": targets.get("exclude_text", []),
            "max_age_days": targets.get("max_age_days"), "max_years_required": targets.get("max_years_required")}


def documents(slug: str, tracks: list[dict[str, Any]]) -> dict[str, Any]:
    """Each track's CV is the file its `cv` names (several tracks may share one master), by default docs/cv_<track>.json."""
    base = cand_dir(slug)
    have = sorted(p.name for p in (base / "docs" / "master").glob("*.pdf")) if (base / "docs" / "master").is_dir() else []
    missing = sorted({t.get("cv") or f"docs/cv_{t['id']}.json" for t in tracks if not (base / (t.get("cv") or f"docs/cv_{t['id']}.json")).exists()})
    if not (base / "docs" / "cover_letter.json").exists():
        missing.append("docs/cover_letter.json")
    return {"master_pdfs": have, "missing": missing}


def checklist(p: dict[str, Any]) -> list[dict[str, str]]:
    slug, st, ap = p["slug"], p["state"], {a["type"]: a for a in p["approvals"]}
    items: list[dict[str, str]] = []

    def add(id_: str, label: str, ok: bool, detail: str, fix: str = "", info: bool = False) -> None:
        items.append({"id": id_, "label": label, "status": "ok" if ok else ("info" if info else "todo"), "detail": detail, "fix": "" if ok else fix})

    c = p["identity"]
    missing = [k for k in ("email", "phone") if not c.get(k)]
    add("contact", "Contact details", not missing, "Email and phone are set." if not missing else f"Missing: {', '.join(missing)}.",
        f"Fill them in candidates/{slug}/intake.json")
    undone = [str(k) for k in range(SETUP_STAGES) if (st["stages"].get(str(k)) or {}).get("status") != "done"]     # a stage never recorded is not done
    add("onboarding", "Onboarding stages 0 to 5", not undone, "Intake, profile, tracks, master documents, platform profiles and alerts are done."
        if not undone else f"Not done: stage {', '.join(sorted(undone, key=int))}.", f"/job-onboard {undone[0] if undone else 0} {slug}")
    s = p["searches"]
    empty = [t["id"] for t in s["tracks"] if not t["searches"]]
    add("searches", "Searches", bool(s["tracks"]) and not empty, f"{len(s['tracks'])} track(s), {sum(len(t['searches']) for t in s['tracks'])} searches."
        if s["tracks"] and not empty else ("No tracks yet." if not s["tracks"] else f"No searches for: {', '.join(empty)}."), f"/job-onboard 2 {slug}")
    bad = [x for x in s["sources"] if not x["known"] or not x["configured"]]
    add("sources", "Job sources", not bad, "Every source the searches use is available." if not bad
        else "; ".join(f"{x['name']}: {x['setup'] or 'not available'}" for x in bad), "job doctor")
    docs = p["documents"]
    no_pdf = not docs["master_pdfs"]
    add("documents", "Master documents", not docs["missing"] and not no_pdf,
        f"{len(docs['master_pdfs'])} master PDFs built." if not docs["missing"] and not no_pdf
        else (f"Missing: {', '.join(docs['missing'])}." if docs["missing"] else "The CV files exist but no master PDF is built yet."), f"/job-onboard 3 {slug}")
    live = ap["go-live"]
    sealed = live["status"] == "valid" and "targets.json" in live.get("files", [])        # go-live seals the targets too
    for typ, label in (("master-docs", "Master documents approved"), ("targets", "Targets approved")):
        a = ap[typ]
        if typ == "targets" and sealed and a["status"] != "valid":
            add(typ, label, True, f"Sealed by the go-live approval ({live['id']}).")
            continue
        add(typ, label, a["status"] == "valid", f"Signed ({a['id']}{', ' + a['date'] if a['date'] else ''})." if a["status"] == "valid"
            else {"pending": "Waiting for a signature.", "broken": f"A sealed file changed: {', '.join(a.get('broken', []))}.", "none": "Never approved."}[a["status"]],
            f"job review {slug} {a['id']} then job sign {slug} {a['id']}" if a["status"] == "pending" else f"job gate request {slug} --type {typ} ...")
    ans = p["answers"]
    sens = [g["question"] for g in ans["unanswered"] if g["sensitive"]]
    add("answers", "Answers to form questions", not ans["unanswered"], f"All {ans['total']} common questions have an answer."
        if not ans["unanswered"] else f"{len(ans['unanswered'])} of {ans['total']} have no answer ({len(sens)} sensitive). A form that asks one stops for you.",
        f"job answer {slug} gaps")
    add("confirm", "Improvised answers confirmed", ans["to_confirm"] == 0, "Nothing waiting." if not ans["to_confirm"]
        else f"{ans['to_confirm']} improvised answer(s) wait for you.", f"job answer {slug} pending")
    add("facts", "Confirmed figures", p["facts"]["claims"] > 0, f"{p['facts']['claims']} confirmed figure(s)."
        if p["facts"]["claims"] else "No figures confirmed yet: a CV cannot state numbers.", f"job facts {slug} add ...")
    add("go-live", "Go-live", live["status"] == "valid", f"Mode is {st['mode']}, and the go-live approval is valid."
        if live["status"] == "valid" else f"Mode is {st['mode']}: nothing is sent until you sign go-live. That is the default.",
        f"job gate request {slug} --type go-live ...", info=True)
    add("sponsors", "Visa sponsor lists", p["sponsor_lists"], "Loaded (shown only to the person)." if p["sponsor_lists"]
        else "Not loaded: board cards show no sponsor badge.", "job sponsors import <file>", info=True)
    return items


def only_if_asked(raw: Any) -> list[str]:
    """Names of the sensitive answers that are only ever used in a field that asks (`citizen_or_pr` → "citizen or pr")."""
    keys = raw.keys() if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    return sorted({str(k).replace("_", " ").strip() for k in keys if not str(k).startswith("_")})


def profile(slug: str) -> dict[str, Any]:
    from status import summary
    base = cand_dir(slug)
    intake = read_json(base / "intake.json", {})
    targets = read_json(base / "targets.json", {})
    answers = read_json(base / "answers.json", {"answers": []})["answers"]
    contact = intake.get("contact") or {}
    sm = summary(slug)
    stages = read_json(base / "state.json", {}).get("stages", {})
    s = searches(targets)
    import answer
    gaps = answer.gaps(slug)
    pending = [q for q in read_json(base / "pending_questions.json", {"questions": []}).get("questions", []) if q.get("status") == "to-confirm"]
    facts = read_json(base / "facts.json", {})
    rules = intake.get("rules") or {}
    out: dict[str, Any] = {
        "slug": slug,
        "identity": {"name": intake.get("name", slug), "email": contact.get("email", ""), "phone": contact.get("phone", ""),
                     "location": contact.get("location_on_cv", ""), "docs_language": intake.get("docs_language", ""),
                     "ui_language": intake.get("ui_language", "")},
        "folders": {"candidate": str(base), "packages": str(package_dir(slug)), "documents": str(base / "docs")},
        "state": {"mode": sm["mode"], "limits": sm["limits"], "quota": sm["quota"], "next": sm["next"], "label": sm["state"]["label"],
                  "stages": {k: {"name": v.get("name", ""), "status": v.get("status", ""), "summary": v.get("summary", "")} for k, v in sorted(stages.items(), key=lambda x: int(x[0]))}},
        "approvals": approvals(slug),
        "searches": s,
        "rules": {"never_mention": rules.get("never_mention", []), "never_include": rules.get("never_include", []), "other": rules.get("other", []),
                  "only_if_asked": only_if_asked(intake.get("sensitive_only_if_asked"))},
        "preferences": intake.get("preferences", {}),
        "answers": {"total": len(answers), "answered": len(answers) - len(gaps), "unanswered": gaps, "to_confirm": len(pending)},
        "facts": {"claims": len(facts.get("claims", []) if isinstance(facts.get("claims"), list) else facts.get("claims", {})),
                  "allow": len(facts.get("allow", []))},
        "documents": documents(slug, targets.get("tracks", [])),
        "sponsor_lists": sponsors_file().exists(),
    }
    out["checklist"] = checklist(out)
    out["progress"] = {"ok": sum(i["status"] == "ok" for i in out["checklist"]),
                       "todo": sum(i["status"] == "todo" for i in out["checklist"]),
                       "total": sum(i["status"] != "info" for i in out["checklist"])}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    a = ap.parse_args()
    print(json.dumps(profile(a.slug), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
