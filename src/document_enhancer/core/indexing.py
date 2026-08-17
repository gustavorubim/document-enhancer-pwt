"""Optional sealed-bundle indexing consumer (stdlib SQLite FTS).

Not part of the authoring critical path. Callers may index a sealed run after audit
passes; GraphRAG/RAG services should consume ``core.graph.v1`` exports instead of
importing ``CoreRunner``.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .integrity import (
    REQUIRED_SEAL_ARTIFACT_KEYS,
    IntegrityError,
    SealManifest,
    digest_bytes,
    validate_seal_manifest,
    verify_artifact,
)
from .layout import (
    AUDIT,
    FINAL_MARKDOWN,
    GRAPH_JSONL,
    ONTOLOGY,
    ORIGINAL_DOCUMENT_PREFIX,
    SEAL,
    SOURCE_TO_TARGET_CSV,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_MANIFEST_KEYS = REQUIRED_SEAL_ARTIFACT_KEYS


@dataclass(frozen=True, slots=True)
class SourceTargetLink:
    """One verified final-heading to canonical source-section relationship."""

    source_section_id: str
    source_title: str
    target_section_id: str
    target_heading: str
    disposition: str
    source_span_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SealedBundle:
    """Validated, provider-independent data exposed to optional consumers."""

    path: Path
    manifest: SealManifest
    run_id: str
    source_digest: str
    final_digest: str
    audit_digest: str
    graph_digest: str
    ontology_digest: str
    graph_schema: str
    final_markdown: str
    graph_jsonl: str
    graph: tuple[Mapping[str, Any], ...]
    ontology: Mapping[str, Any]
    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]
    sections: tuple[tuple[str, str], ...]
    source_targets: tuple[SourceTargetLink, ...]

    @property
    def graph_records(self) -> tuple[Mapping[str, Any], ...]:
        """Return the parsed canonical graph JSONL records."""

        return self.graph


def load_sealed_bundle(bundle: Path) -> SealedBundle:
    """Load and validate a passing, sealed bundle without importing the authoring runtime.

    Validation is intentionally fail-closed: the seal flag, audit status, digest fields,
    final output, and graph endpoints are all checked before a consumer can index them.
    A malformed or incomplete bundle raises ``ValueError``/``FileNotFoundError`` and does
    not create or mutate any consumer state.
    """

    resolved = _resolve_bundle(bundle)
    seal = _read_object(resolved / SEAL, "seal")
    manifest = _validated_manifest(seal)
    _validate_manifest_paths(manifest, resolved)
    manifest = _validated_manifest(manifest, artifact_root=resolved)

    source_ref = manifest.artifacts["source.original"]
    source_root = resolved / Path(ORIGINAL_DOCUMENT_PREFIX).parent
    source_path = resolved / source_ref.path
    source_candidates = [
        path for path in source_root.glob("original*") if path.is_file() and not path.is_symlink()
    ]
    if len(source_candidates) != 1 or source_candidates[0] != source_path:
        raise FileNotFoundError("core bundle must contain exactly one documents/original artifact")
    _read_verified_bytes(resolved, source_ref, key="source.original")

    final_ref = manifest.artifacts["output.final_markdown"]
    final_bytes = _read_verified_bytes(resolved, final_ref, key="output.final_markdown")
    try:
        final_markdown = final_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("final document artifact is not valid UTF-8") from exc

    audit = _read_object_bytes(
        _read_verified_bytes(resolved, manifest.artifacts["audit.report"], key="audit.report"),
        "audit",
    )
    if audit.get("status") != "pass":
        raise ValueError("only a passing core bundle may be consumed")

    ontology = _read_object_bytes(
        _read_verified_bytes(
            resolved, manifest.artifacts["output.ontology"], key="output.ontology"
        ),
        "ontology",
    )
    if _required_string(ontology, "schema_version", "ontology") != "core.graph.v1":
        raise ValueError("ontology artifact does not use core.graph.v1")
    if _required_digest(ontology, "markdown_sha256", "ontology") != manifest.final_digest:
        raise ValueError("ontology markdown digest does not match the sealed final document")
    nodes = _records(ontology, "nodes", "ontology")
    edges = _records(ontology, "edges", "ontology")
    node_ids = _validate_nodes(nodes)
    _validate_edges(edges, node_ids)

    graph_bytes = _read_verified_bytes(
        resolved, manifest.artifacts["output.graph"], key="output.graph"
    )
    try:
        graph_jsonl = graph_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("graph artifact is not valid UTF-8") from exc
    graph, graph_nodes, graph_edges = _parse_graph_jsonl(graph_jsonl)
    graph_node_ids = _validate_nodes(graph_nodes)
    _validate_edges(graph_edges, graph_node_ids)
    if graph_node_ids != node_ids or _edge_keys(graph_edges) != _edge_keys(edges):
        raise ValueError("graph and ontology exports do not describe the same graph")

    source_targets: tuple[SourceTargetLink, ...] = ()
    source_target_ref = manifest.artifacts.get("audit.source_to_target")
    if source_target_ref is not None:
        if source_target_ref.path != SOURCE_TO_TARGET_CSV:
            raise ValueError(
                f"sealed artifact audit.source_to_target must use canonical path "
                f"{SOURCE_TO_TARGET_CSV!r}"
            )
        source_target_bytes = _read_verified_bytes(
            resolved,
            source_target_ref,
            key="audit.source_to_target",
        )
        source_targets = _parse_source_targets(
            source_target_bytes,
            final_digest=manifest.final_digest,
            node_ids=node_ids,
        )

    sections = tuple(_chunks(final_markdown))
    return SealedBundle(
        path=resolved,
        manifest=manifest,
        run_id=manifest.run_id,
        source_digest=manifest.source_digest,
        final_digest=manifest.final_digest,
        audit_digest=manifest.audit_digest,
        graph_digest=manifest.graph_digest,
        ontology_digest=manifest.ontology_digest,
        graph_schema=_required_string(ontology, "schema_version", "ontology"),
        final_markdown=final_markdown,
        graph_jsonl=graph_jsonl,
        graph=tuple(graph),
        ontology=ontology,
        nodes=tuple(nodes),
        edges=tuple(edges),
        sections=sections,
        source_targets=source_targets,
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


def _resolve_bundle(bundle: Path) -> Path:
    candidate = bundle.expanduser()
    if candidate.is_symlink():
        raise ValueError("core bundle path must not be a symlink")
    resolved = candidate.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"core bundle does not exist: {resolved}")
    return resolved


def _validated_manifest(
    value: SealManifest | Mapping[str, object],
    *,
    artifact_root: Path | None = None,
) -> SealManifest:
    try:
        return validate_seal_manifest(value, artifact_root=artifact_root)
    except IntegrityError as exc:
        digest_labels = {
            "output.final_markdown": "final document",
            "audit.report": "audit",
            "output.graph": "graph",
            "output.ontology": "ontology",
            "source.original": "source",
        }
        key = exc.details.get("key")
        if exc.code == "artifact_digest_mismatch" and isinstance(key, str) and key in digest_labels:
            raise ValueError(
                f"{digest_labels[key]} digest does not match the sealed artifact"
            ) from exc
        raise ValueError(f"seal manifest is invalid: {exc}") from exc


def _validate_manifest_paths(manifest: SealManifest, bundle: Path) -> None:
    if manifest.run_id != bundle.name:
        raise ValueError("seal run_id does not match the bundle directory")
    missing = [key for key in _REQUIRED_MANIFEST_KEYS if key not in manifest.artifacts]
    if missing:
        raise ValueError("seal manifest is missing authoritative artifacts: " + ", ".join(missing))
    expected_paths = {
        "output.final_markdown": FINAL_MARKDOWN,
        "audit.report": AUDIT,
        "output.graph": GRAPH_JSONL,
        "output.ontology": ONTOLOGY,
    }
    for key, expected_path in expected_paths.items():
        reference = manifest.artifacts[key]
        if reference.path != expected_path:
            raise ValueError(f"sealed artifact {key} must use canonical path {expected_path!r}")
        if "draft" in Path(reference.path).parts:
            raise ValueError(f"sealed artifact {key} cannot reference a Stage 1 draft path")

    source_path = Path(manifest.artifacts["source.original"].path)
    source_prefix = Path(ORIGINAL_DOCUMENT_PREFIX)
    if source_path.parent != source_prefix.parent or (
        source_path.name != source_prefix.name
        and not source_path.name.startswith(f"{source_prefix.name}.")
    ):
        raise ValueError("sealed source artifact must use the documents/original path")


def _read_verified_bytes(root: Path, artifact: Any, *, key: str) -> bytes:
    try:
        reference = verify_artifact(root, artifact, key=key)
    except IntegrityError as exc:
        raise ValueError(f"{key} artifact failed integrity validation: {exc}") from exc
    path = root.expanduser().resolve() / reference.path
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{key} artifact cannot be read") from exc
    if len(data) != reference.size_bytes or digest_bytes(data) != reference.sha256:
        raise ValueError(f"{key} artifact changed while being read")
    return data


def _read_object_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} artifact is not valid JSON") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} artifact is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} artifact must be a JSON object")
    return cast(dict[str, Any], value)


def _parse_source_targets(
    raw: bytes,
    *,
    final_digest: str,
    node_ids: set[str],
) -> tuple[SourceTargetLink, ...]:
    """Parse either the current explicit linkage CSV or the historical four-column form."""

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("source-to-target artifact is not valid UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    current_fields = [
        "schema_version",
        "source_section_id",
        "source_title",
        "target_section_id",
        "target_heading",
        "disposition",
        "source_span_ids",
        "final_digest",
    ]
    legacy_fields = ["section_id", "title", "disposition", "final_digest"]
    if reader.fieldnames not in (current_fields, legacy_fields):
        raise ValueError("source-to-target artifact has an unsupported header")

    links: list[SourceTargetLink] = []
    for line_number, row in enumerate(reader, start=2):
        if row.get("final_digest") != final_digest:
            raise ValueError(
                f"source-to-target row {line_number} does not match the sealed final document"
            )
        if reader.fieldnames == legacy_fields:
            source_id = str(row.get("section_id") or "").strip()
            source_title = str(row.get("title") or "").strip()
            target_id = source_id
            target_heading = source_title
            spans: tuple[str, ...] = ()
        else:
            if row.get("schema_version") != "core.source-target.v2":
                raise ValueError(
                    f"source-to-target row {line_number} has an unsupported schema version"
                )
            source_id = str(row.get("source_section_id") or "").strip()
            source_title = str(row.get("source_title") or "").strip()
            target_id = str(row.get("target_section_id") or "").strip()
            target_heading = str(row.get("target_heading") or "").strip()
            try:
                span_values = json.loads(str(row.get("source_span_ids") or "[]"))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"source-to-target row {line_number} has invalid source_span_ids"
                ) from exc
            if not isinstance(span_values, list) or not all(
                isinstance(value, str) and value for value in span_values
            ):
                raise ValueError(
                    f"source-to-target row {line_number} source_span_ids must be strings"
                )
            spans = tuple(dict.fromkeys(str(value) for value in span_values))
        if source_id and source_id not in node_ids:
            raise ValueError(
                f"source-to-target row {line_number} references unknown source section {source_id!r}"
            )
        if bool(target_id) != bool(target_heading):
            raise ValueError(
                f"source-to-target row {line_number} must provide both target ID and heading"
            )
        links.append(
            SourceTargetLink(
                source_section_id=source_id,
                source_title=source_title,
                target_section_id=target_id,
                target_heading=target_heading,
                disposition=str(row.get("disposition") or "").strip(),
                source_span_ids=spans,
            )
        )
    return tuple(links)


def _parse_graph_jsonl(
    graph_jsonl: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for line_number, line in enumerate(graph_jsonl.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"graph artifact line {line_number} is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"graph artifact line {line_number} must be a JSON object")
        record = cast(dict[str, Any], value)
        kind = record.get("kind")
        if kind not in {"node", "edge"}:
            raise ValueError(f"graph artifact line {line_number} has an invalid kind")
        records.append(record)
        payload = {key: item for key, item in record.items() if key != "kind"}
        if kind == "node":
            nodes.append(payload)
        else:
            edges.append(payload)
    return records, nodes, edges


def _edge_keys(edges: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    return {(str(edge["source"]), str(edge["target"]), str(edge["edge_type"])) for edge in edges}


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError(f"{label} artifact must not be a symlink")
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{label} artifact is missing: {path}") from exc
    except OSError as exc:
        raise ValueError(f"{label} artifact cannot be read: {path}") from exc
    return _read_object_bytes(raw, label)


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


__all__ = ["CoreBundleIndex", "SealedBundle", "SourceTargetLink", "load_sealed_bundle"]
