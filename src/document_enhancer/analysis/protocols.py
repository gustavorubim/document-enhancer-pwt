"""Narrow ports consumed by analysis specialists."""

from typing import Protocol

from document_enhancer.contracts import Specialist


class AnalysisCallBudget(Protocol):
    def reserve(self, stage: str) -> None: ...


__all__ = ["AnalysisCallBudget", "Specialist"]
