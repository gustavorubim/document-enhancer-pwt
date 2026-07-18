# Monthly Credit Model Monitoring Process

## Purpose and scope

This fictional process monitors production model CM-17 for United States consumer-credit decisions.
It covers data quality, stability, discrimination, and outcome performance.

## Roles and timing

The Model Risk Analytics Manager owns the process. A Monitoring Analyst runs the review by the fifth
business day of each month, and an Independent Model Reviewer challenges the results by the eighth
business day.

## Inputs, systems, and steps

ModelHub supplies predictions and feature summaries. OutcomeLake supplies realized 90-day outcomes.
The analyst validates the observation window, calculates monitoring metrics, records limitations,
and submits the report to ModelGov.

## Controls, thresholds, and evidence

CTRL-MOD-404 includes a monthly reconciliation step: the Monitoring Analyst reconciles ModelHub
prediction records to OutcomeLake realized-outcome records by application ID before calculating
performance. A population stability index above 0.20 triggers enhanced review. ModelGov retains the
input snapshots, reconciliation log, calculations, challenge, and approval for eight years.

## Exceptions and escalation

Missing outcomes postpone performance conclusions but not data-quality reporting. Exception
approver: TBD. A data gap lasting more than 15 calendar days escalates to the Model Risk Committee.

## Output and completion

Completion requires a matched analysis population, documented metrics, independent challenge, and
Model Risk Analytics Manager approval in ModelGov.
