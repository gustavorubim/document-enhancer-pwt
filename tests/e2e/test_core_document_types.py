"""Parity characterization for every governed document type in the core runner.

These tests deliberately use the offline path and the checked-in reference-pack
examples.  They are a small, user-facing proof that changing the document type
does not change the five-phase contract or the output bundle shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from document_enhancer.core import CoreRunner
from document_enhancer.core.layout import (
    AUDIT,
    DECISIONS_YAML,
    FLOW_MARKDOWN,
    GRAPH_JSONL,
    HTML_REPORT,
    INFERRED_FLOW,
    MACRO_MARKDOWN,
    ONTOLOGY,
    PROPOSED_FLOW,
    REVIEW,
    SEAL,
    SECTIONS_MARKDOWN,
)
from document_enhancer.core.recipes import load_recipe

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PACK = ROOT / "reference_packs" / "enterprise_core"

DOCUMENT_TYPES = (
    ("process", "PROC-STEP-001"),
    ("methodology", "METH-MODEL-001"),
    ("standard", "STD-NORMATIVE-001"),
    ("desktop_procedure", "DESK-ACTION-001"),
)


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("document_type", "expected_rubric_id"),
    DOCUMENT_TYPES,
)
def test_core_reference_examples_preserve_review_contract_for_all_document_types(
    tmp_path: Path,
    document_type: str,
    expected_rubric_id: str,
) -> None:
    source = REFERENCE_PACK / "templates" / document_type / "example.md"
    result = CoreRunner(
        tmp_path / "runs",
        recipe_pack=REFERENCE_PACK,
        document_type=document_type,
    ).start(source)

    run_path = tmp_path / "runs" / result.run_id
    review = json.loads((run_path / REVIEW).read_text(encoding="utf-8"))

    assert result.status == "waiting"
    assert result.phase == "human_review"
    assert result.unresolved_question_ids
    assert review["recipe_id"] == f"enterprise_core@2.0.0/{document_type}"
    assert review["rubric_ids"]
    assert review["sections"]
    assert review["section_assessments"]
    assert {item["status"] for item in review["section_assessments"]} <= {
        "correct",
        "missing",
        "improve",
    }
    assert review["findings"]
    assert review["questions"]
    assert expected_rubric_id in review["rubric_ids"]
    assert any(item["rubric_id"] == expected_rubric_id for item in review["findings"])
    assert (run_path / MACRO_MARKDOWN).is_file()
    assert (run_path / SECTIONS_MARKDOWN).is_file()
    assert (run_path / FLOW_MARKDOWN).is_file()
    assert (run_path / INFERRED_FLOW).read_text(encoding="utf-8").startswith("flowchart TD")
    assert (run_path / PROPOSED_FLOW).read_text(encoding="utf-8").startswith("flowchart TD")
    if document_type in {"process", "desktop_procedure"}:
        assert review["process_applicable"] is True
        assert (
            review["inferred_mermaid"] != review["proposed_mermaid"]
            or review["proposed_flow_edges"]
        )
    else:
        assert review["process_applicable"] is False
        assert "No process flow applicable" in review["inferred_mermaid"]
    assert (run_path / DECISIONS_YAML).is_file()


def test_core_clean_synthetic_process_seals_ontology_graph_and_audit_bundle(
    tmp_path: Path,
) -> None:
    """A complete offline run produces the stable semantic/export boundary."""

    recipe = load_recipe(REFERENCE_PACK, document_type="process")
    source = tmp_path / "synthetic-process.md"
    body = [
        "# Synthetic controlled allocation process",
        "",
        "Document ID: DOC-SYNTHETIC-001; Version: V1; Owner: ROLE-OWNER; Status: effective.",
        "",
    ]
    evidence = (
        "This synthetic process contains preconditions, triggers, inputs, a process steps table, "
        "a decision rules table, an exception register, and an escalation path. First validate "
        "inputs, then review the result; if a control fails, escalate and stop."
    )
    for requirement in recipe.required_section_items:
        heading = str(requirement.get("heading") or requirement.get("id"))
        body.extend([f"## {heading}", "", evidence, ""])
    source.write_text("\n".join(body), encoding="utf-8")

    result = CoreRunner(
        tmp_path / "runs",
        recipe_pack=REFERENCE_PACK,
        document_type="process",
    ).start(source)

    run_path = tmp_path / "runs" / result.run_id
    assert result.status == "waiting"
    assert not (run_path / SEAL).exists()
    decisions = run_path / DECISIONS_YAML
    decisions.write_text(
        decisions.read_text(encoding="utf-8")
        .replace("approve_rewrite: false", "approve_rewrite: true")
        .replace('answer: ""', "answer: approved")
        .replace("disposition: defer", "disposition: accept"),
        encoding="utf-8",
    )
    result = CoreRunner(
        tmp_path / "runs",
        recipe_pack=REFERENCE_PACK,
        document_type="process",
    ).resume(result.run_id)
    assert result.status == "succeeded"
    assert result.phase == "verify"
    assert not result.unresolved_question_ids

    audit = json.loads((run_path / AUDIT).read_text(encoding="utf-8"))
    ontology = json.loads((run_path / ONTOLOGY).read_text(encoding="utf-8"))
    graph_lines = (run_path / GRAPH_JSONL).read_text(encoding="utf-8").splitlines()
    seal = json.loads((run_path / SEAL).read_text(encoding="utf-8"))
    review = json.loads((run_path / REVIEW).read_text(encoding="utf-8"))

    assert audit["status"] == "pass"
    assert all(audit["checks"].values())
    assert ontology["schema_version"] == "core.graph.v1"
    assert ontology["nodes"]
    assert any(node["node_type"] != "section" for node in ontology["nodes"])
    assert ontology["edges"]
    assert graph_lines
    assert all(json.loads(line)["kind"] in {"node", "edge"} for line in graph_lines)
    assert review["section_assessments"]
    assert review["process_applicable"] is True
    assert (run_path / INFERRED_FLOW).is_file()
    assert (run_path / PROPOSED_FLOW).is_file()
    assert (run_path / HTML_REPORT).is_file()
    html = (run_path / HTML_REPORT).read_text(encoding="utf-8")
    assert "Final audit: pass" in html
    assert "Report 09" in html
    assert "Original Normalized Document" in html
    assert "Enhanced Document" in html
    assert 'role="tabpanel"' in html
    assert [path.name[:2] for path in sorted((run_path / "markdown").glob("*.md"))] == [
        "01",
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
        "08",
        "09",
    ]
    assert seal["sealed"] is True
    assert seal["source_digest"] == result.source_digest
    assert seal["schema_version"] == "core.seal.v2"
    assert ONTOLOGY in {item["path"] for item in seal["artifacts"].values()}
    assert GRAPH_JSONL in {item["path"] for item in seal["artifacts"].values()}
    assert AUDIT in {item["path"] for item in seal["artifacts"].values()}
    assert HTML_REPORT in {item["path"] for item in seal["artifacts"].values()}
