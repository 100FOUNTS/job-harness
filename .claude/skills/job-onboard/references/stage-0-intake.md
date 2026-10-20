# Stage 0 — Intake

Goal: read everything the candidate gave, cheaply, and extract facts with their source.

1. List `intake.source_dir` (CVs, cover letters, Engineers Australia Career Episodes / CDR, certificates, transcripts).
2. Read text, not pages: `pdftotext -layout file.pdf -`, `textutil -convert txt -stdout file.docx`. For long documents, delegate to a subagent and ask for a structured summary (roles, dates, employers, tools, figures, projects) so the main context stays small.
3. LinkedIn (if the user agrees): open the profile in Claude in Chrome and extract **only** the needed fields with `javascript_tool` (`document.querySelector('main').innerText` sliced), never full `get_page_text` dumps. Sections load lazily: open `/details/experience/`, `/details/education/`, `/details/certifications/`, `/details/publications/` separately and wait 3 s each.
4. Public research only when it adds verifiable facts (e.g. the candidate's own publications by title).
5. Ask two languages: `docs_language` for CVs and letters (e.g. en-AU) and `ui_language` for what the person reads in the daily package (`en` or `es`).
6. Record every number with its source: it will become a `facts.json` claim only if the user confirms it can be explained in an interview.

Lessons
- CV, LinkedIn and Career Episodes often disagree on dates. List each conflict; the user decides which is right, and all future documents use that.
- A role in a cover letter but missing in the CV (e.g. current part-time job) usually belongs in "Other Employment".
