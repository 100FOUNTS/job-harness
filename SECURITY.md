# Security policy

## Reporting a vulnerability
Please report security problems privately, not in a public issue or discussion:

1. Go to the [Security tab](https://github.com/100FOUNTS/job-harness/security) of the repository.
2. Choose **Report a vulnerability** (GitHub Security Advisories).
3. Describe what you found, how to reproduce it, and what it could let someone do. Do not include real personal data; use the fictional example candidate.

We will acknowledge the report, work on a fix in a private advisory and credit you in the release notes if you want that.

## What counts
job-harness runs on a person's own computer and handles CVs, contact details and sometimes a browser session. Reports we especially want:
- A way to make the harness **submit an application** without a valid, signed `go-live` approval.
- A way to bypass `hooks/gate.py` or `scripts/gates.py` (signing as a human, editing sealed files without breaking the seal, reading secrets or browser profiles, deleting a person's data).
- **Prompt injection** from a job ad that gets past `scripts/guard.py` and changes what Claude does.
- The panel (`job panel`, including `--lan` if present) exposing data to other computers or sites, or accepting requests from a web page the person visits (cross-site request forgery, DNS rebinding).
- Secrets, cookies or personal data written to a file that is committed or shared.
- Path traversal or command injection in any `job` command.

Not in scope: a job site changing its pages, rate limits (HTTP 429), or the gate hook missing deliberately obfuscated commands (it is pattern-based and says so). Open a normal issue for those.

## Supported versions
Only the latest release receives fixes. Update with `claude plugin update job-harness@100founts` or `git pull`.
