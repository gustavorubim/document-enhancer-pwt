#!/usr/bin/env python3
"""Opt-in live route evidence; reads credentials only from the process environment."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from pydantic import BaseModel

from document_enhancer.errors import ConfigurationError, ProviderError
from document_enhancer.llm import (
    EMBEDDING_MODEL,
    ROUTE_FLASH,
    ROUTE_FLASH_LITE,
    ROUTE_PRO_PREVIEW,
    EmbeddingDocument,
    EmbeddingProfile,
    GeminiEmbeddingAdapter,
    GeminiGatewayConfig,
    GeminiModelGateway,
    ModelLifecycleError,
)


class LiveEvaluationProbe(BaseModel):
    ok: bool
    route: str


def _status(exc: BaseException) -> str:
    if isinstance(exc, ConfigurationError):
        return "unavailable"
    if isinstance(exc, ModelLifecycleError):
        return "retired"
    if isinstance(exc, ProviderError):
        return "failed"
    return "failed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evals/reports/m8-live.json"))
    args = parser.parse_args()
    if os.getenv("DOCENHANCE_RUN_LIVE") != "1":
        parser.error("live checks are opt-in: set DOCENHANCE_RUN_LIVE=1")

    config = GeminiGatewayConfig.from_env()
    report: dict[str, object] = {
        "schema_version": "1.0",
        "evidence_kind": "live_model",
        "backend": config.backend.value,
        "credentials_present": bool(config.api_key or config.project),
        "routes": {},
    }
    gateway = GeminiModelGateway(config)
    routes = report["routes"]
    assert isinstance(routes, dict)
    for route in (ROUTE_FLASH_LITE, ROUTE_FLASH, ROUTE_PRO_PREVIEW):
        try:
            result = gateway.invoke(
                route=route,
                schema=LiveEvaluationProbe,
                prompt=f"Return ok=true and route='{route}'. This is a fictional M8 lifecycle probe.",
                prompt_id="m8-live-evaluation",
                prompt_version="1",
                use_cache=False,
            )
        except BaseException as exc:
            routes[route] = {"status": _status(exc), "error_type": type(exc).__name__}
        else:
            manifest = result.manifest
            routes[route] = {
                "status": "passed",
                "requested_route": manifest.requested_route_id,
                "effective_route": manifest.effective_route_id,
                "duration_ms": manifest.duration_ms,
                "attempts": manifest.attempts,
                "retries": manifest.retries,
                "fallback_from": manifest.fallback_from,
                "usage": manifest.usage.model_dump(mode="json") if manifest.usage else None,
                "cost_budget_usd": manifest.cost_budget_usd,
            }
    try:
        embedding = GeminiEmbeddingAdapter(profile=EmbeddingProfile(backend=config.backend.value))
        vector = embedding.embed_document_chunks(
            [EmbeddingDocument("M8 fixture", "lifecycle", "fictional embedding probe")]
        )[0]
    except BaseException as exc:
        routes[EMBEDDING_MODEL] = {"status": _status(exc), "error_type": type(exc).__name__}
    else:
        routes[EMBEDDING_MODEL] = {
            "status": "passed",
            "dimensions": len(vector),
            "manifest": asdict(embedding.last_manifest) if embedding.last_manifest else None,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "routes": sorted(routes)}, sort_keys=True))
    return 0 if all(item.get("status") == "passed" for item in routes.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
