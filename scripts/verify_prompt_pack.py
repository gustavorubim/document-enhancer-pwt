#!/usr/bin/env python3
"""Verify a versioned prompt pack, its references, golden compositions, and fake outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from document_enhancer.config import yaml_parser
from document_enhancer.domain.schema_registry import schema_models
from document_enhancer.prompting.composer import PromptPackComposer
from document_enhancer.prompting.errors import PromptPackValidationError
from document_enhancer.prompting.loader import load_prompt_pack
from document_enhancer.prompting.validator import validate_prompt_pack
from document_enhancer.references.loader import load_reference_pack


def _value_for(variable: Any, document_type: str) -> Any:
    if variable.name == "document_type":
        return document_type
    if variable.value_type.lower() in {"mapping", "object", "dict", "json"}:
        return {}
    if variable.name in {"question"}:
        return "Which supplied evidence answers the question?"
    if variable.name == "target_section":
        return "Purpose"
    if variable.default is not None:
        return variable.default
    if variable.value_type.lower() in {"int", "integer"}:
        return 1
    if variable.value_type.lower() in {"bool", "boolean"}:
        return False
    return "GOLDEN DATA ONLY"


def _verify_fake_outputs(pack_root: Path) -> list[str]:
    path = pack_root / "golden" / "fake_outputs.json"
    if not path.is_file():
        return ["golden/fake_outputs.json is missing"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"golden/fake_outputs.json is invalid: {exc}"]
    errors: list[str] = []
    models = schema_models()
    for schema_name, value in payload.items():
        model = models.get(schema_name)
        if model is None:
            errors.append(f"golden fake output uses unknown schema: {schema_name}")
            continue
        try:
            model.model_validate(value)
        except Exception as exc:  # Pydantic's nested locations are useful in the report.
            errors.append(f"golden fake output for {schema_name} is not schema-valid: {exc}")
    return errors


def _verify_compositions(pack_root: Path, reference_pack: Any) -> tuple[list[str], dict[str, int]]:
    path = pack_root / "golden" / "compositions.yaml"
    if not path.is_file():
        return ["golden/compositions.yaml is missing"], {}
    try:
        value = yaml_parser().load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"golden/compositions.yaml is invalid: {exc}"], {}
    if not isinstance(value, dict) or not isinstance(value.get("document_types"), dict):
        return ["golden/compositions.yaml must contain document_types"], {}
    expected_scopes = value.get("reference_scopes")
    if not isinstance(expected_scopes, dict):
        return ["golden/compositions.yaml must contain reference_scopes"], {}
    try:
        pack = load_prompt_pack(pack_root, reference_pack=reference_pack)
    except PromptPackValidationError as exc:
        return list(exc.errors), {}
    prompt_ids = {prompt.prompt_id for prompt in pack.manifest.prompts}
    missing_scopes = sorted(prompt_ids - set(expected_scopes))
    unknown_scopes = sorted(set(expected_scopes) - prompt_ids)
    if missing_scopes:
        errors = [
            "golden/compositions.yaml is missing reference scopes for: " + ", ".join(missing_scopes)
        ]
    else:
        errors = []
    if unknown_scopes:
        errors.append(
            "golden/compositions.yaml has unknown reference scopes for: "
            + ", ".join(unknown_scopes)
        )
    composer = PromptPackComposer(pack, reference_pack=reference_pack)
    counts: dict[str, int] = {}
    for document_type, entry in value["document_types"].items():
        if not isinstance(entry, dict) or not isinstance(entry.get("prompt_ids"), list):
            errors.append(f"golden document type {document_type} is malformed")
            continue
        expected_routes = set(entry.get("model_families", ()))
        counts[document_type] = 0
        for prompt_id in entry["prompt_ids"]:
            try:
                spec = pack.prompt(prompt_id)
                if spec.model_route not in expected_routes:
                    errors.append(
                        f"golden {document_type}/{prompt_id}: route {spec.model_route} is not listed"
                    )
                    continue
                variables = {
                    variable.name: _value_for(variable, str(document_type))
                    for variable in spec.variables
                }
                composed = composer.compose_with_metadata(prompt_id, variables)
                expected_scope = expected_scopes.get(prompt_id)
                if expected_scope != list(composed.reference_scope):
                    errors.append(
                        f"golden {document_type}/{prompt_id}: reference scope does not match"
                    )
                required_markers = (
                    "BEGIN GOVERNED INSTRUCTIONS",
                    "BEGIN GOVERNED CONTEXT",
                    "BEGIN UNTRUSTED SOURCE",
                    "BEGIN REVIEWER INPUTS",
                    "BEGIN OUTPUT CONTRACT",
                )
                if not all(marker in composed.text for marker in required_markers):
                    errors.append(f"golden {document_type}/{prompt_id}: missing visible boundary")
                if "GOLDEN DATA ONLY" in composed.text:
                    assert "BEGIN UNTRUSTED SOURCE" in composed.text
                counts[document_type] += 1
            except Exception as exc:
                errors.append(f"golden {document_type}/{prompt_id}: {type(exc).__name__}: {exc}")
    return errors, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt_pack", type=Path)
    parser.add_argument("--reference-pack", type=Path)
    args = parser.parse_args(argv)
    reference_pack = None
    if args.reference_pack is not None:
        try:
            reference_pack = load_reference_pack(args.reference_pack)
        except Exception as exc:
            print(json.dumps({"ok": False, "errors": [f"reference pack: {exc}"]}, indent=2))
            return 1
    report = validate_prompt_pack(args.prompt_pack, reference_pack=reference_pack)
    errors = list(report.errors)
    counts: dict[str, int] = {}
    if report.ok:
        errors.extend(_verify_fake_outputs(args.prompt_pack))
        if reference_pack is not None:
            composition_errors, counts = _verify_compositions(args.prompt_pack, reference_pack)
            errors.extend(composition_errors)
    result = {
        "ok": not errors,
        "errors": errors,
        "details": report.details,
        "golden_compositions": counts,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
