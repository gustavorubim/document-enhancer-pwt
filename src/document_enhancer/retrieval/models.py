"""Small contracts for the optional sealed-bundle retrieval consumer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _gemini_compatible_schema(schema: dict[str, object]) -> None:
    """Keep strict runtime validation without sending Gemini an unsupported keyword."""

    schema.pop("additionalProperties", None)


class EmbeddingProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    dimensions: int = Field(ge=8)
    format_version: str
    implementation: str


class RagChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    run_id: str
    bundle_path: str
    source_digest: str
    final_digest: str
    document_title: str
    heading_path: tuple[str, ...]
    section_ordinal: int = Field(ge=0)
    chunk_ordinal: int = Field(ge=0)
    start_index: int = Field(ge=0)
    end_index: int = Field(ge=0)
    text: str
    graph_node_ids: tuple[str, ...] = ()
    provenance_span_ids: tuple[str, ...] = ()


class RetrievalHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk: RagChunk
    score: float
    channels: tuple[str, ...]
    channel_ranks: dict[str, int]


class GraphPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_ids: tuple[str, ...]
    edge_types: tuple[str, ...]


class GraphExpansion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seed_node_ids: tuple[str, ...]
    reached_node_ids: tuple[str, ...]
    paths: tuple[GraphPath, ...]
    chunks: tuple[RagChunk, ...]


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: Literal["search_evidence", "expand_graph", "corpus_map", "agent"]
    input: dict[str, object]
    evidence_ids: tuple[str, ...] = ()
    graph_paths: tuple[GraphPath, ...] = ()
    duration_ms: float = Field(default=0, ge=0)
    status: str = "ok"


class AnswerClaim(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_extra=_gemini_compatible_schema
    )

    text: str = Field(min_length=1)
    citation_ids: tuple[str, ...] = Field(min_length=1)


class AnswerEnvelope(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_extra=_gemini_compatible_schema
    )

    status: Literal["answered", "insufficient"]
    claims: tuple[AnswerClaim, ...] = ()


class SourceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    chunk_id: str
    run_id: str
    document_title: str
    heading_path: tuple[str, ...]
    bundle_path: str
    provenance_span_ids: tuple[str, ...] = ()


class AnswerResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["answered", "insufficient"]
    claims: tuple[AnswerClaim, ...]
    sources: tuple[SourceCitation, ...]
    trace: tuple[TraceEvent, ...]


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Literal["answer", "enumerate", "compare", "summarize"]
    scope: Literal["focused", "corpus"]
    coverage: Literal["retrieval", "exhaustive"]
    reason: str


class CorpusAttribute(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_extra=_gemini_compatible_schema
    )

    name: str = Field(min_length=1)
    value: str = Field(min_length=1)


class CorpusMapItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_extra=_gemini_compatible_schema
    )

    item_key: str = ""
    statement: str = Field(min_length=1)
    attributes: tuple[CorpusAttribute, ...] = ()
    citation_ids: tuple[str, ...] = Field(min_length=1)


class CorpusMapEnvelope(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_extra=_gemini_compatible_schema
    )

    items: tuple[CorpusMapItem, ...] = ()


class CoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["retrieval", "exhaustive"]
    documents_requested: int = Field(ge=0)
    documents_scanned: int = Field(ge=0)
    documents_with_matches: int = Field(ge=0)
    chunks_available: int = Field(ge=0)
    chunks_examined: int = Field(ge=0)
    failed_run_ids: tuple[str, ...] = ()
    truncated: bool = False


class CorpusResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["answered", "insufficient"]
    question: str
    plan: QueryPlan
    items: tuple[CorpusMapItem, ...]
    sources: tuple[SourceCitation, ...]
    coverage: CoverageReport
    trace: tuple[TraceEvent, ...]


__all__ = [
    "AnswerClaim",
    "AnswerEnvelope",
    "AnswerResult",
    "CorpusAttribute",
    "CorpusMapEnvelope",
    "CorpusMapItem",
    "CorpusResult",
    "CoverageReport",
    "EmbeddingProfile",
    "GraphExpansion",
    "GraphPath",
    "QueryPlan",
    "RagChunk",
    "RetrievalHit",
    "SourceCitation",
    "TraceEvent",
]
