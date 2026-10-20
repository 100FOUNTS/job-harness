# Stage 1 — Profile and gaps

Goal: `intake.json` (who, rules, preferences, sensitive answers), `answers.json` (form Q&A) and `facts.json` (confirmed figures).

1. Fill `intake.json` from stage 0 with defaults marked as assumptions. Ask ONE compact list of what is missing, typically:
   - work rights / visa / sponsorship (stored in `sensitive_only_if_asked`, never in documents),
   - target roles and seniority, locations, FIFO, employment type, salary, start date,
   - licence (country, IDP), certificates (issuer, expiry), referees (2, at least one professional),
   - date conflicts found in stage 0.
2. Rules the user states go to `intake.rules` (`never_mention`, `never_include`, `other`). They are enforced by `job lint`.
3. Figures: for each number in the old CV ask whether the person can explain how it was measured. Keep → `job facts <slug> add`; uncertain → "approximately"; unmeasurable (e.g. "awareness +35%") → remove. Non-claim numbers (ISO 14001, phone, journal pages) → `facts.json` `allow` list.
4. `answers.json`: map common Australian form questions (right to work, sponsorship now vs future, visa, salary, notice, licence, police check, medical, FIFO, relocation, EEO, referees) to answers. Anything unknown stays `null` → manual-review.

Lessons
- Do not over-explain obvious points to the user (e.g. that a career changer will not apply to senior roles). Propose the action.
- "Will you require sponsorship now **or in the future**?" ≠ "Do you currently require sponsorship?": answer both truthfully and separately.
