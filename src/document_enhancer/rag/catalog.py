"""Atomic cumulative catalog ingestion with historical versions and conflict checks."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from document_enhancer.artifacts.atomic import atomic_write_json
from document_enhancer.domain.run import CatalogIngestionReceipt

from .build import RagBuildError, verify_package
from .migrations import connect, migrate


class CatalogConflictError(RagBuildError):
    """A stable graph or document identity was reused incompatibly."""


CatalogReceipt = CatalogIngestionReceipt


def _rows(connection: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    return list(connection.execute(query))


def _identity_conflicts(
    catalog: sqlite3.Connection, package: sqlite3.Connection
) -> tuple[str, ...]:
    errors: list[str] = []
    for row in package.execute("SELECT node_id, entity_type, canonical_name FROM graph_nodes"):
        existing = catalog.execute(
            "SELECT entity_type, canonical_name FROM graph_nodes WHERE node_id=?", (row["node_id"],)
        ).fetchone()
        if existing and (
            existing["entity_type"] != row["entity_type"]
            or existing["canonical_name"].casefold() != row["canonical_name"].casefold()
        ):
            errors.append(f"graph node identity conflict: {row['node_id']}")
    for row in package.execute("SELECT edge_id, source_id, predicate, target_id FROM graph_edges"):
        existing = catalog.execute(
            "SELECT source_id, predicate, target_id FROM graph_edges WHERE edge_id=?",
            (row["edge_id"],),
        ).fetchone()
        if existing and tuple(existing) != (row["source_id"], row["predicate"], row["target_id"]):
            errors.append(f"graph edge identity conflict: {row['edge_id']}")
    for row in package.execute(
        "SELECT document_id, canonical_title, document_type, namespace FROM documents"
    ):
        existing = catalog.execute(
            "SELECT canonical_title, document_type, namespace FROM documents WHERE document_id=?",
            (row["document_id"],),
        ).fetchone()
        if existing and tuple(existing) != (
            row["canonical_title"],
            row["document_type"],
            row["namespace"],
        ):
            errors.append(f"document identity conflict: {row['document_id']}")
    return tuple(errors)


def _copy_rows(
    destination: sqlite3.Connection,
    source: sqlite3.Connection,
    table: str,
    *,
    mode: str = "IGNORE",
) -> None:
    columns = [str(row["name"]) for row in source.execute(f"PRAGMA table_info({table})")]
    if table == "graph_provenance":
        columns.remove("provenance_id")
    elif table == "embeddings":
        columns.remove("embedding_id")
    if not columns:
        raise CatalogConflictError(f"package is missing required table {table}")
    names = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    statement = f"INSERT OR {mode} INTO {table} ({names}) VALUES ({placeholders})"
    for row in source.execute(f"SELECT {names} FROM {table}"):
        destination.execute(statement, tuple(row))


def _current_version(connection: sqlite3.Connection, document_id: str) -> str:
    rows = list(
        connection.execute(
            """SELECT version_id, effective_from, version_label FROM document_versions
               WHERE document_id=?""",
            (document_id,),
        )
    )
    if not rows:
        raise CatalogConflictError(f"catalog has no version for {document_id}")
    selected = max(
        rows,
        key=lambda row: (
            str(row["effective_from"] or ""),
            str(row["version_label"]),
            str(row["version_id"]),
        ),
    )
    return str(selected["version_id"])


def ingest_package(
    database: Path,
    catalog_path: Path,
    *,
    receipt_path: Path | None = None,
    busy_attempts: int = 4,
) -> CatalogReceipt:
    verification = verify_package(database)
    if not verification.valid:
        raise RagBuildError(
            "catalog ingestion requires a valid package: " + "; ".join(verification.errors)
        )
    package = connect(str(database))
    try:
        build = package.execute("SELECT * FROM rag_builds").fetchone()
        if build is None:
            raise RagBuildError("package has no RAG build")
        build_id = str(build["rag_build_id"])
        document_id = str(build["document_id"])
        version_id = str(build["version_id"])
        catalog_path = catalog_path.expanduser().resolve()
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog = connect(str(catalog_path), catalog=True)
        try:
            migrate(catalog)
            existing = catalog.execute(
                "SELECT * FROM catalog_ingestions WHERE rag_build_id=?", (build_id,)
            ).fetchone()
            if existing:
                receipt = CatalogReceipt(
                    ingestion_id=str(existing["ingestion_id"]),
                    rag_build_id=build_id,
                    document_id=document_id,
                    version_id=version_id,
                    catalog_generation=int(existing["catalog_generation"]),
                    idempotent=True,
                    catalog_path=str(catalog_path),
                )
                if receipt_path:
                    atomic_write_json(receipt_path, receipt.as_dict())
                return receipt
            begun = False
            for attempt in range(1, busy_attempts + 1):
                try:
                    catalog.execute("BEGIN IMMEDIATE")
                    begun = True
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or attempt == busy_attempts:
                        raise
                    time.sleep(min(0.05 * (2 ** (attempt - 1)), 0.5))
            if not begun:
                raise RagBuildError("catalog busy retry policy exhausted")
            try:
                # Repeat idempotence and identity checks under the write lock. The earlier reads
                # are only a fast path; these checks close the race with another ingestion.
                existing = catalog.execute(
                    "SELECT * FROM catalog_ingestions WHERE rag_build_id=?", (build_id,)
                ).fetchone()
                if existing:
                    catalog.rollback()
                    receipt = CatalogReceipt(
                        ingestion_id=str(existing["ingestion_id"]),
                        rag_build_id=build_id,
                        document_id=document_id,
                        version_id=version_id,
                        catalog_generation=int(existing["catalog_generation"]),
                        idempotent=True,
                        catalog_path=str(catalog_path),
                    )
                    if receipt_path:
                        atomic_write_json(receipt_path, receipt.as_dict())
                    return receipt
                conflicts = _identity_conflicts(catalog, package)
                if conflicts:
                    catalog.rollback()
                    if receipt_path:
                        atomic_write_json(
                            receipt_path,
                            {
                                "schema_version": "m7.catalog-ingestion.v1",
                                "rag_build_id": build_id,
                                "document_id": document_id,
                                "version_id": version_id,
                                "status": "conflict",
                                "promoted": False,
                                "conflicts": list(conflicts),
                            },
                        )
                    raise CatalogConflictError("; ".join(conflicts))
                # Copy immutable build inputs first; graph identities use IGNORE only after the
                # compatibility check above. Version-scoped rows remain strict.
                for table in ("rag_builds", "build_inputs", "documents", "graph_nodes"):
                    _copy_rows(catalog, package, table)
                catalog.execute(
                    "UPDATE document_versions SET is_current=0 WHERE document_id=?", (document_id,)
                )
                _copy_rows(catalog, package, "document_versions")
                for table in (
                    "sections",
                    "graph_node_versions",
                    "graph_aliases",
                    "graph_edges",
                    "graph_edge_versions",
                    "graph_provenance",
                    "chunks",
                    "chunk_source_spans",
                    "chunk_entities",
                    "embeddings",
                    "chunk_vectors",
                ):
                    _copy_rows(catalog, package, table)
                selected = _current_version(catalog, document_id)
                catalog.execute(
                    "UPDATE document_versions SET is_current=(version_id=?) WHERE document_id=?",
                    (selected, document_id),
                )
                # FTS is populated by chunk triggers and is deliberately not copied.
                generation = int(
                    catalog.execute(
                        "SELECT COALESCE(MAX(generation), 0) + 1 FROM catalog_generations"
                    ).fetchone()[0]
                )
                now = datetime.now(UTC).isoformat()
                catalog.execute(
                    "INSERT INTO catalog_generations VALUES (?, ?, ?)",
                    (generation, build_id, now),
                )
                token = hashlib.sha256(f"{build_id}\0{generation}".encode()).hexdigest()[:20]
                ingestion_id = f"CATINGEST-{token.upper()}"
                catalog.execute(
                    """INSERT INTO catalog_ingestions VALUES (?, ?, ?, ?, ?, ?, 'promoted', NULL, ?, ?)""",
                    (
                        ingestion_id,
                        build_id,
                        document_id,
                        version_id,
                        build["enhanced_digest"],
                        build["embedding_profile"],
                        generation,
                        now,
                    ),
                )
                integrity = str(catalog.execute("PRAGMA integrity_check").fetchone()[0])
                foreign_keys = list(catalog.execute("PRAGMA foreign_key_check"))
                if integrity != "ok" or foreign_keys:
                    raise RagBuildError("catalog integrity or foreign-key verification failed")
                catalog.commit()
            except Exception:
                catalog.rollback()
                raise
            catalog_path.chmod(0o600)
            receipt = CatalogReceipt(
                ingestion_id=ingestion_id,
                rag_build_id=build_id,
                document_id=document_id,
                version_id=version_id,
                catalog_generation=generation,
                idempotent=False,
                catalog_path=str(catalog_path),
            )
            if receipt_path:
                atomic_write_json(receipt_path, receipt.as_dict())
            return receipt
        finally:
            catalog.close()
    finally:
        package.close()


def inspect_catalog(catalog_path: Path) -> dict[str, object]:
    if not catalog_path.expanduser().is_file():
        raise CatalogConflictError(f"catalog does not exist: {catalog_path.expanduser()}")
    connection = connect(str(catalog_path), catalog=True)
    try:
        migrate(connection)
        generation = int(
            connection.execute(
                "SELECT COALESCE(MAX(generation), 0) FROM catalog_generations"
            ).fetchone()[0]
        )
        return {
            "schema_version": "m7.catalog-inspection.v1",
            "catalog_path": str(catalog_path.expanduser().resolve()),
            "catalog_generation": generation,
            "documents": int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]),
            "versions": int(
                connection.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0]
            ),
            "current_versions": int(
                connection.execute(
                    "SELECT COUNT(*) FROM document_versions WHERE is_current=1"
                ).fetchone()[0]
            ),
            "chunks": int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]),
            "graph_nodes": int(
                connection.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
            ),
            "graph_edges": int(
                connection.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
            ),
            "embeddings": int(connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]),
            "fts_rows": int(connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]),
            "sessions": int(connection.execute("SELECT COUNT(*) FROM rag_sessions").fetchone()[0]),
            "saved_queries": int(
                connection.execute("SELECT COUNT(*) FROM rag_queries").fetchone()[0]
            ),
            "saved_answers": int(
                connection.execute("SELECT COUNT(*) FROM rag_answers").fetchone()[0]
            ),
        }
    finally:
        connection.close()


__all__ = [
    "CatalogConflictError",
    "CatalogReceipt",
    "ingest_package",
    "inspect_catalog",
]
