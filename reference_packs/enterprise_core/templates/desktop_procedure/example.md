---
template_id: TPL-DESKTOP-001
document_type: desktop_procedure
reference_pack: enterprise_core
reference_pack_version: 2.0.0
document_id: DOC-AURORA-REPORT-0018
document_version: DOCV-AURORA-REPORT-0018-V2
status: effective
---

# Publish the Aurora Monthly Allocation Report

**Document ID:** DOC-AURORA-REPORT-0018
**Version:** DOCV-AURORA-REPORT-0018-V2
**Status:** effective
**Owner:** ROLE-REPORTING-OWNER
**Approval authority:** ROLE-FINANCE-CONTROL-COMMITTEE
**Effective date:** 2026-07-16
**Next review date:** 2027-07-16
**Legal entities:** ORG-AURORA-BANK-NA; ORG-AURORA-HOLDCO
**Jurisdictions:** US
**Information classification:** restricted
**Criticality:** high; supports monthly financial and risk reporting

## Document metadata and governance

This fictional procedure publishes an already approved Aurora allocation report. It is not an authorization to change, approve, or externally distribute the report. Local Legal and Compliance validate applicability before adoption.

| Governance field | Required value | Accountable role | Evidence or system of record |
| --- | --- | --- | --- |
| Content owner | ROLE-REPORTING-OWNER | ROLE-CONTROLLER | SYS-POLICY-INVENTORY-001 |
| Procedure approval | ROLE-FINANCE-CONTROL-COMMITTEE | ROLE-COMMITTEE-SECRETARY | EVID-AURORA-DESK-APPROVAL-002 |
| Independent control challenge | ROLE-FINANCIAL-CONTROL | ROLE-CONTROL-OFFICER | EVID-AURORA-DESK-CHALLENGE-002 |
| Operator qualification | Current training and named entitlement | ROLE-REPORTING-OWNER | SYS-TRAINING-001; SYS-IAM-001 |

## Purpose

Publish the approved monthly allocation report to the restricted reporting workspace, verify the effective record, and retain evidence without changing an approved value or bypassing maker-checker controls.

## Scope and applicability

Use this procedure only for the listed US entities, the scheduled monthly Aurora allocation, and the approved production environment after `CTRL-AURORA-001` passes. Do not use it for drafts, ad hoc reporting, external distribution, a different entity, a reopened period, or disaster recovery unless an approved recovery playbook has been activated.

## Prerequisites

The named maker and checker have current training and separate approved entitlements. The period is closed; upstream reconciliations and `CTRL-AURORA-001` passed; the report ID, entity, month, version, checksum, classification, and Finance approval match; the reporting service is available; no active legal hold or incident prohibits processing; and the recovery contact is on duty.

## Access and environment

Use the named least-privilege reporting account, managed device, approved network, and production workspace. Never share credentials or use emergency access for routine work. If emergency access is approved, link the access record to the incident and obtain retrospective review. Lock the session when unattended and terminate it after evidence capture.

## Tools and inputs

| Tool or input ID | Approved version or as-of date | Owner and authoritative source | Classification and legal entity | Purpose and integrity check | Availability or fallback |
| --- | --- | --- | --- | --- | --- |
| SYS-AURORA-REPORTING-001 | Production release 5.4; approved change record | ROLE-TECHNOLOGY-OWNER; CMDB | restricted; both listed entities | Publish and retain report; validate service banner and audit logging | Stop; use recovery playbook only if formally activated |
| OUT-AURORA-ALLOC-001 | Approved month-end version | ROLE-LOSS-OWNER; SYS-AURORA-LEDGER-001 | restricted; entity in file metadata | Report input; verify checksum, totals, entity, period, and approval | Request a corrected, re-approved artifact |
| EVID-AURORA-FIN-APPROVAL-001 | Current reporting month | ROLE-FINANCE-REVIEWER; SYS-WORKFLOW-001 | confidential; same entity and period as report | Independent publication approval; validate immutable workflow ID | Stop and return to Finance review |

## Safety and data handling

Confirm the destination, legal entity, period, and `restricted` label before upload. Never overwrite or delete an effective record, change approved content, download to unmanaged storage, or paste data into chat, email, browser, or unapproved tools. A mismatch, control failure, unexpected prompt, unavailable audit log, or suspected unauthorized access is a safe-stop condition.

## Atomic actions

1. **ACT-AURORA-001 — Confirm authority and approval.** Compare report ID, entity, period, version, checksum, classification, and approval workflow. Expected result: every value matches exactly and the approval is effective.
2. **ACT-AURORA-002 — Validate destination and service.** Sign in with the named account, confirm the production banner, restricted workspace, entity, open audit logging, and service status. Expected result: all indicators match the approved run context.
3. **ACT-AURORA-003 — Stage and validate.** Upload the approved artifact to staging and compare the system-computed checksum, record count, control total, entity, period, and version. Expected result: exact match and no warning.
4. **ACT-AURORA-004 — Obtain checker release.** The independent checker reviews the staged values and authorizes publication in the workflow. Expected result: immutable checker decision linked to the staged object.
5. **ACT-AURORA-005 — Publish and verify.** Publish once, reopen the effective record, and compare publication ID, entity, period, version, checksum, timestamp, status, and audit event. Expected result: one effective record with no duplicate or unresolved warning.
6. **ACT-AURORA-006 — Handoff and close.** Link the evidence set, notify the downstream owner, close the task, and terminate the session. Expected result: acknowledged handoff and complete authoritative evidence.

| Action ID | Operator and segregation | Exact action | Expected result and tolerance | Control and evidence | Time or service objective | Next action or safe stop |
| --- | --- | --- | --- | --- | --- | --- |
| ACT-AURORA-001 | ROLE-REPORTING-ANALYST; maker cannot approve | Compare authority, metadata, checksum, and approval | Exact match; no tolerance | CTRL-AURORA-PUBLISH-001; EVID-AURORA-PUBLISH-001 | Before staging | ACT-AURORA-002 or DEC-AURORA-001 |
| ACT-AURORA-002 | ROLE-REPORTING-ANALYST | Validate account, environment, entity, audit log, and service | All approved indicators visible | CTRL-AURORA-PUBLISH-002; EVID-AURORA-PUBLISH-002 | Within approved run window | ACT-AURORA-003 or safe stop |
| ACT-AURORA-003 | ROLE-REPORTING-ANALYST | Stage file and compare system values | Exact checksum, count, total, entity, period, version | CTRL-AURORA-PUBLISH-003; EVID-AURORA-PUBLISH-003 | Before checker review | ACT-AURORA-004 or DEC-AURORA-002 |
| ACT-AURORA-004 | ROLE-FINANCE-REVIEWER; different person from maker | Review staged object and record release decision | Approved immutable decision linked to object | CTRL-AURORA-PUBLISH-004; EVID-AURORA-PUBLISH-004 | Before publication cutoff | ACT-AURORA-005 or return to maker |
| ACT-AURORA-005 | ROLE-REPORTING-ANALYST | Publish once and reopen effective record | One exact effective record; no duplicate | CTRL-AURORA-PUBLISH-005; EVID-AURORA-PUBLISH-005 | Within 15 minutes of checker release | ACT-AURORA-006 or FAIL-AURORA-003 |
| ACT-AURORA-006 | ROLE-REPORTING-ANALYST | Link evidence, obtain handoff acknowledgement, close task | Evidence complete and downstream acknowledgement recorded | CTRL-AURORA-PUBLISH-006; EVID-AURORA-PUBLISH-006 | Within 30 minutes of publication | Completion or escalation |

## Decisions and branching

If the approval fields do not match, stop without uploading, record the mismatch, and return the artifact to `ROLE-LOSS-OWNER` and `ROLE-FINANCE-REVIEWER`; never correct an approved value in the publication tool. If the destination, audit status, or staged validation is wrong, stop and escalate. Only an exact, independently approved match may proceed.

| Decision ID | Condition and authoritative input | Decision owner | Approved branch | Prohibited branch | Evidence and escalation |
| --- | --- | --- | --- | --- | --- |
| DEC-AURORA-001 | Any authority, report, entity, period, version, checksum, classification, or approval mismatch | ROLE-FINANCE-REVIEWER | Stop; return for correction and re-approval | Edit, substitute, upload, or publish | EVID-AURORA-MISMATCH-001; notify ROLE-LOSS-OWNER immediately |
| DEC-AURORA-002 | Staging validation warning or control-total mismatch | ROLE-REPORTING-OWNER | Preserve staging evidence; remove unapproved staged object under controlled cleanup; investigate | Override warning or publish | EVID-AURORA-MISMATCH-002; open issue within 15 minutes |
| DEC-AURORA-003 | Exact match and checker approval | ROLE-FINANCE-REVIEWER | Release ACT-AURORA-005 | Maker self-approval | EVID-AURORA-PUBLISH-004 |

## Evidence capture

The authoritative evidence is the immutable workflow, system audit, and publication record. Screenshots may illustrate an interface state but cannot replace logs or expose restricted content. The evidence set must link the action, decision, control, operator, checker, entity, period, timestamp, and outcome.

| Evidence ID | Action, decision, and control | Type and producer | Period and legal entity | Authoritative storage and integrity | Retention and hold | Reviewer |
| --- | --- | --- | --- | --- | --- | --- |
| EVID-AURORA-PUBLISH-001 | ACT-AURORA-001; CTRL-AURORA-PUBLISH-001 | Approval comparison; SYS-WORKFLOW-001 | Reporting month and entity | Immutable workflow ID and checksum | RET-AURORA-REPORTING-001; hold overrides disposition | ROLE-FINANCE-REVIEWER |
| EVID-AURORA-PUBLISH-004 | ACT-AURORA-004; DEC-AURORA-003; CTRL-AURORA-PUBLISH-004 | Checker decision; SYS-WORKFLOW-001 | Reporting month and entity | Immutable decision and identity log | RET-AURORA-REPORTING-001; hold-aware | ROLE-FINANCIAL-CONTROL |
| EVID-AURORA-PUBLISH-005 | ACT-AURORA-005; CTRL-AURORA-PUBLISH-005 | Publication and audit log; SYS-AURORA-REPORTING-001 | Reporting month and entity | Immutable publication ID, timestamp, checksum, and audit event | RET-AURORA-REPORTING-001; hold-aware | ROLE-REPORTING-OWNER |
| EVID-AURORA-PUBLISH-006 | ACT-AURORA-006; CTRL-AURORA-PUBLISH-006 | Handoff acknowledgement; SYS-WORKFLOW-001 | Reporting month and entity | Immutable task and acknowledgement IDs | RET-AURORA-REPORTING-001; hold-aware | ROLE-REPORTING-OWNER |

## Failure paths

| Failure ID and severity | Symptom or trigger | Immediate safe stop and containment | Recovery owner and steps | Data, customer, reporting, and downstream assessment | Escalation time and role | Evidence and closure authority |
| --- | --- | --- | --- | --- | --- | --- |
| FAIL-AURORA-001; high | Approval, entity, period, version, or checksum mismatch | Do not stage or publish; preserve inputs | ROLE-LOSS-OWNER corrects and reruns approval | Assess source, impacted report, and other uses; no customer distribution | Immediate to ROLE-REPORTING-OWNER and ROLE-FINANCE-REVIEWER | EVID-AURORA-MISMATCH-001; ROLE-FINANCIAL-CONTROL closes |
| FAIL-AURORA-002; high | Destination unavailable, wrong entity, audit log unavailable, or unexpected privilege | End action; protect input; do not use alternate system | ROLE-TECHNOLOGY-OWNER restores approved service or activates tested recovery plan | Assess reporting deadline, data exposure, service dependencies, and regulatory timing | 15 minutes to Technology and Operational Resilience; Security immediately if access suspected | Incident record; ROLE-OPERATIONAL-RESILIENCE closes recovery |
| FAIL-AURORA-003; critical | Wrong or duplicate effective publication | Stop distribution; do not delete or overwrite; preserve IDs and logs | ROLE-REPORTING-OWNER invokes controlled supersession and reconciliation | Assess every downstream consumer, entity, report, customer impact, and notification duty | Immediately to Controller, Operational Risk, Compliance, and Technology | EVID-AURORA-INCIDENT-001; ROLE-CONTROLLER approves closure with second-line concurrence |

## Rollback and recovery

Before publication, remove a rejected staged object only through the logged cleanup workflow and verify that no effective record exists. After publication, the operator cannot roll back by deletion or overwrite. The Reporting owner invokes controlled supersession, reconciles the replacement, identifies all downstream use, obtains checker approval, and validates recovery against the reporting deadline and service objective. Every recovery action remains linked to the incident.

## Escalation

| Escalation ID | Severity or trigger | Notify | Target time | Required handoff evidence | Decision authority | External notification assessment |
| --- | --- | --- | --- | --- | --- | --- |
| ESC-AURORA-PUBLISH-001 | Input or approval mismatch | ROLE-REPORTING-OWNER; ROLE-LOSS-OWNER; ROLE-FINANCE-REVIEWER | Immediate; issue within 15 minutes | Report ID, entity, period, version, checksum, approval ID, mismatch | ROLE-FINANCE-REVIEWER decides re-approval | ROLE-COMPLIANCE-ADVISORY if reporting deadline or prior use affected |
| ESC-AURORA-PUBLISH-002 | System, audit, availability, or access issue | ROLE-TECHNOLOGY-OWNER; ROLE-OPERATIONAL-RESILIENCE; ROLE-SECURITY-INCIDENT when relevant | 15 minutes; security immediately | User, system, time, symptom, evidence IDs, data exposed | Incident commander | Legal and Compliance assess notification |
| ESC-AURORA-PUBLISH-003 | Wrong or duplicate publication | ROLE-CONTROLLER; ROLE-OPERATIONAL-RISK; ROLE-COMPLIANCE-ADVISORY; ROLE-TECHNOLOGY-OWNER | Immediate | Publication IDs, audit log, consumers, entity, period, amounts, containment | ROLE-CONTROLLER with second-line concurrence | Legal and Compliance document regulatory and customer notification decision |

## Completion criteria

| Completion ID | Observable condition and tolerance | Evidence | Maker | Checker or approver | Downstream handoff and status |
| --- | --- | --- | --- | --- | --- |
| COMPLETE-AURORA-001 | Exactly one effective publication; entity, period, version, checksum, totals, timestamp, and status match; zero unresolved warnings | EVID-AURORA-PUBLISH-001/004/005 | ROLE-REPORTING-ANALYST | ROLE-FINANCE-REVIEWER | ROLE-DOWNSTREAM-REPORTING acknowledges effective ID |
| COMPLETE-AURORA-002 | Evidence linked, task closed, session terminated, and no open incident or exception permits unnoticed continuation | EVID-AURORA-PUBLISH-006 | ROLE-REPORTING-ANALYST | ROLE-REPORTING-OWNER | SYS-WORKFLOW-001 status complete |

## Related requirements, controls, and documents

This procedure implements `REQ-AURORA-001`, `REQ-AURORA-002`, `REQ-AURORA-003`, `CTRL-AURORA-001`, `STD-OPS-DOC-001`, `STD-CONTROL-EVID-001`, and `POL-REC-001`; it is downstream of `PROC-AURORA-ALLOC-001` and must remain aligned with the approved incident and recovery playbooks.

## Regulatory and policy obligation mapping

| Obligation ID | Authority or source | Citation or internal reference | Applicability | Implementing action or control | Evidence owner | Legal or Compliance validation |
| --- | --- | --- | --- | --- | --- | --- |
| OBL-AURORA-PUBLISH-001 | POL-FIN-REPORT-001 | Internal policy section 5 | Listed entities and monthly allocation report | ACT-AURORA-001/004/005; CTRL-AURORA-PUBLISH-001/004/005 | ROLE-REPORTING-OWNER | EVID-AURORA-DESK-APPLICABILITY-002 |
| OBL-AURORA-RECORDS-001 | POL-REC-001 | Internal policy sections 4-8 | All procedure evidence | Evidence capture; ACT-AURORA-006 | ROLE-RECORDS-OWNER | EVID-AURORA-DESK-APPLICABILITY-002 |
| OBL-AURORA-RESILIENCE-002 | POL-OP-RES-001 | Internal policy sections 5-7 | Publication service and reporting deadline | Failure paths; rollback and escalation | ROLE-OPERATIONAL-RESILIENCE | EVID-AURORA-DESK-APPLICABILITY-002 |
| OBL-AURORA-ACCESS-001 | POL-ACCESS-001 | Internal policy sections 6-8 | Operators, checkers, and service identities | Access and environment; ACT-AURORA-002 | ROLE-TECHNOLOGY-OWNER | EVID-AURORA-DESK-APPLICABILITY-002 |

## Version history and approvals

| Version | Effective date | Change and operational impact | Content owner | Risk or Compliance concurrence | Approval authority | Supersedes |
| --- | --- | --- | --- | --- | --- | --- |
| 2.0 | 2026-07-16 | Enterprise governance, maker-checker, resilience, escalation, and evidence expansion; operator retraining required | ROLE-REPORTING-OWNER | ROLE-FINANCIAL-CONTROL; ROLE-COMPLIANCE-ADVISORY | ROLE-FINANCE-CONTROL-COMMITTEE | 1.0 |
