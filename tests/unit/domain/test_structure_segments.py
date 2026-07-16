from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from document_enhancer.domain.analysis import (
    BlockDisposition,
    BlockSegment,
    RecoveredSection,
    StructureRecoveryProposal,
)
from document_enhancer.domain.enums import SourceBlockType, StructureDisposition
from document_enhancer.domain.ids import allocate_segment_id
from document_enhancer.domain.serialization import (
    model_from_json,
    model_from_yaml,
    model_to_json,
    model_to_yaml,
)
from document_enhancer.domain.source import RawDocument, SourceBlock

SOURCE_DIGEST = "b" * 64


def _raw(text: str) -> RawDocument:
    block = SourceBlock(
        ordinal=0,
        block_type=SourceBlockType.PARAGRAPH,
        text=text,
        source_digest=SOURCE_DIGEST,
    )
    return RawDocument(
        document_id="DOC-SEGMENT-0001",
        source_digest=SOURCE_DIGEST,
        media_type="text/markdown",
        size_bytes=len(text.encode()),
        blocks=[block],
        parser_name="segment-fixture",
        parser_version="1",
    )


def _segment(
    span_id: str,
    text: str,
    start: int,
    end: int,
    *,
    digest: str | None = None,
    section_id: str | None = None,
) -> BlockSegment:
    slice_digest = digest or hashlib.sha256(text[start:end].encode()).hexdigest()
    return BlockSegment(
        segment_id=allocate_segment_id(span_id, start, end, slice_digest),
        char_start=start,
        char_end=end,
        disposition=StructureDisposition.BODY,
        section_id=section_id,
        confidence=0.95,
        rationale="deterministic test split",
        slice_sha256=slice_digest,
    )


def _proposal(raw: RawDocument, segments: list[BlockSegment] | None) -> StructureRecoveryProposal:
    block = raw.blocks[0]
    section = RecoveredSection(
        section_id="SEC-SEGMENT-001",
        label="Recovered body",
        level=1,
        start_span_id=block.span_id or "",
        end_span_id=block.span_id or "",
        confidence=0.95,
    )
    return StructureRecoveryProposal(
        recovery_id="RECOVERY-SEGMENT-001",
        document_id=raw.document_id,
        source_digest=raw.source_digest,
        confidence=0.95,
        sections=[section],
        dispositions=[
            BlockDisposition(
                span_id=block.span_id or "",
                disposition=StructureDisposition.BODY,
                source_text_digest=block.text_digest or "",
                confidence=0.95,
                segments=segments,
            )
        ],
        model="fake",
        prompt_id="structure.recover",
    )


def test_segment_id_allocator_is_stable_and_slice_sensitive() -> None:
    digest = hashlib.sha256("α".encode()).hexdigest()
    segment_id = allocate_segment_id("SPAN-ABCDEFGH", 0, 1, digest)
    assert segment_id == allocate_segment_id("SPAN-ABCDEFGH", 0, 1, digest)
    assert segment_id.startswith("SEG-")
    assert segment_id != allocate_segment_id("SPAN-ABCDEFGH", 0, 2, digest)
    assert segment_id != allocate_segment_id("SPAN-ABCDEFGH", 0, 1, "a" * 64)


def test_unicode_segments_use_python_character_offsets_and_round_trip_json_yaml() -> None:
    raw = _raw("αβγ — café")
    text = raw.blocks[0].text
    cut = 3
    segments = [
        _segment(raw.blocks[0].span_id or "", text, 0, cut),
        _segment(raw.blocks[0].span_id or "", text, cut, len(text)),
    ]
    proposal = _proposal(raw, segments)

    validation = proposal.validate_against(raw)
    assert validation.passed
    assert [segment.char_end for segment in proposal.dispositions[0].segments or []] == [3, 10]
    assert (
        model_from_json(StructureRecoveryProposal, model_to_json(proposal)).model_dump()
        == proposal.model_dump()
    )
    assert (
        model_from_yaml(StructureRecoveryProposal, model_to_yaml(proposal)).model_dump()
        == proposal.model_dump()
    )


def test_unsplit_disposition_remains_backward_compatible() -> None:
    raw = _raw("unsplit source")
    block = raw.blocks[0]
    proposal = _proposal(raw, None)
    proposal.dispositions[0] = BlockDisposition(
        span_id=block.span_id or "",
        disposition=StructureDisposition.BODY,
        source_text_digest=block.text_digest or "",
        confidence=0.9,
    )
    assert proposal.validate_against(raw).passed


@pytest.mark.parametrize(
    ("ranges", "message"),
    [
        ([(0, 3), (4, 10)], "gap"),
        ([(0, 4), (3, 10)], "overlaps"),
        ([(3, 10), (0, 3)], "source order"),
        ([(0, 3), (3, 11)], "beyond original text length"),
    ],
)
def test_invalid_ranges_fail_closed_with_precise_errors(
    ranges: list[tuple[int, int]], message: str
) -> None:
    raw = _raw("αβγ — café")
    text = raw.blocks[0].text
    proposal = _proposal(
        raw, [_segment(raw.blocks[0].span_id or "", text, *bounds) for bounds in ranges]
    )
    validation = proposal.validate_against(raw)
    assert not validation.passed
    assert any(message in error for error in validation.errors)


def test_bad_digest_or_deterministic_id_fails_closed() -> None:
    raw = _raw("αβγ — café")
    text = raw.blocks[0].text
    bad_digest = "a" * 64
    bad_segment = BlockSegment(
        segment_id=allocate_segment_id(raw.blocks[0].span_id or "", 0, 3, bad_digest),
        char_start=0,
        char_end=3,
        disposition=StructureDisposition.BODY,
        confidence=0.9,
        slice_sha256=bad_digest,
    )
    good_segment = _segment(raw.blocks[0].span_id or "", text, 3, len(text))
    validation = _proposal(raw, [bad_segment, good_segment]).validate_against(raw)
    assert not validation.passed
    assert any("slice_sha256" in error for error in validation.errors)

    wrong_id = bad_segment.model_copy(
        update={
            "segment_id": "SEG-0000000000000000",
            "slice_sha256": hashlib.sha256(text[:3].encode()).hexdigest(),
        }
    )
    validation = _proposal(raw, [wrong_id, good_segment]).validate_against(raw)
    assert not validation.passed
    assert any("deterministic expected id" in error for error in validation.errors)


def test_unknown_segment_section_reference_fails_precisely() -> None:
    raw = _raw("αβγ — café")
    text = raw.blocks[0].text
    segments = [
        _segment(raw.blocks[0].span_id or "", text, 0, 3, section_id="SEC-UNKNOWN-001"),
        _segment(raw.blocks[0].span_id or "", text, 3, len(text)),
    ]
    validation = _proposal(raw, segments).validate_against(raw)
    assert not validation.passed
    assert any(
        "segment" in error and "unknown section SEC-UNKNOWN-001" in error
        for error in validation.errors
    )


def test_duplicate_segment_ids_fail_at_disposition_construction() -> None:
    segment = BlockSegment(
        segment_id="SEG-0000000000000001",
        char_start=0,
        char_end=1,
        disposition=StructureDisposition.BODY,
        confidence=0.9,
        slice_sha256="a" * 64,
    )
    with pytest.raises(ValidationError, match="duplicate IDs"):
        BlockDisposition(
            span_id="SPAN-ABCDEFGH",
            disposition=StructureDisposition.BODY,
            source_text_digest="a" * 64,
            confidence=0.9,
            segments=[segment, segment.model_copy()],
        )


def test_multibyte_utf8_byte_offsets_are_rejected_as_out_of_range() -> None:
    raw = _raw("αβ")
    text = raw.blocks[0].text
    whole_digest = hashlib.sha256(text.encode()).hexdigest()
    byte_style = [
        _segment(raw.blocks[0].span_id or "", text, 0, 2, digest=whole_digest),
        _segment(raw.blocks[0].span_id or "", text, 2, 4, digest="a" * 64),
    ]
    validation = _proposal(raw, byte_style).validate_against(raw)
    assert not validation.passed
    assert any("beyond original text length" in error for error in validation.errors)


def test_segment_shape_and_offset_unit_are_strict() -> None:
    with pytest.raises(ValidationError, match="at least 2"):
        BlockDisposition(
            span_id="SPAN-ABCDEFGH",
            disposition=StructureDisposition.BODY,
            source_text_digest="a" * 64,
            confidence=0.9,
            segments=[
                BlockSegment(
                    segment_id="SEG-0000000000000001",
                    char_start=0,
                    char_end=1,
                    disposition=StructureDisposition.BODY,
                    confidence=0.9,
                    slice_sha256="a" * 64,
                )
            ],
        )
    with pytest.raises(ValidationError, match="python_characters"):
        BlockSegment.model_validate(
            {
                "segment_id": "SEG-0000000000000001",
                "char_start": 0,
                "char_end": 1,
                "offset_unit": "utf8_bytes",
                "disposition": StructureDisposition.BODY,
                "confidence": 0.9,
                "slice_sha256": "a" * 64,
            }
        )
