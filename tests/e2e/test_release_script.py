from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_release_script_is_syntactically_valid_and_isolates_clone_and_install() -> None:
    path = Path("scripts/verify_release.sh")
    result = subprocess.run(["bash", "-n", str(path)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    text = path.read_text(encoding="utf-8")
    assert "git clone --quiet --no-local" in text
    assert "uv run --isolated --with" in text
    assert "not live_model and not public_download" in text
    assert "--until questions" in text
    assert 'test "$run_exit" -eq 10' in text
