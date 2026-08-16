from __future__ import annotations

import base64
import hashlib
from typing import cast

import pytest

from document_enhancer.core.models import FigureOccurrence, SourceFigure
from document_enhancer.core.visuals import (
    VisualFigureInput,
    VisualInterpreter,
    VisualLimits,
    VisualValidationError,
    table_cells_to_markdown,
)
from document_enhancer.llm import FakeMultimodalModel

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PNG_DIGEST = hashlib.sha256(PNG_1X1).hexdigest()


def _figure(
    figure_id: str = "FIG-001",
    *,
    payload: bytes = PNG_1X1,
    media_type: str = "image/png",
    caption: str = "Submission screen",
) -> tuple[SourceFigure, VisualFigureInput]:
    digest = hashlib.sha256(payload).hexdigest()
    source = SourceFigure(
        figure_id=figure_id,
        asset_id=f"asset-{figure_id.lower()}",
        name=f"{figure_id}.png",
        media_type="image/png",
        sha256=digest,
        size_bytes=len(payload),
        source_path=f"assets/source/{figure_id}.png",
        caption=caption,
        occurrences=[
            FigureOccurrence(
                source_span_id=f"span-{figure_id.lower()}",
                section_id="section-submit",
                ordinal=2,
                location={"line_start": 4},
                anchor_text="Select Submit.",
            )
        ],
    )
    visual = VisualFigureInput.from_source_figure(source, payload)
    if media_type != "image/png":
        visual = visual.model_copy(update={"media_type": media_type})
    return source, visual


def _table_response(visual: VisualFigureInput) -> dict[str, object]:
    return {
        "figure_id": visual.figure_id,
        "source_sha256": visual.sha256,
        "source_span_ids": list(visual.source_span_ids),
        "kind": "table",
        "status": "best_effort",
        "confidence": 0.9,
        "cells": [["Step", "Owner"], ["Submit", "Analyst"]],
    }


@pytest.mark.unit
def test_table_candidate_preserves_source_identity_bytes_digest_caption_and_provenance() -> None:
    source, visual = _figure()
    original_bytes = bytes(visual.payload)
    fake = FakeMultimodalModel([_table_response(visual)])

    result = VisualInterpreter(fake).interpret([visual], context="Submission workflow")

    assert len(result) == 1
    candidate = result[0]
    assert candidate.figure_id == source.figure_id
    assert candidate.asset_id == source.asset_id
    assert candidate.source_sha256 == source.sha256 == PNG_DIGEST
    assert candidate.source_digest == source.sha256
    assert candidate.caption == source.caption
    assert candidate.source_span_ids == ("span-fig-001",)
    occurrences = candidate.provenance["occurrences"]
    assert isinstance(occurrences, list)
    occurrence = cast(dict[str, object], occurrences[0])
    assert occurrence["section_id"] == "section-submit"
    assert candidate.status == "requires_review"
    assert candidate.structured_content.cells == [
        ["Step", "Owner"],
        ["Submit", "Analyst"],
    ]
    assert candidate.to_markdown_table() == (
        "| Step | Owner |\n| --- | --- |\n| Submit | Analyst |\n"
    )
    assert visual.payload == original_bytes
    assert hashlib.sha256(visual.payload).hexdigest() == source.sha256


@pytest.mark.unit
def test_native_table_inputs_are_skipped_without_a_visual_call() -> None:
    fake = FakeMultimodalModel([])

    result = VisualInterpreter(fake).interpret(
        [{"block_type": "table", "rows": [["A", "B"]]}],
        native_tables=[{"block_type": "table"}],
    )

    assert result == []
    assert fake.calls == []


@pytest.mark.unit
def test_malformed_grid_and_provider_linkage_fail_as_requires_review_or_raise() -> None:
    _, visual = _figure()
    malformed = {
        **_table_response(visual),
        "cells": [["Step", "Owner"], ["Submit"]],
    }
    review = VisualInterpreter(FakeMultimodalModel([malformed])).interpret([visual])
    assert review[0].status == "requires_review"
    assert "visual_response_invalid" in review[0].warnings

    strict = VisualInterpreter(
        FakeMultimodalModel(
            [
                {
                    **_table_response(visual),
                    "source_span_ids": ["span-not-in-source"],
                }
            ]
        ),
        failure_mode="raise",
    )
    with pytest.raises(VisualValidationError, match="visual_response_unknown_source_span"):
        strict.interpret([visual])


@pytest.mark.unit
def test_mismatched_digest_unknown_response_id_and_unknown_media_are_bounded() -> None:
    _, visual = _figure()
    tampered = visual.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(VisualValidationError, match="figure_digest_mismatch"):
        VisualInterpreter().interpret([tampered])

    mismatch = VisualInterpreter(
        FakeMultimodalModel([_table_response(visual) | {"source_sha256": "0" * 64}])
    ).interpret([visual])
    assert mismatch[0].status == "requires_review"
    assert "visual_response_digest_mismatch" in mismatch[0].warnings

    unknown_id_response = _table_response(visual) | {"figure_id": "FIG-002"}
    unknown = VisualInterpreter(FakeMultimodalModel([unknown_id_response])).interpret([visual])
    assert unknown[0].figure_id == visual.figure_id
    assert unknown[0].status == "requires_review"

    _, unsupported = _figure(media_type="image/gif")
    unsupported_result = VisualInterpreter(FakeMultimodalModel([])).interpret([unsupported])
    assert unsupported_result[0].status == "unsupported"
    assert "unsupported_visual_media" in unsupported_result[0].warnings


@pytest.mark.unit
def test_count_size_context_and_grid_budgets_do_not_call_model() -> None:
    _, visual = _figure()
    fake = FakeMultimodalModel([])
    size_limited = VisualInterpreter(
        fake,
        limits=VisualLimits(max_bytes_per_figure=len(PNG_1X1) - 1),
    ).interpret([visual])
    assert size_limited[0].status == "requires_review"
    assert "visual_figure_size_budget_exceeded" in size_limited[0].warnings
    assert fake.calls == []

    interpreter = VisualInterpreter(
        fake,
        limits=VisualLimits(
            max_figures=1,
            max_total_bytes=len(PNG_1X1),
            max_context_chars=4,
        ),
    )

    result = interpreter.interpret([visual], context="too long")

    assert result[0].status == "requires_review"
    assert "visual_context_budget_exceeded" in result[0].warnings
    assert fake.calls == []


@pytest.mark.unit
def test_classification_kinds_are_typed_and_chart_values_require_legibility() -> None:
    figures: list[VisualFigureInput] = []
    responses: dict[str, list[object]] = {}
    kinds = ["table", "process_diagram", "chart", "ui_screenshot", "decorative", "unknown"]
    for index, kind in enumerate(kinds, start=1):
        _, visual = _figure(f"FIG-{index:03d}")
        figures.append(visual)
        response: dict[str, object] = {
            "figure_id": visual.figure_id,
            "source_sha256": visual.sha256,
            "source_span_ids": list(visual.source_span_ids),
            "kind": kind,
            "status": "best_effort",
            "confidence": 0.8,
        }
        if kind == "table":
            response["cells"] = [["A", "B"]]
        elif kind == "process_diagram":
            response["mermaid"] = "flowchart TD\nA[Start] --> B[End]"
        elif kind == "chart":
            response["chart_values"] = [{"label": "Q1", "value": 12.0}]
            response["legible"] = False
            response["reviewable"] = False
        responses[visual.figure_id] = [response]

    result = VisualInterpreter(FakeMultimodalModel(responses)).interpret(figures)

    assert [item.kind for item in result] == kinds
    assert result[1].structured_content.mermaid is not None
    assert result[2].structured_content.chart_values == []
    assert result[3].non_authoritative is True
    assert result[5].status == "requires_review"


@pytest.mark.unit
def test_table_markdown_escaping_remains_deterministic() -> None:
    assert table_cells_to_markdown([["A|B", "Line\nwrap"]]) == (
        "| A\\|B | Line wrap |\n| --- | --- |\n"
    )
