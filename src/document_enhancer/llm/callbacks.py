"""Usage extraction and callback helpers for auditable model calls."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

try:  # Keep the core/offline authoring path free of LangChain imports.
    _ImportedCallbackBase = importlib.import_module("langchain_core.callbacks").BaseCallbackHandler
except ImportError:  # pragma: no cover - exercised by minimal core installations

    class _ImportedCallbackBase:
        """Minimal callback shape used until the optional live adapter is installed."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args, kwargs


# The optional import is intentionally dynamic.  Keep the class base opaque to the type checker
# while retaining the real LangChain callback base when the live extra is installed.
_CallbackBase: Any = _ImportedCallbackBase


class UsageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)

    @classmethod
    def from_response(cls, response: object) -> UsageMetadata | None:
        candidates: list[Mapping[str, Any]] = []
        if isinstance(response, Mapping):
            for key in ("usage_metadata", "token_usage", "usage"):
                value = response.get(key)
                if isinstance(value, Mapping):
                    candidates.append(cast(Mapping[str, Any], value))
            raw = response.get("raw")
            if raw is not response:
                nested = cls.from_response(raw)
                if nested is not None:
                    return nested
        for attr in ("usage_metadata", "response_metadata"):
            value = getattr(response, attr, None)
            if isinstance(value, Mapping):
                candidates.append(cast(Mapping[str, Any], value))
        for usage in candidates:
            input_tokens = _first_int(usage, "input_tokens", "prompt_token_count", "prompt_tokens")
            output_tokens = _first_int(
                usage, "output_tokens", "candidates_token_count", "completion_tokens"
            )
            total_tokens = _first_int(usage, "total_tokens", "total_token_count")
            cached = _first_int(usage, "cached_input_tokens", "cached_content_token_count")
            if any(
                value is not None for value in (input_tokens, output_tokens, total_tokens, cached)
            ):
                return cls(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cached_input_tokens=cached,
                )
        return None


def _first_int(mapping: Mapping[str, Any], *names: str) -> int | None:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
    return None


class UsageCallbackHandler(_CallbackBase):
    """Collect the last provider usage object without retaining prompts or content."""

    def __init__(self) -> None:
        self.usage: UsageMetadata | None = None

    def on_llm_end(self, response: Any, **_: Any) -> None:
        self.usage = UsageMetadata.from_response(response)
