"""Immutable, loss-aware source document and block contracts."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.enums import SourceBlockType
from document_enhancer.domain.ids import (
    allocate_span_id,
    ensure_unique_ids,
    validate_sha256,
    validate_span_id,
)
from document_enhancer.domain.provenance import SourceLocation


class SourceBlock(StrictModel):
    """One immutable source block with a stable span identifier."""

    span_id: StrictStr | None = None
    ordinal: StrictInt = Field(ge=0)
    block_type: SourceBlockType
    text: StrictStr
    source_digest: StrictStr
    location: SourceLocation | None = None
    parent_span_id: StrictStr | None = None
    heading_level: StrictInt | None = Field(default=None, ge=1, le=9)
    text_digest: StrictStr | None = None
    substantive: StrictBool = True
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def allocate_stable_fields(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values
        data = dict(values)
        source_digest = data.get("source_digest")
        text = data.get("text")
        ordinal = data.get("ordinal")
        block_type = data.get("block_type")
        if source_digest and text is not None and data.get("text_digest") is None:
            data["text_digest"] = hashlib.sha256(str(text).encode("utf-8")).hexdigest()
        if (
            data.get("span_id") is None
            and source_digest
            and text is not None
            and ordinal is not None
            and block_type is not None
        ):
            block_value = getattr(block_type, "value", block_type)
            data["span_id"] = allocate_span_id(
                str(source_digest), int(ordinal), str(block_value), str(text)
            )
        return data

    @field_validator("source_digest", "text_digest")
    @classmethod
    def validate_digests(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else validate_sha256(value)

    @field_validator("span_id", "parent_span_id")
    @classmethod
    def validate_spans(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else validate_span_id(value)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="source block text")

    @model_validator(mode="after")
    def validate_checksum(self) -> SourceBlock:
        expected = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.text_digest != expected:
            raise ValueError(f"text_digest does not match source block {self.span_id}")
        if self.block_type is SourceBlockType.HEADING and self.heading_level is None:
            raise ValueError("heading blocks require heading_level")
        return self


SourceSpan = SourceBlock
DocumentBlock = SourceBlock


class RawDocument(StrictModel):
    """Ordered parser output; later structure recovery must not mutate it."""

    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    source_digest: StrictStr
    media_type: StrictStr
    source_path: StrictStr | None = None
    size_bytes: StrictInt = Field(ge=0)
    blocks: list[SourceBlock]
    extraction_warnings: list[StrictStr] = Field(default_factory=list)
    parser_name: StrictStr
    parser_version: StrictStr

    @field_validator("source_digest")
    @classmethod
    def validate_source_digest(cls, value: StrictStr) -> StrictStr:
        return validate_sha256(value)

    @field_validator("media_type", "parser_name", "parser_version")
    @classmethod
    def validate_metadata(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="source metadata")

    @model_validator(mode="after")
    def validate_block_order(self) -> RawDocument:
        if not self.blocks:
            raise ValueError("raw document must contain at least one block")
        if any(block.source_digest != self.source_digest for block in self.blocks):
            raise ValueError("every block must use the RawDocument source_digest")
        ensure_unique_ids(block.span_id for block in self.blocks if block.span_id is not None)
        ordinals = [block.ordinal for block in self.blocks]
        if ordinals != list(range(len(ordinals))):
            raise ValueError("raw block ordinals must be contiguous and ordered from zero")
        return self


SourceDocument = RawDocument


class StructuralSection(StrictModel):
    section_id: StrictStr = Field(pattern=r"^(SEC|PROV-SEC)-[A-Z0-9-]+$")
    title: StrictStr
    level: StrictInt = Field(ge=1, le=9)
    start_span_id: StrictStr
    end_span_id: StrictStr
    source_heading: StrictStr | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    inferred: StrictBool = False

    @field_validator("start_span_id", "end_span_id")
    @classmethod
    def validate_boundary_span(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="section title")


class StructuralView(StrictModel):
    origin: Literal["parser", "llm_recovered"]
    sections: list[StructuralSection]
    confidence: float = Field(ge=0.0, le=1.0)
    validation_passed: StrictBool
    validation_errors: list[StrictStr] = Field(default_factory=list)


class NormalizedDocument(StrictModel):
    """Raw source plus the selected, validated structural view."""

    raw: RawDocument
    structural_view: StructuralView
    normalized_markdown: StrictStr
    asset_digests: dict[StrictStr, StrictStr] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_selected_view(self) -> NormalizedDocument:
        if not self.structural_view.validation_passed:
            raise ValueError("a NormalizedDocument requires a validated structural_view")
        raw_span_ids = {block.span_id for block in self.raw.blocks}
        for section in self.structural_view.sections:
            if section.start_span_id not in raw_span_ids or section.end_span_id not in raw_span_ids:
                raise ValueError(
                    f"structural section {section.section_id} references an unknown span"
                )
        return self


def block_text(blocks: Iterable[SourceBlock]) -> str:
    return "\n\n".join(block.text for block in blocks)


__all__ = [
    "DocumentBlock",
    "NormalizedDocument",
    "RawDocument",
    "SourceBlock",
    "SourceDocument",
    "SourceSpan",
    "StructuralSection",
    "StructuralView",
    "block_text",
]
