"""FTS5 lexical retriever with metadata filtering inside the SQL boundary."""

from __future__ import annotations

from pathlib import Path

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from ..catalog_reader import chunk_select, filter_sql, open_catalog_readonly, row_to_document
from ..models import RetrievalFilters
from .base import document_with, query_terms


class FTS5Retriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    catalog_path: Path
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    candidate_count: int = Field(default=20, gt=0, le=1000)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        del run_manager
        terms = query_terms(query)
        if not terms:
            return []
        match = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        connection = open_catalog_readonly(self.catalog_path)
        try:
            where, parameters = filter_sql(self.filters)
            sql = (
                chunk_select()
                + " JOIN chunks_fts ON chunks_fts.chunk_id=c.chunk_id"
                + " WHERE chunks_fts MATCH ?"
            )
            args: list[object] = [match]
            if where:
                sql += " AND " + where
                args.extend(parameters)
            sql += " ORDER BY bm25(chunks_fts), c.chunk_id LIMIT ?"
            args.append(self.candidate_count)
            rows = list(connection.execute(sql, args))
            documents: list[Document] = []
            for rank, row in enumerate(rows, start=1):
                # FTS5 bm25 values are implementation-oriented and often negative. Rank is the
                # fusion contract; this bounded score is for diagnostics only.
                score = 1.0 / rank
                documents.append(
                    document_with(
                        row_to_document(connection, row),
                        retrieval_channel="lexical",
                        retrieval_rank=rank,
                        retrieval_score=score,
                        lexical_query=match,
                    )
                )
            return documents
        finally:
            connection.close()


__all__ = ["FTS5Retriever"]
