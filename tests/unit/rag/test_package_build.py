from __future__ import annotations

import hashlib
import shutil
import sqlite3
import struct
from pathlib import Path

import pytest

from document_enhancer.artifacts.atomic import digest_file
from document_enhancer.llm import EmbeddingProfile, GeminiEmbeddingAdapter
from document_enhancer.rag import (
    OfflineDeterministicEmbedder,
    RagBuildError,
    build_package,
    decode_float32,
    encode_float32,
    ingest_package,
    verify_package,
)
from document_enhancer.rag.migrations import SCHEMA_VERSION, connect, migrate, verify_migrations
from document_enhancer.workflow import DocumentWorkflow, WorkflowServices


def _approved_run(tmp_path: Path) -> Path:
    source = tmp_path / "approved.md"
    source.write_text(
        "# Approved content\n\nThe approved analyst records the monthly review result.\n",
        encoding="utf-8",
    )
    services = WorkflowServices(
        run_root=tmp_path / "runs",
        source=source,
        gate2_enabled=False,
        offline=True,
        auto_catalog_ingest=False,
    )
    result = DocumentWorkflow(services).run()
    assert result.status == "succeeded"
    return tmp_path / "runs" / result.run_id


def _offline_adapter(profile: EmbeddingProfile, *, fail_after: int | None = None):
    return GeminiEmbeddingAdapter(
        profile=profile,
        embedder=OfflineDeterministicEmbedder(profile.dimensions, fail_after=fail_after),
    )


def _replace_text(connection: sqlite3.Connection, table: str, old: str, new: str) -> None:
    for row in connection.execute(f"PRAGMA table_info({table})"):
        if "TEXT" in str(row[2]).upper():
            connection.execute(f"UPDATE {table} SET {row[1]}=replace({row[1]}, ?, ?)", (old, new))


def _raw_digest(connection: sqlite3.Connection, table: str) -> str:
    payload = b"".join(
        str(row[0]).encode() + b"\n"
        for row in connection.execute(f"SELECT raw_json FROM {table} ORDER BY source_ordinal")
    )
    return hashlib.sha256(payload).hexdigest()


def _clone_as_historical_version(source: Path, target: Path, *, suffix: str) -> None:
    shutil.copy2(source, target)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    old_build = str(connection.execute("SELECT rag_build_id FROM rag_builds").fetchone()[0])
    old_version = str(connection.execute("SELECT version_id FROM document_versions").fetchone()[0])
    new_build = f"{old_build}-{suffix}"
    new_version = f"{old_version}-{suffix}"
    endpoint_edges = [
        str(row[0])
        for row in connection.execute(
            "SELECT edge_id FROM graph_edges WHERE source_id=? OR target_id=?",
            (old_version, old_version),
        )
    ]
    chunk_ids = [str(row[0]) for row in connection.execute("SELECT chunk_id FROM chunks")]
    tables = (
        "rag_builds",
        "build_inputs",
        "document_versions",
        "sections",
        "chunks",
        "chunk_source_spans",
        "chunk_entities",
        "graph_nodes",
        "graph_node_versions",
        "graph_aliases",
        "graph_edges",
        "graph_edge_versions",
        "graph_provenance",
        "embeddings",
        "chunk_vectors",
        "chunks_fts",
    )
    for edge_id in endpoint_edges:
        for table in tables:
            _replace_text(connection, table, edge_id, f"{edge_id}-{suffix}")
    for chunk_id in chunk_ids:
        for table in tables:
            _replace_text(connection, table, chunk_id, f"{chunk_id}-{suffix}")
    for table in tables:
        _replace_text(connection, table, old_build, new_build)
        _replace_text(connection, table, old_version, new_version)
    connection.execute(
        "UPDATE document_versions SET version_label=?, effective_from=?",
        (suffix.removeprefix("V"), f"2026-0{suffix.removeprefix('V')}-01"),
    )
    for artifact, table in {
        "chunks.jsonl": "chunks",
        "nodes.jsonl": "graph_nodes",
        "edges.jsonl": "graph_edges",
    }.items():
        connection.execute(
            "UPDATE build_inputs SET digest=? WHERE artifact_name=?",
            (_raw_digest(connection, table), artifact),
        )
    connection.commit()
    connection.close()


def test_package_reconciles_vectors_fts_and_idempotent_rebuild(tmp_path: Path) -> None:
    run_path = _approved_run(tmp_path)
    database = run_path / "rag/document-rag.sqlite3"
    before = digest_file(database)
    manifest = build_package(
        run_path,
        adapter=_offline_adapter(EmbeddingProfile()),
    )
    assert digest_file(database) == before
    verification = verify_package(database, export_dir=run_path / "export")
    assert verification.valid, verification.errors
    assert verification.row_counts["chunks"] > 0
    assert verification.row_counts["chunks"] == verification.row_counts["embeddings"]
    assert verification.row_counts["chunks"] == verification.row_counts["chunks_fts"]
    assert manifest.vector_count == verification.row_counts["chunks"]
    connection = connect(str(database))
    try:
        dimensions = {row[0] for row in connection.execute("SELECT dimension FROM embeddings")}
        assert dimensions == {768}
        assert connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM graph_provenance").fetchone()[0] > 0
    finally:
        connection.close()


def test_profile_change_reembeds_and_partial_failure_never_promotes(tmp_path: Path) -> None:
    run_path = _approved_run(tmp_path)
    database = run_path / "rag/document-rag.sqlite3"
    profile = EmbeddingProfile(dimensions=1536)
    changed = build_package(run_path, profile=profile, adapter=_offline_adapter(profile))
    assert changed.embedding_dimension == 1536
    assert verify_package(database).valid
    promoted_digest = digest_file(database)
    promoted_manifest = (run_path / "rag/build-manifest.json").read_bytes()

    failing_profile = EmbeddingProfile(dimensions=3072)
    with pytest.raises(RagBuildError, match="no package was promoted"):
        build_package(
            run_path,
            profile=failing_profile,
            adapter=_offline_adapter(failing_profile, fail_after=0),
            max_attempts=2,
        )
    assert digest_file(database) == promoted_digest
    assert (run_path / "rag/build-manifest.json").read_bytes() == promoted_manifest
    assert (run_path / "rag/embedding-errors.jsonl").is_file()


def test_input_limit_rejection_preserves_promoted_package(tmp_path: Path) -> None:
    run_path = _approved_run(tmp_path)
    database = run_path / "rag/document-rag.sqlite3"
    before = digest_file(database)
    profile = EmbeddingProfile(dimensions=1536, max_input_characters=10)
    with pytest.raises(RagBuildError, match="no package was promoted"):
        build_package(run_path, profile=profile, adapter=_offline_adapter(profile))
    assert digest_file(database) == before


def test_prior_schema_migrates_forward_and_detects_digest_drift(tmp_path: Path) -> None:
    database = tmp_path / "prior.sqlite3"
    connection = connect(str(database))
    try:
        migrate(connection, target=1)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        migrate(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert verify_migrations(connection) == ()
        connection.execute("UPDATE schema_migrations SET digest='bad' WHERE version=1")
        connection.commit()
        assert "migration 1 metadata mismatch" in verify_migrations(connection)
    finally:
        connection.close()


def test_known_float32_vector_and_fts_tamper_fail_closed(tmp_path: Path) -> None:
    blob, digest, norm = encode_float32([1.0, -2.0, 0.5], dimension=3)
    assert blob == struct.pack("<3f", 1.0, -2.0, 0.5)
    assert decode_float32(blob, dimension=3) == (1.0, -2.0, 0.5)
    assert len(digest) == 64
    assert norm == pytest.approx(2.291287847)

    run_path = _approved_run(tmp_path)
    database = run_path / "rag/document-rag.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("DELETE FROM chunks_fts")
        connection.commit()
    finally:
        connection.close()
    verification = verify_package(database)
    assert not verification.valid
    assert "chunk/FTS row count mismatch" in verification.errors


def test_catalog_ingestion_is_atomic_idempotent_and_monotonic(tmp_path: Path) -> None:
    run_path = _approved_run(tmp_path)
    database = run_path / "rag/document-rag.sqlite3"
    catalog = tmp_path / "catalog.sqlite3"
    first = ingest_package(database, catalog)
    second = ingest_package(database, catalog)
    assert first.catalog_generation == 1
    assert second.catalog_generation == 1
    assert second.idempotent
    connection = connect(str(catalog), catalog=True)
    try:
        assert connection.execute("SELECT COUNT(*) FROM catalog_generations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] > 0
    finally:
        connection.close()


def test_catalog_retains_history_selects_current_and_rejects_identity_conflicts(
    tmp_path: Path,
) -> None:
    run_path = _approved_run(tmp_path)
    first_package = run_path / "rag/document-rag.sqlite3"
    second_package = tmp_path / "version-2.sqlite3"
    _clone_as_historical_version(first_package, second_package, suffix="V2")
    assert verify_package(second_package).valid
    catalog = tmp_path / "historical-catalog.sqlite3"
    assert ingest_package(first_package, catalog).catalog_generation == 1
    assert ingest_package(second_package, catalog).catalog_generation == 2
    connection = connect(str(catalog), catalog=True)
    try:
        versions = list(
            connection.execute(
                "SELECT version_label, is_current FROM document_versions ORDER BY version_label"
            )
        )
        assert [(row[0], row[1]) for row in versions] == [("1.0", 0), ("2", 1)]
        assert connection.execute("SELECT COUNT(*) FROM catalog_generations").fetchone()[0] == 2
    finally:
        connection.close()

    conflicting = tmp_path / "conflicting.sqlite3"
    _clone_as_historical_version(second_package, conflicting, suffix="V3")
    conflict_db = sqlite3.connect(conflicting)
    conflict_db.row_factory = sqlite3.Row
    row = conflict_db.execute(
        """SELECT node_id FROM graph_nodes
           WHERE entity_type NOT IN ('DocumentIdentity', 'DocumentVersion') LIMIT 1"""
    ).fetchone()
    assert row is not None
    conflict_db.execute(
        "UPDATE graph_nodes SET canonical_name=canonical_name || ' conflict' WHERE node_id=?",
        (row["node_id"],),
    )
    conflict_db.commit()
    conflict_db.close()
    from document_enhancer.rag import CatalogConflictError

    conflict_receipt = tmp_path / "catalog-conflict.json"
    with pytest.raises(CatalogConflictError, match="graph node identity conflict"):
        ingest_package(conflicting, catalog, receipt_path=conflict_receipt)
    assert '"status": "conflict"' in conflict_receipt.read_text(encoding="utf-8")
    connection = connect(str(catalog), catalog=True)
    try:
        assert connection.execute("SELECT COUNT(*) FROM catalog_generations").fetchone()[0] == 2
    finally:
        connection.close()
