from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from evals.corpus import family_specs, generate_corpus


@pytest.mark.unit
def test_generator_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_corpus(first)
    generate_corpus(second)

    first_files = {path.relative_to(first) for path in first.rglob("*") if path.is_file()}
    second_files = {path.relative_to(second) for path in second.rglob("*") if path.is_file()}
    assert first_files == second_files
    assert all(
        (first / relative).read_bytes() == (second / relative).read_bytes()
        for relative in first_files
    )


@pytest.mark.unit
def test_checked_in_corpus_matches_generator() -> None:
    generate_corpus(Path("fixtures/synthetic/corpus"), check=True)


@pytest.mark.unit
def test_fixture_gold_has_stable_spans_questions_and_graph_references() -> None:
    manifest = json.loads(
        Path("fixtures/synthetic/corpus/manifest.json").read_text(encoding="utf-8")
    )
    assert len(manifest["families"]) == 5
    assert {family["document_type"] for family in manifest["families"]} == {
        "methodology",
        "process",
        "desktop_procedure",
        "standard",
    }

    for family in manifest["families"]:
        gold = json.loads(
            Path("fixtures/synthetic/corpus", family["gold"]).read_text(encoding="utf-8")
        )
        all_ids = {item["id"] for item in gold["gold_semantic_objects"]}
        assert len(all_ids) == len(gold["gold_semantic_objects"])
        for fact in gold["gold_source_facts"]:
            assert fact["provenance"]["document_id"] == gold["document_id"]
        for defect in gold["seeded_defects"]:
            assert defect["provenance"]["document_id"] == gold["document_id"]
        for edge in gold["gold_semantic_edges"]:
            assert edge["source_id"] in all_ids
            assert edge["target_id"] in all_ids
            assert edge["provenance"]["document_id"] == gold["document_id"]
            assert edge["provenance"]["source_span_id"] in gold["variants"]["clean"]["raw_order"]
        for question in gold["gold_questions"]:
            assert question["question_id"].startswith("Q-")
            assert question["evidence"][0]["span_id"] in gold["variants"]["clean"]["raw_order"]
        for variant in gold["variants"].values():
            ordinals = [block["ordinal"] for block in variant["raw_blocks"]]
            assert ordinals == list(range(len(ordinals)))
            assert variant["raw_order"] == [block["span_id"] for block in variant["raw_blocks"]]
            assert variant["structure_routing"]["expected_mode"] in {"parser", "llm_recovery"}
            assert {"markdown", "docx"} <= set(variant["format_artifacts"])


@pytest.mark.unit
def test_generated_docx_pdf_and_rag_gold_are_real_and_complete() -> None:
    root = Path("fixtures/synthetic/corpus")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for family in manifest["families"]:
        for variant in family["variants"]:
            family_root = root / family["family_id"]
            with zipfile.ZipFile(family_root / f"{variant['variant']}.docx") as archive:
                assert "word/document.xml" in archive.namelist()
                assert b"vbaProject" not in archive.read("word/document.xml")
            if "pdf" in variant["formats"]:
                assert (family_root / f"{variant['variant']}.pdf").read_bytes().startswith(b"%PDF")
        assert (root / family["family_id"] / "enhanced_target.md").is_file()

    questions = json.loads((root / "cross_document_questions.json").read_text(encoding="utf-8"))
    assert len(questions["questions"]) >= 8
    categories = {item["category"] for item in questions["questions"]}
    assert {
        "direct_fact",
        "multi_section_synthesis",
        "control_to_risk_graph",
        "current_vs_superseded",
        "metadata_filter",
        "ambiguous_follow_up",
        "unanswerable",
    } <= categories
    assert all(
        "pending:" not in chunk
        for item in questions["questions"]
        for chunk in item["expected_chunk_ids"]
    )


@pytest.mark.unit
def test_family_definitions_are_five_and_non_proprietary() -> None:
    families = family_specs()
    assert len(families) == 5
    text = " ".join(section.body for family in families for section in family.sections).lower()
    assert "proprietary" not in text
    assert "fictional" in text or "northstar" in text
