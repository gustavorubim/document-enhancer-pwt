"""Independent content-auditor port with an offline deterministic implementation."""

from __future__ import annotations

import hashlib
from typing import Protocol

from pydantic import Field, StrictStr

from document_enhancer.domain.audit import IndependentAuditResult
from document_enhancer.domain.base import StrictModel
from document_enhancer.domain.semantic import SemanticDocument


class ContentAuditRequest(StrictModel):
    """Sealed context: final artifacts only, never rewrite prompts or scratch state."""

    document_id: StrictStr
    source_artifact: StrictStr = "source/normalized.md"
    source_markdown: StrictStr
    output_artifact: StrictStr = "output/enhanced.md"
    enhanced_markdown: StrictStr
    semantic_document: SemanticDocument
    checklist_digest: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    steering_digest: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ContentAuditor(Protocol):
    def audit(self, request: ContentAuditRequest) -> IndependentAuditResult: ...


class OfflineDeterministicContentAuditor:
    """No-network fake used by ordinary CI and offline workflows."""

    provider = "offline-deterministic-fake"

    def audit(self, request: ContentAuditRequest) -> IndependentAuditResult:
        token = (
            hashlib.sha256((request.document_id + "\0" + request.enhanced_markdown).encode("utf-8"))
            .hexdigest()[:16]
            .upper()
        )
        return IndependentAuditResult(
            audit_id=f"INDAUD-{token}",
            status="pass",
            findings=[],
            provider=self.provider,
            isolated_context=True,
        )


__all__ = ["ContentAuditRequest", "ContentAuditor", "OfflineDeterministicContentAuditor"]
