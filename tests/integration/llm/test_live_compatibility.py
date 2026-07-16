from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import BaseModel

from document_enhancer.compatibility import load_external_env
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


class LiveProbe(BaseModel):
    ok: bool
    route: str


def _status_for(exc: BaseException) -> str:
    if isinstance(exc, (ConfigurationError,)):
        return "unavailable"
    if isinstance(exc, ModelLifecycleError):
        return "retired"
    if isinstance(exc, ProviderError):
        return "failed"
    return "failed"


@pytest.mark.live_model
def test_opt_in_live_gemini_routes_and_embedding_are_recorded(tmp_path: Path) -> None:
    if os.getenv("DOCENHANCE_RUN_LIVE") != "1":
        return
    load_external_env(Path("/Users/gvrubim/Documents/document-enhancer/.env"))
    gateway = GeminiModelGateway(GeminiGatewayConfig.from_env())
    report: dict[str, dict[str, str]] = {}
    for route in (ROUTE_FLASH_LITE, ROUTE_FLASH, ROUTE_PRO_PREVIEW):
        try:
            result = gateway.invoke(
                route=route,
                schema=LiveProbe,
                prompt="Return a minimal compatibility probe object.",
                prompt_id="live-compatibility-probe",
                prompt_version="1",
                use_cache=False,
            )
        except BaseException as exc:
            report[route] = {"status": _status_for(exc)}
        else:
            assert result.manifest.requested_route_id == route
            assert result.manifest.effective_route_id == route
            report[route] = {"status": "pass"}
    try:
        adapter = GeminiEmbeddingAdapter(
            profile=EmbeddingProfile(),
        )
        vector = adapter.embed_document_chunks(
            [EmbeddingDocument("Probe", "compatibility", "one short input")]
        )[0]
        assert len(vector) == 768
    except BaseException as exc:
        report[EMBEDDING_MODEL] = {"status": _status_for(exc)}
    else:
        report[EMBEDDING_MODEL] = {"status": "pass"}
    assert set(report) == {ROUTE_FLASH_LITE, ROUTE_FLASH, ROUTE_PRO_PREVIEW, EMBEDDING_MODEL}
    assert all(
        item["status"] in {"pass", "unavailable", "retired", "failed"} for item in report.values()
    )
    report_path = (
        Path(os.environ["DOCENHANCE_LIVE_REPORT"])
        if os.getenv("DOCENHANCE_LIVE_REPORT")
        else tmp_path / "live-compatibility.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
