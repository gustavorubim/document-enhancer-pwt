"""Fail-closed errors for the bounded analysis-specialist lane."""

from __future__ import annotations

from document_enhancer.errors import ProviderError

from .models import AnalysisStageRecord


class AnalysisError(RuntimeError):
    """Base class for analysis failures that must stop downstream promotion."""


class AnalysisPromptContractError(AnalysisError):
    """A resolved prompt, model route, or output schema did not match the lane contract."""


class AnalysisIdentityError(AnalysisError):
    """A structured response did not identify the requested source document."""


class EvidenceResolutionError(AnalysisError):
    """A finding or candidate object could not be tied to exact source evidence."""


class SourceSpanCoverageError(AnalysisError):
    """The section disposition map omitted, duplicated, or reordered source content."""


class CandidateGraphError(AnalysisError):
    """Candidate semantic objects or relationships violated the bounded ontology contract."""


class AnalysisBudgetError(AnalysisError):
    """The configured specialist-call budget cannot complete the bounded lane."""


class AnalysisSynthesisError(AnalysisError):
    """Fan-in could not preserve and canonically synthesize the specialist findings."""


class AnalysisIncompleteError(ProviderError):
    """One or more required stages are unresolved, so fan-in cannot be authoritative."""

    def __init__(self, records: tuple[AnalysisStageRecord, ...]) -> None:
        unresolved = tuple(record for record in records if record.status != "succeeded")
        if not unresolved:
            raise ValueError("analysis incomplete error requires an unresolved stage")
        self.records = records
        self.unresolved_stages = tuple(record.stage for record in unresolved)
        super().__init__("required analysis stage unresolved: " + ", ".join(self.unresolved_stages))


__all__ = [
    "AnalysisBudgetError",
    "AnalysisError",
    "AnalysisIdentityError",
    "AnalysisIncompleteError",
    "AnalysisPromptContractError",
    "AnalysisSynthesisError",
    "CandidateGraphError",
    "EvidenceResolutionError",
    "SourceSpanCoverageError",
]
