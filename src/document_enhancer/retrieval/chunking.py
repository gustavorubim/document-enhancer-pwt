"""Deterministic, Markdown-aware chunking for canonical final documents."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from .models import RagChunk

CHUNKER_VERSION = "markdown-sections-v1"
_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class _Section:
    ordinal: int
    start: int
    end: int
    heading_path: tuple[str, ...]


def chunk_markdown(
    markdown: str,
    *,
    run_id: str,
    bundle_path: Path,
    source_digest: str,
    final_digest: str,
    chunk_size: int = 2400,
    chunk_overlap: int = 300,
) -> list[RagChunk]:
    """Split by heading hierarchy, then recursively split only oversized sections."""

    if chunk_overlap >= chunk_size:
        raise ValueError("chunk overlap must be smaller than chunk size")
    sections, title = _sections(markdown)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        add_start_index=True,
    )
    chunks: list[RagChunk] = []
    for section in sections:
        section_text = markdown[section.start : section.end]
        pieces = _section_pieces(
            section_text,
            chunk_size=chunk_size,
            splitter=splitter,
        )
        for chunk_ordinal, (text, local_start) in enumerate(pieces):
            if not text.strip():
                continue
            clean_text = text.strip()
            local_start = max(local_start, section_text.find(clean_text))
            start = section.start + max(local_start, 0)
            end = start + len(clean_text)
            content_digest = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
            identity = "|".join(
                (
                    CHUNKER_VERSION,
                    final_digest,
                    "/".join(section.heading_path),
                    str(section.ordinal),
                    str(chunk_ordinal),
                    content_digest,
                )
            )
            chunk_id = f"CHK-{hashlib.sha256(identity.encode()).hexdigest()[:20].upper()}"
            chunks.append(
                RagChunk(
                    chunk_id=chunk_id,
                    run_id=run_id,
                    bundle_path=str(bundle_path),
                    source_digest=source_digest,
                    final_digest=final_digest,
                    document_title=title,
                    heading_path=section.heading_path,
                    section_ordinal=section.ordinal,
                    chunk_ordinal=chunk_ordinal,
                    start_index=start,
                    end_index=end,
                    text=clean_text,
                )
            )
    return chunks


def _section_pieces(
    text: str,
    *,
    chunk_size: int,
    splitter: RecursiveCharacterTextSplitter,
) -> list[tuple[str, int]]:
    """Pack complete Markdown blocks and split only a block that cannot fit."""

    stripped = text.strip()
    if not stripped:
        return []
    if len(text) <= chunk_size:
        return [(stripped, text.find(stripped))]
    pieces: list[tuple[str, int]] = []
    packed_start: int | None = None
    packed_end = 0

    def flush() -> None:
        nonlocal packed_start, packed_end
        if packed_start is None:
            return
        raw = text[packed_start:packed_end]
        clean = raw.strip()
        if clean:
            pieces.append((clean, packed_start + raw.find(clean)))
        packed_start = None
        packed_end = 0

    for block_start, block_end in _markdown_block_ranges(text):
        raw_block = text[block_start:block_end]
        clean_block = raw_block.strip()
        if not clean_block:
            continue
        clean_start = block_start + raw_block.find(clean_block)
        clean_end = clean_start + len(clean_block)
        proposed_start = packed_start if packed_start is not None else clean_start
        if clean_end - proposed_start <= chunk_size:
            packed_start = proposed_start
            packed_end = clean_end
            continue
        flush()
        if len(clean_block) <= chunk_size:
            packed_start = clean_start
            packed_end = clean_end
            continue
        for document in splitter.create_documents([clean_block]):
            piece = document.page_content.strip()
            local_start = int(document.metadata.get("start_index", 0))
            local_start = max(local_start, clean_block.find(piece))
            pieces.append((piece, clean_start + max(local_start, 0)))
    flush()
    return pieces


def _markdown_block_ranges(text: str) -> list[tuple[int, int]]:
    """Return contiguous paragraph/fence ranges without splitting fenced blocks."""

    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(lines):
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            break
        start_index = index
        fence = re.match(r"\s*(```+|~~~+)", lines[index])
        if fence:
            marker = fence.group(1)[0]
            index += 1
            while index < len(lines):
                if re.match(rf"\s*{re.escape(marker)}{{3,}}\s*$", lines[index]):
                    index += 1
                    break
                index += 1
        else:
            index += 1
            while index < len(lines) and lines[index].strip():
                index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        start = offsets[start_index]
        end = offsets[index] if index < len(offsets) else len(text)
        ranges.append((start, end))
    return ranges


def _sections(markdown: str) -> tuple[list[_Section], str]:
    headings = list(_HEADING_RE.finditer(markdown))
    if not headings:
        title = "Untitled document"
        return ([_Section(0, 0, len(markdown), (title,))] if markdown.strip() else []), title
    title = next((match.group(2).strip() for match in headings if len(match.group(1)) == 1), None)
    title = title or headings[0].group(2).strip()
    stack: list[str] = []
    result: list[_Section] = []
    for index, match in enumerate(headings):
        level = len(match.group(1))
        stack = stack[: level - 1]
        stack.append(match.group(2).strip())
        start = 0 if index == 0 else match.start()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        result.append(_Section(index, start, end, tuple(stack)))
    return result, title


__all__ = ["CHUNKER_VERSION", "chunk_markdown"]
