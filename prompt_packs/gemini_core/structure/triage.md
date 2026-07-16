---
prompt_id: structure.triage
stage: structure_triage
---

Decide whether the parser outline is trustworthy enough for downstream analysis. Compare the
ordered raw source spans with the parser outline using only deterministic signals and supplied
evidence. Report the decision, confidence, boundary regions, ambiguities, and evidence span IDs.
Do not recover or rewrite text in this stage. A disagreement is evidence for review, not a reason
to silently choose a preferred narrative.
