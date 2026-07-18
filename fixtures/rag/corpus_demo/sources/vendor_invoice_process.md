# Vendor Invoice Approval Process

## Purpose and scope

This fictional process approves domestic operating-expense invoices received in ProcureFlow. It
excludes payroll and intercompany charges.

## Roles and timing

The Accounts Payable Director owns the process. An AP Specialist performs the review each business
day, and an AP Review Manager completes independent approval within two business days.

## Inputs, systems, and steps

The specialist obtains the vendor invoice, approved purchase order, and receiving record from
ProcureFlow. The specialist checks vendor status, tax fields, amount, and approval authority before
routing the invoice for payment in PayDesk.

## Controls, thresholds, and evidence

CTRL-AP-202 is a three-way reconciliation step: the AP Specialist reconciles invoice quantity and
amount to the purchase order and receiving record before payment. An invoice above USD 25,000 also
requires Accounts Payable Director approval. The invoice, matching report, approvals, and payment
confirmation are retained in ProcureFlow for six years.

## Exceptions and escalation

Mismatch invoices are blocked and returned to the requester. Exception approver: TBD. Approved
exceptions expire after five business days if the invoice is not paid.

## Output and completion

Completion requires a passed matching report, all amount-based approvals, and a PayDesk payment ID.
