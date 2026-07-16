from __future__ import annotations

import json
from pathlib import Path

import pytest

from document_enhancer.artifacts.atomic import atomic_promote, atomic_write_bytes
from document_enhancer.artifacts.cache import CacheDependencyGraph, make_cache_key
from document_enhancer.artifacts.checkpoint import CheckpointRecord, CheckpointStore
from document_enhancer.artifacts.manifest import RunManifest, StageRecord
from document_enhancer.artifacts.paths import RunPaths, content_addressed_run_id
from document_enhancer.artifacts.repository import FilesystemArtifactRepository
from document_enhancer.artifacts.run_storage import RunStorage
from document_enhancer.errors import ValidationError
from document_enhancer.ingest.markdown import MarkdownParser
from document_enhancer.ingest.normalize import normalize_document


def test_content_addressed_paths_and_traversal_guards(tmp_path: Path) -> None:
    digest = "a" * 64
    run_id = content_addressed_run_id(digest)
    paths = RunPaths.for_source(tmp_path, digest)

    assert run_id == paths.run_id
    assert digest[:32] in str(paths.run_dir)
    assert paths.artifact_path("source/raw-blocks.json") == paths.run_dir / "source/raw-blocks.json"
    with pytest.raises(ValidationError):
        paths.artifact_path("../outside.json")
    with pytest.raises(ValidationError):
        RunPaths(tmp_path, "../escape")


def test_atomic_write_and_promotion_leave_no_partial_target(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    digest = atomic_write_bytes(target, b"first")
    assert target.read_bytes() == b"first"
    assert len(digest) == 64

    staged = tmp_path / "staged.json"
    atomic_write_bytes(staged, b"second")
    atomic_promote(staged, target)
    assert target.read_bytes() == b"second"
    assert not staged.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_repository_keeps_versioned_bytes_and_rejects_different_overwrite(tmp_path: Path) -> None:
    repo = FilesystemArtifactRepository(tmp_path / "runs")
    paths = RunPaths(tmp_path / "runs", "run-test")
    repo.create_run(paths)

    first = repo.put_json("run-test", "source/document.json", {"value": 1}, stage="normalize")
    assert repo.get_json("run-test", "source/document.json") == {"value": 1}
    assert first.digest
    assert list(repo.list("run-test")) == ["source/document.json"]
    with pytest.raises(ValidationError, match="overwrite"):
        repo.put_json("run-test", "source/document.json", {"value": 2}, stage="normalize")
    assert len(list((paths.versions_dir / "source__document.json").glob("*.bin"))) == 1


def test_cache_graph_changes_downstream_only() -> None:
    graph = CacheDependencyGraph()
    changed = graph.invalidated_by({"normalize"})
    assert changed == (
        "analysis",
        "audit",
        "export",
        "normalize",
        "rag_build",
        "rewrite",
        "selected_view",
        "structure_quality",
        "structure_recovery",
        "structure_scan",
    )
    assert make_cache_key("normalize", {"source": "a"}) != make_cache_key(
        "normalize", {"source": "b"}
    )


def test_checkpoint_reconciliation_marks_tampered_artifacts_stale(tmp_path: Path) -> None:
    repo = FilesystemArtifactRepository(tmp_path / "runs")
    paths = RunPaths(tmp_path / "runs", "run-checkpoint")
    repo.create_run(paths)
    record = repo.put_json("run-checkpoint", "source/raw.json", {"ok": True}, stage="raw_ingest")
    manifest = RunManifest(
        run_id="run-checkpoint",
        source_path="source.md",
        source_name="source.md",
        media_type="text/markdown",
        source_size_bytes=1,
        source_digest="a" * 64,
        stages=(
            StageRecord(
                stage="raw_ingest",
                status="succeeded",
                cache_key="cache",
                artifact_paths=(record.relative_path,),
                artifact_digests=(record.digest,),
            ),
        ),
    )
    checkpoints = CheckpointStore(paths.checkpoint_db)
    checkpoints.save(
        CheckpointRecord(
            run_id="run-checkpoint",
            stage="raw_ingest",
            status="succeeded",
            cache_key="cache",
            artifact_digest=record.digest,
            artifact_path=record.relative_path,
            payload={"artifact_paths": [record.relative_path]},
        )
    )
    paths.artifact_path(record.relative_path).write_bytes(b"tampered")

    report = checkpoints.reconcile(manifest, paths)

    assert report.consistent is False
    assert report.stale_stages == ("raw_ingest",)
    checkpoint = checkpoints.get("run-checkpoint", "raw_ingest")
    assert checkpoint is not None
    assert checkpoint.status == "stale"


def test_run_storage_persists_independent_m3a_artifacts_and_deferred_reservations(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Title\n\nBody with [link](https://example.com).\n", encoding="utf-8")
    raw = MarkdownParser().parse(source)
    normalized = normalize_document(raw)
    storage = RunStorage.for_source(tmp_path / "runs", raw)

    manifest = storage.persist_ingest(normalized)

    run_dir = storage.paths.run_dir
    for relative in (
        "manifest.json",
        "source/raw-blocks.json",
        "source/parser-outline.json",
        "source/structure-quality.json",
        "source/selected-view.json",
        "source/normalized.md",
        "source/document.json",
        "source/structure-scan.json",
        "source/recovered-outline.json",
    ):
        assert (run_dir / relative).is_file(), relative
    assert manifest.status == "succeeded"
    assert {record.relative_path for record in manifest.artifacts} >= {
        "source/raw-blocks.json",
        "source/parser-outline.json",
        "source/structure-quality.json",
        "source/selected-view.json",
    }
    assert json.loads((run_dir / "source/structure-scan.json").read_text())["status"] == "deferred"
    assert (
        json.loads((run_dir / "source/recovered-outline.json").read_text())["model_result"] is False
    )
    assert storage.reconcile(manifest).consistent is True
