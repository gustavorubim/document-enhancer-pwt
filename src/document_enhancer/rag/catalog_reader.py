"""Fail-closed, read-only access helpers for promoted SQLite RAG catalogs."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from .migrations import SCHEMA_VERSION, verify_migrations
from .models import RetrievalFilters


class CatalogReadError(RuntimeError):
    """The catalog cannot safely be used for retrieval."""


def open_catalog_readonly(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise CatalogReadError(f"catalog does not exist: {resolved}")
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version != SCHEMA_VERSION:
        connection.close()
        raise CatalogReadError(
            f"catalog schema version mismatch: expected {SCHEMA_VERSION}, got {version}"
        )
    migration_errors = verify_migrations(connection)
    if migration_errors:
        connection.close()
        raise CatalogReadError(
            "catalog migration verification failed: " + "; ".join(migration_errors)
        )
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    if integrity != "ok" or list(connection.execute("PRAGMA foreign_key_check")):
        connection.close()
        raise CatalogReadError("catalog failed integrity or foreign-key validation")
    chunks = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    fts_rows = int(connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0])
    missing_fts = int(
        connection.execute(
            """SELECT COUNT(*) FROM chunks c
               WHERE NOT EXISTS (SELECT 1 FROM chunks_fts f WHERE f.chunk_id=c.chunk_id)"""
        ).fetchone()[0]
    )
    if chunks != fts_rows or missing_fts:
        connection.close()
        raise CatalogReadError("catalog chunk/FTS index reconciliation failed")
    return connection


def catalog_generation(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT COALESCE(MAX(generation), 0) FROM catalog_generations"
        ).fetchone()[0]
    )


def _json_list(raw: object) -> list[str]:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise CatalogReadError("catalog contains malformed JSON metadata") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CatalogReadError("catalog metadata expected a list of strings")
    return value


def chunk_select() -> str:
    return """SELECT c.*, d.canonical_title, d.document_type, d.namespace,
                     dv.status AS version_status, dv.effective_from, dv.effective_to,
                     dv.is_current
              FROM chunks c
              JOIN documents d ON d.document_id=c.document_id
              JOIN document_versions dv ON dv.version_id=c.version_id"""


def filter_sql(filters: RetrievalFilters, *, alias: str = "c") -> tuple[str, list[object]]:
    clauses: list[str] = []
    parameters: list[object] = []

    def include(column: str, values: Sequence[str]) -> None:
        if values:
            clauses.append(f"{column} IN ({', '.join('?' for _ in values)})")
            parameters.extend(values)

    include(f"{alias}.document_id", filters.document_ids)
    include("d.document_type", filters.document_types)
    include("d.namespace", filters.domains)
    include("dv.status", filters.statuses)
    include(f"{alias}.confidentiality", filters.confidentiality)
    include(f"{alias}.authority", filters.authorities)
    include(f"{alias}.review_status", filters.review_statuses)
    if filters.catalog_generation is not None:
        clauses.append(
            f"EXISTS (SELECT 1 FROM catalog_ingestions ci WHERE ci.version_id={alias}.version_id "
            "AND ci.catalog_generation<=?)"
        )
        parameters.append(filters.catalog_generation)
        if filters.current_versions_only:
            clauses.append(
                f"{alias}.version_id=(SELECT ci2.version_id FROM catalog_ingestions ci2 "
                f"WHERE ci2.document_id={alias}.document_id AND ci2.catalog_generation<=? "
                "ORDER BY ci2.catalog_generation DESC LIMIT 1)"
            )
            parameters.append(filters.catalog_generation)
    elif filters.current_versions_only:
        clauses.append("dv.is_current=1")
    if filters.effective_at:
        clauses.extend(
            [
                "(dv.effective_from IS NULL OR dv.effective_from<=?)",
                "(dv.effective_to IS NULL OR dv.effective_to>=?)",
                f"({alias}.valid_from IS NULL OR {alias}.valid_from<=?)",
                f"({alias}.valid_to IS NULL OR {alias}.valid_to>=?)",
            ]
        )
        parameters.extend([filters.effective_at] * 4)
    return (" AND ".join(clauses), parameters)


def source_spans(connection: sqlite3.Connection, chunk_id: str) -> tuple[str, ...]:
    return tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT source_span_id FROM chunk_source_spans WHERE chunk_id=? ORDER BY source_span_id",
            (chunk_id,),
        )
    )


def row_to_document(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    extra: dict[str, Any] | None = None,
) -> Document:
    metadata: dict[str, Any] = {
        "chunk_id": str(row["chunk_id"]),
        "document_id": str(row["document_id"]),
        "version_id": str(row["version_id"]),
        "section_id": str(row["section_id"]),
        "section_path": str(row["section_path"]),
        "section_title": str(row["section_title"]),
        "markdown_anchor": row["markdown_anchor"],
        "canonical_title": str(row["canonical_title"]),
        "document_type": str(row["document_type"]),
        "namespace": str(row["namespace"]),
        "version_status": str(row["version_status"]),
        "is_current": bool(row["is_current"]),
        "authority": str(row["authority"]),
        "review_status": str(row["review_status"]),
        "confidentiality": str(row["confidentiality"]),
        "effective_from": row["effective_from"],
        "effective_to": row["effective_to"],
        "source_span_ids": list(source_spans(connection, str(row["chunk_id"]))),
        "canonical_terms": _json_list(row["canonical_terms"]),
        "token_count": int(row["token_count"]),
    }
    metadata.update(extra or {})
    return Document(id=str(row["chunk_id"]), page_content=str(row["text"]), metadata=metadata)


def fetch_chunks(
    connection: sqlite3.Connection,
    chunk_ids: Iterable[str],
    filters: RetrievalFilters,
) -> dict[str, sqlite3.Row]:
    ids = tuple(dict.fromkeys(chunk_ids))
    if not ids:
        return {}
    where, parameters = filter_sql(filters)
    query = chunk_select() + f" WHERE c.chunk_id IN ({', '.join('?' for _ in ids)})"
    args: list[object] = list(ids)
    if where:
        query += " AND " + where
        args.extend(parameters)
    return {str(row["chunk_id"]): row for row in connection.execute(query, args)}


__all__ = [
    "CatalogReadError",
    "catalog_generation",
    "chunk_select",
    "fetch_chunks",
    "filter_sql",
    "open_catalog_readonly",
    "row_to_document",
    "source_spans",
]
