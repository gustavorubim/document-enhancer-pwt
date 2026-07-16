"""Run manifest and immutable stage/artifact records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from document_enhancer import __version__

from ..ingest.models import ExtractionWarning, RawDocument, StructureQualityReport, utc_now
from .atomic import atomic_write_json


class ManifestContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactRecord(ManifestContract):
    relative_path: str
    digest: str
    size_bytes: int = Field(ge=0)
    stage: str
    promoted: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class StageRecord(ManifestContract):
    stage: str
    status: Literal["pending", "running", "succeeded", "failed", "stale"]
    cache_key: str
    artifact_paths: tuple[str, ...] = ()
    artifact_digests: tuple[str, ...] = ()
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class RunManifest(ManifestContract):
    schema_version: str = "m3a.run-manifest.v1"
    application_version: str = __version__
    run_id: str
    status: Literal["created", "running", "waiting", "succeeded", "failed"] = "created"
    current_stage: str = "raw_ingest"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    source_path: str
    source_name: str
    media_type: str
    source_size_bytes: int = Field(ge=0)
    source_digest: str
    structure_mode: Literal["auto", "parser", "llm", "recover", "force", "off"] = "auto"
    parser_name: str = "unknown"
    parser_version: str = "unknown"
    extraction_warnings: tuple[ExtractionWarning, ...] = ()
    parser_outline_digest: str | None = None
    structure_quality: StructureQualityReport | None = None
    selected_view_digest: str | None = None
    structure_scan_digest: str | None = None
    structure_recovery_digest: str | None = None
    structure_validation_digest: str | None = None
    structure_call_manifests: tuple[dict[str, Any], ...] = ()
    structure_prompt_resolutions: tuple[dict[str, Any], ...] = ()
    artifacts: tuple[ArtifactRecord, ...] = ()
    stages: tuple[StageRecord, ...] = ()
    cache_keys: dict[str, str] = Field(default_factory=dict)
    failures: tuple[str, ...] = ()
    data_handling: Literal["local_first"] = "local_first"
    external_tracing: bool = False

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        raw: RawDocument,
        structure_mode: Literal["auto", "parser", "llm", "recover", "force", "off"] = "auto",
        quality: StructureQualityReport | None = None,
    ) -> RunManifest:
        return cls(
            run_id=run_id,
            source_path=str(raw.source_path),
            source_name=raw.source_name,
            media_type=raw.media_type,
            source_size_bytes=raw.size_bytes,
            source_digest=raw.source_digest,
            structure_mode=structure_mode,
            parser_name=raw.parser_name,
            parser_version=raw.parser_version,
            extraction_warnings=raw.warnings,
            structure_quality=quality,
        )

    def record_artifact(self, record: ArtifactRecord) -> RunManifest:
        retained = tuple(
            item for item in self.artifacts if item.relative_path != record.relative_path
        )
        return self.model_copy(update={"artifacts": retained + (record,), "updated_at": utc_now()})

    def record_stage(self, record: StageRecord) -> RunManifest:
        retained = tuple(item for item in self.stages if item.stage != record.stage)
        cache_keys = dict(self.cache_keys)
        cache_keys[record.stage] = record.cache_key
        return self.model_copy(
            update={
                "stages": retained + (record,),
                "cache_keys": cache_keys,
                "current_stage": record.stage,
                "updated_at": utc_now(),
            }
        )

    def with_status(self, status: Literal["created", "running", "waiting", "succeeded", "failed"]):
        return self.model_copy(update={"status": status, "updated_at": utc_now()})

    def with_structure(
        self, *, outline_digest: str, selected_view_digest: str, quality: StructureQualityReport
    ) -> RunManifest:
        return self.model_copy(
            update={
                "parser_outline_digest": outline_digest,
                "selected_view_digest": selected_view_digest,
                "structure_quality": quality,
                "updated_at": utc_now(),
            }
        )

    def with_structure_recovery(
        self,
        *,
        mode: Literal["auto", "parser", "recover", "force", "off"],
        scan_digest: str | None,
        recovery_digest: str | None,
        validation_digest: str,
        selected_view_digest: str,
        call_manifests: Sequence[Any] = (),
        prompt_resolutions: Sequence[Any] = (),
    ) -> RunManifest:
        """Attach M3B structure evidence without conflating parser and model artifacts."""

        def dump_items(items: Sequence[Any]) -> tuple[dict[str, Any], ...]:
            return tuple(
                item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
                for item in items
            )

        return self.model_copy(
            update={
                "structure_mode": mode,
                "structure_scan_digest": scan_digest,
                "structure_recovery_digest": recovery_digest,
                "structure_validation_digest": validation_digest,
                "selected_view_digest": selected_view_digest,
                "structure_call_manifests": dump_items(call_manifests),
                "structure_prompt_resolutions": dump_items(prompt_resolutions),
                "updated_at": utc_now(),
            }
        )

    def save(self, path: Path) -> str:
        return atomic_write_json(path, self.model_dump(mode="json"))

    @classmethod
    def load(cls, path: Path) -> RunManifest:
        import json

        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))


def create_run_manifest(
    *, run_id: str, raw: RawDocument, quality: StructureQualityReport | None = None
) -> RunManifest:
    return RunManifest.create(run_id=run_id, raw=raw, quality=quality)


__all__ = ["ArtifactRecord", "RunManifest", "StageRecord", "create_run_manifest"]
