# Stage 0 — Intake

Goal: read everything the candidate gave, cheaply, and extract facts with their source.

1. List `intake.source_dir` (CVs, cover letters, Engineers Australia Career Episodes / CDR, certificates, transcripts).
2. Read text, not pages. PDF: `python3 -c "import sys; sys.path.insert(0, sys.argv[1]); import pdftext; print(pdftext.text(sys.argv[2]))" "<harness folder>/scripts" file.pdf` (plugin install: the harness folder is `${CLAUDE_PLUGIN_ROOT}`; Windows: `py -3` instead of `python3`; it needs `job setup` to have run once, and finds the PDF reader in a clone or a plugin install alike). A short PDF can also simply be opened with the Read tool. Word `.docx`: `python3 -c "import zipfile,re,sys; x=zipfile.ZipFile(sys.argv[1]).read('word/document.xml').decode('utf8'); print(re.sub(r'<[^>]+>','',x.replace('</w:p>','\n')))" file.docx`. Old `.doc`, or a file either command cannot read: ask the person to save it as PDF or `.docx`. For long documents, delegate to a subagent and ask for a structured summary (roles, dates, employers, tools, figures, projects) so the main context stays small.
3. LinkedIn (if the user agrees): open the profile in Claude in Chrome and extract **only** the needed fields with `javascript_tool` (`document.querySelector('main').innerText` sliced), never full `get_page_text` dumps. Sections load lazily: open `/details/experience/`, `/details/education/`, `/details/certifications/`, `/details/publications/` separately and wait 3 s each.
4. Public research only when it adds verifiable facts (e.g. the candidate's own publications by title).
5. Ask two languages: `docs_language` for CVs and letters (e.g. en-AU) and `ui_language` for what the person reads in the daily package (`en` or `es`).
6. Record every number with its source: it will become a `facts.json` claim only if the user confirms it can be explained in an interview.

Lessons
- CV, LinkedIn and Career Episodes often disagree on dates. List each conflict; the user decides which is right, and all future documents use that.
- A role in a cover letter but missing in the CV (e.g. current part-time job) usually belongs in "Other Employment".
