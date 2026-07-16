# Enterprise Document Governance Policy

**Reference ID:** POL-DOC-GOV-001
**Version:** 2.0
**Status:** Active
**Effective:** 2026-07-16
**Owner:** Enterprise Documentation Council
**Approval authority:** Enterprise Risk and Control Committee
**Applicability:** Governed internal documents tagged `governed_document`

## Purpose and policy outcome

This fictional policy establishes the minimum governance framework for policies, standards,
methodologies, processes, and desktop procedures used by a large, internationally active banking
group. Its outcome is a controlled document inventory in which authority, applicability,
accountability, risk, evidence, change, and approval can be traced across legal entities and
jurisdictions.

This policy governs documentation. It does not replace the bank's board charters, risk appetite
framework, legal and regulatory obligations inventory, records schedule, model inventory, control
taxonomy, issue-management framework, or jurisdiction-specific requirements.

## Policy hierarchy and authority

1. A governed document **MUST** state its document type and its position in the authority hierarchy.
2. A policy **MUST** state mandatory principles and accountable executive ownership. A standard
   **MUST** translate policy into testable requirements. A methodology **MUST** define a reproducible
   analytical approach. A process **MUST** define end-to-end work and controls. A desktop procedure
   **MUST** define operator-level execution.
3. A lower-precedence document **MUST NOT** weaken, silently reinterpret, or override a higher-
   precedence obligation.
4. A local or legal-entity addendum **MAY** impose a stricter requirement. It **MUST** identify the
   governing jurisdiction, legal entity, source obligation, owner, and relationship to the global
   document.
5. A conflict between authorities **MUST** be recorded, escalated to the designated interpretation
   authority, and resolved before the affected document becomes effective.

## Applicability and proportionality

Every governed document **MUST** identify:

- in-scope and out-of-scope legal entities, branches, businesses, products, services, processes,
  booking locations, data domains, and jurisdictions;
- intended users and affected customers or stakeholders where relevant;
- confidentiality classification and authoritative publication location;
- risk tier, materiality basis, and whether it supports a critical operation, regulatory report,
  material model, or significant third-party arrangement;
- effective date, transition population, and any approved local variance; and
- the method used to determine proportional governance and review frequency.

`Global` is not sufficient scope by itself. A global document **MUST** define how local obligations,
entity restrictions, and stricter jurisdictional requirements are identified and incorporated.

## Accountability and independent challenge

1. The board or a delegated board committee retains the responsibilities assigned to it by the
   bank's governance framework. Documentation **MUST NOT** reassign board accountability to
   management.
2. The accountable executive **MUST** ensure that the document remains aligned with strategy, risk
   appetite, legal obligations, resources, and the operating model.
3. The business owner, as first line, **MUST** own implementation, controls, evidence, issues, and
   timely remediation.
4. Independent risk management and compliance, as second line, **MUST** provide risk-based review
   and credible challenge where the document affects material risk, regulatory obligations,
   customers, critical operations, or risk acceptance.
5. Internal Audit, as third line, **MUST** remain independent. Internal Audit **MUST NOT** be assigned
   first-line ownership, routine control performance, or management approval responsibilities.
6. Legal, Privacy, Information Security, Records Management, Data Governance, Finance, Model Risk,
   Operational Resilience, and Third-Party Risk **MUST** be consulted when their governed domain is
   affected.
7. Approval and challenge roles **MUST** be performed by authorized people or committees with
   sufficient stature, competence, capacity, and freedom from conflicting responsibilities.

## Minimum governance metadata

A governed document **MUST** include, in a controlled metadata block:

- stable document ID and version ID;
- title, document type, status, confidentiality, language, and authoritative repository;
- business owner, document steward, accountable executive, and approving authority;
- legal-entity, business, jurisdiction, and risk-tier applicability;
- source policy, standard, obligation, risk, control, model, data, system, process, and third-party
  references as applicable;
- approval date, effective date, next review date, transition period, and superseded version;
- materiality assessment, change classification, and change-ticket reference; and
- records category, retention-schedule reference, and legal-hold status where applicable.

A missing governance value **MUST** remain `TBD`, a blocking question, or an approved waiver. It
**MUST NOT** be inferred or invented.

## Regulatory and policy traceability

1. A document that implements a legal, regulatory, supervisory, contractual, or policy obligation
   **MUST** map that obligation to stable internal requirement and control IDs.
2. The mapping **MUST** identify the governing authority, citation or inventory ID, jurisdiction,
   legal entity, applicability conclusion, accountable owner, implementing requirement, control,
   evidence, and review date.
3. External guidance **MUST NOT** be presented as binding law. The bank's approved obligations
   inventory and Legal or Compliance interpretation determine internal applicability.
4. One source obligation **MAY** map to multiple requirements and controls. The relationship **MUST**
   remain visible rather than being collapsed into a narrative claim.
5. Regulatory change, enforcement, audit, loss-event, risk-appetite, and business-change triggers
   **MUST** be assessed for document impact.

## Lifecycle, review, and change control

1. Allowed lifecycle states are `draft`, `in_review`, `approved`, `effective`, `superseded`, and
   `retired`. A document **MUST NOT** be used as authoritative while in draft or after
   retirement.
2. Each document **MUST** have a risk-based review interval. Material policies, standards,
   methodologies, critical-operation processes, and high-risk procedures **MUST** be reviewed at
   least annually unless a stricter requirement applies.
3. Event-driven review **MUST** occur after a material regulatory change, risk-appetite change,
   new product, significant model or technology change, critical third-party change, control
   failure, material issue, operational disruption, legal-entity restructuring, audit finding, or
   change in data lineage.
4. A material change **MUST** create a new version, undergo applicable challenge and approval, define
   implementation and training actions, preserve the prior version, and record downstream impacts.
5. An emergency change **MUST** have a named authority, bounded duration, compensating controls,
   retrospective review, and a decision to ratify or reverse.
6. A rename **MUST NOT** create a new stable identity. A merger, split, or scope transfer **MUST**
   preserve lineage among predecessor and successor IDs.

## Approval and publication

1. Approval evidence **MUST** identify the document/version, decision, approver role, approver
   identity, date/time, conditions, dissent or unresolved matters, and evidence reference.
2. Material documents **MUST** retain evidence of first-line ownership and applicable second-line
   challenge before approval. Board or committee approval **MUST** be recorded when required by the
   governance framework.
3. Segregation of duties **MUST** prevent an author from being the sole approver of a material
   document.
4. Only the authoritative repository **MAY** mark a version effective. Distribution copies **MUST**
   identify the authoritative source and display their uncontrolled-copy status where applicable.
5. Superseded content **MUST** be removed from active navigation without destroying required history.

## Exceptions and waivers

An exception **MUST** identify the affected requirement, legal entities and jurisdictions, reason,
risk assessment, residual risk, compensating controls, accountable owner, approving authority,
start date, expiry or review date, monitoring, downstream impacts, and closure evidence.

An exception **MUST NOT** waive a prohibition that the governing authority declares non-waivable.
Open-ended waivers are prohibited. Expired waivers are invalid and **MUST** trigger escalation.

## Inventory, attestation, and oversight reporting

1. Governed documents **MUST** be registered in an inventory that supports ownership, status,
   applicability, dependency, review, exception, and supersession reporting.
2. Owners **MUST** attest at the assigned cadence that content, mappings, controls, links, access,
   and training remain current.
3. Oversight reporting **MUST** include overdue reviews, expired exceptions, unresolved conflicts,
   orphaned ownership, unimplemented changes, failed controls, and material coverage gaps.
4. Metrics **MUST** be defined with population, numerator, denominator, period, data source, owner,
   threshold, and escalation action. A green status **MUST NOT** conceal excluded or unknown scope.

## Regulatory alignment boundary

This fictional policy reflects general governance themes found in Basel Committee corporate-
governance, risk-data, operational-resilience, operational-risk, third-party-risk, compliance, and
internal-audit publications and in US large-bank supervisory materials. Those publications are
context, not incorporated obligations. Applicability **MUST** be determined through the bank's
approved regulatory-change and obligations-management processes.

## Precedence note

This policy supplies the lifecycle and accountability minimum. `STD-OPS-DOC-001` may add executable
formatting, metadata, traceability, and evidence detail, but it cannot remove or weaken these policy
requirements.
