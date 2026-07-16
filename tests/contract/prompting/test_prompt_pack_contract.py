from __future__ import annotations

import json
from pathlib import Path

from document_enhancer.domain.schema_registry import schema_models
from document_enhancer.prompting.loader import load_prompt_pack
from document_enhancer.prompting.validator import (
    EXPECTED_ROUTES,
    EXPECTED_SCHEMAS,
    validate_prompt_pack,
)
from document_enhancer.references.loader import load_reference_pack

ROOT = Path(__file__).resolve().parents[3]


def test_gemini_core_prompt_inventory_matches_frozen_routes_and_schemas() -> None:
    pack = load_prompt_pack(
        ROOT / "prompt_packs" / "gemini_core",
        reference_pack=load_reference_pack(ROOT / "reference_packs" / "enterprise_core"),
    )
    assert {prompt.prompt_id for prompt in pack.manifest.prompts} == set(EXPECTED_ROUTES)
    for prompt in pack.manifest.prompts:
        assert prompt.model_route == EXPECTED_ROUTES[prompt.prompt_id]
        assert prompt.output_schema == EXPECTED_SCHEMAS[prompt.prompt_id]
        assert prompt.output_schema in schema_models()


def test_golden_fake_outputs_validate_against_the_same_schema_roots() -> None:
    fake_path = ROOT / "prompt_packs" / "gemini_core" / "golden" / "fake_outputs.json"
    payload = json.loads(fake_path.read_text(encoding="utf-8"))
    for schema_name, value in payload.items():
        schema_models()[schema_name].model_validate(value)


def test_reference_compatibility_report_records_all_document_types() -> None:
    report = validate_prompt_pack(
        ROOT / "prompt_packs" / "gemini_core",
        reference_pack=ROOT / "reference_packs" / "enterprise_core",
    )
    assert report.ok
    assert set(report.details["resolved_references"]) == {
        "process",
        "methodology",
        "standard",
        "desktop_procedure",
    }
