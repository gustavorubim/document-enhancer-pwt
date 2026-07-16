"""Deterministic M7.1/M7.2 checks over the final M6 artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from document_enhancer.contracts import Validator
from document_enhancer.domain.audit import AuditEvidence, DeterministicCheck
from document_enhancer.domain.enums import DocumentType, EntityType, LedgerDisposition
from document_enhancer.domain.ids import IDENTIFIER_RE
from document_enhancer.domain.questions import ContentLedger, WaiversArtifact
from document_enhancer.domain.semantic import SemanticDocument
from document_enhancer.ingest.models import RawDocument
from document_enhancer.rewrite import (
    EnhancedDocumentModel,
    validate_content_ledger,
    validate_mermaid,
)


def _evidence(artifact: str, locator: str, quote: str) -> AuditEvidence:
    return AuditEvidence(artifact=artifact, locator=locator, quote=quote[:500])


def _check(
    check_id: str,
    name: str,
    category: str,
    errors: Sequence[str],
    *,
    auto_revisable: bool = False,
    evidence: Sequence[AuditEvidence] = (),
) -> DeterministicCheck:
    failed_evidence = list(evidence) or [
        _evidence("output/enhanced-model.json", check_id, error) for error in errors
    ]
    return DeterministicCheck(
        check_id=check_id,
        name=name,
        category=category,
        passed=not errors,
        auto_revisable=auto_revisable,
        details="; ".join(errors) if errors else "validated",
        evidence=[] if not errors else failed_evidence,
    )


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().upper() not in {"TBD", "UNKNOWN", "N/A?"}
    if isinstance(value, (list, tuple, set, frozenset, dict)):
        return bool(value)
    return True


def _requirement_items(
    requirements: Mapping[str, object] | None, key: str
) -> tuple[Mapping[str, object], ...]:
    value = requirements.get(key, ()) if requirements else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping))


_REQUIRED_FIELDS: dict[EntityType, tuple[str, ...]] = {
    EntityType.PROCESS_STEP: (
        "performer_ids",
        "input_ids",
        "action",
        "output_ids",
        "completion_condition_id",
    ),
    EntityType.METHODOLOGY_STEP: (
        "objective",
        "input_ids",
        "transformation",
        "parameter_ids",
        "assumption_ids",
        "output_ids",
        "validation_checks",
        "failure_conditions",
        "limitation_ids",
        "implementation_reference",
    ),
    EntityType.RULE: (
        "condition",
        "operator",
        "outcome",
        "evaluation_period",
        "unit",
    ),
    EntityType.CONTROL: (
        "objective",
        "risk_ids",
        "execution_frequency",
        "evidence_ids",
        "failure_response",
        "escalation_id",
    ),
    EntityType.EVIDENCE: (
        "evidence_type",
        "producer_id",
        "storage_reference",
        "retention",
    ),
    EntityType.EXCEPTION: (
        "applies_to_ids",
        "authorized_role_id",
        "justification",
        "approval_required",
        "review_or_expiry",
    ),
    EntityType.DEPENDENCY: (
        "dependency_type",
        "required_object_id",
        "provider_id",
        "readiness_condition",
        "failure_impact",
        "fallback",
    ),
    EntityType.CALCULATOR: (
        "calculator_type",
        "version",
        "owner_id",
        "location_reference",
        "input_ids",
        "output_ids",
        "using_step_ids",
        "validation_status",
        "criticality",
        "recovery_fallback",
    ),
}

_REQUIRED_ATTRIBUTE_FIELDS: dict[EntityType, tuple[str, ...]] = {
    EntityType.RISK: ("statement", "owner_id", "mitigation"),
    EntityType.REQUIREMENT: (
        "statement",
        "applicability",
        "accountable_role_id",
        "evidence_ids",
        "exception_id",
    ),
    EntityType.METRIC: ("unit", "evaluation_period", "owner_id"),
}


def _entity_value(item: object, field: str) -> object:
    direct = getattr(item, field, None)
    if direct is not None:
        return direct
    attributes = getattr(item, "attributes", {})
    return attributes.get(field) if isinstance(attributes, Mapping) else None


def _lint_errors(
    model: EnhancedDocumentModel, waivers: set[str], *, enforce_primary_object: bool
) -> list[str]:
    errors: list[str] = []
    expected_primary = {
        DocumentType.PROCESS: EntityType.PROCESS_STEP,
        DocumentType.METHODOLOGY: EntityType.METHODOLOGY_STEP,
        DocumentType.STANDARD: EntityType.REQUIREMENT,
        DocumentType.DESKTOP_PROCEDURE: EntityType.PROCESS_STEP,
    }[model.document.document_type]
    if enforce_primary_object and not any(
        item.entity_type is expected_primary for item in model.objects
    ):
        target = f"DOCUMENT-TYPE-{expected_primary.value.upper()}"
        if target not in waivers:
            errors.append(f"document type requires at least one {expected_primary.value} object")
    known_ids = {model.document.id, model.version.id, *(item.id for item in model.objects)}
    for item in model.objects:
        if item.id in waivers:
            continue
        for field in _REQUIRED_FIELDS.get(item.entity_type, ()):
            if not _present(_entity_value(item, field)):
                errors.append(f"{item.id} missing required field {field}")
        for field in _REQUIRED_ATTRIBUTE_FIELDS.get(item.entity_type, ()):
            if not _present(_entity_value(item, field)):
                errors.append(f"{item.id} missing required field {field}")
        if item.entity_type is EntityType.PROCESS_STEP:
            if not (
                _present(getattr(item, "trigger_ids", None))
                or _present(getattr(item, "precondition_ids", None))
            ):
                errors.append(f"{item.id} missing trigger/precondition")
            if not (
                _present(getattr(item, "next_step_id", None))
                or _present(getattr(item, "failure_path_id", None))
            ):
                errors.append(f"{item.id} missing next step/failure path")
        if item.entity_type is EntityType.RULE:
            threshold_present = _present(getattr(item, "threshold_id", None)) or _present(
                getattr(item, "value", None)
            )
            metric_present = _present(getattr(item, "metric_id", None)) or _present(
                getattr(item, "data_element_id", None)
            )
            if not threshold_present:
                errors.append(f"{item.id} missing threshold/value")
            if not metric_present:
                errors.append(f"{item.id} missing metric/data element")
        if item.entity_type is EntityType.CONTROL:
            for linked in (*getattr(item, "risk_ids", ()), *getattr(item, "evidence_ids", ())):
                if linked not in known_ids:
                    errors.append(f"{item.id} has dangling control link {linked}")
        for key, value in item.model_dump(mode="python").items():
            if (
                key.endswith("_ids")
                and key not in {"source_span_ids", "open_issue_ids"}
                and isinstance(value, list)
            ):
                for linked in value:
                    if isinstance(linked, str) and linked not in known_ids:
                        errors.append(f"{item.id}.{key} has dangling reference {linked}")
            elif (
                key.endswith("_id")
                and isinstance(value, str)
                and key
                not in {
                    "id",
                    "document_id",
                    "document_version_id",
                    "reference_id",
                }
                and value not in known_ids
            ):
                errors.append(f"{item.id}.{key} has dangling reference {value}")
    for table in model.tables:
        if table.table_id in waivers:
            continue
        column_ids = {column.column_id for column in table.columns}
        named_stable_column = (
            "id" not in column_ids
            and "version" not in column_ids
            and not any(column.endswith("_id") for column in column_ids)
        )
        complete_rows = [row for row in table.rows if not row.open_issue_ids]
        stable_row_values = bool(complete_rows) and all(
            any(IDENTIFIER_RE.fullmatch(value) for value in row.values.values())
            for row in complete_rows
        )
        if named_stable_column and not stable_row_values:
            errors.append(f"{table.table_id} has no stable ID column")
        for row in table.rows:
            if row.open_issue_ids:
                continue
            for column in table.columns:
                if column.required and not _present(row.values.get(column.column_id)):
                    errors.append(f"{table.table_id}/{row.row_id} missing {column.column_id}")
    return sorted(set(errors))


def run_deterministic_audit(
    *,
    model: EnhancedDocumentModel,
    semantic: SemanticDocument,
    ledger: ContentLedger,
    raw: RawDocument,
    requirements: Mapping[str, object] | None = None,
    waivers: WaiversArtifact | None = None,
) -> tuple[DeterministicCheck, ...]:
    """Run fail-closed checks without invoking a model or using rewrite scratch state."""

    waiver_ids = {item.target_id for item in (waivers.waivers if waivers else ())}
    checks: list[DeterministicCheck] = []
    schema_errors: list[str] = []
    try:
        EnhancedDocumentModel.model_validate(model.model_dump(mode="python"))
        SemanticDocument.model_validate(semantic.model_dump(mode="python"))
    except ValueError as exc:
        schema_errors.append(str(exc))
    checks.append(_check("CHECK-SCHEMA", "Strict artifact schemas", "schema", schema_errors))

    section_errors: list[str] = []
    table_errors: list[str] = []
    if requirements:
        actual_sections = {item.section_id for item in model.sections}
        for item in _requirement_items(requirements, "sections"):
            if not item.get("required"):
                continue
            section_id = str(item.get("id", ""))
            if section_id not in actual_sections and section_id not in waiver_ids:
                section_errors.append(f"missing required section {section_id}")
        tables_by_id = {item.table_id: item for item in model.tables}
        for item in _requirement_items(requirements, "tables"):
            if not item.get("required"):
                continue
            table_id = str(item.get("id", ""))
            if table_id in waiver_ids:
                continue
            table = tables_by_id.get(table_id)
            if table is None:
                table_errors.append(f"missing required table {table_id}")
                continue
            actual_columns = {column.column_id for column in table.columns}
            columns = item.get("columns", ())
            required_columns = (
                {
                    str(column.get("id"))
                    for column in columns
                    if isinstance(column, Mapping) and column.get("required")
                }
                if isinstance(columns, (list, tuple))
                else set()
            )
            missing = sorted(required_columns - actual_columns)
            if missing:
                table_errors.append(f"{table_id} missing columns {', '.join(missing)}")
    checks.append(
        _check("CHECK-TEMPLATE-SECTIONS", "Required template sections", "template", section_errors)
    )
    checks.append(
        _check("CHECK-TEMPLATE-TABLES", "Required template tables", "template", table_errors)
    )

    graph_errors: list[str] = []
    try:
        semantic.validate_references()
    except ValueError as exc:
        graph_errors.append(str(exc))
    checks.append(
        _check("CHECK-ONTOLOGY", "Ontology and graph references", "ontology", graph_errors)
    )

    provenance_errors: list[str] = []
    for item in [semantic.document, semantic.version, *semantic.objects, *semantic.relationships]:
        provenance = item.provenance
        if provenance.document_id != semantic.document.id:
            provenance_errors.append(f"{item.id} has unrelated document provenance")
        if provenance.origin.value == "source" and not provenance.source_span_id:
            provenance_errors.append(f"{item.id} has source origin without source span")
    checks.append(
        _check(
            "CHECK-PROVENANCE", "Complete node and edge provenance", "provenance", provenance_errors
        )
    )

    reference_errors: list[str] = []
    for field in (
        "template_id",
        "template_version",
        "reference_pack_id",
        "reference_pack_version",
    ):
        if getattr(model, field) != getattr(semantic, field):
            reference_errors.append(f"{field} differs between model and semantic sidecar")
    checks.append(
        _check(
            "CHECK-REFERENCES",
            "Template and reference-pack identity",
            "references",
            reference_errors,
        )
    )

    source_ids = [block.span_id.upper() for block in raw.blocks]
    source_texts = {block.span_id.upper(): block.text for block in raw.blocks}
    coverage = validate_content_ledger(ledger, source_ids, source_texts=source_texts)
    checks.append(
        _check(
            "CHECK-LEDGER",
            "One disposition per substantive source span",
            "ledger",
            list(coverage.errors),
        )
    )
    known_anchors = {item.anchor for item in model.sections}
    known_objects = {model.document.id, model.version.id, *(item.id for item in model.objects)}
    mapping_errors: list[str] = []
    for entry in ledger.entries:
        if entry.disposition is not LedgerDisposition.OMITTED:
            if entry.target_anchor is None:
                mapping_errors.append(f"{entry.ledger_entry_id} has no target anchor")
            elif entry.target_anchor not in known_anchors:
                mapping_errors.append(
                    f"{entry.ledger_entry_id} has unknown target anchor {entry.target_anchor}"
                )
        for object_id in entry.target_object_ids:
            if object_id not in known_objects:
                mapping_errors.append(
                    f"{entry.ledger_entry_id} has unknown target object {object_id}"
                )
    checks.append(
        _check(
            "CHECK-SOURCE-TARGET-MAPPING",
            "Complete source-to-target anchors and dispositions",
            "ledger",
            mapping_errors,
        )
    )
    omission_errors = [
        f"{entry.ledger_entry_id} deliberately omits {entry.source_span_id}"
        for entry in ledger.entries
        if entry.disposition is LedgerDisposition.OMITTED
        and entry.ledger_entry_id not in waiver_ids
        and entry.source_span_id not in waiver_ids
    ]
    checks.append(_check("CHECK-OMISSIONS", "Deliberate omissions", "ledger", omission_errors))

    unresolved = [item.finding_id for item in semantic.open_issues if item.blocking]
    checks.append(
        _check(
            "CHECK-UNRESOLVED",
            "No unresolved blocking items",
            "governance",
            [f"unresolved blocker {item}" for item in unresolved if item not in waiver_ids],
        )
    )

    known = {semantic.document.id, semantic.version.id, *(item.id for item in semantic.objects)}
    mermaid_errors: list[str] = []
    for diagram in model.mermaid:
        mermaid_errors.extend(validate_mermaid(diagram))
        for node in diagram.nodes:
            if node.semantic_id not in known:
                mermaid_errors.append(
                    f"{diagram.diagram_id} node {node.node_id} references {node.semantic_id}"
                )
        for object_id in diagram.source_object_ids:
            if object_id not in known:
                mermaid_errors.append(f"{diagram.diagram_id} references unknown object {object_id}")
    checks.append(
        _check(
            "CHECK-MERMAID",
            "Mermaid syntax and semantic references",
            "mermaid",
            mermaid_errors,
            auto_revisable=True,
        )
    )

    anchor_errors: list[str] = []
    anchors = [item.anchor for item in model.sections]
    if len(anchors) != len(set(anchors)):
        anchor_errors.append("duplicate Markdown anchors")
    semantic_sections = {
        str(item.get("section_id")): str(item.get("anchor"))
        for item in semantic.sections
        if isinstance(item, Mapping)
    }
    for section in model.sections:
        if semantic_sections.get(section.section_id) != section.anchor:
            anchor_errors.append(f"sidecar drift for {section.section_id}")
    checks.append(
        _check("CHECK-ANCHORS", "Sidecar and Markdown anchors", "references", anchor_errors)
    )

    checks.append(
        _check(
            "CHECK-DOCUMENT-LINT",
            "Document-type object and table lint suite",
            "document_lint",
            _lint_errors(model, waiver_ids, enforce_primary_object=requirements is not None),
            auto_revisable=True,
        )
    )
    return tuple(checks)


__all__ = ["Validator", "run_deterministic_audit"]
