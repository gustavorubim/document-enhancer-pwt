"""Fail-closed validation for human answers, steering, waivers, and approvals."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime

from document_enhancer.domain.enums import QuestionStatus
from document_enhancer.domain.questions import (
    AnswersArtifact,
    Question,
    QuestionsArtifact,
    RewriteChecklist,
    Steering,
    WaiversArtifact,
)

from .models import ReviewerValidationReport, ValidationDiagnostic

_SPAN_RE = re.compile(r"^(?:SPAN|span)-[A-Za-z0-9_-]{8,64}$")
_PROVENANCE_RE = re.compile(r"^(?:answer|reference|source|steering|waiver)://[^\s]+$")


def _question_map(questions: QuestionsArtifact) -> dict[str, Question]:
    return {question.question_id: question for question in questions.questions}


def _answer_provenance_valid(value: str | None, source_span_ids: set[str]) -> bool:
    if not value:
        return False
    if value in source_span_ids:
        return True
    return bool(_SPAN_RE.fullmatch(value) or _PROVENANCE_RE.fullmatch(value))


def validate_answers(
    questions: QuestionsArtifact,
    answers: AnswersArtifact,
    *,
    waivers: WaiversArtifact | None = None,
    source_span_ids: Iterable[str] = (),
) -> ReviewerValidationReport:
    diagnostics: list[ValidationDiagnostic] = []
    question_by_id = _question_map(questions)
    known_spans = set(source_span_ids)
    seen: set[str] = set()
    for index, answer in enumerate(answers.answers):
        path = f"answers.answers[{index}]"
        question = question_by_id.get(answer.question_id)
        if answer.answer_id in seen:
            diagnostics.append(
                ValidationDiagnostic.error(
                    "duplicate_answer_id",
                    f"{path}.answer_id",
                    f"answer ID {answer.answer_id} is repeated",
                    remediation="Give each answer one stable answer ID.",
                )
            )
        seen.add(answer.answer_id)
        if question is None:
            diagnostics.append(
                ValidationDiagnostic.error(
                    "unknown_question",
                    f"{path}.question_id",
                    f"question {answer.question_id} is not present in questions.yaml",
                    remediation="Use an existing question_id or regenerate the question artifact.",
                )
            )
            continue
        if answer.status not in question.allowed_statuses:
            diagnostics.append(
                ValidationDiagnostic.error(
                    "status_not_allowed",
                    f"{path}.status",
                    f"status {answer.status.value!r} is not allowed for {answer.question_id}",
                    remediation="Choose one of the allowed statuses listed in questions.yaml.",
                    provenance=tuple(item.span_id for item in question.evidence),
                )
            )
        if answer.status is QuestionStatus.ANSWERED:
            if not answer.answer:
                diagnostics.append(
                    ValidationDiagnostic.error(
                        "missing_answer",
                        f"{path}.answer",
                        "answered questions require a non-empty answer",
                        remediation="Provide the authoritative answer or select not_applicable/deferred.",
                    )
                )
            if not answer.responder:
                diagnostics.append(
                    ValidationDiagnostic.error(
                        "missing_responder",
                        f"{path}.responder",
                        "answered questions require reviewer identity",
                        remediation="Set responder to the accountable reviewer or approver.",
                    )
                )
            if not _answer_provenance_valid(answer.evidence_reference, known_spans):
                diagnostics.append(
                    ValidationDiagnostic.error(
                        "missing_provenance",
                        f"{path}.evidence_reference",
                        "an answered question must point to a source span or explicit answer/reference URI",
                        remediation="Use SPAN-... or answer://..., reference://..., source://..., or steering://... .",
                        provenance=tuple(item.span_id for item in question.evidence),
                    )
                )
        elif answer.status is QuestionStatus.NOT_APPLICABLE:
            if not answer.responder:
                diagnostics.append(
                    ValidationDiagnostic.error(
                        "missing_responder",
                        f"{path}.responder",
                        "not_applicable requires reviewer identity",
                        remediation="Record who approved the not-applicable decision.",
                    )
                )
            if not answer.notes:
                diagnostics.append(
                    ValidationDiagnostic.error(
                        "missing_na_reason",
                        f"{path}.notes",
                        "not_applicable requires a reason",
                        remediation="Explain why the question does not apply.",
                    )
                )
        elif answer.status is QuestionStatus.DEFERRED and not answer.notes:
            diagnostics.append(
                ValidationDiagnostic.warning(
                    "deferred_without_plan",
                    f"{path}.notes",
                    "deferred input has no follow-up or owner",
                    remediation="Add the decision owner, due date, or reopening condition.",
                    provenance=tuple(item.span_id for item in question.evidence),
                )
            )
        elif answer.status is QuestionStatus.WAIVED:
            if waivers is None or not any(
                item.target_id == answer.question_id for item in waivers.waivers
            ):
                diagnostics.append(
                    ValidationDiagnostic.error(
                        "waiver_required",
                        f"{path}.status",
                        "waived answers require a matching waiver with reason, approver, and impact",
                        remediation="Add a waiver targeting this question or use another status.",
                    )
                )
    answered_question_ids = {answer.question_id for answer in answers.answers}
    for question in questions.questions:
        if question.blocking and question.question_id not in answered_question_ids:
            diagnostics.append(
                ValidationDiagnostic.error(
                    "missing_required_answer",
                    "answers.answers",
                    f"blocking question {question.question_id} has no answer entry",
                    remediation="Add an Answer with answered, not_applicable, or a governed waiver status.",
                    provenance=tuple(item.span_id for item in question.evidence),
                )
            )
    if answers.document_id != questions.document_id:
        diagnostics.append(
            ValidationDiagnostic.error(
                "document_mismatch",
                "answers.document_id",
                "answers document_id does not match questions document_id",
                remediation="Regenerate answers.yaml from the current questions artifact.",
            )
        )
    return ReviewerValidationReport(
        artifact_type="answers",
        valid=not any(item.severity == "error" for item in diagnostics),
        diagnostics=diagnostics,
        provenance={
            "document_id": questions.document_id,
            "question_count": len(questions.questions),
            "answer_count": len(answers.answers),
        },
    )


def validate_steering(
    questions: QuestionsArtifact,
    steering: Steering | None,
) -> ReviewerValidationReport:
    diagnostics: list[ValidationDiagnostic] = []
    if steering is None:
        return ReviewerValidationReport(artifact_type="steering", valid=True)
    if steering.document_id != questions.document_id:
        diagnostics.append(
            ValidationDiagnostic.error(
                "document_mismatch",
                "steering.document_id",
                "steering document_id does not match questions document_id",
                remediation="Use the document_id from questions.yaml.",
            )
        )
    directives = [
        steering.target_audience,
        steering.desired_tone,
        steering.document_type_override,
        steering.template_override,
        *steering.terminology_preferences.keys(),
        *steering.exclusions,
        *steering.confidentiality_constraints,
        *steering.additional_requirements,
    ]
    if any(value is not None and not str(value).strip() for value in directives):
        diagnostics.append(
            ValidationDiagnostic.error(
                "blank_directive",
                "steering",
                "steering contains a blank directive",
                remediation="Remove blank entries; do not use empty strings as answers.",
            )
        )
    if any(value for value in directives) and not steering.provided_by:
        diagnostics.append(
            ValidationDiagnostic.error(
                "missing_provenance",
                "steering.provided_by",
                "non-empty steering requires the identity of its provider",
                remediation="Set provided_by before resuming the workflow.",
            )
        )
    return ReviewerValidationReport(
        artifact_type="steering",
        valid=not any(item.severity == "error" for item in diagnostics),
        diagnostics=diagnostics,
        provenance={"document_id": questions.document_id, "provided_by": steering.provided_by},
    )


def validate_waivers(
    questions: QuestionsArtifact,
    waivers: WaiversArtifact,
    *,
    checklist: RewriteChecklist | None = None,
    now: datetime | None = None,
) -> ReviewerValidationReport:
    diagnostics: list[ValidationDiagnostic] = []
    known_targets = {question.question_id for question in questions.questions}
    if checklist is not None:
        known_targets.update(item.checklist_item_id for item in checklist.items)
    if waivers.document_id != questions.document_id:
        diagnostics.append(
            ValidationDiagnostic.error(
                "document_mismatch",
                "waivers.document_id",
                "waivers document_id does not match questions document_id",
                remediation="Use the document_id from questions.yaml.",
            )
        )
    now = now or datetime.now(UTC)
    seen: set[str] = set()
    for index, waiver in enumerate(waivers.waivers):
        path = f"waivers.waivers[{index}]"
        if waiver.waiver_id in seen:
            diagnostics.append(
                ValidationDiagnostic.error(
                    "duplicate_waiver_id",
                    f"{path}.waiver_id",
                    f"waiver ID {waiver.waiver_id} is repeated",
                    remediation="Give each waiver one stable waiver ID.",
                )
            )
        seen.add(waiver.waiver_id)
        if waiver.target_id not in known_targets:
            diagnostics.append(
                ValidationDiagnostic.error(
                    "unknown_waiver_target",
                    f"{path}.target_id",
                    f"waiver target {waiver.target_id} is not a question or checklist item",
                    remediation="Target a current blocking question or checklist item.",
                )
            )
        if waiver.expires_or_review_date is None:
            diagnostics.append(
                ValidationDiagnostic.warning(
                    "waiver_without_review_date",
                    f"{path}.expires_or_review_date",
                    "waiver has no expiry or review date",
                    remediation="Add a date for governed re-review.",
                )
            )
        elif waiver.expires_or_review_date < now:
            diagnostics.append(
                ValidationDiagnostic.error(
                    "waiver_expired",
                    f"{path}.expires_or_review_date",
                    "waiver expiry/review date is in the past",
                    remediation="Renew the waiver or resolve the target item.",
                )
            )
    return ReviewerValidationReport(
        artifact_type="waivers",
        valid=not any(item.severity == "error" for item in diagnostics),
        diagnostics=diagnostics,
        provenance={"document_id": questions.document_id, "waiver_count": len(waivers.waivers)},
    )


def validate_checklist_approval(
    checklist: RewriteChecklist,
    *,
    waivers: WaiversArtifact | None = None,
) -> ReviewerValidationReport:
    diagnostics: list[ValidationDiagnostic] = []
    waiver_ids = {item.waiver_id for item in (waivers.waivers if waivers else ())}
    if checklist.approved_by and checklist.approved_at is None:
        diagnostics.append(
            ValidationDiagnostic.error(
                "missing_approval_time",
                "checklist.approved_at",
                "approved checklist requires approved_at",
                remediation="Record the UTC approval timestamp.",
            )
        )
    if checklist.approved_at and not checklist.approved_by:
        diagnostics.append(
            ValidationDiagnostic.error(
                "missing_approver",
                "checklist.approved_by",
                "approved_at requires approved_by",
                remediation="Record the reviewer who approved the checklist.",
            )
        )
    for index, item in enumerate(checklist.items):
        if item.blocking and item.status in {QuestionStatus.OPEN, QuestionStatus.DEFERRED}:
            diagnostics.append(
                ValidationDiagnostic.error(
                    "unresolved_blocking_item",
                    f"checklist.items[{index}].status",
                    f"blocking checklist item {item.checklist_item_id} is unresolved",
                    remediation="Resolve it, set a valid waiver_id, or do not approve gate 2.",
                    provenance=tuple(evidence.span_id for evidence in item.evidence),
                )
            )
        if item.status is QuestionStatus.WAIVED and item.waiver_id not in waiver_ids:
            diagnostics.append(
                ValidationDiagnostic.error(
                    "missing_checklist_waiver",
                    f"checklist.items[{index}].waiver_id",
                    f"waived item {item.checklist_item_id} has no matching waiver",
                    remediation="Add the waiver to waivers.yaml before approval.",
                )
            )
    return ReviewerValidationReport(
        artifact_type="rewrite-checklist",
        valid=not any(item.severity == "error" for item in diagnostics),
        diagnostics=diagnostics,
        provenance={"document_id": checklist.document_id, "item_count": len(checklist.items)},
    )


def validate_reviewer_inputs(
    questions: QuestionsArtifact,
    answers: AnswersArtifact,
    steering: Steering | None,
    waivers: WaiversArtifact,
    *,
    source_span_ids: Iterable[str] = (),
    checklist: RewriteChecklist | None = None,
) -> ReviewerValidationReport:
    reports = [
        validate_answers(questions, answers, waivers=waivers, source_span_ids=source_span_ids),
        validate_steering(questions, steering),
        validate_waivers(questions, waivers, checklist=checklist),
    ]
    if checklist is not None:
        reports.append(validate_checklist_approval(checklist, waivers=waivers))
    diagnostics = [item for report in reports for item in report.diagnostics]
    return ReviewerValidationReport(
        artifact_type="reviewer-inputs",
        valid=not any(item.severity == "error" for item in diagnostics),
        diagnostics=diagnostics,
        provenance={
            "document_id": questions.document_id,
            "reports": [report.artifact_type for report in reports],
        },
    )


__all__ = [
    "validate_answers",
    "validate_checklist_approval",
    "validate_reviewer_inputs",
    "validate_steering",
    "validate_waivers",
]
