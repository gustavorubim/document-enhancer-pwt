"""Atomic filesystem writes and promotion primitives."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> str:
    """Write bytes through a same-directory temp file and atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        _fsync_directory(path.parent)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return digest_bytes(data)


def atomic_write_json(path: Path, value: Any, *, mode: int = 0o600) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    return atomic_write_bytes(path, data, mode=mode)


def atomic_promote(staged: Path, target: Path) -> None:
    """Promote a fully-written file; the target is never partially replaced."""

    target.parent.mkdir(parents=True, exist_ok=True)
    staged.replace(target)
    _fsync_directory(target.parent)


def atomic_promote_directory(staged: Path, target: Path) -> None:
    """Promote a staging directory only when no prior reviewed version exists."""

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite promoted artifact directory: {target}")
    staged.replace(target)
    _fsync_directory(target.parent)


__all__ = [
    "atomic_promote",
    "atomic_promote_directory",
    "atomic_write_bytes",
    "atomic_write_json",
    "digest_bytes",
    "digest_file",
]
