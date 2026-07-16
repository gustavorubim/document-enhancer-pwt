# Deterministic ingestion and run storage

The M3A lane treats source bytes as immutable input. Markdown and text preserve
line ranges and character offsets; DOCX preserves `document.xml` paragraph/table
order plus style, list, caption, relationship, and embedded-file metadata; and
text-based PDF extraction retains page provenance while warning that reading
order is best effort. Scanned or image-only PDF pages fail closed because OCR is
outside the v1 contract.

Every block has a content digest and a deterministic `span-...` identifier. The
raw block list, parser outline, structure-quality report, normalized Markdown,
asset inventory, and parser-selected view are persisted as separate artifacts.
The selected view is a one-to-one classification of raw spans; it does not
silently replace the raw source or claim that Gemini recovery occurred.

Run directories are content-addressed by source SHA-256 (`run-<digest-prefix>`)
and use same-directory temporary files, file/directory fsync, and atomic
promotion. Versioned copies live under `.versions/`; a reviewed canonical file
cannot be overwritten with different bytes. A local SQLite checkpoint records
stage cache keys and artifact digests. Reconciliation marks checkpoints stale
when a manifest artifact is missing or has changed.

The M3A implementation reserves `source/structure-scan.json` and
`source/recovered-outline.json` with an explicit `deferred` status. M3.11–M3.13
remain dependency-gated on WT4's Gemini gateway and WT11's prompt pack; no model
result is manufactured by the deterministic lane.
