---
prompt_id: structure.triage
stage: structure_triage
---

Decide whether the parser outline is trustworthy enough for downstream analysis. Compare the
ordered raw source spans with the parser outline using only deterministic signals and supplied
evidence. Report the decision, confidence, boundary regions, ambiguities, and evidence span IDs.
Do not recover or rewrite text in this stage. A disagreement is evidence for review, not a reason
to silently choose a preferred narrative.

Output identity is governed and literal:

- `prompt_id` must be exactly `structure.triage`.
- `model` must be exactly `gemini-3.1-flash-lite`.
- Copy `document_id`, `source_digest`, and `parser_outline_digest` exactly from the supplied
  governed document metadata. Never add a version suffix, substitute a schema title, or create an
  alias for any identity value.
- Copy every `evidence_span_ids` value and every boundary `start_span_id`/`end_span_id` verbatim
  from a supplied `[SPAN id=...]` header. Do not generate, normalize, shorten, or version span IDs.
- Treat every supplied source and span digest as immutable lowercase SHA-256 provenance. Copy it
  verbatim when the schema requests it; never recalculate it from normalized or paraphrased text.
