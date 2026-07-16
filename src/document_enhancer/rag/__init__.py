"""SQLite RAG package construction and cumulative catalog APIs."""

from .build import (
    PackageVerification,
    RagBuildError,
    build_package,
    inspect_package,
    verify_package,
)
from .catalog import CatalogConflictError, CatalogReceipt, ingest_package, inspect_catalog
from .embeddings import (
    EmbeddingBatchRunner,
    OfflineDeterministicEmbedder,
    decode_float32,
    encode_float32,
)
from .factory import build_hybrid_retriever, catalog_embedding_profile
from .migrations import SCHEMA_VERSION, migrate, verify_migrations
from .models import RetrievalFilters, RetrievalResult
from .runtime import DeterministicRagModel, PromptPackRagModelPort, RagRuntime
from .sessions import SessionError, SessionStore
from .vector_store import ExactScanPolicy, ExactScanVectorStore, SQLiteCatalogVectorStore

__all__ = [
    "CatalogConflictError",
    "CatalogReceipt",
    "DeterministicRagModel",
    "EmbeddingBatchRunner",
    "ExactScanPolicy",
    "ExactScanVectorStore",
    "OfflineDeterministicEmbedder",
    "PackageVerification",
    "PromptPackRagModelPort",
    "RagBuildError",
    "RagRuntime",
    "RetrievalFilters",
    "RetrievalResult",
    "SCHEMA_VERSION",
    "SQLiteCatalogVectorStore",
    "SessionError",
    "SessionStore",
    "build_hybrid_retriever",
    "build_package",
    "catalog_embedding_profile",
    "decode_float32",
    "encode_float32",
    "ingest_package",
    "inspect_catalog",
    "inspect_package",
    "migrate",
    "verify_migrations",
    "verify_package",
]
