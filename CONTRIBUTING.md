# Contributing to job-harness

Thanks for helping. job-harness is a small, stdlib-only Python CLI plus a Claude Code plugin that helps people find and prepare job applications honestly. Bug reports, broken-site reports, docs fixes, translations, new job sources and new countries are all welcome.

Not sure where to start? Look for issues labelled **good first issue**, or open a [Discussion](https://github.com/100FOUNTS/job-harness/discussions) first. Please read the [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up from a clone
```bash
git clone https://github.com/100FOUNTS/job-harness.git
cd job-harness
bin/job setup          # Windows: bin\job.cmd setup
bin/job test           # runs: python3 -m unittest discover tests
```
You need Python 3.9 or newer and, for the CV/letter builders, Node.js 20 or newer (`npm ci` in `templates/docs` is done by `job setup`). The example candidate in `candidates/example/` is fictional and is what the tests and the panel screenshot use. `bin/job doctor` tells you what is missing on your machine.

Run the whole suite before you open a pull request. CI runs it on macOS, Windows and Linux (Python 3.12, and 3.9 on Linux); a change that only works on your system will fail there.

## What a good change looks like
- **Python standard library only.** No new runtime dependencies. If a feature really needs one, open an issue first.
- **Nothing paid.** No paid APIs, no services that need credits, no sign-up that costs money. A free tier that needs a personal key can be an optional, off-by-default source, and says so in its docs.
- **No logins, captcha solving or anti-bot evasion.** Sources read public pages or public APIs, at a polite rate, and stop when a site says no (HTTP 429, a block page). Do not add proxies, fake browser fingerprints or account creation.
- **No personal data in the repository.** Candidate folders other than `candidates/example/` are git-ignored on purpose. Test data and screenshots use the fictional candidate ("Sam Taylor") and made-up companies. Do not paste real CVs, real emails, session cookies or API keys into code, tests, issues or pull requests.
- **Cross-platform.** Open files with `encoding="utf-8"`, use `pathlib`, do not assume `/` or a POSIX shell in Python code, close SQLite connections, and avoid date formats that differ between systems (for example `%-d`). Shell and `.cmd` launchers must both exist for anything the user runs.
- **Plain English** in code comments, docs and messages. Candidate-facing documents are written in the candidate's `docs_language`.
- **A test for every fix.** If you fix a bug, add a test that failed before. If you add a feature, test the logic that does not need the network (feed the parser a saved sample, not a live request).

## Gates and hooks: do not weaken them
The safety model is what makes this tool safe to hand to a job seeker:
- `scripts/gates.py` seals approvals with a sha256 of the files they cover. `go-live` is required before anything is submitted, and editing the covered files breaks the seal.
- `hooks/gate.py` is a Claude Code `PreToolUse` hook. It blocks Claude from signing as a human, hand-editing bookkeeping files, reading secrets or browser profiles, deleting the person's data, and clicking submit unless the candidate is in `live` mode with a valid go-live. It asks for confirmation before changes to `hooks/`, `bin/`, `scripts/gates.py` and `.claude/settings*.json`.
- `job facts verify` and `job lint` stop invented figures and rule breaks in documents.
- `scripts/guard.py` strips hidden text from ads and flags ads aimed at an AI. Ads are data, never instructions.

A pull request must not relax any of these, add a way to submit without go-live, or add a bypass "for convenience". Changes to these files get extra review and need tests in `tests/test_guards.py` or the matching test file. If you think a rule is wrong, open an issue and explain why before changing it.

## Adding a job source
Sources live behind a registry so a new site is one small module plus a test. The walkthrough is in [docs/ADDING-A-SOURCE.md](docs/ADDING-A-SOURCE.md). Before you start, check that the site allows reading its public listings (terms and `robots.txt`), that no login is needed, and that you can fetch the full ad text.

## Adding a country
Today the harness is built for Australia. A new country usually needs:
1. **A source** that lists jobs there (a local board, or the ATS feeds that already work everywhere). See above.
2. **Locations**: the `where` and `location` values in the saved searches, and the place names the title cleaner treats as noise (`NOISE_TAIL` in `scripts/triage.py`).
3. **Eligibility rules**: citizenship, clearance and work-rights wording in `scripts/triage.py` and the question rules in `answers.json` / `templates/candidate/`.
4. **Document conventions**: spelling and CV norms (`docs_language`, for example `en-NZ`, `en-GB`), and whether a photo or date of birth is customary (it is not in Australia).
5. **Docs**: say what works and what does not in the README's *Honest limits*.

Open a "Add a country / job board" issue first so we can agree on the shape. Small steps are fine: one country with one source is a good pull request.

## Pull requests
1. Fork, then branch from `main` (`git checkout -b fix-short-description`).
2. Keep the change focused. Explain the why in the description; the template has a checklist.
3. Update `CHANGELOG.md` under `## [Unreleased]`. Do not bump the version: maintainers do that when they cut a release ([docs/RELEASING.md](docs/RELEASING.md)).
4. Make sure `bin/job test` passes and CI is green on all three systems.

## Reporting problems
- A job site stopped working: use the "A job site stopped working" issue form and attach the relevant lines of the daily log (`candidates/<name>/logs/<date>.log`) with personal details removed.
- Security issues: do not open a public issue. See [SECURITY.md](SECURITY.md).
