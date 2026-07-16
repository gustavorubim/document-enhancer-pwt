"""Precedence and applicability helpers for governed reference context."""

from __future__ import annotations

from .loader import (
    ApplicabilityContext,
    PrecedenceResolution,
    ResolvedReference,
    resolve_precedence,
)

__all__ = [
    "ApplicabilityContext",
    "PrecedenceResolution",
    "ResolvedReference",
    "resolve_precedence",
]
