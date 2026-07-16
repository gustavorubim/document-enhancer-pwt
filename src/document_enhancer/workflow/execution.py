"""Safe live/offline workflow construction and persisted execution identity."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import StrictBool, StrictStr

from document_enhancer.analysis.orchestrator import AnalysisOrchestrator
from document_enhancer.config import AppConfig, config_as_public_dict
from document_enhancer.domain.base import StrictModel
from document_enhancer.domain.enums import DocumentType
from document_enhancer.errors import ConfigurationError
from document_enhancer.ingest.recovery import (
    StructureMode,
    StructureRecoveryConfig,
    StructureRecoveryService,
)
from document_enhancer.llm import (
    EMBEDDING_MODEL,
    ROUTE_FLASH,
    ROUTE_FLASH_LITE,
    ROUTE_PRO_PREVIEW,
    EmbeddingProfile,
    GeminiEmbeddingAdapter,
    GeminiGatewayConfig,
    GeminiModelGateway,
)
from document_enhancer.prompting import PromptPackComposer, load_prompt_pack
from document_enhancer.rag import OfflineDeterministicEmbedder
from document_enhancer.references.loader import load_reference_pack

from .fingerprints import workflow_input_fingerprints
from .model_services import (
    GeminiAuditRevisionRunner,
    GeminiChecklistGenerator,
    GeminiContentAuditor,
    GeminiGovernedRewriter,
    GeminiQuestionGenerator,
)
from .nodes import WorkflowServices

ExecutionMode = Literal["live", "offline"]

MODEL_LIFECYCLE = {
    ROUTE_FLASH_LITE: "stable",
    ROUTE_FLASH: "stable",
    ROUTE_PRO_PREVIEW: "preview",
    EMBEDDING_MODEL: "stable",
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


class ExecutionMetadata(StrictModel):
    """Secret-free identity that must remain compatible across run and resume."""

    schema_version: StrictStr = "m7.execution.v1"
    mode: ExecutionMode
    structure_mode: StrictStr
    provider: StrictStr
    backend: StrictStr
    credential_source: StrictStr
    model_routes: dict[StrictStr, StrictStr]
    model_lifecycle: dict[StrictStr, StrictStr]
    embedding_profile: StrictStr
    prompt_pack_id: StrictStr
    prompt_pack_version: StrictStr
    prompt_pack_digest: StrictStr
    reference_pack_id: StrictStr
    reference_pack_version: StrictStr
    reference_pack_digest: StrictStr
    schema_digest: StrictStr
    configuration_digest: StrictStr
    auto_catalog_ingest: StrictBool
    catalog_path: StrictStr | None = None

    @property
    def compatibility_digest(self) -> str:
        return _digest(self.model_dump(mode="json"))


def _validate_exact_routes(config: AppConfig) -> None:
    configured = {
        "structure": config.gemini.structure_model,
        "analysis": config.gemini.developer_model,
        "rewrite": config.gemini.rewrite_model,
        "embedding": config.gemini.embedding_model,
    }
    expected = {
        "structure": ROUTE_FLASH_LITE,
        "analysis": ROUTE_FLASH,
        "rewrite": ROUTE_PRO_PREVIEW,
        "embedding": EMBEDDING_MODEL,
    }
    mismatches = [
        f"{stage}={configured[stage]!r} (expected {model!r})"
        for stage, model in expected.items()
        if configured[stage] != model
    ]
    if mismatches:
        raise ConfigurationError(
            "configured model routes are incompatible with the governed prompt pack: "
            + "; ".join(mismatches)
        )


def _gateway_config(config: AppConfig) -> GeminiGatewayConfig:
    gateway = GeminiGatewayConfig.from_env(
        backend=config.gemini.backend,
        project=config.gemini.project,
        location=config.gemini.location,
        allow_pro_fallback=config.gemini.allow_pro_fallback,
    )
    if gateway.backend.value == "developer_api" and gateway.api_key is None:
        raise ConfigurationError(
            "live execution requires GOOGLE_API_KEY or GEMINI_API_KEY in the process environment"
        )
    if gateway.backend.value == "vertex_ai":
        if not gateway.project or not gateway.location:
            raise ConfigurationError("live Vertex AI execution requires project and location")
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if credentials_path and not Path(credentials_path).expanduser().is_file():
            raise ConfigurationError("GOOGLE_APPLICATION_CREDENTIALS does not name a file")
        try:
            import google.auth
            from google.auth.exceptions import DefaultCredentialsError

            credentials, _project = google.auth.default()
        except DefaultCredentialsError as exc:
            raise ConfigurationError(
                "live Vertex AI execution requires Application Default Credentials"
            ) from exc
        if credentials is None:  # pragma: no cover - google-auth promises an object or raises
            raise ConfigurationError(
                "live Vertex AI execution requires Application Default Credentials"
            )
    return gateway


def build_configured_workflow_services(
    *,
    config: AppConfig,
    run_root: Path,
    source: Path,
    document_type: DocumentType,
    structure_mode: StructureMode,
    execution_mode: ExecutionMode,
    prompt_pack: Path,
    reference_pack: Path,
    run_id: str | None = None,
    gate2_enabled: bool = True,
    stop_after: str | None = None,
    auto_catalog_ingest: bool = True,
    catalog_path: Path | None = None,
    gateway: GeminiModelGateway | None = None,
    embedding_adapter: GeminiEmbeddingAdapter | None = None,
) -> WorkflowServices:
    """Construct the complete service graph before source content can reach a provider."""

    if structure_mode not in {"parser", "auto", "recover", "force", "off"}:
        raise ConfigurationError("structure mode must be parser, auto, recover, force, or off")
    _validate_exact_routes(config)
    reference = load_reference_pack(reference_pack)
    prompts = load_prompt_pack(prompt_pack, reference_pack=reference)
    composer = PromptPackComposer(
        prompts,
        reference_pack=reference,
        document_type=document_type.value,
    )
    live = execution_mode == "live"
    credential_source = "none"
    provider = "offline"
    backend = "local"
    if live:
        if gateway is None:
            gateway_config = _gateway_config(config)
            gateway = GeminiModelGateway(gateway_config)
            credential_source = (
                "process_environment" if gateway_config.api_key is not None else "vertex_adc"
            )
        else:
            credential_source = "injected_test_adapter"
        provider = "google"
        backend = config.gemini.backend
        embedding_profile = EmbeddingProfile(
            model=config.gemini.embedding_model,
            dimensions=config.gemini.embedding_dimensions,
            backend=config.gemini.backend,
        )
        embedding = embedding_adapter or GeminiEmbeddingAdapter(
            profile=embedding_profile,
            project=config.gemini.project,
            location=config.gemini.location,
        )
        structure_service = StructureRecoveryService(
            config=StructureRecoveryConfig(
                mode=structure_mode,
                document_type=document_type.value,
            ),
            gateway=gateway,
            prompt_composer=composer,
        )
        analysis = AnalysisOrchestrator(composer, gateway)
        question_generator = GeminiQuestionGenerator(composer, gateway)
        checklist_generator = GeminiChecklistGenerator(composer, gateway)
        rewriter = GeminiGovernedRewriter(composer, gateway)
        content_auditor = GeminiContentAuditor(composer, gateway, document_type=document_type)
        audit_reviser = GeminiAuditRevisionRunner(composer, gateway, document_type=document_type)
    else:
        embedding_profile = EmbeddingProfile.offline(dimensions=config.gemini.embedding_dimensions)
        embedding = embedding_adapter or GeminiEmbeddingAdapter(
            profile=embedding_profile,
            embedder=OfflineDeterministicEmbedder(embedding_profile.dimensions),
        )
        structure_service = StructureRecoveryService(
            config=StructureRecoveryConfig(
                mode=structure_mode,
                document_type=document_type.value,
            )
        )
        analysis = None
        question_generator = None
        checklist_generator = None
        rewriter = None
        content_auditor = None
        audit_reviser = None
    public_config = config_as_public_dict(config)
    public_config["workspace"] = {
        "run_dir": str(run_root.expanduser().resolve()),
        "catalog_path": str(catalog_path.expanduser().resolve()) if catalog_path else None,
    }
    input_fingerprints = workflow_input_fingerprints(
        prompt_pack=prompt_pack,
        reference_pack=reference_pack,
    )
    metadata = ExecutionMetadata(
        mode=execution_mode,
        structure_mode=structure_mode,
        provider=provider,
        backend=backend,
        credential_source=credential_source,
        model_routes={
            "structure": ROUTE_FLASH_LITE,
            "analysis": ROUTE_FLASH,
            "rewrite": ROUTE_PRO_PREVIEW,
            "audit": ROUTE_FLASH,
            "embedding": EMBEDDING_MODEL,
        },
        model_lifecycle=MODEL_LIFECYCLE,
        embedding_profile=embedding_profile.identity,
        prompt_pack_id=prompts.pack_id,
        prompt_pack_version=prompts.version,
        prompt_pack_digest=prompts.pack_sha256,
        reference_pack_id=reference.pack_id,
        reference_pack_version=reference.version,
        reference_pack_digest=reference.pack_sha256,
        schema_digest=str(input_fingerprints["schema"]),
        configuration_digest=_digest(public_config),
        auto_catalog_ingest=auto_catalog_ingest,
        catalog_path=str(catalog_path.expanduser().resolve()) if catalog_path else None,
    )
    return WorkflowServices(
        run_root=run_root,
        source=source,
        run_id=run_id,
        document_type=document_type,
        structure_service=structure_service,
        analysis_runner=analysis,
        question_generator=question_generator,
        checklist_generator=checklist_generator,
        rewrite_runner=rewriter,
        content_auditor=content_auditor,
        audit_revision_runner=audit_reviser,
        structure_mode=structure_mode,
        gate2_enabled=gate2_enabled,
        stop_after=stop_after,
        offline=not live,
        execution_metadata=metadata,
        input_fingerprints={**input_fingerprints, "execution": metadata.compatibility_digest},
        prompt_pack=prompt_pack,
        reference_pack=reference_pack,
        auto_catalog_ingest=auto_catalog_ingest,
        catalog_path=catalog_path,
        embedding_profile=embedding_profile,
        embedding_adapter=embedding,
    )


__all__ = [
    "ExecutionMetadata",
    "ExecutionMode",
    "MODEL_LIFECYCLE",
    "build_configured_workflow_services",
]
