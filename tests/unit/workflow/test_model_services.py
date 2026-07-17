from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from document_enhancer.clarification import build_rewrite_checklist, synthesize_questions
from document_enhancer.domain.analysis import EvidenceQuote, Finding, FindingSet
from document_enhancer.domain.enums import (
    DocumentType,
    FindingSeverity,
    FindingType,
    QuestionStatus,
)
from document_enhancer.domain.questions import (
    Answer,
    AnswersArtifact,
    QuestionsArtifact,
    Steering,
    WaiversArtifact,
)
from document_enhancer.errors import ValidationError
from document_enhancer.ingest.pipeline import ingest_source
from document_enhancer.llm import GeminiModelGateway
from document_enhancer.prompting import PromptPackComposer, load_prompt_pack
from document_enhancer.references.loader import load_reference_pack
from document_enhancer.workflow.model_services import (
    GeminiChecklistGenerator,
    GeminiQuestionGenerator,
    build_question_prompt_input,
)

ROOT = Path(__file__).resolve().parents[3]
PROMPT_ROOT = ROOT / "prompt_packs/gemini_core"
REFERENCE_ROOT = ROOT / "reference_packs/enterprise_core"


class _CapturingGateway:
    def __init__(self, artifact: object) -> None:
        self.artifact = artifact
        self.calls: list[dict[str, Any]] = []

    def invoke(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        artifact = self.artifact
        promote = kwargs.get("promote")
        if callable(promote):
            artifact = promote(artifact)
        return SimpleNamespace(artifact=artifact)


def _composer(document_type: str = "process") -> PromptPackComposer:
    references = load_reference_pack(REFERENCE_ROOT)
    return PromptPackComposer(
        load_prompt_pack(PROMPT_ROOT, reference_pack=references),
        reference_pack=references,
        document_type=document_type,
    )


def _finding_set(span_id: str) -> FindingSet:
    finding = Finding(
        finding_id="F-CONTEXT-001",
        category="control",
        severity=FindingSeverity.BLOCKER,
        finding_type=FindingType.MISSING,
        evidence=[EvidenceQuote(span_id=span_id, quote="The control owner is absent.")],
        target_template_section="SEC-PROC-CONTROLS",
        requirement_id="COM-CONTROL-001",
        impact="Accountable control execution cannot be established.",
        proposed_disposition="Ask the reviewer for the approved control owner.",
        requires_human_answer=True,
        blocking=True,
    )
    return FindingSet(
        document_id="DOC-STAGE-CONTEXT-001",
        source_digest="a" * 64,
        findings=[finding],
        blocking_count=1,
    )


def test_question_generator_sends_baseline_and_referenced_findings_not_full_fanout_or_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "messy.md"
    source.write_text(
        "# Control review\n\nThe control owner is absent.\n\n"
        "FULL-SOURCE-MUST-NOT-REACH-QUESTION-CALL\n",
        encoding="utf-8",
    )
    normalized = ingest_source(source)
    findings = _finding_set(normalized.raw.blocks[1].span_id)
    baseline = synthesize_questions(
        findings,
        document_id="DOC-STAGE-CONTEXT-001",
        strict_blocking=True,
    ).questions
    analysis_result = SimpleNamespace(
        synthesis=SimpleNamespace(finding_set=findings),
        branches=("FULL-ANALYSIS-FANOUT-MUST-NOT-REACH-QUESTION-CALL",),
    )
    gateway = _CapturingGateway(baseline)

    generated = GeminiQuestionGenerator(_composer(), cast(GeminiModelGateway, gateway)).generate(
        baseline=baseline,
        analysis_result=analysis_result,
        normalized=normalized,
        document_type=DocumentType.PROCESS,
    )

    assert generated == baseline
    call = gateway.calls[0]
    prompt = cast(str, call["prompt"])
    assert '"baseline_questions"' in prompt
    assert "F-CONTEXT-001" in prompt
    assert "The control owner is absent." in prompt
    assert "FULL-SOURCE-MUST-NOT-REACH-QUESTION-CALL" not in prompt
    assert "FULL-ANALYSIS-FANOUT-MUST-NOT-REACH-QUESTION-CALL" not in prompt
    assert "[INPUT name=source_text" not in prompt
    assert call["prompt_version"] == "1.1.4"
    input_digests = cast(tuple[str, ...], call["input_digests"])
    assert input_digests[0] == normalized.raw.source_digest
    assert len(input_digests) == 2
    assert all(len(digest) == 64 for digest in input_digests)


def test_checklist_generator_rejects_unknown_baseline_item() -> None:
    findings = _finding_set("SPAN-ABCDEF12")
    questions = synthesize_questions(
        findings,
        document_id="DOC-STAGE-CONTEXT-001",
        strict_blocking=True,
    ).questions
    baseline = build_rewrite_checklist(
        questions,
        answers=AnswersArtifact(document_id=questions.document_id),
        steering=None,
        waivers=WaiversArtifact(document_id=questions.document_id),
    )
    proposal = {
        "items": [
            {
                "item_key": "CHK-UNKNOWN-001",
                "action": baseline.items[0].action.value,
                "verification_method": baseline.items[0].verification_method,
                "acceptance_criterion": baseline.items[0].acceptance_criterion,
                "reason": baseline.items[0].reason,
            }
        ]
    }

    with pytest.raises(ValidationError, match="unknown baseline item"):
        GeminiChecklistGenerator(
            _composer(), cast(GeminiModelGateway, _CapturingGateway(proposal))
        ).generate(
            baseline=baseline,
            questions=questions,
            answers=AnswersArtifact(document_id=questions.document_id),
            steering=None,
            waivers=WaiversArtifact(document_id=questions.document_id),
            document_type=DocumentType.PROCESS,
        )


def test_question_prompt_input_excludes_unrelated_analysis_fanout(tmp_path: Path) -> None:
    source = tmp_path / "messy.md"
    source.write_text("# Control review\n\nThe control owner is absent.\n", encoding="utf-8")
    normalized = ingest_source(source)
    findings = _finding_set(normalized.raw.blocks[1].span_id)
    baseline = synthesize_questions(
        findings,
        document_id="DOC-STAGE-CONTEXT-001",
        strict_blocking=True,
    ).questions

    prompt_input = build_question_prompt_input(
        baseline,
        {"finding_set": findings, "unrelated_analysis_fanout": "x" * 100_000},
    )

    encoded = json.dumps(prompt_input, sort_keys=True)
    assert len(encoded) < 40_000
    assert "unrelated_analysis_fanout" not in encoded


def test_question_generator_rejects_evidence_outside_deterministic_baseline(
    tmp_path: Path,
) -> None:
    source = tmp_path / "messy.md"
    source.write_text("# Control review\n\nThe control owner is absent.\n", encoding="utf-8")
    normalized = ingest_source(source)
    findings = _finding_set(normalized.raw.blocks[1].span_id)
    baseline = synthesize_questions(
        findings,
        document_id="DOC-STAGE-CONTEXT-001",
        strict_blocking=True,
    ).questions
    invalid_question = baseline.questions[0].model_copy(
        update={
            "evidence": [
                baseline.questions[0]
                .evidence[0]
                .model_copy(update={"quote": "provider-invented quote"})
            ]
        }
    )
    invalid = baseline.model_copy(update={"questions": [invalid_question]})

    with pytest.raises(ValidationError, match="outside the deterministic baseline"):
        GeminiQuestionGenerator(
            _composer(), cast(GeminiModelGateway, _CapturingGateway(invalid))
        ).generate(
            baseline=baseline,
            analysis_result=SimpleNamespace(synthesis=SimpleNamespace(finding_set=findings)),
            normalized=normalized,
            document_type=DocumentType.PROCESS,
        )


def test_checklist_generator_sends_governed_seed_summaries_and_compact_reviewer_artifacts() -> None:
    findings = _finding_set("SPAN-ABCDEF12")
    original = synthesize_questions(
        findings,
        document_id="DOC-STAGE-CONTEXT-001",
        strict_blocking=True,
    ).questions
    question = original.questions[0].model_copy(
        update={"examples": ["REDUNDANT-QUESTION-EXAMPLE-MUST-NOT-BE-SENT"]}
    )
    questions = QuestionsArtifact(
        document_id=original.document_id,
        version_id=original.version_id,
        questions=[question],
    )
    answers = AnswersArtifact(
        document_id=questions.document_id,
        answers=[
            Answer(
                answer_id="ANS-CONTEXT-001",
                question_id=question.question_id,
                status=QuestionStatus.ANSWERED,
                answer="ROLE-CONTROL-OWNER is approved.",
                responder="reviewer@example.invalid",
                evidence_reference="review://context/001",
            )
        ],
    )
    steering = Steering(
        steering_id="STEER-CONTEXT-001",
        document_id=questions.document_id,
        additional_requirements=["Keep the control wording concise."],
        provided_by="reviewer@example.invalid",
    )
    waivers = WaiversArtifact(document_id=questions.document_id)
    baseline = build_rewrite_checklist(
        questions,
        answers=answers,
        steering=steering,
        waivers=waivers,
    )
    gateway = _CapturingGateway(
        {
            "items": [
                {
                    "item_key": item.checklist_item_id,
                    "action": item.action.value,
                    "verification_method": item.verification_method,
                    "acceptance_criterion": item.acceptance_criterion,
                    "reason": item.reason,
                }
                for item in baseline.items
            ]
        }
    )

    generated = GeminiChecklistGenerator(_composer(), cast(GeminiModelGateway, gateway)).generate(
        baseline=baseline,
        questions=questions,
        answers=answers,
        steering=steering,
        waivers=waivers,
        document_type=DocumentType.PROCESS,
    )

    assert generated == baseline
    call = gateway.calls[0]
    prompt = cast(str, call["prompt"])
    assert '"baseline_checklist"' in prompt
    assert '"question_summaries"' in prompt
    assert baseline.checklist_id in prompt
    assert question.question_id in prompt
    assert "ANS-CONTEXT-001" in prompt
    assert "Keep the control wording concise." in prompt
    assert "REDUNDANT-QUESTION-EXAMPLE-MUST-NOT-BE-SENT" not in prompt
    assert call["prompt_version"] == "1.1.4"
    input_digests = cast(tuple[str, ...], call["input_digests"])
    assert len(input_digests) == 2
    assert all(len(digest) == 64 for digest in input_digests)
