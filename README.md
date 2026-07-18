# Document Enhancer

Turn one governed source document into a reviewed, rewritten, audited, and graph-ready document
bundle. Drop a file, run Stage 1, answer business questions in a single YAML file, then run Stage 2
to a sealed final package.

The product is intentionally file-backed and linear: no workflow engine, database checkpoint,
retrieval system, prompt-pack runtime, or compatibility mode is required on the authoring path.

## Operator journey

1. Drop one `.md`, `.txt`, `.docx`, or `.pdf` into an inbox (or pass the file path).
2. Parse with heuristics and optional bounded LLM structure recovery.
3. Open `report.html` and read the numbered macro, section, and process-flow reports in order.
4. Compare the inferred and proposed Mermaid diagrams when a process is documented.
5. Answer questions and steering in `review/decisions.yaml`.
6. Continue so the runner rewrites, audits, and seals the bundle.
7. Use the portable semantic, ontology, and graph exports later for GraphRAG, RAG, or ontology.

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

When waiting, open the run directory printed by the CLI. Start with `report.html`, which renders
all currently available Markdown reports in one styled, navigable page and renders the Mermaid
process diagrams as embedded SVG without an external web dependency. The same reports remain
available as portable Markdown files:

```text
report.html                              # pastel tabbed reviewer for every report
markdown/01-source-normalized.md         # exact parsed evidence used by the run
markdown/02-review-overview.md           # reading order and readiness snapshot
markdown/03-macro-review.md              # document-level rubric report
markdown/04-section-review.md            # correct / missing / improve with rationale
markdown/05-process-flow-review.md       # inferred + proposed Mermaid and reasoning
markdown/06-review-questions.md          # every question, rationale, and safe suggestion
diagrams/01-inferred-flow.mmd            # standalone inferred diagram
diagrams/02-proposed-flow.mmd            # standalone proposed diagram
review/decisions.yaml                    # only file the reviewer edits
```

`05-process-flow-review.md` is the human-readable flow report: both Mermaid diagrams are embedded as fenced
`mermaid` blocks, followed by a section explaining why the proposed diagram differs from the
inferred source diagram.

Edit only the allowed response fields in `review/decisions.yaml`: choose each disposition, fill an
answer when using `accept`, add optional rationale / steering / waivers, and set
`approve_rewrite: true`. Then run the complete narrated Stage 2 workflow:

```bash
uv run docenhance stage-two RUN_ID
```

The single command continues the reviewed run, inspects the resulting bundle, and presents every
final audit check using a Rich terminal interface. The individual `continue`, `inspect`, and
`audit` commands remain available for automation and focused troubleshooting.

### Cookbook example

The checked-in Aurora AI complaint triage process is a complete two-stage example. It intentionally
contains contradictory operating details so the workflow must stop for human decisions instead of
silently inventing an answer.

#### Stage 1: generate and review the analysis

```bash
uv run docenhance run examples/cookbook/aurora_ai_complaint_triage_process.docx \
  --document-type process \
  --execution-mode live \
  --until questions
```

Exit code `10` is expected. Copy the printed `RUN_ID`; runs are written under
`.document-enhancer/runs/<RUN_ID>/`. Open the accompanying reviewer:

```text
.document-enhancer/runs/<RUN_ID>/report.html
```

Read reports `01` through `06` in order. The HTML navigation, readiness cards, rendered Markdown,
and Mermaid diagrams present the same evidence stored under `markdown/` and `diagrams/`.

#### Human gate: answer and save the decisions

Open `.document-enhancer/runs/<RUN_ID>/review/decisions.yaml`. For every blocking question, replace
the empty answer with the accountable owner's answer and choose a disposition:

```yaml
approve_rewrite: true
steering: "Keep the final process concise and make every control owner explicit."
waivers: []
decisions:
  - question_id: question-example
    question: "Which P1 acknowledgement target should govern the final process?"
    suggestion: "Use one owner-approved target consistently in the procedure and controls."
    answer: "Use the documented 30-minute P1 acknowledgement target."
    disposition: accept
    rationale: "The control register is the authoritative source."
```

Use `accept` to apply the text in `answer`; use `accept_suggestion` to apply the generated suggestion
without writing a separate answer; use `reject` to resolve the question without applying either;
and use `defer` to keep the run paused. Not every question has a safe suggestion. Do not change the
question ID, question text, or suggestion—the runner validates these against the review artifact.
Save the YAML before continuing.

#### Stage 2: rewrite, verify, and seal the same run

```bash
uv run docenhance stage-two RUN_ID
```

The terminal explains each step while it validates decisions, rewrites, exports, inspects, and
audits the bundle. Reopen the same `report.html`; it is regenerated with reports `07` through `09`:
the final
document, detailed change explanation, and expanded final audit. A successful run reports
`succeeded`, passes the audit, and writes `json/12-seal.json`.

For a deterministic local demonstration without provider enrichment, replace `live` with
`offline`; the same two-stage artifact and decision contracts apply.

The project `uv` configuration installs the live-provider dependency group by default, so the
cookbook command above works after the normal `uv sync --frozen`. If you install the published
package instead of using this checkout, install `document-enhancer[live]` before selecting live
mode.

If a local macOS environment was created by an older checkout and Python reports that it cannot
import `document_enhancer`, refresh it with `uv sync --frozen --reinstall-package
document-enhancer`. As a temporary source-tree diagnostic, the equivalent Stage 1 command is:

```bash
PYTHONPATH=src uv run docenhance run examples/cookbook/aurora_ai_complaint_triage_process.docx \
  --document-type process \
  --execution-mode live \
  --until questions
```

`PYTHONPATH` is not required for the supported workflow; the example is only a troubleshooting
fallback for an already-corrupted local environment.

## Execution modes

- `--execution-mode offline` (default): fully deterministic local parse/review/rewrite/audit.
- `--structure-mode auto` (default): heuristics may request bounded LLM structure recovery in live mode.
- `--execution-mode live`: optional Gemini enrichment. The checkout installs the live dependency
  group by default; set credentials in `.env` or the environment, then pass `--execution-mode live`.

Only these `.env` keys are loaded: `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_CLOUD_PROJECT`,
`GOOGLE_CLOUD_LOCATION`, `DOCENHANCE_BACKEND`.

## What a run produces

```text
runs/RUN_ID/
├── report.html                 # pastel tabbed rendering of all Markdown reports
├── json/                       # 00-run.json through 12-seal.json; every JSON artifact
├── markdown/                   # 01 source through 09 final audit; numbered reading order
├── review/decisions.yaml       # questions, steering, waivers, approve_rewrite
├── diagrams/                   # numbered inferred, proposed, and final Mermaid sources
├── documents/                  # original source and styled DOCX with native headings/tables
├── data/                       # graph.jsonl and source-to-target.csv
└── debug/                      # optional provider call manifests in JSONL
```

The five phases are extract, analyze, human review, rewrite, and verify. Large values live in named
artifacts; `json/00-run.json` remains below 50 KB and records the selected execution mode so a live run
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
  runtime is required on the authoring path.

## Optional local RAG and GraphRAG CLI

Install the optional retrieval dependencies, finish and seal the documents you want to query, then
build an explicit local catalog:

```bash
uv sync --frozen

# The listed runs replace the current catalog. Only passing, sealed bundles are accepted.
uv run docenhance rag index RUN_ID_1 RUN_ID_2

# Deliberately select every passing sealed run under the configured run directory instead.
uv run docenhance rag index --all-sealed

uv run docenhance rag inspect
uv run docenhance rag ask "Who owns the control and how often is it reviewed?" --show-trace
uv run docenhance rag ask \
  "List every control with a reconciliation step across all documents" \
  --coverage exhaustive --show-trace
uv run docenhance rag chat
```

Published-package users install `document-enhancer[rag]`. Indexing uses Gemini Embeddings 2 by
default and reads the same recognized, ignored `.env` credentials as live authoring. The explicit
`--offline` indexing option uses deterministic feature-hash vectors only for tests and local CLI
demonstrations; it is not a semantic embedding profile. Live indexing sends only canonical final
chunks to the configured provider and may incur embedding charges; each `ask` or chat turn also
uses the configured chat model.

The RAG catalog is written under `.document-enhancer/rag/catalog/` unless `--catalog` or
`DOCENHANCE_RAG_CATALOG` selects another path. A build stages and validates the SQLite FTS5 catalog,
FAISS index, graph topology, row counts, embedding profile, and SHA-256 file digests before replacing
the prior catalog. A failed or tampered input leaves the promoted catalog unchanged.

Corpus selection is intentionally conservative:

- only explicitly named runs are indexed unless `--all-sealed` is supplied;
- only the approved `markdown/07-final-document.md` is embedded;
- original sources, review reports, decisions, audits, and change explanations are not embedded;
- `json/09-ontology.json` is loaded as namespaced graph nodes and edges rather than embedded as text;
- every answer source displays its run ID, heading path, and stable chunk ID.

`rag ask` and `rag chat` use hybrid FAISS/FTS retrieval and may search again when evidence points to
another indexed document. They can also traverse one or two real `core.graph.v1` edges. The agent has
only two read-only retrieval tools—no web, shell, arbitrary filesystem, authoring, or write tools.
Visible claims must cite evidence actually retrieved for that question; unknown or missing citations,
conflicting evidence, and absent evidence produce `insufficient` instead of an invented answer.

Question routing stays deliberately small. Focused questions use the bounded multi-hop agent. Questions
that explicitly say `all documents`, `each document`, `across the corpus`, or similar language use a
question-driven corpus map: the model extracts only the requested facts from each selected document,
then one bounded reducer removes cross-batch category mismatches and paraphrases using only those
cited candidates. Deterministic code validates citations before and after reduction. `--scope
focused|corpus` overrides automatic routing. Corpus mode has two coverage levels:

- `--coverage retrieval` searches each selected document independently, which is efficient but does not
  prove that every chunk was examined;
- `--coverage exhaustive` reads every chunk in every selected document, reports exact document/chunk
  coverage and failures, and is the right mode for completeness-sensitive lists and comparisons. It can
  require several model calls and cost more on large catalogs.

The extraction schema is derived from each question rather than fixed to controls, so the same path can
list owners, compare thresholds, collect exceptions, or extract other document-specific facts. Every row
keeps its supporting run and chunk citations. Use repeated `--run RUN_ID` options to restrict either mode
to explicit document versions.

Rich chat is in-memory and bounded. `/sources`, `/trace`, `/clear`, `/help`, and `/exit` are supported;
no session, hidden reasoning, or conversation is persisted. FAISS files are trusted only as generated
local workspace artifacts whose paths and hashes match the catalog manifest. Rebuild the whole small
catalog when the selected sealed corpus or embedding profile changes.

## Supported commands

```text
docenhance version
docenhance run SOURCE [--document-type TYPE] [--structure-mode auto|parser|off] [--execution-mode offline|live]
docenhance watch-inbox [INBOX]
docenhance continue RUN_ID
docenhance stage-two RUN_ID
docenhance status RUN_ID
docenhance inspect RUN_ID
docenhance audit RUN_ID
docenhance rag index RUN_ID... [--all-sealed]
docenhance rag inspect [--json]
docenhance rag ask "QUESTION" [--run RUN_ID] [--scope auto|focused|corpus] [--coverage retrieval|exhaustive] [--show-trace] [--json]
docenhance rag chat [--run RUN_ID] [--scope auto|focused|corpus] [--coverage retrieval|exhaustive] [--show-trace]
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

Active product objective and engineering guidance: `AGENTS.md`.
