# Draft-first implementation evidence

## Verification boundary

- Frozen-plan integrated baseline: `2cbb1332f7924078872a0b8b7e6aa02fb0a6134c`.
- Current increment scope: explicit source-to-target retrieval linkage, bounded PDF embedded-image
  extraction, provider-contract hardening, source-title/mapping-backed accounting, tests,
  dependency lock, and synchronized root documentation.
- Verification modes: deterministic offline fixtures/fakes plus one opt-in live Gemini run against
  the checked-in fictional complete-process fixture. No user document, browser, hosted-CI, or
  public-download result is claimed.
- Live-provider proof: **pass**. Run `a5af52fe075d-b1429e75a0` completed Stage 1, accepted one answer
  copied from its cited source evidence, passed every final audit check, and wrote a strict
  `core.seal.v2` manifest.
- Publication evidence is recorded after the current literal gate and Git integration complete.

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

## Current follow-up increment evidence

### Explicit rewritten-heading linkage

- `core.source-target.v2` separates source section identity from target template identity and records
  source spans plus the final digest.
- The sealed adapter verifies that map. RAG catalog v2 stores target section ID, source section IDs,
  and link method on each chunk.
- The focused retrieval suite includes a renamed-heading case that links `Governance and Monitoring`
  to the original `Controls` graph node and expands its real edges.

### Bounded PDF image extraction

- Direct embedded PNG/JPEG XObjects are checked before decode against image-count, byte, pixel, and
  dimension limits. Page, occurrence, source-span, media-type, and digest provenance is preserved.
- The PDF end-to-end fixture reaches Stage 1 visual review, explicit acceptance, final PNG appendix,
  DOCX media embedding, and a passing final audit. Oversized dimensions are rejected before decode.
- The same deterministic fixture was rendered with Poppler and visually inspected; source text and
  the colored embedded image were present without visible layout defects.

### Live provider and fail-closed behavior

- Final proof run: `/tmp/document-enhancer-live-validation-final2/a5af52fe075d-b1429e75a0`
  (ephemeral local evidence, not committed). It produced 19 validated source-target links, 74 graph
  nodes, and 65 graph edges; the sealed-bundle loader accepted it.
- An earlier live candidate copied template `TBD` cells while claiming fidelity. The application now
  rejects placeholder occurrences unsupported by the complete source before Stage 1 promotion,
  while preserving source-origin markers for human review. The prompt requires template-only
  missing information to remain in the frozen structured gap contract, and regression tests cover
  both sides of that provenance boundary.
- Provider gap identifiers are canonicalized to stable `GAP-###` IDs, mapping placement cannot
  contain draft prose, the source title is retained, and renamed headings use the explicit span
  ledger for final source-accounting checks.

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

Current complete gate result: **PASS** on the post-correction checkout.

- `uv sync --frozen`: passed; editable package synchronized from the frozen lock.
- `uv run ruff format --check .`: passed; **108 files already formatted**.
- `uv run ruff check .`: passed; all checks passed.
- `uv run ty check`: passed; all checks passed.
- `uv run pytest -m "not live_model and not public_download"`: **227 passed, 2 deselected in
  7.97s**.
- `uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core`: passed;
  `enterprise_core` 2.0.0, 27 files, all four document types.
- `uv build`: passed; built `document_enhancer-0.1.0.tar.gz` and
  `document_enhancer-0.1.0-py3-none-any.whl`.

Before the literal gate, all five README Mermaid blocks rendered successfully with Mermaid CLI and
installed headless Chrome, all four local Markdown links resolved, and `git diff --check` passed.
Publication/remote ancestry is verified during the Git closeout and reported in the final handoff.
