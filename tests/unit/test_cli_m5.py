from __future__ import annotations

import json
from pathlib import Path

import pytest
from google.auth.exceptions import DefaultCredentialsError
from typer.testing import CliRunner

from document_enhancer.cli import app

runner = CliRunner()


def test_cli_waiting_status_and_prompt_commands(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "docs/architecture.md",
            "--execution-mode",
            "offline",
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
    snapshot = json.loads(
        (tmp_path / "runs" / payload["run_id"] / "workflow-state.json").read_text(encoding="utf-8")
    )
    assert snapshot["structure_mode"] == "parser"
    assert snapshot["execution_metadata"]["mode"] == "offline"
    assert snapshot["execution_metadata"]["embedding_profile"].startswith("offline:local:")
    resolved = tmp_path / "runs" / payload["run_id"] / "prompts" / "resolved-manifest.json"
    assert resolved.is_file()
    assert "Architecture foundation" not in resolved.read_text(encoding="utf-8")

    status = runner.invoke(
        app,
        ["status", payload["run_id"], "--run-dir", str(tmp_path / "runs"), "--json"],
    )
    assert status.exit_code == 0
    assert json.loads(status.stdout)["next_action"].startswith("Edit clarification")

    wrong_mode = runner.invoke(
        app,
        [
            "resume",
            payload["run_id"],
            "--run-dir",
            str(tmp_path / "runs"),
            "--execution-mode",
            "live",
            "--json",
        ],
    )
    assert wrong_mode.exit_code != 0
    assert "differs from the persisted run" in wrong_mode.output

    resumed = runner.invoke(
        app, ["resume", payload["run_id"], "--run-dir", str(tmp_path / "runs"), "--json"]
    )
    # A full resume now includes M7. The architecture document is not a process fixture, so the
    # strict process/template audit must stop for review rather than report false success.
    assert resumed.exit_code == 10
    resumed_payload = json.loads(resumed.stdout)
    assert resumed_payload["status"] == "waiting"
    assert resumed_payload["current_stage"] == "audit"

    audited = runner.invoke(
        app,
        ["audit", payload["run_id"], "--run-dir", str(tmp_path / "runs"), "--json"],
    )
    assert audited.exit_code == 30
    assert json.loads(audited.stdout)["status"] == "waiting"

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


def test_live_preflight_and_offline_catalog_policy_fail_before_workflow(tmp_path: Path) -> None:
    no_credentials = runner.invoke(
        app,
        [
            "run",
            "docs/architecture.md",
            "--run-dir",
            str(tmp_path / "live-runs"),
            "--until",
            "questions",
            "--json",
        ],
        env={
            "DOCENHANCE_BACKEND": "developer_api",
            "GOOGLE_API_KEY": "",
            "GEMINI_API_KEY": "",
        },
    )
    assert no_credentials.exit_code != 0
    assert "requires GOOGLE_API_KEY or GEMINI_API_KEY" in no_credentials.output
    assert not (tmp_path / "live-runs").exists()

    unsafe_offline_catalog = runner.invoke(
        app,
        [
            "run",
            "docs/architecture.md",
            "--execution-mode",
            "offline",
            "--catalog-ingest",
            "--run-dir",
            str(tmp_path / "offline-runs"),
            "--json",
        ],
    )
    assert unsafe_offline_catalog.exit_code != 0
    assert "requires an explicit --catalog path" in unsafe_offline_catalog.output
    assert not (tmp_path / "offline-runs").exists()


def test_vertex_live_preflight_requires_adc_before_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing_adc():
        raise DefaultCredentialsError("test has no ADC")

    monkeypatch.setattr("google.auth.default", missing_adc)
    result = runner.invoke(
        app,
        [
            "run",
            "docs/architecture.md",
            "--run-dir",
            str(tmp_path / "vertex-runs"),
            "--until",
            "questions",
            "--json",
        ],
        env={
            "DOCENHANCE_BACKEND": "vertex_ai",
            "DOCENHANCE_VERTEX_PROJECT": "test-project",
            "DOCENHANCE_VERTEX_LOCATION": "us-central1",
            "GOOGLE_APPLICATION_CREDENTIALS": "",
        },
    )
    assert result.exit_code != 0
    assert "requires Application Default Credentials" in result.output
    assert not (tmp_path / "vertex-runs").exists()
