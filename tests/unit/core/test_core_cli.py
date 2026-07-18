"""Focused contract checks for the simplified CLI seam."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from document_enhancer.cli import _select_source, app
from document_enhancer.core.layout import DECISIONS_YAML, QUESTIONS_MARKDOWN, REVIEW
from document_enhancer.core.recipes import load_recipe
from document_enhancer.errors import DocumentEnhancerError

ROOT = Path(__file__).resolve().parents[3]
REFERENCE_PACK = ROOT / "reference_packs" / "enterprise_core"
runner = CliRunner()


@pytest.mark.unit
def test_core_source_accepts_a_single_inbox_document(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    document = inbox / "draft.md"
    document.write_text("# Draft\n", encoding="utf-8")

    assert _select_source(inbox) == document


@pytest.mark.unit
def test_core_source_rejects_ambiguous_inbox(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "one.md").write_text("# One\n", encoding="utf-8")
    (inbox / "two.docx").write_bytes(b"not a docx")

    with pytest.raises(DocumentEnhancerError, match="exactly one"):
        _select_source(inbox)


@pytest.mark.unit
def test_default_cli_runs_and_continues_the_core_bundle(tmp_path: Path) -> None:
    recipe = load_recipe(REFERENCE_PACK, document_type="process")
    source = tmp_path / "process.md"
    body = [
        "# Controlled process",
        "",
        "Document ID: DOC-CLI-001; Version: V1; Owner: ROLE-OWNER; Status: TBD.",
        "",
    ]
    evidence = (
        "This process validates inputs, records evidence, reviews results, and escalates a control "
        "failure to the owner before proceeding."
    )
    for requirement in recipe.required_section_items:
        heading = str(requirement.get("heading") or requirement.get("id"))
        body.extend([f"## {heading}", "", evidence, ""])
    source.write_text("\n".join(body), encoding="utf-8")
    run_root = tmp_path / "runs"

    started = runner.invoke(app, ["run", str(source), "--run-dir", str(run_root), "--json"])

    assert started.exit_code == 10, started.output
    payload = json.loads(started.stdout)
    assert payload["phase"] == "human_review"
    run_id = payload["run_id"]

    status = runner.invoke(app, ["status", run_id, "--run-dir", str(run_root), "--json"])
    assert status.exit_code == 0
    assert json.loads(status.stdout)["schema_version"] == "core.cli.v1"

    review_path = run_root / run_id / REVIEW
    review = json.loads(review_path.read_text(encoding="utf-8"))
    generated_decisions = (run_root / run_id / DECISIONS_YAML).read_text(encoding="utf-8")
    assert "question:" in generated_decisions
    assert "suggestion:" in generated_decisions
    assert "answer:" in generated_decisions
    assert "disposition: defer" in generated_decisions
    assert "accept_suggestion" in generated_decisions
    assert (run_root / run_id / QUESTIONS_MARKDOWN).is_file()
    decisions = 'approve_rewrite: true\nsteering: ""\nwaivers: []\ndecisions:\n' + "".join(
        "  - question_id: {question_id}\n    answer: approved\n    disposition: accept\n".format(
            question_id=item["question_id"]
        )
        for item in review["questions"]
        if item["blocking"]
    )
    (run_root / run_id / DECISIONS_YAML).write_text(decisions, encoding="utf-8")

    continued = runner.invoke(app, ["stage-two", run_id, "--run-dir", str(run_root), "--json"])

    assert continued.exit_code == 0, continued.output
    stage_two_payload = json.loads(continued.stdout)
    assert stage_two_payload["schema_version"] == "core.cli.stage-two.v1"
    assert stage_two_payload["run"]["status"] == "succeeded"
    assert stage_two_payload["inspection"]["run"]["status"] == "succeeded"
    assert stage_two_payload["audit"]["status"] == "pass"
    inspected = runner.invoke(app, ["inspect", run_id, "--run-dir", str(run_root), "--json"])
    assert inspected.exit_code == 0
    assert json.loads(inspected.stdout)["run"]["status"] == "succeeded"
    audited = runner.invoke(app, ["audit", run_id, "--run-dir", str(run_root), "--json"])
    assert audited.exit_code == 0
    assert json.loads(audited.stdout)["schema_version"] == "core.cli.audit.v1"


@pytest.mark.unit
def test_stage_two_rich_output_explains_all_three_steps(tmp_path: Path) -> None:
    recipe = load_recipe(REFERENCE_PACK, document_type="process")
    source = tmp_path / "process.md"
    body = ["# Controlled process", "", "Status: TBD", ""]
    for requirement in recipe.required_section_items:
        heading = str(requirement.get("heading") or requirement.get("id"))
        body.extend(
            [
                f"## {heading}",
                "",
                "The owner validates inputs, records evidence, reviews results, and escalates "
                "control failures before proceeding.",
                "",
            ]
        )
    source.write_text("\n".join(body), encoding="utf-8")
    run_root = tmp_path / "runs"
    started = runner.invoke(app, ["run", str(source), "--run-dir", str(run_root), "--json"])
    run_id = json.loads(started.stdout)["run_id"]
    review = json.loads((run_root / run_id / REVIEW).read_text(encoding="utf-8"))
    decisions = 'approve_rewrite: true\nsteering: ""\nwaivers: []\ndecisions:\n' + "".join(
        "  - question_id: {question_id}\n    answer: approved\n    disposition: accept\n".format(
            question_id=item["question_id"]
        )
        for item in review["questions"]
        if item["blocking"]
    )
    (run_root / run_id / DECISIONS_YAML).write_text(decisions, encoding="utf-8")

    completed = runner.invoke(app, ["stage-two", run_id, "--run-dir", str(run_root)])

    assert completed.exit_code == 0, completed.output
    assert "STEP 1/3" in completed.stdout
    assert "STEP 2/3" in completed.stdout
    assert "STEP 3/3" in completed.stdout
    assert "Bundle inspection" in completed.stdout
    assert "Final audit" in completed.stdout
    assert "Stage 2 complete" in completed.stdout


@pytest.mark.unit
def test_stage_one_rich_output_explains_analysis_and_decision_generation(tmp_path: Path) -> None:
    source = tmp_path / "process.md"
    source.write_text(
        "# Complaint triage\n\nThe analyst reviews the complaint and escalates exceptions.\n",
        encoding="utf-8",
    )
    run_root = tmp_path / "runs"

    started = runner.invoke(app, ["run", str(source), "--run-dir", str(run_root)])

    assert started.exit_code == 10, started.output
    assert "STEP 1/2" in started.stdout
    assert "Validate the Stage 1 configuration" in started.stdout
    assert "STEP 2/2" in started.stdout
    assert "Analyze the source and prepare the review gate" in started.stdout
    assert "questions with safe suggestions" in started.stdout
    assert "enhanced decision file" in started.stdout
