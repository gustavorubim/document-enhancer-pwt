"""Safe, deterministic persistence for M5 reviewer artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from document_enhancer.artifacts.atomic import atomic_write_bytes, digest_file
from document_enhancer.domain.questions import (
    AnswersArtifact,
    QuestionsArtifact,
    RewriteChecklist,
    Steering,
    WaiversArtifact,
)
from document_enhancer.domain.serialization import model_from_yaml, model_to_yaml

from .rendering import render_checklist_markdown, render_questions_markdown


def _digest_model(model: BaseModel) -> str:
    value = model.model_dump(mode="json", exclude={"digest"})
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def with_digest[ModelT: BaseModel](model: ModelT) -> ModelT:
    if "digest" not in type(model).model_fields:
        return model
    return model.model_copy(update={"digest": _digest_model(model)})


def write_yaml_if_missing(path: Path, model: BaseModel) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return digest_file(path)
    return atomic_write_bytes(path, model_to_yaml(model).encode("utf-8"))


def write_yaml(path: Path, model: BaseModel, *, replace: bool = True) -> str:
    if path.exists() and not replace:
        return digest_file(path)
    return atomic_write_bytes(path, model_to_yaml(model).encode("utf-8"))


def write_questions_artifacts(
    directory: Path,
    questions: QuestionsArtifact,
    *,
    answers: AnswersArtifact | None = None,
    steering: Steering | None = None,
    waivers: WaiversArtifact | None = None,
) -> dict[str, str]:
    """Write the authoritative question YAML and all editable reviewer surfaces."""

    directory.mkdir(parents=True, exist_ok=True)
    questions = with_digest(questions)
    paths: dict[str, str] = {}
    question_yaml = directory / "questions.yaml"
    question_md = directory / "questions.md"
    paths["clarification/questions.yaml"] = write_yaml(question_yaml, questions)
    paths["clarification/questions.md"] = atomic_write_bytes(
        question_md, render_questions_markdown(questions).encode("utf-8")
    )
    if answers is not None:
        paths["clarification/answers.yaml"] = write_yaml_if_missing(
            directory / "answers.yaml", answers
        )
    if steering is not None:
        paths["clarification/steering.yaml"] = write_yaml_if_missing(
            directory / "steering.yaml", steering
        )
    if waivers is not None:
        paths["clarification/waivers.yaml"] = write_yaml_if_missing(
            directory / "waivers.yaml", waivers
        )
    return paths


def write_checklist_artifacts(directory: Path, checklist: RewriteChecklist) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    checklist = with_digest(checklist)
    return {
        "clarification/rewrite-checklist.yaml": write_yaml(
            directory / "rewrite-checklist.yaml", checklist
        ),
        "clarification/rewrite-checklist.md": atomic_write_bytes(
            directory / "rewrite-checklist.md", render_checklist_markdown(checklist).encode("utf-8")
        ),
    }


def load_yaml[ModelT: BaseModel](path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        return model_from_yaml(model_type, path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"unable to load {path}: {exc}") from exc


__all__ = [
    "load_yaml",
    "with_digest",
    "write_checklist_artifacts",
    "write_questions_artifacts",
    "write_yaml",
    "write_yaml_if_missing",
]
