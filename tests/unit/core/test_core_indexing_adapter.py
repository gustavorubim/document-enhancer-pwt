"""Tests for the optional sealed-bundle consumer boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from document_enhancer.core.indexing import CoreBundleIndex, load_sealed_bundle
from document_enhancer.core.integrity import (
    ArtifactIntegrityError,
    ResumeIdentityError,
    build_seal_manifest,
    capture_resume_identity,
    register_artifact,
)
from document_enhancer.core.layout import AUDIT, FINAL_MARKDOWN, GRAPH_JSONL, ONTOLOGY, SEAL
from document_enhancer.core.models import RunRecord
from document_enhancer.core.store import RunStore


def _write_sealed_bundle(root: Path, *, audit_status: str = "pass") -> Path:
    bundle = root / "run-1"
    (bundle / AUDIT).parent.mkdir(parents=True)
    (bundle / FINAL_MARKDOWN).parent.mkdir(parents=True)
    (bundle / "documents").mkdir(parents=True)
    source = b"# Intake\n\nThe owner reviews the request.\n"
    final = "# Intake\n\nThe owner reviews the request.\n"
    audit = {"schema_version": "core.audit.v1", "status": audit_status, "checks": {}}
    ontology = {
        "schema_version": "core.graph.v1",
        "markdown_sha256": hashlib.sha256(final.encode()).hexdigest(),
        "nodes": [
            {
                "node_id": "section-intake",
                "label": "Intake",
                "node_type": "section",
                "provenance_span_ids": ["SPAN-1"],
            }
        ],
        "edges": [],
    }
    graph_lines = json.dumps({"kind": "node", **ontology["nodes"][0]}, sort_keys=True) + "\n"
    (bundle / "documents/original.md").write_bytes(source)
    (bundle / FINAL_MARKDOWN).write_text(final, encoding="utf-8")
    (bundle / ONTOLOGY).write_text(json.dumps(ontology, sort_keys=True), encoding="utf-8")
    (bundle / GRAPH_JSONL).parent.mkdir(parents=True, exist_ok=True)
    (bundle / GRAPH_JSONL).write_text(graph_lines, encoding="utf-8")
    (bundle / AUDIT).write_text(json.dumps(audit, sort_keys=True), encoding="utf-8")
    _write_manifest(bundle)
    return bundle


def _write_manifest(bundle: Path) -> None:
    artifacts = {
        "source.original": register_artifact(bundle, "documents/original.md"),
        "output.final_markdown": register_artifact(bundle, FINAL_MARKDOWN),
        "audit.report": register_artifact(bundle, AUDIT),
        "output.graph": register_artifact(bundle, GRAPH_JSONL),
        "output.ontology": register_artifact(bundle, ONTOLOGY),
    }
    manifest = build_seal_manifest(
        run_id=bundle.name,
        source_digest=artifacts["source.original"].sha256,
        recipe_id="enterprise_core@1/process",
        recipe_digest="2" * 64,
        configuration_digest="3" * 64,
        artifacts=artifacts,
        artifact_root=bundle,
    )
    (bundle / SEAL).write_text(
        json.dumps(manifest.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
    )


def _read_manifest(bundle: Path) -> dict[str, object]:
    return json.loads((bundle / SEAL).read_text(encoding="utf-8"))


def _write_manifest_payload(bundle: Path, payload: dict[str, object]) -> None:
    (bundle / SEAL).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


@pytest.mark.unit
def test_loader_exposes_validated_snapshot_without_authoring_runtime(tmp_path: Path) -> None:
    bundle = _write_sealed_bundle(tmp_path)

    snapshot = load_sealed_bundle(bundle)

    assert snapshot.run_id == "run-1"
    assert snapshot.graph_schema == "core.graph.v1"
    assert snapshot.final_markdown.startswith("# Intake")
    assert snapshot.graph[0]["kind"] == "node"
    assert snapshot.ontology["schema_version"] == "core.graph.v1"
    assert snapshot.graph_digest == snapshot.manifest.graph_digest
    assert snapshot.ontology_digest == snapshot.manifest.ontology_digest
    assert snapshot.nodes[0]["node_id"] == "section-intake"
    assert snapshot.sections == (("intake", "# Intake\n\nThe owner reviews the request."),)


@pytest.mark.unit
def test_index_is_opt_in_and_search_is_read_only_when_no_catalog_exists(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite3"
    index = CoreBundleIndex(database)

    assert not database.exists()
    assert index.search("owner") == []
    assert not database.exists()

    bundle = _write_sealed_bundle(tmp_path)
    assert index.index(bundle) == 1
    matches = index.search("owner")
    assert matches == [
        {
            "bundle": str(bundle.resolve()),
            "section_id": "intake",
            "text": "# Intake\n\nThe owner reviews the request.",
        }
    ]
    assert index.search("owner", limit=0) == []


@pytest.mark.unit
def test_loader_rejects_tampered_or_failed_bundles_before_indexing(tmp_path: Path) -> None:
    bundle = _write_sealed_bundle(tmp_path)
    (bundle / FINAL_MARKDOWN).write_text("# Tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="final document digest"):
        load_sealed_bundle(bundle)

    failed = _write_sealed_bundle(tmp_path / "failed", audit_status="fail")
    with pytest.raises(ValueError, match="passing"):
        CoreBundleIndex(tmp_path / "failed.sqlite3").index(failed)


@pytest.mark.unit
def test_loader_distinguishes_missing_and_malformed_seals(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    missing.mkdir()
    with pytest.raises(FileNotFoundError, match="seal artifact is missing"):
        load_sealed_bundle(missing)

    malformed = tmp_path / "malformed"
    (malformed / SEAL).parent.mkdir(parents=True)
    (malformed / SEAL).write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="seal artifact is not valid JSON"):
        load_sealed_bundle(malformed)


@pytest.mark.unit
def test_loader_rejects_unknown_graph_edge(tmp_path: Path) -> None:
    bundle = _write_sealed_bundle(tmp_path)
    ontology_path = bundle / ONTOLOGY
    ontology = json.loads(ontology_path.read_text(encoding="utf-8"))
    ontology["edges"] = [{"source": "missing", "target": "section-intake", "edge_type": "uses"}]
    ontology_path.write_text(json.dumps(ontology, sort_keys=True), encoding="utf-8")
    _write_manifest(bundle)

    with pytest.raises(ValueError, match="unknown node"):
        load_sealed_bundle(bundle)


@pytest.mark.unit
def test_loader_rejects_path_only_legacy_seal(tmp_path: Path) -> None:
    bundle = _write_sealed_bundle(tmp_path)
    manifest = _read_manifest(bundle)
    artifacts = cast(dict[str, dict[str, object]], manifest["artifacts"])
    legacy = {
        "run_id": "run-1",
        "source_digest": artifacts["source.original"]["sha256"],
        "final_digest": artifacts["output.final_markdown"]["sha256"],
        "audit_digest": artifacts["audit.report"]["sha256"],
        "artifact_paths": [item["path"] for item in artifacts.values()],
        "sealed": True,
    }
    _write_manifest_payload(bundle, legacy)

    with pytest.raises(ValueError, match="core.seal.v2"):
        load_sealed_bundle(bundle)


@pytest.mark.parametrize("missing", ["graph_digest", "output.graph"])
def test_loader_rejects_incomplete_v2_manifest(tmp_path: Path, missing: str) -> None:
    bundle = _write_sealed_bundle(tmp_path)
    manifest = _read_manifest(bundle)
    if missing == "graph_digest":
        del manifest[missing]
    else:
        artifacts = cast(dict[str, object], manifest["artifacts"])
        del artifacts[missing]
    _write_manifest_payload(bundle, manifest)

    with pytest.raises(ValueError, match="missing|invalid"):
        load_sealed_bundle(bundle)


@pytest.mark.unit
def test_loader_rejects_stage_one_draft_and_traversal_manifest_paths(tmp_path: Path) -> None:
    bundle = _write_sealed_bundle(tmp_path)
    draft = bundle / "draft/document.md"
    draft.parent.mkdir()
    draft.write_bytes((bundle / FINAL_MARKDOWN).read_bytes())
    manifest = _read_manifest(bundle)
    artifacts = cast(dict[str, dict[str, object]], manifest["artifacts"])
    artifacts["output.final_markdown"]["path"] = "draft/document.md"
    _write_manifest_payload(bundle, manifest)

    with pytest.raises(ValueError, match="canonical|draft"):
        load_sealed_bundle(bundle)

    artifacts["output.final_markdown"]["path"] = "../final.md"
    _write_manifest_payload(bundle, manifest)
    with pytest.raises(ValueError, match="artifact path|invalid"):
        load_sealed_bundle(bundle)


@pytest.mark.unit
def test_loader_rejects_registered_symlink_even_when_digest_matches(tmp_path: Path) -> None:
    bundle = _write_sealed_bundle(tmp_path)
    final_path = bundle / FINAL_MARKDOWN
    target = bundle / "markdown/final-target.md"
    target.write_bytes(final_path.read_bytes())
    final_path.unlink()
    final_path.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        load_sealed_bundle(bundle)


@pytest.mark.parametrize("relative_path", [GRAPH_JSONL, ONTOLOGY])
def test_loader_rejects_post_seal_graph_and_ontology_tampering(
    tmp_path: Path, relative_path: str
) -> None:
    bundle = _write_sealed_bundle(tmp_path)
    (bundle / relative_path).write_bytes(b"tampered")

    with pytest.raises(ValueError, match="artifact|digest|size"):
        load_sealed_bundle(bundle)


@pytest.mark.unit
def test_store_verified_reads_and_lock_guarded_resume_identity(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.create_dir("run-1")
    reference = store.write_text("run-1", "markdown/07-final-document.md", "approved")
    record = RunRecord(
        run_id="run-1",
        status="waiting",
        phase="human_review",
        source_digest="1" * 64,
        source_name="input.md",
        artifacts={"output.final_markdown": reference},
    )
    store.save_run(record)

    assert store.read_verified_text("run-1", reference, key="output.final_markdown") == "approved"
    captured = capture_resume_identity(record)
    updated = record.model_copy(update={"status": "running", "phase": "rewrite"})
    assert store.save_run_if_current(updated, captured) == updated
    assert store.load_run("run-1").status == "running"

    with pytest.raises(ResumeIdentityError, match="status"), store.locked_promotion(captured):
        pass

    path = store.run_path("run-1") / reference.path
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="digest"):
        store.read_verified_text("run-1", reference, key="output.final_markdown")
