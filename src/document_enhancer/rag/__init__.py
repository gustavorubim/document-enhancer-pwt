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
from .migrations import SCHEMA_VERSION, migrate, verify_migrations

__all__ = [
    "CatalogConflictError",
    "CatalogReceipt",
    "EmbeddingBatchRunner",
    "OfflineDeterministicEmbedder",
    "PackageVerification",
    "RagBuildError",
    "SCHEMA_VERSION",
    "build_package",
    "decode_float32",
    "encode_float32",
    "ingest_package",
    "inspect_catalog",
    "inspect_package",
    "migrate",
    "verify_migrations",
    "verify_package",
]
