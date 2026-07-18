"""Optional sealed-bundle indexing consumer (stdlib SQLite FTS).

Not part of the authoring critical path. Callers may index a sealed run after audit
passes; GraphRAG/RAG services should consume ``core.graph.v1`` exports instead of
importing ``CoreRunner``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .layout import AUDIT, FINAL_MARKDOWN, ONTOLOGY, ORIGINAL_DOCUMENT_PREFIX, SEAL

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_ARTIFACTS = (AUDIT, FINAL_MARKDOWN, ONTOLOGY)


@dataclass(frozen=True, slots=True)
class SealedBundle:
    """Validated, provider-independent data exposed to optional consumers."""

    path: Path
    run_id: str
    source_digest: str
    final_digest: str
    audit_digest: str
    graph_schema: str
    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]
    sections: tuple[tuple[str, str], ...]


def load_sealed_bundle(bundle: Path) -> SealedBundle:
    """Load and validate a passing, sealed bundle without importing the authoring runtime.

    Validation is intentionally fail-closed: the seal flag, audit status, digest fields,
    final output, and graph endpoints are all checked before a consumer can index them.
    A malformed or incomplete bundle raises ``ValueError``/``FileNotFoundError`` and does
    not create or mutate any consumer state.
    """

    resolved = bundle.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"core bundle does not exist: {resolved}")
    seal = _read_object(resolved / SEAL, "seal")
    if seal.get("sealed") is not True:
        raise ValueError("core bundle is not sealed")
    run_id = _required_string(seal, "run_id", "seal")
    source_digest = _required_digest(seal, "source_digest", "seal")
    final_digest = _required_digest(seal, "final_digest", "seal")
    audit_digest = _required_digest(seal, "audit_digest", "seal")

    missing = [path for path in _REQUIRED_ARTIFACTS if not (resolved / path).is_file()]
    if missing:
        raise FileNotFoundError("core bundle is missing: " + ", ".join(missing))
    artifact_paths = seal.get("artifact_paths")
    if artifact_paths is not None:
        if not isinstance(artifact_paths, list) or not all(
            isinstance(path, str) for path in artifact_paths
        ):
            raise ValueError("seal artifact_paths must be a list of strings")
        omitted = [path for path in _REQUIRED_ARTIFACTS if path not in artifact_paths]
        if omitted:
            raise ValueError("seal does not list required artifacts: " + ", ".join(omitted))

    audit_path = resolved / AUDIT
    final_path = resolved / FINAL_MARKDOWN
    audit = _read_object(audit_path, "audit")
    if audit.get("status") != "pass":
        raise ValueError("only a passing core bundle may be consumed")
    if _sha256(audit_path) != audit_digest:
        raise ValueError("audit digest does not match the sealed artifact")
    if _sha256(final_path) != final_digest:
        raise ValueError("final document digest does not match the sealed artifact")

    source_root = resolved / Path(ORIGINAL_DOCUMENT_PREFIX).parent
    source_candidates = [path for path in source_root.glob("original*") if path.is_file()]
    if len(source_candidates) != 1:
        raise FileNotFoundError("core bundle must contain exactly one documents/original artifact")
    if _sha256(source_candidates[0]) != source_digest:
        raise ValueError("source digest does not match the sealed artifact")

    graph = _read_object(resolved / ONTOLOGY, "ontology")
    nodes = _records(graph, "nodes", "ontology")
    edges = _records(graph, "edges", "ontology")
    node_ids = _validate_nodes(nodes)
    _validate_edges(edges, node_ids)
    sections = tuple(_chunks(final_path.read_text(encoding="utf-8")))
    return SealedBundle(
        path=resolved,
        run_id=run_id,
        source_digest=source_digest,
        final_digest=final_digest,
        audit_digest=audit_digest,
        graph_schema=_required_string(graph, "schema_version", "ontology"),
        nodes=tuple(nodes),
        edges=tuple(edges),
        sections=sections,
    )


class CoreBundleIndex:
    """Optional SQLite FTS/index adapter for :func:`load_sealed_bundle`.

    Construction is lazy and side-effect free.  SQLite is opened for writing only by
    :meth:`index`, and read-only by :meth:`search`; merely authoring a document never
    creates a catalog or depends on this class.
    """

    def __init__(self, database: Path) -> None:
        self.database = database.expanduser().resolve()

    def index(self, bundle: Path) -> int:
        """Replace this bundle's rows with a validated sealed snapshot."""

        snapshot = load_sealed_bundle(bundle)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS bundles (
                    bundle TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    graph_schema TEXT NOT NULL,
                    source_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS nodes (
                    bundle TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    PRIMARY KEY (bundle, node_id)
                );
                CREATE TABLE IF NOT EXISTS edges (
                    bundle TEXT NOT NULL,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    provenance TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
                    bundle UNINDEXED, section_id UNINDEXED, text
                );
                """
            )
            bundle_key = str(snapshot.path)
            connection.execute("DELETE FROM bundles WHERE bundle = ?", (bundle_key,))
            connection.execute("DELETE FROM nodes WHERE bundle = ?", (bundle_key,))
            connection.execute("DELETE FROM edges WHERE bundle = ?", (bundle_key,))
            connection.execute("DELETE FROM chunks WHERE bundle = ?", (bundle_key,))
            connection.execute(
                "INSERT INTO bundles(bundle, run_id, graph_schema, source_digest) VALUES (?, ?, ?, ?)",
                (bundle_key, snapshot.run_id, snapshot.graph_schema, snapshot.source_digest),
            )
            connection.executemany(
                "INSERT INTO nodes(bundle, node_id, label, node_type, provenance) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        bundle_key,
                        str(node["node_id"]),
                        str(node["label"]),
                        str(node["node_type"]),
                        json.dumps(node.get("provenance_span_ids", []), sort_keys=True),
                    )
                    for node in snapshot.nodes
                ],
            )
            connection.executemany(
                "INSERT INTO edges(bundle, source, target, edge_type, provenance) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        bundle_key,
                        str(edge["source"]),
                        str(edge["target"]),
                        str(edge["edge_type"]),
                        json.dumps(edge.get("provenance_span_ids", []), sort_keys=True),
                    )
                    for edge in snapshot.edges
                ],
            )
            connection.executemany(
                "INSERT INTO chunks(bundle, section_id, text) VALUES (?, ?, ?)",
                [(bundle_key, section_id, text) for section_id, text in snapshot.sections],
            )
        return len(snapshot.sections)

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Search indexed final sections; an absent optional index returns no results."""

        if not query.strip() or limit <= 0 or not self.database.is_file():
            return []
        bounded_limit = min(limit, 100)
        try:
            with sqlite3.connect(self._readonly_uri(), uri=True) as connection:
                rows = connection.execute(
                    "SELECT bundle, section_id, text FROM chunks WHERE chunks MATCH ? LIMIT ?",
                    (query, bounded_limit),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError("invalid search query") from exc
        return [{"bundle": row[0], "section_id": row[1], "text": row[2]} for row in rows]

    def _readonly_uri(self) -> str:
        return f"file:{self.database}?mode=ro"


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{label} artifact is missing: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} artifact is not valid JSON") from exc
    except OSError as exc:
        raise ValueError(f"{label} artifact cannot be read: {path}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} artifact is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} artifact must be a JSON object")
    return cast(dict[str, Any], value)


def _required_string(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} field {key!r} must be a non-empty string")
    return value


def _required_digest(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = _required_string(payload, key, label)
    if not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{label} field {key!r} must be a sha256 digest")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _records(payload: Mapping[str, Any], key: str, label: str) -> list[dict[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{label} field {key!r} must be a list of objects")
    return [cast(dict[str, Any], item) for item in value]


def _validate_nodes(nodes: list[dict[str, Any]]) -> set[str]:
    node_ids: set[str] = set()
    for node in nodes:
        for key in ("node_id", "label", "node_type"):
            _required_string(node, key, "ontology node")
        node_id = str(node["node_id"])
        if node_id in node_ids:
            raise ValueError(f"ontology contains duplicate node {node_id!r}")
        node_ids.add(node_id)
        provenance = node.get("provenance_span_ids", [])
        if not isinstance(provenance, list) or not all(
            isinstance(item, str) for item in provenance
        ):
            raise ValueError("ontology node provenance_span_ids must be a list of strings")
    return node_ids


def _validate_edges(edges: list[dict[str, Any]], node_ids: set[str]) -> None:
    for edge in edges:
        for key in ("source", "target", "edge_type"):
            _required_string(edge, key, "ontology edge")
        if str(edge["source"]) not in node_ids or str(edge["target"]) not in node_ids:
            raise ValueError("ontology edge references an unknown node")
        provenance = edge.get("provenance_span_ids", [])
        if not isinstance(provenance, list) or not all(
            isinstance(item, str) for item in provenance
        ):
            raise ValueError("ontology edge provenance_span_ids must be a list of strings")


def _chunks(markdown: str) -> list[tuple[str, str]]:
    headings = list(re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", markdown))
    if not headings:
        return [("document", markdown.strip())] if markdown.strip() else []
    chunks: list[tuple[str, str]] = []
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        text = markdown[match.start() : end].strip()
        section_id = (
            re.sub(r"[^a-z0-9]+", "-", match.group(1).lower()).strip("-") or f"section-{index + 1}"
        )
        if text:
            chunks.append((section_id, text))
    return chunks


__all__ = ["CoreBundleIndex", "SealedBundle", "load_sealed_bundle"]
