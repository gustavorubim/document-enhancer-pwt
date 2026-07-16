"""Evidence-backed macro reviewer."""

from __future__ import annotations

from typing import Literal

from document_enhancer.domain.analysis import MacroAnalysis
from document_enhancer.llm.models import GeminiModelGateway
from document_enhancer.llm.profiles import ROUTE_FLASH
from document_enhancer.prompting import PromptPackComposer

from .common import prompt_variables, select_analysis, validate_evidence
from .errors import EvidenceResolutionError
from .gemini_adapter import invoke_analysis_report
from .models import AnalysisBranchResult, AnalysisRequest
from .protocols import AnalysisCallBudget
from .rendering import render_macro_markdown


class MacroReviewer:
    """One-call macro specialist using only the merged prompt-pack instructions."""

    name: Literal["macro_reviewer"] = "macro_reviewer"
    prompt_id = "analysis.macro"

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
            MacroAnalysis,
            prompt_id=self.prompt_id,
            model_route=ROUTE_FLASH,
        )
        if analysis.candidate_document_type is not None and analysis.candidate_confidence is None:
            raise EvidenceResolutionError(
                "macro candidate_document_type requires an explicit confidence"
            )
        dimensions: set[str] = set()
        for score in analysis.rubric_scores:
            if score.dimension in dimensions:
                raise EvidenceResolutionError(
                    f"macro rubric dimension is duplicated: {score.dimension}"
                )
            dimensions.add(score.dimension)
            if not score.evidence:
                raise EvidenceResolutionError(
                    f"macro rubric score {score.dimension!r} has no source evidence"
                )
            for evidence in score.evidence:
                validate_evidence(request, evidence)
        return AnalysisBranchResult(
            specialist=self.name,
            analysis=analysis,
            markdown=render_macro_markdown(analysis),
            call=call,
        )


__all__ = ["MacroReviewer"]
