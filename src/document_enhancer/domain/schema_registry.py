"""Authoritative mapping from checked-in schema filenames to Pydantic roots."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from document_enhancer.clarification.models import ReviewerValidationReport
from document_enhancer.domain.analysis import (
    AnalysisReport,
    StructureQuality,
    StructureRecoveryProposal,
    StructureScan,
)
from document_enhancer.domain.audit import Audit
from document_enhancer.domain.ontology import Entity, Relationship
from document_enhancer.domain.provenance import Provenance
from document_enhancer.domain.questions import (
    AnswersArtifact,
    ContentLedger,
    QuestionsArtifact,
    RewriteChecklist,
    Steering,
    WaiversArtifact,
)
from document_enhancer.domain.run import (
    CatalogIngestionReceipt,
    ExportBundle,
    ExportChunk,
    PromptPackManifest,
    RagAnswer,
    RagBuildManifest,
    RagCitation,
    RagGroundingAudit,
    RagQuery,
    RagRelevanceGrade,
    RunManifest,
)
from document_enhancer.domain.semantic import SemanticDocument
from document_enhancer.domain.source import RawDocument
from document_enhancer.rewrite.models import EnhancedDocumentModel

SCHEMA_MODELS: Mapping[str, type[BaseModel]] = {
    "analysis.schema.json": AnalysisReport,
    "answers.schema.json": AnswersArtifact,
    "audit.schema.json": Audit,
    "content-ledger.schema.json": ContentLedger,
    "chunk.schema.json": ExportChunk,
    "catalog-ingestion.schema.json": CatalogIngestionReceipt,
    "entity.schema.json": Entity,
    "export.schema.json": ExportBundle,
    "provenance.schema.json": Provenance,
    "prompt-pack-manifest.schema.json": PromptPackManifest,
    "questions.schema.json": QuestionsArtifact,
    "rag-answer.schema.json": RagAnswer,
    "rag-build-manifest.schema.json": RagBuildManifest,
    "rag-citation.schema.json": RagCitation,
    "rag-grounding-audit.schema.json": RagGroundingAudit,
    "rag-query.schema.json": RagQuery,
    "rag-relevance-grade.schema.json": RagRelevanceGrade,
    "relationship.schema.json": Relationship,
    "run-manifest.schema.json": RunManifest,
    "semantic-document.schema.json": SemanticDocument,
    "enhanced-document.schema.json": EnhancedDocumentModel,
    "source-document.schema.json": RawDocument,
    "steering.schema.json": Steering,
    "structure-quality.schema.json": StructureQuality,
    "structure-recovery.schema.json": StructureRecoveryProposal,
    "structure-scan.schema.json": StructureScan,
    "waivers.schema.json": WaiversArtifact,
    "rewrite-checklist.schema.json": RewriteChecklist,
    "validation-report.schema.json": ReviewerValidationReport,
}


def schema_models() -> Mapping[str, type[BaseModel]]:
    return SCHEMA_MODELS


__all__ = ["SCHEMA_MODELS", "schema_models"]
