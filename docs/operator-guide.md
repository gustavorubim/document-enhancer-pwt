# Operator guide

This guide covers the supported local MVP: installation, non-secret configuration, the two-gate
enhancement workflow, artifacts, audit/export, SQLite RAG packages, retrieval and grounded answers,
pack authoring, troubleshooting, data handling, and current limits.

## Install and verify

The supported Python range is 3.12 through 3.13. From a source checkout:

```bash
uv sync --frozen
uv run docenhance version
uv run docenhance doctor --json
uv run docenhance prompts validate --json
```

To install a built wheel without the source checkout:

```bash
uv build
uv run --isolated --with dist/document_enhancer-0.1.0-py3-none-any.whl docenhance --help
```

`scripts/verify_release.sh` performs the stronger clean-clone and isolated-wheel proof described in
`docs/release.md`.

## Configure Gemini and storage

Configuration precedence is defaults, user TOML, project `document-enhancer.toml`, environment,
then explicit application overrides. `docenhance config show --json` displays the non-secret result.
Credentials are never accepted as CLI arguments or TOML fields.

Developer API configuration uses a process environment credential:

```bash
export DOCENHANCE_BACKEND=developer_api
export GEMINI_API_KEY='set-outside-the-repository'
```

Vertex AI uses Application Default Credentials plus explicit project and location metadata:

```bash
export DOCENHANCE_BACKEND=vertex_ai
export DOCENHANCE_VERTEX_PROJECT='your-project'
export DOCENHANCE_VERTEX_LOCATION='us-central1'
gcloud auth application-default login
```

The exact routes are `gemini-3.1-flash-lite` for structure and clerical work,
`gemini-3.5-flash` for analysis/audit, `gemini-3.1-pro-preview` for rewrite/reconciliation, and
`gemini-embedding-2` for embeddings. Defaults use 768-dimensional vectors. Exact model IDs,
backend, dimensions, input-format profile, and vector digests are stored with artifacts. Pro
fallback is disabled unless a named configuration explicitly enables and records it. Preview or
retired-model failures remain visible lifecycle failures.

Useful non-secret overrides include:

```bash
export DOCENHANCE_RUN_DIR=.document-enhancer/runs
export DOCENHANCE_CATALOG_PATH=.document-enhancer/rag/catalog.sqlite3
export DOCENHANCE_EMBEDDING_DIMENSIONS=768
```

## Run the normal two-gate workflow

Start a run. A waiting run exits with code 10 by design:

```bash
uv run docenhance run source.md --document-type process --json
uv run docenhance status RUN_ID --json
```

Gate 1 writes `clarification/questions.yaml`, `answers.yaml`, `steering.yaml`, `waivers.yaml`, and a
validation report. Edit the YAML only. Every answered item needs reviewer identity and an
`answer://`, `reference://`, `source://`, or `steering://` evidence reference. A waiver needs an
approver, reason, impact, review date, and expiry where applicable. Resume validates those edits
before any downstream stage executes:

```bash
uv run docenhance resume RUN_ID --json
```

Gate 2 writes `clarification/rewrite-checklist.yaml`. Resolve or waive blocking items and set
`approved_by` plus `approved_at`, then resume again:

```bash
uv run docenhance resume RUN_ID --json
uv run docenhance audit RUN_ID --json
uv run docenhance export RUN_ID --json
```

Checkpoint/resume does not call a completed upstream model stage again when source, packs, schemas,
and reviewer-input cache keys are unchanged. Source or governed-input changes invalidate the first
dependent stage and downstream results.

## Interpret artifacts, audit, diff, and export

Each run directory contains immutable source/normalization evidence, prompt and analysis manifests,
review YAML, output Markdown and semantic YAML, audit evidence, JSONL exports, a sealed RAG package,
and a workflow snapshot. Important final surfaces are:

```text
output/enhanced.md
output/enhanced.semantic.yaml
audit/audit.json
audit/report.md
audit/content.diff.patch
audit/semantic.diff.yaml
audit/source-to-target.csv
export/chunks.jsonl
export/nodes.jsonl
export/edges.jsonl
export/bundle-manifest.json
rag/document-rag.sqlite3
rag/build-manifest.json
rag/catalog-ingestion.json
```

The audit fails closed on schemas, template/rubric requirements, references, provenance, ledger
coverage, omissions, unresolved items, Mermaid/anchors, and independent content fidelity. The
export manifest is written last and reconciles row counts and SHA-256 digests. A failed audit,
partial export, embedding failure, or corrupt database is never promoted as successful.

## SQLite schema, migrations, packages, and catalog

`rag/document-rag.sqlite3` is a sealed per-run package. It stores document/version metadata,
sections, chunks, provenance, graph nodes/edges, FTS5 rows, embeddings, build inputs, and migration
history. `PRAGMA user_version` and migration digests are verified before reads. Build promotion
checks integrity, foreign keys, JSONL/database counts and digests, finite little-endian float32
vectors, profile cardinality, and FTS parity.

The cumulative catalog retains generations and historical versions; current-only retrieval is the
default. Ingestion is atomic and idempotent. Identity conflicts abort without changing the catalog.

```bash
uv run docenhance rag verify RUN_ID --json
uv run docenhance rag inspect RUN_ID --json
uv run docenhance rag ingest RUN_ID --catalog .document-enhancer/rag/catalog.sqlite3 --json
uv run docenhance rag stats --catalog .document-enhancer/rag/catalog.sqlite3 --json
```

## Search, ask, chat, sources, graph, and stats

Retrieval-only search fuses vector, FTS, and bounded graph channels and exposes channel ranks,
filters, paths, catalog generation, and latency:

```bash
uv run docenhance rag search "monthly review owner" --offline --explain
uv run docenhance rag search "REQ-TPRM-001 evidence" --document-type standard --json
uv run docenhance rag graph CTRL-ACCESS-014 --depth 2 --json
uv run docenhance rag stats --json
```

Grounded answer and chat commands validate structured claim-level citations and allow at most one
retrieval retry plus one grounding repair. Insufficient evidence or failed grounding renders
`insufficient`, never an unqualified answer:

```bash
uv run docenhance rag ask "Who records the monthly review?" --offline --explain
uv run docenhance rag chat --offline --no-save
uv run docenhance rag chat --offline --session SES-MONTHLY-001
uv run docenhance rag sources ANSWER_ID --json
```

Unsaved chat is in memory. A named session stores visible user/final assistant messages, citations,
and diagnostics, never hidden reasoning. `/refresh` explicitly advances a pinned catalog generation;
`/sources`, `/filters`, `/clear`, `/session`, `/help`, and `/exit` are also available.

## Reproduce the offline enhancement and Rich RAG demo

The M8 demo uses fictional content and deterministic local fakes. It stops at Gate 1, writes and
validates a reviewer answer, stops at Gate 2, approves the checklist, resumes through audit/export,
builds and ingests the RAG package, runs search, and returns a cited grounded answer:

```bash
uv run python scripts/run_offline_demo.py --output /tmp/document-enhancer-m8-demo --force
python -m json.tool /tmp/document-enhancer-m8-demo/demo-result.json
```

Expected evidence includes `gate1.stage=gate1`, `gate2.stage=gate2`,
`completed.status=succeeded`, `audit.status=pass`, `rag_package.valid=true`, at least one search hit,
and an answered/partial result with `grounding_passed=true` and citations.

## Author prompt and reference packs

Prompt packs are versioned, digest-checked, schema-bound, and tool-free. Add the prompt template,
declare bounded variables and escaping in `manifest.yaml`, map the exact model route/output schema,
and validate:

```bash
uv run python scripts/verify_prompt_pack.py prompt_packs/gemini_core \
  --reference-pack reference_packs/enterprise_core
```

Reference packs declare every file and digest, precedence, templates, rubrics, terminology,
ontology extensions, and lifecycle metadata. Paths are canonical and YAML has size/depth/node
limits. Validate with:

```bash
uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core
```

See `docs/prompt-pack-authoring.md` and `docs/reference-pack-authoring.md` for field-level contracts.

## Troubleshooting

- Exit 10 is a normal review pause; inspect `status` and `next-action`.
- Exit 20 means reviewer input or another contract failed validation; fix the named artifact.
- Exit 30 means audit, export, package, catalog, retrieval, citation, or grounding failed closed.
- Exit 40 is a provider failure; inspect redacted lifecycle/auth/retry metadata.
- Exit 50 is non-secret configuration failure; run `doctor` and `config show`.
- Exit 60 is unsupported input, active content, unsafe container, encrypted/scanned PDF, or size limit.
- A profile mismatch requires rebuilding with the same embedding model, dimensions, backend, and
  format version; vectors are never silently mixed.
- `rag search --offline` is appropriate for deterministic demos only. Normal queries require the
  same live embedding profile that built the catalog.

## Data handling and known limitations

Source text, enhanced text, graph data, FTS rows, embeddings, questions, answers, and saved chat are
the same confidentiality class. Local files use owner-only database permissions where supported.
Retrieved content remains delimited untrusted evidence and has no shell, browser, network,
code-execution, or document-write authority. External tracing is off by default. Operational logs
use digests/bounded metadata and redact key/token/password shapes.

Current limitations are explicit:

- PDF support is text-based; OCR and image-only/scanned pages are unsupported and fail closed.
- Messy-structure recovery has confidence uncertainty and requires fixture evaluation/human review.
- Gemini model availability, preview behavior, latency, and pricing can change; exact lifecycle
  failures must be re-evaluated live.
- Inferred knowledge remains a separate reviewable graph layer, not authoritative fact.
- Local SQLite is suitable for bounded local catalogs, not unbounded multi-tenant enterprise scale.
- Pinned pre-v1 `sqlite-vec==0.1.9` is a compatibility risk despite release tests.
- There is no enterprise identity/authorization integration or hosted UI in the MVP.
- Retention/purge policy must be defined for deployment; secure deletion depends on platform and
  storage behavior.
