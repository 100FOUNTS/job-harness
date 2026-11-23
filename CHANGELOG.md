# Changelog

All notable changes to job-harness. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/) while below 1.0: a new feature bumps the minor number, a fix bumps the patch number.

The plugin version (in `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` and `HARNESS_VERSION` in `scripts/common.py`) must go up for plugin installs to pick up a change. See [docs/RELEASING.md](docs/RELEASING.md).

## [Unreleased]

## [0.7.0] - 2026-11-23

### Added
- CV entries (`experience`, `entrepreneurship`, `projects`, `other_employment`) accept an optional `"type"` ("Part-time", "Full-time", "Casual", "Contract", "Fixed-term", "Volunteer"...). It is printed after the dates on the employer line: `Org, City  |  Mar 2022 - Jun 2024  |  Part-time`. Without `type` nothing changes, so a candidate who would rather not show employment types simply leaves it out. Résumé parsers (Affinda) read "(part-time)" written inside the job title as part of the title and got the employment type wrong, so the type now has its own place, in both the Word and the PDF.
- `job docs build` (and `job lint <slug> cv.json`) warns, without failing the build, when a `role` carries an employment type such as "(part-time)", "(casual)" or "- Contract", and when an education date uses a full month name. The tailor-writer agent and the stage 3 guide now say to put the type in `type`, never in the role.

### Changed
- CV dates use 3-letter months everywhere, in the Word and the PDF: "Expected December 2026" is printed "Expected Dec 2026" and "September 2020 - March 2021" "Sep 2020 - Mar 2021", so education matches the experience dates (a résumé checker penalised the mix). A bare year for a finished degree stays a bare year.

## [0.6.0] - 2026-11-18

### Added
- `job targets check <slug> [--days 30] [--json]`: a read-only linter for `targets.json`, using the same matchers as triage. Errors: a title phrase that an exclusion rejects (it can never let an ad in), duplicate track ids, missing CV or letter files, unknown ids in `priority` or `seek_cvs.json`. Warnings: a phrase an earlier track always takes, a title accepted but always penalised (`off_field`, missing credentials, `deprioritize`), a track with no saved SEEK resumé in easy/full mode. Info: phrases no ad title matched in the period. Exit code 1 on errors.
- `job nearmiss <slug> [--days 14] [--json]`: the ads the pre-filter rejected by a little: one or two years over `max_years_required`, titles that share part of a track phrase (grouped by the words not yet covered, with examples), the exclusion words doing the most work, and location-only rejects. The top lines go into Monday's daily report.
- `targets.json` `"priority": [track ids, highest first]` (and `priority_step`, default 5) sets each track's ranking weight (+10, +5, 0, −5, −10 for five tracks), in place of a `rank_adjust` per track. The order of `tracks` still decides which track takes an ad.
- `ranking.level_adjust` (`{"senior": -5, "lead": -15, "entry": 10}`) changes the seniority points for one person; 0 turns a level off.

### Fixed
- Title exclusions now match simple plurals: "manager" rejects "Project Managers" and "director" rejects "Directors" ("partner" still does not reject "Partnership", "head" not "Header"). `exclude_text` is unchanged.
- `easy_apply` was only set by LinkedIn cards: an ad applied for on SEEK's own form (`apply_route` = quick) now carries it in `jobs.db`, in re-judged ads and in the package, and a later sighting without the flag no longer clears it.

## [0.5.0] - 2026-11-17

### Fixed
- SEEK Quick Apply (`apply/apply_seek.js`): files were put into inputs by position, and SEEK now has a profile-photo input first, so the CV went to the photo and the letter became a resumé. Inputs are found by id (`#resume-fileFile`, `#coverLetter-fileFile`), never one that accepts images; anything unexpected stops the job as `manual-review` without guessing. The "Continue" button carries an invisible U+2060 and is now found. Each upload must show up in SEEK's list (older files share the name), and a screenshot of each step goes to `seek_steps/` in the job folder.
- Years-of-experience answers: a role that only shares one word with the person's profession ("Environmental Health Officer" for an Environmental Engineer) no longer claims the whole career. If the asked work appears in any of the person's CVs, the answer is at least 1 year (never 0, never sent to review); only work found in no CV is left for the person.

### Added
- Triage judges again the ads seen in the last 14 days that were rejected under older targets (`job triage <slug> --rejudge DAYS`, 0 = off): widening a track now reaches ads already in `jobs.db`, once. Hard requirements, twins and blocked employers stay rejected.
- Title phrases: the last word matches as a stem when it has 6+ letters ("cartograph" ~ Cartographer, "hydrolog" ~ Hydrologist) or ends in `*` ("hse*" ~ HSEQ, SHEQ...). Short words stay whole ("node" does not match "Nodes").
- Daily report and notification: when the scripted apply stops because the SEEK session is gone, it is the first line, with how many days in a row (`job apply <slug> login seek` fixes it). Results are kept in `data/<date>/apply.json`.
- `job apply` only tries ads applied for on SEEK's own form; ads whose route is the employer's site stay for the person instead of ending as `manual-review`.
- `job gate request` marks the previous pending request of the same type as superseded, so only one is left to sign.
- `candidates/<slug>/seek_cvs.json` (`{"<track>": "<file saved on SEEK>"}`): one resumé per area is saved once on SEEK; `job apply` selects the track's file and uploads only the tailored letter, so SEEK's default resumé never changes (an upload always becomes the default). A track missing from the file is left for the person.

### Changed
- Panel, Companies: the order is now a **Priority** (0 to 100) that mixes the average score of the company's qualifying ads (half), how many there are (a third, full marks from 5 ads) and the sponsor lists (a fifth; without sponsor data the first two share the weight). Before, the number of ads came first, so an employer with 22 weak ads beat one with 6 strong ones. The table shows Priority, Best, Average and Ads; hover the Priority for the breakdown. Sorts: By priority, Best score, Most ads, Sponsors only.

## [0.4.0] - 2026-11-16

### Added
- `job block <slug> add|remove|list`: employers to skip. Their ads are dropped in triage (`company excluded`, shown in the panel's dropped list) and flagged on pasted links. Names match after removing case, accents, punctuation and legal suffixes ("ACME Pty Ltd" = "Acme"), but only as a whole name ("Rio" does not block "Rio Tinto"). Stored in `blocklist.json`, so no re-signing of `targets`.
- `job gaps <slug> [--days 30] [--track <id>] [--json]`: the skills the relevant ads ask for, counted across all of them and split into **have it, not in the CV** (quick win, add only where it truthfully fits) and **gap** (a course, certificate or project). Near misses count; ads dropped for hard requirements do not. No AI. The daily report shows the top 3 of each on Mondays when there are 10 or more ads.
- `/job-inbox` and `job inbox <slug> query|check|apply|dismiss`: update application statuses from employer replies in Gmail. Claude reads the mailbox with read-only tools and proposes interview, offer, rejected or withdrawn with the email as evidence (date, sender, subject, a short quote); only what you approve is applied, and declined emails are not proposed again. Email text is untrusted data and goes through `guard`.

### Security
- `hooks/gate.py` blocks Gmail write tools (send, draft, label, archive, trash, spam): the harness only reads your mail.

## [0.3.1] - 2026-11-05

### Added
- Panel: a **Profile** tab (key P, `#perfil`) with the candidate's setup at a glance: a checklist of what is ready and what is missing, each missing item with the command that fixes it; the searches per track and the sources they need; the rules that apply (never mentioned, never included, only if a form asks); answers still empty; approvals and their state; setup steps, sending limits, and where the candidate's files and packages are. It reads `GET /api/profile` and never writes. `job profile <slug>` prints the same data as JSON.

## [0.3.0] - 2026-11-05

### Changed
- The agent rule lines that only repeated what Claude itself does not do (captchas, accounts, passwords) are gone from `CLAUDE.md`, `job-start`, `job-daily` and the form-filler. The README, the Spanish README and the landing page now say these steps are left to the person because of Claude's own limits, not a setting of this harness. The source guidelines (no proxies, no evasion) stay.
- The form-filler no longer decides from the job page which kind of form an employer has: it clicks Apply and looks at what loads.

### Added
- How each job is applied for. Triage now reads, with no extra request for SEEK and LinkedIn, whether a job is applied for on the portal itself (SEEK's own form, LinkedIn Easy Apply) or on the employer's site, and the company feeds (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) are known public forms. It is kept in `jobs.db` (`apply_route`, `apply_ats`; older databases get the columns on first use), shown as a tag on board cards and in the detail, and used by the package's "how to apply" line, which until now guessed.
- `job routes <slug> [--refresh]`: counts the board's open jobs by how they are applied for (portal form, public form, account per employer, employer's site, not known), and fills in the ones not known yet. `job routes <slug> --set <key> --url <page>` records where an Apply button really led, naming the system (Greenhouse, Workday...).
- Sources may define `route(job_id)` or `APPLY` (docs/ADDING-A-SOURCE.md).
- The Apply button is now actually clicked before a job is called fillable. The form-filler probes an employer's site (cookie banner declined, then what loads) and records the gate: `open` (a form with nothing in front, filled up to the review page), `login` (left to the person: no sign-in clicks, no passwords, no accounts), `captcha`, or `blocked` (Claude in Chrome not allowed on that site). `job routes <slug> --set <key> --url <page> --gate <gate>` records it with the employer's host, and `--known <url>` answers from an earlier probe so an employer is not probed twice.
- `job routes <slug> --queue`: ready to fill, still to probe, and the logins grouped by portal (one sign-in per portal, then the form-filler goes on for every ad there). `--hosts` lists the sites Claude in Chrome has to be allowed on before a run, because a site refused after the Apply click stops that job half way. Board cards show the gate ("Form ready", "Needs your login", "Captcha: yours", "Site not allowed").
- `job answer <slug> gaps`: the common form questions in `answers.json` that still have no answer. Each one stops a form that asks it; the onboarding now asks for them.
- The daily-run guide tells the agent to list the hosts to allow first, fill the ready jobs, probe the rest and end with the login queue.

## [0.2.3] - 2026-11-04

### Added
- Panel: a badge next to the company name on a board card when the company is on the visa sponsor lists. Green with a check: the same name, or the same name without Pty/Ltd/Group. Amber, dashed, with a question mark: a listed name starts the same, so it may be a look-alike. Hover, click or tap it for the explanation. A *Sponsor lists* filter button keeps only those companies. It is for your eyes only: nothing about it reaches a CV, letter or form.
- Landing page: a short title (46 characters) and description, and Open Graph / X card tags with a 1200x630 preview image, so a shared link looks right.

## [0.2.2] - 2026-11-04

### Added
- Each GitHub Release now attaches the three lite skill zips (tailor, interview prep, ad review), ready to upload to claude.ai without cloning the repository.


### Fixed
- Paste a link: a WA Government ad now shows its agency (for example "Pilbara Ports Authority") instead of "WA Government", read from the ad page's Department field.

## [0.2.1] - 2026-11-04

### Fixed
- Paste a link: WA Government Jobs links failed with an error since the sources refactor (`discover.wagov_page` moved to `sources.wagov.page`). Found by trying real ads, and now covered by a test.

## [0.2.0] - 2026-11-04

### Added
- Pluggable job sources: one module per portal in `scripts/sources/` behind a registry, with a guide for adding a portal or a country ([docs/ADDING-A-SOURCE.md](docs/ADDING-A-SOURCE.md)).
- Public company job feeds on Greenhouse, Lever, Ashby, Workable and SmartRecruiters, and an optional Adzuna source (free key, off until configured). `job doctor` lists the sources.
- Paste a link in the panel (or `job addlink <slug> <url>`): SEEK, LinkedIn, WA Government and any page with a JobPosting, or the pasted text. Scored, tailored and tracked like the rest.
- The panel on your phone: `job panel --lan`, with a fresh token on every request.
- *What leads to interviews* in the Funnel view: interview rates by score band, track and source after 10 answered applications.
- Red flags on each prepared ad (`job flags`): pay below your minimum or the minimum wage, unpaid or commission-only work, upfront fees and scam patterns, hidden employer, reposts. Warnings only.
- Follow-up drafts after 10 days without news (`job followup`), written by the daily run, never sent. The panel shows a *Follow up* badge and the draft.
- A lite pack for Cowork and claude.ai: standalone skills (tailor, interview prep, ad review). Build the zips with `python3 scripts/build_lite.py`.
- Contributing guide, code of conduct, security policy, issue and pull request templates, a release workflow and a landing page for GitHub Pages.

### Changed
- The README diagram is a Mermaid flowchart with the cross-platform scheduler and the new pieces.

### Fixed
- SEEK job details: `www.seek.com.au/graphql` now answers 308, which urllib does not follow on a POST, so ad descriptions and closing dates came back empty. It now calls `au.seek.com/graphql`.

## [0.1.1] - 2026-11-03

### Added
- Panel: drop a job from its card (key `X`), with an Undo; a *Dropped by you* list with Restore.
- Panel: *Top picks (all days)* and the best score on the *To apply* tile.

## [0.1.0] - 2026-11-03

First public release, installable as a Claude Code plugin (`/plugin marketplace add 100FOUNTS/job-harness`, then `/plugin install job-harness@100founts`).

### Added
- Plugin packaging: manifests, safety hooks that load with the plugin, a data folder outside the plugin (`~/job-harness-data` or `JOB_DATA_DIR`) so updates never touch it, and a `job-start` skill that carries the working rules.
- Panel v2: a local board with every application, why each ad fits or was dropped, today's package with a selector for earlier days, the English interface and a floating *Buy me a coffee* button.
- WA Government Jobs as a third source next to SEEK and LinkedIn.
- Visa sponsor lists (`job sponsors`), shown only to the person in the package and the panel, never in a CV, letter or form.
- A better job filter: tolerant title phrases ("web developer" also finds "Web/UI Developer"), generic titles read from the ad on a budget, a *Maybe worth a look* list, learning from rescued ads and per-track priority.
- Cross-platform runtime: macOS, Windows and Linux, one-command setup (`job setup`), a Poppler-free PDF reader, UTF-8 everywhere, and a scheduler for each system (LaunchAgent, Task Scheduler, systemd user timer or cron).
- Docs for non-technical users (getting started, glossary, troubleshooting), a Spanish quick guide, a sample package and the daily-run architecture diagram.
- Continuous integration on macOS, Windows and Linux.

### Changed
- Panel: PDF text is cached on disk, so a large board loads in under a second.
- A different specialisation after " - " in a title is treated as a different role when removing duplicates.

### Fixed
- The sign-in hint under the plugin reads `! job sign ...` (the `bin/job` path only exists in a clone).

## Before 0.1.0
Initial public commit: discovery from SEEK and LinkedIn, triage, ranking, sealed approvals, the document builders and linters, and the optional SEEK Quick Apply mode.
