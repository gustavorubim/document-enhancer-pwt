"""Controlled five-phase runner used during the v2 migration.

The runner is intentionally boring: each phase reads named artifacts and writes
named artifacts.  It has no graph runtime, database checkpoint, hidden global
state, or provider-specific object in its persisted record. Provider-backed
analysis and rewriting are optional collaborators behind the same phase seams.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from ruamel.yaml import YAML

from document_enhancer.ingest.models import RecoveryThresholds
from document_enhancer.ingest.normalize import normalize_document
from document_enhancer.ingest.pipeline import DocumentIngestor

from .audit import (
    deferred_decisions_resolved,
    dual_flow_artifacts_present,
    graph_types_valid,
    no_unresolved_placeholders,
    render_audit_markdown,
    required_sections_present,
    section_assessments_present,
    semantic_references_valid,
    source_anchor_retained,
    source_sections_retained,
)
from .export import public_graph
from .models import (
    AuditReport,
    Decision,
    DecisionBundle,
    ReviewReport,
    RunRecord,
    Section,
    SourceDocument,
    SourceSpan,
    Waiver,
)
from .providers import AuditProvider, ReviewProvider, RewriteProvider, StructureProvider
from .recipes import Recipe, load_recipe
from .review import (
    bounded_batches,
    build_review,
    merge_provider_review,
    render_flow_markdown,
    render_macro_markdown,
    render_review_index_markdown,
    render_sections_markdown,
)
from .rewrite import (
    apply_reviewer_decisions,
    apply_template_stubs,
    compile_rewrite_plan,
    graph_json_lines,
    render_docx,
    semantic_diff,
    semantic_graph,
    source_target_csv,
)
from .store import RunStore, register_artifact

_PLACEHOLDER_RE = re.compile(r"\b(?:TBD|TODO|TBC)\b|\[\s*\?\s*\]|\?{3,}", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(UTC)


class CoreRunner:
    """Run a document bundle through extract, analyze, review, rewrite, verify."""

    def __init__(
        self,
        root: Path,
        *,
        recipe_pack: Path | None = None,
        document_type: str = "process",
        structure_mode: str = "auto",
        execution_mode: str = "offline",
        review_provider: ReviewProvider | None = None,
        rewrite_provider: RewriteProvider | None = None,
        structure_provider: StructureProvider | None = None,
        audit_provider: AuditProvider | None = None,
    ) -> None:
        self.store = RunStore(root)
        self.ingestor = DocumentIngestor()
        self.document_type = document_type
        if execution_mode not in {"offline", "live"}:
            raise ValueError("core execution_mode must be offline or live")
        self.execution_mode: Literal["offline", "live"] = cast(
            Literal["offline", "live"], execution_mode
        )
        if structure_mode not in {"auto", "parser", "off"}:
            raise ValueError("core structure_mode must be auto, parser, or off")
        self.structure_mode = structure_mode
        self.structure_thresholds = RecoveryThresholds()
        self.review_provider = review_provider
        self.rewrite_provider = rewrite_provider
        self.structure_provider = structure_provider
        self.audit_provider = audit_provider
        self.recipe: Recipe | None = (
            load_recipe(recipe_pack, document_type=document_type) if recipe_pack else None
        )

    def start(
        self,
        source: Path,
        *,
        recipe: str = "enterprise_core",
        stop_at: str = "complete",
    ) -> RunRecord:
        """Create a new run and execute until review or completion.

        A new run is always created, even when the source digest matches an
        earlier run.  This makes retries and comparisons explicit and prevents
        failed or stale state from being silently reused.
        """

        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"source is not a regular file: {source}")
        raw_bytes = source.read_bytes()
        raw = self.ingestor.parse(source)
        run_id = f"{raw.source_digest[:12]}-{uuid.uuid4().hex[:10]}"
        self.store.create_dir(run_id)
        record = RunRecord(
            run_id=run_id,
            source_digest=raw.source_digest,
            recipe_digest=self.recipe.recipe_digest if self.recipe else "0" * 64,
            configuration_digest=self._configuration_digest(),
            source_name=source.name,
            recipe=self.recipe.recipe_id if self.recipe else recipe,
            execution_mode=self.execution_mode,
            status="running",
            phase="extract",
        )
        self.store.save_run(record)
        try:
            record = self._extract(record, raw, raw_bytes, source)
            record = self._analyze(record, raw)
            questions = self._load_review(record).questions
            if questions:
                record = self._update(
                    record,
                    status="waiting",
                    phase="human_review",
                    unresolved_question_ids=[
                        item.question_id for item in questions if item.blocking
                    ],
                )
                return record
            if stop_at == "questions":
                return self._update(record, status="waiting", phase="human_review")
            return self._finish(record)
        except Exception as exc:
            self._update(record, status="failed", error=f"{type(exc).__name__}: {exc}")
            raise RuntimeError(f"core run {record.run_id} failed: {exc}") from exc

    def resume(self, run_id: str, *, decisions_path: Path | None = None) -> RunRecord:
        """Continue a waiting run after the reviewer edits ``decisions.yaml``."""

        record = self.store.load_run(run_id)
        if record.status == "running" and record.phase == "analyze":
            source_path = (
                self.store.run_path(run_id)
                / "source"
                / ("original" + Path(record.source_name).suffix.lower())
            )
            if not source_path.is_file():
                raise FileNotFoundError(f"source artifact is missing for run {run_id}")
            raw = self.ingestor.parse(source_path)
            record = self._analyze(record, raw)
            questions = self._load_review(record).questions
            if questions:
                return self._update(
                    record,
                    status="waiting",
                    phase="human_review",
                    unresolved_question_ids=[
                        item.question_id for item in questions if item.blocking
                    ],
                )
            return self._finish(record)
        if record.status == "running" and record.phase == "rewrite":
            return self._finish(record)
        if record.status != "waiting" or record.phase != "human_review":
            raise ValueError(f"run {run_id} is not waiting for human review")
        path = decisions_path or (self.store.run_path(run_id) / "review/decisions.yaml")
        if not path.is_file():
            return record
        bundle = self._read_decision_bundle(path)
        decisions = bundle.decisions
        review = self._load_review(record)
        answers = {item.question_id: item for item in decisions}
        unresolved = [
            question.question_id
            for question in review.questions
            if question.blocking
            and (
                question.question_id not in answers
                or answers[question.question_id].disposition == "defer"
                or (
                    answers[question.question_id].disposition == "accept"
                    and not answers[question.question_id].answer.strip()
                )
            )
        ]
        if not bundle.approve_rewrite:
            unresolved = [*unresolved, "approve_rewrite"]
        self.store.write_json(
            run_id,
            "review/decisions.json",
            bundle.model_dump(mode="json"),
        )
        if unresolved:
            return self._update(record, unresolved_question_ids=unresolved)
        return self._finish(self._update(record, status="running", phase="rewrite"))

    def _extract(self, record: RunRecord, raw: Any, raw_bytes: bytes, source: Path) -> RunRecord:
        if self.recipe:
            record = register_artifact(
                record,
                "recipe.compiled",
                self.store.write_json(
                    record.run_id,
                    "recipe/compiled.json",
                    self._recipe_manifest(),
                ),
            )
        normalized = normalize_document(raw, thresholds=self.structure_thresholds)
        selected_structure_mode = (
            "parser" if self.structure_mode in {"parser", "off"} else normalized.routing.mode
        )
        structure_warnings = list(normalized.quality.warnings)
        if self.structure_mode == "off":
            structure_warnings.append("structure_recovery_disabled")
        elif self.structure_mode == "parser" and normalized.routing.mode == "llm_recovery":
            structure_warnings.append("structure_recovery_deferred_by_parser_mode")
        spans = [
            SourceSpan(
                span_id=block.span_id,
                start=block.location.char_start or 0,
                end=block.location.char_end or 0,
                line_start=block.location.line_start or 1,
                line_end=block.location.line_end or block.location.line_start or 1,
                sha256=block.content_digest,
            )
            for block in raw.blocks
        ]
        sections = self._sections(raw.blocks, spans)
        structure_manifest: Any | None = None
        if selected_structure_mode == "llm_recovery" and self.structure_provider:
            try:
                recovered = self.structure_provider.recover(
                    source_text=normalized.normalized_markdown,
                    source_digest=raw.source_digest,
                    spans=[{"span_id": block.span_id, "text": block.text} for block in raw.blocks],
                    recipe=self.recipe,
                )
                structure_manifest = getattr(
                    getattr(self.structure_provider, "gateway", None), "last_manifest", None
                )
                if self._valid_recovered_sections(recovered, {item.span_id for item in spans}):
                    sections = recovered
                    structure_warnings.append("llm_recovery_promoted")
                else:
                    structure_warnings.append("llm_recovery_rejected_invalid_coverage")
                    selected_structure_mode = "parser"
            except Exception as exc:
                structure_warnings.append(f"llm_recovery_failed:{type(exc).__name__}")
                selected_structure_mode = "parser"
        elif selected_structure_mode == "llm_recovery":
            structure_warnings.append("recovery_dependencies_unavailable")
        metadata = SourceDocument(
            source_name=source.name,
            source_digest=raw.source_digest,
            media_type=raw.media_type,
            size_bytes=len(raw_bytes),
            parser=f"{raw.parser_name}@{raw.parser_version}",
            structure_score=normalized.quality.structure_score,
            structure_mode=selected_structure_mode,
            structure_reasons=list(normalized.routing.reasons),
            warnings=[item.message for item in raw.warnings] + structure_warnings,
            spans=spans,
            sections=sections,
        )
        suffix = source.suffix.lower() or ".bin"
        record = register_artifact(
            record,
            "source.original",
            self.store.write_bytes(
                record.run_id,
                f"source/original{suffix}",
                raw_bytes,
                media_type=raw.media_type,
            ),
        )
        record = register_artifact(
            record,
            "source.metadata",
            self.store.write_json(
                record.run_id, "source/source.json", metadata.model_dump(mode="json")
            ),
        )
        record = register_artifact(
            record,
            "source.structure_quality",
            self.store.write_json(
                record.run_id,
                "source/structure-quality.json",
                normalized.quality.model_dump(mode="json"),
            ),
        )
        record = register_artifact(
            record,
            "source.structure_routing",
            self.store.write_json(
                record.run_id,
                "source/structure-routing.json",
                {
                    "configured_mode": self.structure_mode,
                    "selected_mode": selected_structure_mode,
                    "routing": normalized.routing.model_dump(mode="json"),
                    "warnings": structure_warnings,
                },
            ),
        )
        if structure_manifest is not None:
            record = register_artifact(
                record,
                "debug.structure_call",
                self.store.write_text(
                    record.run_id,
                    "debug/structure.jsonl",
                    json.dumps(structure_manifest.model_dump(mode="json"), sort_keys=True) + "\n",
                    media_type="application/jsonl",
                ),
            )
        record = register_artifact(
            record,
            "source.normalized",
            self.store.write_text(
                record.run_id,
                "source/normalized.md",
                normalized.normalized_markdown,
                media_type="text/markdown; charset=utf-8",
            ),
        )
        return self._update(record, phase="analyze")

    def _recipe_manifest(self) -> dict[str, object]:
        if self.recipe is None:
            return {"recipe_id": "heuristic-default", "recipe_digest": "0" * 64}
        return {
            "schema_version": "core.recipe.v1",
            "recipe_id": self.recipe.recipe_id,
            "recipe_digest": self.recipe.recipe_digest,
            "reference_pack": {
                "pack_id": self.recipe.pack.pack_id,
                "version": self.recipe.pack.version,
                "pack_sha256": self.recipe.pack.pack_sha256,
            },
            "document_type": self.recipe.document_type,
            "requirements": {
                "sections": len(self.recipe.required_sections),
                "required": sum(
                    self.recipe.classify(item) == "required"
                    for item in self.recipe.required_sections
                ),
                "conditional": sum(
                    self.recipe.classify(item) == "conditional"
                    for item in self.recipe.required_sections
                ),
                "recommended": sum(
                    self.recipe.classify(item) == "recommended"
                    for item in self.recipe.required_sections
                ),
                "tables": len(self.recipe.tables),
                "section_specs": [
                    {
                        "id": str(item.get("id", "")),
                        "heading": str(item.get("heading", "")),
                        "classification": self.recipe.classify(item),
                    }
                    for item in self.recipe.required_sections
                ],
                "table_specs": [
                    {
                        "id": str(item.get("id", "")),
                        "section_id": str(item.get("section_id", "")),
                        "classification": self.recipe.classify(item),
                    }
                    for item in self.recipe.tables
                ],
            },
            "rubric_criteria": len(self.recipe.rubric_criteria),
        }

    def _analyze(self, record: RunRecord, raw: Any) -> RunRecord:
        source_text = "\n".join(block.text for block in raw.blocks)
        source_spans = [
            SourceSpan(
                span_id=block.span_id,
                start=block.location.char_start or 0,
                end=block.location.char_end or 0,
                line_start=block.location.line_start or 1,
                line_end=block.location.line_end or block.location.line_start or 1,
                sha256=block.content_digest,
            )
            for block in raw.blocks
        ]
        sections = self._source_sections(record, raw.blocks, source_spans)
        review = build_review(
            blocks=raw.blocks,
            source_spans=source_spans,
            sections=sections,
            recipe=self.recipe,
        )
        questions = review.questions
        provider_manifests: list[Any] = []
        if self.review_provider:
            candidates = [
                self.review_provider.review(
                    source_text=source_text,
                    source_digest=record.source_digest,
                    recipe=self.recipe,
                )
            ]
            section_reviewer = getattr(self.review_provider, "review_sections", None)
            if callable(section_reviewer):
                for batch in bounded_batches(sections, size=4):
                    candidates.append(
                        section_reviewer(
                            source_text=source_text,
                            source_digest=record.source_digest,
                            sections=batch,
                            recipe=self.recipe,
                        )
                    )
            for candidate in candidates:
                provider_manifest = getattr(
                    getattr(self.review_provider, "gateway", None), "last_manifest", None
                )
                if provider_manifest is not None:
                    provider_manifests.append(provider_manifest)
                review = merge_provider_review(
                    review,
                    candidate,
                    allowed_span_ids={item.span_id for item in source_spans},
                )
            questions = review.questions
        record = register_artifact(
            record,
            "review.report",
            self.store.write_json(
                record.run_id, "review/review.json", review.model_dump(mode="json")
            ),
        )
        record = register_artifact(
            record,
            "review.report_markdown",
            self.store.write_text(
                record.run_id,
                "review/review.md",
                render_review_index_markdown(review),
                media_type="text/markdown; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "review.macro_markdown",
            self.store.write_text(
                record.run_id,
                "review/macro.md",
                render_macro_markdown(review),
                media_type="text/markdown; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "review.sections_markdown",
            self.store.write_text(
                record.run_id,
                "review/sections.md",
                render_sections_markdown(review),
                media_type="text/markdown; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "review.flow_markdown",
            self.store.write_text(
                record.run_id,
                "review/flow.md",
                render_flow_markdown(review),
                media_type="text/markdown; charset=utf-8",
            ),
        )
        if provider_manifests:
            record = register_artifact(
                record,
                "debug.review_call",
                self.store.write_text(
                    record.run_id,
                    "debug/review.jsonl",
                    "".join(
                        json.dumps(item.model_dump(mode="json"), sort_keys=True) + "\n"
                        for item in provider_manifests
                    ),
                    media_type="application/jsonl",
                ),
            )
        record = register_artifact(
            record,
            "review.flow",
            self.store.write_text(
                record.run_id,
                "review/flow.mmd",
                review.inferred_mermaid,
                media_type="text/vnd.mermaid; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "review.flow_inferred",
            self.store.write_text(
                record.run_id,
                "review/flow.inferred.mmd",
                review.inferred_mermaid,
                media_type="text/vnd.mermaid; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "review.flow_proposed",
            self.store.write_text(
                record.run_id,
                "review/flow.proposed.mmd",
                review.proposed_mermaid,
                media_type="text/vnd.mermaid; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "review.decisions",
            self.store.write_text(
                record.run_id,
                "review/decisions.yaml",
                self._questions_yaml(review),
                media_type="application/yaml; charset=utf-8",
            ),
        )
        return self._update(
            record,
            phase="human_review",
            unresolved_question_ids=[q.question_id for q in questions if q.blocking],
        )

    def _finish(self, record: RunRecord) -> RunRecord:
        normalized = self.store.read_text(record.run_id, "source/normalized.md")
        decisions = self._read_decisions_file(record.run_id)
        review = self._load_review(record)
        plan = compile_rewrite_plan(
            source_digest=record.source_digest,
            review=review,
            decisions=decisions,
            recipe=self.recipe,
        )
        record = register_artifact(
            record,
            "rewrite.plan",
            self.store.write_json(
                record.run_id,
                "rewrite/plan.json",
                plan.model_dump(mode="json"),
            ),
        )
        decision_bundle = self._read_decision_bundle(
            self.store.run_path(record.run_id) / "review/decisions.yaml"
        )
        waived = {item.requirement_id for item in decision_bundle.waivers}
        final_text = normalized
        changes: list[str] = []
        rewrite_manifest: Any | None = None
        if self.rewrite_provider:
            final_text, changes = self.rewrite_provider.rewrite(
                source_text=normalized,
                review=review,
                decisions=[item.model_dump(mode="json") for item in decisions],
                source_digest=record.source_digest,
                plan=plan,
                template_text=self.recipe.template_text if self.recipe else "",
                steering=decision_bundle.steering,
            )
            rewrite_manifest = getattr(
                getattr(self.rewrite_provider, "gateway", None), "last_manifest", None
            )
        else:
            final_text, changes = apply_reviewer_decisions(
                final_text,
                decisions=decisions,
                steering=decision_bundle.steering,
            )
            final_text, stub_changes = apply_template_stubs(
                final_text,
                plan=plan,
                recipe=self.recipe,
                decisions=decisions,
                waived_requirement_ids=waived,
            )
            changes.extend(stub_changes)
        record = self._update(record, status="running", phase="rewrite", unresolved_question_ids=[])
        record = register_artifact(
            record,
            "output.final_markdown",
            self.store.write_text(
                record.run_id,
                "output/final.md",
                final_text,
                media_type="text/markdown; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "output.final_docx",
            self.store.write_bytes(
                record.run_id,
                "output/final.docx",
                render_docx(final_text),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )
        semantic = semantic_graph(review, final_text, recipe=self.recipe)
        record = register_artifact(
            record,
            "output.semantic",
            self.store.write_json(record.run_id, "output/semantic.json", semantic),
        )
        record = register_artifact(
            record,
            "output.ontology",
            self.store.write_json(
                record.run_id,
                "output/ontology.json",
                public_graph(semantic),
            ),
        )
        semantic_before = semantic_graph(review, normalized, recipe=self.recipe)
        semantic_diff_payload = semantic_diff(semantic_before, semantic)
        record = register_artifact(
            record,
            "audit.semantic_diff",
            self.store.write_json(
                record.run_id,
                "audit/semantic-diff.json",
                semantic_diff_payload,
            ),
        )
        graph_lines = "".join(json_line + "\n" for json_line in graph_json_lines(semantic))
        record = register_artifact(
            record,
            "output.graph",
            self.store.write_text(
                record.run_id, "output/graph.jsonl", graph_lines, media_type="application/jsonl"
            ),
        )
        record = register_artifact(
            record,
            "output.flow",
            self.store.write_text(
                record.run_id,
                "output/flow.mmd",
                review.proposed_mermaid or review.inferred_mermaid,
                media_type="text/vnd.mermaid; charset=utf-8",
            ),
        )
        source_text = normalized
        diff = "\n".join(
            difflib.unified_diff(
                source_text.splitlines(),
                final_text.splitlines(),
                fromfile="source/normalized.md",
                tofile="output/final.md",
                lineterm="",
            )
        )
        change_note = (
            f"Applied {len(changes)} rewrite change(s).\n"
            + (
                "\n".join(f"- {item}" for item in changes)
                if changes
                else "- No explicit rewrite changes were recorded."
            )
            + f"\n\n{diff or 'No textual changes were required.'}\n"
        )
        record = register_artifact(
            record,
            "audit.changes",
            self.store.write_text(
                record.run_id,
                "audit/changes.md",
                change_note,
                media_type="text/markdown; charset=utf-8",
            ),
        )
        if rewrite_manifest is not None:
            record = register_artifact(
                record,
                "debug.rewrite_call",
                self.store.write_text(
                    record.run_id,
                    "debug/rewrite.jsonl",
                    json.dumps(rewrite_manifest.model_dump(mode="json"), sort_keys=True) + "\n",
                    media_type="application/jsonl",
                ),
            )
        record = register_artifact(
            record,
            "audit.source_to_target",
            self.store.write_text(
                record.run_id,
                "audit/source-to-target.csv",
                source_target_csv(review, final_text),
                media_type="text/csv; charset=utf-8",
            ),
        )
        audit = AuditReport(
            status="pass",
            checks={
                "final_markdown_nonempty": bool(final_text.strip()),
                "source_digest_preserved": record.source_digest == self._source_digest(record),
                "questions_resolved": not record.unresolved_question_ids,
                "no_unresolved_placeholders": no_unresolved_placeholders(final_text),
                "deferred_decisions_resolved": deferred_decisions_resolved(
                    plan.deferred_decision_ids
                ),
                "source_anchor_retained": source_anchor_retained(normalized, final_text),
                "source_sections_accounted_for": source_sections_retained(review, final_text),
                "required_sections_present": required_sections_present(
                    self.recipe, final_text, waived_requirement_ids=waived
                ),
                "section_assessments_present": section_assessments_present(review),
                "dual_flow_artifacts_present": dual_flow_artifacts_present(review),
                "semantic_references_valid": semantic_references_valid(semantic),
                "graph_types_valid": graph_types_valid(semantic, self.recipe),
            },
            summary="Final document was rendered and passed the deterministic bundle checks.",
        )
        audit_manifest: Any | None = None
        if self.audit_provider:
            try:
                independent = self.audit_provider.audit(
                    source_text=normalized,
                    final_text=final_text,
                    review=review,
                    decisions=[item.model_dump(mode="json") for item in decisions],
                    source_digest=record.source_digest,
                )
                audit_manifest = getattr(
                    getattr(self.audit_provider, "gateway", None), "last_manifest", None
                )
                checks = {
                    **audit.checks,
                    "independent_content_audit": independent.status == "pass",
                }
                blockers = list(audit.blockers)
                if independent.status != "pass":
                    blockers.extend(independent.blockers or ["independent_content_audit"])
                audit = audit.model_copy(
                    update={
                        "checks": checks,
                        "blockers": list(dict.fromkeys(blockers)),
                        "summary": f"{audit.summary} Independent audit: {independent.summary}",
                    }
                )
            except Exception as exc:
                audit = audit.model_copy(
                    update={
                        "checks": {**audit.checks, "independent_content_audit": False},
                        "blockers": [
                            *audit.blockers,
                            f"independent_audit_unavailable:{type(exc).__name__}",
                        ],
                        "summary": "Independent content audit could not be completed.",
                    }
                )
        if audit_manifest is not None:
            record = register_artifact(
                record,
                "debug.audit_call",
                self.store.write_text(
                    record.run_id,
                    "debug/audit.jsonl",
                    json.dumps(audit_manifest.model_dump(mode="json"), sort_keys=True) + "\n",
                    media_type="application/jsonl",
                ),
            )
        audit_failed = [key for key, passed in audit.checks.items() if not passed]
        if audit_failed:
            audit = audit.model_copy(
                update={
                    "status": "fail",
                    "blockers": audit_failed,
                    "summary": "Final document is not promotable until failed checks are resolved.",
                }
            )
        record = register_artifact(
            record,
            "audit.report",
            self.store.write_json(record.run_id, "audit/audit.json", audit.model_dump(mode="json")),
        )
        record = register_artifact(
            record,
            "audit.report_markdown",
            self.store.write_text(
                record.run_id,
                "audit/audit.md",
                render_audit_markdown(audit),
                media_type="text/markdown; charset=utf-8",
            ),
        )
        if audit.status == "pass":
            record = register_artifact(
                record,
                "audit.seal",
                self.store.write_json(
                    record.run_id,
                    "audit/seal.json",
                    {
                        "run_id": record.run_id,
                        "source_digest": record.source_digest,
                        "final_digest": record.artifacts["output.final_markdown"].sha256,
                        "audit_digest": record.artifacts["audit.report"].sha256,
                        "artifact_paths": sorted(item.path for item in record.artifacts.values()),
                        "sealed": True,
                    },
                ),
            )
        return self._update(
            record,
            status="succeeded" if audit.status == "pass" else "failed",
            phase="verify",
            error=None,
        )

    def _load_review(self, record: RunRecord) -> ReviewReport:
        return ReviewReport.model_validate(
            self.store.read_json(record.run_id, "review/review.json")
        )

    def _source_sections(
        self, record: RunRecord, blocks: tuple[Any, ...], spans: list[SourceSpan]
    ) -> list[Section]:
        try:
            payload = self.store.read_json(record.run_id, "source/source.json")
            sections = [Section.model_validate(item) for item in payload.get("sections", [])]
            if self._valid_recovered_sections(sections, {item.span_id for item in spans}):
                return sections
        except (FileNotFoundError, TypeError, ValueError):
            pass
        return self._sections(blocks, spans)

    def _read_decisions_file(self, run_id: str) -> list[Decision]:
        path = self.store.run_path(run_id) / "review/decisions.yaml"
        return self._read_decision_bundle(path).decisions if path.is_file() else []

    @staticmethod
    def _read_decision_bundle(path: Path) -> DecisionBundle:
        yaml = YAML(typ="safe")
        data = yaml.load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, Mapping):
            raise ValueError("decisions.yaml must contain a mapping")
        values = data.get("decisions") or []
        if not isinstance(values, list):
            raise ValueError("decisions.yaml decisions must be a list")
        waivers_raw = data.get("waivers") or []
        if not isinstance(waivers_raw, list):
            raise ValueError("decisions.yaml waivers must be a list")
        approve = data.get("approve_rewrite", True)
        return DecisionBundle(
            decisions=[Decision.model_validate(item) for item in values],
            steering=str(data.get("steering") or ""),
            waivers=[Waiver.model_validate(item) for item in waivers_raw],
            approve_rewrite=bool(approve),
        )

    def _update(self, record: RunRecord, **changes: Any) -> RunRecord:
        updated = record.model_copy(update={**changes, "updated_at": _now()})
        self.store.save_run(updated)
        return updated

    def _configuration_digest(self) -> str:
        payload = {
            "document_type": self.document_type,
            "execution_mode": self.execution_mode,
            "structure_mode": self.structure_mode,
            "structure_thresholds": self.structure_thresholds.model_dump(mode="json"),
            "review_provider": type(self.review_provider).__name__
            if self.review_provider
            else None,
            "rewrite_provider": type(self.rewrite_provider).__name__
            if self.rewrite_provider
            else None,
            "audit_provider": type(self.audit_provider).__name__ if self.audit_provider else None,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _sections(blocks: tuple[Any, ...], spans: list[SourceSpan]) -> list[Section]:
        headings = [item for item in blocks if item.block_type == "heading"]
        if not headings:
            return [
                Section(
                    section_id="section-document",
                    title="Document",
                    level=1,
                    span_ids=[item.span_id for item in spans],
                )
            ]
        sections: list[Section] = []
        for index, heading in enumerate(headings):
            next_start = headings[index + 1].ordinal if index + 1 < len(headings) else 10**9
            members = [
                item.span_id for item in blocks if heading.ordinal <= item.ordinal < next_start
            ]
            title = str(heading.attributes.get("title") or heading.text.lstrip("#").strip())
            sections.append(
                Section(
                    section_id=f"section-{index + 1:03d}",
                    title=title or f"Section {index + 1}",
                    level=heading.level or 1,
                    span_ids=members,
                )
            )
        return sections

    @staticmethod
    def _valid_recovered_sections(sections: list[Section], expected_span_ids: set[str]) -> bool:
        if not sections or len({item.section_id for item in sections}) != len(sections):
            return False
        covered: set[str] = set()
        section_ids = {item.section_id for item in sections}
        for section in sections:
            if any(span_id not in expected_span_ids for span_id in section.span_ids):
                return False
            if section.parent_id is not None and section.parent_id not in section_ids:
                return False
            covered.update(section.span_ids)
        return covered == expected_span_ids

    @staticmethod
    def _normalized_markdown(blocks: tuple[Any, ...]) -> str:
        return "\n\n".join(block.text.strip() for block in blocks if block.text.strip()) + "\n"

    @staticmethod
    def _questions_yaml(review: ReviewReport) -> str:
        lines = [
            "# Edit answers and set approve_rewrite: true, then run `docenhance continue <run-id>`.",
            "approve_rewrite: true",
            'steering: ""',
            "waivers: []",
            "decisions:",
        ]
        if not review.questions:
            lines.append("  []")
        for question in review.questions:
            lines.extend(
                [
                    f"  - question_id: {question.question_id}",
                    '    answer: ""',
                    "    disposition: accept",
                ]
            )
        return "\n".join(lines) + "\n"

    def _source_digest(self, record: RunRecord) -> str:
        original = next(
            (item for key, item in record.artifacts.items() if key == "source.original"), None
        )
        if original is None:
            return ""
        return original.sha256


__all__ = ["CoreRunner"]
