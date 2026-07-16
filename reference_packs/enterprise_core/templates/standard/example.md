---
template_id: TPL-STANDARD-001
document_type: standard
reference_pack: enterprise_core
reference_pack_version: 2.0.0
document_id: DOC-AURORA-CONTROL-0011
document_version: DOCV-AURORA-CONTROL-0011-V2
status: effective
---

# Aurora Controlled Data Exchange Standard

**Document ID:** DOC-AURORA-CONTROL-0011
**Version:** DOCV-AURORA-CONTROL-0011-V2
**Status:** effective
**Owner:** ROLE-DATA-GOVERNANCE
**Approval authority:** ROLE-ENTERPRISE-DATA-COMMITTEE
**Effective date:** 2026-07-16
**Next review date:** 2027-07-16
**Legal entities:** ORG-AURORA-BANK-NA; ORG-AURORA-HOLDCO
**Jurisdictions:** US; enterprise global minimum where locally adopted
**Risk tier:** high
**Information classification:** restricted

## Document metadata and governance

This fictional standard governs controlled exchanges used by the Aurora process family. It is not a regulatory interpretation. Legal and Compliance validate applicability before a business applies it in a legal entity or jurisdiction.

| Governance field | Required value | Accountable role | Evidence or system of record |
| --- | --- | --- | --- |
| Content owner | ROLE-DATA-GOVERNANCE | ROLE-CHIEF-DATA-OFFICER | SYS-POLICY-INVENTORY-001 |
| Approval authority | ROLE-ENTERPRISE-DATA-COMMITTEE | ROLE-COMMITTEE-SECRETARY | EVID-AURORA-STD-APPROVAL-002 |
| Independent challenge | ROLE-OPERATIONAL-RISK | ROLE-CHIEF-RISK-OFFICER | EVID-AURORA-STD-CHALLENGE-002 |
| Applicability validation | US entities listed above; local adoption required elsewhere | ROLE-COMPLIANCE-ADVISORY | EVID-AURORA-STD-APPLICABILITY-002 |

## Purpose

Define minimum controls for transferring Aurora exposure or loss data between approved systems while preserving accuracy, completeness, timeliness, lineage, confidentiality, recoverability, and evidence.

## Scope and applicability

This standard applies to scheduled, event-driven, and manual exchanges containing Aurora exposure or loss data for the listed legal entities, including exchanges operated by affiliates or third parties. It excludes public samples and synthetic test data that cannot be linked to customers, accounts, employees, or production positions. A stricter local law, regulatory commitment, policy, or contractual term prevails.

## Terms and definitions

**MUST** and **MUST NOT** identify mandatory requirements. **SHOULD** identifies an expected practice that requires a documented rationale if not followed. A **controlled exchange** is a transfer with an approved source, destination, owner, data contract, control set, and evidence. **Authoritative evidence** is the tamper-evident system record; a screenshot alone is not authoritative evidence.

## Standard principles

Data is owned end to end, reconciled to an authoritative source, limited to an approved purpose, protected in transit and at rest, recoverable within the supported service objective, and subject to first-line execution, second-line challenge, and independent audit.

## Normative requirements

| Requirement ID | Authority or obligation | Normative statement | Entity, jurisdiction, and applicability | Accountable role | Risk and control | Evidence and monitoring | Exception path |
| --- | --- | --- | --- | --- | --- | --- | --- |
| REQ-AURORA-001 | OBL-AURORA-DATA-001 | A controlled exchange MUST use an approved source, destination, interface, data contract, and service owner. | Listed entities; every production exchange | ROLE-DATA-OWNER | RISK-AURORA-DATA-001; CTRL-AURORA-EXCHANGE-001 | EVID-AURORA-EXCHANGE-001; every exchange | EXC-AURORA-STD-001 |
| REQ-AURORA-002 | OBL-AURORA-DATA-002 | A controlled exchange MUST record source and destination IDs, source checksum, record count, control total, legal entity, as-of date, transfer owner, destination acknowledgement, and processing timestamp. | Listed entities; every production exchange | ROLE-DATA-OWNER | RISK-AURORA-DATA-002; CTRL-AURORA-EXCHANGE-002 | EVID-AURORA-EXCHANGE-001; completeness target 100% | EXC-AURORA-STD-001 |
| REQ-AURORA-003 | OBL-AURORA-RESILIENCE-001 | A failed, late, incomplete, or unreconciled transfer MUST stop dependent publication and trigger the documented incident and recovery path. | Listed entities; transfers supporting financial or risk reporting | ROLE-REPORTING-OWNER | RISK-AURORA-REPORTING-001; CTRL-AURORA-EXCHANGE-003 | EVID-AURORA-FAILURE-001; immediate alert | No business override |
| REQ-AURORA-004 | OBL-AURORA-SECURITY-001 | Production credentials MUST NOT be shared, embedded in files, or reused outside the approved service identity. | All operators, systems, and third parties | ROLE-TECHNOLOGY-OWNER | RISK-AURORA-ACCESS-001; CTRL-AURORA-ACCESS-001 | EVID-AURORA-ACCESS-001; quarterly recertification | Emergency access under POL-ACCESS-001 only |
| REQ-AURORA-005 | OBL-AURORA-THIRD-PARTY-001 | A third-party exchange MUST have an accountable internal owner, contract controls, exit and contingency provisions, incident duties, and ongoing performance monitoring. | Any external or affiliate service provider | ROLE-THIRD-PARTY-OWNER | RISK-AURORA-TPRM-001; CTRL-AURORA-TPRM-001 | EVID-AURORA-TPRM-001; quarterly review | EXC-AURORA-STD-002 |

## Accountable roles

| Role ID | Line or capacity | Responsibility | Decision or approval authority | Independence or segregation requirement | Escalation |
| --- | --- | --- | --- | --- | --- |
| ROLE-DATA-OWNER | First line | Owns data quality, exchange execution, reconciliation, and remediation | Accepts operational readiness; cannot approve own exception | Operator and reviewer must be different people for high-risk manual exchanges | ROLE-CHIEF-DATA-OFFICER |
| ROLE-TECHNOLOGY-OWNER | First line | Owns service security, availability, change, recovery, and logs | Approves technical release within policy | Privileged access approval is independent of requestor | ROLE-CHIEF-INFORMATION-OFFICER |
| ROLE-OPERATIONAL-RISK | Second line | Challenges design, thresholds, incidents, and risk acceptance | Concurs with material exceptions | Independent of control operation | ROLE-CHIEF-RISK-OFFICER |
| ROLE-COMPLIANCE-ADVISORY | Second line | Validates regulatory and jurisdiction applicability | Concurrence where an obligation is regulatory | Independent of standard ownership | ROLE-CHIEF-COMPLIANCE-OFFICER |
| ROLE-INTERNAL-AUDIT | Third line | Provides independent assurance under its audit plan | No operating or exception authority | Organizationally independent | ROLE-AUDIT-COMMITTEE |

## Evidence and records

| Evidence ID | Requirement and control | Type and producer | Period and legal entity | Authoritative storage and integrity | Retention and hold | Access owner |
| --- | --- | --- | --- | --- | --- | --- |
| EVID-AURORA-EXCHANGE-001 | REQ-AURORA-001/002; CTRL-AURORA-EXCHANGE-001/002 | Signed transfer and reconciliation log; SYS-AURORA-REPORTING-001 | Each exchange and entity | SYS-AURORA-REPORTING-001/exchanges; immutable ID and checksum | RET-AURORA-001; hold overrides disposition | ROLE-DATA-OWNER |
| EVID-AURORA-FAILURE-001 | REQ-AURORA-003; CTRL-AURORA-EXCHANGE-003 | Incident and recovery record; ROLE-REPORTING-OWNER | Each incident and impacted entity | SYS-INCIDENT-001; immutable incident ID | RET-AURORA-INCIDENT-001; hold-aware | ROLE-OPERATIONAL-RESILIENCE |
| EVID-AURORA-TPRM-001 | REQ-AURORA-005; CTRL-AURORA-TPRM-001 | Due diligence and monitoring record; ROLE-THIRD-PARTY-OWNER | Contract lifecycle and entity | SYS-TPRM-001; access logged | RET-AURORA-TPRM-001; hold-aware | ROLE-THIRD-PARTY-RISK |

## Exceptions and waivers

Exceptions cannot override law, regulatory order, customer protection, record hold, security prohibition, or the publication stop in `REQ-AURORA-003`. The requestor documents affected entities, residual risk, duration, remediation, testing, and downstream disclosure before implementation.

| Exception ID | Requirements affected | Authority and second-line concurrence | Risk and reason | Compensating controls | Expiry or review date | Downstream impact and disclosure |
| --- | --- | --- | --- | --- | --- | --- |
| EXC-AURORA-STD-001 | REQ-AURORA-001/002 | ROLE-ENTERPRISE-DATA-COMMITTEE; ROLE-OPERATIONAL-RISK | Approved destination outage; elevated manual error risk | Dual approval, encrypted managed transfer, same-day reconciliation, no publication until complete | 24 hours; no automatic renewal | Flag dependent report and notify ROLE-REPORTING-OWNER |
| EXC-AURORA-STD-002 | REQ-AURORA-005 | ROLE-THIRD-PARTY-RISK-COMMITTEE; ROLE-OPERATIONAL-RISK | Time-bound contract remediation | Reduced data set, enhanced monitoring, tested exit plan | Committee-approved date no later than 90 days | Disclose to affected control and service owners |

## Enforcement and nonconformance

The first line blocks dependent use, preserves evidence, records the issue, assesses impacted entities and reports, and starts remediation. Material or repeated breaches escalate to the Chief Data Officer and Operational Risk; Compliance assesses notification obligations. Closure requires root cause, validated remediation, evidence, and independent challenge proportional to severity.

## Controls and monitoring

| Control ID | Requirements and risks | Owner and operator | Frequency | Procedure and evidence | Metric, threshold, and breach response | Independent testing |
| --- | --- | --- | --- | --- | --- | --- |
| CTRL-AURORA-EXCHANGE-001 | REQ-AURORA-001; RISK-AURORA-DATA-001 | ROLE-DATA-OWNER; ROLE-DATA-OPERATIONS | Every exchange | Validate approved endpoints and data contract; EVID-AURORA-EXCHANGE-001 | Unapproved endpoint target 0; block and incident | Second-line thematic review annually |
| CTRL-AURORA-EXCHANGE-002 | REQ-AURORA-002; RISK-AURORA-DATA-002 | ROLE-DATA-OWNER; SYS-AURORA-REPORTING-001 | Every exchange | Reconcile checksum, counts, totals, entity, date, and acknowledgement | Complete evidence target 100%; block downstream use | Control Testing samples quarterly |
| CTRL-AURORA-EXCHANGE-003 | REQ-AURORA-003; RISK-AURORA-REPORTING-001 | ROLE-REPORTING-OWNER; SYS-WORKFLOW-001 | Every failure | Enforce publication dependency and open incident | Unblocked failed transfers target 0; critical escalation in 15 minutes | Resilience exercise semiannually |
| CTRL-AURORA-TPRM-001 | REQ-AURORA-005; RISK-AURORA-TPRM-001 | ROLE-THIRD-PARTY-OWNER; ROLE-TPRM-ANALYST | Quarterly and event-driven | Review service, incidents, concentration, controls, and exit readiness | Overdue high findings target 0; committee escalation | Second-line review annually |

## Related policies, standards, and documents

This standard implements `POL-DOC-GOV-001`, `POL-REC-001`, `STD-CONTROL-EVID-001`, and `STD-OPS-DOC-001`; it supports `PROC-AURORA-ALLOC-001` and the Aurora desktop publication procedure. Conflicts are resolved under the policy hierarchy, with applicable law and binding regulatory direction prevailing.

## Implementation guidance

Process owners map every exchange to the controlled inventory, replace examples with approved production identifiers, establish service and recovery objectives, train operators, test failure paths, and obtain Legal or Compliance validation for obligation mappings. Examples in this section are informative and do not create additional requirements.

## Regulatory and policy obligation mapping

| Obligation ID | Authority or source | Citation or internal reference | Interpretation and applicability | Implementing requirement or control | Evidence owner | Legal or Compliance validation |
| --- | --- | --- | --- | --- | --- | --- |
| OBL-AURORA-DATA-001 | POL-DATA-GOV-001 | Internal policy section 4 | Approved ownership and interfaces for listed entities | REQ-AURORA-001; CTRL-AURORA-EXCHANGE-001 | ROLE-DATA-OWNER | EVID-AURORA-STD-APPLICABILITY-002 |
| OBL-AURORA-DATA-002 | POL-DATA-GOV-001 | Internal policy section 6 | Complete lineage and reconciliation for risk and finance data | REQ-AURORA-002; CTRL-AURORA-EXCHANGE-002 | ROLE-DATA-OWNER | EVID-AURORA-STD-APPLICABILITY-002 |
| OBL-AURORA-RESILIENCE-001 | POL-OP-RES-001 | Internal policy section 5 | Protect critical reporting from failed dependencies | REQ-AURORA-003; CTRL-AURORA-EXCHANGE-003 | ROLE-REPORTING-OWNER | EVID-AURORA-STD-APPLICABILITY-002 |
| OBL-AURORA-SECURITY-001 | POL-ACCESS-001 | Internal policy section 7 | Protect nonpublic data and privileged identities | REQ-AURORA-004; CTRL-AURORA-ACCESS-001 | ROLE-TECHNOLOGY-OWNER | EVID-AURORA-STD-APPLICABILITY-002 |
| OBL-AURORA-THIRD-PARTY-001 | POL-TPRM-001 | Internal policy section 4 | Maintain accountable ownership and lifecycle controls | REQ-AURORA-005; CTRL-AURORA-TPRM-001 | ROLE-THIRD-PARTY-OWNER | EVID-AURORA-STD-APPLICABILITY-002 |

## Review and conformance statement

`ROLE-DATA-GOVERNANCE` reviews the standard annually and upon material law, regulatory, risk, service, data, or technology change. First-line owners attest quarterly; second-line Risk and Compliance report exceptions, overdue issues, and control breaches to `ROLE-ENTERPRISE-DATA-COMMITTEE`. Conformance means all applicable requirements are met or covered by a valid, unexpired exception; silence is not conformance.

## Version history and approvals

| Version | Effective date | Change and impact assessment | Content owner | Risk or Compliance concurrence | Approval authority | Supersedes |
| --- | --- | --- | --- | --- | --- | --- |
| 2.0 | 2026-07-16 | Enterprise governance baseline; major template and requirement expansion | ROLE-DATA-GOVERNANCE | ROLE-OPERATIONAL-RISK; ROLE-COMPLIANCE-ADVISORY | ROLE-ENTERPRISE-DATA-COMMITTEE | 1.0 |
