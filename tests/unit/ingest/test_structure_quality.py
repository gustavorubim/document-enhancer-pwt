from __future__ import annotations

from pathlib import Path

from document_enhancer.ingest.markdown import parse_markdown_text
from document_enhancer.ingest.models import RecoveryThresholds
from document_enhancer.ingest.normalize import normalize_document
from document_enhancer.ingest.structure_quality import assess_structure, route_structure

FIXTURE = Path(__file__).parents[3] / "fixtures" / "synthetic" / "ingest" / "messy-layout.md"


def test_clean_heading_structure_stays_on_parser_path() -> None:
    raw = parse_markdown_text(
        "# Title\n\n## Scope\n\nClear content.\n\n## Steps\n\n1. Do it.\n2. Check it.\n"
    )

    report = assess_structure(raw)
    decision = route_structure(report)

    assert report.heading_count == 3
    assert report.heading_style_consistency == 1.0
    assert decision.mode == "parser"
    assert decision.reasons == ()


def test_messy_layout_routes_to_recovery_without_model_output() -> None:
    raw = parse_markdown_text(FIXTURE.read_text(encoding="utf-8"), source_name=str(FIXTURE))
    normalized = normalize_document(raw)

    assert normalized.routing.mode == "llm_recovery"
    assert "no_headings" in normalized.quality.warnings
    assert normalized.selected_view is not None
    assert normalized.selected_view.origin == "parser"
    assert normalized.selected_view.validation_passed is True


def test_thresholds_are_configurable_and_deterministic() -> None:
    raw = parse_markdown_text("Title\n\nBody\n")
    report = assess_structure(raw)
    forced = route_structure(report, RecoveryThresholds(minimum_structure_score=1.0))

    assert forced.mode == "llm_recovery"
    assert "structure_score_below_threshold" in forced.reasons
