"""Small model-facing contracts for semantic discovery.

These DTOs deliberately exclude persistence-owned identity, provenance, lifecycle, and
governance fields.  Gemini identifies candidates with call-local keys and source spans; the
application promotes those candidates into the strict domain in a separate deterministic step.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictFloat, StrictStr, field_validator

from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.enums import EntityType, RelationshipType
from document_enhancer.domain.ids import validate_span_id

_APPLICATION_OWNED_ENTITY_TYPES = {
    EntityType.DOCUMENT_IDENTITY,
    EntityType.DOCUMENT_VERSION,
    EntityType.SECTION,
}
PROMOTABLE_ENTITY_TYPES = tuple(
    item.value for item in EntityType if item not in _APPLICATION_OWNED_ENTITY_TYPES
)
DISCOVERY_RELATIONSHIP_TYPES = tuple(item.value for item in RelationshipType)


class SemanticDetail(StrictModel):
    """One optional semantic observation, without an application-owned schema field."""

    key: StrictStr
    value: StrictStr

    @field_validator("key", "value")
    @classmethod
    def validate_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="semantic detail")


class DiscoveryCandidate(StrictModel):
    """A source-linked node candidate using identity local to this provider response."""

    local_key: StrictStr
    entity_type: StrictStr = Field(json_schema_extra={"enum": list(PROMOTABLE_ENTITY_TYPES)})
    name: StrictStr
    aliases: list[StrictStr] = Field(default_factory=list)
    source_span_id: StrictStr
    basis: Literal["explicit", "inferred"]
    confidence: StrictFloat | None = None
    semantic_details: list[SemanticDetail] = Field(default_factory=list)

    @field_validator("local_key", "entity_type", "name")
    @classmethod
    def validate_required_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="discovery candidate field")

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            non_empty(value, field_name="candidate alias")
        return values

    @field_validator("source_span_id")
    @classmethod
    def validate_source_span(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)


class DiscoveryRelationshipCandidate(StrictModel):
    """A typed edge candidate whose endpoints are provider-local candidate keys."""

    local_key: StrictStr
    source_key: StrictStr
    relationship_type: StrictStr = Field(
        json_schema_extra={"enum": list(DISCOVERY_RELATIONSHIP_TYPES)}
    )
    target_key: StrictStr
    source_span_id: StrictStr
    basis: Literal["explicit", "inferred"]
    confidence: StrictFloat | None = None
    semantic_details: list[SemanticDetail] = Field(default_factory=list)

    @field_validator("local_key", "source_key", "relationship_type", "target_key")
    @classmethod
    def validate_required_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="discovery relationship field")

    @field_validator("source_span_id")
    @classmethod
    def validate_source_span(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)


class DiscoverySemanticJudgment(StrictModel):
    """A source-linked completeness judgment that does not create a graph object."""

    kind: Literal["orphan_control", "unmitigated_risk", "incomplete_rule"]
    description: StrictStr
    source_span_id: StrictStr
    subject_key: StrictStr | None = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="discovery judgment description")

    @field_validator("subject_key")
    @classmethod
    def validate_subject_key(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="judgment subject key")

    @field_validator("source_span_id")
    @classmethod
    def validate_source_span(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)


class DiscoveryCandidateBatch(StrictModel):
    """The complete narrow provider response for one discovery call."""

    candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    relationships: list[DiscoveryRelationshipCandidate] = Field(default_factory=list)
    judgments: list[DiscoverySemanticJudgment] = Field(default_factory=list)


__all__ = [
    "DISCOVERY_RELATIONSHIP_TYPES",
    "PROMOTABLE_ENTITY_TYPES",
    "DiscoveryCandidate",
    "DiscoveryCandidateBatch",
    "DiscoveryRelationshipCandidate",
    "DiscoverySemanticJudgment",
    "SemanticDetail",
]
