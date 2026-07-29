"""Deterministic source-figure persistence, references, and appendix composition."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, cast

from document_enhancer.ingest.models import EmbeddedAsset

from .layout import FINAL_ASSET_PREFIX, SOURCE_ASSET_PREFIX
from .models import FigureOccurrence, RunRecord, Section, SourceFigure
from .store import RunStore, register_artifact

_IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_FIGURE_TOKEN_RE = re.compile(r"\*{0,2}\[FIG-\d{3}\]\*{0,2}")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _extension(media_type: str) -> str:
    return ".png" if media_type == "image/png" else ".jpg"


def final_figure_path(figure: SourceFigure) -> str:
    return f"{FINAL_ASSET_PREFIX}/{figure.figure_id}{_extension(figure.media_type)}"


def _section_for_span(sections: list[Section], span_id: str | None) -> str | None:
    if span_id is None:
        return None
    return next(
        (section.section_id for section in sections if span_id in section.span_ids),
        None,
    )


def _anchor_for_ordinal(blocks: tuple[Any, ...], *, ordinal: int, section: Section | None) -> str:
    allowed = set(section.span_ids) if section else {block.span_id for block in blocks}
    for block in reversed(blocks[: ordinal + 1]):
        text = str(block.text).strip()
        if (
            block.span_id in allowed
            and text
            and block.block_type not in {"figure", "caption", "heading"}
            and not _IMAGE_MARKDOWN_RE.fullmatch(text)
        ):
            return text[:500]
    return ""


def persist_source_figures(
    *,
    store: RunStore,
    record: RunRecord,
    assets: tuple[EmbeddedAsset, ...],
    blocks: tuple[Any, ...],
    sections: list[Section],
) -> tuple[RunRecord, list[SourceFigure]]:
    """Write extractable figures once, in first-occurrence order, and return their manifest."""

    block_by_span = {block.span_id: block for block in blocks}
    candidates: list[EmbeddedAsset] = []
    for asset in assets:
        if not (
            asset.kind == "figure"
            and asset.payload
            and asset.digest
            and asset.media_type in {"image/png", "image/jpeg"}
            and asset.safety == "passive"
        ):
            continue
        payload = bytes(asset.payload)
        if hashlib.sha256(payload).hexdigest() != asset.digest:
            raise ValueError(f"source figure digest mismatch: {asset.name}")
        valid_signature = (
            asset.media_type == "image/png"
            and payload.startswith(b"\x89PNG\r\n\x1a\n")
            or asset.media_type == "image/jpeg"
            and payload.startswith(b"\xff\xd8\xff")
        )
        if not valid_signature:
            raise ValueError(f"source figure has invalid {asset.media_type} bytes: {asset.name}")
        candidates.append(asset)

    def first_ordinal(asset: EmbeddedAsset) -> int:
        occurrences = asset.metadata.get("occurrences")
        if isinstance(occurrences, list) and occurrences:
            value = occurrences[0]
            if isinstance(value, dict):
                return int(value.get("ordinal", 10**9))
        block = block_by_span.get(asset.source_span_id or "")
        return int(block.ordinal) if block else 10**9

    candidates.sort(key=lambda asset: (first_ordinal(asset), asset.asset_id))
    grouped: dict[str, list[EmbeddedAsset]] = {}
    for asset in candidates:
        grouped.setdefault(str(asset.digest), []).append(asset)

    figures: list[SourceFigure] = []
    for figure_index, grouped_assets in enumerate(grouped.values(), start=1):
        figure_id = f"FIG-{figure_index:03d}"
        primary = grouped_assets[0]
        occurrences: list[FigureOccurrence] = []
        seen_occurrences: set[tuple[str | None, int]] = set()
        for asset in grouped_assets:
            raw_occurrences = asset.metadata.get("occurrences")
            values = raw_occurrences if isinstance(raw_occurrences, list) else []
            if not values:
                block = block_by_span.get(asset.source_span_id or "")
                values = [
                    {
                        "source_span_id": asset.source_span_id,
                        "ordinal": block.ordinal if block else 0,
                        "location": (
                            asset.location.model_dump(mode="json") if asset.location else {}
                        ),
                    }
                ]
            for value in values:
                if not isinstance(value, dict):
                    continue
                span_id = str(value.get("source_span_id") or "") or None
                ordinal_value = value.get("ordinal")
                ordinal = ordinal_value if isinstance(ordinal_value, int) else 0
                key = (span_id, ordinal)
                if key in seen_occurrences:
                    continue
                seen_occurrences.add(key)
                section_id = _section_for_span(sections, span_id)
                section = next(
                    (item for item in sections if item.section_id == section_id),
                    None,
                )
                location = value.get("location")
                occurrences.append(
                    FigureOccurrence(
                        source_span_id=span_id,
                        section_id=section_id,
                        ordinal=ordinal,
                        location=dict(location) if isinstance(location, dict) else {},
                        anchor_text=_anchor_for_ordinal(blocks, ordinal=ordinal, section=section),
                    )
                )
        source_path = f"{SOURCE_ASSET_PREFIX}/{figure_id}{_extension(str(primary.media_type))}"
        artifact = store.write_bytes(
            record.run_id,
            source_path,
            bytes(primary.payload or b""),
            media_type=str(primary.media_type),
        )
        record = register_artifact(record, f"source.figure.{figure_id}", artifact)
        caption = str(primary.metadata.get("caption") or primary.metadata.get("label") or "")
        figures.append(
            SourceFigure(
                figure_id=figure_id,
                asset_id=primary.asset_id,
                name=primary.name,
                media_type=cast(Literal["image/png", "image/jpeg"], primary.media_type),
                sha256=str(primary.digest),
                size_bytes=int(primary.size_bytes or 0),
                source_path=source_path,
                caption=caption.strip(),
                occurrences=sorted(occurrences, key=lambda item: item.ordinal),
            )
        )
    return record, figures


def materialize_final_figures(
    *, store: RunStore, record: RunRecord, figures: list[SourceFigure]
) -> RunRecord:
    """Copy immutable source figures to stable final paths used by both renderers."""

    for figure in figures:
        payload = store.read_bytes(record.run_id, figure.source_path)
        if store.sha256(payload) != figure.sha256:
            raise ValueError(f"source figure digest changed: {figure.figure_id}")
        artifact = store.write_bytes(
            record.run_id,
            final_figure_path(figure),
            payload,
            media_type=figure.media_type,
        )
        record = register_artifact(record, f"output.figure.{figure.figure_id}", artifact)
    return record


def _title_matches(expected: str, actual: str) -> bool:
    expected_tokens = {
        token for token in re.findall(r"[a-z0-9]+", expected.lower()) if len(token) >= 3
    }
    actual_tokens = set(re.findall(r"[a-z0-9]+", actual.lower()))
    return bool(expected_tokens) and expected_tokens <= actual_tokens


def _insert_at_section_end(text: str, title: str, marker: str) -> tuple[str, bool]:
    headings = list(_HEADING_RE.finditer(text))
    for index, heading in enumerate(headings):
        if not _title_matches(title, heading.group(2)):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        addition = f"\n\nRelated source screenshot: {marker}.\n"
        return text[:end].rstrip() + addition + "\n" + text[end:].lstrip(), True
    return text, False


def compose_figure_appendix(
    body: str, *, figures: list[SourceFigure], sections: list[Section]
) -> str:
    """Place visible references and append each approved source figure exactly once."""

    if not figures:
        return body.rstrip() + "\n"
    body = _IMAGE_MARKDOWN_RE.sub("", body)
    body = _FIGURE_TOKEN_RE.sub("", body)
    section_by_id = {section.section_id: section for section in sections}
    unplaced: list[SourceFigure] = []
    for figure in figures:
        marker = f"**[{figure.figure_id}]**"
        anchor = next(
            (item.anchor_text for item in figure.occurrences if item.anchor_text),
            "",
        )
        if anchor and body.count(anchor) == 1:
            body = body.replace(anchor, f"{anchor} {marker}", 1)
            continue
        occurrence = figure.occurrences[0] if figure.occurrences else None
        section = section_by_id.get(occurrence.section_id if occurrence else None)
        if section:
            body, placed = _insert_at_section_end(body, section.title, marker)
            if placed:
                continue
        unplaced.append(figure)
    if unplaced:
        markers = ", ".join(f"**[{figure.figure_id}]**" for figure in unplaced)
        body = body.rstrip() + f"\n\n## Source figure references\n\n{markers}\n"

    used_letters = {
        match.group(1).upper()
        for match in re.finditer(r"\bAppendix\s+([A-Z])\b", body, re.IGNORECASE)
    }
    appendix_letter = next(
        (letter for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if letter not in used_letters),
        "Z",
    )
    lines = [
        body.rstrip(),
        "",
        f"## Appendix {appendix_letter} — Source screenshots",
        "",
        (
            "These screenshots are non-authoritative visual aids preserved from the source "
            "document. The written procedure remains authoritative."
        ),
        "",
    ]
    for figure in figures:
        occurrence = figure.occurrences[0] if figure.occurrences else None
        section = section_by_id.get(occurrence.section_id if occurrence else None)
        caption = figure.caption or (
            f"Source screenshot from {section.title}" if section else "Source screenshot"
        )
        lines.extend(
            [
                f"### [{figure.figure_id}] {caption}",
                "",
                f"![{caption}](../{final_figure_path(figure)})",
                "",
            ]
        )
        if section:
            lines.extend([f"Source section: {section.title}.", ""])
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "compose_figure_appendix",
    "final_figure_path",
    "materialize_final_figures",
    "persist_source_figures",
]
