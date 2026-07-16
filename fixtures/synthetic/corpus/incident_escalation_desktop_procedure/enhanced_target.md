# Incident Escalation Desktop Procedure

Status: fictional evaluation target

## Prerequisites and access

The operator needs access to Beacon Monitor, the Incident Console, and the service roster. A screenshot is referenced as the authoritative click path.

## Atomic actions

Open the alert, acknowledge it, and assign the incident to the on-call role. If it is customer-impacting, notify the communications lead.

## Severity decision

Use the service-level table to choose a fifteen-minute or one-hour response. The table does not define the customer-impacting test.

## Failure path and rollback

If the console is unavailable, use the phone tree and record the incident in the offline worksheet. Restore the primary record after service returns.

## Evidence and completion

Save the alert ID and notification timestamp. The procedure does not define the final completion condition or evidence retention.

## Reviewer-approved fixture clarifications

- Q-INCIDENT-001: In Beacon Monitor, open the alert detail, copy the alert ID, severity, affected service, and first-observed timestamp into Incident Console. (provenance: answer://fixture/Q-INCIDENT-001)
- Q-INCIDENT-002: When Incident Console is unavailable, the operator opens the offline worksheet, activates the phone tree, and reconciles entries after service restoration. (provenance: answer://fixture/Q-INCIDENT-002)
- Q-INCIDENT-003: The procedure completes only when the alert is acknowledged, required notifications are timestamped, ownership is assigned, and the record is reconciled. (provenance: answer://fixture/Q-INCIDENT-003)
