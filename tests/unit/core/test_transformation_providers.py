"""DFT-5 provider seams use complete context and strict transformation contracts."""

from __future__ import annotations

import json
from typing import cast

import pytest

from document_enhancer.core.context_budget import ContextBudgetError, preflight_context
from document_enhancer.core.providers import GeminiTransformationProvider
from document_enhancer.core.transformation import VisualExtraction as BundleVisualExtraction
from document_enhancer.core.visuals import VisualContent, VisualExtraction
from document_enhancer.llm import FakeStructuredModel, GeminiGatewayConfig, GeminiModelGateway

_SOURCE_DIGEST = "a" * 64
_RECIPE_DIGEST = "b" * 64
_FIGURE_DIGEST = "c" * 64


def _visual() -> VisualExtraction:
    return VisualExtraction(
        figure_id="FIG-001",
        asset_id="asset-001",
        name="table.png",
        media_type="image/png",
        source_sha256=_FIGURE_DIGEST,
        size_bytes=1,
        source_path="assets/source/FIG-001.png",
        source_span_ids=("span-1",),
        kind="table",
        status="requires_review",
        structured_content=VisualContent(cells=[["Role", "Owner"], ["Maker", "Ops"]]),
    )


def _mapping_response(*, with_gap: bool) -> dict[str, object]:
    if with_gap:
        placements = [
            {
                "template_section_id": "SEC-1",
                "heading": "Purpose",
                "status": "populated",
                "source_span_ids": ["span-1"],
                "order": 10,
            },
            {
                "template_section_id": "SEC-2",
                "heading": "Controls",
                "status": "missing",
                "gap_ids": ["GAP-001"],
                "order": 20,
            },
        ]
        dispositions = [
            {
                "source_span_id": "span-1",
                "action": "placed",
                "destination_section_ids": ["SEC-1"],
                "rationale": "The source states the purpose.",
            },
            {
                "source_span_id": "span-2",
                "action": "intentionally_omitted",
                "rationale": "The source is not evidence for the missing control.",
            },
        ]
        gaps = [
            {
                "gap_id": "GAP-001",
                "template_section_id": "SEC-2",
                "kind": "missing",
                "description": "The source does not identify the control owner.",
                "question_id": "Q-001",
            }
        ]
        questions = [
            {
                "question_id": "Q-001",
                "prompt": "Which control owner should be recorded?",
                "reason": "The required control section has no owner evidence.",
                "context": "Whole-document context: the source names a performer but no accountable owner.",
                "section_id": "SEC-2",
                "suggestion": "Set the control owner to Operations.",
                "suggestion_basis": "recipe_guidance",
            }
        ]
    else:
        placements = [
            {
                "template_section_id": "SEC-1",
                "heading": "Purpose",
                "status": "populated",
                "source_span_ids": ["span-1"],
                "order": 10,
            },
            {
                "template_section_id": "SEC-2",
                "heading": "Controls",
                "status": "populated",
                "source_span_ids": ["span-2"],
                "order": 20,
            },
        ]
        dispositions = [
            {
                "source_span_id": "span-1",
                "action": "placed",
                "destination_section_ids": ["SEC-1"],
                "rationale": "The source states the purpose.",
            },
            {
                "source_span_id": "span-2",
                "action": "placed",
                "destination_section_ids": ["SEC-2"],
                "rationale": "The source states the control.",
            },
        ]
        gaps = []
        questions = []
    return {
        "macro": {"summary": "The source can be mapped without invention."},
        "sections": [
            {
                "section_id": "SEC-1",
                "title": "Purpose",
                "status": "correct",
                "evidence_span_ids": ["span-1"],
            }
        ],
        "process": {"applicable": False},
        "questions": questions,
        "source_dispositions": dispositions,
        "gaps": gaps,
        "template_placement": placements,
    }


def _draft_response() -> dict[str, object]:
    return {
        "sections": [
            {
                "template_section_id": "SEC-1",
                "rewritten_markdown": "The process has a documented purpose.",
            },
            {
                "template_section_id": "SEC-2",
                "rewritten_markdown": "The documented control is retained with clearer wording.",
            },
        ]
    }


def _gateway(responses: list[object]) -> GeminiModelGateway:
    fake = FakeStructuredModel(responses)
    return GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, max_repairs_override=0),
        model_factory=lambda *_: fake,
    )


def test_context_preflight_accounts_for_every_complete_component_and_never_truncates() -> None:
    result = preflight_context(
        source_text="é" * 12,
        template_text="# Template\nRequired section",
        visual_evidence=[{"figure_id": "FIG-001", "cells": [["A"]]}],
        prompt_text="Return the strict schema.",
        expected_output={"sections": [{"rewritten_markdown": "..."}]},
    )

    assert result.status == "fit"
    assert result.complete_context is True
    assert result.truncated is False
    assert result.input_tokens == sum(
        (
            result.source_tokens,
            result.template_tokens,
            result.visual_evidence_tokens,
            result.prompt_tokens,
        )
    )
    oversized = preflight_context(source_text="x" * 300_000, route="analysis")
    assert oversized.status == "oversized"
    assert oversized.truncated is False
    assert "complete_input_exceeds_input_budget" in oversized.reasons


def test_mapping_returns_macro_sections_process_questions_dispositions_coverage_and_placement() -> (
    None
):
    provider = GeminiTransformationProvider(_gateway([_mapping_response(with_gap=True)]))

    result = provider.map_document(
        source_text="# Source\nThe performer is recorded.\nA control is not specified.",
        source_digest=_SOURCE_DIGEST,
        recipe=None,
        template_text="# Purpose\n# Controls",
        source_spans=[
            {"span_id": "span-1", "text": "The performer is recorded."},
            {"span_id": "span-2", "text": "A control is not specified."},
        ],
        visual_extractions=[_visual()],
    )

    assert result.macro.summary.startswith("The source")
    assert result.sections[0].section_id == "SEC-1"
    assert result.process.applicable is False
    assert result.source_dispositions[0].source_span_id == "span-1"
    assert result.template_placement[1].status == "missing"
    assert result.coverage.valid is True
    assert result.coverage.source_span_coverage == 1.0
    assert result.contextual_questions[0].context.startswith("Whole-document context:")
    assert result.contextual_questions[0].suggestion is None
    assert result.contextual_questions[0].suggestion_basis == "none"
    assert result.bundle.questions[0].suggestion is None
    assert result.manifest.context_status == "fit"
    manifest_text = json.dumps(result.manifest.model_dump(mode="json"))
    assert "The performer is recorded" not in manifest_text
    assert "# Purpose" not in manifest_text


def test_draft_consumes_frozen_mapping_and_returns_typed_sections() -> None:
    provider = GeminiTransformationProvider(
        _gateway([_mapping_response(with_gap=False), _draft_response()])
    )
    mapping = provider.map_document(
        source_text="Purpose and control source.",
        source_digest=_SOURCE_DIGEST,
        template_text="# Purpose\n# Controls",
        source_spans=[
            {"span_id": "span-1", "text": "Purpose source."},
            {"span_id": "span-2", "text": "Control source."},
        ],
    )

    draft = provider.generate_draft(
        source_text="Purpose and control source.",
        mapping=mapping,
        template_text="# Purpose\n# Controls",
    )

    assert [item.template_section_id for item in draft.sections] == ["SEC-1", "SEC-2"]
    assert draft.sections[0].rewritten_markdown.startswith("The process")
    assert draft.sections[0].source_span_ids == ["span-1"]
    assert draft.coverage.valid is True
    assert draft.mapping_digest == mapping.mapping_digest
    assert "final_markdown" not in draft.model_dump(mode="json")


def test_draft_rejects_provider_reference_changes() -> None:
    changed = _draft_response()
    original_sections = cast(list[object], changed["sections"])
    changed["sections"] = [
        {
            "template_section_id": "SEC-1",
            "rewritten_markdown": "Unsupported placement.",
            "source_span_ids": ["span-404"],
        },
        original_sections[1],
    ]
    provider = GeminiTransformationProvider(_gateway([_mapping_response(with_gap=False), changed]))
    mapping = provider.map_document(
        source_text="Source.",
        source_digest=_SOURCE_DIGEST,
        template_text="# Purpose\n# Controls",
        source_spans=[
            {"span_id": "span-1", "text": "Purpose."},
            {"span_id": "span-2", "text": "Control."},
        ],
    )

    with pytest.raises(ValueError, match="frozen source_span_ids"):
        provider.generate_draft(
            source_text="Source.",
            mapping=mapping,
            template_text="# Purpose\n# Controls",
        )


def test_independent_audit_rejects_provider_fidelity_findings() -> None:
    audit_response = {
        "status": "pass",
        "checks": [{"name": "content_supported", "passed": True}],
        "unsupported_additions": ["invented approval threshold"],
        "omissions": ["SEC-2"],
        "invalid_references": ["FIG-404"],
        "summary": "The candidate is not faithful.",
    }
    provider = GeminiTransformationProvider(
        _gateway([_mapping_response(with_gap=False), _draft_response(), audit_response])
    )
    mapping = provider.map_document(
        source_text="Source.",
        source_digest=_SOURCE_DIGEST,
        template_text="# Purpose\n# Controls",
        source_spans=[
            {"span_id": "span-1", "text": "Purpose."},
            {"span_id": "span-2", "text": "Control."},
        ],
    )
    draft = provider.generate_draft(
        source_text="Source.",
        mapping=mapping,
        template_text="# Purpose\n# Controls",
    )
    audit = provider.audit_draft(
        source_text="Source.",
        mapping=mapping,
        draft=draft,
        template_text="# Purpose\n# Controls",
    )

    assert audit.status == "fail"
    assert audit.accepted is False
    assert audit.unsupported_additions == ["invented approval threshold"]
    assert audit.omissions == ["SEC-2"]
    assert audit.invalid_references == ["FIG-404"]
    assert audit.manifest.status == "success"


def test_independent_audit_rejects_unresolved_blocking_gap_even_if_provider_says_pass() -> None:
    provider = GeminiTransformationProvider(
        _gateway(
            [
                _mapping_response(with_gap=True),
                {
                    "sections": [
                        {
                            "template_section_id": "SEC-1",
                            "rewritten_markdown": "The purpose is retained.",
                        },
                        {"template_section_id": "SEC-2", "rewritten_markdown": ""},
                    ]
                },
                {"status": "pass", "summary": "No unsupported additions were found."},
            ]
        )
    )
    mapping = provider.map_document(
        source_text="Source.",
        source_digest=_SOURCE_DIGEST,
        template_text="# Purpose\n# Controls",
        source_spans=[
            {"span_id": "span-1", "text": "Purpose."},
            {"span_id": "span-2", "text": "Unmapped."},
        ],
    )
    draft = provider.generate_draft(
        source_text="Source.",
        mapping=mapping,
        template_text="# Purpose\n# Controls",
    )
    audit = provider.audit_draft(
        source_text="Source.",
        mapping=mapping,
        draft=draft,
        template_text="# Purpose\n# Controls",
    )

    assert audit.status == "fail"
    assert audit.accepted is False
    assert audit.unresolved_blocking_gaps == ["GAP-001"]
    assert audit.check_map["blocking_gaps_resolved"] is False


def test_provider_returns_controlled_oversized_status_without_calling_gateway() -> None:
    fake = FakeStructuredModel([])
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, max_repairs_override=0),
        model_factory=lambda *_: fake,
    )
    provider = GeminiTransformationProvider(gateway)

    with pytest.raises(ContextBudgetError) as raised:
        provider.map_document(
            source_text="x" * 300_000,
            source_digest=_SOURCE_DIGEST,
            template_text="# Template",
            source_spans=[{"span_id": "span-1", "text": "x"}],
        )

    assert raised.value.preflight.status == "oversized"
    assert raised.value.preflight.truncated is False
    assert fake.calls == []


def test_bundle_visual_extraction_evidence_is_accepted_without_binary_payload() -> None:
    provider = GeminiTransformationProvider(_gateway([_mapping_response(with_gap=False)]))
    evidence = BundleVisualExtraction(
        figure_id="FIG-001",
        source_digest=_FIGURE_DIGEST,
        kind="table",
        status="requires_review",
        structured_content={"headers": ["Owner"], "rows": [["Ops"]]},
        source_span_ids=["span-1"],
    )

    result = provider.map_document(
        source_text="Source.",
        source_digest=_SOURCE_DIGEST,
        template_text="# Purpose\n# Controls",
        source_spans=[
            {"span_id": "span-1", "text": "Purpose."},
            {"span_id": "span-2", "text": "Control."},
        ],
        visual_extractions=[evidence],
    )

    assert result.bundle.visual_extractions[0].figure_id == "FIG-001"
    assert result.bundle.visual_extractions[0].source_digest == _FIGURE_DIGEST
