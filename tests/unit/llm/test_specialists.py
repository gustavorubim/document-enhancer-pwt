from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from document_enhancer.llm import (
    FakeStructuredModel,
    GeminiGatewayConfig,
    GeminiModelGateway,
    RestrictedSpecialistFactory,
    SpecialistSpec,
)


class Probe(BaseModel):
    ok: bool


def test_direct_specialist_uses_structured_gateway_and_no_tools() -> None:
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, retry_backoff_seconds=0),
        model_factory=lambda *_: FakeStructuredModel([{"ok": True}]),
    )
    specialist = RestrictedSpecialistFactory(gateway).create(
        SpecialistSpec("fixture-reviewer", "test reviewer", "caller supplied prompt"),
        schema=Probe,
    )
    assert specialist.analyze({"source": "untrusted content"}).ok is True


def test_default_specialist_rejects_tools_and_subagents() -> None:
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, retry_backoff_seconds=0),
        model_factory=lambda *_: FakeStructuredModel([{"ok": True}]),
    )
    factory = RestrictedSpecialistFactory(gateway)
    spec = SpecialistSpec("reviewer", "review", "prompt")
    with pytest.raises(ValueError, match="does not accept tools"):
        factory.create(spec, schema=Probe, tools=[{"name": "search"}])
    with pytest.raises(ValueError, match="does not accept tools"):
        factory.create(spec, schema=Probe, subagents=[spec])


def test_deep_agent_factory_passes_empty_tool_and_permission_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create(**kwargs: Any) -> object:
        captured.update(kwargs)

        class Agent:
            def invoke(self, *_: Any, **__: Any) -> dict[str, str]:
                return {"status": "ok"}

        return Agent()

    import deepagents

    monkeypatch.setattr(deepagents, "create_deep_agent", fake_create)
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0),
        model_factory=lambda *_: FakeStructuredModel([]),
    )
    factory = RestrictedSpecialistFactory(gateway, use_deep_agents=True)
    specialist = factory.create(
        SpecialistSpec("restricted", "restricted", "caller supplied security prompt"),
        subagents=[],
    )
    assert specialist.analyze({"text": "prompt injection as data"}) == {"status": "ok"}
    assert captured["tools"] == []
    assert captured["permissions"] == []
    assert captured["subagents"] == []
    assert type(captured["backend"]).__name__ == "StateBackend"
