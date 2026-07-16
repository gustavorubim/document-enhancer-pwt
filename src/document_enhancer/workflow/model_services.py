"""Prompt-pack-backed adapters for the live enhancement workflow.

Each adapter exposes one narrow contract.  Source-controlled prompt metadata is checked before a
provider call, and returned artifacts are constrained again against deterministic workflow state
before they can be promoted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from document_enhancer.audit.content import ContentAuditRequest
from document_enhancer.domain.audit import Audit, IndependentAuditResult
from document_enhancer.domain.enums import DocumentType
from document_enhancer.domain.questions import (
    AnswersArtifact,
    ContentLedger,
    QuestionsArtifact,
    RewriteChecklist,
    Steering,
    WaiversArtifact,
)
from document_enhancer.errors import ValidationError
from document_enhancer.ingest.models import NormalizedDocument
from document_enhancer.llm import (
    ROUTE_FLASH,
    ROUTE_FLASH_LITE,
    ROUTE_PRO_PREVIEW,
    GeminiModelGateway,
)
from document_enhancer.prompting import PromptPackComposer
from document_enhancer.rewrite import (
    EnhancedDocumentModel,
    RevisionCounters,
    SectionRewriteDraft,
    SectionRewriteInput,
    build_enhanced_document,
)

_UNSUPPORTED_GEMINI_SCHEMA_KEYS = {
    "discriminator",
    "exclusiveMaximum",
    "exclusiveMinimum",
    "maxLength",
    "maximum",
    "minLength",
    "minimum",
    "multipleOf",
    "pattern",
    "uniqueItems",
}


def _provider_schema(value: Any) -> Any:
    """Project a strict persisted contract into Gemini's native-schema subset.

    Responses are still promoted through the complete inherited Pydantic contract.  This only
    removes validation keywords that Gemini rejects before a request can be sent.
    """

    if isinstance(value, list):
        return [_provider_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned: dict[str, Any] = {}
    for original_key, item in value.items():
        if original_key in _UNSUPPORTED_GEMINI_SCHEMA_KEYS:
            continue
        if original_key == "const":
            cleaned["enum"] = [item]
            continue
        key = "anyOf" if original_key == "oneOf" else original_key
        cleaned[key] = False if key == "additionalProperties" else _provider_schema(item)
    return cleaned


class _GeminiQuestionsArtifact(QuestionsArtifact):
    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return _provider_schema(QuestionsArtifact.model_json_schema(*args, **kwargs))


class _GeminiRewriteChecklist(RewriteChecklist):
    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return _provider_schema(RewriteChecklist.model_json_schema(*args, **kwargs))


class _GeminiSectionRewriteDraft(SectionRewriteDraft):
    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return _provider_schema(SectionRewriteDraft.model_json_schema(*args, **kwargs))


class _GeminiIndependentAuditResult(IndependentAuditResult):
    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return _provider_schema(IndependentAuditResult.model_json_schema(*args, **kwargs))


class _GeminiEnhancedDocumentModel(EnhancedDocumentModel):
    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return _provider_schema(EnhancedDocumentModel.model_json_schema(*args, **kwargs))


def _json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def _invoke(
    composer: PromptPackComposer,
    gateway: GeminiModelGateway,
    *,
    prompt_id: str,
    route: str,
    output_schema: str,
    schema: type[Any],
    variables: dict[str, object],
    stage: str,
    input_digests: tuple[str, ...] = (),
) -> Any:
    spec = composer.pack.prompt(prompt_id)
    if spec.model_route != route:
        raise ValidationError(
            f"prompt {prompt_id} must use exact route {route}, got {spec.model_route}"
        )
    if spec.output_schema != output_schema:
        raise ValidationError(
            f"prompt {prompt_id} must use output schema {output_schema}, got {spec.output_schema}"
        )
    if spec.optional_tools:
        raise ValidationError(f"prompt {prompt_id} must not enable tools")
    composed = composer.compose_with_metadata(prompt_id, variables)
    return gateway.invoke(
        route=route,
        schema=schema,
        prompt=composed.text,
        stage=stage,
        prompt_id=prompt_id,
        prompt_version=composed.pack_version,
        prompt_digest=composed.digest,
        input_digests=input_digests,
    ).artifact


class GeminiQuestionGenerator:
    prompt_id = "clarification.questions"

    def __init__(self, composer: PromptPackComposer, gateway: GeminiModelGateway) -> None:
        self.composer = composer
        self.gateway = gateway

    def generate(
        self,
        *,
        baseline: QuestionsArtifact,
        analysis_result: object,
        normalized: NormalizedDocument,
        document_type: DocumentType,
    ) -> QuestionsArtifact:
        artifact = _invoke(
            self.composer,
            self.gateway,
            prompt_id=self.prompt_id,
            route=ROUTE_FLASH_LITE,
            output_schema="questions.schema.json",
            schema=_GeminiQuestionsArtifact,
            variables={
                "document_type": document_type.value,
                "document_metadata": {
                    "document_id": baseline.document_id,
                    "source_digest": normalized.raw.source_digest,
                },
                "analysis_results": _json(analysis_result),
                "source_text": normalized.normalized_markdown,
                "reviewer_inputs": "",
            },
            stage="clarification_questions",
            input_digests=(normalized.raw.source_digest,),
        )
        if artifact.document_id != baseline.document_id:
            raise ValidationError("question generator returned a different document identity")
        known_spans = {block.span_id for block in normalized.raw.blocks}
        for question in artifact.questions:
            if any(item.span_id not in known_spans for item in question.evidence):
                raise ValidationError("question generator cited an unknown source span")
        required_findings = {
            finding_id
            for question in baseline.questions
            if question.blocking
            for finding_id in question.source_finding_ids
        }
        returned_findings = {
            finding_id
            for question in artifact.questions
            for finding_id in question.source_finding_ids
        }
        if not required_findings.issubset(returned_findings):
            raise ValidationError("question generator omitted a deterministic blocking finding")
        return artifact


class GeminiChecklistGenerator:
    prompt_id = "clarification.rewrite-checklist"

    def __init__(self, composer: PromptPackComposer, gateway: GeminiModelGateway) -> None:
        self.composer = composer
        self.gateway = gateway

    def generate(
        self,
        *,
        baseline: RewriteChecklist,
        questions: QuestionsArtifact,
        answers: AnswersArtifact,
        steering: Steering | None,
        waivers: WaiversArtifact,
        document_type: DocumentType,
    ) -> RewriteChecklist:
        reviewer = {
            "answers": answers.model_dump(mode="json"),
            "steering": steering.model_dump(mode="json") if steering else None,
            "waivers": waivers.model_dump(mode="json"),
        }
        artifact = _invoke(
            self.composer,
            self.gateway,
            prompt_id=self.prompt_id,
            route=ROUTE_FLASH_LITE,
            output_schema="rewrite-checklist.schema.json",
            schema=_GeminiRewriteChecklist,
            variables={
                "document_type": document_type.value,
                "document_metadata": {"document_id": questions.document_id},
                "analysis_results": _json(questions),
                "reviewer_inputs": _json(reviewer),
            },
            stage="rewrite_checklist",
        )
        if artifact.document_id != baseline.document_id:
            raise ValidationError("checklist generator returned a different document identity")
        required_questions = {item.question_id for item in baseline.items if item.question_id}
        returned_questions = {item.question_id for item in artifact.items if item.question_id}
        if not required_questions.issubset(returned_questions):
            raise ValidationError("checklist generator omitted a governed question")
        return artifact


@dataclass(frozen=True, slots=True)
class GovernedRewriteRequest:
    inputs: tuple[SectionRewriteInput, ...]
    ledger: ContentLedger
    document_id: str
    document_type: DocumentType
    reference_pack_id: str
    reference_pack_version: str
    template_id: str
    template_version: str
    counters: RevisionCounters


class GeminiGovernedRewriter:
    prompt_id = "rewrite.section"

    def __init__(self, composer: PromptPackComposer, gateway: GeminiModelGateway) -> None:
        self.composer = composer
        self.gateway = gateway

    def rewrite(self, request: GovernedRewriteRequest) -> EnhancedDocumentModel:
        model = build_enhanced_document(
            request.inputs,
            document_id=request.document_id,
            document_type=request.document_type,
            reference_pack_id=request.reference_pack_id,
            reference_pack_version=request.reference_pack_version,
            template_id=request.template_id,
            template_version=request.template_version,
            ledger=request.ledger,
            revision_counters=request.counters,
        )
        sections = {section.section_id: section for section in model.sections}
        for item in request.inputs:
            draft = _invoke(
                self.composer,
                self.gateway,
                prompt_id=self.prompt_id,
                route=ROUTE_PRO_PREVIEW,
                output_schema="section-rewrite.schema.json",
                schema=_GeminiSectionRewriteDraft,
                variables={
                    "document_type": request.document_type.value,
                    "document_metadata": {
                        "document_id": request.document_id,
                        "source_digest": item.source_digest,
                    },
                    "source_text": _json(
                        [evidence.model_dump(mode="json") for evidence in item.source_evidence]
                    ),
                    "approved_ledger": _json(item),
                    "target_section": _json(
                        {"section_id": item.section_id, "heading": item.heading}
                    ),
                    "reviewer_inputs": _json(
                        {
                            "answers": [
                                answer.model_dump(mode="json") for answer in item.approved_answers
                            ],
                            "steering": (
                                item.steering.model_dump(mode="json") if item.steering else None
                            ),
                        }
                    ),
                },
                stage="section_rewrite",
                input_digests=(item.source_digest,),
            )
            if draft.section_id != item.section_id:
                raise ValidationError("rewriter returned a different target section")
            if not set(draft.source_span_ids).issubset(item.allowed_source_span_ids):
                raise ValidationError("rewriter cited a source span outside the approved ledger")
            if not set(draft.approved_answer_ids).issubset(item.allowed_answer_ids):
                raise ValidationError("rewriter cited an unapproved reviewer answer")
            allowed_evidence = {(value.span_id, value.quote) for value in item.source_evidence}
            if any(
                (value.span_id, value.quote) not in allowed_evidence for value in draft.evidence
            ):
                raise ValidationError("rewriter returned evidence outside the approved ledger")
            original = sections[item.section_id]
            if not set(draft.open_issue_ids).issubset(original.open_issue_ids):
                raise ValidationError("rewriter created an ungoverned open issue")
            sections[item.section_id] = original.model_copy(
                update={
                    "body": draft.body,
                    "source_span_ids": draft.source_span_ids,
                    "evidence": draft.evidence,
                    "approved_answer_ids": draft.approved_answer_ids,
                    "open_issue_ids": draft.open_issue_ids,
                }
            )
        return model.model_copy(
            update={"sections": [sections[section.section_id] for section in model.sections]}
        )


class GeminiContentAuditor:
    prompt_id = "audit.content-fidelity"

    def __init__(
        self,
        composer: PromptPackComposer,
        gateway: GeminiModelGateway,
        *,
        document_type: DocumentType,
    ) -> None:
        self.composer = composer
        self.gateway = gateway
        self.document_type = document_type

    def audit(self, request: ContentAuditRequest) -> IndependentAuditResult:
        artifact = _invoke(
            self.composer,
            self.gateway,
            prompt_id=self.prompt_id,
            route=ROUTE_FLASH,
            output_schema="independent-audit.schema.json",
            schema=_GeminiIndependentAuditResult,
            variables={
                "document_type": self.document_type.value,
                "document_metadata": {"document_id": request.document_id},
                "source_text": request.source_markdown,
                "enhanced_document": request.enhanced_markdown,
                "reviewer_inputs": _json(
                    {
                        "checklist_digest": request.checklist_digest,
                        "steering_digest": request.steering_digest,
                    }
                ),
            },
            stage="independent_content_fidelity_audit",
        )
        for finding in artifact.findings:
            for evidence in finding.source_evidence:
                if evidence.quote and evidence.quote not in request.source_markdown:
                    raise ValidationError("content auditor cited source text that is not present")
            for evidence in finding.output_evidence:
                if evidence.quote and evidence.quote not in request.enhanced_markdown:
                    raise ValidationError("content auditor cited output text that is not present")
        return artifact.model_copy(
            update={"provider": f"google/{ROUTE_FLASH}", "isolated_context": True}
        )


class GeminiAuditRevisionRunner:
    prompt_id = "rewrite.revision"

    def __init__(
        self,
        composer: PromptPackComposer,
        gateway: GeminiModelGateway,
        *,
        document_type: DocumentType,
    ) -> None:
        self.composer = composer
        self.gateway = gateway
        self.document_type = document_type

    def revise(self, model: EnhancedDocumentModel, audit: Audit) -> EnhancedDocumentModel:
        revised = _invoke(
            self.composer,
            self.gateway,
            prompt_id=self.prompt_id,
            route=ROUTE_PRO_PREVIEW,
            output_schema="enhanced-document.schema.json",
            schema=_GeminiEnhancedDocumentModel,
            variables={
                "document_type": self.document_type.value,
                "document_metadata": {"document_id": model.document.id},
                "enhanced_document": _json(model),
                "audit_findings": _json(audit),
                "reviewer_inputs": "",
            },
            stage="bounded_revision",
        )
        immutable_before = (
            model.document.id,
            model.version.id,
            model.document.source_digest,
            model.ledger_id,
            model.reference_pack_id,
            model.reference_pack_version,
            model.template_id,
            model.template_version,
        )
        immutable_after = (
            revised.document.id,
            revised.version.id,
            revised.document.source_digest,
            revised.ledger_id,
            revised.reference_pack_id,
            revised.reference_pack_version,
            revised.template_id,
            revised.template_version,
        )
        if immutable_after != immutable_before:
            raise ValidationError("audit revision changed immutable governed identity")
        return revised


__all__ = [
    "GeminiAuditRevisionRunner",
    "GeminiChecklistGenerator",
    "GeminiContentAuditor",
    "GeminiGovernedRewriter",
    "GeminiQuestionGenerator",
    "GovernedRewriteRequest",
]
