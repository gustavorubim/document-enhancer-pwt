from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from document_enhancer.core.layout import AUDIT, FINAL_MARKDOWN, ONTOLOGY, SEAL


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
    (bundle / AUDIT).write_text(json.dumps(audit, sort_keys=True), encoding="utf-8")
    seal = {
        "run_id": run_id,
        "source_digest": hashlib.sha256(source).hexdigest(),
        "final_digest": hashlib.sha256(final.encode()).hexdigest(),
        "audit_digest": hashlib.sha256((bundle / AUDIT).read_bytes()).hexdigest(),
        "artifact_paths": [AUDIT, FINAL_MARKDOWN, ONTOLOGY],
        "sealed": True,
    }
    (bundle / SEAL).write_text(json.dumps(seal, sort_keys=True), encoding="utf-8")
    return bundle
