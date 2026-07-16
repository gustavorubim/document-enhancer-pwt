"""Forward-only SQLite migrations for sealed RAG packages and cumulative catalogs."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

SCHEMA_VERSION = 3
MINIMUM_READER_VERSION = 1


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


MIGRATIONS = (
    Migration(
        1,
        "rag_package_core",
        """
        CREATE TABLE rag_builds (
            rag_build_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            bundle_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            source_digest TEXT NOT NULL,
            enhanced_digest TEXT NOT NULL,
            semantic_digest TEXT NOT NULL,
            embedding_profile TEXT NOT NULL,
            embedding_provider TEXT NOT NULL,
            embedding_backend TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            embedding_task TEXT NOT NULL,
            embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension IN (768, 1536, 3072)),
            embedding_format_version TEXT NOT NULL,
            application_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('building', 'validated', 'failed')),
            validation_result TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE build_inputs (
            rag_build_id TEXT NOT NULL REFERENCES rag_builds(rag_build_id) ON DELETE CASCADE,
            artifact_name TEXT NOT NULL,
            digest TEXT NOT NULL,
            row_count INTEGER CHECK (row_count IS NULL OR row_count >= 0),
            PRIMARY KEY (rag_build_id, artifact_name)
        );

        CREATE TABLE documents (
            document_id TEXT PRIMARY KEY,
            canonical_title TEXT NOT NULL,
            document_type TEXT NOT NULL,
            namespace TEXT NOT NULL,
            source_digest TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE document_versions (
            version_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE RESTRICT,
            version_label TEXT NOT NULL,
            status TEXT NOT NULL,
            effective_from TEXT,
            effective_to TEXT,
            source_digest TEXT NOT NULL,
            enhanced_digest TEXT NOT NULL,
            semantic_digest TEXT NOT NULL,
            confidentiality TEXT NOT NULL,
            rag_build_id TEXT NOT NULL REFERENCES rag_builds(rag_build_id) ON DELETE RESTRICT,
            is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
            created_at TEXT NOT NULL,
            UNIQUE (document_id, version_label, enhanced_digest)
        );
        CREATE UNIQUE INDEX one_current_version_per_document
            ON document_versions(document_id) WHERE is_current = 1;
        CREATE INDEX document_versions_document_idx
            ON document_versions(document_id, effective_from, version_id);

        CREATE TABLE sections (
            version_id TEXT NOT NULL REFERENCES document_versions(version_id) ON DELETE CASCADE,
            section_id TEXT NOT NULL,
            parent_section_id TEXT,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            hierarchy_path TEXT NOT NULL,
            title TEXT NOT NULL,
            markdown_anchor TEXT,
            text TEXT NOT NULL,
            checksum TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            source_ordinal INTEGER NOT NULL,
            PRIMARY KEY (version_id, section_id),
            FOREIGN KEY (version_id, parent_section_id)
                REFERENCES sections(version_id, section_id) DEFERRABLE INITIALLY DEFERRED
        );
        CREATE INDEX sections_order_idx ON sections(version_id, ordinal, section_id);

        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE RESTRICT,
            version_id TEXT NOT NULL REFERENCES document_versions(version_id) ON DELETE CASCADE,
            section_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            section_path TEXT NOT NULL,
            section_title TEXT NOT NULL,
            markdown_anchor TEXT,
            text TEXT NOT NULL,
            token_count INTEGER NOT NULL CHECK (token_count >= 0),
            checksum TEXT NOT NULL,
            canonical_terms TEXT NOT NULL,
            contextual_metadata TEXT NOT NULL,
            authority TEXT NOT NULL,
            review_status TEXT NOT NULL,
            confidentiality TEXT NOT NULL,
            valid_from TEXT,
            valid_to TEXT,
            raw_json TEXT NOT NULL,
            source_ordinal INTEGER NOT NULL,
            FOREIGN KEY (version_id, section_id) REFERENCES sections(version_id, section_id)
        );
        CREATE INDEX chunks_version_order_idx ON chunks(version_id, ordinal, chunk_id);
        CREATE INDEX chunks_section_idx ON chunks(version_id, section_id);

        CREATE TABLE chunk_source_spans (
            chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
            source_span_id TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            PRIMARY KEY (chunk_id, source_span_id)
        );
        CREATE INDEX chunk_source_spans_span_idx ON chunk_source_spans(source_span_id, chunk_id);

        CREATE TABLE graph_nodes (
            node_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            attributes_json TEXT NOT NULL,
            layer TEXT NOT NULL,
            authority TEXT NOT NULL,
            review_status TEXT NOT NULL,
            valid_from TEXT,
            valid_to TEXT,
            raw_json TEXT NOT NULL,
            source_ordinal INTEGER NOT NULL
        );
        CREATE INDEX graph_nodes_identity_idx ON graph_nodes(entity_type, canonical_name);

        CREATE TABLE graph_node_versions (
            node_id TEXT NOT NULL REFERENCES graph_nodes(node_id) ON DELETE RESTRICT,
            version_id TEXT NOT NULL REFERENCES document_versions(version_id) ON DELETE CASCADE,
            PRIMARY KEY (node_id, version_id)
        );

        CREATE TABLE graph_aliases (
            node_id TEXT NOT NULL REFERENCES graph_nodes(node_id) ON DELETE CASCADE,
            alias TEXT NOT NULL COLLATE NOCASE,
            PRIMARY KEY (node_id, alias)
        );
        CREATE INDEX graph_aliases_alias_idx ON graph_aliases(alias, node_id);

        CREATE TABLE graph_edges (
            edge_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES graph_nodes(node_id) ON DELETE RESTRICT,
            predicate TEXT NOT NULL,
            target_id TEXT NOT NULL REFERENCES graph_nodes(node_id) ON DELETE RESTRICT,
            layer TEXT NOT NULL,
            authority TEXT NOT NULL,
            review_status TEXT NOT NULL,
            confidence REAL,
            valid_from TEXT,
            valid_to TEXT,
            raw_json TEXT NOT NULL,
            source_ordinal INTEGER NOT NULL
        );
        CREATE INDEX graph_edges_source_idx ON graph_edges(source_id, predicate, target_id);
        CREATE INDEX graph_edges_target_idx ON graph_edges(target_id, predicate, source_id);

        CREATE TABLE graph_edge_versions (
            edge_id TEXT NOT NULL REFERENCES graph_edges(edge_id) ON DELETE RESTRICT,
            version_id TEXT NOT NULL REFERENCES document_versions(version_id) ON DELETE CASCADE,
            PRIMARY KEY (edge_id, version_id)
        );

        CREATE TABLE graph_provenance (
            provenance_id INTEGER PRIMARY KEY,
            object_type TEXT NOT NULL CHECK (object_type IN ('node', 'edge')),
            object_id TEXT NOT NULL,
            version_id TEXT NOT NULL REFERENCES document_versions(version_id) ON DELETE CASCADE,
            source_span_id TEXT,
            answer_id TEXT,
            steering_id TEXT,
            reference_id TEXT,
            origin TEXT NOT NULL,
            authority TEXT NOT NULL,
            layer TEXT NOT NULL,
            review_status TEXT NOT NULL,
            provenance_json TEXT NOT NULL
        );
        CREATE INDEX graph_provenance_object_idx
            ON graph_provenance(object_type, object_id, version_id);
        CREATE INDEX graph_provenance_span_idx ON graph_provenance(source_span_id);

        CREATE TABLE chunk_entities (
            chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
            node_id TEXT NOT NULL REFERENCES graph_nodes(node_id) ON DELETE RESTRICT,
            relation TEXT NOT NULL DEFAULT 'mentions',
            PRIMARY KEY (chunk_id, node_id)
        );

        CREATE TABLE embeddings (
            embedding_id INTEGER PRIMARY KEY,
            object_type TEXT NOT NULL CHECK (object_type = 'chunk'),
            object_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
            rag_build_id TEXT NOT NULL REFERENCES rag_builds(rag_build_id) ON DELETE RESTRICT,
            provider TEXT NOT NULL,
            backend TEXT NOT NULL,
            model TEXT NOT NULL,
            task_type TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            dimension INTEGER NOT NULL CHECK (dimension > 0),
            dtype TEXT NOT NULL CHECK (dtype = 'float32'),
            byte_order TEXT NOT NULL CHECK (byte_order = 'little'),
            vector_encoding TEXT NOT NULL CHECK (vector_encoding = 'raw'),
            vector_blob BLOB NOT NULL,
            vector_digest TEXT NOT NULL,
            input_digest TEXT NOT NULL,
            input_format_version TEXT NOT NULL,
            norm REAL NOT NULL CHECK (norm >= 0),
            normalized INTEGER NOT NULL CHECK (normalized IN (0, 1)),
            selected INTEGER NOT NULL DEFAULT 1 CHECK (selected IN (0, 1)),
            attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts > 0),
            created_at TEXT NOT NULL,
            UNIQUE (object_id, profile_id)
        );
        CREATE UNIQUE INDEX one_selected_embedding_per_chunk
            ON embeddings(object_id) WHERE selected = 1;
        CREATE INDEX embeddings_lookup_idx
            ON embeddings(object_type, object_id, profile_id, rag_build_id);

        CREATE TABLE chunk_vectors (
            chunk_id TEXT PRIMARY KEY REFERENCES chunks(chunk_id) ON DELETE CASCADE,
            profile_id TEXT NOT NULL,
            dimension INTEGER NOT NULL CHECK (dimension > 0),
            vector_blob BLOB NOT NULL,
            vector_digest TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            chunk_id UNINDEXED, document_id UNINDEXED, version_id UNINDEXED,
            section_title, section_path, canonical_terms, text,
            tokenize = 'unicode61'
        );
        CREATE TRIGGER chunks_fts_insert AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(
                chunk_id, document_id, version_id, section_title,
                section_path, canonical_terms, text
            ) VALUES (
                new.chunk_id, new.document_id, new.version_id, new.section_title,
                new.section_path, new.canonical_terms, new.text
            );
        END;
        CREATE TRIGGER chunks_fts_delete AFTER DELETE ON chunks BEGIN
            DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
        END;
        CREATE TRIGGER chunks_fts_update AFTER UPDATE ON chunks BEGIN
            DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
            INSERT INTO chunks_fts(
                chunk_id, document_id, version_id, section_title,
                section_path, canonical_terms, text
            ) VALUES (
                new.chunk_id, new.document_id, new.version_id, new.section_title,
                new.section_path, new.canonical_terms, new.text
            );
        END;

        CREATE TABLE build_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """,
    ),
    Migration(
        2,
        "cumulative_catalog",
        """
        CREATE TABLE catalog_generations (
            generation INTEGER PRIMARY KEY CHECK (generation > 0),
            rag_build_id TEXT NOT NULL REFERENCES rag_builds(rag_build_id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE catalog_ingestions (
            ingestion_id TEXT PRIMARY KEY,
            rag_build_id TEXT NOT NULL UNIQUE REFERENCES rag_builds(rag_build_id) ON DELETE RESTRICT,
            document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE RESTRICT,
            version_id TEXT NOT NULL REFERENCES document_versions(version_id) ON DELETE RESTRICT,
            enhanced_digest TEXT NOT NULL,
            embedding_profile TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('promoted', 'conflict')),
            conflict_details TEXT,
            catalog_generation INTEGER NOT NULL UNIQUE
                REFERENCES catalog_generations(generation) ON DELETE RESTRICT,
            ingested_at TEXT NOT NULL,
            UNIQUE (document_id, version_id, enhanced_digest, embedding_profile)
        );
        """,
    ),
    Migration(
        3,
        "rag_sessions_and_query_audit",
        """
        CREATE TABLE rag_sessions (
            session_id TEXT PRIMARY KEY,
            catalog_generation INTEGER NOT NULL
                REFERENCES catalog_generations(generation) ON DELETE RESTRICT,
            filters_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE rag_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES rag_sessions(session_id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            query_id TEXT,
            answer_id TEXT,
            citations_json TEXT NOT NULL DEFAULT '[]',
            model_metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX rag_messages_session_idx
            ON rag_messages(session_id, created_at, message_id);

        CREATE TABLE rag_queries (
            query_id TEXT PRIMARY KEY,
            session_id TEXT REFERENCES rag_sessions(session_id) ON DELETE CASCADE,
            original_question TEXT NOT NULL,
            normalized_question TEXT NOT NULL,
            catalog_generation INTEGER NOT NULL
                REFERENCES catalog_generations(generation) ON DELETE RESTRICT,
            embedding_profile TEXT NOT NULL,
            filters_json TEXT NOT NULL,
            diagnostics_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('answered', 'partial', 'insufficient', 'failed')),
            created_at TEXT NOT NULL
        );

        CREATE TABLE rag_retrieval_hits (
            query_id TEXT NOT NULL REFERENCES rag_queries(query_id) ON DELETE CASCADE,
            chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE RESTRICT,
            rank INTEGER NOT NULL CHECK (rank > 0),
            fused_score REAL,
            channel_ranks_json TEXT NOT NULL,
            channel_scores_json TEXT NOT NULL,
            graph_paths_json TEXT NOT NULL,
            selected_context INTEGER NOT NULL CHECK (selected_context IN (0, 1)),
            PRIMARY KEY (query_id, chunk_id)
        );

        CREATE TABLE rag_answers (
            answer_id TEXT PRIMARY KEY,
            query_id TEXT NOT NULL UNIQUE REFERENCES rag_queries(query_id) ON DELETE CASCADE,
            answer_markdown TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('answered', 'partial', 'insufficient')),
            grounding_passed INTEGER NOT NULL CHECK (grounding_passed IN (0, 1)),
            caveats_json TEXT NOT NULL,
            unsupported_claims_json TEXT NOT NULL,
            model_route TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE rag_answer_citations (
            answer_id TEXT NOT NULL REFERENCES rag_answers(answer_id) ON DELETE CASCADE,
            citation_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE RESTRICT,
            citation_json TEXT NOT NULL,
            PRIMARY KEY (answer_id, citation_id)
        );
        """,
    ),
)


def connect(path: str, *, catalog: bool = False) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if catalog:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
    return connection


def migrate(connection: sqlite3.Connection, *, target: int = SCHEMA_VERSION) -> None:
    if target < 0 or target > SCHEMA_VERSION:
        raise ValueError(f"unsupported migration target: {target}")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            digest TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )"""
    )
    applied = {
        int(row["version"]): str(row["digest"])
        for row in connection.execute("SELECT version, digest FROM schema_migrations")
    }
    for migration in MIGRATIONS:
        if migration.version > target:
            break
        if migration.version in applied:
            if applied[migration.version] != migration.digest:
                raise RuntimeError(f"migration digest mismatch at version {migration.version}")
            continue
        with connection:
            connection.executescript(migration.sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, digest, applied_at) VALUES (?, ?, ?, ?)",
                (
                    migration.version,
                    migration.name,
                    migration.digest,
                    datetime.now(UTC).isoformat(),
                ),
            )
    connection.execute(f"PRAGMA user_version = {target}")
    if target:
        connection.execute(
            "INSERT OR REPLACE INTO build_metadata(key, value) VALUES ('schema_version', ?)",
            (str(target),),
        )
        connection.execute(
            "INSERT OR REPLACE INTO build_metadata(key, value) VALUES ('minimum_reader_version', ?)",
            (str(MINIMUM_READER_VERSION),),
        )
        connection.commit()


def verify_migrations(connection: sqlite3.Connection) -> tuple[str, ...]:
    errors: list[str] = []
    try:
        rows = list(
            connection.execute(
                "SELECT version, name, digest FROM schema_migrations ORDER BY version"
            )
        )
    except sqlite3.Error as exc:
        return (f"migration table unavailable: {exc}",)
    if [int(row["version"]) for row in rows] != list(range(1, SCHEMA_VERSION + 1)):
        errors.append("database is not at the current migration version")
    expected = {item.version: item for item in MIGRATIONS}
    for row in rows:
        migration = expected.get(int(row["version"]))
        if migration is None or row["name"] != migration.name or row["digest"] != migration.digest:
            errors.append(f"migration {row['version']} metadata mismatch")
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version != SCHEMA_VERSION:
        errors.append(f"PRAGMA user_version is {user_version}, expected {SCHEMA_VERSION}")
    return tuple(errors)


__all__ = [
    "MIGRATIONS",
    "MINIMUM_READER_VERSION",
    "SCHEMA_VERSION",
    "connect",
    "migrate",
    "verify_migrations",
]
