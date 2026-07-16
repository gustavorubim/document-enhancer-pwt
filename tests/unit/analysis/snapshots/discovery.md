# Process and methodology discovery

- Analysis ID: `AN-DISCOVERY-001`
- Candidate objects: 6
- Candidate relationships: 5

## Candidate objects

| ID | Type | Name | Source span | Authority | Review status |
|---|---|---|---|---|---|
| `ROLE-FORECAST-ANALYST` | Role | Forecast Analyst | `SPAN-ANALYSIS00000002` | inferred | unreviewed |
| `STEP-FORECAST-010` | ProcessStep | Run monthly forecast | `SPAN-ANALYSIS00000002` | inferred | unreviewed |
| `CALC-LOSS-001` | Calculator | Loss calculator | `SPAN-ANALYSIS00000002` | inferred | unreviewed |
| `CTRL-REVIEW-001` | Control | Threshold breach review | `SPAN-ANALYSIS00000003` | inferred | unreviewed |
| `EVD-REVIEW-001` | Evidence | Review evidence | `SPAN-ANALYSIS00000003` | inferred | unreviewed |
| `RISK-THRESHOLD-001` | Risk | Unreviewed threshold breach | `SPAN-ANALYSIS00000003` | inferred | unreviewed |

## Candidate relationships

| ID | Source | Relationship | Target | Source span |
|---|---|---|---|---|
| `EDGE-B546B842060E` | `STEP-FORECAST-010` | PERFORMED_BY | `ROLE-FORECAST-ANALYST` | `SPAN-ANALYSIS00000002` |
| `EDGE-5FA7659BCF48` | `STEP-FORECAST-010` | USES_CALCULATOR | `CALC-LOSS-001` | `SPAN-ANALYSIS00000002` |
| `EDGE-1AB57185FB78` | `STEP-FORECAST-010` | EXECUTES_CONTROL | `CTRL-REVIEW-001` | `SPAN-ANALYSIS00000003` |
| `EDGE-09131C6EA835` | `CTRL-REVIEW-001` | PRODUCES_EVIDENCE | `EVD-REVIEW-001` | `SPAN-ANALYSIS00000003` |
| `EDGE-B67F4E971167` | `CTRL-REVIEW-001` | MITIGATES | `RISK-THRESHOLD-001` | `SPAN-ANALYSIS00000003` |

## Findings

No findings were returned.
