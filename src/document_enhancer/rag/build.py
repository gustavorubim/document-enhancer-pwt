"""Fail-closed construction and verification of sealed per-run SQLite RAG packages."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from document_enhancer import __version__
from document_enhancer.artifacts.atomic import atomic_promote, atomic_write_json, digest_file
from document_enhancer.config import yaml_parser
from document_enhancer.domain.audit import Audit
from document_enhancer.domain.enums import EntityType
from document_enhancer.domain.run import (
    ExportBundleManifest,
    ExportChunk,
    ExportEdge,
    ExportNode,
    RagBuildManifest,
)
from document_enhancer.domain.semantic import SemanticDocument
from document_enhancer.export import validate_export_bundle
from document_enhancer.llm import EmbeddingDocument, EmbeddingProfile, GeminiEmbeddingAdapter
from document_enhancer.llm.caching import ResponseCache

from .embeddings import EmbeddingBatchRunner, decode_float32, encode_float32
from .migrations import SCHEMA_VERSION, connect, migrate, verify_migrations


class RagBuildError(RuntimeError):
    """The package failed validation and was not promoted."""


@dataclass(frozen=True, slots=True)
class PackageVerification:
    valid: bool
    errors: tuple[str, ...]
    row_counts: dict[str, int]
    integrity_check: str
    foreign_key_violations: int
    schema_version: int
    rag_build_id: str | None
    embedding_profile: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "m7.rag-verification.v1",
            "valid": self.valid,
            "errors": list(self.errors),
            "row_counts": self.row_counts,
            "integrity_check": self.integrity_check,
            "foreign_key_violations": self.foreign_key_violations,
            "database_schema_version": self.schema_version,
            "rag_build_id": self.rag_build_id,
            "embedding_profile": self.embedding_profile,
        }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _jsonl_digest(raw_rows: list[str]) -> str:
    payload = b"".join(row.encode("utf-8") + b"\n" for row in raw_rows)
    return hashlib.sha256(payload).hexdigest()


def _load_jsonl(path: Path, model: type[Any]) -> list[Any]:
    values: list[Any] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            values.append(model.model_validate_json(line))
        except ValueError as exc:
            raise RagBuildError(f"invalid {path.name} row {line_number}: {exc}") from exc
    return values


def _load_inputs(
    run_path: Path,
) -> tuple[
    ExportBundleManifest,
    list[ExportChunk],
    list[ExportNode],
    list[ExportEdge],
    dict[str, Any],
]:
    audit_path = run_path / "audit/audit.json"
    if not audit_path.is_file():
        raise RagBuildError("RAG build requires a completed audit artifact")
    try:
        Audit.model_validate_json(audit_path.read_text(encoding="utf-8")).assert_pass()
    except ValueError as exc:
        raise RagBuildError("RAG build is blocked because the audit did not pass") from exc
    export_errors = validate_export_bundle(run_path / "export")
    if export_errors:
        raise RagBuildError("RAG build is blocked by invalid export: " + "; ".join(export_errors))
    manifest = ExportBundleManifest.model_validate_json(
        (run_path / "export/bundle-manifest.json").read_text(encoding="utf-8")
    )
    chunks = _load_jsonl(run_path / "export/chunks.jsonl", ExportChunk)
    nodes = _load_jsonl(run_path / "export/nodes.jsonl", ExportNode)
    edges = _load_jsonl(run_path / "export/edges.jsonl", ExportEdge)
    semantic_path = run_path / "output/enhanced.semantic.yaml"
    markdown_path = run_path / "output/enhanced.md"
    if not semantic_path.is_file() or not markdown_path.is_file():
        raise RagBuildError("RAG build requires enhanced Markdown and semantic sidecar")
    semantic = yaml_parser().load(semantic_path.read_text(encoding="utf-8"))
    if not isinstance(semantic, dict) or not semantic.get("validation_passed"):
        raise RagBuildError("semantic sidecar is invalid or not validated")
    try:
        semantic_model = SemanticDocument.model_validate(semantic)
    except ValueError as exc:
        raise RagBuildError("semantic sidecar does not satisfy its strict contract") from exc
    semantic_digest = hashlib.sha256(
        _canonical_json(semantic_model.model_dump(mode="json")).encode()
    ).hexdigest()
    if semantic_digest != manifest.semantic_digest:
        raise RagBuildError("semantic sidecar digest does not match the export manifest")
    excluded = set(semantic_model.provisional_ids) | {
        item.target_object_id for item in semantic_model.open_issues if item.target_object_id
    }
    expected_nodes = [
        ExportNode.from_entity(item)
        for item in [semantic_model.document, semantic_model.version, *semantic_model.objects]
        if item.id not in excluded
    ]
    expected_ids = {item.id for item in expected_nodes}
    expected_edges = [
        ExportEdge.from_relationship(item)
        for item in semantic_model.relationships
        if item.source_id in expected_ids and item.target_id in expected_ids
    ]
    if [_canonical_json(item.model_dump(mode="json")) for item in nodes] != [
        _canonical_json(item.model_dump(mode="json")) for item in expected_nodes
    ]:
        raise RagBuildError("nodes.jsonl does not reconcile to the semantic sidecar")
    if [_canonical_json(item.model_dump(mode="json")) for item in edges] != [
        _canonical_json(item.model_dump(mode="json")) for item in expected_edges
    ]:
        raise RagBuildError("edges.jsonl does not reconcile to the semantic sidecar")
    if digest_file(markdown_path) != manifest.enhanced_digest:
        raise RagBuildError("enhanced Markdown digest does not match the export manifest")
    return manifest, chunks, nodes, edges, semantic


def _profile_id(profile: EmbeddingProfile) -> str:
    return hashlib.sha256(profile.identity.encode("utf-8")).hexdigest()


def _build_id(bundle: ExportBundleManifest, profile: EmbeddingProfile) -> str:
    token = hashlib.sha256(
        f"{bundle.bundle_id}\0{bundle.enhanced_digest}\0{profile.identity}".encode()
    ).hexdigest()[:24]
    return f"RAGBUILD-{token.upper()}"


def _provenance_fields(provenance: dict[str, Any]) -> tuple[Any, ...]:
    return (
        provenance.get("source_span_id"),
        provenance.get("reference_id"),
        provenance.get("origin", "unknown"),
        provenance.get("authority", "unknown"),
        provenance.get("layer", "unknown"),
        provenance.get("review_status", "unknown"),
        _canonical_json(provenance),
    )


def _insert_package_rows(
    connection: sqlite3.Connection,
    *,
    bundle: ExportBundleManifest,
    chunks: list[ExportChunk],
    nodes: list[ExportNode],
    edges: list[ExportEdge],
    semantic: dict[str, Any],
    build_id: str,
    profile: EmbeddingProfile,
    vectors: tuple[Any, ...],
) -> None:
    now = datetime.now(UTC).isoformat()
    profile_id = _profile_id(profile)
    node_by_id = {node.id: node for node in nodes}
    document_node = node_by_id.get(bundle.document_id)
    version_node = node_by_id.get(bundle.version_id)
    if document_node is None or version_node is None:
        raise RagBuildError("export graph is missing document or version identity")
    document_attributes = semantic.get("document", {})
    version_attributes = semantic.get("version", {})
    connection.execute(
        """INSERT INTO rag_builds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            build_id,
            bundle.run_id,
            bundle.bundle_id,
            bundle.document_id,
            bundle.version_id,
            bundle.source_digest,
            bundle.enhanced_digest,
            bundle.semantic_digest,
            profile.identity,
            "google",
            profile.backend,
            profile.model,
            "retrieval_document",
            profile.dimensions,
            profile.document_format_version,
            __version__,
            "building",
            None,
            now,
            None,
        ),
    )
    for name in ("chunks.jsonl", "nodes.jsonl", "edges.jsonl"):
        connection.execute(
            "INSERT INTO build_inputs VALUES (?, ?, ?, ?)",
            (build_id, name, bundle.artifact_digests[name], bundle.artifact_counts[name]),
        )
    connection.execute(
        """INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?)""",
        (
            bundle.document_id,
            document_node.canonical_name,
            str(document_attributes.get("document_type", "unknown")),
            str(document_attributes.get("namespace", "default")),
            bundle.source_digest,
            now,
        ),
    )
    effective = version_attributes.get("effective_dates") or {}
    connection.execute(
        """INSERT INTO document_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
        (
            bundle.version_id,
            bundle.document_id,
            str(version_attributes.get("version", bundle.version_id)),
            str(version_attributes.get("status", "approved")),
            effective.get("valid_from"),
            effective.get("valid_to"),
            bundle.source_digest,
            bundle.enhanced_digest,
            bundle.semantic_digest,
            str(version_attributes.get("confidentiality", "internal")),
            build_id,
            now,
        ),
    )

    semantic_sections = {
        str(value.get("section_id")): value
        for value in semantic.get("sections", [])
        if isinstance(value, dict) and value.get("section_id")
    }
    section_nodes = [node for node in nodes if node.entity_type is EntityType.SECTION]
    for source_ordinal, node in enumerate(section_nodes):
        section = semantic_sections.get(node.id, {})
        section_chunks = [chunk for chunk in chunks if chunk.section_id == node.id]
        text = str(section.get("body") or "\n\n".join(chunk.text for chunk in section_chunks))
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        path = next((chunk.section_path for chunk in section_chunks), [node.canonical_name])
        provenance = section.get("provenance") or [node.provenance.model_dump(mode="json")]
        connection.execute(
            """INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                bundle.version_id,
                node.id,
                section.get("parent_section_id") or node.attributes.get("parent_section_id"),
                int(section.get("order", node.attributes.get("order", source_ordinal))),
                _canonical_json(path),
                str(section.get("heading", node.canonical_name)),
                section.get("anchor") or node.attributes.get("anchor"),
                text,
                checksum,
                _canonical_json(provenance),
                _canonical_json(node.model_dump(mode="json")),
                source_ordinal,
            ),
        )

    for source_ordinal, node in enumerate(nodes):
        raw = node.model_dump(mode="json")
        provenance = raw["provenance"]
        validity = provenance.get("validity") or {}
        connection.execute(
            """INSERT INTO graph_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                node.id,
                node.entity_type.value,
                node.canonical_name,
                _canonical_json(node.attributes),
                node.layer.value,
                node.authority.value,
                node.review_status.value,
                validity.get("valid_from") or provenance.get("valid_from"),
                validity.get("valid_to") or provenance.get("valid_to"),
                _canonical_json(raw),
                source_ordinal,
            ),
        )
        connection.execute(
            "INSERT INTO graph_node_versions VALUES (?, ?)", (node.id, bundle.version_id)
        )
        for alias in sorted(set(node.aliases), key=str.casefold):
            connection.execute("INSERT INTO graph_aliases VALUES (?, ?)", (node.id, alias))
        connection.execute(
            """INSERT INTO graph_provenance(
                object_type, object_id, version_id, source_span_id, reference_id,
                origin, authority, layer, review_status, provenance_json
            ) VALUES ('node', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (node.id, bundle.version_id, *_provenance_fields(provenance)),
        )

    for source_ordinal, edge in enumerate(edges):
        raw = edge.model_dump(mode="json")
        provenance = raw["provenance"]
        validity = provenance.get("validity") or {}
        connection.execute(
            """INSERT INTO graph_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                edge.id,
                edge.source_id,
                edge.predicate.value,
                edge.target_id,
                edge.layer.value,
                edge.authority.value,
                edge.review_status.value,
                provenance.get("confidence"),
                validity.get("valid_from") or provenance.get("valid_from"),
                validity.get("valid_to") or provenance.get("valid_to"),
                _canonical_json(raw),
                source_ordinal,
            ),
        )
        connection.execute(
            "INSERT INTO graph_edge_versions VALUES (?, ?)", (edge.id, bundle.version_id)
        )
        connection.execute(
            """INSERT INTO graph_provenance(
                object_type, object_id, version_id, source_span_id, reference_id,
                origin, authority, layer, review_status, provenance_json
            ) VALUES ('edge', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (edge.id, bundle.version_id, *_provenance_fields(provenance)),
        )

    section_titles = {
        row["section_id"]: row["title"]
        for row in connection.execute("SELECT section_id, title FROM sections")
    }
    if len(vectors) != len(chunks):
        raise RagBuildError("embedding provider did not return one vector per approved chunk")
    for source_ordinal, (chunk, embedded) in enumerate(zip(chunks, vectors, strict=True)):
        raw = chunk.model_dump(mode="json")
        section_id = chunk.section_id
        if section_id is None or section_id not in section_titles:
            raise RagBuildError(f"chunk {chunk.chunk_id} does not resolve to an exported section")
        input_document = EmbeddingDocument(
            document_node.canonical_name, " / ".join(chunk.section_path), chunk.text
        )
        from document_enhancer.llm import format_document

        formatted = format_document(input_document)
        input_digest = hashlib.sha256(formatted.encode("utf-8")).hexdigest()
        blob, vector_digest, norm = encode_float32(embedded.vector, dimension=profile.dimensions)
        connection.execute(
            """INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chunk.chunk_id,
                chunk.document_id,
                chunk.version_id,
                section_id,
                chunk.ordinal,
                _canonical_json(chunk.section_path),
                section_titles[section_id],
                chunk.markdown_anchor,
                chunk.text,
                len(chunk.text.split()),
                chunk.checksum,
                _canonical_json(chunk.canonical_terms),
                _canonical_json(
                    {"object_ids": chunk.object_ids, "source_span_ids": chunk.source_span_ids}
                ),
                chunk.authority.value,
                chunk.review_status.value,
                chunk.security_classification,
                chunk.valid_from,
                chunk.valid_to,
                _canonical_json(raw),
                source_ordinal,
            ),
        )
        provenance_by_span = {
            item.source_span_id: item.model_dump(mode="json")
            for item in chunk.provenance
            if item.source_span_id
        }
        for span in sorted(set(chunk.source_span_ids)):
            connection.execute(
                "INSERT INTO chunk_source_spans VALUES (?, ?, ?)",
                (chunk.chunk_id, span, _canonical_json(provenance_by_span.get(span, {}))),
            )
        for node_id in sorted(set(chunk.object_ids)):
            if node_id not in node_by_id:
                raise RagBuildError(
                    f"chunk {chunk.chunk_id} references unknown graph node {node_id}"
                )
            connection.execute(
                "INSERT INTO chunk_entities VALUES (?, ?, 'mentions')", (chunk.chunk_id, node_id)
            )
        connection.execute(
            """INSERT INTO embeddings(
                object_type, object_id, rag_build_id, provider, backend, model, task_type,
                profile_id, dimension, dtype, byte_order, vector_encoding, vector_blob,
                vector_digest, input_digest, input_format_version, norm, normalized,
                selected, attempts, created_at
            ) VALUES ('chunk', ?, ?, 'google', ?, ?, 'retrieval_document', ?, ?,
                'float32', 'little', 'raw', ?, ?, ?, ?, ?, 0, 1, ?, ?)""",
            (
                chunk.chunk_id,
                build_id,
                profile.backend,
                profile.model,
                profile_id,
                profile.dimensions,
                blob,
                vector_digest,
                input_digest,
                profile.document_format_version,
                norm,
                embedded.attempts,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO chunk_vectors VALUES (?, ?, ?, ?, ?)",
            (chunk.chunk_id, profile_id, profile.dimensions, blob, vector_digest),
        )


def _raw_digest(connection: sqlite3.Connection, table: str) -> str:
    return _jsonl_digest(
        [
            str(row["raw_json"])
            for row in connection.execute(
                f"SELECT raw_json FROM {table} ORDER BY source_ordinal"  # noqa: S608
            )
        ]
    )


def verify_package(database: Path, *, export_dir: Path | None = None) -> PackageVerification:
    errors: list[str] = []
    row_counts: dict[str, int] = {}
    if not database.is_file():
        return PackageVerification(
            False, ("database does not exist",), {}, "missing", 0, 0, None, None
        )
    try:
        connection = connect(str(database))
    except sqlite3.Error as exc:
        return PackageVerification(
            False, (f"database open failed: {exc}",), {}, "failed", 0, 0, None, None
        )
    try:
        errors.extend(verify_migrations(connection))
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            errors.append(f"integrity_check returned {integrity}")
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        if foreign_keys:
            errors.append(f"foreign_key_check returned {len(foreign_keys)} violation(s)")
        for table in (
            "documents",
            "document_versions",
            "sections",
            "chunks",
            "chunk_source_spans",
            "chunk_entities",
            "graph_nodes",
            "graph_edges",
            "graph_aliases",
            "graph_provenance",
            "embeddings",
            "chunk_vectors",
            "chunks_fts",
        ):
            row_counts[table] = int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )  # noqa: S608
        builds = list(connection.execute("SELECT * FROM rag_builds"))
        if len(builds) != 1:
            errors.append("sealed package must contain exactly one RAG build")
            build = None
        else:
            build = builds[0]
            if build["status"] != "validated":
                errors.append("RAG build status is not validated")
        if row_counts.get("chunks") != row_counts.get("embeddings"):
            errors.append("approved chunk/embedding count mismatch")
        if row_counts.get("chunks") != row_counts.get("chunk_vectors"):
            errors.append("approved chunk/vector index count mismatch")
        if row_counts.get("chunks") != row_counts.get("chunks_fts"):
            errors.append("chunk/FTS row count mismatch")
        fts_mismatches = int(
            connection.execute(
                """SELECT COUNT(*) FROM chunks c LEFT JOIN chunks_fts f ON f.chunk_id = c.chunk_id
                WHERE f.chunk_id IS NULL OR f.text <> c.text OR f.section_path <> c.section_path
                   OR f.canonical_terms <> c.canonical_terms"""
            ).fetchone()[0]
        )
        if fts_mismatches:
            errors.append(f"FTS content parity failed for {fts_mismatches} chunk(s)")
        selected_mismatches = int(
            connection.execute(
                """SELECT COUNT(*) FROM chunks c LEFT JOIN embeddings e
                   ON e.object_id = c.chunk_id AND e.selected = 1
                   GROUP BY c.chunk_id HAVING COUNT(e.embedding_id) <> 1"""
            )
            .fetchall()
            .__len__()
        )
        if selected_mismatches:
            errors.append(
                f"selected embedding cardinality failed for {selected_mismatches} chunk(s)"
            )
        for row in connection.execute("SELECT * FROM embeddings"):
            try:
                values = decode_float32(bytes(row["vector_blob"]), dimension=int(row["dimension"]))
                if hashlib.sha256(bytes(row["vector_blob"])).hexdigest() != row["vector_digest"]:
                    raise ValueError("vector digest mismatch")
                if len(values) != int(row["dimension"]):
                    raise ValueError("decoded dimension mismatch")
            except ValueError as exc:
                errors.append(f"invalid vector for {row['object_id']}: {exc}")
        inputs = {
            str(row["artifact_name"]): (str(row["digest"]), int(row["row_count"]))
            for row in connection.execute("SELECT * FROM build_inputs")
        }
        for name, table in {
            "chunks.jsonl": "chunks",
            "nodes.jsonl": "graph_nodes",
            "edges.jsonl": "graph_edges",
        }.items():
            expected = inputs.get(name)
            if expected is None:
                errors.append(f"missing build input metadata for {name}")
            else:
                if row_counts[table] != expected[1]:
                    errors.append(f"database count mismatch for {name}")
                if _raw_digest(connection, table) != expected[0]:
                    errors.append(f"database row digest mismatch for {name}")
        if export_dir is not None:
            export_errors = validate_export_bundle(export_dir)
            errors.extend(f"export: {item}" for item in export_errors)
            for name, expected in inputs.items():
                path = export_dir / name
                if not path.is_file() or digest_file(path) != expected[0]:
                    errors.append(f"database/export digest mismatch for {name}")
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        return PackageVerification(
            not errors,
            tuple(sorted(set(errors))),
            row_counts,
            integrity,
            len(foreign_keys),
            schema_version,
            str(build["rag_build_id"]) if build else None,
            str(build["embedding_profile"]) if build else None,
        )
    except sqlite3.Error as exc:
        errors.append(f"database verification failed: {exc}")
        return PackageVerification(False, tuple(errors), row_counts, "failed", 0, 0, None, None)
    finally:
        connection.close()


def build_package(
    run_path: Path,
    *,
    adapter: GeminiEmbeddingAdapter | None = None,
    profile: EmbeddingProfile | None = None,
    max_attempts: int = 3,
    rate_limit_hook: Any | None = None,
) -> RagBuildManifest:
    run_path = run_path.expanduser().resolve()
    bundle, chunks, nodes, edges, semantic = _load_inputs(run_path)
    selected_profile = profile or (adapter.profile if adapter else EmbeddingProfile())
    if adapter is None:
        adapter = GeminiEmbeddingAdapter(
            profile=selected_profile,
            cache=ResponseCache(run_path / "rag/embedding-cache"),
        )
    elif adapter.profile.identity != selected_profile.identity:
        raise RagBuildError("embedding adapter/profile mismatch")
    build_id = _build_id(bundle, selected_profile)
    rag_dir = run_path / "rag"
    rag_dir.mkdir(parents=True, exist_ok=True)
    target = rag_dir / "document-rag.sqlite3"
    manifest_path = rag_dir / "build-manifest.json"
    if target.is_file() and manifest_path.is_file():
        existing = verify_package(target, export_dir=run_path / "export")
        old = RagBuildManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if existing.valid and old.rag_build_id == build_id:
            return old
    temporary = rag_dir / f".{build_id}.sqlite3.tmp"
    temporary.unlink(missing_ok=True)
    errors_path = rag_dir / "embedding-errors.jsonl"
    errors_path.unlink(missing_ok=True)
    try:
        documents = [
            EmbeddingDocument(
                next(node.canonical_name for node in nodes if node.id == bundle.document_id),
                " / ".join(chunk.section_path),
                chunk.text,
            )
            for chunk in chunks
        ]
        vectors = EmbeddingBatchRunner(
            adapter,
            max_attempts=max_attempts,
            rate_limit_hook=rate_limit_hook,
        ).embed(documents)
        connection = connect(str(temporary))
        try:
            migrate(connection)
            with connection:
                connection.execute("PRAGMA defer_foreign_keys = ON")
                _insert_package_rows(
                    connection,
                    bundle=bundle,
                    chunks=chunks,
                    nodes=nodes,
                    edges=edges,
                    semantic=semantic,
                    build_id=build_id,
                    profile=selected_profile,
                    vectors=vectors,
                )
                connection.execute(
                    "UPDATE rag_builds SET status='validated', validation_result='pending_file_verification', completed_at=? WHERE rag_build_id=?",
                    (datetime.now(UTC).isoformat(), build_id),
                )
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.commit()
        finally:
            connection.close()
        verification = verify_package(temporary, export_dir=run_path / "export")
        if not verification.valid:
            raise RagBuildError("package validation failed: " + "; ".join(verification.errors))
        temporary.chmod(0o600)
        atomic_promote(temporary, target)
        database_digest = digest_file(target)
        graph_layers = Counter(node.layer.value for node in nodes)
        manifest = RagBuildManifest(
            rag_build_id=build_id,
            document_id=bundle.document_id,
            version_id=bundle.version_id,
            database_schema_version=f"m7.rag.sqlite.v{SCHEMA_VERSION}",
            migration_version=str(SCHEMA_VERSION),
            input_digests={
                **bundle.artifact_digests,
                "enhanced.md": bundle.enhanced_digest,
                "enhanced.semantic.yaml": bundle.semantic_digest,
            },
            output_digests={"document-rag.sqlite3": database_digest},
            row_counts=verification.row_counts,
            fts_available=True,
            integrity_check_passed=True,
            foreign_key_check_passed=True,
            graph_layer_counts=dict(graph_layers),
            embedding_model=selected_profile.model,
            embedding_provider="google",
            embedding_backend=selected_profile.backend,
            embedding_task_type="retrieval_document",
            embedding_profile=selected_profile.identity,
            embedding_dimension=selected_profile.dimensions,
            embedding_input_format_version=selected_profile.document_format_version,
            embedding_batch_count=(
                adapter.last_manifest.batch_count if adapter.last_manifest else 0
            ),
            embedding_retry_count=sum(item.attempts - 1 for item in vectors),
            vector_count=len(vectors),
            failed_count=0,
            skipped_count=0,
            promotion_status="promoted",
            validation_passed=True,
        )
        atomic_write_json(manifest_path, manifest.model_dump(mode="json"))
        return manifest
    except Exception as exc:
        failed = rag_dir / f"failed-{build_id}.sqlite3"
        if temporary.exists():
            temporary.replace(failed)
            failed.chmod(0o600)
        error_record = {
            "schema_version": "m7.embedding-errors.v1",
            "rag_build_id": build_id,
            "error_type": type(exc).__name__,
            "retryable": isinstance(exc, (TimeoutError, ConnectionError)),
            "promoted": False,
        }
        errors_path.write_text(_canonical_json(error_record) + "\n", encoding="utf-8")
        errors_path.chmod(0o600)
        if isinstance(exc, RagBuildError):
            raise
        raise RagBuildError(
            f"RAG build failed; no package was promoted ({type(exc).__name__})"
        ) from exc


def inspect_package(database: Path) -> dict[str, object]:
    verification = verify_package(database)
    payload = verification.as_dict()
    if not database.is_file():
        return payload
    connection = connect(str(database))
    try:
        payload["documents"] = [
            dict(row)
            for row in connection.execute(
                """SELECT d.document_id, d.canonical_title, v.version_id, v.version_label,
                   v.status, v.confidentiality, v.is_current
                   FROM documents d JOIN document_versions v USING(document_id)
                   ORDER BY d.document_id, v.version_id"""
            )
        ]
        payload["graph_layer_counts"] = {
            str(row["layer"]): int(row["count"])
            for row in connection.execute(
                "SELECT layer, COUNT(*) AS count FROM graph_nodes GROUP BY layer ORDER BY layer"
            )
        }
    finally:
        connection.close()
    return payload


__all__ = [
    "PackageVerification",
    "RagBuildError",
    "build_package",
    "inspect_package",
    "verify_package",
]
