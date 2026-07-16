from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

from document_enhancer.audit.content import ContentAuditRequest
from document_enhancer.config import AppConfig, yaml_parser
from document_enhancer.domain.analysis import FindingSet
from document_enhancer.domain.audit import IndependentAuditResult
from document_enhancer.domain.enums import DocumentType
from document_enhancer.ingest.recovery import StructureRecoveryConfig, StructureRecoveryService
from document_enhancer.llm import EmbeddingProfile, GeminiEmbeddingAdapter, GeminiModelGateway
from document_enhancer.rag import OfflineDeterministicEmbedder
from document_enhancer.references.loader import load_reference_pack
from document_enhancer.rewrite import build_enhanced_document
from document_enhancer.rewrite.governed_example import apply_governed_example_contract
from document_enhancer.workflow import (
    DocumentWorkflow,
    WorkflowServices,
    build_configured_workflow_services,
)
from document_enhancer.workflow.model_services import GovernedRewriteRequest

ROOT = Path(__file__).resolve().parents[3]
PROMPT_PACK = ROOT / "prompt_packs/gemini_core"
REFERENCE_PACK = ROOT / "reference_packs/enterprise_core"


class _NoCallGateway:
    def invoke(self, **_: object) -> object:  # pragma: no cover - wiring inspection only
        raise AssertionError("the wiring inspection must not invoke a provider")


def test_live_factory_wires_every_model_backed_service_and_exact_identity(tmp_path: Path) -> None:
    profile = EmbeddingProfile()
    embedding = GeminiEmbeddingAdapter(
        profile=profile,
        embedder=OfflineDeterministicEmbedder(profile.dimensions),
    )
    gateway = _NoCallGateway()
    services = build_configured_workflow_services(
        config=AppConfig(),
        run_root=tmp_path / "runs",
        source=tmp_path / "source.md",
        document_type=DocumentType.PROCESS,
        structure_mode="auto",
        execution_mode="live",
        prompt_pack=PROMPT_PACK,
        reference_pack=REFERENCE_PACK,
        gateway=cast(GeminiModelGateway, gateway),
        embedding_adapter=embedding,
        auto_catalog_ingest=False,
    )

    assert services.offline is False
    assert services.structure_mode == "auto"
    assert services.structure_service is not None
    assert getattr(services.structure_service, "gateway", None) is gateway
    assert services.analysis_runner is not None
    assert services.question_generator is not None
    assert services.checklist_generator is not None
    assert services.rewrite_runner is not None
    assert services.content_auditor is not None
    assert services.audit_revision_runner is not None
    assert services.execution_metadata is not None
    assert services.execution_metadata.schema_digest == services.input_fingerprints["schema"]
    assert services.input_fingerprints["prompt"] == services.input_fingerprints["template"]
    assert services.execution_metadata.model_routes == {
        "structure": "gemini-3.1-flash-lite",
        "analysis": "gemini-3.5-flash",
        "rewrite": "gemini-3.1-pro-preview",
        "audit": "gemini-3.5-flash",
        "embedding": "gemini-embedding-2",
    }
    assert services.embedding_profile.provider == "google"


class _StructuredStructureFake:
    def __init__(self) -> None:
        self.calls = 0
        self.config = StructureRecoveryConfig(mode="auto")

    def run(self, document, *, repository=None, run_id=None):
        self.calls += 1
        return StructureRecoveryService(config=StructureRecoveryConfig(mode="parser")).run(
            document, repository=repository, run_id=run_id
        )


class _QuestionFake:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, **kwargs):
        self.calls += 1
        return kwargs["baseline"]


class _ChecklistFake:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, **kwargs):
        self.calls += 1
        return kwargs["baseline"]


class _RewriteFake:
    def __init__(self) -> None:
        self.calls = 0

    def rewrite(self, request: GovernedRewriteRequest):
        self.calls += 1
        model = build_enhanced_document(
            request.inputs,
            document_id=request.document_id,
            document_type=request.document_type,
            reference_pack_id=request.reference_pack_id,
            reference_pack_version=request.reference_pack_version,
            template_id=request.template_id,
            template_version=request.template_version,
            ledger=request.ledger,
            revision_counters=request.counters,
        )
        pack = load_reference_pack(REFERENCE_PACK)
        requirements = yaml_parser().load(
            pack.requirements_path(request.document_type.value).read_text(encoding="utf-8")
        )
        return apply_governed_example_contract(model, request.inputs, requirements)


class _AuditFake:
    def __init__(self) -> None:
        self.calls = 0

    def audit(self, request: ContentAuditRequest) -> IndependentAuditResult:
        self.calls += 1
        token = hashlib.sha256(request.enhanced_markdown.encode()).hexdigest()[:16].upper()
        return IndependentAuditResult(
            audit_id=f"INDAUD-{token}",
            status="pass",
            provider="structured-live-fake",
            isolated_context=True,
        )


def test_arbitrary_non_digest_document_uses_injected_live_path_and_independent_audit(
    tmp_path: Path,
) -> None:
    original = REFERENCE_PACK / "templates/process/example.md"
    source = tmp_path / "arbitrary-process.md"
    source.write_text(
        original.read_text(encoding="utf-8") + "\n<!-- arbitrary non-governed digest copy -->\n",
        encoding="utf-8",
    )
    assert (
        hashlib.sha256(source.read_bytes()).hexdigest()
        != hashlib.sha256(original.read_bytes()).hexdigest()
    )

    structure = _StructuredStructureFake()
    questions = _QuestionFake()
    checklist = _ChecklistFake()
    rewrite = _RewriteFake()
    auditor = _AuditFake()
    profile = EmbeddingProfile()
    services = WorkflowServices(
        run_root=tmp_path / "runs",
        source=source,
        document_type=DocumentType.PROCESS,
        structure_service=structure,
        analysis_runner=lambda request: FindingSet(
            document_id=request.document_id,
            source_digest=request.source_digest,
            findings=[],
            blocking_count=0,
        ),
        question_generator=questions,
        checklist_generator=checklist,
        rewrite_runner=rewrite,
        content_auditor=auditor,
        structure_mode="auto",
        gate2_enabled=False,
        offline=False,
        prompt_pack=PROMPT_PACK,
        reference_pack=REFERENCE_PACK,
        auto_catalog_ingest=False,
        embedding_profile=profile,
        embedding_adapter=GeminiEmbeddingAdapter(
            profile=profile,
            embedder=OfflineDeterministicEmbedder(profile.dimensions),
        ),
    )

    result = DocumentWorkflow(services).run()

    assert result.status == "succeeded", result.errors
    assert structure.calls == 1
    assert questions.calls == 1
    assert checklist.calls == 1
    assert rewrite.calls == 1
    assert auditor.calls == 1
    run_path = tmp_path / "runs" / result.run_id
    assert "structured-live-fake" in (run_path / "audit/content.json").read_text(encoding="utf-8")
