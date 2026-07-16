"""Gemini-native JSON-schema validation and Pydantic promotion boundaries."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from pydantic import BaseModel, TypeAdapter

ArtifactT = TypeVar("ArtifactT")

_ALLOWED_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "items",
    "properties",
    "required",
    "propertyOrdering",
    "anyOf",
    "minItems",
    "maxItems",
    "minProperties",
    "maxProperties",
}
_METADATA_KEYS = {
    "$schema",
    "$defs",
    "definitions",
    "title",
    "default",
    "examples",
    "additionalProperties",
}


class GeminiSchemaError(ValueError):
    """Raised before a provider call when a schema exceeds Gemini's subset."""


class StructuredOutputError(ValueError):
    """Raised when no bounded native-JSON response validates against the schema."""


def schema_for(model: type[Any] | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(model, Mapping):
        return copy.deepcopy(dict(model))
    if isinstance(model, type) and issubclass(model, BaseModel):
        return model.model_json_schema()
    try:
        return TypeAdapter(model).json_schema()
    except Exception as exc:
        raise GeminiSchemaError(f"unable to derive a Pydantic JSON schema: {exc}") from exc


def _resolve_ref(node: Any, root: Mapping[str, Any], stack: tuple[str, ...]) -> Any:
    if isinstance(node, list):
        return [_resolve_ref(item, root, stack) for item in node]
    if not isinstance(node, Mapping):
        return node
    ref = node.get("$ref")
    if ref is None:
        return {key: _resolve_ref(value, root, stack) for key, value in node.items()}
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        raise GeminiSchemaError(f"unsupported schema reference: {ref!r}")
    name = ref.removeprefix("#/$defs/")
    if name in stack:
        raise GeminiSchemaError(
            f"recursive schema is not supported by native Gemini JSON schema: {name}"
        )
    definitions = root.get("$defs", {})
    if not isinstance(definitions, Mapping) or name not in definitions:
        raise GeminiSchemaError(f"unresolved schema reference: {ref}")
    resolved = _resolve_ref(definitions[name], root, (*stack, name))
    extras = {key: value for key, value in node.items() if key != "$ref"}
    if extras and isinstance(resolved, Mapping):
        merged = dict(resolved)
        merged.update(_resolve_ref(extras, root, stack))
        return merged
    return resolved


def _normalize_nullable(node: dict[str, Any]) -> dict[str, Any]:
    any_of = node.get("anyOf")
    if not isinstance(any_of, list):
        return node
    non_null = [item for item in any_of if isinstance(item, Mapping) and item.get("type") != "null"]
    has_null = len(non_null) != len(any_of)
    if has_null and len(non_null) == 1 and isinstance(non_null[0], Mapping):
        result = dict(non_null[0])
        result["nullable"] = True
        for key in ("description", "title"):
            if key in node and key not in result:
                result[key] = node[key]
        return result
    return node


def _validate_node(node: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise GeminiSchemaError(f"schema node at {path} must be an object")
    node = _normalize_nullable(dict(node))
    unknown = set(node) - _ALLOWED_KEYS - _METADATA_KEYS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise GeminiSchemaError(f"unsupported Gemini schema keyword(s) at {path}: {names}")
    if node.get("additionalProperties") not in (None, False):
        raise GeminiSchemaError(f"additionalProperties=true is unsupported at {path}")
    result = {key: value for key, value in node.items() if key not in _METADATA_KEYS}
    node_type = result.get("type")
    if node_type not in {"object", "array", "string", "number", "integer", "boolean", None}:
        raise GeminiSchemaError(f"unsupported Gemini schema type at {path}: {node_type!r}")
    if node_type == "object":
        properties = result.get("properties", {})
        if not isinstance(properties, Mapping):
            raise GeminiSchemaError(f"object properties at {path} must be an object")
        result["properties"] = {
            str(name): _validate_node(value, path=f"{path}.properties.{name}")
            for name, value in properties.items()
        }
        required = result.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise GeminiSchemaError(f"required at {path} must be a list of strings")
        unknown_required = set(required) - set(result["properties"])
        if unknown_required:
            raise GeminiSchemaError(
                f"required fields not in properties at {path}: {sorted(unknown_required)}"
            )
    if node_type == "array" and "items" in result:
        result["items"] = _validate_node(result["items"], path=f"{path}.items")
    if "anyOf" in result:
        if not isinstance(result["anyOf"], list) or not result["anyOf"]:
            raise GeminiSchemaError(f"anyOf at {path} must be a non-empty list")
        result["anyOf"] = [
            _validate_node(item, path=f"{path}.anyOf[{index}]")
            for index, item in enumerate(result["anyOf"])
        ]
    return result


def gemini_schema(model: type[Any] | Mapping[str, Any]) -> dict[str, Any]:
    """Return a dereferenced schema accepted by Gemini's native JSON mode."""

    raw = schema_for(model)
    resolved = _resolve_ref(raw, raw, ())
    normalized = _validate_node(resolved, path="$")
    if normalized.get("type") != "object":
        raise GeminiSchemaError("Gemini native structured output requires an object root schema")
    return normalized


def validate_artifact[ArtifactT](schema: type[ArtifactT], value: object) -> ArtifactT:
    """Promote only a schema-validated object; never return unstructured output."""

    try:
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return cast(ArtifactT, schema.model_validate(value))
        return TypeAdapter(schema).validate_python(value)
    except Exception as exc:
        raise StructuredOutputError(
            f"structured response failed Pydantic validation: {type(exc).__name__}"
        ) from exc


def artifact_json(schema: type[Any], value: object) -> dict[str, Any]:
    artifact = validate_artifact(schema, value)
    if isinstance(artifact, BaseModel):
        return artifact.model_dump(mode="json")
    dumped = TypeAdapter(schema).dump_python(artifact, mode="json")
    if not isinstance(dumped, dict):
        raise StructuredOutputError("structured artifact must serialize to a JSON object")
    return dumped
