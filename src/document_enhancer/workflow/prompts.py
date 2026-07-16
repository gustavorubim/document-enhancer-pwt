"""Prompt-pack selection and safe resolved-prompt run artifacts."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from document_enhancer.artifacts.atomic import atomic_write_json
from document_enhancer.domain.schema_registry import schema_models
from document_enhancer.prompting import PromptPackComposer, load_prompt_pack
from document_enhancer.prompting.snapshot import build_prompt_snapshot
from document_enhancer.references.loader import ReferencePack, load_reference_pack


def resolved_prompt_artifact(
    prompt_pack: Path,
    *,
    reference_pack: Path | ReferencePack,
    prompt_ids: list[str],
    document_type: str = "process",
    variables: dict[str, Any] | None = None,
    destination: Path | None = None,
) -> dict[str, object]:
    """Resolve prompts and retain only digests/metadata, never raw source or credentials."""

    pack = load_prompt_pack(prompt_pack)
    references = (
        reference_pack
        if isinstance(reference_pack, ReferencePack)
        else load_reference_pack(reference_pack)
    )
    composer = PromptPackComposer(pack, reference_pack=references, document_type=document_type)
    entries: list[dict[str, object]] = []
    schemas = schema_models()
    variables = variables or {"document_type": document_type}
    for prompt_id in prompt_ids:
        spec = pack.prompt(prompt_id)
        declared_names = {item.name for item in spec.variables}
        prompt_variables = {
            name: value for name, value in variables.items() if name in declared_names
        }
        composed = composer.compose_with_metadata(prompt_id, prompt_variables)
        schema = schemas.get(composed.resolution.output_schema)
        schema_digest = None
        if schema is not None:
            schema_digest = sha256(
                json.dumps(
                    schema.model_json_schema(), sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
        entries.append(
            build_prompt_snapshot(
                composed,
                variables=prompt_variables,
                schema_digest=schema_digest,
            )
        )
    artifact = {
        "schema_version": "m5.resolved-prompts.v1",
        "pack_id": pack.pack_id,
        "pack_version": pack.version,
        "pack_manifest_sha256": pack.manifest_sha256,
        "reference_pack_id": references.pack_id,
        "reference_pack_version": references.version,
        "document_type": document_type,
        "prompts": entries,
    }
    if destination is not None:
        atomic_write_json(destination, artifact)
    return artifact


def inspect_resolved_prompt_artifact(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read resolved prompt artifact: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "m5.resolved-prompts.v1":
        raise ValueError("resolved prompt artifact has an unsupported schema_version")
    return value


__all__ = ["inspect_resolved_prompt_artifact", "resolved_prompt_artifact"]
