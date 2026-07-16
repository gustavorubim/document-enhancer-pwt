"""Bounded fan-out/fan-in orchestration for the four analysis specialists."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Protocol, cast

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
from .errors import AnalysisBudgetError, AnalysisIdentityError, AnalysisIncompleteError
from .macro import MacroReviewer
from .models import (
    AnalysisBranchResult,
    AnalysisRequest,
    AnalysisRunResult,
    AnalysisStageName,
    AnalysisStageRecord,
    SourceDispositionMap,
)
from .rag_readiness import RagReadinessReviewer, augment_rag_readiness
from .rendering import render_rag_readiness_markdown
from .sections import SectionMapper
from .synthesize import FindingSynthesizer

_REQUIRED_CALLS = 5
_BRANCH_ORDER: tuple[AnalysisStageName, ...] = (
    "macro_reviewer",
    "section_mapper",
    "process_methodology_discoverer",
    "rag_readiness_reviewer",
)


class AnalysisProgressRecorder(Protocol):
    """Narrow durable boundary used before analysis fan-in."""

    def completed_records(
        self, request: AnalysisRequest
    ) -> Mapping[AnalysisStageName, AnalysisStageRecord]: ...

    def record(self, outcome: AnalysisStageRecord) -> None: ...

    def clear(self, stage: AnalysisStageName) -> None: ...


def _safe_failure_record(
    request: AnalysisRequest,
    stage: AnalysisStageName,
    exc: BaseException,
) -> AnalysisStageRecord:
    error_type = type(exc).__name__
    if not error_type.isidentifier() or len(error_type) > 80:
        error_type = "AnalysisStageError"
    return AnalysisStageRecord(
        document_id=request.document_id,
        source_digest=request.source_digest,
        stage=stage,
        status="failed",
        error_type=error_type,
        error_message="Required analysis stage did not produce a validated artifact.",
        retry_action=f"Retry the {stage} analysis stage with the same validated inputs.",
    )


def _quarantine_record(
    request: AnalysisRequest,
    branch: AnalysisBranchResult,
) -> AnalysisStageRecord:
    return AnalysisStageRecord(
        document_id=request.document_id,
        source_digest=request.source_digest,
        stage=branch.specialist,
        status="quarantined",
        branch=branch,
        error_type="CandidateQuarantine",
        error_message="The branch contains non-promoted candidates that require resolution.",
        retry_action=(
            f"Review the {branch.specialist} quarantine findings and retry that analysis stage."
        ),
    )


def _has_blocking_quarantine(branch: AnalysisBranchResult) -> bool:
    return any(
        finding.category == "candidate_quarantine" and finding.blocking
        for finding in branch.analysis.findings
    )


def _validate_branch_identity(
    stage: AnalysisStageName,
    branch: object,
) -> AnalysisBranchResult:
    if not isinstance(branch, AnalysisBranchResult) or branch.specialist != stage:
        raise AnalysisIdentityError(f"{stage} returned the wrong specialist identity")
    expected_type = {
        "macro_reviewer": MacroAnalysis,
        "section_mapper": SectionAnalysis,
        "process_methodology_discoverer": DiscoveryAnalysis,
        "rag_readiness_reviewer": RagReadinessAnalysis,
    }[stage]
    if not isinstance(branch.analysis, expected_type):
        raise AnalysisIdentityError(f"{stage} returned the wrong analysis type")
    return branch


def _resolve_branch_value(
    stage: AnalysisStageName,
    value: object,
) -> tuple[AnalysisBranchResult, object | None]:
    disposition_map: object | None = None
    branch: object = value
    if stage == "section_mapper":
        branch, disposition_map = cast(tuple[AnalysisBranchResult, object], value)
    return _validate_branch_identity(stage, branch), disposition_map


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

    def run(
        self,
        request: AnalysisRequest,
        *,
        recorder: AnalysisProgressRecorder | None = None,
    ) -> AnalysisRunResult:
        budget = BoundedCallBudget(self.max_calls)
        completed = dict(recorder.completed_records(request)) if recorder is not None else {}
        unknown = set(completed) - set(_BRANCH_ORDER)
        if unknown:
            raise AnalysisIdentityError("persisted analysis contains an unknown specialist")
        branches_by_stage: dict[AnalysisStageName, AnalysisBranchResult] = {}
        disposition_map: SourceDispositionMap | None = None
        records_by_stage: dict[AnalysisStageName, AnalysisStageRecord] = {}
        for stage, outcome in completed.items():
            if outcome.status != "succeeded" or outcome.branch is None:
                raise AnalysisIdentityError("recorder returned an unresolved branch as completed")
            if (
                outcome.document_id != request.document_id
                or outcome.source_digest != request.source_digest
                or outcome.stage != stage
            ):
                raise AnalysisIdentityError("persisted analysis branch has foreign input identity")
            validated = _validate_branch_identity(stage, outcome.branch)
            if outcome.disposition_map is not None:
                if (
                    outcome.disposition_map.document_id != request.document_id
                    or outcome.disposition_map.source_digest != request.source_digest
                ):
                    raise AnalysisIdentityError(
                        "persisted section disposition map has foreign input identity"
                    )
                disposition_map = outcome.disposition_map
            branches_by_stage[stage] = validated
            records_by_stage[stage] = outcome

        with ThreadPoolExecutor(
            max_workers=self.max_parallelism,
            thread_name_prefix="document-analysis",
        ) as executor:
            futures: dict[Future[object], AnalysisStageName] = {}
            if "macro_reviewer" not in completed:
                futures[executor.submit(self.macro.review, request, budget=budget)] = (
                    "macro_reviewer"
                )
            if "section_mapper" not in completed:
                futures[executor.submit(self.sections.review, request, budget=budget)] = (
                    "section_mapper"
                )
            if "process_methodology_discoverer" not in completed:
                futures[executor.submit(self.discovery.review, request, budget=budget)] = (
                    "process_methodology_discoverer"
                )
            if "rag_readiness_reviewer" not in completed:
                futures[executor.submit(self.rag.review, request, budget=budget)] = (
                    "rag_readiness_reviewer"
                )

            for future in as_completed(futures):
                stage = futures[future]
                try:
                    branch, candidate_disposition = _resolve_branch_value(stage, future.result())
                    if candidate_disposition is not None:
                        disposition_map = cast(SourceDispositionMap, candidate_disposition)
                    if _has_blocking_quarantine(branch):
                        outcome = _quarantine_record(request, branch)
                    else:
                        outcome = AnalysisStageRecord(
                            document_id=request.document_id,
                            source_digest=request.source_digest,
                            stage=stage,
                            status="succeeded",
                            branch=branch,
                            disposition_map=cast(
                                SourceDispositionMap | None, candidate_disposition
                            ),
                        )
                        branches_by_stage[stage] = branch
                except Exception as exc:  # every sibling still resolves before fail-closed fan-in
                    outcome = _safe_failure_record(request, stage, exc)
                records_by_stage[stage] = outcome
                if recorder is not None:
                    recorder.record(outcome)

        unresolved = tuple(
            records_by_stage[stage]
            for stage in _BRANCH_ORDER
            if records_by_stage[stage].status != "succeeded"
        )
        if unresolved:
            raise AnalysisIncompleteError(tuple(records_by_stage[stage] for stage in _BRANCH_ORDER))

        macro_branch = branches_by_stage["macro_reviewer"]
        section_branch = branches_by_stage["section_mapper"]
        discovery_branch = branches_by_stage["process_methodology_discoverer"]
        rag_branch = branches_by_stage["rag_readiness_reviewer"]
        if disposition_map is None:
            raise AnalysisIdentityError("section branch is missing its persisted disposition map")

        augmented_rag, lint = augment_rag_readiness(
            request,
            cast(RagReadinessAnalysis, rag_branch.analysis),
            cast(DiscoveryAnalysis, discovery_branch.analysis),
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
        try:
            synthesis = self.synthesizer.synthesize(request, branches, budget=budget)
        except Exception as exc:
            synthesis_failure = _safe_failure_record(request, "finding_synthesizer", exc)
            if recorder is not None:
                recorder.record(synthesis_failure)
            raise AnalysisIncompleteError(
                tuple(records_by_stage[stage] for stage in _BRANCH_ORDER) + (synthesis_failure,)
            ) from exc
        if recorder is not None:
            recorder.clear("finding_synthesizer")
        return AnalysisRunResult(
            report=report,
            branches=branches,
            disposition_map=disposition_map,
            rag_lint=lint,
            synthesis=synthesis,
            call_count=_REQUIRED_CALLS,
        )


__all__ = ["AnalysisOrchestrator", "AnalysisProgressRecorder", "BoundedCallBudget"]
