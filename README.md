# Document Enhancer

Document Enhancer is a local-first, Gemini-first Python CLI for turning enterprise methodology, standard, process, and desktop-procedure documents into traceable human, semantic, and retrieval-ready artifacts.

The repository now includes the foundational contracts, governed reference and prompt packs,
source ingestion and structure recovery, the Gemini model gateway, four parallel analysis
specialists, deterministic clarification artifacts, a durable two-gate LangGraph workflow, and a
governed rewrite pipeline that derives Markdown, Mermaid, and semantic outputs from one validated
intermediate model. The audited export pipeline now builds and promotes a validated local SQLite
catalog, and the Rich CLI performs explainable retrieval and grounded cited Q&A over that catalog.

## Verified status

M0–M8 and the repository-level Definition of Done are verified as of 2026-07-16. The complete
post-integration offline gate passed on governed-workflow merge `2b46d21`: 268 tests passed and 2
explicit opt-in tests were deselected; frozen sync, import smoke, Ruff format/check, ty, generated
schemas, both governed packs, all 60 generated corpus files, both evaluation artifacts, package
build, and diff checks also passed. All 21 deterministic offline release thresholds passed across
48 fixture-format evaluations. A separate temporary clean-clone and isolated-wheel proof passed at
`5b763b8`.

The actual two-gate CLI workflow also completed for the checked-in `enterprise_core` process,
methodology, standard, and desktop-procedure examples. Every run passed strict audit, built a valid
sealed SQLite RAG package, promoted the cumulative catalog, returned explainable retrieval results,
and produced a grounded cited answer. The companion negative case proves that incomplete governed
input still fails closed without promoting RAG state. See the
[operator guide](docs/operator-guide.md), [release proof](docs/release.md), and
[evaluation report](evals/reports/m8-evaluation.md) for exact workflows and limitations. These are
controlled offline results, not claims about live Gemini quality or public-source generalization;
all governed proof runs recorded zero Gemini calls and zero public downloads, and live-model and
public-download evaluations remain explicit opt-in checks that were not run.

## Quick start

```bash
uv sync --frozen
uv run docenhance --help
uv run docenhance doctor
```

The project requires Python 3.12 or 3.13 and uses `uv` for a reproducible environment. Provider
credentials are never accepted as CLI arguments or committed configuration. The CLI does not
automatically load `.env`; export the selected provider credential into the process environment
before a live run.

## Cookbook: enhance a document

This section follows one document from local source file through the two human-review gates, final
audit/export, and optional retrieval. Run the commands from the repository root.

### 1. Install and check the local environment

```bash
uv sync --frozen
uv run docenhance version
uv run docenhance doctor --json
uv run docenhance prompts validate --json
```

The CLI accepts Markdown (`.md`), plain text (`.txt`), Word (`.docx`), and text-based PDF (`.pdf`)
sources. Scanned or image-only PDFs require OCR before they can be used.

### 2. Put the source document in the local inbox

The CLI accepts a source from any readable path. The recommended repository-local convention is
`.document-enhancer/inbox/`:

```bash
mkdir -p .document-enhancer/inbox
cp "/absolute/path/to/Current Methodology.docx" \
  ".document-enhancer/inbox/current-methodology.docx"
```

The entire `.document-enhancer/` directory is ignored by Git. This keeps confidential inputs,
review artifacts, generated outputs, and the optional RAG catalog out of commits by default:

```text
.document-enhancer/
├── inbox/                         # source files supplied by the operator
├── runs/<RUN_ID>/                 # isolated evidence and output for each run
└── rag/catalog.sqlite3            # optional cumulative retrieval catalog
```

Keep the original source unchanged while a run is active. The workflow copies it into the run,
records its digest, and refuses to resume against incompatible source or configuration state.

### 3. Choose the document type and execution mode

Use the document type that describes the intended governed output:

| `--document-type` | Use it for |
| --- | --- |
| `process` | Roles, activities, decisions, handoffs, controls, and evidence flows |
| `methodology` | Models, calculations, assumptions, data, validation, and limitations |
| `standard` | Mandatory requirements, exceptions, ownership, and compliance evidence |
| `desktop_procedure` | Step-by-step operating instructions and escalation paths |

Use `--execution-mode offline` for a deterministic, network-free workflow test. It validates the
local orchestration and artifacts but does not measure Gemini quality. The normal live mode is the
default and can send document content to the configured Gemini backend.

For the Developer API, export the credential into the process environment before a live run:

```bash
export DOCENHANCE_BACKEND=developer_api
export GEMINI_API_KEY='set-outside-the-repository'
```

The CLI does not accept credentials as arguments or configuration-file values and does not
automatically load `.env`. Vertex AI operators should use Application Default Credentials and the
project/location settings described in the [operator guide](docs/operator-guide.md).

### 4. Start the run and save the run ID

This live example always pauses at Gate 1 so the intermediate extraction and questions can be
reviewed before rewriting:

```bash
uv run docenhance run \
  ".document-enhancer/inbox/current-methodology.docx" \
  --document-type methodology \
  --until questions \
  --json
```

For a network-free first pass, add `--execution-mode offline`:

```bash
uv run docenhance run \
  ".document-enhancer/inbox/current-methodology.docx" \
  --document-type methodology \
  --execution-mode offline \
  --until questions \
  --json
```

The response contains a value such as `"run_id": "run-abc123..."`. Save it for later commands:

```bash
RUN_ID=run-abc123
RUN_PATH=".document-enhancer/runs/$RUN_ID"
```

A waiting workflow exits with code `10` by design. This is a successful review pause, not a crash.
At any point, inspect the persisted state and the next required action with:

```bash
uv run docenhance status "$RUN_ID" --json
uv run docenhance current-stage "$RUN_ID"
uv run docenhance next-action "$RUN_ID"
```

If `--run-dir PATH` was supplied when the run started, pass the same option to every later
run-scoped command that supports it.

### 5. Review and answer Gate 1

Start with the human-readable questions and extracted source view. Edit only the designated YAML
review surfaces; the other files are evidence generated by the workflow.

| Purpose | Path under `$RUN_PATH` | Operator action |
| --- | --- | --- |
| Original source copy | `source/original.<ext>` | Compare only; do not edit |
| Normalized text | `source/normalized.md` | Check extraction and reading order |
| Structure diagnostics | `source/structure-quality.json` | Review detected structure problems |
| Selected outline/view | `source/selected-view.json` | Confirm headings and boundaries |
| Human-readable questions | `clarification/questions.md` | Read first; do not edit |
| Authoritative questions | `clarification/questions.yaml` | Use the question IDs; do not edit |
| Reviewer answers | `clarification/answers.yaml` | Add evidence-backed answers |
| Rewrite direction | `clarification/steering.yaml` | Optionally set audience, tone, exclusions, and constraints |
| Approved exceptions | `clarification/waivers.yaml` | Add only explicitly approved waivers |
| Gate 1 validation result | `clarification/validation-report.json` | Inspect when Gate 1 remains waiting |

Preserve the generated top-level metadata in `answers.yaml` and add entries under `answers`. A
typical answer has this shape:

```yaml
answers:
  - answer_id: ANS-REVIEW-001
    question_id: Q-COPY-THE-ID-FROM-QUESTIONS
    status: answered
    answer: The Model Governance Lead approves the monthly limitation review.
    responder: reviewer@example.com
    evidence_reference: answer://review/ANS-REVIEW-001
```

An answered item requires a reviewer and an `answer://`, `reference://`, `source://`, or
`steering://` evidence reference. Do not invent an answer merely to pass the gate. Leave it open,
provide documented steering, or record a governed waiver with approver, reason, downstream impact,
and review/expiry date.

Resume after saving the YAML files:

```bash
uv run docenhance resume "$RUN_ID" --json
```

If Gate 1 validation is not satisfied, the workflow remains waiting with exit code `10` and writes
actionable diagnostics to `clarification/validation-report.json`. Correct the named fields and
resume the same run; do not start over.

### 6. Review and approve Gate 2

When the workflow reaches `gate2`, read:

```text
$RUN_PATH/clarification/rewrite-checklist.md
$RUN_PATH/clarification/rewrite-checklist.yaml
```

The Markdown file is the convenient reading surface. The YAML file is authoritative. Confirm that
every blocking checklist item is answered or has an approved waiver, then record the approver and
UTC approval timestamp in `rewrite-checklist.yaml`:

```yaml
approved_by: approver@example.com
approved_at: '2026-07-16T18:00:00Z'
```

Do not approve an unresolved blocker. Resolve checklist statuses against the evidence and waivers
already captured at Gate 1. When every blocking item is resolved and the checklist is approved,
resume again:

```bash
uv run docenhance resume "$RUN_ID" --json
```

### 7. Review the completed enhancement

The final response should report `"status": "succeeded"` and `"current_stage": "complete"`.
Review the completed run in this order:

| Review goal | Path under `$RUN_PATH` |
| --- | --- |
| Main human-readable result | `output/enhanced.md` |
| Semantic representation | `output/enhanced.semantic.yaml` |
| Unresolved or explicitly retained issues | `output/open-issues.yaml` |
| Source disposition and rewrite evidence | `output/content-ledger.json` and `output/rewrite-inputs.json` |
| Audit summary | `audit/report.md` |
| Machine-readable audit decision | `audit/audit.json` |
| Text and semantic change review | `audit/textual.diff.md` and `audit/semantic.diff.yaml` |
| Source-to-output traceability | `audit/source-to-target.csv` |
| Retrieval/export records | `export/chunks.jsonl`, `nodes.jsonl`, and `edges.jsonl` |
| Sealed per-document RAG package | `rag/document-rag.sqlite3` |

The run directory is an evidence bundle. Copy `output/enhanced.md` elsewhere if further editorial
work is needed; do not overwrite the audited artifact in place.

Recheck the final gates from the CLI:

```bash
uv run docenhance audit "$RUN_ID" --json
uv run docenhance export "$RUN_ID" --json
uv run docenhance rag verify "$RUN_ID" --json
uv run docenhance rag inspect "$RUN_ID" --json
```

Audit, export, package, catalog, or grounding failures exit with code `30` and are not promoted as
successful results.

### 8. Add the result to the local RAG catalog and query it

Live runs ingest a validated package into `.document-enhancer/rag/catalog.sqlite3` by default.
Offline runs do not auto-ingest. Ingest an offline package explicitly after reviewing it:

```bash
uv run docenhance rag ingest "$RUN_ID" \
  --catalog .document-enhancer/rag/catalog.sqlite3 \
  --json
```

Inspect the cumulative catalog, then query it using the mode that built it:

```bash
uv run docenhance rag stats --json

# Catalog built by a live run
uv run docenhance rag search "Who approves the monthly limitation review?" --explain
uv run docenhance rag ask "Who approves the monthly limitation review?" --explain

# Catalog built by an offline run
uv run docenhance rag search \
  "Who approves the monthly limitation review?" --offline --explain
uv run docenhance rag ask \
  "Who approves the monthly limitation review?" --offline --explain
```

Use `--offline` with `rag search`, `rag ask`, or `rag chat` only when the catalog was built with the
deterministic offline embedding profile. Live and offline embedding profiles cannot be mixed.

### 9. Try the checked-in examples

The synthetic corpus contains process, methodology, standard, and desktop-procedure documents in
clean, mild, medium, and severe Markdown/DOCX variants. The methodology and desktop-procedure
families also include text-based PDFs. For example:

```bash
uv run docenhance run \
  fixtures/synthetic/corpus/monthly_loss_forecasting_methodology/medium.docx \
  --document-type methodology \
  --execution-mode offline \
  --until questions \
  --json
```

See the [fixture corpus guide](docs/fixture-corpus.md) for the full matrix. To exercise both review
gates, audit/export, RAG packaging, ingestion, search, and a cited answer without credentials, run:

```bash
uv run python scripts/run_offline_demo.py \
  --output .document-enhancer/m8-demo \
  --force
python -m json.tool .document-enhancer/m8-demo/demo-result.json
```

## Current commands

```text
docenhance doctor [--json]
docenhance config show [--json]
docenhance version
docenhance run SOURCE [--document-type TYPE] [--structure-mode MODE] [--execution-mode live|offline] [--run-dir PATH] [--until questions|checklist|complete] [--gate2|--no-gate2] [--catalog-ingest|--no-catalog-ingest] [--catalog PATH] [--json]
docenhance status RUN_ID [--run-dir PATH] [--json]
docenhance current-stage RUN_ID [--run-dir PATH] [--json]
docenhance next-action RUN_ID [--run-dir PATH] [--json]
docenhance resume RUN_ID [--run-dir PATH] [--execution-mode live|offline] [--json]
docenhance audit RUN_ID [--run-dir PATH] [--json]
docenhance export RUN_ID [--run-dir PATH] [--json]
docenhance prompts list [--json]
docenhance prompts show PROMPT_ID [--composed] [--json]
docenhance prompts validate [--json]
docenhance rag build RUN_ID [--run-dir PATH] [--offline] [--json]
docenhance rag verify RUN_ID_OR_PACKAGE [--run-dir PATH] [--json]
docenhance rag inspect RUN_ID_OR_PACKAGE [--run-dir PATH] [--json]
docenhance rag ingest RUN_ID [--run-dir PATH] [--catalog PATH] [--json]
docenhance rag search QUERY [--catalog PATH] [--offline] [--explain] [--json]
docenhance rag ask QUESTION [--catalog PATH] [--offline] [--explain] [--json]
docenhance rag chat [--catalog PATH] [--session ID] [--no-save] [--offline] [--json]
docenhance rag sources ANSWER_OR_SESSION_ID [--catalog PATH] [--json]
docenhance rag graph ENTITY_ID [--catalog PATH] [--depth 1|2] [--json]
docenhance rag stats [--catalog PATH] [--json]
```

The normal `run` mode is live. Use `--execution-mode offline` for the explicit network-free
test/demo path. The workflow writes editable clarification artifacts first, then after the review
gates writes the content ledger, rewrite inputs, enhanced model, enhanced Markdown, open issues,
semantic sidecar, Mermaid validation, audit/diff/export bundle, and sealed RAG package under the
selected run directory. It can then promote that package into the cumulative catalog for the Rich
retrieval and grounded-answer commands. See `docs/rag-cli.md` for the local RAG workflow and
persistence behavior.

## Verification

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -m "not live_model and not public_download"
uv run python scripts/generate_schemas.py --check
uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core
uv run python scripts/verify_prompt_pack.py prompt_packs/gemini_core \
  --reference-pack reference_packs/enterprise_core
uv run python scripts/generate_fixture_corpus.py --check
uv run python scripts/run_evaluations.py --check
uv build
git diff --check
```

For the stronger release proof, run `scripts/verify_release.sh HEAD`; it repeats the gate in a
temporary clean clone and then validates the built wheel from a separate isolated environment.
The checked-in offline evaluation report and exact limitations are in
`evals/reports/m8-evaluation.md`.

Compatibility tests are offline by default. They validate the installed LangChain, LangGraph, Deep Agents, SQLite FTS5, sqlite-vec, and adapter shapes without sending document content anywhere. Live Gemini structured-output and embedding profile checks are separately marked `live_model` and require explicit opt-in.

## Data handling

Source documents and derived artifacts are treated as untrusted, confidential data. The workflow
logs event metadata only, redacts credential-shaped and raw-content values from prompt snapshots,
keeps provider tools disabled by default, and writes run artifacts atomically under the selected
local run directory. A local `.env` is ignored by Git and never loaded automatically by the CLI.
The limited live acceptance harness uses an allowlisted external-environment loader; it never emits
the credential or writes it to run artifacts, output, or logs.
