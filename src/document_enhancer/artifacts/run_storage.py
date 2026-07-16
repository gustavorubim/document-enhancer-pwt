"""Durable M3A run storage for deterministic ingestion artifacts."""

from __future__ import annotations

from pathlib import Path

from document_enhancer.errors import ValidationError

from ..ingest.common import read_source, sha256_bytes
from ..ingest.models import NormalizedDocument, RawDocument
from .atomic import atomic_write_bytes
from .cache import CacheDependencyGraph, make_cache_key
from .checkpoint import CheckpointRecord, CheckpointStore, ReconciliationReport
from .manifest import ArtifactRecord, RunManifest, StageRecord
from .paths import RunPaths
from .repository import FilesystemArtifactRepository


class RunStorage:
    """Persist raw/outline/quality/selected-view artifacts independently and atomically."""

    def __init__(self, paths: RunPaths) -> None:
        self.paths = paths
        self.repository = FilesystemArtifactRepository(paths.root)
        self.checkpoints = CheckpointStore(paths.checkpoint_db)
        self.cache_graph = CacheDependencyGraph()

    @classmethod
    def for_source(
        cls,
        root: Path,
        raw: RawDocument,
        *,
        configuration_digest: str | None = None,
    ) -> RunStorage:
        return cls(
            RunPaths.for_source(
                root,
                raw.source_digest,
                configuration_digest=configuration_digest,
            )
        )

    def _write_stage_artifacts(
        self, *, stage: str, cache_key: str, artifacts: list[ArtifactRecord]
    ) -> None:
        paths = tuple(record.relative_path for record in artifacts)
        digests = tuple(record.digest for record in artifacts)
        self.checkpoints.save(
            CheckpointRecord(
                run_id=self.paths.run_id,
                stage=stage,
                cache_key=cache_key,
                status="succeeded",
                artifact_digest=digests[0] if digests else None,
                artifact_path=paths[0] if paths else None,
                payload={"artifact_paths": paths, "artifact_digests": digests},
            )
        )

    def persist_ingest(self, normalized: NormalizedDocument) -> RunManifest:
        raw = normalized.raw
        if raw.source_digest != sha256_bytes(
            read_source(raw.source_path, max_bytes=raw.size_bytes)
        ):
            raise ValidationError("source changed between parse and artifact promotion")
        self.paths.ensure_layout()
        source_suffix = raw.source_path.suffix.lower()
        original_name = f"source/original{source_suffix}"
        original_data = read_source(raw.source_path, max_bytes=raw.size_bytes)
        raw_record = self.repository.put_json(
            self.paths.run_id,
            "source/raw-blocks.json",
            {
                "source_digest": raw.source_digest,
                "blocks": [block.model_dump(mode="json") for block in raw.blocks],
            },
            stage="raw_ingest",
        )
        original_path = self.paths.artifact_path(original_name)
        original_digest = atomic_write_bytes(original_path, original_data)
        original_record = ArtifactRecord(
            relative_path=original_name,
            digest=original_digest,
            size_bytes=len(original_data),
            stage="raw_ingest",
        )
        warning_record = self.repository.put_json(
            self.paths.run_id,
            "source/extraction-warnings.json",
            [warning.model_dump(mode="json") for warning in raw.warnings],
            stage="raw_ingest",
        )
        inventory_record = self.repository.put_json(
            self.paths.run_id,
            "source/assets/inventory.json",
            [asset.model_dump(mode="json") for asset in normalized.assets],
            stage="normalize",
        )
        normalize_record = self.repository.put(
            self.paths.run_id,
            "source/normalized.md",
            normalized.normalized_markdown,
            stage="normalize",
        )
        outline_record = self.repository.put_json(
            self.paths.run_id,
            "source/parser-outline.json",
            normalized.parser_outline.model_dump(mode="json"),
            stage="structure_quality",
        )
        quality_record = self.repository.put_json(
            self.paths.run_id,
            "source/structure-quality.json",
            {
                **normalized.quality.model_dump(mode="json"),
                "routing": normalized.routing.model_dump(mode="json"),
            },
            stage="structure_quality",
        )
        selected_record = self.repository.put_json(
            self.paths.run_id,
            "source/selected-view.json",
            normalized.selected_view.model_dump(mode="json") if normalized.selected_view else {},
            stage="selected_view",
        )
        document_record = self.repository.put_json(
            self.paths.run_id,
            "source/document.json",
            normalized.model_dump(mode="json"),
            stage="normalize",
        )
        manifest = RunManifest.create(
            run_id=self.paths.run_id,
            raw=raw,
            quality=normalized.quality,
        ).with_structure(
            outline_digest=outline_record.digest,
            selected_view_digest=selected_record.digest,
            quality=normalized.quality,
        )
        raw_key = make_cache_key("raw_ingest", {"source_digest": raw.source_digest})
        normalize_key = make_cache_key(
            "normalize",
            {"document_digest": document_record.digest},
            dependencies={"raw_ingest": raw_key},
        )
        quality_key = make_cache_key(
            "structure_quality",
            {"outline_digest": outline_record.digest, "quality_digest": quality_record.digest},
            dependencies={"normalize": normalize_key},
        )
        selected_key = make_cache_key(
            "selected_view",
            {"selected_view_digest": selected_record.digest},
            dependencies={"structure_quality": quality_key},
        )
        manifest = manifest.record_stage(
            StageRecord(
                stage="raw_ingest",
                status="succeeded",
                cache_key=raw_key,
                artifact_paths=(
                    original_name,
                    raw_record.relative_path,
                    warning_record.relative_path,
                ),
                artifact_digests=(original_record.digest, raw_record.digest, warning_record.digest),
            )
        )
        manifest = manifest.record_stage(
            StageRecord(
                stage="normalize",
                status="succeeded",
                cache_key=normalize_key,
                artifact_paths=(
                    normalize_record.relative_path,
                    inventory_record.relative_path,
                    document_record.relative_path,
                ),
                artifact_digests=(
                    normalize_record.digest,
                    inventory_record.digest,
                    document_record.digest,
                ),
            )
        )
        manifest = manifest.record_stage(
            StageRecord(
                stage="structure_quality",
                status="succeeded",
                cache_key=quality_key,
                artifact_paths=(outline_record.relative_path, quality_record.relative_path),
                artifact_digests=(outline_record.digest, quality_record.digest),
            )
        )
        manifest = manifest.record_stage(
            StageRecord(
                stage="selected_view",
                status="succeeded",
                cache_key=selected_key,
                artifact_paths=(selected_record.relative_path,),
                artifact_digests=(selected_record.digest,),
            )
        ).with_status("succeeded")
        deferred_records = self.reserve_deferred_recovery(manifest)
        all_records = [
            original_record,
            raw_record,
            warning_record,
            inventory_record,
            normalize_record,
            document_record,
            outline_record,
            quality_record,
            selected_record,
            *deferred_records,
        ]
        for record in all_records:
            manifest = manifest.record_artifact(record)
        self._write_stage_artifacts(
            stage="raw_ingest",
            cache_key=raw_key,
            artifacts=[original_record, raw_record, warning_record],
        )
        self._write_stage_artifacts(
            stage="normalize",
            cache_key=normalize_key,
            artifacts=[normalize_record, inventory_record, document_record],
        )
        self._write_stage_artifacts(
            stage="structure_quality",
            cache_key=quality_key,
            artifacts=[outline_record, quality_record],
        )
        self._write_stage_artifacts(
            stage="selected_view", cache_key=selected_key, artifacts=[selected_record]
        )
        self.repository.save_manifest(manifest)
        return manifest

    def reserve_deferred_recovery(self, manifest: RunManifest) -> tuple[ArtifactRecord, ...]:
        """Reserve recovery filenames without writing fake model output."""

        payload = {
            "status": "deferred",
            "reason": "M3.11-M3.13 require the WT4 model gateway and WT11 prompt pack.",
            "source_digest": manifest.source_digest,
            "model_result": False,
        }
        scan = self.repository.put_json(
            self.paths.run_id, "source/structure-scan.json", payload, stage="deferred"
        )
        recovered = self.repository.put_json(
            self.paths.run_id, "source/recovered-outline.json", payload, stage="deferred"
        )
        return scan, recovered

    def reconcile(self, manifest: RunManifest | None = None) -> ReconciliationReport:
        manifest = manifest or RunManifest.load(self.paths.manifest)
        return self.checkpoints.reconcile(manifest, self.paths)


__all__ = ["RunStorage"]
