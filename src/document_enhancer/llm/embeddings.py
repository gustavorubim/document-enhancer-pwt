"""Gemini Embedding 2 adapter with deterministic document/query profiles."""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .caching import CacheKey, ResponseCache, digest_bytes
from .profiles import EMBEDDING_MODEL


class EmbeddingValidationError(ValueError):
    """An embedding response is malformed, non-finite, or in another vector space."""


class EmbeddingInputTooLargeError(ValueError):
    """The adapter rejected an input instead of silently truncating it."""


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    model: str = EMBEDDING_MODEL
    dimensions: int = 768
    document_format_version: str = "gemini-embedding-2-document-v1"
    query_format_version: str = "gemini-embedding-2-query-v1"
    max_input_characters: int = 100_000
    backend: str = "developer_api"

    def __post_init__(self) -> None:
        if self.model != EMBEDDING_MODEL:
            raise ValueError(f"embedding profile must use {EMBEDDING_MODEL!r}")
        if self.dimensions not in {768, 1536, 3072}:
            raise ValueError("Gemini Embedding 2 dimensions must be 768, 1536, or 3072")
        if self.max_input_characters < 1:
            raise ValueError("max_input_characters must be positive")
        if self.backend not in {"developer_api", "vertex_ai"}:
            raise ValueError("backend must be developer_api or vertex_ai")

    @property
    def identity(self) -> str:
        return f"{self.model}:{self.dimensions}:{self.document_format_version}:{self.query_format_version}:{self.backend}"


@dataclass(frozen=True, slots=True)
class EmbeddingDocument:
    title: str
    section_path: str
    text: str


@dataclass(frozen=True, slots=True)
class EmbeddingManifest:
    profile: str
    model: str
    dimensions: int
    batch_count: int
    input_count: int
    cache_hits: int
    input_digests: tuple[str, ...]
    vector_digests: tuple[str, ...]


def _clean(value: str) -> str:
    return " ".join(value.split())


def format_document(document: EmbeddingDocument) -> str:
    return f"title: {_clean(document.title)} — {_clean(document.section_path)} | text: {_clean(document.text)}"


def format_query(question: str) -> str:
    return f"task: search result | query: {_clean(question)}"


def _vector_digest(vector: Sequence[float]) -> str:
    encoded = ",".join(repr(float(item)) for item in vector).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


class GeminiEmbeddingAdapter:
    """LangChain-compatible embedding adapter with an explicit profile boundary."""

    def __init__(
        self,
        *,
        profile: EmbeddingProfile | None = None,
        api_key: str | None = None,
        project: str | None = None,
        location: str | None = None,
        embedder: Any | None = None,
        embedder_factory: Callable[[EmbeddingProfile], Any] | None = None,
        cache: ResponseCache | None = None,
        batch_size: int = 32,
    ) -> None:
        self.profile = profile or EmbeddingProfile()
        self._api_key = api_key
        self._project = project
        self._location = location
        self._embedder = embedder
        self._embedder_factory = embedder_factory
        self._cache = cache
        self.batch_size = max(1, batch_size)
        self.last_manifest: EmbeddingManifest | None = None

    def _client(self) -> Any:
        if self._embedder is not None:
            return self._embedder
        if self._embedder_factory is not None:
            self._embedder = self._embedder_factory(self.profile)
            return self._embedder
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        api_key = self._api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        kwargs: dict[str, Any] = {
            "model": self.profile.model,
            "vertexai": self.profile.backend == "vertex_ai",
            "project": self._project,
            "location": self._location,
            "output_dimensionality": self.profile.dimensions,
        }
        if self.profile.backend == "developer_api":
            if not api_key:
                raise RuntimeError("Gemini Developer API credentials are unavailable")
            kwargs["api_key"] = api_key
        elif not self._project or not self._location:
            raise RuntimeError("Vertex AI embedding requires project and location")
        self._embedder = GoogleGenerativeAIEmbeddings(**kwargs)
        return self._embedder

    def _check_input(self, text: str) -> None:
        if len(text) > self.profile.max_input_characters:
            raise EmbeddingInputTooLargeError(
                "embedding input exceeds the configured limit; split deterministically before retrying"
            )

    def _key(self, text: str, *, task: str) -> CacheKey:
        return CacheKey(
            provider="google",
            backend=self.profile.backend,
            model=self.profile.model,
            parameters={
                "dimensions": self.profile.dimensions,
                "format_version": (
                    self.profile.document_format_version
                    if task == "document"
                    else self.profile.query_format_version
                ),
                "task": task,
            },
            prompt_digest=digest_bytes(text.encode("utf-8")),
            schema_digest="embedding-vector-float32",
            input_digests=(digest_bytes(text.encode("utf-8")),),
        )

    def _validate(self, vector: Sequence[float]) -> list[float]:
        if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)):
            raise EmbeddingValidationError("embedding response is not a numeric sequence")
        if len(vector) != self.profile.dimensions:
            raise EmbeddingValidationError(
                f"embedding dimension mismatch: expected {self.profile.dimensions}, got {len(vector)}"
            )
        result = [float(value) for value in vector]
        if not all(math.isfinite(value) for value in result):
            raise EmbeddingValidationError("embedding response contains a non-finite value")
        return result

    def _cached(self, text: str, *, task: str) -> list[float] | None:
        if self._cache is None:
            return None
        record = self._cache.get(self._key(text, task=task))
        if record is None or not isinstance(record.response, list):
            return None
        try:
            return self._validate(record.response)
        except EmbeddingValidationError:
            return None

    def _store(self, text: str, vector: list[float], *, task: str) -> None:
        if self._cache is None:
            return
        key = self._key(text, task=task)
        self._cache.put(key, vector, manifest={"profile": self.profile.identity, "task": task})

    def embed_document_chunks(self, documents: Sequence[EmbeddingDocument]) -> list[list[float]]:
        formatted = [format_document(document) for document in documents]
        return self._embed(formatted, task="document")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed already-formatted logical documents, preserving one vector per input."""

        return self._embed(texts, task="document")

    def embed_query(self, text: str) -> list[float]:
        formatted = format_query(text)
        self._check_input(formatted)
        cached = self._cached(formatted, task="query")
        if cached is not None:
            self.last_manifest = EmbeddingManifest(
                profile=self.profile.identity,
                model=self.profile.model,
                dimensions=self.profile.dimensions,
                batch_count=0,
                input_count=1,
                cache_hits=1,
                input_digests=(digest_bytes(formatted.encode("utf-8")),),
                vector_digests=(_vector_digest(cached),),
            )
            return cached
        client = self._client()
        vector = client.embed_query(
            formatted,
            output_dimensionality=self.profile.dimensions,
        )
        result = self._validate(vector)
        self._store(formatted, result, task="query")
        self.last_manifest = EmbeddingManifest(
            profile=self.profile.identity,
            model=self.profile.model,
            dimensions=self.profile.dimensions,
            batch_count=1,
            input_count=1,
            cache_hits=0,
            input_digests=(digest_bytes(formatted.encode("utf-8")),),
            vector_digests=(_vector_digest(result),),
        )
        return result

    def _embed(self, texts: Sequence[str], *, task: str) -> list[list[float]]:
        inputs = list(texts)
        for text in inputs:
            self._check_input(text)
        if not inputs:
            self.last_manifest = EmbeddingManifest(
                profile=self.profile.identity,
                model=self.profile.model,
                dimensions=self.profile.dimensions,
                batch_count=0,
                input_count=0,
                cache_hits=0,
                input_digests=(),
                vector_digests=(),
            )
            return []
        vectors: list[list[float] | None] = [None] * len(inputs)
        cache_hits = 0
        missing: list[tuple[int, str]] = []
        for index, text in enumerate(inputs):
            cached = self._cached(text, task=task)
            if cached is None:
                missing.append((index, text))
            else:
                vectors[index] = cached
                cache_hits += 1
        batch_count = 0
        if missing:
            client = self._client()
            for start in range(0, len(missing), self.batch_size):
                batch = missing[start : start + self.batch_size]
                batch_count += 1
                raw_vectors = client.embed_documents(
                    [text for _, text in batch],
                    batch_size=len(batch),
                    output_dimensionality=self.profile.dimensions,
                )
                if len(raw_vectors) != len(batch):
                    raise EmbeddingValidationError(
                        f"embedding provider returned {len(raw_vectors)} vectors for {len(batch)} inputs"
                    )
                for (index, text), raw in zip(batch, raw_vectors, strict=True):
                    vector = self._validate(raw)
                    vectors[index] = vector
                    self._store(text, vector, task=task)
        result = [vector for vector in vectors if vector is not None]
        if len(result) != len(inputs):
            raise EmbeddingValidationError("embedding result lost a logical input")
        input_digests = tuple(digest_bytes(text.encode("utf-8")) for text in inputs)
        self.last_manifest = EmbeddingManifest(
            profile=self.profile.identity,
            model=self.profile.model,
            dimensions=self.profile.dimensions,
            batch_count=batch_count,
            input_count=len(inputs),
            cache_hits=cache_hits,
            input_digests=input_digests,
            vector_digests=tuple(_vector_digest(vector) for vector in result),
        )
        return result

    def assert_query_profile(self, other: GeminiEmbeddingAdapter) -> None:
        if self.profile.identity != other.profile.identity:
            raise EmbeddingValidationError("query/document embedding profile mismatch")
