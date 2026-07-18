from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from typer.testing import CliRunner

from document_enhancer.cli import _load_project_env, app
from document_enhancer.config import load_config
from document_enhancer.llm.models import BackendName, GeminiGatewayConfig
from document_enhancer.retrieval.embeddings import format_document, gemini_embeddings

from .helpers import write_bundle


@pytest.mark.live_model
def test_live_gemini_embedding_two_profile_and_faiss_round_trip(tmp_path: Path) -> None:
    import faiss
    import numpy as np

    _load_project_env()
    config = load_config()
    gateway = GeminiGatewayConfig.from_env(
        backend=config.gemini.backend,
        project=config.gemini.project,
        location=config.gemini.location,
    )
    kwargs: dict[str, object] = {}
    if gateway.backend == BackendName.DEVELOPER_API:
        if gateway.api_key is None:
            pytest.skip("Gemini credentials are unavailable")  # ty: ignore[too-many-positional-arguments]
        kwargs["api_key"] = gateway.api_key
    else:
        if not gateway.project or not gateway.location:
            pytest.skip("Vertex project/location are unavailable")  # ty: ignore[too-many-positional-arguments]
        kwargs.update({"vertexai": True, "project": gateway.project, "location": gateway.location})
    embeddings = gemini_embeddings(
        model=config.rag.embedding_model,
        dimensions=config.rag.embedding_dimensions,
        **kwargs,
    )
    documents = [
        format_document("Alpha", "The owner reviews the control monthly."),
        format_document("Beta", "The vendor supplies a daily file."),
    ]

    vectors = embeddings.embed_documents(documents)
    query = embeddings.embed_query("Who reviews the control monthly?")
    assert len(vectors) == 2
    assert all(len(vector) == 768 for vector in vectors)
    assert len(query) == 768
    assert all(math.isfinite(value) for vector in [*vectors, query] for value in vector)
    matrix = np.asarray(vectors, dtype="float32")
    faiss.normalize_L2(matrix)
    index = faiss.IndexFlatIP(768)
    index.add(matrix)
    faiss.write_index(index, str(tmp_path / "index.faiss"))
    loaded = faiss.read_index(str(tmp_path / "index.faiss"))
    query_matrix = np.asarray([query], dtype="float32")
    faiss.normalize_L2(query_matrix)
    _scores, positions = loaded.search(query_matrix, 1)
    assert int(positions[0][0]) == 0


@pytest.mark.live_model
def test_live_rag_cli_indexes_asks_and_chats_with_valid_citations(tmp_path: Path) -> None:
    _load_project_env()
    gateway = GeminiGatewayConfig.from_env()
    if gateway.backend == BackendName.DEVELOPER_API and gateway.api_key is None:
        pytest.skip("Gemini credentials are unavailable")  # ty: ignore[too-many-positional-arguments]
    first = write_bundle(
        tmp_path / "runs",
        "run-live-a",
        "# Alpha Process\n\n## Overview\n\nAlpha is governed by POL-42.\n",
    )
    second = write_bundle(
        tmp_path / "runs",
        "run-live-b",
        "# POL-42\n\n## Overview\n\nThe Risk Committee reviews POL-42 monthly.\n",
    )
    assert first.is_dir() and second.is_dir()
    catalog = tmp_path / "catalog"
    runner = CliRunner()

    indexed = runner.invoke(
        app,
        [
            "rag",
            "index",
            "run-live-a",
            "run-live-b",
            "--run-dir",
            str(tmp_path / "runs"),
            "--catalog",
            str(catalog),
            "--json",
        ],
    )
    asked = runner.invoke(
        app,
        [
            "rag",
            "ask",
            "Who reviews the policy governing Alpha and how often?",
            "--catalog",
            str(catalog),
            "--json",
        ],
    )
    chatted = runner.invoke(
        app,
        ["rag", "chat", "--catalog", str(catalog)],
        input="What policy governs Alpha?\n/exit\n",
    )

    assert indexed.exit_code == 0, indexed.output
    assert asked.exit_code == 0, asked.output
    payload = json.loads(asked.stdout)
    assert payload["status"] == "answered"
    source_ids = {item["evidence_id"] for item in payload["sources"]}
    assert source_ids
    assert all(
        citation in source_ids for claim in payload["claims"] for citation in claim["citation_ids"]
    )
    assert chatted.exit_code == 0, chatted.output
    assert "Sources" in chatted.stdout
