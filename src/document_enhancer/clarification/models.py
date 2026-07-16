"""Reviewer-loop diagnostics and deterministic clarification results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import Field, StrictBool, StrictStr

from document_enhancer.domain.base import StrictModel
from document_enhancer.domain.questions import QuestionsArtifact


class ValidationDiagnostic(StrictModel):
    """One actionable reviewer-input diagnostic.

    Paths use the persisted YAML shape (for example ``answers.answers[0].answer``),
    which makes the output useful both to a person editing the file and to a script.
    """

    code: StrictStr
    path: StrictStr
    message: StrictStr
    severity: Literal["error", "warning"] = "error"
    remediation: StrictStr | None = None
    provenance: tuple[StrictStr, ...] = ()

    @classmethod
    def error(
        cls,
        code: str,
        path: str,
        message: str,
        *,
        remediation: str | None = None,
        provenance: tuple[str, ...] = (),
    ) -> ValidationDiagnostic:
        return cls(
            code=code,
            path=path,
            message=message,
            severity="error",
            remediation=remediation,
            provenance=provenance,
        )

    @classmethod
    def warning(
        cls,
        code: str,
        path: str,
        message: str,
        *,
        remediation: str | None = None,
        provenance: tuple[str, ...] = (),
    ) -> ValidationDiagnostic:
        return cls(
            code=code,
            path=path,
            message=message,
            severity="warning",
            remediation=remediation,
            provenance=provenance,
        )


class ReviewerValidationReport(StrictModel):
    """Stable validation response for answers, steering, waivers, or a bundle."""

    artifact_type: StrictStr
    valid: StrictBool
    diagnostics: list[ValidationDiagnostic] = Field(default_factory=list)
    provenance: Mapping[str, object] = Field(default_factory=dict)

    @property
    def errors(self) -> tuple[ValidationDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "warning")


class QuestionSynthesisResult(StrictModel):
    """Questions plus the deterministic evidence/finding merge record."""

    questions: QuestionsArtifact
    source_finding_ids_by_question: dict[StrictStr, list[StrictStr]] = Field(default_factory=dict)
    exact_duplicate_count: int = Field(default=0, ge=0)
    semantic_duplicate_count: int = Field(default=0, ge=0)
    blocking_question_ids: list[StrictStr] = Field(default_factory=list)
    warnings: list[StrictStr] = Field(default_factory=list)


def diagnostic_text(report: ReviewerValidationReport) -> str:
    """Render diagnostics in deterministic, line-oriented form."""

    if report.valid and not report.warnings:
        return f"{report.artifact_type}: valid"
    lines = [f"{report.artifact_type}: {'valid' if report.valid else 'invalid'}"]
    for item in report.diagnostics:
        suffix = f" Remediation: {item.remediation}" if item.remediation else ""
        lines.append(f"- [{item.severity}] {item.path}: {item.message}{suffix}")
    return "\n".join(lines)


__all__ = [
    "QuestionSynthesisResult",
    "ReviewerValidationReport",
    "ValidationDiagnostic",
    "diagnostic_text",
]
