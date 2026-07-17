"""Versioned Gemini routes and explicit per-stage generation budgets.

The route IDs in this module are part of the run/cache contract.  They are
deliberately not ``latest`` aliases: model lifecycle changes must be visible
to a caller and to a run manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ROUTE_FLASH_LITE: Final = "gemini-3.1-flash-lite"
ROUTE_FLASH: Final = "gemini-3.5-flash"
ROUTE_PRO_PREVIEW: Final = "gemini-3.1-pro-preview"


@dataclass(frozen=True, slots=True)
class GeminiRoute:
    """A complete, auditable generation profile for one stage family."""

    route_id: str
    stage: str
    model: str
    temperature: float
    top_p: float
    top_k: int
    max_output_tokens: int
    timeout_seconds: float
    provider_retries: int
    structured_repairs: int
    token_budget: int
    output_budget: int
    cost_budget_usd: float | None
    thinking_level: str | None = None
    seed: int = 7
    allow_fallback: bool = False

    def parameters(self) -> dict[str, object]:
        """Return only public request parameters for manifests and cache keys."""

        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
            "provider_retries": self.provider_retries,
            "structured_repairs": self.structured_repairs,
            "token_budget": self.token_budget,
            "output_budget": self.output_budget,
            "cost_budget_usd": self.cost_budget_usd,
            "thinking_level": self.thinking_level,
            "seed": self.seed,
            "tools": [],
        }


_FLASH_LITE: dict[str, Any] = dict(
    model=ROUTE_FLASH_LITE,
    temperature=0.0,
    top_p=0.95,
    top_k=40,
    max_output_tokens=8000,
    timeout_seconds=45.0,
    provider_retries=2,
    structured_repairs=2,
    token_budget=40000,
    output_budget=8000,
    cost_budget_usd=0.20,
    thinking_level="minimal",
)
_FLASH: dict[str, Any] = dict(
    model=ROUTE_FLASH,
    temperature=0.0,
    top_p=0.95,
    top_k=40,
    max_output_tokens=14000,
    timeout_seconds=90.0,
    provider_retries=2,
    structured_repairs=2,
    token_budget=56000,
    output_budget=14000,
    cost_budget_usd=1.00,
    thinking_level="low",
)
_PRO: dict[str, Any] = dict(
    model=ROUTE_PRO_PREVIEW,
    temperature=0.0,
    top_p=0.95,
    top_k=40,
    max_output_tokens=14000,
    timeout_seconds=150.0,
    provider_retries=1,
    structured_repairs=2,
    token_budget=42000,
    output_budget=14000,
    cost_budget_usd=3.00,
    thinking_level="medium",
)


ROUTES: Final[dict[str, GeminiRoute]] = {
    ROUTE_FLASH_LITE: GeminiRoute(
        route_id=ROUTE_FLASH_LITE,
        stage="clerical",
        **_FLASH_LITE,
    ),
    ROUTE_FLASH: GeminiRoute(route_id=ROUTE_FLASH, stage="analysis", **_FLASH),
    ROUTE_PRO_PREVIEW: GeminiRoute(
        route_id=ROUTE_PRO_PREVIEW,
        stage="reconciliation",
        **_PRO,
    ),
}

STAGE_ROUTES: Final[dict[str, str]] = {
    "structure": ROUTE_FLASH_LITE,
    "structure_scan": ROUTE_FLASH_LITE,
    "structure_recovery": ROUTE_FLASH_LITE,
    "terminology": ROUTE_FLASH_LITE,
    "questions": ROUTE_FLASH_LITE,
    "analysis": ROUTE_FLASH,
    "macro": ROUTE_FLASH,
    "sections": ROUTE_FLASH,
    "discovery": ROUTE_FLASH,
    "audit": ROUTE_FLASH,
    "rewrite": ROUTE_PRO_PREVIEW,
    "reconciliation": ROUTE_PRO_PREVIEW,
}


def resolve_route(route_or_stage: str) -> GeminiRoute:
    """Resolve either an exact route ID or a documented stage name."""

    route_id = STAGE_ROUTES.get(route_or_stage, route_or_stage)
    try:
        return ROUTES[route_id]
    except KeyError as exc:
        supported = ", ".join(sorted(ROUTES))
        raise ValueError(
            f"Unknown Gemini route or stage {route_or_stage!r}; use: {supported}"
        ) from exc
