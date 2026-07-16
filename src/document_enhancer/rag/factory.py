"""Construction helpers for profile-safe local retrievers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from document_enhancer.llm import EmbeddingProfile, GeminiEmbeddingAdapter

from .catalog_reader import CatalogReadError, open_catalog_readonly
from .models import RetrievalFilters
from .retrievers import FTS5Retriever, GraphRetriever, HybridRetriever, VectorRetriever
from .vector_store import ExactScanPolicy, SQLiteCatalogVectorStore


def catalog_embedding_profile(path: Path) -> tuple[EmbeddingProfile, str]:
    connection = open_catalog_readonly(path)
    try:
        rows = list(
            connection.execute(
                """SELECT DISTINCT embedding_profile, embedding_provider, embedding_model,
                                  embedding_dimension, embedding_backend,
                                  embedding_format_version
                   FROM rag_builds WHERE status='validated' ORDER BY embedding_profile"""
            )
        )
        if len(rows) != 1:
            raise CatalogReadError("catalog must have one validated query embedding profile")
        provider = str(rows[0]["embedding_provider"])
        profile = (
            EmbeddingProfile.offline(dimensions=int(rows[0]["embedding_dimension"]))
            if provider == "offline"
            else EmbeddingProfile(
                model=str(rows[0]["embedding_model"]),
                dimensions=int(rows[0]["embedding_dimension"]),
                backend=str(rows[0]["embedding_backend"]),
            )
        )
        identity = str(rows[0]["embedding_profile"])
        if profile.identity != identity or profile.document_format_version != str(
            rows[0]["embedding_format_version"]
        ):
            raise CatalogReadError("catalog embedding profile metadata does not reconcile")
        return profile, identity
    finally:
        connection.close()


def build_hybrid_retriever(
    catalog_path: Path,
    embedding: GeminiEmbeddingAdapter,
    *,
    filters: RetrievalFilters | None = None,
    top_k: int = 10,
    candidate_count: int = 20,
    graph_depth: int = 1,
    vector_backend: Literal["auto", "sqlite_vec", "exact_scan"] = "auto",
    max_exact_scan_vectors: int = 1_000,
) -> HybridRetriever:
    profile, identity = catalog_embedding_profile(catalog_path)
    if embedding.profile.identity != identity or embedding.profile.dimensions != profile.dimensions:
        raise CatalogReadError("query embedding adapter does not match the indexed catalog profile")
    selected = filters or RetrievalFilters()
    store = SQLiteCatalogVectorStore(
        catalog_path,
        embedding=embedding,
        profile=identity,
        dimension=profile.dimensions,
        backend=vector_backend,
        exact_scan_policy=ExactScanPolicy(
            max_vectors=max_exact_scan_vectors,
            profile=identity,
        ),
    )
    return HybridRetriever(
        vector=VectorRetriever(store=store, filters=selected, candidate_count=candidate_count),
        lexical=FTS5Retriever(
            catalog_path=catalog_path,
            filters=selected,
            candidate_count=candidate_count,
        ),
        graph=GraphRetriever(
            catalog_path=catalog_path,
            filters=selected,
            candidate_count=candidate_count,
            max_depth=graph_depth,
        ),
        top_k=top_k,
    )


__all__ = ["build_hybrid_retriever", "catalog_embedding_profile"]
