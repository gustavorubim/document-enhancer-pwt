"""Reconciled M7.7/M7.8 JSONL export bundle construction and validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from document_enhancer.artifacts.atomic import atomic_write_bytes, atomic_write_json, digest_file
from document_enhancer.contracts import Exporter
from document_enhancer.domain.audit import Audit
from document_enhancer.domain.run import (
    ExportBundle,
    ExportBundleManifest,
    ExportChunk,
    ExportEdge,
    ExportNode,
)
from document_enhancer.domain.semantic import SemanticDocument


def _jsonl(values: Sequence[BaseModel]) -> bytes:
    return b"".join(
        json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
        for value in values
    )


def _digest_payload(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_export_bundle(
    *,
    run_id: str,
    source_digest: str,
    semantic: SemanticDocument,
    chunks: tuple[ExportChunk, ...],
    audit: Audit,
) -> ExportBundle:
    """Create a success manifest only after audit passes and every row reconciles."""

    audit.assert_pass()
    excluded = set(semantic.provisional_ids) | {
        item.target_object_id for item in semantic.open_issues if item.target_object_id
    }
    entities = [semantic.document, semantic.version, *semantic.objects]
    nodes = [ExportNode.from_entity(item) for item in entities if item.id not in excluded]
    node_ids = {item.id for item in nodes}
    edges = [
        ExportEdge.from_relationship(item)
        for item in semantic.relationships
        if item.source_id in node_ids and item.target_id in node_ids
    ]
    chunk_rows = list(chunks)
    payloads = {
        "chunks.jsonl": _jsonl(chunk_rows),
        "nodes.jsonl": _jsonl(nodes),
        "edges.jsonl": _jsonl(edges),
    }
    enhanced_digest = semantic.version.enhanced_digest
    if enhanced_digest is None:
        raise ValueError("enhanced digest is required before export")
    semantic_digest = _digest_payload(semantic.model_dump(mode="json"))
    token = (
        hashlib.sha256((run_id + "\0" + semantic_digest + "\0" + enhanced_digest).encode())
        .hexdigest()[:16]
        .upper()
    )
    manifest = ExportBundleManifest(
        bundle_id=f"BUNDLE-{token}",
        document_id=semantic.document.id,
        version_id=semantic.version.id,
        schema_version="m7.export-bundle.v1",
        chunk_schema_version="m7.chunk.v1",
        graph_schema_version="m7.graph-jsonl.v1",
        run_id=run_id,
        source_digest=source_digest,
        enhanced_digest=enhanced_digest,
        semantic_digest=semantic_digest,
        reference_pack_id=semantic.reference_pack_id,
        reference_pack_version=semantic.reference_pack_version,
        ontology_version=semantic.ontology_version,
        generation_policy="approved-semantic-v1",
        chunks_count=len(chunk_rows),
        nodes_count=len(nodes),
        edges_count=len(edges),
        artifact_digests={
            name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()
        },
        artifact_counts={
            "chunks.jsonl": len(chunk_rows),
            "nodes.jsonl": len(nodes),
            "edges.jsonl": len(edges),
        },
        validation_errors=[],
        validation_passed=True,
        generated_at=semantic.generated_at,
    )
    return ExportBundle(manifest=manifest, chunks=chunk_rows, nodes=nodes, edges=edges)


def write_export_bundle(bundle: ExportBundle, directory: Path) -> None:
    """Atomically write rows first and the success manifest last."""

    if not bundle.manifest.validation_passed:
        raise ValueError("cannot write an invalid export bundle")
    directory.mkdir(parents=True, exist_ok=True)
    rows = {
        "chunks.jsonl": _jsonl(bundle.chunks),
        "nodes.jsonl": _jsonl(bundle.nodes),
        "edges.jsonl": _jsonl(bundle.edges),
    }
    for name, payload in rows.items():
        if hashlib.sha256(payload).hexdigest() != bundle.manifest.artifact_digests[name]:
            raise ValueError(f"refusing to write inconsistent {name}")
        atomic_write_bytes(directory / name, payload)
    atomic_write_json(directory / "bundle-manifest.json", bundle.manifest.model_dump(mode="json"))


def validate_export_bundle(directory: Path) -> tuple[str, ...]:
    """Recompute counts/digests and reject partial, stale, or invented success manifests."""

    manifest_path = directory / "bundle-manifest.json"
    if not manifest_path.is_file():
        return ("missing bundle-manifest.json",)
    try:
        manifest = ExportBundleManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        return (f"invalid bundle-manifest.json: {exc}",)
    errors: list[str] = []
    for name in ("chunks.jsonl", "nodes.jsonl", "edges.jsonl"):
        path = directory / name
        if not path.is_file():
            errors.append(f"missing {name}")
            continue
        if digest_file(path) != manifest.artifact_digests.get(name):
            errors.append(f"digest mismatch for {name}")
        try:
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        except (UnicodeError, json.JSONDecodeError):
            errors.append(f"invalid JSONL in {name}")
            continue
        if len(rows) != manifest.artifact_counts.get(name):
            errors.append(f"count mismatch for {name}")
    expected = {
        "chunks.jsonl": manifest.chunks_count,
        "nodes.jsonl": manifest.nodes_count,
        "edges.jsonl": manifest.edges_count,
    }
    for name, count in expected.items():
        if manifest.artifact_counts.get(name) != count:
            errors.append(f"manifest count mismatch for {name}")
    if not manifest.validation_passed:
        errors.append("bundle manifest is not validated")
    return tuple(sorted(set(errors)))


__all__ = ["Exporter", "build_export_bundle", "validate_export_bundle", "write_export_bundle"]
