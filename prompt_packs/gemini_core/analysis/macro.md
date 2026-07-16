---
prompt_id: analysis.macro
stage: macro_analysis
---

Assess the document's purpose, audience, candidate document type, authority, scope, lifecycle,
template fit, structural completeness, and high-level fidelity/governance/retrieval risks. Map
each conclusion to evidence spans or a named governed requirement. Use the applicable common and
document-type rubrics from context and preserve uncertainty when the source does not establish a
fact. Every emitted rubric score must include at least one evidence item with both the exact
source span ID and its minimum verbatim supporting quote. If no supplied span supports a rubric
score, do not emit that score; record the gap as a finding instead. Never emit an empty rubric
score evidence list.
