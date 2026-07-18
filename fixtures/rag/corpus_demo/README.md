# Adaptive corpus RAG demonstration

This fixture is a five-document fictional corpus for verifying the complete authoring-to-retrieval
journey. The source facts and expected reconciliation controls are machine-readable in
`expectations.json`.

## Sealed demonstration runs

| Source | Sealed run | Expected owner | Retention | Reconciliation control |
| --- | --- | --- | --- | --- |
| `payment_settlement_process.md` | `918108480c23-93606487d4` | Treasury Operations Manager | 7 years | `CTRL-PAY-101` |
| `vendor_invoice_process.md` | `4a96f70178e8-77a788bd0c` | Accounts Payable Director | 6 years | `CTRL-AP-202` |
| `privileged_access_process.md` | `bb21fd5c68a4-82889042c6` | IAM Governance Lead | 7 years | none |
| `model_monitoring_process.md` | `cb5c3f51a738-672995c3c6` | Model Risk Analytics Manager | 8 years | `CTRL-MOD-404` |
| `complaint_quality_process.md` | `9dc086ca1df9-b98b271f40` | Customer Advocacy QA Director | 7 years | `CTRL-CQA-505` |

Each source was analyzed offline through Stage 1, paused at the human gate, received 17 explicit
reviewer decisions, and completed Stage 2 with all 12 deterministic audit checks passing. The two
initial failed attempts remain unsealed in local run history; they exposed and led to a regression
fix for matching required headings against prose instead of actual Markdown headings.

## Live catalog and answer proof

The five runs above produced one validated Gemini-backed catalog with 215 chunks, 115 graph nodes,
80 graph edges, and zero rejected candidates. Live verification on 2026-07-18 produced:

- automatic corpus retrieval: 5/5 documents, 40/215 chunks, exactly `CTRL-PAY-101`,
  `CTRL-AP-202`, `CTRL-MOD-404`, and `CTRL-CQA-505`;
- exhaustive corpus map-reduce: 5/5 documents, 215/215 chunks, 30 successful map batches, one
  successful reducer, no failed run, no truncation, and the same exact four control IDs;
- arbitrary comparison: all five correct business-owner and retention-period pairs;
- focused retrieval: Treasury Operations Manager for the payment process and IAM Governance Lead
  for privileged-access recertification, with validated chunk citations;
- graph retrieval: real `contains` paths from the model-monitoring control section to its evidence,
  record, requirement, and risk nodes, with a cited answer;
- Rich chat: cited owner answer, `/sources` replay, and clean `/exit`.

The completeness-sensitive verification command is:

```bash
uv run docenhance rag ask \
  "List all controls that have a reconciliation step from all documents." \
  --coverage exhaustive --json
```

Success requires `coverage.documents_scanned == 5`, `coverage.chunks_examined == 215`, no failed
runs, `reduction_failed == false`, `truncated == false`, and item keys equal to the four values in
`expectations.json`.
