"""Content-addressed, atomic model response caching.

Cache keys contain digests and public request parameters only.  Prompts,
source text, credentials, and provider client objects are intentionally absent
from cache paths and metadata.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|access[_-]?token|authorization|password|secret)", re.I)
_RAW_INPUT_KEY = re.compile(r"(?:prompt|source[_-]?text|document[_-]?text|raw[_-]?source)", re.I)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: object) -> str:
    return digest_bytes(canonical_json(value).encode("utf-8"))


def _ensure_public(value: object, *, path: str = "value") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text) or _RAW_INPUT_KEY.search(key_text):
                raise ValueError(
                    f"sensitive or raw-input field is not cacheable: {path}.{key_text}"
                )
            _ensure_public(child, path=f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _ensure_public(child, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class CacheKey:
    """The complete dependency set for one structured response."""

    provider: str
    backend: str
    model: str
    parameters: Mapping[str, object]
    prompt_digest: str
    schema_digest: str
    input_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_public(self.parameters, path="parameters")
        if not self.prompt_digest or not self.schema_digest:
            raise ValueError("prompt_digest and schema_digest are required cache dependencies")

    def material(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "backend": self.backend,
            "model": self.model,
            "parameters": dict(self.parameters),
            "prompt_digest": self.prompt_digest,
            "schema_digest": self.schema_digest,
            "input_digests": list(self.input_digests),
        }

    @property
    def digest(self) -> str:
        return digest_json(self.material())


@dataclass(frozen=True, slots=True)
class CacheRecord:
    key: CacheKey
    response: Any
    response_digest: str
    created_at: str
    manifest: Mapping[str, object]


class ResponseCache:
    """A small filesystem cache with atomic promotion and strict metadata rules."""

    format_version = 1

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: CacheKey) -> Path:
        return self.root / f"{key.digest}.json"

    def get(self, key: CacheKey) -> CacheRecord | None:
        path = self.path_for(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return None
        if (
            payload.get("format_version") != self.format_version
            or payload.get("key") != key.material()
        ):
            return None
        response = payload.get("response")
        response_digest = payload.get("response_digest")
        if not isinstance(response_digest, str) or digest_json(response) != response_digest:
            return None
        manifest = payload.get("manifest", {})
        if not isinstance(manifest, dict):
            return None
        return CacheRecord(
            key=key,
            response=response,
            response_digest=response_digest,
            created_at=str(payload.get("created_at", "")),
            manifest=manifest,
        )

    def put(
        self,
        key: CacheKey,
        response: Any,
        *,
        manifest: Mapping[str, object] | None = None,
    ) -> CacheRecord:
        _ensure_public(response, path="response")
        safe_manifest = dict(manifest or {})
        _ensure_public(safe_manifest, path="manifest")
        response_digest = digest_json(response)
        created_at = datetime.now(UTC).isoformat()
        payload = {
            "format_version": self.format_version,
            "key": key.material(),
            "response": response,
            "response_digest": response_digest,
            "created_at": created_at,
            "manifest": safe_manifest,
        }
        encoded = (canonical_json(payload) + "\n").encode("utf-8")
        destination = self.path_for(key)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{key.digest}.", suffix=".tmp", dir=self.root
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary_name).replace(destination)
            try:
                directory_fd = os.open(self.root, os.O_RDONLY)
            except OSError:
                directory_fd = -1
            if directory_fd >= 0:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            with suppress(FileNotFoundError):
                Path(temporary_name).unlink()
        return CacheRecord(
            key=key,
            response=response,
            response_digest=response_digest,
            created_at=created_at,
            manifest=safe_manifest,
        )

    def invalidate(self, key: CacheKey) -> None:
        try:
            self.path_for(key).unlink()
        except FileNotFoundError:
            return
