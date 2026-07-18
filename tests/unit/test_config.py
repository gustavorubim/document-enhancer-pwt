from __future__ import annotations

from pathlib import Path

import pytest

from document_enhancer.config import config_as_public_dict, load_config
from document_enhancer.errors import ConfigurationError


def test_configuration_precedence(tmp_path: Path) -> None:
    user = tmp_path / "user.toml"
    project = tmp_path / "project.toml"
    user.write_text('[gemini]\nbackend = "vertex_ai"\nstructure_model = "user"\n')
    project.write_text('[gemini]\nstructure_model = "project"\n')
    config = load_config(
        user_path=user,
        project_path=project,
        environ={"DOCENHANCE_STRUCTURE_MODEL": "environment"},
        cli_overrides={"gemini": {"structure_model": "cli"}},
    )
    assert config.gemini.backend == "vertex_ai"
    assert config.gemini.structure_model == "cli"


def test_public_config_contains_no_credential_fields() -> None:
    payload = config_as_public_dict(load_config(environ={}))
    rendered = repr(payload).lower()
    assert "api_key" not in rendered
    assert "password" not in rendered
    assert payload["workspace"]["run_dir"] == ".document-enhancer/runs"


def test_invalid_environment_value_has_configuration_exit_contract() -> None:
    with pytest.raises(ConfigurationError):
        load_config(environ={"DOCENHANCE_BACKEND": "not-a-backend"})


def test_rag_configuration_is_non_secret_and_validates_numeric_overrides() -> None:
    config = load_config(
        environ={
            "DOCENHANCE_RAG_CATALOG": "/tmp/catalog",
            "DOCENHANCE_RAG_EMBEDDING_DIMENSIONS": "1536",
            "DOCENHANCE_RAG_CHUNK_SIZE": "3000",
            "DOCENHANCE_RAG_CHUNK_OVERLAP": "250",
        }
    )

    assert config.rag.catalog_dir == Path("/tmp/catalog")
    assert config.rag.embedding_dimensions == 1536
    assert config.rag.chunk_size == 3000
    assert config.rag.chunk_overlap == 250
    with pytest.raises(ConfigurationError, match="integer"):
        load_config(environ={"DOCENHANCE_RAG_CHUNK_SIZE": "large"})
