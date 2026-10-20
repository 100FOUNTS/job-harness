# job-harness

A Claude Code harness that takes a candidate from "here is my folder" to daily, rule-abiding job applications in Australia: intake → profile and gaps → target tracks → master documents → SEEK/LinkedIn profiles → alerts → daily cycle (dry-run, then live) with a daily report.

## Language
Code, keys and internal notes in English. Answer the user in their language. Candidate documents are in the intake's `docs_language` (en-AU: organise, licence, modelling…).

## How to work here
- **Entry points:** `/job-onboard <stage> <slug>` (stages 0–5), `/job-daily <slug>` (the daily cycle; also run by launchd), `/job-learn`. In the terminal everything goes through `bin/job` (`job help`).
- **Source of truth:** `candidates/<slug>/` → `intake.json`, `targets.json`, `answers.json`, `facts.json`, `state.json`, `tracker.json`, `progress.md`, `approvals/`, `docs/`, `data/<date>/`. Never the chat history. The SessionStart hook injects `job status --context`.
- **Scripts for data, agents for judgment.** Discovery (`job discover`) and pre-filtering (`job triage`) are code: no browser, no LLM. Claude judges the shortlist, writes tailored documents and fills forms.
- **Browser:** Claude in Chrome, one tab at a time, closed when done. The user's own Chrome holds the SEEK/LinkedIn sessions.

## Rules
- **Truthfulness:** never invent experience, qualifications, software, dates or figures. Every figure in a CV or letter must exist in `facts.json` (`job facts verify`). A form question not covered by `answers.json`/`intake.json` → `manual-review`, never a guess.
- **Candidate rules** live in `intake.rules` (e.g. never mention visa/sponsorship; never include practice exercises) and are enforced by `job lint`.
- **Sensitive answers** (`intake.sensitive_only_if_asked`) only when a form field explicitly asks. Never in letters, CVs or free text.
- **Sealed approvals:** `master-docs`, `profile-changes`, `targets` and `report` may be signed with `--by-agent --note "User approved in chat: '<their words>'"`, **only after an explicit OK from the user in the chat for that specific approval**. Never on your own initiative. `go-live` needs the person's own signature in their terminal (`job sign`) unless the owner set `JOB_HUMAN_SIGN=""`.
- **Dry-run by default.** Submitting needs `mode live` + a signed, intact `go-live`. The hook blocks "submit" clicks otherwise. Editing intake/targets/master docs after go-live breaks the seal → back to dry-run.
- **Limits:** `job track <slug> quota` before every submission (per platform, per day, per week). The tracker refuses to mark more.
- **Never delete** anything in the person's accounts or in `candidates/` (hook-enforced). If something should be deleted, tell the user.
- **Never** create accounts, enter passwords, solve captchas, or accept new terms. Those → `manual-review`.
- **Bookkeeping** (`state.json`, `facts.json`, `tracker.json`, `approvals/`) only changes through `job state|facts|track|gate`.
- **Failures:** a step that fails twice → skip it, record it, continue. Every new lesson → `job learn log` and, if it is code, a test.

## Development
- `job test` before accepting changes to `scripts/`, `hooks/`, `bin/`.
- A new step is done by hand once, then codified (scripts + reference). Lessons so far: `learn/observations.jsonl`.
