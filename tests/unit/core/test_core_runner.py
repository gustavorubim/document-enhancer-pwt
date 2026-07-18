"""Focused tests for the file-backed v2 runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from document_enhancer.core import CoreRunner, RunStore
from document_enhancer.core.layout import (
    AUDIT,
    DECISIONS_YAML,
    FINAL_DOCX,
    FINAL_MARKDOWN,
    HTML_REPORT,
    ORIGINAL_DOCUMENT_PREFIX,
    REVIEW,
    REVIEW_INDEX_MARKDOWN,
    REWRITE_PLAN,
    RUN_RECORD,
    SOURCE_MARKDOWN,
)
from document_enhancer.core.models import (
    AuditReport,
    Decision,
    FlowEdge,
    Question,
    ReviewReport,
    RunRecord,
    Section,
)
from document_enhancer.core.review import merge_provider_review
from document_enhancer.core.rewrite import apply_reviewer_decisions
from document_enhancer.core.store import register_artifact
from document_enhancer.ingest.pipeline import DocumentIngestor


@pytest.mark.unit
def test_runner_pauses_for_questions_and_resumes_from_yaml(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text(
        "# Intake\n\nThe owner submits the request.\n\n# Decision\n\nStatus: TBD\n",
        encoding="utf-8",
    )
    runner = CoreRunner(tmp_path / "runs")

    waiting = runner.start(source)

    assert waiting.status == "waiting"
    assert waiting.phase == "human_review"
    assert waiting.unresolved_question_ids == ["question-placeholder-001"]
    assert (tmp_path / "runs" / waiting.run_id / REVIEW_INDEX_MARKDOWN).is_file()
    assert (tmp_path / "runs" / waiting.run_id / HTML_REPORT).is_file()
    decisions = tmp_path / "runs" / waiting.run_id / DECISIONS_YAML
    decisions.write_text(
        "approve_rewrite: true\n"
        'steering: ""\n'
        "waivers: []\n"
        "decisions:\n"
        "  - question_id: question-placeholder-001\n"
        "    answer: approved\n"
        "    disposition: accept\n",
        encoding="utf-8",
    )

    complete = runner.resume(waiting.run_id)

    assert complete.status == "succeeded"
    assert complete.phase == "verify"
    assert (tmp_path / "runs" / complete.run_id / RUN_RECORD).stat().st_size < 50_000
    final = (tmp_path / "runs" / complete.run_id / FINAL_MARKDOWN).read_text(encoding="utf-8")
    assert "Status: approved" in final
    audit = json.loads((tmp_path / "runs" / complete.run_id / AUDIT).read_text())
    assert audit["status"] == "pass"
    assert set(complete.artifacts) >= {
        "source.original",
        "review.report",
        "output.final_markdown",
        "output.final_docx",
        "output.semantic",
        "output.ontology",
        "output.graph",
        "audit.report",
        "audit.changes",
        "audit.source_to_target",
    }
    retry = runner.start(source)
    assert retry.run_id != complete.run_id
    assert (tmp_path / "runs" / complete.run_id / RUN_RECORD).is_file()


@pytest.mark.unit
def test_runner_completes_clean_structured_document(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text(
        "# Intake\n\nThe owner submits the request.\n\n"
        "# Approval\n\nThe manager reviews and approves the request.\n",
        encoding="utf-8",
    )

    result = CoreRunner(tmp_path / "runs").start(source)

    assert result.status == "succeeded"
    assert result.unresolved_question_ids == []
    assert result.artifacts["source.original"].sha256 == result.source_digest
    assert (tmp_path / "runs" / result.run_id / FINAL_DOCX).stat().st_size > 0
    assert "audit.seal" in result.artifacts
    with pytest.raises(RuntimeError, match="sealed"):
        RunStore(tmp_path / "runs").write_text(result.run_id, FINAL_MARKDOWN, "tampered")


@pytest.mark.unit
def test_run_record_keeps_the_selected_provider_mode(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Intake\n\nThe owner reviews the result.\n", encoding="utf-8")

    result = CoreRunner(tmp_path / "runs", execution_mode="live").start(source)

    assert result.execution_mode == "live"
    assert RunStore(tmp_path / "runs").load_run(result.run_id).execution_mode == "live"


@pytest.mark.unit
def test_run_store_rejects_artifact_path_escape(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.create_dir("run-1")

    with pytest.raises(ValueError, match="escapes"):
        store.write_text("run-1", "../outside.txt", "no")


@pytest.mark.unit
def test_resume_rehydrates_an_interrupted_analyze_phase(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Review\n\nThe owner reviews the result.\n", encoding="utf-8")
    raw = DocumentIngestor().parse(source)
    store = RunStore(tmp_path / "runs")
    store.create_dir("interrupted")
    record = RunRecord(
        run_id="interrupted",
        source_digest=raw.source_digest,
        source_name=source.name,
        status="running",
        phase="analyze",
    )
    store.save_run(record)
    original_artifact = store.write_bytes(
        "interrupted",
        f"{ORIGINAL_DOCUMENT_PREFIX}.md",
        source.read_bytes(),
        media_type=raw.media_type,
    )
    normalized_artifact = store.write_text(
        "interrupted", SOURCE_MARKDOWN, source.read_text(encoding="utf-8")
    )
    record = register_artifact(record, "source.original", original_artifact)
    record = register_artifact(record, "source.normalized", normalized_artifact)
    store.save_run(record)

    resumed = CoreRunner(tmp_path / "runs").resume("interrupted")

    assert resumed.status == "succeeded"
    assert resumed.phase == "verify"


@pytest.mark.unit
def test_provider_enrichment_and_rewrite_are_recorded_as_optional_artifacts(tmp_path: Path) -> None:
    class ReviewStub:
        def review(self, **_: object) -> ReviewReport:
            return ReviewReport(summary="provider review")

    class RewriteStub:
        def rewrite(self, **_: object) -> tuple[str, list[str]]:
            return "# Source\n\nOwner approved.\n", ["rewrote the body"]

    source = tmp_path / "input.md"
    source.write_text("# Source\n\nThe owner reviews the result.\n", encoding="utf-8")

    result = CoreRunner(
        tmp_path / "runs", review_provider=ReviewStub(), rewrite_provider=RewriteStub()
    ).start(source)

    assert result.status == "succeeded"
    assert "Owner approved." in (tmp_path / "runs" / result.run_id / FINAL_MARKDOWN).read_text()
    assert (tmp_path / "runs" / result.run_id / REWRITE_PLAN).is_file()


@pytest.mark.unit
def test_provider_questions_are_part_of_the_human_gate(tmp_path: Path) -> None:
    class ReviewStub:
        def review(self, **_: object) -> ReviewReport:
            return ReviewReport(
                summary="provider review",
                questions=[
                    Question(
                        question_id="provider-q-1",
                        prompt="Confirm the owner.",
                        reason="The provider found an unresolved business choice.",
                    )
                ],
            )

    source = tmp_path / "input.md"
    source.write_text("# Source\n\nThe owner reviews the result.\n", encoding="utf-8")

    result = CoreRunner(tmp_path / "runs", review_provider=ReviewStub()).start(source)

    assert result.status == "waiting"
    assert result.unresolved_question_ids == ["provider-q-1"]


@pytest.mark.unit
def test_offline_rewrite_applies_natural_language_open_point_decisions() -> None:
    source = (
        "P1: within 60 minutes of receipt\n"
        "STEP-CCT-050 says 60 minutes; CTRL-CCT-002 says 30 minutes\n"
        "Draft says manager approval; approval partner not stated\n"
        "RULE-CCT-004 names manager approval but does not identify required independent approval\n"
        "The pilot readiness checklist still says five years after calendar-year end. "
        "Records Management must confirm which period is authoritative before approval.\n"
        "Retain pilot complaint records for 5 years after calendar-year end.\n"
        "Section 15 says 7 years after closure; readiness checklist says 5 years after year end\n"
    )
    decision = Decision(
        question_id="question-open-points-001",
        answer=(
            "Use 30 minutes, retain records for seven years after case closure, and require an "
            "independent Compliance approver for every material batch action."
        ),
    )

    rewritten, changes = apply_reviewer_decisions(source, decisions=[decision])

    assert "60 minutes" not in rewritten
    assert "5 years" not in rewritten
    assert "approval partner not stated" not in rewritten
    assert "independent Compliance concurrence is required" in rewritten
    assert len(changes) >= 7


@pytest.mark.unit
def test_review_provider_uses_one_macro_call_and_bounded_section_batches(tmp_path: Path) -> None:
    class ReviewStub:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def review(self, **_: object) -> ReviewReport:
            self.batch_sizes.append(0)
            return ReviewReport(summary="macro")

        def review_sections(self, *, sections: list[object], **_: object) -> ReviewReport:
            self.batch_sizes.append(len(sections))
            return ReviewReport(summary="sections")

    source = tmp_path / "input.md"
    source.write_text(
        "\n\n".join(f"# Section {index}\n\nThe owner reviews step {index}." for index in range(9)),
        encoding="utf-8",
    )
    provider = ReviewStub()

    result = CoreRunner(tmp_path / "runs", review_provider=provider).start(source)

    assert result.status == "succeeded"
    assert provider.batch_sizes == [0, 4, 4, 1]


@pytest.mark.unit
def test_flow_graph_requires_evidence_for_relationships(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text(
        "# Intake\n\nThe owner records the request.\n\n"
        "# Approval\n\nIf complete, then submit to the manager.\n\n"
        "# Archive\n\nStore the approved record.\n",
        encoding="utf-8",
    )

    result = CoreRunner(tmp_path / "runs").start(source)
    review = ReviewReport.model_validate(
        json.loads((tmp_path / "runs" / result.run_id / REVIEW).read_text(encoding="utf-8"))
    )

    assert [node.node_id for node in review.flow_nodes] == [
        "section-001",
        "section-002",
        "section-003",
    ]
    assert {(edge.source, edge.target, edge.relation) for edge in review.flow_edges} == {
        ("section-002", "section-003", "branch"),
    }
    assert review.flow_edges[0].evidence_span_ids
    assert "section-001 --> section-002" not in review.mermaid


@pytest.mark.unit
def test_provider_flow_edges_are_evidence_filtered_and_typed() -> None:
    base = ReviewReport(
        summary="base",
        process_applicable=True,
        sections=[
            Section(section_id="one", title="One", level=1, span_ids=["span-1"]),
            Section(section_id="two", title="Two", level=1, span_ids=["span-2"]),
        ],
    )
    candidate = ReviewReport(
        summary="provider",
        flow_edges=[
            FlowEdge(
                edge_id="candidate-valid",
                source="one",
                target="two",
                relation="branch",
                evidence_span_ids=["span-1"],
            ),
            FlowEdge(
                edge_id="candidate-invalid",
                source="one",
                target="two",
                relation="sequence",
                evidence_span_ids=["unknown"],
            ),
        ],
    )

    merged = merge_provider_review(base, candidate, allowed_span_ids={"span-1", "span-2"})

    assert [(edge.source, edge.target, edge.relation) for edge in merged.flow_edges] == [
        ("one", "two", "branch")
    ]
    assert "branch" in merged.mermaid


@pytest.mark.unit
def test_independent_audit_provider_is_recorded_without_changing_offline_contract(
    tmp_path: Path,
) -> None:
    class AuditStub:
        def audit(self, **_: object) -> AuditReport:
            return AuditReport(
                status="pass",
                checks={"content_fidelity": True},
                summary="independent pass",
            )

    source = tmp_path / "input.md"
    source.write_text("# Source\n\nThe owner reviews the result.\n", encoding="utf-8")

    result = CoreRunner(tmp_path / "runs", audit_provider=AuditStub()).start(source)

    assert result.status == "succeeded"
    audit = json.loads((tmp_path / "runs" / result.run_id / AUDIT).read_text(encoding="utf-8"))
    assert audit["checks"]["independent_content_audit"] is True
