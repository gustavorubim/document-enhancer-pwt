# Document Enhancer

Document Enhancer is a local-first, Gemini-first Python CLI for turning enterprise methodology, standard, process, and desktop-procedure documents into traceable human, semantic, and retrieval-ready artifacts.

This repository currently contains the WT0 foundation. It freezes the cross-lane contracts, configuration and logging behavior, provider routing policy, compatibility probes, and a usable `docenhance doctor` command. Later milestones add ingestion, analysis, rewrite, audit, export, and RAG execution behind these ports.

## Quick start

```bash
uv sync --frozen
uv run docenhance --help
uv run docenhance doctor
```

The project requires Python 3.12 or 3.13 and uses `uv` for a reproducible environment. Provider credentials are never accepted as CLI arguments or committed configuration. For local Gemini checks, use the external ignored `.env` or the provider's normal credential mechanism and explicitly opt in with `DOCENHANCE_RUN_LIVE=1`.

## Commands in the foundation

```text
docenhance doctor [--json]
docenhance config show [--json]
docenhance version
```

The remaining product commands are reserved for later milestones. Calling an unsupported command returns a clear configuration/contract error rather than pretending that a later workflow is available.

## Verification

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -m "not live_model and not public_download" --cov
uv build
uv run --isolated --with ./dist/document_enhancer-0.1.0-py3-none-any.whl docenhance --help
```

The WT0 coverage floor is an initial 70% scaffold baseline. It is intentionally recorded in `pyproject.toml` with a requirement to raise it as later milestone behavior and tests land; it is not a release-quality threshold.

Compatibility tests are offline by default. They validate the installed LangChain, LangGraph, Deep Agents, SQLite FTS5, sqlite-vec, and adapter shapes without sending document content anywhere. Live Gemini structured-output and embedding profile checks are separately marked `live_model` and require explicit opt-in.

## Data handling

Source documents and derived artifacts are treated as untrusted, confidential data. The foundation logs event metadata only, redacts credential-shaped values, keeps provider tools disabled by default, and does not create or modify run artifacts. The external `.env` is intentionally preserved for local use and is never read into output or logs.
