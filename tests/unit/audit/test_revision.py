from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError as PydanticValidationError

from document_enhancer.audit import (
    AuditIssueResolutionPatch,
    AuditRevisionPatchSet,
    AuditSectionRevisionPatch,
    apply_audit_revision_patches,
)
from document_enhancer.domain.audit import (
    Audit,
    AuditEvidence,
    AuditRoutingDecision,
    ContentAuditFinding,
    IndependentAuditResult,
)
from document_enhancer.domain.enums import AuditStatus, DocumentType
from document_enhancer.errors import ValidationError
from document_enhancer.ingest.normalize import normalize_document
from document_enhancer.ingest.pipeline import parse_source
from document_enhancer.llm import GeminiModelGateway
from document_enhancer.prompting import PromptPackComposer, load_prompt_pack
from document_enhancer.references.loader import load_reference_pack
from document_enhancer.rewrite import (
    EnhancedDocumentModel,
    OpenIssue,
    build_content_ledger,
    build_enhanced_document,
    build_rewrite_inputs,
)
from document_enhancer.workflow.model_services import GeminiAuditRevisionRunner

ROOT = Path(__file__).resolve().parents[3]
PROMPT_ROOT = ROOT / "prompt_packs/gemini_core"
REFERENCE_ROOT = ROOT / "reference_packs/enterprise_core"
FINDING_ID = "F-AUDIT-REVISION-001"


def _model(tmp_path: Path) -> EnhancedDocumentModel:
    source = tmp_path / "source.md"
    source.write_text(
        "# Purpose\n\nThe analyst reviews the approved monthly file and records the result.\n",
        encoding="utf-8",
    )
    normalized = normalize_document(parse_source(source))
    sections = [{"id": "SEC-PROC-PURPOSE", "heading": "Purpose", "anchor": "purpose"}]
    ledger = build_content_ledger(
        normalized, document_id="DOC-AUDIT-REVISION-001", target_sections=sections
    )
    inputs = build_rewrite_inputs(normalized, ledger, sections=sections)
    return build_enhanced_document(
        inputs,
        document_id="DOC-AUDIT-REVISION-001",
        document_type=DocumentType.PROCESS,
        ledger=ledger,
    )


def _audit(model: EnhancedDocumentModel) -> Audit:
    evidence = AuditEvidence(
        artifact="output/enhanced.md",
        locator=model.sections[0].section_id,
        quote=model.sections[0].body,
    )
    finding = ContentAuditFinding(
        finding_id=FINDING_ID,
        category="clarity",
        severity="blocker",
        summary="The completion evidence must be explicit.",
        blocking=True,
        auto_revisable=True,
        source_evidence=[evidence],
        output_evidence=[evidence],
        proposed_disposition="Clarify the existing source-supported section body.",
    )
    return Audit(
        audit_id="AUDIT-REVISION-001",
        document_id=model.document.id,
        version_id=model.version.id,
        status=AuditStatus.FAIL,
        independent_audit=IndependentAuditResult(
            audit_id="INDAUD-REVISION-001",
            status="fail",
            findings=[finding],
            provider="recorded-test",
            isolated_context=True,
        ),
        routing=AuditRoutingDecision(
            route="auto_revise",
            reason="all blockers are safely auto-revisable",
            blocker_ids=[FINDING_ID],
            audit_revision=0,
            remaining_audit_revisions=1,
        ),
    )


def _patch(model: EnhancedDocumentModel) -> AuditRevisionPatchSet:
    section = model.sections[0]
    return AuditRevisionPatchSet(
        section_patches=[
            AuditSectionRevisionPatch(
                section_id=section.section_id,
                revised_body=(
                    "The analyst reviews the approved monthly file and records the result as "
                    "completion evidence."
                ),
                evidence_span_ids=[section.source_span_ids[0]],
                audit_finding_ids=[FINDING_ID],
            )
        ]
    )


def test_provider_patch_schema_is_narrow_and_excludes_canonical_document_ownership() -> None:
    patch_schema = AuditRevisionPatchSet.model_json_schema()
    full_schema = EnhancedDocumentModel.model_json_schema()
    encoded = json.dumps(patch_schema, sort_keys=True)
    assert set(patch_schema["properties"]) == {"section_patches", "issue_resolutions"}
    assert len(encoded) < 10_000
    assert len(encoded) * 10 < len(json.dumps(full_schema, sort_keys=True))
    for forbidden in (
        '"document"',
        '"version"',
        '"provenance"',
        '"review_status"',
        '"digest"',
        '"relationships"',
    ):
        assert forbidden not in encoded


def test_patch_application_changes_only_approved_body_and_revalidates_domain(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    revised = apply_audit_revision_patches(model, _audit(model), _patch(model))

    assert revised.sections[0].body.endswith("completion evidence.")
    assert revised.sections[0].model_dump(exclude={"body"}) == model.sections[0].model_dump(
        exclude={"body"}
    )
    assert revised.model_dump(exclude={"sections"}) == model.model_dump(exclude={"sections"})
    assert model.sections[0].body != revised.sections[0].body
    EnhancedDocumentModel.model_validate(revised.model_dump(mode="python"))


def test_patch_application_resolves_only_linked_issue_with_same_finding(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    section = model.sections[0]
    issue = OpenIssue(
        issue_id="ISSUE-AUDIT-REVISION-001",
        category="unknown",
        statement="Completion evidence wording is unclear.",
        source_span_ids=[section.source_span_ids[0]],
        target_section_id=section.section_id,
    )
    governed = model.model_copy(
        update={
            "sections": [
                section.model_copy(update={"open_issue_ids": [issue.issue_id]}),
                *model.sections[1:],
            ],
            "open_issues": [issue],
        }
    )
    patch = _patch(governed).model_copy(
        update={
            "issue_resolutions": [
                AuditIssueResolutionPatch(
                    issue_id=issue.issue_id,
                    audit_finding_ids=[FINDING_ID],
                )
            ]
        }
    )

    revised = apply_audit_revision_patches(governed, _audit(governed), patch)

    assert revised.open_issues[0].status == "resolved"
    assert issue.issue_id not in revised.sections[0].open_issue_ids


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("unknown_section", "unknown section"),
        ("unknown_span", "evidence outside"),
        ("unapproved_finding", "outside the approved"),
        ("unapproved_route", "not approved"),
        ("unchanged_body", "material change"),
    ),
)
def test_invalid_or_unapproved_patch_is_rejected_atomically(
    tmp_path: Path, mutation: str, message: str
) -> None:
    model = _model(tmp_path)
    audit = _audit(model)
    patch = _patch(model)
    section_patch = patch.section_patches[0]
    if mutation == "unknown_section":
        section_patch = section_patch.model_copy(update={"section_id": "SEC-PROC-UNKNOWN"})
    elif mutation == "unknown_span":
        section_patch = section_patch.model_copy(update={"evidence_span_ids": ["SPAN-UNKNOWN1"]})
    elif mutation == "unapproved_finding":
        section_patch = section_patch.model_copy(
            update={"audit_finding_ids": ["F-AUDIT-NOT-APPROVED"]}
        )
    elif mutation == "unapproved_route":
        audit = audit.model_copy(
            update={"routing": audit.routing.model_copy(update={"route": "human_review"})}
        )
    elif mutation == "unchanged_body":
        section_patch = section_patch.model_copy(update={"revised_body": model.sections[0].body})
    patch = patch.model_copy(update={"section_patches": [section_patch]})

    with pytest.raises(ValidationError, match=message):
        apply_audit_revision_patches(model, audit, patch)
    assert model.sections[0].body != section_patch.revised_body or mutation == "unchanged_body"


def test_provider_cannot_add_unsupported_patch_fields() -> None:
    with pytest.raises(PydanticValidationError, match="Extra inputs are not permitted"):
        AuditRevisionPatchSet.model_validate(
            {
                "section_patches": [
                    {
                        "section_id": "SEC-PROC-PURPOSE",
                        "revised_body": "Revised body.",
                        "evidence_span_ids": ["SPAN-ABCDEFGH"],
                        "audit_finding_ids": [FINDING_ID],
                        "provenance": {"origin": "invented"},
                    }
                ]
            }
        )


class _PromotingGateway:
    def __init__(self, artifact: AuditRevisionPatchSet) -> None:
        self.artifact = artifact
        self.call: dict[str, Any] | None = None

    def invoke(self, **kwargs: Any) -> SimpleNamespace:
        self.call = kwargs
        promoted = kwargs["promote"](self.artifact)
        return SimpleNamespace(artifact=promoted)


def test_model_service_sends_only_patch_schema_and_promotes_to_strict_document(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    references = load_reference_pack(REFERENCE_ROOT)
    composer = PromptPackComposer(
        load_prompt_pack(PROMPT_ROOT, reference_pack=references),
        reference_pack=references,
        document_type="process",
    )
    gateway = _PromotingGateway(_patch(model))
    runner = GeminiAuditRevisionRunner(
        composer,
        cast(GeminiModelGateway, gateway),
        document_type=DocumentType.PROCESS,
    )

    revised = runner.revise(model, _audit(model))

    assert revised.sections[0].body.endswith("completion evidence.")
    assert gateway.call is not None
    provider_schema = cast(type[Any], gateway.call["schema"])
    assert not issubclass(provider_schema, AuditRevisionPatchSet)
    assert set(provider_schema.model_json_schema()["properties"]) == {
        "section_patches",
        "issue_resolutions",
    }
    assert gateway.call["result_schema"] is EnhancedDocumentModel
    assert len(json.dumps(provider_schema.model_json_schema())) < 10_000
    assert "Output schema name: audit-revision-patch.schema.json" in gateway.call["prompt"]
    assert len(gateway.call["input_digests"]) == 2
