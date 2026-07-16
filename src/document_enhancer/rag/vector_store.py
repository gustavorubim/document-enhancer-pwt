"""Small LangChain adapter used by the WT0 SQLite compatibility spike.

This is deliberately an in-memory exact-scan implementation. It is a compatibility boundary and
diagnostic fallback, not the production RAG catalog. The production lane must replace it with the
pinned sqlite-vec adapter while retaining the same profile and size guard.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt
from typing import Any, ClassVar

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from pydantic import PrivateAttr


@dataclass(frozen=True)
class ExactScanPolicy:
    """Safety boundary for the deliberately bounded exact-scan fallback."""

    max_vectors: int = 1_000
    profile: str = "gemini-embedding-2:768:v1"

    def validate(self, *, vector_count: int, profile: str) -> None:
        if vector_count > self.max_vectors:
            raise ValueError(
                f"exact-scan fallback is limited to {self.max_vectors} vectors; "
                f"received {vector_count}"
            )
        if profile != self.profile:
            raise ValueError(
                f"embedding profile mismatch: indexed={self.profile!r}, requested={profile!r}"
            )


class ExactScanVectorStore(VectorStore):
    """Concrete LangChain `VectorStore` for known vectors and bounded diagnostics."""

    _documents: list[Document] = PrivateAttr(default_factory=list)
    _vectors: list[tuple[float, ...]] = PrivateAttr(default_factory=list)
    _embedding: Embeddings | None = PrivateAttr(default=None)
    _profile: str = PrivateAttr(default="")
    _policy: ExactScanPolicy = PrivateAttr(default_factory=ExactScanPolicy)
    _default_profile: ClassVar[str] = "gemini-embedding-2:768:v1"

    def __init__(
        self,
        documents: Sequence[Document],
        vectors: Sequence[Sequence[float]],
        *,
        embedding: Embeddings | None,
        profile: str = _default_profile,
        policy: ExactScanPolicy | None = None,
    ) -> None:
        super().__init__()
        if len(documents) != len(vectors):
            raise ValueError("documents and vectors must have equal lengths")
        if not vectors:
            raise ValueError("exact-scan vector store requires at least one vector")
        dimensions = len(vectors[0])
        if dimensions == 0 or any(len(vector) != dimensions for vector in vectors):
            raise ValueError("all vectors must have the same non-zero dimensionality")
        selected_policy = policy or ExactScanPolicy(profile=profile)
        selected_policy.validate(vector_count=len(vectors), profile=profile)
        self._documents = list(documents)
        self._vectors = [tuple(float(value) for value in vector) for vector in vectors]
        self._embedding = embedding
        self._profile = profile
        self._policy = selected_policy

    @classmethod
    def from_vectors(
        cls,
        documents: Sequence[Document],
        vectors: Sequence[Sequence[float]],
        *,
        profile: str = _default_profile,
        policy: ExactScanPolicy | None = None,
        embedding: Embeddings | None = None,
    ) -> ExactScanVectorStore:
        return cls(
            documents,
            vectors,
            embedding=embedding,
            profile=profile,
            policy=policy,
        )

    @classmethod
    def from_texts(
        cls,
        texts: list[str],
        embedding: Embeddings,
        metadatas: list[dict[str, Any]] | None = None,
        *,
        ids: list[str] | None = None,
        **kwargs: Any,
    ) -> ExactScanVectorStore:
        profile = str(kwargs.pop("profile", cls._default_profile))
        policy = kwargs.pop("policy", None)
        if kwargs:
            raise TypeError(f"unsupported exact-scan options: {sorted(kwargs)}")
        metadata_rows = metadatas or [{} for _ in texts]
        if len(metadata_rows) != len(texts):
            raise ValueError("metadatas and texts must have equal lengths")
        documents = [
            Document(
                page_content=text, metadata={**metadata, **({"id": ids[index]} if ids else {})}
            )
            for index, (text, metadata) in enumerate(zip(texts, metadata_rows, strict=True))
        ]
        return cls(
            documents,
            embedding.embed_documents(texts),
            embedding=embedding,
            profile=profile,
            policy=policy,
        )

    def similarity_search(self, query: str, k: int = 4, **kwargs: Any) -> list[Document]:
        if self._embedding is None:
            raise ValueError("exact-scan vector store needs an embedding adapter for text queries")
        return [
            document
            for document, _score in self.similarity_search_with_score_by_vector(
                self._embedding.embed_query(query), k=k, **kwargs
            )
        ]

    def similarity_search_with_score_by_vector(
        self,
        embedding: Sequence[float],
        k: int = 4,
        **_: Any,
    ) -> list[tuple[Document, float]]:
        query = tuple(float(value) for value in embedding)
        if len(query) != len(self._vectors[0]):
            raise ValueError("query vector dimensionality does not match the indexed profile")
        query_norm = sqrt(sum(value * value for value in query))
        if query_norm == 0:
            raise ValueError("query vector must have non-zero norm")
        scored: list[tuple[Document, float]] = []
        for document, vector in zip(self._documents, self._vectors, strict=True):
            vector_norm = sqrt(sum(value * value for value in vector))
            if vector_norm == 0:
                raise ValueError("indexed vectors must have non-zero norm")
            cosine = sum(left * right for left, right in zip(query, vector, strict=True)) / (
                query_norm * vector_norm
            )
            scored.append((document, 1.0 - cosine))
        scored.sort(key=lambda item: item[1])
        return scored[: max(0, k)]


__all__ = ["ExactScanPolicy", "ExactScanVectorStore"]
