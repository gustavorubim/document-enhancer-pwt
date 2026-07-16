"""Narrow provider contract and deterministic audit-revision promotion.

The provider may propose revised prose and name already-governed evidence, findings, sections, and
issues.  It never receives authority to replace the canonical enhanced-document model.
"""

from __future__ import annotations

from pydantic import Field, StrictStr, field_validator, model_validator

from document_enhancer.domain.audit import Audit
from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.ids import ensure_unique_ids, validate_identifier, validate_span_id
from document_enhancer.errors import ValidationError
from document_enhancer.rewrite import EnhancedDocumentModel, EnhancedSection


class AuditSectionRevisionPatch(StrictModel):
    """One provider-proposed prose change to an existing enhanced section."""

    section_id: StrictStr = Field(pattern=r"^(SEC|PROV-SEC)-[A-Z0-9-]+$")
    revised_body: StrictStr = Field(max_length=60_000)
    evidence_span_ids: list[StrictStr] = Field(min_length=1)
    audit_finding_ids: list[StrictStr] = Field(min_length=1)

    @field_validator("revised_body")
    @classmethod
    def validate_body(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="revised audit section body")

    @field_validator("evidence_span_ids")
    @classmethod
    def validate_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        ensure_unique_ids(values)
        return values

    @field_validator("audit_finding_ids")
    @classmethod
    def validate_findings(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_identifier(value, label="audit finding id")
        ensure_unique_ids(values)
        return values


class AuditIssueResolutionPatch(StrictModel):
    """Request to resolve one existing issue through a cited section revision."""

    issue_id: StrictStr
    audit_finding_ids: list[StrictStr] = Field(min_length=1)

    @field_validator("issue_id")
    @classmethod
    def validate_issue_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="open issue id")

    @field_validator("audit_finding_ids")
    @classmethod
    def validate_findings(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_identifier(value, label="audit finding id")
        ensure_unique_ids(values)
        return values


class AuditRevisionPatchSet(StrictModel):
    """Provider-facing audit revision DTO without canonical document ownership."""

    section_patches: list[AuditSectionRevisionPatch] = Field(default_factory=list)
    issue_resolutions: list[AuditIssueResolutionPatch] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_patch_set(self) -> AuditRevisionPatchSet:
        if not self.section_patches and not self.issue_resolutions:
            raise ValueError("audit revision patch set must contain at least one patch")
        ensure_unique_ids(item.section_id for item in self.section_patches)
        ensure_unique_ids(item.issue_id for item in self.issue_resolutions)
        return self


def _eligible_finding_ids(audit: Audit) -> set[str]:
    failed_checks = {
        check.check_id
        for check in audit.deterministic_checks
        if check.blocking and not check.passed and check.auto_revisable
    }
    content_findings = {
        finding.finding_id
        for finding in audit.independent_audit.findings
        if finding.blocking and finding.auto_revisable
    }
    return (failed_checks | content_findings) & set(audit.routing.blocker_ids)


def _section_evidence_span_ids(section: EnhancedSection) -> set[str]:
    spans: set[str] = {str(value) for value in section.source_span_ids}
    spans.update(
        str(evidence.span_id) for evidence in section.evidence if evidence.span_id is not None
    )
    spans.update(
        str(provenance.source_span_id)
        for provenance in section.provenance
        if provenance.source_span_id is not None
    )
    return spans


def _require_eligible_findings(
    finding_ids: list[StrictStr], eligible: set[str], *, target: str
) -> None:
    unknown = set(finding_ids) - eligible
    if unknown:
        raise ValidationError(
            f"audit revision target {target} cites findings outside the approved auto-revision scope"
        )


def apply_audit_revision_patches(
    model: EnhancedDocumentModel,
    audit: Audit,
    patches: AuditRevisionPatchSet,
) -> EnhancedDocumentModel:
    """Atomically apply a provider patch after deterministic scope validation.

    Any invalid item rejects the entire patch set.  The caller's structured-repair boundary may
    ask the provider for one corrected DTO, but no partial or invalid revision is promoted.
    """

    governed = EnhancedDocumentModel.model_validate(model.model_dump(mode="python"))
    validated_audit = Audit.model_validate(audit.model_dump(mode="python"))
    validated_patches = AuditRevisionPatchSet.model_validate(patches.model_dump(mode="python"))
    if validated_audit.document_id != governed.document.id:
        raise ValidationError("audit revision document identity does not match the governed model")
    if validated_audit.routing.route != "auto_revise":
        raise ValidationError("audit revision is not approved by the audit routing decision")

    eligible = _eligible_finding_ids(validated_audit)
    if not eligible:
        raise ValidationError("audit revision has no eligible auto-revisable finding")

    sections = {section.section_id: section for section in governed.sections}
    revised_sections = dict(sections)
    section_findings: dict[str, set[str]] = {}
    material_changes = 0
    for patch in validated_patches.section_patches:
        section = sections.get(patch.section_id)
        if section is None:
            raise ValidationError("audit revision cites an unknown section target")
        _require_eligible_findings(patch.audit_finding_ids, eligible, target=patch.section_id)
        unknown_spans = set(patch.evidence_span_ids) - _section_evidence_span_ids(section)
        if unknown_spans:
            raise ValidationError(
                f"audit revision target {patch.section_id} cites evidence outside the governed section"
            )
        if patch.revised_body == section.body:
            raise ValidationError(
                f"audit revision target {patch.section_id} does not contain a material change"
            )
        revised_sections[patch.section_id] = section.model_copy(update={"body": patch.revised_body})
        section_findings[patch.section_id] = set(patch.audit_finding_ids)
        material_changes += 1

    issues = {issue.issue_id: issue for issue in governed.open_issues}
    revised_issues = dict(issues)
    resolved_issue_ids: set[str] = set()
    for resolution in validated_patches.issue_resolutions:
        issue = issues.get(resolution.issue_id)
        if issue is None:
            raise ValidationError("audit revision cites an unknown issue target")
        if issue.status != "open":
            raise ValidationError("audit revision may resolve only an open issue")
        _require_eligible_findings(
            resolution.audit_finding_ids, eligible, target=resolution.issue_id
        )
        linked_sections = {
            section.section_id
            for section in governed.sections
            if resolution.issue_id in section.open_issue_ids
            or issue.target_section_id == section.section_id
        }
        approved_sections = {
            section_id
            for section_id in linked_sections
            if section_id in section_findings
            and set(resolution.audit_finding_ids) & section_findings[section_id]
        }
        if not approved_sections:
            raise ValidationError(
                "audit issue resolution requires a linked section patch citing the same approved finding"
            )
        revised_issues[resolution.issue_id] = issue.model_copy(update={"status": "resolved"})
        resolved_issue_ids.add(resolution.issue_id)
        material_changes += 1

    if resolved_issue_ids:
        revised_sections = {
            section_id: section.model_copy(
                update={
                    "open_issue_ids": [
                        issue_id
                        for issue_id in section.open_issue_ids
                        if issue_id not in resolved_issue_ids
                    ]
                }
            )
            for section_id, section in revised_sections.items()
        }
    if material_changes == 0:  # pragma: no cover - guarded by DTO and per-patch validation
        raise ValidationError("audit revision did not produce a material governed change")

    candidate = governed.model_copy(
        update={
            "sections": [revised_sections[item.section_id] for item in governed.sections],
            "open_issues": [revised_issues[item.issue_id] for item in governed.open_issues],
        }
    )
    rebuilt = EnhancedDocumentModel.model_validate(candidate.model_dump(mode="python"))
    rebuilt.assert_valid()
    # Revalidate the complete audit contract at the same acceptance boundary.  A new audit is
    # executed by the workflow after rendering the rebuilt model.
    Audit.model_validate(validated_audit.model_dump(mode="python"))
    return rebuilt


__all__ = [
    "AuditIssueResolutionPatch",
    "AuditRevisionPatchSet",
    "AuditSectionRevisionPatch",
    "apply_audit_revision_patches",
]
