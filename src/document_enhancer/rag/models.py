"""Strict query-time contracts for local catalog retrieval and grounded answers."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator

from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.run import RagAnswer
from document_enhancer.domain.run import RagGroundingAudit as GroundingAudit
from document_enhancer.domain.run import RagRelevanceGrade as RelevanceGrade


class RetrievalFilters(StrictModel):
    """Allow-listed metadata policy applied inside every retrieval channel."""

    document_ids: tuple[StrictStr, ...] = ()
    document_types: tuple[StrictStr, ...] = ()
    domains: tuple[StrictStr, ...] = ()
    statuses: tuple[StrictStr, ...] = ()
    confidentiality: tuple[StrictStr, ...] = ()
    authorities: tuple[StrictStr, ...] = ("explicit", "derived", "reviewed")
    review_statuses: tuple[StrictStr, ...] = ()
    graph_layers: tuple[StrictStr, ...] = ()
    effective_at: StrictStr | None = None
    current_versions_only: StrictBool = True
    catalog_generation: StrictInt | None = Field(default=None, gt=0)

    @field_validator("effective_at")
    @classmethod
    def validate_effective_date(cls, value: StrictStr | None) -> StrictStr | None:
        if value is not None:
            date.fromisoformat(value)
        return value


class GraphPathStep(StrictModel):
    edge_id: StrictStr
    source_id: StrictStr
    predicate: StrictStr
    target_id: StrictStr
    layer: StrictStr
    authority: StrictStr
    depth: StrictInt = Field(gt=0, le=2)


class RetrievalHit(StrictModel):
    chunk_id: StrictStr
    document_id: StrictStr
    version_id: StrictStr
    section_id: StrictStr
    section_path: StrictStr
    section_title: StrictStr
    markdown_anchor: StrictStr | None = None
    text: StrictStr
    token_count: StrictInt = Field(default=0, ge=0)
    source_span_ids: tuple[StrictStr, ...] = ()
    authority: StrictStr
    review_status: StrictStr
    confidentiality: StrictStr
    channel: Literal["vector", "lexical", "graph", "hybrid"]
    rank: StrictInt = Field(gt=0)
    score: StrictFloat
    fused_score: StrictFloat | None = None
    channel_ranks: dict[StrictStr, StrictInt] = Field(default_factory=dict)
    channel_scores: dict[StrictStr, StrictFloat] = Field(default_factory=dict)
    graph_paths: tuple[tuple[GraphPathStep, ...], ...] = ()

    @field_validator("text", "section_path", "section_title")
    @classmethod
    def validate_text_fields(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="retrieval hit text")


class RetrievalDiagnostics(StrictModel):
    normalized_query: StrictStr
    catalog_generation: StrictInt = Field(ge=0)
    embedding_profile: StrictStr
    filters: RetrievalFilters
    channel_counts: dict[StrictStr, StrictInt] = Field(default_factory=dict)
    retry_count: StrictInt = Field(default=0, ge=0, le=1)
    selected_context_ids: tuple[StrictStr, ...] = ()
    context_tokens: StrictInt = Field(default=0, ge=0)
    latency_ms: dict[StrictStr, StrictFloat] = Field(default_factory=dict)
    stages: tuple[StrictStr, ...] = ()


class RetrievalResult(StrictModel):
    hits: tuple[RetrievalHit, ...]
    diagnostics: RetrievalDiagnostics


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: StrictStr

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="chat message")


class RagRunResult(StrictModel):
    answer: RagAnswer
    retrieval: RetrievalResult
    rewritten_query: StrictStr
    grounding: GroundingAudit
    retrieval_retry_count: StrictInt = Field(ge=0, le=1)
    grounding_repair_count: StrictInt = Field(ge=0, le=1)


__all__ = [
    "ChatMessage",
    "GraphPathStep",
    "GroundingAudit",
    "RelevanceGrade",
    "RagRunResult",
    "RetrievalDiagnostics",
    "RetrievalFilters",
    "RetrievalHit",
    "RetrievalResult",
]
