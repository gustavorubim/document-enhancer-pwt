"""Errors raised while loading or composing a versioned prompt pack."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PromptPackError(ValueError):
    """Base class for prompt-pack failures safe to show to a caller."""


class PromptPackSecurityError(PromptPackError):
    """Raised for unsafe YAML, path, include, or content-boundary operations."""


class PromptPackValidationError(PromptPackError):
    """Raised when a prompt pack is incomplete or violates a prompt contract."""

    def __init__(self, message: str, *, errors: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.errors = errors or (message,)


@dataclass(frozen=True)
class PromptPackValidationReport:
    """Precise, machine-readable validation output for service and CLI callers."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors
