"""The bounded enterprise ontology and relationship contract."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Annotated, Literal

from pydantic import (
    AliasChoices,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from document_enhancer.domain.base import JsonValue, StrictModel, non_empty
from document_enhancer.domain.enums import (
    Authority,
    DocumentType,
    EntityType,
    GraphLayer,
    Layer,
    ProvenanceOrigin,
    RelationshipType,
    ReviewStatus,
    VersionStatus,
)
from document_enhancer.domain.ids import (
    ensure_unique_ids,
    validate_entity_id,
    validate_identifier,
    validate_sha256,
)
from document_enhancer.domain.provenance import Provenance, TemporalValidity


def _non_empty_list(values: list[StrictStr]) -> list[StrictStr]:
    for value in values:
        non_empty(value, field_name="list item")
    return values


class Entity(StrictModel):
    """Common fields present on every graph node."""

    id: StrictStr
    entity_type: EntityType
    name: StrictStr
    aliases: list[StrictStr] = Field(default_factory=list)
    provenance: Provenance
    authority: Authority | None = None
    layer: Layer | None = None
    review_status: ReviewStatus | None = None
    validity: TemporalValidity | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    provisional: StrictBool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="name")

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, value: list[StrictStr]) -> list[StrictStr]:
        return _non_empty_list(value)

    @model_validator(mode="after")
    def validate_identity_and_authority(self) -> Entity:
        if self.validity is None and (self.valid_from is not None or self.valid_to is not None):
            object.__setattr__(
                self,
                "validity",
                TemporalValidity(valid_from=self.valid_from, valid_to=self.valid_to),
            )
        elif self.validity is not None:
            if self.valid_from is not None and self.validity.valid_from != self.valid_from:
                raise ValueError("valid_from conflicts with validity.valid_from")
            if self.valid_to is not None and self.validity.valid_to != self.valid_to:
                raise ValueError("valid_to conflicts with validity.valid_to")
        validate_entity_id(self.id, self.entity_type)
        if self.id.startswith("PROV-") and not self.provisional:
            object.__setattr__(self, "provisional", True)
        if self.authority is None:
            object.__setattr__(self, "authority", self.provenance.authority)
        if self.layer is None:
            object.__setattr__(self, "layer", self.provenance.layer)
        if self.review_status is None:
            object.__setattr__(self, "review_status", self.provenance.review_status)
        if self.authority is not self.provenance.authority:
            raise ValueError("entity authority must match provenance.authority")
        if self.layer is not self.provenance.layer:
            raise ValueError("entity layer must match provenance.layer")
        if self.review_status is not self.provenance.review_status:
            raise ValueError("entity review_status must match provenance.review_status")
        _validate_layer_authority(self.layer, self.authority)
        return self

    @property
    def canonical_name(self) -> str:
        return self.name


class DocumentIdentity(Entity):
    entity_type: Literal[EntityType.DOCUMENT_IDENTITY] = EntityType.DOCUMENT_IDENTITY
    document_type: DocumentType
    namespace: StrictStr = "default"
    source_digest: StrictStr | None = None

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="namespace")

    @field_validator("source_digest")
    @classmethod
    def validate_source_digest(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else validate_sha256(value)


class DocumentVersion(Entity):
    entity_type: Literal[EntityType.DOCUMENT_VERSION] = EntityType.DOCUMENT_VERSION
    document_id: StrictStr = Field(pattern=r"^DOC-[A-Z0-9-]+$")
    version: StrictStr
    status: VersionStatus
    source_digest: StrictStr | None = None
    enhanced_digest: StrictStr | None = None
    confidentiality: StrictStr = "internal"
    effective_dates: TemporalValidity | None = None

    @field_validator("version", "confidentiality")
    @classmethod
    def validate_version_strings(cls, value: StrictStr) -> StrictStr:
        return non_empty(value, field_name="version field")

    @field_validator("source_digest", "enhanced_digest")
    @classmethod
    def validate_version_digests(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else validate_sha256(value)


class Section(Entity):
    entity_type: Literal[EntityType.SECTION] = EntityType.SECTION
    order: StrictInt = Field(ge=0)
    parent_section_id: StrictStr | None = Field(
        default=None, pattern=r"^(SEC|PROV-SEC)-[A-Z0-9-]+$"
    )
    anchor: StrictStr | None = None


class Statement(Entity):
    entity_type: Literal[EntityType.STATEMENT] = EntityType.STATEMENT
    text: StrictStr | None = None


class Table(Entity):
    entity_type: Literal[EntityType.TABLE] = EntityType.TABLE
    title: StrictStr | None = None
    headers: list[StrictStr] = Field(default_factory=list)
    source_span_ids: list[StrictStr] = Field(default_factory=list)


class Figure(Entity):
    entity_type: Literal[EntityType.FIGURE] = EntityType.FIGURE
    caption: StrictStr | None = None
    asset_digest: StrictStr | None = None

    @field_validator("asset_digest")
    @classmethod
    def validate_asset_digest(cls, value: StrictStr | None) -> StrictStr | None:
        return None if value is None else validate_sha256(value)


class Process(Entity):
    entity_type: Literal[EntityType.PROCESS] = EntityType.PROCESS


class Methodology(Entity):
    entity_type: Literal[EntityType.METHODOLOGY] = EntityType.METHODOLOGY


class Activity(Entity):
    entity_type: Literal[EntityType.ACTIVITY] = EntityType.ACTIVITY


class Trigger(Entity):
    entity_type: Literal[EntityType.TRIGGER] = EntityType.TRIGGER


class Requirement(Entity):
    entity_type: Literal[EntityType.REQUIREMENT] = EntityType.REQUIREMENT


class Risk(Entity):
    entity_type: Literal[EntityType.RISK] = EntityType.RISK


class Policy(Entity):
    entity_type: Literal[EntityType.POLICY] = EntityType.POLICY


class Standard(Entity):
    entity_type: Literal[EntityType.STANDARD] = EntityType.STANDARD


class Regulation(Entity):
    entity_type: Literal[EntityType.REGULATION] = EntityType.REGULATION


class Approval(Entity):
    entity_type: Literal[EntityType.APPROVAL] = EntityType.APPROVAL


class Record(Entity):
    entity_type: Literal[EntityType.RECORD] = EntityType.RECORD


class Role(Entity):
    entity_type: Literal[EntityType.ROLE] = EntityType.ROLE


class Organization(Entity):
    entity_type: Literal[EntityType.ORGANIZATION] = EntityType.ORGANIZATION


class EscalationPath(Entity):
    entity_type: Literal[EntityType.ESCALATION_PATH] = EntityType.ESCALATION_PATH


class System(Entity):
    entity_type: Literal[EntityType.SYSTEM] = EntityType.SYSTEM


class DataAsset(Entity):
    entity_type: Literal[EntityType.DATA_ASSET] = EntityType.DATA_ASSET


class DataElement(Entity):
    entity_type: Literal[EntityType.DATA_ELEMENT] = EntityType.DATA_ELEMENT


class Input(Entity):
    entity_type: Literal[EntityType.INPUT] = EntityType.INPUT


class Output(Entity):
    entity_type: Literal[EntityType.OUTPUT] = EntityType.OUTPUT


class Model(Entity):
    entity_type: Literal[EntityType.MODEL] = EntityType.MODEL


class Parameter(Entity):
    entity_type: Literal[EntityType.PARAMETER] = EntityType.PARAMETER


class Metric(Entity):
    entity_type: Literal[EntityType.METRIC] = EntityType.METRIC


class Threshold(Entity):
    entity_type: Literal[EntityType.THRESHOLD] = EntityType.THRESHOLD


class Formula(Entity):
    entity_type: Literal[EntityType.FORMULA] = EntityType.FORMULA


class ServiceLevel(Entity):
    entity_type: Literal[EntityType.SERVICE_LEVEL] = EntityType.SERVICE_LEVEL


class Assumption(Entity):
    entity_type: Literal[EntityType.ASSUMPTION] = EntityType.ASSUMPTION
    statement: StrictStr | None = None
    applies_to_ids: list[StrictStr] = Field(default_factory=list)
    risk_if_violated: StrictStr | None = None
    validation_method: StrictStr | None = None
    owner_id: StrictStr | None = None
    review_frequency: StrictStr | None = None


class Limitation(Entity):
    entity_type: Literal[EntityType.LIMITATION] = EntityType.LIMITATION
    statement: StrictStr | None = None
    affected_ids: list[StrictStr] = Field(default_factory=list)
    impact: StrictStr | None = None
    mitigation: StrictStr | None = None
    disclosure_requirements: StrictStr | None = None


class Exception(Entity):
    entity_type: Literal[EntityType.EXCEPTION] = EntityType.EXCEPTION
    applies_to_ids: list[StrictStr] = Field(default_factory=list)
    authorized_role_id: StrictStr | None = None
    justification: StrictStr | None = None
    evidence_ids: list[StrictStr] = Field(default_factory=list)
    approval_required: StrictBool | None = None
    review_or_expiry: TemporalValidity | None = None


class Dependency(Entity):
    entity_type: Literal[EntityType.DEPENDENCY] = EntityType.DEPENDENCY
    dependency_type: StrictStr | None = None
    required_object_id: StrictStr | None = None
    timing: StrictStr | None = None
    provider_id: StrictStr | None = None
    readiness_condition: StrictStr | None = None
    failure_impact: StrictStr | None = None
    fallback: StrictStr | None = None
    escalation_id: StrictStr | None = None


class Precondition(Entity):
    entity_type: Literal[EntityType.PRECONDITION] = EntityType.PRECONDITION
    condition: StrictStr | None = None


class CompletionCondition(Entity):
    entity_type: Literal[EntityType.COMPLETION_CONDITION] = EntityType.COMPLETION_CONDITION
    condition: StrictStr | None = None


class GlossaryTerm(Entity):
    entity_type: Literal[EntityType.GLOSSARY_TERM] = EntityType.GLOSSARY_TERM
    definition: StrictStr | None = None
    preferred_term: StrictStr | None = None


class ProcessStep(Entity):
    entity_type: Literal[EntityType.PROCESS_STEP] = EntityType.PROCESS_STEP
    action: StrictStr | None = None
    performer_ids: list[StrictStr] = Field(default_factory=list)
    trigger_ids: list[StrictStr] = Field(default_factory=list)
    precondition_ids: list[StrictStr] = Field(default_factory=list)
    input_ids: list[StrictStr] = Field(default_factory=list)
    output_ids: list[StrictStr] = Field(default_factory=list)
    system_ids: list[StrictStr] = Field(default_factory=list)
    data_asset_ids: list[StrictStr] = Field(default_factory=list)
    calculator_ids: list[StrictStr] = Field(default_factory=list)
    control_ids: list[StrictStr] = Field(default_factory=list)
    decision_ids: list[StrictStr] = Field(default_factory=list)
    exception_ids: list[StrictStr] = Field(default_factory=list)
    completion_condition_id: StrictStr | None = None
    next_step_id: StrictStr | None = None
    failure_path_id: StrictStr | None = None


class MethodologyStep(Entity):
    entity_type: Literal[EntityType.METHODOLOGY_STEP] = EntityType.METHODOLOGY_STEP
    objective: StrictStr | None = None
    input_ids: list[StrictStr] = Field(default_factory=list)
    transformation: StrictStr | None = None
    formula_ids: list[StrictStr] = Field(default_factory=list)
    parameter_ids: list[StrictStr] = Field(default_factory=list)
    assumption_ids: list[StrictStr] = Field(default_factory=list)
    output_ids: list[StrictStr] = Field(default_factory=list)
    validation_checks: list[StrictStr] = Field(default_factory=list)
    failure_conditions: list[StrictStr] = Field(default_factory=list)
    limitation_ids: list[StrictStr] = Field(default_factory=list)
    implementation_reference: StrictStr | None = None


class Control(Entity):
    entity_type: Literal[EntityType.CONTROL] = EntityType.CONTROL
    objective: StrictStr | None = None
    risk_ids: list[StrictStr] = Field(default_factory=list)
    execution_frequency: StrictStr | None = None
    performer_id: StrictStr | None = None
    owner_id: StrictStr | None = None
    procedure_or_step_id: StrictStr | None = None
    evidence_ids: list[StrictStr] = Field(default_factory=list)
    failure_response: StrictStr | None = None
    escalation_id: StrictStr | None = None


class Rule(Entity):
    entity_type: Literal[EntityType.RULE] = EntityType.RULE
    condition: StrictStr | None = None
    metric_id: StrictStr | None = None
    data_element_id: StrictStr | None = None
    operator: StrictStr | None = None
    threshold_id: StrictStr | None = None
    value: StrictStr | None = None
    unit: StrictStr | None = None
    evaluation_period: StrictStr | None = None
    outcome: StrictStr | None = None
    escalation_id: StrictStr | None = None
    override_authority_id: StrictStr | None = None
    required_evidence_ids: list[StrictStr] = Field(default_factory=list)


class Decision(Entity):
    entity_type: Literal[EntityType.DECISION] = EntityType.DECISION
    rule_ids: list[StrictStr] = Field(default_factory=list)
    condition_ids: list[StrictStr] = Field(default_factory=list)
    outcomes: list[StrictStr] = Field(default_factory=list)
    branch_target_ids: list[StrictStr] = Field(default_factory=list)
    decision_owner_id: StrictStr | None = None
    evidence_ids: list[StrictStr] = Field(default_factory=list)


class Calculator(Entity):
    entity_type: Literal[EntityType.CALCULATOR] = EntityType.CALCULATOR
    calculator_type: StrictStr | None = None
    version: StrictStr | None = None
    owner_id: StrictStr | None = None
    location_reference: StrictStr | None = None
    input_ids: list[StrictStr] = Field(default_factory=list)
    output_ids: list[StrictStr] = Field(default_factory=list)
    using_step_ids: list[StrictStr] = Field(default_factory=list)
    validation_status: StrictStr | None = None
    validation_date: StrictStr | None = None
    criticality: StrictStr | None = None
    recovery_fallback: StrictStr | None = None


class Evidence(Entity):
    entity_type: Literal[EntityType.EVIDENCE] = EntityType.EVIDENCE
    evidence_type: StrictStr | None = None
    producer_id: StrictStr | None = None
    linked_control_ids: list[StrictStr] = Field(default_factory=list)
    linked_step_ids: list[StrictStr] = Field(default_factory=list)
    linked_decision_ids: list[StrictStr] = Field(default_factory=list)
    storage_reference: StrictStr | None = None
    retention: StrictStr | None = None
    as_of_date: StrictStr | None = None
    reviewer_id: StrictStr | None = None


SemanticObject = Annotated[
    DocumentIdentity
    | DocumentVersion
    | Section
    | Statement
    | Table
    | Figure
    | Process
    | ProcessStep
    | Methodology
    | MethodologyStep
    | Activity
    | Decision
    | Trigger
    | Requirement
    | Control
    | Risk
    | Policy
    | Standard
    | Regulation
    | Approval
    | Evidence
    | Record
    | Role
    | Organization
    | EscalationPath
    | System
    | DataAsset
    | DataElement
    | Input
    | Output
    | Calculator
    | Model
    | Parameter
    | Rule
    | Metric
    | Threshold
    | Formula
    | ServiceLevel
    | Assumption
    | Limitation
    | Exception
    | Dependency
    | Precondition
    | CompletionCondition
    | GlossaryTerm,
    Field(discriminator="entity_type"),
]


def _pairs(
    relation: RelationshipType,
    sources: Iterable[EntityType],
    targets: Iterable[EntityType],
) -> set[tuple[RelationshipType, EntityType, EntityType]]:
    return {(relation, source, target) for source in sources for target in targets}


_DOCUMENTS = {EntityType.DOCUMENT_IDENTITY, EntityType.DOCUMENT_VERSION}
_WORK = {
    EntityType.PROCESS,
    EntityType.PROCESS_STEP,
    EntityType.METHODOLOGY,
    EntityType.METHODOLOGY_STEP,
    EntityType.ACTIVITY,
}
_ACTORS = {EntityType.ROLE, EntityType.ORGANIZATION}
_DATA = {EntityType.DATA_ASSET, EntityType.DATA_ELEMENT}
_POLICY = {
    EntityType.REQUIREMENT,
    EntityType.POLICY,
    EntityType.STANDARD,
    EntityType.REGULATION,
}
_STEP_LIKE = {EntityType.PROCESS_STEP, EntityType.METHODOLOGY_STEP, EntityType.ACTIVITY}

_ALLOWED_PAIRS: set[tuple[RelationshipType, EntityType, EntityType]] = set()
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.HAS_VERSION, {EntityType.DOCUMENT_IDENTITY}, {EntityType.DOCUMENT_VERSION}
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.CURRENT_VERSION, {EntityType.DOCUMENT_IDENTITY}, {EntityType.DOCUMENT_VERSION}
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.SUPERSEDES,
    {EntityType.DOCUMENT_VERSION},
    _DOCUMENTS | _POLICY | {EntityType.METHODOLOGY, EntityType.PROCESS},
)
_ALLOWED_PAIRS |= _pairs(RelationshipType.HAS_SECTION, _DOCUMENTS, {EntityType.SECTION})
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.CONTAINS_STATEMENT, {EntityType.SECTION}, {EntityType.STATEMENT}
)
_ALLOWED_PAIRS |= _pairs(RelationshipType.CONTAINS_TABLE, {EntityType.SECTION}, {EntityType.TABLE})
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.CONTAINS_FIGURE, {EntityType.SECTION}, {EntityType.FIGURE}
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.DEFINES,
    _WORK | _POLICY | {EntityType.SECTION, EntityType.STATEMENT},
    {EntityType.GLOSSARY_TERM},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.REFERENCES, set(EntityType), _DOCUMENTS | _POLICY | {EntityType.REQUIREMENT}
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.GOVERNED_BY, _WORK | {EntityType.CONTROL, EntityType.RULE}, _POLICY
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.IMPLEMENTS, _WORK | {EntityType.CONTROL, EntityType.PROCESS_STEP}, _POLICY
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.HAS_STEP, {EntityType.PROCESS}, {EntityType.PROCESS_STEP, EntityType.ACTIVITY}
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.HAS_STEP,
    {EntityType.METHODOLOGY},
    {EntityType.METHODOLOGY_STEP, EntityType.ACTIVITY},
)
_ALLOWED_PAIRS |= _pairs(RelationshipType.PRECEDES, _STEP_LIKE, _STEP_LIKE)
_ALLOWED_PAIRS |= _pairs(RelationshipType.NEXT_ON_TRUE, {EntityType.DECISION}, _STEP_LIKE)
_ALLOWED_PAIRS |= _pairs(RelationshipType.NEXT_ON_FALSE, {EntityType.DECISION}, _STEP_LIKE)
_ALLOWED_PAIRS |= _pairs(RelationshipType.TRIGGERED_BY, _WORK, {EntityType.TRIGGER})
_ALLOWED_PAIRS |= _pairs(RelationshipType.PERFORMED_BY, _STEP_LIKE | {EntityType.CONTROL}, _ACTORS)
_ALLOWED_PAIRS |= _pairs(RelationshipType.ACCOUNTABLE_TO, _ACTORS, _ACTORS)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.APPROVED_BY,
    _DOCUMENTS | _WORK | _POLICY | {EntityType.EXCEPTION, EntityType.APPROVAL},
    _ACTORS,
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.ESCALATES_TO,
    _STEP_LIKE | {EntityType.CONTROL, EntityType.EXCEPTION, EntityType.DEPENDENCY},
    _ACTORS | {EntityType.ESCALATION_PATH},
)
_ALLOWED_PAIRS |= _pairs(RelationshipType.CONSUMES, _STEP_LIKE, {EntityType.INPUT} | _DATA)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.PRODUCES,
    _STEP_LIKE,
    {EntityType.OUTPUT, EntityType.EVIDENCE, EntityType.RECORD},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.USES,
    _STEP_LIKE | {EntityType.RULE},
    {EntityType.SYSTEM, EntityType.CALCULATOR, EntityType.MODEL, EntityType.FORMULA} | _DATA,
)
_ALLOWED_PAIRS |= _pairs(RelationshipType.USES_SYSTEM, _STEP_LIKE, {EntityType.SYSTEM})
_ALLOWED_PAIRS |= _pairs(RelationshipType.USES_DATA, _STEP_LIKE | {EntityType.RULE}, _DATA)
_ALLOWED_PAIRS |= _pairs(RelationshipType.USES_CALCULATOR, _STEP_LIKE, {EntityType.CALCULATOR})
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.DEPENDS_ON,
    _WORK,
    {
        EntityType.DEPENDENCY,
        EntityType.SYSTEM,
        EntityType.DATA_ASSET,
        EntityType.PROCESS,
        EntityType.METHODOLOGY,
    },
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.REQUIRES,
    _WORK | {EntityType.CONTROL, EntityType.RULE, EntityType.STANDARD},
    _POLICY | {EntityType.INPUT, EntityType.PRECONDITION, EntityType.ROLE, EntityType.SYSTEM},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.HAS_PRECONDITION, _STEP_LIKE | {EntityType.RULE}, {EntityType.PRECONDITION}
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.HAS_COMPLETION_CONDITION, _STEP_LIKE, {EntityType.COMPLETION_CONDITION}
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.EVALUATES,
    {EntityType.DECISION},
    {EntityType.RULE, EntityType.METRIC, EntityType.THRESHOLD},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.USES_METRIC, _WORK | {EntityType.CONTROL, EntityType.RULE}, {EntityType.METRIC}
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.HAS_THRESHOLD,
    {EntityType.RULE, EntityType.METRIC, EntityType.SERVICE_LEVEL},
    {EntityType.THRESHOLD},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.TRIGGERS,
    {EntityType.RULE, EntityType.DECISION, EntityType.METRIC, EntityType.THRESHOLD},
    {EntityType.TRIGGER} | _STEP_LIKE,
)
_ALLOWED_PAIRS |= _pairs(RelationshipType.MITIGATES, {EntityType.CONTROL}, {EntityType.RISK})
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.ADDRESSES_RISK,
    {EntityType.CONTROL, EntityType.PROCESS_STEP, EntityType.REQUIREMENT},
    {EntityType.RISK},
)
_ALLOWED_PAIRS |= _pairs(RelationshipType.EXECUTES_CONTROL, _STEP_LIKE, {EntityType.CONTROL})
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.PRODUCES_EVIDENCE,
    {EntityType.CONTROL} | _STEP_LIKE | {EntityType.DECISION},
    {EntityType.EVIDENCE},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.VALIDATED_BY,
    {EntityType.METHODOLOGY, EntityType.METHODOLOGY_STEP, EntityType.MODEL, EntityType.CALCULATOR},
    _ACTORS | {EntityType.CONTROL, EntityType.PROCESS_STEP},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.TESTED_BY,
    {EntityType.CONTROL, EntityType.RULE, EntityType.MODEL, EntityType.CALCULATOR},
    _ACTORS | {EntityType.CONTROL, EntityType.RECORD, EntityType.EVIDENCE},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.MONITORED_BY,
    _WORK | {EntityType.CONTROL, EntityType.RULE, EntityType.METRIC, EntityType.SERVICE_LEVEL},
    _ACTORS | {EntityType.SYSTEM, EntityType.METRIC},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.HAS_ASSUMPTION,
    {EntityType.METHODOLOGY, EntityType.METHODOLOGY_STEP, EntityType.RULE, EntityType.MODEL},
    {EntityType.ASSUMPTION},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.HAS_LIMITATION,
    {EntityType.METHODOLOGY, EntityType.METHODOLOGY_STEP, EntityType.MODEL, EntityType.CALCULATOR},
    {EntityType.LIMITATION},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.HAS_EXCEPTION,
    _WORK | {EntityType.RULE, EntityType.REQUIREMENT, EntityType.CONTROL},
    {EntityType.EXCEPTION},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.OVERRIDES,
    {EntityType.EXCEPTION},
    {
        EntityType.RULE,
        EntityType.REQUIREMENT,
        EntityType.CONTROL,
        EntityType.PROCESS_STEP,
        EntityType.METHODOLOGY,
    },
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.HAS_PARAMETER,
    {EntityType.MODEL, EntityType.FORMULA, EntityType.METHODOLOGY_STEP, EntityType.RULE},
    {EntityType.PARAMETER},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.USES_MODEL,
    {EntityType.METHODOLOGY, EntityType.METHODOLOGY_STEP, EntityType.PROCESS_STEP, EntityType.RULE},
    {EntityType.MODEL},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.USES_FORMULA,
    {EntityType.METHODOLOGY, EntityType.METHODOLOGY_STEP, EntityType.RULE, EntityType.MODEL},
    {EntityType.FORMULA},
)
_ALLOWED_PAIRS |= _pairs(
    RelationshipType.DEFINED_BY,
    set(EntityType),
    {EntityType.STATEMENT, EntityType.RULE, EntityType.FORMULA, EntityType.METHODOLOGY},
)
_ALLOWED_PAIRS |= _pairs(RelationshipType.HAS_ALIAS, set(EntityType), {EntityType.GLOSSARY_TERM})
_ALLOWED_PAIRS |= _pairs(RelationshipType.RELATED_TO_DOCUMENT, set(EntityType), _DOCUMENTS)

ALLOWED_RELATIONSHIPS: frozenset[tuple[RelationshipType, EntityType, EntityType]] = frozenset(
    _ALLOWED_PAIRS
)


def is_relationship_allowed(
    relationship_type: RelationshipType,
    source_type: EntityType,
    target_type: EntityType,
) -> bool:
    return (relationship_type, source_type, target_type) in ALLOWED_RELATIONSHIPS


def _validate_layer_authority(layer: Layer | None, authority: Authority | None) -> None:
    if layer is None or authority is None:
        return
    allowed: dict[Layer, set[Authority]] = {
        Layer.AUTHORITATIVE: {Authority.EXPLICIT, Authority.DERIVED, Authority.REVIEWED},
        Layer.GOVERNED: {Authority.EXPLICIT, Authority.DERIVED, Authority.REVIEWED},
        Layer.EXTRACTED: set(Authority),
        Layer.RETRIEVAL: {Authority.DERIVED, Authority.INFERRED, Authority.REVIEWED},
    }
    if authority not in allowed[layer]:
        raise ValueError(f"authority {authority.value!r} is not permitted in {layer.value!r} layer")


class Relationship(StrictModel):
    """A typed edge; arbitrary RELATED_TO edges are intentionally impossible."""

    id: StrictStr | None = None
    source_id: StrictStr
    source_type: EntityType
    relationship_type: RelationshipType | None = Field(
        default=None,
        validation_alias=AliasChoices("relationship_type", "predicate"),
    )
    target_id: StrictStr
    target_type: EntityType
    provenance: Provenance
    authority: Authority | None = None
    layer: Layer | None = None
    review_status: ReviewStatus | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    validity: TemporalValidity | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    overwrites_id: StrictStr | None = None
    overwrites_layer: Layer | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def allocate_edge_id(cls, values: object) -> object:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        if not data.get("id") and data.get("source_id") and data.get("target_id"):
            relationship_type = data.get("relationship_type", data.get("predicate", "EDGE"))
            token = (
                hashlib.sha256(
                    f"{data['source_id']}\0{relationship_type}\0{data['target_id']}".encode()
                )
                .hexdigest()[:12]
                .upper()
            )
            data["id"] = f"EDGE-{token}"
        return data

    @model_validator(mode="after")
    def validate_relationship(self) -> Relationship:
        if self.validity is None and (self.valid_from is not None or self.valid_to is not None):
            object.__setattr__(
                self,
                "validity",
                TemporalValidity(valid_from=self.valid_from, valid_to=self.valid_to),
            )
        elif self.validity is not None:
            if self.valid_from is not None and self.validity.valid_from != self.valid_from:
                raise ValueError("valid_from conflicts with validity.valid_from")
            if self.valid_to is not None and self.validity.valid_to != self.valid_to:
                raise ValueError("valid_to conflicts with validity.valid_to")
        if self.id is None:
            raise ValueError("relationship id could not be allocated")
        validate_identifier(self.id, label="relationship id")
        if self.relationship_type is None:
            raise ValueError("relationship_type is required")
        if not is_relationship_allowed(self.relationship_type, self.source_type, self.target_type):
            raise ValueError(
                f"relationship {self.relationship_type.value} does not permit "
                f"{self.source_type.value} -> {self.target_type.value}"
            )
        if self.authority is None:
            object.__setattr__(self, "authority", self.provenance.authority)
        if self.layer is None:
            object.__setattr__(self, "layer", self.provenance.layer)
        if self.review_status is None:
            object.__setattr__(self, "review_status", self.provenance.review_status)
        if self.authority is not self.provenance.authority:
            raise ValueError("relationship authority must match provenance.authority")
        if self.layer is not self.provenance.layer:
            raise ValueError("relationship layer must match provenance.layer")
        if self.review_status is not self.provenance.review_status:
            raise ValueError("relationship review_status must match provenance.review_status")
        _validate_layer_authority(self.layer, self.authority)
        if self.overwrites_id is not None and self.overwrites_layer is None:
            raise ValueError("overwrites_layer is required when overwrites_id is set")
        if (
            self.overwrites_layer is not None
            and self.layer is not None
            and self.layer.rank > self.overwrites_layer.rank
        ):
            raise ValueError(
                "a higher-numbered graph layer cannot overwrite a lower-numbered layer"
            )
        return self

    @property
    def predicate(self) -> RelationshipType:
        if self.relationship_type is None:  # pragma: no cover - guarded by validator
            raise ValueError("relationship_type is missing")
        return self.relationship_type


Node = Entity
Edge = Relationship
GraphNode = Entity
GraphEdge = Relationship


class EntityRegistry:
    """Deterministic uniqueness and reference resolver for a semantic graph."""

    def __init__(self, entities: Iterable[Entity] = ()) -> None:
        self._entities: dict[str, Entity] = {}
        self.add_many(entities)

    def add(self, entity: Entity) -> None:
        if entity.id in self._entities:
            existing = self._entities[entity.id]
            raise ValueError(
                f"duplicate entity id {entity.id}: {existing.entity_type.value} and "
                f"{entity.entity_type.value} cannot coexist"
            )
        self._entities[entity.id] = entity

    def add_many(self, entities: Iterable[Entity]) -> None:
        for entity in entities:
            self.add(entity)

    def resolve(self, identifier: str, expected_type: EntityType | None = None) -> Entity:
        try:
            entity = self._entities[identifier]
        except KeyError as exc:
            raise ValueError(f"dangling entity reference: {identifier}") from exc
        if expected_type is not None and entity.entity_type is not expected_type:
            raise ValueError(
                f"reference {identifier} resolves to {entity.entity_type.value}, "
                f"expected {expected_type.value}"
            )
        return entity

    def validate_relationship(self, relationship: Relationship) -> None:
        source = self.resolve(relationship.source_id, relationship.source_type)
        target = self.resolve(relationship.target_id, relationship.target_type)
        if relationship.overwrites_id is not None:
            overwritten = self.resolve(relationship.overwrites_id)
            if (
                relationship.layer is not None
                and overwritten.layer is not None
                and relationship.layer.rank > overwritten.layer.rank
            ):
                raise ValueError(
                    f"relationship {relationship.id} cannot overwrite lower-layer object "
                    f"{overwritten.id}"
                )
        if (
            source.provenance.document_id != target.provenance.document_id
            and relationship.relationship_type is not RelationshipType.RELATED_TO_DOCUMENT
        ):
            raise ValueError(
                f"cross-document relationship {relationship.id} requires RELATED_TO_DOCUMENT"
            )

    def validate_relationships(self, relationships: Iterable[Relationship]) -> None:
        for relationship in relationships:
            self.validate_relationship(relationship)

    @property
    def entities(self) -> tuple[Entity, ...]:
        return tuple(self._entities.values())


def validate_unique_entities(entities: Iterable[Entity]) -> None:
    ensure_unique_ids(entity.id for entity in entities)


__all__ = [
    "ALLOWED_RELATIONSHIPS",
    "Activity",
    "Approval",
    "Assumption",
    "Calculator",
    "CompletionCondition",
    "Control",
    "DataAsset",
    "DataElement",
    "Decision",
    "Dependency",
    "DocumentIdentity",
    "DocumentVersion",
    "Entity",
    "EntityRegistry",
    "EntityType",
    "EscalationPath",
    "Evidence",
    "Edge",
    "Exception",
    "Figure",
    "Formula",
    "GlossaryTerm",
    "GraphEdge",
    "GraphNode",
    "GraphLayer",
    "Input",
    "Layer",
    "Limitation",
    "Methodology",
    "MethodologyStep",
    "Metric",
    "Model",
    "Organization",
    "Output",
    "Parameter",
    "Policy",
    "Precondition",
    "Process",
    "ProcessStep",
    "ProvenanceOrigin",
    "Relationship",
    "RelationshipType",
    "Requirement",
    "Record",
    "Regulation",
    "Risk",
    "Role",
    "Section",
    "SemanticObject",
    "ServiceLevel",
    "Standard",
    "Statement",
    "System",
    "Table",
    "Threshold",
    "Trigger",
    "VersionStatus",
    "is_relationship_allowed",
    "Node",
    "validate_unique_entities",
]
