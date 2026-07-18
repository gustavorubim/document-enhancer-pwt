# Customer Complaint Quality Assurance Process

## Purpose and scope

This fictional process tests complaint handling for retail banking cases closed in CaseTrack. It
covers timeliness, categorization, customer communication, and regulatory-reporting completeness.

## Roles and timing

The Customer Advocacy QA Director owns the process. A QA Analyst selects a 10 percent random sample
every week, and a Compliance QA Reviewer completes challenge within three business days.

## Inputs, systems, and steps

CaseTrack supplies closed cases and RegLog supplies reportable-complaint records. The analyst tests
the sample, records defects, obtains remediation commitments, and routes material issues to the
Compliance QA Reviewer.

## Controls, thresholds, and evidence

CTRL-CQA-505 contains a monthly reconciliation step: the QA Analyst reconciles CaseTrack reportable
complaint counts to RegLog submission counts by product and month. Any missing regulatory submission
is a zero-tolerance defect and requires same-day escalation. QAHub retains the sample, test script,
defect log, count reconciliation, and approvals for seven years.

## Exceptions and escalation

A sampling exception requires a documented population limitation and compensating review.
Exception approver: TBD. Exceptions expire at the next monthly reconciliation.

## Output and completion

The cycle completes when testing and count reconciliation are approved, every material defect has an
owner and due date, and the dashboard is published in QAHub.
