"""LangChain vector retriever over the validated local vector-store boundary."""

from __future__ import annotations

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from ..models import RetrievalFilters
from ..vector_store import SQLiteCatalogVectorStore
from .base import document_with


class VectorRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    store: SQLiteCatalogVectorStore
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    candidate_count: int = Field(default=20, gt=0, le=1000)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        del run_manager
        scored = self.store.similarity_search_with_score(
            query, k=self.candidate_count, filters=self.filters
        )
        return [
            document_with(
                document,
                retrieval_channel="vector",
                retrieval_rank=rank,
                retrieval_score=float(1.0 / (1.0 + max(0.0, distance))),
                vector_distance=float(distance),
            )
            for rank, (document, distance) in enumerate(scored, start=1)
        ]


__all__ = ["VectorRetriever"]
