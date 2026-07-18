"""Optional local RAG/GraphRAG consumer for sealed Document Enhancer bundles."""

from .models import (
    AnswerClaim,
    AnswerEnvelope,
    AnswerResult,
    EmbeddingProfile,
    GraphExpansion,
    GraphPath,
    RagChunk,
    RetrievalHit,
    SourceCitation,
    TraceEvent,
)

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
