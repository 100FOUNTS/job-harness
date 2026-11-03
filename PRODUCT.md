# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
The operator of a job-harness install: one person who runs the harness for one or more job-seeking candidates (themselves, a partner, a friend). Developers and non-technical people alike open the panel; the non-technical case sets the bar for clarity. They use it in two moments, equally: a daily pass after the scheduled run (what is new, what closes soon, open the ad, apply, mark it) and a periodic review (follow-ups due, what happened to past applications, whether the ranking is working).

## Product Purpose
job-harness takes a candidate from "here is my folder" to daily, rule-abiding job applications in Australia. Scripts discover and pre-filter ads from SEEK, LinkedIn and WA Government Jobs, rank them, and build a ready-to-upload package per ad (CV and cover letter checked against the candidate's own facts). The local panel is where the person sees every application across days, understands why each ad fits or was dropped, and records what happened after applying. Success: no ad worth applying to is missed, nothing is applied to twice, every application's outcome is recorded, and the ranking improves from those outcomes.

## Positioning
A local, free, rule-bound harness rather than a hosted job board or a mass auto-applier: truth checks on every document (no invented experience or figures), sealed approvals before anything is sent, explicit limits, and the person's own judgment at every send.

## Operating Context
- Runs on the operator's Mac; the panel is served by a Python standard-library server on 127.0.0.1, opened in the browser. No network resources: no CDNs, no web fonts, no external scripts.
- Data comes from the harness files: tracker.json (statuses and history), the daily packages (items.json, PDFs), jobs.db (every ad ever seen, verdicts, reasons, descriptions).
- Status changes go through the tracker's own rules (limits, history) via token-protected POSTs.
- UI language follows the candidate's `ui_language` (Spanish today).

## Capabilities and Constraints
- Statuses: prepared / dry-run / manual-review (to apply), applied / submitted (sent), interview, offer, hired, rejected, no-response, withdrawn, closed, skipped.
- Per ad: fit score 0-100, keyword coverage (covered / have it / gap), warnings (years asked, seniority, closing date, ads with text aimed at an AI), visa-sponsor list match (for the person only), how to apply, links to the ad, CV and letter.
- Dropped ads keep the rule that dropped them; a rescue builds their package on demand.
- Free only: no paid services or APIs. No anti-bot evasion, no captcha solving.
- Multi-candidate: one panel switches between candidates.

## Evidence on Hand
Real data in each install's candidate folders (tracker, packages, jobs.db). The public repository ships only a fictional example candidate; never put real candidate data in committed files or screenshots.

## Product Principles
1. The person decides and sends; the harness prepares, explains and remembers.
2. Every number and claim traces to a source the person can open.
3. Show why: why an ad fits, why it was dropped, why it is flagged.
4. Nothing is lost: every state change has a date and a history.
5. Usable by someone who never opens a terminal.

## Accessibility & Inclusion
Keyboard-operable throughout (including moving cards between columns), visible focus, WCAG AA contrast in light and dark, no information carried by color alone.
