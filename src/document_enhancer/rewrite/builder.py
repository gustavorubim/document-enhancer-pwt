"""Build and project the single validated M6 intermediate document model."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from document_enhancer.domain.analysis import EvidenceQuote, Finding
from document_enhancer.domain.enums import (
    Authority,
    DocumentType,
    EntityType,
    FindingSeverity,
    FindingType,
    Layer,
    ProvenanceOrigin,
    RelationshipType,
    ReviewStatus,
    VersionStatus,
)
from document_enhancer.domain.ontology import (
    DocumentIdentity,
    DocumentVersion,
    Entity,
    Relationship,
    Section,
    SemanticObject,
    Statement,
    Table,
)
from document_enhancer.domain.provenance import Provenance
from document_enhancer.domain.questions import ContentLedger
from document_enhancer.domain.semantic import SemanticDocument

from .inputs import SectionRewriteInput
from .mermaid import generate_mermaid
from .models import (
    EnhancedDocumentModel,
    EnhancedSection,
    MermaidDiagram,
    MermaidEdge,
    MermaidNode,
    OpenIssue,
    RevisionCounters,
    StructuredTable,
    StructuredTableRow,
    TableColumn,
)


def _source_digest(inputs: Sequence[SectionRewriteInput]) -> str:
    if not inputs:
        return "0" * 64
    return inputs[0].source_digest


def _slug(value: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", value.lower())) or "section"


def _provenance(
    document_id: str,
    version_id: str,
    *,
    source_span_id: str | None = None,
    origin: ProvenanceOrigin = ProvenanceOrigin.MODEL,
    authority: Authority = Authority.DERIVED,
    layer: Layer = Layer.AUTHORITATIVE,
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED,
    reviewer_id: str | None = None,
    reference_id: str | None = None,
) -> Provenance:
    return Provenance(
        document_id=document_id,
        document_version_id=version_id,
        source_span_id=source_span_id,
        origin=origin,
        authority=authority,
        layer=layer,
        confidence=1.0 if origin is ProvenanceOrigin.MODEL else None,
        extraction_method="m6.intermediate-model",
        review_status=review_status,
        reviewer_id=reviewer_id,
        reference_id=reference_id,
    )


def _section_for_kind(sections: Sequence[EnhancedSection], kind: str) -> EnhancedSection:
    preferred = {
        "steps": ("step", "method"),
        "rules": ("rule", "threshold", "parameter"),
        "controls": ("control", "validation"),
        "risks": ("control", "limitation", "scope"),
        "evidence": ("control", "validation", "output"),
        "assumptions": ("assumption",),
        "limitations": ("limitation", "scope"),
        "exceptions": ("exception", "recovery", "override"),
        "dependencies": ("depend", "data", "system", "implementation"),
        "calculators": ("calculator", "model", "formula"),
        "inputs_outputs": ("input", "output", "data"),
        "versions": ("version", "governance", "approval"),
        "roles": ("role", "responsib", "governance"),
        "metrics": ("metric", "monitor"),
    }
    tokens = preferred.get(kind, ())
    for section in sections:
        if any(token in section.heading.lower() for token in tokens):
            return section
    return sections[0]


def _approved_objects(
    inputs: Sequence[SectionRewriteInput],
    *,
    document_id: str,
    version_id: str,
) -> list[SemanticObject]:
    result: list[SemanticObject] = []
    seen: set[str] = set()
    for item in inputs:
        spans = item.allowed_source_span_ids
        for answer in item.approved_answers:
            for candidate in answer.new_semantic_objects:
                if candidate.id in seen or candidate.provisional:
                    continue
                provenance = _provenance(
                    document_id,
                    version_id,
                    source_span_id=next(iter(spans), None),
                    origin=ProvenanceOrigin.ANSWER,
                    authority=Authority.EXPLICIT,
                    layer=Layer.AUTHORITATIVE,
                    review_status=ReviewStatus.ACCEPTED,
                    reviewer_id=answer.responder,
                )
                data = candidate.model_dump(mode="json")
                data.update(
                    {
                        "provenance": provenance.model_dump(mode="json"),
                        "authority": Authority.EXPLICIT,
                        "layer": Layer.AUTHORITATIVE,
                        "review_status": ReviewStatus.ACCEPTED,
                        "provisional": False,
                    }
                )
                result.append(type(candidate).model_validate(data))
                seen.add(candidate.id)
    return result


def _table_specs(
    document_type: DocumentType,
) -> list[tuple[str, str, str, tuple[str, ...], tuple[EntityType, ...]]]:
    version_id = (
        "TBL-PROC-VERSIONS" if document_type is DocumentType.PROCESS else "TBL-METH-VERSIONS"
    )
    return [
        (
            "steps",
            "TBL-M6-STEPS",
            "Steps",
            ("id", "performer", "action", "input", "output", "evidence", "completion", "failure"),
            (EntityType.PROCESS_STEP, EntityType.METHODOLOGY_STEP),
        ),
        (
            "rules",
            "TBL-M6-RULES",
            "Rules",
            ("id", "condition", "operator", "threshold", "outcome", "override"),
            (EntityType.RULE,),
        ),
        (
            "controls",
            "TBL-M6-CONTROLS",
            "Controls",
            ("id", "risk", "frequency", "owner", "evidence", "failure_response"),
            (EntityType.CONTROL,),
        ),
        (
            "risks",
            "TBL-M6-RISKS",
            "Risks",
            ("id", "statement", "owner", "mitigation"),
            (EntityType.RISK,),
        ),
        (
            "evidence",
            "TBL-M6-EVIDENCE",
            "Evidence",
            ("id", "type", "producer", "linked_object", "storage", "retention"),
            (EntityType.EVIDENCE,),
        ),
        (
            "assumptions",
            "TBL-M6-ASSUMPTIONS",
            "Assumptions",
            ("id", "statement", "risk", "validation", "owner"),
            (EntityType.ASSUMPTION,),
        ),
        (
            "limitations",
            "TBL-M6-LIMITATIONS",
            "Limitations",
            ("id", "statement", "scope", "impact", "mitigation"),
            (EntityType.LIMITATION,),
        ),
        (
            "exceptions",
            "TBL-M6-EXCEPTIONS",
            "Exceptions",
            ("id", "applies_to", "authority", "evidence", "expiry"),
            (EntityType.EXCEPTION,),
        ),
        (
            "dependencies",
            "TBL-M6-DEPENDENCIES",
            "Dependencies",
            ("id", "type", "required", "owner", "readiness", "fallback"),
            (EntityType.DEPENDENCY,),
        ),
        (
            "calculators",
            "TBL-M6-CALCULATORS",
            "Calculators",
            ("id", "type", "version", "owner", "inputs", "outputs", "validation", "fallback"),
            (EntityType.CALCULATOR,),
        ),
        (
            "inputs_outputs",
            "TBL-M6-INPUTS-OUTPUTS",
            "Inputs and outputs",
            ("id", "type", "name", "owner", "source_or_consumer"),
            (EntityType.INPUT, EntityType.OUTPUT),
        ),
        (
            "versions",
            version_id,
            "Version history",
            ("version", "effective", "change", "approver", "decision"),
            (EntityType.DOCUMENT_VERSION, EntityType.APPROVAL),
        ),
        (
            "roles",
            "TBL-M6-ROLES",
            "Roles and accountability",
            ("id", "responsibility", "accountability", "escalation"),
            (EntityType.ROLE,),
        ),
        (
            "metrics",
            "TBL-M6-METRICS",
            "Metrics and service levels",
            ("id", "definition", "unit", "period", "threshold", "owner"),
            (EntityType.METRIC,),
        ),
    ]


def _field(value: object, name: str, default: str = "TBD") -> str:
    raw = getattr(value, name, None)
    if raw is None and isinstance(value, Mapping):
        raw = value.get(name)
    if raw is None or raw == "":
        return default
    if isinstance(raw, (list, tuple, set)):
        return ", ".join(str(item) for item in raw) or default
    return str(raw)


def _row_values(kind: str, entity: Entity) -> dict[str, str]:
    values: dict[str, str] = {}
    if kind == "steps":
        values = {
            "id": entity.id,
            "performer": _field(entity, "performer_ids", "TBD"),
            "action": _field(entity, "action"),
            "input": _field(entity, "input_ids"),
            "output": _field(entity, "output_ids"),
            "evidence": _field(entity, "evidence_ids"),
            "completion": _field(entity, "completion_condition_id"),
            "failure": _field(entity, "failure_path_id"),
        }
    elif kind == "rules":
        values = {
            "id": entity.id,
            "condition": _field(entity, "condition"),
            "operator": _field(entity, "operator"),
            "threshold": _field(entity, "threshold_id", _field(entity, "value")),
            "outcome": _field(entity, "outcome"),
            "override": _field(entity, "override_authority_id"),
        }
    elif kind == "controls":
        values = {
            "id": entity.id,
            "risk": _field(entity, "risk_ids"),
            "frequency": _field(entity, "execution_frequency"),
            "owner": _field(entity, "owner_id", _field(entity, "performer_id")),
            "evidence": _field(entity, "evidence_ids"),
            "failure_response": _field(entity, "failure_response"),
        }
    elif kind == "risks":
        values = {
            "id": entity.id,
            "statement": entity.name,
            "owner": _field(entity, "owner_id"),
            "mitigation": _field(entity, "mitigation"),
        }
    elif kind == "evidence":
        values = {
            "id": entity.id,
            "type": _field(entity, "evidence_type"),
            "producer": _field(entity, "producer_id"),
            "linked_object": _field(entity, "linked_step_ids"),
            "storage": _field(entity, "storage_reference"),
            "retention": _field(entity, "retention"),
        }
    elif kind == "assumptions":
        values = {
            "id": entity.id,
            "statement": _field(entity, "statement", entity.name),
            "risk": _field(entity, "risk_if_violated"),
            "validation": _field(entity, "validation_method"),
            "owner": _field(entity, "owner_id"),
        }
    elif kind == "limitations":
        values = {
            "id": entity.id,
            "statement": _field(entity, "statement", entity.name),
            "scope": _field(entity, "affected_ids"),
            "impact": _field(entity, "impact"),
            "mitigation": _field(entity, "mitigation"),
        }
    elif kind == "exceptions":
        values = {
            "id": entity.id,
            "applies_to": _field(entity, "applies_to_ids"),
            "authority": _field(entity, "authorized_role_id"),
            "evidence": _field(entity, "evidence_ids"),
            "expiry": _field(entity, "review_or_expiry"),
        }
    elif kind == "dependencies":
        values = {
            "id": entity.id,
            "type": _field(entity, "dependency_type"),
            "required": _field(entity, "required_object_id"),
            "owner": _field(entity, "provider_id"),
            "readiness": _field(entity, "readiness_condition"),
            "fallback": _field(entity, "fallback"),
        }
    elif kind == "calculators":
        values = {
            "id": entity.id,
            "type": _field(entity, "calculator_type"),
            "version": _field(entity, "version"),
            "owner": _field(entity, "owner_id"),
            "inputs": _field(entity, "input_ids"),
            "outputs": _field(entity, "output_ids"),
            "validation": _field(entity, "validation_status"),
            "fallback": _field(entity, "recovery_fallback"),
        }
    elif kind == "inputs_outputs":
        values = {
            "id": entity.id,
            "type": entity.entity_type.value,
            "name": entity.name,
            "owner": _field(entity, "owner_id"),
            "source_or_consumer": _field(
                entity, "source_reference", _field(entity, "consumer_ids")
            ),
        }
    elif kind == "versions":
        values = {
            "version": _field(entity, "version", entity.name),
            "effective": _field(entity, "effective_dates"),
            "change": _field(entity, "change_summary"),
            "approver": _field(entity, "approver_id"),
            "decision": _field(entity, "decision"),
        }
    elif kind == "roles":
        values = {
            "id": entity.id,
            "responsibility": entity.name,
            "accountability": _field(entity, "accountability"),
            "escalation": _field(entity, "escalation_id"),
        }
    elif kind == "metrics":
        values = {
            "id": entity.id,
            "definition": entity.name,
            "unit": _field(entity, "unit"),
            "period": _field(entity, "evaluation_period"),
            "threshold": _field(entity, "threshold_id"),
            "owner": _field(entity, "owner_id"),
        }
    return values


def build_enhanced_document(
    rewrite_inputs: Sequence[SectionRewriteInput],
    *,
    document_id: str,
    document_type: DocumentType | str = DocumentType.PROCESS,
    reference_pack_id: str = "enterprise_core",
    reference_pack_version: str = "1.0.0",
    template_id: str | None = None,
    template_version: str = "1.0.0",
    ledger: ContentLedger | None = None,
    revision_counters: RevisionCounters | None = None,
) -> EnhancedDocumentModel:
    """Construct a validated intermediate model without adding unsupported facts."""

    doc_type = DocumentType(document_type)
    source_digest = _source_digest(rewrite_inputs)
    first_span = next(
        (span_id for item in rewrite_inputs for span_id in item.allowed_source_span_ids), None
    )
    suffix = document_id.removeprefix("DOC-")
    version_id = f"DOCV-{suffix}-001"
    document_provenance = _provenance(
        document_id,
        version_id,
        source_span_id=first_span,
        origin=ProvenanceOrigin.SOURCE,
        authority=Authority.EXPLICIT,
        layer=Layer.AUTHORITATIVE,
    )
    document = DocumentIdentity(
        id=document_id,
        name="Enhanced document",
        document_type=doc_type,
        source_digest=source_digest,
        provenance=document_provenance,
        authority=Authority.EXPLICIT,
        layer=Layer.AUTHORITATIVE,
    )
    version = DocumentVersion(
        id=version_id,
        name="Draft version",
        document_id=document_id,
        version="1.0",
        status=VersionStatus.DRAFT,
        source_digest=source_digest,
        provenance=document_provenance,
        authority=Authority.EXPLICIT,
        layer=Layer.AUTHORITATIVE,
    )
    sections: list[EnhancedSection] = []
    open_issues: list[OpenIssue] = []
    for item in rewrite_inputs:
        source_ids = list(item.allowed_source_span_ids)
        evidence = [
            EvidenceQuote(span_id=evidence.span_id, quote=evidence.quote)
            for evidence in item.source_evidence
        ]
        body_parts = [evidence.quote for evidence in item.source_evidence]
        answer_ids = [answer.answer_id for answer in item.approved_answers]
        body_parts.extend(
            f"Approved reviewer input {answer.answer_id}: {answer.answer}"
            for answer in item.approved_answers
            if answer.answer
        )
        issue_ids: list[str] = []
        if not body_parts:
            issue_id = f"OPEN-M6-{_slug(item.section_id).upper()}"
            issue_ids.append(issue_id)
            open_issues.append(
                OpenIssue(
                    issue_id=issue_id,
                    category="tbd",
                    statement=f"No approved evidence is available for {item.heading}; do not assert a value.",
                    target_section_id=item.section_id,
                )
            )
            body_parts.append(f"TBD — see open issue {issue_id}.")
        section_provenance = [
            _provenance(
                document_id,
                version_id,
                source_span_id=source_ids[0] if source_ids else None,
                origin=ProvenanceOrigin.SOURCE if source_ids else ProvenanceOrigin.MODEL,
                authority=Authority.EXPLICIT if source_ids else Authority.DERIVED,
                layer=Layer.AUTHORITATIVE,
            )
        ]
        sections.append(
            EnhancedSection(
                section_id=item.section_id,
                heading=item.heading,
                order=len(sections),
                anchor=item.anchor,
                body="\n\n".join(body_parts),
                source_span_ids=source_ids,
                evidence=evidence,
                approved_answer_ids=answer_ids,
                open_issue_ids=issue_ids,
                provenance=section_provenance,
            )
        )
    if not sections:
        raise ValueError("an enhanced document requires at least one target section")

    objects: list[SemanticObject] = []
    relationships: list[Relationship] = []
    for section in sections:
        objects.append(
            Section(
                id=section.section_id,
                name=section.heading,
                order=section.order,
                anchor=section.anchor,
                provenance=section.provenance[0],
                authority=section.provenance[0].authority,
                layer=section.provenance[0].layer,
                attributes={"open_issue_ids": section.open_issue_ids},
            )
        )
        for index, quote in enumerate(section.evidence):
            statement_id = f"STMT-{suffix}-{section.order + 1:03d}-{index + 1:03d}"
            statement = Statement(
                id=statement_id,
                name=f"Statement {section.order + 1}.{index + 1}",
                text=quote.quote,
                provenance=_provenance(
                    document_id,
                    version_id,
                    source_span_id=quote.span_id,
                    origin=ProvenanceOrigin.SOURCE,
                    authority=Authority.EXPLICIT,
                    layer=Layer.AUTHORITATIVE,
                ),
                authority=Authority.EXPLICIT,
                layer=Layer.AUTHORITATIVE,
            )
            objects.append(statement)
            section.object_ids.append(statement.id)
            relationships.append(
                Relationship(
                    source_id=section.section_id,
                    source_type=EntityType.SECTION,
                    relationship_type=RelationshipType.CONTAINS_STATEMENT,
                    target_id=statement.id,
                    target_type=EntityType.STATEMENT,
                    provenance=statement.provenance,
                )
            )
    objects.extend(
        _approved_objects(rewrite_inputs, document_id=document_id, version_id=version_id)
    )
    known_ids = {entity.id for entity in objects}
    for entity in objects:
        if entity.entity_type in {EntityType.SECTION, EntityType.STATEMENT}:
            continue
        # Candidate object fields remain evidence-bearing attributes.  Only explicit answer
        # objects enter this list; unapproved analysis candidates never get promoted.
        if entity.id not in known_ids:
            continue

    tables: list[StructuredTable] = []
    for kind, table_id, title, column_ids, types in _table_specs(doc_type):
        section = _section_for_kind(sections, kind)
        columns = [
            TableColumn(column_id=column_id, label=column_id.replace("_", " ").title())
            for column_id in column_ids
        ]
        candidates = [entity for entity in objects if entity.entity_type in types]
        rows: list[StructuredTableRow] = []
        table_source_ids: list[str] = []
        for ordinal, entity in enumerate(candidates, start=1):
            source_span = entity.provenance.source_span_id
            if source_span:
                table_source_ids.append(source_span)
            rows.append(
                StructuredTableRow(
                    row_id=f"ROW-{kind.upper()}-{ordinal:03d}",
                    values=_row_values(kind, entity),
                    source_span_ids=[source_span] if source_span else [],
                    object_ids=[entity.id],
                )
            )
        if not rows:
            issue_id = f"OPEN-M6-TABLE-{kind.replace('_', '-').upper()}"
            if issue_id not in {issue.issue_id for issue in open_issues}:
                open_issues.append(
                    OpenIssue(
                        issue_id=issue_id,
                        category="tbd",
                        statement=f"No approved {kind.replace('_', ' ')} object is available; table values remain TBD.",
                        target_section_id=section.section_id,
                    )
                )
            rows = [
                StructuredTableRow(
                    row_id=f"ROW-{kind.replace('_', '-').upper()}-TBD",
                    values={column_id: "TBD" for column_id in column_ids},
                    open_issue_ids=[issue_id],
                )
            ]
        table_provenance = _provenance(
            document_id,
            version_id,
            source_span_id=table_source_ids[0]
            if table_source_ids
            else next(iter(section.source_span_ids), None),
            origin=ProvenanceOrigin.SOURCE
            if table_source_ids or section.source_span_ids
            else ProvenanceOrigin.MODEL,
            authority=Authority.EXPLICIT
            if table_source_ids or section.source_span_ids
            else Authority.DERIVED,
            layer=Layer.AUTHORITATIVE,
        )
        table = StructuredTable(
            table_id=table_id,
            table_kind=cast(Any, kind),
            title=title,
            purpose=f"Structured {kind.replace('_', ' ')} representation for traceable reuse.",
            section_id=section.section_id,
            columns=columns,
            rows=rows,
            source_span_ids=table_source_ids or section.source_span_ids,
            provenance=[table_provenance],
        )
        tables.append(table)
        section.table_ids.append(table_id)
        objects.append(
            Table(
                id=table_id,
                name=title,
                title=title,
                headers=[column.label for column in columns],
                source_span_ids=table.source_span_ids,
                provenance=table_provenance,
                authority=table_provenance.authority,
                layer=table_provenance.layer,
                attributes={
                    "open_issue_ids": sorted(
                        issue_id for row in table.rows for issue_id in row.open_issue_ids
                    )
                },
            )
        )
        relationships.append(
            Relationship(
                source_id=section.section_id,
                source_type=EntityType.SECTION,
                relationship_type=RelationshipType.CONTAINS_TABLE,
                target_id=table_id,
                target_type=EntityType.TABLE,
                provenance=table_provenance,
            )
        )
    for section in sections:
        relationships.append(
            Relationship(
                source_id=document_id,
                source_type=EntityType.DOCUMENT_IDENTITY,
                relationship_type=RelationshipType.HAS_SECTION,
                target_id=section.section_id,
                target_type=EntityType.SECTION,
                provenance=section.provenance[0],
            )
        )
    relationships.extend(
        [
            Relationship(
                source_id=document_id,
                source_type=EntityType.DOCUMENT_IDENTITY,
                relationship_type=RelationshipType.HAS_VERSION,
                target_id=version_id,
                target_type=EntityType.DOCUMENT_VERSION,
                provenance=document_provenance,
            ),
            Relationship(
                source_id=document_id,
                source_type=EntityType.DOCUMENT_IDENTITY,
                relationship_type=RelationshipType.CURRENT_VERSION,
                target_id=version_id,
                target_type=EntityType.DOCUMENT_VERSION,
                provenance=document_provenance,
            ),
        ]
    )
    nodes: list[MermaidNode] = []
    node_by_entity: dict[str, str] = {}
    for entity in objects:
        if entity.entity_type not in {
            EntityType.PROCESS_STEP,
            EntityType.METHODOLOGY_STEP,
            EntityType.DECISION,
            EntityType.DEPENDENCY,
        }:
            continue
        node_id = "N_" + re.sub(r"[^A-Za-z0-9_]", "_", entity.id)
        node_by_entity[entity.id] = node_id
        nodes.append(
            MermaidNode(
                node_id=node_id,
                semantic_id=entity.id,
                label=entity.name,
                source_span_ids=[entity.provenance.source_span_id]
                if entity.provenance.source_span_id
                else [],
            )
        )
    edges = [
        MermaidEdge(
            edge_id=relationship.id or "EDGE-M6",
            source_node_id=node_by_entity[relationship.source_id],
            target_node_id=node_by_entity[relationship.target_id],
            relationship_type=relationship.relationship_type,
        )
        for relationship in relationships
        if relationship.source_id in node_by_entity and relationship.target_id in node_by_entity
    ]
    diagram = MermaidDiagram(
        diagram_id=f"DIAG-{suffix}-FLOW",
        diagram_type="process"
        if doc_type in {DocumentType.PROCESS, DocumentType.DESKTOP_PROCEDURE}
        else "lineage",
        caption="Structured flow derived from approved process steps, decisions, and dependencies.",
        nodes=nodes,
        edges=edges,
        source_object_ids=sorted(node_by_entity),
    )
    overview = _section_for_kind(sections, "steps")
    overview.mermaid_ids.append(diagram.diagram_id)
    model = EnhancedDocumentModel(
        document=document,
        version=version,
        template_id=template_id or f"TPL-{doc_type.value.upper()}-001",
        template_version=template_version,
        reference_pack_id=reference_pack_id,
        reference_pack_version=reference_pack_version,
        ledger_id=ledger.ledger_id if ledger else "LEDGER-UNSPECIFIED",
        sections=sections,
        tables=tables,
        objects=objects,
        relationships=relationships,
        mermaid=[diagram],
        open_issues=open_issues,
        revision_counters=revision_counters or RevisionCounters(),
        provisional_ids=[],
    )
    return model


def build_semantic_document(model: EnhancedDocumentModel) -> SemanticDocument:
    """Project the sidecar from the exact intermediate model, without re-discovery."""

    model.assert_valid()
    findings = [
        Finding(
            finding_id=issue.issue_id,
            category=issue.category,
            severity=FindingSeverity.HIGH,
            finding_type=FindingType.UNSUPPORTED,
            evidence=list(issue.evidence),
            target_template_section=issue.target_section_id,
            target_object_id=issue.target_object_id,
            impact="The item remains unresolved and is excluded from authoritative semantic facts.",
            proposed_disposition="Resolve or explicitly waive the open issue before asserting the fact.",
            requires_human_answer=True,
            blocking=False,
        )
        for issue in model.open_issues
    ]
    return SemanticDocument(
        document=model.document,
        version=model.version,
        objects=model.objects,
        relationships=model.relationships,
        open_issues=findings,
        provisional_ids=model.provisional_ids,
        template_id=model.template_id,
        template_version=model.template_version,
        ontology_version="0.1.0",
        reference_pack_id=model.reference_pack_id,
        reference_pack_version=model.reference_pack_version,
        markdown_artifact=model.markdown_artifact,
        ledger_id=model.ledger_id,
        sections=[section.model_dump(mode="json") for section in model.sections],
        tables=[table.model_dump(mode="json") for table in model.tables],
        mermaid=[
            diagram.model_dump(mode="json") | {"markdown": generate_mermaid(diagram)}
            for diagram in model.mermaid
        ],
        revision_counters=model.revision_counters.model_dump(mode="json"),
        validation_passed=True,
    )


generate_semantic_document = build_semantic_document


__all__ = [
    "build_enhanced_document",
    "build_semantic_document",
    "generate_semantic_document",
]
