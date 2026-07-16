"""Shared retriever conversion and deterministic query helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from langchain_core.documents import Document

from document_enhancer.contracts import Retriever

from ..catalog_reader import catalog_generation, open_catalog_readonly
from ..models import GraphPathStep, RetrievalFilters, RetrievalHit


def query_terms(query: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(token.casefold() for token in re.findall(r"[\w-]+", query) if token)
    )[:64]


def generation(path: Path) -> int:
    connection = open_catalog_readonly(path)
    try:
        return catalog_generation(connection)
    finally:
        connection.close()


def document_hit(
    document: Document,
    *,
    rank: int,
    channel: Literal["vector", "lexical", "graph", "hybrid"],
) -> RetrievalHit:
    metadata = document.metadata
    raw_paths = metadata.get("graph_paths", [])
    paths = tuple(tuple(GraphPathStep.model_validate(step) for step in path) for path in raw_paths)
    return RetrievalHit(
        chunk_id=str(metadata["chunk_id"]),
        document_id=str(metadata["document_id"]),
        version_id=str(metadata["version_id"]),
        section_id=str(metadata["section_id"]),
        section_path=str(metadata["section_path"]),
        section_title=str(metadata["section_title"]),
        markdown_anchor=(
            str(metadata["markdown_anchor"]) if metadata.get("markdown_anchor") else None
        ),
        text=document.page_content,
        token_count=int(metadata.get("token_count", 0)),
        source_span_ids=tuple(str(value) for value in metadata.get("source_span_ids", [])),
        authority=str(metadata["authority"]),
        review_status=str(metadata["review_status"]),
        confidentiality=str(metadata["confidentiality"]),
        channel=channel,
        rank=rank,
        score=float(metadata.get("retrieval_score", 0.0)),
        fused_score=(
            float(metadata["fused_score"]) if metadata.get("fused_score") is not None else None
        ),
        channel_ranks={
            str(key): int(value) for key, value in metadata.get("channel_ranks", {}).items()
        },
        channel_scores={
            str(key): float(value) for key, value in metadata.get("channel_scores", {}).items()
        },
        graph_paths=paths,
    )


def document_with(document: Document, **metadata: Any) -> Document:
    value = document.model_copy(deep=True)
    value.metadata.update(metadata)
    return value


__all__ = [
    "RetrievalFilters",
    "Retriever",
    "document_hit",
    "document_with",
    "generation",
    "query_terms",
]
