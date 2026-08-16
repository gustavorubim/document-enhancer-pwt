from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from document_enhancer.core.integrity import build_seal_manifest, register_artifact
from document_enhancer.core.layout import AUDIT, FINAL_MARKDOWN, GRAPH_JSONL, ONTOLOGY, SEAL


def write_bundle(
    root: Path,
    run_id: str,
    final: str,
    *,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    audit_status: str = "pass",
) -> Path:
    bundle = root / run_id
    (bundle / AUDIT).parent.mkdir(parents=True)
    (bundle / FINAL_MARKDOWN).parent.mkdir(parents=True)
    (bundle / "documents").mkdir(parents=True)
    source = final.encode("utf-8")
    audit = {"schema_version": "core.audit.v1", "status": audit_status, "checks": {}}
    graph = {
        "schema_version": "core.graph.v1",
        "markdown_sha256": hashlib.sha256(final.encode()).hexdigest(),
        "nodes": nodes
        or [
            {
                "node_id": "sec-1",
                "label": "Overview",
                "node_type": "Section",
                "provenance_span_ids": [f"span-{run_id}"],
            }
        ],
        "edges": edges or [],
    }
    (bundle / "documents/original.md").write_bytes(source)
    (bundle / FINAL_MARKDOWN).write_text(final, encoding="utf-8")
    (bundle / ONTOLOGY).write_text(json.dumps(graph, sort_keys=True), encoding="utf-8")
    (bundle / GRAPH_JSONL).parent.mkdir(parents=True, exist_ok=True)
    graph_records = [{"kind": "node", **node} for node in graph["nodes"]] + [
        {"kind": "edge", **edge} for edge in graph["edges"]
    ]
    (bundle / GRAPH_JSONL).write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in graph_records),
        encoding="utf-8",
    )
    (bundle / AUDIT).write_text(json.dumps(audit, sort_keys=True), encoding="utf-8")
    artifacts = {
        "source.original": register_artifact(bundle, "documents/original.md"),
        "output.final_markdown": register_artifact(bundle, FINAL_MARKDOWN),
        "audit.report": register_artifact(bundle, AUDIT),
        "output.graph": register_artifact(bundle, GRAPH_JSONL),
        "output.ontology": register_artifact(bundle, ONTOLOGY),
    }
    seal = build_seal_manifest(
        run_id=run_id,
        source_digest=artifacts["source.original"].sha256,
        recipe_id="test-fixture",
        recipe_digest=hashlib.sha256(b"test-fixture-recipe").hexdigest(),
        configuration_digest=hashlib.sha256(b"test-fixture-configuration").hexdigest(),
        artifacts=artifacts,
        artifact_root=bundle,
    )
    (bundle / SEAL).write_text(
        json.dumps(seal.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
    )
    return bundle
