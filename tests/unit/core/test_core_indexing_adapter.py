"""Tests for the optional sealed-bundle consumer boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from document_enhancer.core.indexing import CoreBundleIndex, load_sealed_bundle


def _write_sealed_bundle(root: Path, *, audit_status: str = "pass") -> Path:
    bundle = root / "run-1"
    (bundle / "audit").mkdir(parents=True)
    (bundle / "output").mkdir()
    (bundle / "source").mkdir()
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
    (bundle / "source/original").write_bytes(source)
    (bundle / "output/final.md").write_text(final, encoding="utf-8")
    (bundle / "output/ontology.json").write_text(
        json.dumps(ontology, sort_keys=True), encoding="utf-8"
    )
    (bundle / "audit/audit.json").write_text(json.dumps(audit, sort_keys=True), encoding="utf-8")
    seal = {
        "run_id": "run-1",
        "source_digest": hashlib.sha256(source).hexdigest(),
        "final_digest": hashlib.sha256(final.encode()).hexdigest(),
        "audit_digest": hashlib.sha256((bundle / "audit/audit.json").read_bytes()).hexdigest(),
        "artifact_paths": ["audit/audit.json", "output/final.md", "output/ontology.json"],
        "sealed": True,
    }
    (bundle / "audit/seal.json").write_text(json.dumps(seal, sort_keys=True), encoding="utf-8")
    return bundle


@pytest.mark.unit
def test_loader_exposes_validated_snapshot_without_authoring_runtime(tmp_path: Path) -> None:
    bundle = _write_sealed_bundle(tmp_path)

    snapshot = load_sealed_bundle(bundle)

    assert snapshot.run_id == "run-1"
    assert snapshot.graph_schema == "core.graph.v1"
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
    (bundle / "output/final.md").write_text("# Tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="final document digest"):
        load_sealed_bundle(bundle)

    failed = _write_sealed_bundle(tmp_path / "failed", audit_status="fail")
    with pytest.raises(ValueError, match="passing"):
        CoreBundleIndex(tmp_path / "failed.sqlite3").index(failed)


@pytest.mark.unit
def test_loader_rejects_unknown_graph_edge(tmp_path: Path) -> None:
    bundle = _write_sealed_bundle(tmp_path)
    ontology_path = bundle / "output/ontology.json"
    ontology = json.loads(ontology_path.read_text(encoding="utf-8"))
    ontology["edges"] = [{"source": "missing", "target": "section-intake", "edge_type": "uses"}]
    ontology_path.write_text(json.dumps(ontology, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown node"):
        load_sealed_bundle(bundle)
