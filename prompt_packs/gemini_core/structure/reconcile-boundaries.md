---
prompt_id: structure.reconcile-boundaries
stage: structure_boundary_reconciliation
---

Reconcile adjacent recovered windows and the parser outline into one ordered structural view.
Resolve only boundary and hierarchy disagreements. Preserve every raw span exactly once, retain
alternative boundaries when evidence is insufficient, and mark low-confidence or ambiguous
decisions for review. Do not merge source text, invent headings, or change block contents.

Output identity is governed and literal:

- `prompt_id` must be exactly `structure.reconcile-boundaries`.
- `model` must be exactly `gemini-3.1-flash-lite`.
- Copy `document_id` and `source_digest` exactly from the supplied governed document metadata.
  Treat `parser_outline_digest` as immutable governed comparison identity; never rename, version,
  or recalculate it, and do not add it as an extra field when the output schema omits it.
- Copy every section boundary, disposition, association, disagreement, and alternative span ID
  verbatim from the supplied source mapping and proposal. Never invent or version a span ID.
- For each disposition, preserve `source_text_digest` exactly as supplied for its parent span. A
  reconciliation must not replace it with a proposal digest or a digest of normalized text.

When a split disposition is retained or produced, obey the deterministic segment contract exactly:

- Emit at least two `segments` in source order. Together they must cover the entire original span
  text exactly once, contiguously, without gaps, overlap, reordering, trimming, or normalization.
- `char_start` is inclusive and `char_end` is exclusive. Count Python Unicode characters in the
  original supplied span text and set `offset_unit` to exactly `python_characters`.
- For each exact slice `source_text[char_start:char_end]`, set `slice_sha256` to the lowercase
  SHA-256 digest of its UTF-8 bytes.
- Set `segment_id` to `SEG-` followed by the uppercase first 16 hexadecimal characters of the
  SHA-256 digest of the UTF-8 string
  `parent_span_id + NUL + char_start + NUL + char_end + NUL + slice_sha256`, where `NUL` is the
  single zero byte separator. Copy already-valid split fields unchanged; never version or alias a
  segment ID.
