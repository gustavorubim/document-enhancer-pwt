# Document Enhancer agent guidance

## Product objective

Build a file-backed document enhancement workflow that turns one dropped source into a
reviewed, steered, rewritten, audited, and graph-ready document bundle.

The intended operator journey is:

1. Drop one `.md`, `.txt`, `.docx`, or `.pdf` into an inbox folder (or pass the file) and trigger a
   run.
2. Parse the document with heuristics and, when needed, bounded LLM structure recovery. Produce a
   canonical breakup: ordered spans, sections, quality signals, and warnings.
3. Run a macro analysis against the selected recipe rubric and produce a clear macro report.
4. Run section-by-section analysis against the rubric and produce a section report that states, for
   each section, what is correct, what is missing, and what should be improved.
5. Run process-flow analysis when a process is being documented. Produce a flow report with:
   - the inferred process as Mermaid
   - the proposed/corrected process as Mermaid
   - what is incorrect, missing, or ambiguous in the documented flow
6. During Stage 1, map all source spans to the selected template and write an unapproved candidate
   in clear English using only source-supported content. Preserve missing, ambiguous, conflicting,
   or unreadable content as typed gaps and visible review callouts; never copy template-only
   placeholders into generated prose.
7. Separate genuine questions, ambiguities, safe context-aware suggestions, and steering decisions
   into one editable `review/decisions.yaml` for the human.
8. After decisions are answered, revise the exact candidate from approved decisions and source
   evidence without rerunning or silently changing the frozen Stage 1 mapping.
9. Deliver the final document, audit, and change explanation. Seal only when deterministic checks
   pass.
10. Emit portable semantic/graph/ontology-ready exports so a later GraphRAG, RAG, or ontology system
   can consume the bundle. Retrieval services are consumers of sealed outputs, not part of the
   authoring critical path.

Engineering simplification is in service of this workflow: one five-phase runner, one decision
gate, one recipe/reference pack, compact `run.json` state, and no legacy graph/checkpoint/RAG
runtime on the authoring path. Do not reintroduce platform machinery that does not advance the
operator journey above.

The current architecture, completed rewards, and release gate live in `plan.md`. The frozen
draft-first implementation contract remains in `DRAFT_FIRST_IMPLEMENTATION_PLAN.md`, its evidence
ledger is `DRAFT_FIRST_IMPLEMENTATION_EVIDENCE.md`, and current implementation details live in
`README.md`. Residual product and quality work lives only in `FOLLOW_UP.md`.

## Mission

Deliver the product objective through verified increments. Optimize for forward progress on the
critical path while preserving correctness, security, traceability, provenance, and no-invention
gates. Do not let optional hardening prevent the next workflow-quality milestone from starting.

## Progress-first orchestration

- Keep one critical-path workflow gap as the primary work in progress.
- Limit parallel write-heavy lanes to work with genuinely independent ownership boundaries.
- Complete, integrate, and formally close the current increment before expanding into optional
  hardening or unrelated follow-on work.
- Do not interrupt an implementation worker with non-blocking review comments. Collect those
  comments and perform one bounded review after the worker produces a coherent commit.
- Default to one implementation pass and one bounded correction pass per lane. Further findings
  must be classified explicitly as blocking or deferred.
- Reopen a merged lane only for a demonstrated blocker or regression.
- When a safe, relevant next implementation step exists, take it instead of remaining in polling,
  review, or status-reporting mode.

## Finding classification

A finding blocks progress only when it demonstrates at least one of the following:

- A required test, release gate, or product-objective acceptance criterion fails.
- Required workflow behavior above is missing or incorrect.
- Data can be lost, silently changed, invented, corrupted, or promoted without validation.
- A security, privacy, credential, provenance, or tool-boundary requirement is violated.
- A public or shared contract is incompatible with its required consumer.

Naming improvements, refactoring, speculative safeguards, additional edge cases, optional
documentation, broader portability, and polish are non-blocking unless they satisfy a condition
above. Record non-blocking findings in `FOLLOW_UP.md` and continue on the critical path. Create the
file if needed, and keep each entry scoped and actionable.

## Review and verification cadence

- During implementation, run owned or focused tests plus relevant formatting, lint, and type
  checks.
- Run the complete repository gate once before lane handoff and once after integration. Do not
  rerun the entire gate after every micro-edit unless a shared contract or root dependency changed.
- A worker self-review plus one integrator review is the normal review budget.
- If a second correction pass still reveals a genuine blocker, isolate that blocker, fix it, and
  avoid expanding the correction into adjacent optional work.
- Never weaken a required test, validation rule, or acceptance criterion merely to advance.

The integration gate is:

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -m "not live_model and not public_download"
uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core
uv build
```

Prefer `PYTHONPATH=src` when diagnosing install/import issues. Recreate `.venv` if the editable
install is polluted. Run opt-in live-provider checks only when the increment requires them and
credentials are explicitly available.

## README maintenance

- Update `README.md` after every completed implementation task before declaring the task closed.
- Keep the README synchronized with the implementation, including supported commands, operator
  workflow, phase transitions, artifact paths, module ownership, model/agent boundaries, and
  safety or retrieval boundaries.
- When control flow, module responsibilities, provider behavior, agent tools, or the run/catalog
  lifecycle changes, update the corresponding Mermaid diagram in the same task.
- Verify edited Mermaid blocks and local README links as part of task verification. Do not leave a
  diagram that describes a planned or historical architecture as if it were the current code.
- Workers that do not own the root `README.md` must return the exact documentation delta and
  implementation evidence to the integrator; the integrator owns applying it before closure.

## Increment closure

After an increment passes its acceptance criteria, the integrator must:

1. Merge the verified implementation.
2. Update `plan.md` with evidence-backed status when the contract or release state changed; do not
   rewrite the frozen historical implementation plan.
3. Update `README.md` for the completed implementation, including any affected diagrams. README
   synchronization is mandatory, not conditional on whether the public command surface changed.
4. Update `DRAFT_FIRST_IMPLEMENTATION_EVIDENCE.md` with the checks actually exercised and record
   every remaining non-blocking item in `FOLLOW_UP.md`.
5. Archive or close completed threads and remove completed worktrees when safe.
6. Push the integrated branch when a remote is configured and pushing is in scope.
7. Begin the next unblocked critical-path workflow gap immediately.

Workers should not edit shared plans, the root `README.md`, shared configuration, or another lane's
files unless their task explicitly grants that ownership. They must return the evidence the
integrator needs to close the increment.

## Status reporting

Every orchestration update should state:

- Current workflow gap or task IDs.
- The single current blocker, or `none`.
- The exact next implementation or integration action.
- Verification completed since the prior update.
- Non-blocking findings deferred to `FOLLOW_UP.md`.

Do not describe dormant, merged, idle, or unloaded worktrees as active implementation.
