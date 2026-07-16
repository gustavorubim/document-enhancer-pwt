"""Strict M7 audit, diff, evidence, and routing contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.enums import AuditFindingKind, AuditStatus
from document_enhancer.domain.ids import ensure_unique_ids, validate_identifier, validate_span_id
from document_enhancer.domain.questions import Waiver


class AuditEvidence(StrictModel):
    """One immutable input or output citation used by an audit result."""

    artifact: StrictStr
    locator: StrictStr
    quote: StrictStr | None = None
    digest: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("artifact", "locator", "quote")
    @classmethod
    def validate_text(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="audit evidence")

    @model_validator(mode="after")
    def require_quote_or_digest(self) -> AuditEvidence:
        if self.quote is None and self.digest is None:
            raise ValueError("audit evidence requires a quote or digest")
        return self


class DeterministicCheck(StrictModel):
    check_id: StrictStr
    name: StrictStr
    category: StrictStr
    passed: StrictBool
    blocking: StrictBool = True
    auto_revisable: StrictBool = False
    details: StrictStr | None = None
    evidence: list[AuditEvidence] = Field(default_factory=list)
    waived_by: StrictStr | None = None

    @field_validator("check_id")
    @classmethod
    def validate_check_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="audit check id")

    @field_validator("name", "category", "details")
    @classmethod
    def validate_check_text(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="audit check field")

    @model_validator(mode="after")
    def validate_failure_evidence(self) -> DeterministicCheck:
        if not self.passed and not self.evidence:
            raise ValueError("failed deterministic checks require evidence")
        if self.waived_by is not None and not self.passed:
            raise ValueError(
                "waived requirements must be represented as passed with waiver evidence"
            )
        return self


class ContentAuditFinding(StrictModel):
    finding_id: StrictStr
    category: StrictStr
    severity: Literal["low", "medium", "high", "blocker"]
    summary: StrictStr
    blocking: StrictBool = False
    auto_revisable: StrictBool = False
    source_evidence: list[AuditEvidence] = Field(min_length=1)
    output_evidence: list[AuditEvidence] = Field(min_length=1)
    proposed_disposition: StrictStr

    @field_validator("finding_id")
    @classmethod
    def validate_finding_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="content audit finding id")

    @field_validator("category", "summary", "proposed_disposition")
    @classmethod
    def validate_finding_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="content audit finding")


class IndependentAuditResult(StrictModel):
    audit_id: StrictStr
    status: Literal["pass", "fail", "unavailable"]
    findings: list[ContentAuditFinding] = Field(default_factory=list)
    provider: StrictStr
    isolated_context: Literal[True] = True
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("audit_id")
    @classmethod
    def validate_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="independent audit id")

    @model_validator(mode="after")
    def validate_status(self) -> IndependentAuditResult:
        ensure_unique_ids(item.finding_id for item in self.findings)
        if self.status == "pass" and any(item.blocking for item in self.findings):
            raise ValueError("passing independent audit cannot contain blocking findings")
        return self


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
    change_type: Literal["added", "removed", "changed", "retyped"]
    before: dict[str, object] | None = None
    after: dict[str, object] | None = None
    kind: AuditFindingKind
    rationale: StrictStr | None = None

    @field_validator("change_id", "object_id")
    @classmethod
    def validate_change_ids(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="semantic change id")


class SemanticDiff(StrictModel):
    added: list[SemanticChange] = Field(default_factory=list)
    removed: list[SemanticChange] = Field(default_factory=list)
    changed: list[SemanticChange] = Field(default_factory=list)
    retyped: list[SemanticChange] = Field(default_factory=list)


class AuditRoutingDecision(StrictModel):
    route: Literal["export", "auto_revise", "human_review", "failed"]
    reason: StrictStr
    blocker_ids: list[StrictStr] = Field(default_factory=list)
    audit_revision: StrictInt = Field(ge=0)
    remaining_audit_revisions: StrictInt = Field(ge=0)


class Audit(StrictModel):
    audit_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    version_id: StrictStr | None = Field(default=None, pattern=r"^(DOCV|VER)-[A-Z0-9-]+$")
    status: AuditStatus
    deterministic_checks: list[DeterministicCheck] = Field(default_factory=list)
    independent_audit: IndependentAuditResult
    waivers: list[Waiver] = Field(default_factory=list)
    revision_count: StrictInt = Field(default=0, ge=0)
    routing: AuditRoutingDecision
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

    @model_validator(mode="after")
    def validate_consistency(self) -> Audit:
        ensure_unique_ids(check.check_id for check in self.deterministic_checks)
        deterministic_failures = [
            check for check in self.deterministic_checks if check.blocking and not check.passed
        ]
        content_failures = [item for item in self.independent_audit.findings if item.blocking]
        if self.status is AuditStatus.PASS:
            if deterministic_failures or content_failures:
                raise ValueError("a passing audit cannot contain blocking failures")
            if self.independent_audit.status != "pass":
                raise ValueError("a passing audit requires a passing independent audit")
            if self.unresolved_issue_ids:
                raise ValueError("a passing audit cannot contain unresolved blocking issues")
            if self.routing.route != "export":
                raise ValueError("a passing audit must route to export")
        return self

    def assert_pass(self) -> None:
        if self.status is not AuditStatus.PASS:
            raise ValueError(f"audit status is {self.status.value}, not pass")


AuditReport = Audit

__all__ = [
    "Audit",
    "AuditEvidence",
    "AuditReport",
    "AuditRoutingDecision",
    "ContentAuditFinding",
    "DeterministicCheck",
    "IndependentAuditResult",
    "SemanticChange",
    "SemanticDiff",
    "SourceTargetMapping",
]
