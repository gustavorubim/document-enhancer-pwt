"""RAG-readiness specialist plus deterministic lint augmentation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from document_enhancer.domain.analysis import DiscoveryAnalysis, Finding, RagReadinessAnalysis
from document_enhancer.domain.enums import FindingSeverity, FindingType, SourceBlockType
from document_enhancer.domain.ontology import Calculator, Control, Dependency
from document_enhancer.llm.models import GeminiModelGateway
from document_enhancer.llm.profiles import ROUTE_FLASH
from document_enhancer.prompting import PromptPackComposer

from .common import make_lint_finding, prompt_variables, select_analysis
from .errors import EvidenceResolutionError
from .gemini_adapter import invoke_analysis_report
from .models import (
    AnalysisBranchResult,
    AnalysisRequest,
    DeterministicLintResult,
)
from .protocols import AnalysisCallBudget
from .rendering import render_rag_readiness_markdown

_CHECK_IDS = (
    "RAG-HEADINGS",
    "RAG-STABLE-IDS",
    "RAG-SEMANTIC-OBJECT-IDS",
    "RAG-OBJECT-COMPLETENESS",
    "RAG-CODE-OBSERVABLE-DIAGRAMS",
    "RAG-CHUNKABILITY",
    "RAG-PROVENANCE",
    "RAG-TABLE-STRUCTURE",
    "RAG-UNRESOLVED-ITEMS",
    "RAG-RETRIEVAL-AMBIGUITY",
)
_VAGUE_PATTERN = re.compile(
    r"\b(it|they|this|that|these|those|timely|material|appropriate|as needed)\b",
    re.IGNORECASE,
)
_UNRESOLVED_PATTERN = re.compile(
    r"\b(TBD|TODO|TO BE DETERMINED|UNKNOWN|FIXME)\b|\[\?+\]",
    re.IGNORECASE,
)
_ACRONYM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
_STABLE_ID_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")
_MERMAID_PREFIXES = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "erDiagram",
    "journey",
    "gantt",
    "pie",
)


def _append(findings: list[Finding], finding: Finding) -> None:
    if any(existing.finding_id == finding.finding_id for existing in findings):
        raise EvidenceResolutionError(f"deterministic lint ID collision: {finding.finding_id}")
    findings.append(finding)


def _missing_control_fields(item: Control) -> tuple[str, ...]:
    fields: list[str] = []
    if not item.objective:
        fields.append("objective")
    if not item.risk_ids:
        fields.append("risk_ids")
    if not item.execution_frequency:
        fields.append("execution_frequency")
    if not (item.performer_id or item.owner_id):
        fields.append("performer_or_owner")
    if not item.procedure_or_step_id:
        fields.append("procedure_or_step_id")
    if not item.evidence_ids:
        fields.append("evidence_ids")
    if not item.failure_response:
        fields.append("failure_response")
    if not item.escalation_id:
        fields.append("escalation_id")
    return tuple(fields)


def _missing_calculator_fields(item: Calculator) -> tuple[str, ...]:
    values = {
        "calculator_type": item.calculator_type,
        "version": item.version,
        "owner_id": item.owner_id,
        "location_reference": item.location_reference,
        "input_ids": item.input_ids,
        "output_ids": item.output_ids,
        "using_step_ids": item.using_step_ids,
        "validation_status": item.validation_status,
        "criticality": item.criticality,
        "recovery_fallback": item.recovery_fallback,
    }
    return tuple(name for name, value in values.items() if not value)


def _missing_dependency_fields(item: Dependency) -> tuple[str, ...]:
    values = {
        "dependency_type": item.dependency_type,
        "required_object_id": item.required_object_id,
        "timing": item.timing,
        "provider_id": item.provider_id,
        "readiness_condition": item.readiness_condition,
        "failure_impact": item.failure_impact,
        "fallback_or_escalation": item.fallback or item.escalation_id,
    }
    return tuple(name for name, value in values.items() if not value)


def _object_completeness(item: object) -> tuple[str, ...]:
    if isinstance(item, Control):
        return _missing_control_fields(item)
    if isinstance(item, Calculator):
        return _missing_calculator_fields(item)
    if isinstance(item, Dependency):
        return _missing_dependency_fields(item)
    return ()


def _undefined_acronyms(texts: Iterable[str]) -> tuple[str, ...]:
    combined = "\n".join(texts)
    without_ids = _STABLE_ID_PATTERN.sub("", combined)
    candidates = set(_ACRONYM_PATTERN.findall(without_ids))
    undefined = {
        value
        for value in candidates
        if not re.search(rf"\b[^\n()]{{3,80}}\s\({re.escape(value)}\)", combined)
        and not re.search(rf"\b{re.escape(value)}\s*[:=]", combined)
    }
    return tuple(sorted(undefined))


def deterministic_rag_lint(
    request: AnalysisRequest,
    discovery: DiscoveryAnalysis,
    *,
    max_chunk_characters: int = 2_000,
) -> DeterministicLintResult:
    """Run stable source/semantic checks without model interpretation."""

    findings: list[Finding] = []
    blocks = request.document.raw.blocks
    first_span = request.authoritative_span_ids[0]

    sections = request.document.structural_view.sections
    if not sections:
        _append(
            findings,
            make_lint_finding(
                request,
                check_id="RAG-HEADINGS",
                category="headings",
                severity=FindingSeverity.BLOCKER,
                finding_type=FindingType.MISSING,
                span_ids=(first_span,),
                impact="The document has no validated heading hierarchy for stable retrieval paths.",
                proposed_disposition="Create reviewed section headings before chunk generation.",
                requirement_id="RAG-HEADING-HIERARCHY",
                requires_human_answer=True,
                blocking=True,
            ),
        )
    else:
        for section in sections:
            if section.section_id.startswith("PROV-"):
                _append(
                    findings,
                    make_lint_finding(
                        request,
                        check_id="RAG-STABLE-IDS",
                        category="stable_ids",
                        severity=FindingSeverity.HIGH,
                        finding_type=FindingType.MISSING,
                        span_ids=(section.start_span_id,),
                        impact="A provisional section ID cannot anchor a stable retrieval export.",
                        proposed_disposition="Review and assign a permanent section ID.",
                        target_object_id=section.section_id,
                        requires_human_answer=True,
                    ),
                )
        previous_level = sections[0].level
        for section in sections[1:]:
            if section.level > previous_level + 1:
                _append(
                    findings,
                    make_lint_finding(
                        request,
                        check_id="RAG-HEADINGS",
                        category="headings",
                        severity=FindingSeverity.MEDIUM,
                        finding_type=FindingType.NONCOMPLIANT,
                        span_ids=(section.start_span_id,),
                        impact="A skipped heading level weakens deterministic section paths.",
                        proposed_disposition="Normalize the heading hierarchy without changing content.",
                        target_object_id=section.section_id,
                        details=(str(previous_level), str(section.level)),
                    ),
                )
            previous_level = section.level

    for item in discovery.objects:
        span_id = item.provenance.source_span_id
        if span_id is None:  # Candidate validation normally catches this first.
            continue
        if item.provisional or item.id.startswith("PROV-"):
            _append(
                findings,
                make_lint_finding(
                    request,
                    check_id="RAG-SEMANTIC-OBJECT-IDS",
                    category="semantic_object_ids",
                    severity=FindingSeverity.HIGH,
                    finding_type=FindingType.MISSING,
                    span_ids=(span_id,),
                    impact="A provisional semantic object ID creates unstable retrieval references.",
                    proposed_disposition="Assign or approve a permanent ontology-conformant ID.",
                    target_object_id=item.id,
                    requires_human_answer=True,
                ),
            )
        missing = _object_completeness(item)
        if missing:
            _append(
                findings,
                make_lint_finding(
                    request,
                    check_id="RAG-OBJECT-COMPLETENESS",
                    category="semantic_object_completeness",
                    severity=FindingSeverity.HIGH,
                    finding_type=FindingType.MISSING,
                    span_ids=(span_id,),
                    impact=(
                        f"{item.entity_type.value} {item.id} is incomplete for reliable retrieval: "
                        + ", ".join(missing)
                    ),
                    proposed_disposition="Resolve each missing graph-critical field or mark it explicitly not applicable.",
                    target_object_id=item.id,
                    requires_human_answer=True,
                    details=missing,
                ),
            )
        if item.provenance.source_span_id not in request.authoritative_span_ids:
            _append(
                findings,
                make_lint_finding(
                    request,
                    check_id="RAG-PROVENANCE",
                    category="provenance",
                    severity=FindingSeverity.BLOCKER,
                    finding_type=FindingType.UNSUPPORTED,
                    span_ids=(first_span,),
                    impact=f"Semantic object {item.id} has no resolvable source provenance.",
                    proposed_disposition="Link the candidate to exact source evidence or remove it.",
                    target_object_id=item.id,
                    blocking=True,
                ),
            )

    for block in blocks:
        if block.span_id is None:  # RawDocument validation normally prevents this.
            continue
        if block.block_type is SourceBlockType.FIGURE:
            format_name = block.metadata.get("format", "").lower()
            code_observable = format_name == "mermaid" or block.text.lstrip().startswith(
                _MERMAID_PREFIXES
            )
            if not code_observable:
                _append(
                    findings,
                    make_lint_finding(
                        request,
                        check_id="RAG-CODE-OBSERVABLE-DIAGRAMS",
                        category="diagram_graphability",
                        severity=FindingSeverity.HIGH,
                        finding_type=FindingType.NONCOMPLIANT,
                        span_ids=(block.span_id,),
                        impact="The diagram cannot be inspected or reconstructed from code-observable logic.",
                        proposed_disposition="Represent authoritative diagram logic as typed objects and generated Mermaid.",
                    ),
                )
        if len(block.text) > max_chunk_characters:
            _append(
                findings,
                make_lint_finding(
                    request,
                    check_id="RAG-CHUNKABILITY",
                    category="chunkability",
                    severity=FindingSeverity.MEDIUM,
                    finding_type=FindingType.IMPROVEMENT,
                    span_ids=(block.span_id,),
                    impact="The source block exceeds the deterministic chunk-size policy.",
                    proposed_disposition="Split at a reviewed semantic boundary while retaining provenance.",
                    details=(str(len(block.text)), str(max_chunk_characters)),
                ),
            )
        if block.block_type is SourceBlockType.TABLE:
            required = {"id", "title", "headers", "source"}
            missing = tuple(sorted(required - set(block.metadata)))
            if missing:
                _append(
                    findings,
                    make_lint_finding(
                        request,
                        check_id="RAG-TABLE-STRUCTURE",
                        category="table_structure",
                        severity=FindingSeverity.MEDIUM,
                        finding_type=FindingType.MISSING,
                        span_ids=(block.span_id,),
                        impact="The table is not self-contained for retrieval: "
                        + ", ".join(missing),
                        proposed_disposition="Add stable identity, title, explicit headers, and source metadata.",
                        details=missing,
                    ),
                )
        if _UNRESOLVED_PATTERN.search(block.text):
            _append(
                findings,
                make_lint_finding(
                    request,
                    check_id="RAG-UNRESOLVED-ITEMS",
                    category="unresolved_items",
                    severity=FindingSeverity.HIGH,
                    finding_type=FindingType.MISSING,
                    span_ids=(block.span_id,),
                    impact="Unresolved placeholder content would create ambiguous retrieval evidence.",
                    proposed_disposition="Resolve, waive, or explicitly exclude the item from authoritative exports.",
                    requires_human_answer=True,
                ),
            )
        vague = tuple(
            sorted({match.group(0).lower() for match in _VAGUE_PATTERN.finditer(block.text)})
        )
        if vague:
            _append(
                findings,
                make_lint_finding(
                    request,
                    check_id="RAG-RETRIEVAL-AMBIGUITY",
                    category="retrieval_ambiguity",
                    severity=FindingSeverity.MEDIUM,
                    finding_type=FindingType.VAGUE,
                    span_ids=(block.span_id,),
                    impact="Vague references reduce standalone chunk meaning: " + ", ".join(vague),
                    proposed_disposition="Replace each vague reference with its evidence-supported canonical referent.",
                    details=vague,
                ),
            )

    undefined = _undefined_acronyms(block.text for block in blocks)
    if undefined:
        _append(
            findings,
            make_lint_finding(
                request,
                check_id="RAG-RETRIEVAL-AMBIGUITY",
                category="undefined_acronyms",
                severity=FindingSeverity.MEDIUM,
                finding_type=FindingType.AMBIGUOUS,
                span_ids=(first_span,),
                impact="Undefined acronyms create retrieval ambiguity: " + ", ".join(undefined),
                proposed_disposition="Add canonical definitions and aliases backed by source or reviewer evidence.",
                details=undefined,
            ),
        )

    return DeterministicLintResult(check_ids=_CHECK_IDS, findings=tuple(findings))


def augment_rag_readiness(
    request: AnalysisRequest,
    analysis: RagReadinessAnalysis,
    discovery: DiscoveryAnalysis,
) -> tuple[RagReadinessAnalysis, DeterministicLintResult]:
    lint = deterministic_rag_lint(request, discovery)
    findings = list(analysis.findings)
    known_ids = {item.finding_id for item in findings}
    for finding in lint.findings:
        if finding.finding_id in known_ids:
            raise EvidenceResolutionError(f"LLM/lint finding ID collision: {finding.finding_id}")
        findings.append(finding)
        known_ids.add(finding.finding_id)
    texts = [block.text for block in request.document.raw.blocks]
    undefined = tuple(sorted(set(analysis.undefined_acronyms) | set(_undefined_acronyms(texts))))
    vague = tuple(
        sorted(
            set(analysis.vague_references)
            | {
                f"{block.span_id}:{match.group(0).lower()}"
                for block in request.document.raw.blocks
                for match in _VAGUE_PATTERN.finditer(block.text)
            }
        )
    )
    missing_ids = tuple(
        sorted(
            set(analysis.missing_ids)
            | {
                finding.target_object_id
                for finding in lint.findings
                if finding.category in {"stable_ids", "semantic_object_ids"}
                and finding.target_object_id is not None
            }
        )
    )
    values = analysis.model_dump(mode="python")
    values.update(
        findings=findings,
        undefined_acronyms=list(undefined),
        vague_references=list(vague),
        missing_ids=list(missing_ids),
        candidate_objects=sorted(
            set(analysis.candidate_objects) | {item.id for item in discovery.objects}
        ),
    )
    augmented = RagReadinessAnalysis.model_validate(values)
    return augmented, lint


class RagReadinessReviewer:
    """One-call retrieval reviewer; deterministic augmentation occurs at fan-in."""

    name: Literal["rag_readiness_reviewer"] = "rag_readiness_reviewer"
    prompt_id = "analysis.rag-readiness"

    def __init__(self, composer: PromptPackComposer, gateway: GeminiModelGateway) -> None:
        self.composer = composer
        self.gateway = gateway

    def review(
        self,
        request: AnalysisRequest,
        *,
        budget: AnalysisCallBudget | None = None,
    ) -> AnalysisBranchResult:
        if budget is not None:
            budget.reserve(self.name)
        report, call = invoke_analysis_report(
            self.gateway,
            self.composer,
            prompt_id=self.prompt_id,
            variables=prompt_variables(request),
            stage=self.name,
            request=request,
        )
        analysis = select_analysis(
            request,
            report,
            RagReadinessAnalysis,
            prompt_id=self.prompt_id,
            model_route=ROUTE_FLASH,
        )
        return AnalysisBranchResult(
            specialist=self.name,
            analysis=analysis,
            markdown=render_rag_readiness_markdown(analysis),
            call=call,
        )


__all__ = [
    "RagReadinessReviewer",
    "augment_rag_readiness",
    "deterministic_rag_lint",
]
