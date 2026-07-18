# Document Enhancer

Turn one governed source document into a reviewed, rewritten, audited, and graph-ready document
bundle. Drop a file, run one command, answer business questions in a single YAML file, then continue
to a sealed final package.

The product is intentionally file-backed and linear: no workflow engine, database checkpoint,
retrieval system, prompt-pack runtime, or compatibility mode is required on the authoring path.

## Operator journey

1. Drop one `.md`, `.txt`, `.docx`, or `.pdf` into an inbox (or pass the file path).
2. Parse with heuristics and optional bounded LLM structure recovery.
3. Read the macro report (document vs rubric).
4. Read the section report (`correct` / `missing` / `improve` per section).
5. Read the process-flow report with inferred and proposed Mermaid when a process is documented.
6. Answer questions and steering in `review/decisions.yaml`.
7. Continue so the runner rewrites, audits, and seals the bundle.
8. Use portable `semantic.json` / `ontology.json` / `graph.jsonl` later for GraphRAG, RAG, or ontology.

## Quick start

```bash
uv sync --frozen

# File path, or a directory containing exactly one supported source.
uv run docenhance run .document-enhancer/inbox/aurora-ai-complaint-triage.docx --document-type process

# Or the thin inbox wrapper (directory must contain exactly one document):
uv run docenhance watch-inbox
```

Exit code `10` means the run is waiting for human decisions. Exit code `0` means it finished;
non-zero other than `10` means failure.

When waiting, open the run directory printed by the CLI and review:

```text
review/macro.md              # verbose document-level rubric report
review/sections.md           # correct / missing / improve with rationale
review/flow.md               # inferred + proposed Mermaid embedded, plus adjustment reasoning
review/flow.inferred.mmd     # standalone inferred diagram
review/flow.proposed.mmd     # standalone proposed diagram
review/decisions.yaml
```

`flow.md` is the human-readable flow report: both Mermaid diagrams are embedded as fenced
`mermaid` blocks, followed by a section explaining why the proposed diagram differs from the
inferred source diagram.

Edit only `review/decisions.yaml`: fill answers, optional `steering` / `waivers`, and keep
`approve_rewrite: true`. Then continue the exact run:

```bash
uv run docenhance continue RUN_ID
uv run docenhance inspect RUN_ID
uv run docenhance audit RUN_ID
```

### Cookbook example

The checked-in Aurora AI complaint triage process is a good end-to-end review sample:

```bash
uv run docenhance run examples/cookbook/aurora_ai_complaint_triage_process.docx \
  --document-type process \
  --execution-mode offline
```

Runs are written under `.document-enhancer/runs/<RUN_ID>/`.

## Execution modes

- `--execution-mode offline` (default): fully deterministic local parse/review/rewrite/audit.
- `--structure-mode auto` (default): heuristics may request bounded LLM structure recovery in live mode.
- `--execution-mode live`: optional Gemini enrichment. Run `uv sync --group live`, set credentials in
  `.env` or the environment, then pass `--execution-mode live`.

Only these `.env` keys are loaded: `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_CLOUD_PROJECT`,
`GOOGLE_CLOUD_LOCATION`, `DOCENHANCE_BACKEND`.

## What a run produces

```text
runs/RUN_ID/
├── run.json                    # compact, sole mutable run state
├── source/                     # original bytes, normalized text, spans, parser quality
├── recipe/compiled.json        # validated policy, rubric, and template fingerprint
├── review/
│   ├── review.md               # index of specialist reports
│   ├── macro.md                # document-level rubric report
│   ├── sections.md             # correct / missing / improve per section
│   ├── flow.md                 # process-flow critique
│   ├── flow.inferred.mmd       # inferred process
│   ├── flow.proposed.mmd       # proposed/corrected process
│   └── decisions.yaml          # questions, steering, waivers, approve_rewrite
├── rewrite/plan.json           # source-backed approved rewrite plan
├── output/                     # final.md, final.docx, semantic.json, ontology.json, graph.jsonl
└── audit/                      # audit, change explanation, source-to-target map, optional seal
```

The five phases are extract, analyze, human review, rewrite, and verify. Large values live in named
artifacts; `run.json` remains below 50 KB and records the selected execution mode so a live run
continues live after human review.

## Quality boundaries

- Parsers preserve source bytes, block order, locations, stable span IDs, warnings, and digests.
- Heuristics choose parser structure or bounded LLM structure recovery; providers cannot invent
  source spans or replace deterministic evidence checks.
- Reference packs define the document type, policy context, rubric, terminology, and templates.
- The single decision file holds genuine business questions plus steering/waivers/approval.
- Final auditing checks source retention, required sections, graph references, unresolved blockers,
  section assessments, and dual flow artifacts before sealing an approved bundle.
- Semantic JSON and JSONL graph exports are portable for a future RAG/ontology consumer; no retrieval
  runtime ships on the authoring path.

## Supported commands

```text
docenhance version
docenhance run SOURCE [--document-type TYPE] [--structure-mode auto|parser|off] [--execution-mode offline|live]
docenhance watch-inbox [INBOX]
docenhance continue RUN_ID
docenhance status RUN_ID
docenhance inspect RUN_ID
docenhance audit RUN_ID
docenhance validate-recipe [--document-type TYPE]
```

Supported document types are `process`, `methodology`, `standard`, and `desktop_procedure`.
The checked-in `reference_packs/enterprise_core` pack is the default.

## Development gate

```bash
scripts/gate_core.sh
uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core
uv build
```

Active product objective: `AGENTS.md`. Architecture: `SIMPLIFICATION_PLAN.md`. Workflow quality
status: `WORKFLOW_ENHANCEMENT_PLAN.md`.
