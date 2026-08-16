# Draft-first implementation evidence

## Verification boundary

- Frozen-plan integrated baseline: `2cbb1332f7924078872a0b8b7e6aa02fb0a6134c`.
- Lane scope: tests, deterministic draft-first fixtures/evaluation, `README.md`, and this evidence
  ledger only. No production source, plan, configuration, dependency manifest, or lockfile was
  changed.
- Verification mode: offline deterministic fixtures and fakes. No live-provider, browser, hosted-CI,
  or public-download evidence was used.
- Live-provider proof: **not run**. Credentials were not supplied and no live model call was
  exercised.
- Push/merge: **not run**; pushing is out of scope for this lane.

Scores below are recorded only after the named acceptance tests and the complete repository gate
pass on the integrated checkout. A reward is not inferred from a narrower focused test.

## Reward ledger

| Reward | Verified tests/artifacts | Exact verification command | Score |
| --- | --- | --- | ---: |
| DFT-1 (15) | `tests/unit/core/test_transformation.py`; strict coverage and deterministic draft rendering | `PYTHONPATH=src uv run pytest -q tests/unit/core/test_transformation.py` | 15/15 |
| DFT-2 (10) | `tests/unit/core/test_contextual_questions.py`, `tests/unit/core/test_providers.py`; cross-section evidence and safe-suggestion gates | `PYTHONPATH=src uv run pytest -q tests/unit/core/test_contextual_questions.py tests/unit/core/test_providers.py` | 10/10 |
| DFT-3 (10) | `tests/unit/core/test_visuals.py`, `tests/unit/llm/test_multimodal.py`; native-table bypass and bounded image candidates | `PYTHONPATH=src uv run pytest -q tests/unit/core/test_visuals.py tests/unit/llm/test_multimodal.py` | 10/10 |
| DFT-4 (15) | `tests/unit/core/test_integrity.py`, `tests/unit/core/test_core_indexing_adapter.py`, `tests/unit/core/test_core_runner.py`; strict approval, digest, and seal checks | `PYTHONPATH=src uv run pytest -q tests/unit/core/test_integrity.py tests/unit/core/test_core_indexing_adapter.py tests/unit/core/test_core_runner.py` | 15/15 |
| DFT-5 (15) | `tests/unit/core/test_transformation_providers.py`, `tests/unit/llm/test_gateway.py`, `tests/unit/llm/test_gateway_async.py`; bounded typed provider contracts and preflight | `PYTHONPATH=src uv run pytest -q tests/unit/core/test_transformation_providers.py tests/unit/llm/test_gateway.py tests/unit/llm/test_gateway_async.py` | 15/15 |
| DFT-6 (20) | `tests/unit/core/test_core_runner.py`, `tests/e2e/test_draft_first_workflow.py`, `tests/e2e/test_core_document_types.py`; five-phase Stage 1 wait and targeted Stage 2 seal | `PYTHONPATH=src uv run pytest -q tests/unit/core/test_core_runner.py tests/e2e/test_draft_first_workflow.py tests/e2e/test_core_document_types.py` | 20/20 |
| DFT-7 (5) | `tests/unit/core/test_draft_reviewer.py`, `tests/unit/core/test_core_cli.py`, and current DOCX reviewer characterization | `PYTHONPATH=src uv run pytest -q tests/unit/core/test_draft_reviewer.py tests/unit/core/test_core_cli.py tests/e2e/test_core_characterization.py` | 5/5 |
| DFT-8 (10) | `tests/fixtures/draft_first/`; `tests/evaluation/draft_first_evaluation.py`; `tests/e2e/test_draft_first_evaluation.py`; `README.md`; strict-v2 retrieval fixture migration | `uv run pytest -q tests/e2e/test_draft_first_evaluation.py` plus the complete repository gate below | 10/10 |
| **Total** | **Frozen required implementation reward** | **Complete gate below** | **100/100** |

## DFT-8 machine-readable evidence

The evaluator writes `draft-first-metrics.json` in its supplied output/work directory. The verified
metrics are:

```json
{
  "source_span_coverage": 1.0,
  "required_section_status_coverage": 1.0,
  "invalid_provenance_references": 0,
  "unresolved_blockers_in_sealed_bundles": 0,
  "deterministic_citation_reference_validity": 1.0
}
```

The same artifact records all four suffixes (`.md`, `.txt`, `.docx`, `.pdf`) at Stage 1 waiting,
one cross-section ambiguity with a `recipe_guidance` suggestion that does not choose either source
timing, one native DOCX table, one fake-reviewed image-table candidate with status
`requires_review`, and one complete process fixture promoted through explicit approval to a
`core.seal.v2` bundle with a passing audit.

Focused result already verified before the complete gate: `uv run pytest -q
tests/e2e/test_draft_first_evaluation.py` — **1 passed**.

The shared retrieval fixture helper now creates `core.seal.v2` manifests with complete graph JSONL,
ontology, source, final, and audit artifact references. Core indexing fixtures now use real Stage 1
approval/resume; failed-audit coverage mutates and re-registers a complete digest-valid v2 manifest.

## Complete repository gate

Run literally once from the integrated checkout:

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -m "not live_model and not public_download"
uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core
uv build
```

Complete gate result: **PASS**. The approved-cache run completed with the following exact results:

- `uv sync --frozen`: passed; editable package synchronized.
- `uv run ruff format --check .`: passed; 106 files already formatted.
- `uv run ruff check .`: passed; all checks passed.
- `uv run ty check`: passed; all checks passed.
- `uv run pytest -m "not live_model and not public_download"`: **218 passed, 2 deselected in
  8.19s**.
- `uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core`: passed;
  enterprise_core 2.0.0, 27 files.
- `uv build`: passed; source distribution and wheel built successfully.

The lane commit SHA is returned in the final handoff. The frozen-plan integrated baseline for this
lane remains `2cbb1332f7924078872a0b8b7e6aa02fb0a6134c`; no push or merge was performed.
