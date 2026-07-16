from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from document_enhancer.analysis.discovery import (
    ProcessMethodologyDiscoverer,
    validate_candidate_graph,
)
from document_enhancer.analysis.errors import (
    CandidateGraphError,
    EvidenceResolutionError,
    SourceSpanCoverageError,
)
from document_enhancer.analysis.macro import MacroReviewer
from document_enhancer.analysis.models import AnalysisRequest, SpanDisposition
from document_enhancer.analysis.promotion import promote_discovery_candidate_batch
from document_enhancer.analysis.provider_models import DiscoveryCandidateBatch
from document_enhancer.analysis.rag_readiness import (
    RagReadinessReviewer,
    augment_rag_readiness,
    deterministic_rag_lint,
)
from document_enhancer.analysis.rendering import render_rag_readiness_markdown
from document_enhancer.analysis.sections import SectionMapper, build_disposition_map
from document_enhancer.domain.analysis import (
    AnalysisReport,
    DiscoveryAnalysis,
    MacroAnalysis,
    RagReadinessAnalysis,
    SectionAnalysis,
)
from document_enhancer.domain.source import NormalizedDocument, StructuralSection, StructuralView
from document_enhancer.llm.models import GeminiModelGateway
from document_enhancer.llm.profiles import ROUTE_FLASH
from document_enhancer.prompting import PromptPackComposer

GatewayFactory = Callable[[Mapping[str, list[object]]], tuple[GeminiModelGateway, Any]]


def _snapshot(name: str) -> str:
    return (Path(__file__).parent / "snapshots" / name).read_text(encoding="utf-8")


def _analysis(response: object, expected: type[Any]) -> Any:
    report = AnalysisReport.model_validate(response)
    assert len(report.analyses) == 1
    assert isinstance(report.analyses[0], expected)
    return report.analyses[0]


def _discovery(response: object, request: AnalysisRequest) -> DiscoveryAnalysis:
    return promote_discovery_candidate_batch(
        request,
        DiscoveryCandidateBatch.model_validate(response),
    )


def test_macro_reviewer_records_exact_route_round_trips_and_matches_markdown_snapshot(
    composer: PromptPackComposer,
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
    gateway_factory: GatewayFactory,
) -> None:
    gateway, model = gateway_factory({"macro_reviewer": responses["macro_reviewer"]})

    result = MacroReviewer(composer, gateway).review(analysis_request)

    assert isinstance(result.analysis, MacroAnalysis)
    assert result.call.manifest.requested_route_id == ROUTE_FLASH
    assert result.call.manifest.effective_route_id == ROUTE_FLASH
    assert result.call.manifest.model == ROUTE_FLASH
    assert result.call.manifest.prompt_id == "analysis.macro"
    assert result.call.manifest.prompt_digest == result.call.resolution.rendered_prompt_digest
    assert MacroAnalysis.model_validate_json(result.analysis.model_dump_json()) == result.analysis
    assert result.markdown == _snapshot("macro.md")
    assert model.calls[0]["route"] == ROUTE_FLASH


def test_section_mapper_covers_non_substantive_span_and_matches_snapshot(
    composer: PromptPackComposer,
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
    gateway_factory: GatewayFactory,
) -> None:
    gateway, _ = gateway_factory({"section_mapper": responses["section_mapper"]})

    result, disposition_map = SectionMapper(composer, gateway).review(analysis_request)

    assert isinstance(result.analysis, SectionAnalysis)
    assert disposition_map.authoritative_span_ids == analysis_request.authoritative_span_ids
    assert len(disposition_map.dispositions) == len(analysis_request.document.raw.blocks)
    assert analysis_request.document.raw.blocks[-1].substantive is False
    assert disposition_map.dispositions[-1].span_id == analysis_request.authoritative_span_ids[-1]
    assert disposition_map.dispositions[-1].disposition is SpanDisposition.OMITTED
    assert result.markdown == _snapshot("sections.md")


@pytest.mark.parametrize("defect", ["missing", "duplicate", "unknown", "reordered"])
def test_section_disposition_map_fails_closed_on_coverage_defects(
    defect: str,
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
) -> None:
    section = _analysis(responses["section_mapper"][0], SectionAnalysis)
    values = section.model_dump(mode="python")
    mappings = list(values["mappings"])
    if defect == "missing":
        mappings.pop()
    elif defect == "duplicate":
        mappings[1] = {**mappings[1], "source_span_ids": mappings[0]["source_span_ids"]}
    elif defect == "unknown":
        mappings[0] = {**mappings[0], "source_span_ids": ["SPAN-UNKNOWN00000001"]}
    else:
        mappings[0], mappings[1] = mappings[1], mappings[0]
    invalid = SectionAnalysis.model_validate({**values, "mappings": mappings})

    with pytest.raises(SourceSpanCoverageError):
        build_disposition_map(analysis_request, invalid)


def test_section_disposition_map_preserves_multiple_split_targets(
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
) -> None:
    section = _analysis(responses["section_mapper"][0], SectionAnalysis)
    values = section.model_dump(mode="python")
    mappings = list(values["mappings"])
    mappings[0] = {
        **mappings[0],
        "disposition": "split",
        "target_section_ids": ["SEC-GOVERNANCE", "SEC-OVERVIEW"],
    }
    split = SectionAnalysis.model_validate({**values, "mappings": mappings})

    disposition_map = build_disposition_map(analysis_request, split)

    assert disposition_map.dispositions[0].target_section_ids == (
        "SEC-GOVERNANCE",
        "SEC-OVERVIEW",
    )


@pytest.mark.parametrize(
    ("disposition", "targets"),
    [
        ("preserved", []),
        ("moved", ["SEC-ONE", "SEC-TWO"]),
        ("split", ["SEC-ONE"]),
        ("omitted", ["SEC-ONE"]),
    ],
)
def test_section_disposition_map_rejects_invalid_target_cardinality(
    disposition: str,
    targets: list[str],
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
) -> None:
    section = _analysis(responses["section_mapper"][0], SectionAnalysis)
    values = section.model_dump(mode="python")
    mappings = list(values["mappings"])
    mappings[0] = {
        **mappings[0],
        "disposition": disposition,
        "target_section_ids": targets,
    }
    invalid = SectionAnalysis.model_validate({**values, "mappings": mappings})

    with pytest.raises(SourceSpanCoverageError):
        build_disposition_map(analysis_request, invalid)


def test_discovery_returns_typed_candidates_and_rejects_mermaid_semantics(
    composer: PromptPackComposer,
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
    gateway_factory: GatewayFactory,
) -> None:
    gateway, _ = gateway_factory(
        {"process_methodology_discoverer": responses["process_methodology_discoverer"]}
    )
    result = ProcessMethodologyDiscoverer(composer, gateway).review(analysis_request)

    assert isinstance(result.analysis, DiscoveryAnalysis)
    assert {item.entity_type.value for item in result.analysis.objects} >= {
        "ProcessStep",
        "Role",
        "Calculator",
        "Control",
        "Evidence",
        "Risk",
    }
    assert {item.predicate.value for item in result.analysis.candidate_relationships} >= {
        "PERFORMED_BY",
        "USES_CALCULATOR",
        "EXECUTES_CONTROL",
        "PRODUCES_EVIDENCE",
        "MITIGATES",
    }
    assert result.markdown == _snapshot("discovery.md")
    invalid = result.analysis.model_copy(update={"mermaid": "flowchart LR\nA-->B"})
    with pytest.raises(CandidateGraphError, match="Mermaid"):
        validate_candidate_graph(analysis_request, invalid)


def test_discovery_rejects_unresolvable_candidate_provenance(
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
) -> None:
    discovery = _discovery(responses["process_methodology_discoverer"][0], analysis_request)
    objects = list(discovery.objects)
    bad_provenance = objects[0].provenance.model_copy(
        update={"source_span_id": "SPAN-UNKNOWN00000001"}
    )
    objects[0] = objects[0].model_copy(update={"provenance": bad_provenance})
    invalid = discovery.model_copy(update={"objects": objects})

    with pytest.raises(CandidateGraphError, match="source-span provenance"):
        validate_candidate_graph(analysis_request, invalid)


def test_rag_reviewer_and_lint_are_deterministic_and_complete(
    composer: PromptPackComposer,
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
    gateway_factory: GatewayFactory,
) -> None:
    discovery = _discovery(responses["process_methodology_discoverer"][0], analysis_request)
    validate_candidate_graph(analysis_request, discovery)
    gateway, _ = gateway_factory({"rag_readiness_reviewer": responses["rag_readiness_reviewer"]})
    branch = RagReadinessReviewer(composer, gateway).review(analysis_request)
    assert isinstance(branch.analysis, RagReadinessAnalysis)
    lint_one = deterministic_rag_lint(analysis_request, discovery)
    lint_two = deterministic_rag_lint(analysis_request, discovery)

    assert lint_one.model_dump(mode="json") == lint_two.model_dump(mode="json")
    assert set(lint_one.check_ids) == {
        "RAG-HEADINGS",
        "RAG-STABLE-IDS",
        "RAG-SEMANTIC-OBJECT-IDS",
        "RAG-OBJECT-COMPLETENESS",
        "RAG-CODE-OBSERVABLE-DIAGRAMS",
        "RAG-CHUNKABILITY",
        "RAG-PROVENANCE",
        "RAG-TABLE-STRUCTURE",
        "RAG-UNRESOLVED-ITEMS",
        "RAG-RETRIEVAL-AMBIGUITY",
    }
    assert {finding.category for finding in lint_one.findings} >= {
        "semantic_object_completeness",
        "diagram_graphability",
        "table_structure",
        "unresolved_items",
        "retrieval_ambiguity",
    }
    augmented, lint = augment_rag_readiness(
        analysis_request,
        branch.analysis,
        discovery,
    )
    assert len(augmented.findings) == len(branch.analysis.findings) + len(lint.findings)
    assert "STEP-FORECAST-010" in augmented.candidate_objects
    assert render_rag_readiness_markdown(augmented) == _snapshot("rag-readiness.md")


def test_rag_lint_flags_provisional_root_section(
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
) -> None:
    original = analysis_request.document.structural_view.sections[0]
    provisional = StructuralSection.model_validate(
        {**original.model_dump(mode="python"), "section_id": "PROV-SEC-SOURCE-001"}
    )
    view = StructuralView.model_validate(
        {
            **analysis_request.document.structural_view.model_dump(mode="python"),
            "sections": [provisional],
        }
    )
    document = NormalizedDocument.model_validate(
        {**analysis_request.document.model_dump(mode="python"), "structural_view": view}
    )
    request = AnalysisRequest.model_validate(
        {**analysis_request.model_dump(mode="python"), "document": document}
    )
    discovery = _discovery(responses["process_methodology_discoverer"][0], analysis_request)

    lint = deterministic_rag_lint(request, discovery)

    matches = [
        finding
        for finding in lint.findings
        if finding.category == "stable_ids" and finding.target_object_id == "PROV-SEC-SOURCE-001"
    ]
    assert len(matches) == 1


def test_macro_rejects_unresolvable_exact_evidence(
    composer: PromptPackComposer,
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
    gateway_factory: GatewayFactory,
) -> None:
    invalid: Any = copy.deepcopy(responses["macro_reviewer"][0])
    invalid["analyses"][0]["findings"][0]["evidence"][0]["quote"] = "not in source"
    gateway, _ = gateway_factory({"macro_reviewer": [invalid]})

    with pytest.raises(EvidenceResolutionError, match="does not occur"):
        MacroReviewer(composer, gateway).review(analysis_request)
