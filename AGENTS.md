# Document Enhancer agent guidance

## Mission

Deliver `plan.md` through verified milestone completion. Optimize for forward progress on the
critical path while preserving correctness, security, traceability, and the explicit acceptance
criteria. Do not let optional hardening prevent the next milestone from starting.

## Progress-first orchestration

- Keep one critical-path milestone as the primary work in progress.
- Limit parallel write-heavy lanes to work with genuinely independent ownership boundaries.
- Complete, integrate, and formally close the current milestone before expanding into optional
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

- A required test, release gate, or milestone acceptance criterion fails.
- Required behavior in `plan.md` is missing or incorrect.
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

Run opt-in live-provider or public-download checks only when the milestone requires them and the
required credentials or network policy are explicitly available.

## Milestone closure

After a milestone passes its acceptance criteria, the integrator must:

1. Merge the verified implementation.
2. Update `plan.md` with evidence-backed task status.
3. Update `README.md` when the supported product surface or user workflow changed.
4. Record remaining non-blocking work in `FOLLOW_UP.md`.
5. Archive or close completed threads and remove completed worktrees when safe.
6. Push the integrated branch when a remote is configured and pushing is in scope.
7. Begin the next unblocked critical-path milestone immediately.

Workers should not edit `plan.md`, the root `README.md`, shared configuration, or another lane's
files unless their task explicitly grants that ownership. They must return the evidence the
integrator needs to close the milestone.

## Status reporting

Every orchestration update should state:

- Current milestone and task IDs.
- The single current blocker, or `none`.
- The exact next implementation or integration action.
- Verification completed since the prior update.
- Non-blocking findings deferred to `FOLLOW_UP.md`.

Do not describe dormant, merged, idle, or unloaded worktrees as active implementation.
