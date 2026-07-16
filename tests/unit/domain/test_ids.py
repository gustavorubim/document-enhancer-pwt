from __future__ import annotations

import pytest

from document_enhancer.domain.enums import EntityType
from document_enhancer.domain.ids import (
    allocate_provisional_id,
    allocate_span_id,
    ensure_unique_ids,
    validate_entity_id,
)


def test_provisional_ids_are_deterministic_and_unique_against_existing() -> None:
    first = allocate_provisional_id(EntityType.PROCESS, "Monthly loss forecast", namespace="acme")
    second = allocate_provisional_id(
        EntityType.PROCESS,
        "Monthly loss forecast",
        namespace="acme",
        existing_ids=[first],
    )
    assert first == allocate_provisional_id(
        EntityType.PROCESS, "Monthly loss forecast", namespace="acme"
    )
    assert first.startswith("PROV-PROC-MONTHLY-LOSS-FORECAST-")
    assert second != first
    validate_entity_id(first, EntityType.PROCESS)


def test_span_id_is_stable_for_same_source_position_and_text() -> None:
    digest = "a" * 64
    assert allocate_span_id(digest, 3, "paragraph", "same") == allocate_span_id(
        digest, 3, "paragraph", "same"
    )
    assert allocate_span_id(digest, 3, "paragraph", "same") != allocate_span_id(
        digest, 4, "paragraph", "same"
    )


def test_entity_id_and_uniqueness_fail_precisely() -> None:
    with pytest.raises(ValueError, match="prefix"):
        validate_entity_id("CTRL-DQ-027", EntityType.PROCESS)
    with pytest.raises(ValueError, match="duplicate IDs"):
        ensure_unique_ids(["PROC-A-001", "PROC-A-001"])
