"""Logging contract: diagnostics to stderr, structured values redacted."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

_SECRET_PATTERN = re.compile(
    r"(?i)(google_api_key|gemini_api_key|api[_-]?key|access[_-]?token|secret|password)"
    r"\s*[:=]\s*([\"']?)([^\s,\"']+)\2"
)
_TOKEN_PATTERN = re.compile(r"\b(?:AIza[0-9A-Za-z_-]{20,}|ya29\.[0-9A-Za-z_-]+)\b")


def redact(value: object) -> str:
    text = str(value)
    text = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return _TOKEN_PATTERN.sub("[REDACTED]", text)


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(argument) for argument in record.args)
        return True


def configure_logging(*, verbose: bool = False) -> None:
    """Configure one stderr handler; callers should log metadata, never source text."""

    root = logging.getLogger("document_enhancer")
    root.handlers.clear()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(RedactionFilter())
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"document_enhancer.{name}")


def safe_event(name: str, **fields: Any) -> dict[str, str]:
    """Create a redacted event payload suitable for future JSONL event logs."""

    sensitive_names = {"api_key", "gemini_api_key", "google_api_key", "token", "secret", "password"}
    return {
        "event": redact(name),
        **{
            key: "[REDACTED]" if key.lower() in sensitive_names else redact(value)
            for key, value in fields.items()
        },
    }
