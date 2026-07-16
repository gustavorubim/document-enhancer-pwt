"""Immutable runtime records produced by the analysis-specialist lane."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from document_enhancer.domain.analysis import (
    AnalysisReport,
    DiscoveryAnalysis,
    Finding,
    FindingSet,
    MacroAnalysis,
    RagReadinessAnalysis,
    SectionAnalysis,
)
from document_enhancer.domain.enums import DocumentType, SpanDisposition
from document_enhancer.domain.run import PromptResolution
from document_enhancer.domain.source import NormalizedDocument
from document_enhancer.llm.models import CallManifest


class FrozenModel(BaseModel):
    """Strict, immutable base for orchestration records that are safe to persist."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
        use_enum_values=False,
    )


class MetadataEntry(FrozenModel):
    key: StrictStr
    value: StrictStr

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: StrictStr) -> StrictStr:
        if not value.strip():
            raise ValueError("metadata key must not be blank")
        return value


class AnalysisRequest(FrozenModel):
    """Validated source and governed inputs shared by all four specialists."""

    document: NormalizedDocument
    document_type: DocumentType
    metadata: tuple[MetadataEntry, ...] = ()
    reviewer_inputs: StrictStr = ""
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, values: tuple[MetadataEntry, ...]) -> tuple[MetadataEntry, ...]:
        keys = [item.key for item in values]
        if len(set(keys)) != len(keys):
            raise ValueError("analysis metadata keys must be unique")
        if keys != sorted(keys):
            raise ValueError("analysis metadata must be sorted by key")
        return values

    @property
    def document_metadata(self) -> dict[str, str]:
        return {item.key: item.value for item in self.metadata}

    @property
    def document_id(self) -> str:
        return self.document.raw.document_id

    @property
    def source_digest(self) -> str:
        return self.document.raw.source_digest

    @property
    def authoritative_span_ids(self) -> tuple[str, ...]:
        return tuple(
            block.span_id for block in self.document.raw.blocks if block.span_id is not None
        )


class PromptCallRecord(FrozenModel):
    """Exact prompt resolution and model-call manifest for one bounded call."""

    resolution: PromptResolution
    manifest: CallManifest


AnalysisArtifact = Annotated[
    MacroAnalysis | SectionAnalysis | DiscoveryAnalysis | RagReadinessAnalysis,
    Field(discriminator="analysis_type"),
]


class AnalysisBranchResult(FrozenModel):
    specialist: Literal[
        "macro_reviewer",
        "section_mapper",
        "process_methodology_discoverer",
        "rag_readiness_reviewer",
    ]
    analysis: AnalysisArtifact
    markdown: StrictStr
    call: PromptCallRecord


class SourceSpanDisposition(FrozenModel):
    span_id: StrictStr
    target_section_ids: tuple[StrictStr, ...] = ()
    disposition: SpanDisposition
    rationale: StrictStr


class SourceDispositionMap(FrozenModel):
    document_id: StrictStr
    source_digest: StrictStr
    authoritative_span_ids: tuple[StrictStr, ...]
    dispositions: tuple[SourceSpanDisposition, ...]


AnalysisStageName = Literal[
    "macro_reviewer",
    "section_mapper",
    "process_methodology_discoverer",
    "rag_readiness_reviewer",
    "finding_synthesizer",
]


class AnalysisStageRecord(FrozenModel):
    """Safe, independently persistable outcome for one required analysis stage."""

    document_id: StrictStr
    source_digest: StrictStr
    stage: AnalysisStageName
    status: Literal["succeeded", "failed", "quarantined"]
    branch: AnalysisBranchResult | None = None
    disposition_map: SourceDispositionMap | None = None
    error_type: StrictStr | None = None
    error_message: StrictStr | None = None
    retry_action: StrictStr | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> AnalysisStageRecord:
        if self.disposition_map is not None and self.stage != "section_mapper":
            raise ValueError("only the section branch can contain a source disposition map")
        if self.status == "succeeded":
            if self.branch is None or self.branch.specialist != self.stage:
                raise ValueError("successful branch stage record requires its matching branch")
            if self.stage == "section_mapper" and self.disposition_map is None:
                raise ValueError("successful section branch requires its source disposition map")
            if any(
                value is not None
                for value in (self.error_type, self.error_message, self.retry_action)
            ):
                raise ValueError("successful branch stage record cannot contain failure metadata")
            return self
        if self.error_type is None or self.error_message is None or self.retry_action is None:
            raise ValueError("unresolved analysis stage requires safe failure and retry metadata")
        if self.status == "failed" and self.branch is not None:
            raise ValueError("failed analysis stage cannot contain an unvalidated branch")
        if self.branch is not None and self.branch.specialist != self.stage:
            raise ValueError("quarantined branch stage record has the wrong specialist")
        return self


class DeterministicLintResult(FrozenModel):
    check_ids: tuple[StrictStr, ...]
    findings: tuple[Finding, ...]


class FindingConflict(FrozenModel):
    conflict_id: StrictStr
    source_analysis_ids: tuple[StrictStr, ...]
    finding_ids: tuple[StrictStr, ...]
    evidence_signature: StrictStr
    differing_fields: tuple[StrictStr, ...]


class RankedFinding(FrozenModel):
    rank: StrictInt = Field(ge=1)
    priority: Literal["blocking", "high", "medium", "low", "informational"]
    finding: Finding


class SynthesisResult(FrozenModel):
    model_report: AnalysisReport
    finding_set: FindingSet
    ranked_findings: tuple[RankedFinding, ...]
    conflicts: tuple[FindingConflict, ...]
    markdown: StrictStr
    call: PromptCallRecord


class AnalysisRunResult(FrozenModel):
    """Complete deterministic fan-out/fan-in result in stable specialist order."""

    report: AnalysisReport
    branches: tuple[AnalysisBranchResult, ...]
    disposition_map: SourceDispositionMap
    rag_lint: DeterministicLintResult
    synthesis: SynthesisResult
    call_count: StrictInt = Field(ge=0)
    complete: StrictBool = True

    @property
    def call_records(self) -> tuple[PromptCallRecord, ...]:
        return tuple(branch.call for branch in self.branches) + (self.synthesis.call,)


__all__ = [
    "AnalysisArtifact",
    "AnalysisBranchResult",
    "AnalysisRequest",
    "AnalysisRunResult",
    "AnalysisStageName",
    "AnalysisStageRecord",
    "DeterministicLintResult",
    "FindingConflict",
    "FrozenModel",
    "MetadataEntry",
    "PromptCallRecord",
    "RankedFinding",
    "SourceDispositionMap",
    "SourceSpanDisposition",
    "SpanDisposition",
    "SynthesisResult",
]
