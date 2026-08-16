"""Atomic file-backed storage for the core document bundle."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from .integrity import (
    DigestMismatchError,
    ResumeIdentity,
    guard_promotion_identity,
    verify_artifact,
    verify_registered_artifacts,
)
from .layout import RUN_RECORD, SEAL
from .models import ArtifactRef, RunRecord


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RunStore:
    """Persist a run as named files and one compact JSON state manifest."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        self._held_run_locks = threading.local()

    def run_path(self, run_id: str) -> Path:
        if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
            raise ValueError("invalid run id")
        return self.root / run_id

    def create_dir(self, run_id: str) -> Path:
        path = self.run_path(run_id)
        path.mkdir(parents=True, exist_ok=False)
        return path

    def save_run(self, record: RunRecord) -> None:
        with self._run_lock(record.run_id):
            self._save_run_unlocked(record)

    def save_run_if_current(
        self, record: RunRecord, expected_identity: ResumeIdentity
    ) -> RunRecord:
        """Compare the current identity and atomically save a guarded state update."""

        if record.run_id != expected_identity.run_id:
            raise ValueError("guarded run update must target the captured run")
        with self._run_lock(record.run_id):
            current = self._load_run_unlocked(record.run_id)
            guard_promotion_identity(expected_identity, current)
            self._save_run_unlocked(record)
        return record

    @contextmanager
    def locked_promotion(self, expected_identity: ResumeIdentity) -> Iterator[RunRecord]:
        """Hold the run lock after identity validation through a promotion block."""

        with self._run_lock(expected_identity.run_id):
            current = self._load_run_unlocked(expected_identity.run_id)
            guard_promotion_identity(expected_identity, current)
            yield current

    def load_run(self, run_id: str) -> RunRecord:
        with self._run_lock(run_id):
            return self._load_run_unlocked(run_id)

    def write_bytes(
        self,
        run_id: str,
        relative_path: str,
        data: bytes,
        *,
        media_type: str = "application/octet-stream",
    ) -> ArtifactRef:
        with self._run_lock(run_id):
            return self._write_bytes_unlocked(run_id, relative_path, data, media_type=media_type)

    def write_text(
        self,
        run_id: str,
        relative_path: str,
        text: str,
        *,
        media_type: str = "text/plain; charset=utf-8",
    ) -> ArtifactRef:
        return self.write_bytes(run_id, relative_path, text.encode("utf-8"), media_type=media_type)

    def write_json(self, run_id: str, relative_path: str, value: Any) -> ArtifactRef:
        text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n"
        return self.write_text(run_id, relative_path, text, media_type="application/json")

    def read_text(self, run_id: str, relative_path: str) -> str:
        with self._run_lock(run_id):
            return self._safe_path(run_id, relative_path).read_text(encoding="utf-8")

    def read_bytes(self, run_id: str, relative_path: str) -> bytes:
        with self._run_lock(run_id):
            return self._safe_path(run_id, relative_path).read_bytes()

    @staticmethod
    def sha256(data: bytes) -> str:
        return sha256_bytes(data)

    def read_json(self, run_id: str, relative_path: str) -> Any:
        return json.loads(self.read_text(run_id, relative_path))

    def verify_artifact(
        self,
        run_id: str,
        artifact: ArtifactRef | Mapping[str, object],
        *,
        key: str | None = None,
    ) -> ArtifactRef:
        """Verify one registered artifact against the bytes in this run."""

        with self._run_lock(run_id):
            return verify_artifact(self.run_path(run_id), artifact, key=key)

    def verify_registered_artifacts(
        self,
        run_id: str,
        artifacts: Mapping[str, ArtifactRef | Mapping[str, object]],
        *,
        required_keys: Iterable[str] = (),
    ) -> dict[str, ArtifactRef]:
        """Verify a run's registered artifact set before a consumer uses it."""

        with self._run_lock(run_id):
            return verify_registered_artifacts(
                self.run_path(run_id), artifacts, required_keys=required_keys
            )

    def read_verified_bytes(
        self,
        run_id: str,
        artifact: ArtifactRef | Mapping[str, object],
        *,
        key: str | None = None,
    ) -> bytes:
        """Read bytes only after verifying the registered size and digest."""

        with self._run_lock(run_id):
            reference = verify_artifact(self.run_path(run_id), artifact, key=key)
            path = self._safe_path(run_id, reference.path)
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise DigestMismatchError(
                    f"registered artifact changed while being read: {reference.path}",
                    details={"key": key, "path": reference.path},
                ) from exc
            if len(data) != reference.size_bytes or sha256_bytes(data) != reference.sha256:
                raise DigestMismatchError(
                    f"registered artifact changed while being read: {reference.path}",
                    details={"key": key, "path": reference.path},
                )
            return data

    def read_verified_text(
        self,
        run_id: str,
        artifact: ArtifactRef | Mapping[str, object],
        *,
        key: str | None = None,
    ) -> str:
        """Read a UTF-8 artifact only after its registered bytes are verified."""

        return self.read_verified_bytes(run_id, artifact, key=key).decode("utf-8")

    def read_verified_json(
        self,
        run_id: str,
        artifact: ArtifactRef | Mapping[str, object],
        *,
        key: str | None = None,
    ) -> Any:
        """Parse JSON only after its registered bytes are verified."""

        return json.loads(self.read_verified_text(run_id, artifact, key=key))

    def exists(self, run_id: str, relative_path: str) -> bool:
        with self._run_lock(run_id):
            return self._safe_path(run_id, relative_path).is_file()

    def _safe_path(self, run_id: str, relative_path: str) -> Path:
        relative = self._relative_path(relative_path)
        run_dir = self.run_path(run_id)
        if run_dir.is_symlink():
            raise ValueError(f"run path must not be a symlink: {run_id}")
        if not run_dir.is_dir():
            raise FileNotFoundError(f"run directory not found: {run_id}")
        root = run_dir.resolve()
        path = root / relative
        current = root
        for part in Path(relative).parts:
            current /= part
            if current.is_symlink():
                raise ValueError(f"artifact path must not contain a symlink: {relative_path}")
        if path == root or root not in path.parents:
            raise ValueError("artifact path escapes the run directory")
        return path

    def _load_run_unlocked(self, run_id: str) -> RunRecord:
        path = self._safe_path(run_id, RUN_RECORD)
        if not path.is_file():
            raise FileNotFoundError(f"run record not found: {run_id}")
        return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def _save_run_unlocked(self, record: RunRecord) -> None:
        path = self._safe_path(record.run_id, RUN_RECORD)
        self._atomic_write(path, (record.model_dump_json(indent=2) + "\n").encode("utf-8"))

    def _write_bytes_unlocked(
        self,
        run_id: str,
        relative_path: str,
        data: bytes,
        *,
        media_type: str,
    ) -> ArtifactRef:
        normalized = self._relative_path(relative_path)
        path = self._safe_path(run_id, normalized)
        seal = self._safe_path(run_id, SEAL)
        if seal.is_file() or seal.is_symlink():
            raise RuntimeError(f"run {run_id} is sealed; artifacts are immutable")
        self._atomic_write(path, data)
        return ArtifactRef(
            path=normalized,
            sha256=sha256_bytes(data),
            size_bytes=len(data),
            media_type=media_type,
        )

    @staticmethod
    def _relative_path(relative_path: str | Path) -> str:
        if not isinstance(relative_path, (str, Path)):
            raise ValueError("artifact path must be relative")
        raw = str(relative_path)
        path = Path(relative_path)
        if not raw.strip() or path.is_absolute() or any(part == ".." for part in path.parts):
            raise ValueError("artifact path is invalid or escapes the run directory")
        if not path.parts:
            raise ValueError("artifact path must name a file")
        return path.as_posix()

    @contextmanager
    def _run_lock(self, run_id: str) -> Iterator[None]:
        run_dir = self.run_path(run_id)
        if not run_dir.is_dir() or run_dir.is_symlink():
            raise FileNotFoundError(f"run directory not found: {run_id}")
        held = getattr(self._held_run_locks, "run_ids", None)
        if held is None:
            held = set()
            self._held_run_locks.run_ids = held
        with self._thread_lock:
            if run_id in held:
                yield
                return
            lock_path = run_dir / ".run.lock"
            with lock_path.open("a+b") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                held.add(run_id)
                try:
                    yield
                finally:
                    held.remove(run_id)
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temp_name).replace(path)
        except Exception:
            with suppress(FileNotFoundError):
                Path(temp_name).unlink()
            raise


def register_artifact(record: RunRecord, key: str, artifact: ArtifactRef) -> RunRecord:
    """Return a record with a new artifact reference and refreshed timestamp."""

    return record.model_copy(update={"artifacts": {**record.artifacts, key: artifact}})


__all__ = ["RunStore", "register_artifact", "sha256_bytes"]
