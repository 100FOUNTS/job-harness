# Changelog

All notable changes to job-harness. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/) while below 1.0: a new feature bumps the minor number, a fix bumps the patch number.

The plugin version (in `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` and `HARNESS_VERSION` in `scripts/common.py`) must go up for plugin installs to pick up a change. See [docs/RELEASING.md](docs/RELEASING.md).

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
