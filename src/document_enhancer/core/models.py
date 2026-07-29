"""Canonical v2 contracts for a document enhancement run.

These contracts are deliberately small.  Large intermediate payloads belong in
named artifacts, while ``json/00-run.json`` contains only metadata, references, and
digests needed to resume or audit a run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal["created", "running", "waiting", "succeeded", "failed"]
PhaseName = Literal["extract", "analyze", "human_review", "rewrite", "verify"]
Severity = Literal["info", "warning", "error", "blocker"]
FindingScope = Literal["macro", "section", "flow", "rewrite", "verify"]
AssessmentStatus = Literal["correct", "missing", "improve"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    """Small, strict model base used only by the core bundle contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ArtifactRef(StrictModel):
    """A small reference to a file in the run bundle."""

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = "application/octet-stream"


class SourceSpan(StrictModel):
    """Stable source coordinates used as evidence by findings and diffs."""

    span_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Section(StrictModel):
    """A source section represented by spans rather than copied source text."""

    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    level: int = Field(ge=1, le=6)
    span_ids: list[str] = Field(default_factory=list)
    parent_id: str | None = None


class FigureOccurrence(StrictModel):
    """One source location at which an extracted figure appeared."""

    source_span_id: str | None = None
    section_id: str | None = None
    ordinal: int = Field(ge=0)
    location: dict[str, object] = Field(default_factory=dict)
    anchor_text: str = ""


class SourceFigure(StrictModel):
    """Persisted source figure with a stable reader-facing identifier."""

    figure_id: str = Field(pattern=r"^FIG-\d{3}$")
    asset_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    media_type: Literal["image/png", "image/jpeg"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    source_path: str = Field(min_length=1)
    caption: str = ""
    occurrences: list[FigureOccurrence] = Field(default_factory=list)


class Finding(StrictModel):
    finding_id: str = Field(min_length=1)
    scope: FindingScope
    severity: Severity
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    rubric_id: str = Field(min_length=1)
    section_id: str | None = None
    evidence_span_ids: list[str] = Field(default_factory=list)
    recommendation: str | None = None
    disposition: AssessmentStatus | None = None


class SectionAssessment(StrictModel):
    """Per-section rubric outcome used by the human section report."""

    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    requirement_id: str | None = None
    status: AssessmentStatus
    criterion_ids: list[str] = Field(default_factory=list)
    evidence_span_ids: list[str] = Field(default_factory=list)
    what_is_correct: str = ""
    what_is_missing: str = ""
    what_to_improve: str = ""


class Question(StrictModel):
    question_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    blocking: bool = True
    section_id: str | None = None
    suggestion: str | None = None
    answer: str | None = None


class FlowNode(StrictModel):
    node_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    node_type: Literal["section", "decision", "step"] = "section"


class FlowEdge(StrictModel):
    edge_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation: Literal["sequence", "reference", "branch", "escalation"] = "sequence"
    evidence_span_ids: list[str] = Field(default_factory=list)


class Decision(StrictModel):
    question_id: str = Field(min_length=1)
    question: str = ""
    suggestion: str | None = None
    answer: str = ""
    disposition: Literal["accept", "accept_suggestion", "defer", "reject"] = "accept"
    rationale: str | None = None


class Waiver(StrictModel):
    requirement_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class SourceDocument(StrictModel):
    """Canonical extracted source metadata; source text remains an artifact."""

    schema_version: Literal["core.source.v1", "core.source.v2"] = "core.source.v2"
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_name: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    parser: str = Field(min_length=1)
    structure_score: float = Field(ge=0.0, le=1.0)
    structure_mode: Literal["parser", "llm_recovery"]
    structure_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    spans: list[SourceSpan] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    figures: list[SourceFigure] = Field(default_factory=list)


class ReviewBundle(StrictModel):
    """Combined macro, section, and flow review output."""

    schema_version: Literal["core.review.v1"] = "core.review.v1"
    summary: str = Field(min_length=1)
    recipe_id: str = "heuristic-default"
    rubric_ids: list[str] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    section_assessments: list[SectionAssessment] = Field(default_factory=list)
    flow_nodes: list[FlowNode] = Field(default_factory=list)
    flow_edges: list[FlowEdge] = Field(default_factory=list)
    proposed_flow_nodes: list[FlowNode] = Field(default_factory=list)
    proposed_flow_edges: list[FlowEdge] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    process_applicable: bool = False
    mermaid: str = "flowchart TD\n"
    inferred_mermaid: str = "flowchart TD\n"
    proposed_mermaid: str = "flowchart TD\n"


class DecisionBundle(StrictModel):
    schema_version: Literal["core.decisions.v1"] = "core.decisions.v1"
    decisions: list[Decision] = Field(default_factory=list)
    steering: str = ""
    waivers: list[Waiver] = Field(default_factory=list)
    approve_rewrite: bool = False


class RewritePlanItem(StrictModel):
    """Deterministic rewrite scope for one approved source section."""

    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_span_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    figure_ids: list[str] = Field(default_factory=list)
    missing_required: bool = False
    requirement_id: str | None = None


class RewritePlan(StrictModel):
    """Application-owned rewrite instructions derived before any provider call."""

    schema_version: Literal["core.rewrite-plan.v1"] = "core.rewrite-plan.v1"
    recipe_id: str = Field(min_length=1)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    items: list[RewritePlanItem] = Field(default_factory=list)
    required_section_ids: list[str] = Field(default_factory=list)
    accepted_decision_ids: list[str] = Field(default_factory=list)
    deferred_decision_ids: list[str] = Field(default_factory=list)
    evidence_policy: str = "Use source spans and explicit accepted decisions only; preserve unknowns as open questions."


class SemanticNode(StrictModel):
    node_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    node_type: str = Field(min_length=1)
    properties: dict[str, object] = Field(default_factory=dict)
    provenance_span_ids: list[str] = Field(default_factory=list)


class SemanticEdge(StrictModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    edge_type: str = Field(min_length=1)
    properties: dict[str, object] = Field(default_factory=dict)
    provenance_span_ids: list[str] = Field(default_factory=list)


class DocumentIR(StrictModel):
    """Approved document representation shared by final renderers and exporters."""

    schema_version: Literal["core.ir.v1"] = "core.ir.v1"
    sections: list[Section] = Field(default_factory=list)
    nodes: list[SemanticNode] = Field(default_factory=list)
    edges: list[SemanticEdge] = Field(default_factory=list)
    markdown_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


# ``ReviewReport`` is retained as the readable name used by the CLI and tests;
# the canonical contract name is ``ReviewBundle``.
ReviewReport = ReviewBundle


class AuditReport(StrictModel):
    schema_version: Literal["core.audit.v1"] = "core.audit.v1"
    status: Literal["pass", "warn", "fail"]
    checks: dict[str, bool] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)


class RunRecord(StrictModel):
    """The only mutable run state; all large values remain external artifacts."""

    schema_version: Literal["core.run.v1"] = "core.run.v1"
    run_id: str = Field(min_length=1)
    status: RunStatus = "created"
    phase: PhaseName = "extract"
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe_digest: str = Field(default="0" * 64, pattern=r"^[0-9a-f]{64}$")
    configuration_digest: str = Field(default="0" * 64, pattern=r"^[0-9a-f]{64}$")
    source_name: str = Field(min_length=1)
    recipe: str = "enterprise_core"
    execution_mode: Literal["offline", "live"] = "offline"
    artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    unresolved_question_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
