from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from document_enhancer.domain.analysis import SectionMapping
from document_enhancer.domain.serialization import (
    model_from_json,
    model_from_yaml,
    model_to_json,
    model_to_yaml,
)


def _mapping(*, disposition: str = "preserved", **values: Any) -> SectionMapping:
    payload: dict[str, Any] = {
        "source_span_ids": ["SPAN-ABCDEFGH"],
        "disposition": disposition,
    }
    payload.update(values)
    return SectionMapping.model_validate(payload)


def test_section_mapping_supports_one_multiple_and_explicit_none() -> None:
    one = _mapping(target_section_ids=["SEC-ONE"])
    multiple = _mapping(target_section_ids=["SEC-ONE", "SEC-TWO"])
    none = _mapping(target_section_ids=[], disposition="omitted")

    assert one.target_section_ids == ["SEC-ONE"]
    assert one.target_section_id == "SEC-ONE"
    assert multiple.target_section_ids == ["SEC-ONE", "SEC-TWO"]
    assert multiple.target_section_id is None
    assert none.target_section_ids == []
    assert none.target_section_id is None


def test_section_mapping_defaults_and_serializes_explicit_empty_targets() -> None:
    mapping = _mapping(disposition="omitted")

    assert mapping.target_section_ids == []
    assert mapping.model_dump()["target_section_ids"] == []
    assert '"target_section_ids": []' in model_to_json(mapping)
    assert "target_section_ids: []" in model_to_yaml(mapping)


def test_legacy_singular_input_normalizes_to_canonical_plural_field() -> None:
    legacy = _mapping(target_section_id="SEC-LEGACY")
    legacy_none = _mapping(target_section_id=None, disposition="omitted")
    consistent = _mapping(
        target_section_id="SEC-LEGACY",
        target_section_ids=["SEC-LEGACY"],
    )
    consistent_none = _mapping(target_section_id=None, target_section_ids=[])

    assert legacy.target_section_ids == ["SEC-LEGACY"]
    assert legacy_none.target_section_ids == []
    assert consistent.target_section_ids == ["SEC-LEGACY"]
    assert consistent_none.target_section_ids == []
    assert "target_section_id" not in legacy.model_dump()
    assert legacy.model_dump()["target_section_ids"] == ["SEC-LEGACY"]


def test_section_mapping_json_yaml_round_trip_uses_plural_canonical_name() -> None:
    mapping = _mapping(target_section_ids=["SEC-ONE", "SEC-TWO"], rationale="shared source")

    json_text = model_to_json(mapping)
    yaml_text = model_to_yaml(mapping)
    assert "target_section_ids" in json_text
    assert "target_section_id:" not in yaml_text
    assert model_from_json(SectionMapping, json_text).model_dump() == mapping.model_dump()
    assert model_from_yaml(SectionMapping, yaml_text).model_dump() == mapping.model_dump()


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {"target_section_id": "SEC-ONE", "target_section_ids": ["SEC-TWO"]},
            "conflicting",
        ),
        (
            {"target_section_ids": ["SEC-ONE", "SEC-ONE"]},
            "unique IDs",
        ),
        ({"target_section_ids": ["   "]}, "must not be blank"),
    ],
)
def test_section_mapping_rejects_conflicts_duplicates_and_blanks(
    values: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _mapping(**values)


@pytest.mark.parametrize(
    "values",
    [
        {"target_section_ids": "SEC-ONE"},
        {"target_section_ids": [1]},
        {"target_section_id": ["SEC-ONE"]},
    ],
)
def test_section_mapping_rejects_invalid_target_shapes(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _mapping(**values)


@pytest.mark.parametrize(
    "disposition",
    ["preserved", "moved", "merged", "split", "omitted", "uncertain", "blocking"],
)
def test_section_mapping_accepts_only_canonical_dispositions(disposition: str) -> None:
    assert _mapping(disposition=disposition).disposition.value == disposition


@pytest.mark.parametrize("disposition", ["mapped", "unmapped", "retain", "blocked", "other"])
def test_section_mapping_rejects_noncanonical_dispositions(disposition: str) -> None:
    with pytest.raises(ValidationError, match="disposition"):
        _mapping(disposition=disposition)
