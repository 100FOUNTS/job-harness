# Suggested GitHub labels

The issue forms apply some of these automatically, so create them under Issues, Labels. Colours are suggestions.

| Label | Colour | Use |
|---|---|---|
| `bug` | `d73a4a` | Something does not work as described |
| `broken-site` | `e99695` | A job site changed and a source stopped working |
| `enhancement` | `a2eeef` | An improvement to something that exists |
| `new-source` | `0e8a16` | A new job board, feed or ATS |
| `new-country` | `0e8a16` | Support for another country |
| `good first issue` | `7057ff` | Small, well-described, no deep knowledge of the safety model needed |
| `help wanted` | `008672` | Maintainers would welcome a contribution |
| `docs` | `0075ca` | README, guides, comments |
| `translation` | `1d76db` | Spanish guide or another language |
| `windows` | `5319e7` | Windows-specific |
| `linux` | `5319e7` | Linux-specific |
| `macos` | `5319e7` | macOS-specific |
| `panel` | `fbca04` | The local board (`job panel`) |
| `safety` | `b60205` | Gates, hooks, approvals, guard. Needs extra review |
| `plugin` | `c5def5` | Plugin manifests, install and update |
| `lite` | `bfdadc` | The Cowork / claude.ai lite pack |
| `question` | `d876e3` | Usually moved to Discussions |
| `wontfix` | `ffffff` | Out of scope (paid services, anti-bot evasion, submitting without go-live) |

## Five good first issues
Each is small, touches one area and has an obvious test. Copy them into issues labelled `good first issue`.

1. **Add more Australian places to the title cleaner.** `NOISE_TAIL` in `scripts/triage.py` only strips "Perth", "WA", "Adelaide" and "SA" from the end of a title, so "Data Analyst - Melbourne" and "Data Analyst - Sydney" are treated as different roles from "Data Analyst". Add the other capitals and states (Sydney, Melbourne, Brisbane, Canberra, Hobart, Darwin, NSW, VIC, QLD, ACT, TAS, NT) and a test in `tests/test_filter.py`.
2. **Make the SEEK country configurable.** `scripts/discover.py` hard-codes `siteKey` `AU-Main`, the `seek-request-country` header and the `seek.com.au` host. Read them from the search entry, defaulting to Australia, so a New Zealand search (`NZ-Main`, `seek.co.nz`) can be tried. Test that the default request is unchanged.
3. **Translate a guide to Spanish.** `docs/es/` has only a short README. Translate `docs/TROUBLESHOOTING.md` or `docs/GLOSSARY.md` into `docs/es/` and link it from `docs/es/README.md`. Keep command names and file names unchanged.
4. **Report how it runs on your Windows or Linux PC.** Windows and Linux support passes CI but has little daily use. Follow `docs/GETTING-STARTED.md` on a real machine with the example candidate, then open an issue with `job doctor` output, what worked and what did not. A fix for anything you find is a bonus.
5. **Add more company-suffix words to the sponsor matcher.** `GENERIC` in `scripts/sponsors.py` lists words set aside when matching an ad's short company name to a legal name (Pty, Ltd, Group, Australia). Add common others (for example "Services", "Operations", "Enterprises", "Solutions") only where a test shows a real match is missed, and add a test in the sponsors tests that a different company is still not matched.
