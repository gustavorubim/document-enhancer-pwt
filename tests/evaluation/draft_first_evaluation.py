"""Deterministic Wave 4 evaluation for the draft-first workflow.

The evaluator exercises the four supported source suffixes offline, then seals one complete
process fixture through the real approval gate.  Its JSON output is intentionally small enough to
serve as release evidence while retaining the exact fixture and audit facts behind each metric.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any, cast

from document_enhancer.core import CoreRunner
from document_enhancer.core.indexing import load_sealed_bundle
from document_enhancer.core.layout import (
    AUDIT,
    DRAFT_AUDIT,
    DRAFT_DOCUMENT,
    DRAFT_TRANSFORMATION,
    DRAFT_VISUAL_EXTRACTIONS,
    FINAL_MARKDOWN,
    REVIEW,
    SEAL,
)
from document_enhancer.core.models import RunRecord
from document_enhancer.llm import FakeMultimodalModel

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "draft_first"
REFERENCE_PACK = ROOT / "reference_packs" / "enterprise_core"

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PNG_DIGEST = hashlib.sha256(PNG_1X1).hexdigest()


def _fixed_zip_bytes(entries: list[tuple[str, str | bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return buffer.getvalue()


def _docx_fixture_bytes() -> bytes:
    document = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
 <w:body>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Desktop table fixture</w:t></w:r></w:p>
  <w:p><w:r><w:t>Use the approved input and record the completion evidence.</w:t></w:r></w:p>
  <w:tbl>
   <w:tr><w:tc><w:p><w:r><w:t>Field</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Owner</w:t></w:r></w:p></w:tc></w:tr>
   <w:tr><w:tc><w:p><w:r><w:t>Input</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>ROLE-OWNER</w:t></w:r></w:p></w:tc></w:tr>
  </w:tbl>
  <w:p><w:r><w:t>Compare the image-table candidate with the source figure.</w:t><w:drawing><a:blip r:embed="rId2"/></w:drawing></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr><w:r><w:t>Figure 1. Image table candidate.</w:t></w:r></w:p>
  <w:sectPr/>
 </w:body>
</w:document>"""
    relationships = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/table.png"/>
</Relationships>"""
    return _fixed_zip_bytes(
        [
            ("word/document.xml", document),
            ("word/_rels/document.xml.rels", relationships),
            ("word/media/table.png", PNG_1X1),
        ]
    )


def _pdf_fixture_bytes(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 20 250 Td ({escaped}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def _write_format_fixtures(root: Path) -> dict[str, tuple[Path, str]]:
    sources = root / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    markdown = sources / "ambiguity.md"
    markdown.write_bytes((FIXTURE_ROOT / "ambiguity.md").read_bytes())
    text = sources / "methodology.txt"
    text.write_bytes((FIXTURE_ROOT / "methodology.txt").read_bytes())
    docx = sources / "table-candidate.docx"
    docx.write_bytes(_docx_fixture_bytes())
    pdf = sources / "standard.pdf"
    pdf.write_bytes(
        _pdf_fixture_bytes(
            "DFT-8 standard. The control owner records the approved evidence and review result."
        )
    )
    return {
        "md": (markdown, "process"),
        "txt": (text, "methodology"),
        "docx": (docx, "desktop_procedure"),
        "pdf": (pdf, "standard"),
    }


def _approve_all(path: Path) -> None:
    decisions = path / "review" / "decisions.yaml"
    decisions.write_text(
        decisions.read_text(encoding="utf-8")
        .replace("approve_rewrite: false", "approve_rewrite: true")
        .replace('answer: ""', "answer: approved")
        .replace("disposition: defer", "disposition: accept"),
        encoding="utf-8",
    )


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object at {path}")
    return cast(dict[str, Any], value)


def _start_fixture(
    root: Path,
    source: Path,
    document_type: str,
    *,
    visual_provider: Any | None = None,
) -> tuple[RunRecord, Path]:
    runner = CoreRunner(
        root / "runs",
        recipe_pack=REFERENCE_PACK,
        document_type=document_type,
        visual_provider=visual_provider,
    )
    result = runner.start(source)
    return result, root / "runs" / result.run_id


def _provenance_reference_count(mapping: dict[str, Any], draft_audit: dict[str, Any]) -> int:
    coverage = cast(dict[str, Any], mapping["coverage"])
    reference_fields = (
        "unknown_span_references",
        "unknown_section_references",
        "unknown_gap_references",
        "unknown_question_references",
        "unknown_figure_references",
        "invalid_gap_ids",
        "invalid_visual_references",
    )
    return sum(len(cast(list[Any], coverage.get(field, []))) for field in reference_fields) + len(
        cast(list[Any], draft_audit.get("invalid_references", []))
    )


def _complete_process_source(root: Path) -> Path:
    source = root / "complete-process.md"
    source.write_bytes((FIXTURE_ROOT / "complete_process.md").read_bytes())
    return source


def run_evaluation(root: Path) -> dict[str, Any]:
    """Run the offline DFT-8 fixture evaluation and write one JSON metrics artifact."""

    root.mkdir(parents=True, exist_ok=True)
    fixtures = _write_format_fixtures(root)
    stage_results: list[dict[str, Any]] = []
    coverage_values: list[float] = []
    section_status_values: list[float] = []
    invalid_provenance_references = 0
    ambiguity_evidence: dict[str, Any] = {}
    visual_evidence: dict[str, Any] = {}

    for suffix, (source, document_type) in fixtures.items():
        provider: Any | None = None
        if suffix == "docx":
            provider = FakeMultimodalModel(
                {
                    "FIG-001": [
                        {
                            "figure_id": "FIG-001",
                            "source_sha256": PNG_DIGEST,
                            "source_span_ids": [],
                            "kind": "table",
                            "status": "best_effort",
                            "confidence": 0.9,
                            "cells": [["Field", "Value"], ["Owner", "ROLE-OWNER"]],
                        }
                    ]
                }
            )
        result, run_path = _start_fixture(root, source, document_type, visual_provider=provider)
        mapping = _json(run_path / DRAFT_TRANSFORMATION)
        draft_audit = _json(run_path / DRAFT_AUDIT)
        coverage = cast(dict[str, Any], mapping["coverage"])
        coverage_values.append(float(coverage["source_span_coverage"]))
        section_status_values.append(float(coverage["required_section_status_coverage"]))
        invalid_provenance_references += _provenance_reference_count(mapping, draft_audit)
        stage_results.append(
            {
                "suffix": suffix,
                "source": source.name,
                "document_type": document_type,
                "status": result.status,
                "phase": result.phase,
                "draft_artifacts_present": all(
                    (run_path / path).is_file()
                    for path in (
                        DRAFT_TRANSFORMATION,
                        DRAFT_DOCUMENT,
                        DRAFT_AUDIT,
                        DRAFT_VISUAL_EXTRACTIONS,
                    )
                ),
            }
        )
        if suffix == "md":
            review = _json(run_path / REVIEW)
            questions = [
                item
                for item in cast(list[dict[str, Any]], review["questions"])
                if item["question_id"] == "question-open-points-001"
            ]
            if len(questions) != 1:
                raise AssertionError("the Markdown fixture must produce one cross-section question")
            question = questions[0]
            suggestion = str(question.get("suggestion") or "")
            ambiguity_evidence = {
                "question_id": question["question_id"],
                "evidence_span_count": len(cast(list[Any], question["evidence_span_ids"])),
                "sections_in_context": all(
                    title in str(question["context"]) for title in ("Intake", "Controls")
                ),
                "safe_suggestion": bool(suggestion)
                and question["suggestion_basis"] == "recipe_guidance"
                and "60" not in suggestion
                and "30" not in suggestion,
                "suggestion_basis": question["suggestion_basis"],
            }
        if suffix == "docx":
            visual_payload = _json(run_path / DRAFT_VISUAL_EXTRACTIONS)
            extractions = cast(list[dict[str, Any]], visual_payload["visual_extractions"])
            visual = next(item for item in extractions if item["figure_id"] == "FIG-001")
            normalized = (run_path / "markdown/01-source-normalized.md").read_text(encoding="utf-8")
            visual_evidence = {
                "native_table_blocks": normalized.count("| Field | Owner |"),
                "image_table_candidate": visual["kind"] == "table",
                "candidate_status": visual["status"],
                "candidate_source_digest": visual["source_sha256"],
                "provider_calls": len(provider.calls)
                if isinstance(provider, FakeMultimodalModel)
                else 0,
            }

    complete_source = _complete_process_source(root)
    final_runner = CoreRunner(
        root / "sealed-runs",
        recipe_pack=REFERENCE_PACK,
        document_type="process",
    )
    waiting = final_runner.start(complete_source)
    complete_path = root / "sealed-runs" / waiting.run_id
    _approve_all(complete_path)
    sealed_result = final_runner.resume(waiting.run_id)
    if sealed_result.status != "succeeded":
        raise AssertionError(f"complete process fixture did not seal: {sealed_result.status}")
    bundle = load_sealed_bundle(complete_path)
    audit = _json(complete_path / AUDIT)
    checks = cast(dict[str, Any], audit["checks"])
    reference_checks = [
        bool(checks.get(name))
        for name in (
            "semantic_references_valid",
            "source_sections_accounted_for",
            "required_sections_present",
            "figure_references_valid",
            "figure_appendix_complete",
            "figure_asset_digests_match",
            "final_docx_figures_embedded",
        )
    ]
    metrics = {
        "source_span_coverage": sum(coverage_values) / len(coverage_values),
        "required_section_status_coverage": sum(section_status_values) / len(section_status_values),
        "invalid_provenance_references": invalid_provenance_references,
        "unresolved_blockers_in_sealed_bundles": len(cast(list[Any], audit["blockers"])),
        "deterministic_citation_reference_validity": sum(reference_checks) / len(reference_checks),
    }
    payload: dict[str, Any] = {
        "schema_version": "document-enhancer.draft-first.evaluation.v1",
        "execution_mode": "offline",
        "live_provider_proof": "not run",
        "fixtures": stage_results,
        "sealed_bundle": {
            "run_id": bundle.run_id,
            "schema_version": _json(complete_path / SEAL)["schema_version"],
            "final_document": FINAL_MARKDOWN,
            "audit_status": audit["status"],
        },
        "cross_section_ambiguity": ambiguity_evidence,
        "visual_table": visual_evidence,
        "metrics": metrics,
    }
    (root / "draft-first-metrics.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def _assert_release_metrics(payload: dict[str, Any]) -> None:
    metrics = cast(dict[str, Any], payload["metrics"])
    assert sorted(item["suffix"] for item in cast(list[dict[str, Any]], payload["fixtures"])) == [
        "docx",
        "md",
        "pdf",
        "txt",
    ]
    assert all(
        item["status"] == "waiting" and item["draft_artifacts_present"]
        for item in cast(list[dict[str, Any]], payload["fixtures"])
    )
    assert payload["sealed_bundle"]["schema_version"] == "core.seal.v2"
    assert payload["sealed_bundle"]["audit_status"] == "pass"
    assert payload["cross_section_ambiguity"]["safe_suggestion"] is True
    assert payload["cross_section_ambiguity"]["evidence_span_count"] >= 2
    assert payload["visual_table"] == {
        "candidate_source_digest": PNG_DIGEST,
        "candidate_status": "requires_review",
        "image_table_candidate": True,
        "native_table_blocks": 1,
        "provider_calls": 1,
    }
    assert metrics == {
        "deterministic_citation_reference_validity": 1.0,
        "invalid_provenance_references": 0,
        "required_section_status_coverage": 1.0,
        "source_span_coverage": 1.0,
        "unresolved_blockers_in_sealed_bundles": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="write metrics JSON at this path instead of the temporary work directory",
    )
    args = parser.parse_args()
    work_root = args.output.parent / ".draft-first-evaluation" if args.output else None
    if work_root is None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="document-enhancer-dft8-") as temporary:
            payload = run_evaluation(Path(temporary))
            _assert_release_metrics(payload)
            print(json.dumps(payload, indent=2, sort_keys=True))
        return
    payload = run_evaluation(work_root)
    _assert_release_metrics(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
