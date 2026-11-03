# Getting started (no terminal needed)

This guide takes you from nothing to your first daily package using only the **Claude desktop app**. You never have to type a command yourself: you type short requests to Claude, and Claude runs the commands.

Steps marked **(not confirmed)** are things the official Claude documentation does not spell out. If one does not work the way it is written here, the note under it says what to do instead.

## What you need
- A computer with macOS, Windows or Linux. (Windows and Linux support is new: it passes automated tests but has had little real-world use. See [TROUBLESHOOTING](TROUBLESHOOTING.md).)
- A paid Claude subscription (Pro, Max, Ultra, Team or Enterprise). Claude Code is part of it.
- A folder with your CVs, certificates and other career documents.
- Python 3.9+ and Node.js 20+. If they are missing, Claude tells you in step 7 and shows the install command for your system. The desktop app itself does not need Node.js, but the harness does.

## 1. Install the Claude desktop app and sign in
Download the app from the [official quickstart](https://code.claude.com/docs/en/desktop-quickstart) (macOS, Windows; Linux is in beta), run the installer, open **Claude** and sign in with your Anthropic account.

## 2. Open the Code tab
Click **Code** at the top of the sidebar. If it asks you to upgrade, you need a paid plan. If it asks you to sign in online, finish the sign-in and restart the app.

## 3. Make a folder for your data
In your home folder, create a new empty folder called exactly **`job-harness-data`**. (On macOS: Finder, your home folder, File, New Folder. On Windows: File Explorer, your user folder, New folder.)

This is where your private data will live: your intake, facts, approvals and logs. It is separate from the harness code, so updating the harness never touches it. The safety rules (hooks) only run when Claude is opened in this folder, which is why we start here.

## 4. Choose that folder in the Code tab
Under the prompt box, click the first control (the environment selector) and choose the top entry in the **Local** group. Then click the folder control next to it, choose **Open folder...**, and pick `job-harness-data`.

## 5. Add the harness and install the plugin
In the prompt box, type:
```
/plugin marketplace add 100FOUNTS/job-harness
```
then:
```
/plugin install job-harness@100founts
```
Choose the install scope **Install for you (user scope)** if it asks.

**(not confirmed)** The documentation says plugins are installed in the desktop app from **+ next to the prompt box, then Add plugins**, but it does not say that the `/plugin` commands above work in the Code tab. If Claude answers that `/plugin` is not available:
1. Open a terminal once (the desktop app has one: press **Ctrl+`**), or any terminal on your computer.
2. Run `claude plugin marketplace add 100FOUNTS/job-harness` and `claude plugin install job-harness@100founts`. This needs the Claude Code command-line tool, which you can install from the [CLI quickstart](https://code.claude.com/docs/en/quickstart).
3. Back in the desktop app, click **+**, then **Add plugins**, and check that **job-harness** is listed. The terminal and the desktop app share the same plugin settings.

Plugins are not available in WSL sessions on Windows; use a normal Local session.

## 6. Start
Type:
```
/job-harness:job-start
```
(Typing `/` shows a list of commands; pick the one that starts with `job-harness:`.) The plugin's skills always begin with `/job-harness:`.

## 7. What Claude will do and ask
1. **Check your machine.** Claude runs `job setup`. It checks Python and Node.js, installs the document tools (a minute or two) and creates the folder for the daily packages (`job-packages` in your home folder by default). If Python or Node.js is missing, it shows you the install command for your system; install it, open a new session and say "continue".
2. **Explain** in a few lines what the harness does and does not do.
3. **Ask your first name** and where your CVs and certificates are. Pick the folder when asked (or paste its path).
4. **Onboarding, one stage at a time** (Claude says which stage it is on):
   - Stage 0: reads your documents.
   - Stage 1: asks the questions only you can answer (the roles you want, locations, licences, referees, which figures you can explain in an interview).
   - Stage 2: proposes your target job tracks and searches.
   - Stage 3: writes your master CV and cover letter.
   - Stages 4 and 5: review your SEEK and LinkedIn profiles and set up job alerts. These two need the **Claude in Chrome** extension; Claude tells you how to connect it. You can skip them for now.

You can stop at any time. Next time, open the same folder and say "continue my job search"; `job status` tells Claude exactly where you were.

## 8. How to approve things
At some points Claude shows you what it wants to settle (your target tracks, your master documents, profile edits). It explains it in plain words and asks for your OK.

- **Say OK in the chat** (for example "OK, the master documents look right"). Claude then signs the approval itself and records your words. You do not type any command.
- Claude never signs on its own initiative.
- One approval is different: **go-live**, which would allow the harness to *submit* applications. Only you sign it. You do not need it for the normal flow, where you click Apply yourself. If you ever want it, Claude shows you what you are signing and tells you what to type. **(not confirmed)** The command is typed inside the Code tab with a leading `!` (`! job sign <name> <id> --confirm <name>`); the documentation I checked describes `!` for the terminal version of Claude Code and does not say it works in the desktop Code tab. If it does not, run `job sign <name> <id>` in a normal terminal and type your name when asked.

If Claude asks permission to run a command or edit a file (a permission prompt), that is Claude Code's normal safety check, not the harness. Reading files and running `job ...` commands are expected. See [TROUBLESHOOTING](TROUBLESHOOTING.md) for which to approve.

## 9. Turn on the daily run
When onboarding is done, say:

> Install the daily schedule for me at 9am.

Claude runs `job schedule install <name> --hour 9`. After that your computer prepares your package every day at that time by itself, without using Claude and without costing anything. It runs only when the computer is on (a run missed while it was asleep happens when it wakes, on macOS and Linux with systemd). Say "run it now" to test one run immediately.

Alternative: a scheduled task in the desktop app (**Scheduled** in the Code tab sidebar, then **New task**). That one only runs while the app is open and the computer is awake, and each run uses Claude. The first option is simpler.

## 10. See your results
- **The panel.** Say "open my job panel". Claude runs `job panel`, which serves a page on your own computer, normally at `http://127.0.0.1:8765`. Open that address in your browser. You see every job, why it fits or was dropped, and buttons to mark "applied", "interview" and so on. It is reachable only from your computer. **(not confirmed)** that Claude can keep the panel running in the background in the desktop app; if the address stops working, ask Claude to start it again.
- **The package folder.** Each day: `job-packages/<name>/<date>/` in your home folder. Open `index.html` for the list of jobs with links, or `SUMMARY.md`. Each job has its own folder with the CV and cover letter as PDFs.

## 11. Apply
For each job you like: open the link, click Apply, upload the two PDFs from that job's folder, and mark it in the panel. The harness never submits for you unless you sign go-live.

## What to say to Claude next
- "Tailor today's best jobs" (it rewrites the CV and letter of the top three, with a separate reviewer)
- "I have an interview with [company]" (an interview preparation pack and a mock interview)
- "Why was this job dropped?"
- "Stop the daily run" (Claude creates the STOP file; see [TROUBLESHOOTING](TROUBLESHOOTING.md))

Unknown word? See the [glossary](GLOSSARY.md).
