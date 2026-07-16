# M5 workflow and CLI contract

The M5 workflow is local-first and resumable. A run keeps immutable source and analysis artifacts
under `.document-enhancer/runs/<run_id>/` (or the configured `--run-dir`) and writes the current
workflow snapshot to `workflow-state.json`. The snapshot contains digests, stage state, and safe
metadata; it does not contain credentials.

## Stages and routes

The compiled LangGraph state machine uses these deterministic stage names:

```text
raw_ingest -> normalize -> structure_quality -> structure_scan
  -> structure_recovery (only when M3 routing requires it)
  -> structure_validate -> selected_view -> analysis
  -> question_synthesis -> gate1 -> checklist -> gate2 -> complete
```

M3 owns parser normalization and structure recovery. M4 owns the injected analysis runner. M5
does not replace either port. In offline mode the CLI selects parser structure and produces no
model-derived findings; a configured model gateway and analysis runner can be injected by an
application integration.

## Human gates

Gate 1 is required when a blocking question exists, or when `run --until questions` is used. The
run exits with code `10` (`WAITING_FOR_REVIEW`) after writing:

```text
clarification/questions.yaml
clarification/questions.md
clarification/answers.yaml
clarification/steering.yaml
clarification/waivers.yaml
clarification/validation-report.json
```

Questions are authoritative YAML. Markdown is a deterministic reading surface. Answers must use
an existing question ID. An answered question requires reviewer identity and a source span or
explicit `answer://`, `reference://`, `source://`, or `steering://` provenance reference. A
waived question requires a matching waiver with an approver, reason, impact, and review/expiry
date. No answer is inferred from a blank field.

Gate 2 is enabled by default. It pauses when the rewrite checklist has items. `--until checklist`
also creates a one-shot pause at Gate 2, including for an empty checklist. A reviewer resumes
only after setting both `approved_by` and `approved_at` in `clarification/rewrite-checklist.yaml`
and resolving or waiving every blocking item. `--no-gate2` is an explicit local/debug policy.

## Commands and stable output

```bash
docenhance run source.md --until questions
docenhance status RUN_ID --json
docenhance current-stage RUN_ID --json
docenhance next-action RUN_ID --json
docenhance resume RUN_ID --json
```

Human-readable output goes to stdout. `--json` emits a stable object with `schema_version`,
`run_id`, `status`, `current_stage`, `next_action`, `completed_stages`, `cache_keys`, `errors`,
and `exit_code`. JSON output contains no ANSI sequences.

The waiting exit code is deliberately non-zero so shell automation cannot mistake a paused run
for a completed enhancement. `resume` checks that the source digest still matches before
validating edited reviewer files. Invalid reviewer files remain fail-closed and produce
actionable paths/diagnostics; no model stage runs while reviewer validation is invalid.

## Idempotence and cache invalidation

Every transition saves a durable snapshot and a SQLite checkpoint. Artifact writes use atomic
promotion, and the side-effect receipt table makes identical effects no-ops when a LangGraph
interrupt re-executes a node. Completed upstream stages are represented in the snapshot and are
not replayed by `resume`.

The cache proof API (`document_enhancer.workflow.WorkflowCache`) covers a single changed source,
answer, steering, waiver, template, reference file, prompt, or schema. Source changes invalidate
the entire pipeline. Reviewer-input changes invalidate gate 1 and downstream checklist/gate
stages, while unchanged ingest, structure, analysis, and question keys remain reusable. Prompt,
schema, template, and reference changes invalidate the first dependent stage and every downstream
stage through the explicit dependency graph.

## Prompt-pack inspection

```bash
docenhance prompts list --json
docenhance prompts show clarification.questions --json
docenhance prompts show clarification.questions --composed --json
docenhance prompts validate --json
```

Prompt IDs resolve only through the selected versioned pack. Composition uses visible boundaries
for governed instructions, governed context, untrusted source data, reviewer inputs, and the
schema-only output contract. Resolved run artifacts retain template, fragment, reference,
variable, schema, and rendered-prompt digests; raw credentials and sensitive input bodies are
redacted or represented by size/digest metadata.
