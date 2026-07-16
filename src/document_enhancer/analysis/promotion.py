"""Deterministic promotion from model-facing discovery DTOs to the strict domain."""

from __future__ import annotations

import hashlib
from collections import Counter

from pydantic import TypeAdapter

from document_enhancer.domain.analysis import DiscoveryAnalysis, Finding
from document_enhancer.domain.enums import (
    Authority,
    EntityType,
    FindingSeverity,
    FindingType,
    Layer,
    ProvenanceOrigin,
    RelationshipType,
    ReviewStatus,
)
from document_enhancer.domain.ids import allocate_provisional_id
from document_enhancer.domain.ontology import EntityRegistry, Relationship, SemanticObject
from document_enhancer.domain.provenance import Provenance
from document_enhancer.llm.profiles import ROUTE_FLASH

from .common import make_lint_finding
from .models import AnalysisRequest
from .provider_models import (
    PROMOTABLE_ENTITY_TYPES,
    DiscoveryCandidate,
    DiscoveryCandidateBatch,
    DiscoveryRelationshipCandidate,
    DiscoverySemanticJudgment,
    SemanticDetail,
)

_PROMPT_ID = "analysis.process-methodology-discovery"
_SEMANTIC_OBJECT_ADAPTER = TypeAdapter(SemanticObject)


def _token(*values: str, length: int = 12) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()[:length].upper()


def _details(values: list[SemanticDetail]) -> dict[str, str]:
    keys = [item.key for item in values]
    if len(keys) != len(set(keys)):
        raise ValueError("semantic detail keys must be unique within one candidate")
    return {item.key: item.value for item in values}


def _provenance(
    request: AnalysisRequest,
    *,
    source_span_id: str,
    basis: str,
    confidence: float | None,
) -> Provenance:
    if source_span_id not in request.authoritative_span_ids:
        raise ValueError(f"unknown source span {source_span_id}")
    inferred = basis == "inferred"
    if inferred and confidence is None:
        # Confidence is a model judgment. The application must never manufacture it.
        raise ValueError("inferred candidate is missing model confidence")
    return Provenance(
        document_id=request.document_id,
        source_span_id=source_span_id,
        origin=ProvenanceOrigin.MODEL if inferred else ProvenanceOrigin.SOURCE,
        authority=Authority.INFERRED if inferred else Authority.EXPLICIT,
        layer=Layer.EXTRACTED,
        confidence=confidence,
        extraction_method=_PROMPT_ID,
        extracted_at=request.requested_at,
        review_status=ReviewStatus.UNREVIEWED,
    )


def _quarantine_finding(
    request: AnalysisRequest,
    *,
    item_kind: str,
    item_key: str,
    ordinal: int,
    source_span_id: str,
    error: Exception | str,
) -> Finding:
    known_spans = set(request.authoritative_span_ids)
    evidence_spans = (
        (source_span_id,) if source_span_id in known_spans else request.authoritative_span_ids[:1]
    )
    error_text = str(error)
    if "missing model confidence" in error_text:
        reason = "inferred candidate is missing model confidence"
    elif "unknown source span" in error_text:
        reason = "candidate references a source span outside the authoritative input"
    elif "was not promoted" in error_text or "not provider-promotable" in error_text:
        reason = "candidate depends on an object that was not safely promoted"
    elif "must be unique" in error_text or "duplicate" in error_text:
        reason = "candidate local key is not unique"
    else:
        reason = f"{type(error).__name__}: candidate violates deterministic promotion rules"
    return make_lint_finding(
        request,
        check_id="DISCOVERY-CANDIDATE-QUARANTINE",
        category="candidate_quarantine",
        severity=FindingSeverity.BLOCKER,
        finding_type=FindingType.EXTRACTION_RISK,
        span_ids=evidence_spans,
        impact=f"{item_kind} candidate {ordinal} was quarantined: {reason}",
        proposed_disposition=(
            "Review or correct this candidate independently; other valid discovery candidates "
            "remain available for Gate 1 review."
        ),
        requirement_id=None if evidence_spans else "SYSTEM-DISCOVERY-PROMOTION",
        requires_human_answer=True,
        blocking=True,
        details=(item_kind, item_key, str(ordinal)),
    )


def _duplicate_keys(
    items: list[DiscoveryCandidate] | list[DiscoveryRelationshipCandidate],
) -> set[str]:
    counts = Counter(item.local_key for item in items)
    return {key for key, count in counts.items() if count > 1}


def _promote_candidate(
    request: AnalysisRequest,
    candidate: DiscoveryCandidate,
    *,
    existing_ids: tuple[str, ...],
) -> SemanticObject:
    if candidate.entity_type not in PROMOTABLE_ENTITY_TYPES:
        raise ValueError(f"entity type {candidate.entity_type!r} is not provider-promotable")
    entity_type = EntityType(candidate.entity_type)
    provenance = _provenance(
        request,
        source_span_id=candidate.source_span_id,
        basis=candidate.basis,
        confidence=candidate.confidence,
    )
    identifier = allocate_provisional_id(
        entity_type,
        candidate.name[:40],
        existing_ids=existing_ids,
        namespace=(
            f"{request.document_id}|{request.source_digest}|"
            f"{candidate.local_key}|{candidate.source_span_id}"
        ),
    )
    return _SEMANTIC_OBJECT_ADAPTER.validate_python(
        {
            "id": identifier,
            "entity_type": entity_type,
            "name": candidate.name,
            "aliases": candidate.aliases,
            "provenance": provenance,
            "authority": Authority.INFERRED
            if candidate.basis == "inferred"
            else Authority.EXPLICIT,
            "layer": Layer.EXTRACTED,
            "review_status": ReviewStatus.UNREVIEWED,
            "attributes": _details(candidate.semantic_details),
            "provisional": True,
        }
    )


def _promote_relationship(
    request: AnalysisRequest,
    candidate: DiscoveryRelationshipCandidate,
    *,
    entities_by_key: dict[str, SemanticObject],
    registry: EntityRegistry,
) -> Relationship:
    try:
        source = entities_by_key[candidate.source_key]
        target = entities_by_key[candidate.target_key]
    except KeyError as exc:
        raise ValueError(f"relationship endpoint {exc.args[0]!r} was not promoted") from exc
    try:
        relationship_type = RelationshipType(candidate.relationship_type)
    except ValueError as exc:
        raise ValueError(f"unknown relationship type {candidate.relationship_type!r}") from exc
    provenance = _provenance(
        request,
        source_span_id=candidate.source_span_id,
        basis=candidate.basis,
        confidence=candidate.confidence,
    )
    relationship = Relationship(
        id=(
            "EDGE-"
            + _token(
                request.document_id,
                request.source_digest,
                candidate.local_key,
                source.id,
                relationship_type.value,
                target.id,
            )
        ),
        source_id=source.id,
        source_type=source.entity_type,
        relationship_type=relationship_type,
        target_id=target.id,
        target_type=target.entity_type,
        provenance=provenance,
        authority=Authority.INFERRED if candidate.basis == "inferred" else Authority.EXPLICIT,
        layer=Layer.EXTRACTED,
        review_status=ReviewStatus.UNREVIEWED,
        confidence=candidate.confidence,
        attributes=_details(candidate.semantic_details),
    )
    registry.validate_relationship(relationship)
    return relationship


def _promote_judgment(
    request: AnalysisRequest,
    judgment: DiscoverySemanticJudgment,
    *,
    entities_by_key: dict[str, SemanticObject],
) -> tuple[str, str]:
    if judgment.source_span_id not in request.authoritative_span_ids:
        raise ValueError(f"unknown source span {judgment.source_span_id}")
    if judgment.subject_key is not None and judgment.subject_key not in entities_by_key:
        raise ValueError(f"judgment subject {judgment.subject_key!r} was not promoted")
    rendered = f"{judgment.description} [source: {judgment.source_span_id}]"
    return judgment.kind, rendered


def promote_discovery_candidate_batch(
    request: AnalysisRequest,
    batch: DiscoveryCandidateBatch,
) -> DiscoveryAnalysis:
    """Promote valid items and retain item-level failures as non-promoted findings.

    The same validated request and provider batch produce byte-equivalent domain data, including
    IDs and application-owned timestamps. Strict domain validation still runs for every promoted
    node and edge; quarantine is not promotion.
    """

    objects: list[SemanticObject] = []
    entities_by_key: dict[str, SemanticObject] = {}
    findings: list[Finding] = []
    duplicate_candidates = _duplicate_keys(batch.candidates)

    for ordinal, candidate in enumerate(batch.candidates):
        try:
            if candidate.local_key in duplicate_candidates:
                raise ValueError("candidate local_key is duplicated in this provider batch")
            promoted = _promote_candidate(
                request,
                candidate,
                existing_ids=tuple(item.id for item in objects),
            )
        except (KeyError, TypeError, ValueError) as exc:
            findings.append(
                _quarantine_finding(
                    request,
                    item_kind="entity",
                    item_key=candidate.local_key,
                    ordinal=ordinal,
                    source_span_id=candidate.source_span_id,
                    error=exc,
                )
            )
            continue
        objects.append(promoted)
        entities_by_key[candidate.local_key] = promoted

    registry = EntityRegistry(objects)
    relationships: list[Relationship] = []
    duplicate_relationships = _duplicate_keys(batch.relationships)
    for ordinal, candidate in enumerate(batch.relationships):
        try:
            if candidate.local_key in duplicate_relationships:
                raise ValueError("relationship local_key is duplicated in this provider batch")
            promoted_relationship = _promote_relationship(
                request,
                candidate,
                entities_by_key=entities_by_key,
                registry=registry,
            )
        except (KeyError, TypeError, ValueError) as exc:
            findings.append(
                _quarantine_finding(
                    request,
                    item_kind="relationship",
                    item_key=candidate.local_key,
                    ordinal=ordinal,
                    source_span_id=candidate.source_span_id,
                    error=exc,
                )
            )
            continue
        relationships.append(promoted_relationship)

    judgments: dict[str, list[str]] = {
        "orphan_control": [],
        "unmitigated_risk": [],
        "incomplete_rule": [],
    }
    for ordinal, judgment in enumerate(batch.judgments):
        key = judgment.subject_key or judgment.kind
        try:
            kind, rendered = _promote_judgment(
                request,
                judgment,
                entities_by_key=entities_by_key,
            )
        except (KeyError, TypeError, ValueError) as exc:
            findings.append(
                _quarantine_finding(
                    request,
                    item_kind="judgment",
                    item_key=key,
                    ordinal=ordinal,
                    source_span_id=judgment.source_span_id,
                    error=exc,
                )
            )
            continue
        judgments[kind].append(rendered)

    analysis_id = "AN-DISCOVERY-" + _token(
        request.document_id,
        request.source_digest,
        _PROMPT_ID,
    )
    return DiscoveryAnalysis(
        analysis_id=analysis_id,
        analysis_type="discovery",
        document_id=request.document_id,
        source_digest=request.source_digest,
        findings=findings,
        created_at=request.requested_at,
        model_route=ROUTE_FLASH,
        prompt_id=_PROMPT_ID,
        objects=objects,
        candidate_relationships=relationships,
        orphan_controls=judgments["orphan_control"],
        unmitigated_risks=judgments["unmitigated_risk"],
        incomplete_rules=judgments["incomplete_rule"],
        mermaid=None,
    )


__all__ = ["promote_discovery_candidate_batch"]
