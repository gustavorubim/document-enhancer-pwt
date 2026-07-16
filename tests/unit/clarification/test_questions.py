from __future__ import annotations

from document_enhancer.clarification import (
    build_rewrite_checklist,
    render_questions_markdown,
    synthesize_questions,
    validate_answers,
    validate_waivers,
)
from document_enhancer.clarification.artifacts import with_digest
from document_enhancer.domain.analysis import EvidenceQuote, Finding, FindingSet
from document_enhancer.domain.enums import FindingSeverity, FindingType, QuestionStatus
from document_enhancer.domain.questions import Answer, AnswersArtifact, Waiver, WaiversArtifact


def _finding(
    finding_id: str,
    category: str,
    impact: str,
    *,
    severity: FindingSeverity = FindingSeverity.HIGH,
    blocking: bool = False,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        category=category,
        severity=severity,
        finding_type=FindingType.MISSING,
        evidence=[EvidenceQuote(span_id="SPAN-ABCDEF12", quote=impact)],
        impact=impact,
        proposed_disposition="ask the reviewer for the authoritative value",
        requires_human_answer=True,
        blocking=blocking,
    )


def test_question_synthesis_covers_governance_categories_and_deduplicates() -> None:
    findings = FindingSet(
        document_id="DOC-CLARIFICATION-001",
        source_digest="a" * 64,
        findings=[
            _finding(
                "F-CONTROL-001",
                "control",
                "the control owner is missing",
                severity=FindingSeverity.BLOCKER,
                blocking=True,
            ),
            _finding(
                "F-CONTROL-002",
                "control",
                "the control owner is not documented",
                severity=FindingSeverity.HIGH,
            ),
            _finding("F-CALC-001", "calculation", "threshold unit is unclear"),
            _finding("F-DEP-001", "dependency", "the source system dependency is missing"),
            _finding("F-EXC-001", "exception", "exception approval is unclear"),
            _finding("F-CONFLICT-001", "conflict", "two statements contradict each other"),
            _finding("F-AMB-001", "ambiguity", "the next step is vague"),
            _finding("F-STEER-001", "steering", "the target audience is not specified"),
        ],
        blocking_count=1,
    )
    result = synthesize_questions(findings, strict_blocking=True)
    artifact = result.questions
    categories = {question.category.value for question in artifact.questions}
    assert {
        "control",
        "calculation",
        "dependency",
        "exception",
        "conflict",
        "ambiguity",
        "steering",
    } <= categories
    assert result.semantic_duplicate_count >= 1
    assert len(artifact.questions) < len(findings.findings)
    assert result.blocking_question_ids
    assert all(question.proposed_safe_default is None for question in artifact.questions)
    assert all(
        dependency in {item.question_id for item in artifact.questions}
        for item in artifact.questions
        for dependency in item.depends_on_question_ids
    )
    assert render_questions_markdown(artifact) == render_questions_markdown(artifact)


def test_reviewer_validation_is_fail_closed_and_actionable() -> None:
    findings = FindingSet(
        document_id="DOC-CLARIFICATION-002",
        source_digest="b" * 64,
        findings=[
            _finding(
                "F-CONTROL-003",
                "control",
                "owner missing",
                severity=FindingSeverity.BLOCKER,
                blocking=True,
            )
        ],
        blocking_count=1,
    )
    questions = synthesize_questions(findings).questions
    empty = AnswersArtifact(document_id=questions.document_id)
    report = validate_answers(questions, empty, source_span_ids={"SPAN-ABCDEF12"})
    assert not report.valid
    assert any(item.code == "missing_required_answer" for item in report.errors)

    answer = AnswersArtifact(
        document_id=questions.document_id,
        answers=[
            Answer(
                answer_id="ANS-003",
                question_id=questions.questions[0].question_id,
                status=QuestionStatus.ANSWERED,
                answer="Role-Control-Owner",
                responder="reviewer@example.com",
                evidence_reference="answer://review/003",
            )
        ],
    )
    assert validate_answers(questions, answer, source_span_ids={"SPAN-ABCDEF12"}).valid

    checklist = build_rewrite_checklist(questions, answers=answer)
    assert checklist.items[0].question_id == questions.questions[0].question_id
    assert checklist.items[0].evidence[0].span_id == "SPAN-ABCDEF12"

    expired = WaiversArtifact(
        document_id=questions.document_id,
        waivers=[
            Waiver(
                waiver_id="WAIVER-003",
                target_id=questions.questions[0].question_id,
                reason="temporary exception",
                approver="approver@example.com",
                downstream_impact="control owner remains unresolved",
                expires_or_review_date=__import__("datetime").datetime(
                    2020, 1, 1, tzinfo=__import__("datetime").UTC
                ),
            )
        ],
    )
    waiver_report = validate_waivers(questions, expired)
    assert not waiver_report.valid
    assert any(item.code == "waiver_expired" for item in waiver_report.errors)


def test_artifact_digest_is_stored_without_changing_yaml_contract() -> None:
    findings = FindingSet(
        document_id="DOC-CLARIFICATION-003",
        source_digest="c" * 64,
        findings=[],
        blocking_count=0,
    )
    artifact = with_digest(synthesize_questions(findings).questions)
    assert artifact.digest and len(artifact.digest) == 64
