# Synthetic fixture corpus

The WT9 corpus is a deterministic, fictional evaluation input set for the document-enhancement workflow. It is not an enhanced-document gold set and contains no copied enterprise or proprietary material.

## Inventory

`fixtures/synthetic/corpus/manifest.json` indexes five families:

| Family | Type | Deliberate coverage |
| --- | --- | --- |
| `monthly_loss_forecasting_methodology` | methodology | equations/threshold units, offline calculator, assumptions, controls, limitations |
| `quarterly_user_access_review_process` | process | compound steps, systems, evidence, trigger, exception authority, escalation |
| `incident_escalation_desktop_procedure` | desktop procedure | screenshot dependence, service levels, fallback worksheet, rollback, completion |
| `third_party_risk_standard` | standard | normative/advisory conflict, requirement IDs, evidence, exception authority, supersession |
| `model_change_governance_process` | process | cross-document dependencies, approvals, versions, evidence, current-version ambiguity |

Each family has `clean`, `mild`, `medium`, and `severe` Markdown variants. The variants preserve the same fictional facts while changing structure and layout signals: inconsistent numbering, bold or table headings, repeated page furniture, table-layout artifacts, multi-topic blocks, an untrusted instruction string, malformed Mermaid, and unresolved IDs. Every variant has a gold raw-block order, section boundaries, routing expectation, and lossy/scanned metadata contract in its family `gold.json`.

The cross-document question set is versioned separately in `cross_document_questions.json`. It defines expected evidence spans, acceptable typed graph paths, required facts, forbidden claims, and an abstention case. The expected chunks, answers, ranks, and citations are intentionally pending until M7R exists.

DOCX/PDF and binary scanned fixtures are deferred to M3. The `lossy_metadata` field records that deferral explicitly; it is not a claim that a binary fixture passed extraction.

## Generation and versioning

The source of truth for synthetic facts and render rules is `evals/corpus.py`. Generate the checked-in corpus with:

```bash
uv run python scripts/generate_fixture_corpus.py
```

Verify that the checked-in bytes are reproducible without changing them:

```bash
uv run python scripts/generate_fixture_corpus.py --check
```

Changes to facts, IDs, section boundaries, defects, or layout degradation require a corpus schema/version review. Do not add timestamps, random IDs, model outputs, secrets, or downloaded public documents to generated files. A source digest is the SHA-256 of the exact rendered variant; gold references retain stable span IDs and provenance rather than relying on line numbers alone.

## Gold and pending boundaries

The following are honest Wave-2 gold contracts:

- source facts and their source spans;
- raw block order and section hierarchy/boundaries;
- expected parser-versus-recovery routing;
- seeded clarification questions and defect labels;
- typed semantic objects and allow-listed edges;
- cross-document evidence, graph-path, citation, and abstention expectations.

`content_dispositions.status` is `pending_m6`, and `enhanced_output.status` is `pending_m6_m7`. No enhanced Markdown, semantic sidecar, ledger, graph export, SQLite package, embedding, retrieval result, or model answer is fabricated in this wave. WT9 should populate those artifacts only after the corresponding lane contracts and real outputs merge.

The generator and evaluator are safe to run offline. Public sources are governed separately by `fixtures/public/sources.yaml`; they are fetch-on-demand references, never synthetic gold.
