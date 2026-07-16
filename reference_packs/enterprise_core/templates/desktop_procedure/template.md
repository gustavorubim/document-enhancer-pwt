---
template_id: TPL-DESKTOP-001
document_type: desktop_procedure
reference_pack: enterprise_core
reference_pack_version: 1.0.0
document_id: "{{ document.id }}"
document_version: "{{ document.version }}"
status: "{{ document.status }}"
---

<!-- AUTHORING: Screenshots are aids only. Keep executable actions and expected results in text. -->
# {{ document.title }}

**Document ID:** {{ document.id }}
**Version:** {{ document.version }}
**Status:** {{ document.status }}
**Owner:** {{ document.owner }}
**Effective date:** {{ document.effective_date }}
**Next review date:** {{ document.next_review_date }}

## Document metadata and governance

{{ sections.metadata }}

## Purpose

{{ sections.purpose }}

## Scope and applicability

{{ sections.scope }}

## Prerequisites

{{ sections.prerequisites }}

## Access and environment

{{ sections.access }}

## Tools and inputs

{{ sections.tools }}

| Tool or input ID | Version | Owner | Purpose | Fallback |
| --- | --- | --- | --- | --- |
| {{ tables.tools }} | TBD | TBD | TBD | TBD |

## Safety and data handling

{{ sections.safety }}

## Atomic actions

{{ sections.actions }}

| Action ID | Operator | Action | Expected result | Evidence | Next action |
| --- | --- | --- | --- | --- | --- |
| {{ tables.actions }} | TBD | TBD | TBD | TBD | TBD |

## Decisions and branching

{{ sections.decisions }}

## Evidence capture

{{ sections.evidence }}

| Evidence ID | Type | Producer | Storage reference | Retention |
| --- | --- | --- | --- | --- |
| {{ tables.evidence }} | TBD | TBD | TBD | TBD |

## Failure paths

{{ sections.failure }}

| Failure ID | Symptom | Safe stop | Recovery | Escalation |
| --- | --- | --- | --- | --- |
| {{ tables.failure }} | TBD | TBD | TBD | TBD |

## Rollback and recovery

{{ sections.rollback }}

## Escalation

{{ sections.escalation }}

## Completion criteria

{{ sections.completion }}

## Related requirements, controls, and documents

{{ sections.related }}

## Version history and approvals

{{ sections.version }}

| Version | Effective date | Change | Approver |
| --- | --- | --- | --- |
| {{ tables.versions }} | TBD | TBD | TBD |

<!-- AUTHORING: Remove all examples and hidden instructions through the renderer before delivery. -->
