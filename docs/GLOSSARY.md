# Glossary

Words used in this project, in plain language.

**Approval** (also *gate*). A record that you checked something and agree. There are five kinds: `targets`, `master-docs`, `profile-changes`, `report` and `go-live`. Claude signs the first four after you say OK in the chat; only you sign `go-live`. See *Seal* and *Sign*.

**Candidate.** One job seeker and everything about them, kept in one folder, `candidates/<slug>/`. One install can hold several candidates (yourself, a partner, a friend). The only candidate shipped with the code is the fictional `example`.

**Data folder.** Where your private files live. In a clone of the repository it is the repository folder itself (`candidates/` inside it). Installed as a plugin it is `~/job-harness-data` (or the folder in `JOB_DATA_DIR`), outside the plugin code, so updating the plugin never touches it. `python3 scripts/common.py where` prints it.

**Facts** (`facts.json`). The list of numbers and claims a CV or letter may use, each with its source ("managed 12 staff", "reduced costs by 8%"). `job facts verify` rejects any figure that is not in the list, so nothing can be invented.

**Go-live.** The approval that allows the harness to *submit* applications for you (only in the optional modes `easy`, `full` and `live`). Without it nothing is ever submitted. Only you can sign it, unless the owner changed that setting.

**Hook.** A small safety program that Claude Code runs before every action Claude takes. The harness's hook (`hooks/gate.py`) blocks dangerous actions (for example signing as you, deleting your data, or clicking submit without a valid go-live) and asks you first before Claude changes the harness's own rules.

**Intake.** The first stage of onboarding, and the file `intake.json` it fills: who you are, your contact details, your rules (for example "never mention visa"), your preferences, and the sensitive answers (work rights and the like) that are used **only** when an application form asks.

**Manual review** (`manual-review`). The status of a job the harness could not finish safely, for example a form question it has no approved answer for, or an application that needs an account. It is left to you, with the reason written down. The harness never guesses.

**Master documents.** Your approved base CV (one per track) and your cover letter template, in `candidates/<slug>/docs/`. Every daily CV and letter starts from them. Changing a master document after you approved it breaks its seal.

**Modes.** How far the daily run goes. `prepare`: scripts find and rank jobs and build your package; you apply. `easy`: also submits SEEK Quick Apply applications with a script. `full`: easy plus simple company forms. `dry-run` and `live`: the older agent-driven cycle where Claude fills forms in Chrome and stops before the last click (`dry-run`) or clicks submit (`live`). Anything that submits needs a valid go-live.

**Package** (daily package). The folder for one day: `~/job-packages/<slug>/<date>/`, with `SUMMARY.md`, `index.html` and one subfolder per job holding the tailored CV and cover letter (PDF and docx) and a short summary of the job.

**Panel.** The local board you open with `job panel`: every application across days, why each ad fits or was dropped, and buttons to record what happened. It runs on your computer only (`127.0.0.1`).

**Plugin.** A bundle (skills, agents, hooks) that you install into Claude Code from a marketplace. Installed this way the commands are `/job-harness:<name>`. The alternative is a *clone*: downloading the repository and working inside it.

**Quota** (limits). The maximum number of applications per platform, per day and per week. `job track <slug> quota` shows what is left; the tracker refuses to record more.

**Seal.** The fingerprint (sha256) of the files an approval covers. If one of those files changes after you approved it, the seal breaks: the approval stops counting, and submissions stop until you sign again.

**Sign.** To make an approval official. Claude signs the ordinary approvals with `job sign ... --by-agent` after your OK in the chat, and writes your words in the note. You sign `go-live` yourself with `job sign <slug> <id>`, or inside Claude Code with `! job sign <slug> <id> --confirm <slug>`.

**Slug.** The short name of a candidate used in commands and folder names: lowercase letters, no spaces or accents (for example `ana`).

**Track.** A family of roles you apply to, with its own CV, title keywords and searches. Someone might have a main track (their profession) and an entry-level track in a nearby field. Defined in `targets.json`.
