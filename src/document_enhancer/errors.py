"""Stable exception and process-exit contracts for the CLI."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Document Enhancer process exit codes."""

    OK = 0
    WAITING_FOR_REVIEW = 10
    VALIDATION_FAILURE = 20
    AUDIT_FAILURE = 30
    PROVIDER_FAILURE = 40
    CONFIGURATION_FAILURE = 50
    UNSUPPORTED_INPUT = 60
    INTERNAL_FAILURE = 70


class DocumentEnhancerError(Exception):
    """Base error with a stable exit code and safe user-facing message."""

    exit_code = ExitCode.INTERNAL_FAILURE

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ConfigurationError(DocumentEnhancerError):
    exit_code = ExitCode.CONFIGURATION_FAILURE


class ValidationError(DocumentEnhancerError):
    exit_code = ExitCode.VALIDATION_FAILURE


class UnsupportedInputError(DocumentEnhancerError):
    exit_code = ExitCode.UNSUPPORTED_INPUT


class ProviderError(DocumentEnhancerError):
    exit_code = ExitCode.PROVIDER_FAILURE


class AuditError(DocumentEnhancerError):
    exit_code = ExitCode.AUDIT_FAILURE


class WaitingForReviewError(DocumentEnhancerError):
    exit_code = ExitCode.WAITING_FOR_REVIEW


class ContractNotImplementedError(DocumentEnhancerError):
    """A later-milestone command was requested before its implementation lane merged."""

    exit_code = ExitCode.CONFIGURATION_FAILURE
