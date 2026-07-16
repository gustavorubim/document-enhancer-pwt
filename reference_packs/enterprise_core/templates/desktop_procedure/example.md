---
template_id: TPL-DESKTOP-001
document_type: desktop_procedure
reference_pack: enterprise_core
reference_pack_version: 1.0.0
document_id: DOC-AURORA-REPORT-0018
document_version: DOCV-AURORA-REPORT-0018-V1
status: effective
---

# Publish the Aurora Monthly Allocation Report

**Document ID:** DOC-AURORA-REPORT-0018
**Version:** DOCV-AURORA-REPORT-0018-V1
**Status:** effective
**Owner:** ROLE-REPORTING-OWNER
**Effective date:** 2026-02-01
**Next review date:** 2027-02-01

## Document metadata and governance

This fictional desktop procedure publishes an already approved Aurora allocation report. It is owned by `ROLE-REPORTING-OWNER`, approved by `ROLE-FINANCE-REVIEWER`, and applies to the restricted reporting workspace.

## Purpose

Publish the approved monthly allocation report to the reporting workspace and retain the publication evidence.

## Scope and applicability

Use this procedure for the monthly Aurora allocation after `CTRL-AURORA-001` has passed. Do not use it for drafts, unapproved reports, or external distribution.

## Prerequisites

The operator must have an approved report ID, a matching checksum, an approved finance review, and a closed reporting month. The operator verifies the starting state before opening the reporting application.

## Access and environment

Use the named least-privilege reporting account in the restricted workspace. Do not copy report content to personal storage or paste restricted data into chat, email, or browser tools.

## Tools and inputs

| Tool or input ID | Version | Owner | Purpose | Fallback |
| --- | --- | --- | --- | --- |
| SYS-AURORA-REPORTING-001 | 5.4 | ROLE-REPORTING-OWNER | Publish and retain report | Stop and escalate |
| OUT-AURORA-ALLOC-001 | 3.0 | ROLE-LOSS-OWNER | Approved report input | Request corrected artifact |

## Safety and data handling

Confirm the destination label is `restricted`. Never overwrite an effective report. If the checksum or approval does not match, stop at once and open `EXC-AURORA-UI-001`.

## Atomic actions

1. **ACT-AURORA-001 — Confirm approval.** Open the approval record and compare report ID, version, checksum, and month. Expected result: all four values match. Capture `EVID-AURORA-PUBLISH-001`.
2. **ACT-AURORA-002 — Open destination.** Sign in to `SYS-AURORA-REPORTING-001` and open the restricted Aurora workspace. Expected result: the workspace label is visible and no draft is selected.
3. **ACT-AURORA-003 — Upload report.** Select the approved report and confirm the displayed checksum. Expected result: the system accepts the file without a validation warning.
4. **ACT-AURORA-004 — Publish and verify.** Select Publish, then reopen the published record and compare the version and timestamp. Expected result: status is effective and the publication link is recorded.

| Action ID | Operator | Action | Expected result | Evidence | Next action |
| --- | --- | --- | --- | --- | --- |
| ACT-AURORA-001 | ROLE-REPORTING-ANALYST | Compare approval fields | All fields match | EVID-AURORA-PUBLISH-001 | ACT-AURORA-002 |
| ACT-AURORA-002 | ROLE-REPORTING-ANALYST | Open restricted workspace | Correct destination visible | EVID-AURORA-PUBLISH-002 | ACT-AURORA-003 |
| ACT-AURORA-003 | ROLE-REPORTING-ANALYST | Upload and validate checksum | No validation warning | EVID-AURORA-PUBLISH-003 | ACT-AURORA-004 |
| ACT-AURORA-004 | ROLE-REPORTING-ANALYST | Publish and reopen | Effective version visible | EVID-AURORA-PUBLISH-004 | Completion |

## Decisions and branching

If the approval fields do not match, follow `DEC-AURORA-001` to the safe stop. If the destination displays a draft or a different month, do not continue. If validation passes, continue to publish.

## Evidence capture

Retain the approval comparison, checksum confirmation, publication ID, and timestamp in `SYS-AURORA-REPORTING-001`. Screenshots may illustrate the result but the system record is authoritative.

| Evidence ID | Type | Producer | Storage reference | Retention |
| --- | --- | --- | --- | --- |
| EVID-AURORA-PUBLISH-001 | approval_record | ROLE-REPORTING-ANALYST | SYS-AURORA-REPORTING-001/publish | POL-REC-001, seven years |
| EVID-AURORA-PUBLISH-004 | system_log | SYS-AURORA-REPORTING-001 | SYS-AURORA-REPORTING-001/audit | POL-REC-001, seven years |

## Failure paths

| Failure ID | Symptom | Safe stop | Recovery | Escalation |
| --- | --- | --- | --- | --- |
| FAIL-AURORA-001 | Approval or checksum mismatch | Do not upload or publish | Request corrected approved artifact | ROLE-LOSS-OWNER |
| FAIL-AURORA-002 | Destination unavailable | Do not retry with another system | Preserve approved artifact and wait | ROLE-REPORTING-OWNER |

## Rollback and recovery

If the wrong version is published, stop further distribution, record the publication ID, and escalate to `ROLE-REPORTING-OWNER`. The owner follows the approved supersession process; the operator does not delete or overwrite records manually.

## Escalation

The operator escalates input mismatches to `ROLE-LOSS-OWNER`, system issues to `ROLE-REPORTING-OWNER`, and suspected unauthorized access to `ROLE-SECURITY-INCIDENT`. Each handoff includes the report ID, version, timestamp, and evidence reference.

## Completion criteria

The procedure is complete when the effective publication ID, matching version, timestamp, checksum, and evidence references are recorded and the Finance reviewer acknowledges the handoff.

## Related requirements, controls, and documents

This procedure implements `REQ-AURORA-001`, `REQ-AURORA-002`, `CTRL-AURORA-001`, `STD-OPS-DOC-001`, and `POL-REC-001`. It is downstream of `PROC-AURORA-ALLOC-001`.

## Version history and approvals

| Version | Effective date | Change | Approver |
| --- | --- | --- | --- |
| 1.0 | 2026-02-01 | Initial fictional publication procedure | ROLE-FINANCE-REVIEWER |
