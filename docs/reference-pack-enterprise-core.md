# `enterprise_core` reference-pack map

`enterprise_core` is the fictional default pack used by the M2 reference lane. It is intentionally generic enough for local tests while exercising the contracts needed by later workflow lanes.

## Contents

| Area | Files | Contract exercised |
| --- | --- | --- |
| Ontology | `ontology/entity_types.yaml`, `relationship_types.yaml`, `id_patterns.yaml`, `controlled_terms.yaml` | Bounded objects, allow-listed relationships, stable IDs, controlled vocabulary, graph layers, minimum graph-critical fields |
| Process | `templates/process/` | Triggers, atomic steps, decisions, controls, evidence, exceptions, recovery, dependencies, metrics, retention, approvals |
| Methodology | `templates/methodology/` | Lineage, transformations, formulas, calculators, assumptions, limitations, validation, tolerances, implementation mapping |
| Standard | `templates/standard/` | Normative terms, requirement IDs, applicability, accountable roles, evidence, enforcement, exceptions, version governance |
| Desktop procedure | `templates/desktop_procedure/` | Access, tools, safety, atomic actions, expected results, screenshots as non-authoritative aids, failure/rollback/recovery |
| Context | `context/` | Fictional style guide, document governance policy, records-retention policy, operational documentation standard, control evidence standard, glossary |
| Rubrics | `rubrics/` | Common 0–4 dimensions, hard blockers, waiver semantics, and complete document-type mappings |

## Intentional precedence cases

`POL-DOC-GOV-001` controls lifecycle minimums over `STD-OPS-DOC-001` formatting guidance. `POL-REC-001` controls minimum evidence retention over `STD-CONTROL-EVID-001` when a standard is less specific. The manifest records both cases as `higher_precedence_wins` conflicts; resolution remains visible to callers.

All examples use fictional Aurora objects such as `PROC-AURORA-ALLOC-001`, `CALC-AURORA-ALLOC-001`, and `SYS-AURORA-REPORTING-001`. These names are fixtures, not enterprise registries or proprietary source material.
