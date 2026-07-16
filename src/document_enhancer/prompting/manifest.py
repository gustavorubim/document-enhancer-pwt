"""Immutable runtime records used by the prompt-pack loader and composer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from document_enhancer.domain.run import PromptPackManifest, PromptSpec


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ReferenceInputSpec:
    """A logical reference input and its resolution rule inside a reference pack."""

    logical_name: str
    path: str | None = None
    kind: str = "supporting"
    required: bool = True
    source: str = "pack"
    kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedReferenceInput:
    """Reference metadata plus content used for one composition.

    ``content`` is intentionally runtime-only. Snapshot helpers omit it and retain only
    the immutable metadata and digest fields.
    """

    logical_name: str
    path: str | None
    kind: str
    pack_id: str
    pack_version: str
    pack_sha256: str
    sha256: str
    size_bytes: int
    content: str = ""
    reference_id: str | None = None

    def snapshot(self) -> dict[str, object]:
        return {
            "logical_name": self.logical_name,
            "path": self.path,
            "kind": self.kind,
            "reference_id": self.reference_id,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "pack_sha256": self.pack_sha256,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class PromptTemplate:
    """Decoded Markdown template and front-matter metadata."""

    path: str
    digest: str
    front_matter: Mapping[str, Any]
    body: str


@dataclass(frozen=True)
class PromptPack:
    """Validated, immutable view over a prompt-pack root."""

    root: Path
    manifest: PromptPackManifest
    raw_manifest: Mapping[str, Any]
    file_digests: Mapping[str, str]
    reference_inputs: Mapping[str, ReferenceInputSpec]
    templates: Mapping[str, PromptTemplate]
    manifest_sha256: str
    pack_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.resolve())
        object.__setattr__(self, "raw_manifest", _freeze(self.raw_manifest))
        object.__setattr__(self, "file_digests", MappingProxyType(dict(self.file_digests)))
        object.__setattr__(self, "reference_inputs", MappingProxyType(dict(self.reference_inputs)))
        object.__setattr__(self, "templates", MappingProxyType(dict(self.templates)))

    @property
    def pack_id(self) -> str:
        return self.manifest.pack_id

    @property
    def version(self) -> str:
        return self.manifest.version

    def prompt(self, prompt_id: str) -> PromptSpec:
        for prompt in self.manifest.prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        raise KeyError(prompt_id)

    def template_for(self, prompt: PromptSpec) -> PromptTemplate:
        try:
            return self.templates[prompt.prompt_id]
        except KeyError as exc:  # pragma: no cover - guarded at load time
            raise KeyError(f"template for prompt {prompt.prompt_id!r} is not loaded") from exc
