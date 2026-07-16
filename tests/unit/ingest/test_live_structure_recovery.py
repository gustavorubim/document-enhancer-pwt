from __future__ import annotations

import os
from pathlib import Path

import pytest

from document_enhancer.ingest.markdown import MarkdownParser
from document_enhancer.ingest.recovery import StructureRecoveryConfig, StructureRecoveryService
from document_enhancer.llm import GeminiGatewayConfig, GeminiModelGateway
from document_enhancer.prompting.composer import PromptPackComposer
from document_enhancer.prompting.loader import load_prompt_pack
from document_enhancer.references.loader import load_reference_pack

ROOT = Path(__file__).resolve().parents[3]


def _configured_api_key() -> str | None:
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        if os.getenv(name):
            return os.environ[name]
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() in {"GOOGLE_API_KEY", "GEMINI_API_KEY"}:
            value = value.strip().strip('"').strip("'")
            if value:
                return value
    return None


@pytest.mark.live_model
def test_live_structure_scan_and_one_recovery_proposal() -> None:
    if os.getenv("DOCENHANCE_LIVE_STRUCTURE") != "1":
        pytest.skip()
    api_key = _configured_api_key()
    if not api_key:
        pytest.skip()
    reference_pack = load_reference_pack(ROOT / "reference_packs" / "enterprise_core")
    prompt_pack = load_prompt_pack(
        ROOT / "prompt_packs" / "gemini_core", reference_pack=reference_pack
    )
    composer = PromptPackComposer(prompt_pack, reference_pack=reference_pack)
    raw = MarkdownParser().parse(ROOT / "fixtures" / "synthetic" / "ingest" / "m3b" / "clean.md")
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(api_key=api_key, max_retries_override=1),
    )

    scan_result = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="auto"),
        gateway=gateway,
        prompt_composer=composer,
    ).run(raw)
    assert scan_result.metadata is not None
    assert any(
        manifest.prompt_id == "structure.triage" for manifest in scan_result.metadata.call_manifests
    )

    recovery_result = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="force"),
        gateway=gateway,
        prompt_composer=composer,
    ).run(raw)
    assert recovery_result.metadata is not None
    assert any(
        manifest.prompt_id == "structure.recover-window"
        for manifest in recovery_result.metadata.call_manifests
    )
    assert recovery_result.window_proposals
