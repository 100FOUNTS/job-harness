# Lite pack for Cowork and claude.ai

For people who will not install Claude Code. These are three standalone **skills**: plain instructions that Claude follows in a normal chat. They need no terminal, no Python, no hooks and no folders.

| Skill | What it does |
|---|---|
| `job-review-lite` | Paste an ad (and your CV): fit, gaps, chance of a shortlist and red flags in the ad |
| `job-tailor-lite` | Paste an ad and your CV: a tailored CV and a cover letter, honest, ATS-friendly, Australian conventions |
| `job-interview-lite` | Paste an ad and your CV: likely questions, STAR answers from your real history, questions to ask, and a mock interview |

## What you do not get
The lite pack is the writing and judgment part of job-harness. It has none of the machinery:
- no daily search of SEEK, LinkedIn or WA Government Jobs, no ranking, no panel and no daily package;
- no automatic check of your figures (`job facts verify`) or of CV rules (`job lint`): the skills tell Claude to use only what is in your CV, but nothing checks it for you, so read the result before you send it;
- no sealed approvals and no applying: you always send the application yourself.

For the full tool, see the [README](../README.md).

## Get the zips
From a clone of this repository:
```bash
python3 scripts/build_lite.py
```
This writes `dist/lite/job-review-lite.zip`, `job-tailor-lite.zip` and `job-interview-lite.zip`. Each zip contains the skill folder (`job-tailor-lite/SKILL.md`), which is the shape the upload expects. You can also zip a folder from `lite/` yourself, as long as the folder name equals the `name` in its `SKILL.md`.

## Upload to claude.ai
1. Open claude.ai and go to **Customize**, then **Skills** (in some versions: **Settings**, then **Capabilities** or **Features**).
2. Click **+**, then **Create skill**, then **Upload a skill**, and choose one zip.
3. Repeat for each skill, and make sure each is switched on.

Requirements, from Anthropic's help pages: skills are available on Free, Pro, Max, Ultra, Team and Enterprise plans, and **code execution and file creation must be turned on** (individual plans: Settings, Capabilities; on Team and Enterprise an owner turns it on, and an owner may also turn off user-created skills). Custom skills belong to your own account only.

## Use them in Cowork
Skills you add in claude.ai are available in Cowork on the same account; Anthropic's help pages say skill sharing works in both chat and Cowork. If a skill does not show up in Cowork, check that it is switched on in the Skills list and start a new session.

## Using them
Start a chat and paste what the skill needs, for example:

> Review this job ad against my CV. [paste the ad] [paste or attach your CV]

or "Tailor my CV and write a cover letter for this ad", or "Prepare me for an interview for this job". Claude picks the skill from your request. If it does not, name it: "use job-tailor-lite".

Tips:
- Paste the ad as text. Claude may not be able to open a link.
- Remove anything you do not want a chat to see. What you paste is processed by Claude under your own plan.
- Ask Claude to list every number it used and where it came from in your CV.
- Skills do not sync across surfaces: uploading to claude.ai does not add them to Claude Code or the API.

## Changing a skill
Edit the `SKILL.md` in this folder (keep the `name` equal to the folder name; the `description` is what Claude uses to decide when to use the skill, so say what it does and when), run `python3 scripts/build_lite.py`, and upload the new zip. `python3 -m unittest tests.test_lite` checks the rules: `name` in lowercase letters, digits and hyphens (64 characters at most, no "claude" or "anthropic"), `description` not empty, 1,024 characters at most, no XML tags.

## For Claude Code users
The full skills (`/job-tailor`, `/job-interview`) live in `.claude/skills/` and use the harness's checks. The lite versions are separate on purpose.
