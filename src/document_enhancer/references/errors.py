"""Reference-pack specific errors and validation reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ReferencePackError(ValueError):
    """Base class for safe, user-facing reference-pack failures."""


class ReferencePackSecurityError(ReferencePackError):
    """Raised when a pack attempts an unsafe filesystem or YAML operation."""


class ReferencePackValidationError(ReferencePackError):
    """Raised when a reference pack is incomplete or internally inconsistent."""

    def __init__(self, message: str, *, errors: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.errors = errors


@dataclass(frozen=True)
class ValidationReport:
    """Machine-readable validation result used by the CLI verifier and tests."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors
