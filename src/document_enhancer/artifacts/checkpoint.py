"""Local SQLite checkpointing and filesystem/manifest reconciliation."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .atomic import digest_file
from .manifest import RunManifest
from .paths import RunPaths


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CheckpointRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    stage: str
    cache_key: str
    status: str
    artifact_digest: str | None = None
    artifact_path: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=_now)


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    consistent: bool
    checked_stages: int = Field(ge=0)
    stale_stages: tuple[str, ...] = ()
    orphaned_checkpoints: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()


class CheckpointStore:
    """Small SQLite checkpoint store with explicit transaction boundaries."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    run_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    artifact_digest TEXT,
                    artifact_path TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, stage)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_checkpoints_cache ON checkpoints(run_id, cache_key)"
            )

    def save(self, record: CheckpointRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints
                    (run_id, stage, cache_key, status, artifact_digest, artifact_path, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, stage) DO UPDATE SET
                    cache_key=excluded.cache_key,
                    status=excluded.status,
                    artifact_digest=excluded.artifact_digest,
                    artifact_path=excluded.artifact_path,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record.run_id,
                    record.stage,
                    record.cache_key,
                    record.status,
                    record.artifact_digest,
                    record.artifact_path,
                    json.dumps(record.payload, ensure_ascii=False, sort_keys=True),
                    record.updated_at,
                ),
            )

    def get(self, run_id: str, stage: str) -> CheckpointRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM checkpoints WHERE run_id = ? AND stage = ?", (run_id, stage)
            ).fetchone()
        return self._record(row) if row else None

    def list(self, run_id: str) -> tuple[CheckpointRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM checkpoints WHERE run_id = ? ORDER BY stage", (run_id,)
            ).fetchall()
        return tuple(self._record(row) for row in rows)

    def delete(self, run_id: str, stage: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM checkpoints WHERE run_id = ? AND stage = ?", (run_id, stage)
            )

    @staticmethod
    def _record(row: sqlite3.Row) -> CheckpointRecord:
        return CheckpointRecord(
            run_id=row["run_id"],
            stage=row["stage"],
            cache_key=row["cache_key"],
            status=row["status"],
            artifact_digest=row["artifact_digest"],
            artifact_path=row["artifact_path"],
            payload=json.loads(row["payload_json"]),
            updated_at=row["updated_at"],
        )

    def reconcile(self, manifest: RunManifest, paths: RunPaths) -> ReconciliationReport:
        records = {record.stage: record for record in self.list(manifest.run_id)}
        stale: list[str] = []
        issues: list[str] = []
        manifest_stages = {stage.stage: stage for stage in manifest.stages}
        for stage_name, stage in manifest_stages.items():
            record = records.get(stage_name)
            if record is None:
                issues.append(f"missing_checkpoint:{stage_name}")
                continue
            valid = record.status == stage.status and record.cache_key == stage.cache_key
            for relative_path, expected_digest in zip(
                stage.artifact_paths, stage.artifact_digests, strict=False
            ):
                path = paths.artifact_path(relative_path)
                if not path.is_file() or digest_file(path) != expected_digest:
                    valid = False
                    issues.append(f"artifact_mismatch:{stage_name}:{relative_path}")
            if not valid:
                stale.append(stage_name)
                self.save(record.model_copy(update={"status": "stale", "updated_at": _now()}))
        orphaned = sorted(set(records) - set(manifest_stages))
        for stage_name in orphaned:
            self.save(
                records[stage_name].model_copy(update={"status": "stale", "updated_at": _now()})
            )
        return ReconciliationReport(
            run_id=manifest.run_id,
            consistent=not stale and not orphaned and not issues,
            checked_stages=len(manifest_stages),
            stale_stages=tuple(sorted(stale)),
            orphaned_checkpoints=tuple(orphaned),
            issues=tuple(issues),
        )


def reconcile_filesystem_and_manifest(
    manifest: RunManifest, paths: RunPaths, checkpoint_store: CheckpointStore
) -> ReconciliationReport:
    return checkpoint_store.reconcile(manifest, paths)


__all__ = [
    "CheckpointRecord",
    "CheckpointStore",
    "ReconciliationReport",
    "reconcile_filesystem_and_manifest",
]
