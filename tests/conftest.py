from __future__ import annotations

import pytest


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DOCENHANCE_BACKEND",
        "DOCENHANCE_DEVELOPER_MODEL",
        "DOCENHANCE_RUN_DIR",
        "DOCENHANCE_RAG_CATALOG",
        "DOCENHANCE_RAG_EMBEDDING_MODEL",
        "DOCENHANCE_RAG_EMBEDDING_DIMENSIONS",
        "DOCENHANCE_RAG_CHUNK_SIZE",
        "DOCENHANCE_RAG_CHUNK_OVERLAP",
        "DOCENHANCE_LIVE_PROVIDER_CHECKS",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
