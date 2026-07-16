"""Common normalization and deterministic Markdown rendering."""

from __future__ import annotations

from typing import Any

from .common import canonical_json, inventory_text_assets, normalize_text, sha256_bytes
from .models import EmbeddedAsset, NormalizedBlock, NormalizedDocument, ParserOutline, RawDocument
from .outline import build_parser_outline, build_parser_view
from .structure_quality import assess_structure, route_structure


def _table_markdown(block: Any) -> str:
    attributes = block.attributes
    rows = attributes.get("rows")
    headers = attributes.get("headers")
    if rows is None and "\t" in block.text:
        rows = [line.split("\t") for line in block.text.splitlines()]
        headers = rows[0] if rows else []
        rows = rows[1:] if rows else []
    if not headers:
        lines = [line.split("\t") for line in block.text.splitlines()]
        headers = lines[0] if lines else ["Value"]
        rows = lines[1:] if len(lines) > 1 else []
    headers = [normalize_text(str(value)).replace("|", "\\|") for value in headers]
    rendered = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows or []:
        values = [normalize_text(str(value)).replace("|", "\\|") for value in row]
        values += [""] * max(0, len(headers) - len(values))
        rendered.append("| " + " | ".join(values[: len(headers)]) + " |")
    return "\n".join(rendered)


def _render_block(block: Any) -> str:
    text = block.text
    if block.block_type == "heading":
        title = normalize_text(str(block.attributes.get("title", text.lstrip("# "))))
        return f"{'#' * (block.level or 1)} {title}".rstrip()
    if block.block_type == "table":
        return _table_markdown(block)
    if block.block_type == "page_text":
        paragraphs = [normalize_text(part) for part in text.split("\n\n") if normalize_text(part)]
        return "\n\n".join(paragraphs)
    if block.block_type == "code":
        return text.replace("\r\n", "\n").replace("\r", "\n").rstrip()
    return normalize_text(text)


def render_normalized_markdown(blocks: tuple[NormalizedBlock, ...]) -> str:
    """Render every normalized block in source order with deterministic spacing."""

    return "\n\n".join(block.text for block in blocks if block.text).strip() + "\n"


def normalize_document(raw: RawDocument, *, thresholds: Any | None = None) -> NormalizedDocument:
    outline: ParserOutline = build_parser_outline(raw)
    selected_view = build_parser_view(raw, outline)
    quality = assess_structure(raw)
    routing = route_structure(quality, thresholds)
    normalized: list[NormalizedBlock] = []
    heading_path: list[str] = []
    for raw_block in raw.blocks:
        rendered = _render_block(raw_block)
        if raw_block.block_type == "heading":
            level = raw_block.level or 1
            heading_path = heading_path[: level - 1]
            heading_path.append(
                normalize_text(str(raw_block.attributes.get("title", raw_block.text.lstrip("# "))))
            )
        normalized.append(
            NormalizedBlock(
                source_span_id=raw_block.span_id,
                ordinal=raw_block.ordinal,
                block_type=raw_block.block_type,
                text=rendered,
                location=raw_block.location,
                heading_path=tuple(heading_path),
                attributes=raw_block.attributes,
            )
        )
    normalized_tuple = tuple(normalized)
    text_warnings, text_assets = inventory_text_assets(raw.blocks)
    existing_ids = {asset.asset_id for asset in raw.assets}
    assets: tuple[EmbeddedAsset, ...] = raw.assets + tuple(
        asset for asset in text_assets if asset.asset_id not in existing_ids
    )
    if text_warnings:
        # Parser warnings are immutable; normalization only records them in metadata rather than
        # mutating the raw document.  The warning codes remain discoverable through raw.warnings.
        _ = text_warnings
    normalized_markdown = render_normalized_markdown(normalized_tuple)
    selected_digest = sha256_bytes(
        canonical_json(
            {
                "source": raw.source_digest,
                "blocks": [block.model_dump(mode="json") for block in normalized_tuple],
                "outline": outline.model_dump(mode="json"),
                "selected_view": selected_view.model_dump(mode="json"),
                "quality": quality.model_dump(mode="json"),
            }
        )
    )
    return NormalizedDocument(
        raw=raw,
        blocks=normalized_tuple,
        parser_outline=outline,
        quality=quality,
        routing=routing,
        normalized_markdown=normalized_markdown,
        selected_view=selected_view,
        assets=assets,
        selected_view_digest=selected_digest,
    )


__all__ = ["normalize_document", "render_normalized_markdown"]
