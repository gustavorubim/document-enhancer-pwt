"""Approved, section-scoped inputs for a governed rewrite pass."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import Field, StrictStr, field_validator, model_validator

from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.enums import QuestionStatus
from document_enhancer.domain.ids import ensure_unique_ids, validate_sha256, validate_span_id
from document_enhancer.domain.questions import (
    Answer,
    AnswersArtifact,
    ChecklistItem,
    ContentLedger,
    RewriteChecklist,
    Steering,
)


class ApprovedEvidence(StrictModel):
    evidence_id: StrictStr
    span_id: StrictStr
    quote: StrictStr
    source_digest: StrictStr
    target_section_id: StrictStr | None = None

    @field_validator("evidence_id")
    @classmethod
    def validate_evidence_id(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="evidence id")

    @field_validator("span_id")
    @classmethod
    def validate_evidence_span(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)

    @field_validator("quote")
    @classmethod
    def validate_quote(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="approved evidence quote")

    @field_validator("source_digest")
    @classmethod
    def validate_evidence_digest(cls, value: StrictStr) -> StrictStr:
        return validate_sha256(value)


class GovernedReference(StrictModel):
    """Reference metadata allowed into a rewrite input; template instructions are excluded."""

    reference_id: StrictStr
    kind: StrictStr
    title: StrictStr
    precedence: StrictStr
    digest: StrictStr | None = None
    approved_excerpt: StrictStr | None = None

    @field_validator("reference_id", "kind", "title", "precedence")
    @classmethod
    def validate_reference_fields(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="governed reference field")

    @field_validator("digest")
    @classmethod
    def validate_reference_digest(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else validate_sha256(value)


class SectionRewriteInput(StrictModel):
    """The only facts and controls a section rewrite is permitted to use."""

    section_id: StrictStr
    heading: StrictStr
    anchor: StrictStr
    source_digest: StrictStr
    source_evidence: list[ApprovedEvidence] = Field(default_factory=list)
    approved_answers: list[Answer] = Field(default_factory=list)
    steering: Steering | None = None
    checklist_items: list[ChecklistItem] = Field(default_factory=list)
    governed_references: list[GovernedReference] = Field(default_factory=list)
    allowed_source_span_ids: list[StrictStr] = Field(default_factory=list)
    allowed_answer_ids: list[StrictStr] = Field(default_factory=list)
    allowed_object_ids: list[StrictStr] = Field(default_factory=list)

    @field_validator("section_id", "heading", "anchor")
    @classmethod
    def validate_input_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="section rewrite input")

    @field_validator("source_digest")
    @classmethod
    def validate_input_digest(cls, value: StrictStr) -> StrictStr:
        return validate_sha256(value)

    @field_validator("allowed_source_span_ids")
    @classmethod
    def validate_input_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        return values

    @model_validator(mode="after")
    def validate_approved_scope(self) -> SectionRewriteInput:
        ensure_unique_ids(item.answer_id for item in self.approved_answers)
        ensure_unique_ids(item.checklist_item_id for item in self.checklist_items)
        if set(self.allowed_source_span_ids) != {item.span_id for item in self.source_evidence}:
            raise ValueError("allowed_source_span_ids must exactly match source_evidence")
        if set(self.allowed_answer_ids) != {item.answer_id for item in self.approved_answers}:
            raise ValueError("allowed_answer_ids must exactly match approved_answers")
        if any(item.status is not QuestionStatus.ANSWERED for item in self.approved_answers):
            raise ValueError("only answered reviewer inputs may enter a rewrite input")
        return self


def _value(item: object, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _span_map(normalized: object) -> tuple[str, str, str]:
    raw = _value(normalized, "raw")
    blocks = _value(normalized, "blocks") or _value(raw, "blocks")
    if not blocks:
        raise ValueError("normalized document has no source blocks")
    source_digest = str(_value(raw, "source_digest", _value(normalized, "source_digest", "")))
    return source_digest, "", ""


def build_rewrite_inputs(
    normalized: object,
    ledger: ContentLedger,
    *,
    sections: Sequence[Mapping[str, object]],
    answers: AnswersArtifact | None = None,
    steering: Steering | None = None,
    checklist: RewriteChecklist | None = None,
    governed_references: Sequence[GovernedReference] = (),
) -> list[SectionRewriteInput]:
    """Build section inputs from source spans plus explicitly approved human inputs only."""

    raw = _value(normalized, "raw")
    blocks = _value(normalized, "blocks") or _value(raw, "blocks")
    if not blocks:
        raise ValueError("normalized document has no source blocks")
    source_digest = str(_value(raw, "source_digest", _value(normalized, "source_digest", "")))
    if len(source_digest) != 64:
        raise ValueError("normalized document has no valid source digest")
    text_by_span = {
        str(_value(block, "source_span_id", _value(block, "span_id", ""))).upper(): str(
            _value(block, "text", "")
        )
        for block in blocks
    }
    section_specs = list(sections)
    answers_by_question = {item.question_id: item for item in (answers.answers if answers else ())}
    checklist_items = list(checklist.items) if checklist else []
    result: list[SectionRewriteInput] = []
    for raw_spec in section_specs:
        section_id = str(raw_spec.get("id", raw_spec.get("section_id", "")))
        heading = str(raw_spec.get("heading", raw_spec.get("title", section_id)))
        anchor = str(raw_spec.get("anchor", _slug(heading)))
        entries = [entry for entry in ledger.entries if entry.target_anchor == anchor]
        evidence = [
            ApprovedEvidence(
                evidence_id=f"EVD-{entry.source_span_id.removeprefix('SPAN-')}",
                span_id=entry.source_span_id,
                quote=text_by_span[entry.source_span_id],
                source_digest=source_digest,
                target_section_id=section_id,
            )
            for entry in entries
            if entry.disposition.value != "omitted" and entry.source_span_id in text_by_span
        ]
        evidence_span_ids = {item.span_id for item in evidence}
        section_checklist = [
            item
            for item in checklist_items
            if item.target_section_id == section_id
            or bool({quote.span_id for quote in item.evidence} & evidence_span_ids)
        ]
        approved_answers = [
            answer
            for answer in answers_by_question.values()
            if answer.status is QuestionStatus.ANSWERED
            and any(item.question_id == answer.question_id for item in section_checklist)
        ]
        result.append(
            SectionRewriteInput(
                section_id=section_id,
                heading=heading,
                anchor=anchor,
                source_digest=source_digest,
                source_evidence=evidence,
                approved_answers=approved_answers,
                steering=steering if steering and steering.provided_by else None,
                checklist_items=section_checklist,
                governed_references=list(governed_references),
                allowed_source_span_ids=sorted(evidence_span_ids),
                allowed_answer_ids=sorted(answer.answer_id for answer in approved_answers),
                allowed_object_ids=sorted(
                    object_id
                    for answer in approved_answers
                    for object_id in (item.id for item in answer.new_semantic_objects)
                ),
            )
        )
    return result


def _slug(value: str) -> str:
    tokens = [token.lower() for token in value.replace("/", " ").split() if token]
    return (
        "-".join("".join(char for char in token if char.isalnum()) for token in tokens) or "section"
    )


build_section_rewrite_inputs = build_rewrite_inputs


__all__ = [
    "ApprovedEvidence",
    "GovernedReference",
    "SectionRewriteInput",
    "build_rewrite_inputs",
    "build_section_rewrite_inputs",
]
