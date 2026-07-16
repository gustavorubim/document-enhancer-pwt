"""LangGraph-compatible state and durable workflow snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from pydantic import Field, StrictBool, StrictStr

from document_enhancer.domain.base import StrictModel


class WorkflowState(TypedDict, total=False):
    run_id: str
    source_path: str
    source_digest: str
    document_id: str
    document_type: str
    status: Literal["created", "running", "waiting", "succeeded", "failed"]
    current_stage: str
    resume_entry: str
    next_action: str
    completed_stages: list[str]
    cache_keys: dict[str, str]
    stage_inputs: dict[str, object]
    raw: object
    normalized: object
    structure_result: object
    analysis_result: object
    questions: object
    answers: object
    steering: object
    waivers: object
    checklist: object
    validation_report: object
    content_ledger: object
    rewrite_inputs: object
    enhanced_model: object
    semantic_document: object
    mermaid_validation: object
    revision_counters: object
    errors: list[str]
    stop_after: str | None
    gate2_enabled: bool
    offline: bool


class WorkflowSnapshot(StrictModel):
    """JSON-safe state stored beside the run artifacts after every transition."""

    schema_version: StrictStr = "m5.workflow-state.v1"
    run_id: StrictStr
    status: Literal["created", "running", "waiting", "succeeded", "failed"]
    current_stage: StrictStr
    next_action: StrictStr
    source_path: StrictStr
    source_digest: StrictStr
    document_id: StrictStr | None = None
    document_type: StrictStr = "process"
    completed_stages: list[StrictStr] = Field(default_factory=list)
    cache_keys: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    stage_inputs: dict[StrictStr, object] = Field(default_factory=dict)
    state: dict[StrictStr, object] = Field(default_factory=dict)
    errors: list[StrictStr] = Field(default_factory=list)
    gate2_enabled: StrictBool = True
    offline: StrictBool = True

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> WorkflowSnapshot:
        data = _json_safe(dict(state))
        transient = {
            "run_id": data.get("run_id", ""),
            "status": data.get("status", "created"),
            "current_stage": data.get("current_stage", "raw_ingest"),
            "next_action": data.get("next_action", "run the next stage"),
            "source_path": data.get("source_path", ""),
            "source_digest": data.get("source_digest", ""),
            "document_id": data.get("document_id"),
            "document_type": data.get("document_type", "process"),
            "completed_stages": data.get("completed_stages", []),
            "cache_keys": data.get("cache_keys", {}),
            "stage_inputs": data.get("stage_inputs", {}),
            "errors": data.get("errors", []),
            "gate2_enabled": data.get("gate2_enabled", True),
            "offline": data.get("offline", True),
        }
        return cls(state=data, **transient)

    def to_state(self) -> WorkflowState:
        return cast(WorkflowState, dict(self.state))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if hasattr(value, "value") and isinstance(value.value, (str, int, float, bool)):
        return value.value
    return value


def state_json(value: Any) -> Any:
    """Expose the safe conversion for tests and artifact writers."""

    return _json_safe(value)


__all__ = ["WorkflowSnapshot", "WorkflowState", "state_json"]
