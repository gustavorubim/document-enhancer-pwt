"""LangChain vector stores for promoted SQLite catalogs and bounded diagnostics."""

from __future__ import annotations

import hashlib
import math
import sqlite3
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from pydantic import PrivateAttr

from .catalog_reader import (
    CatalogReadError,
    fetch_chunks,
    open_catalog_readonly,
    row_to_document,
)
from .embeddings import decode_float32
from .models import RetrievalFilters


class _SQLiteVecUnavailable(RuntimeError):
    """The pinned extension cannot be loaded on this platform."""


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


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("query vector dimensionality does not match the indexed profile")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("query and indexed vectors must have non-zero norm")
    cosine = sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
    return 1.0 - cosine


class ExactScanVectorStore(VectorStore):
    """Concrete LangChain store retained as the explicit small-catalog fallback."""

    _documents: list[Document] = PrivateAttr(default_factory=list)
    _vectors: list[tuple[float, ...]] = PrivateAttr(default_factory=list)
    _embedding: Embeddings | Any | None = PrivateAttr(default=None)
    _profile: str = PrivateAttr(default="")
    _policy: ExactScanPolicy = PrivateAttr(default_factory=ExactScanPolicy)
    _default_profile: ClassVar[str] = "gemini-embedding-2:768:v1"

    def __init__(
        self,
        documents: Sequence[Document],
        vectors: Sequence[Sequence[float]],
        *,
        embedding: Embeddings | Any | None,
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
        if any(not math.isfinite(float(value)) for vector in vectors for value in vector):
            raise ValueError("indexed vectors must contain only finite values")
        selected_policy = policy or ExactScanPolicy(profile=profile)
        selected_policy.validate(vector_count=len(vectors), profile=profile)
        self._documents = [document.model_copy(deep=True) for document in documents]
        self._vectors = [tuple(float(value) for value in vector) for vector in vectors]
        self._embedding = embedding
        self._profile = profile
        self._policy = selected_policy

    @property
    def embeddings(self) -> Embeddings | None:
        return self._embedding

    @classmethod
    def from_vectors(
        cls,
        documents: Sequence[Document],
        vectors: Sequence[Sequence[float]],
        *,
        profile: str = _default_profile,
        policy: ExactScanPolicy | None = None,
        embedding: Embeddings | Any | None = None,
    ) -> ExactScanVectorStore:
        return cls(documents, vectors, embedding=embedding, profile=profile, policy=policy)

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
                id=ids[index] if ids else None,
                page_content=text,
                metadata={**metadata, **({"id": ids[index]} if ids else {})},
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

    def similarity_search_with_score(
        self, query: str, k: int = 4, **kwargs: Any
    ) -> list[tuple[Document, float]]:
        if self._embedding is None:
            raise ValueError("exact-scan vector store needs an embedding adapter for text queries")
        return self.similarity_search_with_score_by_vector(
            self._embedding.embed_query(query), k=k, **kwargs
        )

    def similarity_search_by_vector(
        self, embedding: list[float], k: int = 4, **kwargs: Any
    ) -> list[Document]:
        return [
            document
            for document, _score in self.similarity_search_with_score_by_vector(
                embedding, k=k, **kwargs
            )
        ]

    def similarity_search_with_score_by_vector(
        self,
        embedding: Sequence[float],
        k: int = 4,
        **_: Any,
    ) -> list[tuple[Document, float]]:
        query = tuple(float(value) for value in embedding)
        scored = [
            (document.model_copy(deep=True), _distance(query, vector))
            for document, vector in zip(self._documents, self._vectors, strict=True)
        ]
        scored.sort(key=lambda item: (item[1], str(item[0].metadata.get("chunk_id", ""))))
        return scored[: max(0, k)]


class SQLiteCatalogVectorStore(VectorStore):
    """Validated SQLiteVec adapter with a bounded exact-scan compatibility fallback."""

    _catalog_path: Path = PrivateAttr()
    _embedding: Embeddings | Any = PrivateAttr()
    _profile: str = PrivateAttr()
    _dimension: int = PrivateAttr()
    _documents: dict[str, Document] = PrivateAttr(default_factory=dict)
    _vectors: dict[str, tuple[float, ...]] = PrivateAttr(default_factory=dict)
    _backend: Literal["sqlite_vec", "exact_scan"] = PrivateAttr(default="exact_scan")
    _vec_connection: sqlite3.Connection | None = PrivateAttr(default=None)
    _rowids: dict[int, str] = PrivateAttr(default_factory=dict)
    _policy: ExactScanPolicy = PrivateAttr()

    def __init__(
        self,
        catalog_path: Path,
        *,
        embedding: Embeddings | Any,
        profile: str,
        dimension: int,
        backend: Literal["auto", "sqlite_vec", "exact_scan"] = "auto",
        exact_scan_policy: ExactScanPolicy | None = None,
    ) -> None:
        super().__init__()
        self._catalog_path = catalog_path.expanduser().resolve()
        self._embedding = embedding
        self._profile = profile
        self._dimension = dimension
        self._documents = {}
        self._vectors = {}
        self._rowids = {}
        self._backend = "exact_scan"
        self._vec_connection = None
        self._policy = exact_scan_policy or ExactScanPolicy(max_vectors=1_000, profile=profile)
        self._load_validated_rows()
        if backend == "exact_scan":
            self._enable_exact_scan()
        else:
            try:
                self._enable_sqlite_vec()
            except (
                ImportError,
                ModuleNotFoundError,
                OSError,
                sqlite3.NotSupportedError,
                _SQLiteVecUnavailable,
            ) as exc:
                if backend == "sqlite_vec":
                    raise CatalogReadError("SQLiteVec is required but unavailable") from exc
                self._enable_exact_scan()

    @classmethod
    def from_texts(
        cls,
        texts: list[str],
        embedding: Embeddings,
        metadatas: list[dict[str, Any]] | None = None,
        *,
        ids: list[str] | None = None,
        **kwargs: Any,
    ) -> SQLiteCatalogVectorStore:
        del texts, embedding, metadatas, ids, kwargs
        raise NotImplementedError(
            "SQLiteCatalogVectorStore is read-only; build and promote a validated catalog first"
        )

    @property
    def embeddings(self) -> Embeddings | None:
        return self._embedding

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def profile(self) -> str:
        return self._profile

    @property
    def dimension(self) -> int:
        return self._dimension

    def _load_validated_rows(self) -> None:
        connection = open_catalog_readonly(self._catalog_path)
        try:
            profiles = list(
                connection.execute(
                    """SELECT DISTINCT profile_id, dimension FROM embeddings WHERE selected=1
                       ORDER BY profile_id, dimension"""
                )
            )
            if len(profiles) != 1:
                raise CatalogReadError("catalog must expose exactly one selected embedding profile")
            indexed_profile, indexed_dimension = str(profiles[0][0]), int(profiles[0][1])
            expected_profile_id = hashlib.sha256(self._profile.encode()).hexdigest()
            if indexed_profile != expected_profile_id:
                raise CatalogReadError(
                    f"embedding profile mismatch: indexed={indexed_profile!r}, requested={self._profile!r}"
                )
            if indexed_dimension != self._dimension:
                raise CatalogReadError(
                    f"embedding dimension mismatch: indexed={indexed_dimension}, requested={self._dimension}"
                )
            rows = list(
                connection.execute(
                    """SELECT cv.*, e.vector_blob AS embedding_blob,
                              e.vector_digest AS embedding_digest, e.dimension AS embedding_dimension
                       FROM chunk_vectors cv
                       JOIN embeddings e ON e.object_id=cv.chunk_id AND e.selected=1
                       ORDER BY cv.chunk_id"""
                )
            )
            chunk_count = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
            if not rows or len(rows) != chunk_count:
                raise CatalogReadError("catalog chunk/vector coverage is incomplete")
            chunk_rows = fetch_chunks(
                connection,
                (str(row["chunk_id"]) for row in rows),
                RetrievalFilters(
                    current_versions_only=False,
                    authorities=(),
                    review_statuses=(),
                ),
            )
            if len(chunk_rows) != len(rows):
                raise CatalogReadError("catalog vector references a missing chunk")
            for row in rows:
                chunk_id = str(row["chunk_id"])
                blob = bytes(row["vector_blob"])
                if (
                    str(row["profile_id"]) != expected_profile_id
                    or int(row["dimension"]) != self._dimension
                    or int(row["embedding_dimension"]) != self._dimension
                    or bytes(row["embedding_blob"]) != blob
                    or str(row["embedding_digest"]) != str(row["vector_digest"])
                    or hashlib.sha256(blob).hexdigest() != str(row["vector_digest"])
                ):
                    raise CatalogReadError(f"corrupt or mismatched vector row: {chunk_id}")
                vector = decode_float32(blob, dimension=self._dimension)
                if math.sqrt(sum(value * value for value in vector)) == 0:
                    raise CatalogReadError(f"zero-norm vector is not retrievable: {chunk_id}")
                self._vectors[chunk_id] = vector
                self._documents[chunk_id] = row_to_document(connection, chunk_rows[chunk_id])
        finally:
            connection.close()

    def _enable_exact_scan(self) -> None:
        self._policy.validate(vector_count=len(self._vectors), profile=self._profile)
        self._backend = "exact_scan"

    def _enable_sqlite_vec(self) -> None:
        import sqlite_vec

        connection = sqlite3.connect(":memory:")
        try:
            connection.enable_load_extension(True)
            try:
                sqlite_vec.load(connection)
            except sqlite3.OperationalError as exc:
                raise _SQLiteVecUnavailable("SQLiteVec extension loading failed") from exc
            connection.execute(
                f"CREATE VIRTUAL TABLE vectors USING vec0(embedding float[{self._dimension}])"
            )
            for rowid, (chunk_id, vector) in enumerate(sorted(self._vectors.items()), start=1):
                blob = sqlite_vec.serialize_float32(list(vector))
                connection.execute(
                    "INSERT INTO vectors(rowid, embedding) VALUES (?, ?)", (rowid, blob)
                )
                self._rowids[rowid] = chunk_id
            connection.commit()
        except Exception:
            connection.close()
            raise
        self._vec_connection = connection
        self._backend = "sqlite_vec"

    def _eligible_ids(self, filters: RetrievalFilters) -> set[str]:
        connection = open_catalog_readonly(self._catalog_path)
        try:
            return set(fetch_chunks(connection, self._vectors, filters))
        finally:
            connection.close()

    def similarity_search(self, query: str, k: int = 4, **kwargs: Any) -> list[Document]:
        return [
            document for document, _score in self.similarity_search_with_score(query, k, **kwargs)
        ]

    def similarity_search_with_score(
        self, query: str, k: int = 4, **kwargs: Any
    ) -> list[tuple[Document, float]]:
        return self.similarity_search_with_score_by_vector(
            self._embedding.embed_query(query), k=k, **kwargs
        )

    def similarity_search_by_vector(
        self, embedding: list[float], k: int = 4, **kwargs: Any
    ) -> list[Document]:
        return [
            document
            for document, _score in self.similarity_search_with_score_by_vector(
                embedding, k=k, **kwargs
            )
        ]

    def similarity_search_with_score_by_vector(
        self, embedding: Sequence[float], k: int = 4, **kwargs: Any
    ) -> list[tuple[Document, float]]:
        query = tuple(float(value) for value in embedding)
        if len(query) != self._dimension or any(not math.isfinite(value) for value in query):
            raise ValueError("query vector dimensionality or values do not match indexed profile")
        filters = kwargs.pop("filters", RetrievalFilters())
        if kwargs:
            raise TypeError(f"unsupported vector search options: {sorted(kwargs)}")
        if not isinstance(filters, RetrievalFilters):
            filters = RetrievalFilters.model_validate(filters)
        if k <= 0:
            return []
        eligible = self._eligible_ids(filters)
        # SQLiteVec cannot apply relational metadata predicates inside the temporary vec0 table.
        # Rank all validated vectors, then apply the already-computed eligible ID set so a narrow
        # filter cannot lose its best hit merely because unrelated vectors filled a pre-filter k.
        candidate_count = len(self._vectors)
        if self._backend == "sqlite_vec":
            assert self._vec_connection is not None
            import sqlite_vec

            rows = self._vec_connection.execute(
                "SELECT rowid, distance FROM vectors WHERE embedding MATCH ? AND k = ?",
                (sqlite_vec.serialize_float32(list(query)), candidate_count),
            )
            scored = [(self._rowids[int(rowid)], float(distance)) for rowid, distance in rows]
        else:
            scored = [
                (chunk_id, _distance(query, vector)) for chunk_id, vector in self._vectors.items()
            ]
            scored.sort(key=lambda item: (item[1], item[0]))
        selected: list[tuple[Document, float]] = []
        for chunk_id, distance in scored:
            if chunk_id not in eligible:
                continue
            document = self._documents[chunk_id].model_copy(deep=True)
            document.metadata.update({"retrieval_channel": "vector", "vector_distance": distance})
            selected.append((document, distance))
            if len(selected) >= max(0, k):
                break
        return selected

    def __del__(self) -> None:
        private = getattr(self, "__pydantic_private__", None)
        connection = private.get("_vec_connection") if isinstance(private, dict) else None
        if connection is not None:
            with suppress(sqlite3.Error):
                connection.close()


__all__ = ["ExactScanPolicy", "ExactScanVectorStore", "SQLiteCatalogVectorStore"]
