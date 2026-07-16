"""Filesystem artifact repository with content-addressed versions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from document_enhancer.contracts import ArtifactRepository
from document_enhancer.errors import ValidationError

from .atomic import atomic_promote, atomic_write_bytes, digest_bytes, digest_file
from .manifest import ArtifactRecord, RunManifest
from .paths import RunPaths


def _artifact_bytes(artifact: Any) -> bytes:
    if isinstance(artifact, bytes):
        return artifact
    if isinstance(artifact, str):
        return artifact.encode("utf-8")
    if isinstance(artifact, BaseModel):
        value = artifact.model_dump(mode="json")
    elif isinstance(artifact, Mapping):
        value = dict(artifact)
    else:
        value = artifact
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


class FilesystemArtifactRepository:
    """Store immutable artifact versions and atomically publish canonical paths."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()

    def paths(self, run_id: str) -> RunPaths:
        return RunPaths(self.root, run_id)

    def create_run(self, paths: RunPaths) -> None:
        paths.ensure_layout()

    def put(
        self, run_id: str, name: str, artifact: Any, *, stage: str = "unknown"
    ) -> ArtifactRecord:
        paths = self.paths(run_id)
        paths.ensure_layout()
        data = _artifact_bytes(artifact)
        digest = digest_bytes(data)
        canonical = paths.artifact_path(name)
        if canonical.exists() and digest_file(canonical) != digest:
            raise ValidationError(
                f"refusing to overwrite promoted artifact with different content: {name}"
            )
        version_dir = paths.versions_dir / name.replace("/", "__")
        version_dir.mkdir(parents=True, exist_ok=True)
        versioned = version_dir / f"{digest}.bin"
        if not versioned.exists():
            atomic_write_bytes(versioned, data)
        elif digest_file(versioned) != digest:
            raise ValidationError("content-addressed artifact version digest collision")
        if not canonical.exists():
            atomic_write_bytes(canonical, data)
        return ArtifactRecord(relative_path=name, digest=digest, size_bytes=len(data), stage=stage)

    def put_json(
        self, run_id: str, name: str, value: Any, *, stage: str = "unknown"
    ) -> ArtifactRecord:
        return self.put(run_id, name, value, stage=stage)

    def put_json_revision(
        self,
        run_id: str,
        name: str,
        value: Any,
        *,
        stage: str = "unknown",
        replace: bool = False,
        replace_deferred: bool = False,
    ) -> ArtifactRecord:
        """Write a content-addressed revision and atomically publish it.

        The ordinary :meth:`put_json` contract remains immutable. M3B uses this explicit
        revision path for selected views and independently revisable structure artifacts after a
        real result has passed validation; it also replaces M3A's visible ``deferred``
        reservations. A failed promotion leaves the prior canonical bytes untouched.
        """

        paths = self.paths(run_id)
        paths.ensure_layout()
        data = _artifact_bytes(value)
        digest = digest_bytes(data)
        canonical = paths.artifact_path(name)
        if canonical.exists() and digest_file(canonical) == digest:
            return ArtifactRecord(
                relative_path=name,
                digest=digest,
                size_bytes=len(data),
                stage=stage,
            )
        if canonical.exists() and not replace:
            if not replace_deferred:
                raise ValidationError(
                    f"refusing to overwrite promoted artifact with different content: {name}"
                )
            try:
                prior = json.loads(canonical.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValidationError(f"cannot inspect deferred reservation: {name}") from exc
            if not isinstance(prior, dict) or prior.get("status") != "deferred":
                raise ValidationError(f"refusing to replace non-deferred artifact: {name}")
        version_dir = paths.versions_dir / name.replace("/", "__")
        version_dir.mkdir(parents=True, exist_ok=True)
        versioned = version_dir / f"{digest}.bin"
        if not versioned.exists():
            atomic_write_bytes(versioned, data)
        elif digest_file(versioned) != digest:
            raise ValidationError("content-addressed artifact version digest collision")
        staged = paths.stage_path(name)
        atomic_write_bytes(staged, data)
        if not canonical.exists() or replace or replace_deferred:
            try:
                atomic_promote(staged, canonical)
            except Exception:
                staged.unlink(missing_ok=True)
                raise
        else:
            staged.unlink(missing_ok=True)
        return ArtifactRecord(relative_path=name, digest=digest, size_bytes=len(data), stage=stage)

    def get(self, run_id: str, name: str) -> bytes | None:
        path = self.paths(run_id).artifact_path(name)
        return path.read_bytes() if path.is_file() else None

    def get_json(self, run_id: str, name: str) -> Any | None:
        data = self.get(run_id, name)
        return json.loads(data) if data is not None else None

    def list(self, run_id: str) -> tuple[str, ...]:
        paths = self.paths(run_id)
        if not paths.run_dir.exists():
            return ()
        result: list[str] = []
        for path in paths.run_dir.rglob("*"):
            if not path.is_file() or ".versions" in path.parts or ".staging" in path.parts:
                continue
            result.append(path.relative_to(paths.run_dir).as_posix())
        return tuple(sorted(result))

    def stage(self, run_id: str, name: str, artifact: Any) -> Path:
        paths = self.paths(run_id)
        paths.ensure_layout()
        staged = paths.stage_path(name)
        atomic_write_bytes(staged, _artifact_bytes(artifact))
        return staged

    def promote(self, run_id: str, name: str) -> ArtifactRecord:
        paths = self.paths(run_id)
        staged = paths.stage_path(name)
        canonical = paths.artifact_path(name)
        if not staged.is_file():
            raise ValidationError(f"staged artifact does not exist: {name}")
        if canonical.exists() and digest_file(canonical) != digest_file(staged):
            raise ValidationError(f"refusing to overwrite promoted artifact: {name}")
        if not canonical.exists():
            atomic_promote(staged, canonical)
        else:
            staged.unlink(missing_ok=True)
        digest = digest_file(canonical)
        return ArtifactRecord(
            relative_path=name, digest=digest, size_bytes=canonical.stat().st_size, stage="promote"
        )

    def save_manifest(self, manifest: RunManifest) -> str:
        paths = self.paths(manifest.run_id)
        paths.ensure_layout()
        return manifest.save(paths.manifest)


FileSystemArtifactRepository = FilesystemArtifactRepository


__all__ = ["ArtifactRepository", "FileSystemArtifactRepository", "FilesystemArtifactRepository"]
