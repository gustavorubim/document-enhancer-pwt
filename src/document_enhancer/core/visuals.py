"""Bounded interpretation of already-extracted passive image figures.

This module is deliberately downstream of ingestion.  It receives immutable image
bytes plus the persisted ``SourceFigure`` identity and returns reviewable
structured candidates.  It never opens paths, fetches URLs, runs OCR, or changes
the source figure.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

from document_enhancer.llm.multimodal import (
    MultimodalProvider,
    MultimodalRequest,
    VisualChartValue,
    VisualKind,
    VisualModelResponse,
    VisualProcessEdge,
    VisualProcessNode,
    VisualStatus,
)

from .models import SourceFigure


class VisualValidationError(ValueError):
    """A source or provider visual contract failed closed."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


class VisualLimits(BaseModel):
    """Explicit per-call visual count, media, context, and grid budgets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_figures: int = Field(default=8, ge=1, le=64)
    max_bytes_per_figure: int = Field(default=4_000_000, ge=1, le=4_000_000)
    max_total_bytes: int = Field(default=12_000_000, ge=1, le=32_000_000)
    max_context_chars: int = Field(default=8_000, ge=0, le=32_000)
    max_caption_chars: int = Field(default=2_000, ge=0, le=8_000)
    max_rows: int = Field(default=128, ge=1, le=512)
    max_columns: int = Field(default=64, ge=1, le=256)
    max_cells: int = Field(default=2_048, ge=1, le=16_384)


class VisualFigureInput(BaseModel):
    """Immutable source figure metadata paired with already-extracted bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    figure_id: str = Field(pattern=r"^FIG-\d{3}$")
    asset_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        validation_alias=AliasChoices("sha256", "source_sha256", "source_digest"),
    )
    size_bytes: int = Field(ge=0)
    source_path: str = Field(min_length=1)
    caption: str = ""
    source_span_ids: tuple[str, ...] = ()
    provenance: dict[str, object] = Field(default_factory=dict)
    payload: bytes = Field(min_length=1, repr=False)

    @classmethod
    def from_source_figure(cls, figure: SourceFigure, payload: bytes) -> VisualFigureInput:
        """Build an input without copying or mutating the persisted source figure."""

        source_span_ids = tuple(
            dict.fromkeys(
                occurrence.source_span_id
                for occurrence in figure.occurrences
                if occurrence.source_span_id
            )
        )
        return cls(
            figure_id=figure.figure_id,
            asset_id=figure.asset_id,
            name=figure.name,
            media_type=figure.media_type,
            sha256=figure.sha256,
            size_bytes=figure.size_bytes,
            source_path=figure.source_path,
            caption=figure.caption,
            source_span_ids=source_span_ids,
            provenance={
                "occurrences": [item.model_dump(mode="json") for item in figure.occurrences],
                "source_path": figure.source_path,
            },
            payload=bytes(payload),
        )

    def validate_integrity(self) -> None:
        """Check that the supplied bytes still match the registered source evidence."""

        if len(self.payload) != self.size_bytes:
            raise VisualValidationError(
                "figure_size_mismatch",
                f"figure {self.figure_id} size does not match its registered source size",
            )
        actual = hashlib.sha256(self.payload).hexdigest()
        if actual != self.sha256:
            raise VisualValidationError(
                "figure_digest_mismatch",
                f"figure {self.figure_id} bytes do not match its registered source digest",
            )

    @property
    def source_digest(self) -> str:
        return self.sha256


class VisualContent(BaseModel):
    """Typed candidate content kept separate from the source image evidence."""

    model_config = ConfigDict(extra="forbid")

    cells: list[list[str]] | None = None
    mermaid: str | None = None
    process_nodes: list[VisualProcessNode] = Field(default_factory=list)
    process_edges: list[VisualProcessEdge] = Field(default_factory=list)
    chart_values: list[VisualChartValue] = Field(default_factory=list)
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)

    @field_validator("cells")
    @classmethod
    def _rectangular_cells(cls, value: list[list[str]] | None) -> list[list[str]] | None:
        if value is None:
            return None
        if not value or not value[0]:
            raise ValueError("visual table cells must contain a non-empty rectangular grid")
        width = len(value[0])
        if any(len(row) != width for row in value):
            raise ValueError("visual table cells must be rectangular")
        return value


class VisualExtraction(BaseModel):
    """Versioned reviewable visual candidate linked to immutable source evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["core.visual-extraction.v1"] = "core.visual-extraction.v1"
    figure_id: str = Field(pattern=r"^FIG-\d{3}$")
    asset_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    source_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        validation_alias=AliasChoices("source_sha256", "source_digest", "sha256"),
    )
    size_bytes: int = Field(ge=0)
    source_path: str = Field(min_length=1)
    caption: str = ""
    source_span_ids: tuple[str, ...] = ()
    provenance: dict[str, object] = Field(default_factory=dict)
    kind: VisualKind
    status: VisualStatus
    structured_content: VisualContent = Field(default_factory=VisualContent)
    warnings: tuple[str, ...] = ()
    non_authoritative: bool = False

    @property
    def source_digest(self) -> str:
        """Compatibility name for callers that use the frozen plan terminology."""

        return self.source_sha256

    @property
    def requires_review(self) -> bool:
        return self.status == "requires_review"

    def to_markdown_table(self) -> str | None:
        """Render a validated table candidate without altering the source image."""

        if self.kind != "table" or self.structured_content.cells is None:
            return None
        return table_cells_to_markdown(self.structured_content.cells)


class VisualProvider(Protocol):
    """Core-facing alias for the minimal multimodal provider port."""

    def classify(self, request: MultimodalRequest) -> VisualModelResponse: ...


def _escape_table_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ").replace("\r", " ").strip()


def table_cells_to_markdown(cells: Sequence[Sequence[str]]) -> str:
    """Convert a rectangular string grid into deterministic Markdown table text."""

    content = VisualContent(cells=[list(row) for row in cells]).cells
    if content is None:  # pragma: no cover - guarded by the model validator
        raise VisualValidationError("missing_table_cells")
    header, *rows = content
    lines = [
        "| " + " | ".join(_escape_table_cell(value) for value in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_escape_table_cell(value) for value in row) + " |" for row in rows
    )
    return "\n".join(lines) + "\n"


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _looks_like_native_table(value: object) -> bool:
    block_type = _field(value, "block_type", "")
    kind = _field(value, "kind", "")
    return str(block_type).casefold() == "table" or str(kind).casefold() == "table"


class VisualInterpreter:
    """Classify and convert eligible passive figures through one bounded provider port."""

    def __init__(
        self,
        provider: VisualProvider | MultimodalProvider | None = None,
        *,
        limits: VisualLimits | None = None,
        failure_mode: Literal["requires_review", "raise"] = "requires_review",
        known_figure_ids: Sequence[str] | None = None,
    ) -> None:
        self.provider = provider
        self.limits = limits or VisualLimits()
        self.failure_mode = failure_mode
        self.known_figure_ids = frozenset(known_figure_ids or ())

    def interpret(
        self,
        figures: Sequence[VisualFigureInput | Mapping[str, object] | object],
        *,
        native_tables: Sequence[object] = (),
        context: str = "",
    ) -> list[VisualExtraction]:
        """Interpret only passive figures; native tables are deterministic parser output.

        ``native_tables`` is intentionally accepted as a separate input so callers
        can pass the full extracted inventory without accidentally sending a native
        table to the visual model.  Native table content produces no extraction here.
        """

        _ = native_tables
        if not isinstance(context, str):
            raise VisualValidationError("invalid_visual_context")
        normalized: list[VisualFigureInput] = []
        for value in figures:
            if _looks_like_native_table(value):
                continue
            item = self._coerce_figure(value)
            item.validate_integrity()
            if self.known_figure_ids and item.figure_id not in self.known_figure_ids:
                raise VisualValidationError("unknown_figure_id")
            normalized.append(item)

        if len(context) > self.limits.max_context_chars:
            return [
                self._review_candidate(item, "visual_context_budget_exceeded")
                for item in normalized
            ]

        results: list[VisualExtraction] = []
        total_bytes = 0
        for index, item in enumerate(normalized):
            if index >= self.limits.max_figures:
                results.append(self._review_candidate(item, "visual_figure_count_budget_exceeded"))
                continue
            if len(item.payload) > self.limits.max_bytes_per_figure:
                results.append(self._review_candidate(item, "visual_figure_size_budget_exceeded"))
                continue
            if len(item.caption) > self.limits.max_caption_chars:
                results.append(self._review_candidate(item, "visual_caption_budget_exceeded"))
                continue
            if total_bytes + len(item.payload) > self.limits.max_total_bytes:
                results.append(self._review_candidate(item, "visual_total_bytes_budget_exceeded"))
                continue
            total_bytes += len(item.payload)
            if item.media_type not in {"image/png", "image/jpeg"}:
                results.append(self._unsupported_candidate(item, "unsupported_visual_media"))
                continue
            if self.provider is None:
                results.append(self._review_candidate(item, "visual_provider_not_configured"))
                continue
            request = MultimodalRequest(
                figure_id=item.figure_id,
                source_sha256=item.sha256,
                media_type=item.media_type,
                image_bytes=item.payload,
                caption=item.caption,
                source_span_ids=item.source_span_ids,
                provenance=item.provenance,
                context=context,
            )
            try:
                response = self.provider.classify(request)
                response = VisualModelResponse.model_validate(response)
                results.append(self._promote(item, response))
            except (ValidationError, ValueError, TypeError, RuntimeError) as exc:
                results.append(
                    self._failure_candidate(
                        item,
                        "visual_response_invalid",
                        exc,
                    )
                )
        return results

    @staticmethod
    def _coerce_figure(
        value: VisualFigureInput | Mapping[str, object] | object,
    ) -> VisualFigureInput:
        if isinstance(value, VisualFigureInput):
            return value
        try:
            return VisualFigureInput.model_validate(value)
        except ValidationError as exc:
            raise VisualValidationError("invalid_visual_figure_input") from exc

    def _failure_candidate(
        self, item: VisualFigureInput, code: str, exc: BaseException
    ) -> VisualExtraction:
        if isinstance(exc, VisualValidationError):
            code = exc.code
        if self.failure_mode == "raise":
            raise VisualValidationError(code) from exc
        return self._review_candidate(item, code)

    def _review_candidate(self, item: VisualFigureInput, warning: str) -> VisualExtraction:
        return self._build_extraction(
            item,
            kind="unknown",
            status="requires_review",
            content=VisualContent(warnings=[warning]),
            warnings=(warning,),
        )

    def _unsupported_candidate(self, item: VisualFigureInput, warning: str) -> VisualExtraction:
        return self._build_extraction(
            item,
            kind="unknown",
            status="unsupported",
            content=VisualContent(warnings=[warning]),
            warnings=(warning,),
        )

    def _promote(self, item: VisualFigureInput, response: VisualModelResponse) -> VisualExtraction:
        warnings = list(response.warnings)
        if response.figure_id != item.figure_id:
            raise VisualValidationError("visual_response_unknown_figure_id")
        if response.source_sha256 != item.sha256:
            raise VisualValidationError("visual_response_digest_mismatch")
        allowed_spans = set(item.source_span_ids)
        if any(span_id not in allowed_spans for span_id in response.source_span_ids):
            raise VisualValidationError("visual_response_unknown_source_span")
        if response.source_span_ids and set(response.source_span_ids) != allowed_spans:
            warnings.append("visual_response_source_linkage_completed_from_source")

        cells = response.cells
        chart_values: list[VisualChartValue] = []
        if response.kind == "table":
            if cells is None:
                raise VisualValidationError("visual_table_cells_missing")
            if len(cells) > self.limits.max_rows:
                raise VisualValidationError("visual_table_row_budget_exceeded")
            width = len(cells[0]) if cells else 0
            if width > self.limits.max_columns or len(cells) * width > self.limits.max_cells:
                raise VisualValidationError("visual_table_cell_budget_exceeded")
        elif response.kind == "process_diagram":
            node_ids = {node.node_id for node in response.process_nodes}
            if response.process_edges and not node_ids:
                raise VisualValidationError("visual_process_nodes_missing")
            if any(
                edge.source not in node_ids or edge.target not in node_ids
                for edge in response.process_edges
            ):
                raise VisualValidationError("visual_process_edge_unknown_node")
            if not response.mermaid and not response.process_nodes:
                raise VisualValidationError("visual_process_content_missing")
        elif response.kind == "chart":
            if response.chart_values and not (response.legible and response.reviewable):
                cells = None
                warnings.append("chart_values_not_legible_and_reviewable")
            else:
                chart_values = list(response.chart_values)
            if response.legible and response.reviewable and not chart_values:
                warnings.append("chart_values_missing")
        else:
            chart_values = list(response.chart_values)

        if response.kind == "ui_screenshot":
            warnings.append("ui_screenshot_non_authoritative")
        if response.kind == "unknown":
            warnings.append("visual_kind_unknown")

        content = VisualContent(
            cells=cells if response.kind == "table" else None,
            mermaid=response.mermaid if response.kind == "process_diagram" else None,
            process_nodes=list(response.process_nodes)
            if response.kind == "process_diagram"
            else [],
            process_edges=list(response.process_edges)
            if response.kind == "process_diagram"
            else [],
            chart_values=chart_values if response.kind == "chart" else [],
            summary=response.summary,
            warnings=warnings,
        )
        status: VisualStatus = response.status
        if response.kind != "decorative" and status != "unsupported":
            # All model-derived semantic conversions remain human-review candidates.
            status = "requires_review"
            if "visual_conversion_requires_review" not in warnings:
                warnings.append("visual_conversion_requires_review")
                content = content.model_copy(update={"warnings": warnings})
        if response.kind == "unknown":
            status = "requires_review"
        return self._build_extraction(
            item,
            kind=response.kind,
            status=status,
            content=content,
            warnings=tuple(warnings),
            non_authoritative=response.kind == "ui_screenshot",
        )

    def _build_extraction(
        self,
        item: VisualFigureInput,
        *,
        kind: VisualKind,
        status: VisualStatus,
        content: VisualContent,
        warnings: Sequence[str],
        non_authoritative: bool = False,
    ) -> VisualExtraction:
        return VisualExtraction(
            figure_id=item.figure_id,
            asset_id=item.asset_id,
            name=item.name,
            media_type=item.media_type,
            source_sha256=item.sha256,
            size_bytes=item.size_bytes,
            source_path=item.source_path,
            caption=item.caption,
            source_span_ids=item.source_span_ids,
            provenance=dict(item.provenance),
            kind=kind,
            status=status,
            structured_content=content,
            warnings=tuple(dict.fromkeys(warnings)),
            non_authoritative=non_authoritative,
        )


def interpret_visuals(
    figures: Sequence[VisualFigureInput | Mapping[str, object] | object],
    *,
    provider: VisualProvider | MultimodalProvider | None = None,
    limits: VisualLimits | None = None,
    native_tables: Sequence[object] = (),
    context: str = "",
    failure_mode: Literal["requires_review", "raise"] = "requires_review",
) -> list[VisualExtraction]:
    """Convenience wrapper for one bounded visual interpretation batch."""

    return VisualInterpreter(
        provider,
        limits=limits,
        failure_mode=failure_mode,
    ).interpret(figures, native_tables=native_tables, context=context)


__all__ = [
    "VisualContent",
    "VisualExtraction",
    "VisualFigureInput",
    "VisualInterpreter",
    "VisualLimits",
    "VisualProvider",
    "VisualValidationError",
    "interpret_visuals",
    "table_cells_to_markdown",
]
