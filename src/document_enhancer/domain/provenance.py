"""Source, authority, review, and temporal provenance contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import (
    AliasChoices,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.enums import (
    Authority,
    Layer,
    ProvenanceOrigin,
    ReviewStatus,
)
from document_enhancer.domain.ids import validate_span_id


class TemporalValidity(StrictModel):
    """Inclusive validity interval; open-ended endpoints are allowed."""

    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def validate_order(self) -> TemporalValidity:
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise ValueError("valid_to must not precede valid_from")
        return self


class SourceLocation(StrictModel):
    """Loss-aware location across Markdown, DOCX, PDF, and table sources."""

    line_start: StrictInt | None = Field(default=None, ge=1)
    line_end: StrictInt | None = Field(default=None, ge=1)
    char_start: StrictInt | None = Field(default=None, ge=0)
    char_end: StrictInt | None = Field(default=None, ge=0)
    page: StrictInt | None = Field(default=None, ge=1)
    paragraph_index: StrictInt | None = Field(default=None, ge=0)
    table_index: StrictInt | None = Field(default=None, ge=0)
    row_index: StrictInt | None = Field(default=None, ge=0)
    column_index: StrictInt | None = Field(default=None, ge=0)
    xml_path: StrictStr | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> SourceLocation:
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must not precede line_start")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("char_end must not precede char_start")
        if self.column_index is not None and self.row_index is None and self.table_index is None:
            raise ValueError("column_index requires a table or row location")
        return self


class Provenance(StrictModel):
    """Mandatory traceability attached to every semantic node and relationship."""

    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    document_version_id: StrictStr | None = Field(default=None, pattern=r"^(DOCV|VER)-[A-Z0-9-]+$")
    source_span_id: StrictStr | None = Field(
        default=None,
        validation_alias=AliasChoices("source_span_id", "source_span"),
    )
    section_id: StrictStr | None = Field(default=None, pattern=r"^(SEC|PROV-SEC)-[A-Z0-9-]+$")
    location: SourceLocation | None = None
    origin: ProvenanceOrigin
    authority: Authority
    layer: Layer
    confidence: StrictFloat | None = Field(default=None, ge=0.0, le=1.0)
    extraction_method: StrictStr
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    validity: TemporalValidity | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    reviewer_id: StrictStr | None = None
    reference_id: StrictStr | None = None

    @field_validator("extraction_method")
    @classmethod
    def validate_method(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="extraction_method")

    @field_validator("source_span_id")
    @classmethod
    def validate_source_span(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else validate_span_id(value)

    @field_validator("reviewer_id", "reference_id")
    @classmethod
    def validate_optional_ids(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="identifier")

    @model_validator(mode="after")
    def validate_traceability_rules(self) -> Provenance:
        if self.validity is None and (self.valid_from is not None or self.valid_to is not None):
            object.__setattr__(
                self,
                "validity",
                TemporalValidity(valid_from=self.valid_from, valid_to=self.valid_to),
            )
        elif self.validity is not None:
            if self.valid_from is not None and self.validity.valid_from != self.valid_from:
                raise ValueError("valid_from conflicts with validity.valid_from")
            if self.valid_to is not None and self.validity.valid_to != self.valid_to:
                raise ValueError("valid_to conflicts with validity.valid_to")
        if self.origin is ProvenanceOrigin.SOURCE and self.source_span_id is None:
            raise ValueError("source provenance requires source_span_id")
        if self.origin is ProvenanceOrigin.MODEL and self.confidence is None:
            raise ValueError("model provenance requires confidence")
        if self.authority is Authority.INFERRED and self.confidence is None:
            raise ValueError("inferred provenance requires confidence")
        if self.authority is Authority.REVIEWED and self.review_status not in {
            ReviewStatus.ACCEPTED,
            ReviewStatus.WAIVED,
        }:
            raise ValueError("reviewed provenance requires accepted or waived review_status")
        if (
            self.review_status in {ReviewStatus.ACCEPTED, ReviewStatus.WAIVED}
            and not self.reviewer_id
        ):
            raise ValueError("accepted or waived provenance requires reviewer_id")
        if self.layer is Layer.AUTHORITATIVE and self.authority is Authority.INFERRED:
            raise ValueError("inferred claims cannot be authoritative")
        if self.layer is Layer.GOVERNED and self.authority is Authority.INFERRED:
            raise ValueError("inferred claims cannot be governed")
        return self


__all__ = ["Provenance", "SourceLocation", "TemporalValidity"]
