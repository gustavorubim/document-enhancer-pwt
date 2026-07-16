"""Shared deterministic validation and serialization for analysis specialists."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from document_enhancer.domain.analysis import (
    AnalysisBase,
    AnalysisReport,
    EvidenceQuote,
    Finding,
)
from document_enhancer.domain.enums import FindingSeverity, FindingType

from .errors import AnalysisIdentityError, EvidenceResolutionError
from .models import AnalysisRequest


def canonical_json(value: Any) -> str:
    """Serialize one model/data value for stable prompts, hashes, and comparisons."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def source_payload(request: AnalysisRequest) -> str:
    """Render source material as inert, ordered data with stable span identifiers."""

    payload = {
        "document_id": request.document_id,
        "source_digest": request.source_digest,
        "media_type": request.document.raw.media_type,
        "structure": {
            "origin": request.document.structural_view.origin,
            "confidence": request.document.structural_view.confidence,
            "sections": [
                section.model_dump(mode="json")
                for section in request.document.structural_view.sections
            ],
        },
        "ordered_blocks": [
            {
                "span_id": block.span_id,
                "ordinal": block.ordinal,
                "block_type": block.block_type.value,
                "substantive": block.substantive,
                "heading_level": block.heading_level,
                "text": block.text,
                "text_digest": block.text_digest,
                "location": (
                    block.location.model_dump(mode="json") if block.location is not None else None
                ),
                "metadata": dict(sorted(block.metadata.items())),
            }
            for block in request.document.raw.blocks
        ],
    }
    return canonical_json(payload)


def prompt_variables(request: AnalysisRequest) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "document_id": request.document_id,
        "source_digest": request.source_digest,
        "media_type": request.document.raw.media_type,
        "structure_origin": request.document.structural_view.origin,
        "span_count": len(request.document.raw.blocks),
        **request.document_metadata,
    }
    return {
        "document_type": request.document_type.value,
        "document_metadata": metadata,
        "source_text": source_payload(request),
        "reviewer_inputs": request.reviewer_inputs,
    }


def _block_by_span(request: AnalysisRequest) -> dict[str, Any]:
    return {
        block.span_id: block for block in request.document.raw.blocks if block.span_id is not None
    }


def validate_evidence(request: AnalysisRequest, evidence: EvidenceQuote) -> None:
    """Require every quoted snippet to resolve exactly inside its identified source span."""

    block = _block_by_span(request).get(evidence.span_id)
    if block is None:
        raise EvidenceResolutionError(f"evidence references unknown span {evidence.span_id}")
    if (evidence.start_offset is None) != (evidence.end_offset is None):
        raise EvidenceResolutionError(
            f"evidence {evidence.span_id} must provide both offsets or neither"
        )
    if evidence.start_offset is not None and evidence.end_offset is not None:
        if evidence.end_offset > len(block.text):
            raise EvidenceResolutionError(f"evidence offsets exceed source span {evidence.span_id}")
        if block.text[evidence.start_offset : evidence.end_offset] != evidence.quote:
            raise EvidenceResolutionError(
                f"evidence quote does not match offsets in {evidence.span_id}"
            )
    elif evidence.quote not in block.text:
        raise EvidenceResolutionError(
            f"evidence quote does not occur in source span {evidence.span_id}"
        )


def validate_finding(request: AnalysisRequest, finding: Finding) -> None:
    """Enforce source evidence or a named governed requirement for every finding."""

    if not finding.evidence and not finding.requirement_id:
        raise EvidenceResolutionError(
            f"finding {finding.finding_id} has neither source evidence nor a requirement ID"
        )
    for evidence in finding.evidence:
        validate_evidence(request, evidence)


def validate_report_identity(request: AnalysisRequest, report: AnalysisReport) -> None:
    if report.document_id != request.document_id:
        raise AnalysisIdentityError(
            f"analysis report document {report.document_id} does not match {request.document_id}"
        )
    if report.source_digest != request.source_digest:
        raise AnalysisIdentityError("analysis report source digest does not match the request")
    for analysis in report.analyses:
        if analysis.document_id != request.document_id:
            raise AnalysisIdentityError(
                f"analysis {analysis.analysis_id} identifies a different document"
            )
        if analysis.source_digest != request.source_digest:
            raise AnalysisIdentityError(
                f"analysis {analysis.analysis_id} identifies a different source digest"
            )
        for finding in analysis.findings:
            validate_finding(request, finding)


def select_analysis[AnalysisT: AnalysisBase](
    request: AnalysisRequest,
    report: AnalysisReport,
    expected_type: type[AnalysisT],
    *,
    prompt_id: str,
    model_route: str,
) -> AnalysisT:
    """Select exactly one expected branch and canonicalize auditable call metadata."""

    validate_report_identity(request, report)
    if len(report.analyses) != 1 or not isinstance(report.analyses[0], expected_type):
        raise AnalysisIdentityError(f"{prompt_id} must return exactly one {expected_type.__name__}")
    analysis = report.analyses[0]
    if analysis.prompt_id not in (None, prompt_id):
        raise AnalysisIdentityError(
            f"analysis response prompt {analysis.prompt_id} does not match {prompt_id}"
        )
    if analysis.model_route not in (None, model_route):
        raise AnalysisIdentityError(
            f"analysis response route {analysis.model_route} does not match {model_route}"
        )
    values = analysis.model_dump(mode="python")
    values["prompt_id"] = prompt_id
    values["model_route"] = model_route
    return expected_type.model_validate(values)


def deterministic_finding_id(
    check_id: str,
    *,
    span_ids: Iterable[str] = (),
    target_object_id: str | None = None,
    details: Iterable[str] = (),
) -> str:
    payload = "\0".join([check_id, *span_ids, target_object_id or "", *sorted(details)]).encode(
        "utf-8"
    )
    token = hashlib.sha256(payload).hexdigest()[:14].upper()
    slug = "-".join(part for part in check_id.upper().replace("_", "-").split("-") if part)
    return f"FND-{slug}-{token}"


def evidence_for_span(request: AnalysisRequest, span_id: str, *, limit: int = 240) -> EvidenceQuote:
    block = _block_by_span(request).get(span_id)
    if block is None:
        raise EvidenceResolutionError(f"cannot create evidence for unknown span {span_id}")
    quote = block.text[:limit]
    return EvidenceQuote(
        span_id=span_id,
        quote=quote,
        start_offset=0,
        end_offset=len(quote),
    )


def make_lint_finding(
    request: AnalysisRequest,
    *,
    check_id: str,
    category: str,
    severity: FindingSeverity,
    finding_type: FindingType,
    span_ids: tuple[str, ...],
    impact: str,
    proposed_disposition: str,
    target_template_section: str | None = None,
    target_object_id: str | None = None,
    requirement_id: str | None = None,
    requires_human_answer: bool = False,
    blocking: bool = False,
    details: tuple[str, ...] = (),
) -> Finding:
    evidence = [evidence_for_span(request, span_id) for span_id in span_ids]
    return Finding(
        finding_id=deterministic_finding_id(
            check_id,
            span_ids=span_ids,
            target_object_id=target_object_id,
            details=details,
        ),
        category=category,
        severity=severity,
        finding_type=finding_type,
        evidence=evidence,
        target_template_section=target_template_section,
        target_object_id=target_object_id,
        requirement_id=requirement_id,
        impact=impact,
        proposed_disposition=proposed_disposition,
        requires_human_answer=requires_human_answer,
        blocking=blocking,
    )


def finding_payload(finding: Finding, *, include_id: bool = True) -> dict[str, Any]:
    value = finding.model_dump(mode="json")
    if not include_id:
        value.pop("finding_id", None)
    return value


__all__ = [
    "canonical_json",
    "deterministic_finding_id",
    "evidence_for_span",
    "finding_payload",
    "make_lint_finding",
    "prompt_variables",
    "select_analysis",
    "source_payload",
    "validate_evidence",
    "validate_finding",
    "validate_report_identity",
]
