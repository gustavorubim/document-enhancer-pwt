"""Shared deterministic helpers for input adapters."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import unicodedata
from pathlib import Path
from typing import Any, Literal

from document_enhancer.errors import UnsupportedInputError

from .models import EmbeddedAsset, ExtractionWarning, RawBlock, SourceLocation

DEFAULT_MAX_SOURCE_BYTES = 25 * 1024 * 1024
_FORMULA_RE = re.compile(r"(?s)(\$\$.*?\$\$|\\\(.*?\\\)|\\\[.*?\\\])")
_INLINE_FORMULA_RE = re.compile(r"(?<!\$)\$(?!\s)([^$\n]+?)(?<!\s)\$")
_LINK_RE = re.compile(r"!?(?:\[([^\]]*)\])\(([^)\s]+)(?:\s+[^)]*)?\)")
_AUTOLINK_RE = re.compile(r"<((?:https?://|mailto:)[^>]+)>")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def normalize_text(value: str) -> str:
    """Normalize display text without changing the immutable raw block."""

    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    return "\n".join(line.rstrip() for line in value.split("\n")).strip()


def read_source(source: Path, *, max_bytes: int = DEFAULT_MAX_SOURCE_BYTES) -> bytes:
    """Read a regular local file with a deterministic size guard."""

    try:
        if not source.is_file():
            raise UnsupportedInputError(f"Source is not a regular file: {source.name}")
        size = source.stat().st_size
        if size > max_bytes:
            raise UnsupportedInputError(
                f"Source exceeds the configured size limit ({max_bytes} bytes)",
                detail=f"size_bytes={size}; source={source.name}",
            )
        return source.read_bytes()
    except OSError as exc:
        raise UnsupportedInputError(f"Unable to read source: {source.name}") from exc


def decode_utf8(data: bytes) -> tuple[str, bool]:
    """Decode UTF-8 and report whether replacement characters were required."""

    try:
        return data.decode("utf-8-sig"), False
    except UnicodeDecodeError:
        return data.decode("utf-8-sig", errors="replace"), True


def media_type_for(source: Path) -> str:
    suffix = source.suffix.lower()
    return {
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf": "application/pdf",
    }.get(suffix, mimetypes.guess_type(source.name)[0] or "application/octet-stream")


def line_offsets(text: str) -> tuple[int, ...]:
    """Return zero-based character offsets for the start of each one-based line."""

    offsets = [0]
    for index, char in enumerate(text):
        if char == "\n":
            offsets.append(index + 1)
    return tuple(offsets)


def location_for_lines(
    *,
    kind: Literal["markdown", "text", "docx", "pdf"],
    text: str,
    offsets: tuple[int, ...],
    start_line: int,
    end_line: int,
) -> SourceLocation:
    start_index = offsets[start_line - 1]
    end_index = offsets[end_line] if end_line < len(offsets) else len(text)
    return SourceLocation(
        kind=kind,  # type: ignore[arg-type]
        line_start=start_line,
        line_end=end_line,
        char_start=start_index,
        char_end=end_index,
    )


def span_id(
    *, source_digest: str, ordinal: int, block_type: str, text: str, location: SourceLocation
) -> str:
    """Create a stable source span ID from immutable source coordinates and content."""

    identity = canonical_json(
        {
            "source": source_digest,
            "ordinal": ordinal,
            "type": block_type,
            "text": text,
            "location": location.model_dump(mode="json"),
        }
    )
    return f"span-{sha256_bytes(identity)[:24]}"


def block_digest(block_type: str, text: str, location: SourceLocation) -> str:
    return sha256_bytes(
        canonical_json(
            {"type": block_type, "text": text, "location": location.model_dump(mode="json")}
        )
    )


def _asset_location(block: RawBlock, start: int, end: int) -> SourceLocation:
    location = block.location
    if location.char_start is None:
        return location
    return location.model_copy(
        update={"char_start": location.char_start + start, "char_end": location.char_start + end}
    )


def inventory_text_assets(
    blocks: tuple[RawBlock, ...],
) -> tuple[tuple[ExtractionWarning, ...], tuple[EmbeddedAsset, ...]]:
    """Inventory links/formulas without resolving or fetching active targets."""

    assets: list[EmbeddedAsset] = []
    warnings: list[ExtractionWarning] = []
    for block in blocks:
        text = block.text
        for index, match in enumerate(_LINK_RE.finditer(text)):
            image = match.group(0).startswith("!")
            target = match.group(2)
            safety = "passive"
            code = ""
            if target.lower().startswith(("javascript:", "data:", "file:", "vbscript:")):
                safety = "unsafe"
                code = "unsafe_link_target"
            asset = EmbeddedAsset(
                asset_id=f"asset-{sha256_text(f'{block.span_id}:link:{index}')[:20]}",
                kind="figure" if image else "link",
                name=match.group(1) or target,
                source_span_id=block.span_id,
                location=_asset_location(block, match.start(), match.end()),
                safety=safety,  # type: ignore[arg-type]
                target=target,
                metadata={"label": match.group(1) or "", "syntax": "markdown"},
            )
            assets.append(asset)
            if code:
                warnings.append(
                    ExtractionWarning(
                        code=code,
                        message="Active or local link target was inventoried but not resolved.",
                        severity="error",
                        location=asset.location,
                    )
                )
        for index, match in enumerate(_AUTOLINK_RE.finditer(text)):
            target = match.group(1)
            assets.append(
                EmbeddedAsset(
                    asset_id=f"asset-{sha256_text(f'{block.span_id}:autolink:{index}')[:20]}",
                    kind="link",
                    name=target,
                    source_span_id=block.span_id,
                    location=_asset_location(block, match.start(), match.end()),
                    safety="passive",
                    target=target,
                    metadata={"syntax": "autolink"},
                )
            )
        formula_matches = list(_FORMULA_RE.finditer(text)) + list(_INLINE_FORMULA_RE.finditer(text))
        for index, match in enumerate(sorted(formula_matches, key=lambda item: item.start())):
            assets.append(
                EmbeddedAsset(
                    asset_id=f"asset-{sha256_text(f'{block.span_id}:formula:{index}')[:20]}",
                    kind="formula",
                    name=f"formula-{index + 1}",
                    source_span_id=block.span_id,
                    location=_asset_location(block, match.start(), match.end()),
                    safety="passive",
                    target=match.group(0),
                    metadata={"format": "inline_or_display_math"},
                )
            )
    return tuple(warnings), tuple(assets)


__all__ = [
    "DEFAULT_MAX_SOURCE_BYTES",
    "block_digest",
    "canonical_json",
    "decode_utf8",
    "inventory_text_assets",
    "line_offsets",
    "location_for_lines",
    "media_type_for",
    "normalize_text",
    "read_source",
    "sha256_bytes",
    "sha256_text",
    "span_id",
]
