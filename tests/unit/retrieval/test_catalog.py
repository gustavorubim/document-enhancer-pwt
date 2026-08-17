from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest

from document_enhancer.core.layout import FINAL_MARKDOWN
from document_enhancer.retrieval.catalog import (
    RagCatalog,
    RagCatalogBuilder,
    read_catalog_profile,
    resolve_bundle_paths,
)
from document_enhancer.retrieval.embeddings import (
    DeterministicEmbeddings,
    IdentityEmbeddings,
)

from .helpers import write_bundle


def _corpus(tmp_path: Path) -> tuple[Path, Path]:
    nodes = [
        {
            "node_id": "sec-overview",
            "label": "Overview",
            "node_type": "Section",
            "provenance_span_ids": ["span-overview"],
        },
        {
            "node_id": "sec-controls",
            "label": "Controls",
            "node_type": "Control",
            "provenance_span_ids": ["span-controls"],
        },
    ]
    edges = [
        {
            "source": "sec-overview",
            "target": "sec-controls",
            "edge_type": "governed_by",
            "provenance_span_ids": ["span-edge"],
        }
    ]
    first = write_bundle(
        tmp_path / "runs",
        "run-a",
        "# Alpha Process\n\n## Overview\n\nAlpha is governed by POL-42.\n\n"
        "## Controls\n\nThe control owner records each review.\n",
        nodes=nodes,
        edges=edges,
    )
    second = write_bundle(
        tmp_path / "runs",
        "run-b",
        "# POL-42\n\n## Overview\n\nPOL-42 requires a monthly review by the Risk Committee.\n",
        nodes=[nodes[0]],
    )
    return first, second


@pytest.mark.unit
def test_atomic_catalog_hybrid_search_namespaces_graph_and_filters(tmp_path: Path) -> None:
    first, second = _corpus(tmp_path)
    catalog_path = tmp_path / "rag" / "catalog"
    embeddings = DeterministicEmbeddings()

    summary = RagCatalogBuilder(catalog_path, embeddings).build([first, second])

    assert summary["counts"] == {
        "bundles": 2,
        "chunks": 5,
        "nodes": 3,
        "edges": 1,
        "chunk_node_links": 3,
    }
    assert (catalog_path / "faiss/index.faiss").is_file()
    assert (catalog_path / "catalog.sqlite3").is_file()
    assert summary["linking"] == {
        "linked_chunks": 3,
        "unmatched_chunks": 2,
        "ambiguous_chunks": 0,
        "source_to_target_chunks": 0,
        "label_chunks": 3,
    }
    with RagCatalog.open(catalog_path, embeddings) as catalog:
        exact = catalog.search("POL-42 monthly review", limit=5)
        assert exact[0].chunk.run_id == "run-b"
        assert {channel for hit in exact for channel in hit.channels} == {"lexical", "vector"}
        filtered = catalog.search("review", run_ids=["run-a"], limit=5)
        assert filtered and {item.chunk.run_id for item in filtered} == {"run-a"}
        expansion = catalog.expand_graph(["run-a::sec-overview"], depth=1)
        assert "run-a::sec-controls" in expansion.reached_node_ids
        assert expansion.paths[0].edge_types == ("governed_by",)
        assert {item.run_id for item in expansion.chunks} == {"run-a"}
        with pytest.raises(ValueError, match="ambiguous"):
            catalog.expand_graph(["sec-overview"])
        with pytest.raises(ValueError, match="one or two"):
            catalog.expand_graph(["run-a::sec-overview"], depth=3)


@pytest.mark.unit
def test_graph_snapshot_is_portable_evidence_linked_and_filterable(tmp_path: Path) -> None:
    first, second = _corpus(tmp_path)
    path = tmp_path / "catalog"
    embeddings = DeterministicEmbeddings()
    RagCatalogBuilder(path, embeddings).build([first, second])

    with RagCatalog.open(path, embeddings) as catalog:
        complete = catalog.graph_snapshot()
        filtered = catalog.graph_snapshot(run_ids=["run-a"])
        with pytest.raises(ValueError, match="not indexed"):
            catalog.graph_snapshot(run_ids=["missing"])

    assert complete["schema_version"] == "document-enhancer.graph-visualization.v1"
    assert complete["counts"] == {
        "documents": 2,
        "nodes": 3,
        "edges": 1,
        "linked_nodes": 3,
    }
    nodes = cast(list[dict[str, Any]], complete["nodes"])
    control = next(item for item in nodes if item["id"] == "run-a::sec-controls")
    assert control["type"] == "Control"
    assert control["evidence"][0]["heading_path"] == ["Alpha Process", "Controls"]
    assert "control owner" in control["evidence"][0]["excerpt"]
    assert filtered["counts"] == {
        "documents": 1,
        "nodes": 2,
        "edges": 1,
        "linked_nodes": 2,
    }
    documents = cast(list[dict[str, Any]], filtered["documents"])
    assert {item["run_id"] for item in documents} == {"run-a"}


@pytest.mark.unit
def test_tampered_bundle_cannot_replace_promoted_catalog(tmp_path: Path) -> None:
    first, second = _corpus(tmp_path)
    catalog_path = tmp_path / "rag" / "catalog"
    embeddings = DeterministicEmbeddings()
    RagCatalogBuilder(catalog_path, embeddings).build([first, second])
    before = hashlib.sha256((catalog_path / "manifest.json").read_bytes()).hexdigest()
    (second / FINAL_MARKDOWN).write_text("# Tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="final document digest"):
        RagCatalogBuilder(catalog_path, embeddings).build([second])

    assert hashlib.sha256((catalog_path / "manifest.json").read_bytes()).hexdigest() == before


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["missing", "unsealed", "failed_audit"])
def test_invalid_bundle_never_replaces_promoted_catalog(tmp_path: Path, failure: str) -> None:
    first, _ = _corpus(tmp_path)
    catalog_path = tmp_path / "rag" / "catalog"
    embeddings = DeterministicEmbeddings()
    RagCatalogBuilder(catalog_path, embeddings).build([first])
    before = hashlib.sha256((catalog_path / "manifest.json").read_bytes()).hexdigest()
    invalid = tmp_path / "runs" / failure
    if failure == "unsealed":
        invalid.mkdir()
    elif failure == "failed_audit":
        invalid = write_bundle(
            tmp_path / "runs",
            failure,
            "# Failed\n\n## Overview\n\nEvidence.\n",
            audit_status="fail",
        )

    with pytest.raises((FileNotFoundError, ValueError)):
        RagCatalogBuilder(catalog_path, embeddings).build([invalid])

    assert hashlib.sha256((catalog_path / "manifest.json").read_bytes()).hexdigest() == before


@pytest.mark.unit
def test_catalog_rejects_corruption_profile_mismatch_and_unknown_filters(tmp_path: Path) -> None:
    first, _ = _corpus(tmp_path)
    catalog_path = tmp_path / "rag" / "catalog"
    embeddings = DeterministicEmbeddings()
    RagCatalogBuilder(catalog_path, embeddings).build([first])

    with pytest.raises(ValueError, match="embedding profile"):
        RagCatalog.open(catalog_path, DeterministicEmbeddings(dimensions=32))
    with (
        RagCatalog.open(
            catalog_path, IdentityEmbeddings(read_catalog_profile(catalog_path))
        ) as catalog,
        pytest.raises(ValueError, match="not indexed"),
    ):
        catalog.search("owner", run_ids=["missing"])

    manifest = json.loads((catalog_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["catalog.sqlite3"] = "0" * 64
    (catalog_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        RagCatalog.open(catalog_path, embeddings)


@pytest.mark.unit
def test_catalog_rejects_validly_hashed_row_count_corruption(tmp_path: Path) -> None:
    first, _ = _corpus(tmp_path)
    catalog_path = tmp_path / "catalog"
    embeddings = DeterministicEmbeddings()
    RagCatalogBuilder(catalog_path, embeddings).build([first])
    database = catalog_path / "catalog.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM chunks_fts WHERE rowid = 1")
    manifest_path = catalog_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["catalog.sqlite3"] = hashlib.sha256(database.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="FTS row count"):
        RagCatalog.open(catalog_path, embeddings)


@pytest.mark.unit
def test_bundle_selection_is_explicit_and_all_sealed_skips_unsealed(tmp_path: Path) -> None:
    first, second = _corpus(tmp_path)
    (tmp_path / "runs" / "unsealed").mkdir()

    assert resolve_bundle_paths(tmp_path / "runs", ["run-a"], all_sealed=False) == [first]
    assert resolve_bundle_paths(tmp_path / "runs", [], all_sealed=True) == [first, second]
    with pytest.raises(ValueError, match="not both"):
        resolve_bundle_paths(tmp_path / "runs", ["run-a"], all_sealed=True)
    with pytest.raises(ValueError, match="at least"):
        resolve_bundle_paths(tmp_path / "runs", [], all_sealed=False)
    with pytest.raises(ValueError, match="invalid run"):
        resolve_bundle_paths(tmp_path / "runs", ["../outside"], all_sealed=False)


@pytest.mark.unit
def test_read_only_catalog_supports_agent_tool_threads(tmp_path: Path) -> None:
    first, second = _corpus(tmp_path)
    embeddings = DeterministicEmbeddings()
    path = tmp_path / "catalog"
    RagCatalogBuilder(path, embeddings).build([first, second])

    with RagCatalog.open(path, embeddings) as catalog, ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(catalog.search, "monthly review") for _ in range(8)]
        results = [future.result() for future in futures]

    assert all(result and result[0].chunk.run_id == "run-b" for result in results)


@pytest.mark.unit
def test_ambiguous_graph_labels_are_reported_not_guessed(tmp_path: Path) -> None:
    nodes = [
        {
            "node_id": f"node-{index}",
            "label": "Overview",
            "node_type": "Section",
            "provenance_span_ids": [],
        }
        for index in range(2)
    ]
    bundle = write_bundle(
        tmp_path / "runs",
        "run-ambiguous",
        "# Document\n\n## Overview\n\nEvidence.\n",
        nodes=nodes,
    )

    summary = RagCatalogBuilder(tmp_path / "catalog", DeterministicEmbeddings()).build([bundle])

    assert summary["linking"] == {
        "linked_chunks": 0,
        "unmatched_chunks": 1,
        "ambiguous_chunks": 1,
        "source_to_target_chunks": 0,
        "label_chunks": 0,
    }


@pytest.mark.unit
def test_rewritten_heading_links_through_verified_source_target_ids(tmp_path: Path) -> None:
    bundle = write_bundle(
        tmp_path / "runs",
        "run-renamed",
        "# Payments\n\n## Governance and Monitoring\n\nThe owner records each review.\n",
        nodes=[
            {
                "node_id": "sec-controls",
                "label": "Controls",
                "node_type": "Control",
                "provenance_span_ids": ["span-controls"],
            }
        ],
        source_targets=[
            {
                "source_section_id": "sec-controls",
                "source_title": "Controls",
                "target_section_id": "template-monitoring",
                "target_heading": "Governance and Monitoring",
                "source_span_ids": ["span-controls"],
            }
        ],
    )
    embeddings = DeterministicEmbeddings()
    path = tmp_path / "catalog"

    summary = RagCatalogBuilder(path, embeddings).build([bundle])

    assert summary["linking"] == {
        "linked_chunks": 1,
        "unmatched_chunks": 1,
        "ambiguous_chunks": 0,
        "source_to_target_chunks": 1,
        "label_chunks": 0,
    }
    with RagCatalog.open(path, embeddings) as catalog:
        chunk = next(
            item
            for item in catalog.chunks()
            if item.heading_path[-1] == "Governance and Monitoring"
        )
        expansion = catalog.expand_graph(["run-renamed::sec-controls"])

    assert chunk.target_section_id == "template-monitoring"
    assert chunk.source_section_ids == ("sec-controls",)
    assert chunk.link_method == "source_to_target"
    assert chunk.graph_node_ids == ("run-renamed::sec-controls",)
    assert chunk.provenance_span_ids == ("span-controls",)
    assert chunk.chunk_id in {item.chunk_id for item in expansion.chunks}


@pytest.mark.unit
def test_cyclic_graph_traversal_stops_at_two_hops(tmp_path: Path) -> None:
    nodes = [
        {
            "node_id": name.lower(),
            "label": name,
            "node_type": "Section",
            "provenance_span_ids": [],
        }
        for name in ("A", "B", "C")
    ]
    edges = [
        {"source": "a", "target": "b", "edge_type": "next", "provenance_span_ids": []},
        {"source": "b", "target": "c", "edge_type": "next", "provenance_span_ids": []},
        {"source": "c", "target": "a", "edge_type": "next", "provenance_span_ids": []},
    ]
    bundle = write_bundle(
        tmp_path / "runs",
        "run-cycle",
        "# Cycle\n\n## A\n\nA.\n\n## B\n\nB.\n\n## C\n\nC.\n",
        nodes=nodes,
        edges=edges,
    )
    embeddings = DeterministicEmbeddings()
    path = tmp_path / "catalog"
    RagCatalogBuilder(path, embeddings).build([bundle])

    with RagCatalog.open(path, embeddings) as catalog:
        expansion = catalog.expand_graph(["run-cycle::a"], depth=2)

    assert set(expansion.reached_node_ids) == {"run-cycle::a", "run-cycle::b", "run-cycle::c"}
    assert expansion.paths
    assert all(len(path.edge_types) <= 2 for path in expansion.paths)


@pytest.mark.unit
def test_search_budgets_empty_queries_and_large_limits(tmp_path: Path) -> None:
    first, second = _corpus(tmp_path)
    embeddings = DeterministicEmbeddings()
    path = tmp_path / "catalog"
    RagCatalogBuilder(path, embeddings).build([first, second])

    with RagCatalog.open(path, embeddings) as catalog:
        assert catalog.search("") == []
        assert catalog.search("review", limit=0) == []
        assert len(catalog.search("review", limit=1000)) <= 20
