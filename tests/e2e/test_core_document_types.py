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
from document_enhancer.core.recipes import load_recipe

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PACK = ROOT / "reference_packs" / "enterprise_core"

DOCUMENT_TYPES = (
    ("process", "PROC-STEP-001", "question-rubric-proc-step-001"),
    ("methodology", "METH-MODEL-001", "question-rubric-meth-model-001"),
    ("standard", "STD-NORMATIVE-001", "question-rubric-std-normative-001"),
    (
        "desktop_procedure",
        "DESK-ACTION-001",
        "question-rubric-desk-action-001",
    ),
)


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("document_type", "expected_rubric_id", "expected_question_id"),
    DOCUMENT_TYPES,
)
def test_core_reference_examples_preserve_review_contract_for_all_document_types(
    tmp_path: Path,
    document_type: str,
    expected_rubric_id: str,
    expected_question_id: str,
) -> None:
    source = REFERENCE_PACK / "templates" / document_type / "example.md"
    result = CoreRunner(
        tmp_path / "runs",
        recipe_pack=REFERENCE_PACK,
        document_type=document_type,
    ).start(source)

    run_path = tmp_path / "runs" / result.run_id
    review = json.loads((run_path / "review" / "review.json").read_text(encoding="utf-8"))

    assert result.status == "waiting"
    assert result.phase == "human_review"
    assert result.unresolved_question_ids == [expected_question_id]
    assert review["recipe_id"] == f"enterprise_core@2.0.0/{document_type}"
    assert review["rubric_ids"]
    assert review["sections"]
    assert review["findings"]
    assert review["questions"]
    assert expected_rubric_id in review["rubric_ids"]
    assert any(item["rubric_id"] == expected_rubric_id for item in review["findings"])
    assert any(item["question_id"] == expected_question_id for item in review["questions"])
    assert (run_path / "source" / "source.json").is_file()
    assert (run_path / "source" / "normalized.md").is_file()
    assert (run_path / "review" / "review.md").is_file()
    assert (run_path / "review" / "flow.mmd").read_text(encoding="utf-8").startswith("flowchart TD")
    assert (run_path / "review" / "decisions.yaml").is_file()


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
    assert result.status == "succeeded"
    assert result.phase == "verify"
    assert not result.unresolved_question_ids

    audit = json.loads((run_path / "audit" / "audit.json").read_text(encoding="utf-8"))
    ontology = json.loads((run_path / "output" / "ontology.json").read_text(encoding="utf-8"))
    graph_lines = (run_path / "output" / "graph.jsonl").read_text(encoding="utf-8").splitlines()
    seal = json.loads((run_path / "audit" / "seal.json").read_text(encoding="utf-8"))

    assert audit["status"] == "pass"
    assert all(audit["checks"].values())
    assert ontology["schema_version"] == "core.graph.v1"
    assert ontology["nodes"]
    assert ontology["edges"]
    assert graph_lines
    assert all(json.loads(line)["kind"] in {"node", "edge"} for line in graph_lines)
    assert seal["sealed"] is True
    assert seal["source_digest"] == result.source_digest
    assert "output/ontology.json" in seal["artifact_paths"]
    assert "output/graph.jsonl" in seal["artifact_paths"]
    assert "audit/audit.json" in seal["artifact_paths"]
