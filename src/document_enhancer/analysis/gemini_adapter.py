"""Prompt-pack and Gemini gateway adapters for schema-valid analysis calls.

All analysis calls use narrow provider DTOs. Separate deterministic promoters construct and
validate persistence-grade reports inside the gateway's bounded repair/cache boundary.
"""

from __future__ import annotations

from typing import Any

from document_enhancer.domain.analysis import (
    AnalysisReport,
    DiscoveryAnalysis,
)
from document_enhancer.llm.models import GeminiModelGateway
from document_enhancer.llm.profiles import ROUTE_FLASH
from document_enhancer.prompting import ComposedPrompt, PromptPackComposer

from .errors import AnalysisPromptContractError
from .models import AnalysisRequest, PromptCallRecord
from .promotion import promote_discovery_candidate_batch
from .provider_models import DiscoveryCandidateBatch
from .stage_promotion import (
    GeminiMacroAnalysisReport,
    GeminiRagReadinessAnalysisReport,
    GeminiSectionAnalysisReport,
    GeminiSynthesisAnalysisReport,
    promote_stage_report,
)

ANALYSIS_OUTPUT_SCHEMA = "analysis.schema.json"

_STAGE_SCHEMAS = {
    "analysis.macro": GeminiMacroAnalysisReport,
    "analysis.sections": GeminiSectionAnalysisReport,
    "analysis.rag-readiness": GeminiRagReadinessAnalysisReport,
    "analysis.synthesize-findings": GeminiSynthesisAnalysisReport,
}


def compose_analysis_prompt(
    composer: PromptPackComposer,
    *,
    prompt_id: str,
    variables: dict[str, Any],
) -> ComposedPrompt:
    """Compose and verify the immutable prompt-pack contract before any model call."""

    try:
        spec = composer.pack.prompt(prompt_id)
    except KeyError as exc:  # pragma: no cover - composer gives the same diagnostic
        raise AnalysisPromptContractError(f"analysis prompt is unavailable: {prompt_id}") from exc
    if spec.prompt_id != prompt_id:
        raise AnalysisPromptContractError("resolved prompt ID does not match the requested ID")
    if spec.model_route != ROUTE_FLASH:
        raise AnalysisPromptContractError(
            f"analysis prompt {prompt_id} must use exact route {ROUTE_FLASH}, got {spec.model_route}"
        )
    if spec.output_schema != ANALYSIS_OUTPUT_SCHEMA:
        raise AnalysisPromptContractError(
            f"analysis prompt {prompt_id} must use {ANALYSIS_OUTPUT_SCHEMA}"
        )
    if spec.optional_tools:
        raise AnalysisPromptContractError(f"analysis prompt {prompt_id} must not enable tools")
    composed = composer.compose_with_metadata(prompt_id, variables)
    if composed.prompt_id != prompt_id or composed.resolution.prompt_id != prompt_id:
        raise AnalysisPromptContractError("composed prompt identity mismatch")
    if composed.resolution.output_schema != ANALYSIS_OUTPUT_SCHEMA:
        raise AnalysisPromptContractError("composed prompt output-schema mismatch")
    return composed


def invoke_analysis_report(
    gateway: GeminiModelGateway,
    composer: PromptPackComposer,
    *,
    prompt_id: str,
    variables: dict[str, Any],
    stage: str,
    request: AnalysisRequest,
) -> tuple[AnalysisReport, PromptCallRecord]:
    """Invoke exactly one native-structured Flash call and record all prompt/model evidence."""

    composed = compose_analysis_prompt(composer, prompt_id=prompt_id, variables=variables)
    try:
        provider_schema = _STAGE_SCHEMAS[prompt_id]
    except KeyError as exc:
        raise AnalysisPromptContractError(
            f"analysis prompt has no exact provider schema: {prompt_id}"
        ) from exc
    reference_digests = sorted(
        item.sha256 for item in composed.resolved_references if item.sha256 != request.source_digest
    )
    call = gateway.invoke(
        route=ROUTE_FLASH,
        schema=provider_schema,
        prompt=composed.text,
        stage=stage,
        prompt_id=prompt_id,
        prompt_version=composed.pack_version,
        prompt_digest=composed.digest,
        input_digests=[request.source_digest, *reference_digests],
        input_token_budget=composed.input_token_budget,
        output_token_budget=composed.output_token_budget,
        promote=lambda provider_report: promote_stage_report(
            request,
            provider_report,
            prompt_id=prompt_id,
        ),
        result_schema=AnalysisReport,
    )
    manifest = call.manifest
    if (
        manifest.requested_route_id != ROUTE_FLASH
        or manifest.effective_route_id != ROUTE_FLASH
        or manifest.model != ROUTE_FLASH
    ):
        raise AnalysisPromptContractError("analysis model route changed during invocation")
    if manifest.prompt_id != prompt_id or manifest.prompt_version != composed.pack_version:
        raise AnalysisPromptContractError("analysis call manifest prompt identity mismatch")
    if manifest.prompt_digest != composed.digest:
        raise AnalysisPromptContractError("analysis call manifest prompt digest mismatch")
    report = AnalysisReport.model_validate(call.artifact.model_dump(mode="python"))
    record = PromptCallRecord(
        resolution=composed.resolution.model_copy(deep=True),
        manifest=manifest.model_copy(deep=True),
    )
    return report, record


def invoke_discovery_candidate_batch(
    gateway: GeminiModelGateway,
    composer: PromptPackComposer,
    *,
    variables: dict[str, Any],
    stage: str,
    source_digest: str,
    request: AnalysisRequest,
) -> tuple[DiscoveryAnalysis, PromptCallRecord]:
    """Invoke the narrow DTO and promote it inside the bounded repair/cache boundary."""

    prompt_id = "analysis.process-methodology-discovery"
    composed = compose_analysis_prompt(composer, prompt_id=prompt_id, variables=variables)
    reference_digests = sorted(
        item.sha256 for item in composed.resolved_references if item.sha256 != source_digest
    )
    call = gateway.invoke(
        route=ROUTE_FLASH,
        schema=DiscoveryCandidateBatch,
        prompt=composed.text,
        stage=stage,
        prompt_id=prompt_id,
        prompt_version=composed.pack_version,
        prompt_digest=composed.digest,
        input_digests=[source_digest, *reference_digests],
        input_token_budget=composed.input_token_budget,
        output_token_budget=composed.output_token_budget,
        promote=lambda batch: promote_discovery_candidate_batch(request, batch),
        result_schema=DiscoveryAnalysis,
    )
    manifest = call.manifest
    if (
        manifest.requested_route_id != ROUTE_FLASH
        or manifest.effective_route_id != ROUTE_FLASH
        or manifest.model != ROUTE_FLASH
    ):
        raise AnalysisPromptContractError("analysis model route changed during invocation")
    if manifest.prompt_id != prompt_id or manifest.prompt_version != composed.pack_version:
        raise AnalysisPromptContractError("analysis call manifest prompt identity mismatch")
    if manifest.prompt_digest != composed.digest:
        raise AnalysisPromptContractError("analysis call manifest prompt digest mismatch")
    analysis = DiscoveryAnalysis.model_validate(call.artifact.model_dump(mode="python"))
    record = PromptCallRecord(
        resolution=composed.resolution.model_copy(deep=True),
        manifest=manifest.model_copy(deep=True),
    )
    return analysis, record


__all__ = [
    "ANALYSIS_OUTPUT_SCHEMA",
    "GeminiMacroAnalysisReport",
    "GeminiRagReadinessAnalysisReport",
    "GeminiSectionAnalysisReport",
    "GeminiSynthesisAnalysisReport",
    "compose_analysis_prompt",
    "invoke_analysis_report",
    "invoke_discovery_candidate_batch",
]
