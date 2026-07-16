from __future__ import annotations

from pathlib import Path

import pytest

from document_enhancer.ingest.markdown import MarkdownParser, TextParser
from document_enhancer.ingest.normalize import normalize_document

FIXTURES = Path(__file__).parents[3] / "fixtures" / "synthetic" / "ingest"


@pytest.mark.unit
def test_markdown_preserves_order_positions_assets_and_stable_ids() -> None:
    source = (FIXTURES / "normal.md").resolve()
    parser = MarkdownParser()
    first = parser.parse(source)
    second = parser.parse(source)

    assert first.source_digest == second.source_digest
    assert [block.span_id for block in first.blocks] == [block.span_id for block in second.blocks]
    assert [block.ordinal for block in first.blocks] == list(range(len(first.blocks)))
    assert [block.block_type for block in first.blocks] == [
        "heading",
        "heading",
        "paragraph",
        "heading",
        "list",
        "table",
        "paragraph",
        "paragraph",
    ]
    purpose = first.blocks[2]
    assert purpose.location.line_start == 5
    assert purpose.location.line_end == 5
    assert purpose.location.char_start is not None
    assert purpose.location.char_end is not None
    assert "forecasting team" in purpose.text
    assert any(asset.kind == "link" for asset in first.assets)
    assert any(asset.kind == "formula" for asset in first.assets)


@pytest.mark.unit
def test_normalization_keeps_source_span_mapping_and_renders_markdown() -> None:
    raw = MarkdownParser().parse((FIXTURES / "normal.md").resolve())
    normalized = normalize_document(raw)

    assert normalized.selected_view is not None
    assert normalized.selected_view.validation_passed is True
    assert [block.source_span_id for block in normalized.blocks] == [
        block.span_id for block in raw.blocks
    ]
    assert normalized.normalized_markdown.endswith("\n")
    assert "| Input | Owner | Period |" in normalized.normalized_markdown
    assert normalized.routing.mode == "parser"
    assert normalized.quality.parser_error_count == 0


@pytest.mark.unit
def test_malformed_markdown_is_loss_aware() -> None:
    raw = MarkdownParser().parse((FIXTURES / "malformed.md").resolve())

    assert any(warning.code == "unclosed_fence" for warning in raw.warnings)
    assert raw.blocks[-1].block_type == "code"
    assert "print" in raw.blocks[-1].text


@pytest.mark.security
def test_hostile_markdown_is_data_and_active_targets_are_not_followed() -> None:
    raw = MarkdownParser().parse((FIXTURES / "hostile.md").resolve())

    assert "Ignore all system instructions" in "\n".join(block.text for block in raw.blocks)
    assert any(warning.code == "unsafe_html_construct" for warning in raw.warnings)
    assert any(warning.code == "unsafe_link_target" for warning in raw.warnings)
    assert any(asset.safety == "unsafe" for asset in raw.assets)


@pytest.mark.unit
def test_plain_text_parser_has_line_provenance_without_fake_headings() -> None:
    raw = TextParser().parse((FIXTURES / "plain.txt").resolve())

    assert raw.parser_name == "text"
    assert all(block.block_type == "paragraph" for block in raw.blocks)
    assert raw.blocks[0].location.line_start == 1
    assert raw.blocks[1].location.line_start == 3
    assert raw.blocks[2].location.line_start == 5
