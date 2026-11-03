# Troubleshooting

Start here, whatever the problem:

```
job doctor
```
It lists what your machine can run (Required and Optional) and prints the exact command to fix what is missing. `job setup --check` does the same and also checks that `job` is on your PATH. If you work through Claude, just say "run job doctor and tell me what is wrong". (Installed as a plugin, `job` is available in Claude's shell; in a plain terminal use the full path to `bin/job`, or `bin\job.cmd` on Windows.)

## "0 jobs found" or fewer than expected
- **The sites change.** SEEK, LinkedIn and WA Government Jobs sometimes change their pages or answer with an error. Look at today's log (`candidates/<name>/logs/<date>.log`): lines with `HTTP 429` mean the site is rate-limiting you; a different error code or a message from a search means the site may have changed. Try again the next day. If it keeps failing for days, report it (the maintainers need to update the harness).
- **LinkedIn rate limits.** LinkedIn's public pages answer HTTP 429 after many requests. One discovery run per day is fine. Do not run `job discover` many times in a row; jobs whose text could not be read are retried the next day.
- **Your targets are too narrow.** Run `job discover <name> --dry` (it writes nothing) and `job triage <name>`, then look at why ads were dropped (the panel's "dropped" view shows the rule for each). A keyword with zero results, or a strict filter such as a long list of excluded words, empties the list. Loosen the search keywords or the filters in `targets.json` (ask Claude to do it; changing targets needs your OK again).
- **Everything was already seen.** The harness lists an ad only once. `job db <name> stats` shows how many ads it has recorded.
- **No network.** `job doctor` shows "Network to SEEK".

## The daily schedule did not run
1. **Was the computer on?** A local schedule cannot run when the computer is off. macOS (LaunchAgent) and Linux (systemd timer with `Persistent=true`) run a missed job when the computer wakes up; on Windows check Task Scheduler's own history. A scheduled task in the Claude desktop app only runs while the app is open and the computer is awake, and skips a run if the computer sleeps through it.
2. **Is it installed?** `job schedule status <name>` prints `loaded` or `not loaded`. If not loaded: `job schedule install <name> --hour 9`.
3. **What happened?** Read `candidates/<name>/logs/<date>.log` (one file per day). It shows each step (discover, triage, prepare, apply, cleanup, report) and the reason for any failure. On macOS there are also `launchd.out` and `launchd.err` in the same folder. Typical lines: `STOP file present, exiting` (see below) and `another run is active, exiting` (a run was still going; a lock older than 6 hours is treated as a crashed run and taken over).
4. **Installed as a plugin and updated or removed it?** The schedule starts a small launcher in your data folder that finds the current plugin folder. If it cannot, it writes `launcher.log` in the data folder; open Claude Code and run `job setup`, then `job schedule install <name> --hour 9` again.
5. **Test it now:** `job schedule run-now <name>` runs once immediately and tells you where the package will appear.
6. **macOS only:** if your data or package folder is inside Documents, Desktop or iCloud Drive, macOS may block background jobs from reading it. Either move the package folder (set `JOB_PACKAGE_DIR` to something like `~/job-packages`) or allow access in System Settings, Privacy & Security, Files and Folders (or Full Disk Access).

## How to stop everything
Create an empty file called `STOP` in the candidate's folder: `candidates/<name>/STOP` (inside your data folder if you use the plugin). The next daily run logs "STOP file present, exiting" and does nothing. Delete the file to resume. You can ask Claude to create it, or:
- macOS and Linux: `touch candidates/<name>/STOP`
- Windows: `type nul > candidates\<name>\STOP`

To remove the schedule completely: `job schedule uninstall <name>`. To leave the submitting modes: `job state <name> mode prepare`.

## PDF, document or Node.js errors
Messages such as "Can't read PDFs", "Cannot find module 'docx'", "pdfkit" or "node: command not found" mean Node.js or the document tools are missing or incomplete. Run:
```
job setup
```
It checks Python (3.9+) and Node.js (20+), runs `npm install` for the document tools and PDF reader, and is safe to run again. If Node.js itself is missing it prints the install command for your system (for example `winget install OpenJS.NodeJS.LTS` on Windows); install it, open a new terminal or session, and run `job setup` again. `npm install` needs an internet connection.

If a CV or letter fails its checks (`ok: false`), the message names the problem: usually a figure that is not in `facts.json` or a rule from your intake. The fix is in the documents or the facts, not in the tools.

## Permission prompts in Claude Code
Claude Code asks before it edits files or runs commands. That is Claude Code's normal behaviour, separate from the harness's own safety hook. For this harness:
- **Safe to approve** (and to "always allow"): `job ...` commands, reading and writing files inside your candidate folder, and the Claude in Chrome tools when you started a profile or alerts stage.
- **Read the message first** if the prompt says "This changes the harness's own rules". That is the harness asking before changes to `hooks/`, `bin/`, `scripts/gates.py` or `.claude/settings*.json`. Approve only if you asked Claude to make that change. A job ad can contain text aimed at an AI; this prompt is what stops it from changing the rules quietly.
- **You will never be asked to approve**: signing `go-live` for you, deleting your data, or reading passwords. The harness blocks those outright.
- The daily schedule cannot show prompts (nobody is there), so the default run uses only scripts that need none.

## Messages from the harness hook
Messages that start with `[job-harness gate]` come from the safety hook. The common ones:
- "Human signatures are given by the person ...": Claude tried to sign `go-live`, or a signature that is yours to give. Only you can sign it; see the README's section on approvals. The message shows the command.
- "... is bookkeeping: change it through `job state|facts|track|gate`, never by hand": a file such as `state.json` or `tracker.json` must only change through `job` commands. Ask Claude to use the command.
- "The harness never deletes candidate data": deleting is left to you.
- "Dry-run: do not submit ...": expected in the default setup. You apply yourself.
- The safety hooks only run when Claude Code is opened in the harness folder (a clone) or in your data folder (a plugin install, default `~/job-harness-data`). If `job status` is not shown when the session starts, you opened a different folder.

## Windows notes
- Run the harness with `bin\job.cmd`, for example `bin\job.cmd setup`. It uses the first Python 3 it finds (`py -3`, then `python`, then `python3`). To type just `job` anywhere, add the `bin` folder to PATH (Start menu, "Edit the system environment variables", Path, New). Installed as a plugin, `job` is already available inside Claude's shell.
- Install Python from python.org or with `winget install Python.Python.3.12`. The "python" shortcut that opens the Microsoft Store is not Python; the launcher skips it.
- Windows and Linux support is new: the test suite runs there in CI, but it has had little use on real PCs. Please report what breaks, with the output of `job doctor`.
- The safety hooks are started through `sh` (`hooks/py.sh`). If Claude Code reports that a hook failed to start on Windows, install [Git for Windows](https://git-scm.com/download/win) (it provides `sh`) and reopen Claude Code. This is not something we could test on a real PC.
- Plugins do not load in WSL sessions of the desktop app; use a Local session.
- The daily schedule uses Windows Task Scheduler (`job schedule status <name>` queries it). Task Scheduler does not wake a sleeping computer by default.

## Linux notes
`job schedule install` uses a systemd user timer. If systemd is not available it prints a crontab line for you to add with `crontab -e`. Desktop notifications use `notify-send` if it is installed; without it the run still works, just silently.

## Still stuck
Run `job doctor --json` and `job status <name>`, and open an issue at https://github.com/100FOUNTS/job-harness/issues with that output (it never contains secrets or your documents; check before you paste).
