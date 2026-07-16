# `enterprise_core` 2.0 reference-pack map

`enterprise_core` is the fictional default pack used by the M2 reference lane. Version 2.0 provides a G-SIB-scale governance baseline for highly regulated banking documentation while remaining institution-neutral and safe for local tests. It contains no proprietary policy text and does not claim legal, regulatory, or supervisory compliance.

Before adoption, an institution must replace the Aurora fixtures, assign approved owners and committees, apply its policy hierarchy and records schedule, and obtain Legal and Compliance validation for every jurisdiction, legal entity, regulatory interpretation, notification duty, and exception authority.

## Contents

| Area | Files | Contract exercised |
| --- | --- | --- |
| Ontology | `ontology/entity_types.yaml`, `relationship_types.yaml`, `id_patterns.yaml`, `controlled_terms.yaml` | Bounded objects, allow-listed relationships, stable IDs, controlled vocabulary, graph layers, minimum graph-critical fields |
| Process | `templates/process/` | Legal-entity scope, three-lines roles, governed inputs, atomic steps, decisions, risks, controls, evidence, exceptions, resilience dependencies, metrics, obligation mapping, retention, and approvals |
| Methodology | `templates/methodology/` | Intended and prohibited use, classification and tiering, lineage, transformations, models and formulas, parameters and overlays, limitations, independent validation, monitoring, production mapping, obligation mapping, and approvals |
| Standard | `templates/standard/` | Normative terms, stable requirement IDs, authority and applicability, accountable and independent roles, risks and controls, evidence integrity, enforcement, exceptions, obligation mapping, conformance, and version governance |
| Desktop procedure | `templates/desktop_procedure/` | Named access, maker-checker segregation, authoritative inputs, atomic actions, approved and prohibited branches, evidence integrity, safe stops, impact assessment, rollback, timed escalation, completion, and obligation mapping |
| Context | `context/` | Enterprise document governance, records and legal holds, operational documentation, control evidence, banking style, and glossary |
| Rubrics | `rubrics/` | Common 0–4 dimensions, hard blockers, waiver semantics, enterprise-governance criteria, and complete document-type mappings |

## Governance model

The pack expects documents to identify the applicable legal entities and jurisdictions; accountable executives and delegated approval forums; first-line owners and operators; independent second-line Risk and Compliance challenge; and third-line Internal Audit assurance without assigning Internal Audit operating responsibility. It also expects stable mappings from authority to requirement, risk, control, evidence, issue, exception, and approval.

Governance is proportional to criticality and risk, but proportionality cannot silently remove a mandatory obligation. Exceptions are risk decisions with defined authority, independent concurrence, compensating controls, an expiry date, monitoring, remediation, and downstream disclosure. Emergency changes and emergency access remain time-bound and retrospectively reviewed.

Evidence must be attributable, complete, tamper-evident where appropriate, linked to the relevant population and period, stored in an authoritative repository, access-controlled, retrievable, subject to legal hold, and disposed of under an approved records schedule. The fictional seven-year examples are fallbacks for test data, not universal legal requirements.

## Supervisory design alignment

The governance shape is informed by primary supervisory material current when version 2.0 was prepared:

- The Basel Committee's [Corporate governance principles for banks](https://www.bis.org/bcbs/publ/d328.htm) informed board and senior-management accountability, risk governance, risk culture, three-lines responsibilities, and Internal Audit independence.
- [BCBS 239](https://www.bis.org/publ/bcbs239.htm) informed governed data ownership, lineage, accuracy, completeness, timeliness, reconciliation, and risk-reporting evidence, especially for G-SIB-scale operations.
- The Basel Committee's [Principles for operational resilience](https://www.bis.org/bcbs/publ/d516.htm) informed critical-operation dependencies, tolerances, continuity, recovery, scenario exercises, and escalation.
- The Basel Committee's [Principles for the sound management of third-party risk](https://www.bis.org/bcbs/publ/d605.htm) informed accountable ownership, lifecycle due diligence, concentration, subcontractor, resilience, contingency, and exit expectations.
- The Federal Reserve's [SR 26-2 revised model risk management guidance](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm) informed risk-based model and methodology governance, intended-use boundaries, independent validation, ongoing monitoring, findings, overlays, implementation verification, and inventory controls. SR 26-2 superseded SR 11-7 and SR 21-8 on April 17, 2026.
- The US agencies' [Interagency Guidance on Third-Party Relationships: Risk Management](https://www.federalreserve.gov/supervisionreg/srletters/sr2304.htm) informed the US third-party lifecycle and governance examples.

These publications are contextual design inputs only. The pack deliberately uses internal fictional obligation IDs in examples instead of presenting external text as an institution-specific legal interpretation. A real bank must maintain its own regulatory inventory, applicability decisions, citations, interpretation owners, change monitoring, and evidence of Legal or Compliance review.

## Intentional precedence cases

`POL-DOC-GOV-001` controls lifecycle minimums over `STD-OPS-DOC-001` formatting guidance. `POL-REC-001` controls minimum evidence retention over `STD-CONTROL-EVID-001` when a standard is less specific. The manifest records both cases as `higher_precedence_wins` conflicts; resolution remains visible to callers.

All examples use fictional Aurora objects such as `PROC-AURORA-ALLOC-001`, `CALC-AURORA-ALLOC-001`, and `SYS-AURORA-REPORTING-001`. These names, thresholds, retention schedules, committees, systems, and approvals are fixtures, not enterprise registries, production instructions, or proprietary source material.
