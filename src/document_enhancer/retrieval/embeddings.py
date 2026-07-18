"""Versioned embedding profiles for the optional RAG catalog."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from langchain_core.embeddings import Embeddings

from .models import EmbeddingProfile

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_FORMAT_VERSION = "gemini-embedding-2-question-answering-v1"


def format_document(title: str, text: str) -> str:
    return f"title: {title.strip() or 'none'} | text: {text}"


def format_query(query: str) -> str:
    return f"task: question answering | query: {query.strip()}"


class ProfiledEmbeddings(Embeddings):
    """Attach a persisted identity and the asymmetric query format to an embedding client."""

    def __init__(self, inner: Embeddings, profile: EmbeddingProfile) -> None:
        self.inner = inner
        self.profile = profile

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self.inner.embed_documents(texts)
        self._validate(vectors, len(texts))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        vectors = [self.inner.embed_query(format_query(text))]
        self._validate(vectors, 1)
        return vectors[0]

    def _validate(self, vectors: list[list[float]], expected: int) -> None:
        if len(vectors) != expected:
            raise ValueError("embedding provider returned the wrong vector cardinality")
        for vector in vectors:
            if len(vector) != self.profile.dimensions:
                raise ValueError("embedding provider returned the wrong vector dimensions")
            if not all(math.isfinite(value) for value in vector):
                raise ValueError("embedding provider returned a non-finite vector")


class DeterministicEmbeddings(Embeddings):
    """Feature-hash vectors for offline tests; never represented as a live provider."""

    def __init__(self, dimensions: int = 64) -> None:
        self.profile = EmbeddingProfile(
            provider="offline",
            model="feature-hash-v1",
            dimensions=dimensions,
            format_version="offline-feature-hash-v1",
            implementation="document_enhancer.retrieval.DeterministicEmbeddings",
        )
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(format_query(text))

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class IdentityEmbeddings(Embeddings):
    """Profile-only client used to inspect an index without calling its provider."""

    def __init__(self, profile: EmbeddingProfile) -> None:
        self.profile = profile

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("inspection embeddings cannot embed documents")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("inspection embeddings cannot embed queries")


def gemini_embeddings(*, model: str, dimensions: int, **kwargs: Any) -> ProfiledEmbeddings:
    """Create the live Gemini Embeddings 2 profile without reading or logging credentials."""

    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    inner = GoogleGenerativeAIEmbeddings(
        model=model,
        output_dimensionality=dimensions,
        task_type=None,
        **kwargs,
    )
    profile = EmbeddingProfile(
        provider="google",
        model=model,
        dimensions=dimensions,
        format_version=_FORMAT_VERSION,
        implementation="langchain_google_genai.GoogleGenerativeAIEmbeddings",
    )
    return ProfiledEmbeddings(inner, profile)


def embedding_profile(embeddings: Embeddings) -> EmbeddingProfile:
    profile = getattr(embeddings, "profile", None)
    if not isinstance(profile, EmbeddingProfile):
        raise ValueError("embedding implementation must expose an EmbeddingProfile")
    return profile


__all__ = [
    "DeterministicEmbeddings",
    "IdentityEmbeddings",
    "ProfiledEmbeddings",
    "embedding_profile",
    "format_document",
    "format_query",
    "gemini_embeddings",
]
