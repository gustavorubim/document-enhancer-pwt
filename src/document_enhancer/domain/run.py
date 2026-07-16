"""Prompt, export, RAG, and run-manifest artifact contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from document_enhancer.domain.base import StrictModel, non_empty
from document_enhancer.domain.enums import (
    Authority,
    Layer,
    RagAnswerStatus,
    RelationshipType,
    ReviewStatus,
)
from document_enhancer.domain.ids import ensure_unique_ids, validate_identifier, validate_span_id
from document_enhancer.domain.ontology import EntityType, Provenance, Relationship


class PromptVariable(StrictModel):
    name: StrictStr
    value_type: StrictStr
    required: StrictBool = True
    default: object | None = None
    max_size: StrictInt | None = Field(default=None, gt=0)
    escaping: StrictStr = "delimited"

    @field_validator("name", "value_type", "escaping")
    @classmethod
    def validate_variable_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="prompt variable field")


class PromptSpec(StrictModel):
    prompt_id: StrictStr
    stage: StrictStr
    template_path: StrictStr
    shared_fragments: list[StrictStr] = Field(default_factory=list)
    model_route: StrictStr
    output_schema: StrictStr
    allowed_inputs: list[StrictStr] = Field(default_factory=list)
    optional_tools: list[StrictStr] = Field(default_factory=list)
    token_budget: StrictInt = Field(gt=0)
    output_budget: StrictInt = Field(gt=0)
    retry_policy: StrictStr
    safety_policy: StrictStr
    variables: list[PromptVariable] = Field(default_factory=list)

    @field_validator(
        "prompt_id",
        "stage",
        "template_path",
        "model_route",
        "output_schema",
        "retry_policy",
        "safety_policy",
    )
    @classmethod
    def validate_prompt_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="prompt specification field")

    @model_validator(mode="after")
    def validate_variables(self) -> PromptSpec:
        ensure_unique_ids(variable.name for variable in self.variables)
        if any(
            tool.lower() in {"shell", "network", "browser", "code_execution"}
            for tool in self.optional_tools
        ):
            raise ValueError(
                "document-analysis prompts cannot enable shell, network, browser, or code tools"
            )
        return self


class PromptPackManifest(StrictModel):
    pack_id: StrictStr
    version: StrictStr
    owner: StrictStr
    status: Literal["draft", "active", "deprecated"]
    compatible_application_versions: list[StrictStr] = Field(default_factory=list)
    compatible_schema_versions: list[StrictStr] = Field(default_factory=list)
    prompts: list[PromptSpec]
    required_references: list[StrictStr] = Field(default_factory=list)
    file_digests: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    composition_order: list[StrictStr] = Field(default_factory=list)

    @field_validator("pack_id", "version", "owner")
    @classmethod
    def validate_manifest_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="prompt manifest field")

    @model_validator(mode="after")
    def validate_prompt_ids(self) -> PromptPackManifest:
        ensure_unique_ids(prompt.prompt_id for prompt in self.prompts)
        return self


class PromptResolution(StrictModel):
    prompt_id: StrictStr
    pack_id: StrictStr
    pack_version: StrictStr
    template_digest: StrictStr
    shared_fragment_digests: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    resolved_reference_digests: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    variable_names: list[StrictStr] = Field(default_factory=list)
    composition_order: list[StrictStr] = Field(default_factory=list)
    rendered_prompt_digest: StrictStr
    output_schema: StrictStr
    resolved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExportChunk(StrictModel):
    chunk_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    version_id: StrictStr = Field(pattern=r"^(DOCV|VER)-[A-Z0-9-]+$")
    section_id: StrictStr | None = None
    section_path: list[StrictStr] = Field(default_factory=list)
    object_ids: list[StrictStr] = Field(default_factory=list)
    canonical_terms: list[StrictStr] = Field(default_factory=list)
    text: StrictStr
    source_span_ids: list[StrictStr] = Field(default_factory=list)
    markdown_anchor: StrictStr | None = None
    security_classification: StrictStr
    valid_from: str | None = None
    valid_to: str | None = None
    checksum: StrictStr
    ordinal: StrictInt = Field(ge=0)

    @field_validator("chunk_id")
    @classmethod
    def validate_chunk_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="chunk id")

    @field_validator("text", "security_classification", "checksum")
    @classmethod
    def validate_chunk_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="chunk field")

    @field_validator("source_span_ids")
    @classmethod
    def validate_chunk_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        return values


class ExportNode(StrictModel):
    id: StrictStr
    entity_type: EntityType
    canonical_name: StrictStr
    aliases: list[StrictStr] = Field(default_factory=list)
    attributes: dict[str, object] = Field(default_factory=dict)
    layer: Layer
    authority: Authority
    review_status: ReviewStatus
    provenance: Provenance


class ExportEdge(StrictModel):
    id: StrictStr
    source_id: StrictStr
    predicate: RelationshipType
    target_id: StrictStr
    layer: Layer
    authority: Authority
    review_status: ReviewStatus
    provenance: Provenance

    @classmethod
    def from_relationship(cls, relationship: Relationship) -> ExportEdge:
        if relationship.id is None:  # pragma: no cover - Relationship validates this invariant
            raise ValueError("cannot export a relationship without an id")
        return cls(
            id=relationship.id,
            source_id=relationship.source_id,
            predicate=relationship.predicate,
            target_id=relationship.target_id,
            layer=relationship.layer,
            authority=relationship.authority,
            review_status=relationship.review_status,
            provenance=relationship.provenance,
        )


class ExportBundleManifest(StrictModel):
    bundle_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    version_id: StrictStr = Field(pattern=r"^(DOCV|VER)-[A-Z0-9-]+$")
    schema_version: StrictStr
    generation_policy: StrictStr
    chunks_count: StrictInt = Field(ge=0)
    nodes_count: StrictInt = Field(ge=0)
    edges_count: StrictInt = Field(ge=0)
    artifact_digests: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    validation_passed: StrictBool
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExportBundle(StrictModel):
    manifest: ExportBundleManifest
    chunks: list[ExportChunk] = Field(default_factory=list)
    nodes: list[ExportNode] = Field(default_factory=list)
    edges: list[ExportEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> ExportBundle:
        actual = (len(self.chunks), len(self.nodes), len(self.edges))
        expected = (
            self.manifest.chunks_count,
            self.manifest.nodes_count,
            self.manifest.edges_count,
        )
        if actual != expected:
            raise ValueError(f"export manifest counts {expected} do not match bundle {actual}")
        ensure_unique_ids(chunk.chunk_id for chunk in self.chunks)
        ensure_unique_ids(node.id for node in self.nodes)
        ensure_unique_ids(edge.id for edge in self.edges)
        return self


class RagBuildManifest(StrictModel):
    rag_build_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    version_id: StrictStr = Field(pattern=r"^(DOCV|VER)-[A-Z0-9-]+$")
    database_schema_version: StrictStr
    migration_version: StrictStr
    input_digests: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    output_digests: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    row_counts: dict[StrictStr, StrictInt] = Field(default_factory=dict)
    fts_available: StrictBool
    integrity_check_passed: StrictBool
    foreign_key_check_passed: StrictBool
    graph_layer_counts: dict[StrictStr, StrictInt] = Field(default_factory=dict)
    embedding_model: StrictStr | None = None
    embedding_backend: StrictStr | None = None
    embedding_dimension: StrictInt | None = Field(default=None, gt=0)
    embedding_input_format_version: StrictStr | None = None
    vector_count: StrictInt = Field(default=0, ge=0)
    failed_count: StrictInt = Field(default=0, ge=0)
    skipped_count: StrictInt = Field(default=0, ge=0)
    promotion_status: Literal["not_started", "failed", "promoted"]
    validation_passed: StrictBool
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RagQuery(StrictModel):
    query_id: StrictStr
    question: StrictStr
    normalized_question: StrictStr | None = None
    session_id: StrictStr | None = None
    catalog_generation: StrictInt | None = Field(default=None, ge=0)
    embedding_profile: StrictStr
    top_k: StrictInt = Field(default=10, gt=0, le=1000)
    filters: dict[StrictStr, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("query_id")
    @classmethod
    def validate_query_id(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="query id")

    @field_validator("question", "normalized_question", "embedding_profile")
    @classmethod
    def validate_query_text(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else non_empty(value, field_name="query field")


class RagCitation(StrictModel):
    citation_id: StrictStr
    chunk_id: StrictStr
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    version_id: StrictStr = Field(pattern=r"^(DOCV|VER)-[A-Z0-9-]+$")
    section_id: StrictStr | None = None
    section_path: list[StrictStr] = Field(default_factory=list)
    source_span_ids: list[StrictStr] = Field(default_factory=list)
    markdown_anchor: StrictStr | None = None

    @field_validator("citation_id", "chunk_id")
    @classmethod
    def validate_citation_ids(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="citation identifier")

    @field_validator("source_span_ids")
    @classmethod
    def validate_citation_spans(cls, values: list[StrictStr]) -> list[StrictStr]:
        for value in values:
            validate_span_id(value)
        return values


class ClaimCitation(StrictModel):
    claim: StrictStr
    citation_ids: list[StrictStr]

    @field_validator("claim")
    @classmethod
    def validate_claim(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="claim")


class RagAnswer(StrictModel):
    answer_id: StrictStr
    query_id: StrictStr
    status: RagAnswerStatus
    answer_markdown: StrictStr
    citations: list[RagCitation] = Field(default_factory=list)
    claim_citations: list[ClaimCitation] = Field(default_factory=list)
    caveats: list[StrictStr] = Field(default_factory=list)
    unsupported_claims: list[StrictStr] = Field(default_factory=list)
    model_route: StrictStr | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("answer_id", "query_id")
    @classmethod
    def validate_answer_identifiers(cls, value: StrictStr) -> StrictStr:
        return validate_identifier(value, label="RAG answer identifier")

    @field_validator("answer_markdown")
    @classmethod
    def validate_answer_markdown(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="answer_markdown")

    @model_validator(mode="after")
    def validate_citation_references(self) -> RagAnswer:
        citation_ids = {citation.citation_id for citation in self.citations}
        for claim in self.claim_citations:
            missing = set(claim.citation_ids) - citation_ids
            if missing:
                raise ValueError(f"claim citations reference unknown handles: {sorted(missing)}")
        if self.status is RagAnswerStatus.ANSWERED and self.unsupported_claims:
            raise ValueError("answered RAG responses cannot contain unsupported_claims")
        return self


class ModelCallManifest(StrictModel):
    call_id: StrictStr
    stage: StrictStr
    provider: StrictStr
    model: StrictStr
    prompt_id: StrictStr
    prompt_version: StrictStr
    schema_name: StrictStr
    parameters: dict[StrictStr, object] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime | None = None
    retry_count: StrictInt = Field(default=0, ge=0)
    input_digest: StrictStr | None = None
    output_digest: StrictStr | None = None
    token_usage: dict[StrictStr, StrictInt] = Field(default_factory=dict)
    error: StrictStr | None = None


class StageManifest(StrictModel):
    stage: StrictStr
    status: Literal["pending", "running", "complete", "failed", "waiting"]
    cache_key: StrictStr | None = None
    artifact_digests: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    model_call_ids: list[StrictStr] = Field(default_factory=list)
    completed_at: datetime | None = None


class RunManifest(StrictModel):
    run_id: StrictStr
    parent_run_id: StrictStr | None = None
    status: Literal["created", "running", "waiting", "passed", "failed"]
    current_stage: StrictStr
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_path: StrictStr
    source_media_type: StrictStr
    source_size_bytes: StrictInt = Field(ge=0)
    source_sha256: StrictStr
    extraction_warnings: list[StrictStr] = Field(default_factory=list)
    structure_mode: Literal["auto", "parser", "llm"]
    parser_outline_digest: StrictStr | None = None
    selected_outline_digest: StrictStr | None = None
    structure_quality: object | None = None
    structure_recovery_validation: object | None = None
    reference_pack_id: StrictStr | None = None
    reference_pack_version: StrictStr | None = None
    reference_pack_digest: StrictStr | None = None
    prompt_pack_id: StrictStr | None = None
    prompt_pack_version: StrictStr | None = None
    prompt_resolutions: list[PromptResolution] = Field(default_factory=list)
    application_version: StrictStr
    python_version: StrictStr
    platform: StrictStr
    schema_versions: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    model_calls: list[ModelCallManifest] = Field(default_factory=list)
    stages: list[StageManifest] = Field(default_factory=list)
    completed_stages: list[StrictStr] = Field(default_factory=list)
    failures: list[StrictStr] = Field(default_factory=list)
    revision_count: StrictInt = Field(default=0, ge=0)
    answer_digest: StrictStr | None = None
    steering_digest: StrictStr | None = None
    waiver_digest: StrictStr | None = None
    checklist_digest: StrictStr | None = None
    embedding_profile: dict[StrictStr, object] | None = None
    sqlite_metadata: dict[StrictStr, object] | None = None
    data_handling_mode: StrictStr
    external_tracing_enabled: StrictBool = False

    @field_validator(
        "run_id",
        "current_stage",
        "source_path",
        "source_media_type",
        "source_sha256",
        "application_version",
        "python_version",
        "platform",
        "data_handling_mode",
    )
    @classmethod
    def validate_run_text(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="run manifest field")

    @model_validator(mode="after")
    def validate_call_ids(self) -> RunManifest:
        ensure_unique_ids(call.call_id for call in self.model_calls)
        ensure_unique_ids(stage.stage for stage in self.stages)
        return self


__all__ = [
    "ClaimCitation",
    "ExportBundleManifest",
    "ExportBundle",
    "ExportChunk",
    "ExportEdge",
    "ExportNode",
    "ModelCallManifest",
    "PromptPackManifest",
    "PromptResolution",
    "PromptSpec",
    "PromptVariable",
    "RagAnswer",
    "RagBuildManifest",
    "RagCitation",
    "RagQuery",
    "RunManifest",
    "StageManifest",
]
