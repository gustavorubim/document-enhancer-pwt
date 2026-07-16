"""Deterministic and independent content-audit contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from document_enhancer.domain.analysis import Finding
from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.enums import AuditFindingKind, AuditStatus
from document_enhancer.domain.ids import ensure_unique_ids, validate_identifier, validate_span_id
from document_enhancer.domain.questions import Waiver


class DeterministicCheck(StrictModel):
    check_id: StrictStr
    name: StrictStr
    passed: StrictBool
    blocking: StrictBool = True
    details: StrictStr | None = None
    evidence: list[StrictStr] = Field(default_factory=list)

    @field_validator("check_id")
    @classmethod
    def validate_check_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="audit check id")

    @field_validator("name", "details")
    @classmethod
    def validate_check_text(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="audit check field")


class SourceTargetMapping(StrictModel):
    source_span_id: StrictStr
    target_anchor: StrictStr | None = None
    target_object_ids: list[StrictStr] = Field(default_factory=list)
    disposition: StrictStr
    reason: StrictStr | None = None

    @field_validator("source_span_id")
    @classmethod
    def validate_mapping_span(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)


class SemanticChange(StrictModel):
    change_id: StrictStr
    object_id: StrictStr
    change_type: str
    before: dict[str, object] | None = None
    after: dict[str, object] | None = None
    kind: AuditFindingKind
    rationale: StrictStr | None = None

    @field_validator("change_id", "object_id")
    @classmethod
    def validate_change_ids(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="semantic change id")

    @field_validator("change_type", "rationale")
    @classmethod
    def validate_change_text(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="semantic change field")


class SemanticDiff(StrictModel):
    added: list[SemanticChange] = Field(default_factory=list)
    removed: list[SemanticChange] = Field(default_factory=list)
    changed: list[SemanticChange] = Field(default_factory=list)
    retyped: list[SemanticChange] = Field(default_factory=list)


class Audit(StrictModel):
    audit_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    version_id: StrictStr | None = Field(default=None, pattern=r"^(DOCV|VER)-[A-Z0-9-]+$")
    status: AuditStatus
    deterministic_checks: list[DeterministicCheck] = Field(default_factory=list)
    content_findings: list[Finding] = Field(default_factory=list)
    waivers: list[Waiver] = Field(default_factory=list)
    revision_count: StrictInt = Field(default=0, ge=0)
    textual_diff: StrictStr = ""
    semantic_diff: SemanticDiff = Field(default_factory=SemanticDiff)
    source_to_target: list[SourceTargetMapping] = Field(default_factory=list)
    unresolved_issue_ids: list[StrictStr] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    summary: StrictStr | None = None

    @field_validator("audit_id")
    @classmethod
    def validate_audit_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="audit id")

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="audit summary")

    @model_validator(mode="after")
    def validate_check_consistency(self) -> Audit:
        ensure_unique_ids(check.check_id for check in self.deterministic_checks)
        failures = [
            check for check in self.deterministic_checks if check.blocking and not check.passed
        ]
        if self.status is AuditStatus.PASS and failures:
            raise ValueError("a passing audit cannot contain failed blocking deterministic checks")
        return self

    def assert_pass(self) -> None:
        if self.status is not AuditStatus.PASS:
            raise ValueError(f"audit status is {self.status.value}, not pass")


AuditReport = Audit


__all__ = [
    "Audit",
    "AuditReport",
    "DeterministicCheck",
    "SemanticChange",
    "SemanticDiff",
    "SourceTargetMapping",
]
