from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from document_enhancer.domain.ontology import Relationship
from document_enhancer.domain.provenance import Provenance
from document_enhancer.domain.questions import QuestionsArtifact
from document_enhancer.domain.schema_registry import schema_models
from document_enhancer.domain.serialization import model_from_json, model_from_yaml

ROOT = Path(__file__).resolve().parents[2]


def test_checked_in_schemas_match_pydantic_generation() -> None:
    for filename, model in schema_models().items():
        path = ROOT / "schemas" / filename
        assert path.exists(), filename
        expected = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        assert path.read_text(encoding="utf-8") == expected, filename


def test_schemas_are_json_objects_with_closed_critical_roots() -> None:
    for filename in schema_models():
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        assert schema["type"] == "object", filename
        assert schema["additionalProperties"] is False, filename


def test_structure_recovery_schema_declares_typed_python_character_segments() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "structure-recovery.schema.json").read_text(encoding="utf-8")
    )
    segment = schema["$defs"]["BlockSegment"]
    assert segment["additionalProperties"] is False
    assert {"char_start", "char_end", "offset_unit", "slice_sha256"} <= set(segment["properties"])
    assert segment["properties"]["segment_id"]["pattern"] == r"^SEG-[A-F0-9]{16}$"
    assert segment["properties"]["offset_unit"]["const"] == "python_characters"
    disposition = schema["$defs"]["BlockDisposition"]
    segments_schema = disposition["properties"]["segments"]["anyOf"][0]
    assert segments_schema["minItems"] == 2


def test_valid_yaml_fixture_round_trips_and_negative_fixtures_fail() -> None:
    fixtures = ROOT / "tests" / "contract" / "fixtures"
    questions = model_from_yaml(
        QuestionsArtifact,
        (fixtures / "questions.valid.yaml").read_text(encoding="utf-8"),
    )
    assert questions.questions[0].question_id == "Q-FIXTURE-001"
    with pytest.raises(ValidationError):
        model_from_json(
            QuestionsArtifact,
            (fixtures / "questions.unknown-field.json").read_text(encoding="utf-8"),
        )
    with pytest.raises(ValidationError):
        model_from_json(
            Relationship,
            (fixtures / "relationship.related-to.json").read_text(encoding="utf-8"),
        )
    with pytest.raises(ValidationError):
        model_from_json(
            Provenance,
            (fixtures / "provenance.temporal-invalid.json").read_text(encoding="utf-8"),
        )
