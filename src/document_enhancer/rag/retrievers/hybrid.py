"""Deterministic weighted Reciprocal Rank Fusion over local retrieval channels."""

from __future__ import annotations

from collections import Counter
from time import perf_counter

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from ..models import RetrievalDiagnostics, RetrievalFilters, RetrievalResult
from .base import document_hit, document_with, generation
from .graph import GraphRetriever
from .lexical import FTS5Retriever
from .vector import VectorRetriever


class HybridRetriever(BaseRetriever):
    """One explainable retrieval boundary with stable RRF tie-breaking."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    vector: VectorRetriever
    lexical: FTS5Retriever
    graph: GraphRetriever
    top_k: int = Field(default=10, gt=0, le=1000)
    rrf_constant: int = Field(default=60, ge=1)
    weights: dict[str, float] = Field(
        default_factory=lambda: {"vector": 1.0, "lexical": 1.0, "graph": 0.8}
    )
    max_per_document: int = Field(default=2, ge=1)

    @property
    def filters(self) -> RetrievalFilters:
        return self.vector.filters

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        del run_manager
        channels = {
            "vector": self.vector.invoke(query),
            "lexical": self.lexical.invoke(query),
            "graph": self.graph.invoke(query),
        }
        documents: dict[str, Document] = {}
        ranks: dict[str, dict[str, int]] = {}
        scores: dict[str, dict[str, float]] = {}
        fused: dict[str, float] = {}
        for channel, hits in channels.items():
            weight = float(self.weights.get(channel, 0.0))
            for rank, document in enumerate(hits, start=1):
                chunk_id = str(document.metadata["chunk_id"])
                documents.setdefault(chunk_id, document.model_copy(deep=True))
                ranks.setdefault(chunk_id, {})[channel] = rank
                scores.setdefault(chunk_id, {})[channel] = float(
                    document.metadata.get("retrieval_score", 0.0)
                )
                fused[chunk_id] = fused.get(chunk_id, 0.0) + weight / (self.rrf_constant + rank)
                if document.metadata.get("graph_paths"):
                    documents[chunk_id].metadata["graph_paths"] = document.metadata["graph_paths"]
        ordered = sorted(fused, key=lambda item: (-fused[item], item))
        selected: list[Document] = []
        per_document: Counter[str] = Counter()
        for chunk_id in ordered:
            document = documents[chunk_id]
            document_id = str(document.metadata["document_id"])
            if per_document[document_id] >= self.max_per_document:
                continue
            per_document[document_id] += 1
            selected.append(
                document_with(
                    document,
                    retrieval_channel="hybrid",
                    retrieval_rank=len(selected) + 1,
                    retrieval_score=float(fused[chunk_id]),
                    fused_score=float(fused[chunk_id]),
                    channel_ranks=ranks[chunk_id],
                    channel_scores=scores[chunk_id],
                )
            )
            if len(selected) >= self.top_k:
                break
        return selected

    def search(self, query: str) -> RetrievalResult:
        if not query.strip():
            raise ValueError("retrieval query must not be blank")
        if len(query) > 8_000:
            raise ValueError("retrieval query exceeds the 8000-character safety limit")
        started = perf_counter()
        documents = self.invoke(query)
        hits = tuple(
            document_hit(document, rank=rank, channel="hybrid")
            for rank, document in enumerate(documents, start=1)
        )
        counts = Counter(channel for hit in hits for channel in hit.channel_ranks)
        return RetrievalResult(
            hits=hits,
            diagnostics=RetrievalDiagnostics(
                normalized_query=query,
                catalog_generation=(
                    self.filters.catalog_generation or generation(self.lexical.catalog_path)
                ),
                embedding_profile=self.vector.store.profile,
                filters=self.filters,
                channel_counts=dict(sorted(counts.items())),
                latency_ms={"hybrid_retrieval": (perf_counter() - started) * 1000},
            ),
        )


__all__ = ["HybridRetriever"]
