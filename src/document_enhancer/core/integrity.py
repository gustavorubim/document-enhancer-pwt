"""Fail-closed integrity contracts for draft promotion and sealed bundles.

This module deliberately does not write run state or decide workflow transitions.  It
provides the small, typed checks that those consumers must call before consuming a
waiting run, promoting a final artifact, or exposing a sealed bundle.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, cast

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from document_enhancer.errors import ValidationError

from .models import ArtifactRef, DecisionBundle, RunRecord

SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SHA256_RE = re.compile(SHA256_PATTERN)

# These names are the authoritative inputs to a sealed consumer.  A caller may
# require additional artifacts, but may not weaken this baseline.
REQUIRED_SEAL_ARTIFACT_KEYS = (
    "source.original",
    "output.final_markdown",
    "audit.report",
    "output.graph",
    "output.ontology",
)


class IntegrityError(ValidationError):
    """Base error for a typed, diagnosable integrity failure."""

    failure_code: ClassVar[str] = "integrity_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code or self.failure_code
        self.details = dict(details or {})
        detail = f"{self.code}: {message}"
        if self.details:
            detail += f" ({json.dumps(self.details, sort_keys=True, default=str)})"
        super().__init__(message, detail=detail)


class ApprovalRequiredError(IntegrityError):
    """Raised when the human gate is absent, false, or otherwise not explicit."""

    failure_code = "approval_required"


class ApprovalTypeError(IntegrityError):
    """Raised when the approval field is not a real boolean."""

    failure_code = "approval_type_invalid"


class ArtifactIntegrityError(IntegrityError):
    """Raised when an artifact reference cannot be safely verified."""

    failure_code = "artifact_integrity_error"


class DigestMismatchError(ArtifactIntegrityError):
    """Raised when a registered digest or size differs from the file on disk."""

    failure_code = "artifact_digest_mismatch"


class RecipeConfigurationMismatchError(IntegrityError):
    """Raised when a waiting run is resumed under different inputs."""

    failure_code = "recipe_configuration_mismatch"


class SealManifestError(IntegrityError):
    """Raised when a seal is incomplete, malformed, or internally inconsistent."""

    failure_code = "seal_manifest_invalid"


class ResumeIdentityError(IntegrityError):
    """Raised when a run changed between capture and a guarded operation."""

    failure_code = "resume_identity_mismatch"


class SealManifest(BaseModel):
    """Versioned, complete seal contract for downstream consumers.

    The manifest uses the semantic artifact keys already present in ``RunRecord``.
    Every value is a full ``ArtifactRef`` so a consumer can verify bytes and size,
    including the graph and ontology exports, without trusting a path-only list.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: Literal["core.seal.v2"] = "core.seal.v2"
    run_id: str = Field(min_length=1)
    source_digest: str = Field(pattern=SHA256_PATTERN)
    recipe_id: str = Field(min_length=1)
    recipe_digest: str = Field(pattern=SHA256_PATTERN)
    configuration_digest: str = Field(pattern=SHA256_PATTERN)
    final_digest: str = Field(pattern=SHA256_PATTERN)
    audit_digest: str = Field(pattern=SHA256_PATTERN)
    graph_digest: str = Field(pattern=SHA256_PATTERN)
    ontology_digest: str = Field(pattern=SHA256_PATTERN)
    artifacts: dict[str, ArtifactRef] = Field(min_length=1)
    approval_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    sealed: Literal[True] = True

    @property
    def artifact_paths(self) -> tuple[str, ...]:
        """Return the registered paths in deterministic key order."""

        return tuple(self.artifacts[key].path for key in sorted(self.artifacts))


@dataclass(frozen=True, slots=True)
class ResumeIdentity:
    """Compare-and-verify token for resume and promotion operations.

    ``state_digest`` binds the run state, unresolved questions, and every registered
    artifact reference.  It is not a lock by itself: the store/runner must compare
    this token immediately before writing the next state or seal.
    """

    run_id: str
    status: str
    phase: str
    source_digest: str
    recipe_id: str
    recipe_digest: str
    configuration_digest: str
    artifact_manifest_digest: str
    state_digest: str
    artifact_keys: tuple[str, ...]

    @property
    def schema_version(self) -> str:
        return "core.resume-identity.v1"

    def model_dump(self) -> dict[str, object]:
        """Return a JSON-safe representation for diagnostics or state records."""

        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "status": self.status,
            "phase": self.phase,
            "source_digest": self.source_digest,
            "recipe_id": self.recipe_id,
            "recipe_digest": self.recipe_digest,
            "configuration_digest": self.configuration_digest,
            "artifact_manifest_digest": self.artifact_manifest_digest,
            "state_digest": self.state_digest,
            "artifact_keys": list(self.artifact_keys),
        }


def digest_bytes(data: bytes) -> str:
    """Return the canonical SHA-256 digest for bytes."""

    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON-compatible values without lossy coercion."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IntegrityError(
            "value cannot be represented by the canonical JSON digest primitive",
            code="non_canonical_value",
        ) from exc


def digest_json(value: object) -> str:
    """Return a deterministic digest for a JSON-compatible value."""

    return digest_bytes(canonical_json_bytes(value))


def digest_file(path: Path) -> str:
    """Hash one regular file, converting I/O failures to diagnosable errors."""

    try:
        with path.open("rb") as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            return digest.hexdigest()
    except FileNotFoundError as exc:
        raise ArtifactIntegrityError(
            f"artifact file is missing: {path}",
            code="artifact_missing",
            details={"path": str(path)},
        ) from exc
    except OSError as exc:
        raise ArtifactIntegrityError(
            f"artifact file cannot be read: {path}",
            code="artifact_unreadable",
            details={"path": str(path)},
        ) from exc


def register_artifact(
    root: Path,
    relative_path: str | Path,
    *,
    media_type: str = "application/octet-stream",
) -> ArtifactRef:
    """Create a digest-bearing reference for a file inside ``root``.

    Registration is read-only and rejects missing files, absolute paths, path traversal,
    and symlinks.  The returned reference is suitable for ``RunRecord.artifacts`` and
    ``SealManifest.artifacts``.
    """

    path = _resolve_artifact_path(root, relative_path)
    if _artifact_path_has_symlink(root, relative_path):
        raise ArtifactIntegrityError(
            f"artifact path must not be a symlink: {relative_path}",
            code="artifact_symlink",
            details={"path": str(relative_path)},
        )
    try:
        size_bytes = path.stat().st_size
    except FileNotFoundError as exc:
        raise ArtifactIntegrityError(
            f"artifact file is missing: {relative_path}",
            code="artifact_missing",
            details={"path": str(relative_path)},
        ) from exc
    except OSError as exc:
        raise ArtifactIntegrityError(
            f"artifact file cannot be inspected: {relative_path}",
            code="artifact_unreadable",
            details={"path": str(relative_path)},
        ) from exc
    if not path.is_file():
        raise ArtifactIntegrityError(
            f"artifact path is not a regular file: {relative_path}",
            code="artifact_not_file",
            details={"path": str(relative_path)},
        )
    return ArtifactRef(
        path=_relative_path(root, path),
        sha256=digest_file(path),
        size_bytes=size_bytes,
        media_type=media_type,
    )


def register_artifact_digest(
    root: Path,
    relative_path: str | Path,
    *,
    media_type: str = "application/octet-stream",
) -> ArtifactRef:
    """Named alias emphasizing that registration records a content digest."""

    return register_artifact(root, relative_path, media_type=media_type)


def artifact_ref_for_bytes(
    relative_path: str | Path,
    data: bytes,
    *,
    media_type: str = "application/octet-stream",
) -> ArtifactRef:
    """Create a reference before a caller writes the supplied bytes."""

    path = _relative_path_value(relative_path)
    return ArtifactRef(
        path=path,
        sha256=digest_bytes(data),
        size_bytes=len(data),
        media_type=media_type,
    )


def verify_artifact(
    root: Path,
    artifact: ArtifactRef | Mapping[str, object],
    *,
    key: str | None = None,
) -> ArtifactRef:
    """Verify one registered artifact's path, size, and SHA-256 digest."""

    reference = _coerce_artifact_ref(artifact, label=key or "artifact")
    path = _resolve_artifact_path(root, reference.path)
    if _artifact_path_has_symlink(root, reference.path):
        raise ArtifactIntegrityError(
            f"registered artifact is a symlink: {reference.path}",
            code="artifact_symlink",
            details={"key": key, "path": reference.path},
        )
    try:
        actual_size = path.stat().st_size
    except FileNotFoundError as exc:
        raise ArtifactIntegrityError(
            f"registered artifact is missing: {reference.path}",
            code="artifact_missing",
            details={"key": key, "path": reference.path},
        ) from exc
    except OSError as exc:
        raise ArtifactIntegrityError(
            f"registered artifact cannot be inspected: {reference.path}",
            code="artifact_unreadable",
            details={"key": key, "path": reference.path},
        ) from exc
    if not path.is_file():
        raise ArtifactIntegrityError(
            f"registered artifact is not a regular file: {reference.path}",
            code="artifact_not_file",
            details={"key": key, "path": reference.path},
        )
    if actual_size != reference.size_bytes:
        raise DigestMismatchError(
            f"artifact size does not match registration: {reference.path}",
            details={
                "key": key,
                "path": reference.path,
                "expected_size": reference.size_bytes,
                "actual_size": actual_size,
            },
        )
    actual_digest = digest_file(path)
    if not hmac.compare_digest(actual_digest, reference.sha256):
        raise DigestMismatchError(
            f"artifact digest does not match registration: {reference.path}",
            details={
                "key": key,
                "path": reference.path,
                "expected_digest": reference.sha256,
                "actual_digest": actual_digest,
            },
        )
    return reference


def verify_registered_artifacts(
    root: Path,
    artifacts: Mapping[str, ArtifactRef | Mapping[str, object]],
    *,
    required_keys: Iterable[str] = (),
) -> dict[str, ArtifactRef]:
    """Verify every registered artifact and return normalized references.

    This generic helper verifies the supplied registry as a whole.  Seal callers
    should use :func:`validate_seal_manifest`, which always requires the complete
    authoritative set; ``required_keys`` is available for intermediate stages.
    """

    if not isinstance(artifacts, Mapping):
        raise ArtifactIntegrityError("artifact registry must be a mapping", code="registry_invalid")
    normalized = {
        _nonempty_key(key, label="artifact key"): _coerce_artifact_ref(value, label=str(key))
        for key, value in artifacts.items()
    }
    _validate_unique_artifact_paths(normalized)
    required = _required_keys(required_keys, include_baseline=False)
    missing = sorted(set(required) - set(normalized))
    if missing:
        raise ArtifactIntegrityError(
            "artifact registry is missing required artifacts",
            code="artifact_registry_incomplete",
            details={"missing": missing},
        )
    return {key: verify_artifact(root, reference, key=key) for key, reference in normalized.items()}


def require_explicit_approval(decisions: Mapping[str, object] | DecisionBundle) -> None:
    """Require ``approve_rewrite`` to be present and exactly ``True``.

    A raw mapping is preferred at the YAML boundary: a missing key is distinguishable
    from an explicit false value.  A parsed ``DecisionBundle`` remains supported, but
    its default false value is still rejected.
    """

    if isinstance(decisions, DecisionBundle):
        approved: object = decisions.approve_rewrite
    elif isinstance(decisions, Mapping):
        if "approve_rewrite" not in decisions:
            raise ApprovalRequiredError("decisions are missing explicit approve_rewrite: true")
        approved = decisions["approve_rewrite"]
    else:
        raise ApprovalTypeError(
            "decision gate must be a mapping or DecisionBundle",
            details={"received_type": type(decisions).__name__},
        )
    if type(approved) is not bool:
        raise ApprovalTypeError(
            "approve_rewrite must be a boolean",
            details={"received_type": type(approved).__name__},
        )
    if approved is not True:
        raise ApprovalRequiredError("explicit approve_rewrite: true is required before revision")


def validate_recipe_configuration_digests(
    expected_recipe_digest: str,
    actual_recipe_digest: str,
    expected_configuration_digest: str,
    actual_configuration_digest: str,
    *,
    expected_recipe_id: str | None = None,
    actual_recipe_id: str | None = None,
) -> None:
    """Fail closed when the waiting run's recipe or configuration changed."""

    _validate_digest(expected_recipe_digest, "expected recipe digest")
    _validate_digest(actual_recipe_digest, "current recipe digest")
    _validate_digest(expected_configuration_digest, "expected configuration digest")
    _validate_digest(actual_configuration_digest, "current configuration digest")
    if expected_recipe_id is not None and (
        not isinstance(expected_recipe_id, str) or not expected_recipe_id.strip()
    ):
        raise RecipeConfigurationMismatchError("expected recipe id must be non-empty")
    if actual_recipe_id is not None and (
        not isinstance(actual_recipe_id, str) or not actual_recipe_id.strip()
    ):
        raise RecipeConfigurationMismatchError("current recipe id must be non-empty")
    if (
        expected_recipe_id is not None
        and actual_recipe_id is not None
        and expected_recipe_id != actual_recipe_id
    ):
        raise RecipeConfigurationMismatchError(
            "recipe id changed while resuming the run",
            details={
                "expected_recipe_id": expected_recipe_id,
                "actual_recipe_id": actual_recipe_id,
            },
        )
    if not hmac.compare_digest(expected_recipe_digest, actual_recipe_digest):
        raise RecipeConfigurationMismatchError(
            "recipe digest changed while resuming the run",
            details={
                "expected_recipe_digest": expected_recipe_digest,
                "actual_recipe_digest": actual_recipe_digest,
            },
        )
    if not hmac.compare_digest(expected_configuration_digest, actual_configuration_digest):
        raise RecipeConfigurationMismatchError(
            "configuration digest changed while resuming the run",
            details={
                "expected_configuration_digest": expected_configuration_digest,
                "actual_configuration_digest": actual_configuration_digest,
            },
        )


def build_seal_manifest(
    *,
    run_id: str,
    source_digest: str,
    recipe_id: str,
    recipe_digest: str,
    configuration_digest: str,
    artifacts: Mapping[str, ArtifactRef | Mapping[str, object]],
    approval_digest: str | None = None,
    artifact_root: Path | None = None,
    additional_required_keys: Iterable[str] = (),
) -> SealManifest:
    """Build and validate a complete v2 seal manifest from registered artifacts."""

    normalized = _normalize_artifacts(artifacts)
    required = _required_keys(additional_required_keys)
    missing = sorted(set(required) - set(normalized))
    if missing:
        raise SealManifestError(
            "cannot build a complete seal manifest with missing artifacts",
            details={"missing": missing},
        )
    try:
        manifest = SealManifest(
            run_id=run_id,
            source_digest=source_digest,
            recipe_id=recipe_id,
            recipe_digest=recipe_digest,
            configuration_digest=configuration_digest,
            final_digest=normalized["output.final_markdown"].sha256,
            audit_digest=normalized["audit.report"].sha256,
            graph_digest=normalized["output.graph"].sha256,
            ontology_digest=normalized["output.ontology"].sha256,
            artifacts=normalized,
            approval_digest=approval_digest,
        )
    except PydanticValidationError as exc:
        raise SealManifestError(
            "seal manifest fields are invalid",
            code="seal_schema_invalid",
            details={"errors": exc.errors(include_url=False)},
        ) from exc
    return validate_seal_manifest(
        manifest,
        artifact_root=artifact_root,
        additional_required_keys=additional_required_keys,
    )


def validate_seal_manifest(
    manifest: SealManifest | Mapping[str, object],
    *,
    artifact_root: Path | None = None,
    additional_required_keys: Iterable[str] = (),
    expected_identity: ResumeIdentity | None = None,
) -> SealManifest:
    """Validate a v2 seal's schema, complete artifact set, and optional file bytes."""

    parsed = _coerce_seal_manifest(manifest)
    if parsed.sealed is not True:
        raise SealManifestError("seal manifest is not marked sealed")
    _validate_digest(parsed.source_digest, "seal source digest")
    validate_recipe_configuration_digests(
        parsed.recipe_digest,
        parsed.recipe_digest,
        parsed.configuration_digest,
        parsed.configuration_digest,
    )
    normalized = _normalize_artifacts(parsed.artifacts)
    required = _required_keys(additional_required_keys)
    missing = sorted(set(required) - set(normalized))
    if missing:
        raise SealManifestError(
            "seal manifest is missing authoritative artifacts",
            details={"missing": missing},
        )
    _validate_unique_artifact_paths(normalized)
    expected_digests = {
        "source.original": parsed.source_digest,
        "output.final_markdown": parsed.final_digest,
        "audit.report": parsed.audit_digest,
        "output.graph": parsed.graph_digest,
        "output.ontology": parsed.ontology_digest,
    }
    for key, expected in expected_digests.items():
        actual = normalized[key].sha256
        if not hmac.compare_digest(expected, actual):
            raise SealManifestError(
                f"seal digest does not match registered artifact: {key}",
                code="seal_digest_mismatch",
                details={"key": key, "expected_digest": expected, "actual_digest": actual},
            )
    if expected_identity is not None:
        _validate_manifest_identity(parsed, expected_identity)
    if artifact_root is not None:
        verify_registered_artifacts(
            artifact_root,
            normalized,
            required_keys=additional_required_keys,
        )
    return parsed


def migrate_legacy_seal_manifest(
    legacy: Mapping[str, object],
    *,
    recipe_id: str,
    recipe_digest: str,
    configuration_digest: str,
    artifacts: Mapping[str, ArtifactRef | Mapping[str, object]],
    artifact_root: Path | None = None,
) -> SealManifest:
    """Explicitly upgrade a path-list seal; never used implicitly by validation.

    Legacy seals do not carry recipe/configuration identity or complete per-artifact
    references.  Callers must supply both identities and all authoritative refs.  A
    legacy manifest that lacks graph or ontology artifacts is therefore rejected and
    must be regenerated rather than silently treated as sealed.
    """

    if not isinstance(legacy, Mapping):
        raise SealManifestError("legacy seal must be a mapping", code="legacy_seal_invalid")
    if legacy.get("sealed") is not True:
        raise SealManifestError("legacy seal is not marked sealed", code="legacy_seal_unsealed")
    run_id = _required_string_value(legacy, "run_id", label="legacy seal")
    source_digest = _required_digest_value(legacy, "source_digest", label="legacy seal")
    final_digest = _required_digest_value(legacy, "final_digest", label="legacy seal")
    audit_digest = _required_digest_value(legacy, "audit_digest", label="legacy seal")
    paths = legacy.get("artifact_paths")
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise SealManifestError(
            "legacy seal must contain an artifact_paths list",
            code="legacy_seal_incomplete",
        )
    normalized = _normalize_artifacts(artifacts)
    missing_in_legacy: list[str] = []
    for key in REQUIRED_SEAL_ARTIFACT_KEYS:
        reference = normalized.get(key)
        if reference is None:
            missing_in_legacy.append(key)
        elif reference.path not in paths:
            missing_in_legacy.append(reference.path)
    if missing_in_legacy:
        raise SealManifestError(
            "legacy seal cannot be upgraded without every authoritative artifact",
            code="legacy_seal_incomplete",
            details={"missing": missing_in_legacy},
        )
    if normalized["source.original"].sha256 != source_digest:
        raise SealManifestError("legacy source digest does not match supplied artifact")
    if normalized["output.final_markdown"].sha256 != final_digest:
        raise SealManifestError("legacy final digest does not match supplied artifact")
    if normalized["audit.report"].sha256 != audit_digest:
        raise SealManifestError("legacy audit digest does not match supplied artifact")
    try:
        migrated = SealManifest(
            run_id=run_id,
            source_digest=source_digest,
            recipe_id=recipe_id,
            recipe_digest=recipe_digest,
            configuration_digest=configuration_digest,
            final_digest=final_digest,
            audit_digest=audit_digest,
            graph_digest=normalized["output.graph"].sha256,
            ontology_digest=normalized["output.ontology"].sha256,
            artifacts=normalized,
        )
    except PydanticValidationError as exc:
        raise SealManifestError(
            "migrated seal fields are invalid",
            code="seal_schema_invalid",
            details={"errors": exc.errors(include_url=False)},
        ) from exc
    return validate_seal_manifest(migrated, artifact_root=artifact_root)


def capture_resume_identity(record: RunRecord | Mapping[str, object]) -> ResumeIdentity:
    """Capture the state and artifact identity of a waiting or running record."""

    if isinstance(record, RunRecord):
        payload = record.model_dump(mode="json")
    elif isinstance(record, Mapping):
        payload = dict(record)
    else:
        raise ResumeIdentityError("run record must be a mapping")
    run_id = _required_string_value(payload, "run_id", label="run record")
    status = _required_string_value(payload, "status", label="run record")
    phase = _required_string_value(payload, "phase", label="run record")
    source_digest = _required_digest_value(payload, "source_digest", label="run record")
    recipe_id = _required_string_value(payload, "recipe", label="run record")
    recipe_digest = _required_digest_value(payload, "recipe_digest", label="run record")
    configuration_digest = _required_digest_value(
        payload, "configuration_digest", label="run record"
    )
    artifacts_value = payload.get("artifacts")
    if not isinstance(artifacts_value, Mapping):
        raise ResumeIdentityError("run record artifacts must be a mapping", code="identity_invalid")
    artifacts = _normalize_artifacts(
        cast(Mapping[str, ArtifactRef | Mapping[str, object]], artifacts_value)
    )
    _validate_unique_artifact_paths(artifacts)
    artifact_payload = {
        key: reference.model_dump(mode="json") for key, reference in sorted(artifacts.items())
    }
    artifact_manifest_digest = digest_json(artifact_payload)
    unresolved_value = payload.get("unresolved_question_ids", [])
    if not isinstance(unresolved_value, list) or not all(
        isinstance(item, str) for item in unresolved_value
    ):
        raise ResumeIdentityError(
            "run record unresolved_question_ids must be a list of strings",
            code="identity_invalid",
        )
    state_payload = {
        "run_id": run_id,
        "status": status,
        "phase": phase,
        "source_digest": source_digest,
        "recipe_id": recipe_id,
        "recipe_digest": recipe_digest,
        "configuration_digest": configuration_digest,
        "artifact_manifest_digest": artifact_manifest_digest,
        "unresolved_question_ids": list(unresolved_value),
    }
    return ResumeIdentity(
        run_id=run_id,
        status=status,
        phase=phase,
        source_digest=source_digest,
        recipe_id=recipe_id,
        recipe_digest=recipe_digest,
        configuration_digest=configuration_digest,
        artifact_manifest_digest=artifact_manifest_digest,
        state_digest=digest_json(state_payload),
        artifact_keys=tuple(sorted(artifacts)),
    )


def validate_resume_identity(
    expected: ResumeIdentity,
    current: ResumeIdentity | RunRecord | Mapping[str, object],
) -> ResumeIdentity:
    """Require the current run to equal a previously captured identity token."""

    actual = current if isinstance(current, ResumeIdentity) else capture_resume_identity(current)
    fields = (
        "run_id",
        "status",
        "phase",
        "source_digest",
        "recipe_id",
        "recipe_digest",
        "configuration_digest",
        "artifact_manifest_digest",
        "state_digest",
        "artifact_keys",
    )
    for field_name in fields:
        expected_value = getattr(expected, field_name)
        actual_value = getattr(actual, field_name)
        equal = (
            hmac.compare_digest(expected_value, actual_value)
            if isinstance(expected_value, str) and isinstance(actual_value, str)
            else expected_value == actual_value
        )
        if not equal:
            raise ResumeIdentityError(
                f"run identity changed before guarded operation: {field_name}",
                details={
                    "field": field_name,
                    "expected": expected_value,
                    "actual": actual_value,
                },
            )
    return actual


def guard_promotion_identity(
    expected: ResumeIdentity,
    current: ResumeIdentity | RunRecord | Mapping[str, object],
) -> ResumeIdentity:
    """Explicitly named alias for the final pre-promotion compare-and-verify call."""

    return validate_resume_identity(expected, current)


def _coerce_seal_manifest(value: SealManifest | Mapping[str, object]) -> SealManifest:
    if isinstance(value, SealManifest):
        return value
    if not isinstance(value, Mapping):
        raise SealManifestError("seal manifest must be a mapping", code="seal_schema_invalid")
    try:
        return SealManifest.model_validate(value, strict=True)
    except PydanticValidationError as exc:
        raise SealManifestError(
            "seal manifest does not match core.seal.v2",
            code="seal_schema_invalid",
            details={"errors": exc.errors(include_url=False)},
        ) from exc


def _normalize_artifacts(
    artifacts: Mapping[str, ArtifactRef | Mapping[str, object]],
) -> dict[str, ArtifactRef]:
    if not isinstance(artifacts, Mapping):
        raise SealManifestError(
            "artifact registry must be a mapping", code="artifact_registry_invalid"
        )
    normalized = {
        _nonempty_key(key, label="artifact key"): _coerce_artifact_ref(value, label=str(key))
        for key, value in artifacts.items()
    }
    _validate_unique_artifact_paths(normalized)
    return normalized


def _coerce_artifact_ref(value: object, *, label: str) -> ArtifactRef:
    if isinstance(value, ArtifactRef):
        reference = value
    else:
        try:
            reference = ArtifactRef.model_validate(value, strict=True)
        except PydanticValidationError as exc:
            raise ArtifactIntegrityError(
                f"artifact reference is invalid: {label}",
                code="artifact_reference_invalid",
                details={"key": label, "errors": exc.errors(include_url=False)},
            ) from exc
    _relative_path_value(reference.path)
    if not reference.media_type.strip():
        raise ArtifactIntegrityError(
            f"artifact media type is empty: {label}",
            code="artifact_reference_invalid",
        )
    return reference


def _validate_unique_artifact_paths(artifacts: Mapping[str, ArtifactRef]) -> None:
    paths: dict[str, str] = {}
    for key, reference in artifacts.items():
        path = _relative_path_value(reference.path)
        previous = paths.get(path)
        if previous is not None and previous != key:
            raise ArtifactIntegrityError(
                "multiple artifact keys refer to the same path",
                code="artifact_path_ambiguous",
                details={"path": path, "keys": [previous, key]},
            )
        paths[path] = key


def _validate_manifest_identity(manifest: SealManifest, expected: ResumeIdentity) -> None:
    comparisons = (
        ("run_id", manifest.run_id, expected.run_id),
        ("source_digest", manifest.source_digest, expected.source_digest),
        ("recipe_id", manifest.recipe_id, expected.recipe_id),
        ("recipe_digest", manifest.recipe_digest, expected.recipe_digest),
        ("configuration_digest", manifest.configuration_digest, expected.configuration_digest),
    )
    for field_name, actual, expected_value in comparisons:
        equal = hmac.compare_digest(actual, expected_value)
        if not equal:
            raise ResumeIdentityError(
                f"seal identity does not match captured run identity: {field_name}",
                details={"field": field_name, "expected": expected_value, "actual": actual},
            )


def _required_keys(additional: Iterable[str], *, include_baseline: bool = True) -> tuple[str, ...]:
    values = list(REQUIRED_SEAL_ARTIFACT_KEYS) if include_baseline else []
    for key in additional:
        if not isinstance(key, str) or not key.strip():
            raise IntegrityError("required artifact keys must be non-empty strings")
        if key not in values:
            values.append(key)
    return tuple(values)


def _validate_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise IntegrityError(
            f"{label} must be a lowercase SHA-256 digest",
            code="digest_invalid",
            details={"field": label},
        )
    return value


def _required_digest_value(payload: Mapping[str, object], key: str, *, label: str) -> str:
    if key not in payload:
        raise IntegrityError(
            f"{label} is missing required field {key!r}",
            code="identity_invalid",
            details={"field": key},
        )
    return _validate_digest(payload[key], f"{label} field {key!r}")


def _required_string_value(payload: Mapping[str, object], key: str, *, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError(
            f"{label} field {key!r} must be a non-empty string",
            code="identity_invalid",
            details={"field": key},
        )
    return value


def _nonempty_key(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError(f"{label} must be a non-empty string", code="key_invalid")
    return value


def _relative_path_value(value: str | Path) -> str:
    path = Path(value)
    invalid = (
        path.is_absolute()
        or not str(value).strip()
        or path in {Path(), Path("..")}
        or any(part == ".." for part in path.parts)
    )
    if invalid:
        raise ArtifactIntegrityError(
            f"artifact path must be relative and stay inside its bundle: {value}",
            code="artifact_path_invalid",
            details={"path": str(value)},
        )
    return path.as_posix()


def _resolve_artifact_path(root: Path, relative_path: str | Path) -> Path:
    path_value = _relative_path_value(relative_path)
    resolved_root = root.expanduser().resolve()
    candidate = (resolved_root / path_value).resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise ArtifactIntegrityError(
            f"artifact path escapes its bundle: {relative_path}",
            code="artifact_path_invalid",
            details={"path": str(relative_path), "root": str(resolved_root)},
        )
    return candidate


def _artifact_path_has_symlink(root: Path, relative_path: str | Path) -> bool:
    current = root.expanduser().resolve()
    for part in Path(_relative_path_value(relative_path)).parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.expanduser().resolve()).as_posix()
    except ValueError as exc:
        raise ArtifactIntegrityError(
            f"artifact path escapes its bundle: {path}",
            code="artifact_path_invalid",
        ) from exc


__all__ = [
    "ApprovalRequiredError",
    "ApprovalTypeError",
    "ArtifactIntegrityError",
    "DigestMismatchError",
    "IntegrityError",
    "REQUIRED_SEAL_ARTIFACT_KEYS",
    "RecipeConfigurationMismatchError",
    "ResumeIdentity",
    "ResumeIdentityError",
    "SealManifest",
    "SealManifestError",
    "artifact_ref_for_bytes",
    "build_seal_manifest",
    "canonical_json_bytes",
    "capture_resume_identity",
    "digest_bytes",
    "digest_file",
    "digest_json",
    "guard_promotion_identity",
    "migrate_legacy_seal_manifest",
    "register_artifact",
    "register_artifact_digest",
    "require_explicit_approval",
    "validate_recipe_configuration_digests",
    "validate_resume_identity",
    "validate_seal_manifest",
    "verify_artifact",
    "verify_registered_artifacts",
]
