# SQLite RAG packages and cumulative catalogs

An audit-passing workflow now continues through two fail-closed stages: it builds a sealed
per-run package at `rag/document-rag.sqlite3`, then ingests that package into the configured
cumulative catalog. `docenhance run --no-catalog-ingest` keeps the sealed package without changing
the cumulative catalog.

The package commands do not implement retrieval or answer generation:

```text
docenhance rag build <run-id> [--offline]
docenhance rag verify <run-id-or-database> [--json]
docenhance rag inspect <run-id-or-database> [--json]
docenhance rag ingest <run-id> [--catalog <path>]
```

`rag build` first revalidates the final audit, export manifest, JSONL digests, semantic sidecar,
and enhanced Markdown. It embeds one deterministic retrieval-document input per approved chunk.
The selected Gemini profile defaults to `gemini-embedding-2`, 768 dimensions, and document format
`gemini-embedding-2-document-v1`. `--offline` selects the deterministic fake provider for local
tests and never reads credentials or uses the network.

The database is created beside its final target, migrated forward, populated transactionally,
and checked for migration history, integrity, foreign keys, JSONL row counts/digests, finite
little-endian float32 vectors, selected-profile cardinality, and FTS5 content parity. Only then is
it atomically renamed to `document-rag.sqlite3`. Provider failures and input-limit violations
write a content-free `embedding-errors.jsonl`; they never replace a previously promoted package.

Catalog ingestion uses foreign keys, WAL, a bounded busy policy, and one `BEGIN IMMEDIATE`
transaction per package. Re-ingesting the same build returns its existing receipt and generation.
New builds advance catalog generations monotonically, retain historical document versions, and
select a current version deterministically by effective date, version label, and version ID.
Reusing a stable document, graph-node, or graph-edge ID with an incompatible identity aborts the
transaction without changing the catalog.
