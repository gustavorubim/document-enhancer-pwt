"""Render the selected reference-pack template from the validated M6 model."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from document_enhancer.references.loader import ReferencePack, load_reference_pack
from document_enhancer.references.renderer import render_template_text

from .mermaid import generate_mermaid
from .models import EnhancedDocumentModel, StructuredTable

_TABLE_ROW_RE = re.compile(r"(?m)^\|[^\n]*\{\{\s*tables\.([A-Za-z0-9_-]+)\s*\}\}[^\n]*\|\s*$")
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s+.*?```", re.DOTALL | re.IGNORECASE)


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip() or "TBD"


def _table_rows(table: StructuredTable) -> str:
    return "\n".join(
        "| "
        + " | ".join(_cell(row.values.get(column.column_id, "TBD")) for column in table.columns)
        + " |"
        for row in table.rows
    )


def _additional_tables(model: EnhancedDocumentModel, template: str) -> str:
    rendered_kinds = set(re.findall(r"\{\{\s*tables\.([A-Za-z0-9_-]+)\s*\}\}", template))
    extra = [table for table in model.tables if table.table_kind not in rendered_kinds]
    if not extra:
        return ""
    blocks = ["## Structured traceability tables", ""]
    for table in extra:
        blocks.extend(
            [
                f"### {table.title} ({table.table_id})",
                "",
                table.purpose,
                "",
                "| " + " | ".join(column.label for column in table.columns) + " |",
                "| " + " | ".join("---" for _ in table.columns) + " |",
                _table_rows(table),
                "",
            ]
        )
    return "\n".join(blocks)


def _table_index(model: EnhancedDocumentModel) -> str:
    rows = [
        "## Table identifiers",
        "",
        "| Table ID | Kind |",
        "| --- | --- |",
    ]
    rows.extend(f"| {table.table_id} | {table.table_kind} |" for table in model.tables)
    return "\n".join(rows)


def _pack_and_template(
    model: EnhancedDocumentModel,
    reference_pack: Path | ReferencePack,
) -> tuple[ReferencePack, Path]:
    pack = (
        reference_pack
        if isinstance(reference_pack, ReferencePack)
        else load_reference_pack(reference_pack)
    )
    document_type = model.document.document_type.value
    return pack, pack.template_path(document_type)


def _payload(model: EnhancedDocumentModel) -> dict[str, Any]:
    document = model.document
    version = model.version
    sections: dict[str, str] = {}
    for section in model.sections:
        sections[section.anchor] = section.body
        sections[section.section_id] = section.body
    tables = {table.table_kind: _table_rows(table) for table in model.tables}
    attributes = document.attributes
    return {
        "document": {
            "id": document.id,
            "title": document.name,
            "version": version.version,
            "status": version.status.value,
            "owner": attributes.get("owner", "TBD"),
            "effective_date": attributes.get("effective_date", "TBD"),
            "next_review_date": attributes.get("next_review_date", "TBD"),
        },
        "sections": sections,
        "tables": tables,
    }


def render_enhanced_markdown(
    model: EnhancedDocumentModel,
    *,
    reference_pack: Path | ReferencePack,
) -> str:
    """Render target Markdown while stripping controls and replacing all template placeholders."""

    model.assert_valid()
    _pack, template_path = _pack_and_template(model, reference_pack)
    template = template_path.read_text(encoding="utf-8")

    def table_replace(match: re.Match[str]) -> str:
        kind = match.group(1)
        table = next((item for item in model.tables if item.table_kind == kind), None)
        if table is None:
            return "| TBD |"
        return _table_rows(table)

    template = _TABLE_ROW_RE.sub(table_replace, template)

    def mermaid_replace(_match: re.Match[str]) -> str:
        if not model.mermaid:
            return '```mermaid\nflowchart TD\n    TBD_FLOW["No approved structured flow"]\n```'
        return "```mermaid\n" + generate_mermaid(model.mermaid[0]).rstrip() + "\n```"

    template = _MERMAID_BLOCK_RE.sub(mermaid_replace, template)
    rendered = render_template_text(template, _payload(model))
    rendered = rendered.rstrip() + "\n\n" + _additional_tables(model, template)
    rendered = rendered.rstrip() + "\n\n" + _table_index(model)
    rendered = rendered.rstrip() + "\n"
    if "{{" in rendered or "}}" in rendered or "<!--" in rendered or "-->" in rendered:
        raise ValueError("rendered Markdown contains template controls or authoring comments")
    if "STEP-TBD" in rendered or "CompletionCondition-TBD" in rendered:
        raise ValueError("rendered Markdown contains an unrendered template placeholder")
    return rendered


render_markdown = render_enhanced_markdown


__all__ = ["render_enhanced_markdown", "render_markdown"]
