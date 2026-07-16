"""Bounded fan-out/fan-in orchestration for the four analysis specialists."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from document_enhancer.domain.analysis import (
    AnalysisReport,
    DiscoveryAnalysis,
    MacroAnalysis,
    RagReadinessAnalysis,
    SectionAnalysis,
)
from document_enhancer.llm.models import GeminiModelGateway
from document_enhancer.prompting import PromptPackComposer

from .discovery import ProcessMethodologyDiscoverer
from .errors import AnalysisBudgetError, AnalysisIdentityError
from .macro import MacroReviewer
from .models import AnalysisBranchResult, AnalysisRequest, AnalysisRunResult
from .rag_readiness import RagReadinessReviewer, augment_rag_readiness
from .rendering import render_rag_readiness_markdown
from .sections import SectionMapper
from .synthesize import FindingSynthesizer

_REQUIRED_CALLS = 5


class BoundedCallBudget:
    """Thread-safe one-run call counter; a reservation is consumed even on failure."""

    def __init__(self, max_calls: int) -> None:
        if max_calls < 1:
            raise AnalysisBudgetError("analysis call budget must be positive")
        self.max_calls = max_calls
        self._used = 0
        self._lock = Lock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    def reserve(self, stage: str) -> None:
        with self._lock:
            if self._used >= self.max_calls:
                raise AnalysisBudgetError(
                    f"analysis call budget exhausted before {stage}; limit={self.max_calls}"
                )
            self._used += 1


class AnalysisOrchestrator:
    """Run four independent calls, deterministic augmentation, and one synthesis call."""

    def __init__(
        self,
        composer: PromptPackComposer,
        gateway: GeminiModelGateway,
        *,
        max_calls: int = _REQUIRED_CALLS,
        max_parallelism: int = 4,
    ) -> None:
        if max_calls < _REQUIRED_CALLS:
            raise AnalysisBudgetError(
                f"complete analysis requires {_REQUIRED_CALLS} bounded calls, got {max_calls}"
            )
        if not 1 <= max_parallelism <= 4:
            raise ValueError("analysis max_parallelism must be between one and four")
        self.composer = composer
        self.gateway = gateway
        self.max_calls = max_calls
        self.max_parallelism = max_parallelism
        self.macro = MacroReviewer(composer, gateway)
        self.sections = SectionMapper(composer, gateway)
        self.discovery = ProcessMethodologyDiscoverer(composer, gateway)
        self.rag = RagReadinessReviewer(composer, gateway)
        self.synthesizer = FindingSynthesizer(composer, gateway)

    def run(self, request: AnalysisRequest) -> AnalysisRunResult:
        budget = BoundedCallBudget(self.max_calls)
        with ThreadPoolExecutor(
            max_workers=self.max_parallelism,
            thread_name_prefix="document-analysis",
        ) as executor:
            macro_future = executor.submit(self.macro.review, request, budget=budget)
            sections_future = executor.submit(self.sections.review, request, budget=budget)
            discovery_future = executor.submit(self.discovery.review, request, budget=budget)
            rag_future = executor.submit(self.rag.review, request, budget=budget)

            # Resolve in contract order, independent of provider completion order.
            macro_branch = macro_future.result()
            section_branch, disposition_map = sections_future.result()
            discovery_branch = discovery_future.result()
            rag_branch = rag_future.result()

        if not isinstance(macro_branch.analysis, MacroAnalysis):
            raise AnalysisIdentityError("macro specialist returned the wrong analysis type")
        if not isinstance(section_branch.analysis, SectionAnalysis):
            raise AnalysisIdentityError("section specialist returned the wrong analysis type")
        if not isinstance(discovery_branch.analysis, DiscoveryAnalysis):
            raise AnalysisIdentityError("discovery specialist returned the wrong analysis type")
        if not isinstance(rag_branch.analysis, RagReadinessAnalysis):
            raise AnalysisIdentityError("RAG specialist returned the wrong analysis type")

        augmented_rag, lint = augment_rag_readiness(
            request,
            rag_branch.analysis,
            discovery_branch.analysis,
        )
        rag_branch = AnalysisBranchResult(
            specialist=rag_branch.specialist,
            analysis=augmented_rag,
            markdown=render_rag_readiness_markdown(augmented_rag),
            call=rag_branch.call,
        )
        branches = (
            macro_branch,
            section_branch,
            discovery_branch,
            rag_branch,
        )
        report = AnalysisReport(
            document_id=request.document_id,
            source_digest=request.source_digest,
            analyses=[branch.analysis for branch in branches],
        )
        synthesis = self.synthesizer.synthesize(request, branches, budget=budget)
        return AnalysisRunResult(
            report=report,
            branches=branches,
            disposition_map=disposition_map,
            rag_lint=lint,
            synthesis=synthesis,
            call_count=budget.used,
        )


__all__ = ["AnalysisOrchestrator", "BoundedCallBudget"]
