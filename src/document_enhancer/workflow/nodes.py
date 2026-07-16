"""LangGraph node implementations that compose the M3/M4 ports with M5 gates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from langgraph.types import interrupt

from document_enhancer.analysis.models import AnalysisRequest
from document_enhancer.artifacts.paths import RunPaths, content_addressed_run_id
from document_enhancer.artifacts.run_storage import RunStorage
from document_enhancer.audit import ContentAuditor, build_audit, write_audit_artifacts
from document_enhancer.chunking import build_chunks
from document_enhancer.clarification import (
    build_rewrite_checklist,
    load_yaml,
    synthesize_questions,
    validate_checklist_approval,
    validate_reviewer_inputs,
    write_checklist_artifacts,
    write_questions_artifacts,
)
from document_enhancer.config import yaml_parser
from document_enhancer.domain.analysis import AnalysisReport, FindingSet
from document_enhancer.domain.audit import Audit
from document_enhancer.domain.enums import DocumentType
from document_enhancer.domain.questions import (
    AnswersArtifact,
    ContentLedger,
    QuestionsArtifact,
    RewriteChecklist,
    Steering,
    WaiversArtifact,
)
from document_enhancer.domain.run import ExportChunk
from document_enhancer.domain.semantic import SemanticDocument
from document_enhancer.domain.serialization import model_to_yaml
from document_enhancer.domain.source import NormalizedDocument as DomainNormalizedDocument
from document_enhancer.errors import ValidationError, WaitingForReviewError
from document_enhancer.export import (
    build_export_bundle,
    validate_export_bundle,
    write_export_bundle,
)
from document_enhancer.ingest.models import NormalizedDocument, RawDocument
from document_enhancer.ingest.normalize import normalize_document
from document_enhancer.ingest.pipeline import ParserRegistry, parse_source
from document_enhancer.ingest.recovery import (
    StructureRecoveryConfig,
    StructureRecoveryResult,
    StructureRecoveryService,
)
from document_enhancer.llm import EmbeddingProfile, GeminiEmbeddingAdapter
from document_enhancer.rag import OfflineDeterministicEmbedder, build_package, ingest_package
from document_enhancer.references.loader import load_reference_pack
from document_enhancer.rewrite import (
    EnhancedDocumentModel,
    GovernedReference,
    RevisionCounters,
    SectionRewriteInput,
    build_content_ledger,
    build_enhanced_document,
    build_rewrite_inputs,
    build_semantic_document,
    render_enhanced_markdown,
    validate_content_ledger,
    validate_mermaid,
)
from document_enhancer.rewrite.governed_example import apply_governed_example_contract

from .cache import WorkflowCache, stage_inputs_for
from .checkpoint import WorkflowCheckpoint
from .prompts import resolved_prompt_artifact
from .routing import gate1_required, gate1_satisfied, gate2_required, gate2_satisfied, next_action
from .state import WorkflowSnapshot, WorkflowState, state_json

if TYPE_CHECKING:
    from .execution import ExecutionMetadata

AnalysisRunner = Callable[[AnalysisRequest], object]
RewriteRunner = Callable[[tuple[SectionRewriteInput, ...]], object]
AuditRevisionRunner = Callable[[EnhancedDocumentModel, Audit], object]


class QuestionGenerator(Protocol):
    def generate(
        self,
        *,
        baseline: QuestionsArtifact,
        analysis_result: object,
        normalized: NormalizedDocument,
        document_type: DocumentType,
    ) -> QuestionsArtifact: ...


class ChecklistGenerator(Protocol):
    def generate(
        self,
        *,
        baseline: RewriteChecklist,
        questions: QuestionsArtifact,
        answers: AnswersArtifact,
        steering: Steering | None,
        waivers: WaiversArtifact,
        document_type: DocumentType,
    ) -> RewriteChecklist: ...


class StructureRunner(Protocol):
    def run(
        self,
        document: NormalizedDocument,
        *,
        repository: Any | None = None,
        run_id: str | None = None,
    ) -> StructureRecoveryResult: ...


@dataclass
class WorkflowServices:
    """Dependencies injected at the M5 boundary; all model calls remain optional in tests."""

    run_root: Path
    source: Path
    run_id: str | None = None
    document_type: DocumentType = DocumentType.PROCESS
    parser_registry: ParserRegistry | None = None
    structure_service: StructureRunner | None = None
    analysis_runner: AnalysisRunner | None = None
    question_generator: QuestionGenerator | None = None
    checklist_generator: ChecklistGenerator | None = None
    rewrite_runner: object | None = None
    content_auditor: ContentAuditor | None = None
    audit_revision_runner: object | None = None
    structure_mode: str = "parser"
    gate2_enabled: bool = True
    stop_after: str | None = None
    offline: bool = True
    input_fingerprints: dict[str, object] = field(default_factory=dict)
    cache: WorkflowCache = field(default_factory=WorkflowCache)
    checkpoint: WorkflowCheckpoint | None = None
    storage: RunStorage | None = None
    prompt_pack: Path | None = None
    reference_pack: Path | None = None
    prompt_ids: tuple[str, ...] = (
        "clarification.questions",
        "clarification.rewrite-checklist",
    )
    max_rewrite_revisions: int = 2
    max_audit_revisions: int = 1
    rag_enabled: bool = True
    auto_catalog_ingest: bool = True
    catalog_path: Path | None = None
    embedding_profile: EmbeddingProfile = field(default_factory=EmbeddingProfile)
    embedding_adapter: GeminiEmbeddingAdapter | None = None
    execution_metadata: ExecutionMetadata | None = None

    def __post_init__(self) -> None:
        if self.offline and self.embedding_profile.provider != "offline":
            if self.embedding_adapter is not None:
                raise ValueError("offline workflow cannot use a live embedding adapter identity")
            self.embedding_profile = EmbeddingProfile.offline(
                dimensions=self.embedding_profile.dimensions
            )
        if not self.offline and self.embedding_profile.provider != "google":
            raise ValueError("live workflow requires a Google/Gemini embedding profile")

    def attach_run(self, raw: RawDocument, *, run_id: str | None = None) -> None:
        resolved_run_id = run_id or self.run_id or content_addressed_run_id(raw.source_digest)
        self.run_id = resolved_run_id
        paths = RunPaths(self.run_root, resolved_run_id)
        state_path = paths.artifact_path("workflow-state.json")
        if state_path.is_file():
            try:
                existing = WorkflowSnapshot.model_validate_json(
                    state_path.read_text(encoding="utf-8")
                )
            except ValueError as exc:
                raise ValidationError(
                    "existing content-addressed run has an invalid workflow snapshot"
                ) from exc
            current_execution = (
                self.execution_metadata.model_dump(mode="json")
                if self.execution_metadata is not None
                else None
            )
            if (
                existing.offline != self.offline
                or existing.structure_mode != self.structure_mode
                or existing.execution_metadata != current_execution
            ):
                raise ValidationError(
                    "content-addressed run already exists with an incompatible execution profile"
                )
        self.storage = RunStorage(paths)
        self.checkpoint = WorkflowCheckpoint(paths)

    @property
    def paths(self) -> RunPaths:
        if self.checkpoint is None:
            raise RuntimeError("workflow run paths are not attached yet")
        return self.checkpoint.paths


def _as_raw(value: object) -> RawDocument:
    return value if isinstance(value, RawDocument) else RawDocument.model_validate(value)


def _as_normalized(value: object) -> NormalizedDocument:
    return (
        value if isinstance(value, NormalizedDocument) else NormalizedDocument.model_validate(value)
    )


def _as_questions(value: object) -> QuestionsArtifact:
    return (
        value if isinstance(value, QuestionsArtifact) else QuestionsArtifact.model_validate(value)
    )


def _as_answers(value: object) -> AnswersArtifact:
    return value if isinstance(value, AnswersArtifact) else AnswersArtifact.model_validate(value)


def _as_steering(value: object | None) -> Steering | None:
    return (
        None
        if value is None
        else (value if isinstance(value, Steering) else Steering.model_validate(value))
    )


def _as_waivers(value: object) -> WaiversArtifact:
    return value if isinstance(value, WaiversArtifact) else WaiversArtifact.model_validate(value)


def _as_checklist(value: object) -> RewriteChecklist:
    return value if isinstance(value, RewriteChecklist) else RewriteChecklist.model_validate(value)


def _as_ledger(value: object) -> ContentLedger:
    return value if isinstance(value, ContentLedger) else ContentLedger.model_validate(value)


def _as_rewrite_inputs(value: object) -> tuple[SectionRewriteInput, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(
            item
            if isinstance(item, SectionRewriteInput)
            else SectionRewriteInput.model_validate(item)
            for item in value
        )
    raise ValidationError("rewrite inputs are missing or invalid")


def _as_enhanced_model(value: object) -> EnhancedDocumentModel:
    return (
        value
        if isinstance(value, EnhancedDocumentModel)
        else EnhancedDocumentModel.model_validate(value)
    )


def _as_semantic(value: object) -> SemanticDocument:
    return value if isinstance(value, SemanticDocument) else SemanticDocument.model_validate(value)


def _as_audit(value: object) -> Audit:
    return value if isinstance(value, Audit) else Audit.model_validate(value)


def _as_revision_counters(value: object, services: WorkflowServices) -> RevisionCounters:
    if value is None:
        return RevisionCounters(
            max_rewrite_revisions=services.max_rewrite_revisions,
            max_audit_revisions=services.max_audit_revisions,
        )
    return value if isinstance(value, RevisionCounters) else RevisionCounters.model_validate(value)


def _finding_set(value: object) -> FindingSet:
    if isinstance(value, FindingSet):
        return value
    if isinstance(value, AnalysisReport):
        findings = [finding for analysis in value.analyses for finding in analysis.findings]
        return FindingSet(
            document_id=value.document_id,
            source_digest=value.source_digest,
            findings=findings,
            blocking_count=sum(finding.blocking for finding in findings),
            generated_from_analysis_ids=[analysis.analysis_id for analysis in value.analyses],
        )
    if hasattr(value, "synthesis"):
        synthesis = cast(Any, value).synthesis
        return _finding_set(synthesis.finding_set)
    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        if "finding_set" in mapping:
            return _finding_set(mapping["finding_set"])
        if "synthesis" in mapping:
            return _finding_set(mapping["synthesis"])
        if "findings" in mapping:
            return FindingSet.model_validate(mapping)
    return FindingSet(
        document_id="DOC-OFFLINE", source_digest="0" * 64, findings=[], blocking_count=0
    )


def _input_values(state: WorkflowState, services: WorkflowServices) -> dict[str, object]:
    raw = state.get("raw")
    normalized = state.get("normalized")
    source_digest = state.get("source_digest", "")
    values = {
        "source": source_digest,
        "structure": state.get("cache_keys", {}).get("selected_view", ""),
        "analysis": state.get("cache_keys", {}).get("analysis", ""),
        "questions": state.get("cache_keys", {}).get("question_synthesis", ""),
        "checklist": state.get("cache_keys", {}).get("checklist", ""),
        "ledger": state.get("cache_keys", {}).get("content_ledger", ""),
        "rewrite": state.get("cache_keys", {}).get("rewrite_model", ""),
        "semantic_model": state.get("cache_keys", {}).get("semantic", ""),
        "waivers": state_json(state.get("waivers", "")),
        **services.input_fingerprints,
    }
    if isinstance(raw, RawDocument):
        values["source"] = raw.source_digest
    if isinstance(normalized, NormalizedDocument):
        values["structure"] = normalized.selected_view_digest or normalized.raw.source_digest
    return values


def _stage_key(state: WorkflowState, services: WorkflowServices, stage: str) -> str:
    values = _input_values(state, services)
    inputs = stage_inputs_for(stage, values)
    completed = state.get("cache_keys", {})
    key = services.cache.key(stage, inputs, completed_keys=completed)
    state.setdefault("stage_inputs", {})[stage] = state_json(inputs)
    return key


def _finish_stage(state: WorkflowState, services: WorkflowServices, stage: str) -> WorkflowState:
    state["current_stage"] = stage
    if stage != "complete":
        state["status"] = "running"
    completed = state.setdefault("completed_stages", [])
    if stage not in completed:
        completed.append(stage)
    state.setdefault("cache_keys", {})[stage] = _stage_key(state, services, stage)
    state["next_action"] = next_action(state)
    if services.checkpoint is not None:
        services.checkpoint.record_stage(
            state,
            stage=stage,
            cache_key=state["cache_keys"][stage],
            status="succeeded",
        )
        services.checkpoint.save_state(state)
    return state


def _persist_waiting(
    state: WorkflowState, services: WorkflowServices, stage: str, payload: dict[str, object]
) -> None:
    state["current_stage"] = stage
    state["status"] = "waiting"
    state["next_action"] = next_action(state)
    state["resume_entry"] = stage
    if services.checkpoint is not None:
        services.checkpoint.record_stage(
            state,
            stage=stage,
            cache_key=_stage_key(state, services, stage),
            status="pending",
            payload=payload,
        )
        services.checkpoint.save_state(state)


def _pause(
    state: WorkflowState, services: WorkflowServices, stage: str, payload: dict[str, object]
) -> None:
    _persist_waiting(state, services, stage, payload)
    # A real LangGraph interrupt is used when this node runs inside the compiled graph. The
    # durable JSON snapshot above is the process-boundary recovery record; the CLI can recreate a
    # graph after termination and start at resume_entry without replaying completed nodes.
    interrupt({"stage": stage, **payload})
    raise WaitingForReviewError(next_action(state))  # pragma: no cover - interrupt always raises


def raw_ingest_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    if state.get("raw") and state.get("run_id"):
        return _finish_stage(state, services, "raw_ingest")
    raw = parse_source(services.source, registry=services.parser_registry)
    services.attach_run(raw)
    state.update(
        {
            "run_id": services.paths.run_id,
            "source_path": str(services.source.resolve()),
            "source_digest": raw.source_digest,
            # M3's immutable ingest contract intentionally does not invent a domain document
            # identity. Until M6's governed identity assignment, use a stable source-derived
            # provisional document ID and keep the source digest in the manifest.
            "document_id": f"DOC-{raw.source_digest[:16].upper()}",
            "document_type": services.document_type.value,
            "raw": raw,
            "status": "running",
            "gate2_enabled": services.gate2_enabled,
            "offline": services.offline,
            "structure_mode": services.structure_mode,
            "execution_metadata": (
                services.execution_metadata.model_dump(mode="json")
                if services.execution_metadata is not None
                else None
            ),
            "stop_after": services.stop_after,
        }
    )
    return _finish_stage(state, services, "raw_ingest")


def normalize_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    raw = _as_raw(state["raw"])
    normalized = normalize_document(raw)
    state["normalized"] = normalized
    if services.storage is None:
        services.attach_run(raw, run_id=str(state["run_id"]))
    assert services.storage is not None
    services.storage.persist_ingest(normalized)
    return _finish_stage(state, services, "normalize")


def structure_quality_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    normalized = _as_normalized(state["normalized"])
    state["normalized"] = normalized
    return _finish_stage(state, services, "structure_quality")


def structure_scan_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    normalized = _as_normalized(state["normalized"])
    if services.structure_service is None:
        config = StructureRecoveryConfig(
            mode=cast(Any, services.structure_mode), document_type=services.document_type.value
        )
        services.structure_service = StructureRecoveryService(config=config)
    assert services.storage is not None
    result = services.structure_service.run(
        normalized,
        repository=services.storage,
        run_id=str(state["run_id"]),
    )
    state["structure_result"] = result
    state["normalized"] = result.normalized
    state["document_id"] = result.authoritative_raw.document_id
    return _finish_stage(state, services, "structure_scan")


def structure_recovery_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    # M3's StructureRecoveryService owns scan/window/reconciliation/recovery. This node keeps the
    # LangGraph route explicit and makes the no-recovery path a deterministic no-op.
    return _finish_stage(state, services, "structure_recovery")


def structure_validate_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    result = state.get("structure_result")
    if result is not None:
        validation = getattr(result, "validation", None)
        if validation is None and isinstance(result, dict):
            validation = result.get("validation")
        passed = getattr(validation, "passed", None) if validation is not None else None
        if passed is None and isinstance(validation, dict):
            passed = validation.get("passed")
        if passed is False and services.structure_mode not in {"parser", "off"}:
            raise ValidationError("selected structure failed exact source coverage validation")
    return _finish_stage(state, services, "structure_validate")


def selected_view_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    normalized = _as_normalized(state["normalized"])
    if normalized.selected_view is None or not normalized.selected_view.validation_passed:
        raise ValidationError("selected structural view is missing or failed validation")
    return _finish_stage(state, services, "selected_view")


def analysis_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    normalized = _as_normalized(state["normalized"])
    if services.analysis_runner is None:
        # Offline/debug mode intentionally produces no answer or factual finding. The absence of
        # a provider is visible in the workflow state and cannot invent a content claim.
        state["analysis_result"] = FindingSet(
            document_id=state["document_id"],
            source_digest=state["source_digest"],
            findings=[],
            blocking_count=0,
        )
    else:
        structure_result = cast(Any, state.get("structure_result"))
        if structure_result is None or not hasattr(structure_result, "authoritative_raw"):
            raise ValidationError("M4 analysis requires the validated M3 authoritative source port")
        analysis_document = DomainNormalizedDocument(
            raw=structure_result.authoritative_raw,
            structural_view=structure_result.authoritative_view,
            normalized_markdown=normalized.normalized_markdown,
            asset_digests={
                asset.asset_id: asset.digest
                for asset in normalized.assets
                if asset.digest is not None
            },
        )
        request = AnalysisRequest(
            document=analysis_document,
            document_type=DocumentType(
                str(state.get("document_type", services.document_type.value))
            ),
            metadata=(),
            reviewer_inputs="",
        )
        state["analysis_result"] = services.analysis_runner(request)
    return _finish_stage(state, services, "analysis")


def question_synthesis_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    findings = _finding_set(state.get("analysis_result"))
    result = synthesize_questions(
        findings,
        document_id=str(state["document_id"]),
        strict_blocking=True,
    )
    questions = _as_questions(result.questions)
    if services.question_generator is not None:
        questions = services.question_generator.generate(
            baseline=questions,
            analysis_result=state.get("analysis_result"),
            normalized=_as_normalized(state["normalized"]),
            document_type=services.document_type,
        )
    state["questions"] = questions
    answers = AnswersArtifact(document_id=questions.document_id, version_id=questions.version_id)
    steering = Steering(steering_id="STEER-REVIEW-001", document_id=questions.document_id)
    waivers = WaiversArtifact(document_id=questions.document_id)
    state["answers"] = answers
    state["steering"] = steering
    state["waivers"] = waivers
    assert services.checkpoint is not None
    paths = services.paths
    question_artifact_payload = {
        "questions": questions.model_dump(mode="json"),
        "answers": answers.model_dump(mode="json"),
        "steering": steering.model_dump(mode="json"),
        "waivers": waivers.model_dump(mode="json"),
    }

    def write_question_artifacts() -> None:
        write_questions_artifacts(
            paths.artifact_path("clarification"),
            questions,
            answers=answers,
            steering=steering,
            waivers=waivers,
        )

    services.checkpoint.side_effect_once(
        "question_synthesis",
        "clarification-artifacts",
        question_artifact_payload,
        write_question_artifacts,
    )
    if services.prompt_pack is not None and services.reference_pack is not None:
        normalized = _as_normalized(state["normalized"])
        document_type = str(state.get("document_type", services.document_type.value))
        resolved_prompt_artifact(
            services.prompt_pack,
            reference_pack=services.reference_pack,
            prompt_ids=list(services.prompt_ids),
            document_type=document_type,
            variables={
                "document_type": document_type,
                "document_metadata": {},
                "source_text": normalized.normalized_markdown,
                "analysis_results": json.dumps(
                    state_json(state.get("analysis_result")), sort_keys=True
                ),
                "reviewer_inputs": "",
            },
            destination=paths.artifact_path("prompts/resolved-manifest.json"),
        )
    return _finish_stage(state, services, "question_synthesis")


def _load_reviewer_inputs(
    state: WorkflowState, services: WorkflowServices
) -> tuple[QuestionsArtifact, AnswersArtifact, Steering | None, WaiversArtifact]:
    questions = _as_questions(state["questions"])
    directory = services.paths.artifact_path("clarification")
    answers = (
        load_yaml(directory / "answers.yaml", AnswersArtifact)
        if (directory / "answers.yaml").exists()
        else AnswersArtifact(document_id=questions.document_id)
    )
    steering = (
        load_yaml(directory / "steering.yaml", Steering)
        if (directory / "steering.yaml").exists()
        else None
    )
    waivers = (
        load_yaml(directory / "waivers.yaml", WaiversArtifact)
        if (directory / "waivers.yaml").exists()
        else WaiversArtifact(document_id=questions.document_id)
    )
    return questions, answers, steering, waivers


def gate1_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    questions, answers, steering, waivers = _load_reviewer_inputs(state, services)
    raw = _as_raw(state["raw"])
    report = validate_reviewer_inputs(
        questions,
        answers,
        steering,
        waivers,
        source_span_ids=(block.span_id for block in raw.blocks),
    )
    state["questions"] = questions
    state["answers"] = answers
    state["steering"] = steering
    state["waivers"] = waivers
    state["validation_report"] = report
    from document_enhancer.artifacts.atomic import atomic_write_json

    assert services.checkpoint is not None

    def write_validation_report() -> None:
        atomic_write_json(
            services.paths.artifact_path("clarification/validation-report.json"),
            report.model_dump(mode="json"),
        )

    services.checkpoint.side_effect_once(
        "gate1",
        "validation-report",
        report.model_dump(mode="json"),
        write_validation_report,
    )
    required = gate1_required(questions, stop_after=state.get("stop_after"))
    if required and (
        state.get("stop_after") == "questions" or not report.valid or not gate1_satisfied(state)
    ):
        _pause(
            state,
            services,
            "gate1",
            {
                "question_count": len(questions.questions),
                "blocking_question_ids": [
                    item.question_id for item in questions.questions if item.blocking
                ],
                "diagnostic_count": len(report.diagnostics),
            },
        )
    return _finish_stage(state, services, "gate1")


def checklist_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    questions, answers, steering, waivers = _load_reviewer_inputs(state, services)
    existing = services.paths.artifact_path("clarification/rewrite-checklist.yaml")
    checklist = build_rewrite_checklist(
        questions,
        answers=answers,
        steering=steering,
        waivers=waivers,
    )
    if services.checklist_generator is not None:
        checklist = services.checklist_generator.generate(
            baseline=checklist,
            questions=questions,
            answers=answers,
            steering=steering,
            waivers=waivers,
            document_type=services.document_type,
        )
    # Gate 2 edits are human-owned once approval exists; otherwise regeneration is safe and
    # reflects changed reviewer inputs without duplicating side effects.
    if existing.exists():
        try:
            prior = load_yaml(existing, RewriteChecklist)
            if prior.approved_by:
                checklist = prior
        except ValueError:
            pass
    state["questions"] = questions
    state["answers"] = answers
    state["steering"] = steering
    state["waivers"] = waivers
    state["checklist"] = checklist
    assert services.checkpoint is not None

    def write_checklist() -> None:
        write_checklist_artifacts(services.paths.artifact_path("clarification"), checklist)

    services.checkpoint.side_effect_once(
        "checklist",
        "rewrite-checklist-artifacts",
        checklist.model_dump(mode="json"),
        write_checklist,
    )
    return _finish_stage(state, services, "checklist")


def gate2_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    checklist_path = services.paths.artifact_path("clarification/rewrite-checklist.yaml")
    checklist = load_yaml(checklist_path, RewriteChecklist)
    waivers = _as_waivers(state.get("waivers", WaiversArtifact(document_id=checklist.document_id)))
    report = validate_checklist_approval(checklist, waivers=waivers)
    state["checklist"] = checklist
    state["validation_report"] = report
    if gate2_required(state) and (not report.valid or not gate2_satisfied(state)):
        _pause(
            state,
            services,
            "gate2",
            {
                "checklist_item_count": len(checklist.items),
                "unresolved_blocking_item_ids": [
                    item.checklist_item_id for item in checklist.unresolved_blocking_items
                ],
                "diagnostic_count": len(report.diagnostics),
            },
        )
    return _finish_stage(state, services, "gate2")


def _m6_reference_contract(
    services: WorkflowServices,
) -> tuple[list[dict[str, object]], str, str, str, str]:
    """Resolve only machine-readable template metadata; authoring comments never enter inputs."""

    document_type = services.document_type.value
    if services.reference_pack is None:
        sections: list[dict[str, object]] = [
            {
                "id": f"SEC-{document_type.upper()}-CONTENT",
                "heading": "Document content",
                "anchor": "document-content",
            }
        ]
        return sections, "enterprise_core", "1.0.0", f"TPL-{document_type.upper()}-001", "1.0.0"
    pack = load_reference_pack(services.reference_pack)
    requirements_path = pack.requirements_path(document_type)
    requirements = yaml_parser().load(requirements_path.read_text(encoding="utf-8"))
    sections: list[dict[str, object]] = []
    for item in requirements.get("sections", ()) if isinstance(requirements, dict) else ():
        if not isinstance(item, dict):
            continue
        heading = str(item.get("heading", item.get("id", "section")))
        sections.append(
            {
                "id": str(item.get("id")),
                "heading": heading,
                "anchor": _m6_slug(heading),
                "order": int(item.get("order", len(sections))),
            }
        )
    template_id = str(requirements.get("template_id", f"TPL-{document_type.upper()}-001"))
    template_version = str(requirements.get("version", "1.0.0"))
    return sections, pack.pack_id, pack.version, template_id, template_version


def _m6_slug(value: str) -> str:
    import re

    return "-".join(re.findall(r"[a-z0-9]+", value.lower())) or "section"


def _m6_governed_references(services: WorkflowServices) -> tuple[GovernedReference, ...]:
    if services.reference_pack is None:
        return ()
    pack = load_reference_pack(services.reference_pack)
    return tuple(
        GovernedReference(
            reference_id=f"REF-{item.path.replace('/', '-').replace('.', '-').upper()}",
            kind=item.kind,
            title=item.path,
            precedence=item.kind,
            digest=item.sha256,
        )
        for item in pack.files
        if item.path != "manifest.yaml"
    )


def content_ledger_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    normalized = _as_normalized(state["normalized"])
    sections, _pack_id, _pack_version, _template_id, _template_version = _m6_reference_contract(
        services
    )
    ledger = build_content_ledger(
        normalized,
        document_id=str(state["document_id"]),
        target_sections=sections,
    )
    source_blocks = normalized.raw.blocks
    source_ids = [block.span_id.upper() for block in source_blocks]
    source_texts = {block.span_id.upper(): block.text for block in source_blocks}
    coverage = validate_content_ledger(ledger, source_ids, source_texts=source_texts)
    if not coverage.valid:
        raise ValidationError("content ledger coverage failed: " + "; ".join(coverage.errors))
    state["content_ledger"] = ledger
    from document_enhancer.artifacts.atomic import atomic_write_bytes, atomic_write_json

    assert services.checkpoint is not None
    payload = ledger.model_dump(mode="json")

    def write_ledger() -> None:
        jsonl = "".join(
            json.dumps(entry.model_dump(mode="json"), sort_keys=True) + "\n"
            for entry in ledger.entries
        )
        atomic_write_bytes(
            services.paths.artifact_path("output/content-ledger.jsonl"), jsonl.encode("utf-8")
        )
        atomic_write_json(services.paths.artifact_path("output/content-ledger.json"), payload)

    services.checkpoint.side_effect_once("content_ledger", "content-ledger", payload, write_ledger)
    return _finish_stage(state, services, "content_ledger")


def rewrite_inputs_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    normalized = _as_normalized(state["normalized"])
    ledger = _as_ledger(state["content_ledger"])
    sections, _pack_id, _pack_version, _template_id, _template_version = _m6_reference_contract(
        services
    )
    questions, answers, steering, waivers = _load_reviewer_inputs(state, services)
    del questions, waivers
    checklist = _as_checklist(state.get("checklist"))
    inputs = build_rewrite_inputs(
        normalized,
        ledger,
        sections=sections,
        answers=answers,
        steering=steering,
        checklist=checklist,
        governed_references=_m6_governed_references(services),
    )
    state["rewrite_inputs"] = list(inputs)
    from document_enhancer.artifacts.atomic import atomic_write_json

    assert services.checkpoint is not None
    payload = [item.model_dump(mode="json") for item in inputs]
    services.checkpoint.side_effect_once(
        "rewrite_inputs",
        "rewrite-inputs",
        payload,
        lambda: (
            atomic_write_json(services.paths.artifact_path("output/rewrite-inputs.json"), payload),
            None,
        )[1],
    )
    return _finish_stage(state, services, "rewrite_inputs")


def rewrite_model_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    inputs = _as_rewrite_inputs(state["rewrite_inputs"])
    ledger = _as_ledger(state["content_ledger"])
    _sections, pack_id, pack_version, template_id, template_version = _m6_reference_contract(
        services
    )
    counters = _as_revision_counters(state.get("revision_counters"), services).consume_rewrite()
    if services.rewrite_runner is not None:
        from .model_services import GovernedRewriteRequest

        request = GovernedRewriteRequest(
            inputs=inputs,
            ledger=ledger,
            document_id=str(state["document_id"]),
            document_type=services.document_type,
            reference_pack_id=pack_id,
            reference_pack_version=pack_version,
            template_id=template_id,
            template_version=template_version,
            counters=counters,
        )
        if hasattr(services.rewrite_runner, "rewrite"):
            candidate = cast(Any, services.rewrite_runner).rewrite(request)
        else:
            candidate = cast(RewriteRunner, services.rewrite_runner)(inputs)
        if isinstance(candidate, Mapping) and "model" in candidate:
            candidate = cast(Mapping[str, object], candidate)["model"]
        model = _as_enhanced_model(candidate)
    else:
        model = build_enhanced_document(
            inputs,
            document_id=str(state["document_id"]),
            document_type=services.document_type,
            reference_pack_id=pack_id,
            reference_pack_version=pack_version,
            template_id=template_id,
            template_version=template_version,
            ledger=ledger,
            revision_counters=counters,
        )
        if services.offline and services.reference_pack is not None:
            pack = load_reference_pack(services.reference_pack)
            example_digest = hashlib.sha256(
                pack.example_path(services.document_type.value).read_bytes()
            ).hexdigest()
            if inputs and inputs[0].source_digest == example_digest:
                requirements = _m7_requirements(services)
                if requirements is None:
                    raise ValidationError("governed example rewrite requires template requirements")
                model = apply_governed_example_contract(model, inputs, requirements)
    model = model.model_copy(update={"revision_counters": counters})
    state["revision_counters"] = counters
    state["enhanced_model"] = model
    from document_enhancer.artifacts.atomic import atomic_write_bytes, atomic_write_json

    assert services.checkpoint is not None
    payload = model.model_dump(mode="json")

    def write_model() -> None:
        atomic_write_json(services.paths.artifact_path("output/enhanced-model.json"), payload)
        atomic_write_bytes(
            services.paths.artifact_path("output/open-issues.yaml"),
            json.dumps(
                {"issues": [issue.model_dump(mode="json") for issue in model.open_issues]},
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            + b"\n",
        )

    services.checkpoint.side_effect_once("rewrite_model", "enhanced-model", payload, write_model)
    return _finish_stage(state, services, "rewrite_model")


def render_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    model = _as_enhanced_model(state["enhanced_model"])
    if services.reference_pack is None:
        from document_enhancer.references.loader import bundled_reference_pack_path

        reference_pack = bundled_reference_pack_path()
    else:
        reference_pack = services.reference_pack
    markdown = render_enhanced_markdown(model, reference_pack=reference_pack)
    digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    version = model.version.model_copy(update={"enhanced_digest": digest})
    model = model.model_copy(update={"version": version, "markdown_digest": digest})
    state["enhanced_model"] = model
    from document_enhancer.artifacts.atomic import atomic_write_bytes, atomic_write_json

    assert services.checkpoint is not None
    payload = {"digest": digest, "markdown_artifact": model.markdown_artifact}

    def write_render() -> None:
        atomic_write_bytes(
            services.paths.artifact_path("output/enhanced.md"), markdown.encode("utf-8")
        )
        atomic_write_json(
            services.paths.artifact_path("output/enhanced-model.json"),
            model.model_dump(mode="json"),
        )

    services.checkpoint.side_effect_once("render", "enhanced-markdown", payload, write_render)
    return _finish_stage(state, services, "render")


def semantic_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    model = _as_enhanced_model(state["enhanced_model"])
    semantic = build_semantic_document(model)
    state["semantic_document"] = semantic
    from document_enhancer.artifacts.atomic import atomic_write_bytes

    assert services.checkpoint is not None
    payload = semantic.model_dump(mode="json")
    services.checkpoint.side_effect_once(
        "semantic",
        "semantic-sidecar",
        payload,
        lambda: (
            atomic_write_bytes(
                services.paths.artifact_path("output/enhanced.semantic.yaml"),
                model_to_yaml(semantic).encode("utf-8"),
            ),
            None,
        )[1],
    )
    return _finish_stage(state, services, "semantic")


def mermaid_validate_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    model = _as_enhanced_model(state["enhanced_model"])
    results = []
    for diagram in model.mermaid:
        errors = validate_mermaid(diagram)
        if errors:
            raise ValidationError(
                f"Mermaid validation failed for {diagram.diagram_id}: {'; '.join(errors)}"
            )
        results.append({"diagram_id": diagram.diagram_id, "valid": True, "errors": []})
    state["mermaid_validation"] = results
    from document_enhancer.artifacts.atomic import atomic_write_json

    assert services.checkpoint is not None
    services.checkpoint.side_effect_once(
        "mermaid_validate",
        "mermaid-validation",
        results,
        lambda: (
            atomic_write_json(
                services.paths.artifact_path("output/mermaid-validation.json"), results
            ),
            None,
        )[1],
    )
    return _finish_stage(state, services, "mermaid_validate")


def _m7_requirements(services: WorkflowServices) -> Mapping[str, object] | None:
    if services.reference_pack is None:
        return None
    pack = load_reference_pack(services.reference_pack)
    value = yaml_parser().load(
        pack.requirements_path(services.document_type.value).read_text(encoding="utf-8")
    )
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def audit_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    model = _as_enhanced_model(state["enhanced_model"])
    semantic = _as_semantic(state["semantic_document"])
    ledger = _as_ledger(state["content_ledger"])
    raw = _as_raw(state["raw"])
    normalized = _as_normalized(state["normalized"])
    enhanced_path = services.paths.artifact_path("output/enhanced.md")
    if not enhanced_path.is_file():
        raise ValidationError("enhanced Markdown is missing before audit")
    counters = _as_revision_counters(state.get("revision_counters"), services)
    _questions, _answers, _steering, waivers = _load_reviewer_inputs(state, services)
    state["waivers"] = waivers
    audit = build_audit(
        run_id=str(state["run_id"]),
        model=model,
        semantic=semantic,
        ledger=ledger,
        raw=raw,
        source_markdown=normalized.normalized_markdown,
        enhanced_markdown=enhanced_path.read_text(encoding="utf-8"),
        counters=counters,
        requirements=_m7_requirements(services),
        waivers=waivers,
        content_auditor=services.content_auditor,
    )
    state["audit_result"] = audit
    state["audit_route"] = audit.routing.route
    assert services.checkpoint is not None
    services.checkpoint.side_effect_once(
        "audit",
        "audit-artifacts",
        audit.model_dump(mode="json"),
        lambda: write_audit_artifacts(audit, services.paths.artifact_path("audit")),
    )
    if audit.routing.route == "auto_revise":
        if services.audit_revision_runner is None:
            state["audit_route"] = "human_review"
        else:
            counters = counters.consume_audit()
            if hasattr(services.audit_revision_runner, "revise"):
                candidate = cast(Any, services.audit_revision_runner).revise(model, audit)
            else:
                candidate = cast(AuditRevisionRunner, services.audit_revision_runner)(model, audit)
            revised = _as_enhanced_model(candidate)
            revised = revised.model_copy(update={"revision_counters": counters})
            state["enhanced_model"] = revised
            state["revision_counters"] = counters
            state["audit_route"] = "auto_revise"
    return _finish_stage(state, services, "audit")


def audit_gate_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    audit = _as_audit(state["audit_result"])
    _pause(
        state,
        services,
        "audit",
        {
            "audit_status": audit.status.value,
            "route": audit.routing.route,
            "blocker_ids": audit.routing.blocker_ids,
        },
    )
    return state  # pragma: no cover


def audit_failed_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    audit = _as_audit(state["audit_result"])
    raise ValidationError("audit failed closed: " + audit.routing.reason)


def diff_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    audit = _as_audit(state["audit_result"])
    audit.assert_pass()
    return _finish_stage(state, services, "diff")


def chunk_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    audit = _as_audit(state["audit_result"])
    audit.assert_pass()
    chunks = build_chunks(_as_enhanced_model(state["enhanced_model"]))
    if not chunks:
        raise ValidationError("audit passed but no authoritative semantic chunks were produced")
    state["chunks"] = list(chunks)
    return _finish_stage(state, services, "chunk")


def export_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    audit = _as_audit(state["audit_result"])
    chunks = tuple(
        item if isinstance(item, ExportChunk) else ExportChunk.model_validate(item)
        for item in cast(list[object], state["chunks"])
    )
    bundle = build_export_bundle(
        run_id=str(state["run_id"]),
        source_digest=str(state["source_digest"]),
        semantic=_as_semantic(state["semantic_document"]),
        chunks=chunks,
        audit=audit,
    )
    assert services.checkpoint is not None
    export_dir = services.paths.artifact_path("export")
    services.checkpoint.side_effect_once(
        "export",
        "export-bundle",
        bundle.manifest.model_dump(mode="json"),
        lambda: write_export_bundle(bundle, export_dir),
    )
    errors = validate_export_bundle(export_dir)
    if errors:
        raise ValidationError("export reconciliation failed: " + "; ".join(errors))
    state["export_bundle"] = bundle
    return _finish_stage(state, services, "export")


def rag_build_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    if not services.rag_enabled:
        state["rag_build"] = {"status": "disabled"}
        return _finish_stage(state, services, "rag_build")
    adapter = services.embedding_adapter
    if adapter is None and services.offline:
        adapter = GeminiEmbeddingAdapter(
            profile=services.embedding_profile,
            embedder=OfflineDeterministicEmbedder(services.embedding_profile.dimensions),
        )
    manifest = build_package(
        services.paths.run_dir,
        adapter=adapter,
        profile=services.embedding_profile,
    )
    state["rag_build"] = manifest
    return _finish_stage(state, services, "rag_build")


def catalog_ingest_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    if not services.rag_enabled or not services.auto_catalog_ingest:
        state["catalog_ingestion"] = {"status": "disabled"}
        return _finish_stage(state, services, "catalog_ingest")
    catalog_path = services.catalog_path or services.run_root.parent / "rag/catalog.sqlite3"
    receipt = ingest_package(
        services.paths.artifact_path("rag/document-rag.sqlite3"),
        catalog_path,
        receipt_path=services.paths.artifact_path("rag/catalog-ingestion.json"),
    )
    state["catalog_ingestion"] = receipt.as_dict()
    return _finish_stage(state, services, "catalog_ingest")


def complete_node(state: WorkflowState, services: WorkflowServices) -> WorkflowState:
    state["status"] = "succeeded"
    state["current_stage"] = "complete"
    state["next_action"] = next_action(state)
    return _finish_stage(state, services, "complete")


__all__ = [
    "WorkflowServices",
    "audit_failed_node",
    "audit_gate_node",
    "audit_node",
    "analysis_node",
    "checklist_node",
    "catalog_ingest_node",
    "content_ledger_node",
    "complete_node",
    "chunk_node",
    "diff_node",
    "export_node",
    "gate1_node",
    "gate2_node",
    "mermaid_validate_node",
    "normalize_node",
    "question_synthesis_node",
    "rag_build_node",
    "raw_ingest_node",
    "selected_view_node",
    "structure_quality_node",
    "structure_recovery_node",
    "structure_scan_node",
    "structure_validate_node",
    "rewrite_inputs_node",
    "rewrite_model_node",
    "render_node",
    "semantic_node",
]
