"""Canonical semantic sidecar and graph validation."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import AliasChoices, Field, StrictBool, StrictStr, field_validator, model_validator

from document_enhancer.domain.analysis import Finding
from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.ids import ensure_unique_ids
from document_enhancer.domain.ontology import (
    DocumentIdentity,
    DocumentVersion,
    Entity,
    EntityRegistry,
    Relationship,
    SemanticObject,
)


class SemanticDocument(StrictModel):
    """Versioned canonical object graph emitted beside enhanced Markdown."""

    schema_version: StrictStr = "0.1.0"
    document: DocumentIdentity
    version: DocumentVersion
    objects: list[SemanticObject] = Field(
        default_factory=list,
        validation_alias=AliasChoices("objects", "entities"),
    )
    relationships: list[Relationship] = Field(default_factory=list)
    open_issues: list[Finding] = Field(default_factory=list)
    provisional_ids: list[StrictStr] = Field(default_factory=list)
    template_id: StrictStr
    template_version: StrictStr
    ontology_version: StrictStr = "0.1.0"
    reference_pack_id: StrictStr | None = None
    reference_pack_version: StrictStr | None = None
    markdown_artifact: StrictStr | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    validation_passed: StrictBool = True

    @field_validator(
        "schema_version",
        "template_id",
        "template_version",
        "ontology_version",
        "reference_pack_id",
        "reference_pack_version",
    )
    @classmethod
    def validate_metadata(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="semantic metadata")

    @model_validator(mode="after")
    def validate_graph(self) -> SemanticDocument:
        if self.version.document_id != self.document.id:
            raise ValueError("DocumentVersion.document_id must equal SemanticDocument.document.id")
        if self.document.provenance.document_id != self.document.id:
            raise ValueError("document provenance must identify the document itself")
        if self.version.provenance.document_id != self.document.id:
            raise ValueError("version provenance must point to the owning document")
        entities: list[Entity] = [self.document, self.version, *self.objects]
        ensure_unique_ids(entity.id for entity in entities)
        for entity in entities:
            if entity.provenance.document_id != self.document.id:
                raise ValueError(f"{entity.id} has provenance for another document")
            if (
                entity is not self.document
                and entity.provenance.document_version_id is not None
                and entity.provenance.document_version_id != self.version.id
            ):
                raise ValueError(f"{entity.id} has provenance for another document version")
        expected_provisional = {entity.id for entity in entities if entity.provisional}
        if set(self.provisional_ids) != expected_provisional:
            raise ValueError("provisional_ids must exactly list provisional graph objects")
        registry = EntityRegistry(entities)
        registry.validate_relationships(self.relationships)
        for relationship in self.relationships:
            if relationship.provenance.document_id != self.document.id:
                raise ValueError(f"{relationship.id} has provenance for another document")
            if (
                relationship.provenance.document_version_id is not None
                and relationship.provenance.document_version_id != self.version.id
            ):
                raise ValueError(f"{relationship.id} has provenance for another document version")
        return self

    @property
    def entities(self) -> tuple[SemanticObject, ...]:
        """Compatibility read accessor for callers that use the plan's graph vocabulary."""

        return tuple(self.objects)

    def resolve(self, identifier: str) -> Entity:
        return EntityRegistry([self.document, self.version, *self.objects]).resolve(identifier)

    def validate_references(self) -> None:
        EntityRegistry([self.document, self.version, *self.objects]).validate_relationships(
            self.relationships
        )


__all__ = ["SemanticDocument"]
