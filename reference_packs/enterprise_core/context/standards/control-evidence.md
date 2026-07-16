# Enterprise Control Evidence Standard

**Reference ID:** STD-CONTROL-EVID-001
**Version:** 2.0
**Status:** Active
**Effective:** 2026-07-16
**Owner:** Enterprise Controls Office
**Applicability:** Documents tagged `controlled_activity`

## Purpose

This fictional standard defines the minimum information needed to demonstrate that a control is
appropriately designed, executed over the stated population and period, reviewed, and connected to
its risk, obligation, issue, and retention context. Evidence must permit an informed reviewer,
independent tester, auditor, or supervisor to reconstruct the control without relying on the
operator's memory.

## Control design record

Every key or material control **MUST** have a stable control ID and a design record that identifies:

- control objective, risk IDs, obligation or policy IDs, and relevant assertions;
- legal entities, businesses, products, processes, systems, data, jurisdictions, and populations;
- control owner, performer, reviewer, escalation owner, and line-of-defense responsibilities;
- preventive, detective, or corrective nature and manual, automated, or hybrid operation;
- event trigger or frequency, timing, cut-off, service level, and tolerance;
- procedure, input, data lineage, selection method, decision rule, expected output, and evidence;
- segregation-of-duties and privileged-access requirements;
- failure criteria, residual risk, escalation, issue linkage, and recovery action;
- system of record, evidence schema, retention schedule, confidentiality, and legal-hold handling;
- dependencies, including end-user computing, models, third parties, subcontractors, and fallback;
- design approval, effective date, next review, change triggers, and related test plan.

Control descriptions **MUST** distinguish the control objective from the execution steps and from
management monitoring. Phrases such as `review as appropriate` or `investigate timely` are invalid
unless the scope, threshold, timeframe, decision authority, and required evidence are defined.

## Execution evidence

Each execution **MUST** capture:

1. control ID and design version;
2. performer identity and role, reviewer identity and role, and event timestamps with timezone;
3. business date, as-of date, period, cut-off, legal entity, and population boundaries;
4. source systems, source extracts, record counts, control totals, lineage, and integrity checks;
5. sampling method and sample population when sampling is permitted;
6. procedure performed, criteria applied, items reviewed, and automated job or query version;
7. result, identified exceptions, false positives, unresolved items, and conclusion;
8. reviewer challenge, disposition, approval or rejection, and completion time;
9. issue, incident, risk acceptance, remediation, and retest references where applicable; and
10. authoritative storage reference, classification, retention schedule, and checksum or immutable
    audit-trail reference where supported.

Evidence **MUST** demonstrate completeness and accuracy of the population before it demonstrates
that selected items passed. A control cannot be reported as passed when the population is unknown,
materially incomplete, or outside tolerance without an approved and visible exception.

## Review and segregation of duties

1. The reviewer **MUST** have the authority, competence, information, and independence required by
   the control design.
2. A reviewer **MUST NOT** merely confirm that a file exists. Review evidence **MUST** show the
   criteria evaluated, challenge performed, exceptions considered, and decision reached.
3. Maker-checker controls **MUST** prevent the same identity from performing and approving the same
   execution unless an approved emergency-access process records the conflict and compensating
   review.
4. Automated controls **MUST** have governed logic, access, configuration, change, scheduling,
   failure alerting, and data-interface controls. Automation does not eliminate ownership or review.

## Data, model, and end-user-computing evidence

1. Evidence derived from risk or financial data **MUST** identify authoritative sources,
   transformations, reconciliations, critical data elements, data owners, quality thresholds, and
   unresolved limitations.
2. Model-dependent controls **MUST** identify the model or methodology inventory ID, approved use,
   version, validation status, limitations, overlays, and monitoring status.
3. Spreadsheet, query, script, or other end-user-computing evidence **MUST** identify the governed
   asset, version, owner, access, change history, input/output checks, and independent review level.
4. A manual adjustment or overlay **MUST** identify the pre-adjustment value, adjustment, rationale,
   authority, evidence, affected period, expiry, and downstream impact.

## Exceptions, failures, and issues

1. A failed control **MUST** be recorded as failed or incomplete; it **MUST NOT** be converted to
   pass through narrative qualification.
2. Each exception **MUST** identify the affected item or population, rule, cause, risk impact,
   owner, disposition, approver, due date, compensating control, and closure evidence.
3. A material, repeat, systemic, aged, or risk-appetite-breaching failure **MUST** route to the
   approved issue, incident, breach, and escalation frameworks.
4. Management risk acceptance **MUST** be explicit, time-bounded, within delegated authority, and
   linked to residual risk and monitoring. It does not erase the control failure.
5. Remediation closure **MUST** include validation or retest by an appropriately independent party.

## Evidence integrity and storage

Evidence **MUST** be retained in the named system of record, protected against unauthorized change,
and accessible for review throughout the retention period. Links **MUST** resolve for authorized
reviewers. Email, chat, screenshots, or locally stored files **MUST NOT** be the only authoritative
evidence when a source-system record, data extract, query result, or approval object is available.

Evidence replicated to another system **MUST** preserve the authoritative-source reference,
metadata, classification, lineage, and chain of custody. Redaction or transformation **MUST** be
controlled and must not prevent reconstruction of the original decision.

## Third-party controls

For a third-party-performed or -supported control, the bank **MUST** identify the retained bank
owner, contractual obligation, service and control boundary, provider and material subcontractors,
evidence access, monitoring, incident notification, assurance report limitations, complementary
user-entity controls, concentration, resilience, and exit or substitution plan. An assurance report
**MUST NOT** substitute for evaluating whether its scope, period, controls, exceptions, and user
responsibilities cover the bank's actual use.

## Monitoring and testing

Control reporting **MUST** define the complete population and disclose late, missing, failed,
overridden, and unknown executions. Key metrics **MUST** include calculation logic, data source,
period, threshold, owner, escalation, and coverage limitations. Control owners **MUST** periodically
review design effectiveness; independent testing **MUST** assess design and operating effectiveness
at a risk-based frequency.

## Relationship to retention and documentation

`POL-REC-001` controls retention, legal hold, and disposition when it is more specific or longer.
`POL-DOC-GOV-001` controls ownership, lifecycle, approval, and exception governance.
`STD-OPS-DOC-001` controls how control requirements are expressed in governed documents.
