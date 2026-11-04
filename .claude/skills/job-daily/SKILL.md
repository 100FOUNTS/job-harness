---
name: job-daily
description: Runs the daily job-application cycle for a job-harness candidate: discover new jobs, pre-filter, judge fit, tailor CV and cover letter, apply (or dry-run) within limits, and write the daily report. Use for "/job-daily ana", "run today's applications", "corre el ciclo diario", or when the agent-driven daily schedule calls it (`job schedule install <slug> --runner agent`).
argument-hint: "<slug>"
arguments: [slug]
---

# Daily cycle — candidate **$slug**

This is the agent-driven cycle (modes `dry-run`/`live`, with Claude in Chrome). The default daily schedule (mode `prepare`) does not use it: that run is scripts only (no AI, no browser) and ends with the package for the person to apply from. Under the plugin the command is `/job-harness:job-daily`.

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
- Before the first job: `job routes $slug --hosts` and put the sites it lists in the report's "allow these in Chrome" line (Claude in Chrome asks per site; a refused site stops that job half way). `job answer $slug gaps` lists the common questions with no answer yet: every one of them stops a form that asks it.
- Order: ready jobs first (`job routes $slug --queue`: `ready_to_fill`), then `to_probe` (the form-filler clicks Apply and records the gate). A host already known as `login` is not probed again: the job goes to the login queue.
- At the end, put `login_queue` in the report: one line per portal ("sign in once to <host>: N jobs"). When the person says they signed in, run the form-filler again for those jobs.
- Before each submission in live mode: `job track $slug quota --platform <p>`; if 0 left, stop applying.
- Outcome → `job track $slug set <key> submitted|dry-run|manual-review|failed --note "..."`.
- Wait 4–12 minutes (random) between applications in live mode; in dry-run 30–60 s is enough.

## 4b. Warnings and follow-ups (scripts, no LLM)
- Each prepared job carries `red_flags` in the tracker (pay below the person's minimum, unpaid or commission-only work, upfront fees, a hidden employer, reposts). They are warnings: mention them in your summary, never drop a job because of them.
- Applications sent 10+ days ago with no answer get a draft in their package folder (`followup.md`, tracker field `followup_draft`); `python3 scripts/followup.py $slug due|draft-all`. You may polish a draft's wording, but sending is the person's job: you never send it, and the gates already block sending.

## 5. Close
1. `job report $slug --notify` and show the report path.
2. Rewrite `candidates/$slug/progress.md` (today's counts, manual-review list, anything broken).
3. New lessons (a form pattern, a platform change) → `job learn log --kind platform --area seek|linkedin|forms --lesson "..."`.

## Rules
- Never answer a form field with something not in answers.json/intake.json → manual-review.
- Never mention visa/sponsorship outside a field that explicitly asks. Never write free text beyond the tailored cover letter.
- A step failing twice → record and continue with the next job. Never loop.
