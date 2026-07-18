# Workflow quality enhancement plan

Status: implemented through Phases 0–6 in the file-backed `core/` path.

This plan upgrades the simplified authoring shell to the specialist operator journey in
[AGENTS.md](AGENTS.md). Engineering simplification remains complete; this file tracks the
workflow-quality contract.

## Delivered increments

1. Hygiene: husk packages removed, CLI `--structure-mode auto`, sealed-bundle consumer renamed to
   `core/indexing.py`, unused direct deps trimmed.
2. Review contracts: `SectionAssessment` (`correct` / `missing` / `improve`), scoped rubric mapping,
   and separate verbose `review/macro.md`, `sections.md`, `flow.md`.
3. Dual process flow: inferred and proposed Mermaid embedded in `flow.md`, plus adjustment reasoning;
   standalone `.mmd` artifacts retained.
4. Decisions + rewrite: `approve_rewrite`, `steering`, `waivers`, missing-section stubs, offline
   application of accepted decisions, template text passed to the live rewrite provider.
5. Ontology-shaped graph export: section `ontology_hooks` projected into `core.graph.v1`.
6. Stronger verify: assessments, dual flow, deferred decisions, graph types, and stronger anchors.
7. Inbox UX: `docenhance watch-inbox` thin wrapper around `run`.

## Acceptance gate

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -m "not live_model and not public_download"
uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core
uv build
```
