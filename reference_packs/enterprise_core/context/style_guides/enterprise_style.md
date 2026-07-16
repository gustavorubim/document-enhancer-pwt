# Enterprise Banking Documentation Style Guide

**Reference ID:** STYLE-CORE-001
**Version:** 2.0
**Status:** Active
**Effective:** 2026-07-16
**Owner:** Enterprise Documentation Council
**Applies to:** Process, methodology, standard, and desktop-procedure documents

## Writing objective

Write so that an authorized operator, control owner, challenger, approver, auditor, or supervisor can
identify who must do what, for which entity and population, under which authority, using which data
and system, by when, with what evidence, and what happens when the expected result is not achieved.
Polish never substitutes for evidence or resolved governance.

## Voice and sentence design

- Use direct, concrete sentences and active voice. Put the accountable actor before the action.
- Use one action, decision, threshold, or outcome per sentence when describing executable work.
- Prefer `The Reconciliation Owner reviews the complete population by 17:00 America/New_York` to
  `Reconciliations should be reviewed timely`.
- Define acronyms at first use and use one canonical name thereafter.
- Avoid idiom, marketing language, rhetorical claims, unexplained jargon, and statements that imply
  certainty beyond the evidence.
- Separate facts, requirements, assumptions, interpretations, guidance, examples, and open issues.

## Normative language

Use these terms consistently:

| Term | Meaning |
| --- | --- |
| `MUST` | Enforceable internal requirement within the stated applicability |
| `MUST NOT` | Prohibition within the stated applicability |
| `SHOULD` | Expected practice; deviation requires documented rationale |
| `SHOULD NOT` | Discouraged practice; use requires documented rationale |
| `MAY` | Permitted option, not an obligation |

Every normative statement needs a stable requirement ID, applicability, authority, accountable role,
evidence, monitoring, and exception path. Do not use `shall` as a synonym. Do not convert external
guidance into a `MUST` without an approved internal obligation or policy basis.

## Governance and accountability language

- Distinguish board oversight, senior-management accountability, first-line ownership, second-line
  challenge, and third-line independent assurance.
- Do not assign management ownership to Internal Audit or describe second-line review as execution of
  a first-line control.
- Identify a role and decision right, not only a department name. `Finance` is ambiguous;
  `ROLE-CONTROLLER-APPROVER approves the legal-entity adjustment` is testable.
- Use `accountable`, `performs`, `reviews`, `challenges`, `approves`, `consults`, and `receives` with
  their ordinary governance meaning. Do not label multiple roles accountable for the same decision
  without an explicit joint-governance mechanism.
- State delegated authority, escalation, conflicts of interest, and non-delegable decisions.

## Scope, legal entities, and jurisdictions

State scope across legal entity, branch, business, product, service, process, customer segment,
booking location, data domain, system, third party, and jurisdiction as applicable. Avoid `all
entities` or `global` unless the document defines the inventory and local-overlay mechanism.

When rules differ, use a jurisdiction or legal-entity matrix. State whether a local requirement is
stricter, additive, conflicting, or not applicable. Do not generalize one jurisdiction's rule into a
global legal claim.

## Dates, time, amounts, and thresholds

- Use ISO 8601 dates (`2026-07-16`) and timestamps with timezone
  (`2026-07-16T17:00:00-04:00`).
- State the business calendar, cut-off, holiday rule, and timezone when timing affects execution.
- Pair every amount with currency and basis; every percentage with numerator, denominator, and
  period; every rate with convention; every duration with start/end events; and every threshold with
  operator, unit, evaluation period, source, and boundary behavior.
- Define rounding, precision, sign, null, zero, missing-data, and late-data treatment when they can
  change a decision.
- Replace `material`, `timely`, `periodic`, `significant`, `reasonable`, and `as needed` with a
  controlled taxonomy, measurable rule, named decision authority, or visible `TBD`.

## Stable IDs and names

Use stable IDs for documents, versions, obligations, requirements, risks, controls, processes,
steps, decisions, models, methodologies, formulas, parameters, data assets, data elements, systems,
third parties, evidence, issues, incidents, exceptions, approvals, metrics, and records when those
objects are authoritative or retrievable.

A display-name change does not change the stable ID. A superseded object keeps its historical ID and
links to its successor. Do not create generic `related to` relationships when a controlled
relationship such as `implements`, `mitigates`, `depends on`, `produces`, `validates`, or `supersedes`
is available.

## Risk, control, evidence, and issue statements

- Write a risk as cause, event, and impact where practical.
- Write a control with objective, owner, performer, reviewer, trigger/frequency, population, action,
  evidence, threshold, and failure response.
- Distinguish control design from one execution and from management monitoring.
- State evidence type, producer, source system, period, population, storage reference, review,
  result, retention, and lineage. `See screenshot` is not sufficient.
- A failed or incomplete control remains failed or incomplete even when management accepts the risk.
- Link exceptions, issues, incidents, remediation, retesting, and closure without erasing the
  original condition.

## Data, methodology, and model language

- Name authoritative source systems, data owners and stewards, legal-entity context, critical data
  elements, transformations, quality rules, reconciliations, lineage, and as-of periods.
- Define formulas symbol by symbol with units and sign conventions. Keep executable logic in text or
  tables, not only in code or screenshots.
- Distinguish model, methodology, calculator, deterministic rule, and end-user-computing asset
  according to the approved inventories and taxonomies.
- State intended use, prohibited use, assumptions, limitations, overlays, validation status,
  monitoring, and implementation mapping.
- Label estimates, inferred relationships, and expert judgment; do not present them as observed fact.

## Operational resilience and third parties

When a document supports a critical operation, identify the critical operation, disruption
tolerance, end-to-end dependencies, recovery objectives, fallback, test evidence, and resumption
authority. Describe people, facilities, technology, data, legal entities, and third parties needed
to deliver the operation.

For third parties, distinguish the bank owner, provider, material subcontractors, service, data and
system access, criticality, monitoring, incident notification, concentration or substitutability,
continuity, and exit. Do not imply that outsourcing transfers accountability.

## Headings and cross-references

Use one level-one title and the section order in the selected template. Do not skip heading levels.
Headings use sentence case and describe content rather than document navigation. Refer to stable IDs
and exact section titles rather than `above`, `below`, `the relevant policy`, or an unlabeled link.

Cross-references must resolve to an authoritative version. If applicability, ownership, or version is
unknown, create an issue or `TBD`; do not imply a link.

## Tables

Give each authoritative table a stable table ID and a descriptive title. Define row-level IDs,
columns, units, period/as-of context, source or owner, and controlled values. Repeat enough context
for a row to remain understandable when retrieved independently.

Use `Not applicable — <reason>` rather than a blank cell. Use `TBD — <owner and due date>` for an
unresolved required value. Avoid merged cells, color-only meaning, unexplained symbols, and tables
that require a nearby paragraph to identify their population or authority.

## Diagrams and screenshots

Diagrams supplement, but never replace, authoritative text and tables. Every diagram needs a stable
figure ID, accessible caption, text explanation, and stable IDs in node labels. Clearly distinguish
authoritative, inferred, and illustrative relationships.

Screenshots are non-authoritative aids. Provide alt text or a caption describing the task-relevant
content. Do not expose customer data, secrets, credentials, personal data, production identifiers,
or uncontrolled environment details.

## Confidentiality and distribution

Display the classification and handling restrictions required by the authoritative classification
policy. Do not copy restricted content into examples, prompts, comments, filenames, URLs, or public
issue trackers. Use fictional values in templates and examples. State the authoritative repository
and whether printed or exported copies are uncontrolled.

## Accessibility and localization

Use logical reading order, descriptive headings, plain language, meaningful link labels, sufficient
contrast, and captions for tables and figures. Do not rely on color, position, or icon alone.

Preserve stable IDs across translations. Identify the authoritative language, translation owner,
translation date, and conflict rule. Do not translate legal or controlled terms without approved
local interpretation.

## Review and unresolved content

Preserve `TBD`, open questions, conflicts, limitations, dissent, and waivers until they are resolved
through the governed process. Never silently fill a missing owner, threshold, approval, citation,
retention period, or validation result. Reviewers score evidence, accountability, and executability;
they do not approve unsupported content because it reads smoothly.
