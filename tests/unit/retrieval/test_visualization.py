from __future__ import annotations

from pathlib import Path

import pytest

from document_enhancer.retrieval.visualization import write_graph_html


@pytest.mark.unit
def test_graph_html_escapes_untrusted_data_and_requires_force(tmp_path: Path) -> None:
    snapshot: dict[str, object] = {
        "schema_version": "document-enhancer.graph-visualization.v1",
        "catalog_digest": "a" * 64,
        "documents": [{"run_id": "run-a", "title": "Alpha"}],
        "nodes": [
            {
                "id": "run-a::node-1",
                "run_id": "run-a",
                "original_id": "node-1",
                "label": "</script><script>alert(1)</script>",
                "type": "Control",
                "provenance_span_ids": ["span-1"],
                "evidence": [],
            }
        ],
        "edges": [],
        "counts": {"documents": 1, "nodes": 1, "edges": 0, "linked_nodes": 0},
    }
    output = tmp_path / "nested" / "graph.html"

    payload = write_graph_html(snapshot, output)

    html = output.read_text(encoding="utf-8")
    assert payload["size_bytes"] == output.stat().st_size
    assert payload["self_contained"] is True
    assert "__GRAPH_DATA__" not in html
    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script\\u003e" in html
    assert "<script src=" not in html
    assert "https://" not in html and "http://" not in html
    with pytest.raises(ValueError, match="pass --force"):
        write_graph_html(snapshot, output)
    write_graph_html(snapshot, output, force=True)
