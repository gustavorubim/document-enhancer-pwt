---
template_id: TPL-METHODOLOGY-001
document_type: methodology
reference_pack: enterprise_core
reference_pack_version: 1.0.0
document_id: DOC-AURORA-METH-0007
document_version: DOCV-AURORA-METH-0007-V2
status: effective
---

# Aurora Exposure-Weighted Loss Allocation Methodology

**Document ID:** DOC-AURORA-METH-0007
**Version:** DOCV-AURORA-METH-0007-V2
**Status:** effective
**Owner:** ROLE-METHOD-OWNER
**Effective date:** 2026-02-01
**Next review date:** 2027-02-01

## Document metadata and governance

This fictional methodology is owned by `ROLE-METHOD-OWNER` and approved by `ROLE-MODEL-GOVERNANCE-CHAIR` in `EVID-AURORA-METH-APPROVAL-002`. Version 2 adds a missing-exposure treatment and a quarterly back-test.

## Objective

Estimate each Aurora segment's share of a monthly portfolio loss using closed exposure and loss inputs so Finance Operations can reconcile the allocation to the ledger.

## Scope and applicability

The methodology applies to US Aurora segments with a closed monthly exposure snapshot. It is not valid for stress scenarios, incomplete exposure extracts, or periods with unresolved ledger restatements. It is tagged `governed_document`, `controlled_activity`, and `records`.

## Conceptual framework

The method distributes the total portfolio loss in proportion to each segment's eligible exposure. The output preserves the portfolio total and produces a reviewable contribution for each segment.

## Definitions

**Eligible exposure** is exposure after exclusion of records marked `inactive`. **Allocation share** is a segment's eligible exposure divided by total eligible exposure. **KPI** means key performance indicator.

## Data inputs and lineage

`DATA-AURORA-EXPOSURE-001` supplies segment exposure as of the close date, and `DATA-AURORA-LOSS-001` supplies the closed loss total. `ROLE-DATA-OWNER` owns both extracts. The source fields are `segment_id`, `eligible_exposure`, `loss_total`, and `as_of_date`.

| Data ID | Owner | Fields | Period | Quality check |
| --- | --- | --- | --- | --- |
| DATA-AURORA-EXPOSURE-001 | ROLE-DATA-OWNER | segment_id, eligible_exposure, as_of_date | Monthly close | Unique segment IDs and non-negative exposure |
| DATA-AURORA-LOSS-001 | ROLE-DATA-OWNER | loss_total, as_of_date | Monthly close | Closed status and non-null total |

## Data preparation and transformations

The analyst filters inactive records, rejects negative exposure, joins the two extracts on `as_of_date`, and records excluded rows. A missing segment exposure is treated as a blocking data-quality failure; it is not imputed by this methodology.

## Methodological steps

1. Validate input dates and closure status.
2. Filter eligible exposure and record exclusions.
3. Sum eligible exposure by segment and for the portfolio.
4. Calculate each segment's share and multiply by the portfolio loss.
5. Reconcile rounded segment outputs to the portfolio total.

## Models, formulas, algorithms, parameters, and calculators

`MODEL-AURORA-ALLOC-001` implements the formula `segment_loss = loss_total × segment_exposure / total_eligible_exposure`. `CALC-AURORA-ALLOC-001` version 4 is the approved spreadsheet calculator. Rounding uses two decimal places for presentation only; the reconciliation uses unrounded values.

| Object ID | Type | Formula or algorithm | Parameters | Calculator | Validation status |
| --- | --- | --- | --- | --- | --- |
| MODEL-AURORA-ALLOC-001 | Model | loss_total × segment_exposure / total_eligible_exposure | Two-place display rounding | CALC-AURORA-ALLOC-001 v4 | Accepted 2026-01-25 |

## Assumptions

The closed loss total is complete, eligible exposure is comparable across segments, and the exposure snapshot and loss total share an as-of date. `ROLE-METHOD-OWNER` reviews these assumptions quarterly.

| ID | Statement | Risk if violated | Validation | Owner |
| --- | --- | --- | --- | --- |
| ASM-AURORA-001 | Closed loss total is complete | Allocation may understate segments | Closure-status check and quarterly back-test | ROLE-METHOD-OWNER |

## Parameter selection and thresholds

The only configurable parameter is display precision, fixed at two decimal places by `PARAM-AURORA-ROUND-001`. The reconciliation tolerance is `0.50%` of the loss total and is owned by `ROLE-METHOD-OWNER`. A parameter change requires a new methodology version.

## Decision rules

`RULE-AURORA-METH-001` permits publication only when total eligible exposure is greater than zero and absolute reconciliation variance is less than or equal to 0.50% of loss total. No override is permitted for zero exposure; the process owner must correct the input.

## Limitations and applicability boundaries

The proportional allocation does not model causal loss drivers and is not a stress model. It is unsuitable when segment exposure is not comparable or when losses are not attributable to the close period. The report must disclose these limitations.

## Exceptions and overrides

No exception may override the zero-exposure rule. A late ledger correction may delay publication but cannot alter the formula. `ROLE-MODEL-GOVERNANCE-CHAIR` approves any change to scope or formula.

## Validation and testing

`TEST-AURORA-METH-001` checks total preservation on a seeded portfolio; tolerance is 0.01% of loss total. `TEST-AURORA-METH-002` performs a quarterly back-test against finalized ledger values. Results are retained as `EVID-AURORA-METH-TEST-002`.

| Test ID | Objective | Tolerance | Owner | Evidence | Result |
| --- | --- | --- | --- | --- | --- |
| TEST-AURORA-METH-001 | Preserve portfolio loss total | 0.01% | ROLE-METHOD-VALIDATOR | EVID-AURORA-METH-TEST-001 | Passed 2026-01-25 |
| TEST-AURORA-METH-002 | Compare allocation to finalized ledger | 5.00% segment deviation | ROLE-METHOD-VALIDATOR | EVID-AURORA-METH-TEST-002 | Passed 2026-01-20 |

## Monitoring metrics and performance tolerances

`METRIC-AURORA-METH-001` is quarterly absolute segment deviation. A result above 5.00% triggers investigation; two consecutive breaches require methodology review.

## Governance and approvals

The method owner maintains the calculator and assumptions. The independent validator reviews tests. The governance chair approves changes and exceptions.

| Role | Decision | Date | Evidence |
| --- | --- | --- | --- |
| ROLE-METHOD-OWNER | Recommended version 2 | 2026-01-20 | EVID-AURORA-METH-RECOMMEND-002 |
| ROLE-MODEL-GOVERNANCE-CHAIR | Approved version 2 | 2026-01-27 | EVID-AURORA-METH-APPROVAL-002 |

## Implementation mapping

`PROC-AURORA-ALLOC-001` implements this method. `CTRL-AURORA-001` controls the process reconciliation. The calculator is owned by `ROLE-METHOD-OWNER` and stored in `SYS-AURORA-REPORTING-001`.

## Related processes, controls, policies, and standards

Related objects are `PROC-AURORA-ALLOC-001`, `CTRL-AURORA-001`, `STD-OPS-DOC-001`, `STD-CONTROL-EVID-001`, and `POL-REC-001`.

## Version history

| Version | Effective date | Change | Approver |
| --- | --- | --- | --- |
| 1.0 | 2025-02-01 | Initial proportional allocation method | ROLE-MODEL-GOVERNANCE-CHAIR |
| 2.0 | 2026-02-01 | Added missing-exposure treatment and quarterly back-test | ROLE-MODEL-GOVERNANCE-CHAIR |
