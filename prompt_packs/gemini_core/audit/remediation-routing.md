---
prompt_id: audit.remediation-routing
stage: remediation_routing
---

Route audit findings into auto-revisable, reviewer-required, waived, or terminal failure paths.
Use the supplied severity, evidence, checklist status, waiver metadata, and deterministic gate
rules. A model cannot waive a blocker, promote an inferred claim, or authorize a factual change.
Return precise next actions and the reason each item is safe or unsafe to revise automatically.
