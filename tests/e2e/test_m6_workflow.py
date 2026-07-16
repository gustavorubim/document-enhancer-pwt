from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from document_enhancer.cli import app


@pytest.mark.e2e
def test_offline_cli_completes_m6_and_writes_agreeing_outputs(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "run",
            "docs/architecture.md",
            "--no-gate2",
            "--run-dir",
            str(tmp_path / "runs"),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    run_dir = tmp_path / "runs" / payload["run_id"] / "output"
    required = {
        "content-ledger.jsonl",
        "rewrite-inputs.json",
        "enhanced-model.json",
        "enhanced.md",
        "open-issues.yaml",
        "enhanced.semantic.yaml",
        "mermaid-validation.json",
    }
    assert required <= {path.name for path in run_dir.iterdir()}
    model = json.loads((run_dir / "enhanced-model.json").read_text(encoding="utf-8"))
    semantic = (run_dir / "enhanced.semantic.yaml").read_text(encoding="utf-8")
    assert model["ledger_id"] in semantic
    assert "AUTHORING" not in (run_dir / "enhanced.md").read_text(encoding="utf-8")
