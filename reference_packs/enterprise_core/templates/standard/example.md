---
template_id: TPL-STANDARD-001
document_type: standard
reference_pack: enterprise_core
reference_pack_version: 1.0.0
document_id: DOC-AURORA-CONTROL-0011
document_version: DOCV-AURORA-CONTROL-0011-V1
status: effective
---

# Aurora Controlled Data Exchange Standard

**Document ID:** DOC-AURORA-CONTROL-0011
**Version:** DOCV-AURORA-CONTROL-0011-V1
**Status:** effective
**Owner:** ROLE-DATA-GOVERNANCE
**Effective date:** 2026-03-01
**Next review date:** 2027-03-01

## Document metadata and governance

This fictional standard is approved by `ROLE-DATA-GOVERNANCE-CHAIR` and applies to controlled exchanges used by the Aurora process family. Approval evidence is `EVID-AURORA-STD-APPROVAL-001`.

## Purpose

Define minimum controls for moving Aurora data between approved systems while preserving lineage, confidentiality, and evidence.

## Scope and applicability

This standard applies to scheduled or manual exchanges containing Aurora exposure or loss data. It excludes public samples and one-time synthetic test data. It is tagged `governed_document` and `controlled_activity`.

## Terms and definitions

**MUST** means an enforceable requirement. **Controlled exchange** means a transfer with a named source, destination, owner, and evidence. **KPI** means key performance indicator.

## Standard principles

Exchanges use least privilege, named ownership, immutable source checksums, and a recoverable failure path. A screenshot can support review but cannot be the only evidence for an authoritative transfer.

## Normative requirements

| Requirement ID | Normative statement | Applicability | Accountable role | Evidence | Exception path |
| --- | --- | --- | --- | --- | --- |
| REQ-AURORA-001 | A controlled exchange MUST use an approved source and destination system. | All Aurora exchanges | ROLE-DATA-GOVERNANCE | EVID-AURORA-EXCHANGE-001 | EXC-AURORA-STD-001 |
| REQ-AURORA-002 | A controlled exchange MUST record source checksum, as-of date, and transfer owner. | All Aurora exchanges | ROLE-DATA-GOVERNANCE | EVID-AURORA-EXCHANGE-001 | EXC-AURORA-STD-001 |
| REQ-AURORA-003 | A failed transfer MUST stop downstream publication and escalate to the data owner. | Failed transfer | ROLE-DATA-OWNER | EVID-AURORA-FAILURE-001 | No override |

## Accountable roles

| Role ID | Responsibility | Approval authority | Escalation |
| --- | --- | --- | --- |
| ROLE-DATA-GOVERNANCE | Owns the standard and exceptions | ROLE-DATA-GOVERNANCE-CHAIR | ROLE-RISK-OFFICER |
| ROLE-DATA-OWNER | Owns source data and transfer execution | None | ROLE-DATA-GOVERNANCE |

## Evidence and records

| Evidence ID | Type | Producer | Storage reference | Retention |
| --- | --- | --- | --- | --- |
| EVID-AURORA-EXCHANGE-001 | system_log | ROLE-DATA-OWNER | SYS-AURORA-REPORTING-001/exchanges | POL-REC-001, seven years |
| EVID-AURORA-FAILURE-001 | incident_record | ROLE-DATA-OWNER | SYS-AURORA-REPORTING-001/incidents | POL-REC-001, seven years |

## Exceptions and waivers

`EXC-AURORA-STD-001` permits a temporary destination outage workaround for no more than 24 hours. It requires approval by `ROLE-DATA-GOVERNANCE-CHAIR`, a reason, a compensating control, and expiry at the next business day.

| Exception ID | Authority | Reason | Expiry or review date | Downstream impact |
| --- | --- | --- | --- | --- |
| EXC-AURORA-STD-001 | ROLE-DATA-GOVERNANCE-CHAIR | Destination outage | Next business day | Publication remains blocked until reconciliation |

## Enforcement and nonconformance

The data owner blocks publication when a requirement fails, records the evidence, and escalates to Data Governance. Repeated failure opens a risk review with `ROLE-RISK-OFFICER`.

## Controls and monitoring

`CTRL-AURORA-EXCHANGE-001` checks a checksum and destination acknowledgement for every transfer. `METRIC-AURORA-EXCHANGE-001` measures the percentage of exchanges with complete evidence; the target is 100%.

## Related policies, standards, and documents

This standard implements `STD-CONTROL-EVID-001`, is governed by `POL-DOC-GOV-001` and `POL-REC-001`, and supports `PROC-AURORA-ALLOC-001`.

## Implementation guidance

The process owner maps each transfer to `SYS-AURORA-LEDGER-001` or `SYS-AURORA-REPORTING-001`, records the checksum in the transfer log, and retains the acknowledgement with the monthly report.

## Review and conformance statement

`ROLE-DATA-GOVERNANCE` reviews conformance quarterly. A conforming exchange has all required fields and no unresolved blocker. The first review is due 2026-06-30.

## Version history and approvals

| Version | Effective date | Change | Approver | Decision |
| --- | --- | --- | --- | --- |
| 1.0 | 2026-03-01 | Initial fictional standard | ROLE-DATA-GOVERNANCE-CHAIR | Approved |
