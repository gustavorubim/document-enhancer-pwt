"""Safe prompt-run snapshots containing digests and metadata, never raw source or credentials."""

from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from .composer import ComposedPrompt

_SECRET_KEYS = {"api_key", "apikey", "token", "secret", "password", "credential"}
_RAW_KEYS = {
    "source_text",
    "raw_source",
    "raw_source_text",
    "document_text",
    "prompt",
    "reviewer_inputs",
    "reviewer_input",
    "answers",
    "steering",
    "waivers",
    "checklist",
    "analysis_results",
}
_SECRET_TEXT = re.compile(
    r"(?:GOOGLE_API_KEY|GEMINI_API_KEY|BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY|sk-[A-Za-z0-9]{12,})"
)


def _redact(value: Any, *, key: str = "") -> Any:
    lowered = key.lower()
    if any(secret in lowered for secret in _SECRET_KEYS):
        return "[REDACTED]"
    if lowered in _RAW_KEYS:
        return {"sha256": _sha(value), "size": len(str(value))}
    if isinstance(value, str) and _SECRET_TEXT.search(value):
        return {"sha256": _sha(value), "size": len(value), "redacted": True}
    if isinstance(value, dict):
        return {str(item_key): _redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, key=key) for item in value]
    return value


def _sha(value: Any) -> str:
    import hashlib

    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def build_prompt_snapshot(
    composed: ComposedPrompt,
    *,
    variables: dict[str, Any] | None = None,
    schema_digest: str | None = None,
) -> dict[str, Any]:
    """Build a snapshot suitable for a run artifact.

    The exact prompt text is intentionally excluded. Template/fragment digests, resolved
    reference metadata, variable names, and the rendered digest are sufficient to reproduce
    and audit the composition without duplicating sensitive source material.
    """

    return {
        "prompt_id": composed.prompt_id,
        "prompt_pack_id": composed.pack_id,
        "prompt_pack_version": composed.pack_version,
        "prompt_pack_manifest_sha256": composed.pack_manifest_sha256,
        "prompt_pack_sha256": composed.pack_sha256,
        "reference_scope": list(composed.reference_scope),
        "rendered_prompt_digest": composed.resolution.rendered_prompt_digest,
        "template_digest": composed.resolution.template_digest,
        "shared_fragment_digests": dict(composed.resolution.shared_fragment_digests),
        "resolved_reference_digests": dict(composed.resolution.resolved_reference_digests),
        "resolved_references": [item.snapshot() for item in composed.resolved_references],
        "variable_names": list(composed.resolution.variable_names),
        "variable_values": _redact(variables or {}),
        "composition_order": list(composed.resolution.composition_order),
        "output_schema": composed.resolution.output_schema,
        "schema_digest": schema_digest,
    }


def write_prompt_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    """Write one deterministic JSON snapshot after removing unsafe fields."""

    safe = _redact(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(safe, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    open_descriptor: int | None = descriptor
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            open_descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except BaseException:
        if open_descriptor is not None:
            os.close(open_descriptor)
        raise
    finally:
        with suppress(FileNotFoundError):
            temporary_path.unlink()


__all__ = ["build_prompt_snapshot", "write_prompt_snapshot"]
