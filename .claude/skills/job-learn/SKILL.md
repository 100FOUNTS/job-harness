---
name: job-learn
description: Reviews the job-harness lessons (learn/observations.jsonl) and proposes concrete improvements to scripts, references, agents or tests. Use for "/job-learn", "what did we learn", "improve the harness".
---

1. `job learn list` and the last daily logs (`candidates/*/logs/*.log`, reports with many manual-review items).
2. Group by area (seek, linkedin, forms, docs, ats, harness). For each repeated problem propose ONE change: a script check, a reference update, an agent instruction, or an `answers.json` entry. Code changes come with a test that fails without them.
3. Show the proposal to the user; apply only after explicit approval; run `job test`.
