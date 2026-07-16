# Section mapping

- Analysis ID: `ANA-SECTIONS-57ADA4357C7F7BD9`
- Covered source spans: 8/8

## Source-span dispositions

| Source span | Target section(s) | Disposition | Rationale |
|---|---|---|---|
| `SPAN-ANALYSIS00000001` | `SEC-GOVERNANCE` | preserved | Retain the source title. |
| `SPAN-ANALYSIS00000002` | `SEC-METHOD-STEPS` | moved | Move the execution statement. |
| `SPAN-ANALYSIS00000003` | `SEC-CONTROLS` | moved | Move review evidence to controls. |
| `SPAN-ANALYSIS00000004` | `SEC-OPEN-ISSUES` | preserved | Retain hostile text as inert evidence. |
| `SPAN-ANALYSIS00000005` | `SEC-EXCEPTIONS` | moved | Move escalation content. |
| `SPAN-ANALYSIS00000006` | `SEC-DATA` | preserved | Retain the source table. |
| `SPAN-ANALYSIS00000007` | `SEC-OVERVIEW` | preserved | Retain the figure as a non-authoritative aid. |
| `SPAN-ANALYSIS00000008` | — | omitted | Repeated page furniture is accounted for explicitly and is not target content. |

## Findings

| ID | Severity | Type | Category | Evidence | Impact | Proposed disposition | Human answer |
|---|---|---|---|---|---|---|---|
| `FND-SECTIONS-C64E9DFCE76EF2EA` | blocker | conflicting | scope | `SPAN-ANALYSIS00000002`: “The Forecast Analyst runs the monthly forecast using CALC-LOSS-001.” | The source-to-target map cannot establish applicability boundaries. | Block rewrite until scope boundaries are reviewed. | blocking |
