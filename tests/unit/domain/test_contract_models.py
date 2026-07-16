from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from document_enhancer.domain.analysis import (
    BlockDisposition,
    StructureRecoveryProposal,
)
from document_enhancer.domain.enums import (
    Authority,
    DocumentType,
    EntityType,
    Layer,
    ProvenanceOrigin,
    RelationshipType,
    ReviewStatus,
    SourceBlockType,
    StructureDisposition,
)
from document_enhancer.domain.ontology import (
    DocumentIdentity,
    DocumentVersion,
    EntityRegistry,
    Process,
    ProcessStep,
    Relationship,
    Role,
    is_relationship_allowed,
)
from document_enhancer.domain.provenance import Provenance, TemporalValidity
from document_enhancer.domain.questions import (
    ContentLedger,
    Question,
)
from document_enhancer.domain.semantic import SemanticDocument
from document_enhancer.domain.serialization import (
    model_from_json,
    model_from_yaml,
    model_to_json,
    model_to_yaml,
)
from document_enhancer.domain.source import RawDocument, SourceBlock

DOC_ID = "DOC-TEST-0001"
VERSION_ID = "DOCV-TEST-0001-001"
SPAN = "SPAN-ABCDEFGH"
SOURCE_DIGEST = "a" * 64


def provenance(
    *,
    layer: Layer = Layer.EXTRACTED,
    authority: Authority = Authority.EXPLICIT,
    origin: ProvenanceOrigin = ProvenanceOrigin.SOURCE,
    version_id: str | None = VERSION_ID,
    span_id: str | None = SPAN,
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED,
    confidence: float | None = None,
) -> Provenance:
    return Provenance(
        document_id=DOC_ID,
        document_version_id=version_id,
        source_span_id=span_id,
        origin=origin,
        authority=authority,
        layer=layer,
        confidence=confidence,
        extraction_method="unit_fixture",
        review_status=review_status,
        reviewer_id="ROLE-REVIEWER" if review_status is ReviewStatus.ACCEPTED else None,
    )


def test_provenance_rejects_missing_source_and_backwards_temporal_range() -> None:
    with pytest.raises(ValidationError, match="source_span_id"):
        provenance(span_id=None)
    with pytest.raises(ValidationError, match="valid_to"):
        TemporalValidity(valid_from=date(2026, 2, 1), valid_to=date(2026, 1, 1))


def test_relationship_allowlist_rejects_generic_and_incompatible_edges() -> None:
    assert is_relationship_allowed(
        RelationshipType.HAS_STEP, EntityType.PROCESS, EntityType.PROCESS_STEP
    )
    with pytest.raises(ValidationError, match="RELATED_TO"):
        Relationship.model_validate(
            {
                "source_id": "PROC-TEST-001",
                "source_type": EntityType.PROCESS,
                "predicate": "RELATED_TO",
                "target_id": "RISK-TEST-001",
                "target_type": EntityType.RISK,
                "provenance": provenance(),
            }
        )
    with pytest.raises(ValidationError, match="does not permit"):
        Relationship(
            source_id="PROC-TEST-001",
            source_type=EntityType.PROCESS,
            relationship_type=RelationshipType.MITIGATES,
            target_id="RISK-TEST-001",
            target_type=EntityType.RISK,
            provenance=provenance(),
        )


def test_registry_rejects_dangling_reference_and_layer_overwrite() -> None:
    process = ProcessStep(id="STEP-TEST-001", name="Step", action="Act", provenance=provenance())
    role = Role(id="ROLE-OWNER", name="Owner", provenance=provenance())
    registry = EntityRegistry([process, role])
    relationship = Relationship(
        source_id=process.id,
        source_type=process.entity_type,
        relationship_type=RelationshipType.PERFORMED_BY,
        target_id=role.id,
        target_type=role.entity_type,
        provenance=provenance(),
    )
    registry.validate_relationship(relationship)
    dangling = relationship.model_copy(update={"target_id": "ROLE-MISSING"})
    with pytest.raises(ValueError, match="dangling"):
        registry.validate_relationship(dangling)

    with pytest.raises(ValidationError, match="higher-numbered"):
        Relationship(
            source_id=process.id,
            source_type=process.entity_type,
            relationship_type=RelationshipType.PERFORMED_BY,
            target_id=role.id,
            target_type=role.entity_type,
            provenance=provenance(
                layer=Layer.RETRIEVAL,
                authority=Authority.INFERRED,
                origin=ProvenanceOrigin.MODEL,
                confidence=0.8,
            ),
            overwrites_id=role.id,
            overwrites_layer=Layer.AUTHORITATIVE,
        )


def test_source_blocks_and_recovery_require_exact_ordered_coverage() -> None:
    blocks = [
        SourceBlock(
            ordinal=0,
            block_type=SourceBlockType.HEADING,
            heading_level=1,
            text="Title",
            source_digest=SOURCE_DIGEST,
        ),
        SourceBlock(
            ordinal=1,
            block_type=SourceBlockType.PARAGRAPH,
            text="Body",
            source_digest=SOURCE_DIGEST,
        ),
    ]
    raw = RawDocument(
        document_id=DOC_ID,
        source_digest=SOURCE_DIGEST,
        media_type="text/markdown",
        size_bytes=10,
        blocks=blocks,
        parser_name="fixture",
        parser_version="1",
    )
    proposal = StructureRecoveryProposal(
        recovery_id="RECOVERY-001",
        document_id=DOC_ID,
        source_digest=SOURCE_DIGEST,
        confidence=0.9,
        sections=[],
        dispositions=[
            BlockDisposition(
                span_id=block.span_id or "",
                disposition=StructureDisposition.BODY,
                source_text_digest=block.text_digest or "",
                confidence=0.9,
            )
            for block in blocks
        ],
        model="fake",
        prompt_id="structure.recover",
    )
    assert proposal.validate_against(raw).passed
    proposal.dispositions[1] = proposal.dispositions[0]
    assert not proposal.validate_against(raw).passed


def test_semantic_document_round_trips_json_and_yaml_and_resolves_edges() -> None:
    document = DocumentIdentity(
        id=DOC_ID,
        name="Test document",
        document_type=DocumentType.PROCESS,
        provenance=provenance(version_id=None, layer=Layer.AUTHORITATIVE),
        layer=Layer.AUTHORITATIVE,
        authority=Authority.EXPLICIT,
    )
    version_provenance = provenance(layer=Layer.AUTHORITATIVE, authority=Authority.EXPLICIT)
    version = DocumentVersion(
        id=VERSION_ID,
        name="Version 1",
        document_id=DOC_ID,
        version="1.0",
        status="effective",
        provenance=version_provenance,
        layer=Layer.AUTHORITATIVE,
        authority=Authority.EXPLICIT,
    )
    process = Process(id="PROC-TEST-001", name="Process", provenance=provenance())
    step = ProcessStep(id="STEP-TEST-001", name="Step", action="Act", provenance=provenance())
    edge = Relationship(
        source_id=process.id,
        source_type=process.entity_type,
        relationship_type=RelationshipType.HAS_STEP,
        target_id=step.id,
        target_type=step.entity_type,
        provenance=provenance(),
    )
    semantic = SemanticDocument(
        document=document,
        version=version,
        objects=[process, step],
        relationships=[edge],
        provisional_ids=[],
        template_id="process",
        template_version="0.1.0",
    )
    assert semantic.resolve(step.id).name == "Step"
    assert (
        model_from_json(SemanticDocument, model_to_json(semantic)).model_dump()
        == semantic.model_dump()
    )
    assert (
        model_from_yaml(SemanticDocument, model_to_yaml(semantic)).model_dump()
        == semantic.model_dump()
    )


def test_unknown_critical_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_field"):
        Question.model_validate(
            {
                "question_id": "Q-001",
                "category": "missing",
                "priority": "high",
                "blocking": False,
                "question": "What is the owner?",
                "why_it_matters": "Ownership is required.",
                "extra_field": "unsafe",
            }
        )
    with pytest.raises(ValidationError, match="extra_field"):
        ContentLedger.model_validate(
            {
                "ledger_id": "LEDGER-001",
                "document_id": DOC_ID,
                "entries": [],
                "complete": False,
                "extra_field": "unsafe",
            }
        )
