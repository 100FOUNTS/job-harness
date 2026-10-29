# Stage 3 — Master documents

Goal: one CV JSON per track (`docs/cv_<track>.json`) and one cover letter JSON (`docs/cover_letter.json`), built and checked.

Format (Australian, ATS): one column, no tables/text boxes/images/headers/footers, standard headings (Professional Summary, Key Skills, Work Experience, Projects (optional `projects`, same shape as experience), Other Employment, Education and Qualifications, Publications, Additional Information), reverse chronological, uniform dates "May 2025 – Dec 2025", one role per entry, 2 pages (max 3), en-AU spelling, contact in the body, "Referees: Available upon request".

1. Write the JSON (schema = `templates/docs` generators; see an existing candidate's `docs/`). Bullets: action verb + task + how + result, figures only from `facts.json`.
2. `job docs <slug> build docs/cv_<track>.json --kind cv --out candidates/<slug>/docs/master --name <First_Last>_Resume[_TRACK]`. It writes docx + pdf and runs lint + facts verify on both. Fix until `ok: true`.
3. Look at the PDF (`pdftoppm -r 60` on page 1–2) once for spacing. Do not iterate more than needed: the generators already encode the layout.
4. Cover letter JSON: 5 paragraphs (purpose, why this company, technical evidence, Australian/transferable experience, closing with availability), `{{placeholders}}` for company-specific parts, one page.
5. Gate `master-docs` (human): files = the JSONs + built PDFs. Show `job review` / `job sign` and wait.

Lessons (all codified in the generators/lint)
- Calibri/Cambria break PDF text extraction ("restora on") → Arial in docx, Helvetica in the PDF.
- Pages ignores "space before" and hangs on unseen dialogs when unattended → PDFs come from `generar_pdf.js` (pdfkit), headless.
- Two titles in one entry ("Assistant Manager | Shift Lead") confuse ATS → one entry per role.
