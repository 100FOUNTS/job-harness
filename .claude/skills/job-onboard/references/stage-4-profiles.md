# Stage 4 — Platform profiles (SEEK, LinkedIn)

Goal: profiles consistent with the master CV, findable by recruiters, without publishing anything to the network.

## 4a. Audit (read-only) → proposal
Use the `profile-auditor` agent. It writes `candidates/<slug>/profiles/proposal.md`: problems by priority + exact texts to paste. Typical findings: no default resumé on SEEK (CV invisible), old resumé with wrong dates, no summary/salary, missing roles, misspelt companies, hospitality skills only, headline typos, missing sections.

## 4b. Apply approved changes
Only after the user approves (gate `profile-changes`, human). One tab, closed at the end.

SEEK (au.seek.com/profile/me)
- Upload the master PDF as `<First_Last>_Resume.pdf` and make it default. SEEK then re-parses it and shows "Found in resumé" suggestions: add the correct ones, "Don't include" the rest.
- Combobox fields (company, qualification): click → cmd+a → type → click the dialog title to close suggestions. **Escape discards the whole form.**
- Summary has a character limit (~600): watch the counter.
- Role titles/locations autocomplete: type all but the last character, wait 1 s, type the last one, then pick the exact option.
- Leave "Right to work" as the candidate set it; do not add it if empty (rule: only when a form asks).

LinkedIn
- Turn **Notify network OFF** in every add/edit form before saving; on "share this update" screens click **Skip**.
- LinkedIn drops characters when typing fast: set long texts with the native value setter + input event via `javascript_tool`, then verify the value.
- Sections load lazily: check `/details/<section>/` for existing items **before adding** (otherwise duplicates).
- Some certifications require an issuing organisation: if unknown, ask; never invent.
- "Open to work": recruiters only; titles, on-site + hybrid, employment types, locations.

## Never
Delete anything (resumés, posts, duplicates): tell the user exactly what to delete. Verify identity, enter passwords, accept terms: the person does it.
