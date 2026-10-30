---
name: job-daily
description: Runs the daily job-application cycle for a job-harness candidate: discover new jobs, pre-filter, judge fit, tailor CV and cover letter, apply (or dry-run) within limits, and write the daily report. Use for "/job-daily ana", "run today's applications", or when launchd calls it.
argument-hint: "<slug>"
arguments: [slug]
---

# Daily cycle — candidate **$slug**

Run unattended. No questions to the user: anything uncertain becomes `manual-review` with a reason. Stay cheap: scripts do data, you only judge and write.

## 0. Preflight
1. `job status $slug --json` → `mode`, `go_live`, `quota`. **Effective mode = live only if mode is live AND go_live is true**; otherwise dry-run.
2. If `candidates/$slug/STOP` exists → write the report and stop.

## 1. Data (scripts, no LLM)
If `candidates/$slug/data/<today>/shortlist.json` does not exist: `job discover $slug` then `job triage $slug`.
Both write `candidates/$slug/jobs.db`: ads already rejected under the same targets are not listed again, and descriptions already fetched are reused. For questions across days (who hires, which requirement keeps excluding the person, a possible repost) query it: `job db $slug sql "SELECT ..."`.

## 1b. Carry-over
Jobs already in the tracker with status `prepared` (documents built on a previous run or by hand) go straight to step 4 first, using their recorded `cv`/`letter` paths: `job track $slug list --status prepared`. They count towards today's quota.

## 2. Judge (agent `job-triager`, no browser)
Give it the shortlist path and the candidate folder. It returns, per job: `select` true/false, `fit` 0–100, `track`, a 1–2 line `summary` (what the role is + why it fits), and `reason` if not selected.
- Respect quota per platform: never select more than `quota.platform_left` per platform nor `quota.day_left` in total.
- Record every shortlisted job so it is never judged twice: `job track $slug add --key ... --title ... --company ... --url ... --platform ... --track ... --fit N --summary "..."`, then for the not selected `job track $slug set <key> skipped --reason "..."`.

## 3. Tailor (agent `tailor-writer`, no browser) — per selected job
Writes `data/<today>/apps/<key-with-underscore>/cv.json` and `letter.json` from the track's master JSONs. Then:
`job docs $slug build data/<today>/apps/<dir>/cv.json --kind cv --name <First_Last>_Resume` and the same for `letter.json --kind letter --name <First_Last>_Cover_Letter`.
If `ok` is false: give the problems back to the writer once; still failing → `job track $slug set <key> manual-review --reason "docs check failed: ..."`.
Success → `job track $slug set <key> prepared --cv <pdf> --letter <pdf>`.

## 4. Apply (agent `form-filler`, browser) — one job at a time
Pass: the job URL, the PDFs, `answers.json`, `intake.json`, and the effective mode.
- Before each submission in live mode: `job track $slug quota --platform <p>`; if 0 left, stop applying.
- Outcome → `job track $slug set <key> submitted|dry-run|manual-review|failed --note "..."`.
- Wait 4–12 minutes (random) between applications in live mode; in dry-run 30–60 s is enough.

## 5. Close
1. `job report $slug --notify` and show the report path.
2. Rewrite `candidates/$slug/progress.md` (today's counts, manual-review list, anything broken).
3. New lessons (a form pattern, a platform change) → `job learn log --kind platform --area seek|linkedin|forms --lesson "..."`.

## Rules
- Never answer a form field with something not in answers.json/intake.json → manual-review.
- Never create accounts (Workday/PageUp/etc.), enter passwords, solve captchas or accept new terms → manual-review.
- Never mention visa/sponsorship outside a field that explicitly asks. Never write free text beyond the tailored cover letter.
- A step failing twice → record and continue with the next job. Never loop.
