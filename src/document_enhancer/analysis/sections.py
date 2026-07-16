"""Fail-closed source-to-target section mapping."""

from __future__ import annotations

from typing import Literal

from document_enhancer.domain.analysis import SectionAnalysis
from document_enhancer.llm.models import GeminiModelGateway
from document_enhancer.llm.profiles import ROUTE_FLASH
from document_enhancer.prompting import PromptPackComposer

from .common import prompt_variables, select_analysis
from .errors import SourceSpanCoverageError
from .gemini_adapter import invoke_analysis_report
from .models import (
    AnalysisBranchResult,
    AnalysisRequest,
    SourceDispositionMap,
    SourceSpanDisposition,
    SpanDisposition,
)
from .protocols import AnalysisCallBudget
from .rendering import render_section_markdown

_DISPOSITIONS = {
    "preserve": SpanDisposition.PRESERVED,
    "preserved": SpanDisposition.PRESERVED,
    "retain": SpanDisposition.PRESERVED,
    "retained": SpanDisposition.PRESERVED,
    "move": SpanDisposition.MOVED,
    "moved": SpanDisposition.MOVED,
    "merge": SpanDisposition.MERGED,
    "merged": SpanDisposition.MERGED,
    "split": SpanDisposition.SPLIT,
    "omit": SpanDisposition.OMITTED,
    "omitted": SpanDisposition.OMITTED,
    "uncertain": SpanDisposition.UNCERTAIN,
    "blocking": SpanDisposition.BLOCKING,
    "blocked": SpanDisposition.BLOCKING,
}
_SINGLE_TARGET = {
    SpanDisposition.PRESERVED,
    SpanDisposition.MOVED,
    SpanDisposition.MERGED,
}


def _disposition(value: str) -> SpanDisposition:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return _DISPOSITIONS[normalized]
    except KeyError as exc:
        raise SourceSpanCoverageError(f"unknown source-span disposition: {value!r}") from exc


def build_disposition_map(
    request: AnalysisRequest,
    analysis: SectionAnalysis,
) -> SourceDispositionMap:
    """Require one explicit disposition for every raw block in exact source order."""

    expected = list(request.authoritative_span_ids)
    known = set(expected)
    actual: list[str] = []
    dispositions: list[SourceSpanDisposition] = []
    seen: set[str] = set()
    for mapping in analysis.mappings:
        if not mapping.source_span_ids:
            raise SourceSpanCoverageError("section mapping contains an empty source-span group")
        if not mapping.rationale or not mapping.rationale.strip():
            raise SourceSpanCoverageError("every source-span disposition requires a rationale")
        disposition = _disposition(mapping.disposition)
        if disposition is SpanDisposition.MERGED and len(mapping.source_span_ids) < 2:
            raise SourceSpanCoverageError("a merged disposition requires at least two source spans")
        if disposition is SpanDisposition.SPLIT and len(mapping.source_span_ids) != 1:
            raise SourceSpanCoverageError(
                "a split disposition must identify exactly one source span"
            )
        targets = tuple(mapping.target_section_ids)
        if disposition in _SINGLE_TARGET and len(targets) != 1:
            raise SourceSpanCoverageError(
                f"{disposition.value} disposition requires exactly one target section"
            )
        if disposition is SpanDisposition.SPLIT and len(targets) < 2:
            raise SourceSpanCoverageError(
                "a split disposition requires at least two target sections"
            )
        if disposition is SpanDisposition.OMITTED and targets:
            raise SourceSpanCoverageError("an omitted disposition must not name target sections")
        for span_id in mapping.source_span_ids:
            if span_id not in known:
                raise SourceSpanCoverageError(f"section mapping references unknown span {span_id}")
            if span_id in seen:
                raise SourceSpanCoverageError(f"section mapping duplicates source span {span_id}")
            seen.add(span_id)
            actual.append(span_id)
            dispositions.append(
                SourceSpanDisposition(
                    span_id=span_id,
                    target_section_ids=targets,
                    disposition=disposition,
                    rationale=mapping.rationale,
                )
            )
    if actual != expected:
        missing = [span_id for span_id in expected if span_id not in seen]
        if missing:
            raise SourceSpanCoverageError(
                "section mapping omitted source span(s): " + ", ".join(missing)
            )
        raise SourceSpanCoverageError("section mapping does not preserve exact raw-block order")
    return SourceDispositionMap(
        document_id=request.document_id,
        source_digest=request.source_digest,
        authoritative_span_ids=tuple(expected),
        dispositions=tuple(dispositions),
    )


class SectionMapper:
    """One-call mapper with deterministic full-span disposition validation."""

    name: Literal["section_mapper"] = "section_mapper"
    prompt_id = "analysis.sections"

    def __init__(self, composer: PromptPackComposer, gateway: GeminiModelGateway) -> None:
        self.composer = composer
        self.gateway = gateway

    def review(
        self,
        request: AnalysisRequest,
        *,
        budget: AnalysisCallBudget | None = None,
    ) -> tuple[AnalysisBranchResult, SourceDispositionMap]:
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
            SectionAnalysis,
            prompt_id=self.prompt_id,
            model_route=ROUTE_FLASH,
        )
        disposition_map = build_disposition_map(request, analysis)
        return (
            AnalysisBranchResult(
                specialist=self.name,
                analysis=analysis,
                markdown=render_section_markdown(analysis, disposition_map),
                call=call,
            ),
            disposition_map,
        )


__all__ = ["SectionMapper", "build_disposition_map"]
