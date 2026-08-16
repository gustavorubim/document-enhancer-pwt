"""Deterministic whole-context preflight for transformation provider calls.

The transformation providers have to send the complete source and selected template.  This
module makes that boundary explicit: it counts every request component and the expected
structured response before a gateway call.  It deliberately has no truncation helper.  A caller
must either fit the complete request or handle the returned controlled oversized status.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from document_enhancer.llm.caching import canonical_json
from document_enhancer.llm.profiles import resolve_route

ContextStatus = Literal["fit", "oversized", "hierarchical"]
ContextStrategy = Literal["full", "hierarchical"]


class ContextPreflight(BaseModel):
    """Measured request/output context and the deterministic admission decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["core.context-preflight.v1"] = "core.context-preflight.v1"
    status: ContextStatus
    strategy: ContextStrategy
    route_id: str = Field(min_length=1)
    token_budget: int = Field(ge=1)
    input_token_budget: int = Field(ge=1)
    output_token_budget: int = Field(ge=1)
    source_chars: int = Field(ge=0)
    template_chars: int = Field(ge=0)
    visual_evidence_chars: int = Field(ge=0)
    prompt_chars: int = Field(ge=0)
    expected_output_chars: int = Field(ge=0)
    source_tokens: int = Field(ge=0)
    template_tokens: int = Field(ge=0)
    visual_evidence_tokens: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    expected_output_tokens: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    reasons: list[str] = Field(default_factory=list)
    complete_context: bool = True
    truncated: bool = False

    @property
    def fits(self) -> bool:
        """Whether the complete request and expected output fit the selected route."""

        return self.status == "fit"

    @property
    def estimated_input_tokens(self) -> int:
        return self.input_tokens

    @property
    def estimated_output_tokens(self) -> int:
        return self.expected_output_tokens


class ContextBudgetError(ValueError):
    """Raised when a provider cannot admit a complete request under its route budget."""

    def __init__(self, preflight: ContextPreflight) -> None:
        self.preflight = preflight
        detail = ", ".join(preflight.reasons) or "complete context exceeds route budget"
        super().__init__(f"transformation context preflight {preflight.status}: {detail}")


def _json_safe(value: object) -> object:
    """Convert structured evidence to deterministic JSON without retaining binary payloads."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(child) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def serialize_structured_context(value: object) -> str:
    """Serialize non-text context deterministically for prompt construction and accounting."""

    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return canonical_json(_json_safe(value))


def estimate_tokens(text: str) -> int:
    """Use one stable conservative character-to-token estimate for offline preflight."""

    if not text:
        return 0
    # UTF-8 bytes avoid treating a non-ASCII source as cheaper merely because it has fewer Python
    # code points.  The estimate is intentionally deterministic; the gateway remains authoritative
    # when the live provider reports actual usage.
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def preflight_context(
    *,
    source_text: str,
    template_text: str = "",
    visual_evidence: object = "",
    prompt_text: str | None = None,
    prompt: str | None = None,
    expected_output: object | None = None,
    expected_output_text: str | None = None,
    route: str = "analysis",
    allow_hierarchical: bool = False,
    input_token_budget: int | None = None,
    output_token_budget: int | None = None,
) -> ContextPreflight:
    """Admit a complete context or return a controlled oversized/hierarchical result.

    ``source_text``, ``template_text``, and ``visual_evidence`` are measured in full.  The
    function never slices any component.  ``prompt_text`` is the complete instruction and
    structured-catalog portion that the caller will add to those components.  The expected output
    is measured separately against the route's output budget.
    """

    if not isinstance(source_text, str) or not isinstance(template_text, str):
        raise TypeError("source_text and template_text must be strings")
    if prompt_text is not None and prompt is not None and prompt_text != prompt:
        raise ValueError("prompt_text and prompt must agree when both are supplied")
    instruction_text = prompt_text if prompt_text is not None else (prompt or "")
    if not isinstance(instruction_text, str):
        raise TypeError("prompt_text must be a string")
    if expected_output_text is not None and expected_output is not None:
        rendered_expected = serialize_structured_context(expected_output)
        if rendered_expected != expected_output_text:
            raise ValueError("expected_output and expected_output_text must agree")
    else:
        rendered_expected = (
            expected_output_text
            if expected_output_text is not None
            else serialize_structured_context(expected_output)
        )
    rendered_visual = serialize_structured_context(visual_evidence)

    resolved = resolve_route(route)
    route_input_budget = resolved.token_budget - resolved.output_budget
    bounded_input = route_input_budget if input_token_budget is None else input_token_budget
    bounded_output = resolved.output_budget if output_token_budget is None else output_token_budget
    if bounded_input < 1 or bounded_output < 1:
        raise ValueError("input and output token budgets must be positive")

    source_tokens = estimate_tokens(source_text)
    template_tokens = estimate_tokens(template_text)
    visual_tokens = estimate_tokens(rendered_visual)
    prompt_tokens = estimate_tokens(instruction_text)
    expected_tokens = estimate_tokens(rendered_expected)
    input_tokens = source_tokens + template_tokens + visual_tokens + prompt_tokens
    total_tokens = input_tokens + expected_tokens
    reasons: list[str] = []
    if bounded_input + bounded_output > resolved.token_budget:
        reasons.append("configured_input_output_budget_exceeds_route_cap")
    if input_tokens > bounded_input:
        reasons.append("complete_input_exceeds_input_budget")
    if expected_tokens > bounded_output:
        reasons.append("expected_output_exceeds_output_budget")

    input_oversized = input_tokens > bounded_input
    output_oversized = expected_tokens > bounded_output
    hierarchical = bool(allow_hierarchical and input_oversized and not output_oversized)
    status: ContextStatus = "hierarchical" if hierarchical else ("oversized" if reasons else "fit")
    strategy: ContextStrategy = "hierarchical" if hierarchical else "full"
    return ContextPreflight(
        status=status,
        strategy=strategy,
        route_id=resolved.route_id,
        token_budget=resolved.token_budget,
        input_token_budget=bounded_input,
        output_token_budget=bounded_output,
        source_chars=len(source_text),
        template_chars=len(template_text),
        visual_evidence_chars=len(rendered_visual),
        prompt_chars=len(instruction_text),
        expected_output_chars=len(rendered_expected),
        source_tokens=source_tokens,
        template_tokens=template_tokens,
        visual_evidence_tokens=visual_tokens,
        prompt_tokens=prompt_tokens,
        expected_output_tokens=expected_tokens,
        input_tokens=input_tokens,
        total_tokens=total_tokens,
        reasons=reasons,
        complete_context=True,
        truncated=False,
    )


preflight = preflight_context
ContextBudget = ContextPreflight
ContextPreflightResult = ContextPreflight


__all__ = [
    "ContextBudget",
    "ContextBudgetError",
    "ContextPreflight",
    "ContextPreflightResult",
    "ContextStatus",
    "estimate_tokens",
    "preflight",
    "preflight_context",
    "serialize_structured_context",
]
