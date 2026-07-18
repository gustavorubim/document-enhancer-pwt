# Quarterly Privileged Access Recertification Process

## Purpose and scope

This fictional process certifies privileged access for the OrionCloud, LedgerOne, and ControlVault
production environments. Service accounts governed by the machine-identity standard are excluded.

## Roles and timing

The IAM Governance Lead owns the process. The Access Review Coordinator opens each campaign on the
first business day after quarter end. Application Owners must certify access within ten business
days, and Information Security reviews overdue cases.

## Inputs, systems, and steps

AccessHub provides the privileged-entitlement population and HumanCore provides active-worker
status. Application Owners certify, revoke, or time-limit each entitlement. The coordinator tracks
completion and confirms that approved removals were executed in AccessHub.

## Controls, thresholds, and evidence

CTRL-IAM-303 requires documented quarterly certification of every in-scope privileged entitlement.
The permitted threshold is zero uncertified entitlements at campaign closure. AccessHub stores the
population, certifications, revocation tickets, and closure report for seven years.

## Exceptions and escalation

An overdue certification suspends the entitlement until an authorized decision is recorded.
Exception approver: TBD. Every exception expires within 30 calendar days.

## Output and completion

The campaign closes after all entitlements have a certification outcome, all required revocations
are confirmed, and the IAM Governance Lead signs the closure report.
