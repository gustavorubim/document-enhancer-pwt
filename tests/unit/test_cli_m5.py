from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from document_enhancer.cli import app

runner = CliRunner()


def test_cli_waiting_status_and_prompt_commands(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "docs/architecture.md",
            "--run-dir",
            str(tmp_path / "runs"),
            "--until",
            "questions",
            "--json",
        ],
    )
    assert result.exit_code == 10
    payload = json.loads(result.stdout)
    assert payload["status"] == "waiting"
    assert payload["current_stage"] == "gate1"
    assert payload["exit_code"] == 10
    resolved = tmp_path / "runs" / payload["run_id"] / "prompts" / "resolved-manifest.json"
    assert resolved.is_file()
    assert "Architecture foundation" not in resolved.read_text(encoding="utf-8")

    status = runner.invoke(
        app,
        ["status", payload["run_id"], "--run-dir", str(tmp_path / "runs"), "--json"],
    )
    assert status.exit_code == 0
    assert json.loads(status.stdout)["next_action"].startswith("Edit clarification")

    resumed = runner.invoke(
        app, ["resume", payload["run_id"], "--run-dir", str(tmp_path / "runs"), "--json"]
    )
    assert resumed.exit_code == 0
    assert json.loads(resumed.stdout)["status"] == "succeeded"

    prompts = runner.invoke(app, ["prompts", "list", "--json"])
    assert prompts.exit_code == 0
    assert any(
        item["prompt_id"] == "clarification.questions"
        for item in json.loads(prompts.stdout)["prompts"]
    )

    composed = runner.invoke(app, ["prompts", "show", "structure.triage", "--composed", "--json"])
    assert composed.exit_code == 0
    composed_payload = json.loads(composed.stdout)
    assert "BEGIN GOVERNED INSTRUCTIONS" in composed_payload["text"]

    validated = runner.invoke(app, ["prompts", "validate", "--json"])
    assert validated.exit_code == 0
    assert json.loads(validated.stdout)["ok"] is True
