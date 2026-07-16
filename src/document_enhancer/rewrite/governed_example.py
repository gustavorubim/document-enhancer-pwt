"""Deterministic projection of a reference pack's validated complete example.

This adapter is deliberately narrow: callers may use it only after proving that the source
digest exactly matches the selected pack's checked-in example digest.  It therefore turns
already-governed source tables and primary document objects into the normal M6 model without
inventing missing content or making a provider call.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import cast

from document_enhancer.domain.enums import (
    Authority,
    DocumentType,
    EntityType,
    Layer,
    ProvenanceOrigin,
    RelationshipType,
    VersionStatus,
)
from document_enhancer.domain.ontology import (
    Assumption,
    CompletionCondition,
    EscalationPath,
    Input,
    Limitation,
    MethodologyStep,
    Output,
    Parameter,
    Precondition,
    ProcessStep,
    Relationship,
    Requirement,
    Role,
    SemanticObject,
    Table,
)
from document_enhancer.domain.provenance import Provenance

from .inputs import ApprovedEvidence, SectionRewriteInput
from .models import (
    EnhancedDocumentModel,
    MermaidDiagram,
    MermaidNode,
    StructuredTable,
    StructuredTableRow,
    TableColumn,
    TableKind,
)

_IDENTIFIER_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")
_NUMBERED_ITEM_RE = re.compile(r"(?m)^\s*\d+\.\s+(.*\S)\s*$")


def _provenance(model: EnhancedDocumentModel, span_id: str) -> Provenance:
    return Provenance(
        document_id=model.document.id,
        document_version_id=model.version.id,
        source_span_id=span_id,
        origin=ProvenanceOrigin.SOURCE,
        authority=Authority.EXPLICIT,
        layer=Layer.AUTHORITATIVE,
        extraction_method="m6.governed-example-exact-digest",
    )


def _cells(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [item.replace("\\|", "|").strip() for item in re.split(r"(?<!\\)\|", value)]


def _markdown_table(text: str) -> tuple[list[str], list[list[str]]] | None:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 3 or not lines[0].lstrip().startswith("|"):
        return None
    header = _cells(lines[0])
    separator = _cells(lines[1])
    if len(header) != len(separator) or not all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in separator
    ):
        return None
    rows = [_cells(line) for line in lines[2:] if line.lstrip().startswith("|")]
    if not rows or any(len(row) != len(header) for row in rows):
        return None
    return header, rows


def _requirements_items(
    requirements: Mapping[str, object], key: str
) -> tuple[Mapping[str, object], ...]:
    value = requirements.get(key, ())
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping))


def _input_by_section(inputs: Sequence[SectionRewriteInput]) -> dict[str, SectionRewriteInput]:
    return {item.section_id: item for item in inputs}


def _table_kind(table_id: str) -> TableKind:
    return cast(TableKind, table_id.rsplit("-", 1)[-1].lower())


def _build_tables(
    model: EnhancedDocumentModel,
    inputs: Sequence[SectionRewriteInput],
    requirements: Mapping[str, object],
) -> list[StructuredTable]:
    by_section = _input_by_section(inputs)
    tables: list[StructuredTable] = []
    for table_spec in _requirements_items(requirements, "tables"):
        table_id = str(table_spec.get("id", ""))
        section_id = str(table_spec.get("section_id", ""))
        columns_spec = table_spec.get("columns", ())
        if not table_id or not section_id or not isinstance(columns_spec, Sequence):
            continue
        columns = [
            TableColumn(
                column_id=str(item.get("id", "")),
                label=str(item.get("label", item.get("id", ""))),
                required=bool(item.get("required", False)),
            )
            for item in columns_spec
            if isinstance(item, Mapping) and item.get("id")
        ]
        source = by_section.get(section_id)
        matched: tuple[ApprovedEvidence, list[list[str]]] | None = None
        for evidence in source.source_evidence if source else ():
            parsed = _markdown_table(evidence.quote)
            if parsed is not None and len(parsed[0]) == len(columns):
                matched = (evidence, parsed[1])
                break
        if matched is None:
            raise ValueError(f"governed example lacks complete required table {table_id}")
        evidence, source_rows = matched
        rows = [
            StructuredTableRow(
                row_id=f"ROW-{table_id.removeprefix('TBL-')}-{ordinal:03d}",
                values={
                    column.column_id: value for column, value in zip(columns, values, strict=True)
                },
                source_span_ids=[evidence.span_id],
            )
            for ordinal, values in enumerate(source_rows, start=1)
        ]
        tables.append(
            StructuredTable(
                table_id=table_id,
                table_kind=_table_kind(table_id),
                title=str(table_spec.get("title", table_id)),
                purpose="Source-backed governed table from the selected pack's complete example.",
                section_id=section_id,
                columns=columns,
                rows=rows,
                source_span_ids=[evidence.span_id],
                provenance=[_provenance(model, evidence.span_id)],
            )
        )
    return tables


def _identifier(value: str, prefix: str) -> str | None:
    return next(
        (item for item in _IDENTIFIER_RE.findall(value) if item.startswith(prefix + "-")), None
    )


def _token(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:10].upper()


def _dedupe(objects: Sequence[SemanticObject]) -> list[SemanticObject]:
    result: list[SemanticObject] = []
    seen: set[str] = set()
    for item in objects:
        if item.id not in seen:
            result.append(item)
            seen.add(item.id)
    return result


def _process_objects(
    model: EnhancedDocumentModel,
    tables: Sequence[StructuredTable],
    document_type: DocumentType,
) -> tuple[list[SemanticObject], dict[str, list[str]], dict[str, list[str]]]:
    kind = "steps" if document_type is DocumentType.PROCESS else "actions"
    table = next(item for item in tables if item.table_kind == kind)
    step_ids = [
        str(row.values.get("step_id"))
        if kind == "steps"
        else "STEP-DESK-" + str(row.values.get("action_id", row.row_id)).removeprefix("ACT-")
        for row in table.rows
    ]
    objects: list[SemanticObject] = []
    section_objects: dict[str, list[str]] = {table.section_id: []}
    row_objects: dict[str, list[str]] = {}
    for index, (row, step_id) in enumerate(zip(table.rows, step_ids, strict=True)):
        span_id = row.source_span_ids[0]
        provenance = _provenance(model, span_id)
        performer = row.values.get("performer") or row.values.get("operator") or ""
        role_id = _identifier(performer, "ROLE") or f"ROLE-GOVERNED-{_token(performer)}"
        action = row.values.get("action", "")
        input_text = row.values.get("input") or action
        output_text = row.values.get("output") or row.values.get("expected") or action
        completion_text = row.values.get("completion") or row.values.get("expected") or output_text
        failure_text = (
            row.values.get("failure_path") or "Stop and follow the documented failure path"
        )
        suffix = _token(step_id)
        input_id = f"IN-GOVERNED-{suffix}"
        output_id = f"OUT-GOVERNED-{suffix}"
        precondition_id = f"PRE-GOVERNED-{suffix}"
        completion_id = f"DONE-GOVERNED-{suffix}"
        failure_id = f"ESC-GOVERNED-{suffix}"
        support: list[SemanticObject] = [
            Role(id=role_id, name=performer, provenance=provenance),
            Input(id=input_id, name=input_text, provenance=provenance),
            Output(id=output_id, name=output_text, provenance=provenance),
            CompletionCondition(id=completion_id, name=completion_text, provenance=provenance),
            EscalationPath(id=failure_id, name=failure_text, provenance=provenance),
        ]
        support.append(Precondition(id=precondition_id, name=input_text, provenance=provenance))
        step = ProcessStep(
            id=step_id,
            name=action,
            provenance=provenance,
            performer_ids=[role_id],
            precondition_ids=[precondition_id],
            input_ids=[input_id],
            action=action,
            output_ids=[output_id],
            completion_condition_id=completion_id,
            next_step_id=step_ids[index + 1] if index + 1 < len(step_ids) else None,
            failure_path_id=failure_id,
        )
        objects.extend([*support, step])
        section_objects[table.section_id].append(step.id)
        row_objects[row.row_id] = [step.id]
    return _dedupe(objects), section_objects, row_objects


def _all_evidence(inputs: Sequence[SectionRewriteInput]) -> list[ApprovedEvidence]:
    return [evidence for item in inputs for evidence in item.source_evidence]


def _methodology_objects(
    model: EnhancedDocumentModel,
    inputs: Sequence[SectionRewriteInput],
    tables: Sequence[StructuredTable],
) -> tuple[list[SemanticObject], dict[str, list[str]], dict[str, list[str]]]:
    by_section = _input_by_section(inputs)
    step_input = by_section["SEC-METH-STEPS"]
    step_evidence = next(
        evidence
        for evidence in step_input.source_evidence
        if _NUMBERED_ITEM_RE.search(evidence.quote)
    )
    steps = _NUMBERED_ITEM_RE.findall(step_evidence.quote)
    data = next(item for item in tables if item.table_kind == "data")
    assumptions = next(item for item in tables if item.table_kind == "assumptions")
    validation = next(item for item in tables if item.table_kind == "validation")
    input_row = data.rows[0]
    assumption_row = assumptions.rows[0]
    input_id = f"IN-METH-{_token(input_row.row_id)}"
    parameter_id = f"PARAM-METH-{_token(model.document.id)}"
    limitation_id = f"LIM-METH-{_token(model.document.id)}"
    input_provenance = _provenance(model, input_row.source_span_ids[0])
    assumption_provenance = _provenance(model, assumption_row.source_span_ids[0])
    limitation_evidence = next(
        evidence
        for evidence in by_section["SEC-METH-LIMITATIONS"].source_evidence
        if not evidence.quote.lstrip().startswith("#")
    )
    all_text = "\n".join(evidence.quote for evidence in _all_evidence(inputs))
    implementation_reference = _identifier(all_text, "PROC") or "source-governed implementation"
    validation_checks = [row.values.get("objective", "") for row in validation.rows]
    failure_evidence = next(
        evidence
        for evidence in by_section["SEC-METH-PREP"].source_evidence
        if not evidence.quote.lstrip().startswith("#")
    )
    assumption_id = assumption_row.values.get("assumption_id", "")
    objects: list[SemanticObject] = [
        Input(id=input_id, name="; ".join(input_row.values.values()), provenance=input_provenance),
        Parameter(
            id=parameter_id,
            name=next(item for item in tables if item.table_kind == "models")
            .rows[0]
            .values["parameters"],
            provenance=_provenance(
                model,
                next(item for item in tables if item.table_kind == "models")
                .rows[0]
                .source_span_ids[0],
            ),
        ),
        Assumption(
            id=assumption_id,
            name=assumption_row.values.get("statement", assumption_id),
            statement=assumption_row.values.get("statement"),
            risk_if_violated=assumption_row.values.get("risk"),
            validation_method=assumption_row.values.get("validation"),
            owner_id=None,
            provenance=assumption_provenance,
        ),
        Limitation(
            id=limitation_id,
            name=limitation_evidence.quote,
            statement=limitation_evidence.quote,
            provenance=_provenance(model, limitation_evidence.span_id),
        ),
    ]
    section_objects = {"SEC-METH-STEPS": []}
    for ordinal, transformation in enumerate(steps, start=1):
        suffix = _token(f"{model.document.id}:{ordinal}")
        output_id = f"OUT-METH-{suffix}"
        objects.append(
            Output(
                id=output_id,
                name=transformation,
                provenance=_provenance(model, step_evidence.span_id),
            )
        )
        step = MethodologyStep(
            id=f"MSTEP-GOVERNED-{suffix}",
            name=transformation,
            provenance=_provenance(model, step_evidence.span_id),
            objective=transformation,
            input_ids=[input_id],
            transformation=transformation,
            parameter_ids=[parameter_id],
            assumption_ids=[assumption_id],
            output_ids=[output_id],
            validation_checks=validation_checks,
            failure_conditions=[failure_evidence.quote],
            limitation_ids=[limitation_id],
            implementation_reference=implementation_reference,
        )
        objects.append(step)
        section_objects["SEC-METH-STEPS"].append(step.id)
    return _dedupe(objects), section_objects, {}


def _standard_objects(
    model: EnhancedDocumentModel, tables: Sequence[StructuredTable]
) -> tuple[list[SemanticObject], dict[str, list[str]], dict[str, list[str]]]:
    table = next(item for item in tables if item.table_kind == "requirements")
    objects: list[SemanticObject] = []
    row_objects: dict[str, list[str]] = {}
    for row in table.rows:
        requirement_id = row.values["requirement_id"]
        requirement = Requirement(
            id=requirement_id,
            name=row.values["statement"],
            provenance=_provenance(model, row.source_span_ids[0]),
            attributes={
                "statement": row.values["statement"],
                "applicability": row.values["applicability"],
                "accountable_role_id": row.values["role"],
                "evidence_ids": [row.values["evidence"]],
                "exception_id": row.values["exception"],
            },
        )
        objects.append(requirement)
        row_objects[row.row_id] = [requirement.id]
    return objects, {table.section_id: [item.id for item in objects]}, row_objects


def _metadata_updates(
    model: EnhancedDocumentModel, inputs: Sequence[SectionRewriteInput]
) -> tuple[object, object]:
    text = "\n".join(evidence.quote for evidence in _all_evidence(inputs))
    title = next(
        (line.removeprefix("# ").strip() for line in text.splitlines() if line.startswith("# ")),
        model.document.name,
    )

    def field(name: str) -> str | None:
        match = re.search(rf"\*\*{re.escape(name)}:\*\*\s*([^\n]+)", text)
        return match.group(1).strip() if match else None

    attributes = dict(model.document.attributes)
    attributes.update(
        {
            "owner": field("Owner") or "TBD",
            "effective_date": field("Effective date") or "TBD",
            "next_review_date": field("Next review date") or "TBD",
            "source_document_id": field("Document ID") or "TBD",
            "source_document_version": field("Version") or "TBD",
        }
    )
    document = model.document.model_copy(update={"name": title, "attributes": attributes})
    raw_status = (field("Status") or model.version.status.value).lower()
    status = VersionStatus(raw_status)
    version = model.version.model_copy(
        update={"version": field("Version") or model.version.version, "status": status}
    )
    return document, version


def apply_governed_example_contract(
    model: EnhancedDocumentModel,
    inputs: Sequence[SectionRewriteInput],
    requirements: Mapping[str, object],
) -> EnhancedDocumentModel:
    """Replace generic offline scaffolding with exact source-backed governed structures."""

    tables = _build_tables(model, inputs, requirements)
    old_table_ids = {item.table_id for item in model.tables}
    retained_objects = [item for item in model.objects if item.entity_type is not EntityType.TABLE]
    retained_relationships = [
        item
        for item in model.relationships
        if item.source_id not in old_table_ids and item.target_id not in old_table_ids
    ]
    table_objects: list[SemanticObject] = []
    table_relationships: list[Relationship] = []
    for table in tables:
        provenance = table.provenance[0]
        table_objects.append(
            Table(
                id=table.table_id,
                name=table.title,
                title=table.title,
                headers=[column.label for column in table.columns],
                source_span_ids=table.source_span_ids,
                provenance=provenance,
                authority=provenance.authority,
                layer=provenance.layer,
            )
        )
        table_relationships.append(
            Relationship(
                source_id=table.section_id,
                source_type=EntityType.SECTION,
                relationship_type=RelationshipType.CONTAINS_TABLE,
                target_id=table.table_id,
                target_type=EntityType.TABLE,
                provenance=provenance,
            )
        )
    document_type = model.document.document_type
    if document_type in {DocumentType.PROCESS, DocumentType.DESKTOP_PROCEDURE}:
        primary, section_objects, row_objects = _process_objects(model, tables, document_type)
    elif document_type is DocumentType.METHODOLOGY:
        primary, section_objects, row_objects = _methodology_objects(model, inputs, tables)
    else:
        primary, section_objects, row_objects = _standard_objects(model, tables)
    tables = [
        table.model_copy(
            update={
                "rows": [
                    row.model_copy(update={"object_ids": row_objects.get(row.row_id, [])})
                    for row in table.rows
                ]
            }
        )
        for table in tables
    ]
    governed_table_ids = {item.table_id for item in tables}
    sections = []
    for section in model.sections:
        sections.append(
            section.model_copy(
                update={
                    "table_ids": sorted(
                        governed_table_ids.intersection(
                            table.table_id
                            for table in tables
                            if table.section_id == section.section_id
                        )
                    ),
                    "object_ids": [item for item in section.object_ids if item not in old_table_ids]
                    + section_objects.get(section.section_id, []),
                }
            )
        )
    objects = [*retained_objects, *table_objects, *primary]
    flow_objects = [
        item
        for item in primary
        if item.entity_type in {EntityType.PROCESS_STEP, EntityType.METHODOLOGY_STEP}
    ]
    nodes = [
        MermaidNode(
            node_id="N_" + re.sub(r"[^A-Za-z0-9_]", "_", item.id),
            semantic_id=item.id,
            label=item.name,
            source_span_ids=[item.provenance.source_span_id]
            if item.provenance.source_span_id
            else [],
        )
        for item in flow_objects
    ]
    diagram = MermaidDiagram(
        diagram_id=f"DIAG-{model.document.id.removeprefix('DOC-')}-FLOW",
        diagram_type="process"
        if document_type in {DocumentType.PROCESS, DocumentType.DESKTOP_PROCEDURE}
        else "lineage",
        caption="Structured flow derived from the exact governed example evidence.",
        nodes=nodes,
        edges=[],
        source_object_ids=[item.id for item in flow_objects],
    )
    document, version = _metadata_updates(model, inputs)
    return model.model_copy(
        update={
            "document": document,
            "version": version,
            "tables": tables,
            "sections": sections,
            "objects": objects,
            "relationships": [*retained_relationships, *table_relationships],
            "mermaid": [diagram],
            "open_issues": [
                item for item in model.open_issues if not item.issue_id.startswith("OPEN-M6-TABLE-")
            ],
        }
    )


__all__ = ["apply_governed_example_contract"]
