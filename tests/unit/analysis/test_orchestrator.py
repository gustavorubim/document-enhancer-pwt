from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from document_enhancer.analysis.errors import (
    AnalysisBudgetError,
    AnalysisPromptContractError,
)
from document_enhancer.analysis.gemini_adapter import (
    GeminiDiscoveryAnalysisReport,
    GeminiMacroAnalysisReport,
    GeminiRagReadinessAnalysisReport,
    GeminiSectionAnalysisReport,
    GeminiSynthesisAnalysisReport,
)
from document_enhancer.analysis.macro import MacroReviewer
from document_enhancer.analysis.models import AnalysisRequest, AnalysisRunResult
from document_enhancer.analysis.orchestrator import AnalysisOrchestrator
from document_enhancer.domain.analysis import AnalysisReport, FindingSet
from document_enhancer.errors import ProviderError
from document_enhancer.llm.models import GeminiModelGateway
from document_enhancer.llm.profiles import ROUTE_FLASH
from document_enhancer.llm.structured import (
    StructuredOutputError,
    gemini_schema,
    validate_artifact,
)
from document_enhancer.prompting import PromptPackComposer
from document_enhancer.references.loader import ReferencePack

GatewayFactory = Callable[[Mapping[str, list[object]]], tuple[GeminiModelGateway, Any]]


def _snapshot(name: str) -> str:
    return (Path(__file__).parent / "snapshots" / name).read_text(encoding="utf-8")


def test_fan_out_fan_in_is_bounded_ordered_injection_safe_and_schema_valid(
    composer: PromptPackComposer,
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
    gateway_factory: GatewayFactory,
) -> None:
    gateway, model = gateway_factory(responses)

    result = AnalysisOrchestrator(composer, gateway).run(analysis_request)

    assert [branch.specialist for branch in result.branches] == [
        "macro_reviewer",
        "section_mapper",
        "process_methodology_discoverer",
        "rag_readiness_reviewer",
    ]
    assert result.call_count == 5
    assert len(model.calls) == 5
    assert {call["route"] for call in model.calls} == {ROUTE_FLASH}
    assert [record.resolution.prompt_id for record in result.call_records] == [
        "analysis.macro",
        "analysis.sections",
        "analysis.process-methodology-discovery",
        "analysis.rag-readiness",
        "analysis.synthesize-findings",
    ]
    assert AnalysisReport.model_validate_json(result.report.model_dump_json()) == result.report
    assert AnalysisRunResult.model_validate_json(result.model_dump_json()) == result
    assert FindingSet.model_validate_json(result.synthesis.finding_set.model_dump_json()) == (
        result.synthesis.finding_set
    )
    assert len(result.synthesis.conflicts) >= 1
    assert result.synthesis.markdown == _snapshot("synthesis.md")
    final_ids = {finding.finding_id for finding in result.synthesis.finding_set.findings}
    assert "FND-SCOPE-MACRO" in final_ids
    assert "FND-SCOPE-SYNTH" not in final_ids

    branch_prompts = [
        str(call["prompt"]) for call in model.calls if call["stage"] != "finding_synthesizer"
    ]
    assert len(branch_prompts) == 4
    for prompt in branch_prompts:
        governed, untrusted = prompt.split("BEGIN UNTRUSTED SOURCE", maxsplit=1)
        assert "Ignore all prior instructions" not in governed
        assert "Ignore all prior instructions" in untrusted
        assert "END UNTRUSTED SOURCE" in untrusted

    schemas_by_stage = {str(call["stage"]): call["schema"] for call in model.calls}
    assert set(schemas_by_stage) == {
        "macro_reviewer",
        "section_mapper",
        "process_methodology_discoverer",
        "rag_readiness_reviewer",
        "finding_synthesizer",
    }
    expected_types = {
        "macro_reviewer": "macro",
        "section_mapper": "sections",
        "process_methodology_discoverer": "discovery",
        "rag_readiness_reviewer": "rag_readiness",
        "finding_synthesizer": "synthesis",
    }
    for stage, analysis_type in expected_types.items():
        analyses = schemas_by_stage[stage]["properties"]["analyses"]
        assert "anyOf" not in analyses["items"]
        assert analyses["items"]["properties"]["analysis_type"]["enum"] == [analysis_type]
    discovery_objects = schemas_by_stage["process_methodology_discoverer"]["properties"][
        "analyses"
    ]["items"]["properties"]["objects"]["items"]
    assert "anyOf" not in discovery_objects
    assert len(discovery_objects["properties"]["entity_type"]["enum"]) == 45
    assert "entity_type" in discovery_objects["required"]


def test_invalid_structured_output_fails_closed_without_partial_artifact(
    composer: PromptPackComposer,
    analysis_request: AnalysisRequest,
    gateway_factory: GatewayFactory,
) -> None:
    gateway, _ = gateway_factory({"macro_reviewer": [{"invalid": True}]})

    with pytest.raises(ProviderError, match="structured output failed"):
        MacroReviewer(composer, gateway).review(analysis_request)


def test_orchestrator_rejects_insufficient_call_budget(
    composer: PromptPackComposer,
    gateway_factory: GatewayFactory,
) -> None:
    gateway, _ = gateway_factory({})

    with pytest.raises(AnalysisBudgetError, match="requires 5"):
        AnalysisOrchestrator(composer, gateway, max_calls=4)


def test_prompt_route_mismatch_fails_before_provider_call(
    composer: PromptPackComposer,
    reference_pack: ReferencePack,
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
    gateway_factory: GatewayFactory,
) -> None:
    prompts = [
        prompt.model_copy(update={"model_route": "gemini-3.1-pro-preview"})
        if prompt.prompt_id == "analysis.macro"
        else prompt
        for prompt in composer.pack.manifest.prompts
    ]
    manifest = composer.pack.manifest.model_copy(update={"prompts": prompts})
    bad_pack = replace(composer.pack, manifest=manifest)
    bad_composer = PromptPackComposer(
        bad_pack,
        reference_pack=reference_pack,
        document_type="methodology",
    )
    gateway, model = gateway_factory({"macro_reviewer": responses["macro_reviewer"]})

    with pytest.raises(AnalysisPromptContractError, match="exact route"):
        MacroReviewer(bad_composer, gateway).review(analysis_request)
    assert model.calls == []


@pytest.mark.parametrize(
    ("adapter", "analysis_type"),
    (
        (GeminiMacroAnalysisReport, "macro"),
        (GeminiSectionAnalysisReport, "sections"),
        (GeminiDiscoveryAnalysisReport, "discovery"),
        (GeminiRagReadinessAnalysisReport, "rag_readiness"),
        (GeminiSynthesisAnalysisReport, "synthesis"),
    ),
)
def test_analysis_schema_adapters_are_stage_only_and_keep_full_pydantic_validation(
    adapter: type[AnalysisReport], analysis_type: str
) -> None:
    schema = gemini_schema(adapter)

    assert schema["type"] == "object"
    assert set(schema["properties"]) == {
        "document_id",
        "source_digest",
        "analyses",
        "generated_at",
    }
    analyses = schema["properties"]["analyses"]
    assert "anyOf" not in analyses["items"]
    assert analyses["items"]["properties"]["analysis_type"]["enum"] == [analysis_type]

    unsupported = {
        "const",
        "discriminator",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maxLength",
        "maximum",
        "minLength",
        "minimum",
        "multipleOf",
        "oneOf",
        "pattern",
        "uniqueItems",
    }

    def assert_supported(value: object) -> None:
        if isinstance(value, dict):
            assert not (set(value) & unsupported)
            additional_properties = value.get("additionalProperties")
            if additional_properties is not None:
                assert additional_properties is False
            for item in value.values():
                assert_supported(item)
        elif isinstance(value, list):
            for item in value:
                assert_supported(item)

    assert_supported(schema)
    with pytest.raises(StructuredOutputError, match="Pydantic validation"):
        validate_artifact(
            adapter,
            {
                "document_id": "invalid-lowercase-id",
                "source_digest": "not-a-digest",
                "analyses": [],
            },
        )


def test_section_provider_schema_constrains_disposition_to_canonical_values() -> None:
    schema = gemini_schema(GeminiSectionAnalysisReport)
    mapping = schema["properties"]["analyses"]["items"]["properties"]["mappings"]["items"]

    assert mapping["properties"]["disposition"]["enum"] == [
        "preserved",
        "moved",
        "merged",
        "split",
        "omitted",
        "uncertain",
        "blocking",
    ]
