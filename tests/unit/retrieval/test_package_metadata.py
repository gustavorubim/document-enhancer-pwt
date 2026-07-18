from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.unit
def test_rag_dependencies_are_optional_and_minimal() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]
    core = "\n".join(project["dependencies"])
    rag = "\n".join(project["optional-dependencies"]["rag"])

    assert "langchain" not in core
    assert "faiss" not in core
    assert "deepagents" not in rag
    assert {
        dependency.split(">=", 1)[0] for dependency in project["optional-dependencies"]["rag"]
    } == {
        "faiss-cpu",
        "langchain",
        "langchain-google-genai",
        "langchain-text-splitters",
    }
