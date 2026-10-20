---
name: job-onboard
description: Onboards a job-search candidate in the job-harness, one stage at a time (intake, profile and gaps, target tracks, master CV/cover letter, SEEK/LinkedIn profiles, alerts). Use when the user says "onboard <name>", "/job-onboard 2 ana", "create the master CV", "fix the LinkedIn/SEEK profile" or "set up alerts".
argument-hint: "<stage 0-5> <slug>"
arguments: [stage, slug]
---

# Onboarding orchestrator

Stage **$stage** · candidate **$slug**. Answer the user in Spanish; candidate documents in en-AU.

## Before starting (always)
1. `job status $slug` — stage states, pending signatures, broken seals, open questions, next step. If the candidate does not exist: `job new $slug --name "..." --source-dir "..."`.
2. Read `candidates/$slug/progress.md`, `intake.json`, `CLAUDE.md`. Never rely on chat history.
3. `job learn list` — apply the lessons (they exist because something went wrong before).

## Stages
| Stage | Procedure | Output | Gate |
|---|---|---|---|
| 0 Intake | [references/stage-0-intake.md](references/stage-0-intake.md) | source docs read, facts extracted | — |
| 1 Profile and gaps | [references/stage-1-profile.md](references/stage-1-profile.md) | intake.json, answers.json, facts.json, questions | — |
| 2 Target tracks | [references/stage-2-targets.md](references/stage-2-targets.md) | targets.json | targets (agent after OK) |
| 3 Master documents | [references/stage-3-docs.md](references/stage-3-docs.md) | docs/*.json → docx/pdf, lint + facts ok | master-docs (human) |
| 4 Platform profiles | [references/stage-4-profiles.md](references/stage-4-profiles.md) | proposal → approved changes applied | profile-changes (human) |
| 5 Alerts | [references/stage-5-alerts.md](references/stage-5-alerts.md) | saved searches = targets.searches | — |

## When finishing a stage (always)
1. `job state $slug stage $stage --status done --summary "..."` (or `blocked` + `job ask $slug add "..." --blocks $stage`).
2. Request the stage gate if it has one, show the user the exact commands to review and sign, and wait.
3. Rewrite `candidates/$slug/progress.md` (done / pending / next step).
4. Any new lesson → `job learn log --kind ... --area ... --lesson "..."`.

## Rules for every stage
- Ask only what is missing; propose defaults the user can override. One short list of questions at a time.
- Never write a user-visible claim you cannot trace to a source document or to the user's words.
- Profile edits and alerts change the person's accounts: only after explicit approval in chat, one tab at a time.
- Never delete anything in the person's accounts; tell the user what to delete.
