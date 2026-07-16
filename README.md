# Document Enhancer

Document Enhancer is a local-first, Gemini-first Python CLI for turning enterprise methodology, standard, process, and desktop-procedure documents into traceable human, semantic, and retrieval-ready artifacts.

The repository now includes the foundational contracts, governed reference and prompt packs,
source ingestion and structure recovery, the Gemini model gateway, four parallel analysis
specialists, deterministic clarification artifacts, a durable two-gate LangGraph workflow, and a
governed rewrite pipeline that derives Markdown, Mermaid, and semantic outputs from one validated
intermediate model. The audited export pipeline now builds and promotes a validated local SQLite
catalog, and the Rich CLI performs explainable retrieval and grounded cited Q&A over that catalog.

## Verified status

M8 (fixtures, evaluation, security, documentation, and release) is formally complete as of
2026-07-16. The complete offline gate passed on merged code commit `d7c80c1`: 266 tests passed and 2
opt-in tests were deselected; frozen sync, import smoke, Ruff format/check, ty, generated schemas,
both governed packs, all 60 generated corpus files, both evaluation artifacts, package build, and
diff checks also passed. All 21 deterministic offline release thresholds passed across 48
fixture-format evaluations. A separate temporary clean clone and isolated-wheel proof passed at
`5b763b8` with zero Gemini calls and zero public downloads. These are controlled offline results,
not claims about live Gemini quality or public-source generalization; live-model and public-download
evaluations remain explicit opt-in checks. The final plan/evidence reconciliation audit is active.

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
docenhance rag build RUN_ID [--run-dir PATH] [--offline] [--json]
docenhance rag verify RUN_ID_OR_PACKAGE [--run-dir PATH] [--json]
docenhance rag inspect RUN_ID_OR_PACKAGE [--run-dir PATH] [--json]
docenhance rag ingest RUN_ID [--run-dir PATH] [--catalog PATH] [--json]
docenhance rag search QUERY [--catalog PATH] [--explain] [--json]
docenhance rag ask QUESTION [--catalog PATH] [--explain] [--json]
docenhance rag chat [--catalog PATH] [--session ID] [--no-save] [--json]
docenhance rag sources ANSWER_OR_SESSION_ID [--catalog PATH] [--json]
docenhance rag graph ENTITY_ID [--catalog PATH] [--depth 1|2] [--json]
docenhance rag stats [--catalog PATH] [--json]
```

The workflow is offline-safe by default. It writes editable clarification artifacts first, then
after the review gates writes the content ledger, rewrite inputs, enhanced model, enhanced
Markdown, open issues, semantic sidecar, Mermaid validation, audit/diff/export bundle, and sealed
RAG package under the selected run directory. It can then promote that package into the cumulative
catalog for the Rich retrieval and grounded-answer commands. See `docs/rag-cli.md` for the local
RAG workflow and persistence behavior.

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
uv run python scripts/run_evaluations.py --check
uv build
git diff --check
```

For the stronger release proof, run `scripts/verify_release.sh HEAD`; it repeats the gate in a
temporary clean clone and then validates the built wheel from a separate isolated environment.
The checked-in offline evaluation report and exact limitations are in
`evals/reports/m8-evaluation.md`.

Compatibility tests are offline by default. They validate the installed LangChain, LangGraph, Deep Agents, SQLite FTS5, sqlite-vec, and adapter shapes without sending document content anywhere. Live Gemini structured-output and embedding profile checks are separately marked `live_model` and require explicit opt-in.

## Data handling

Source documents and derived artifacts are treated as untrusted, confidential data. The workflow
logs event metadata only, redacts credential-shaped and raw-content values from prompt snapshots,
keeps provider tools disabled by default, and writes run artifacts atomically under the selected
local run directory. The external `.env` is intentionally preserved for local use and is never
read into output or logs.
