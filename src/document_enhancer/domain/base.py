"""Shared strict Pydantic primitives for domain artifacts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

JsonValue = Any


class StrictModel(BaseModel):
    """Base class used by every persisted contract.

    ``extra='forbid'`` is deliberate: an artifact cannot silently accept a new
    critical field. Forward-compatible additions must be represented by an
    explicit ``extensions`` field in the relevant contract.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
        validate_default=True,
        use_enum_values=False,
    )


NonEmptyString = StrictStr
PositiveInt = StrictInt
NonNegativeInt = StrictInt
Probability = StrictFloat
StrictDate = date
StrictDateTime = datetime


def non_empty(value: StrictStr, *, field_name: str = "value") -> StrictStr:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def validate_probability(value: StrictFloat | None) -> StrictFloat | None:
    if value is not None and not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return value


__all__ = [
    "ConfigDict",
    "Field",
    "JsonValue",
    "NonEmptyString",
    "PositiveInt",
    "NonNegativeInt",
    "Probability",
    "StrictBool",
    "StrictDate",
    "StrictDateTime",
    "StrictFloat",
    "StrictInt",
    "StrictModel",
    "StrictStr",
    "non_empty",
    "validate_probability",
]
