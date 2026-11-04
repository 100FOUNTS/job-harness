# Changelog

All notable changes to job-harness. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/) while below 1.0: a new feature bumps the minor number, a fix bumps the patch number.

The plugin version (in `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` and `HARNESS_VERSION` in `scripts/common.py`) must go up for plugin installs to pick up a change. See [docs/RELEASING.md](docs/RELEASING.md).

## [Unreleased]

<!-- The maintainer finalises these bullets when the version is cut. -->

### Added
- Pluggable job sources: a registry of sources behind `job discover`, ATS feeds (Greenhouse, Lever, Workable, SmartRecruiters, Ashby) and an optional Adzuna source (free key, off by default).
- Paste a link in the panel: add a job you found yourself and get it ranked, tailored and tracked like the rest.
- The panel on your phone: `job panel --lan` serves it on your home network.
- Calibration view in the panel: how the score compares with what actually happened to your applications.
- Red flags on each ad (pay, hours, wording that is worth a second look), shown on the card and in the package.
- Follow-up drafts for applications that went quiet.
- A lite pack for Cowork and claude.ai: standalone skills (tailor, interview prep, ad review) that need no Claude Code, hooks or Python. Build the zips with `python3 scripts/build_lite.py`.
- Contributing guide, code of conduct, security policy, issue and pull request templates, a release process and a landing page (GitHub Pages).

### Changed
- The daily-run diagram shows the scheduler as launchd, Task Scheduler or systemd/cron, and the new pieces (sources, paste a link, red flags, follow-ups).

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

[Unreleased]: https://github.com/100FOUNTS/job-harness/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/100FOUNTS/job-harness/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/100FOUNTS/job-harness/releases/tag/v0.1.0
