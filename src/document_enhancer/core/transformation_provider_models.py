"""Strict result contracts for whole-document transformation provider calls.

The gateway response schemas used by :mod:`document_enhancer.core.providers` are intentionally
smaller than these application results.  Provider text is promoted into the Wave 1
``TransformationBundle`` and ``DraftSection`` contracts only after deterministic reference and
question-safety checks have run.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from document_enhancer.llm.callbacks import UsageMetadata

from .context_budget import ContextPreflight
from .models import (
    Finding,
    FlowEdge,
    FlowNode,
    Question,
)
from .transformation import (
    CoverageReport,
    DraftSection,
    DraftStatus,
    SourceDisposition,
    TransformationBundle,
    TransformationModel,
)

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

ProviderCallStatus = Literal[
    "success",
    "cache_hit",
    "failed",
    "fallback",
    "oversized",
    "hierarchical",
]


class ProviderCallManifest(TransformationModel):
    """Secret-safe evidence for one transformation call.

    This compact manifest deliberately contains no model credentials, prompt text, source text,
    template text, or image bytes.  The full gateway manifest remains available to the gateway
    caller; the transformation result exposes only the digest/usage/status subset needed by the
    core bundle.
    """

    schema_version: Literal["core.transformation-call-manifest.v1"] = (
        "core.transformation-call-manifest.v1"
    )
    operation: str = Field(min_length=1)
    status: ProviderCallStatus
    context_status: Literal["fit", "oversized", "hierarchical"]
    prompt_digest: str = Field(pattern=_SHA256_PATTERN)
    input_digests: list[str] = Field(default_factory=list)
    schema_digest: str = Field(pattern=_SHA256_PATTERN)
    response_digest: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    usage: UsageMetadata | None = None
    token_budget: int = Field(ge=1)
    output_budget: int = Field(ge=1)


class MacroAnalysis(TransformationModel):
    """Typed whole-document macro findings returned alongside the mapping."""

    schema_version: Literal["core.transformation-macro.v1"] = "core.transformation-macro.v1"
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)


class SectionAnalysis(TransformationModel):
    """Typed analysis for one selected template section."""

    schema_version: Literal["core.transformation-section-analysis.v1"] = (
        "core.transformation-section-analysis.v1"
    )
    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    requirement_id: str | None = None
    status: Literal["correct", "missing", "improve"]
    evidence_span_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    what_is_correct: str = ""
    what_is_missing: str = ""
    what_to_improve: str = ""


class ProcessAnalysis(TransformationModel):
    """Typed inferred/proposed process views for the mapping call."""

    schema_version: Literal["core.transformation-process-analysis.v1"] = (
        "core.transformation-process-analysis.v1"
    )
    applicable: bool = False
    summary: str = ""
    inferred_mermaid: str = "flowchart TD\n"
    proposed_mermaid: str = "flowchart TD\n"
    flow_nodes: list[FlowNode] = Field(default_factory=list)
    flow_edges: list[FlowEdge] = Field(default_factory=list)
    proposed_flow_nodes: list[FlowNode] = Field(default_factory=list)
    proposed_flow_edges: list[FlowEdge] = Field(default_factory=list)


class TemplatePlacement(TransformationModel):
    """The application-visible placement ledger for one template section."""

    schema_version: Literal["core.template-placement.v1"] = "core.template-placement.v1"
    template_section_id: str = Field(min_length=1)
    heading: str = Field(min_length=1)
    status: DraftStatus
    source_span_ids: list[str] = Field(default_factory=list)
    figure_ids: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    required: bool = True
    order: int = Field(default=0, ge=0)
    level: int = Field(default=2, ge=1, le=6)
    rationale: str = ""


class TransformationMapping(TransformationModel):
    """Complete promoted whole-document mapping and analysis result."""

    schema_version: Literal["core.transformation-mapping.v1"] = "core.transformation-mapping.v1"
    source_digest: str = Field(pattern=_SHA256_PATTERN)
    recipe_id: str = Field(min_length=1)
    bundle: TransformationBundle
    macro: MacroAnalysis
    sections: list[SectionAnalysis] = Field(default_factory=list)
    process: ProcessAnalysis
    contextual_questions: list[Question] = Field(default_factory=list)
    coverage: CoverageReport
    template_placement: list[TemplatePlacement] = Field(default_factory=list)
    mapping_digest: str = Field(pattern=_SHA256_PATTERN)
    preflight: ContextPreflight
    manifest: ProviderCallManifest

    @property
    def source_dispositions(self) -> list[SourceDisposition]:
        """Expose the canonical disposition ledger without duplicating its contract."""

        return self.bundle.source_dispositions

    @property
    def template_sections(self) -> list[DraftSection]:
        """Expose canonical template sections under the mapping vocabulary."""

        return self.bundle.template_sections

    @property
    def questions(self) -> list[Question]:
        return self.contextual_questions


WholeDocumentMapping = TransformationMapping
MappingResult = TransformationMapping


class DraftGenerationResult(TransformationModel):
    """Typed candidate draft sections promoted from a frozen mapping."""

    schema_version: Literal["core.transformation-draft-result.v1"] = (
        "core.transformation-draft-result.v1"
    )
    mapping_digest: str = Field(pattern=_SHA256_PATTERN)
    bundle: TransformationBundle
    sections: list[DraftSection] = Field(default_factory=list)
    coverage: CoverageReport
    preflight: ContextPreflight
    manifest: ProviderCallManifest

    @property
    def draft_sections(self) -> list[DraftSection]:
        return self.sections

    @property
    def document_markdown(self) -> str:
        """Render only through the deterministic Wave 1 renderer when requested."""

        return self.bundle.render_markdown()


DraftResult = DraftGenerationResult
TypedDraft = DraftGenerationResult


class FidelityCheck(TransformationModel):
    """One independent fidelity assertion and its provider/local explanation."""

    name: str = Field(min_length=1)
    passed: bool
    detail: str = ""


class DraftFidelityAudit(TransformationModel):
    """Independent draft-fidelity verdict with explicit rejection categories."""

    schema_version: Literal["core.transformation-fidelity-audit.v1"] = (
        "core.transformation-fidelity-audit.v1"
    )
    status: Literal["pass", "warn", "fail"]
    accepted: bool
    checks: list[FidelityCheck] = Field(default_factory=list)
    unsupported_additions: list[str] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)
    invalid_references: list[str] = Field(default_factory=list)
    unresolved_blocking_gaps: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    mapping_digest: str = Field(pattern=_SHA256_PATTERN)
    draft_digest: str = Field(pattern=_SHA256_PATTERN)
    preflight: ContextPreflight
    manifest: ProviderCallManifest

    @property
    def check_map(self) -> dict[str, bool]:
        return {item.name: item.passed for item in self.checks}


FidelityAuditResult = DraftFidelityAudit


__all__ = [
    "DraftFidelityAudit",
    "DraftGenerationResult",
    "DraftResult",
    "FidelityAuditResult",
    "FidelityCheck",
    "MacroAnalysis",
    "MappingResult",
    "ProcessAnalysis",
    "ProviderCallManifest",
    "SectionAnalysis",
    "TemplatePlacement",
    "TransformationMapping",
    "TypedDraft",
    "WholeDocumentMapping",
]
