"""Pure routing policies for the resumable M5 graph."""

from __future__ import annotations

from collections.abc import Mapping

from document_enhancer.domain.questions import QuestionsArtifact, RewriteChecklist


def structure_recovery_required(state: Mapping[str, object]) -> bool:
    result = state.get("structure_result")
    if isinstance(result, Mapping):
        metadata = result.get("metadata")
        if isinstance(metadata, Mapping):
            return str(metadata.get("status", "")) in {"recovered", "failed"}
        validation = result.get("validation")
        if isinstance(validation, Mapping):
            return str(validation.get("scope", "")) == "full"
    normalized = state.get("normalized")
    if isinstance(normalized, Mapping):
        routing = normalized.get("routing")
        return isinstance(routing, Mapping) and routing.get("mode") == "llm_recovery"
    return False


def gate1_required(
    questions: QuestionsArtifact,
    *,
    stop_after: str | None = None,
) -> bool:
    return stop_after == "questions" or bool(
        questions.questions and any(item.blocking for item in questions.questions)
    )


def gate1_satisfied(state: Mapping[str, object]) -> bool:
    questions = state.get("questions")
    if not isinstance(questions, QuestionsArtifact):
        return False
    if not any(item.blocking for item in questions.questions):
        return True
    validation = state.get("validation_report")
    if isinstance(validation, Mapping):
        return bool(validation.get("valid"))
    return bool(getattr(validation, "valid", False))


def gate2_required(state: Mapping[str, object]) -> bool:
    if state.get("stop_after") == "checklist":
        return True
    if not bool(state.get("gate2_enabled", True)):
        return False
    checklist = state.get("checklist")
    if isinstance(checklist, RewriteChecklist):
        return bool(checklist.items)
    return bool(isinstance(checklist, Mapping) and checklist.get("items"))


def gate2_satisfied(state: Mapping[str, object]) -> bool:
    checklist = state.get("checklist")
    return bool(
        isinstance(checklist, RewriteChecklist) and checklist.approved_by and checklist.approved_at
    )


def next_action(state: Mapping[str, object]) -> str:
    stage = str(state.get("current_stage", "raw_ingest"))
    if stage == "gate1":
        return "Edit clarification/answers.yaml, steering.yaml, and waivers.yaml, then run docenhance resume."
    if stage == "gate2":
        return "Review clarification/rewrite-checklist.yaml, record approval or waivers, then run docenhance resume."
    if stage in {"succeeded", "complete"} or state.get("status") == "succeeded":
        return "No action required; the run is complete."
    return f"Run the {stage} stage or resume the persisted task."


__all__ = [
    "gate1_required",
    "gate1_satisfied",
    "gate2_required",
    "gate2_satisfied",
    "next_action",
    "structure_recovery_required",
]
