"""Immutable, loss-aware contracts produced by deterministic ingestion.

The models in this module deliberately live behind the WT0 parser port.  They are
small enough to be adapted to the richer WT1 domain contracts while keeping the
source bytes, source order, and provenance stable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Return a timezone-aware timestamp for artifact metadata."""

    return datetime.now(UTC)


class FrozenContract(BaseModel):
    """Base class for contracts that must not be mutated after parsing."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_assignment=True)


class SourceLocation(FrozenContract):
    """Best-effort source coordinates; absent coordinates are represented as null."""

    kind: Literal["markdown", "text", "docx", "pdf"]
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    page: int | None = Field(default=None, ge=1)
    paragraph_index: int | None = Field(default=None, ge=0)
    table_index: int | None = Field(default=None, ge=0)
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)
    xml_path: str | None = None
    relationship_id: str | None = None


class ExtractionWarning(FrozenContract):
    """A visible parser limitation or lossy/unsafe construct classification."""

    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"
    location: SourceLocation | None = None
    source_digest: str | None = None


class EmbeddedAsset(FrozenContract):
    """Inventory entry for a figure, link, formula, or embedded file."""

    asset_id: str
    kind: Literal["figure", "link", "formula", "embedded_file"]
    name: str
    source_span_id: str | None = None
    location: SourceLocation | None = None
    media_type: str | None = None
    digest: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    safety: Literal["passive", "unsafe", "unsupported", "unresolved"] = "passive"
    relationship_id: str | None = None
    target: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawBlock(FrozenContract):
    """An immutable ordered source block with exact extracted text."""

    span_id: str
    ordinal: int = Field(ge=0)
    block_type: str
    text: str
    location: SourceLocation
    content_digest: str
    level: int | None = Field(default=None, ge=1, le=6)
    style: str | None = None
    list_kind: Literal["ordered", "unordered", "task", "none"] = "none"
    list_depth: int | None = Field(default=None, ge=0)
    list_marker: str | None = None
    caption: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)


class RawDocument(FrozenContract):
    """Loss-aware parser output; blocks are the immutable source of truth."""

    source_path: Path
    source_name: str
    media_type: str
    size_bytes: int = Field(ge=0)
    source_digest: str
    blocks: tuple[RawBlock, ...] = ()
    warnings: tuple[ExtractionWarning, ...] = ()
    assets: tuple[EmbeddedAsset, ...] = ()
    parser_name: str
    parser_version: str
    scanned: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutlineSection(FrozenContract):
    """A parser-derived section boundary expressed only in source spans."""

    section_id: str
    title: str
    level: int = Field(ge=1, le=6)
    start_span_id: str
    end_span_id: str
    heading_span_id: str | None = None
    parent_id: str | None = None
    inferred: bool = False
    source_block_ids: tuple[str, ...] = ()


class ParserOutline(FrozenContract):
    """Best-effort outline; it never replaces the raw block sequence."""

    sections: tuple[OutlineSection, ...] = ()
    title: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    warnings: tuple[str, ...] = ()


class StructuralBlockSegment(FrozenContract):
    """Validated character-slice metadata retained in a selected structural view."""

    segment_id: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    offset_unit: Literal["python_characters"] = "python_characters"
    disposition: str
    section_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str | None = None
    slice_sha256: str


class StructuralBlockDisposition(FrozenContract):
    """One deterministic classification in a selected structural view."""

    source_span_id: str
    ordinal: int = Field(ge=0)
    disposition: str
    section_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_text_digest: str
    segments: tuple[StructuralBlockSegment, ...] | None = None


class SelectedStructuralView(FrozenContract):
    """Persisted structural selection kept separate from raw blocks and the outline."""

    origin: Literal["parser", "llm_recovered"]
    source_digest: str
    outline: ParserOutline
    blocks: tuple[StructuralBlockDisposition, ...]
    validation_passed: bool
    warnings: tuple[str, ...] = ()


class StructureQualityReport(FrozenContract):
    """Deterministic structure signals used to route later recovery."""

    substantive_block_count: int = Field(ge=0)
    heading_count: int = Field(ge=0)
    heading_density: float = Field(ge=0.0, le=1.0)
    heading_style_consistency: float = Field(ge=0.0, le=1.0)
    numbering_continuity: float = Field(ge=0.0, le=1.0)
    toc_mismatch_count: int = Field(ge=0)
    layout_table_score: float = Field(ge=0.0, le=1.0)
    repeated_furniture_count: int = Field(ge=0)
    orphan_block_ratio: float = Field(ge=0.0, le=1.0)
    long_block_ratio: float = Field(ge=0.0, le=1.0)
    parser_warning_count: int = Field(ge=0)
    parser_error_count: int = Field(ge=0)
    structure_score: float = Field(ge=0.0, le=1.0)
    warnings: tuple[str, ...] = ()


class RecoveryThresholds(FrozenContract):
    """Configurable, deterministic routing thresholds."""

    minimum_structure_score: float = Field(default=0.62, ge=0.0, le=1.0)
    minimum_heading_consistency: float = Field(default=0.70, ge=0.0, le=1.0)
    maximum_toc_mismatches: int = Field(default=0, ge=0)
    maximum_orphan_ratio: float = Field(default=0.20, ge=0.0, le=1.0)
    maximum_long_block_ratio: float = Field(default=0.35, ge=0.0, le=1.0)
    maximum_parser_warnings: int = Field(default=2, ge=0)


class StructureRoutingDecision(FrozenContract):
    """Routing result without making an LLM call."""

    mode: Literal["parser", "llm_recovery"]
    reasons: tuple[str, ...] = ()
    score: float = Field(ge=0.0, le=1.0)


class NormalizedBlock(FrozenContract):
    """Normalized rendering of a raw block while retaining its source span."""

    source_span_id: str
    ordinal: int = Field(ge=0)
    block_type: str
    text: str
    location: SourceLocation
    heading_path: tuple[str, ...] = ()
    attributes: dict[str, Any] = Field(default_factory=dict)


class NormalizedDocument(FrozenContract):
    """Common normalized view consumed by later analysis lanes."""

    raw: RawDocument
    blocks: tuple[NormalizedBlock, ...]
    parser_outline: ParserOutline
    quality: StructureQualityReport
    routing: StructureRoutingDecision
    normalized_markdown: str
    selected_view: SelectedStructuralView | None = None
    assets: tuple[EmbeddedAsset, ...] = ()
    normalized_at: datetime | None = None
    selected_view_origin: Literal["parser", "llm_recovered"] = "parser"
    selected_view_digest: str | None = None


__all__ = [
    "EmbeddedAsset",
    "ExtractionWarning",
    "NormalizedBlock",
    "NormalizedDocument",
    "OutlineSection",
    "ParserOutline",
    "RawBlock",
    "RawDocument",
    "RecoveryThresholds",
    "SelectedStructuralView",
    "SourceLocation",
    "StructuralBlockDisposition",
    "StructuralBlockSegment",
    "StructureQualityReport",
    "StructureRoutingDecision",
    "utc_now",
]
