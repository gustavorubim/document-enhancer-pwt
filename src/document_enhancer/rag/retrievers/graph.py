"""Bounded deterministic graph-neighborhood retriever."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from ..catalog_reader import fetch_chunks, open_catalog_readonly, row_to_document
from ..models import GraphPathStep, RetrievalFilters
from .base import document_with, query_terms


class GraphRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    catalog_path: Path
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    candidate_count: int = Field(default=20, gt=0, le=1000)
    max_depth: int = Field(default=1, ge=1, le=2)
    allowed_predicates: tuple[str, ...] = ()
    minimum_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    def _linked_nodes(self, connection: Any, query: str) -> tuple[str, ...]:
        terms = query_terms(query)
        if not terms:
            return ()
        matches: set[str] = set()
        for term in terms:
            like = f"%{term}%"
            for row in connection.execute(
                """SELECT node_id FROM graph_nodes
                   WHERE lower(node_id)=? OR lower(canonical_name) LIKE ?
                   UNION
                   SELECT node_id FROM graph_aliases WHERE lower(alias) LIKE ?
                   ORDER BY node_id LIMIT 20""",
                (term, like, like),
            ):
                matches.add(str(row[0]))
        return tuple(sorted(matches))

    def _edge_allowed(self, row: Any) -> bool:
        if str(row["predicate"]) in {"retrieval_association", "RELATED_TO_DOCUMENT"}:
            return False
        if str(row["layer"]) == "retrieval":
            return False
        if self.allowed_predicates and str(row["predicate"]) not in self.allowed_predicates:
            return False
        if self.filters.graph_layers and str(row["layer"]) not in self.filters.graph_layers:
            return False
        if self.filters.authorities and str(row["authority"]) not in self.filters.authorities:
            return False
        if (
            self.filters.review_statuses
            and str(row["review_status"]) not in self.filters.review_statuses
        ):
            return False
        if self.filters.effective_at:
            if row["valid_from"] and str(row["valid_from"]) > self.filters.effective_at:
                return False
            if row["valid_to"] and str(row["valid_to"]) < self.filters.effective_at:
                return False
        confidence = row["confidence"]
        return confidence is None or float(confidence) >= self.minimum_confidence

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        del run_manager
        connection = open_catalog_readonly(self.catalog_path)
        try:
            roots = self._linked_nodes(connection, query)
            if not roots:
                return []
            paths: dict[str, list[list[dict[str, object]]]] = {root: [[]] for root in roots}
            queue = deque((root, 0, []) for root in roots)
            visited_depth: dict[str, int] = {root: 0 for root in roots}
            while queue:
                node_id, depth, path = queue.popleft()
                if depth >= self.max_depth:
                    continue
                rows = connection.execute(
                    """SELECT edge_id, source_id, predicate, target_id, layer, authority,
                              confidence, review_status, valid_from, valid_to
                       FROM graph_edges WHERE (source_id=? OR target_id=?)
                         AND (? IS NULL OR EXISTS (
                           SELECT 1 FROM graph_edge_versions gev
                           JOIN catalog_ingestions ci ON ci.version_id=gev.version_id
                           WHERE gev.edge_id=graph_edges.edge_id AND ci.catalog_generation<=?
                         ))
                       ORDER BY edge_id""",
                    (
                        node_id,
                        node_id,
                        self.filters.catalog_generation,
                        self.filters.catalog_generation,
                    ),
                )
                for row in rows:
                    if not self._edge_allowed(row):
                        continue
                    other = str(
                        row["target_id"] if row["source_id"] == node_id else row["source_id"]
                    )
                    next_depth = depth + 1
                    step = GraphPathStep(
                        edge_id=str(row["edge_id"]),
                        source_id=str(row["source_id"]),
                        predicate=str(row["predicate"]),
                        target_id=str(row["target_id"]),
                        layer=str(row["layer"]),
                        authority=str(row["authority"]),
                        depth=next_depth,
                    ).model_dump(mode="json")
                    next_path = [*path, step]
                    paths.setdefault(other, []).append(next_path)
                    if visited_depth.get(other, self.max_depth + 1) > next_depth:
                        visited_depth[other] = next_depth
                        queue.append((other, next_depth, next_path))

            node_ids = tuple(sorted(paths))
            placeholders = ", ".join("?" for _ in node_ids)
            chunk_nodes: dict[str, list[str]] = {}
            for row in connection.execute(
                f"""SELECT chunk_id, node_id FROM chunk_entities
                    WHERE node_id IN ({placeholders}) ORDER BY chunk_id, node_id""",
                node_ids,
            ):
                chunk_nodes.setdefault(str(row["chunk_id"]), []).append(str(row["node_id"]))
            rows = fetch_chunks(connection, chunk_nodes, self.filters)
            ranked = sorted(
                rows,
                key=lambda chunk_id: (
                    min(len(path) for node in chunk_nodes[chunk_id] for path in paths[node]),
                    chunk_id,
                ),
            )[: self.candidate_count]
            documents: list[Document] = []
            for rank, chunk_id in enumerate(ranked, start=1):
                graph_paths = [
                    path for node_id in chunk_nodes[chunk_id] for path in paths[node_id] if path
                ]
                documents.append(
                    document_with(
                        row_to_document(connection, rows[chunk_id]),
                        retrieval_channel="graph",
                        retrieval_rank=rank,
                        retrieval_score=1.0 / rank,
                        linked_node_ids=chunk_nodes[chunk_id],
                        graph_paths=graph_paths[:4],
                    )
                )
            return documents
        finally:
            connection.close()


__all__ = ["GraphRetriever"]
