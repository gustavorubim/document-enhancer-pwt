"""Controlled vocabulary used by the ontology and artifact contracts."""

from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    DOCUMENT_IDENTITY = "DocumentIdentity"
    DOCUMENT_VERSION = "DocumentVersion"
    SECTION = "Section"
    STATEMENT = "Statement"
    TABLE = "Table"
    FIGURE = "Figure"
    PROCESS = "Process"
    PROCESS_STEP = "ProcessStep"
    METHODOLOGY = "Methodology"
    METHODOLOGY_STEP = "MethodologyStep"
    ACTIVITY = "Activity"
    DECISION = "Decision"
    TRIGGER = "Trigger"
    REQUIREMENT = "Requirement"
    CONTROL = "Control"
    RISK = "Risk"
    POLICY = "Policy"
    STANDARD = "Standard"
    REGULATION = "Regulation"
    APPROVAL = "Approval"
    EVIDENCE = "Evidence"
    RECORD = "Record"
    ROLE = "Role"
    ORGANIZATION = "Organization"
    ESCALATION_PATH = "EscalationPath"
    SYSTEM = "System"
    DATA_ASSET = "DataAsset"
    DATA_ELEMENT = "DataElement"
    INPUT = "Input"
    OUTPUT = "Output"
    CALCULATOR = "Calculator"
    MODEL = "Model"
    PARAMETER = "Parameter"
    RULE = "Rule"
    METRIC = "Metric"
    THRESHOLD = "Threshold"
    FORMULA = "Formula"
    SERVICE_LEVEL = "ServiceLevel"
    ASSUMPTION = "Assumption"
    LIMITATION = "Limitation"
    EXCEPTION = "Exception"
    DEPENDENCY = "Dependency"
    PRECONDITION = "Precondition"
    COMPLETION_CONDITION = "CompletionCondition"
    GLOSSARY_TERM = "GlossaryTerm"


class RelationshipType(StrEnum):
    HAS_VERSION = "HAS_VERSION"
    CURRENT_VERSION = "CURRENT_VERSION"
    SUPERSEDES = "SUPERSEDES"
    HAS_SECTION = "HAS_SECTION"
    CONTAINS_STATEMENT = "CONTAINS_STATEMENT"
    CONTAINS_TABLE = "CONTAINS_TABLE"
    CONTAINS_FIGURE = "CONTAINS_FIGURE"
    DEFINES = "DEFINES"
    REFERENCES = "REFERENCES"
    GOVERNED_BY = "GOVERNED_BY"
    IMPLEMENTS = "IMPLEMENTS"
    HAS_STEP = "HAS_STEP"
    PRECEDES = "PRECEDES"
    NEXT_ON_TRUE = "NEXT_ON_TRUE"
    NEXT_ON_FALSE = "NEXT_ON_FALSE"
    TRIGGERED_BY = "TRIGGERED_BY"
    PERFORMED_BY = "PERFORMED_BY"
    ACCOUNTABLE_TO = "ACCOUNTABLE_TO"
    APPROVED_BY = "APPROVED_BY"
    ESCALATES_TO = "ESCALATES_TO"
    CONSUMES = "CONSUMES"
    PRODUCES = "PRODUCES"
    USES = "USES"
    USES_SYSTEM = "USES_SYSTEM"
    USES_DATA = "USES_DATA"
    USES_CALCULATOR = "USES_CALCULATOR"
    DEPENDS_ON = "DEPENDS_ON"
    REQUIRES = "REQUIRES"
    HAS_PRECONDITION = "HAS_PRECONDITION"
    HAS_COMPLETION_CONDITION = "HAS_COMPLETION_CONDITION"
    EVALUATES = "EVALUATES"
    USES_METRIC = "USES_METRIC"
    HAS_THRESHOLD = "HAS_THRESHOLD"
    TRIGGERS = "TRIGGERS"
    MITIGATES = "MITIGATES"
    ADDRESSES_RISK = "ADDRESSES_RISK"
    EXECUTES_CONTROL = "EXECUTES_CONTROL"
    PRODUCES_EVIDENCE = "PRODUCES_EVIDENCE"
    VALIDATED_BY = "VALIDATED_BY"
    TESTED_BY = "TESTED_BY"
    MONITORED_BY = "MONITORED_BY"
    HAS_ASSUMPTION = "HAS_ASSUMPTION"
    HAS_LIMITATION = "HAS_LIMITATION"
    HAS_EXCEPTION = "HAS_EXCEPTION"
    OVERRIDES = "OVERRIDES"
    HAS_PARAMETER = "HAS_PARAMETER"
    USES_MODEL = "USES_MODEL"
    USES_FORMULA = "USES_FORMULA"
    DEFINED_BY = "DEFINED_BY"
    HAS_ALIAS = "HAS_ALIAS"
    RELATED_TO_DOCUMENT = "RELATED_TO_DOCUMENT"


class Authority(StrEnum):
    EXPLICIT = "explicit"
    DERIVED = "derived"
    INFERRED = "inferred"
    REVIEWED = "reviewed"


class Layer(StrEnum):
    AUTHORITATIVE = "authoritative"
    GOVERNED = "governed"
    EXTRACTED = "extracted"
    RETRIEVAL = "retrieval"

    @property
    def rank(self) -> int:
        return list(type(self)).index(self) + 1


GraphLayer = Layer


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    IN_REVIEW = "in_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WAIVED = "waived"
    DEPRECATED = "deprecated"


class ProvenanceOrigin(StrEnum):
    SOURCE = "source"
    ANSWER = "answer"
    STEERING = "steering"
    REFERENCE = "reference"
    MODEL = "model"


class DocumentType(StrEnum):
    PROCESS = "process"
    METHODOLOGY = "methodology"
    STANDARD = "standard"
    DESKTOP_PROCEDURE = "desktop_procedure"


class VersionStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    EFFECTIVE = "effective"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class SourceBlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    FIGURE = "figure"
    FORMULA = "formula"
    CODE = "code"
    PAGE_BREAK = "page_break"
    HEADER = "header"
    FOOTER = "footer"
    UNKNOWN = "unknown"


class StructureDecision(StrEnum):
    ACCEPT_PARSER = "accept_parser"
    RECOVER = "recover"
    NEEDS_REVIEW = "needs_review"


class StructureDisposition(StrEnum):
    HEADING = "heading"
    BODY = "body"
    LIST = "list"
    TABLE = "table"
    FIGURE = "figure"
    FORMULA = "formula"
    PAGE_FURNITURE = "page_furniture"
    TABLE_OF_CONTENTS = "table_of_contents"
    BOILERPLATE = "boilerplate"
    UNCERTAIN = "uncertain"


class SpanDisposition(StrEnum):
    """Canonical source-to-target outcomes emitted by section analysis."""

    PRESERVED = "preserved"
    MOVED = "moved"
    MERGED = "merged"
    SPLIT = "split"
    OMITTED = "omitted"
    UNCERTAIN = "uncertain"
    BLOCKING = "blocking"


class FindingSeverity(StrEnum):
    BLOCKER = "blocker"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class FindingType(StrEnum):
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"
    DUPLICATE = "duplicate"
    VAGUE = "vague"
    UNSUPPORTED = "unsupported"
    NONCOMPLIANT = "noncompliant"
    EXTRACTION_RISK = "extraction_risk"
    IMPROVEMENT = "improvement"


class QuestionCategory(StrEnum):
    MISSING = "missing"
    AMBIGUITY = "ambiguity"
    CONFLICT = "conflict"
    VALIDATION = "validation"
    OWNERSHIP = "ownership"
    CONTROL = "control"
    CALCULATION = "calculation"
    DEPENDENCY = "dependency"
    EXCEPTION = "exception"
    STEERING = "steering"


class QuestionPriority(StrEnum):
    BLOCKING = "blocking"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    DEFERRED = "deferred"
    NOT_APPLICABLE = "not_applicable"
    WAIVED = "waived"


class ChecklistAction(StrEnum):
    RETAIN = "retain"
    CLARIFY = "clarify"
    MOVE = "move"
    SPLIT = "split"
    MERGE = "merge"
    STRUCTURE = "structure"
    ADD_FROM_ANSWER = "add_from_answer"
    DEPRECATE = "deprecate"
    OMIT = "omit"


class LedgerDisposition(StrEnum):
    RETAINED = "retained"
    CLARIFIED = "clarified"
    MOVED = "moved"
    SPLIT = "split"
    MERGED = "merged"
    STRUCTURED = "structured"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"
    OMITTED = "omitted"


class AuditStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WAITING = "waiting"


class AuditFindingKind(StrEnum):
    EDITORIAL = "editorial"
    ANSWER_CLARIFICATION = "answer_clarification"
    STRUCTURED_FACT = "structured_fact"
    INFERRED_PROPOSAL = "inferred_proposal"
    UNRESOLVED = "unresolved"
    OMISSION = "omission"


class RagAnswerStatus(StrEnum):
    ANSWERED = "answered"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


__all__ = [name for name in globals() if not name.startswith("_")]
