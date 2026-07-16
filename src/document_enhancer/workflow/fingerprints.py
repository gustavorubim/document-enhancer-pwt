"""Governed input fingerprints used by the M5 stage cache."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from document_enhancer.domain.schema_registry import schema_models
from document_enhancer.prompting import load_prompt_pack
from document_enhancer.references.loader import load_reference_pack


def workflow_input_fingerprints(
    *, prompt_pack: Path | None = None, reference_pack: Path | None = None
) -> dict[str, object]:
    """Return stable pack/schema fingerprints without reading source or credentials."""

    result: dict[str, object] = {}
    if prompt_pack is not None:
        pack = load_prompt_pack(prompt_pack)
        result["prompt"] = pack.pack_sha256
        result["template"] = pack.pack_sha256
    if reference_pack is not None:
        result["reference"] = load_reference_pack(reference_pack).pack_sha256
    schema_payload = {
        name: model.model_json_schema() for name, model in sorted(schema_models().items())
    }
    result["schema"] = sha256(
        json.dumps(schema_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return result


__all__ = ["workflow_input_fingerprints"]
