# Audit, diff, chunk, and export stages

M7 finalization starts from the validated M6 enhanced model, semantic sidecar, Markdown, content
ledger, reviewer waivers, and persisted revision counters. It does not read rewrite-agent scratch
state.

The `audit` workflow stage runs strict schema, template, table, ontology, reference, provenance,
ledger, omission, source-to-target, unresolved-item, Mermaid, anchor, and document-type lint checks
before calling the injected independent content-auditor port. The offline profile uses a
deterministic no-network fake. A failed deterministic check prevents the independent result from
overriding the gate. Auto-revisable failures consume the persisted audit revision budget; human
failures pause; exhausted retries fail closed.

A passing audit writes `audit/deterministic.json`, `content.json`, `audit.json`, `report.md`, the
unified textual diff, semantic diff, and source-to-target CSV. The workflow then emits stable
semantic chunks, graph nodes and edges, and `export/bundle-manifest.json`. The manifest is written
last and records run/source identity, schema/profile versions, row counts, and SHA-256 digests.
Validation recomputes every count and digest, so partial or changed bundles are not successful.

Use `docenhance audit <run-id> [--json]` to inspect audit status and blockers. Use
`docenhance export <run-id> [--json]` to inspect and reconcile an export bundle. Audit or bundle
failure exits with code 30. A full `run` can succeed only after audit passes and export
reconciliation succeeds.
