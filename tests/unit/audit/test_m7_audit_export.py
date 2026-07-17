from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from document_enhancer.audit import (
    ContentAuditor,
    ContentAuditRequest,
    build_audit,
    run_deterministic_audit,
    write_audit_artifacts,
)
from document_enhancer.chunking import build_chunks
from document_enhancer.domain.audit import (
    AuditEvidence,
    ContentAuditFinding,
    IndependentAuditResult,
)
from document_enhancer.domain.enums import (
    AuditStatus,
    LedgerDisposition,
)
from document_enhancer.domain.ontology import (
    CompletionCondition,
    Control,
    Input,
    Output,
    ProcessStep,
    Role,
    Rule,
    Trigger,
)
from document_enhancer.export import (
    build_export_bundle,
    validate_export_bundle,
    write_export_bundle,
)
from document_enhancer.ingest.normalize import normalize_document
from document_enhancer.ingest.pipeline import parse_source
from document_enhancer.rewrite import (
    MermaidDiagram,
    MermaidNode,
    RevisionCounters,
    build_content_ledger,
    build_enhanced_document,
    build_rewrite_inputs,
    build_semantic_document,
    render_enhanced_markdown,
)


def _artifacts(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source.md"
    source.write_text(
        "# Purpose\n\nThe analyst reviews the approved monthly file and records the result.\n",
        encoding="utf-8",
    )
    normalized = normalize_document(parse_source(source))
    sections = [{"id": "SEC-PROC-PURPOSE", "heading": "Purpose", "anchor": "purpose"}]
    ledger = build_content_ledger(normalized, document_id="DOC-M7-001", target_sections=sections)
    inputs = build_rewrite_inputs(normalized, ledger, sections=sections)
    model = build_enhanced_document(inputs, document_id="DOC-M7-001", ledger=ledger)
    markdown = render_enhanced_markdown(
        model, reference_pack=Path("reference_packs/enterprise_core")
    )
    import hashlib

    digest = hashlib.sha256(markdown.encode()).hexdigest()
    model = model.model_copy(
        update={
            "markdown_digest": digest,
            "version": model.version.model_copy(update={"enhanced_digest": digest}),
        }
    )
    semantic = build_semantic_document(model)
    return normalized, ledger, model, semantic, markdown


def _audit(tmp_path: Path, content_auditor: ContentAuditor | None = None):
    normalized, ledger, model, semantic, markdown = _artifacts(tmp_path)
    audit = build_audit(
        run_id="run-m7-test",
        model=model,
        semantic=semantic,
        ledger=ledger,
        raw=normalized.raw,
        source_markdown=normalized.normalized_markdown,
        enhanced_markdown=markdown,
        counters=RevisionCounters(),
        content_auditor=content_auditor,
    )
    return audit, (normalized, ledger, model, semantic, markdown)


def test_passing_fixture_emits_reconciled_audit_diff_chunk_graph_and_manifest(
    tmp_path: Path,
) -> None:
    _base_audit, (normalized, ledger, model, semantic, markdown) = _audit(tmp_path)
    provenance = model.objects[0].provenance
    supporting = [
        Role(id="ROLE-M7-ANALYST", name="Analyst", provenance=provenance),
        Trigger(id="TRG-M7-001", name="Monthly trigger", provenance=provenance),
        Input(id="IN-M7-001", name="Approved file", provenance=provenance),
        Output(id="OUT-M7-001", name="Review record", provenance=provenance),
        CompletionCondition(id="DONE-M7-001", name="Recorded", provenance=provenance),
    ]
    step = ProcessStep(
        id="STEP-M7-001",
        name="Record review",
        provenance=provenance,
        performer_ids=["ROLE-M7-ANALYST"],
        trigger_ids=["TRG-M7-001"],
        input_ids=["IN-M7-001"],
        action="Record the review result.",
        output_ids=["OUT-M7-001"],
        completion_condition_id="DONE-M7-001",
        next_step_id="STEP-M7-001",
    )
    section = model.sections[0].model_copy(
        update={"object_ids": [*model.sections[0].object_ids, step.id]}
    )
    model = model.model_copy(
        update={
            "objects": [*model.objects, *supporting, step],
            "sections": [section, *model.sections[1:]],
        }
    )
    semantic = semantic.model_copy(update={"objects": model.objects})
    audit = build_audit(
        run_id="run-m7-test",
        model=model,
        semantic=semantic,
        ledger=ledger,
        raw=normalized.raw,
        source_markdown=normalized.normalized_markdown,
        enhanced_markdown=markdown,
        counters=RevisionCounters(),
        requirements={
            "sections": [{"id": "SEC-PROC-PURPOSE", "required": True}],
            "tables": [],
        },
    )
    assert audit.status is AuditStatus.PASS
    assert audit.routing.route == "export"
    assert audit.textual_diff.startswith("--- source/normalized.md")
    assert len(audit.source_to_target) == len(normalized.raw.blocks)

    chunks = build_chunks(model)
    assert chunks
    assert [item.chunk_id for item in chunks] == [item.chunk_id for item in build_chunks(model)]
    assert all("TBD" not in item.text for item in chunks)
    assert all(item.provenance and item.markdown_anchor for item in chunks)

    audit_dir = tmp_path / "audit"
    write_audit_artifacts(audit, audit_dir)
    assert {
        "deterministic.json",
        "content.json",
        "audit.json",
        "report.md",
        "textual.diff.md",
        "semantic.diff.yaml",
        "source-to-target.csv",
    } <= {item.name for item in audit_dir.iterdir()}

    bundle = build_export_bundle(
        run_id="run-m7-test",
        source_digest=normalized.raw.source_digest,
        semantic=semantic,
        chunks=chunks,
        audit=audit,
    )
    export_dir = tmp_path / "export"
    write_export_bundle(bundle, export_dir)
    assert validate_export_bundle(export_dir) == ()
    assert bundle.manifest.nodes_count == len(bundle.nodes)
    assert bundle.manifest.edges_count == len(bundle.edges)
    assert all(item.provenance and item.layer and item.authority for item in bundle.nodes)

    with (export_dir / "nodes.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": "INVENTED"}) + "\n")
    errors = validate_export_bundle(export_dir)
    assert "digest mismatch for nodes.jsonl" in errors
    assert "count mismatch for nodes.jsonl" in errors


@pytest.mark.parametrize(
    ("mutation", "check_id"),
    [
        ("omission", "CHECK-OMISSIONS"),
        ("ledger_gap", "CHECK-LEDGER"),
        ("invalid_mermaid_reference", "CHECK-MERMAID"),
        ("provenance_gap", "CHECK-SCHEMA"),
        ("dangling_edge", "CHECK-SCHEMA"),
        ("missing_unit", "CHECK-DOCUMENT-LINT"),
        ("orphan_control", "CHECK-DOCUMENT-LINT"),
        ("unresolved_blocker", "CHECK-UNRESOLVED"),
    ],
)
def test_negative_content_and_graph_defects_fail_the_appropriate_gate(
    tmp_path: Path, mutation: str, check_id: str
) -> None:
    normalized, ledger, model, semantic, _markdown = _artifacts(tmp_path)
    if mutation == "omission":
        first = ledger.entries[0].model_copy(
            update={"disposition": LedgerDisposition.OMITTED, "omitted_reason": "deliberate"}
        )
        ledger = ledger.model_copy(update={"entries": [first, *ledger.entries[1:]]})
    elif mutation == "ledger_gap":
        ledger = ledger.model_copy(update={"entries": ledger.entries[1:]})
    elif mutation == "invalid_mermaid_reference":
        diagram = MermaidDiagram(
            diagram_id="DIAG-M7-BAD",
            diagram_type="process",
            caption="Invalid semantic reference",
            nodes=[MermaidNode(node_id="BadNode", semantic_id="STEP-NOT-FOUND", label="bad")],
        )
        model = model.model_copy(update={"mermaid": [diagram]})
    elif mutation == "provenance_gap":
        entity = model.objects[0]
        bad = entity.model_copy(
            update={"provenance": entity.provenance.model_copy(update={"document_id": "DOC-OTHER"})}
        )
        model = model.model_copy(update={"objects": [bad, *model.objects[1:]]})
        semantic = semantic.model_copy(update={"objects": model.objects})
    elif mutation == "dangling_edge":
        edge = semantic.relationships[0].model_copy(update={"target_id": "STMT-NOT-FOUND"})
        semantic = semantic.model_copy(
            update={"relationships": [edge, *semantic.relationships[1:]]}
        )
    elif mutation == "missing_unit":
        provenance = model.objects[0].provenance
        rule = Rule(
            id="RULE-M7-001",
            name="Amount threshold",
            provenance=provenance,
            condition="amount exceeds threshold",
            metric_id=model.objects[0].id,
            operator=">",
            value="10",
            evaluation_period="monthly",
            outcome="escalate",
        )
        model = model.model_copy(update={"objects": [*model.objects, rule]})
        semantic = semantic.model_copy(update={"objects": model.objects})
    elif mutation == "orphan_control":
        control = Control(
            id="CTRL-M7-001",
            name="Review control",
            provenance=model.objects[0].provenance,
            objective="review",
            execution_frequency="monthly",
            failure_response="escalate",
        )
        model = model.model_copy(update={"objects": [*model.objects, control]})
        semantic = semantic.model_copy(update={"objects": model.objects})
    else:
        issue = semantic.open_issues[0].model_copy(update={"blocking": True})
        semantic = semantic.model_copy(update={"open_issues": [issue, *semantic.open_issues[1:]]})

    checks = run_deterministic_audit(
        model=model,
        semantic=semantic,
        ledger=ledger,
        raw=normalized.raw,
    )
    selected = next(item for item in checks if item.check_id == check_id)
    assert not selected.passed
    assert selected.evidence


def test_template_required_sections_tables_ids_and_columns_fail_closed(tmp_path: Path) -> None:
    normalized, ledger, model, semantic, _markdown = _artifacts(tmp_path)
    requirements = {
        "sections": [{"id": "SEC-PROC-MISSING", "required": True}],
        "tables": [
            {
                "id": "TBL-PROC-MISSING",
                "required": True,
                "columns": [{"id": "unit", "required": True}],
            }
        ],
    }
    checks = run_deterministic_audit(
        model=model,
        semantic=semantic,
        ledger=ledger,
        raw=normalized.raw,
        requirements=requirements,
    )
    assert not next(item for item in checks if item.check_id == "CHECK-TEMPLATE-SECTIONS").passed
    assert not next(item for item in checks if item.check_id == "CHECK-TEMPLATE-TABLES").passed


class _NegativeAuditor:
    def __init__(self) -> None:
        self.request: ContentAuditRequest | None = None

    def audit(self, request: ContentAuditRequest) -> IndependentAuditResult:
        self.request = request
        return IndependentAuditResult(
            audit_id="INDAUD-M7-NEGATIVE",
            status="fail",
            provider="fake",
            findings=[
                ContentAuditFinding(
                    finding_id="CFIND-M7-INVENTED",
                    category="unsupported_addition",
                    severity="blocker",
                    summary="Output invents an approval.",
                    blocking=True,
                    source_evidence=[
                        AuditEvidence(
                            artifact="source/normalized.md",
                            locator="SPAN-1",
                            quote="No approval is stated.",
                        )
                    ],
                    output_evidence=[
                        AuditEvidence(
                            artifact="output/enhanced.md",
                            locator="#approval",
                            quote="Approved by CFO.",
                        )
                    ],
                    proposed_disposition="Remove or obtain reviewer evidence.",
                )
            ],
        )


class _UnavailableAuditor:
    def audit(self, request: ContentAuditRequest) -> IndependentAuditResult:
        raise RuntimeError(f"provider unavailable for {request.document_id}")


def test_independent_auditor_is_isolated_evidence_linked_and_cannot_override_determinism(
    tmp_path: Path,
) -> None:
    auditor = _NegativeAuditor()
    audit, _ = _audit(tmp_path, content_auditor=auditor)
    assert audit.status is AuditStatus.WAITING
    assert audit.routing.route == "human_review"
    assert auditor.request is not None
    assert set(type(auditor.request).model_fields) == {
        "document_id",
        "source_artifact",
        "source_markdown",
        "output_artifact",
        "enhanced_markdown",
        "semantic_document",
        "checklist_digest",
        "steering_digest",
        "reviewer_inputs",
    }

    with pytest.raises(PydanticValidationError):
        ContentAuditFinding(
            finding_id="CFIND-M7-NO-OUTPUT",
            category="omission",
            severity="high",
            summary="Missing output evidence",
            source_evidence=[
                AuditEvidence(artifact="source", locator="1", quote="source evidence")
            ],
            output_evidence=[],
            proposed_disposition="fix",
        )

    deterministic_failure, artifacts = _audit(tmp_path / "second")
    normalized, ledger, model, semantic, markdown = artifacts
    omitted = ledger.entries[0].model_copy(
        update={"disposition": LedgerDisposition.OMITTED, "omitted_reason": "deliberate"}
    )
    failed = build_audit(
        run_id="run-m7-fail",
        model=model,
        semantic=semantic,
        ledger=ledger.model_copy(update={"entries": [omitted, *ledger.entries[1:]]}),
        raw=normalized.raw,
        source_markdown=normalized.normalized_markdown,
        enhanced_markdown=markdown,
        counters=RevisionCounters(),
        content_auditor=auditor,
    )
    assert deterministic_failure.status is AuditStatus.PASS
    assert failed.status is not AuditStatus.PASS
    assert failed.independent_audit.status == "unavailable"
    with pytest.raises(ValueError, match="not pass"):
        build_export_bundle(
            run_id="run-m7-fail",
            source_digest=normalized.raw.source_digest,
            semantic=semantic,
            chunks=build_chunks(model),
            audit=failed,
        )


def test_unavailable_independent_auditor_routes_to_human_review_not_auto_revision(
    tmp_path: Path,
) -> None:
    audit, _ = _audit(tmp_path, content_auditor=_UnavailableAuditor())

    assert audit.independent_audit.status == "unavailable"
    assert audit.independent_audit.provider == "_UnavailableAuditor"
    assert audit.routing.blocker_ids == ["INDEPENDENT-AUDIT-NOT-PASSED"]
    assert audit.routing.route == "human_review"
    assert audit.status is AuditStatus.WAITING


def test_auto_revision_routing_is_bounded_and_exhaustion_fails_closed(tmp_path: Path) -> None:
    normalized, ledger, model, semantic, markdown = _artifacts(tmp_path)
    diagram = MermaidDiagram(
        diagram_id="DIAG-M7-BAD",
        diagram_type="process",
        caption="Invalid semantic reference",
        nodes=[MermaidNode(node_id="BadNode", semantic_id="STEP-NOT-FOUND", label="bad")],
    )
    model = model.model_copy(update={"mermaid": [diagram]})
    available = build_audit(
        run_id="run-m7-route",
        model=model,
        semantic=semantic,
        ledger=ledger,
        raw=normalized.raw,
        source_markdown=normalized.normalized_markdown,
        enhanced_markdown=markdown,
        counters=RevisionCounters(max_audit_revisions=1),
    )
    assert available.routing.route == "auto_revise"
    exhausted = build_audit(
        run_id="run-m7-route",
        model=model,
        semantic=semantic,
        ledger=ledger,
        raw=normalized.raw,
        source_markdown=normalized.normalized_markdown,
        enhanced_markdown=markdown,
        counters=RevisionCounters(audit_revision=1, max_audit_revisions=1),
    )
    assert exhausted.routing.route == "failed"
    assert exhausted.status is AuditStatus.FAIL
