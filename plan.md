# Current implementation and delivery plan

Status: implemented and release-verified

Updated: 2026-08-16

Authoritative historical contract: `DRAFT_FIRST_IMPLEMENTATION_PLAN.md`

Implementation evidence: `DRAFT_FIRST_IMPLEMENTATION_EVIDENCE.md`

## Outcome

Document Enhancer accepts one `.md`, `.txt`, `.docx`, or `.pdf` source plus a selected reference
pack, performs the existing macro, section, and process analysis, and writes the source-supported
content into the target template during Stage 1. Missing, ambiguous, conflicting, or unreadable
content remains visible as structured review metadata. A human resolves the generated questions in
one decision file before Stage 2 can revise, audit, and seal the final bundle.

The authoring path is a deterministic five-phase runner with bounded typed model operations. It is
not one opaque model call and does not use a Deep Agents runtime.

## Current operator contract

1. `docenhance run SOURCE` selects exactly one source and a validated document-type recipe.
2. Extract preserves original bytes, ordered spans, source sections, tables, figures, warnings, and
   digests. Direct embedded PNG/JPEG images in supported PDFs are extracted within fixed budgets;
   whole-page rasterization and OCR are outside the authoring path.
3. Analyze produces the macro review, per-section correct/missing/improve assessment, inferred and
   proposed process flows, contextual questions with safe suggestions, a complete source-to-template
   mapping, and an unapproved template-aligned candidate draft.
4. Stage 1 always stops at `waiting / human_review` and writes `review/decisions.yaml`. The candidate
   begins with the source document title, preserves only source-supported prose, and represents
   missing content through typed gaps rather than copied template placeholders.
5. The reviewer answers or rejects each question, optionally adds steering or waivers, and sets
   `approve_rewrite: true`.
6. `docenhance stage-two RUN_ID` or `docenhance continue RUN_ID` validates the immutable Stage 1
   artifacts and decisions, applies targeted revisions to that exact candidate, renders final
   Markdown and DOCX, emits semantic/ontology/graph exports, and runs the promotion audit.
7. Only a passing audit writes `json/12-seal.json`. Failed verification remains inspectable and is
   never retrieval-authoritative.
8. Optional RAG commands consume explicitly selected passing sealed bundles. Retrieval is not on
   the authoring critical path.

## Model-operation design

Live mode can load the complete source, selected template, recipe metadata, and eligible visual
evidence whenever the context preflight fits. The application separates responsibilities so each
output has a narrow schema and a deterministic promotion boundary:

| Operation | Responsibility | Application-owned gate |
| --- | --- | --- |
| Structure recovery | Recover headings/blocks only when parser quality routes to recovery | Span IDs and source evidence must resolve |
| Whole-document mapping | Macro, section, process, questions, safe suggestions, gaps, and source dispositions | Complete source-span coverage and valid template/figure/question references |
| Candidate drafting | Rewrite each frozen target section in clear English from mapped evidence | Frozen IDs/status/provenance; no invented sections or unsupported template-origin placeholder prose |
| Draft fidelity audit | Independently report additions, omissions, bad references, and blockers | Local checks remain authoritative even if the provider says pass |
| Stage 2 revision/audit | Apply approved answers and independently review final content | Immutable decisions, no unresolved gaps/placeholders, provenance, figures, graph, and all final checks |

This design deliberately rejects a single all-powerful call: analysis, drafting, and independent
audit have different failure modes and need separate typed evidence. A deep agent would add tool
selection and looping without improving the fixed document workflow, so it remains out of scope.

## Artifact and provenance contracts

Stage 1 writes:

- `draft/transformation.json`: frozen mapping, typed gaps, questions, dispositions, and coverage;
- `draft/document.md` and `draft/document.docx`: visibly unapproved template-aligned candidate;
- `draft/audit.json`: independent plus deterministic fidelity result;
- `draft/visual-extractions.json`: bounded image/table/diagram candidates;
- `markdown/02-review-overview.md` through `06-review-questions.md`, both flow diagrams,
  `review/decisions.yaml`, and `report.html`.

Successful Stage 2 adds:

- `markdown/07-final-document.md` and `documents/final.docx`;
- `markdown/08-change-explanation.md` and `markdown/09-final-audit.md`;
- `json/08-semantic.json`, `json/09-ontology.json`, `data/graph.jsonl`, and the final flow;
- `data/source-to-target.csv` using `core.source-target.v2`;
- `json/11-audit.json` and the strict `core.seal.v2` manifest.

The v2 source-to-target contract records source section ID/title, target template section
ID/heading, source span IDs, disposition, and final digest. The sealed-bundle loader validates that
map. RAG catalog v2 uses it before label fallback, so a rewritten target heading still links to the
correct source graph node while unmatched and ambiguous links remain visible in catalog metrics.

## Bounded PDF visual support

The PDF parser extracts direct embedded image XObjects only when all of these checks pass:

- at most 16 promoted images per PDF;
- at most 4 MiB compressed/decoded bytes per image;
- at most 16 million pixels and 8,192 pixels on either dimension;
- decoded bytes have a supported PNG or JPEG signature.

Every promoted image receives page, occurrence, source-span, digest, and media-type provenance and
then follows the same `FIG-###` human-review/appendix path as DOCX and local Markdown images.
Unsupported or over-budget images remain inventoried with warnings. Scanned or image-only PDFs
remain fail-closed; there is no OCR and no whole-page rasterization.

## Verifiable completion rewards

| ID | Reward | Required evidence | Status |
| --- | --- | --- | --- |
| F1 | Rewritten headings retain graph linkage | v2 source-target unit/integration test proves explicit source ID linkage and graph expansion | Complete |
| F2 | PDF embedded screenshots reach final artifacts safely | parser budget tests plus PDF Stage 1/Stage 2 appendix and DOCX-media E2E; rendered fixture visually checked | Complete |
| F3 | Live provider path works end to end | fictional fixture reaches Stage 1, source-supported decision, passing final audit, and strict seal | Complete: run `a5af52fe075d-b1429e75a0` |
| F4 | Provider variance fails closed | generated template placeholders and unsupported mapping changes are rejected by deterministic tests | Complete |
| F5 | Current documentation is synchronized | `plan.md`, `AGENTS.md`, `README.md`, evidence ledger, and follow-up ledger describe the shipped contracts | Complete |
| F6 | Repository is release-ready | literal integration gate passes; implementation is committed, fast-forwarded to `main`, and pushed | Complete |

## Release gate

Run literally from the integrated checkout:

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -m "not live_model and not public_download"
uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core
uv build
```

The release closes only after the gate passes, the branch is fast-forwarded into `main`, the remote
ancestry is verified, completed task/worktree state is archived or removed safely, and
`FOLLOW_UP.md` contains every remaining non-blocking item.

## Deliberate non-goals

- OCR, whole-page PDF rasterization, and promotion of unsupported image encodings.
- Retrieval, shared chat, managed vector databases, or graph databases on the authoring path.
- Autonomous business decisions, inferred owners/dates/thresholds/approvals, or model-created graph
  truth.
- Deep Agents, subagent loops, or unbounded tool access for the fixed five-phase workflow.

## Open work

No product or release follow-up is open after F1 through F6. Any later finding must be classified
against the acceptance boundary and either demonstrated as a blocker or added as one scoped entry
to `FOLLOW_UP.md`.
