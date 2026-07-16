---
prompt_id: structure.recover-window
stage: structure_window_recovery
---

Recover a proposed section hierarchy for the supplied source window. Return only span labels,
ordered section boundaries, nesting, associations, confidence, and ambiguities. Copy no source
text except the permitted heading label field and never paraphrase, normalize, drop, duplicate,
or reorder a raw block. Every disposition must point to exactly one supplied span ID and preserve
the span's source text digest.
