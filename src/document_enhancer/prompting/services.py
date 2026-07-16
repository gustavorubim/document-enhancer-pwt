"""Prompt discovery and inspection services for the future WT6 CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from document_enhancer.references.loader import ReferencePack

from .composer import PromptPackComposer
from .loader import load_prompt_pack
from .manifest import PromptPack
from .validator import validate_prompt_pack


def list_prompts(
    location: Path | PromptPack,
    *,
    reference_pack: Path | ReferencePack | None = None,
) -> list[dict[str, object]]:
    pack = location if isinstance(location, PromptPack) else load_prompt_pack(location)
    return [
        {
            "prompt_id": prompt.prompt_id,
            "stage": prompt.stage,
            "model_route": prompt.model_route,
            "output_schema": prompt.output_schema,
            "template_path": prompt.template_path,
            "pack_id": pack.pack_id,
            "pack_version": pack.version,
        }
        for prompt in pack.manifest.prompts
    ]


def show_prompt(
    location: Path | PromptPack,
    prompt_id: str,
    *,
    composed: bool = False,
    variables: dict[str, Any] | None = None,
    reference_pack: Path | ReferencePack | None = None,
    document_type: str = "process",
) -> str | dict[str, object]:
    pack = location if isinstance(location, PromptPack) else load_prompt_pack(location)
    prompt = pack.prompt(prompt_id)
    if not composed:
        return {
            "prompt_id": prompt.prompt_id,
            "stage": prompt.stage,
            "model_route": prompt.model_route,
            "output_schema": prompt.output_schema,
            "template_path": prompt.template_path,
            "shared_fragments": list(prompt.shared_fragments),
            "variables": [item.model_dump(mode="json") for item in prompt.variables],
            "pack_id": pack.pack_id,
            "pack_version": pack.version,
        }
    if not isinstance(reference_pack, ReferencePack):
        if reference_pack is None:
            raise ValueError("--composed prompt inspection requires a reference pack")
        from document_enhancer.references.loader import load_reference_pack

        reference_pack = load_reference_pack(reference_pack)
    return PromptPackComposer(
        pack,
        reference_pack=reference_pack,
        document_type=document_type,
    ).compose(prompt_id, variables or {"document_type": document_type})


def validate(
    location: Path | PromptPack,
    *,
    reference_pack: Path | ReferencePack | None = None,
) -> dict[str, object]:
    report = validate_prompt_pack(location, reference_pack=reference_pack)
    return {
        "ok": report.ok,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
        **report.details,
    }


__all__ = ["list_prompts", "show_prompt", "validate"]
