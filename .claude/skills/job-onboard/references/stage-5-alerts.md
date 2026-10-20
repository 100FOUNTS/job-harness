# Stage 5 — Alerts

Goal: the saved searches on each platform match `targets.json` searches (they are also what `job discover` reads, via public endpoints).

1. For each search in `targets.json`, after the user's OK:
   - LinkedIn: `https://www.linkedin.com/jobs/search/?keywords=<kw>&location=<loc>` → toggle "Set alert" (check "Alert on").
   - SEEK: `https://au.seek.com/<kw-with-dashes>-jobs/in-<Where-With-Dashes>` (e.g. `in-Western-Australia-WA`) → heart "Save this search". A wrong location slug returns 0 results: search once from the box to get the canonical URL.
2. Verify: SEEK `https://au.seek.com/my-activity/saved-searches` (count), LinkedIn "Alert on" state.
3. If LinkedIn offers job alerts after editing "Open to work", do not accept silently; ask.
4. `job discover <slug> --dry` to confirm the endpoints return jobs for every search.
