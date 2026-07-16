from __future__ import annotations

import asyncio
import time

import pytest
from pydantic import BaseModel

from document_enhancer.llm import ROUTE_FLASH_LITE, GeminiGatewayConfig, GeminiModelGateway


class Probe(BaseModel):
    ok: bool


class SlowModel:
    def with_structured_output(self, *_: object, **__: object) -> object:
        class Runnable:
            def invoke(self, *_: object, **__: object) -> object:
                time.sleep(0.25)
                return {"parsed": {"ok": True}}

        return Runnable()


def test_async_gateway_timeout_cancels_inflight_call() -> None:
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, retry_backoff_seconds=0),
        model_factory=lambda *_: SlowModel(),
    )

    async def exercise() -> None:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                gateway.ainvoke(route=ROUTE_FLASH_LITE, schema=Probe, prompt="slow"),
                timeout=0.02,
            )

    asyncio.run(exercise())
