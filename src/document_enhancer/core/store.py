"""Atomic file-backed storage for the core document bundle."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from .layout import RUN_RECORD, SEAL
from .models import ArtifactRef, RunRecord


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RunStore:
    """Persist a run as named files and one compact JSON state manifest."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def run_path(self, run_id: str) -> Path:
        if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
            raise ValueError("invalid run id")
        return self.root / run_id

    def create_dir(self, run_id: str) -> Path:
        path = self.run_path(run_id)
        path.mkdir(parents=True, exist_ok=False)
        return path

    def save_run(self, record: RunRecord) -> None:
        path = self._safe_path(record.run_id, RUN_RECORD)
        self._atomic_write(path, (record.model_dump_json(indent=2) + "\n").encode("utf-8"))

    def load_run(self, run_id: str) -> RunRecord:
        path = self.run_path(run_id) / RUN_RECORD
        if not path.is_file():
            raise FileNotFoundError(f"run record not found: {run_id}")
        return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def write_bytes(
        self,
        run_id: str,
        relative_path: str,
        data: bytes,
        *,
        media_type: str = "application/octet-stream",
    ) -> ArtifactRef:
        path = self._safe_path(run_id, relative_path)
        seal = self.run_path(run_id) / SEAL
        if seal.is_file() and relative_path != SEAL:
            raise RuntimeError(f"run {run_id} is sealed; artifacts are immutable")
        self._atomic_write(path, data)
        return ArtifactRef(
            path=relative_path,
            sha256=sha256_bytes(data),
            size_bytes=len(data),
            media_type=media_type,
        )

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
        return self._safe_path(run_id, relative_path).read_text(encoding="utf-8")

    def read_bytes(self, run_id: str, relative_path: str) -> bytes:
        return self._safe_path(run_id, relative_path).read_bytes()

    @staticmethod
    def sha256(data: bytes) -> str:
        return sha256_bytes(data)

    def read_json(self, run_id: str, relative_path: str) -> Any:
        return json.loads(self.read_text(run_id, relative_path))

    def exists(self, run_id: str, relative_path: str) -> bool:
        return self._safe_path(run_id, relative_path).is_file()

    def _safe_path(self, run_id: str, relative_path: str) -> Path:
        root = self.run_path(run_id).resolve()
        path = (root / relative_path).resolve()
        if path != root and root not in path.parents:
            raise ValueError("artifact path escapes the run directory")
        return path

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
