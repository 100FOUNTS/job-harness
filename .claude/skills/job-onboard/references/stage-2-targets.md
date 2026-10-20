# Stage 2 — Target tracks

Goal: `targets.json` — the role families the candidate will apply to, each with its own CV, title keywords and searches.

1. Propose 1–3 tracks (e.g. main profession + an entry-level adjacent track the person is studying for). For each: realistic titles, `title_include` keywords, and searches per platform (SEEK keywords + where; LinkedIn keywords + location).
2. Per track, for the daily ranking: `keywords` {core: what the CV proves strongly, support: adjacent skills} (left empty, the terms of the track CV's skills list are used), `cv_pdf` (master PDF to attach), `letter_focus_fallback` and `letter_strengths` (one phrase each for the letter), `primary: true` on the main track (its CV answers years-of-experience questions). Optional `description_include` {words, min, titles}: a generic title ("Fire Planning Officer") joins the track when the ad mentions its words at least `min` times.
3. `ranking` block (the person's odds, not skills): `off_field` title words of neighbouring professions they are not (e.g. geotechnical, surveyor), `missing_credentials` (CEnvP, CPEng, Green Star…), `licence_required` regex for a local licence they lack, `preferred_locations` (first choice) / `secondary_locations` (second choice, still ahead of anywhere else), `senior_salary_from_k`. Seniority, years asked and recency are scored the same for everyone.
4. Global filters: `exclude_title` (seniority not targeted), `exclude_text` (citizenship/PR/clearance), `locations_include`, `max_age_days`.
5. Check search volume before saving: open each search once; a keyword with 0 results or thousands of irrelevant ones is replaced (e.g. "GIS Officer" 0 → "GIS Analyst"; "Environmental GIS" too broad → dropped).
6. Dry-test: `job discover <slug> --dry` then `job triage <slug>` and show the user the shortlist and the rejection reasons. Adjust keywords until the shortlist looks right.
7. Gate `targets` (agent may sign after the user's explicit OK in chat).

Lessons
- A seniority range ("Scientist to Associate Director") is judged by its entry point; `exclude_title` only looks before " to ".
- Practice exercises are not evidence for a CV; an adjacent track is supported by real skills, courses and transferable experience.
- Do not filter "no sponsorship available" ads when the candidate has full work rights for the near term (e.g. a graduate visa); filter only citizenship/PR/clearance requirements.
