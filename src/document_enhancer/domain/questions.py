"""Human clarification, steering, waiver, checklist, and ledger artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import Field, StrictBool, StrictStr, field_validator, model_validator

from document_enhancer.domain.analysis import EvidenceQuote
from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.enums import (
    ChecklistAction,
    LedgerDisposition,
    QuestionCategory,
    QuestionPriority,
    QuestionStatus,
)
from document_enhancer.domain.ids import ensure_unique_ids, validate_identifier, validate_span_id
from document_enhancer.domain.ontology import SemanticObject


class Question(StrictModel):
    question_id: StrictStr
    category: QuestionCategory
    priority: QuestionPriority
    blocking: StrictBool
    question: StrictStr
    why_it_matters: StrictStr
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    source_finding_ids: list[StrictStr] = Field(default_factory=list)
    target_section_id: StrictStr | None = None
    target_object_id: StrictStr | None = None
    expected_answer_shape: StrictStr | None = None
    examples: list[StrictStr] = Field(default_factory=list)
    allowed_statuses: list[QuestionStatus] = Field(
        default_factory=lambda: [
            QuestionStatus.ANSWERED,
            QuestionStatus.DEFERRED,
            QuestionStatus.NOT_APPLICABLE,
            QuestionStatus.WAIVED,
        ]
    )
    depends_on_question_ids: list[StrictStr] = Field(default_factory=list)
    proposed_safe_default: StrictStr | None = None

    @field_validator("question_id")
    @classmethod
    def validate_question_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="question id")

    @field_validator("question", "why_it_matters", "expected_answer_shape", "proposed_safe_default")
    @classmethod
    def validate_question_text(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="question text")

    @field_validator("source_finding_ids")
    @classmethod
    def validate_finding_ids(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_identifier(value, label="source finding id")
        return values


class Answer(StrictModel):
    answer_id: StrictStr
    question_id: StrictStr
    status: QuestionStatus
    answer: StrictStr | None = None
    responder: StrictStr | None = None
    answered_at: datetime | None = None
    evidence_reference: StrictStr | None = None
    new_semantic_objects: list[SemanticObject] = Field(default_factory=list)
    notes: StrictStr | None = None

    @field_validator("answer_id", "question_id")
    @classmethod
    def validate_answer_ids(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="answer identifier")

    @field_validator("answer", "responder", "evidence_reference", "notes")
    @classmethod
    def validate_optional_text(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="answer field")

    @model_validator(mode="after")
    def validate_answer_state(self) -> Answer:
        if self.status is QuestionStatus.ANSWERED and not self.answer:
            raise ValueError("answered questions require an answer")
        if self.status in {QuestionStatus.ANSWERED, QuestionStatus.WAIVED} and not self.responder:
            raise ValueError("answered or waived questions require responder")
        if self.answered_at is None and self.status is not QuestionStatus.DEFERRED:
            object.__setattr__(self, "answered_at", datetime.now(UTC))
        return self


class AnswersArtifact(StrictModel):
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    version_id: StrictStr | None = Field(default=None, pattern=r"^(DOCV|VER)-[A-Z0-9-]+$")
    answers: list[Answer] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    digest: StrictStr | None = None

    @model_validator(mode="after")
    def validate_answer_ids_unique(self) -> AnswersArtifact:
        ensure_unique_ids(answer.answer_id for answer in self.answers)
        return self


class QuestionsArtifact(StrictModel):
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    version_id: StrictStr | None = Field(default=None, pattern=r"^(DOCV|VER)-[A-Z0-9-]+$")
    questions: list[Question] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    digest: StrictStr | None = None

    @model_validator(mode="after")
    def validate_question_ids_unique(self) -> QuestionsArtifact:
        ensure_unique_ids(question.question_id for question in self.questions)
        return self


class Steering(StrictModel):
    steering_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    target_audience: StrictStr | None = None
    desired_tone: StrictStr | None = None
    permitted_restructuring: StrictBool | None = None
    terminology_preferences: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    document_type_override: StrictStr | None = None
    template_override: StrictStr | None = None
    exclusions: list[StrictStr] = Field(default_factory=list)
    confidentiality_constraints: list[StrictStr] = Field(default_factory=list)
    additional_requirements: list[StrictStr] = Field(default_factory=list)
    provided_by: StrictStr | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("steering_id")
    @classmethod
    def validate_steering_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="steering id")

    @field_validator(
        "target_audience",
        "desired_tone",
        "document_type_override",
        "template_override",
        "provided_by",
    )
    @classmethod
    def validate_steering_text(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="steering field")


class Waiver(StrictModel):
    waiver_id: StrictStr
    target_id: StrictStr
    reason: StrictStr
    approver: StrictStr
    expires_or_review_date: datetime | None = None
    downstream_impact: StrictStr
    status: QuestionStatus = QuestionStatus.WAIVED

    @field_validator("waiver_id", "target_id")
    @classmethod
    def validate_waiver_ids(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="waiver identifier")

    @field_validator("reason", "approver", "downstream_impact")
    @classmethod
    def validate_waiver_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="waiver field")


class WaiversArtifact(StrictModel):
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    waivers: list[Waiver] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    digest: StrictStr | None = None

    @model_validator(mode="after")
    def validate_waiver_ids_unique(self) -> WaiversArtifact:
        ensure_unique_ids(waiver.waiver_id for waiver in self.waivers)
        return self


class ChecklistItem(StrictModel):
    checklist_item_id: StrictStr
    source_finding_id: StrictStr | None = None
    question_id: StrictStr | None = None
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    answer_id: StrictStr | None = None
    steering_id: StrictStr | None = None
    reference_rule_id: StrictStr | None = None
    audit_requirement: StrictStr | None = None
    target_section_id: StrictStr | None = None
    target_object_id: StrictStr | None = None
    action: ChecklistAction
    verification_method: StrictStr
    acceptance_criterion: StrictStr
    blocking: StrictBool
    status: QuestionStatus = QuestionStatus.OPEN
    waiver_id: StrictStr | None = None
    reason: StrictStr | None = None

    @field_validator("checklist_item_id")
    @classmethod
    def validate_checklist_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="checklist item id")

    @field_validator("verification_method", "acceptance_criterion", "reason")
    @classmethod
    def validate_checklist_text(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="checklist field")

    @model_validator(mode="after")
    def validate_basis(self) -> ChecklistItem:
        if not any(
            value is not None
            for value in (
                self.source_finding_id,
                self.question_id,
                self.answer_id,
                self.steering_id,
                self.reference_rule_id,
                self.audit_requirement,
            )
        ):
            raise ValueError(
                "checklist item requires a finding, question, answer, steering, rule, or audit basis"
            )
        if self.status is QuestionStatus.WAIVED and not self.waiver_id:
            raise ValueError("waived checklist items require waiver_id")
        return self


class RewriteChecklist(StrictModel):
    checklist_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    items: list[ChecklistItem] = Field(default_factory=list)
    approved_by: StrictStr | None = None
    approved_at: datetime | None = None
    digest: StrictStr | None = None

    @field_validator("checklist_id")
    @classmethod
    def validate_checklist_identifier(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="checklist id")

    @model_validator(mode="after")
    def validate_item_ids(self) -> RewriteChecklist:
        ensure_unique_ids(item.checklist_item_id for item in self.items)
        return self

    @property
    def unresolved_blocking_items(self) -> tuple[ChecklistItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.blocking and item.status in {QuestionStatus.OPEN, QuestionStatus.DEFERRED}
        )

    def assert_ready(self) -> None:
        if self.unresolved_blocking_items:
            ids = ", ".join(item.checklist_item_id for item in self.unresolved_blocking_items)
            raise ValueError(f"rewrite checklist has unresolved blocking items: {ids}")


class ContentLedgerEntry(StrictModel):
    ledger_entry_id: StrictStr
    source_span_id: StrictStr
    disposition: LedgerDisposition
    target_anchor: StrictStr | None = None
    target_object_ids: list[StrictStr] = Field(default_factory=list)
    rationale: StrictStr
    evidence_ids: list[StrictStr] = Field(default_factory=list)
    omitted_reason: StrictStr | None = None
    source_text_digest: StrictStr | None = None
    source_ordinal: int | None = Field(default=None, ge=0)

    @field_validator("ledger_entry_id")
    @classmethod
    def validate_ledger_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="ledger entry id")

    @field_validator("source_span_id")
    @classmethod
    def validate_ledger_span(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)

    @field_validator("rationale", "omitted_reason")
    @classmethod
    def validate_ledger_text(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="ledger field")

    @model_validator(mode="after")
    def validate_omission(self) -> ContentLedgerEntry:
        if self.disposition is LedgerDisposition.OMITTED and not self.omitted_reason:
            raise ValueError("omitted ledger entries require omitted_reason")
        return self


class ContentLedger(StrictModel):
    ledger_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    entries: list[ContentLedgerEntry]
    complete: StrictBool
    digest: StrictStr | None = None

    @field_validator("ledger_id")
    @classmethod
    def validate_ledger_identifier(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="ledger id")

    @model_validator(mode="after")
    def validate_entries(self) -> ContentLedger:
        ensure_unique_ids(entry.ledger_entry_id for entry in self.entries)
        if not self.entries and self.complete:
            raise ValueError("a complete content ledger must contain entries")
        return self

    def coverage_errors(self, source_span_ids: Iterable[str]) -> tuple[str, ...]:
        """Return deterministic one-disposition-per-span coverage diagnostics."""

        expected = tuple(validate_span_id(str(span_id)) for span_id in source_span_ids)
        expected_set = set(expected)
        seen: dict[str, int] = {}
        errors: list[str] = []
        for entry in self.entries:
            seen[entry.source_span_id] = seen.get(entry.source_span_id, 0) + 1
        duplicate_ids = sorted(span_id for span_id, count in seen.items() if count != 1)
        missing = sorted(expected_set - set(seen))
        unexpected = sorted(set(seen) - expected_set)
        if duplicate_ids:
            errors.append("duplicate dispositions: " + ", ".join(duplicate_ids))
        if missing:
            errors.append("missing dispositions: " + ", ".join(missing))
        if unexpected:
            errors.append("unexpected source spans: " + ", ".join(unexpected))
        if len(expected) != len(expected_set):
            errors.append("source span input contains duplicate IDs")
        return tuple(errors)

    def assert_coverage(self, source_span_ids: Iterable[str]) -> None:
        errors = self.coverage_errors(source_span_ids)
        if errors:
            raise ValueError("content ledger coverage failed: " + "; ".join(errors))


QuestionArtifact = QuestionsArtifact
AnswerArtifact = AnswersArtifact
SteeringArtifact = Steering
WaiverArtifact = WaiversArtifact
ChecklistArtifact = RewriteChecklist
ContentLedgerArtifact = ContentLedger


__all__ = [
    "Answer",
    "AnswerArtifact",
    "AnswersArtifact",
    "ChecklistItem",
    "ContentLedger",
    "ContentLedgerEntry",
    "ContentLedgerArtifact",
    "Question",
    "QuestionArtifact",
    "QuestionsArtifact",
    "RewriteChecklist",
    "Steering",
    "SteeringArtifact",
    "Waiver",
    "WaiverArtifact",
    "WaiversArtifact",
    "ChecklistArtifact",
]
