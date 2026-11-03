---
name: job-onboard
description: Onboards a job-search candidate in the job-harness, one stage at a time (intake, profile and gaps, target tracks, master CV/cover letter, SEEK/LinkedIn profiles, alerts). Use when the user says "onboard <name>", "/job-onboard 2 ana", "create the master CV", "fix the LinkedIn/SEEK profile" or "set up alerts".
argument-hint: "<stage 0-5> <slug>"
arguments: [stage, slug]
---

# Onboarding orchestrator

Stage **$stage** · candidate **$slug**. Answer the user in their language; candidate documents in the intake's `docs_language` (en-AU by default). Under the plugin the commands are `/job-harness:<skill>` (for example `/job-harness:job-onboard`); in a clone they are `/job-onboard` and so on.

## Before starting (always)
1. `job status $slug` — stage states, pending signatures, broken seals, open questions, next step. If the candidate does not exist: `job new $slug --name "..." --source-dir "..."`.
2. Read `candidates/$slug/progress.md`, `intake.json`, `CLAUDE.md`. Never rely on chat history.
3. `job learn list` — apply the lessons (they exist because something went wrong before).

## Stages
| Stage | Procedure | Output | Gate |
|---|---|---|---|
| 0 Intake | [references/stage-0-intake.md](references/stage-0-intake.md) | source docs read, facts extracted | — |
| 1 Profile and gaps | [references/stage-1-profile.md](references/stage-1-profile.md) | intake.json, answers.json, facts.json, questions | — |
| 2 Target tracks | [references/stage-2-targets.md](references/stage-2-targets.md) | targets.json | targets (you, OK in chat) |
| 3 Master documents | [references/stage-3-docs.md](references/stage-3-docs.md) | docs/*.json → docx/pdf, lint + facts ok | master-docs (you, OK in chat) |
| 4 Platform profiles | [references/stage-4-profiles.md](references/stage-4-profiles.md) | proposal → approved changes applied | profile-changes (you, OK in chat) |
| 5 Alerts | [references/stage-5-alerts.md](references/stage-5-alerts.md) | saved searches = targets.searches | — |

## When finishing a stage (always)
1. `job state $slug stage $stage --status done --summary "..."` (or `blocked` + `job ask $slug add "..." --blocks $stage`).
2. If the stage has a gate: `job gate request $slug --type <type> --files ... --description "..."`, show the user what they are approving in plain words (`job review $slug <id>` lists the files and the automatic checks), and ask for an explicit OK in the chat. After their OK, sign it yourself: `job sign $slug <id> --by-agent --note "User approved in chat: '<their words>'"`. Do not ask the person to type sign commands for these approvals. Only `go-live` needs the person's own signature (it is never part of onboarding), and only if the owner has not set `JOB_HUMAN_SIGN=""`. If a `--by-agent` signature is refused because the owner made a type human-only, tell the person to run `job sign $slug <id>` in a terminal, or `! job sign $slug <id> --confirm $slug` inside Claude Code.
3. Rewrite `candidates/$slug/progress.md` (done / pending / next step).
4. Any new lesson → `job learn log --kind ... --area ... --lesson "..."`.

## Rules for every stage
- Ask only what is missing; propose defaults the user can override. One short list of questions at a time.
- Never write a user-visible claim you cannot trace to a source document or to the user's words.
- Profile edits and alerts change the person's accounts: only after explicit approval in chat, one tab at a time.
- Never delete anything in the person's accounts; tell the user what to delete.
- Never sign an approval the person has not explicitly OK'd in the chat for that specific approval.
