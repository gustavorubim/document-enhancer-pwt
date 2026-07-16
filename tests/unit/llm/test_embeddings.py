from __future__ import annotations

import math
from pathlib import Path

import pytest

from document_enhancer.llm import (
    EmbeddingDocument,
    EmbeddingInputTooLargeError,
    EmbeddingProfile,
    EmbeddingValidationError,
    GeminiEmbeddingAdapter,
    format_document,
    format_query,
)
from document_enhancer.llm.caching import ResponseCache


class FakeEmbedder:
    def __init__(self) -> None:
        self.document_batches: list[list[str]] = []
        self.document_kwargs: list[dict[str, object]] = []
        self.query_inputs: list[str] = []
        self.query_kwargs: list[dict[str, object]] = []

    def embed_documents(self, texts: list[str], **kwargs: object) -> list[list[float]]:
        self.document_batches.append(texts)
        self.document_kwargs.append(kwargs)
        return [[float(index + 1)] + [0.0] * 767 for index, _ in enumerate(texts)]

    def embed_query(self, text: str, **kwargs: object) -> list[float]:
        self.query_inputs.append(text)
        self.query_kwargs.append(kwargs)
        return [1.0] + [0.0] * 767


def test_document_and_query_formatting_is_deterministic() -> None:
    assert format_document(EmbeddingDocument(" Demo ", "1 / Scope", "line\nvalue")) == (
        "title: Demo — 1 / Scope | text: line value"
    )
    assert (
        format_query("  What   is the trigger? ")
        == "task: search result | query: What is the trigger?"
    )


def test_embeddings_preserve_one_logical_input_per_vector_and_cache_metadata(
    tmp_path: Path,
) -> None:
    fake = FakeEmbedder()
    adapter = GeminiEmbeddingAdapter(
        profile=EmbeddingProfile(),
        embedder=fake,
        cache=ResponseCache(tmp_path / "cache"),
        batch_size=2,
    )
    vectors = adapter.embed_document_chunks(
        [
            EmbeddingDocument("Doc", "A", "one"),
            EmbeddingDocument("Doc", "B", "two"),
            EmbeddingDocument("Doc", "C", "three"),
        ]
    )
    assert len(vectors) == 3
    assert [len(batch) for batch in fake.document_batches] == [2, 1]
    assert adapter.last_manifest is not None
    assert adapter.last_manifest.input_count == 3
    assert adapter.last_manifest.batch_count == 2
    assert adapter.embed_query("what?")[0] == 1.0
    assert fake.query_inputs == ["task: search result | query: what?"]
    assert all("task_type" not in kwargs for kwargs in fake.document_kwargs)
    assert all("task_type" not in kwargs for kwargs in fake.query_kwargs)
    assert all(
        "one" not in path.read_text(encoding="utf-8")
        for path in (tmp_path / "cache").glob("*.json")
    )


def test_embeddings_reject_oversize_dimension_and_nonfinite_values() -> None:
    with pytest.raises(EmbeddingInputTooLargeError):
        GeminiEmbeddingAdapter(
            profile=EmbeddingProfile(max_input_characters=3), embedder=FakeEmbedder()
        ).embed_documents(["four"])

    class WrongDimension(FakeEmbedder):
        def embed_documents(self, texts: list[str], **_: object) -> list[list[float]]:
            return [[0.0] * 3 for _ in texts]

    with pytest.raises(EmbeddingValidationError, match="dimension"):
        GeminiEmbeddingAdapter(embedder=WrongDimension()).embed_documents(["ok"])

    class NonFinite(FakeEmbedder):
        def embed_documents(self, texts: list[str], **_: object) -> list[list[float]]:
            return [[math.inf] + [0.0] * 767 for _ in texts]

    with pytest.raises(EmbeddingValidationError, match="non-finite"):
        GeminiEmbeddingAdapter(embedder=NonFinite()).embed_documents(["ok"])
