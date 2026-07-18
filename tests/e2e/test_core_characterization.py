"""User-visible characterization for the simplified core workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from document_enhancer.core import CoreRunner

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PACK = ROOT / "reference_packs" / "enterprise_core"


@pytest.mark.e2e
def test_core_process_docx_characterization_pauses_with_review_bundle(tmp_path: Path) -> None:
    source = ROOT / "examples/cookbook/aurora_ai_complaint_triage_process.docx"
    result = CoreRunner(
        tmp_path / "runs",
        recipe_pack=REFERENCE_PACK,
        document_type="process",
    ).start(source)

    run_path = tmp_path / "runs" / result.run_id
    review = json.loads((run_path / "review/review.json").read_text(encoding="utf-8"))

    assert result.status == "waiting"
    assert result.phase == "human_review"
    assert result.source_name.endswith(".docx")
    assert (run_path / "source/original.docx").is_file()
    assert (run_path / "source/normalized.md").stat().st_size > 0
    assert (run_path / "source/structure-quality.json").is_file()
    routing = json.loads((run_path / "source/structure-routing.json").read_text(encoding="utf-8"))
    assert routing["configured_mode"] == "auto"
    assert routing["selected_mode"] in {"parser", "llm_recovery"}
    assert (run_path / "review/flow.mmd").read_text(encoding="utf-8").startswith("flowchart")
    assert (run_path / "review/macro.md").is_file()
    assert (run_path / "review/sections.md").is_file()
    flow_md = (run_path / "review/flow.md").read_text(encoding="utf-8")
    assert "```mermaid" in flow_md
    assert "## Why the proposed diagram was adjusted" in flow_md
    assert "```mermaid" in flow_md and flow_md.count("```mermaid") >= 2
    assert (run_path / "review/flow.inferred.mmd").is_file()
    assert (run_path / "review/flow.proposed.mmd").is_file()
    assert "Executive summary" in (run_path / "review/macro.md").read_text(encoding="utf-8")
    assert "What is correct" in (run_path / "review/sections.md").read_text(encoding="utf-8")
    assert review["recipe_id"] == "enterprise_core@2.0.0/process"
    assert review["sections"]
    assert review["section_assessments"]
    assert {item["status"] for item in review["section_assessments"]} & {
        "correct",
        "missing",
        "improve",
    }
    assert review["process_applicable"] is True
    assert review["findings"]
    assert result.unresolved_question_ids
    assert (run_path / "run.json").stat().st_size < 50_000


@pytest.mark.e2e
def test_core_methodology_characterization_reports_rubric_and_template_gaps(
    tmp_path: Path,
) -> None:
    source = REFERENCE_PACK / "templates/methodology/example.md"
    result = CoreRunner(
        tmp_path / "runs",
        recipe_pack=REFERENCE_PACK,
        document_type="methodology",
    ).start(source)

    run_path = tmp_path / "runs" / result.run_id
    review = json.loads((run_path / "review/review.json").read_text(encoding="utf-8"))
    rubric_ids = {item["rubric_id"] for item in review["findings"]}

    assert result.status == "waiting"
    assert review["recipe_id"] == "enterprise_core@2.0.0/methodology"
    assert review["rubric_ids"]
    assert rubric_ids
    assert all(
        finding["evidence_span_ids"] or finding["rubric_id"] in review["rubric_ids"]
        for finding in review["findings"]
    )
    assert review["questions"]
    assert review["section_assessments"]
    assert review["process_applicable"] is False
    assert (run_path / "review/macro.md").is_file()
    assert (run_path / "review/sections.md").is_file()
    assert (run_path / "review/flow.md").is_file()
