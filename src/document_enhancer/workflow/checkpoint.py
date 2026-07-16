"""Durable M5 workflow checkpoints and idempotent side-effect receipts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from document_enhancer.artifacts.atomic import atomic_write_json
from document_enhancer.artifacts.checkpoint import CheckpointRecord, CheckpointStore
from document_enhancer.artifacts.paths import RunPaths

from .state import WorkflowSnapshot, WorkflowState


class SideEffectLedger:
    """Receipt table preventing duplicate non-model effects after interrupt re-execution."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_side_effects (
                    effect_key TEXT PRIMARY KEY,
                    payload_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def run_once(self, effect_key: str, payload: object, effect: Callable[[], None]) -> bool:
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload_digest FROM workflow_side_effects WHERE effect_key = ?",
                (effect_key,),
            ).fetchone()
            if row is not None:
                if row[0] == digest:
                    return False
                # A reviewer edit legitimately changes a validation report. Update the receipt
                # after applying the new content; identical re-execution remains a no-op.
                effect()
                connection.execute(
                    "UPDATE workflow_side_effects SET payload_digest = ?, created_at = ? WHERE effect_key = ?",
                    (digest, datetime.now(UTC).isoformat(), effect_key),
                )
                return True
            effect()
            connection.execute(
                "INSERT INTO workflow_side_effects(effect_key, payload_digest, created_at) VALUES (?, ?, ?)",
                (effect_key, digest, datetime.now(UTC).isoformat()),
            )
        return True

    def count(self, prefix: str = "") -> int:
        with sqlite3.connect(self.path) as connection:
            if prefix:
                return int(
                    connection.execute(
                        "SELECT COUNT(*) FROM workflow_side_effects WHERE effect_key LIKE ?",
                        (prefix + "%",),
                    ).fetchone()[0]
                )
            return int(
                connection.execute("SELECT COUNT(*) FROM workflow_side_effects").fetchone()[0]
            )


class WorkflowCheckpoint:
    """Filesystem state plus the existing M3 SQLite checkpoint store."""

    def __init__(self, paths: RunPaths) -> None:
        self.paths = paths
        self.paths.ensure_layout()
        self.checkpoints = CheckpointStore(paths.checkpoint_db)
        self.effects = SideEffectLedger(paths.checkpoint_db)
        self.state_path = paths.artifact_path("workflow-state.json")

    def save_state(self, state: Mapping[str, Any]) -> WorkflowSnapshot:
        snapshot = WorkflowSnapshot.from_state(state)
        atomic_write_json(self.state_path, snapshot.model_dump(mode="json"))
        return snapshot

    def load_state(self) -> WorkflowState:
        snapshot = WorkflowSnapshot.model_validate_json(self.state_path.read_text(encoding="utf-8"))
        return snapshot.to_state()

    def has_state(self) -> bool:
        return self.state_path.is_file()

    def record_stage(
        self,
        state: Mapping[str, Any],
        *,
        stage: str,
        cache_key: str,
        status: str,
        artifact_paths: tuple[str, ...] = (),
        artifact_digests: tuple[str, ...] = (),
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.checkpoints.save(
            CheckpointRecord(
                run_id=str(state.get("run_id", self.paths.run_id)),
                stage=stage,
                cache_key=cache_key,
                status=status,
                artifact_digest=artifact_digests[0] if artifact_digests else None,
                artifact_path=artifact_paths[0] if artifact_paths else None,
                payload={
                    "artifact_paths": artifact_paths,
                    "artifact_digests": artifact_digests,
                    **dict(payload or {}),
                },
            )
        )

    def side_effect_once(
        self, stage: str, effect_name: str, payload: object, effect: Callable[[], None]
    ) -> bool:
        return self.effects.run_once(f"{self.paths.run_id}:{stage}:{effect_name}", payload, effect)


__all__ = ["SideEffectLedger", "WorkflowCheckpoint"]
