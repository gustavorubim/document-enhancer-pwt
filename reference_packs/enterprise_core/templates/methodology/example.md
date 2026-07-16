---
template_id: TPL-METHODOLOGY-001
document_type: methodology
reference_pack: enterprise_core
reference_pack_version: 2.0.0
document_id: DOC-AURORA-METH-0007
document_version: DOCV-AURORA-METH-0007-V3
status: effective
---

# Aurora Exposure-Weighted Loss Allocation Methodology

**Document ID:** DOC-AURORA-METH-0007
**Version:** DOCV-AURORA-METH-0007-V3
**Status:** effective
**Owner:** ROLE-LOSS-METHODOLOGY-OWNER
**Effective date:** 2026-08-01
**Next review date:** 2027-07-31

## Document metadata and governance

This fictional methodology allocates an already approved monthly loss estimate across the US-booked
Aurora portfolio. `MODEL-AURORA-ALLOC-001` is classified as a Tier 2 model in the fictional model
inventory because it applies a quantitative method to support material internal risk reporting.

### Methodology control (TBL-METH-METADATA)

| Methodology ID | Version | Status | Classification | Legal entities and jurisdictions | Inventory ID and risk tier | Intended decision or use | Prohibited use | Owner | Accountable executive | Validation or challenge status | Approving authority | Effective date | Next review date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DOC-AURORA-METH-0007 | DOCV-AURORA-METH-0007-V3 | effective | confidential | Aurora Bank N.A. and Aurora Holdings Finance Company; US | MODEL-AURORA-ALLOC-001; Tier 2 | Allocate approved monthly loss for internal Finance and Risk reporting | Credit decisions, capital, reserves, pricing, stress testing, or non-US entities | ROLE-LOSS-METHODOLOGY-OWNER | ROLE-CFO-AURORA | Independently validated 2026-07-15 with one accepted limitation | COMMITTEE-AURORA-MODEL-RISK | 2026-08-01 | 2027-07-31 |

## Objective

Allocate the approved monthly Aurora loss estimate to each in-scope legal entity and portfolio in
proportion to month-end managed exposure, while preserving the total approved loss and providing a
reproducible basis for review and reporting.

## Scope and applicability

The methodology applies only to the US-booked managed portfolio and to closed reporting months. It
excludes forecasting, scenario analysis, capital, reserves, pricing, customer decisions, regulatory
submissions, portfolios with negative exposure, and periods with unresolved data-integrity issues.
Use outside this scope requires a separately approved methodology; it cannot be authorized by an
operational exception.

## Conceptual framework

The method assumes that month-end managed exposure is an appropriate allocation basis for an
aggregate loss amount that has already been approved outside this methodology. It does not estimate
loss. The method preserves the approved total and distributes it according to relative exposure.
This is an associational allocation rule, not a causal model of loss.

## Definitions

For entity or portfolio (i), `Exposure_i` is non-negative managed exposure in USD at 23:59
America/New_York on the last calendar day of the reporting month. `ApprovedLoss` is the signed
monthly loss amount in USD. `Allocation_i` is the rounded allocated amount. `Residual` is the cent-
level difference between the approved total and the sum of rounded allocations.

## Data inputs and lineage

### Data lineage and quality (TBL-METH-DATA)

| Data ID | Authoritative source | Legal-entity and period scope | Owner and steward | Critical elements | Lineage and transformations | Quality and reconciliation rule | Classification and residency | Approved fallback | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DATA-AURORA-LOSS-001 | SYS-AURORA-LEDGER-001 | Both in-scope entities; closed month | ROLE-LEDGER-OWNER / ROLE-FINANCE-DATA-STEWARD | approved_loss_usd, month, approval_id | Ledger close to approved-loss interface; no transformation | Amount and approval ID equal signed close record | restricted; US region | None | EVID-AURORA-DATA-LOSS-001 |
| DATA-AURORA-EXPOSURE-001 | SYS-AURORA-RISK-001 | Both in-scope entities; month end | ROLE-RISK-DATA-OWNER / ROLE-RISK-DATA-STEWARD | entity_id, portfolio_id, managed_exposure_usd, as_of | Position store to risk aggregation to controlled extract | Zero unmapped rows; totals reconcile within USD 1.00 | confidential; US region | Prior month only under EXC-AURORA-METH-001 | EVID-AURORA-DATA-EXPOSURE-001 |
| MAP-AURORA-ENTITY-001 | SYS-AURORA-MDM-001 | Active portfolio mappings for month | ROLE-REFERENCE-DATA-OWNER / ROLE-REFERENCE-DATA-STEWARD | portfolio_id, legal_entity_id, effective dates | Master data extract; no manual remap | Every active portfolio has one effective entity | confidential; US region | None | EVID-AURORA-MAPPING-001 |

## Data preparation and transformations

1. Read source extracts without overwriting them and record file or object checksums.
2. Reject duplicate portfolio IDs, negative or missing exposure, missing entity mappings, inconsistent
   months, or a loss amount without matching approval.
3. Join exposure to the effective-dated legal-entity mapping using `portfolio_id` and reporting date.
4. Aggregate managed exposure by legal entity and portfolio without excluding zero-exposure rows.
5. Reconcile aggregate exposure to `RISK-REPORT-AURORA-001` and record counts before calculation.

Missing or late values are not imputed. The prior-month fallback requires the approved exception,
visible disclosure, enhanced variance review, and recalculation when current data arrives.

## Methodological steps

1. `STEP-AURORA-METH-001` begins by validating input identity, approval, legal-entity scope, dates,
   counts, totals, mappings, and quality thresholds; any failed entry criterion stops the method.
2. `STEP-AURORA-METH-002` calculates unrounded shares and allocations using the approved inputs,
   formula, parameter values, and implementation version.
3. `STEP-AURORA-METH-003` rounds to cents and assigns the residual to the largest unrounded
   allocation, breaking a tie by ascending stable portfolio ID.
4. `STEP-AURORA-METH-004` reconciles the final total, records controls and evidence, and produces
   output with legal-entity lineage, limitation disclosures, and the downstream handoff status.

## Models, formulas, algorithms, parameters, and calculators

For each eligible portfolio (i):

`Share_i = Exposure_i / sum(Exposure_j)`

`UnroundedAllocation_i = ApprovedLoss × Share_i`

`Allocation_i = round(UnroundedAllocation_i, USD 0.01)` followed by the deterministic residual rule.

### Model, formula, and implementation inventory (TBL-METH-MODELS)

| Object ID | Classification and risk tier | Purpose and approved use | Formula or algorithm | Inputs and parameters | Units, timing, and rounding | Owner and developer | Implementation or calculator | Validation status and date | Limitations and fallback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MODEL-AURORA-ALLOC-001 | Model; Tier 2 | Internal monthly allocation only | FORM-AURORA-ALLOC-001 plus ALG-AURORA-RESIDUAL-001 | ApprovedLoss, Exposure_i, reporting month | USD, month end, half-even cents | ROLE-LOSS-METHODOLOGY-OWNER / ROLE-QUANT-DEVELOPER | CALC-AURORA-ALLOC-001 v4.2 in SYS-AURORA-CALC-001 | Validated 2026-07-15; approved | Not a loss estimator; no manual fallback |
| FORM-AURORA-ALLOC-001 | Formula component | Preserve total while allocating by exposure | ApprovedLoss × Exposure_i / sum(Exposure_j) | No estimated parameter | USD; unrounded until final step | ROLE-LOSS-METHODOLOGY-OWNER | CALC-AURORA-ALLOC-001 v4.2 | Unit, boundary, and benchmark tests passed | Invalid when total exposure is zero |

## Assumptions

### Assumptions (TBL-METH-ASSUMPTIONS)

| Assumption ID | Statement and rationale | Applicability and period | Risk if violated | Test or monitoring | Owner | Breach action | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ASM-AURORA-001 | Managed exposure is an appropriate allocation basis because the approved aggregate loss has no portfolio attribution | Both entities; each month | Misleading entity or portfolio allocation | Quarterly outcome and composition review | ROLE-LOSS-METHODOLOGY-OWNER | Escalate for alternative basis assessment | EVID-AURORA-ASM-001 |
| ASM-AURORA-002 | Total managed exposure is positive | Every run | Division by zero and invalid allocation | Pre-calculation control | ROLE-LOSS-OWNER | Stop; no override | EVID-AURORA-INPUT-001 |
| ASM-AURORA-003 | Stable portfolio IDs provide a neutral residual tie-break | Every run | Non-reproducible cent assignment | Determinism test on every release | ROLE-QUANT-DEVELOPER | Block release | EVID-AURORA-VALID-003 |

## Parameter selection and thresholds

The methodology has no statistically estimated coefficient. Thresholds are governed decision rules,
not model estimates. A management overlay changes output and therefore requires explicit pre- and
post-overlay values, rationale, authority, expiry, and monitoring.

### Parameters and overlays (TBL-METH-PARAMETERS)

| Parameter or overlay ID | Definition and source | Selection or estimation method | Value, unit, and period | Approval authority | Sensitivity or uncertainty | Monitoring and recalibration | Override or expiry | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PAR-AURORA-RECON-001 | Maximum absolute total reconciliation difference | Control design, not estimated | USD 1.00 per monthly run | ROLE-CONTROLLER-AURORA | A lower threshold does not change allocations; a higher threshold can conceal error | Annual design review | No run-level override | EVID-AURORA-PARAM-001 |
| OVR-AURORA-001 | Temporary allocation adjustment | Expert judgment with documented affected portfolios | No standing value; one month maximum | COMMITTEE-AURORA-MODEL-RISK | Full pre/post output and downstream impact required | Daily until reversed or incorporated | Expires at month-end | EVID-AURORA-OVERLAY-001 |

## Decision rules

If total exposure is less than or equal to USD 0.00, stop. If any exposure is negative, missing, or
unmapped, stop. If current exposure is unavailable, only `EXC-AURORA-METH-001` may authorize prior-
month exposure. If the portfolio composition changes by more than 10.00% of total exposure from the
prior month, obtain second-line challenge before use. All comparisons use unrounded source values.

## Limitations and applicability boundaries

### Limitations and use restrictions (TBL-METH-LIMITATIONS)

| Limitation ID | Affected use or population | Cause | Impact and severity | Mitigation or compensating control | Required disclosure | Owner | Monitoring or trigger | Escalation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LIM-AURORA-001 | Portfolio allocation | Exposure may not reflect causal loss attribution | Medium; output may misstate relative economic cause | Label as allocation; compare outcomes and reassess basis annually | State that output is not a loss estimate | ROLE-LOSS-METHODOLOGY-OWNER | Quarterly outcome review | COMMITTEE-AURORA-MODEL-RISK on breach |
| LIM-AURORA-002 | Prior-month fallback | Current exposure delay | High; stale composition | Exception, enhanced variance review, recalculation, and disclosure | Identify stale period and quantified replacement impact | ROLE-LOSS-OWNER | Daily until current data | ROLE-CFO-AURORA after one business day |
| LIM-AURORA-003 | Non-US entities and regulatory submissions | Methodology not designed or validated for those uses | High; unsupported use | Prohibit use and require separate approval | Display prohibited-use statement | ROLE-LOSS-METHODOLOGY-OWNER | Usage monitoring | ROLE-MODEL-RISK-CHALLENGER immediately |

## Exceptions and overrides

`EXC-AURORA-METH-001` permits prior-month exposure for one reporting month when current exposure is
unavailable, only after first-line risk assessment and second-line approval. It requires an enhanced
variance review, output disclosure, daily monitoring, recalculation with current exposure, and
quantification of downstream impact. It cannot authorize zero, negative, or unmapped exposure or use
outside the approved purpose.

## Validation and testing

Independent validation evaluates conceptual soundness, input and lineage controls, formula and
rounding correctness, implementation, sensitivity, benchmark agreement, outcomes, limitations,
governance, and ongoing monitoring. Validation uses source-controlled code and data distinct from
development evidence where practical.

### Validation and testing (TBL-METH-VALIDATION)

| Test ID | Validation component and independence | Objective and population | Method, benchmark, or challenger | Tolerance and decision rule | Owner | Result and date | Findings or limitations | Evidence and next due |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TEST-AURORA-001 | Conceptual soundness; independent second line | Approved use and allocation basis | Challenge against equal-weight and loss-driver alternatives | Approve only if rationale and limitations are complete | ROLE-MODEL-VALIDATOR | Pass, 2026-07-15 | LIM-AURORA-001 retained | EVID-AURORA-VALID-001; due 2027-07-15 |
| TEST-AURORA-002 | Implementation verification; independent second line | All formula, rounding, zero, negative, missing, and tie boundaries | Independent benchmark implementation | Exact agreement to USD 0.01 and identical tie result | ROLE-MODEL-VALIDATOR | Pass, 2026-07-15 | None | EVID-AURORA-VALID-002; rerun each material release |
| TEST-AURORA-003 | Data and lineage; Data Risk challenge | Both entities and three input objects | Trace source-to-output and reconcile totals | Zero unmapped rows; totals within USD 1.00 | ROLE-DATA-RISK-CHALLENGER | Pass, 2026-07-14 | Prior-month fallback remains high risk | EVID-AURORA-VALID-003; due 2027-07-14 |
| TEST-AURORA-004 | Outcome analysis; first line with second-line review | Twelve completed months | Compare allocated share with subsequent attributed loss | Escalate when absolute share difference exceeds 15 percentage points for 3 months | ROLE-LOSS-METHODOLOGY-OWNER | Pass with observation, 2026-06-30 | Short history for one portfolio | EVID-AURORA-OUTCOME-001; quarterly |

## Monitoring metrics and performance tolerances

### Ongoing monitoring and escalation (TBL-METH-MONITORING)

| Metric ID | Population and purpose | Formula and source | Unit and frequency | Threshold or tolerance | Owner and forum | Breach action | Limitation or coverage gap | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| METRIC-AURORA-METH-001 | All monthly runs; total preservation | absolute(sum Allocation_i − ApprovedLoss) from calculator output | USD, every run | USD 0.00 after residual | ROLE-LOSS-OWNER / monthly control forum | Stop and open model issue | None | EVID-AURORA-MON-001 |
| METRIC-AURORA-METH-002 | All active portfolios; data coverage | unmapped exposure / total exposure | percentage, every run | 0.00% | ROLE-RISK-DATA-OWNER / data-risk forum | Stop and open data issue | Zero-exposure rows remain in denominator rules | EVID-AURORA-MON-002 |
| METRIC-AURORA-METH-003 | Portfolios with attributed outcomes; performance | absolute allocated share − attributed-loss share | percentage points, quarterly | Escalate above 15 points for 3 consecutive months | ROLE-LOSS-METHODOLOGY-OWNER / COMMITTEE-AURORA-MODEL-RISK | Assess methodology change or limitation | Not all losses have portfolio attribution | EVID-AURORA-OUTCOME-001 |

## Governance and approvals

### Governance decisions (TBL-METH-GOVERNANCE)

| Role or forum | Governance capacity or line | Decision or challenge | Scope and delegated authority | Date | Conditions, dissent, or limitations | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| ROLE-LOSS-METHODOLOGY-OWNER | First line owner | Recommends methodology and owns monitoring | Approved use only; no self-validation | 2026-07-18 | Accepts responsibility for LIM-AURORA-001 monitoring | EVID-AURORA-GOV-001 |
| ROLE-MODEL-VALIDATOR | Second line independent validation | Concludes validation and rates findings | Independent from development and use | 2026-07-15 | Validation passed with LIM-AURORA-001 retained | EVID-AURORA-VALIDATION-REPORT-001 |
| COMMITTEE-AURORA-MODEL-RISK | Management risk committee | Approves use, tier, limitations, and conditions | Both in-scope entities and stated purpose | 2026-07-24 | Quarterly outcome reporting required | EVID-AURORA-APPROVAL-METH-003 |
| INTERNAL-AUDIT-AURORA | Third line assurance | No management approval role | May independently assess governance and controls | Not applicable | Independence preserved | Audit plan reference only |

## Implementation mapping

### Methodology-to-production mapping (TBL-METH-IMPLEMENTATION)

| Mapping ID | Methodology object | Production asset and version | Process and control | Owner | Verification method and result | Change or release reference | Fallback and rollback | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MAP-AURORA-IMPL-001 | FORM-AURORA-ALLOC-001 | CALC-AURORA-ALLOC-001 v4.2 | PROC-AURORA-ALLOC-001 / CTRL-AURORA-CALC-001 | ROLE-QUANT-DEVELOPER | Independent benchmark exact to USD 0.01; pass | CHG-AURORA-2026-041 | Roll back to v4.1 only with approved compatibility assessment | EVID-AURORA-VALID-002 |
| MAP-AURORA-IMPL-002 | ALG-AURORA-RESIDUAL-001 | Function allocate_residual v4.2 | STEP-AURORA-002 / CTRL-AURORA-CALC-001 | ROLE-QUANT-DEVELOPER | Boundary and deterministic tie tests; pass | CHG-AURORA-2026-041 | Stop; manual residual assignment prohibited | EVID-AURORA-VALID-004 |

## Related processes, controls, policies, and standards

The methodology is implemented by `PROC-AURORA-ALLOC-001`, monitored by
`CTRL-AURORA-CALC-001`, and governed by `POL-DOC-GOV-001`, `STD-OPS-DOC-001`, and
`STD-CONTROL-EVID-001`.

### Obligation and authority mapping (TBL-METH-OBLIGATIONS)

| Mapping ID | Authority or obligation ID | Jurisdiction and legal entities | Applicability conclusion | Methodology requirement or use | Control and evidence | Interpretation owner | Review date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MAP-AURORA-MRM-001 | OBL-AURORA-MRM-001 | US; both in-scope entities | Applicable under fictional model-risk taxonomy | Inventory, intended use, independent validation, monitoring, and change control | CTRL-AURORA-CALC-001 / EVID-AURORA-VALIDATION-REPORT-001 | ROLE-MODEL-RISK-POLICY-OWNER | 2027-07-31 |
| MAP-AURORA-RDARR-001 | OBL-AURORA-RISK-DATA-001 | US; both in-scope entities | Applicable to risk-data lineage and reporting support | Data lineage, reconciliation, and limitation disclosure | CTRL-AURORA-INPUT-001 / EVID-AURORA-DATA-EXPOSURE-001 | ROLE-RISK-DATA-POLICY-OWNER | 2027-07-31 |

## Version history

### Version history and approvals (TBL-METH-VERSIONS)

| Version | Change class | Effective date | Change and impact | Development owner | Independent validator or challenger | Approving authority | Decision and conditions | Implementation status | Evidence | Supersedes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3.0 | Material | 2026-08-01 | Added model classification, prohibited uses, entity scope, full lineage, independent validation, monitoring, implementation, and obligation mapping | ROLE-LOSS-METHODOLOGY-OWNER | ROLE-MODEL-VALIDATOR | COMMITTEE-AURORA-MODEL-RISK | Approved with quarterly outcome reporting | CALC-AURORA-ALLOC-001 v4.2 verified and released | EVID-AURORA-APPROVAL-METH-003 | DOCV-AURORA-METH-0007-V2 |
