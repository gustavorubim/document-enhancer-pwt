from __future__ import annotations

import pytest
from pydantic import BaseModel

from document_enhancer.llm import (
    ROUTE_FLASH,
    ROUTE_FLASH_LITE,
    ROUTE_PRO_PREVIEW,
    GeminiSchemaError,
    gemini_schema,
    resolve_route,
)


class Child(BaseModel):
    name: str


class Probe(BaseModel):
    ok: bool
    child: Child | None = None
    score: int = 0


def test_exact_routes_and_stage_routing_are_stable() -> None:
    assert resolve_route(ROUTE_FLASH_LITE).model == ROUTE_FLASH_LITE
    assert resolve_route(ROUTE_FLASH_LITE).token_budget == 40_000
    assert resolve_route("structure_recovery").route_id == ROUTE_FLASH_LITE
    assert resolve_route("analysis").route_id == ROUTE_FLASH
    assert resolve_route("rewrite").route_id == ROUTE_PRO_PREVIEW


def test_pydantic_schema_is_dereferenced_and_nullable() -> None:
    schema = gemini_schema(Probe)
    assert schema["type"] == "object"
    assert schema["properties"]["child"]["nullable"] is True
    assert "$defs" not in str(schema)
    assert "additionalProperties" not in schema


def test_unsupported_schema_keyword_fails_before_provider_call() -> None:
    with pytest.raises(GeminiSchemaError, match="unsupported Gemini schema keyword"):
        gemini_schema(
            {"type": "object", "properties": {"value": {"type": "string", "pattern": "x"}}}
        )
