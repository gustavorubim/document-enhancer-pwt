# M8 offline evaluation report

Release status: **passed_offline**

This report is generated from checked-in fictional gold contracts. The default run made zero provider calls and zero public downloads. It validates deterministic graders, release contracts, and route configuration; it does not claim live Gemini quality, service latency, token usage, pricing, or public-source generalization.

## Section 20 threshold evidence

| Threshold | Observed | Required | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| `schema_valid_final_artifacts` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `raw_block_coverage_order` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `severe_section_boundary_f1` | 100.0% | 90.0% | passed | recorded_offline_gold_replay |
| `unique_ids_and_references` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `disposition_coverage` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `semantic_provenance_coverage` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `blocking_resolution` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `unsupported_claim_free` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `question_seed_recall` | 100.0% | 95.0% | passed | recorded_offline_gold_replay |
| `process_object_recall` | 100.0% | 95.0% | passed | recorded_offline_gold_replay |
| `stable_chunk_ids` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `sqlite_graph_embedding_completeness` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `embedding_smoke_rank` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `retrieval_recall_at_10_fused` | 100.0% | 90.0% | passed | recorded_offline_gold_replay |
| `graph_path_correctness` | 100.0% | 85.0% | passed | recorded_offline_gold_replay |
| `citation_precision` | 100.0% | 95.0% | passed | recorded_offline_gold_replay |
| `citation_recall` | 100.0% | 90.0% | passed | recorded_offline_gold_replay |
| `unsupported_material_claims_zero` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `unanswerable_abstention` | 100.0% | 95.0% | passed | recorded_offline_gold_replay |
| `answered_partial_citation_validation` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |
| `configured_route_coverage` | 100.0% | 100.0% | passed | recorded_offline_gold_replay |

## Per-family enhancement and package results

| Family | Fixture-format reports | Passed | Failed |
| --- | ---: | ---: | ---: |
| `monthly_loss_forecasting_methodology` | 12 | 12 | 0 |
| `quarterly_user_access_review_process` | 8 | 8 | 0 |
| `incident_escalation_desktop_procedure` | 12 | 12 | 0 |
| `third_party_risk_standard` | 8 | 8 | 0 |
| `model_change_governance_process` | 8 | 8 | 0 |

Each family/format/severity report grades raw-block coverage and order, boundary F1, hierarchy, schema validity, unique IDs and references, dispositions, provenance, question/object/defect recall and precision, chunk stability, SQLite/FTS/graph/vector completeness, embedding smoke ranking, and route coverage.

## Retrieval channels

| Channel | Queries | Recall@10 | MRR | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| vector | 8 | 100.0% | 1.000 | 1.000 |
| fts | 8 | 100.0% | 1.000 | 1.000 |
| graph | 4 | 100.0% | 1.000 | 1.000 |
| fused | 8 | 100.0% | 1.000 | 1.000 |

Graph-path correctness: 100.0%. Filter correctness: 100.0%. Follow-up resolution: 100.0%.

## Answers and citations

Groundedness: 100.0%. Citation precision: 100.0%. Citation recall: 100.0%. Abstention accuracy: 100.0%. Unsupported material claims: 0.

| Question | Status | Evidence chunks | Citations | Forbidden claims present |
| --- | --- | --- | --- | --- |
| `RAG-Q-001` | answered | CHK-M8-FORECAST-METHOD | SPN-FORECAST-007 | none |
| `RAG-Q-002` | answered | CHK-M8-MCG-APPROVAL, CHK-M8-MCG-EVIDENCE | SPN-MCG-006, SPN-MCG-008 | none |
| `RAG-Q-003` | answered | CHK-M8-ACCESS-CONTROL | SPN-ACCESS-008 | none |
| `RAG-Q-004` | partial | CHK-M8-MCG-INTAKE, CHK-M8-FORECAST-METHOD | SPN-MCG-002, SPN-FORECAST-006 | none |
| `RAG-Q-005` | insufficient | CHK-M8-MCG-LIFECYCLE | SPN-MCG-010 | none |
| `RAG-Q-006` | answered | CHK-M8-ACCESS-CONTROL | SPN-ACCESS-009 | none |
| `RAG-Q-007` | answered | CHK-M8-TPRM-SCOPE | SPN-TPRM-002 | none |
| `RAG-Q-008` | insufficient | CHK-M8-ACCESS-TRIGGER | SPN-ACCESS-002 | none |
| `RAG-Q-009` | insufficient | none | none | none |

## Gemini route, latency, cost, fallback, and lifecycle evidence

| Route | Offline mode | Coverage/quality | Deterministic latency proxy | Actual provider cost | Fallback/lifecycle |
| --- | --- | ---: | ---: | ---: | --- |
| `gemini-3.1-flash-lite` | recorded_offline_gold_replay | 100.0% | 5.80 ms | $0.00 | disabled; exact versioned route; preview route may change or retire |
| `gemini-3.5-flash` | recorded_offline_gold_replay | 100.0% | 6.80 ms | $0.00 | disabled; exact versioned route; preview route may change or retire |
| `gemini-3.1-pro-preview` | recorded_offline_gold_replay | 100.0% | 7.80 ms | $0.00 | disabled; exact versioned route; preview route may change or retire |
| `gemini-embedding-2` | recorded_offline_deterministic_embedding | 100.0% | 5.80 ms | $0.00 | none; embedding failures block promotion; exact model identity is stored with every vector profile |

Latency values above are deterministic workload proxies for regression comparison, not wall-clock service measurements. Actual provider cost is zero because the offline gate does not call Gemini. Live quality, service latency, token usage, and billed cost are reported only by the explicit `live_model` evaluation.

## Fixture-format detail

| Family | Severity | Format | Status | Lowest metric |
| --- | --- | --- | --- | ---: |
| `monthly_loss_forecasting_methodology` | clean | docx | evaluated | 100.0% |
| `monthly_loss_forecasting_methodology` | clean | markdown | evaluated | 100.0% |
| `monthly_loss_forecasting_methodology` | clean | pdf | evaluated | 100.0% |
| `monthly_loss_forecasting_methodology` | medium | docx | evaluated | 100.0% |
| `monthly_loss_forecasting_methodology` | medium | markdown | evaluated | 100.0% |
| `monthly_loss_forecasting_methodology` | medium | pdf | evaluated | 100.0% |
| `monthly_loss_forecasting_methodology` | mild | docx | evaluated | 100.0% |
| `monthly_loss_forecasting_methodology` | mild | markdown | evaluated | 100.0% |
| `monthly_loss_forecasting_methodology` | mild | pdf | evaluated | 100.0% |
| `monthly_loss_forecasting_methodology` | severe | docx | evaluated | 100.0% |
| `monthly_loss_forecasting_methodology` | severe | markdown | evaluated | 100.0% |
| `monthly_loss_forecasting_methodology` | severe | pdf | evaluated | 100.0% |
| `quarterly_user_access_review_process` | clean | docx | evaluated | 100.0% |
| `quarterly_user_access_review_process` | clean | markdown | evaluated | 100.0% |
| `quarterly_user_access_review_process` | medium | docx | evaluated | 100.0% |
| `quarterly_user_access_review_process` | medium | markdown | evaluated | 100.0% |
| `quarterly_user_access_review_process` | mild | docx | evaluated | 100.0% |
| `quarterly_user_access_review_process` | mild | markdown | evaluated | 100.0% |
| `quarterly_user_access_review_process` | severe | docx | evaluated | 100.0% |
| `quarterly_user_access_review_process` | severe | markdown | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | clean | docx | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | clean | markdown | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | clean | pdf | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | medium | docx | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | medium | markdown | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | medium | pdf | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | mild | docx | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | mild | markdown | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | mild | pdf | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | severe | docx | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | severe | markdown | evaluated | 100.0% |
| `incident_escalation_desktop_procedure` | severe | pdf | evaluated | 100.0% |
| `third_party_risk_standard` | clean | docx | evaluated | 100.0% |
| `third_party_risk_standard` | clean | markdown | evaluated | 100.0% |
| `third_party_risk_standard` | medium | docx | evaluated | 100.0% |
| `third_party_risk_standard` | medium | markdown | evaluated | 100.0% |
| `third_party_risk_standard` | mild | docx | evaluated | 100.0% |
| `third_party_risk_standard` | mild | markdown | evaluated | 100.0% |
| `third_party_risk_standard` | severe | docx | evaluated | 100.0% |
| `third_party_risk_standard` | severe | markdown | evaluated | 100.0% |
| `model_change_governance_process` | clean | docx | evaluated | 100.0% |
| `model_change_governance_process` | clean | markdown | evaluated | 100.0% |
| `model_change_governance_process` | medium | docx | evaluated | 100.0% |
| `model_change_governance_process` | medium | markdown | evaluated | 100.0% |
| `model_change_governance_process` | mild | docx | evaluated | 100.0% |
| `model_change_governance_process` | mild | markdown | evaluated | 100.0% |
| `model_change_governance_process` | severe | docx | evaluated | 100.0% |
| `model_change_governance_process` | severe | markdown | evaluated | 100.0% |

## Failures and limitations

- No deterministic offline threshold failures.
- Live Gemini quality, service latency, token use, and billed cost were not measured in the offline release gate.
- Public-source downloads are registry-only and require an explicit public_download run.
- Offline retrieval evidence is a controlled gold replay; it is not a production retriever benchmark.
- Text PDFs do not cover OCR or scanned-image recovery.
- Messy source structure remains uncertain and requires confidence routing plus human review.
- Gemini exact routes, especially preview models, may change availability or lifecycle state.
- Inferred knowledge remains a separate reviewable graph layer.
- Local SQLite is not an unbounded or multi-tenant enterprise catalog.
- Pre-v1 SQLiteVec behavior is pinned but remains a compatibility risk.
- The MVP has no enterprise identity integration or hosted UI.
