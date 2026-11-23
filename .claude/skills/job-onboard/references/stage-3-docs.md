# Stage 3 — Master documents

Goal: one CV JSON per track (`docs/cv_<track>.json`) and one cover letter JSON (`docs/cover_letter.json`), built and checked.

Format (Australian, ATS): one column, no tables/text boxes/images/headers/footers, standard headings (Professional Summary, Key Skills, Work Experience, Projects (optional `projects`: entries like experience, one-line bullets `[name, text]`, or a single paragraph string; `projects_heading` renames it, e.g. "Data and AI Projects (Self-Directed Study, 2026)"), Other Employment, Education and Qualifications, Publications, Additional Information), reverse chronological, uniform dates "May 2025 – Dec 2025" (3-letter months everywhere, including education: "Expected Dec 2026"; a finished degree may stay a bare year "2019", never invent a month), one role per entry, 2 pages (max 3), en-AU spelling, contact in the body, "Referees: Available upon request" (or `referees: ""` to leave the line out, as the guide prefers to an evasive phrase).

1. Write the JSON (schema = `templates/docs` generators; see an existing candidate's `docs/`). Experience-like entries (`experience`, `entrepreneurship`, `projects`, `other_employment`) are `{"role", "org", "dates", "bullets"}` plus an optional `"type"` ("Part-time", "Full-time", "Casual", "Contract", "Fixed-term", "Volunteer", "Internship"), printed after the dates: `Org, City  |  Mar 2022 - Jun 2024  |  Part-time`. Set `type` only when the person's own documents say it; never write it inside `role`. Bullets: action verb + task + how + result, figures only from `facts.json`.
2. `job docs <slug> build docs/cv_<track>.json --kind cv --out candidates/<slug>/docs/master --name <First_Last>_Resume[_TRACK]`. It writes docx + pdf and runs lint + facts verify on both. Fix until `ok: true`.
3. Look at the built PDF once for spacing (open pages 1–2 with the Read tool and its `pages` option). Do not iterate more than needed: the generators already encode the layout.
4. Cover letter JSON: 5 paragraphs (purpose, why this company, technical evidence, Australian/transferable experience, closing with availability), `{{placeholders}}` for company-specific parts, one page.
5. Gate `master-docs`: files = the JSONs + built PDFs. Show the person what they approve (`job review`), ask for their OK in the chat, then sign with `--by-agent` and their words in `--note`.

Lessons (all codified in the generators/lint)
- Calibri/Cambria break PDF text extraction ("restora on") → Arial in docx, Helvetica in the PDF.
- Pages ignores "space before" and hangs on unseen dialogs when unattended → PDFs come from `generar_pdf.js` (pdfkit), headless.
- "Assistant Manager (part-time)" as a role: a parser reads "(part-time)" as part of the job title and misfiles the job's employment type (part-time as full-time, a paid job as volunteer) → plain job title in `role`, the employment type in `type`. `job docs build` warns about it.
- Education dates in long form ("Expected December 2026") next to "Mar 2022 - Jun 2024" in experience: résumé checkers penalise mixed date formats → "Expected Dec 2026". The generators shorten month names; `job docs build` warns when the JSON has them.
- Two titles in one entry ("Assistant Manager | Shift Lead") confuse ATS → one entry per role.
