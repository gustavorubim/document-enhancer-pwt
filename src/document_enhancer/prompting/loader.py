"""Safe loading and immutable resolution of versioned Markdown prompt packs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from document_enhancer.config import yaml_parser
from document_enhancer.contracts import PromptPackLoader
from document_enhancer.domain.run import PromptPackManifest
from document_enhancer.references.loader import (
    ApplicabilityContext,
    ReferencePack,
    load_reference_pack,
)

from .errors import (
    PromptPackSecurityError,
    PromptPackValidationError,
)
from .manifest import (
    PromptPack,
    PromptTemplate,
    ReferenceInputSpec,
    ResolvedReferenceInput,
    _freeze,
)

__all__ = [
    "PromptPackLoader",
    "ApplicabilityContext",
    "GeminiPromptPackLoader",
    "DefaultPromptPackLoader",
    "PromptPack",
    "PromptTemplate",
    "ReferenceInputSpec",
    "ResolvedReferenceInput",
    "load_prompt_pack",
    "resolve_reference_inputs",
]

MAX_MANIFEST_BYTES = 512_000
MAX_FILE_BYTES = 2_000_000
MAX_YAML_NODES = 30_000
MAX_YAML_DEPTH = 50
MAX_PACK_FILES = 500
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INCLUDE_RE = re.compile(
    r"\{\{\s*(?:include\s*[: ]\s*['\"]?([^'\"}\s]+)['\"]?|>\s*([^}\s]+))\s*\}\}",
    re.IGNORECASE,
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _safe_yaml_load(raw: bytes, *, label: str) -> Any:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise PromptPackSecurityError(f"YAML file exceeds the prompt-pack limit: {label}")
    try:
        value = yaml_parser().load(raw.decode("utf-8"))
    except Exception as exc:  # ruamel exposes several parser/constructor exception classes.
        raise PromptPackSecurityError(f"Unsafe or invalid YAML in prompt pack: {label}") from exc
    _check_yaml_tree(value, label=label)
    return value


def _check_yaml_tree(
    value: Any,
    *,
    label: str,
    depth: int = 0,
    count: list[int] | None = None,
    seen: set[int] | None = None,
) -> None:
    counter = count or [0]
    seen_nodes = seen if seen is not None else set()
    counter[0] += 1
    if counter[0] > MAX_YAML_NODES:
        raise PromptPackSecurityError(f"YAML node limit exceeded: {label}")
    if depth > MAX_YAML_DEPTH:
        raise PromptPackSecurityError(f"YAML nesting limit exceeded: {label}")
    if isinstance(value, Mapping):
        object_id = id(value)
        if object_id in seen_nodes:
            raise PromptPackSecurityError(f"YAML aliases or cycles are not allowed: {label}")
        seen_nodes.add(object_id)
        for key, item in value.items():
            if not isinstance(key, str):
                raise PromptPackSecurityError(f"YAML keys must be strings: {label}")
            _check_yaml_tree(item, label=label, depth=depth + 1, count=counter, seen=seen_nodes)
    elif isinstance(value, list):
        object_id = id(value)
        if object_id in seen_nodes:
            raise PromptPackSecurityError(f"YAML aliases or cycles are not allowed: {label}")
        seen_nodes.add(object_id)
        for item in value:
            _check_yaml_tree(item, label=label, depth=depth + 1, count=counter, seen=seen_nodes)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise PromptPackSecurityError(f"Unsupported YAML value type in prompt pack: {label}")


def _safe_relative(root: Path, relative: str, *, allow_template: bool = False) -> Path:
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise PromptPackSecurityError(f"Invalid prompt-pack path: {relative!r}")
    if "\\" in relative or relative.startswith("/") or ":" in relative:
        raise PromptPackSecurityError(f"Non-canonical prompt-pack path: {relative}")
    if allow_template:
        relative = re.sub(r"\{[A-Za-z_][A-Za-z0-9_]*\}", "placeholder", relative)
    pure = PurePosixPath(relative)
    if any(part in {"", ".", ".."} for part in pure.parts) or pure.is_absolute():
        raise PromptPackSecurityError(f"Path traversal or non-canonical path rejected: {relative}")
    resolved_root = root.resolve()
    candidate = (root / Path(*pure.parts)).resolve(strict=False)
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise PromptPackSecurityError(f"Prompt-pack path escapes its root: {relative}") from exc
    return candidate


def _read_file(root: Path, relative: str, *, max_bytes: int = MAX_FILE_BYTES) -> bytes:
    path = _safe_relative(root, relative)
    if path.is_symlink():
        raise PromptPackSecurityError(f"Symlinked prompt-pack files are not allowed: {relative}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PromptPackValidationError(
            f"Prompt-pack file is missing or unreadable: {relative}"
        ) from exc
    if len(raw) > max_bytes:
        raise PromptPackSecurityError(f"Prompt-pack file exceeds the size limit: {relative}")
    return raw


def _parse_markdown(raw: bytes, *, relative: str) -> tuple[Mapping[str, Any], str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptPackValidationError(f"Prompt Markdown must be UTF-8: {relative}") from exc
    if not text.startswith("---\n"):
        return {}, text
    closing = text.find("\n---\n", 4)
    if closing < 0:
        raise PromptPackValidationError(f"Prompt front matter is not closed: {relative}")
    front_raw = text[4:closing].encode("utf-8")
    front = _safe_yaml_load(front_raw, label=relative)
    if not isinstance(front, Mapping):
        raise PromptPackValidationError(f"Prompt front matter must be a mapping: {relative}")
    return dict(front), text[closing + len("\n---\n") :]


def _expand_includes(
    root: Path,
    relative: str,
    body: str,
    file_digests: Mapping[str, str],
    *,
    stack: tuple[str, ...] = (),
) -> str:
    if relative in stack:
        chain = " -> ".join((*stack, relative))
        raise PromptPackValidationError(f"Cyclic prompt include detected: {chain}")

    def replace(match: re.Match[str]) -> str:
        include = match.group(1) or match.group(2)
        if include not in file_digests:
            raise PromptPackValidationError(
                f"Unresolved prompt include {include!r} referenced by {relative}"
            )
        raw = _read_file(root, include)
        _front, included_body = _parse_markdown(raw, relative=include)
        return _expand_includes(
            root,
            include,
            included_body,
            file_digests,
            stack=(*stack, relative),
        )

    return _INCLUDE_RE.sub(replace, body)


def _expand_frontmatter_includes(
    root: Path,
    relative: str,
    front_matter: Mapping[str, Any],
    file_digests: Mapping[str, str],
) -> str:
    declared = front_matter.get("includes", ())
    if declared in (None, ""):
        return ""
    if isinstance(declared, str) or not isinstance(declared, (list, tuple)):
        raise PromptPackValidationError(f"{relative} front matter includes must be a list")
    pieces: list[str] = []
    for include in declared:
        if not isinstance(include, str) or include not in file_digests:
            raise PromptPackValidationError(
                f"Unresolved prompt include {include!r} referenced by {relative}"
            )
        raw = _read_file(root, include)
        _front, body = _parse_markdown(raw, relative=include)
        pieces.append(_expand_includes(root, include, body, file_digests, stack=(relative,)))
    return "\n\n".join(pieces)


def _load_reference_specs(
    raw: Mapping[str, Any], required: Sequence[str]
) -> dict[str, ReferenceInputSpec]:
    value = raw.get("reference_inputs", {})
    if not isinstance(value, Mapping):
        raise PromptPackValidationError("manifest.reference_inputs must be a mapping")
    result: dict[str, ReferenceInputSpec] = {}
    for logical_name, entry in value.items():
        if not isinstance(logical_name, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]{1,80}", logical_name
        ):
            raise PromptPackValidationError("reference input logical names must be snake_case")
        if not isinstance(entry, Mapping):
            raise PromptPackValidationError(f"reference_inputs.{logical_name} must be a mapping")
        path = entry.get("path")
        if path is not None and not isinstance(path, str):
            raise PromptPackValidationError(
                f"reference_inputs.{logical_name}.path must be a string"
            )
        if path is not None:
            _safe_relative(Path("/prompt-pack"), path, allow_template=True)
        kinds = entry.get("kinds", ())
        if isinstance(kinds, str):
            kinds = (kinds,)
        if not isinstance(kinds, (list, tuple)) or not all(isinstance(item, str) for item in kinds):
            raise PromptPackValidationError(
                f"reference_inputs.{logical_name}.kinds must be strings"
            )
        source = entry.get("source", "pack")
        if source not in {"pack", "applicable_context", "runtime"}:
            raise PromptPackValidationError(f"reference_inputs.{logical_name}.source is invalid")
        result[logical_name] = ReferenceInputSpec(
            logical_name=logical_name,
            path=path,
            kind=str(entry.get("kind", "supporting")),
            required=bool(entry.get("required", True)),
            source=source,
            kinds=tuple(kinds),
        )
    missing = sorted(set(required) - set(result))
    if missing:
        raise PromptPackValidationError(
            "manifest.required_references has no binding for: " + ", ".join(missing)
        )
    return result


def _manifest_model(raw: Mapping[str, Any]) -> PromptPackManifest:
    # ``reference_inputs`` is deliberately a loader concern. It is kept in the raw manifest
    # while the frozen cross-lane Pydantic contract remains dependency-light.
    model_data = dict(raw)
    for key in (
        "schema_version",
        "reference_inputs",
        "required_runtime_inputs",
        "composition_contract",
        "document_types",
        "manifest_sha256",
        "pack_sha256",
        "description",
    ):
        model_data.pop(key, None)
    try:
        return PromptPackManifest.model_validate(model_data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(item) for item in first.get("loc", ())) or "manifest"
        raise PromptPackValidationError(
            f"manifest.{location}: {first.get('msg', 'invalid value')}"
        ) from exc


def _pack_digest(manifest_sha256: str, file_digests: Mapping[str, str]) -> str:
    payload = (
        manifest_sha256
        + "\n"
        + "\n".join(f"{path}\0{file_digests[path]}" for path in sorted(file_digests))
    )
    return _sha256_bytes(payload.encode("utf-8"))


def _load(location: Path) -> PromptPack:
    root = Path(location).resolve()
    if not root.is_dir():
        raise PromptPackValidationError(f"Prompt-pack root is not a directory: {location}")
    manifest_path = root / "manifest.yaml"
    try:
        raw_manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise PromptPackValidationError(
            f"Prompt-pack manifest is missing: {manifest_path}"
        ) from exc
    raw = _safe_yaml_load(raw_manifest_bytes, label="manifest.yaml")
    if not isinstance(raw, Mapping):
        raise PromptPackValidationError("manifest.yaml root must be a mapping")
    raw = dict(raw)
    if len(raw.get("file_digests", {})) > MAX_PACK_FILES:
        raise PromptPackSecurityError("Prompt pack contains too many manifest-listed files")

    manifest = _manifest_model(raw)
    file_digests_raw = raw.get("file_digests")
    if not isinstance(file_digests_raw, Mapping) or not file_digests_raw:
        raise PromptPackValidationError("manifest.file_digests must list every prompt-pack file")
    file_digests: dict[str, str] = {}
    for relative, expected in file_digests_raw.items():
        if (
            not isinstance(relative, str)
            or not isinstance(expected, str)
            or not _SHA256_RE.fullmatch(expected)
        ):
            raise PromptPackValidationError(
                f"manifest.file_digests has an invalid entry: {relative!r}"
            )
        path = _safe_relative(root, relative)
        if not path.is_file():
            raise PromptPackValidationError(f"manifest.file_digests lists missing file: {relative}")
        actual = _sha256_bytes(_read_file(root, relative))
        if actual != expected:
            raise PromptPackValidationError(
                f"digest mismatch for {relative}: expected {expected}, got {actual}"
            )
        file_digests[relative] = expected

    required = manifest.required_references
    reference_specs = _load_reference_specs(raw, required)
    templates: dict[str, PromptTemplate] = {}
    for prompt in manifest.prompts:
        if prompt.template_path not in file_digests:
            raise PromptPackValidationError(
                f"prompt {prompt.prompt_id} template is not listed in manifest.file_digests"
            )
        for fragment in prompt.shared_fragments:
            if fragment not in file_digests:
                raise PromptPackValidationError(
                    f"prompt {prompt.prompt_id} shared fragment is not listed: {fragment}"
                )
        raw_template = _read_file(root, prompt.template_path)
        front, body = _parse_markdown(raw_template, relative=prompt.template_path)
        for field, expected in (("prompt_id", prompt.prompt_id), ("stage", prompt.stage)):
            if front.get(field) != expected:
                raise PromptPackValidationError(
                    f"{prompt.template_path} front matter {field!r} does not match manifest"
                )
        declared = _expand_frontmatter_includes(root, prompt.template_path, front, file_digests)
        expanded_body = "\n\n".join(part for part in (declared, body) if part)
        expanded = _expand_includes(root, prompt.template_path, expanded_body, file_digests)
        templates[prompt.prompt_id] = PromptTemplate(
            path=prompt.template_path,
            digest=file_digests[prompt.template_path],
            front_matter=_freeze(front),
            body=expanded,
        )

    manifest_sha256 = _sha256_bytes(_canonical_json(raw))
    pack_sha256 = _pack_digest(manifest_sha256, file_digests)
    return PromptPack(
        root=root,
        manifest=manifest,
        raw_manifest=raw,
        file_digests=file_digests,
        reference_inputs=reference_specs,
        templates=templates,
        manifest_sha256=manifest_sha256,
        pack_sha256=pack_sha256,
    )


class GeminiPromptPackLoader:
    """Concrete implementation of the frozen ``PromptPackLoader`` port."""

    def load(
        self,
        location: Path,
        *,
        reference_pack: Path | ReferencePack | None = None,
        reference_context: ApplicabilityContext | Mapping[str, Any] | None = None,
    ) -> PromptPack:
        pack = _load(location)
        if isinstance(reference_pack, Path):
            reference_pack = load_reference_pack(reference_pack)
        if reference_pack is not None:
            document_types = _document_types(pack)
            for document_type in document_types:
                resolve_reference_inputs(
                    pack,
                    reference_pack,
                    document_type=document_type,
                    context=reference_context,
                )
        from .validator import validate_prompt_pack

        report = validate_prompt_pack(pack, reference_pack=reference_pack)
        if not report.ok:
            raise PromptPackValidationError(
                "Prompt-pack validation failed: " + "; ".join(report.errors),
                errors=report.errors,
            )
        return pack

    def validate(self, pack: Path | PromptPack) -> tuple[str, ...]:
        from .validator import validate_prompt_pack

        report = validate_prompt_pack(pack)
        return report.errors


DefaultPromptPackLoader = GeminiPromptPackLoader


def _document_types(pack: PromptPack) -> tuple[str, ...]:
    configured = pack.raw_manifest.get(
        "document_types", ("process", "methodology", "standard", "desktop_procedure")
    )
    if isinstance(configured, str):
        configured = (configured,)
    if not isinstance(configured, (list, tuple)) or not all(
        isinstance(item, str) for item in configured
    ):
        raise PromptPackValidationError("manifest.document_types must be a list of strings")
    return tuple(configured)


def _reference_file_digest(reference_pack: ReferencePack, relative: str) -> str:
    for entry in reference_pack.files:
        if entry.path == relative:
            return entry.sha256
    # ReferencePack.path performs the manifest allow-list and root-constrained check.
    raw = reference_pack.path(relative).read_bytes()
    return _sha256_bytes(raw)


def resolve_reference_inputs(
    pack: PromptPack,
    reference_pack: ReferencePack,
    *,
    document_type: str = "process",
    context: ApplicabilityContext | Mapping[str, Any] | None = None,
) -> tuple[ResolvedReferenceInput, ...]:
    """Resolve all required governed inputs and retain exact pack/file metadata."""

    context_obj = (
        context
        if isinstance(context, ApplicabilityContext)
        else ApplicabilityContext.from_mapping(context)
    )
    # Prompt-pack validation must be able to resolve the common governed-document context even
    # when the caller has not yet supplied run-specific metadata. Explicit caller fields win.
    context_obj = ApplicabilityContext(
        document_type=context_obj.document_type or document_type,
        business_domain=context_obj.business_domain or "enterprise_operations",
        jurisdiction=context_obj.jurisdiction or "GLOBAL",
        confidentiality=context_obj.confidentiality or "public_internal",
        document_status=context_obj.document_status or "draft",
        tags=context_obj.tags or frozenset({"governed_document", "controlled_activity"}),
        effective_on=context_obj.effective_on,
    )
    results: list[ResolvedReferenceInput] = []
    for logical_name in pack.manifest.required_references:
        spec = pack.reference_inputs[logical_name]
        if spec.source == "runtime":
            continue
        selected: list[tuple[str, str | None, str]] = []
        if spec.source == "applicable_context":
            resolution = reference_pack.resolve_context(context_obj)
            if not resolution.ok:
                raise PromptPackValidationError(
                    f"reference resolution for {logical_name} failed: "
                    + "; ".join(resolution.errors)
                )
            kinds = set(spec.kinds)
            selected = [
                (reference.path or "", reference.reference_id, reference.kind)
                for reference in resolution.references
                if reference.path and (not kinds or reference.kind in kinds)
            ]
        else:
            if not spec.path:
                raise PromptPackValidationError(f"reference input {logical_name} has no path")
            relative = spec.path.format(document_type=document_type)
            selected = [(relative, logical_name, spec.kind)]
        if not selected and spec.required:
            raise PromptPackValidationError(
                f"required reference input did not resolve: {logical_name}"
            )
        for relative, reference_id, kind in selected:
            if not relative:
                continue
            path = reference_pack.path(relative)
            raw = path.read_bytes()
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PromptPackValidationError(
                    f"reference input is not UTF-8: {logical_name} ({relative})"
                ) from exc
            results.append(
                ResolvedReferenceInput(
                    logical_name=logical_name,
                    path=relative,
                    kind=kind,
                    pack_id=reference_pack.pack_id,
                    pack_version=reference_pack.version,
                    pack_sha256=reference_pack.pack_sha256,
                    sha256=_reference_file_digest(reference_pack, relative),
                    size_bytes=len(raw),
                    content=content,
                    reference_id=reference_id,
                )
            )
    return tuple(results)


def load_prompt_pack(
    location: Path,
    *,
    reference_pack: Path | ReferencePack | None = None,
    reference_context: ApplicabilityContext | Mapping[str, Any] | None = None,
) -> PromptPack:
    """Load a prompt pack and optionally prove all required references resolve."""

    return GeminiPromptPackLoader().load(
        location,
        reference_pack=reference_pack,
        reference_context=reference_context,
    )
