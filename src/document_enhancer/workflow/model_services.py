"""Prompt-pack-backed adapters for the live enhancement workflow.

Each adapter exposes one narrow contract.  Source-controlled prompt metadata is checked before a
provider call, and returned artifacts are constrained again against deterministic workflow state
before they can be promoted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, cast

from pydantic import BaseModel

from document_enhancer.audit import AuditRevisionPatchSet, apply_audit_revision_patches
from document_enhancer.audit.content import ContentAuditRequest
from document_enhancer.domain.analysis import AnalysisReport, Finding, FindingSet
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


class _GeminiAuditRevisionPatchSet(AuditRevisionPatchSet):
    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return _provider_schema(AuditRevisionPatchSet.model_json_schema(*args, **kwargs))


def _json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def _json_digest(value: object) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _analysis_findings(value: object) -> tuple[Finding, ...]:
    """Resolve only the promoted findings needed by the clarification boundary."""

    if isinstance(value, FindingSet):
        return tuple(value.findings)
    if isinstance(value, AnalysisReport):
        return tuple(finding for analysis in value.analyses for finding in analysis.findings)
    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        for key in ("finding_set", "synthesis", "report"):
            if key in mapping:
                findings = _analysis_findings(mapping[key])
                if findings:
                    return findings
        raw_findings = mapping.get("findings")
        if isinstance(raw_findings, list):
            return tuple(Finding.model_validate(item) for item in raw_findings)
        return ()
    synthesis = getattr(value, "synthesis", None)
    if synthesis is not None:
        findings = _analysis_findings(synthesis)
        if findings:
            return findings
    finding_set = getattr(value, "finding_set", None)
    if finding_set is not None:
        return _analysis_findings(finding_set)
    return ()


def _question_input(baseline: QuestionsArtifact, analysis_result: object) -> dict[str, object]:
    """Build the compact deterministic question seed instead of serializing the full fan-out."""

    finding_ids = sorted(
        {
            finding_id
            for question in baseline.questions
            for finding_id in question.source_finding_ids
        }
    )
    findings_by_id = {
        finding.finding_id: finding for finding in _analysis_findings(analysis_result)
    }
    finding_fields = {
        "finding_id",
        "category",
        "severity",
        "finding_type",
        "target_template_section",
        "target_object_id",
        "requirement_id",
        "impact",
        "proposed_disposition",
        "requires_human_answer",
        "blocking",
    }
    return {
        "baseline_questions": baseline.model_dump(
            mode="json",
            exclude={"generated_at", "digest"},
            exclude_none=True,
        ),
        # Evidence is already present on the deterministic baseline question. Repeating it on
        # each finding consumes budget without improving the model's decision boundary.
        "findings": [
            findings_by_id[finding_id].model_dump(
                mode="json",
                include=finding_fields,
                exclude_none=True,
            )
            for finding_id in finding_ids
            if finding_id in findings_by_id
        ],
    }


def _checklist_input(baseline: RewriteChecklist, questions: QuestionsArtifact) -> dict[str, object]:
    """Retain the governed checklist seed plus only question fields needed for reconciliation."""

    return {
        "baseline_checklist": baseline.model_dump(
            mode="json",
            exclude={"digest"},
            exclude_none=True,
        ),
        "question_summaries": [
            question.model_dump(
                mode="json",
                include={
                    "question_id",
                    "blocking",
                    "question",
                    "source_finding_ids",
                    "target_section_id",
                    "target_object_id",
                    "depends_on_question_ids",
                },
                exclude_none=True,
            )
            for question in questions.questions
        ],
    }


def _reviewer_input(
    answers: AnswersArtifact,
    steering: Steering | None,
    waivers: WaiversArtifact,
) -> dict[str, object]:
    return {
        "answers": answers.model_dump(
            mode="json",
            exclude={"generated_at", "digest"},
            exclude_none=True,
        ),
        "steering": (
            steering.model_dump(
                mode="json",
                exclude={"created_at"},
                exclude_none=True,
            )
            if steering
            else None
        ),
        "waivers": waivers.model_dump(
            mode="json",
            exclude={"generated_at", "digest"},
            exclude_none=True,
        ),
    }


def _promote_questions(
    baseline: QuestionsArtifact,
    value: object,
) -> QuestionsArtifact:
    """Constrain provider questions to deterministic identity, findings, and evidence handles."""

    artifact = QuestionsArtifact.model_validate(value)
    if artifact.document_id != baseline.document_id:
        raise ValidationError("question generator returned a different document identity")
    allowed_evidence = {
        (evidence.span_id, evidence.quote)
        for question in baseline.questions
        for evidence in question.evidence
    }
    for question in artifact.questions:
        if any(
            (evidence.span_id, evidence.quote) not in allowed_evidence
            for evidence in question.evidence
        ):
            raise ValidationError(
                "question generator cited evidence outside the deterministic baseline"
            )
    required_findings = {
        finding_id
        for question in baseline.questions
        if question.blocking
        for finding_id in question.source_finding_ids
    }
    returned_findings = {
        finding_id for question in artifact.questions for finding_id in question.source_finding_ids
    }
    if not required_findings.issubset(returned_findings):
        raise ValidationError("question generator omitted a deterministic blocking finding")
    return artifact


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
    promote: Callable[[Any], Any] | None = None,
    result_schema: type[Any] | None = None,
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
        input_token_budget=composed.input_token_budget,
        output_token_budget=composed.output_token_budget,
        promote=promote,
        result_schema=result_schema,
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
        question_input = _question_input(baseline, analysis_result)
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
                "analysis_results": _json(question_input),
                "reviewer_inputs": "",
            },
            stage="clarification_questions",
            input_digests=(normalized.raw.source_digest, _json_digest(question_input)),
            promote=lambda value: _promote_questions(baseline, value),
            result_schema=QuestionsArtifact,
        )
        return QuestionsArtifact.model_validate(artifact)


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
        checklist_input = _checklist_input(baseline, questions)
        reviewer = _reviewer_input(answers, steering, waivers)
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
                "analysis_results": _json(checklist_input),
                "reviewer_inputs": _json(reviewer),
            },
            stage="rewrite_checklist",
            input_digests=(_json_digest(checklist_input), _json_digest(reviewer)),
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
            output_schema="audit-revision-patch.schema.json",
            schema=_GeminiAuditRevisionPatchSet,
            variables={
                "document_type": self.document_type.value,
                "document_metadata": {"document_id": model.document.id},
                "enhanced_document": _json(model),
                "audit_findings": _json(audit),
                "reviewer_inputs": "",
            },
            stage="bounded_revision",
            input_digests=(_json_digest(model), _json_digest(audit)),
            promote=lambda value: apply_audit_revision_patches(model, audit, value),
            result_schema=EnhancedDocumentModel,
        )
        return EnhancedDocumentModel.model_validate(revised)


__all__ = [
    "GeminiAuditRevisionRunner",
    "GeminiChecklistGenerator",
    "GeminiContentAuditor",
    "GeminiGovernedRewriter",
    "GeminiQuestionGenerator",
    "GovernedRewriteRequest",
]
