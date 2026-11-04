## What and why
<!-- What changes, and what problem it solves. Link the issue if there is one. -->

## How I tested it
<!-- `bin/job test`, plus anything you ran by hand. -->

## Checklist
- [ ] `bin/job test` passes (CI also runs macOS, Windows and Linux)
- [ ] Python standard library only; nothing paid; no logins, captcha solving or anti-bot evasion
- [ ] No personal data (real CVs, emails, cookies, API keys) in code, tests, screenshots or this description
- [ ] Files are opened with `encoding="utf-8"`; paths use `pathlib`; works on Windows
- [ ] Gates and hooks are not weakened (`hooks/gate.py`, `scripts/gates.py`, `scripts/guard.py`, `job lint`, `job facts verify`), or this PR explains why and adds tests
- [ ] `CHANGELOG.md` has a line under `[Unreleased]` (no version bump)
- [ ] Docs updated if behaviour changed (README, `docs/`, and `docs/es/` if it affects the Spanish guide)
