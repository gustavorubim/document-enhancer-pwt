"""Versioned reference-pack loading, validation, digests, and context resolution.

The WT0 ``ReferencePackLoader`` protocol remains re-exported under its original name.
``EnterpriseReferencePackLoader`` is the concrete implementation for M2 and deliberately
uses plain immutable runtime records rather than duplicating WT1 domain models.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from document_enhancer.config import yaml_parser
from document_enhancer.contracts import ReferencePackLoader as ReferencePackLoader

from .errors import (
    ReferencePackError,
    ReferencePackSecurityError,
    ReferencePackValidationError,
    ValidationReport,
)
from .renderer import render_template

__all__ = [
    "ApplicabilityContext",
    "EnterpriseReferencePackLoader",
    "ReferenceFile",
    "ReferencePack",
    "ReferencePackLoader",
    "ReferencePackValidator",
    "ResolvedReference",
    "PrecedenceResolution",
    "load_reference_pack",
    "resolve_precedence",
    "validate_reference_pack",
]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]{2,80}$")
_ALLOWED_PRECEDENCE = (
    "reviewer_steering",
    "regulation",
    "policy",
    "standard",
    "template",
    "style_guide",
    "source",
)
_ALLOWED_STATUS = {"draft", "active", "deprecated", "retired"}
_MAX_YAML_BYTES = 2_000_000
_MAX_YAML_NODES = 20_000
_MAX_YAML_DEPTH = 40


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=lambda item: item.isoformat() if isinstance(item, (date, datetime)) else str(item),
    ).encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _safe_yaml_load(path: Path) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReferencePackValidationError(f"Unable to read YAML file: {path}") from exc
    if len(raw) > _MAX_YAML_BYTES:
        raise ReferencePackSecurityError(f"YAML file exceeds {_MAX_YAML_BYTES} bytes: {path}")
    parser = yaml_parser()
    try:
        value = parser.load(raw.decode("utf-8"))
    except Exception as exc:  # ruamel exposes several parser/constructor exception classes.
        raise ReferencePackSecurityError(f"Unsafe or invalid YAML: {path}") from exc
    _check_yaml_tree(value, path=path)
    return value


def _check_yaml_tree(
    value: Any,
    *,
    path: Path,
    depth: int = 0,
    count: list[int] | None = None,
    seen: set[int] | None = None,
) -> None:
    counter = count or [0]
    seen_nodes = seen if seen is not None else set()
    counter[0] += 1
    if counter[0] > _MAX_YAML_NODES:
        raise ReferencePackSecurityError(f"YAML node limit exceeded: {path}")
    if depth > _MAX_YAML_DEPTH:
        raise ReferencePackSecurityError(f"YAML nesting limit exceeded: {path}")
    if isinstance(value, Mapping):
        object_id = id(value)
        if object_id in seen_nodes:
            raise ReferencePackSecurityError(f"YAML aliases or cycles are not allowed: {path}")
        seen_nodes.add(object_id)
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReferencePackSecurityError(f"YAML keys must be strings: {path}")
            _check_yaml_tree(item, path=path, depth=depth + 1, count=counter, seen=seen_nodes)
    elif isinstance(value, list):
        object_id = id(value)
        if object_id in seen_nodes:
            raise ReferencePackSecurityError(f"YAML aliases or cycles are not allowed: {path}")
        seen_nodes.add(object_id)
        for item in value:
            _check_yaml_tree(item, path=path, depth=depth + 1, count=counter, seen=seen_nodes)
    elif value is not None and not isinstance(value, (str, int, float, bool, date, datetime)):
        raise ReferencePackSecurityError(
            f"Unsupported YAML value type {type(value).__name__}: {path}"
        )


def _safe_relative(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise ReferencePackSecurityError(f"Invalid reference-pack path: {relative!r}")
    if "\\" in relative:
        raise ReferencePackSecurityError(
            f"Backslash is not allowed in reference-pack paths: {relative}"
        )
    raw_parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts) or ":" in relative:
        raise ReferencePackSecurityError(
            f"Path traversal or non-canonical path rejected: {relative}"
        )
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ReferencePackSecurityError(
            f"Path traversal or non-canonical path rejected: {relative}"
        )
    root_resolved = root.resolve()
    candidate = (root / Path(*pure.parts)).resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ReferencePackSecurityError(f"Path escapes reference-pack root: {relative}") from exc
    return candidate


def _required_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReferencePackValidationError(f"{name} must be a mapping")
    return value


@dataclass(frozen=True)
class ReferenceFile:
    path: str
    sha256: str
    kind: str
    required: bool = True


@dataclass(frozen=True)
class ApplicabilityContext:
    """Filters used to select applicable governed context."""

    document_type: str | None = None
    business_domain: str | None = None
    jurisdiction: str | None = None
    confidentiality: str | None = None
    document_status: str | None = None
    tags: frozenset[str] = frozenset()
    effective_on: date | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> ApplicabilityContext:
        value = value or {}
        raw_tags = value.get("tags", ())
        tags = (
            frozenset(str(item) for item in raw_tags)
            if isinstance(raw_tags, (list, tuple, set))
            else frozenset()
        )
        return cls(
            document_type=value.get("document_type"),
            business_domain=value.get("business_domain"),
            jurisdiction=value.get("jurisdiction"),
            confidentiality=value.get("confidentiality"),
            document_status=value.get("document_status"),
            tags=tags,
            effective_on=_as_date(value.get("effective_on")),
        )


@dataclass(frozen=True)
class ResolvedReference:
    reference_id: str
    path: str | None
    kind: str
    precedence: str
    precedence_rank: int
    applicable: bool = True
    reason: str = "matched applicability"


@dataclass(frozen=True)
class PrecedenceResolution:
    references: tuple[ResolvedReference, ...]
    conflicts: tuple[str, ...]
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ReferencePack:
    """Validated, immutable view of one reference-pack root."""

    root: Path
    manifest: Mapping[str, Any]
    files: tuple[ReferenceFile, ...]

    @property
    def pack_id(self) -> str:
        return str(self.manifest["pack_id"])

    @property
    def version(self) -> str:
        return str(self.manifest["version"])

    @property
    def supported_document_types(self) -> tuple[str, ...]:
        supported = self.manifest.get("supported_document_types", {})
        return tuple(str(item) for item in supported)

    @property
    def pack_sha256(self) -> str:
        return str(self.manifest.get("pack_sha256", ""))

    def path(self, relative: str) -> Path:
        """Resolve a manifest-owned path under the pack root."""

        candidate = _safe_relative(self.root, relative)
        listed = {item.path for item in self.files}
        if relative != "manifest.yaml" and relative not in listed:
            raise ReferencePackValidationError(f"Path is not listed in manifest files: {relative}")
        if not candidate.is_file():
            raise ReferencePackValidationError(f"Reference-pack file is missing: {relative}")
        return candidate

    def template_path(self, document_type: str) -> Path:
        supported = _required_mapping(
            self.manifest.get("supported_document_types"), "supported_document_types"
        )
        entry = supported.get(document_type)
        if not isinstance(entry, Mapping) or not isinstance(entry.get("template"), str):
            raise ReferencePackValidationError(f"Unsupported document type: {document_type}")
        return self.path(entry["template"])

    def requirements_path(self, document_type: str) -> Path:
        supported = _required_mapping(
            self.manifest.get("supported_document_types"), "supported_document_types"
        )
        entry = supported.get(document_type)
        if not isinstance(entry, Mapping) or not isinstance(entry.get("requirements"), str):
            raise ReferencePackValidationError(
                f"No requirements for document type: {document_type}"
            )
        return self.path(entry["requirements"])

    def example_path(self, document_type: str) -> Path:
        supported = _required_mapping(
            self.manifest.get("supported_document_types"), "supported_document_types"
        )
        entry = supported.get(document_type)
        if not isinstance(entry, Mapping) or not isinstance(entry.get("example"), str):
            raise ReferencePackValidationError(f"No example for document type: {document_type}")
        return self.path(entry["example"])

    def render(self, document_type: str, data: Mapping[str, Any] | None = None) -> str:
        return render_template(self.template_path(document_type), data)

    def applicable_references(
        self, context: ApplicabilityContext | Mapping[str, Any] | None = None
    ) -> tuple[ResolvedReference, ...]:
        return resolve_precedence(self, context).references

    def resolve_context(
        self, context: ApplicabilityContext | Mapping[str, Any] | None = None
    ) -> PrecedenceResolution:
        return resolve_precedence(self, context)


def _selector_matches(selector: Mapping[str, Any], context: ApplicabilityContext) -> bool:
    values = {
        "document_types": {context.document_type} if context.document_type else set(),
        "business_domains": {context.business_domain} if context.business_domain else set(),
        "jurisdictions": {context.jurisdiction} if context.jurisdiction else set(),
        "confidentiality": {context.confidentiality} if context.confidentiality else set(),
        "document_status": {context.document_status} if context.document_status else set(),
        "tags": set(context.tags),
    }
    for key, expected in values.items():
        allowed = selector.get(key)
        if allowed is None:
            continue
        if isinstance(allowed, str):
            allowed_values = {allowed}
        elif isinstance(allowed, Sequence):
            allowed_values = {str(item) for item in allowed}
        else:
            return False
        if key == "tags":
            if not allowed_values.issubset(expected):
                return False
        elif not expected or not expected.intersection(allowed_values):
            return False
    from_date = _as_date(selector.get("effective_from"))
    to_date = _as_date(selector.get("effective_to"))
    if from_date and context.effective_on and context.effective_on < from_date:
        return False
    if to_date and context.effective_on and context.effective_on > to_date:
        return False
    if context.effective_on and from_date is None and to_date is None:
        return True
    return True


def resolve_precedence(
    pack: ReferencePack,
    context: ApplicabilityContext | Mapping[str, Any] | None = None,
    *,
    reviewer_steering: bool = False,
) -> PrecedenceResolution:
    context = (
        context
        if isinstance(context, ApplicabilityContext)
        else ApplicabilityContext.from_mapping(context)
    )
    precedence = tuple(pack.manifest.get("precedence", {}).get("order", ()))
    rank = {name: index for index, name in enumerate(precedence)}
    resolved: list[ResolvedReference] = []
    sources = pack.manifest.get("context_sources", ())
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
        sources = ()
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        source_id = str(source.get("reference_id", ""))
        kind = str(source.get("kind", ""))
        selector = source.get("applies_when", {})
        if not isinstance(selector, Mapping) or not _selector_matches(selector, context):
            continue
        if kind not in rank:
            continue
        resolved.append(
            ResolvedReference(
                reference_id=source_id,
                path=str(source.get("path")) if source.get("path") else None,
                kind=kind,
                precedence=kind,
                precedence_rank=rank[kind],
            )
        )
    if reviewer_steering and "reviewer_steering" in rank:
        resolved.append(
            ResolvedReference(
                reference_id="RUN-REVIEWER-STEERING",
                path=None,
                kind="reviewer_steering",
                precedence="reviewer_steering",
                precedence_rank=rank["reviewer_steering"],
                reason="explicit current-run steering",
            )
        )
    resolved.sort(key=lambda item: (item.precedence_rank, item.reference_id))
    conflicts: list[str] = []
    errors: list[str] = []
    by_id = {item.reference_id: item for item in resolved}
    for conflict in pack.manifest.get("conflicts", ()):
        if not isinstance(conflict, Mapping):
            continue
        left = by_id.get(str(conflict.get("left")))
        right = by_id.get(str(conflict.get("right")))
        if not left or not right:
            continue
        if left.precedence_rank == right.precedence_rank:
            message = (
                f"conflict {conflict.get('conflict_id', 'unknown')} has equal precedence for "
                f"{left.reference_id} and {right.reference_id}"
            )
            conflicts.append(message)
            errors.append(message)
        elif conflict.get("resolution") not in {"higher_precedence_wins", "surface_both"}:
            message = f"conflict {conflict.get('conflict_id', 'unknown')} has invalid resolution"
            conflicts.append(message)
            errors.append(message)
        else:
            if conflict.get("resolution") == "surface_both":
                conflicts.append(
                    f"conflict {conflict.get('conflict_id', 'unknown')} surfaced; "
                    f"both {left.reference_id} and {right.reference_id} remain visible"
                )
            else:
                winner = left if left.precedence_rank < right.precedence_rank else right
                conflicts.append(
                    f"conflict {conflict.get('conflict_id', 'unknown')} surfaced; "
                    f"{winner.reference_id} controls by higher precedence"
                )
    return PrecedenceResolution(tuple(resolved), tuple(conflicts), tuple(errors))


class ReferencePackValidator:
    """Deterministic validator for manifest, files, templates, ontology, and rubrics."""

    def validate(
        self,
        location: Path | ReferencePack,
        *,
        context: ApplicabilityContext | Mapping[str, Any] | None = None,
    ) -> list[str]:
        return list(self.report(location, context=context).errors)

    def report(
        self,
        location: Path | ReferencePack,
        *,
        context: ApplicabilityContext | Mapping[str, Any] | None = None,
    ) -> ValidationReport:
        if isinstance(location, ReferencePack):
            root = location.root
            manifest = dict(location.manifest)
        else:
            root = Path(location)
            manifest_path = root / "manifest.yaml"
            errors: list[str] = []
            if not root.exists() or not root.is_dir():
                return ValidationReport((f"reference-pack root does not exist: {root}",))
            if not manifest_path.is_file():
                return ValidationReport((f"missing manifest.yaml under: {root}",))
            try:
                manifest = _safe_yaml_load(manifest_path)
            except ReferencePackError as exc:
                return ValidationReport((str(exc),))
            if not isinstance(manifest, Mapping):
                return ValidationReport(("manifest.yaml must contain a mapping",))
        errors = self._validate_manifest(root, manifest)
        if errors:
            return ValidationReport(tuple(errors))
        file_entries = tuple(
            ReferenceFile(
                str(item["path"]),
                str(item["sha256"]),
                str(item.get("kind", "supporting")),
                bool(item.get("required", True)),
            )
            for item in manifest["files"]
        )
        errors.extend(self._validate_files(root, manifest, file_entries))
        errors.extend(self._validate_references(root, manifest, file_entries))
        errors.extend(self._validate_templates(root, manifest))
        errors.extend(self._validate_ontology_and_rubrics(root, manifest))
        warnings: list[str] = []
        if not errors:
            pack = ReferencePack(root.resolve(), manifest, file_entries)
            resolution = resolve_precedence(pack, context)
            errors.extend(resolution.errors)
        return ValidationReport(tuple(errors), tuple(warnings), {"file_count": len(file_entries)})

    def _validate_manifest(self, root: Path, manifest: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        required = (
            "pack_id",
            "version",
            "description",
            "owner",
            "status",
            "effective_from",
            "supported_document_types",
            "precedence",
            "files",
        )
        for key in required:
            if key not in manifest:
                errors.append(f"manifest missing required field: {key}")
        if errors:
            return errors
        if not isinstance(manifest.get("pack_id"), str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_-]{2,80}", str(manifest["pack_id"])
        ):
            errors.append("manifest pack_id must be a stable identifier")
        if not isinstance(manifest.get("version"), str) or not re.fullmatch(
            r"\d+\.\d+\.\d+", str(manifest["version"])
        ):
            errors.append("manifest version must be semantic MAJOR.MINOR.PATCH")
        if manifest.get("status") not in _ALLOWED_STATUS:
            errors.append(f"manifest status must be one of {sorted(_ALLOWED_STATUS)}")
        if _as_date(manifest.get("effective_from")) is None:
            errors.append("manifest effective_from must be an ISO date")
        effective_to = manifest.get("effective_to")
        if effective_to not in (None, "") and _as_date(effective_to) is None:
            errors.append("manifest effective_to must be an ISO date or null")
        if not isinstance(manifest.get("owner"), Mapping):
            errors.append("manifest owner must be a mapping")
        supported = manifest.get("supported_document_types")
        if not isinstance(supported, Mapping) or not supported:
            errors.append("manifest supported_document_types must be a non-empty mapping")
        precedence = manifest.get("precedence")
        if not isinstance(precedence, Mapping):
            errors.append("manifest precedence must be a mapping")
        else:
            order = precedence.get("order")
            if not isinstance(order, Sequence) or isinstance(order, (str, bytes)):
                errors.append("manifest precedence.order must be a list")
            else:
                order_values = [str(item) for item in order]
                if len(order_values) != len(set(order_values)):
                    errors.append("manifest precedence.order contains duplicate levels")
                missing_levels = {"policy", "standard", "template", "style_guide", "source"} - set(
                    order_values
                )
                if missing_levels:
                    errors.append(
                        f"manifest precedence.order missing levels: {sorted(missing_levels)}"
                    )
                unknown = set(order_values) - set(_ALLOWED_PRECEDENCE)
                if unknown:
                    errors.append(
                        f"manifest precedence.order has invalid levels: {sorted(unknown)}"
                    )
            policy = precedence.get("conflict_policy")
            if not isinstance(policy, Mapping):
                errors.append("manifest precedence.conflict_policy must be a mapping")
            elif policy.get("same_precedence") != "error":
                errors.append("manifest precedence same_precedence policy must be error")
        files = manifest.get("files")
        if not isinstance(files, Sequence) or isinstance(files, (str, bytes)) or not files:
            errors.append("manifest files must be a non-empty list")
        else:
            seen: set[str] = set()
            for index, entry in enumerate(files):
                if not isinstance(entry, Mapping):
                    errors.append(f"manifest files[{index}] must be a mapping")
                    continue
                path = entry.get("path")
                if not isinstance(path, str):
                    errors.append(f"manifest files[{index}] path must be a string")
                    continue
                try:
                    _safe_relative(root, path)
                except (ReferencePackError, TypeError) as exc:
                    errors.append(str(exc))
                if path in seen:
                    errors.append(f"manifest files contains duplicate path: {path}")
                seen.add(str(path))
                digest = entry.get("sha256")
                if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
                    errors.append(f"manifest files[{index}] missing valid sha256 digest: {path}")
        return errors

    def _validate_files(
        self, root: Path, manifest: Mapping[str, Any], entries: Sequence[ReferenceFile]
    ) -> list[str]:
        errors: list[str] = []
        listed = {entry.path for entry in entries}
        for entry in entries:
            try:
                path = _safe_relative(root, entry.path)
            except ReferencePackError as exc:
                errors.append(str(exc))
                continue
            if not path.is_file():
                errors.append(f"missing referenced file: {entry.path}")
                continue
            actual = _sha256_file(path)
            if actual != entry.sha256:
                errors.append(
                    f"digest mismatch for {entry.path}: expected {entry.sha256}, got {actual}"
                )
        discovered = {
            path.relative_to(root.resolve()).as_posix()
            for path in root.resolve().rglob("*")
            if path.is_file()
            and path.name != "manifest.yaml"
            and ".git" not in path.parts
            and path.name != ".DS_Store"
        }
        unexpected = sorted(discovered - listed)
        if unexpected:
            errors.append(f"unlisted files in reference pack: {', '.join(unexpected)}")
        pack_payload = [
            {"path": entry.path, "sha256": entry.sha256}
            for entry in sorted(entries, key=lambda item: item.path)
        ]
        actual_pack_digest = _sha256_bytes(_canonical_json(pack_payload))
        if manifest.get("pack_sha256") != actual_pack_digest:
            errors.append(
                f"pack_sha256 mismatch: expected {manifest.get('pack_sha256')}, got {actual_pack_digest}"
            )
        manifest_for_digest = {
            key: value
            for key, value in manifest.items()
            if key not in {"manifest_sha256", "pack_sha256"}
        }
        actual_manifest_digest = _sha256_bytes(_canonical_json(manifest_for_digest))
        if manifest.get("manifest_sha256") != actual_manifest_digest:
            errors.append("manifest_sha256 mismatch")
        return errors

    def _validate_references(
        self, root: Path, manifest: Mapping[str, Any], entries: Sequence[ReferenceFile]
    ) -> list[str]:
        errors: list[str] = []
        listed = {entry.path for entry in entries}
        for field in ("glossary", "style_guide"):
            path = manifest.get(field)
            if not isinstance(path, str) or path not in listed:
                errors.append(f"unresolved manifest {field} mapping: {path}")
        ontology = manifest.get("ontology", {})
        if isinstance(ontology, Mapping):
            for field in ("entity_types", "relationship_types", "id_patterns", "controlled_terms"):
                path = ontology.get(field)
                if not isinstance(path, str) or path not in listed:
                    errors.append(f"unresolved ontology {field} mapping: {path}")
        rubrics = manifest.get("rubrics", {})
        if isinstance(rubrics, Mapping):
            for field, path in rubrics.items():
                if not isinstance(path, str) or path not in listed:
                    errors.append(f"unresolved rubric {field} mapping: {path}")
        supported = manifest.get("supported_document_types", {})
        if isinstance(supported, Mapping):
            for document_type, entry in supported.items():
                if not isinstance(entry, Mapping):
                    errors.append(f"supported document type {document_type} must be a mapping")
                    continue
                for field in ("template", "requirements", "example"):
                    path = entry.get(field)
                    if not isinstance(path, str) or path not in listed:
                        errors.append(f"unresolved {document_type} {field} mapping: {path}")
        sources = manifest.get("context_sources", ())
        source_ids: set[str] = set()
        if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
            errors.append("manifest context_sources must be a list")
        else:
            for source in sources:
                if not isinstance(source, Mapping):
                    errors.append("context_sources entries must be mappings")
                    continue
                source_id = str(source.get("reference_id", ""))
                if not _ID_RE.fullmatch(source_id):
                    errors.append(f"invalid context reference_id: {source_id}")
                if source_id in source_ids:
                    errors.append(f"duplicate context reference_id: {source_id}")
                source_ids.add(source_id)
                if source.get("path") not in listed:
                    errors.append(f"unresolved context source mapping: {source.get('path')}")
                if source.get("kind") not in _ALLOWED_PRECEDENCE:
                    errors.append(f"invalid context source precedence kind: {source.get('kind')}")
        for conflict in manifest.get("conflicts", ()):
            if not isinstance(conflict, Mapping):
                errors.append("conflicts entries must be mappings")
                continue
            if conflict.get("resolution") not in {"higher_precedence_wins", "surface_both"}:
                errors.append(
                    f"invalid precedence conflict resolution: {conflict.get('resolution')}"
                )
            for side in ("left", "right"):
                if conflict.get(side) not in source_ids:
                    errors.append(
                        f"unresolved precedence conflict {conflict.get('conflict_id')}: {conflict.get(side)}"
                    )
        return errors

    def _validate_templates(self, root: Path, manifest: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        supported = manifest.get("supported_document_types", {})
        if not isinstance(supported, Mapping):
            return errors
        for document_type, entry in supported.items():
            if not isinstance(entry, Mapping):
                continue
            try:
                template_path = _safe_relative(root, str(entry.get("template")))
                requirements_path = _safe_relative(root, str(entry.get("requirements")))
                example_path = _safe_relative(root, str(entry.get("example")))
            except ReferencePackError as exc:
                errors.append(str(exc))
                continue
            if (
                not template_path.is_file()
                or not requirements_path.is_file()
                or not example_path.is_file()
            ):
                continue
            try:
                requirements = _safe_yaml_load(requirements_path)
            except ReferencePackError as exc:
                errors.append(str(exc))
                continue
            if not isinstance(requirements, Mapping):
                errors.append(f"{document_type} requirements must be a mapping")
                continue
            sections = requirements.get("sections")
            if (
                not isinstance(sections, Sequence)
                or isinstance(sections, (str, bytes))
                or not sections
            ):
                errors.append(f"{document_type} requirements must define sections")
                continue
            template = template_path.read_text(encoding="utf-8")
            if not template.lstrip().startswith("---"):
                errors.append(f"{document_type} template must have YAML front matter")
            section_ids: set[str] = set()
            headings = {
                match.group(1).strip()
                for match in re.finditer(r"^#{1,6}\s+(.+?)\s*$", template, re.MULTILINE)
            }
            for section in sections:
                if not isinstance(section, Mapping):
                    errors.append(f"{document_type} requirements section must be a mapping")
                    continue
                section_id = str(section.get("id", ""))
                if not _ID_RE.fullmatch(section_id):
                    errors.append(f"{document_type} has invalid section ID: {section_id}")
                if section_id in section_ids:
                    errors.append(f"{document_type} has duplicate section ID: {section_id}")
                section_ids.add(section_id)
                heading = str(section.get("heading", ""))
                if heading not in headings:
                    errors.append(
                        f"{document_type} section heading not found in template: {heading}"
                    )
                criteria = section.get("rubric_criteria")
                if (
                    not isinstance(criteria, Sequence)
                    or isinstance(criteria, (str, bytes))
                    or not criteria
                ):
                    errors.append(f"{document_type} section has no rubric mapping: {section_id}")
            table_ids: set[str] = set()
            for table in requirements.get("tables", ()):
                if not isinstance(table, Mapping):
                    errors.append(f"{document_type} table requirement must be a mapping")
                    continue
                table_id = str(table.get("id", ""))
                if not _ID_RE.fullmatch(table_id) or table_id in table_ids:
                    errors.append(f"{document_type} invalid or duplicate table ID: {table_id}")
                table_ids.add(table_id)
                if table.get("section_id") not in section_ids:
                    errors.append(
                        f"{document_type} table maps to unresolved section: {table.get('section_id')}"
                    )
                columns = table.get("columns")
                if (
                    not isinstance(columns, Sequence)
                    or isinstance(columns, (str, bytes))
                    or not columns
                ):
                    errors.append(f"{document_type} table has no columns: {table_id}")
                if not table.get("rubric_criteria"):
                    errors.append(f"{document_type} table has no rubric mapping: {table_id}")
            if "AUTHORING" not in template:
                errors.append(f"{document_type} template has no authoring instruction comments")
            for label, data in (
                ("empty", {}),
                ("populated", {"document": {"title": "Fictional render"}}),
            ):
                rendered = render_template(template_path, data)
                if "<!--" in rendered:
                    errors.append(f"{document_type} {label} rendering leaked an HTML comment")
                if "AUTHORING:" in rendered:
                    errors.append(
                        f"{document_type} {label} rendering leaked authoring instructions"
                    )
                if "{{" in rendered or "}}" in rendered:
                    errors.append(
                        f"{document_type} {label} rendering leaked a template placeholder"
                    )
        return errors

    def _validate_ontology_and_rubrics(self, root: Path, manifest: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        ontology = manifest.get("ontology", {})
        if not isinstance(ontology, Mapping):
            errors.append("manifest ontology must be a mapping")
        else:
            ontology_data: dict[str, Mapping[str, Any]] = {}
            for field in ("entity_types", "relationship_types", "id_patterns", "controlled_terms"):
                path = ontology.get(field)
                if not isinstance(path, str):
                    errors.append(f"manifest ontology missing path: {field}")
                    continue
                try:
                    data = _safe_yaml_load(_safe_relative(root, path))
                except ReferencePackError as exc:
                    errors.append(str(exc))
                    continue
                if not isinstance(data, Mapping):
                    errors.append(f"ontology file must contain a mapping: {path}")
                else:
                    ontology_data[field] = data
            entity_types = ontology_data.get("entity_types", {}).get("entity_types", ())
            entity_ids = {
                str(item.get("type_id"))
                for item in entity_types
                if isinstance(item, Mapping) and item.get("type_id")
            }
            errors.extend(self._duplicate_list_ids(entity_types, "type_id", "entity_types.yaml"))
            relationships = ontology_data.get("relationship_types", {}).get(
                "relationship_types", ()
            )
            errors.extend(
                self._validate_relationships(relationships, entity_ids, "relationship_types.yaml")
            )
            patterns = ontology_data.get("id_patterns", {}).get("patterns", {})
            if isinstance(patterns, Mapping):
                unknown_pattern_types = sorted(set(str(item) for item in patterns) - entity_ids)
                if unknown_pattern_types:
                    errors.append(f"id_patterns has unknown entity types: {unknown_pattern_types}")
        rubrics = manifest.get("rubrics", {})
        if not isinstance(rubrics, Mapping):
            errors.append("manifest rubrics must be a mapping")
            return errors
        common_path = rubrics.get("common")
        try:
            common = _safe_yaml_load(_safe_relative(root, str(common_path)))
        except ReferencePackError as exc:
            errors.append(str(exc))
            return errors
        common_ids = self._criterion_ids(common)
        if not common_ids:
            errors.append("common rubric defines no criteria")
        if isinstance(common, Mapping):
            errors.extend(
                self._duplicate_list_ids(common.get("criteria"), "criterion_id", "common rubric")
            )
        for document_type in manifest.get("supported_document_types", {}):
            path = rubrics.get(document_type)
            if not isinstance(path, str):
                errors.append(f"missing rubric mapping for document type: {document_type}")
                continue
            try:
                rubric = _safe_yaml_load(_safe_relative(root, path))
            except ReferencePackError as exc:
                errors.append(str(exc))
                continue
            criterion_ids = common_ids | self._criterion_ids(rubric)
            if isinstance(rubric, Mapping):
                errors.extend(
                    self._duplicate_list_ids(
                        rubric.get("criteria"), "criterion_id", f"{document_type} rubric"
                    )
                )
            if not isinstance(rubric, Mapping) or rubric.get("document_type") != document_type:
                errors.append(f"rubric document_type mismatch: {document_type}")
            supported_entry = manifest["supported_document_types"].get(document_type, {})
            requirements_path = (
                supported_entry.get("requirements")
                if isinstance(supported_entry, Mapping)
                else None
            )
            try:
                requirements = _safe_yaml_load(_safe_relative(root, str(requirements_path)))
            except ReferencePackError as exc:
                errors.append(str(exc))
                requirements = {}
            requirement_ids: set[str] = set()
            used_criteria: set[str] = set()
            if isinstance(requirements, Mapping):
                for section in requirements.get("sections", ()):
                    if isinstance(section, Mapping):
                        requirement_ids.add(str(section.get("id")))
                        used_criteria.update(
                            str(item) for item in section.get("rubric_criteria", ())
                        )
                for table in requirements.get("tables", ()):
                    if isinstance(table, Mapping):
                        requirement_ids.add(str(table.get("id")))
                        used_criteria.update(str(item) for item in table.get("rubric_criteria", ()))
            if not used_criteria.issubset(criterion_ids):
                errors.append(
                    f"{document_type} requirements contain unresolved rubric criteria: {sorted(used_criteria - criterion_ids)}"
                )
            mapped_ids: set[str] = set()
            for mapping in (
                rubric.get("template_mappings", ()) if isinstance(rubric, Mapping) else ()
            ):
                if not isinstance(mapping, Mapping):
                    errors.append(
                        f"{document_type} rubric template_mappings entries must be mappings"
                    )
                    continue
                if not mapping.get("requirement_id"):
                    errors.append(f"{document_type} rubric mapping missing requirement_id")
                    continue
                requirement_id = str(mapping["requirement_id"])
                mapped_ids.add(requirement_id)
                if requirement_id not in requirement_ids:
                    errors.append(f"unresolved rubric/template mapping: {requirement_id}")
                for criterion_id in mapping.get("criterion_ids", ()):
                    if criterion_id not in criterion_ids:
                        errors.append(f"unresolved rubric criterion mapping: {criterion_id}")
            missing_mappings = sorted(requirement_ids - mapped_ids)
            if missing_mappings:
                errors.append(
                    f"{document_type} requirements missing rubric mappings: {missing_mappings}"
                )
        return errors

    @staticmethod
    def _duplicate_list_ids(value: Any, key: str, label: str) -> list[str]:
        if not isinstance(value, list):
            return [f"{label} must define a list of objects"]
        seen: set[str] = set()
        errors: list[str] = []
        for item in value:
            if not isinstance(item, Mapping) or not item.get(key):
                errors.append(f"{label} entry missing {key}")
                continue
            identifier = str(item[key])
            if identifier in seen:
                errors.append(f"duplicate ontology ID in {label}: {identifier}")
            seen.add(identifier)
        return errors

    @staticmethod
    def _validate_relationships(relationships: Any, entity_ids: set[str], label: str) -> list[str]:
        errors = ReferencePackValidator._duplicate_list_ids(relationships, "relationship_id", label)
        if not isinstance(relationships, list):
            return errors
        allowed_layers = {"authoritative", "governed", "extracted", "retrieval"}
        for relationship in relationships:
            if not isinstance(relationship, Mapping):
                continue
            relationship_id = relationship.get("relationship_id", "")
            if relationship_id == "RELATED_TO":
                errors.append("generic RELATED_TO relationship is not allowed")
            if relationship.get("layer") not in allowed_layers:
                errors.append(
                    f"invalid relationship layer for {relationship_id}: {relationship.get('layer')}"
                )
            for endpoint in ("source_types", "target_types"):
                values = relationship.get(endpoint)
                if not isinstance(values, list):
                    errors.append(f"{label} {relationship_id} missing {endpoint}")
                    continue
                unknown = sorted(set(str(item) for item in values) - entity_ids)
                if unknown:
                    errors.append(f"{label} {relationship_id} has unknown {endpoint}: {unknown}")
        return errors

    @staticmethod
    def _criterion_ids(rubric: Any) -> set[str]:
        if not isinstance(rubric, Mapping):
            return set()
        result: set[str] = set()
        for criterion in rubric.get("criteria", ()):
            if isinstance(criterion, Mapping) and criterion.get("criterion_id"):
                result.add(str(criterion["criterion_id"]))
        for dimension in rubric.get("dimensions", ()):
            if isinstance(dimension, Mapping):
                for criterion in dimension.get("criteria", ()):
                    if isinstance(criterion, Mapping) and criterion.get("criterion_id"):
                        result.add(str(criterion["criterion_id"]))
        return result


class EnterpriseReferencePackLoader:
    """Concrete loader implementing the M2 reference-pack workflow."""

    def __init__(self, *, validator: ReferencePackValidator | None = None) -> None:
        self.validator = validator or ReferencePackValidator()

    def load(
        self,
        location: Path,
        *,
        context: ApplicabilityContext | Mapping[str, Any] | None = None,
    ) -> ReferencePack:
        root = Path(location).resolve()
        report = self.validator.report(root, context=context)
        if not report.ok:
            raise ReferencePackValidationError(
                "Reference-pack validation failed: " + "; ".join(report.errors),
                errors=report.errors,
            )
        manifest = _safe_yaml_load(root / "manifest.yaml")
        entries = tuple(
            ReferenceFile(
                str(item["path"]),
                str(item["sha256"]),
                str(item.get("kind", "supporting")),
                bool(item.get("required", True)),
            )
            for item in manifest["files"]
        )
        return ReferencePack(root, manifest, entries)

    def validate(self, pack: Path | ReferencePack) -> Sequence[str]:
        return self.validator.validate(pack)

    def render(
        self,
        pack: ReferencePack,
        document_type: str,
        data: Mapping[str, Any] | None = None,
    ) -> str:
        return pack.render(document_type, data)


DefaultReferencePackLoader = EnterpriseReferencePackLoader


def load_reference_pack(
    location: Path,
    *,
    context: ApplicabilityContext | Mapping[str, Any] | None = None,
) -> ReferencePack:
    return EnterpriseReferencePackLoader().load(location, context=context)


def validate_reference_pack(location: Path) -> ValidationReport:
    return ReferencePackValidator().report(location)
