from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import BaseModel

from document_enhancer.llm import (
    ROUTE_FLASH,
    ROUTE_FLASH_LITE,
    ROUTE_PRO_PREVIEW,
    FakeStructuredModel,
    GeminiGatewayConfig,
    GeminiModelGateway,
    RecordedStructuredModel,
)


class Probe(BaseModel):
    ok: bool
    route: str


@pytest.mark.integration
def test_all_requested_routes_run_concurrently_against_deterministic_fakes(tmp_path) -> None:
    routes = [ROUTE_FLASH_LITE, ROUTE_FLASH, ROUTE_PRO_PREVIEW]

    def call(route: str) -> str:
        fake = FakeStructuredModel([{"ok": True, "route": route}])
        gateway = GeminiModelGateway(
            GeminiGatewayConfig(max_retries_override=0, retry_backoff_seconds=0),
            model_factory=lambda *_: fake,
        )
        result = gateway.invoke(route=route, schema=Probe, prompt=f"offline {route}")
        assert result.manifest.requested_route_id == route
        return result.artifact.route

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sorted(pool.map(call, routes)) == sorted(routes)

    recorder_path = tmp_path / "recorded.json"
    recorder = RecordedStructuredModel(recorder_path, [{"ok": True, "route": "recorded"}])
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, retry_backoff_seconds=0),
        model_factory=lambda *_: recorder,
    )
    gateway.invoke(route=ROUTE_FLASH_LITE, schema=Probe, prompt="record this")
    replay = RecordedStructuredModel(recorder_path)
    replay_gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, retry_backoff_seconds=0),
        model_factory=lambda *_: replay,
    )
    assert (
        replay_gateway.invoke(
            route=ROUTE_FLASH_LITE, schema=Probe, prompt="record this"
        ).artifact.route
        == "recorded"
    )
