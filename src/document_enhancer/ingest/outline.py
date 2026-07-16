"""Deterministic parser outline construction and structural coverage helpers."""

from __future__ import annotations

from document_enhancer.ingest.common import sha256_text

from .models import (
    OutlineSection,
    ParserOutline,
    RawDocument,
    SelectedStructuralView,
    StructuralBlockDisposition,
)


def build_parser_outline(document: RawDocument) -> ParserOutline:
    """Build section boundaries from parser headings while retaining every block ID."""

    blocks = document.blocks
    if not blocks:
        return ParserOutline(warnings=("empty_document",), confidence=0.0)

    headings = [
        (index, block) for index, block in enumerate(blocks) if block.block_type == "heading"
    ]
    if not headings:
        section_id = f"section-{sha256_text(document.source_digest + ':root')[:16]}"
        return ParserOutline(
            title=document.source_name,
            sections=(
                OutlineSection(
                    section_id=section_id,
                    title=document.source_name,
                    level=1,
                    start_span_id=blocks[0].span_id,
                    end_span_id=blocks[-1].span_id,
                    inferred=True,
                    source_block_ids=tuple(block.span_id for block in blocks),
                ),
            ),
            confidence=0.35,
            warnings=("no_parser_headings",),
        )

    sections: list[OutlineSection] = []
    first_heading_index = headings[0][0]
    if first_heading_index > 0:
        preamble = blocks[:first_heading_index]
        sections.append(
            OutlineSection(
                section_id=f"section-{sha256_text(document.source_digest + ':preamble')[:16]}",
                title="Preamble",
                level=1,
                start_span_id=preamble[0].span_id,
                end_span_id=preamble[-1].span_id,
                inferred=True,
                source_block_ids=tuple(block.span_id for block in preamble),
            )
        )

    # A heading owns blocks until the next heading at the same or higher level.
    for heading_position, (start_index, heading) in enumerate(headings):
        end_index = len(blocks) - 1
        for candidate_index, candidate in headings[heading_position + 1 :]:
            if (candidate.level or 1) <= (heading.level or 1):
                end_index = candidate_index - 1
                break
        parent_id: str | None = None
        for prior in reversed(sections):
            if prior.level < (heading.level or 1) and prior.start_span_id in {
                blocks[index].span_id for index, _ in headings if index <= start_index
            }:
                parent_id = prior.section_id
                break
        section_id = f"section-{sha256_text(document.source_digest + ':' + heading.span_id)[:16]}"
        section_blocks = blocks[start_index : end_index + 1]
        sections.append(
            OutlineSection(
                section_id=section_id,
                title=str(heading.attributes.get("title", heading.text.lstrip("# ").strip())),
                level=heading.level or 1,
                start_span_id=heading.span_id,
                end_span_id=blocks[end_index].span_id,
                heading_span_id=heading.span_id,
                parent_id=parent_id,
                source_block_ids=tuple(block.span_id for block in section_blocks),
            )
        )

    title = str(headings[0][1].attributes.get("title", headings[0][1].text))
    confidence = 0.9 if all((block.level or 1) <= 6 for _, block in headings) else 0.5
    return ParserOutline(title=title, sections=tuple(sections), confidence=confidence)


def covered_block_ids(outline: ParserOutline) -> tuple[str, ...]:
    """Return section block IDs in first-seen order, useful for coverage checks."""

    result: list[str] = []
    seen: set[str] = set()
    for section in outline.sections:
        for span_id in section.source_block_ids:
            if span_id not in seen:
                seen.add(span_id)
                result.append(span_id)
    return tuple(result)


def build_parser_view(document: RawDocument, outline: ParserOutline) -> SelectedStructuralView:
    """Build an exactly-once parser-selected view without claiming recovered structure."""

    dispositions: list[StructuralBlockDisposition] = []
    for block in document.blocks:
        candidates = [
            section for section in outline.sections if block.span_id in section.source_block_ids
        ]
        # Nested outline ranges overlap by design.  Assign each block to the narrowest
        # (highest-level number) section for a one-to-one selected-view representation.
        section = max(candidates, key=lambda item: item.level) if candidates else None
        disposition = {
            "heading": "heading",
            "list": "list",
            "table": "table",
            "figure": "figure",
            "caption": "caption",
            "code": "code",
            "page_text": "body",
        }.get(block.block_type, "body")
        dispositions.append(
            StructuralBlockDisposition(
                source_span_id=block.span_id,
                ordinal=block.ordinal,
                disposition=disposition,
                section_id=section.section_id if section else None,
                source_text_digest=block.content_digest,
            )
        )
    ordered = [item.ordinal for item in dispositions]
    expected = list(range(len(document.blocks)))
    validation_passed = (
        ordered == expected
        and len({item.source_span_id for item in dispositions}) == len(document.blocks)
        and set(covered_block_ids(outline)) == {block.span_id for block in document.blocks}
    )
    warnings = () if validation_passed else ("parser_view_coverage_failed",)
    return SelectedStructuralView(
        origin="parser",
        source_digest=document.source_digest,
        outline=outline,
        blocks=tuple(dispositions),
        validation_passed=validation_passed,
        warnings=warnings,
    )


__all__ = ["build_parser_outline", "build_parser_view", "covered_block_ids"]
