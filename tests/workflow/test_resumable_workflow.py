from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from document_enhancer.clarification import load_yaml
from document_enhancer.clarification.artifacts import write_yaml
from document_enhancer.domain.analysis import Finding, FindingSet
from document_enhancer.domain.enums import FindingSeverity, FindingType, QuestionStatus
from document_enhancer.domain.questions import (
    Answer,
    AnswersArtifact,
    QuestionsArtifact,
    RewriteChecklist,
)
from document_enhancer.workflow import DocumentWorkflow, WorkflowServices


def test_interrupt_resume_reuses_completed_analysis_and_side_effects(tmp_path: Path) -> None:
    calls: list[str] = []

    def analysis(request):
        calls.append("analysis")
        finding = Finding(
            finding_id="F-CONTROL-RESUME",
            category="control",
            severity=FindingSeverity.BLOCKER,
            finding_type=FindingType.MISSING,
            impact="control owner is missing",
            proposed_disposition="ask the reviewer",
            requires_human_answer=True,
            blocking=True,
        )
        return FindingSet(
            document_id=request.document_id,
            source_digest=request.source_digest,
            findings=[finding],
            blocking_count=1,
        )

    services = WorkflowServices(
        run_root=tmp_path / "runs",
        source=Path("docs/architecture.md"),
        analysis_runner=analysis,
        structure_mode="parser",
        gate2_enabled=True,
        offline=True,
    )
    waiting = DocumentWorkflow(services).run()
    assert waiting.status == "waiting"
    assert waiting.exit_code == 10
    assert waiting.current_stage == "gate1"
    assert calls == ["analysis"]

    run_dir = tmp_path / "runs" / waiting.run_id
    questions = load_yaml(run_dir / "clarification/questions.yaml", QuestionsArtifact)
    answers = AnswersArtifact(
        document_id=questions.document_id,
        answers=[
            Answer(
                answer_id="ANS-RESUME",
                question_id=questions.questions[0].question_id,
                status=QuestionStatus.ANSWERED,
                answer="Control Owner",
                responder="reviewer@example.com",
                evidence_reference="answer://resume/1",
            )
        ],
    )
    write_yaml(run_dir / "clarification/answers.yaml", answers)

    gate2_waiting = DocumentWorkflow(
        WorkflowServices(
            run_root=tmp_path / "runs",
            source=Path(),
            run_id=waiting.run_id,
            structure_mode="parser",
            gate2_enabled=True,
            offline=True,
        )
    ).resume()
    assert gate2_waiting.status == "waiting"
    assert gate2_waiting.current_stage == "gate2"
    assert calls == ["analysis"]

    checklist_path = run_dir / "clarification/rewrite-checklist.yaml"
    checklist = load_yaml(checklist_path, RewriteChecklist)
    write_yaml(
        checklist_path,
        checklist.model_copy(
            update={"approved_by": "approver@example.com", "approved_at": datetime.now(UTC)}
        ),
    )
    complete = DocumentWorkflow(
        WorkflowServices(
            run_root=tmp_path / "runs",
            source=Path(),
            run_id=waiting.run_id,
            structure_mode="parser",
            gate2_enabled=True,
            offline=True,
        )
    ).resume()
    assert complete.status == "succeeded"
    assert complete.current_stage == "complete"
    assert calls == ["analysis"]
    assert (run_dir / "workflow-state.json").is_file()
    assert (run_dir / "clarification/questions.yaml").is_file()
    assert (run_dir / "audit/audit.json").is_file()
    assert (run_dir / "audit/source-to-target.csv").is_file()
    assert (run_dir / "export/chunks.jsonl").is_file()
    assert (run_dir / "export/nodes.jsonl").is_file()
    assert (run_dir / "export/edges.jsonl").is_file()
    assert (run_dir / "export/bundle-manifest.json").is_file()
