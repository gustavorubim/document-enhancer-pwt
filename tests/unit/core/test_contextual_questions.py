"""Contextual review questions must be evidence-linked and fail closed."""

from __future__ import annotations

import pytest

from document_enhancer.core.models import (
    FigureOccurrence,
    Question,
    ReviewReport,
    Section,
    SourceFigure,
    SourceSpan,
)
from document_enhancer.core.review import build_review, merge_provider_review
from document_enhancer.ingest.models import RawBlock, SourceLocation


def _block(
    span_id: str,
    ordinal: int,
    text: str,
    *,
    block_type: str = "paragraph",
    start: int = 0,
) -> RawBlock:
    return RawBlock(
        span_id=span_id,
        ordinal=ordinal,
        block_type=block_type,
        text=text,
        location=SourceLocation(
            kind="markdown",
            line_start=ordinal + 1,
            line_end=ordinal + 1,
            char_start=start,
            char_end=start + len(text),
        ),
        content_digest="a" * 64,
    )


def _span(span_id: str, ordinal: int) -> SourceSpan:
    return SourceSpan(
        span_id=span_id,
        start=ordinal,
        end=ordinal + 1,
        line_start=ordinal + 1,
        line_end=ordinal + 1,
        sha256="a" * 64,
    )


def _figure(span_id: str = "span-2") -> SourceFigure:
    return SourceFigure(
        figure_id="FIG-001",
        asset_id="asset-1",
        name="source.png",
        media_type="image/png",
        sha256="b" * 64,
        size_bytes=1,
        source_path="assets/source/FIG-001.png",
        occurrences=[
            FigureOccurrence(
                source_span_id=span_id,
                section_id="section-intake",
                ordinal=1,
            )
        ],
    )


def test_question_contract_requires_explicit_safe_suggestion_basis() -> None:
    supported = Question(
        question_id="q-supported",
        prompt="Which cited wording should be retained?",
        reason="The source contains two supported phrasings.",
        context="Whole-document context: both phrasings appear in the control section.",
        evidence_span_ids=["span-1"],
        figure_ids=["FIG-001"],
        suggestion="Use the wording in the cited source span.",
        suggestion_basis="source_supported",
    )

    assert supported.suggestion_basis == "source_supported"
    assert supported.evidence_figure_ids == ["FIG-001"]

    # Legacy/unclassified provider text and plausible invented recipe values are
    # absent rather than being promoted as safe suggestions.
    unclassified = Question(
        question_id="q-unsafe",
        prompt="What should be supplied?",
        reason="The source is incomplete.",
        suggestion="Set the approval threshold to 10 minutes.",
    )
    unsafe_guidance = Question(
        question_id="q-unsafe-guidance",
        prompt="What should be supplied?",
        reason="The source is incomplete.",
        suggestion="Set the approval threshold to 10 minutes.",
        suggestion_basis="recipe_guidance",
    )
    for question in (unclassified, unsafe_guidance):
        assert question.suggestion is None
        assert question.suggestion_basis == "none"

    with pytest.raises(ValueError, match="suggestion_basis"):
        Question(
            question_id="q-invalid",
            prompt="What should be supplied?",
            reason="The source is incomplete.",
            suggestion_basis="source_supported",
        )


def test_cross_section_contradictions_become_one_evidence_linked_question() -> None:
    blocks = (
        _block("span-1", 0, "# Intake", block_type="heading", start=0),
        _block(
            "span-2",
            1,
            "The review must be completed within 60 minutes.",
            start=10,
        ),
        _block("span-3", 2, "# Controls", block_type="heading", start=65),
        _block(
            "span-4",
            3,
            "The review must be completed within 30 minutes.",
            start=76,
        ),
    )
    sections = [
        Section(
            section_id="section-intake", title="Intake", level=1, span_ids=["span-1", "span-2"]
        ),
        Section(
            section_id="section-controls", title="Controls", level=1, span_ids=["span-3", "span-4"]
        ),
    ]

    review = build_review(
        blocks=blocks,
        source_spans=[_span(item.span_id, item.ordinal) for item in blocks],
        sections=sections,
        recipe=None,
        figures=[_figure()],
    )

    questions = [
        item for item in review.questions if item.question_id == "question-open-points-001"
    ]
    assert len(questions) == 1
    question = questions[0]
    assert question.blocking is True
    assert question.evidence_span_ids == ["span-2", "span-4"]
    assert question.figure_ids == ["FIG-001"]
    assert "Intake" in question.context
    assert "Controls" in question.context
    assert "60 minutes" in question.context
    assert "30 minutes" in question.context
    assert question.suggestion_basis == "recipe_guidance"
    assert question.suggestion is not None
    assert "60" not in question.suggestion
    assert "30" not in question.suggestion


def test_cross_section_authority_contradiction_is_consolidated() -> None:
    blocks = (
        _block("span-1", 0, "# Intake", block_type="heading", start=0),
        _block("span-2", 1, "The request is approved by Operations.", start=10),
        _block("span-3", 2, "# Escalation", block_type="heading", start=52),
        _block("span-4", 3, "The request is approved by Compliance.", start=65),
    )
    sections = [
        Section(
            section_id="section-intake", title="Intake", level=1, span_ids=["span-1", "span-2"]
        ),
        Section(
            section_id="section-escalation",
            title="Escalation",
            level=1,
            span_ids=["span-3", "span-4"],
        ),
    ]

    review = build_review(
        blocks=blocks,
        source_spans=[_span(item.span_id, item.ordinal) for item in blocks],
        sections=sections,
        recipe=None,
    )

    questions = [
        item for item in review.questions if item.question_id == "question-open-points-001"
    ]
    assert len(questions) == 1
    assert questions[0].evidence_span_ids == ["span-2", "span-4"]
    assert "Operations" in questions[0].context
    assert "Compliance" in questions[0].context


def test_placeholder_question_has_context_and_no_unsupported_suggestion() -> None:
    blocks = (
        _block("span-1", 0, "# Approval", block_type="heading", start=0),
        _block("span-2", 1, "Status: TBD", start=12),
    )
    sections = [
        Section(
            section_id="section-approval", title="Approval", level=1, span_ids=["span-1", "span-2"]
        )
    ]

    review = build_review(
        blocks=blocks,
        source_spans=[_span(item.span_id, item.ordinal) for item in blocks],
        sections=sections,
        recipe=None,
    )

    question = next(
        item for item in review.questions if item.question_id == "question-placeholder-001"
    )
    assert question.context.startswith("Whole-document context:")
    assert question.evidence_span_ids == ["span-2"]
    assert question.section_id == "section-approval"
    assert question.suggestion is None
    assert question.suggestion_basis == "none"


def test_provider_questions_filter_evidence_and_demote_unsupported_basis() -> None:
    base = ReviewReport(
        summary="base",
        sections=[Section(section_id="section-a", title="A", level=1, span_ids=["span-1"])],
    )
    candidate = ReviewReport(
        summary="provider",
        questions=[
            Question(
                question_id="provider-supported",
                prompt="Which wording is supported?",
                reason="The provider found a source-backed alternative.",
                evidence_span_ids=["span-1", "unknown"],
                figure_ids=["FIG-001", "FIG-999"],
                suggestion="Use the cited source wording.",
                suggestion_basis="source_supported",
            ),
            Question(
                question_id="provider-unrooted",
                prompt="What value should be used?",
                reason="The provider did not cite source evidence.",
                suggestion="Use a threshold of 5 days.",
                suggestion_basis="recipe_guidance",
            ),
        ],
    )

    merged = merge_provider_review(
        base,
        candidate,
        allowed_span_ids={"span-1"},
        allowed_figure_ids={"FIG-001"},
    )

    supported = next(item for item in merged.questions if item.question_id == "provider-supported")
    assert supported.evidence_span_ids == ["span-1"]
    assert supported.figure_ids == ["FIG-001"]
    assert supported.context.startswith("Whole-document context:")

    unrooted = next(item for item in merged.questions if item.question_id == "provider-unrooted")
    assert unrooted.suggestion is None
    assert unrooted.suggestion_basis == "none"
