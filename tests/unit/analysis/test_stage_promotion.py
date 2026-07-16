from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from document_enhancer.analysis.macro import MacroReviewer
from document_enhancer.analysis.models import AnalysisRequest
from document_enhancer.analysis.orchestrator import AnalysisOrchestrator
from document_enhancer.domain.analysis import AnalysisReport
from document_enhancer.llm.caching import ResponseCache
from document_enhancer.llm.models import CallStatus, GeminiModelGateway
from document_enhancer.prompting import PromptPackComposer

GatewayFactory = Callable[[Mapping[str, list[object]]], tuple[GeminiModelGateway, Any]]


def _duplicate_provider_identity(responses: dict[str, list[object]]) -> dict[str, list[object]]:
    duplicated = copy.deepcopy(responses)
    for stage in (
        "macro_reviewer",
        "section_mapper",
        "rag_readiness_reviewer",
        "finding_synthesizer",
    ):
        report = cast(dict[str, Any], duplicated[stage][0])
        report.update(
            document_id="DOC-FOREIGN-PROVIDER",
            source_digest="b" * 64,
            generated_at="2000-01-01T00:00:00Z",
        )
        analyses = cast(list[dict[str, Any]], report["analyses"])
        for analysis in analyses:
            analysis.update(
                analysis_id="ANA-DUPLICATE-PROVIDER-01",
                document_id="DOC-FOREIGN-PROVIDER",
                source_digest="b" * 64,
                created_at="2000-01-01T00:00:00Z",
                model_route="provider-owned-route",
                prompt_id="provider-owned-prompt",
                version_id="DOCV-PROVIDER-01",
            )
            findings = cast(list[dict[str, Any]], analysis.get("findings", []))
            for finding in findings:
                finding["finding_id"] = "FND-DUPLICATE-PROVIDER-01"
    return duplicated


def test_duplicate_provider_ids_are_ignored_and_synthesis_references_canonical_ids(
    composer: PromptPackComposer,
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
    gateway_factory: GatewayFactory,
) -> None:
    duplicated = _duplicate_provider_identity(responses)
    first_gateway, _ = gateway_factory(duplicated)
    second_gateway, _ = gateway_factory(_duplicate_provider_identity(responses))

    first = AnalysisOrchestrator(composer, first_gateway).run(analysis_request)
    second = AnalysisOrchestrator(composer, second_gateway).run(analysis_request)

    branch_ids = [branch.analysis.analysis_id for branch in first.branches]
    synthesis_ids = [analysis.analysis_id for analysis in first.synthesis.model_report.analyses]
    all_analysis_ids = [*branch_ids, *synthesis_ids]
    assert len(all_analysis_ids) == len(set(all_analysis_ids)) == 5
    assert all(identifier != "ANA-DUPLICATE-PROVIDER-01" for identifier in all_analysis_ids)
    assert [branch.analysis.model_dump(mode="json") for branch in first.branches] == [
        branch.analysis.model_dump(mode="json") for branch in second.branches
    ]
    assert first.synthesis.model_report.model_dump(mode="json") == (
        second.synthesis.model_report.model_dump(mode="json")
    )

    strict_combined = AnalysisReport(
        document_id=analysis_request.document_id,
        source_digest=analysis_request.source_digest,
        analyses=[
            *(branch.analysis for branch in first.branches),
            *first.synthesis.model_report.analyses,
        ],
        generated_at=analysis_request.requested_at,
    )
    assert AnalysisReport.model_validate_json(strict_combined.model_dump_json()) == strict_combined
    assert strict_combined.generated_at == analysis_request.requested_at
    for analysis in strict_combined.analyses:
        assert analysis.document_id == analysis_request.document_id
        assert analysis.source_digest == analysis_request.source_digest
        assert analysis.created_at == analysis_request.requested_at
        assert analysis.model_route == "gemini-3.5-flash"
        assert analysis.prompt_id != "provider-owned-prompt"

    provider_finding_ids = {
        finding.finding_id for analysis in strict_combined.analyses for finding in analysis.findings
    }
    assert "FND-DUPLICATE-PROVIDER-01" not in provider_finding_ids
    assert len(provider_finding_ids) == sum(
        len(analysis.findings) for analysis in strict_combined.analyses
    )

    expected_sources = [*branch_ids, *synthesis_ids]
    assert first.synthesis.finding_set.generated_from_analysis_ids == expected_sources
    assert all(
        source_id in expected_sources
        for conflict in first.synthesis.conflicts
        for source_id in conflict.source_analysis_ids
    )
    macro_evidence = first.branches[0].analysis.findings[0].evidence[0]
    assert macro_evidence.quote == (
        "The Forecast Analyst runs the monthly forecast using CALC-LOSS-001."
    )
    assert macro_evidence.span_id == analysis_request.authoritative_span_ids[1]


def test_promoted_stage_report_is_the_only_cached_artifact_and_manifest_contract(
    tmp_path: Path,
    composer: PromptPackComposer,
    analysis_request: AnalysisRequest,
    responses: dict[str, list[object]],
    gateway_factory: GatewayFactory,
) -> None:
    duplicated = _duplicate_provider_identity(responses)
    gateway, model = gateway_factory({"macro_reviewer": duplicated["macro_reviewer"]})
    gateway._cache = ResponseCache(tmp_path / "cache")  # noqa: SLF001

    first = MacroReviewer(composer, gateway).review(analysis_request)
    second = MacroReviewer(composer, gateway).review(analysis_request)

    assert len(model.calls) == 1
    assert first.analysis == second.analysis
    assert first.call.manifest.status == CallStatus.SUCCESS
    assert second.call.manifest.status == CallStatus.CACHE_HIT
    assert first.call.manifest.schema_name == "GeminiMacroAnalysisReport"
    assert first.call.manifest.result_schema_name == "AnalysisReport"
    assert first.call.manifest.result_schema_digest == second.call.manifest.result_schema_digest
    assert first.call.manifest.cache_key == second.call.manifest.cache_key
    cache_text = next((tmp_path / "cache").glob("*.json")).read_text(encoding="utf-8")
    assert "ANA-DUPLICATE-PROVIDER-01" not in cache_text
    assert "FND-DUPLICATE-PROVIDER-01" not in cache_text
    assert first.analysis.analysis_id in cache_text
