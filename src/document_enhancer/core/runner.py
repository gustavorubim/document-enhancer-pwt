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
from collections.abc import Mapping, Sequence
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
    figure_appendix_complete,
    figure_asset_digests_match,
    figure_references_valid,
    final_docx_figures_embedded,
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
from .figures import (
    compose_figure_appendix,
    materialize_final_figures,
    persist_source_figures,
)
from .html_report import render_html_report
from .integrity import (
    ApprovalRequiredError,
    ApprovalTypeError,
    build_seal_manifest,
    capture_resume_identity,
    require_explicit_approval,
    validate_recipe_configuration_digests,
)
from .layout import (
    AUDIT,
    AUDIT_MARKDOWN,
    CHANGES_MARKDOWN,
    DECISIONS_JSON,
    DECISIONS_YAML,
    DRAFT_AUDIT,
    DRAFT_DOCUMENT,
    DRAFT_DOCUMENT_DOCX,
    DRAFT_TRANSFORMATION,
    DRAFT_VISUAL_EXTRACTIONS,
    FINAL_DOCX,
    FINAL_FLOW,
    FINAL_MARKDOWN,
    FLOW_MARKDOWN,
    GRAPH_JSONL,
    HTML_REPORT,
    INFERRED_FLOW,
    MACRO_MARKDOWN,
    ONTOLOGY,
    ORIGINAL_DOCUMENT_PREFIX,
    PROPOSED_FLOW,
    QUESTIONS_MARKDOWN,
    RECIPE,
    REVIEW,
    REVIEW_INDEX_MARKDOWN,
    REWRITE_PLAN,
    SEAL,
    SECTIONS_MARKDOWN,
    SEMANTIC,
    SEMANTIC_DIFF,
    SOURCE_MARKDOWN,
    SOURCE_METADATA,
    SOURCE_TO_TARGET_CSV,
    STRUCTURE_QUALITY,
    STRUCTURE_ROUTING,
)
from .models import (
    AuditReport,
    Decision,
    DecisionBundle,
    Question,
    ReviewReport,
    RunRecord,
    Section,
    SectionAssessment,
    SourceDocument,
    SourceSpan,
    Waiver,
)
from .providers import (
    AuditProvider,
    GeminiTransformationProvider,
    ReviewProvider,
    RewriteProvider,
    StructureProvider,
    TransformationProvider,
)
from .recipes import Recipe, load_recipe
from .review import (
    bounded_batches,
    build_review,
    merge_provider_review,
    render_flow_markdown,
    render_macro_markdown,
    render_questions_markdown,
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
from .transformation import TransformationBundle
from .transformation_provider_models import (
    DraftFidelityAudit,
    DraftGenerationResult,
    SectionAnalysis,
    TransformationMapping,
)
from .visuals import VisualExtraction as RichVisualExtraction
from .visuals import VisualFigureInput, VisualInterpreter

_PLACEHOLDER_RE = re.compile(r"\b(?:TBD|TODO|TBC)\b|\[\s*\?\s*\]|\?{3,}", re.IGNORECASE)
_DRAFT_STAGE1_ARTIFACT_KEYS = (
    "source.original",
    "source.metadata",
    "source.normalized",
    "review.report",
    "draft.transformation",
    "draft.document",
    "draft.document_docx",
    "draft.audit",
    "draft.visual_extractions",
)
_DRAFT_PROMOTION_ARTIFACT_KEYS = (*_DRAFT_STAGE1_ARTIFACT_KEYS, "review.decisions")


def _stable_slug(value: object, *, fallback: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return text or fallback


def _token_set(value: object) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", str(value).casefold()) if len(token) > 2}


def _object_mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): child for key, child in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return {str(key): child for key, child in dumped.items()}
    return {}


def _string_list(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item) for item in value]
    return []


class _OfflineTransformationGateway:
    """Structured, deterministic gateway used by the offline transformation adapter."""

    def __init__(self, owner: _OfflineTransformationProvider) -> None:
        self.owner = owner

    def structured(self, *, schema: Any, **_: object) -> Any:
        return schema.model_validate(self.owner._response(schema.__name__))


class _OfflineTransformationProvider:
    """Use the integrated transformation contracts without credentials or network calls.

    The adapter delegates preflight, promotion, coverage, draft freezing, and fidelity checks to
    ``GeminiTransformationProvider``.  Only the structured response is deterministic and local.
    """

    def __init__(self, *, document_type: str) -> None:
        self.document_type = document_type
        self._source_text = ""
        self._source_spans: list[dict[str, object]] = []
        self._template_text = ""
        self._visual_values: list[dict[str, object]] = []
        self._recipe: Recipe | None = None
        self._mapping: TransformationMapping | None = None
        self._gateway = _OfflineTransformationGateway(self)
        self._provider = GeminiTransformationProvider(
            cast(Any, self._gateway),
            allow_hierarchical=False,
        )

    def map_document(
        self,
        *,
        source_text: str,
        source_digest: str,
        recipe: Recipe | None = None,
        template_text: str | None = None,
        source_spans: Sequence[object] = (),
        source_evidence: Sequence[object] | None = None,
        visual_extractions: Sequence[object] = (),
        visual_evidence: Sequence[object] | None = None,
    ) -> TransformationMapping:
        selected_spans = source_evidence if source_evidence is not None else source_spans
        selected_visuals = visual_evidence if visual_evidence is not None else visual_extractions
        self._source_text = source_text
        self._source_spans = [_object_mapping(item) for item in selected_spans]
        self._template_text = template_text or ""
        self._recipe = recipe
        self._visual_values = [_object_mapping(item) for item in selected_visuals]
        mapping_result = self._provider.map_document(
            source_text=source_text,
            source_digest=source_digest,
            recipe=recipe,
            template_text=template_text,
            source_spans=source_spans,
            source_evidence=source_evidence,
            visual_extractions=visual_extractions,
            visual_evidence=visual_evidence,
        )
        self._mapping = mapping_result.model_copy(
            update={"manifest": mapping_result.manifest.model_copy(update={"status": "fallback"})}
        )
        return self._mapping

    def generate_draft(
        self,
        *,
        source_text: str,
        mapping: TransformationMapping | TransformationBundle,
        template_text: str = "",
        visual_extractions: Sequence[object] = (),
        visual_evidence: Sequence[object] | None = None,
    ) -> DraftGenerationResult:
        self._mapping = mapping if isinstance(mapping, TransformationMapping) else self._mapping
        self._source_text = source_text
        self._template_text = template_text
        draft_result = self._provider.generate_draft(
            source_text=source_text,
            mapping=mapping,
            template_text=template_text,
            visual_extractions=visual_extractions,
            visual_evidence=visual_evidence,
        )
        return draft_result.model_copy(
            update={"manifest": draft_result.manifest.model_copy(update={"status": "fallback"})}
        )

    def audit_draft(
        self,
        *,
        source_text: str,
        mapping: TransformationMapping | TransformationBundle,
        draft: DraftGenerationResult | TransformationBundle,
        template_text: str = "",
        visual_extractions: Sequence[object] = (),
        visual_evidence: Sequence[object] | None = None,
    ) -> DraftFidelityAudit:
        self._source_text = source_text
        self._template_text = template_text
        audit_result = self._provider.audit_draft(
            source_text=source_text,
            mapping=mapping,
            draft=draft,
            template_text=template_text,
            visual_extractions=visual_extractions,
            visual_evidence=visual_evidence,
        )
        return audit_result.model_copy(
            update={"manifest": audit_result.manifest.model_copy(update={"status": "fallback"})}
        )

    def _section_specs(self) -> list[dict[str, object]]:
        if self._recipe is not None and self._recipe.required_sections:
            result: list[dict[str, object]] = []
            for index, item in enumerate(self._recipe.required_sections, 1):
                section_id = str(item.get("id") or item.get("section_id") or f"section-{index:03d}")
                heading = str(item.get("heading") or item.get("title") or section_id)
                classification = self._recipe.classify(item)
                result.append(
                    {
                        "id": section_id,
                        "heading": heading,
                        "required": classification == "required"
                        or bool(item.get("required", False)),
                        "order": int(item.get("order", index - 1)),
                        "level": int(item.get("level", 2)),
                        "classification": classification,
                    }
                )
            return result
        section_ids: list[str] = []
        for item in self._source_spans:
            value = str(item.get("section_id") or "section-document")
            if value not in section_ids:
                section_ids.append(value)
        if not section_ids:
            section_ids = ["section-document"]
        return [
            {
                "id": section_id,
                "heading": str(
                    next(
                        (
                            item.get("section_title")
                            for item in self._source_spans
                            if str(item.get("section_id") or "section-document") == section_id
                        ),
                        section_id.replace("-", " ").title(),
                    )
                ),
                "required": True,
                "order": index,
                "level": 2,
                "classification": "required",
            }
            for index, section_id in enumerate(section_ids)
        ]

    def _assigned_spans(self, specs: list[dict[str, object]]) -> dict[str, list[str]]:
        assigned = {str(item["id"]): [] for item in specs}
        if not specs:
            return assigned
        for span in self._source_spans:
            source_section = str(span.get("section_id") or "")
            source_title = str(span.get("section_title") or source_section)
            source_tokens = _token_set(f"{source_section} {source_title}")
            best_id = str(specs[0]["id"])
            best_score = -1
            for spec in specs:
                candidate_tokens = _token_set(f"{spec['id']} {spec['heading']}")
                score = len(source_tokens & candidate_tokens)
                if score > best_score:
                    best_id = str(spec["id"])
                    best_score = score
            assigned[best_id].append(str(span["span_id"]))
        return assigned

    def _response(self, schema_name: str) -> dict[str, object]:
        if schema_name == "_ProviderMappingResponse":
            return self._mapping_response()
        if schema_name == "_ProviderDraftResponse":
            return self._draft_response()
        if schema_name == "_ProviderFidelityResponse":
            return {
                "status": "pass",
                "checks": [{"name": "offline_deterministic_audit", "passed": True, "detail": ""}],
                "summary": "Deterministic offline draft fidelity audit completed.",
            }
        raise ValueError(f"unsupported offline transformation schema: {schema_name}")

    def _mapping_response(self) -> dict[str, object]:
        specs = self._section_specs()
        assigned = self._assigned_spans(specs)
        figure_values = self._current_visual_values()
        gaps: list[dict[str, object]] = []
        questions: list[dict[str, object]] = []
        placements: list[dict[str, object]] = []
        analyses: list[dict[str, object]] = []
        for spec in specs:
            section_id = str(spec["id"])
            span_ids = assigned[section_id]
            source_text = "\n".join(
                str(item.get("text") or "")
                for item in self._source_spans
                if str(item.get("span_id")) in span_ids
            )
            if not span_ids:
                status = "missing" if bool(spec["required"]) else "not_applicable"
            elif "CONFLICT" in source_text.upper():
                status = "conflicting"
            elif _PLACEHOLDER_RE.search(source_text):
                status = "partial"
            else:
                status = "populated"
            gap_ids: list[str] = []
            if status in {"missing", "partial", "conflicting"}:
                gap_id = f"GAP-{len(gaps) + 1:03d}"
                question_id = (
                    "question-placeholder-001"
                    if status == "partial" and _PLACEHOLDER_RE.search(source_text)
                    else f"question-map-{len(gaps) + 1:03d}"
                )
                gap_ids.append(gap_id)
                kind = {
                    "missing": "missing",
                    "partial": "ambiguous",
                    "conflicting": "conflicting",
                }[status]
                gaps.append(
                    {
                        "gap_id": gap_id,
                        "template_section_id": section_id,
                        "kind": kind,
                        "description": (
                            f"The selected template section '{spec['heading']}' requires human review "
                            "before promotion."
                        ),
                        "evidence_span_ids": span_ids,
                        "blocking": bool(spec["required"]),
                        "question_id": question_id,
                    }
                )
                questions.append(
                    {
                        "question_id": question_id,
                        "prompt": (
                            f"What should replace the unresolved marker in '{spec['heading']}'?"
                            if question_id == "question-placeholder-001"
                            else f"How should the '{spec['heading']}' section be resolved?"
                        ),
                        "reason": (
                            "The source contains an unresolved placeholder."
                            if question_id == "question-placeholder-001"
                            else "The mapping found a missing, ambiguous, or conflicting requirement."
                        ),
                        "context": "Review the linked source evidence and provide only an accountable answer.",
                        "evidence_span_ids": span_ids,
                        "blocking": bool(spec["required"]),
                        "section_id": section_id,
                        "suggestion": (
                            None
                            if question_id == "question-placeholder-001"
                            else (
                                "Compare the source evidence with the selected recipe requirement and "
                                "supply only a source-backed answer."
                            )
                        ),
                        "suggestion_basis": (
                            "none"
                            if question_id == "question-placeholder-001"
                            else "recipe_guidance"
                        ),
                    }
                )
            section_figures = [
                str(item.get("figure_id"))
                for item in figure_values
                if set(_string_list(item.get("source_span_ids"))) & set(span_ids)
            ]
            placements.append(
                {
                    "template_section_id": section_id,
                    "heading": str(spec["heading"]),
                    "status": status,
                    "source_span_ids": span_ids,
                    "figure_ids": section_figures,
                    "gap_ids": gap_ids,
                    "required": bool(spec["required"]),
                    "order": int(cast(int, spec["order"])),
                    "level": int(cast(int, spec["level"])),
                    "rationale": "All source spans are retained in the selected template section set.",
                }
            )
            analyses.append(
                {
                    "section_id": section_id,
                    "title": str(spec["heading"]),
                    "requirement_id": section_id,
                    "status": "correct"
                    if status == "populated"
                    else ("missing" if status == "missing" else "improve"),
                    "evidence_span_ids": span_ids,
                    "what_is_correct": "Source evidence is mapped to this template section."
                    if span_ids
                    else "",
                    "what_is_missing": "Human resolution is required before promotion."
                    if status in {"missing", "partial", "conflicting"}
                    else "",
                    "what_to_improve": "Review the mapped wording and linked evidence."
                    if status == "populated"
                    else "",
                }
            )
        source_dispositions = [
            {
                "source_span_id": str(item["span_id"]),
                "action": "placed",
                "destination_section_ids": [
                    section_id
                    for section_id, span_ids in assigned.items()
                    if str(item["span_id"]) in span_ids
                ][:1],
                "rationale": "Source span retained in the selected template section set.",
            }
            for item in self._source_spans
        ]
        node_values = [
            {
                "node_id": f"node-{_stable_slug(section_id, fallback=f'section-{index}')}",
                "label": str(spec["heading"]),
                "section_id": section_id,
                "node_type": "section",
            }
            for index, (section_id, spec) in enumerate(
                ((str(item["template_section_id"]), item) for item in placements), 1
            )
        ]
        edge_values = [
            {
                "source": node_values[index - 1]["node_id"],
                "target": node_values[index]["node_id"],
                "relation": "sequence",
                "evidence_span_ids": [],
            }
            for index in range(1, len(node_values))
        ]
        mermaid_lines = ["flowchart TD"]
        for node in node_values:
            mermaid_lines.append(f"  {node['node_id']}[{node['label']}]")
        for edge in edge_values:
            mermaid_lines.append(f"  {edge['source']} --> {edge['target']}")
        return {
            "macro": {
                "summary": "Deterministic offline mapping retained all source spans and evaluated the selected template.",
                "question_ids": [str(item["question_id"]) for item in questions],
            },
            "sections": analyses,
            "process": {
                "applicable": self.document_type in {"process", "desktop_procedure"},
                "summary": "Inferred section sequence from the parsed source.",
                "inferred_mermaid": "\n".join(mermaid_lines) + "\n",
                "proposed_mermaid": "\n".join(mermaid_lines) + "\n",
                "flow_nodes": node_values,
                "flow_edges": edge_values,
                "proposed_flow_nodes": node_values,
                "proposed_flow_edges": edge_values,
            },
            "questions": questions,
            "source_dispositions": source_dispositions,
            "gaps": gaps,
            "template_placement": placements,
            "coverage": {
                "valid": True,
                "source_span_coverage": 1.0,
                "required_section_status_coverage": 1.0,
            },
        }

    def _draft_response(self) -> dict[str, object]:
        if self._mapping is None:
            raise ValueError("offline draft generation requires a mapping")
        text_by_id = {
            str(item["span_id"]): str(item.get("text") or "") for item in self._source_spans
        }
        return {
            "summary": "Deterministic offline candidate draft generated from the frozen mapping.",
            "sections": [
                {
                    "template_section_id": section.template_section_id,
                    "rewritten_markdown": "\n\n".join(
                        text_by_id[span_id]
                        for span_id in section.source_span_ids
                        if span_id in text_by_id
                    ).strip(),
                    "status": section.status,
                    "source_span_ids": list(section.source_span_ids),
                    "figure_ids": list(section.figure_ids),
                    "gap_ids": list(section.gap_ids),
                }
                for section in self._mapping.bundle.template_sections
            ],
        }

    def _current_visual_values(self) -> list[dict[str, object]]:
        return [dict(item) for item in getattr(self, "_visual_values", [])]


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
        transformation_provider: TransformationProvider | None = None,
        visual_provider: Any | None = None,
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
        self._transformation_provider_configured = transformation_provider is not None
        self.transformation_provider = transformation_provider or _OfflineTransformationProvider(
            document_type=document_type
        )
        self.visual_provider = visual_provider
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
            # Stage 1 is always a human gate, including a complete document with no
            # generated questions.  ``stop_at`` remains accepted for CLI compatibility,
            # but it cannot bypass explicit approval.
            _ = stop_at
            questions = self._load_review(record).questions
            record = self._update(
                record,
                status="waiting",
                phase="human_review",
                unresolved_question_ids=[item.question_id for item in questions if item.blocking],
            )
            return self._refresh_html_report(record)
        except Exception as exc:
            self._update(record, status="failed", error=f"{type(exc).__name__}: {exc}")
            raise RuntimeError(f"core run {record.run_id} failed: {exc}") from exc

    def resume(self, run_id: str, *, decisions_path: Path | None = None) -> RunRecord:
        """Continue a waiting run after the reviewer edits ``decisions.yaml``."""

        record = self.store.load_run(run_id)
        if record.status == "failed" and record.phase == "verify":
            if "draft.document" in record.artifacts:
                return self._recover_draft(record)
            return self._finish(
                self._update(
                    record,
                    status="running",
                    phase="rewrite",
                    error=None,
                    unresolved_question_ids=[],
                )
            )
        if record.status == "running" and record.phase == "analyze":
            source_path = self.store.run_path(run_id) / record.artifacts["source.original"].path
            if not source_path.is_file():
                raise FileNotFoundError(f"source artifact is missing for run {run_id}")
            raw = self.ingestor.parse(source_path)
            record = self._analyze(record, raw)
            questions = self._load_review(record).questions
            return self._update(
                record,
                status="waiting",
                phase="human_review",
                unresolved_question_ids=[item.question_id for item in questions if item.blocking],
            )
        if record.status == "running" and record.phase == "rewrite":
            if "draft.document" in record.artifacts:
                return self._recover_draft(record)
            return self._finish(record)
        if record.status != "waiting" or record.phase != "human_review":
            raise ValueError(f"run {run_id} is not waiting for human review")
        path = decisions_path or (self.store.run_path(run_id) / DECISIONS_YAML)
        if not path.is_file():
            return record
        bundle = self._read_decision_bundle(path)
        initial_identity = capture_resume_identity(record)
        validate_recipe_configuration_digests(
            record.recipe_digest,
            self.recipe.recipe_digest if self.recipe else "0" * 64,
            record.configuration_digest,
            self._configuration_digest(),
            expected_recipe_id=record.recipe,
            actual_recipe_id=self.recipe.recipe_id if self.recipe else record.recipe,
        )
        review = self._load_review(record)
        decisions = self._canonical_decisions(review, bundle.decisions)
        bundle = bundle.model_copy(update={"decisions": decisions})
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
                or (
                    answers[question.question_id].disposition == "accept_suggestion"
                    and not question.suggestion
                )
            )
        ]
        if not bundle.approve_rewrite:
            unresolved = [*unresolved, "approve_rewrite"]
        decisions_artifact = self.store.write_json(
            run_id,
            DECISIONS_JSON,
            bundle.model_dump(mode="json"),
        )
        record = register_artifact(record, "review.decisions", decisions_artifact)
        record = self.store.save_run_if_current(
            record.model_copy(update={"updated_at": _now()}),
            initial_identity,
        )
        expected_identity = capture_resume_identity(record)
        self.store.verify_registered_artifacts(
            run_id,
            record.artifacts,
            required_keys=(
                "source.original",
                "source.metadata",
                "source.normalized",
                "review.report",
                "draft.transformation",
                "draft.document",
                "draft.document_docx",
                "draft.audit",
                "draft.visual_extractions",
            ),
        )
        if unresolved:
            updated = record.model_copy(
                update={"unresolved_question_ids": unresolved, "updated_at": _now()}
            )
            return self.store.save_run_if_current(updated, expected_identity)
        require_explicit_approval(
            {
                "approve_rewrite": bundle.approve_rewrite,
            }
        )
        with self.store.locked_promotion(expected_identity) as current:
            validate_recipe_configuration_digests(
                current.recipe_digest,
                self.recipe.recipe_digest if self.recipe else "0" * 64,
                current.configuration_digest,
                self._configuration_digest(),
                expected_recipe_id=current.recipe,
                actual_recipe_id=self.recipe.recipe_id if self.recipe else current.recipe,
            )
            return self._finish(
                current.model_copy(update={"status": "running", "phase": "rewrite"}),
                decision_bundle=bundle,
                expected_identity=expected_identity,
            )

    def _recover_draft(self, record: RunRecord) -> RunRecord:
        """Recover draft-first promotion only from a guarded, verified state."""

        expected_identity = self._prepare_draft_recovery(record)
        with self.store.locked_promotion(expected_identity) as current:
            # Recheck the mutable environment and every registered input before the
            # promotion block; locked_promotion guards the state identity itself.
            self._validate_draft_recovery(current)
            decision_bundle = self._load_decision_bundle(current)
            return self._finish(
                current.model_copy(
                    update={
                        "status": "running",
                        "phase": "rewrite",
                        "error": None,
                        "unresolved_question_ids": [],
                    }
                ),
                decision_bundle=decision_bundle,
                expected_identity=expected_identity,
            )

    def _prepare_draft_recovery(self, record: RunRecord) -> Any:
        self._validate_draft_recovery(record)
        return capture_resume_identity(record)

    def _validate_draft_recovery(self, record: RunRecord) -> None:
        validate_recipe_configuration_digests(
            record.recipe_digest,
            self.recipe.recipe_digest if self.recipe else "0" * 64,
            record.configuration_digest,
            self._configuration_digest(),
            expected_recipe_id=record.recipe,
            actual_recipe_id=self.recipe.recipe_id if self.recipe else record.recipe,
        )
        self.store.verify_registered_artifacts(
            record.run_id,
            record.artifacts,
            required_keys=_DRAFT_PROMOTION_ARTIFACT_KEYS,
        )

    def _extract(self, record: RunRecord, raw: Any, raw_bytes: bytes, source: Path) -> RunRecord:
        if self.recipe:
            record = register_artifact(
                record,
                "recipe.compiled",
                self.store.write_json(
                    record.run_id,
                    RECIPE,
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
        record, figures = persist_source_figures(
            store=self.store,
            record=record,
            assets=normalized.assets,
            blocks=raw.blocks,
            sections=sections,
        )
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
            figures=figures,
        )
        suffix = source.suffix.lower() or ".bin"
        record = register_artifact(
            record,
            "source.original",
            self.store.write_bytes(
                record.run_id,
                f"{ORIGINAL_DOCUMENT_PREFIX}{suffix}",
                raw_bytes,
                media_type=raw.media_type,
            ),
        )
        record = register_artifact(
            record,
            "source.metadata",
            self.store.write_json(record.run_id, SOURCE_METADATA, metadata.model_dump(mode="json")),
        )
        record = register_artifact(
            record,
            "source.structure_quality",
            self.store.write_json(
                record.run_id,
                STRUCTURE_QUALITY,
                normalized.quality.model_dump(mode="json"),
            ),
        )
        record = register_artifact(
            record,
            "source.structure_routing",
            self.store.write_json(
                record.run_id,
                STRUCTURE_ROUTING,
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
                SOURCE_MARKDOWN,
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
        source_section_titles = {item.section_id: item.title for item in sections}
        source_evidence = [
            {
                "span_id": block.span_id,
                "text": block.text,
                "section_id": next(
                    (
                        section.section_id
                        for section in sections
                        if block.span_id in section.span_ids
                    ),
                    "section-document",
                ),
                "section_title": next(
                    (
                        source_section_titles[section.section_id]
                        for section in sections
                        if block.span_id in section.span_ids
                    ),
                    "Document",
                ),
                "block_type": block.block_type,
                "attributes": dict(block.attributes),
            }
            for block in raw.blocks
        ]
        try:
            source_document = self._load_source(record)
        except FileNotFoundError:
            source_document = SourceDocument(
                source_name=record.source_name,
                source_digest=record.source_digest,
                media_type=getattr(raw, "media_type", "text/plain"),
                size_bytes=len(source_text.encode("utf-8")),
                parser="rehydrated",
                structure_score=1.0,
                structure_mode="parser",
                sections=sections,
            )
            record = register_artifact(
                record,
                "source.metadata",
                self.store.write_json(
                    record.run_id,
                    SOURCE_METADATA,
                    source_document.model_dump(mode="json"),
                ),
            )
        visuals = self._interpret_visuals(record, raw, source_document.figures, source_text)
        review = build_review(
            blocks=raw.blocks,
            source_spans=source_spans,
            sections=sections,
            recipe=self.recipe,
            figures=source_document.figures,
        )
        provider_manifests: list[Any] = []
        if self.review_provider and not self._transformation_provider_configured:
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
        mapping = self.transformation_provider.map_document(
            source_text=source_text,
            source_digest=record.source_digest,
            recipe=self.recipe,
            template_text=self.recipe.template_text if self.recipe else "",
            source_spans=source_evidence,
            visual_extractions=visuals,
        )
        mapping_review = ReviewReport(
            summary=mapping.macro.summary or "Whole-document transformation mapping completed.",
            recipe_id=mapping.recipe_id,
            sections=sections,
            section_assessments=[self._section_assessment(item) for item in mapping.sections],
            findings=mapping.macro.findings,
            questions=[
                item
                for item in mapping.contextual_questions
                if item.question_id not in {question.question_id for question in review.questions}
            ],
            process_applicable=mapping.process.applicable,
            flow_nodes=mapping.process.flow_nodes,
            flow_edges=mapping.process.flow_edges,
            proposed_flow_nodes=mapping.process.proposed_flow_nodes,
            proposed_flow_edges=mapping.process.proposed_flow_edges,
            inferred_mermaid=mapping.process.inferred_mermaid,
            proposed_mermaid=mapping.process.proposed_mermaid,
            mermaid=mapping.process.inferred_mermaid,
        )
        review = merge_provider_review(
            review,
            mapping_review,
            allowed_span_ids={item.span_id for item in source_spans},
            allowed_figure_ids={item.figure_id for item in source_document.figures},
        )
        review = self._merge_visual_questions(review, visuals, source_document.figures)
        draft = self.transformation_provider.generate_draft(
            source_text=source_text,
            mapping=mapping,
            template_text=self.recipe.template_text if self.recipe else "",
            visual_extractions=visuals,
        )
        fidelity = self.transformation_provider.audit_draft(
            source_text=source_text,
            mapping=mapping,
            draft=draft,
            template_text=self.recipe.template_text if self.recipe else "",
            visual_extractions=visuals,
        )
        draft_markdown = self._render_candidate_draft(
            draft,
            visuals,
            document_title=sections[0].title if sections else None,
        )
        record = register_artifact(
            record,
            "draft.transformation",
            self.store.write_json(
                record.run_id, DRAFT_TRANSFORMATION, mapping.model_dump(mode="json")
            ),
        )
        record = register_artifact(
            record,
            "draft.document",
            self.store.write_text(
                record.run_id,
                DRAFT_DOCUMENT,
                draft_markdown,
                media_type="text/markdown; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "draft.document_docx",
            self.store.write_bytes(
                record.run_id,
                DRAFT_DOCUMENT_DOCX,
                render_docx(
                    draft_markdown, asset_root=self.store.run_path(record.run_id) / "assets/source"
                ),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )
        record = register_artifact(
            record,
            "draft.audit",
            self.store.write_json(record.run_id, DRAFT_AUDIT, fidelity.model_dump(mode="json")),
        )
        visual_payload = {
            "schema_version": "core.visual-extractions.v1",
            "source_digest": record.source_digest,
            "visual_extractions": [item.model_dump(mode="json") for item in visuals],
            "figure_digests": {item.figure_id: item.sha256 for item in source_document.figures},
        }
        record = register_artifact(
            record,
            "draft.visual_extractions",
            self.store.write_json(record.run_id, DRAFT_VISUAL_EXTRACTIONS, visual_payload),
        )
        manifests = [mapping.manifest, draft.manifest, fidelity.manifest]
        record = register_artifact(
            record,
            "debug.transformation_call",
            self.store.write_text(
                record.run_id,
                "debug/transformation.jsonl",
                "".join(
                    json.dumps(item.model_dump(mode="json"), sort_keys=True) + "\n"
                    for item in manifests
                ),
                media_type="application/jsonl",
            ),
        )
        questions = review.questions
        record = register_artifact(
            record,
            "review.report",
            self.store.write_json(record.run_id, REVIEW, review.model_dump(mode="json")),
        )
        record = register_artifact(
            record,
            "review.report_markdown",
            self.store.write_text(
                record.run_id,
                REVIEW_INDEX_MARKDOWN,
                render_review_index_markdown(review),
                media_type="text/markdown; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "review.macro_markdown",
            self.store.write_text(
                record.run_id,
                MACRO_MARKDOWN,
                render_macro_markdown(review),
                media_type="text/markdown; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "review.sections_markdown",
            self.store.write_text(
                record.run_id,
                SECTIONS_MARKDOWN,
                render_sections_markdown(review),
                media_type="text/markdown; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "review.flow_markdown",
            self.store.write_text(
                record.run_id,
                FLOW_MARKDOWN,
                render_flow_markdown(review),
                media_type="text/markdown; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "review.questions_markdown",
            self.store.write_text(
                record.run_id,
                QUESTIONS_MARKDOWN,
                render_questions_markdown(review),
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
        inferred_flow = self.store.write_text(
            record.run_id,
            INFERRED_FLOW,
            review.inferred_mermaid,
            media_type="text/vnd.mermaid; charset=utf-8",
        )
        record = register_artifact(record, "review.flow_inferred", inferred_flow)
        record = register_artifact(
            record,
            "review.flow_proposed",
            self.store.write_text(
                record.run_id,
                PROPOSED_FLOW,
                review.proposed_mermaid,
                media_type="text/vnd.mermaid; charset=utf-8",
            ),
        )
        self.store.write_text(
            record.run_id,
            DECISIONS_YAML,
            self._questions_yaml(review),
            media_type="application/yaml; charset=utf-8",
        )
        return self._update(
            record,
            phase="human_review",
            unresolved_question_ids=[q.question_id for q in questions if q.blocking],
        )

    @staticmethod
    def _section_assessment(item: SectionAnalysis) -> SectionAssessment:
        return SectionAssessment(
            section_id=item.section_id,
            title=item.title,
            requirement_id=item.requirement_id,
            status=item.status,
            evidence_span_ids=list(item.evidence_span_ids),
            what_is_correct=item.what_is_correct,
            what_is_missing=item.what_is_missing,
            what_to_improve=item.what_to_improve,
        )

    def _interpret_visuals(
        self,
        record: RunRecord,
        raw: Any,
        figures: list[Any],
        source_text: str,
    ) -> list[RichVisualExtraction]:
        inputs: list[VisualFigureInput] = []
        for figure in figures:
            key = f"source.figure.{figure.figure_id}"
            artifact = record.artifacts.get(key)
            if artifact is None:
                continue
            payload = self.store.read_verified_bytes(record.run_id, artifact, key=key)
            inputs.append(VisualFigureInput.from_source_figure(figure, payload))
        native_tables = [block for block in raw.blocks if block.block_type == "table"]
        return VisualInterpreter(
            self.visual_provider,
            known_figure_ids=[item.figure_id for item in figures],
        ).interpret(
            inputs,
            native_tables=native_tables,
            context=source_text,
        )

    @staticmethod
    def _merge_visual_questions(
        review: ReviewReport,
        visuals: list[RichVisualExtraction],
        figures: list[Any],
    ) -> ReviewReport:
        figure_by_id = {item.figure_id: item for item in figures}
        questions = list(review.questions)
        seen = {item.question_id for item in questions}
        for extraction in visuals:
            if extraction.status not in {"extracted", "best_effort", "requires_review"}:
                continue
            question_id = f"question-visual-{extraction.figure_id}"
            if question_id in seen:
                continue
            occurrence = next(
                iter(figure_by_id[extraction.figure_id].occurrences),
                None,
            )
            questions.append(
                Question(
                    question_id=question_id,
                    prompt=(
                        f"Should the candidate conversion for {extraction.figure_id} be accepted "
                        "into the revised document?"
                    ),
                    reason=(
                        "Visual conversion is a candidate interpretation and must be compared with "
                        "the original source figure before promotion."
                    ),
                    context=(
                        "The original figure remains authoritative. Accept only a conversion that "
                        "matches the source, or reject it and retain the original figure."
                    ),
                    evidence_span_ids=list(extraction.source_span_ids),
                    figure_ids=[extraction.figure_id],
                    blocking=True,
                    section_id=occurrence.section_id if occurrence is not None else None,
                )
            )
            seen.add(question_id)
        return review.model_copy(update={"questions": questions})

    @staticmethod
    def _render_candidate_draft(
        draft: DraftGenerationResult,
        visuals: list[RichVisualExtraction],
        *,
        document_title: str | None = None,
    ) -> str:
        text = draft.document_markdown.rstrip() + "\n"
        if document_title:
            safe_title = re.sub(r"[\r\n]+", " ", document_title).lstrip("# ").strip()
            if safe_title:
                text = re.sub(r"\A# Candidate draft\n", f"# {safe_title}\n", text, count=1)
        for extraction in visuals:
            if extraction.status == "unsupported":
                continue
            figure_id = extraction.figure_id
            content = extraction.structured_content
            conversion = ""
            if extraction.kind == "table" and content.cells:
                headers = content.cells[0]
                rows = content.cells[1:]
                conversion = (
                    "| " + " | ".join(str(item) for item in headers) + " |\n"
                    "| "
                    + " | ".join("---" for _ in headers)
                    + " |\n"
                    + "\n".join("| " + " | ".join(str(item) for item in row) + " |" for row in rows)
                )
            elif content.mermaid:
                conversion = f"```mermaid\n{content.mermaid.rstrip()}\n```"
            elif content.summary:
                conversion = content.summary
            else:
                conversion = "No structured conversion was produced; review the original figure."
            text += (
                f"\n<!-- document-enhancer:visual-candidate={figure_id} -->\n"
                f"> **UNAPPROVED VISUAL CANDIDATE — {figure_id}**\n\n"
                f"{conversion}\n\n"
                f"> Compare this candidate with the authoritative source figure before accepting it.\n"
                f"<!-- document-enhancer:visual-candidate-end={figure_id} -->\n"
            )
        return text

    @staticmethod
    def _revise_exact_draft(
        draft_markdown: str,
        *,
        mapping: TransformationMapping | None,
        visuals: object,
        review: ReviewReport,
        decisions: list[Decision],
        decision_bundle: DecisionBundle,
    ) -> tuple[str, list[str]]:
        if mapping is None:
            raise ValueError("draft-first promotion requires a transformation mapping")
        decision_by_question = {item.question_id: item for item in decisions}
        waived = {item.requirement_id for item in decision_bundle.waivers}
        text = draft_markdown
        changes: list[str] = []
        unresolved_gaps: list[str] = []
        for gap in mapping.bundle.gaps:
            decision = (
                decision_by_question.get(gap.question_id) if gap.question_id is not None else None
            )
            resolved = bool(
                gap.template_section_id in waived
                or (
                    decision is not None
                    and decision.disposition == "accept"
                    and decision.answer.strip()
                )
            )
            if gap.blocking and not resolved:
                unresolved_gaps.append(gap.gap_id)
            if (
                decision is not None
                and decision.disposition == "accept"
                and decision.answer.strip()
            ):
                replacement = decision.answer.strip()
                text = re.sub(
                    rf"(?ms)^> \*\*{re.escape(gap.gap_id)}\*\*.*?(?=\n\n|\Z)",
                    replacement,
                    text,
                    count=1,
                )
                changes.append(f"Applied accepted decision {decision.question_id} to {gap.gap_id}.")
            elif resolved:
                text = re.sub(
                    rf"(?ms)^> \*\*{re.escape(gap.gap_id)}\*\*.*?(?=\n\n|\Z)\n?",
                    "",
                    text,
                    count=1,
                )
                changes.append(f"Resolved {gap.gap_id} by waiver.")
        visual_items = []
        if isinstance(visuals, Mapping):
            candidate_items = visuals.get("visual_extractions")
            if isinstance(candidate_items, list):
                visual_items = candidate_items
        elif isinstance(visuals, list):
            visual_items = visuals
        visual_unreviewed: list[str] = []
        for item in visual_items:
            if not isinstance(item, Mapping):
                continue
            figure_id = str(item.get("figure_id") or "")
            status = str(item.get("status") or "requires_review")
            if status not in {"extracted", "best_effort", "requires_review"}:
                continue
            decision = decision_by_question.get(f"question-visual-{figure_id}")
            accepted = decision is not None and decision.disposition == "accept"
            rejected = decision is not None and decision.disposition == "reject"
            if not accepted and not rejected:
                visual_unreviewed.append(figure_id)
                continue
            marker = re.compile(
                rf"(?ms)^<!-- document-enhancer:visual-candidate={re.escape(figure_id)} -->.*?"
                rf"^<!-- document-enhancer:visual-candidate-end={re.escape(figure_id)} -->\n?"
            )
            if rejected:
                text = marker.sub("", text, count=1)
                changes.append(f"Rejected visual candidate {figure_id}; retained source figure.")
            else:
                candidate = marker.search(text)
                if candidate:
                    body = candidate.group(0)
                    body = re.sub(r"(?m)^<!-- .*? -->\n?", "", body)
                    body = re.sub(r"(?m)^> \*\*UNAPPROVED VISUAL CANDIDATE.*?\n", "", body)
                    body = re.sub(
                        r"(?m)^> Compare this candidate with the authoritative source figure before accepting it\.\n?",
                        "",
                        body,
                    )
                    text = text[: candidate.start()] + body.strip("\n") + text[candidate.end() :]
                changes.append(f"Accepted reviewed visual candidate {figure_id}.")
        text, reviewer_changes = apply_reviewer_decisions(
            text,
            decisions=decisions,
            steering=decision_bundle.steering,
        )
        changes.extend(reviewer_changes)
        text = re.sub(r"(?m)^<!-- document-enhancer:section=.*? -->\n?", "", text)
        text = re.sub(r"(?m)^> \*\*DRAFT STATUS:.*?\n", "", text)
        text = re.sub(r"(?m)^> \*\*UNAPPROVED DRAFT\*\*.*?\n\n?", "", text)
        if not unresolved_gaps and not visual_unreviewed:
            text = re.sub(r"(?ms)\n## Review markers\n.*\Z", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
        if unresolved_gaps:
            changes.append("Blocking transformation gaps remain unresolved.")
        if visual_unreviewed:
            changes.append("Visual candidates remain unreviewed.")
        return text, changes

    def _finish(
        self,
        record: RunRecord,
        *,
        decision_bundle: DecisionBundle | None = None,
        expected_identity: Any | None = None,
    ) -> RunRecord:
        draft_mode = "draft.document" in record.artifacts
        if draft_mode:
            self._validate_draft_recovery(record)
            self.store.verify_registered_artifacts(
                record.run_id,
                record.artifacts,
                required_keys=_DRAFT_PROMOTION_ARTIFACT_KEYS,
            )
            normalized = self.store.read_verified_text(
                record.run_id,
                record.artifacts["source.normalized"],
                key="source.normalized",
            )
            draft_markdown = self.store.read_verified_text(
                record.run_id,
                record.artifacts["draft.document"],
                key="draft.document",
            )
            mapping = TransformationMapping.model_validate(
                self.store.read_verified_json(
                    record.run_id,
                    record.artifacts["draft.transformation"],
                    key="draft.transformation",
                )
            )
            draft_fidelity = DraftFidelityAudit.model_validate(
                self.store.read_verified_json(
                    record.run_id,
                    record.artifacts["draft.audit"],
                    key="draft.audit",
                )
            )
            visual_manifest = self.store.read_verified_json(
                record.run_id,
                record.artifacts["draft.visual_extractions"],
                key="draft.visual_extractions",
            )
        else:
            normalized = self.store.read_text(record.run_id, SOURCE_MARKDOWN)
            draft_markdown = normalized
            mapping = None
            draft_fidelity = None
            visual_manifest = None
        review = self._load_review(record)
        if record.artifacts.get("review.decisions") is not None or decision_bundle is None:
            decision_bundle = self._load_decision_bundle(record)
        canonical_decisions = self._canonical_decisions(review, decision_bundle.decisions)
        decision_bundle = decision_bundle.model_copy(update={"decisions": canonical_decisions})
        decisions = self._effective_decisions(review, canonical_decisions)
        try:
            source_document = self._load_source(record)
            figures = source_document.figures
            source_sections = source_document.sections
        except FileNotFoundError:
            figures = []
            source_sections = review.sections
        if draft_mode:
            require_explicit_approval(decision_bundle)
        plan = compile_rewrite_plan(
            source_digest=record.source_digest,
            review=review,
            decisions=decisions,
            recipe=self.recipe,
            figures=figures,
        )
        record = register_artifact(
            record,
            "rewrite.plan",
            self.store.write_json(
                record.run_id,
                REWRITE_PLAN,
                plan.model_dump(mode="json"),
            ),
        )
        waived = {item.requirement_id for item in decision_bundle.waivers}
        final_text = draft_markdown if draft_mode else normalized
        changes: list[str] = []
        rewrite_manifest: Any | None = None
        if draft_mode:
            final_text, draft_changes = self._revise_exact_draft(
                draft_markdown,
                mapping=mapping,
                visuals=visual_manifest,
                review=review,
                decisions=decisions,
                decision_bundle=decision_bundle,
            )
            changes.extend(draft_changes)
        elif self.rewrite_provider:
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
        record = materialize_final_figures(
            store=self.store,
            record=record,
            figures=figures,
        )
        final_text = compose_figure_appendix(
            final_text,
            figures=figures,
            sections=source_sections,
        )
        if figures:
            changes.append(
                f"Preserved {len(figures)} source screenshot(s) in a referenced appendix."
            )
        record = self._update(record, status="running", phase="rewrite", unresolved_question_ids=[])
        record = register_artifact(
            record,
            "output.final_markdown",
            self.store.write_text(
                record.run_id,
                FINAL_MARKDOWN,
                final_text,
                media_type="text/markdown; charset=utf-8",
            ),
        )
        record = register_artifact(
            record,
            "output.final_docx",
            self.store.write_bytes(
                record.run_id,
                FINAL_DOCX,
                render_docx(
                    final_text,
                    asset_root=self.store.run_path(record.run_id) / "assets/final",
                ),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )
        semantic = semantic_graph(review, final_text, recipe=self.recipe)
        record = register_artifact(
            record,
            "output.semantic",
            self.store.write_json(record.run_id, SEMANTIC, semantic),
        )
        record = register_artifact(
            record,
            "output.ontology",
            self.store.write_json(
                record.run_id,
                ONTOLOGY,
                public_graph(semantic),
            ),
        )
        semantic_before = semantic_graph(
            review,
            draft_markdown if draft_mode else normalized,
            recipe=self.recipe,
        )
        semantic_diff_payload = semantic_diff(semantic_before, semantic)
        record = register_artifact(
            record,
            "audit.semantic_diff",
            self.store.write_json(
                record.run_id,
                SEMANTIC_DIFF,
                semantic_diff_payload,
            ),
        )
        graph_lines = "".join(json_line + "\n" for json_line in graph_json_lines(semantic))
        record = register_artifact(
            record,
            "output.graph",
            self.store.write_text(
                record.run_id, GRAPH_JSONL, graph_lines, media_type="application/jsonl"
            ),
        )
        record = register_artifact(
            record,
            "output.flow",
            self.store.write_text(
                record.run_id,
                FINAL_FLOW,
                review.proposed_mermaid or review.inferred_mermaid,
                media_type="text/vnd.mermaid; charset=utf-8",
            ),
        )
        source_text = normalized
        diff = "\n".join(
            difflib.unified_diff(
                source_text.splitlines(),
                final_text.splitlines(),
                fromfile=SOURCE_MARKDOWN,
                tofile=FINAL_MARKDOWN,
                lineterm="",
            )
        )
        change_items = (
            "\n".join(f"- {item}" for item in changes)
            if changes
            else "- No explicit rewrite changes were recorded."
        )
        change_note = (
            "# Change explanation\n\n"
            "## Summary\n\n"
            f"The rewrite stage recorded **{len(changes)}** explicit change(s). The final document "
            "was produced from the normalized source, the selected recipe, and the accepted "
            "human decisions. This report explains the recorded changes and preserves the exact "
            "textual diff for audit.\n\n"
            "## Recorded rewrite actions\n\n"
            f"{change_items}\n\n"
            "## How to review the result\n\n"
            "Read the final document first for coherence, then use the diff below to inspect "
            "specific additions, removals, and wording changes. A leading `-` is source text that "
            "was removed; a leading `+` is final text that was added. Unchanged context is shown "
            "around each edit so reviewers can evaluate meaning rather than isolated lines.\n\n"
            "## Source-to-final textual diff\n\n"
            "```diff\n"
            f"{diff or 'No textual changes were required.'}\n"
            "```\n\n"
            "## Traceability note\n\n"
            "This explanation is descriptive, not a new source of business truth. The accepted "
            "decision file and source-to-target map remain the authoritative trace for why the "
            "rewrite was allowed.\n"
        )
        record = register_artifact(
            record,
            "audit.changes",
            self.store.write_text(
                record.run_id,
                CHANGES_MARKDOWN,
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
                SOURCE_TO_TARGET_CSV,
                source_target_csv(review, final_text, mapping=mapping),
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
                "source_sections_accounted_for": source_sections_retained(
                    review,
                    final_text,
                    mapping=mapping.bundle if mapping is not None else None,
                ),
                "required_sections_present": required_sections_present(
                    self.recipe, final_text, waived_requirement_ids=waived
                ),
                "section_assessments_present": section_assessments_present(review),
                "dual_flow_artifacts_present": dual_flow_artifacts_present(review),
                "semantic_references_valid": semantic_references_valid(semantic),
                "graph_types_valid": graph_types_valid(semantic, self.recipe),
                "figure_references_valid": figure_references_valid(final_text, figures),
                "figure_appendix_complete": figure_appendix_complete(final_text, figures),
                "figure_asset_digests_match": figure_asset_digests_match(
                    self.store.run_path(record.run_id), figures
                ),
                "final_docx_figures_embedded": final_docx_figures_embedded(
                    self.store.read_verified_bytes(
                        record.run_id,
                        record.artifacts["output.final_docx"],
                        key="output.final_docx",
                    ),
                    figures,
                ),
                "draft_artifacts_verified": not draft_mode
                or all(
                    key in record.artifacts
                    for key in (
                        "draft.transformation",
                        "draft.document",
                        "draft.document_docx",
                        "draft.audit",
                        "draft.visual_extractions",
                    )
                ),
                "transformation_coverage": not draft_mode
                or bool(mapping is not None and mapping.coverage.valid),
                "draft_fidelity_consistent": not draft_mode
                or bool(
                    draft_fidelity is not None
                    and mapping is not None
                    and draft_fidelity.mapping_digest == mapping.mapping_digest
                    and not draft_fidelity.invalid_references
                    and not draft_fidelity.unsupported_additions
                ),
                "blocking_gaps_resolved": not draft_mode
                or bool(
                    mapping is not None
                    and all(
                        gap.gap_id not in final_text for gap in mapping.bundle.gaps if gap.blocking
                    )
                ),
                "visual_conversions_reviewed": not draft_mode
                or bool(
                    visual_manifest is not None
                    and all(
                        f"document-enhancer:visual-candidate={item.get('figure_id')}"
                        not in final_text
                        for item in visual_manifest.get("visual_extractions", [])
                        if isinstance(item, Mapping)
                        and item.get("status") in {"extracted", "best_effort", "requires_review"}
                    )
                ),
                "approval_explicit": not draft_mode or decision_bundle.approve_rewrite is True,
                "recipe_configuration_unchanged": True,
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
            self.store.write_json(record.run_id, AUDIT, audit.model_dump(mode="json")),
        )
        record = register_artifact(
            record,
            "audit.report_markdown",
            self.store.write_text(
                record.run_id,
                AUDIT_MARKDOWN,
                render_audit_markdown(audit),
                media_type="text/markdown; charset=utf-8",
            ),
        )
        record = self._update(
            record,
            status="succeeded" if audit.status == "pass" else "failed",
            phase="verify",
            error=None,
        )
        record = self._refresh_html_report(record, audit=audit)
        if audit.status == "pass":
            approval_digest = record.artifacts["review.decisions"].sha256
            seal_manifest = build_seal_manifest(
                run_id=record.run_id,
                source_digest=record.source_digest,
                recipe_id=record.recipe,
                recipe_digest=record.recipe_digest,
                configuration_digest=record.configuration_digest,
                artifacts=record.artifacts,
                approval_digest=approval_digest,
                artifact_root=self.store.run_path(record.run_id),
            )
            record = register_artifact(
                record,
                "audit.seal",
                self.store.write_json(
                    record.run_id,
                    SEAL,
                    seal_manifest.model_dump(mode="json"),
                ),
            )
            self.store.save_run(record)
        return record

    def _refresh_html_report(
        self, record: RunRecord, *, audit: AuditReport | None = None
    ) -> RunRecord:
        report_paths = (
            SOURCE_MARKDOWN,
            REVIEW_INDEX_MARKDOWN,
            MACRO_MARKDOWN,
            SECTIONS_MARKDOWN,
            FLOW_MARKDOWN,
            QUESTIONS_MARKDOWN,
            FINAL_MARKDOWN,
            CHANGES_MARKDOWN,
            AUDIT_MARKDOWN,
        )
        documents = [
            (
                path,
                self.store.read_verified_text(
                    record.run_id,
                    record.artifacts[
                        next(key for key, ref in record.artifacts.items() if ref.path == path)
                    ],
                    key=next(key for key, ref in record.artifacts.items() if ref.path == path),
                )
                if any(ref.path == path for ref in record.artifacts.values())
                else self.store.read_text(record.run_id, path),
            )
            for path in report_paths
            if self.store.exists(record.run_id, path)
        ]
        review = self._load_review(record)
        try:
            figures = self._load_source(record).figures
        except (FileNotFoundError, TypeError, ValueError):
            figures = []
        draft_markdown: str | None = None
        transformation: object | None = None
        visual_extractions: list[object] = []
        if record.status == "waiting" and "draft.document" in record.artifacts:
            draft_markdown = self.store.read_verified_text(
                record.run_id,
                record.artifacts["draft.document"],
                key="draft.document",
            )
            transformation = self.store.read_verified_json(
                record.run_id,
                record.artifacts["draft.transformation"],
                key="draft.transformation",
            )
            visual_payload = self.store.read_verified_json(
                record.run_id,
                record.artifacts["draft.visual_extractions"],
                key="draft.visual_extractions",
            )
            visual_extractions = list(visual_payload.get("visual_extractions", []))
        record = register_artifact(
            record,
            "report.html",
            self.store.write_text(
                record.run_id,
                HTML_REPORT,
                render_html_report(
                    record=record,
                    review=review,
                    documents=documents,
                    audit=audit,
                    figures=figures,
                    draft_markdown=draft_markdown,
                    transformation=transformation,
                    visual_extractions=visual_extractions,
                ),
                media_type="text/html; charset=utf-8",
            ),
        )
        self.store.save_run(record)
        return record

    def _load_review(self, record: RunRecord) -> ReviewReport:
        artifact = record.artifacts.get("review.report")
        payload = (
            self.store.read_verified_json(record.run_id, artifact, key="review.report")
            if artifact is not None
            else self.store.read_json(record.run_id, REVIEW)
        )
        return ReviewReport.model_validate(payload)

    def _load_source(self, record: RunRecord) -> SourceDocument:
        artifact = record.artifacts.get("source.metadata")
        payload = (
            self.store.read_verified_json(record.run_id, artifact, key="source.metadata")
            if artifact is not None
            else self.store.read_json(record.run_id, SOURCE_METADATA)
        )
        return SourceDocument.model_validate(payload)

    def _source_sections(
        self, record: RunRecord, blocks: tuple[Any, ...], spans: list[SourceSpan]
    ) -> list[Section]:
        try:
            artifact = record.artifacts.get("source.metadata")
            payload = (
                self.store.read_verified_json(record.run_id, artifact, key="source.metadata")
                if artifact is not None
                else self.store.read_json(record.run_id, SOURCE_METADATA)
            )
            sections = [Section.model_validate(item) for item in payload.get("sections", [])]
            if self._valid_recovered_sections(sections, {item.span_id for item in spans}):
                return sections
        except (FileNotFoundError, TypeError, ValueError):
            pass
        return self._sections(blocks, spans)

    def _read_decisions_file(self, run_id: str) -> list[Decision]:
        record = self.store.load_run(run_id)
        decision_bundle = self._load_decision_bundle(record)
        review = self._load_review(record)
        return self._effective_decisions(review, decision_bundle.decisions)

    def _load_decision_bundle(self, record: RunRecord) -> DecisionBundle:
        """Load canonical decisions, verifying the registered artifact when present."""

        artifact = record.artifacts.get("review.decisions")
        if artifact is not None:
            payload = self.store.read_verified_json(
                record.run_id,
                artifact,
                key="review.decisions",
            )
            return DecisionBundle.model_validate(payload)
        return self._read_decision_bundle(self.store.run_path(record.run_id) / DECISIONS_YAML)

    @staticmethod
    def _canonical_decisions(review: ReviewReport, decisions: list[Decision]) -> list[Decision]:
        """Validate editable choices against the immutable generated question context."""

        questions = {item.question_id: item for item in review.questions}
        canonical: list[Decision] = []
        seen: set[str] = set()
        for decision in decisions:
            if decision.question_id in seen:
                raise ValueError(f"duplicate decision for {decision.question_id}")
            seen.add(decision.question_id)
            question = questions.get(decision.question_id)
            if question is None:
                raise ValueError(f"unknown decision question_id: {decision.question_id}")
            if decision.question and decision.question != question.prompt:
                raise ValueError(
                    f"question text for {decision.question_id} must not be changed; edit answer instead"
                )
            if decision.suggestion is not None and decision.suggestion != question.suggestion:
                raise ValueError(
                    f"suggestion for {decision.question_id} must not be changed; choose a disposition instead"
                )
            canonical.append(
                decision.model_copy(
                    update={"question": question.prompt, "suggestion": question.suggestion}
                )
            )
        return canonical

    @classmethod
    def _effective_decisions(
        cls, review: ReviewReport, decisions: list[Decision]
    ) -> list[Decision]:
        """Resolve accepted suggestions to the canonical text used during rewrite."""

        effective: list[Decision] = []
        for decision in cls._canonical_decisions(review, decisions):
            if decision.disposition == "accept_suggestion":
                if not decision.suggestion:
                    raise ValueError(
                        f"{decision.question_id} has no suggestion to accept; provide an answer instead"
                    )
                decision = decision.model_copy(
                    update={"answer": decision.suggestion, "disposition": "accept"}
                )
            effective.append(decision)
        return effective

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
        if "approve_rewrite" not in data:
            raise ApprovalRequiredError("decisions are missing explicit approve_rewrite")
        approve = data["approve_rewrite"]
        if type(approve) is not bool:
            raise ApprovalTypeError("approve_rewrite must be a boolean")
        return DecisionBundle(
            decisions=[Decision.model_validate(item) for item in values],
            steering=str(data.get("steering") or ""),
            waivers=[Waiver.model_validate(item) for item in waivers_raw],
            approve_rewrite=approve,
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
            "transformation_provider": type(self.transformation_provider).__name__
            if self._transformation_provider_configured
            else "offline-deterministic",
            "visual_provider": type(self.visual_provider).__name__
            if self.visual_provider
            else None,
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
            "# Human decision gate. Read markdown/06-review-questions.md before editing.",
            "# Edit answer, disposition, rationale, steering, waivers, and approve_rewrite only.",
            "# Dispositions: accept | accept_suggestion | reject | defer",
            "# - accept: apply the text in answer",
            "# - accept_suggestion: apply the generated suggestion (when present)",
            "# - reject: resolve without applying the answer or suggestion",
            "# - defer: keep Stage 2 paused",
            "schema_version: core.decisions.v1",
            "approve_rewrite: false",
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
                    f"    question: {json.dumps(question.prompt, ensure_ascii=False)}",
                    (
                        f"    suggestion: {json.dumps(question.suggestion, ensure_ascii=False)}"
                        if question.suggestion
                        else "    suggestion: null"
                    ),
                    '    answer: ""',
                    "    disposition: defer",
                    '    rationale: ""',
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
