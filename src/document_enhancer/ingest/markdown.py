"""Position-preserving Markdown and plain-text parsers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from .common import (
    DEFAULT_MAX_SOURCE_BYTES,
    block_digest,
    decode_utf8,
    inventory_text_assets,
    media_type_for,
    read_source,
    sha256_bytes,
    span_id,
)
from .models import EmbeddedAsset, ExtractionWarning, RawBlock, RawDocument, SourceLocation

_HEADING_RE = re.compile(r"^(#{1,6})(?:[ \t]+|$)(.*?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})([^`]*)$")
_LIST_RE = re.compile(r"^(\s*)([-+*]|\d+[.)])[ \t]+(.*)$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_HR_RE = re.compile(r"^\s{0,3}(?:\*\s*){3,}$|^\s{0,3}(?:-\s*){3,}$|^\s{0,3}(?:_\s*){3,}$")
_IMAGE_ONLY_RE = re.compile(r"^\s*!\[[^]]*\]\([^)]*\)\s*$")
_HTML_RE = re.compile(r"^\s*</?(?:script|iframe|object|embed|form|svg|style|video|audio)\b", re.I)


def _line_parts(text: str) -> tuple[list[str], list[int]]:
    lines = text.splitlines(keepends=True)
    if text and not lines:
        lines = [text]
    if not text:
        return [], []
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line)
    return lines, starts


def _line_text(line: str) -> str:
    return line.rstrip("\r\n")


def _location(
    *,
    kind: Literal["markdown", "text", "docx", "pdf"],
    lines: list[str],
    starts: list[int],
    start: int,
    end: int,
) -> SourceLocation:
    start_offset = starts[start]
    end_offset = starts[end] + len(_line_text(lines[end]))
    return SourceLocation(
        kind=kind,  # type: ignore[arg-type]
        line_start=start + 1,
        line_end=end + 1,
        char_start=start_offset,
        char_end=end_offset,
    )


def _block(
    *,
    source_digest: str,
    ordinal: int,
    block_type: str,
    text: str,
    location: SourceLocation,
    **kwargs: Any,
) -> RawBlock:
    return RawBlock(
        span_id=span_id(
            source_digest=source_digest,
            ordinal=ordinal,
            block_type=block_type,
            text=text,
            location=location,
        ),
        ordinal=ordinal,
        block_type=block_type,
        text=text,
        location=location,
        content_digest=block_digest(block_type, text, location),
        attributes=kwargs.pop("attributes", {}),
        **kwargs,
    )


def _table_metadata(table_lines: list[str]) -> dict[str, Any]:
    def cells(line: str) -> list[str]:
        value = line.strip().strip("|")
        return [cell.strip() for cell in value.split("|")]

    return {
        "headers": cells(table_lines[0]) if table_lines else [],
        "rows": [cells(line) for line in table_lines[2:]],
        "column_count": len(cells(table_lines[0])) if table_lines else 0,
        "has_separator": len(table_lines) > 1 and bool(_TABLE_SEPARATOR_RE.match(table_lines[1])),
    }


def _parse_text_blocks(
    text: str,
    *,
    source_digest: str,
    kind: Literal["markdown", "text", "docx", "pdf"],
    headings: bool,
) -> tuple[tuple[RawBlock, ...], tuple[ExtractionWarning, ...]]:
    lines, starts = _line_parts(text)
    blocks: list[RawBlock] = []
    warnings: list[ExtractionWarning] = []
    index = 0
    ordinal = 0
    while index < len(lines):
        current = _line_text(lines[index])
        if not current.strip():
            index += 1
            continue

        heading = _HEADING_RE.match(current) if headings else None
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            location = _location(kind=kind, lines=lines, starts=starts, start=index, end=index)
            blocks.append(
                _block(
                    source_digest=source_digest,
                    ordinal=ordinal,
                    block_type="heading",
                    text=text[location.char_start : location.char_end],
                    location=location,
                    level=level,
                    style=f"markdown_h{level}",
                    attributes={"title": title, "marker": heading.group(1)},
                )
            )
            ordinal += 1
            index += 1
            continue

        fence = _FENCE_RE.match(current)
        if fence:
            marker = fence.group(1)
            fence_char = marker[0]
            closing = re.compile(rf"^\s{{0,3}}{re.escape(fence_char)}{{{len(marker)},}}\s*$")
            end = index + 1
            while end < len(lines) and not closing.match(_line_text(lines[end])):
                end += 1
            if end == len(lines):
                warnings.append(
                    ExtractionWarning(
                        code="unclosed_fence",
                        message="Fenced code block has no closing fence; retained to end of source.",
                        severity="warning",
                        location=_location(
                            kind=kind, lines=lines, starts=starts, start=index, end=end - 1
                        ),
                    )
                )
                last = end - 1
            else:
                last = end
            location = _location(kind=kind, lines=lines, starts=starts, start=index, end=last)
            language = fence.group(2).strip().split(maxsplit=1)[0] if fence.group(2).strip() else ""
            blocks.append(
                _block(
                    source_digest=source_digest,
                    ordinal=ordinal,
                    block_type="code",
                    text=text[location.char_start : location.char_end],
                    location=location,
                    attributes={"fence": marker, "language": language},
                )
            )
            ordinal += 1
            index = last + 1
            continue

        if _IMAGE_ONLY_RE.match(current):
            location = _location(kind=kind, lines=lines, starts=starts, start=index, end=index)
            blocks.append(
                _block(
                    source_digest=source_digest,
                    ordinal=ordinal,
                    block_type="figure",
                    text=text[location.char_start : location.char_end],
                    location=location,
                    caption=False,
                )
            )
            ordinal += 1
            index += 1
            continue

        if _HR_RE.match(current):
            location = _location(kind=kind, lines=lines, starts=starts, start=index, end=index)
            blocks.append(
                _block(
                    source_digest=source_digest,
                    ordinal=ordinal,
                    block_type="thematic_break",
                    text=text[location.char_start : location.char_end],
                    location=location,
                )
            )
            ordinal += 1
            index += 1
            continue

        if (
            index + 1 < len(lines)
            and "|" in current
            and _TABLE_SEPARATOR_RE.match(_line_text(lines[index + 1]))
        ):
            end = index + 2
            while (
                end < len(lines)
                and _line_text(lines[end]).strip()
                and "|" in _line_text(lines[end])
            ):
                end += 1
            last = end - 1
            location = _location(kind=kind, lines=lines, starts=starts, start=index, end=last)
            table_lines = [_line_text(lines[line]) for line in range(index, last + 1)]
            blocks.append(
                _block(
                    source_digest=source_digest,
                    ordinal=ordinal,
                    block_type="table",
                    text=text[location.char_start : location.char_end],
                    location=location,
                    attributes=_table_metadata(table_lines),
                )
            )
            ordinal += 1
            index = end
            continue

        list_match = _LIST_RE.match(current)
        if list_match:
            end = index + 1
            while end < len(lines):
                candidate = _line_text(lines[end])
                if not candidate.strip():
                    break
                next_list = _LIST_RE.match(candidate)
                if next_list or candidate.startswith(("  ", "\t")):
                    end += 1
                    continue
                break
            last = end - 1
            location = _location(kind=kind, lines=lines, starts=starts, start=index, end=last)
            marker = list_match.group(2)
            list_kind = "ordered" if marker[0].isdigit() else "unordered"
            if current.lstrip().startswith("- ["):
                list_kind = "task"
            blocks.append(
                _block(
                    source_digest=source_digest,
                    ordinal=ordinal,
                    block_type="list",
                    text=text[location.char_start : location.char_end],
                    location=location,
                    list_kind=list_kind,  # type: ignore[arg-type]
                    list_depth=len(list_match.group(1)) // 2,
                    list_marker=marker,
                    attributes={"items": end - index},
                )
            )
            ordinal += 1
            index = end
            continue

        if _HTML_RE.match(current) or current.lstrip().startswith("<!--"):
            end = index + 1
            while end < len(lines) and _line_text(lines[end]).strip():
                end += 1
            last = end - 1
            location = _location(kind=kind, lines=lines, starts=starts, start=index, end=last)
            warning_code = "unsafe_html_construct" if _HTML_RE.match(current) else "raw_html"
            warnings.append(
                ExtractionWarning(
                    code=warning_code,
                    message="Raw HTML was retained as data and will not be executed.",
                    severity="error" if warning_code == "unsafe_html_construct" else "warning",
                    location=location,
                )
            )
            blocks.append(
                _block(
                    source_digest=source_digest,
                    ordinal=ordinal,
                    block_type="raw_html",
                    text=text[location.char_start : location.char_end],
                    location=location,
                    attributes={
                        "safety": "unsafe" if warning_code == "unsafe_html_construct" else "passive"
                    },
                )
            )
            ordinal += 1
            index = end
            continue

        block_type = "blockquote" if current.lstrip().startswith(">") else "paragraph"
        end = index + 1
        while end < len(lines):
            candidate = _line_text(lines[end])
            if not candidate.strip():
                break
            if headings and _HEADING_RE.match(candidate):
                break
            if _FENCE_RE.match(candidate) or _LIST_RE.match(candidate) or _HR_RE.match(candidate):
                break
            if (
                end + 1 < len(lines)
                and "|" in candidate
                and _TABLE_SEPARATOR_RE.match(_line_text(lines[end + 1]))
            ):
                break
            end += 1
        last = end - 1
        location = _location(kind=kind, lines=lines, starts=starts, start=index, end=last)
        blocks.append(
            _block(
                source_digest=source_digest,
                ordinal=ordinal,
                block_type=block_type,
                text=text[location.char_start : location.char_end],
                location=location,
            )
        )
        ordinal += 1
        index = end

    return tuple(blocks), tuple(warnings)


def _raw_document(
    *,
    source: Path,
    data: bytes,
    text: str,
    kind: Literal["markdown", "text", "docx", "pdf"],
    parser_name: str,
    headings: bool,
) -> RawDocument:
    source_digest = sha256_bytes(data)
    blocks, warnings = _parse_text_blocks(
        text, source_digest=source_digest, kind=kind, headings=headings
    )
    decode_warnings: tuple[ExtractionWarning, ...] = ()
    try:
        _, replacement = decode_utf8(data)
    except Exception:  # pragma: no cover - defensive; decode_utf8 is total
        replacement = False
    if replacement:
        decode_warnings = (
            ExtractionWarning(
                code="invalid_utf8_replaced",
                message="Invalid UTF-8 bytes were replaced for parsing; raw source digest is retained.",
                severity="error",
            ),
        )
    all_warnings = decode_warnings + warnings
    asset_warnings, assets = inventory_text_assets(blocks)
    return RawDocument(
        source_path=source,
        source_name=source.name,
        media_type=media_type_for(source),
        size_bytes=len(data),
        source_digest=source_digest,
        blocks=blocks,
        warnings=all_warnings + asset_warnings,
        assets=assets,
        parser_name=parser_name,
        parser_version="1",
        metadata={"headings_enabled": headings},
    )


class MarkdownParser:
    """Parse Markdown without rendering or executing embedded content."""

    supported_suffixes = frozenset({".md", ".markdown"})

    def __init__(self, *, max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES) -> None:
        self.max_source_bytes = max_source_bytes

    def can_parse(self, source: Path) -> bool:
        return source.suffix.lower() in self.supported_suffixes

    def parse(self, source: Path) -> RawDocument:
        data = read_source(source, max_bytes=self.max_source_bytes)
        text, _ = decode_utf8(data)
        raw = _raw_document(
            source=source,
            data=data,
            text=text,
            kind="markdown",
            parser_name="markdown",
            headings=True,
        )
        return _materialize_local_images(raw, max_bytes=self.max_source_bytes)


class TextParser:
    """Parse plain text into ordered paragraphs with line and character provenance."""

    supported_suffixes = frozenset({".txt", ".text"})

    def __init__(self, *, max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES) -> None:
        self.max_source_bytes = max_source_bytes

    def can_parse(self, source: Path) -> bool:
        return source.suffix.lower() in self.supported_suffixes

    def parse(self, source: Path) -> RawDocument:
        data = read_source(source, max_bytes=self.max_source_bytes)
        text, _ = decode_utf8(data)
        return _raw_document(
            source=source, data=data, text=text, kind="text", parser_name="text", headings=False
        )


def _materialize_local_images(raw: RawDocument, *, max_bytes: int) -> RawDocument:
    """Resolve passive Markdown image references beneath the source directory only."""

    source_root = raw.source_path.parent.resolve()
    assets: list[EmbeddedAsset] = []
    warnings = list(raw.warnings)
    for asset in raw.assets:
        if asset.kind != "figure" or not asset.target:
            assets.append(asset)
            continue
        parsed = urlsplit(asset.target)
        if parsed.scheme or parsed.netloc:
            assets.append(asset.model_copy(update={"safety": "unresolved"}))
            warnings.append(
                ExtractionWarning(
                    code="external_image_not_fetched",
                    message="External Markdown image was inventoried but not fetched.",
                    severity="warning",
                    location=asset.location,
                )
            )
            continue
        candidate = (source_root / unquote(parsed.path)).resolve()
        if candidate == source_root or source_root not in candidate.parents:
            assets.append(asset.model_copy(update={"safety": "unsafe"}))
            warnings.append(
                ExtractionWarning(
                    code="unsafe_image_target",
                    message="Markdown image path escapes the source directory and was not read.",
                    severity="error",
                    location=asset.location,
                )
            )
            continue
        try:
            if not candidate.is_file() or candidate.stat().st_size > max_bytes:
                raise OSError
            payload = candidate.read_bytes()
        except OSError:
            assets.append(asset.model_copy(update={"safety": "unresolved"}))
            warnings.append(
                ExtractionWarning(
                    code="local_image_unavailable",
                    message="Local Markdown image could not be read within the configured limit.",
                    severity="warning",
                    location=asset.location,
                )
            )
            continue
        media_type = media_type_for(candidate)
        if media_type not in {"image/png", "image/jpeg"}:
            assets.append(asset.model_copy(update={"safety": "unsupported"}))
            warnings.append(
                ExtractionWarning(
                    code="unsupported_image_format",
                    message="Only PNG and JPEG source figures can be carried into the final appendix.",
                    severity="warning",
                    location=asset.location,
                )
            )
            continue
        digest = sha256_bytes(payload)
        assets.append(
            asset.model_copy(
                update={
                    "asset_id": f"asset-{digest[:20]}",
                    "name": candidate.name,
                    "media_type": media_type,
                    "digest": digest,
                    "size_bytes": len(payload),
                    "payload": payload,
                    "metadata": {**asset.metadata, "resolved_local": True},
                }
            )
        )
    return raw.model_copy(update={"assets": tuple(assets), "warnings": tuple(warnings)})


def parse_markdown_text(text: str, *, source_name: str = "<memory>") -> RawDocument:
    """Parse in-memory Markdown for tests and deterministic callers."""

    data = text.encode("utf-8")
    source = Path(source_name)
    return _raw_document(
        source=source, data=data, text=text, kind="markdown", parser_name="markdown", headings=True
    )


__all__ = ["MarkdownParser", "TextParser", "parse_markdown_text"]
