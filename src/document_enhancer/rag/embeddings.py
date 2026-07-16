"""Deterministic embedding build helpers and strict float32 vector encoding."""

from __future__ import annotations

import hashlib
import math
import struct
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from document_enhancer.llm import EmbeddingDocument, GeminiEmbeddingAdapter


def encode_float32(vector: Sequence[float], *, dimension: int) -> tuple[bytes, str, float]:
    values = tuple(float(value) for value in vector)
    if len(values) != dimension:
        raise ValueError(f"vector dimension mismatch: expected {dimension}, got {len(values)}")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("vector contains a non-finite value")
    blob = struct.pack(f"<{dimension}f", *values)
    decoded = struct.unpack(f"<{dimension}f", blob)
    if not all(math.isfinite(value) for value in decoded):
        raise ValueError("float32 conversion produced a non-finite value")
    return (
        blob,
        hashlib.sha256(blob).hexdigest(),
        math.sqrt(sum(value * value for value in decoded)),
    )


def decode_float32(blob: bytes, *, dimension: int) -> tuple[float, ...]:
    expected = dimension * 4
    if len(blob) != expected:
        raise ValueError(f"vector byte length mismatch: expected {expected}, got {len(blob)}")
    values = struct.unpack(f"<{dimension}f", blob)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("stored vector contains a non-finite value")
    return values


class OfflineDeterministicEmbedder:
    """Fake provider for offline tests; it never reads credentials or uses the network."""

    def __init__(self, dimension: int = 768, *, fail_after: int | None = None) -> None:
        self.dimension = dimension
        self.fail_after = fail_after
        self.calls = 0

    def _vector(self, text: str) -> list[float]:
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise ConnectionError("deterministic partial embedding failure")
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        values = [
            ((seed[index % len(seed)] / 255.0) * 2.0) - 1.0 for index in range(self.dimension)
        ]
        norm = math.sqrt(sum(value * value for value in values))
        return [value / norm for value in values]

    def embed_documents(self, texts: list[str], **_: object) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str, **_: object) -> list[float]:
        return self._vector(text)


@dataclass(frozen=True, slots=True)
class EmbeddedVector:
    vector: tuple[float, ...]
    attempts: int


def is_retryable_embedding_error(error: BaseException) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    return status in {408, 409, 429, 500, 502, 503, 504}


class EmbeddingBatchRunner:
    """One-logical-input embedding runner with bounded retry and rate-limit hooks."""

    def __init__(
        self,
        adapter: GeminiEmbeddingAdapter,
        *,
        max_attempts: int = 3,
        rate_limit_hook: Callable[[int], None] | None = None,
        retry_delay: Callable[[int], float] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.adapter = adapter
        self.max_attempts = max_attempts
        self.rate_limit_hook = rate_limit_hook or (lambda _count: None)
        self.retry_delay = retry_delay or (lambda attempt: min(0.05 * (2 ** (attempt - 1)), 1.0))

    def embed(self, documents: Sequence[EmbeddingDocument]) -> tuple[EmbeddedVector, ...]:
        if not documents:
            return ()
        attempts = 0
        while True:
            attempts += 1
            self.rate_limit_hook(len(documents))
            try:
                vectors = self.adapter.embed_document_chunks(documents)
                return tuple(EmbeddedVector(tuple(vector), attempts) for vector in vectors)
            except Exception as exc:
                if attempts >= self.max_attempts or not is_retryable_embedding_error(exc):
                    raise
                # Completed transport batches have already entered the adapter cache. A retry
                # resumes only missing profile/content keys while preserving logical ordering.
                time.sleep(self.retry_delay(attempts))


__all__ = [
    "EmbeddingBatchRunner",
    "EmbeddedVector",
    "OfflineDeterministicEmbedder",
    "decode_float32",
    "encode_float32",
    "is_retryable_embedding_error",
]
