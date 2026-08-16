"""Focused acceptance tests for the renderer-only draft-first reviewer seam."""

from __future__ import annotations

import re

import pytest

from document_enhancer.core.html_report import render_html_report
from document_enhancer.core.models import (
    AuditReport,
    FigureOccurrence,
    Question,
    ReviewReport,
    RunRecord,
    SectionAssessment,
    SourceFigure,
)
from document_enhancer.core.transformation import (
    DraftSection,
    Gap,
    SourceDisposition,
    TransformationBundle,
    TransformationQuestion,
    VisualExtraction,
    VisualReference,
)


def _record() -> RunRecord:
    return RunRecord(
        run_id="run-draft-reviewer-001",
        status="waiting",
        phase="human_review",
        source_digest="a" * 64,
        recipe_digest="b" * 64,
        source_name="source.md",
        recipe="enterprise_core",
    )


def _review() -> ReviewReport:
    return ReviewReport(
        summary="The source needs a reviewer decision before rewrite.",
        section_assessments=[
            SectionAssessment(
                section_id="section-1",
                title="Overview",
                status="improve",
                evidence_span_ids=["span-001"],
            )
        ],
        questions=[
            Question(
                question_id="Q-001",
                prompt="Which source-backed wording should be retained?",
                reason="The candidate preserves a structured ambiguity.",
                context="The ambiguity affects the overview and the process evidence.",
                evidence_span_ids=["span-001"],
                figure_ids=["FIG-001"],
                suggestion="Retain the wording supported by FIG-001 after review.",
                suggestion_basis="source_supported",
            )
        ],
    )


def _transformation() -> TransformationBundle:
    return TransformationBundle(
        source_digest="a" * 64,
        recipe_id="enterprise_core",
        recipe_digest="b" * 64,
        source_span_ids=["span-001"],
        source_dispositions=[
            SourceDisposition(
                source_span_id="span-001",
                action="placed",
                destination_section_ids=["section-1"],
                rationale="The source span supports the candidate overview.",
            )
        ],
        template_sections=[
            DraftSection(
                template_section_id="section-1",
                heading="Overview",
                status="partial",
                rewritten_markdown=(
                    "The known control is documented. **GAP-001** and **Q-001** require review. "
                    "The source includes **FIG-001**. <script>alert('x')</script>"
                ),
                source_span_ids=["span-001"],
                figure_ids=["FIG-001"],
                gap_ids=["GAP-001"],
                order=1,
            )
        ],
        gaps=[
            Gap(
                gap_id="GAP-001",
                template_section_id="section-1",
                kind="ambiguous",
                description="The source wording is ambiguous.",
                evidence_span_ids=["span-001"],
                figure_ids=["FIG-001"],
                question_id="Q-001",
            )
        ],
        questions=[
            TransformationQuestion(
                question_id="Q-001",
                prompt="Which source-backed wording should be retained?",
                reason="The source wording is ambiguous.",
                section_id="section-1",
                evidence_span_ids=["span-001"],
                figure_ids=["FIG-001"],
            )
        ],
        visual_references=[
            VisualReference(
                figure_id="FIG-001",
                source_digest="c" * 64,
                media_type="image/png",
                source_span_ids=["span-001"],
                caption="Source control screenshot",
            )
        ],
        visual_extractions=[
            VisualExtraction(
                figure_id="FIG-001",
                source_digest="c" * 64,
                kind="table",
                status="requires_review",
                structured_content={
                    "cells": [["Control", "State"], ["Review", "Required"]],
                    "warnings": ["visual_conversion_requires_review"],
                },
                source_span_ids=["span-001"],
                warnings=["best_effort_visual_data"],
            )
        ],
    )


def _source_figure() -> SourceFigure:
    return SourceFigure(
        figure_id="FIG-001",
        asset_id="asset-001",
        name="source.png",
        media_type="image/png",
        sha256="c" * 64,
        size_bytes=12,
        source_path="assets/source/FIG-001.png",
        caption="Source control screenshot",
        occurrences=[
            FigureOccurrence(source_span_id="span-001", section_id="section-1", ordinal=0)
        ],
    )


@pytest.mark.unit
def test_candidate_first_tabs_link_ids_evidence_and_visual_review() -> None:
    documents = [
        ("markdown/09-final-audit.md", "# Final audit\n\nNot run.\n"),
        ("markdown/06-review-questions.md", "# Questions\n\nSee Q-001.\n"),
        ("markdown/02-review-overview.md", "# Overview\n\nReview context.\n"),
        ("markdown/05-process-flow-review.md", "# Flow\n\nNo flow.\n"),
        ("markdown/04-section-review.md", "# Sections\n\nSection evidence.\n"),
        ("markdown/01-source-normalized.md", "# Source\n\nSource evidence span-001.\n"),
        ("markdown/03-macro-review.md", "# Macro\n\nMacro evidence.\n"),
        ("markdown/07-final-document.md", "# Final\n\nFinal content.\n"),
    ]

    rendered = render_html_report(
        record=_record(),
        review=_review(),
        documents=documents,
        audit=AuditReport(status="warn", summary="Draft audit is pending approval."),
        figures=[_source_figure()],
        draft=_transformation(),
    )

    tab_names = re.findall(r'class="tab-name">([^<]+)</span>', rendered)
    assert tab_names[:6] == ["Candidate draft", "Source", "Macro", "Sections", "Flow", "Questions"]
    assert 'role="tablist"' in rendered
    assert 'role="tab"' in rendered
    assert 'aria-selected="true"' in rendered
    assert 'id="candidate-draft"' in rendered
    assert "Candidate draft · UNAPPROVED · draft/document.md" in rendered
    assert "UNAPPROVED CANDIDATE CONTENT" in rendered
    assert "This draft is a proposed rewrite" in rendered
    assert "Draft audit" in rendered
    assert "Final document" in rendered

    assert 'href="#question-q-001"' in rendered
    assert 'id="gap-gap-001"' in rendered
    assert 'id="source-span-span-001"' in rendered
    assert 'href="#figure-fig-001"' in rendered
    assert "FIG-001" in rendered
    assert "REQUIRES_REVIEW" in rendered
    assert "Candidate table conversion" in rendered
    assert "Reviewer action:" in rendered
    assert "best_effort_visual_data" in rendered
    assert "not authoritative" in rendered
    assert "not accepted or sealed" in rendered
    assert "&lt;script&gt;alert" in rendered
    assert "<script>alert('x')</script>" not in rendered
    rendered_ids = re.findall(r'\bid="([^"]+)"', rendered)
    assert len(rendered_ids) == len(set(rendered_ids))
    assert re.search(
        r'<article class="visual-review-card[^>]*id="visual-fig-001".*?'
        r'<h3><a href="#figure-fig-001">FIG-001</a>',
        rendered,
        re.DOTALL,
    )

    rendered_without_source = render_html_report(
        record=_record(),
        review=_review(),
        documents=documents,
        figures=[],
        draft=_transformation(),
    )
    rendered_without_source_ids = re.findall(r'\bid="([^"]+)"', rendered_without_source)
    assert len(rendered_without_source_ids) == len(set(rendered_without_source_ids))
    assert re.search(
        r'<article class="visual-review-card[^>]*id="visual-fig-001".*?'
        r'<h3><a href="#visual-fig-001">FIG-001</a>',
        rendered_without_source,
        re.DOTALL,
    )


@pytest.mark.unit
def test_frozen_draft_document_path_is_detected_without_changing_legacy_callers() -> None:
    documents = [
        ("markdown/01-source-normalized.md", "# Source\n\nSource.\n"),
        ("draft/document.md", "# Candidate\n\n**GAP-001**\n"),
        ("markdown/03-macro-review.md", "# Macro\n\nMacro.\n"),
    ]

    rendered = render_html_report(record=_record(), review=_review(), documents=documents)

    tab_names = re.findall(r'class="tab-name">([^<]+)</span>', rendered)
    assert tab_names[:3] == ["Candidate draft", "Source", "Macro"]
    assert "Unapproved candidate draft" in rendered
    assert 'href="#question-question-gap-001"' in rendered


@pytest.mark.unit
def test_existing_report_api_remains_numbered_when_no_candidate_is_supplied() -> None:
    rendered = render_html_report(
        record=_record(),
        review=_review(),
        documents=[
            ("markdown/01-source-normalized.md", "# Source\n"),
            ("markdown/03-macro-review.md", "# Macro\n"),
        ],
    )

    tab_names = re.findall(r'class="tab-name">([^<]+)</span>', rendered)
    assert tab_names == ["Original Normalized Document", "Macro Review"]
    assert 'id="candidate-draft"' not in rendered
    assert "Candidate draft · UNAPPROVED" not in rendered


@pytest.mark.unit
@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../../outside.png",
        "assets\\source\\FIG-001.png",
        ".",
        "..",
        "",
        "assets/source/FIG-001.png?download=1",
        "assets/source/FIG-001.png#fragment",
        "assets/source/%2e%2e/outside.png",
        "tmp/FIG-001.png",
        "/tmp/outside.png",
        "javascript:alert('not safe')",
    ],
)
def test_source_figure_urls_remain_local_and_escaped(unsafe_path: str) -> None:
    unsafe_figure = _source_figure().model_copy(update={"source_path": unsafe_path})

    rendered = render_html_report(
        record=_record(),
        review=_review(),
        documents=[("markdown/01-source-normalized.md", "# Source\n")],
        figures=[unsafe_figure],
    )

    if unsafe_path:
        assert f'src="{unsafe_path}"' not in rendered
    else:
        assert 'src=""' in rendered
    assert 'src=""' in rendered
    assert 'src="javascript:' not in rendered


@pytest.mark.unit
def test_source_figure_urls_allow_normalized_run_assets() -> None:
    final_figure = _source_figure().model_copy(update={"source_path": "assets/final/FIG-001.png"})

    rendered = render_html_report(
        record=_record(),
        review=_review(),
        documents=[("markdown/01-source-normalized.md", "# Source\n")],
        figures=[final_figure],
    )

    assert 'src="assets/final/FIG-001.png"' in rendered
