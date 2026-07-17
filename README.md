# Document Enhancer

Turn one governed source document into a reviewed, rewritten, audited, and graph-ready document
bundle. The product is intentionally file-backed and linear: no workflow engine, database
checkpoint, retrieval system, prompt-pack runtime, or compatibility mode is required.

## Quick start

```bash
uv sync --frozen

# A file, or a directory containing exactly one .md, .txt, .docx, or .pdf source.
uv run docenhance run .document-enhancer/inbox --document-type process
```

The command writes one unique run under `.document-enhancer/runs` and either finishes or exits with
code `10` when business decisions are needed. Read `review/review.md`, answer only the questions in
`review/decisions.yaml`, then continue the exact run:

```bash
uv run docenhance continue RUN_ID
uv run docenhance inspect RUN_ID
uv run docenhance audit RUN_ID
```

Use `--execution-mode offline` for deterministic local operation (the default). For bounded Gemini
enrichment, first run `uv sync --group live`, set provider credentials in `.env` or the environment,
and use `--execution-mode live`. Only `GOOGLE_API_KEY`, `GEMINI_API_KEY`,
`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, and `DOCENHANCE_BACKEND` are read from `.env`.

## What a run produces

```text
runs/RUN_ID/
├── run.json                    # compact, sole mutable run state
├── source/                     # original bytes, normalized text, spans, parser quality
├── recipe/compiled.json        # validated policy, rubric, and template fingerprint
├── review/                     # macro/section/flow review, Mermaid, questions, decisions
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
- The single decision file holds only genuine business questions. Unknown values remain explicit.
- Final auditing checks source retention, required sections, graph references, unresolved blockers,
  and template coverage before sealing an approved bundle.
- The semantic JSON and JSONL graph are portable outputs for a future RAG, ontology, or search
  system; no retrieval runtime ships in this repository.

## Supported commands

```text
docenhance version
docenhance run SOURCE [--document-type TYPE] [--execution-mode offline|live]
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

The focused gate covers parser behavior, all four document types, the human decision pause,
rewrite/audit artifacts, semantic exports, live-provider seams, and CLI behavior.
