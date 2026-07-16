"""Structure, analysis, finding, and evidence contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.enums import (
    DocumentType,
    FindingSeverity,
    FindingType,
    StructureDecision,
    StructureDisposition,
)
from document_enhancer.domain.ids import ensure_unique_ids, validate_identifier, validate_span_id
from document_enhancer.domain.ontology import Relationship, SemanticObject
from document_enhancer.domain.source import RawDocument


class EvidenceQuote(StrictModel):
    span_id: StrictStr
    quote: StrictStr
    start_offset: StrictInt | None = Field(default=None, ge=0)
    end_offset: StrictInt | None = Field(default=None, ge=0)

    @field_validator("span_id")
    @classmethod
    def validate_span(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)

    @field_validator("quote")
    @classmethod
    def validate_quote(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="evidence quote")

    @model_validator(mode="after")
    def validate_offsets(self) -> EvidenceQuote:
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("evidence end_offset must not precede start_offset")
        return self


class StructureQuality(StrictModel):
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    source_digest: StrictStr
    heading_density: StrictFloat = Field(ge=0.0, le=1.0)
    heading_style_consistency: StrictFloat = Field(ge=0.0, le=1.0)
    numbering_continuity: StrictFloat = Field(ge=0.0, le=1.0)
    table_layout_signal: StrictFloat = Field(ge=0.0, le=1.0)
    repeated_furniture_count: StrictInt = Field(ge=0)
    block_length_anomaly_count: StrictInt = Field(ge=0)
    toc_mismatch_count: StrictInt = Field(ge=0)
    orphan_block_count: StrictInt = Field(ge=0)
    parser_warnings: list[StrictStr] = Field(default_factory=list)
    quality_score: StrictFloat = Field(ge=0.0, le=1.0)
    needs_recovery: StrictBool


class BoundaryRegion(StrictModel):
    start_span_id: StrictStr
    end_span_id: StrictStr
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    rationale: StrictStr | None = None

    @field_validator("start_span_id", "end_span_id")
    @classmethod
    def validate_spans(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)


class StructureScan(StrictModel):
    scan_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    source_digest: StrictStr
    parser_outline_digest: StrictStr
    decision: StructureDecision
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    boundary_regions: list[BoundaryRegion] = Field(default_factory=list)
    evidence_span_ids: list[StrictStr] = Field(default_factory=list)
    ambiguities: list[StrictStr] = Field(default_factory=list)
    model: StrictStr
    prompt_id: StrictStr
    prompt_digest: StrictStr
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("scan_id", "model", "prompt_id", "prompt_digest")
    @classmethod
    def validate_strings(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="structure scan field")

    @field_validator("evidence_span_ids")
    @classmethod
    def validate_evidence_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        return values


class RecoveredSection(StrictModel):
    section_id: StrictStr = Field(pattern=r"^(SEC|PROV-SEC)-[A-Z0-9-]+$")
    label: StrictStr
    level: StrictInt = Field(ge=1, le=9)
    start_span_id: StrictStr
    end_span_id: StrictStr
    source_heading_text: StrictStr | None = None
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    rationale: StrictStr | None = None
    inferred_label: StrictBool = False

    @field_validator("start_span_id", "end_span_id")
    @classmethod
    def validate_spans(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="recovered section label")


class BlockDisposition(StrictModel):
    span_id: StrictStr
    disposition: StructureDisposition
    section_id: StrictStr | None = Field(default=None, pattern=r"^(SEC|PROV-SEC)-[A-Z0-9-]+$")
    source_text_digest: StrictStr
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    rationale: StrictStr | None = None

    @field_validator("span_id")
    @classmethod
    def validate_span(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)


class StructureAssociation(StrictModel):
    span_id: StrictStr
    section_id: StrictStr
    association: Literal["table", "figure", "formula", "caption", "nearby"]

    @field_validator("span_id")
    @classmethod
    def validate_association_span(cls, value: StrictStr) -> StrictStr:
        return validate_span_id(value)


class BoundaryAlternative(StrictModel):
    alternative_id: StrictStr
    sections: list[RecoveredSection]
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    reason: StrictStr


class StructureDisagreement(StrictModel):
    span_ids: list[StrictStr]
    parser_label: StrictStr | None = None
    model_label: StrictStr | None = None
    resolution: StrictStr | None = None
    requires_review: StrictBool = True

    @field_validator("span_ids")
    @classmethod
    def validate_disagreement_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        return values


class StructureValidation(StrictModel):
    passed: StrictBool
    covered_span_ids: list[StrictStr] = Field(default_factory=list)
    errors: list[StrictStr] = Field(default_factory=list)


class StructureRecoveryProposal(StrictModel):
    recovery_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    source_digest: StrictStr
    proposed_document_type: DocumentType | None = None
    proposed_title: StrictStr | None = None
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    sections: list[RecoveredSection]
    dispositions: list[BlockDisposition]
    associations: list[StructureAssociation] = Field(default_factory=list)
    boundary_alternatives: list[BoundaryAlternative] = Field(default_factory=list)
    disagreements: list[StructureDisagreement] = Field(default_factory=list)
    validation: StructureValidation | None = None
    model: StrictStr
    prompt_id: StrictStr

    def validate_against(self, raw: RawDocument) -> StructureValidation:
        """Validate exact raw-span coverage/order without rewriting source text."""

        expected = [block.span_id for block in raw.blocks]
        actual = [item.span_id for item in self.dispositions]
        errors: list[str] = []
        if actual != expected:
            errors.append("dispositions must cover every raw span exactly once in source order")
        if len(set(actual)) != len(actual):
            errors.append("dispositions contain duplicate span IDs")
        by_id = {block.span_id: block for block in raw.blocks}
        for item in self.dispositions:
            block = by_id.get(item.span_id)
            if block is None:
                errors.append(f"unknown span {item.span_id}")
            elif block.text_digest != item.source_text_digest:
                errors.append(f"source text digest mismatch for {item.span_id}")
        known_sections = {section.section_id for section in self.sections}
        for item in self.dispositions:
            if item.section_id is not None and item.section_id not in known_sections:
                errors.append(
                    f"disposition {item.span_id} references unknown section {item.section_id}"
                )
        result = StructureValidation(
            passed=not errors,
            covered_span_ids=actual,
            errors=errors,
        )
        object.__setattr__(self, "validation", result)
        return result


class Finding(StrictModel):
    finding_id: StrictStr
    category: StrictStr
    severity: FindingSeverity
    finding_type: FindingType
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    target_template_section: StrictStr | None = None
    target_object_id: StrictStr | None = None
    requirement_id: StrictStr | None = None
    impact: StrictStr
    proposed_disposition: StrictStr
    requires_human_answer: StrictBool
    blocking: StrictBool = False

    @field_validator("finding_id")
    @classmethod
    def validate_finding_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="finding id")

    @field_validator("category", "impact", "proposed_disposition")
    @classmethod
    def validate_finding_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="finding field")


class RubricScore(StrictModel):
    dimension: StrictStr
    score: StrictInt = Field(ge=0, le=4)
    weight: StrictFloat = Field(gt=0.0, le=100.0)
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    explanation: StrictStr


class AnalysisBase(StrictModel):
    analysis_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    version_id: StrictStr | None = Field(default=None, pattern=r"^(DOCV|VER)-[A-Z0-9-]+$")
    source_digest: StrictStr
    findings: list[Finding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model_route: StrictStr | None = None
    prompt_id: StrictStr | None = None


class MacroAnalysis(AnalysisBase):
    analysis_type: Literal["macro"] = "macro"
    candidate_document_type: DocumentType | None = None
    candidate_confidence: StrictFloat | None = Field(default=None, ge=0.0, le=1.0)
    purpose: StrictStr | None = None
    audience: StrictStr | None = None
    owner_id: StrictStr | None = None
    authority: StrictStr | None = None
    lifecycle_status: StrictStr | None = None
    scope: StrictStr | None = None
    template_fit: StrictStr | None = None
    alternative_templates: list[StrictStr] = Field(default_factory=list)
    rubric_scores: list[RubricScore] = Field(default_factory=list)


class SectionMapping(StrictModel):
    source_span_ids: list[StrictStr]
    target_section_id: StrictStr | None = None
    disposition: StrictStr
    rationale: StrictStr | None = None

    @field_validator("source_span_ids")
    @classmethod
    def validate_mapping_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        return values


class SectionAnalysis(AnalysisBase):
    analysis_type: Literal["sections"] = "sections"
    mappings: list[SectionMapping] = Field(default_factory=list)
    missing_target_sections: list[StrictStr] = Field(default_factory=list)
    contradictions: list[StrictStr] = Field(default_factory=list)
    repeated_content: list[StrictStr] = Field(default_factory=list)
    terminology_drift: list[StrictStr] = Field(default_factory=list)


class DiscoveryAnalysis(AnalysisBase):
    analysis_type: Literal["discovery"] = "discovery"
    objects: list[SemanticObject] = Field(default_factory=list)
    candidate_relationships: list[Relationship] = Field(default_factory=list)
    orphan_controls: list[StrictStr] = Field(default_factory=list)
    unmitigated_risks: list[StrictStr] = Field(default_factory=list)
    incomplete_rules: list[StrictStr] = Field(default_factory=list)
    mermaid: StrictStr | None = None


class ChunkCandidate(StrictModel):
    chunk_key: StrictStr
    section_id: StrictStr | None = None
    object_ids: list[StrictStr] = Field(default_factory=list)
    source_span_ids: list[StrictStr] = Field(default_factory=list)
    rationale: StrictStr


class RagReadinessAnalysis(AnalysisBase):
    analysis_type: Literal["rag_readiness"] = "rag_readiness"
    undefined_acronyms: list[StrictStr] = Field(default_factory=list)
    vague_references: list[StrictStr] = Field(default_factory=list)
    missing_ids: list[StrictStr] = Field(default_factory=list)
    missing_provenance: list[StrictStr] = Field(default_factory=list)
    oversized_sections: list[StrictStr] = Field(default_factory=list)
    mixed_topic_spans: list[StrictStr] = Field(default_factory=list)
    candidate_chunks: list[ChunkCandidate] = Field(default_factory=list)
    candidate_objects: list[StrictStr] = Field(default_factory=list)


class AnalysisReport(StrictModel):
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    source_digest: StrictStr
    analyses: list[MacroAnalysis | SectionAnalysis | DiscoveryAnalysis | RagReadinessAnalysis]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_analysis_ids(self) -> AnalysisReport:
        ensure_unique_ids(analysis.analysis_id for analysis in self.analyses)
        return self


class FindingSet(StrictModel):
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    source_digest: StrictStr
    findings: list[Finding]
    generated_from_analysis_ids: list[StrictStr] = Field(default_factory=list)
    blocking_count: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_count(self) -> FindingSet:
        actual = sum(finding.blocking for finding in self.findings)
        if actual != self.blocking_count:
            raise ValueError(f"blocking_count={self.blocking_count} does not match {actual}")
        ensure_unique_ids(finding.finding_id for finding in self.findings)
        return self


__all__ = [
    "AnalysisBase",
    "AnalysisReport",
    "BoundaryAlternative",
    "BoundaryRegion",
    "BlockDisposition",
    "ChunkCandidate",
    "DiscoveryAnalysis",
    "EvidenceQuote",
    "Finding",
    "FindingSet",
    "MacroAnalysis",
    "RagReadinessAnalysis",
    "RecoveredSection",
    "RubricScore",
    "SectionAnalysis",
    "SectionMapping",
    "StructureDisagreement",
    "StructureQuality",
    "StructureRecoveryProposal",
    "StructureScan",
    "StructureValidation",
]
