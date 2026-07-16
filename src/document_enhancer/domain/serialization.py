"""Deterministic JSON/YAML serialization helpers for persisted contracts."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from pydantic import BaseModel
from ruamel.yaml import YAML


def model_to_data(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json", exclude_none=False)


def model_to_json(model: BaseModel, *, indent: int = 2) -> str:
    return json.dumps(model_to_data(model), indent=indent, sort_keys=True) + "\n"


def model_from_json[ModelT: BaseModel](model_type: type[ModelT], text: str) -> ModelT:
    return model_type.model_validate_json(text)


def model_to_yaml(model: BaseModel) -> str:
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    stream = StringIO()
    yaml.dump(model_to_data(model), stream)
    return stream.getvalue()


def model_from_yaml[ModelT: BaseModel](model_type: type[ModelT], text: str) -> ModelT:
    yaml = YAML(typ="safe")
    data = yaml.load(text)
    if not isinstance(data, dict):
        raise ValueError("artifact YAML root must be a mapping")
    return model_type.model_validate(data)


def write_json(path: Path, model: BaseModel) -> None:
    path.write_text(model_to_json(model), encoding="utf-8")


def write_yaml(path: Path, model: BaseModel) -> None:
    path.write_text(model_to_yaml(model), encoding="utf-8")


__all__ = [
    "model_from_json",
    "model_from_yaml",
    "model_to_data",
    "model_to_json",
    "model_to_yaml",
    "write_json",
    "write_yaml",
]
