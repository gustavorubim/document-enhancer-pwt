# Macro analysis

- Analysis ID: `ANA-MACRO-891BB2AEDCE7AF79`
- Candidate document type: methodology
- Candidate confidence: 0.91
- Purpose: Describe monthly loss forecasting work.
- Audience: Forecast analysts and model owners.
- Owner: Not established
- Authority: Not established
- Lifecycle status: Not established
- Scope: Monthly forecasting activities.
- Template fit: Methodology template is the strongest candidate.
- Alternative templates: Not established

## Rubric scores

| Dimension | Score | Weight | Evidence | Explanation |
|---|---:|---:|---|---|
| Purpose, scope, applicability, and audience | 2/4 | 10 | `SPAN-ANALYSIS00000002`: “The Forecast Analyst runs the monthly forecast using CALC-LOSS-001.” | Purpose is visible but boundaries are not explicit. |

## Findings

| ID | Severity | Type | Category | Evidence | Impact | Proposed disposition | Human answer |
|---|---|---|---|---|---|---|---|
| `FND-MACRO-70319555C5E1E7E2` | high | ambiguous | scope | `SPAN-ANALYSIS00000002`: “The Forecast Analyst runs the monthly forecast using CALC-LOSS-001.” | The operating scope is implied rather than bounded. | Ask the reviewer to define inclusions and exclusions. | yes |
