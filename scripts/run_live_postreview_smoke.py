#!/usr/bin/env python3
"""Run the thin M9 post-review flow with live Gemini calls and safe evidence only.

This is an opt-in plumbing check over fictional content. It deliberately keeps structure
recovery, analysis, question synthesis, and answer generation deterministic so the only model
calls are the post-review contracts under test: checklist, one section rewrite, content audit,
and an optional bounded revision. Document and query embeddings use Gemini Embedding 2; the RAG
answer itself uses the deterministic offline model over the resulting live-indexed catalog.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from document_enhancer.clarification import load_yaml
from document_enhancer.clarification.artifacts import write_yaml
from document_enhancer.config import load_config
from document_enhancer.domain.analysis import Finding, FindingSet
from document_enhancer.domain.enums import (
    DocumentType,
    FindingSeverity,
    FindingType,
    QuestionStatus,
)
from document_enhancer.domain.questions import (
    Answer,
    AnswersArtifact,
    QuestionsArtifact,
    RewriteChecklist,
)
from document_enhancer.ingest.recovery import StructureRecoveryConfig, StructureRecoveryService
from document_enhancer.llm import (
    EMBEDDING_MODEL,
    ROUTE_FLASH,
    ROUTE_FLASH_LITE,
    ROUTE_PRO_PREVIEW,
    CallManifest,
    EmbeddingProfile,
    GeminiEmbeddingAdapter,
    GeminiGatewayConfig,
    GeminiModelGateway,
)
from document_enhancer.prompting import PromptPackComposer, load_prompt_pack
from document_enhancer.rag import (
    DeterministicRagModel,
    RagRuntime,
    build_hybrid_retriever,
    verify_package,
)
from document_enhancer.references.loader import load_reference_pack
from document_enhancer.workflow import DocumentWorkflow, WorkflowServices
from document_enhancer.workflow.model_services import (
    GeminiAuditRevisionRunner,
    GeminiChecklistGenerator,
    GeminiContentAuditor,
    GeminiGovernedRewriter,
)

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PACK = ROOT / "prompt_packs/gemini_core"
REFERENCE_PACK = ROOT / "reference_packs/enterprise_core"
SOURCE_TEXT = """# Monthly evidence review

The monthly evidence review is recorded in the fictional Harbor Evidence Vault. The approved
owner is intentionally unspecified and must be confirmed before publication.
"""
ANSWER_TEXT = "Approved Analyst"
RAG_QUESTION = "Who owns the monthly evidence review?"


class RecordingGateway:
    """Collect secret-free manifests while delegating every provider call."""

    def __init__(self, delegate: GeminiModelGateway) -> None:
        self.delegate = delegate
        self.manifests: list[CallManifest] = []

    def invoke(self, **kwargs: Any) -> Any:
        before = self.delegate.last_manifest
        try:
            result = self.delegate.invoke(**kwargs)
        except BaseException:
            failed = self.delegate.last_manifest
            if failed is not None and failed is not before:
                self.manifests.append(failed)
            raise
        self.manifests.append(result.manifest)
        return result


class TimedEmbeddingAdapter:
    """Record aggregate latency around the standard embedding adapter without retaining text."""

    def __init__(self, delegate: GeminiEmbeddingAdapter) -> None:
        self.delegate = delegate
        self.events: list[dict[str, object]] = []

    @property
    def profile(self) -> EmbeddingProfile:
        return self.delegate.profile

    @property
    def last_manifest(self) -> object:
        return self.delegate.last_manifest

    def _record(self, operation: str, call: Any, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        result = call(*args, **kwargs)
        duration_ms = (time.perf_counter() - started) * 1000
        manifest = self.delegate.last_manifest
        self.events.append(
            {
                "operation": operation,
                "duration_ms": round(duration_ms, 3),
                "manifest": asdict(manifest) if manifest is not None else None,
                "cost": {"status": "unavailable", "usd": None},
            }
        )
        return result

    def embed_document_chunks(self, documents: Any) -> Any:
        return self._record("document", self.delegate.embed_document_chunks, documents)

    def embed_query(self, text: str) -> list[float]:
        return cast(list[float], self._record("query", self.delegate.embed_query, text))


def _analysis_with_one_owner_question(request: Any) -> FindingSet:
    finding = Finding(
        finding_id="F-M9-OWNER-001",
        category="ownership",
        severity=FindingSeverity.BLOCKER,
        finding_type=FindingType.MISSING,
        target_template_section="SEC-PROCESS-CONTENT",
        impact="The monthly evidence review needs an approved accountable role.",
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


def _composer() -> PromptPackComposer:
    references = load_reference_pack(REFERENCE_PACK)
    return PromptPackComposer(
        load_prompt_pack(PROMPT_PACK, reference_pack=references),
        reference_pack=references,
        document_type=DocumentType.PROCESS.value,
    )


def _services(
    root: Path,
    source: Path,
    gateway: RecordingGateway,
    embedding: TimedEmbeddingAdapter,
    *,
    run_id: str | None = None,
) -> WorkflowServices:
    composer = _composer()
    routed_gateway = cast(GeminiModelGateway, gateway)
    # Keeping the workflow reference-pack field unset creates exactly one synthetic target
    # section for this thin plumbing probe. The model services still receive the governed prompt
    # and reference context through the composer above.
    return WorkflowServices(
        run_root=root / "runs",
        source=source,
        run_id=run_id,
        document_type=DocumentType.PROCESS,
        structure_service=StructureRecoveryService(
            config=StructureRecoveryConfig(mode="parser", document_type="process")
        ),
        analysis_runner=_analysis_with_one_owner_question,
        question_generator=None,
        checklist_generator=GeminiChecklistGenerator(composer, routed_gateway),
        rewrite_runner=GeminiGovernedRewriter(composer, routed_gateway),
        content_auditor=GeminiContentAuditor(
            composer, routed_gateway, document_type=DocumentType.PROCESS
        ),
        audit_revision_runner=GeminiAuditRevisionRunner(
            composer, routed_gateway, document_type=DocumentType.PROCESS
        ),
        structure_mode="parser",
        gate2_enabled=True,
        offline=False,
        auto_catalog_ingest=True,
        catalog_path=root / "catalog.sqlite3",
        embedding_profile=embedding.profile,
        embedding_adapter=cast(GeminiEmbeddingAdapter, embedding),
    )


def safe_model_evidence(manifest: CallManifest) -> dict[str, object]:
    """Project a call manifest into the evidence fields used by this smoke check."""

    usage = manifest.usage.model_dump(mode="json") if manifest.usage is not None else None
    return {
        "stage": manifest.stage,
        "requested_route": manifest.requested_route_id,
        "effective_route": manifest.effective_route_id,
        "model": manifest.model,
        "status": manifest.status.value,
        "attempts": manifest.attempts,
        "retries": manifest.retries,
        "structured_repairs": manifest.structured_repairs,
        "duration_ms": round(manifest.duration_ms, 3),
        "usage": usage,
        "cost": {"status": "unavailable", "usd": None},
        "prompt_id": manifest.prompt_id,
        "prompt_digest": manifest.prompt_digest,
        "schema_digest": manifest.schema_digest,
        "result_schema_digest": manifest.result_schema_digest,
    }


def validate_model_call_shape(calls: list[dict[str, object]]) -> None:
    """Fail if the smoke test expands beyond its intended bounded live call surface."""

    counts = Counter(str(call["stage"]) for call in calls)
    expected = {
        "rewrite_checklist": (1, 1, ROUTE_FLASH_LITE),
        "section_rewrite": (1, 1, ROUTE_PRO_PREVIEW),
        "independent_content_fidelity_audit": (1, 2, ROUTE_FLASH),
        "bounded_revision": (0, 1, ROUTE_PRO_PREVIEW),
    }
    unexpected = sorted(set(counts) - set(expected))
    if unexpected:
        raise RuntimeError(f"unexpected live model stages: {', '.join(unexpected)}")
    for stage, (minimum, maximum, route) in expected.items():
        count = counts[stage]
        if count < minimum or count > maximum:
            raise RuntimeError(f"{stage} used {count} calls; expected {minimum}..{maximum}")
        if any(
            call["requested_route"] != route or call["effective_route"] != route
            for call in calls
            if call["stage"] == stage
        ):
            raise RuntimeError(f"{stage} did not remain on exact route {route}")


def _render_answer(result: Any, *, console: Console) -> None:
    console.print(Panel(result.answer.answer_markdown, title="Grounded offline answer"))
    table = Table(title="Validated citations")
    table.add_column("Citation")
    table.add_column("Document")
    table.add_column("Section")
    for citation in result.answer.citations:
        table.add_row(
            citation.citation_id,
            f"{citation.document_id}@{citation.version_id}",
            " / ".join(citation.section_path),
        )
    console.print(table)


def run_live_postreview_smoke(root: Path, *, console: Console | None = None) -> dict[str, object]:
    """Run the bounded fictional flow; caller owns output-directory lifecycle."""

    root.mkdir(parents=True, exist_ok=False)
    source = root / "source.md"
    source.write_text(SOURCE_TEXT, encoding="utf-8")

    config = load_config(project_path=ROOT / "document-enhancer.toml")
    routes = {
        "structure": config.gemini.structure_model,
        "analysis": config.gemini.developer_model,
        "rewrite": config.gemini.rewrite_model,
        "embedding": config.gemini.embedding_model,
    }
    required_routes = {
        "structure": ROUTE_FLASH_LITE,
        "analysis": ROUTE_FLASH,
        "rewrite": ROUTE_PRO_PREVIEW,
        "embedding": EMBEDDING_MODEL,
    }
    if routes != required_routes:
        raise RuntimeError("configured Gemini model routes do not match the governed M9 routes")
    gateway_config = GeminiGatewayConfig.from_env(
        backend=config.gemini.backend,
        project=config.gemini.project,
        location=config.gemini.location,
        allow_pro_fallback=False,
    )
    if gateway_config.backend.value == "developer_api" and gateway_config.api_key is None:
        raise RuntimeError("GOOGLE_API_KEY or GEMINI_API_KEY is required")
    gateway = RecordingGateway(GeminiModelGateway(gateway_config))
    embedding = TimedEmbeddingAdapter(
        GeminiEmbeddingAdapter(
            profile=EmbeddingProfile(
                model=config.gemini.embedding_model,
                dimensions=config.gemini.embedding_dimensions,
                backend=config.gemini.backend,
            ),
            project=config.gemini.project,
            location=config.gemini.location,
        )
    )

    gate1 = DocumentWorkflow(_services(root, source, gateway, embedding)).run()
    if gate1.status != "waiting" or gate1.current_stage != "gate1":
        raise RuntimeError("fictional smoke run did not stop at Gate 1")
    run_path = root / "runs" / gate1.run_id
    questions = load_yaml(run_path / "clarification/questions.yaml", QuestionsArtifact)
    if len(questions.questions) != 1 or not questions.questions[0].blocking:
        raise RuntimeError("fictional smoke run did not create exactly one blocking question")
    write_yaml(
        run_path / "clarification/answers.yaml",
        AnswersArtifact(
            document_id=questions.document_id,
            answers=[
                Answer(
                    answer_id="ANS-M9-OWNER-001",
                    question_id=questions.questions[0].question_id,
                    status=QuestionStatus.ANSWERED,
                    answer=ANSWER_TEXT,
                    responder="fictional-reviewer@example.invalid",
                    evidence_reference="answer://m9-live-postreview/owner",
                )
            ],
        ),
    )

    gate2 = DocumentWorkflow(
        _services(root, Path(), gateway, embedding, run_id=gate1.run_id)
    ).resume()
    if gate2.status != "waiting" or gate2.current_stage != "gate2":
        raise RuntimeError("validated Gate 1 inputs did not reach Gate 2")
    checklist_path = run_path / "clarification/rewrite-checklist.yaml"
    checklist = load_yaml(checklist_path, RewriteChecklist)
    write_yaml(
        checklist_path,
        checklist.model_copy(
            update={
                "approved_by": "fictional-approver@example.invalid",
                "approved_at": datetime.now(UTC),
            }
        ),
    )

    completed = DocumentWorkflow(
        _services(root, Path(), gateway, embedding, run_id=gate1.run_id)
    ).resume()
    if completed.status != "succeeded":
        raise RuntimeError("approved post-review smoke run did not complete")
    enhanced = (run_path / "output/enhanced.md").read_text(encoding="utf-8")
    if ANSWER_TEXT not in enhanced:
        raise RuntimeError("approved Gate 1 answer did not reach the enhanced document")
    package = verify_package(run_path / "rag/document-rag.sqlite3", export_dir=run_path / "export")
    if not package.valid:
        raise RuntimeError("live-embedded RAG package verification failed")

    retriever = build_hybrid_retriever(
        root / "catalog.sqlite3",
        cast(GeminiEmbeddingAdapter, embedding),
        vector_backend="exact_scan",
        top_k=5,
    )
    answer = RagRuntime(retriever, DeterministicRagModel()).answer(RAG_QUESTION)
    if not answer.answer.citations or not answer.grounding.passed:
        raise RuntimeError("deterministic answer lacks validated citations")
    output_console = console or Console()
    _render_answer(answer, console=output_console)

    model_calls = [safe_model_evidence(item) for item in gateway.manifests]
    validate_model_call_shape(model_calls)
    audit = json.loads((run_path / "audit/audit.json").read_text(encoding="utf-8"))
    return {
        "schema_version": "m9.live-postreview.v1",
        "evidence_kind": "live_model",
        "fictional_content": True,
        "run_id": gate1.run_id,
        "gates": {
            "gate1": {"status": gate1.status, "stage": gate1.current_stage},
            "gate2": {"status": gate2.status, "stage": gate2.current_stage},
            "completed": {"status": completed.status, "stage": completed.current_stage},
        },
        "approved_answer_promoted": True,
        "audit": {
            "status": audit["status"],
            "route": audit["routing"]["route"],
            "revision_count": audit["revision_count"],
        },
        "model_calls": model_calls,
        "embedding_calls": embedding.events,
        "rag_package": {
            "valid": package.valid,
            "rows": package.row_counts,
            "catalog": str(root / "catalog.sqlite3"),
        },
        "answer": {
            "question": RAG_QUESTION,
            "status": answer.answer.status.value,
            "grounding_passed": answer.grounding.passed,
            "markdown": answer.answer.answer_markdown,
            "citations": [item.model_dump(mode="json") for item in answer.answer.citations],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".document-enhancer/m9-live-postreview"),
    )
    parser.add_argument("--force", action="store_true", help="remove prior output first")
    parser.add_argument("--json", action="store_true", help="suppress Rich output")
    args = parser.parse_args()
    if os.getenv("DOCENHANCE_RUN_LIVE") != "1":
        parser.error("live checks are opt-in: set DOCENHANCE_RUN_LIVE=1")
    if args.output.exists():
        if not args.force:
            parser.error(f"output exists; use --force to replace it: {args.output}")
        shutil.rmtree(args.output)
    console = Console(quiet=args.json)
    result = run_live_postreview_smoke(args.output, console=console)
    evidence = args.output / "live-evidence.json"
    evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({"evidence": str(evidence), "status": "passed"}, sort_keys=True))
    else:
        console.print(f"[green]PASSED[/green] safe evidence: {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
