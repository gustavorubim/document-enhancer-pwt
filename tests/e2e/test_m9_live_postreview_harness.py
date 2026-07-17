from __future__ import annotations

from pathlib import Path

import pytest
from scripts.run_live_postreview_smoke import (
    RecordingGateway,
    TimedEmbeddingAdapter,
    _analysis_with_one_owner_question,
    _services,
    validate_model_call_shape,
)

from document_enhancer.llm import (
    EmbeddingProfile,
    GeminiEmbeddingAdapter,
    GeminiGatewayConfig,
    GeminiModelGateway,
)
from document_enhancer.rag import OfflineDeterministicEmbedder
from document_enhancer.workflow import DocumentWorkflow


def test_live_harness_reaches_gate1_without_credentials_or_provider_calls(tmp_path: Path) -> None:
    root = tmp_path / "smoke"
    root.mkdir()
    source = root / "source.md"
    source.write_text(
        "# Monthly review\n\nThe approved owner is intentionally unspecified.\n",
        encoding="utf-8",
    )
    gateway = RecordingGateway(
        GeminiModelGateway(GeminiGatewayConfig(api_key="fictional-test-key"))
    )
    embedding = TimedEmbeddingAdapter(
        GeminiEmbeddingAdapter(
            profile=EmbeddingProfile(),
            embedder=OfflineDeterministicEmbedder(768),
        )
    )
    services = _services(root, source, gateway, embedding)
    result = DocumentWorkflow(services).run()
    assert result.status == "waiting"
    assert result.current_stage == "gate1"


def test_fixture_finding_targets_the_single_smoke_section() -> None:
    request = type("Request", (), {"document_id": "DOC-M9", "source_digest": "a" * 64})()
    result = _analysis_with_one_owner_question(request)
    assert result.blocking_count == 1
    assert result.findings[0].target_template_section == "SEC-PROCESS-CONTENT"


def test_live_call_shape_is_exact_and_bounded() -> None:
    calls: list[dict[str, object]] = [
        {
            "stage": "rewrite_checklist",
            "requested_route": "gemini-3.1-flash-lite",
            "effective_route": "gemini-3.1-flash-lite",
        },
        {
            "stage": "section_rewrite",
            "requested_route": "gemini-3.1-pro-preview",
            "effective_route": "gemini-3.1-pro-preview",
        },
        {
            "stage": "independent_content_fidelity_audit",
            "requested_route": "gemini-3.5-flash",
            "effective_route": "gemini-3.5-flash",
        },
    ]
    validate_model_call_shape(calls)
    with pytest.raises(RuntimeError, match="section_rewrite used 2 calls"):
        validate_model_call_shape([*calls, calls[1]])


def test_test_only_gateway_configuration_does_not_require_real_credentials() -> None:
    gateway = GeminiModelGateway(GeminiGatewayConfig(api_key="fictional-test-key"))
    assert gateway.config.public_dict()["api_key_configured"] is True
