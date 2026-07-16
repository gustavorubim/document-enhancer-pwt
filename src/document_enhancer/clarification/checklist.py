"""Evidence-linked rewrite checklist construction."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from document_enhancer.domain.enums import ChecklistAction, QuestionCategory, QuestionStatus
from document_enhancer.domain.questions import (
    Answer,
    AnswersArtifact,
    ChecklistItem,
    Question,
    QuestionsArtifact,
    RewriteChecklist,
    Steering,
    WaiversArtifact,
)

from .rendering import render_checklist_markdown

_ACTION_BY_CATEGORY = {
    QuestionCategory.MISSING: ChecklistAction.ADD_FROM_ANSWER,
    QuestionCategory.AMBIGUITY: ChecklistAction.CLARIFY,
    QuestionCategory.CONFLICT: ChecklistAction.MERGE,
    QuestionCategory.VALIDATION: ChecklistAction.STRUCTURE,
    QuestionCategory.OWNERSHIP: ChecklistAction.ADD_FROM_ANSWER,
    QuestionCategory.CONTROL: ChecklistAction.STRUCTURE,
    QuestionCategory.CALCULATION: ChecklistAction.CLARIFY,
    QuestionCategory.DEPENDENCY: ChecklistAction.ADD_FROM_ANSWER,
    QuestionCategory.EXCEPTION: ChecklistAction.CLARIFY,
    QuestionCategory.STEERING: ChecklistAction.STRUCTURE,
}

_VERIFICATION_BY_CATEGORY = {
    QuestionCategory.MISSING: "Confirm the supplied fact is present in the target section and is linked to its answer provenance.",
    QuestionCategory.AMBIGUITY: "Review the rewritten wording against the cited source spans and the approved answer.",
    QuestionCategory.CONFLICT: "Confirm one authoritative statement remains and the conflict resolution is documented.",
    QuestionCategory.VALIDATION: "Run the named validation or testing procedure and retain its evidence reference.",
    QuestionCategory.OWNERSHIP: "Confirm each role/owner resolves to an explicit governed object or approved TBD/open issue.",
    QuestionCategory.CONTROL: "Confirm control objective, performer, frequency, evidence, failure response, and escalation are explicit.",
    QuestionCategory.CALCULATION: "Confirm formula/calculator, inputs, units, thresholds, validation, and fallback are all documented.",
    QuestionCategory.DEPENDENCY: "Confirm dependency owner, readiness condition, timing, failure impact, and fallback are explicit.",
    QuestionCategory.EXCEPTION: "Confirm exception authority, evidence, validity period, and recovery/escalation path are explicit.",
    QuestionCategory.STEERING: "Confirm the approved steering directive is applied and does not introduce unsupported facts.",
}


def _stable_checklist_id(document_id: str, questions: QuestionsArtifact) -> str:
    payload = {
        "document_id": document_id,
        "questions": [question.model_dump(mode="json") for question in questions.questions],
    }
    import json

    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"CHECK-{digest[:16].upper()}"


def _answer_for(question: Question, answers: AnswersArtifact | None) -> Answer | None:
    if answers is None:
        return None
    return next(
        (answer for answer in answers.answers if answer.question_id == question.question_id), None
    )


def _waiver_for(target_id: str, waivers: WaiversArtifact | None) -> str | None:
    if waivers is None:
        return None
    return next(
        (waiver.waiver_id for waiver in waivers.waivers if waiver.target_id == target_id), None
    )


def _item_for_question(
    question: Question,
    *,
    answers: AnswersArtifact | None,
    waivers: WaiversArtifact | None,
) -> ChecklistItem:
    answer = _answer_for(question, answers)
    waiver_id = _waiver_for(question.question_id, waivers)
    status = answer.status if answer is not None else QuestionStatus.OPEN
    if status is QuestionStatus.WAIVED and waiver_id is None:
        status = QuestionStatus.OPEN
    action = _ACTION_BY_CATEGORY[question.category]
    evidence = list(question.evidence)
    if answer is not None and answer.evidence_reference:
        # The answer's provenance remains represented by the answer_id and evidence_reference;
        # source quotes are intentionally not fabricated here.
        reason = f"Reviewer input {answer.answer_id} is {answer.status.value}; provenance={answer.evidence_reference}."
    else:
        reason = "No reviewer answer is available; keep the unresolved item visible."
    if waiver_id:
        reason = f"Waiver {waiver_id} governs this item until its review/expiry date."
    return ChecklistItem(
        checklist_item_id=f"CHK-{question.question_id.removeprefix('Q-')}",
        source_finding_id=question.source_finding_ids[0] if question.source_finding_ids else None,
        question_id=question.question_id,
        answer_id=answer.answer_id if answer else None,
        target_section_id=question.target_section_id,
        target_object_id=question.target_object_id,
        action=action,
        verification_method=_VERIFICATION_BY_CATEGORY[question.category],
        acceptance_criterion=(
            f"{question.category.value.capitalize()} issue is resolved with explicit authoritative content, "
            "provenance, and no invented value."
        ),
        blocking=question.blocking,
        status=status,
        waiver_id=waiver_id,
        reason=reason,
        evidence=evidence,
    )


def build_rewrite_checklist(
    questions: QuestionsArtifact,
    *,
    answers: AnswersArtifact | None = None,
    steering: Steering | None = None,
    waivers: WaiversArtifact | None = None,
    reference_rules: Sequence[Mapping[str, Any]] = (),
    audit_requirements: Sequence[str] = (),
) -> RewriteChecklist:
    """Build a reviewable checklist from questions and reviewer inputs.

    Steering, reference rules, and audit requirements are added as separate checklist items so
    a reviewer can distinguish requested direction from an answer to a missing fact.
    """

    items = [
        _item_for_question(question, answers=answers, waivers=waivers)
        for question in questions.questions
    ]
    if steering is not None and any(
        (
            steering.target_audience,
            steering.desired_tone,
            steering.terminology_preferences,
            steering.exclusions,
            steering.additional_requirements,
        )
    ):
        items.append(
            ChecklistItem(
                checklist_item_id=f"CHK-STEERING-{steering.steering_id.removeprefix('STEER-')}",
                steering_id=steering.steering_id,
                action=ChecklistAction.STRUCTURE,
                verification_method="Compare the rendered document with every steering directive and its provider.",
                acceptance_criterion="Approved steering is applied without changing authoritative facts or provenance.",
                blocking=False,
                status=QuestionStatus.ANSWERED,
                reason=f"Steering supplied by {steering.provided_by or 'unidentified reviewer'}.",
            )
        )
    for rule in sorted(reference_rules, key=lambda value: str(value.get("rule_id", ""))):
        rule_id = str(rule.get("rule_id", ""))
        if not rule_id:
            continue
        items.append(
            ChecklistItem(
                checklist_item_id=f"CHK-RULE-{rule_id}",
                reference_rule_id=rule_id,
                target_section_id=str(rule.get("target_section_id"))
                if rule.get("target_section_id")
                else None,
                action=ChecklistAction.STRUCTURE,
                verification_method="Check the target section against the selected reference-pack requirement.",
                acceptance_criterion=str(
                    rule.get(
                        "acceptance_criterion",
                        "Reference requirement is satisfied or explicitly waived.",
                    )
                ),
                blocking=bool(rule.get("blocking", True)),
                reason=str(rule.get("reason", "Reference-pack requirement.")),
            )
        )
    for requirement in sorted(set(audit_requirements)):
        digest = hashlib.sha256(requirement.encode("utf-8")).hexdigest()[:12].upper()
        items.append(
            ChecklistItem(
                checklist_item_id=f"CHK-AUDIT-{digest}",
                audit_requirement=requirement,
                action=ChecklistAction.STRUCTURE,
                verification_method="Run the deterministic audit check named by this requirement.",
                acceptance_criterion=requirement,
                blocking=True,
                reason="Independent audit requirement.",
            )
        )
    # The question order is already topological; the remaining namespaces are sorted to keep
    # repeated runs byte-stable.
    question_items = items[: len(questions.questions)]
    other_items = sorted(items[len(questions.questions) :], key=lambda item: item.checklist_item_id)
    checklist = RewriteChecklist(
        checklist_id=_stable_checklist_id(questions.document_id, questions),
        document_id=questions.document_id,
        items=[*question_items, *other_items],
    )
    return checklist


def checklist_markdown(checklist: RewriteChecklist) -> str:
    return render_checklist_markdown(checklist)


__all__ = ["build_rewrite_checklist", "checklist_markdown"]
