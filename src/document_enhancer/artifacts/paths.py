"""Content-addressed run and artifact paths."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from document_enhancer.errors import ValidationError

_SAFE_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")


def content_addressed_run_id(source_digest: str, *, configuration_digest: str | None = None) -> str:
    """Return a deterministic run ID containing the source content address."""

    if not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        raise ValidationError("source_digest must be a lowercase SHA-256 digest")
    suffix = f"-{configuration_digest[:16]}" if configuration_digest else ""
    if configuration_digest and not re.fullmatch(r"[0-9a-f]{64}", configuration_digest):
        raise ValidationError("configuration_digest must be a lowercase SHA-256 digest")
    return f"run-{source_digest[:32]}{suffix}"


@dataclass(frozen=True)
class RunPaths:
    """Safe paths for one immutable run namespace."""

    root: Path
    run_id: str

    def __post_init__(self) -> None:
        if not _SAFE_RUN_ID.fullmatch(self.run_id):
            raise ValidationError("run_id contains unsupported path characters")
        object.__setattr__(self, "root", self.root.expanduser())

    @classmethod
    def for_source(
        cls,
        root: Path,
        source_digest: str,
        *,
        configuration_digest: str | None = None,
        run_id: str | None = None,
    ) -> RunPaths:
        return cls(
            root=root,
            run_id=run_id
            or content_addressed_run_id(source_digest, configuration_digest=configuration_digest),
        )

    @property
    def run_dir(self) -> Path:
        return self.root / self.run_id

    @property
    def manifest(self) -> Path:
        return self.run_dir / "manifest.json"

    @property
    def checkpoint_db(self) -> Path:
        return self.run_dir / "checkpoint.sqlite3"

    @property
    def versions_dir(self) -> Path:
        return self.run_dir / ".versions"

    def artifact_path(self, name: str) -> Path:
        """Resolve a relative artifact name under the run, rejecting traversal."""

        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or not name
            or "\\" in name
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ValidationError("artifact name must be a relative path without traversal")
        candidate = (self.run_dir / Path(*relative.parts)).resolve()
        run_dir = self.run_dir.resolve()
        if candidate != run_dir and run_dir not in candidate.parents:
            raise ValidationError("artifact path escapes the run directory")
        return candidate

    def stage_path(self, name: str) -> Path:
        return self.artifact_path(f".staging/{name}")

    def ensure_layout(self) -> None:
        for relative in (
            "source/assets",
            "references",
            "prompts/templates",
            "analysis",
            "clarification",
            "output",
            "audit",
            "export",
            "rag",
            "logs",
            ".versions",
            ".staging",
        ):
            self.artifact_path(relative).mkdir(parents=True, exist_ok=True)


__all__ = ["RunPaths", "content_addressed_run_id"]
