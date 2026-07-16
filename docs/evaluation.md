# Evaluation contracts

WT9 provides deterministic, evidence-oriented evaluation scaffolding in `evals/`. Reports use schema version `0.1` and contain one result per metric with:

```json
{
  "metric_id": "structure_coverage_order",
  "status": "passed|failed|not_evaluated",
  "score": 1.0,
  "numerator": 8,
  "denominator": 8,
  "details": {},
  "dependencies": []
}
```

`not_evaluated` is a first-class result. It requires a reason and dependency list; it is never treated as a passing score. A corpus report is `pending_dependencies` while any dependency-gated metric is unavailable.

## Current support

When a candidate selected structural view is supplied, the deterministic graders can measure raw-span coverage/order and exact section-boundary matches. With no candidate artifact, those metrics are `not_evaluated` rather than inferred from source text. The fixture contract itself remains testable for stable IDs, source digests, section bounds, question provenance, and graph references.

The framework has named slots for ontology/graph completeness, question quality, ledger/rewrite fidelity, SQLite/embedding completeness, retrieval ranking, groundedness, citations, abstention, cost, and latency. In the WT0 baseline they remain explicitly pending because M4B, M5, M6, M7, M7R, or live-provider artifacts have not merged. The evaluator does not manufacture a sidecar, database, vector, rank, answer, or timing.

Once downstream artifacts exist, graders should consume their stable IDs and provenance rather than scrape prose. The intended measures are:

- object/edge and question set precision/recall/F1 against seeded IDs;
- ledger disposition coverage and source-to-output fidelity;
- SQLite row/checksum/foreign-key/FTS/vector completeness;
- retrieval evidence ranking such as Recall@k, MRR, nDCG, graph-path correctness, and filter correctness;
- claim groundedness, citation precision/recall, forbidden-claim detection, and unanswerable-question abstention;
- provider-reported cost/token usage and wall-clock latency, with model route and retry metadata.

These metrics must remain separate by fixture, input format, severity, model route, and retrieval channel. Aggregate thresholds from plan.md Section 20 are release evidence only after the artifact-producing lanes and live evaluation route exist.

## Running reports

Generate a deterministic report over the checked-in corpus:

```bash
uv run python -c 'from pathlib import Path; from evals.grading import evaluate_corpus; evaluate_corpus(Path("fixtures/synthetic/corpus"), output_path=Path("evals/reports/synthetic-corpus.json"))'
```

The report will say `pending_dependencies` and explain each not-evaluated metric. That is the expected Wave-2 result. Do not rename pending results to pass merely to satisfy a release threshold.
