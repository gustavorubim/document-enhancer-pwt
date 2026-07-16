"""Fail-closed errors for the bounded analysis-specialist lane."""


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


__all__ = [
    "AnalysisBudgetError",
    "AnalysisError",
    "AnalysisIdentityError",
    "AnalysisPromptContractError",
    "AnalysisSynthesisError",
    "CandidateGraphError",
    "EvidenceResolutionError",
    "SourceSpanCoverageError",
]
