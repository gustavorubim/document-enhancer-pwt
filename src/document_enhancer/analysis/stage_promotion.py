"""Model-facing analysis DTOs and deterministic promotion into the strict domain.

The provider may judge document content, but it does not own persisted identity or call
provenance.  These DTOs therefore omit application-owned fields.  Their pre-validation
normalizers discard those fields when replaying older recorded responses, which also proves that
provider-supplied identities cannot influence the promoted result.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import (
    Field,
    StrictBool,
    StrictFloat,
    StrictStr,
    field_validator,
    model_validator,
)

from document_enhancer.domain.analysis import (
    AnalysisReport,
    ChunkCandidate,
    EvidenceQuote,
    Finding,
    MacroAnalysis,
    RagReadinessAnalysis,
    RubricScore,
    SectionAnalysis,
    SectionMapping,
    SynthesisAnalysis,
)
from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.enums import DocumentType, FindingSeverity, FindingType
from document_enhancer.llm.profiles import ROUTE_FLASH

from .common import canonical_json, make_lint_finding, validate_finding
from .models import AnalysisRequest

_APPLICATION_ANALYSIS_FIELDS = {
    "analysis_id",
    "created_at",
    "document_id",
    "model_route",
    "prompt_id",
    "source_digest",
    "version_id",
}
_APPLICATION_REPORT_FIELDS = {"document_id", "generated_at", "source_digest"}

_UNSUPPORTED_VALIDATION_KEYS = {
    "discriminator",
    "exclusiveMaximum",
    "exclusiveMinimum",
    "maxLength",
    "maximum",
    "minLength",
    "minimum",
    "multipleOf",
    "pattern",
    "uniqueItems",
}


def _provider_schema(value: Any) -> Any:
    """Return a semantics-preserving Gemini subset of a Pydantic JSON Schema."""

    if isinstance(value, list):
        return [_provider_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned: dict[str, Any] = {}
    for original_key, item in value.items():
        if original_key in _UNSUPPORTED_VALIDATION_KEYS:
            continue
        if original_key == "const":
            cleaned["enum"] = [item]
            continue
        key = "anyOf" if original_key == "oneOf" else original_key
        if key == "additionalProperties" and item is True:
            cleaned[key] = False
        else:
            cleaned[key] = _provider_schema(item)
    return cleaned


def _without_fields(value: object, fields: set[str]) -> object:
    if not isinstance(value, Mapping):
        return value
    return {key: item for key, item in value.items() if key not in fields}


class ProviderFinding(StrictModel):
    """A model judgment without an application-owned finding ID."""

    category: StrictStr
    severity: FindingSeverity
    finding_type: FindingType
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    target_template_section: StrictStr | None = None
    target_object_id: StrictStr | None = None
    requirement_id: StrictStr | None = None
    impact: StrictStr
    proposed_disposition: StrictStr
    requires_human_answer: StrictBool
    blocking: StrictBool = False

    @model_validator(mode="before")
    @classmethod
    def discard_provider_identity(cls, value: object) -> object:
        return _without_fields(value, {"finding_id"})

    @field_validator("category", "impact", "proposed_disposition")
    @classmethod
    def validate_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="provider finding field")


class _ProviderAnalysisBase(StrictModel):
    findings: list[ProviderFinding] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def discard_application_fields(cls, value: object) -> object:
        return _without_fields(value, _APPLICATION_ANALYSIS_FIELDS)


class ProviderMacroAnalysis(_ProviderAnalysisBase):
    analysis_type: Literal["macro"] = "macro"
    candidate_document_type: DocumentType | None = None
    candidate_confidence: StrictFloat | None = Field(default=None, ge=0.0, le=1.0)
    purpose: StrictStr | None = None
    audience: StrictStr | None = None
    owner_id: StrictStr | None = None
    authority: StrictStr | None = None
    lifecycle_status: StrictStr | None = None
    scope: StrictStr | None = None
    template_fit: StrictStr | None = None
    alternative_templates: list[StrictStr] = Field(default_factory=list)
    rubric_scores: list[RubricScore] = Field(default_factory=list)


class ProviderSectionAnalysis(_ProviderAnalysisBase):
    analysis_type: Literal["sections"] = "sections"
    mappings: list[SectionMapping] = Field(default_factory=list)
    missing_target_sections: list[StrictStr] = Field(default_factory=list)
    contradictions: list[StrictStr] = Field(default_factory=list)
    repeated_content: list[StrictStr] = Field(default_factory=list)
    terminology_drift: list[StrictStr] = Field(default_factory=list)


class ProviderRagReadinessAnalysis(_ProviderAnalysisBase):
    analysis_type: Literal["rag_readiness"] = "rag_readiness"
    undefined_acronyms: list[StrictStr] = Field(default_factory=list)
    vague_references: list[StrictStr] = Field(default_factory=list)
    missing_ids: list[StrictStr] = Field(default_factory=list)
    missing_provenance: list[StrictStr] = Field(default_factory=list)
    oversized_sections: list[StrictStr] = Field(default_factory=list)
    mixed_topic_spans: list[StrictStr] = Field(default_factory=list)
    candidate_chunks: list[ChunkCandidate] = Field(default_factory=list)
    candidate_objects: list[StrictStr] = Field(default_factory=list)


class ProviderSynthesisAnalysis(_ProviderAnalysisBase):
    analysis_type: Literal["synthesis"] = "synthesis"


class _ProviderStageReport(StrictModel):
    @model_validator(mode="before")
    @classmethod
    def discard_application_fields(cls, value: object) -> object:
        return _without_fields(value, _APPLICATION_REPORT_FIELDS)

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return _provider_schema(super().model_json_schema(*args, **kwargs))


class GeminiMacroAnalysisReport(_ProviderStageReport):
    analyses: list[ProviderMacroAnalysis]


class GeminiSectionAnalysisReport(_ProviderStageReport):
    analyses: list[ProviderSectionAnalysis]


class GeminiRagReadinessAnalysisReport(_ProviderStageReport):
    analyses: list[ProviderRagReadinessAnalysis]


class GeminiSynthesisAnalysisReport(_ProviderStageReport):
    analyses: list[ProviderSynthesisAnalysis]


ProviderStageReport = (
    GeminiMacroAnalysisReport
    | GeminiSectionAnalysisReport
    | GeminiRagReadinessAnalysisReport
    | GeminiSynthesisAnalysisReport
)

_STAGE_CONTRACTS: dict[
    str,
    tuple[
        type[ProviderMacroAnalysis]
        | type[ProviderSectionAnalysis]
        | type[ProviderRagReadinessAnalysis]
        | type[ProviderSynthesisAnalysis],
        type[MacroAnalysis]
        | type[SectionAnalysis]
        | type[RagReadinessAnalysis]
        | type[SynthesisAnalysis],
        str,
    ],
] = {
    "analysis.macro": (ProviderMacroAnalysis, MacroAnalysis, "MACRO"),
    "analysis.sections": (ProviderSectionAnalysis, SectionAnalysis, "SECTIONS"),
    "analysis.rag-readiness": (
        ProviderRagReadinessAnalysis,
        RagReadinessAnalysis,
        "RAGREADINESS",
    ),
    "analysis.synthesize-findings": (
        ProviderSynthesisAnalysis,
        SynthesisAnalysis,
        "SYNTHESIS",
    ),
}


def _token(*values: str, length: int = 16) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()[:length].upper()


def _finding_id(
    request: AnalysisRequest,
    *,
    stage_token: str,
    prompt_id: str,
    finding: ProviderFinding,
    occurrence: int,
) -> str:
    semantic_payload = canonical_json(finding.model_dump(mode="json"))
    token = _token(
        request.document_id,
        request.source_digest,
        prompt_id,
        semantic_payload,
    )
    base = f"FND-{stage_token}-{token}"
    return base if occurrence == 1 else f"{base}-{occurrence}"


def _promote_rag_candidate_chunks(
    request: AnalysisRequest,
    analysis: ProviderRagReadinessAnalysis,
) -> tuple[list[ChunkCandidate], list[Finding]]:
    """Promote only source-bound chunk suggestions and quarantine invalid items visibly."""

    known_spans = set(request.authoritative_span_ids)
    duplicate_keys = {
        key
        for key, count in Counter(chunk.chunk_key for chunk in analysis.candidate_chunks).items()
        if count > 1
    }
    promoted: list[ChunkCandidate] = []
    findings: list[Finding] = []
    for ordinal, chunk in enumerate(analysis.candidate_chunks, start=1):
        reasons: list[str] = []
        if chunk.chunk_key in duplicate_keys:
            reasons.append("duplicate_chunk_key")
        if not chunk.source_span_ids:
            reasons.append("missing_source_spans")
        elif set(chunk.source_span_ids) - known_spans:
            reasons.append("unknown_source_spans")
        if not reasons:
            promoted.append(chunk)
            continue

        evidence_spans = tuple(
            span_id for span_id in chunk.source_span_ids if span_id in known_spans
        )[:1]
        if not evidence_spans:
            evidence_spans = request.authoritative_span_ids[:1]
        findings.append(
            make_lint_finding(
                request,
                check_id="RAG-CANDIDATE-CHUNK-QUARANTINE",
                category="candidate_chunk_quarantine",
                severity=FindingSeverity.BLOCKER,
                finding_type=FindingType.EXTRACTION_RISK,
                span_ids=evidence_spans,
                impact=(
                    f"RAG candidate chunk {ordinal} was quarantined because its source binding "
                    "did not resolve against the authoritative input."
                ),
                proposed_disposition=(
                    "Review the source boundaries and reconstruct this candidate chunk from "
                    "authoritative spans before RAG promotion."
                ),
                requirement_id=None if evidence_spans else "SYSTEM-RAG-CHUNK-PROMOTION",
                requires_human_answer=True,
                blocking=True,
                details=(chunk.chunk_key, *reasons),
            )
        )
    return promoted, findings


def promote_stage_report(
    request: AnalysisRequest,
    provider_report: ProviderStageReport,
    *,
    prompt_id: str,
) -> AnalysisReport:
    """Construct one strict stage report using only request-owned identity and provenance."""

    try:
        provider_type, domain_type, stage_token = _STAGE_CONTRACTS[prompt_id]
    except KeyError as exc:
        raise ValueError(f"unsupported analysis promotion stage: {prompt_id}") from exc
    if len(provider_report.analyses) != 1:
        raise ValueError(f"{prompt_id} must return exactly one analysis result")
    provider_analysis = provider_report.analyses[0]
    if not isinstance(provider_analysis, provider_type):
        raise ValueError(f"{prompt_id} returned the wrong provider analysis type")

    payload_counts: Counter[str] = Counter()
    allocated_finding_ids: set[str] = set()
    findings: list[Finding] = []
    for provider_finding in provider_analysis.findings:
        semantic_payload = canonical_json(provider_finding.model_dump(mode="json"))
        payload_counts[semantic_payload] += 1
        finding_id = _finding_id(
            request,
            stage_token=stage_token,
            prompt_id=prompt_id,
            finding=provider_finding,
            occurrence=payload_counts[semantic_payload],
        )
        collision = 2
        collision_base = finding_id
        while finding_id in allocated_finding_ids:
            finding_id = f"{collision_base}-C{collision}"
            collision += 1
        allocated_finding_ids.add(finding_id)
        finding = Finding.model_validate(
            {
                "finding_id": finding_id,
                **provider_finding.model_dump(mode="python"),
            }
        )
        validate_finding(request, finding)
        findings.append(finding)

    analysis_values = provider_analysis.model_dump(mode="python")
    if isinstance(provider_analysis, ProviderRagReadinessAnalysis):
        promoted_chunks, quarantined_findings = _promote_rag_candidate_chunks(
            request, provider_analysis
        )
        analysis_values["candidate_chunks"] = promoted_chunks
        findings.extend(quarantined_findings)
    analysis_values.update(
        analysis_id=(
            f"ANA-{stage_token}-" + _token(request.document_id, request.source_digest, prompt_id)
        ),
        document_id=request.document_id,
        version_id=None,
        source_digest=request.source_digest,
        findings=findings,
        created_at=request.requested_at,
        model_route=ROUTE_FLASH,
        prompt_id=prompt_id,
    )
    analysis = domain_type.model_validate(analysis_values)
    return AnalysisReport(
        document_id=request.document_id,
        source_digest=request.source_digest,
        analyses=[analysis],
        generated_at=request.requested_at,
    )


__all__ = [
    "GeminiMacroAnalysisReport",
    "GeminiRagReadinessAnalysisReport",
    "GeminiSectionAnalysisReport",
    "GeminiSynthesisAnalysisReport",
    "ProviderFinding",
    "ProviderMacroAnalysis",
    "ProviderRagReadinessAnalysis",
    "ProviderSectionAnalysis",
    "ProviderStageReport",
    "ProviderSynthesisAnalysis",
    "promote_stage_report",
]
