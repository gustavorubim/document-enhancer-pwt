"""Domain contracts for ontology, provenance, and machine artifacts."""

from document_enhancer.domain.enums import *  # noqa: F403
from document_enhancer.domain.ids import (
    allocate_provisional_id,
    allocate_span_id,
    ensure_unique_ids,
    validate_entity_id,
    validate_identifier,
    validate_sha256,
    validate_span_id,
)
from document_enhancer.domain.ontology import (
    ALLOWED_RELATIONSHIPS,
    Entity,
    EntityRegistry,
    Relationship,
    SemanticObject,
    is_relationship_allowed,
)
from document_enhancer.domain.provenance import Provenance, SourceLocation, TemporalValidity
from document_enhancer.domain.semantic import SemanticDocument

__all__ = [
    "ALLOWED_RELATIONSHIPS",
    "Entity",
    "EntityRegistry",
    "Provenance",
    "Relationship",
    "SemanticDocument",
    "SemanticObject",
    "SourceLocation",
    "TemporalValidity",
    "allocate_provisional_id",
    "allocate_span_id",
    "ensure_unique_ids",
    "is_relationship_allowed",
    "validate_entity_id",
    "validate_identifier",
    "validate_sha256",
    "validate_span_id",
]
