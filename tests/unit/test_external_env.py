from __future__ import annotations

import os
from pathlib import Path

from document_enhancer.compatibility import load_external_env


def test_gemini_alias_maps_only_without_conventional_credentials(
    tmp_path: Path, monkeypatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "gemini_api=alias-dummy\nunknown_key=must-not-load\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("UNKNOWN_KEY", raising=False)

    load_external_env(env_file)

    assert os.environ["GEMINI_API_KEY"] == "alias-dummy"
    assert "UNKNOWN_KEY" not in os.environ

    monkeypatch.setenv("GEMINI_API_KEY", "conventional-dummy")
    load_external_env(env_file)
    assert os.environ["GEMINI_API_KEY"] == "conventional-dummy"

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-dummy")
    load_external_env(env_file)
    assert "GEMINI_API_KEY" not in os.environ
