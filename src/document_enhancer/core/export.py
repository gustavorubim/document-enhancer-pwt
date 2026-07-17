"""Small, provider-independent graph export contract for optional indexers."""

from __future__ import annotations

import json
from typing import Any

from .models import DocumentIR


def public_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Normalize a core IR payload into the stable graph/indexer boundary."""

    ir = DocumentIR.model_validate(graph)
    return {
        "schema_version": "core.graph.v1",
        "markdown_sha256": ir.markdown_sha256,
        "nodes": [item.model_dump(mode="json") for item in ir.nodes],
        "edges": [item.model_dump(mode="json") for item in ir.edges],
    }


def public_graph_jsonl(graph: dict[str, Any]) -> str:
    """Return one generic node/edge record per line for optional indexers."""

    payload = public_graph(graph)
    lines = [json.dumps({"kind": "node", **node}, sort_keys=True) for node in payload["nodes"]]
    lines.extend(json.dumps({"kind": "edge", **edge}, sort_keys=True) for edge in payload["edges"])
    return "\n".join(lines) + ("\n" if lines else "")


__all__ = ["public_graph", "public_graph_jsonl"]
