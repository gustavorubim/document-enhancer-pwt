from __future__ import annotations

import base64
import hashlib

import pytest
from pydantic import ValidationError

from document_enhancer.llm import (
    FakeMultimodalModel,
    FakeStructuredModel,
    GeminiGatewayConfig,
    GeminiModelGateway,
    GeminiMultimodalProvider,
    MultimodalRequest,
    VisualModelResponse,
)

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _response(*, figure_id: str = "FIG-001", digest: str | None = None) -> dict[str, object]:
    return {
        "figure_id": figure_id,
        "source_digest": digest or hashlib.sha256(PNG_1X1).hexdigest(),
        "source_span_ids": ["span-figure-1"],
        "kind": "table",
        "status": "best_effort",
        "confidence": 0.93,
        "cells": [["Step", "Owner"], ["Submit", "Analyst"]],
    }


@pytest.mark.unit
def test_visual_response_aliases_and_rectangular_cells_are_strict() -> None:
    result = VisualModelResponse.model_validate(_response())

    assert result.source_sha256 == hashlib.sha256(PNG_1X1).hexdigest()
    assert result.cells == [["Step", "Owner"], ["Submit", "Analyst"]]
    assert result.model_dump(mode="json")["source_sha256"] == result.source_sha256

    with pytest.raises(ValidationError, match="rectangular"):
        VisualModelResponse.model_validate(
            {**_response(), "cells": [["Step", "Owner"], ["Submit"]]}
        )


@pytest.mark.unit
def test_fake_multimodal_model_validates_output_and_records_only_digests() -> None:
    request = MultimodalRequest(
        figure_id="FIG-001",
        source_sha256=hashlib.sha256(PNG_1X1).hexdigest(),
        media_type="image/png",
        image_bytes=PNG_1X1,
        source_span_ids=("span-figure-1",),
        context="The figure belongs to the submission section.",
    )
    fake = FakeMultimodalModel([_response()])

    result = fake.classify(request)

    assert result.kind == "table"
    assert result.source_span_ids == ["span-figure-1"]
    assert fake.calls[0]["image_digest"] == request.image_digest
    assert "image_bytes" not in fake.calls[0]
    assert "submission section" not in str(fake.calls[0])


@pytest.mark.unit
def test_gemini_multimodal_provider_uses_existing_gateway_and_image_digest_dependency() -> None:
    fake_model = FakeStructuredModel([_response()])
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, max_repairs_override=0),
        model_factory=lambda *_: fake_model,
    )
    provider = GeminiMultimodalProvider(gateway)
    request = MultimodalRequest(
        figure_id="FIG-001",
        source_sha256=hashlib.sha256(PNG_1X1).hexdigest(),
        media_type="image/png",
        image_bytes=PNG_1X1,
        source_span_ids=("span-figure-1",),
    )

    result = provider.classify(request)

    assert result.cells == [["Step", "Owner"], ["Submit", "Analyst"]]
    assert gateway.last_manifest is not None
    assert request.image_digest in gateway.last_manifest.input_digests
    assert fake_model.calls
    assert fake_model.calls[0]["prompt_digest"] != gateway.last_manifest.prompt_digest


@pytest.mark.unit
def test_multimodal_gateway_rejects_unsupported_or_oversized_payloads() -> None:
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, max_repairs_override=0),
        model_factory=lambda *_: FakeStructuredModel([]),
    )
    with pytest.raises(ValueError, match="image/png or image/jpeg"):
        gateway.invoke_multimodal(
            route="visual",
            schema=VisualModelResponse,
            prompt="classify",
            image_bytes=PNG_1X1,
            media_type="image/gif",
        )
    with pytest.raises(ValueError, match="4000000"):
        gateway.invoke_multimodal(
            route="visual",
            schema=VisualModelResponse,
            prompt="classify",
            image_bytes=b"x" * 4_000_001,
            media_type="image/png",
        )
