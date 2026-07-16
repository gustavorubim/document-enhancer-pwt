from document_enhancer.artifacts.repository import ArtifactRepository
from document_enhancer.audit.deterministic import Validator
from document_enhancer.contracts import (
    DocumentParser,
    Exporter,
    ModelGateway,
    PromptComposer,
    PromptPackLoader,
    ReferencePackLoader,
    Retriever,
    Specialist,
)
from document_enhancer.export.bundle import Exporter as BundleExporter
from document_enhancer.ingest.base import DocumentParser as IngestParser
from document_enhancer.llm.models import ModelGateway as LlmGateway
from document_enhancer.prompting.composer import PromptComposer as Composer
from document_enhancer.prompting.loader import PromptPackLoader as Loader
from document_enhancer.rag.retrievers.base import Retriever as RetrieverPort
from document_enhancer.references.loader import ReferencePackLoader as RefLoader


def test_ports_are_frozen_and_re_exported() -> None:
    assert DocumentParser is IngestParser
    assert ArtifactRepository.__name__ == "ArtifactRepository"
    assert ReferencePackLoader is RefLoader
    assert PromptPackLoader is Loader
    assert PromptComposer is Composer
    assert ModelGateway is LlmGateway
    assert Retriever is RetrieverPort
    assert Exporter is BundleExporter
    assert all(
        hasattr(port, "__dict__")
        for port in (
            DocumentParser,
            ArtifactRepository,
            ReferencePackLoader,
            PromptPackLoader,
            PromptComposer,
            ModelGateway,
            Specialist,
            Validator,
            Retriever,
            Exporter,
        )
    )
