"""Cross-lane WT0 ports.

These protocols are intentionally dependency-light. Later lanes implement adapters behind them;
the workflow must not depend on vendor SDK object types or on a concrete storage backend.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, TypeVar

Artifact = TypeVar("Artifact")
Query = TypeVar("Query")


class DocumentParser(Protocol):
    supported_suffixes: frozenset[str]

    def can_parse(self, source: Path) -> bool: ...

    def parse(self, source: Path) -> Any: ...


class ArtifactRepository(Protocol):
    def put(self, run_id: str, name: str, artifact: Artifact) -> None: ...

    def get(self, run_id: str, name: str) -> Artifact | None: ...

    def list(self, run_id: str) -> Sequence[str]: ...


class ReferencePackLoader(Protocol):
    def load(self, location: Path) -> Any: ...

    def validate(self, pack: Any) -> Sequence[str]: ...


class PromptPackLoader(Protocol):
    def load(self, location: Path) -> Any: ...


class PromptComposer(Protocol):
    def compose(self, prompt_id: str, variables: Mapping[str, Any]) -> str: ...


class ModelGateway(Protocol):
    def structured(self, *, route: str, schema: type[Artifact], prompt: str) -> Artifact: ...

    def embed_documents(
        self, *, profile: str, texts: Sequence[str]
    ) -> Sequence[Sequence[float]]: ...

    def embed_query(self, *, profile: str, text: str) -> Sequence[float]: ...


class Specialist(Protocol):
    name: str

    def analyze(self, context: Mapping[str, Any]) -> Any: ...


class Validator(Protocol):
    def validate(self, artifact: Any) -> Sequence[str]: ...


class Retriever(Protocol):
    def retrieve(self, query: Query, *, limit: int = 10) -> Iterable[Any]: ...


class Exporter(Protocol):
    def export(self, artifact: Any, destination: Path) -> Sequence[Path]: ...
