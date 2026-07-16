# Enterprise Records Retention and Evidence Preservation Policy

**Reference ID:** POL-REC-001
**Version:** 2.0
**Status:** Active
**Effective:** 2026-07-16
**Owner:** Enterprise Records Management
**Approval authority:** Enterprise Risk and Control Committee
**Applicability:** Documents tagged `records` and evidence retained by a governed process

## Purpose and policy outcome

This fictional policy requires complete, authentic, accessible, protected, and disposition-
controlled records for governed decisions and activities. The intended outcome is that the bank can
reconstruct what was approved, performed, reviewed, reported, changed, excepted, or remediated for
the applicable legal entity, jurisdiction, population, and period.

## Records in scope

The following are records when generated or received as part of governed work:

- approved policies, standards, methodologies, processes, procedures, versions, and addenda;
- board and committee decisions, minutes, challenge, conditions, and attestations;
- regulatory obligation mappings, interpretations, submissions, correspondence, and examinations;
- risk assessments, risk acceptances, control designs, execution evidence, testing, and monitoring;
- model development, validation, change, approval, implementation, monitoring, and limitation records;
- source data, lineage, reconciliations, adjustments, reports, calculations, and sign-offs;
- issues, incidents, exceptions, waivers, remediation plans, closure evidence, and lessons learned;
- third-party due diligence, contracts, monitoring, incidents, concentration analysis, and exit plans;
- training, access, publication, distribution, and acknowledgement records; and
- metadata and audit trails needed to establish authenticity, integrity, custody, and disposition.

Transient working material is not automatically a record, but it **MUST NOT** be deleted when it is
the only evidence of a decision, calculation, review, obligation interpretation, control execution,
or legal hold.

## Retention authority and period

1. Each record class **MUST** map to an approved retention-schedule ID, legal entities,
   jurisdictions, triggering event, retention period, owner, system of record, and disposition rule.
2. The longest applicable legal, regulatory, litigation, tax, contractual, supervisory, or internal
   policy period **MUST** control.
3. The fictional enterprise fallback for governed operational evidence is seven years after the end
   of the fiscal year in which the record was finalized. The fallback **MUST NOT** shorten a mapped
   schedule and **MUST NOT** be represented as a universal legal requirement.
4. If the applicable schedule, trigger, or jurisdiction is unresolved, the record **MUST** be
   preserved and escalated to Records Management. Unknown retention never authorizes destruction.
5. A change to a retention period **MUST** preserve evidence of the prior rule, the approving
   authority, effective date, affected population, and migration or reclassification action.

## Legal hold and preservation

1. A legal, regulatory, investigation, audit, complaint, or supervisory hold **MUST** suspend routine
   disposition for the covered population regardless of the normal retention date.
2. Hold notices **MUST** identify scope, custodians, systems, date range, issuing authority,
   acknowledgement, collection status, and release authority.
3. Custodians and system owners **MUST** preserve content and metadata without alteration and
   **MUST** escalate unavailable, incomplete, encrypted, or inaccessible records.
4. Only the authorized Legal or Records function **MAY** release a hold. Release evidence **MUST**
   precede resumed disposition.

## Record metadata and lineage

Every governed record **MUST** identify, as applicable:

- stable record or evidence ID and record class;
- producing person, role, system, and legal entity;
- event time and timezone, business date, period or as-of date, and finalization time;
- source population, source systems, transformations, checksum or integrity control, and lineage;
- related document version, obligation, risk, control, model, process, issue, exception, or decision;
- confidentiality, privacy, residency, and access classification;
- system of record, storage reference, format, retention schedule, disposition date, and hold status;
- reviewer, review outcome, approval, and any identified deficiency.

An email subject, screenshot, local file path, or ticket number alone is insufficient metadata when it
does not identify the underlying population, decision, version, and authoritative record.

## Integrity, accessibility, and protection

1. Records **MUST** be stored in an approved system of record with access control, audit logging,
   backup, recovery, and change protection appropriate to classification and criticality.
2. Evidence **MUST** remain readable, searchable, exportable, and linked to its metadata throughout
   the retention period. Proprietary formats **MUST** have a documented preservation or migration
   plan.
3. Manual evidence **MUST** retain the source artifact, execution context, and reviewer decision.
   Screenshots **MUST NOT** be the sole evidence when machine records or source data are available.
4. Record copies transferred across entities, jurisdictions, or providers **MUST** preserve lineage,
   access restrictions, residency requirements, and authoritative-source designation.
5. Encryption keys, technical dependencies, and third-party services needed to retrieve a record
   **MUST** be governed for the full retention period.

## Privacy, secrecy, and minimization

Records **MUST** contain only data necessary for the governed purpose and evidence requirement.
Banking secrecy, privacy, customer confidentiality, employee confidentiality, market-sensitive
information, and cross-border restrictions **MUST** be applied before collection, replication,
sharing, or export. Redaction **MUST** be authorized, reversible where required, and traceable to the
unredacted authoritative record.

## Third-party and cloud records

Contracts and operating procedures for third-party recordkeeping **MUST** address ownership,
location, access, format, audit rights, security, retention, legal hold, regulator access where
applicable, subcontractors, portability, incident notification, termination, return, and verified
destruction. Outsourcing record storage **MUST NOT** outsource the bank's accountability.

## Disposition

1. Disposition **MUST** be authorized, logged, reproducible, and blocked by holds, unresolved scope,
   active issues, or pending migration exceptions.
2. The disposition process **MUST** confirm the schedule, trigger, population, legal entity,
   jurisdiction, hold status, approvals, method, and completion evidence.
3. Destruction **MUST** be appropriate to classification and media and **MUST** address replicas,
   exports, backups, and provider-held copies according to the approved schedule and technical
   capability.
4. Failed or partial disposition **MUST** create an issue and remain visible until remediated.

## Monitoring and assurance

Records Management **MUST** monitor unmapped record classes, overdue disposition, inaccessible
records, hold failures, unauthorized copies, provider gaps, stale ownership, and failed retrieval
tests. Material gaps **MUST** be escalated through issue management. Independent assurance **MAY**
test the design and operating effectiveness of the records program without assuming management
ownership.

## Regulatory alignment boundary

This policy is a fictional global baseline. It is not a retention schedule and does not determine
the legal period for any specific record. Legal, Regulatory Compliance, Privacy, Tax, and Records
Management **MUST** approve jurisdiction- and record-specific mappings.

## Precedence note

This policy controls minimum preservation and disposition requirements when
`STD-CONTROL-EVID-001` is less specific. It never authorizes deletion, overrides a legal hold, or
reduces a longer applicable period.
