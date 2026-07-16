---
prompt_id: clarification.questions
stage: clarification_questions
---

Use `baseline_questions` as the deterministic seed and the compact `findings` list only as its
governed rationale. Preserve coverage of every blocking source finding, deduplicate semantically
equivalent questions, and order prerequisites before dependent questions. Include why the answer
matters, evidence, target, expected answer shape, allowed states, and dependencies. Do not request
the full source or analysis fan-out: cited evidence in the seed is the complete evidence boundary
for this call. Propose a safe default only for a justified non-factual choice; never propose
owners, IDs, thresholds, approvals, controls, dates, or evidence as facts.
