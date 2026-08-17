"""Focused tests for deterministic final-audit helpers."""

import pytest

from document_enhancer.core.audit import source_sections_retained
from document_enhancer.core.models import ReviewReport, Section
from document_enhancer.core.transformation import (
    DraftSection,
    SourceAction,
    SourceDisposition,
    TransformationBundle,
)


def _mapping(*, action: SourceAction = "placed") -> TransformationBundle:
    destinations = ["SEC-001"] if action == "placed" else []
    return TransformationBundle(
        source_digest="a" * 64,
        recipe_id="test-recipe",
        recipe_digest="b" * 64,
        source_span_ids=["span-001"],
        template_sections=[
            DraftSection(
                template_section_id="SEC-001",
                heading="Governance and monitoring",
                status="populated",
                rewritten_markdown="The source control is represented here.",
                source_span_ids=["span-001"],
            )
        ],
        source_dispositions=[
            SourceDisposition(
                source_span_id="span-001",
                action=action,
                destination_section_ids=destinations,
                rationale="The source span is explicitly accounted for.",
            )
        ],
    )


@pytest.mark.unit
def test_source_accounting_uses_explicit_mapping_when_heading_is_renamed() -> None:
    review = ReviewReport(
        summary="review",
        sections=[
            Section(
                section_id="section-001",
                title="Controls",
                level=1,
                span_ids=["span-001"],
            )
        ],
    )

    assert source_sections_retained(
        review,
        "# Governance and monitoring\n\nThe source control is represented here.\n",
        mapping=_mapping(),
    )
    assert not source_sections_retained(
        review,
        "# Governance and monitoring\n\nThe source control is represented here.\n",
        mapping=_mapping(action="intentionally_omitted"),
    )
