# Enterprise Operational Documentation Standard

**Reference ID:** STD-OPS-DOC-001
**Version:** 2.0
**Status:** Active
**Effective:** 2026-07-16
**Owner:** Enterprise Documentation Council
**Applicability:** Process, methodology, standard, and desktop-procedure documents

## Purpose

This fictional standard translates enterprise document-governance policy into testable authoring,
traceability, execution, evidence, and publication requirements suitable for a large,
internationally active bank.

## Document control and applicability

1. Each document **MUST** use a stable document ID, a distinct version ID, an approved document type,
   and the lifecycle states defined by `POL-DOC-GOV-001`.
2. The governance block **MUST** identify owner, steward, accountable executive, approving authority,
   effective and review dates, classification, risk tier, legal entities, jurisdictions, businesses,
   authoritative repository, and superseded version.
3. Scope **MUST** state inclusions, exclusions, intended users, affected operations or customers,
   transition population, and local-addendum rules.
4. Materiality **MUST** be explicit. Documents supporting a critical operation, regulatory report,
   material model, key control, or significant third party **MUST** identify that dependency.

## Authority and obligation mapping

1. Normative content **MUST** map to stable internal policy, standard, regulatory-obligation, risk,
   control, and evidence IDs where applicable.
2. Each external obligation mapping **MUST** include authority, citation or inventory ID,
   jurisdiction, legal entity, applicability conclusion, owner, implementing requirement, control,
   evidence, and review date.
3. Guidance, law, regulation, policy, standard, and source-document statements **MUST** remain
   distinguishable. External guidance **MUST NOT** be relabeled as binding law.
4. Unresolved conflicts and interpretation questions **MUST** be visible and assigned; they **MUST
   NOT** be resolved by stylistic rewriting.

## Roles, decision rights, and three lines

1. Roles **MUST** use stable IDs and distinguish accountable executive, business owner, performer,
   reviewer, approver, challenger, data owner, system owner, issue owner, and escalation authority.
2. Role tables **MUST** identify the applicable line of defense or governance capacity without
   treating Internal Audit as a management control owner.
3. Decision rights **MUST** state delegated authority, quorum or committee requirements where
   applicable, conflicts of interest, escalation, and non-delegable decisions.
4. A RACI label alone is insufficient; the document **MUST** describe the decision or deliverable for
   which the role is responsible.

## Executable actions and decisions

1. Each executable action **MUST** have a stable ID, performer, prerequisite, input, system or tool,
   action, output, expected result, control, evidence, completion condition, timing, and failure path.
2. Each decision **MUST** identify the condition, data source, operator, threshold and unit,
   evaluation period, outcome, branch target, authority, override rule, and evidence.
3. Qualifiers such as `material`, `timely`, `periodic`, `significant`, `reasonable`, or `as needed`
   **MUST** be defined through a threshold, taxonomy, decision authority, or visible `TBD`.
4. Dates **MUST** use ISO 8601. Timestamps **MUST** include timezone. Amounts, percentages, counts,
   rates, and durations **MUST** identify units, currency, basis, period, and rounding where relevant.

## Risk, control, evidence, and issue traceability

1. A control **MUST** link objective, risk, obligation, owner, performer, reviewer, frequency or
   trigger, procedure, population, evidence, threshold, failure response, issue route, and retention.
2. A process or procedure **MUST** identify safe-stop, escalation, recovery, and resumption criteria
   for reasonably foreseeable failure states.
3. An exception **MUST** identify authority, affected scope, risk, residual risk, compensating
   control, monitoring, expiry, downstream impact, and closure evidence.
4. An issue **MUST** identify severity, root cause, owner, actions, milestones, due date, status,
   validation, escalation, and closure authority when referenced as a remediation mechanism.
5. Evidence requirements **MUST** meet `STD-CONTROL-EVID-001` and retention **MUST** meet
   `POL-REC-001`.

## Data, models, systems, and third parties

1. Data tables **MUST** identify source system, data asset or element, owner, steward, legal entity,
   period, classification, lineage, transformation, quality rule, reconciliation, and fallback.
2. Model or methodology references **MUST** identify inventory ID, approved use, version, owner,
   validation status, limitations, monitoring, and implementation mapping.
3. Systems, calculators, scripts, and end-user-computing assets **MUST** identify version, owner,
   access, change control, input/output checks, and recovery or fallback.
4. Third-party dependencies **MUST** identify the provider, service, criticality, data and system
   access, material subcontractors where known, contract or service-level reference, monitoring,
   concentration or substitutability concern, incident route, and exit or continuity plan.

## Operational resilience

Documents supporting a critical operation **MUST** identify the operation, impact tolerance or
approved disruption threshold, end-to-end dependencies, legal entities, locations, people,
facilities, technology, data, third parties, recovery time and point objectives where applicable,
manual workaround, communication route, test evidence, and resumption authority. Business
continuity and disaster recovery references **MUST** be executable and current; a link alone is not
sufficient.

## Methodology and model-risk documentation

A methodology that meets the enterprise definition of a model **MUST** map to the model inventory
and applicable model-risk governance. It **MUST** distinguish development, use, independent
validation, approval, implementation verification, ongoing monitoring, outcome analysis,
limitations, overrides, and change. Vendor models remain subject to documentation and risk-based
review even when source code or development data is restricted.

## Change and release management

1. Material changes **MUST** state rationale, impacted obligations, risks, controls, data, models,
   systems, processes, customers, legal entities, reports, training, tests, approvals, transition,
   fallback, and effective date.
2. Version history **MUST** distinguish editorial, non-material, material, emergency, and local-
   addendum changes.
3. Implementation evidence **MUST** show that affected users, controls, systems, inventories, and
   downstream documents were updated before or within the approved transition period.
4. Emergency changes **MUST** retain safe implementation evidence and retrospective approval.

## Tables, diagrams, and machine-readable content

1. Authoritative tables **MUST** have stable IDs, descriptive titles, defined columns, row-level
   stable IDs, source or owner, and period or as-of context where relevant.
2. A diagram **MUST NOT** be the only representation of an authoritative sequence, decision, control,
   or dependency. Each diagram **MUST** have an accessible caption and corresponding text or table.
3. Mermaid nodes and edges **MUST** reference stable IDs. Decorative or inferred edges **MUST NOT**
   be promoted to authoritative relationships.
4. Cross-references **MUST** use stable IDs and exact titles. `Above`, `below`, `usual process`, and
   undocumented hyperlinks are not sufficient references.

## Review, approval, and publication quality gates

Before approval, the owner **MUST** confirm:

- complete governance metadata and applicability;
- resolved or explicitly escalated authority conflicts;
- obligation-to-requirement-to-control-to-evidence traceability;
- identified risks, controls, exceptions, issues, and resilience dependencies;
- data, model, system, end-user-computing, and third-party mappings;
- first-line ownership and required independent challenge;
- executable actions, measurable decisions, and observable completion criteria;
- current references, links, training, testing, retention, and publication controls;
- no invented fact, silent omission, expired waiver, or hidden `TBD`; and
- accessible headings, tables, diagrams, and reading order.

## Relationship to policy

These requirements implement `POL-DOC-GOV-001`. If formatting convenience or source-document style
conflicts with lifecycle, accountability, traceability, or approval requirements, the policy wins
and the conflict remains visible.
