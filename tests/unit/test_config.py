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
    assert payload["gemini"]["embedding_dimensions"] == 768


def test_invalid_environment_value_has_configuration_exit_contract() -> None:
    with pytest.raises(ConfigurationError):
        load_config(environ={"DOCENHANCE_EMBEDDING_DIMENSIONS": "not-an-int"})
