"""Prompt-pack and Gemini gateway adapter for schema-valid analysis reports.

The persisted analysis schema contains validation keywords that Pydantic enforces but the
Gemini native-schema subset does not accept.  The adapter removes only those provider-side
keywords.  The gateway still promotes every response through the complete ``AnalysisReport``
contract before this lane accepts it.
"""

from __future__ import annotations

import json
from typing import Any

from document_enhancer.domain.analysis import (
    AnalysisReport,
    DiscoveryAnalysis,
    MacroAnalysis,
    RagReadinessAnalysis,
    SectionAnalysis,
    SynthesisAnalysis,
)
from document_enhancer.llm.models import GeminiModelGateway
from document_enhancer.llm.profiles import ROUTE_FLASH
from document_enhancer.prompting import ComposedPrompt, PromptPackComposer

from .errors import AnalysisPromptContractError
from .models import PromptCallRecord

ANALYSIS_OUTPUT_SCHEMA = "analysis.schema.json"

_UNSUPPORTED_VALIDATION_KEYS = {
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
    """Return a semantics-preserving Gemini subset of the persisted JSON Schema."""

    if isinstance(value, list):
        return [_provider_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned: dict[str, Any] = {}
    for original_key, item in value.items():
        if original_key in _UNSUPPORTED_VALIDATION_KEYS:
            continue
        if original_key == "const":
            cleaned["enum"] = [item]
            continue
        key = "anyOf" if original_key == "oneOf" else original_key
        if key == "additionalProperties" and item is True:
            # Gemini cannot represent free-form dictionaries. These fields are optional in the
            # candidate graph and remain fully validated if a provider returns them through a
            # recorded/future adapter that supports them.
            cleaned[key] = False
        else:
            cleaned[key] = _provider_schema(item)
    return cleaned


def _collapse_discovery_object_union(schema: dict[str, Any]) -> dict[str, Any]:
    """Merge the ontology discriminator union into one bounded provider object.

    The persisted ``DiscoveryAnalysis`` still validates each returned object against its exact
    discriminated subtype. The native provider schema carries the union of relevant fields once,
    avoiding dozens of repeated copies of the common entity/provenance graph.
    """

    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):  # pragma: no cover - Pydantic contract invariant
        return schema
    discovery = definitions.get("DiscoveryAnalysis")
    if not isinstance(discovery, dict):  # pragma: no cover - Pydantic contract invariant
        return schema
    try:
        items = discovery["properties"]["objects"]["items"]
        variants = items["oneOf"]
    except (KeyError, TypeError):  # pragma: no cover - Pydantic contract invariant
        return schema
    if not isinstance(variants, list) or not variants:
        return schema

    variant_schemas: list[dict[str, Any]] = []
    for variant in variants:
        if not isinstance(variant, dict) or not isinstance(variant.get("$ref"), str):
            return schema
        name = variant["$ref"].removeprefix("#/$defs/")
        resolved = definitions.get(name)
        if not isinstance(resolved, dict):
            return schema
        variant_schemas.append(resolved)

    property_options: dict[str, dict[str, dict[str, Any]]] = {}
    required = set(variant_schemas[0].get("required", []))
    entity_types: set[str] = set()
    for variant in variant_schemas:
        required &= set(variant.get("required", []))
        properties = variant.get("properties", {})
        if not isinstance(properties, dict):
            return schema
        for name, value in properties.items():
            if not isinstance(value, dict):
                continue
            if name == "entity_type":
                literal = value.get("const")
                if isinstance(literal, str):
                    entity_types.add(literal)
                continue
            canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
            property_options.setdefault(name, {})[canonical] = value

    merged_properties: dict[str, Any] = {
        "entity_type": {"type": "string", "enum": sorted(entity_types)}
    }
    required.add("entity_type")
    for name, options in sorted(property_options.items()):
        values = list(options.values())
        merged_properties[name] = values[0] if len(values) == 1 else {"anyOf": values}
    discovery["properties"]["objects"]["items"] = {
        "type": "object",
        "properties": merged_properties,
        "required": sorted(required),
        "additionalProperties": False,
    }
    return schema


class _GeminiStageReport(AnalysisReport):
    """Provider projection shared by exact stage report contracts."""

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return _provider_schema(super().model_json_schema(*args, **kwargs))


class GeminiMacroAnalysisReport(_GeminiStageReport):
    analyses: list[MacroAnalysis]


class GeminiSectionAnalysisReport(_GeminiStageReport):
    analyses: list[SectionAnalysis]


class GeminiDiscoveryAnalysisReport(_GeminiStageReport):
    analyses: list[DiscoveryAnalysis]

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raw = super(_GeminiStageReport, cls).model_json_schema(*args, **kwargs)
        return _provider_schema(_collapse_discovery_object_union(raw))


class GeminiRagReadinessAnalysisReport(_GeminiStageReport):
    analyses: list[RagReadinessAnalysis]


class GeminiSynthesisAnalysisReport(_GeminiStageReport):
    analyses: list[SynthesisAnalysis]


_STAGE_SCHEMAS: dict[str, type[_GeminiStageReport]] = {
    "analysis.macro": GeminiMacroAnalysisReport,
    "analysis.sections": GeminiSectionAnalysisReport,
    "analysis.process-methodology-discovery": GeminiDiscoveryAnalysisReport,
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
    source_digest: str,
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
        item.sha256 for item in composed.resolved_references if item.sha256 != source_digest
    )
    call = gateway.invoke(
        route=ROUTE_FLASH,
        schema=provider_schema,
        prompt=composed.text,
        stage=stage,
        prompt_id=prompt_id,
        prompt_version=composed.pack_version,
        prompt_digest=composed.digest,
        input_digests=[source_digest, *reference_digests],
        input_token_budget=composed.input_token_budget,
        output_token_budget=composed.output_token_budget,
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


__all__ = [
    "ANALYSIS_OUTPUT_SCHEMA",
    "GeminiDiscoveryAnalysisReport",
    "GeminiMacroAnalysisReport",
    "GeminiRagReadinessAnalysisReport",
    "GeminiSectionAnalysisReport",
    "GeminiSynthesisAnalysisReport",
    "compose_analysis_prompt",
    "invoke_analysis_report",
]
