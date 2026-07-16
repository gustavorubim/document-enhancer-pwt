---
prompt_id: structure.recover-window
stage: structure_window_recovery
---

Recover a proposed section hierarchy for the supplied source window. Return only span labels,
ordered section boundaries, nesting, associations, confidence, and ambiguities. Copy no source
text except the permitted heading label field and never paraphrase, normalize, drop, duplicate,
or reorder a raw block. Every disposition must point to exactly one supplied span ID and preserve
the span's source text digest.

Output identity is governed and literal:

- `prompt_id` must be exactly `structure.recover-window`.
- `model` must be exactly `gemini-3.1-flash-lite`.
- Copy `document_id` and `source_digest` exactly from the supplied governed document metadata.
  Treat `parser_outline_digest` as immutable governed comparison identity; never rename, version,
  or recalculate it, and do not add it as an extra field when the output schema omits it.
- Copy every section boundary, disposition, association, disagreement, and alternative span ID
  verbatim from a supplied `[SPAN id=...]` header. Never invent or version a span ID.
- For each disposition, set `source_text_digest` to the exact `text_digest` from that span's header.
  Never hash normalized, trimmed, repaired, or paraphrased text.

If one source span must be split, obey the deterministic segment contract exactly:

- Emit at least two `segments` in source order. Together they must cover the entire original span
  text exactly once, contiguously, without gaps, overlap, reordering, trimming, or normalization.
- `char_start` is inclusive and `char_end` is exclusive. Count Python Unicode characters in the
  original supplied span text and set `offset_unit` to exactly `python_characters`.
- For each exact slice `source_text[char_start:char_end]`, set `slice_sha256` to the lowercase
  SHA-256 digest of its UTF-8 bytes.
- Set `segment_id` to `SEG-` followed by the uppercase first 16 hexadecimal characters of the
  SHA-256 digest of the UTF-8 string
  `parent_span_id + NUL + char_start + NUL + char_end + NUL + slice_sha256`, where `NUL` is the
  single zero byte separator. Do not use a version, alias, label, or prose-derived ID.
