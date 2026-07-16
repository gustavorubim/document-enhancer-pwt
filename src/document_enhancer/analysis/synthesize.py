"""Deterministic finding synthesis around the merged synthesis prompt."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable

from document_enhancer.domain.analysis import (
    AnalysisReport,
    Finding,
    FindingSet,
    SynthesisAnalysis,
)
from document_enhancer.domain.enums import FindingSeverity
from document_enhancer.llm.models import GeminiModelGateway
from document_enhancer.llm.profiles import ROUTE_FLASH
from document_enhancer.prompting import PromptPackComposer

from .common import canonical_json, finding_payload, validate_report_identity
from .errors import AnalysisIdentityError, AnalysisSynthesisError
from .gemini_adapter import invoke_analysis_report
from .models import (
    AnalysisBranchResult,
    AnalysisRequest,
    FindingConflict,
    RankedFinding,
    SynthesisResult,
)
from .protocols import AnalysisCallBudget
from .rendering import render_synthesis_markdown

_SEVERITY_ORDER = {
    FindingSeverity.BLOCKER: 0,
    FindingSeverity.HIGH: 1,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.LOW: 3,
    FindingSeverity.INFORMATIONAL: 4,
}
_CONFLICT_FIELDS = (
    "severity",
    "finding_type",
    "impact",
    "proposed_disposition",
    "requires_human_answer",
    "blocking",
)


def _evidence_payload(finding: Finding) -> list[dict[str, object]]:
    return sorted(
        (item.model_dump(mode="json") for item in finding.evidence),
        key=canonical_json,
    )


def _semantic_payload(finding: Finding) -> dict[str, object]:
    payload = finding_payload(finding, include_id=False)
    payload["evidence"] = _evidence_payload(finding)
    return payload


def _evidence_signature(finding: Finding) -> str:
    payload = {
        "category": finding.category,
        "target_template_section": finding.target_template_section,
        "target_object_id": finding.target_object_id,
        "requirement_id": finding.requirement_id,
        "evidence": _evidence_payload(finding),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _deduplicate(
    sourced_findings: Iterable[tuple[str, Finding]],
) -> tuple[list[Finding], dict[str, tuple[str, ...]]]:
    by_id: dict[str, str] = {}
    by_payload: dict[str, list[tuple[str, Finding]]] = defaultdict(list)
    for analysis_id, finding in sourced_findings:
        payload = canonical_json(_semantic_payload(finding))
        existing = by_id.get(finding.finding_id)
        if existing is not None and existing != payload:
            raise AnalysisSynthesisError(
                f"finding ID {finding.finding_id} identifies conflicting payloads"
            )
        by_id[finding.finding_id] = payload
        by_payload[payload].append((analysis_id, finding))

    findings: list[Finding] = []
    origins: dict[str, tuple[str, ...]] = {}
    for payload in sorted(by_payload):
        values = by_payload[payload]
        selected = min((finding for _, finding in values), key=lambda item: item.finding_id)
        findings.append(selected)
        origins[selected.finding_id] = tuple(sorted({analysis_id for analysis_id, _ in values}))
    return findings, origins


def capture_conflicts(
    findings: Iterable[Finding],
    origins: dict[str, tuple[str, ...]],
) -> tuple[FindingConflict, ...]:
    groups: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        groups[_evidence_signature(finding)].append(finding)
    conflicts: list[FindingConflict] = []
    for signature, values in sorted(groups.items()):
        if len(values) < 2:
            continue
        source_ids = tuple(
            sorted(
                {analysis_id for finding in values for analysis_id in origins[finding.finding_id]}
            )
        )
        if len(source_ids) < 2:
            continue
        differing = tuple(
            field
            for field in _CONFLICT_FIELDS
            if len({canonical_json(getattr(finding, field)) for finding in values}) > 1
        )
        if not differing:
            continue
        finding_ids = tuple(sorted(finding.finding_id for finding in values))
        token = (
            hashlib.sha256(
                canonical_json(
                    {
                        "signature": signature,
                        "findings": finding_ids,
                        "fields": differing,
                    }
                ).encode("utf-8")
            )
            .hexdigest()[:14]
            .upper()
        )
        conflicts.append(
            FindingConflict(
                conflict_id=f"CONFLICT-{token}",
                source_analysis_ids=source_ids,
                finding_ids=finding_ids,
                evidence_signature=signature,
                differing_fields=differing,
            )
        )
    return tuple(conflicts)


def rank_findings(findings: Iterable[Finding]) -> tuple[RankedFinding, ...]:
    ordered = sorted(
        findings,
        key=lambda finding: (
            0 if finding.blocking else 1,
            _SEVERITY_ORDER[finding.severity],
            0 if finding.requires_human_answer else 1,
            finding.category.casefold(),
            finding.target_template_section or "",
            finding.target_object_id or "",
            _evidence_signature(finding),
            finding.finding_id,
        ),
    )
    ranked: list[RankedFinding] = []
    for index, finding in enumerate(ordered, start=1):
        if finding.blocking or finding.severity is FindingSeverity.BLOCKER:
            priority = "blocking"
        else:
            priority = finding.severity.value
        ranked.append(RankedFinding(rank=index, priority=priority, finding=finding))
    return tuple(ranked)


def _canonicalize_model_report(
    request: AnalysisRequest,
    report: AnalysisReport,
    *,
    prompt_id: str,
) -> AnalysisReport:
    validate_report_identity(request, report)
    if not report.analyses:
        raise AnalysisIdentityError("finding synthesis must return at least one analysis result")
    analyses = []
    for analysis in report.analyses:
        if not isinstance(analysis, SynthesisAnalysis):
            raise AnalysisIdentityError("finding synthesis returned a non-synthesis analysis type")
        if analysis.prompt_id not in (None, prompt_id):
            raise AnalysisIdentityError(
                f"synthesis analysis {analysis.analysis_id} has a mismatched prompt ID"
            )
        if analysis.model_route not in (None, ROUTE_FLASH):
            raise AnalysisIdentityError(
                f"synthesis analysis {analysis.analysis_id} has a mismatched model route"
            )
        values = analysis.model_dump(mode="python")
        values["prompt_id"] = prompt_id
        values["model_route"] = ROUTE_FLASH
        analyses.append(type(analysis).model_validate(values))
    values = report.model_dump(mode="python")
    values["analyses"] = analyses
    return AnalysisReport.model_validate(values)


class FindingSynthesizer:
    """One-call fan-in that can add findings but cannot erase branch disagreement."""

    name = "finding_synthesizer"
    prompt_id = "analysis.synthesize-findings"

    def __init__(self, composer: PromptPackComposer, gateway: GeminiModelGateway) -> None:
        self.composer = composer
        self.gateway = gateway

    def synthesize(
        self,
        request: AnalysisRequest,
        branches: tuple[AnalysisBranchResult, ...],
        *,
        budget: AnalysisCallBudget | None = None,
    ) -> SynthesisResult:
        branch_sourced = [
            (branch.analysis.analysis_id, finding)
            for branch in branches
            for finding in branch.analysis.findings
        ]
        pre_findings, pre_origins = _deduplicate(branch_sourced)
        pre_conflicts = capture_conflicts(pre_findings, pre_origins)
        analysis_results = canonical_json(
            {
                "analyses": [branch.analysis.model_dump(mode="json") for branch in branches],
                "deterministic_exact_duplicates_removed": len(branch_sourced) - len(pre_findings),
                "preserved_conflicts": [item.model_dump(mode="json") for item in pre_conflicts],
            }
        )
        variables = {
            "document_type": request.document_type.value,
            "document_metadata": {
                "document_id": request.document_id,
                "source_digest": request.source_digest,
                "analysis_count": len(branches),
                **request.document_metadata,
            },
            "analysis_results": analysis_results,
            "reviewer_inputs": request.reviewer_inputs,
        }
        if budget is not None:
            budget.reserve(self.name)
        model_report, call = invoke_analysis_report(
            self.gateway,
            self.composer,
            prompt_id=self.prompt_id,
            variables=variables,
            stage=self.name,
            source_digest=request.source_digest,
        )
        model_report = _canonicalize_model_report(
            request,
            model_report,
            prompt_id=self.prompt_id,
        )
        all_sourced = [
            *branch_sourced,
            *(
                (analysis.analysis_id, finding)
                for analysis in model_report.analyses
                for finding in analysis.findings
            ),
        ]
        findings, origins = _deduplicate(all_sourced)
        conflicts = capture_conflicts(findings, origins)
        ranked = rank_findings(findings)
        generated_from: list[str] = []
        for analysis_id in [
            *(branch.analysis.analysis_id for branch in branches),
            *(analysis.analysis_id for analysis in model_report.analyses),
        ]:
            if analysis_id not in generated_from:
                generated_from.append(analysis_id)
        finding_set = FindingSet(
            document_id=request.document_id,
            source_digest=request.source_digest,
            findings=[item.finding for item in ranked],
            generated_from_analysis_ids=generated_from,
            blocking_count=sum(item.finding.blocking for item in ranked),
        )
        return SynthesisResult(
            model_report=model_report,
            finding_set=finding_set,
            ranked_findings=ranked,
            conflicts=conflicts,
            markdown=render_synthesis_markdown(ranked, conflicts),
            call=call,
        )


__all__ = ["FindingSynthesizer", "capture_conflicts", "rank_findings"]
