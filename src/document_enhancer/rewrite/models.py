"""Strict intermediate contracts for governed M6 output.

The intermediate model is deliberately richer than the final Markdown renderer.  It is the
single source used for the Markdown document, tables, Mermaid, and semantic sidecar, which
prevents two independent interpretations of the same rewrite.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from document_enhancer.domain.analysis import EvidenceQuote
from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.enums import EntityType, RelationshipType, ReviewStatus
from document_enhancer.domain.ids import ensure_unique_ids, validate_identifier, validate_span_id
from document_enhancer.domain.ontology import (
    DocumentIdentity,
    DocumentVersion,
    EntityRegistry,
    Relationship,
    SemanticObject,
)
from document_enhancer.domain.provenance import Provenance
from document_enhancer.errors import ValidationError


class RevisionLimitExceeded(ValidationError):
    """Raised when a durable rewrite or audit budget is exhausted."""


class RevisionCounters(StrictModel):
    """Persisted, fail-closed revision budget for the M6/M7 workflow boundary."""

    schema_version: StrictStr = "m6.revision-counters.v1"
    rewrite_revision: StrictInt = Field(default=0, ge=0)
    audit_revision: StrictInt = Field(default=0, ge=0)
    max_rewrite_revisions: StrictInt = Field(default=2, ge=0)
    max_audit_revisions: StrictInt = Field(default=1, ge=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> RevisionCounters:
        if self.rewrite_revision > self.max_rewrite_revisions:
            raise ValueError("rewrite_revision exceeds max_rewrite_revisions")
        if self.audit_revision > self.max_audit_revisions:
            raise ValueError("audit_revision exceeds max_audit_revisions")
        return self

    @property
    def rewrite_count(self) -> int:
        return self.rewrite_revision

    @property
    def audit_count(self) -> int:
        return self.audit_revision

    def consume_rewrite(self) -> RevisionCounters:
        if self.rewrite_revision >= self.max_rewrite_revisions:
            raise RevisionLimitExceeded(
                f"rewrite revision limit exhausted ({self.max_rewrite_revisions})"
            )
        return self.model_copy(update={"rewrite_revision": self.rewrite_revision + 1})

    def consume_audit(self) -> RevisionCounters:
        if self.audit_revision >= self.max_audit_revisions:
            raise RevisionLimitExceeded(
                f"audit revision limit exhausted ({self.max_audit_revisions})"
            )
        return self.model_copy(update={"audit_revision": self.audit_revision + 1})

    # Friendly aliases used by workflow callers and contract tests.
    next_rewrite = consume_rewrite
    next_audit = consume_audit


class OpenIssue(StrictModel):
    """An unsupported, unknown, or TBD item that is visible but not an asserted fact."""

    issue_id: StrictStr
    category: Literal["unsupported", "unknown", "tbd", "ambiguous", "conflicting"]
    statement: StrictStr
    status: Literal["open", "waived", "resolved"] = "open"
    source_span_ids: list[StrictStr] = Field(default_factory=list)
    target_section_id: StrictStr | None = None
    target_object_id: StrictStr | None = None
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    authoritative: StrictBool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("issue_id")
    @classmethod
    def validate_issue_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="open issue id")

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="open issue statement")

    @field_validator("source_span_ids")
    @classmethod
    def validate_issue_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        return values

    @model_validator(mode="after")
    def validate_non_authoritative(self) -> OpenIssue:
        if self.authoritative:
            raise ValueError("open issues cannot be authoritative semantic facts")
        return self


class SectionRewriteDraft(StrictModel):
    """Narrow model output for one governed section rewrite.

    The workflow, not the model, owns section ordering, semantic identities, tables, diagrams,
    and promotion.  This contract limits a provider to prose plus evidence already present in the
    approved section input.
    """

    section_id: StrictStr = Field(pattern=r"^(SEC|PROV-SEC)-[A-Z0-9-]+$")
    body: StrictStr
    source_span_ids: list[StrictStr] = Field(default_factory=list)
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    approved_answer_ids: list[StrictStr] = Field(default_factory=list)
    open_issue_ids: list[StrictStr] = Field(default_factory=list)

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="section rewrite body")

    @field_validator("source_span_ids")
    @classmethod
    def validate_source_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        return values


class EnhancedSection(StrictModel):
    """One target section and its approved, traceable body."""

    section_id: StrictStr = Field(pattern=r"^(SEC|PROV-SEC)-[A-Z0-9-]+$")
    heading: StrictStr
    order: StrictInt = Field(ge=0)
    anchor: StrictStr = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    body: StrictStr
    source_span_ids: list[StrictStr] = Field(default_factory=list)
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    approved_answer_ids: list[StrictStr] = Field(default_factory=list)
    object_ids: list[StrictStr] = Field(default_factory=list)
    table_ids: list[StrictStr] = Field(default_factory=list)
    mermaid_ids: list[StrictStr] = Field(default_factory=list)
    open_issue_ids: list[StrictStr] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)

    @field_validator("heading", "body")
    @classmethod
    def validate_section_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="section text")

    @field_validator("source_span_ids")
    @classmethod
    def validate_section_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        return values

    @model_validator(mode="after")
    def validate_traceability(self) -> EnhancedSection:
        ensure_unique_ids(self.object_ids)
        ensure_unique_ids(self.table_ids)
        if not (self.source_span_ids or self.evidence or self.open_issue_ids or self.provenance):
            raise ValueError(f"section {self.section_id} has no traceability")
        return self


class TableColumn(StrictModel):
    column_id: StrictStr
    label: StrictStr
    required: StrictBool = True

    @field_validator("column_id", "label")
    @classmethod
    def validate_column_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="table column")


class StructuredTableRow(StrictModel):
    row_id: StrictStr
    values: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    source_span_ids: list[StrictStr] = Field(default_factory=list)
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    object_ids: list[StrictStr] = Field(default_factory=list)
    open_issue_ids: list[StrictStr] = Field(default_factory=list)

    @field_validator("row_id")
    @classmethod
    def validate_row_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="table row id")

    @field_validator("source_span_ids")
    @classmethod
    def validate_row_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        return values

    @model_validator(mode="after")
    def validate_row_traceability(self) -> StructuredTableRow:
        if not (self.source_span_ids or self.evidence or self.object_ids or self.open_issue_ids):
            raise ValueError(f"table row {self.row_id} has no provenance or open issue")
        return self


TableKind = Literal[
    "steps",
    "actions",
    "completion",
    "decisions",
    "rules",
    "controls",
    "risks",
    "data",
    "inputs",
    "models",
    "metadata",
    "evidence",
    "assumptions",
    "limitations",
    "exceptions",
    "dependencies",
    "calculators",
    "validation",
    "monitoring",
    "governance",
    "implementation",
    "requirements",
    "obligations",
    "parameters",
    "tools",
    "failure",
    "escalation",
    "inputs_outputs",
    "versions",
    "roles",
    "metrics",
    "custom",
]


class StructuredTable(StrictModel):
    table_id: StrictStr = Field(pattern=r"^(TBL|PROV-TBL)-[A-Z0-9-]+$")
    table_kind: TableKind
    title: StrictStr
    purpose: StrictStr
    section_id: StrictStr = Field(pattern=r"^(SEC|PROV-SEC)-[A-Z0-9-]+$")
    columns: list[TableColumn] = Field(min_length=1)
    rows: list[StructuredTableRow] = Field(min_length=1)
    source_span_ids: list[StrictStr] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)

    @field_validator("title", "purpose")
    @classmethod
    def validate_table_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="table field")

    @model_validator(mode="after")
    def validate_table_shape(self) -> StructuredTable:
        ensure_unique_ids(column.column_id for column in self.columns)
        ensure_unique_ids(row.row_id for row in self.rows)
        columns = {column.column_id for column in self.columns}
        for row in self.rows:
            unknown = set(row.values) - columns
            if unknown:
                raise ValueError(f"table row {row.row_id} has unknown columns: {sorted(unknown)}")
        if not (self.source_span_ids or self.provenance):
            raise ValueError(f"table {self.table_id} has no provenance")
        return self


_MERMAID_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class MermaidNode(StrictModel):
    node_id: StrictStr
    semantic_id: StrictStr
    label: StrictStr
    source_span_ids: list[StrictStr] = Field(default_factory=list)

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, value: StrictStr) -> StrictStr:
        if not _MERMAID_ID_RE.fullmatch(value):
            raise ValueError("Mermaid node IDs must be syntax-safe ASCII identifiers")
        return value

    @field_validator("semantic_id")
    @classmethod
    def validate_semantic_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="Mermaid semantic id")

    @field_validator("source_span_ids")
    @classmethod
    def validate_mermaid_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        return values


class MermaidEdge(StrictModel):
    edge_id: StrictStr
    source_node_id: StrictStr
    target_node_id: StrictStr
    relationship_type: RelationshipType | None = None
    label: StrictStr | None = None

    @field_validator("edge_id")
    @classmethod
    def validate_edge_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="Mermaid edge id")


class MermaidDiagram(StrictModel):
    diagram_id: StrictStr
    diagram_type: Literal["process", "decision", "dependency", "lineage"]
    caption: StrictStr
    nodes: list[MermaidNode] = Field(default_factory=list)
    edges: list[MermaidEdge] = Field(default_factory=list)
    source_object_ids: list[StrictStr] = Field(default_factory=list)

    @field_validator("diagram_id")
    @classmethod
    def validate_diagram_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="diagram id")

    @model_validator(mode="after")
    def validate_cross_references(self) -> MermaidDiagram:
        ensure_unique_ids(node.node_id for node in self.nodes)
        ensure_unique_ids(edge.edge_id for edge in self.edges)
        node_ids = {node.node_id for node in self.nodes}
        for edge in self.edges:
            if edge.source_node_id not in node_ids or edge.target_node_id not in node_ids:
                raise ValueError(f"Mermaid edge {edge.edge_id} references an unknown node")
        return self


class EnhancedDocumentModel(StrictModel):
    """Validated M6 intermediate representation shared by all output producers."""

    schema_version: StrictStr = "m6.enhanced-document.v1"
    document: DocumentIdentity
    version: DocumentVersion
    template_id: StrictStr
    template_version: StrictStr
    reference_pack_id: StrictStr
    reference_pack_version: StrictStr
    ledger_id: StrictStr
    sections: list[EnhancedSection] = Field(min_length=1)
    tables: list[StructuredTable] = Field(default_factory=list)
    objects: list[SemanticObject] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    mermaid: list[MermaidDiagram] = Field(default_factory=list)
    open_issues: list[OpenIssue] = Field(default_factory=list)
    revision_counters: RevisionCounters = Field(default_factory=RevisionCounters)
    provisional_ids: list[StrictStr] = Field(default_factory=list)
    markdown_artifact: StrictStr = "output/enhanced.md"
    markdown_digest: StrictStr | None = None
    semantic_artifact: StrictStr = "output/enhanced.semantic.yaml"
    validation_passed: StrictBool = True
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "template_id",
        "template_version",
        "reference_pack_id",
        "reference_pack_version",
        "ledger_id",
    )
    @classmethod
    def validate_model_metadata(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="enhanced model metadata")

    @model_validator(mode="after")
    def validate_model(self) -> EnhancedDocumentModel:
        if self.version.document_id != self.document.id:
            raise ValueError("version document_id must match document.id")
        entities = [self.document, self.version, *self.objects]
        ensure_unique_ids(entity.id for entity in entities)
        ensure_unique_ids(section.section_id for section in self.sections)
        ensure_unique_ids(table.table_id for table in self.tables)
        ensure_unique_ids(issue.issue_id for issue in self.open_issues)
        known = {entity.id for entity in entities}
        for entity in self.objects:
            if entity.provenance.document_id != self.document.id:
                raise ValueError(f"object {entity.id} has unrelated provenance")
            structural = entity.entity_type in {
                EntityType.SECTION,
                EntityType.TABLE,
                EntityType.FIGURE,
            }
            approved_non_source = entity.provenance.origin.value in {
                "answer",
                "reference",
                "steering",
            } and entity.review_status in {ReviewStatus.ACCEPTED, ReviewStatus.WAIVED}
            if (
                not structural
                and entity.provenance.source_span_id is None
                and not approved_non_source
            ):
                raise ValueError(
                    f"authoritative object {entity.id} lacks approved source or reviewer provenance"
                )
        if set(self.provisional_ids) != {
            entity.id for entity in self.objects if entity.provisional
        }:
            raise ValueError("provisional_ids must exactly list provisional objects")
        section_ids = {section.section_id for section in self.sections}
        table_ids = {table.table_id for table in self.tables}
        for section in self.sections:
            if set(section.table_ids) - table_ids:
                raise ValueError(f"section {section.section_id} references an unknown table")
            if set(section.object_ids) - known:
                raise ValueError(f"section {section.section_id} references an unknown object")
        for table in self.tables:
            if table.section_id not in section_ids:
                raise ValueError(f"table {table.table_id} references an unknown section")
        registry = EntityRegistry(entities)
        registry.validate_relationships(self.relationships)
        for relationship in self.relationships:
            if relationship.provenance.document_id != self.document.id:
                raise ValueError(f"relationship {relationship.id} has unrelated provenance")
            structural_edge = relationship.source_type in {
                EntityType.DOCUMENT_IDENTITY,
                EntityType.DOCUMENT_VERSION,
                EntityType.SECTION,
                EntityType.TABLE,
                EntityType.FIGURE,
            } or relationship.target_type in {
                EntityType.DOCUMENT_IDENTITY,
                EntityType.DOCUMENT_VERSION,
                EntityType.SECTION,
                EntityType.TABLE,
                EntityType.FIGURE,
            }
            if (
                not structural_edge
                and relationship.provenance.source_span_id is None
                and relationship.provenance.origin.value not in {"answer", "reference", "steering"}
            ):
                raise ValueError(
                    f"authoritative relationship {relationship.id} lacks approved provenance"
                )
        return self

    @property
    def semantic_objects(self) -> tuple[SemanticObject, ...]:
        return tuple(self.objects)

    def assert_valid(self) -> None:
        if not self.validation_passed:
            raise ValueError("enhanced document model is not validated")


EnhancedDocument = EnhancedDocumentModel
IntermediateEnhancedDocument = EnhancedDocumentModel


__all__ = [
    "EnhancedDocumentModel",
    "EnhancedDocument",
    "IntermediateEnhancedDocument",
    "EnhancedSection",
    "MermaidDiagram",
    "MermaidEdge",
    "MermaidNode",
    "OpenIssue",
    "RevisionCounters",
    "RevisionLimitExceeded",
    "SectionRewriteDraft",
    "StructuredTable",
    "StructuredTableRow",
    "TableColumn",
]
