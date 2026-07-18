# Daily Payment Settlement Process

## Purpose and scope

This fictional process settles Northstar Bank card payments for United States operations. It starts
after the AtlasPay daily cutoff and ends when settlement evidence is approved in ControlVault.

## Roles and timing

The Treasury Operations Manager owns the process. A Settlement Analyst performs the work every
business day at 7:00 AM Eastern Time, and a Treasury Control Officer independently reviews it by
10:00 AM Eastern Time.

## Inputs, systems, and steps

The analyst exports the prior-day AtlasPay settlement file and the LedgerOne cash-ledger report.
The analyst validates file dates, calculates totals, investigates breaks, and submits the evidence
packet in ControlVault. The reviewer approves or rejects the packet before funds are released.

## Controls, thresholds, and evidence

CTRL-PAY-101 is a daily reconciliation step: the Settlement Analyst reconciles AtlasPay settlement
totals to LedgerOne cash-ledger totals. Differences greater than USD 10,000 stop release and are
escalated to the Treasury Operations Manager. Evidence consists of both exports, the signed break
log, and reviewer approval. ControlVault retains the packet for seven years.

## Exceptions and escalation

An unresolved break remains on hold. Exception approver: TBD. No exception may remain open longer
than two business days.

## Output and completion

The process completes only when totals agree within USD 10,000, the reviewer approves the packet,
and the settlement-release confirmation is stored in ControlVault.
