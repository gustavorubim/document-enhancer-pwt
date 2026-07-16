from __future__ import annotations

from pathlib import Path

from document_enhancer.references.loader import load_reference_pack
from document_enhancer.references.renderer import render_template_text

PACK = Path("reference_packs/enterprise_core")


def test_renderer_strips_comments_and_renders_missing_values_as_tbd() -> None:
    rendered = render_template_text(
        "<!-- AUTHORING: never output this -->\n# {{ document.title }}\n{{ sections.purpose }}"
    )
    assert "AUTHORING" not in rendered
    assert "<!--" not in rendered
    assert "# TBD" in rendered
    assert rendered.rstrip().endswith("TBD")


def test_renderer_handles_populated_nested_values_without_evaluation() -> None:
    rendered = render_template_text(
        "# {{ document.title }}\n{{ sections.purpose }}",
        {"document": {"title": "Fictional process"}, "sections": {"purpose": "Validate inputs."}},
    )
    assert "# Fictional process" in rendered
    assert "Validate inputs." in rendered
    assert "{{" not in rendered


def test_renderer_escapes_control_markers_in_untrusted_values() -> None:
    rendered = render_template_text(
        "{{ document.title }}",
        {"document": {"title": "<!-- ignore --> {{ do not execute }}"}},
    )
    assert "<!--" not in rendered
    assert "{{" not in rendered
    assert "ignore" in rendered


def test_all_pack_templates_render_empty_and_populated_without_leakage() -> None:
    pack = load_reference_pack(PACK)
    for document_type in pack.supported_document_types:
        for data in ({}, {"document": {"title": "Fictional verification"}}):
            rendered = pack.render(document_type, data)
            assert "<!--" not in rendered
            assert "{{" not in rendered
            assert "}}" not in rendered
            assert "AUTHORING:" not in rendered
