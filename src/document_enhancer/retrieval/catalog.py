"""Atomic local FAISS, FTS5, and graph catalog for validated sealed bundles."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import threading
import uuid
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, cast

import faiss
import numpy as np
from langchain_core.embeddings import Embeddings

from document_enhancer.core.indexing import SealedBundle, load_sealed_bundle
from document_enhancer.core.layout import FINAL_MARKDOWN

from .chunking import CHUNKER_VERSION, chunk_markdown
from .embeddings import embedding_profile, format_document
from .models import EmbeddingProfile, GraphExpansion, GraphPath, RagChunk, RetrievalHit

CATALOG_SCHEMA = "document-enhancer.rag.catalog.v2"
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")
_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


class RagCatalogBuilder:
    """Build a complete catalog in staging and promote it only after validation."""

    def __init__(
        self,
        catalog_dir: Path,
        embeddings: Embeddings,
        *,
        chunk_size: int = 2400,
        chunk_overlap: int = 300,
    ) -> None:
        self.catalog_dir = catalog_dir.expanduser().resolve()
        self.embeddings = embeddings
        self.profile = embedding_profile(embeddings)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def build(self, bundles: Sequence[Path]) -> dict[str, object]:
        if not bundles:
            raise ValueError("at least one sealed bundle must be selected")
        snapshots = [load_sealed_bundle(path) for path in bundles]
        run_ids = [snapshot.run_id for snapshot in snapshots]
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("selected bundles contain duplicate run IDs")

        parent = self.catalog_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging = parent / f".{self.catalog_dir.name}.tmp-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            chunks, node_links, linking = self._prepare_chunks(snapshots)
            if not chunks:
                raise ValueError("selected bundles contain no indexable final text")
            self._write_sqlite(staging / "catalog.sqlite3", snapshots, chunks, node_links)
            self._write_faiss(staging / "faiss", chunks)
            manifest = self._manifest(staging, snapshots, chunks, node_links, linking)
            (staging / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            validated = RagCatalog.open(staging, self.embeddings)
            summary = validated.inspect()
            validated.close()
            self._promote(staging)
            return {**summary, "catalog": str(self.catalog_dir)}
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def _prepare_chunks(
        self, snapshots: Sequence[SealedBundle]
    ) -> tuple[list[RagChunk], dict[str, tuple[str, ...]], dict[str, int]]:
        all_chunks: list[RagChunk] = []
        node_links: dict[str, tuple[str, ...]] = {}
        linking = {
            "linked_chunks": 0,
            "unmatched_chunks": 0,
            "ambiguous_chunks": 0,
            "source_to_target_chunks": 0,
            "label_chunks": 0,
        }
        for snapshot in snapshots:
            markdown = (snapshot.path / FINAL_MARKDOWN).read_text(encoding="utf-8")
            chunks = chunk_markdown(
                markdown,
                run_id=snapshot.run_id,
                bundle_path=snapshot.path,
                source_digest=snapshot.source_digest,
                final_digest=snapshot.final_digest,
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )
            labels: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
            nodes_by_id: dict[str, Mapping[str, Any]] = {}
            for node in snapshot.nodes:
                labels[_normalized(str(node["label"]))].append(node)
                nodes_by_id[str(node["node_id"])] = node
            source_targets: dict[str, list[Any]] = defaultdict(list)
            for link in snapshot.source_targets:
                if link.target_section_id and link.target_heading:
                    source_targets[_normalized(link.target_heading)].append(link)
            for chunk in chunks:
                leaf = _normalized(chunk.heading_path[-1])
                linked: tuple[str, ...] = ()
                provenance: tuple[str, ...] = ()
                source_section_ids: tuple[str, ...] = ()
                target_section_id: str | None = None
                link_method = "none"
                explicit = source_targets.get(leaf, [])
                if explicit:
                    target_ids = tuple(dict.fromkeys(link.target_section_id for link in explicit))
                    if len(target_ids) == 1:
                        target_section_id = target_ids[0]
                        source_section_ids = tuple(
                            dict.fromkeys(
                                link.source_section_id
                                for link in explicit
                                if link.source_section_id
                            )
                        )
                        linked = tuple(
                            f"{snapshot.run_id}::{section_id}" for section_id in source_section_ids
                        )
                        provenance = tuple(
                            dict.fromkeys(
                                [span for link in explicit for span in link.source_span_ids]
                                + [
                                    str(span)
                                    for section_id in source_section_ids
                                    for span in cast(
                                        list[object],
                                        nodes_by_id[section_id].get("provenance_span_ids", []),
                                    )
                                ]
                            )
                        )
                        if linked:
                            linking["linked_chunks"] += 1
                            linking["source_to_target_chunks"] += 1
                            link_method = "source_to_target"
                        else:
                            linking["unmatched_chunks"] += 1
                    else:
                        linking["ambiguous_chunks"] += 1
                else:
                    matches = labels.get(leaf, [])
                    if len(matches) == 1:
                        linking["linked_chunks"] += 1
                        linking["label_chunks"] += 1
                        source_section_ids = (str(matches[0]["node_id"]),)
                        linked = (f"{snapshot.run_id}::{source_section_ids[0]}",)
                        provenance = tuple(
                            dict.fromkeys(
                                str(span)
                                for span in cast(
                                    list[object], matches[0].get("provenance_span_ids", [])
                                )
                            )
                        )
                        link_method = "label"
                    elif matches:
                        linking["ambiguous_chunks"] += 1
                    else:
                        linking["unmatched_chunks"] += 1
                enriched = chunk.model_copy(
                    update={
                        "target_section_id": target_section_id,
                        "source_section_ids": source_section_ids,
                        "link_method": link_method,
                        "graph_node_ids": linked,
                        "provenance_span_ids": provenance,
                    }
                )
                all_chunks.append(enriched)
                node_links[enriched.chunk_id] = linked
        return all_chunks, node_links, linking

    def _write_faiss(self, path: Path, chunks: Sequence[RagChunk]) -> None:
        inputs = [format_document(chunk.document_title, chunk.text) for chunk in chunks]
        vectors = self.embeddings.embed_documents(inputs)
        matrix = np.asarray(vectors, dtype="float32")
        if matrix.shape != (len(chunks), self.profile.dimensions):
            raise ValueError("embedding matrix does not match the catalog profile")
        faiss.normalize_L2(matrix)
        index = faiss.IndexFlatIP(self.profile.dimensions)
        index.add(matrix)
        path.mkdir(parents=True)
        faiss.write_index(index, str(path / "index.faiss"))

    def _write_sqlite(
        self,
        path: Path,
        snapshots: Sequence[SealedBundle],
        chunks: Sequence[RagChunk],
        node_links: Mapping[str, tuple[str, ...]],
    ) -> None:
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE bundles (
                    run_id TEXT PRIMARY KEY,
                    bundle_path TEXT NOT NULL,
                    source_digest TEXT NOT NULL,
                    final_digest TEXT NOT NULL,
                    audit_digest TEXT NOT NULL,
                    graph_schema TEXT NOT NULL
                );
                CREATE TABLE chunks (
                    chunk_id TEXT PRIMARY KEY,
                    vector_id INTEGER NOT NULL UNIQUE,
                    run_id TEXT NOT NULL REFERENCES bundles(run_id),
                    bundle_path TEXT NOT NULL,
                    source_digest TEXT NOT NULL,
                    final_digest TEXT NOT NULL,
                    document_title TEXT NOT NULL,
                    heading_path TEXT NOT NULL,
                    section_ordinal INTEGER NOT NULL,
                    chunk_ordinal INTEGER NOT NULL,
                    start_index INTEGER NOT NULL,
                    end_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    target_section_id TEXT,
                    source_section_ids TEXT NOT NULL,
                    link_method TEXT NOT NULL,
                    provenance_span_ids TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, text);
                CREATE TABLE nodes (
                    node_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES bundles(run_id),
                    original_node_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    provenance_span_ids TEXT NOT NULL,
                    UNIQUE(run_id, original_node_id)
                );
                CREATE TABLE edges (
                    run_id TEXT NOT NULL REFERENCES bundles(run_id),
                    source TEXT NOT NULL REFERENCES nodes(node_id),
                    target TEXT NOT NULL REFERENCES nodes(node_id),
                    edge_type TEXT NOT NULL,
                    provenance_span_ids TEXT NOT NULL
                );
                CREATE TABLE chunk_nodes (
                    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id),
                    node_id TEXT NOT NULL REFERENCES nodes(node_id),
                    PRIMARY KEY(chunk_id, node_id)
                );
                CREATE INDEX edge_source_idx ON edges(source);
                CREATE INDEX edge_target_idx ON edges(target);
                CREATE INDEX chunk_run_idx ON chunks(run_id);
                """
            )
            connection.executemany(
                "INSERT INTO bundles VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        snapshot.run_id,
                        str(snapshot.path),
                        snapshot.source_digest,
                        snapshot.final_digest,
                        snapshot.audit_digest,
                        snapshot.graph_schema,
                    )
                    for snapshot in snapshots
                ],
            )
            connection.executemany(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        chunk.chunk_id,
                        vector_id,
                        chunk.run_id,
                        chunk.bundle_path,
                        chunk.source_digest,
                        chunk.final_digest,
                        chunk.document_title,
                        json.dumps(chunk.heading_path),
                        chunk.section_ordinal,
                        chunk.chunk_ordinal,
                        chunk.start_index,
                        chunk.end_index,
                        chunk.text,
                        chunk.target_section_id,
                        json.dumps(chunk.source_section_ids),
                        chunk.link_method,
                        json.dumps(chunk.provenance_span_ids),
                    )
                    for vector_id, chunk in enumerate(chunks)
                ],
            )
            connection.executemany(
                "INSERT INTO chunks_fts(chunk_id, text) VALUES (?, ?)",
                [(chunk.chunk_id, chunk.text) for chunk in chunks],
            )
            for snapshot in snapshots:
                connection.executemany(
                    "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            f"{snapshot.run_id}::{node['node_id']}",
                            snapshot.run_id,
                            str(node["node_id"]),
                            str(node["label"]),
                            str(node["node_type"]),
                            json.dumps(node.get("provenance_span_ids", []), sort_keys=True),
                        )
                        for node in snapshot.nodes
                    ],
                )
                connection.executemany(
                    "INSERT INTO edges VALUES (?, ?, ?, ?, ?)",
                    [
                        (
                            snapshot.run_id,
                            f"{snapshot.run_id}::{edge['source']}",
                            f"{snapshot.run_id}::{edge['target']}",
                            str(edge["edge_type"]),
                            json.dumps(edge.get("provenance_span_ids", []), sort_keys=True),
                        )
                        for edge in snapshot.edges
                    ],
                )
            connection.executemany(
                "INSERT INTO chunk_nodes VALUES (?, ?)",
                [
                    (chunk_id, node_id)
                    for chunk_id, node_ids in node_links.items()
                    for node_id in node_ids
                ],
            )
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise ValueError("catalog contains foreign-key violations")

    def _manifest(
        self,
        staging: Path,
        snapshots: Sequence[SealedBundle],
        chunks: Sequence[RagChunk],
        node_links: Mapping[str, tuple[str, ...]],
        linking: Mapping[str, int],
    ) -> dict[str, object]:
        files = {
            relative: _sha256(staging / relative)
            for relative in ("catalog.sqlite3", "faiss/index.faiss")
        }
        return {
            "schema_version": CATALOG_SCHEMA,
            "embedding_profile": self.profile.model_dump(mode="json"),
            "chunking": {
                "version": CHUNKER_VERSION,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
            },
            "bundles": [
                {
                    "run_id": snapshot.run_id,
                    "path": str(snapshot.path),
                    "source_digest": snapshot.source_digest,
                    "final_digest": snapshot.final_digest,
                    "audit_digest": snapshot.audit_digest,
                }
                for snapshot in snapshots
            ],
            "counts": {
                "bundles": len(snapshots),
                "chunks": len(chunks),
                "nodes": sum(len(snapshot.nodes) for snapshot in snapshots),
                "edges": sum(len(snapshot.edges) for snapshot in snapshots),
                "chunk_node_links": sum(len(value) for value in node_links.values()),
            },
            "linking": dict(linking),
            "files": files,
        }

    def _promote(self, staging: Path) -> None:
        backup = self.catalog_dir.parent / f".{self.catalog_dir.name}.backup-{uuid.uuid4().hex}"
        had_catalog = self.catalog_dir.exists()
        if had_catalog:
            self.catalog_dir.replace(backup)
        try:
            staging.replace(self.catalog_dir)
        except BaseException:
            if had_catalog and backup.exists():
                backup.replace(self.catalog_dir)
            raise
        if backup.exists():
            shutil.rmtree(backup)


class RagCatalog:
    """Validated read-only view over one promoted local catalog."""

    def __init__(
        self,
        path: Path,
        manifest: Mapping[str, Any],
        connection: sqlite3.Connection,
        vector_index: Any,
        embeddings: Embeddings,
    ) -> None:
        self.path = path
        self.manifest = manifest
        self.connection = connection
        self.vector_index = vector_index
        self.embeddings = embeddings
        self._db_lock = threading.RLock()
        self.connection.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: Path, embeddings: Embeddings) -> RagCatalog:
        resolved = path.expanduser().resolve()
        manifest_path = resolved / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"RAG catalog does not exist: {resolved}")
        manifest = _read_object(manifest_path)
        if manifest.get("schema_version") != CATALOG_SCHEMA:
            raise ValueError("unsupported RAG catalog schema")
        expected_profile = embedding_profile(embeddings).model_dump(mode="json")
        if manifest.get("embedding_profile") != expected_profile:
            raise ValueError("embedding profile does not match the catalog")
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise ValueError("catalog manifest files must be an object")
        for relative, digest in files.items():
            if not isinstance(relative, str) or not isinstance(digest, str):
                raise ValueError("catalog manifest file entry is invalid")
            candidate = (resolved / relative).resolve()
            if not candidate.is_relative_to(resolved):
                raise ValueError("catalog manifest path escapes the catalog")
            if not candidate.is_file() or _sha256(candidate) != digest:
                raise ValueError(f"catalog artifact digest mismatch: {relative}")
        connection = sqlite3.connect(
            f"file:{resolved / 'catalog.sqlite3'}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        try:
            index = faiss.read_index(str(resolved / "faiss/index.faiss"))
            catalog = cls(resolved, manifest, connection, index, embeddings)
            catalog._validate_counts()
            return catalog
        except BaseException:
            connection.close()
            raise

    def close(self) -> None:
        with self._db_lock:
            self.connection.close()

    def __enter__(self) -> RagCatalog:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def inspect(self) -> dict[str, object]:
        counts = cast(dict[str, object], self.manifest["counts"])
        return {
            "schema_version": CATALOG_SCHEMA,
            "catalog": str(self.path),
            "embedding_profile": self.manifest["embedding_profile"],
            "chunking": self.manifest["chunking"],
            "counts": counts,
            "linking": self.manifest["linking"],
            "run_ids": [
                item["run_id"] for item in cast(list[dict[str, str]], self.manifest["bundles"])
            ],
            "catalog_digest": hashlib.sha256(
                json.dumps(self.manifest, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    def run_ids(self) -> tuple[str, ...]:
        """Return the catalog's explicit document versions in stable order."""

        return tuple(
            str(item["run_id"]) for item in cast(list[dict[str, str]], self.manifest["bundles"])
        )

    def chunks(self, *, run_ids: Sequence[str] | None = None) -> tuple[RagChunk, ...]:
        """Read every chunk for selected runs in deterministic document order."""

        with self._db_lock:
            allowed = set(run_ids or ())
            self._validate_run_ids(allowed)
            parameters: list[object] = []
            where = ""
            if allowed:
                placeholders = ",".join("?" for _ in allowed)
                where = f" WHERE run_id IN ({placeholders})"
                parameters.extend(sorted(allowed))
            rows = self.connection.execute(
                "SELECT chunk_id FROM chunks"
                f"{where} ORDER BY run_id, section_ordinal, chunk_ordinal, chunk_id",
                parameters,
            ).fetchall()
            return tuple(self._chunk(str(row["chunk_id"])) for row in rows)

    def graph_snapshot(self, *, run_ids: Sequence[str] | None = None) -> dict[str, object]:
        """Return a portable, read-only graph and linked-evidence snapshot for visualization."""

        with self._db_lock:
            allowed = set(run_ids or ())
            self._validate_run_ids(allowed)
            where = ""
            parameters: list[object] = []
            if allowed:
                placeholders = ",".join("?" for _ in allowed)
                where = f" WHERE run_id IN ({placeholders})"
                parameters.extend(sorted(allowed))
            node_rows = self.connection.execute(
                "SELECT node_id, run_id, original_node_id, label, node_type, provenance_span_ids "
                f"FROM nodes{where} ORDER BY run_id, node_id",
                parameters,
            ).fetchall()
            edge_rows = self.connection.execute(
                "SELECT run_id, source, target, edge_type, provenance_span_ids "
                f"FROM edges{where} ORDER BY run_id, source, target, edge_type",
                parameters,
            ).fetchall()
            document_rows = self.connection.execute(
                f"SELECT run_id, min(document_title) AS title FROM chunks{where} "
                "GROUP BY run_id ORDER BY run_id",
                parameters,
            ).fetchall()
            chunk_where = ""
            chunk_parameters: list[object] = []
            if allowed:
                placeholders = ",".join("?" for _ in allowed)
                chunk_where = f" WHERE c.run_id IN ({placeholders})"
                chunk_parameters.extend(sorted(allowed))
            chunk_rows = self.connection.execute(
                "SELECT cn.node_id, c.chunk_id, c.run_id, c.document_title, c.heading_path, c.text "
                "FROM chunk_nodes AS cn JOIN chunks AS c ON c.chunk_id = cn.chunk_id"
                f"{chunk_where} ORDER BY c.run_id, cn.node_id, c.section_ordinal, c.chunk_ordinal",
                chunk_parameters,
            ).fetchall()

            evidence: dict[str, list[dict[str, object]]] = defaultdict(list)
            documents = {str(row["run_id"]): str(row["title"]) for row in document_rows}
            for row in chunk_rows:
                text = " ".join(str(row["text"]).split())
                evidence[str(row["node_id"])].append(
                    {
                        "chunk_id": str(row["chunk_id"]),
                        "heading_path": json.loads(str(row["heading_path"])),
                        "excerpt": text[:360] + ("…" if len(text) > 360 else ""),
                    }
                )
            nodes = [
                {
                    "id": str(row["node_id"]),
                    "run_id": str(row["run_id"]),
                    "original_id": str(row["original_node_id"]),
                    "label": str(row["label"]),
                    "type": str(row["node_type"]),
                    "provenance_span_ids": json.loads(str(row["provenance_span_ids"])),
                    "evidence": evidence.get(str(row["node_id"]), []),
                }
                for row in node_rows
            ]
            edges = [
                {
                    "run_id": str(row["run_id"]),
                    "source": str(row["source"]),
                    "target": str(row["target"]),
                    "type": str(row["edge_type"]),
                    "provenance_span_ids": json.loads(str(row["provenance_span_ids"])),
                }
                for row in edge_rows
            ]
            return {
                "schema_version": "document-enhancer.graph-visualization.v1",
                "catalog_digest": self.inspect()["catalog_digest"],
                "documents": [
                    {"run_id": run_id, "title": title}
                    for run_id, title in sorted(documents.items())
                ],
                "nodes": nodes,
                "edges": edges,
                "counts": {
                    "documents": len(documents),
                    "nodes": len(nodes),
                    "edges": len(edges),
                    "linked_nodes": sum(bool(item["evidence"]) for item in nodes),
                },
            }

    def search(
        self,
        query: str,
        *,
        run_ids: Sequence[str] | None = None,
        limit: int = 6,
    ) -> list[RetrievalHit]:
        with self._db_lock:
            return self._search_unlocked(query, run_ids=run_ids, limit=limit)

    def _search_unlocked(
        self,
        query: str,
        *,
        run_ids: Sequence[str] | None = None,
        limit: int = 6,
    ) -> list[RetrievalHit]:
        query = query.strip()
        if not query:
            return []
        if limit <= 0:
            return []
        limit = min(limit, 20)
        allowed = set(run_ids or ())
        self._validate_run_ids(allowed)
        vector_rank: dict[str, int] = {}
        fetch = min(max(limit * 8, 24), 100)
        query_vector = np.asarray([self.embeddings.embed_query(query)], dtype="float32")
        faiss.normalize_L2(query_vector)
        _scores, positions = self.vector_index.search(query_vector, fetch)
        for position in positions[0]:
            if int(position) < 0:
                continue
            row = self.connection.execute(
                "SELECT chunk_id, run_id FROM chunks WHERE vector_id = ?", (int(position),)
            ).fetchone()
            if row is None:
                raise ValueError("FAISS index references an unknown vector ID")
            chunk_id = str(row["chunk_id"])
            run_id = str(row["run_id"])
            if not chunk_id or (allowed and run_id not in allowed):
                continue
            vector_rank.setdefault(chunk_id, len(vector_rank) + 1)

        lexical_rank = self._lexical_ranks(query, allowed, fetch)
        chunk_ids = set(vector_rank) | set(lexical_rank)
        ranked: list[tuple[float, str, tuple[str, ...], dict[str, int]]] = []
        for chunk_id in chunk_ids:
            ranks: dict[str, int] = {}
            if chunk_id in vector_rank:
                ranks["vector"] = vector_rank[chunk_id]
            if chunk_id in lexical_rank:
                ranks["lexical"] = lexical_rank[chunk_id]
            score = sum(1.0 / (60 + rank) for rank in ranks.values())
            ranked.append((score, chunk_id, tuple(sorted(ranks)), ranks))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [
            RetrievalHit(
                chunk=self._chunk(chunk_id),
                score=score,
                channels=channels,
                channel_ranks=ranks,
            )
            for score, chunk_id, channels, ranks in ranked[:limit]
        ]

    def expand_graph(
        self,
        node_ids: Sequence[str],
        *,
        depth: int = 1,
        run_ids: Sequence[str] | None = None,
        chunk_limit: int = 12,
    ) -> GraphExpansion:
        with self._db_lock:
            return self._expand_graph_unlocked(
                node_ids, depth=depth, run_ids=run_ids, chunk_limit=chunk_limit
            )

    def _expand_graph_unlocked(
        self,
        node_ids: Sequence[str],
        *,
        depth: int = 1,
        run_ids: Sequence[str] | None = None,
        chunk_limit: int = 12,
    ) -> GraphExpansion:
        if depth not in {1, 2}:
            raise ValueError("graph depth must be one or two")
        allowed = set(run_ids or ())
        self._validate_run_ids(allowed)
        seeds = tuple(dict.fromkeys(self._resolve_node_id(value, allowed) for value in node_ids))
        if not seeds:
            return GraphExpansion(seed_node_ids=(), reached_node_ids=(), paths=(), chunks=())
        parameters: list[object] = []
        where = ""
        if allowed:
            placeholders = ",".join("?" for _ in allowed)
            where = f" WHERE run_id IN ({placeholders})"
            parameters.extend(sorted(allowed))
        rows = self.connection.execute(
            f"SELECT source, target, edge_type FROM edges{where}", parameters
        ).fetchall()
        adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for row in rows:
            adjacency[str(row["source"])].append((str(row["target"]), str(row["edge_type"])))
            adjacency[str(row["target"])].append((str(row["source"]), str(row["edge_type"])))
        for values in adjacency.values():
            values.sort()

        reached = set(seeds)
        paths: list[GraphPath] = []
        queue: deque[tuple[str, tuple[str, ...], tuple[str, ...], int]] = deque(
            (seed, (seed,), (), 0) for seed in seeds
        )
        best_depth = {seed: 0 for seed in seeds}
        while queue:
            current, path_nodes, path_edges, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for neighbor, edge_type in adjacency.get(current, []):
                next_depth = current_depth + 1
                next_nodes = (*path_nodes, neighbor)
                next_edges = (*path_edges, edge_type)
                paths.append(GraphPath(node_ids=next_nodes, edge_types=next_edges))
                reached.add(neighbor)
                if next_depth < best_depth.get(neighbor, depth + 1):
                    best_depth[neighbor] = next_depth
                    queue.append((neighbor, next_nodes, next_edges, next_depth))
        paths = sorted(
            paths, key=lambda item: (len(item.edge_types), item.node_ids, item.edge_types)
        )
        reached_sorted = tuple(sorted(reached))
        placeholders = ",".join("?" for _ in reached_sorted)
        chunk_rows = self.connection.execute(
            f"SELECT DISTINCT chunk_id FROM chunk_nodes WHERE node_id IN ({placeholders}) "
            "ORDER BY chunk_id LIMIT ?",
            (*reached_sorted, min(max(chunk_limit, 0), 50)),
        ).fetchall()
        return GraphExpansion(
            seed_node_ids=seeds,
            reached_node_ids=reached_sorted,
            paths=tuple(paths),
            chunks=tuple(self._chunk(str(row["chunk_id"])) for row in chunk_rows),
        )

    def _validate_counts(self) -> None:
        expected = self.manifest.get("counts")
        if not isinstance(expected, dict):
            raise ValueError("catalog counts are missing")
        actual = {
            "bundles": self.connection.execute("SELECT count(*) FROM bundles").fetchone()[0],
            "chunks": self.connection.execute("SELECT count(*) FROM chunks").fetchone()[0],
            "nodes": self.connection.execute("SELECT count(*) FROM nodes").fetchone()[0],
            "edges": self.connection.execute("SELECT count(*) FROM edges").fetchone()[0],
            "chunk_node_links": self.connection.execute(
                "SELECT count(*) FROM chunk_nodes"
            ).fetchone()[0],
        }
        if actual != expected:
            raise ValueError("catalog row counts do not match the manifest")
        if int(self.vector_index.ntotal) != actual["chunks"]:
            raise ValueError("FAISS vector count does not match catalog chunks")
        fts_count = self.connection.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        if fts_count != actual["chunks"]:
            raise ValueError("FTS row count does not match catalog chunks")

    def _lexical_ranks(self, query: str, allowed: set[str], limit: int) -> dict[str, int]:
        tokens = list(dict.fromkeys(_TOKEN_RE.findall(query.lower())))
        if not tokens:
            return {}
        expression = " OR ".join(f'"{token}"' for token in tokens[:20])
        parameters: list[object] = [expression]
        where = ""
        if allowed:
            placeholders = ",".join("?" for _ in allowed)
            where = f" AND c.run_id IN ({placeholders})"
            parameters.extend(sorted(allowed))
        parameters.append(limit)
        rows = self.connection.execute(
            "SELECT f.chunk_id FROM chunks_fts AS f JOIN chunks AS c ON c.chunk_id=f.chunk_id "
            f"WHERE chunks_fts MATCH ?{where} ORDER BY bm25(chunks_fts), f.chunk_id LIMIT ?",
            parameters,
        ).fetchall()
        return {str(row["chunk_id"]): rank for rank, row in enumerate(rows, 1)}

    def _chunk(self, chunk_id: str) -> RagChunk:
        row = self.connection.execute(
            "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"catalog references unknown chunk: {chunk_id}")
        node_rows = self.connection.execute(
            "SELECT node_id FROM chunk_nodes WHERE chunk_id = ? ORDER BY node_id", (chunk_id,)
        ).fetchall()
        link_method = str(row["link_method"])
        if link_method not in {"none", "source_to_target", "label"}:
            raise ValueError(f"catalog chunk has invalid link method: {link_method}")
        return RagChunk(
            chunk_id=str(row["chunk_id"]),
            run_id=str(row["run_id"]),
            bundle_path=str(row["bundle_path"]),
            source_digest=str(row["source_digest"]),
            final_digest=str(row["final_digest"]),
            document_title=str(row["document_title"]),
            heading_path=tuple(json.loads(str(row["heading_path"]))),
            section_ordinal=int(row["section_ordinal"]),
            chunk_ordinal=int(row["chunk_ordinal"]),
            start_index=int(row["start_index"]),
            end_index=int(row["end_index"]),
            text=str(row["text"]),
            target_section_id=(
                str(row["target_section_id"]) if row["target_section_id"] is not None else None
            ),
            source_section_ids=tuple(json.loads(str(row["source_section_ids"]))),
            link_method=cast(
                Literal["none", "source_to_target", "label"],
                link_method,
            ),
            graph_node_ids=tuple(str(item["node_id"]) for item in node_rows),
            provenance_span_ids=tuple(json.loads(str(row["provenance_span_ids"]))),
        )

    def _validate_run_ids(self, run_ids: set[str]) -> None:
        if not run_ids:
            return
        rows = self.connection.execute("SELECT run_id FROM bundles").fetchall()
        known = {str(row["run_id"]) for row in rows}
        unknown = sorted(run_ids - known)
        if unknown:
            raise ValueError("run filter is not indexed: " + ", ".join(unknown))

    def _resolve_node_id(self, value: str, allowed: set[str]) -> str:
        value = value.strip()
        if not value:
            raise ValueError("graph node ID cannot be empty")
        if "::" in value:
            row = self.connection.execute(
                "SELECT run_id FROM nodes WHERE node_id = ?", (value,)
            ).fetchone()
            if row is None or (allowed and str(row["run_id"]) not in allowed):
                raise ValueError(f"graph node is not indexed: {value}")
            return value
        parameters: list[object] = [value]
        where = "original_node_id = ?"
        if allowed:
            placeholders = ",".join("?" for _ in allowed)
            where += f" AND run_id IN ({placeholders})"
            parameters.extend(sorted(allowed))
        rows = self.connection.execute(
            f"SELECT node_id FROM nodes WHERE {where} ORDER BY node_id", parameters
        ).fetchall()
        if not rows:
            raise ValueError(f"graph node is not indexed: {value}")
        if len(rows) != 1:
            raise ValueError(f"graph node ID is ambiguous; use a namespaced ID: {value}")
        return str(rows[0]["node_id"])


def resolve_bundle_paths(
    run_root: Path, run_ids: Sequence[str], *, all_sealed: bool = False
) -> list[Path]:
    root = run_root.expanduser().resolve()
    if all_sealed and run_ids:
        raise ValueError("provide run IDs or --all-sealed, not both")
    if not all_sealed and not run_ids:
        raise ValueError("provide at least one run ID or --all-sealed")
    if all_sealed:
        candidates = (
            sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []
        )
        accepted: list[Path] = []
        for candidate in candidates:
            try:
                load_sealed_bundle(candidate)
            except (FileNotFoundError, ValueError):
                continue
            accepted.append(candidate)
        if not accepted:
            raise ValueError("no sealed bundles were found")
        return accepted
    paths: list[Path] = []
    for run_id in dict.fromkeys(run_ids):
        if not run_id or Path(run_id).name != run_id:
            raise ValueError(f"invalid run ID: {run_id!r}")
        paths.append(root / run_id)
    return paths


def read_catalog_profile(path: Path) -> EmbeddingProfile:
    resolved = path.expanduser().resolve()
    manifest = _read_object(resolved / "manifest.json")
    if manifest.get("schema_version") != CATALOG_SCHEMA:
        raise ValueError("unsupported RAG catalog schema")
    return EmbeddingProfile.model_validate(manifest.get("embedding_profile"))


def _normalized(value: str) -> str:
    return _NORMALIZE_RE.sub(" ", value.lower()).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("RAG catalog manifest is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("RAG catalog manifest must be an object")
    return cast(dict[str, Any], value)


__all__ = [
    "CATALOG_SCHEMA",
    "RagCatalog",
    "RagCatalogBuilder",
    "read_catalog_profile",
    "resolve_bundle_paths",
]
