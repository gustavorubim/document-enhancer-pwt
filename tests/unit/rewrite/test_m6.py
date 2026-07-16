from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from document_enhancer.domain.enums import DocumentType, QuestionStatus
from document_enhancer.domain.questions import (
    Answer,
    AnswersArtifact,
    ChecklistItem,
    RewriteChecklist,
)
from document_enhancer.ingest.normalize import normalize_document
from document_enhancer.ingest.pipeline import parse_source
from document_enhancer.rewrite import (
    EnhancedDocumentModel,
    MermaidDiagram,
    RevisionCounters,
    build_content_ledger,
    build_enhanced_document,
    build_rewrite_inputs,
    build_semantic_document,
    generate_mermaid,
    render_enhanced_markdown,
    validate_content_ledger,
)


def _normalized(tmp_path: Path):
    source = tmp_path / "source.md"
    source.write_text(
        "# Purpose\n\nThe process starts each month.\n\n# Scope\n\nIt covers approved forecasts.\n",
        encoding="utf-8",
    )
    return normalize_document(parse_source(source))


def _sections() -> list[dict[str, object]]:
    return [
        {"id": "SEC-PROC-PURPOSE", "heading": "Purpose", "anchor": "purpose"},
        {
            "id": "SEC-PROC-SCOPE",
            "heading": "Scope and applicability",
            "anchor": "scope-and-applicability",
        },
    ]


def test_content_ledger_covers_each_normalized_span_exactly_once(tmp_path: Path) -> None:
    normalized = _normalized(tmp_path)
    ledger = build_content_ledger(
        normalized,
        document_id="DOC-M6-001",
        target_sections=_sections(),
    )
    source_ids = [block.span_id.upper() for block in normalized.raw.blocks]
    report = validate_content_ledger(ledger, source_ids)
    assert report.valid
    assert len(ledger.entries) == len(source_ids)
    assert {entry.source_span_id for entry in ledger.entries} == set(source_ids)

    duplicate = ledger.model_copy(update={"entries": [*ledger.entries, ledger.entries[0]]})
    invalid = validate_content_ledger(duplicate, source_ids)
    assert not invalid.valid
    assert invalid.duplicate_span_ids == (ledger.entries[0].source_span_id,)


def test_content_ledger_digests_verbatim_markdown_hard_breaks(tmp_path: Path) -> None:
    source = tmp_path / "hard-break.md"
    source.write_text(
        "# Metadata\n\n**Owner:** First line  \n**Status:** effective\n", encoding="utf-8"
    )
    normalized = normalize_document(parse_source(source))
    ledger = build_content_ledger(
        normalized,
        document_id="DOC-M6-HARD-BREAK",
        target_sections=[{"id": "SEC-METADATA", "heading": "Metadata", "anchor": "metadata"}],
    )
    source_ids = [block.span_id.upper() for block in normalized.raw.blocks]
    source_texts = {block.span_id.upper(): block.text for block in normalized.raw.blocks}

    report = validate_content_ledger(ledger, source_ids, source_texts=source_texts)

    assert report.valid


def test_content_ledger_prefers_structural_heading_over_table_vocabulary(tmp_path: Path) -> None:
    source = tmp_path / "governed-table.md"
    source.write_text(
        "# Process\n\n## Roles and responsibilities\n\n"
        "| Role | Governance | Metadata |\n| --- | --- | --- |\n| Owner | First line | Active |\n",
        encoding="utf-8",
    )
    normalized = normalize_document(parse_source(source))
    ledger = build_content_ledger(
        normalized,
        document_id="DOC-M6-STRUCTURAL-ANCHOR",
        target_sections=[
            {
                "id": "SEC-METADATA",
                "heading": "Document metadata and governance",
                "anchor": "document-metadata-and-governance",
            },
            {
                "id": "SEC-ROLES",
                "heading": "Roles and responsibilities",
                "anchor": "roles-and-responsibilities",
            },
        ],
    )
    table_span = next(
        block.source_span_id.upper() for block in normalized.blocks if block.block_type == "table"
    )

    entry = next(item for item in ledger.entries if item.source_span_id == table_span)

    assert entry.target_anchor == "roles-and-responsibilities"


def test_rewrite_inputs_expose_only_answered_reviewer_facts(tmp_path: Path) -> None:
    normalized = _normalized(tmp_path)
    ledger = build_content_ledger(
        normalized,
        document_id="DOC-M6-002",
        target_sections=_sections(),
    )
    checklist = RewriteChecklist(
        checklist_id="CHECK-M6-002",
        document_id="DOC-M6-002",
        items=[
            ChecklistItem(
                checklist_item_id="CHK-Q-OWNER",
                question_id="Q-OWNER",
                target_section_id="SEC-PROC-PURPOSE",
                action="add_from_answer",
                verification_method="compare with answer",
                acceptance_criterion="owner is explicit",
                blocking=False,
            ),
            ChecklistItem(
                checklist_item_id="CHK-Q-DEFERRED",
                question_id="Q-DEFERRED",
                target_section_id="SEC-PROC-PURPOSE",
                action="clarify",
                verification_method="review",
                acceptance_criterion="ambiguity is visible",
                blocking=False,
            ),
        ],
    )
    answers = AnswersArtifact(
        document_id="DOC-M6-002",
        answers=[
            Answer(
                answer_id="ANS-OWNER",
                question_id="Q-OWNER",
                status=QuestionStatus.ANSWERED,
                answer="Forecast Analyst",
                responder="ROLE-REVIEWER",
                evidence_reference="answer://m6/owner",
            ),
            Answer(
                answer_id="ANS-DEFERRED",
                question_id="Q-DEFERRED",
                status=QuestionStatus.DEFERRED,
            ),
        ],
    )
    inputs = build_rewrite_inputs(
        normalized,
        ledger,
        sections=_sections(),
        answers=answers,
        checklist=checklist,
    )
    purpose = inputs[0]
    assert [answer.answer_id for answer in purpose.approved_answers] == ["ANS-OWNER"]
    assert "ANS-DEFERRED" not in purpose.allowed_answer_ids
    assert set(purpose.allowed_source_span_ids) == {
        evidence.span_id for evidence in purpose.source_evidence
    }


def test_model_render_and_sidecar_share_ids_and_explicit_open_issues(tmp_path: Path) -> None:
    normalized = _normalized(tmp_path)
    sections = _sections()
    ledger = build_content_ledger(normalized, document_id="DOC-M6-003", target_sections=sections)
    inputs = build_rewrite_inputs(normalized, ledger, sections=sections)
    model = build_enhanced_document(
        inputs,
        document_id="DOC-M6-003",
        document_type=DocumentType.PROCESS,
        ledger=ledger,
    )
    markdown = render_enhanced_markdown(
        model, reference_pack=Path("reference_packs/enterprise_core")
    )
    assert "AUTHORING" not in markdown
    assert "STEP-TBD" not in markdown
    assert "{{" not in markdown and "<!--" not in markdown
    assert all(
        kind in {table.table_kind for table in model.tables}
        for kind in {
            "steps",
            "rules",
            "controls",
            "risks",
            "evidence",
            "assumptions",
            "limitations",
            "exceptions",
            "dependencies",
            "calculators",
            "inputs_outputs",
            "versions",
        }
    )
    for table in model.tables:
        assert table.table_id in markdown
    semantic = build_semantic_document(model)
    assert {item.id for item in semantic.objects} == {item.id for item in model.objects}
    assert {item.id for item in semantic.relationships} == {item.id for item in model.relationships}
    assert semantic.ledger_id == ledger.ledger_id
    issue_ids = {issue.finding_id for issue in semantic.open_issues}
    assert issue_ids
    assert issue_ids.isdisjoint({item.id for item in semantic.objects})


def test_mermaid_revision_budget_and_fail_closed_exhaustion() -> None:
    diagram = MermaidDiagram(
        diagram_id="DIAG-M6-FLOW",
        diagram_type="process",
        caption="A flow",
        nodes=[],
        edges=[],
    )
    assert "flowchart TD" in generate_mermaid(diagram)
    counters = RevisionCounters(max_rewrite_revisions=1, max_audit_revisions=1)
    used = counters.consume_rewrite()
    with pytest.raises(Exception, match="rewrite revision limit exhausted"):
        used.consume_rewrite()
    with pytest.raises(ValidationError):
        EnhancedDocumentModel.model_validate({"unexpected": True})
