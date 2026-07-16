"""Candidate process and methodology semantic discovery."""

from __future__ import annotations

from typing import Literal

from document_enhancer.domain.analysis import DiscoveryAnalysis
from document_enhancer.domain.enums import Layer, ReviewStatus
from document_enhancer.domain.ids import ensure_unique_ids
from document_enhancer.domain.ontology import EntityRegistry
from document_enhancer.llm.models import GeminiModelGateway
from document_enhancer.prompting import PromptPackComposer

from .common import prompt_variables
from .errors import CandidateGraphError
from .gemini_adapter import invoke_discovery_candidate_batch
from .models import AnalysisBranchResult, AnalysisRequest
from .promotion import promote_discovery_candidate_batch
from .protocols import AnalysisCallBudget
from .rendering import render_discovery_markdown


def validate_candidate_graph(request: AnalysisRequest, analysis: DiscoveryAnalysis) -> None:
    """Keep discovery reviewable, provenance-complete, typed, and non-authoritative."""

    if analysis.mermaid:
        raise CandidateGraphError(
            "discovery output must not use model-authored Mermaid as semantic evidence"
        )
    try:
        ensure_unique_ids(item.id for item in analysis.objects)
        ensure_unique_ids(
            item.id for item in analysis.candidate_relationships if item.id is not None
        )
    except ValueError as exc:
        raise CandidateGraphError(str(exc)) from exc
    known_spans = set(request.authoritative_span_ids)
    for item in analysis.objects:
        if item.layer is not Layer.EXTRACTED:
            raise CandidateGraphError(
                f"candidate object {item.id} must remain in the extracted graph layer"
            )
        if item.review_status not in {ReviewStatus.UNREVIEWED, ReviewStatus.IN_REVIEW}:
            raise CandidateGraphError(
                f"candidate object {item.id} cannot be accepted before human review"
            )
        if item.provenance.document_id != request.document_id:
            raise CandidateGraphError(f"candidate object {item.id} has foreign provenance")
        if item.provenance.source_span_id not in known_spans:
            raise CandidateGraphError(
                f"candidate object {item.id} lacks resolvable source-span provenance"
            )
    registry = EntityRegistry(analysis.objects)
    for relationship in analysis.candidate_relationships:
        if relationship.layer is not Layer.EXTRACTED:
            raise CandidateGraphError(
                f"candidate relationship {relationship.id} must remain extracted"
            )
        if relationship.review_status not in {ReviewStatus.UNREVIEWED, ReviewStatus.IN_REVIEW}:
            raise CandidateGraphError(
                f"candidate relationship {relationship.id} cannot be pre-approved"
            )
        if relationship.provenance.document_id != request.document_id:
            raise CandidateGraphError(
                f"candidate relationship {relationship.id} has foreign provenance"
            )
        if relationship.provenance.source_span_id not in known_spans:
            raise CandidateGraphError(
                f"candidate relationship {relationship.id} lacks source-span provenance"
            )
        try:
            registry.validate_relationship(relationship)
        except ValueError as exc:
            raise CandidateGraphError(str(exc)) from exc


class ProcessMethodologyDiscoverer:
    """One-call typed candidate discovery specialist."""

    name: Literal["process_methodology_discoverer"] = "process_methodology_discoverer"
    prompt_id = "analysis.process-methodology-discovery"

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
        candidates, call = invoke_discovery_candidate_batch(
            self.gateway,
            self.composer,
            variables=prompt_variables(request),
            stage=self.name,
            source_digest=request.source_digest,
        )
        analysis = promote_discovery_candidate_batch(request, candidates)
        validate_candidate_graph(request, analysis)
        return AnalysisBranchResult(
            specialist=self.name,
            analysis=analysis,
            markdown=render_discovery_markdown(analysis),
            call=call,
        )


__all__ = ["ProcessMethodologyDiscoverer", "validate_candidate_graph"]
