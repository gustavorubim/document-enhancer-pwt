"""Small contracts for the optional sealed-bundle retrieval consumer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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

    tool: Literal["search_evidence", "expand_graph", "agent"]
    input: dict[str, object]
    evidence_ids: tuple[str, ...] = ()
    graph_paths: tuple[GraphPath, ...] = ()
    duration_ms: float = Field(default=0, ge=0)
    status: str = "ok"


class AnswerClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    citation_ids: tuple[str, ...] = Field(min_length=1)


class AnswerEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

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


__all__ = [
    "AnswerClaim",
    "AnswerEnvelope",
    "AnswerResult",
    "EmbeddingProfile",
    "GraphExpansion",
    "GraphPath",
    "RagChunk",
    "RetrievalHit",
    "SourceCitation",
    "TraceEvent",
]
