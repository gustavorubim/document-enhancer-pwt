"""Cross-lane WT0 ports.

These protocols keep parsing, reference packs, and the optional provider gateway independent from
vendor SDK object types.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, TypeVar

Artifact = TypeVar("Artifact")


class DocumentParser(Protocol):
    supported_suffixes: frozenset[str]

    def can_parse(self, source: Path) -> bool: ...

    def parse(self, source: Path) -> Any: ...


class ReferencePackLoader(Protocol):
    def load(self, location: Path) -> Any: ...

    def validate(self, pack: Any) -> Sequence[str]: ...


class ModelGateway(Protocol):
    def structured(self, *, route: str, schema: type[Artifact], prompt: str) -> Artifact: ...
