# Document Enhancer

Document Enhancer is a local-first, Gemini-first Python CLI for turning enterprise methodology, standard, process, and desktop-procedure documents into traceable human, semantic, and retrieval-ready artifacts.

The repository now includes the foundational contracts, governed reference and prompt packs,
source ingestion and structure recovery, the Gemini model gateway, four parallel analysis
specialists, deterministic clarification artifacts, and a durable two-gate LangGraph workflow.
Governed rewriting, audit/export, and RAG execution follow in the remaining milestones.

## Verified status

M5 (questions, reviewer inputs, checklist, and resumable graph) is formally complete as of
2026-07-16. The complete offline gate passed on merged code commit `80cec30`: 220 tests passed and
2 opt-in tests were deselected; frozen sync, Ruff format/check, ty, generated schemas, the
enterprise reference pack, all 20 governed prompt routes across four document types, the synthetic
corpus, package build, and diff checks also passed. Runs now pause with exit code 10 for review,
persist durable state and idempotent side-effect receipts, validate reviewer edits fail-closed, and
resume without replaying unchanged analysis. M6 (governed rewrite, Mermaid, and semantic sidecar)
is the active next milestone.

## Quick start

```bash
uv sync --frozen
uv run docenhance --help
uv run docenhance doctor
```

The project requires Python 3.12 or 3.13 and uses `uv` for a reproducible environment. Provider credentials are never accepted as CLI arguments or committed configuration. For local Gemini checks, use the external ignored `.env` or the provider's normal credential mechanism and explicitly opt in with `DOCENHANCE_RUN_LIVE=1`.

## Current commands

```text
docenhance doctor [--json]
docenhance config show [--json]
docenhance version
docenhance run SOURCE [--run-dir PATH] [--until questions|checklist] [--json]
docenhance status RUN_ID [--run-dir PATH] [--json]
docenhance current-stage RUN_ID [--run-dir PATH] [--json]
docenhance next-action RUN_ID [--run-dir PATH] [--json]
docenhance resume RUN_ID [--run-dir PATH] [--json]
docenhance prompts list [--json]
docenhance prompts show PROMPT_ID [--composed] [--json]
docenhance prompts validate [--json]
```

The M5 workflow is offline-safe by default and writes editable clarification YAML plus readable
Markdown under the selected run directory. Calling a later unsupported product command returns a
clear configuration/contract error rather than pretending the capability is available.

## Verification

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -m "not live_model and not public_download"
uv run python scripts/generate_schemas.py --check
uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core
uv run python scripts/verify_prompt_pack.py prompt_packs/gemini_core \
  --reference-pack reference_packs/enterprise_core
uv run python scripts/generate_fixture_corpus.py --check
uv build
git diff --check
```

The coverage floor remains an incremental project guardrail, not a release-quality threshold; M8
raises and enforces the final threshold after the remaining workflow, rewrite, audit, export, and
RAG behavior lands.

Compatibility tests are offline by default. They validate the installed LangChain, LangGraph, Deep Agents, SQLite FTS5, sqlite-vec, and adapter shapes without sending document content anywhere. Live Gemini structured-output and embedding profile checks are separately marked `live_model` and require explicit opt-in.

## Data handling

Source documents and derived artifacts are treated as untrusted, confidential data. The workflow
logs event metadata only, redacts credential-shaped and raw-content values from prompt snapshots,
keeps provider tools disabled by default, and writes run artifacts atomically under the selected
local run directory. The external `.env` is intentionally preserved for local use and is never
read into output or logs.
