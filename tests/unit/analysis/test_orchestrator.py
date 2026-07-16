from __future__ import annotations

import json
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
    GeminiMacroAnalysisReport,
    GeminiRagReadinessAnalysisReport,
    GeminiSectionAnalysisReport,
    GeminiSynthesisAnalysisReport,
)
from document_enhancer.analysis.macro import MacroReviewer
from document_enhancer.analysis.models import AnalysisRequest, AnalysisRunResult
from document_enhancer.analysis.orchestrator import AnalysisOrchestrator
from document_enhancer.analysis.promotion import promote_discovery_candidate_batch
from document_enhancer.analysis.provider_models import DiscoveryCandidateBatch
from document_enhancer.domain.analysis import (
    AnalysisReport,
    DiscoveryAnalysis,
    FindingSet,
    RubricScore,
)
from document_enhancer.domain.ontology import Statement
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
        "rag_readiness_reviewer": "rag_readiness",
        "finding_synthesizer": "synthesis",
    }
    for stage, analysis_type in expected_types.items():
        analyses = schemas_by_stage[stage]["properties"]["analyses"]
        assert "anyOf" not in analyses["items"]
        assert analyses["items"]["properties"]["analysis_type"]["enum"] == [analysis_type]
    discovery_schema = schemas_by_stage["process_methodology_discoverer"]
    assert set(discovery_schema["properties"]) == {"candidates", "relationships", "judgments"}
    candidate = discovery_schema["properties"]["candidates"]["items"]
    assert len(candidate["properties"]["entity_type"]["enum"]) == 42
    assert "entity_type" in candidate["required"]


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


def test_discovery_provider_schema_is_compact_and_only_exposes_safe_common_fields() -> None:
    schema = gemini_schema(DiscoveryCandidateBatch)
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    objects = schema["properties"]["candidates"]["items"]

    assert len(encoded) < 12_000
    assert set(objects["properties"]) == {
        "aliases",
        "basis",
        "confidence",
        "entity_type",
        "local_key",
        "name",
        "semantic_details",
        "source_span_id",
    }
    entity_types = set(objects["properties"]["entity_type"]["enum"])
    assert len(entity_types) == 42
    assert {"DocumentIdentity", "DocumentVersion", "Section"}.isdisjoint(entity_types)
    assert {"Statement", "Process", "Control"} <= entity_types
    assert set(objects["required"]) == {
        "local_key",
        "entity_type",
        "name",
        "source_span_id",
        "basis",
    }

    banned = {
        "analysis_id",
        "authority",
        "created_at",
        "document_id",
        "edge_id",
        "extracted_at",
        "finding_id",
        "id",
        "layer",
        "provenance",
        "provisional",
        "review_status",
        "source_digest",
        "timestamp",
    }

    def property_names(value: object) -> set[str]:
        if isinstance(value, dict):
            properties = value.get("properties")
            names = {str(name) for name in properties} if isinstance(properties, dict) else set()
            children: set[str] = set()
            for item in value.values():
                children.update(property_names(item))
            return names | children
        if isinstance(value, list):
            children = set()
            for item in value:
                children.update(property_names(item))
            return children
        return set()

    assert property_names(schema).isdisjoint(banned)


def test_discovery_promotion_is_full_domain_valid_and_deterministic(
    analysis_request: AnalysisRequest,
) -> None:
    span_id = analysis_request.authoritative_span_ids[1]
    payload = {
        "candidates": [
            {
                "local_key": "statement-one",
                "entity_type": "Statement",
                "name": "Compact provider object",
                "aliases": ["Candidate statement"],
                "source_span_id": span_id,
                "basis": "explicit",
                "semantic_details": [{"key": "text", "value": "Source-backed statement"}],
            }
        ],
        "relationships": [],
        "judgments": [],
    }

    provider = validate_artifact(DiscoveryCandidateBatch, payload)
    first = promote_discovery_candidate_batch(analysis_request, provider)
    second = promote_discovery_candidate_batch(analysis_request, provider)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert DiscoveryAnalysis.model_validate_json(first.model_dump_json()) == first
    assert isinstance(first.objects[0], Statement)
    assert first.objects[0].id.startswith("PROV-STMT-")
    assert first.objects[0].provisional is True
    assert first.objects[0].provenance.document_id == analysis_request.document_id
    assert first.objects[0].provenance.source_span_id == span_id
    assert first.objects[0].provenance.confidence is None


def test_discovery_promotion_quarantines_item_failures_without_inventing_confidence(
    analysis_request: AnalysisRequest,
) -> None:
    span_id = analysis_request.authoritative_span_ids[1]
    batch = DiscoveryCandidateBatch.model_validate(
        {
            "candidates": [
                {
                    "local_key": "good-role",
                    "entity_type": "Role",
                    "name": "Forecast Analyst",
                    "source_span_id": span_id,
                    "basis": "explicit",
                },
                {
                    "local_key": "unsafe-inference",
                    "entity_type": "Risk",
                    "name": "Possible missing control",
                    "source_span_id": span_id,
                    "basis": "inferred",
                },
            ],
            "relationships": [
                {
                    "local_key": "bad-edge",
                    "source_key": "good-role",
                    "relationship_type": "PERFORMED_BY",
                    "target_key": "unsafe-inference",
                    "source_span_id": span_id,
                    "basis": "inferred",
                }
            ],
            "judgments": [],
        }
    )

    promoted = promote_discovery_candidate_batch(analysis_request, batch)

    assert [item.name for item in promoted.objects] == ["Forecast Analyst"]
    assert promoted.candidate_relationships == []
    assert len(promoted.findings) == 2
    assert all(item.category == "candidate_quarantine" for item in promoted.findings)
    assert all(item.blocking is True for item in promoted.findings)
    assert all(item.severity.value == "blocker" for item in promoted.findings)
    assert all(item.target_object_id is None for item in promoted.findings)
    assert any("missing model confidence" in item.impact for item in promoted.findings)


def test_rubric_score_requires_at_least_one_authoritative_evidence_item() -> None:
    with pytest.raises(ValueError, match="at least 1 item"):
        RubricScore.model_validate(
            {
                "dimension": "purpose_scope",
                "score": 2,
                "weight": 10.0,
                "evidence": [],
                "explanation": "The source is incomplete.",
            }
        )

    schema = gemini_schema(GeminiMacroAnalysisReport)
    evidence = schema["properties"]["analyses"]["items"]["properties"]["rubric_scores"]["items"][
        "properties"
    ]["evidence"]
    assert evidence["minItems"] == 1
