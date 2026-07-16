#!/usr/bin/env python3
"""Run the reproducible M8 human-review-to-grounded-RAG demonstration."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from document_enhancer.clarification import load_yaml
from document_enhancer.clarification.artifacts import write_yaml
from document_enhancer.domain.analysis import Finding, FindingSet
from document_enhancer.domain.enums import FindingSeverity, FindingType, QuestionStatus
from document_enhancer.domain.questions import (
    Answer,
    AnswersArtifact,
    QuestionsArtifact,
    RewriteChecklist,
)
from document_enhancer.llm import EmbeddingProfile, GeminiEmbeddingAdapter
from document_enhancer.rag import (
    DeterministicRagModel,
    OfflineDeterministicEmbedder,
    RagRuntime,
    build_hybrid_retriever,
    catalog_embedding_profile,
    verify_package,
)
from document_enhancer.workflow import DocumentWorkflow, WorkflowServices


def _analysis_with_one_review_question(request: Any) -> FindingSet:
    finding = Finding(
        finding_id="F-DEMO-OWNER-001",
        category="control",
        severity=FindingSeverity.BLOCKER,
        finding_type=FindingType.MISSING,
        impact="The monthly review record needs an approved owner.",
        proposed_disposition="Ask the reviewer for the approved role.",
        requires_human_answer=True,
        blocking=True,
    )
    return FindingSet(
        document_id=request.document_id,
        source_digest=request.source_digest,
        findings=[finding],
        blocking_count=1,
    )


def _services(
    root: Path,
    source: Path,
    *,
    run_id: str | None = None,
    analysis_runner: Any | None = None,
) -> WorkflowServices:
    return WorkflowServices(
        run_root=root / "runs",
        source=source,
        run_id=run_id,
        analysis_runner=analysis_runner,
        structure_mode="parser",
        gate2_enabled=True,
        offline=True,
        catalog_path=root / "catalog.sqlite3",
        embedding_profile=EmbeddingProfile(),
    )


def run_demo(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=False)
    source = root / "source.md"
    source.write_text(
        "# Monthly review\n\nThe approved analyst records the monthly review result in the fictional Harbor Evidence Vault.\n",
        encoding="utf-8",
    )
    waiting = DocumentWorkflow(
        _services(root, source, analysis_runner=_analysis_with_one_review_question)
    ).run()
    if waiting.status != "waiting" or waiting.current_stage != "gate1":
        raise RuntimeError("demo did not stop at the first human review gate")

    run_path = root / "runs" / waiting.run_id
    questions = load_yaml(run_path / "clarification/questions.yaml", QuestionsArtifact)
    answers = AnswersArtifact(
        document_id=questions.document_id,
        answers=[
            Answer(
                answer_id="ANS-DEMO-OWNER-001",
                question_id=questions.questions[0].question_id,
                status=QuestionStatus.ANSWERED,
                answer="Approved Analyst",
                responder="fictional-reviewer@example.invalid",
                evidence_reference="answer://m8-demo/owner",
            )
        ],
    )
    write_yaml(run_path / "clarification/answers.yaml", answers)

    gate2 = DocumentWorkflow(_services(root, Path(), run_id=waiting.run_id)).resume()
    if gate2.status != "waiting" or gate2.current_stage != "gate2":
        raise RuntimeError("edited Gate 1 inputs did not validate and reach Gate 2")
    checklist_path = run_path / "clarification/rewrite-checklist.yaml"
    checklist = load_yaml(checklist_path, RewriteChecklist)
    approved = checklist.model_copy(
        update={
            "approved_by": "fictional-approver@example.invalid",
            "approved_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    write_yaml(checklist_path, approved)

    completed = DocumentWorkflow(_services(root, Path(), run_id=waiting.run_id)).resume()
    if completed.status != "succeeded":
        raise RuntimeError("demo workflow did not complete after Gate 2 approval")
    audit = json.loads((run_path / "audit/audit.json").read_text(encoding="utf-8"))
    package = verify_package(run_path / "rag/document-rag.sqlite3", export_dir=run_path / "export")
    if audit["status"] != "pass" or not package.valid:
        raise RuntimeError("audit or RAG package verification failed")

    profile, _identity = catalog_embedding_profile(root / "catalog.sqlite3")
    embedding = GeminiEmbeddingAdapter(
        profile=profile,
        embedder=OfflineDeterministicEmbedder(profile.dimensions),
    )
    retriever = build_hybrid_retriever(
        root / "catalog.sqlite3", embedding, vector_backend="exact_scan", top_k=5
    )
    query = "Who records the monthly review result?"
    search = retriever.search(query)
    answer = RagRuntime(retriever, DeterministicRagModel()).answer(query)
    if not search.hits or answer.answer.status.value not in {"answered", "partial"}:
        raise RuntimeError("offline retrieval or grounded answer failed")
    if not answer.answer.citations or not answer.grounding.passed:
        raise RuntimeError("offline answer lacks validated citations")
    return {
        "schema_version": "m8.demo.v1",
        "run_id": waiting.run_id,
        "gate1": {"status": waiting.status, "stage": waiting.current_stage},
        "review_inputs_validated": True,
        "gate2": {"status": gate2.status, "stage": gate2.current_stage},
        "completed": {"status": completed.status, "stage": completed.current_stage},
        "audit": {"status": audit["status"], "route": audit["routing"]["route"]},
        "rag_package": {
            "valid": package.valid,
            "rows": package.row_counts,
            "database": str(run_path / "rag/document-rag.sqlite3"),
        },
        "catalog": str(root / "catalog.sqlite3"),
        "search": {
            "query": query,
            "hits": [hit.chunk_id for hit in search.hits],
            "channels": search.diagnostics.channel_counts,
        },
        "answer": {
            "status": answer.answer.status.value,
            "grounding_passed": answer.grounding.passed,
            "citations": [citation.model_dump(mode="json") for citation in answer.answer.citations],
            "markdown": answer.answer.answer_markdown,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".document-enhancer/m8-demo"))
    parser.add_argument("--force", action="store_true", help="remove a prior demo output first")
    args = parser.parse_args()
    if args.output.exists():
        if not args.force:
            parser.error(f"output exists; use --force to replace it: {args.output}")
        shutil.rmtree(args.output)
    result = run_demo(args.output)
    summary = args.output / "demo-result.json"
    summary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": str(summary), "status": "passed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
