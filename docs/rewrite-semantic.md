# M6 rewrite and semantic output

The M6 path starts only after the approved gate-2 checklist. It creates one content ledger for
every normalized source span, builds section inputs from that ledger plus answered reviewer
inputs and governed reference metadata, and validates an `EnhancedDocumentModel` before any
output is promoted.

Markdown, structured tables, Mermaid, and `enhanced.semantic.yaml` are projections of that same
model. Source text is copied only through evidence links; unanswered, unsupported, unknown, and
TBD values become `OpenIssue` records and are not emitted as authoritative semantic objects.
Mermaid node IDs are syntax-safe projections of stable semantic IDs, and every edge is checked
against the model's node set.

M6 artifacts are written under `output/`:

- `content-ledger.jsonl` — one disposition per normalized source span.
- `rewrite-inputs.json` and `enhanced-model.json` — bounded rewrite inputs and validated model.
- `enhanced.md` — selected reference-pack template with authoring comments removed.
- `open-issues.yaml` — explicit unresolved items.
- `enhanced.semantic.yaml` — typed sidecar projected from the same model.
- `mermaid-validation.json` — deterministic diagram reference checks.

`revision_counters` is persisted in the workflow checkpoint. Rewrite and audit increments fail
closed once their configured maximum is reached; no exhausted pass is silently retried.
