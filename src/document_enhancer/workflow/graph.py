"""Compiled LangGraph workflow plus process-boundary run/resume facade."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from pydantic import Field, StrictInt, StrictStr

from document_enhancer.artifacts.paths import RunPaths
from document_enhancer.domain.base import StrictModel
from document_enhancer.errors import DocumentEnhancerError, ValidationError, WaitingForReviewError

from .nodes import (
    WorkflowServices,
    analysis_node,
    checklist_node,
    complete_node,
    gate1_node,
    gate2_node,
    normalize_node,
    question_synthesis_node,
    raw_ingest_node,
    selected_view_node,
    structure_quality_node,
    structure_recovery_node,
    structure_scan_node,
    structure_validate_node,
)
from .routing import gate1_satisfied, next_action, structure_recovery_required
from .state import WorkflowSnapshot, WorkflowState


class WorkflowResult(StrictModel):
    schema_version: StrictStr = "m5.workflow-result.v1"
    run_id: StrictStr
    status: Literal["created", "running", "waiting", "succeeded", "failed"]
    current_stage: StrictStr
    next_action: StrictStr
    exit_code: StrictInt
    errors: list[StrictStr] = Field(default_factory=list)
    completed_stages: list[StrictStr] = Field(default_factory=list)
    cache_keys: dict[StrictStr, StrictStr] = Field(default_factory=dict)


def _entry_route(state: WorkflowState) -> str:
    value = state.get("resume_entry") or state.get("current_stage") or "raw_ingest"
    if value in {"succeeded", "complete"} or state.get("status") == "succeeded":
        return "complete"
    return str(value)


def _structure_route(state: WorkflowState) -> str:
    return "structure_recovery" if structure_recovery_required(state) else "structure_validate"


def _gate1_route(state: WorkflowState) -> str:
    return "checklist" if gate1_satisfied(state) else "gate1"


def _gate2_route(state: WorkflowState) -> str:
    return "complete"


def _node_call(
    function: Callable[[WorkflowState, WorkflowServices], WorkflowState], services: WorkflowServices
) -> Callable[[WorkflowState], WorkflowState]:
    def call(state: WorkflowState) -> WorkflowState:
        return function(state, services)

    return call


def build_graph(services: WorkflowServices):
    """Build a graph with explicit conditional routes and a testable injected service boundary."""

    # LangGraph's generic TypedDict protocol is stricter than the runtime state adapter used by
    # this repository; the injected node boundary is intentionally validated by our own durable
    # snapshot model and workflow tests.
    builder = cast(Any, StateGraph(cast(Any, WorkflowState)))
    builder.add_node("raw_ingest", _node_call(raw_ingest_node, services))
    builder.add_node("normalize", _node_call(normalize_node, services))
    builder.add_node("structure_quality", _node_call(structure_quality_node, services))
    builder.add_node("structure_scan", _node_call(structure_scan_node, services))
    builder.add_node("structure_recovery", _node_call(structure_recovery_node, services))
    builder.add_node("structure_validate", _node_call(structure_validate_node, services))
    builder.add_node("selected_view", _node_call(selected_view_node, services))
    builder.add_node("analysis", _node_call(analysis_node, services))
    builder.add_node("question_synthesis", _node_call(question_synthesis_node, services))
    builder.add_node("gate1", _node_call(gate1_node, services))
    builder.add_node("checklist", _node_call(checklist_node, services))
    builder.add_node("gate2", _node_call(gate2_node, services))
    builder.add_node("complete", _node_call(complete_node, services))

    builder.add_conditional_edges(
        START,
        _entry_route,
        {
            "raw_ingest": "raw_ingest",
            "normalize": "normalize",
            "structure_quality": "structure_quality",
            "structure_scan": "structure_scan",
            "structure_recovery": "structure_recovery",
            "structure_validate": "structure_validate",
            "selected_view": "selected_view",
            "analysis": "analysis",
            "question_synthesis": "question_synthesis",
            "gate1": "gate1",
            "checklist": "checklist",
            "gate2": "gate2",
            "complete": "complete",
        },
    )
    builder.add_edge("raw_ingest", "normalize")
    builder.add_edge("normalize", "structure_quality")
    builder.add_edge("structure_quality", "structure_scan")
    builder.add_conditional_edges(
        "structure_scan",
        _structure_route,
        {"structure_recovery": "structure_recovery", "structure_validate": "structure_validate"},
    )
    builder.add_edge("structure_recovery", "structure_validate")
    builder.add_edge("structure_validate", "selected_view")
    builder.add_edge("selected_view", "analysis")
    builder.add_edge("analysis", "question_synthesis")
    builder.add_edge("question_synthesis", "gate1")
    builder.add_conditional_edges(
        "gate1", _gate1_route, {"gate1": "gate1", "checklist": "checklist"}
    )
    builder.add_edge("checklist", "gate2")
    builder.add_conditional_edges("gate2", _gate2_route, {"complete": "complete"})
    builder.add_edge("complete", END)
    return builder.compile(checkpointer=InMemorySaver())


def _result_from_state(state: WorkflowState, *, exit_code: int | None = None) -> WorkflowResult:
    status = str(state.get("status", "running"))
    if exit_code is None:
        exit_code = 10 if status == "waiting" else 0 if status == "succeeded" else 20
    return WorkflowResult(
        run_id=str(state.get("run_id", "")),
        status=cast(Any, status),
        current_stage=str(state.get("current_stage", "raw_ingest")),
        next_action=str(state.get("next_action") or next_action(state)),
        exit_code=exit_code,
        errors=[str(item) for item in state.get("errors", [])],
        completed_stages=[str(item) for item in state.get("completed_stages", [])],
        cache_keys={str(key): str(value) for key, value in state.get("cache_keys", {}).items()},
    )


@dataclass
class DocumentWorkflow:
    """Run one document through M5 and resume it after a process-boundary interrupt."""

    services: WorkflowServices

    def _initial_state(self) -> WorkflowState:
        return {
            "status": "created",
            "current_stage": "raw_ingest",
            "resume_entry": "raw_ingest",
            "next_action": "run the raw_ingest stage",
            "completed_stages": [],
            "cache_keys": {},
            "stage_inputs": {},
            "errors": [],
            "gate2_enabled": self.services.gate2_enabled,
            "offline": self.services.offline,
            "stop_after": self.services.stop_after,
        }

    def _invoke(self, state: WorkflowState) -> WorkflowResult:
        graph = build_graph(self.services)
        thread_id = str(
            state.get("run_id") or hashlib.sha256(str(self.services.source).encode()).hexdigest()
        )
        config = {"configurable": {"thread_id": thread_id}}
        try:
            result = graph.invoke(state, config)
        except GraphInterrupt:
            if self.services.checkpoint is None:
                raise
            result = self.services.checkpoint.load_state()
            result["status"] = "waiting"
            return _result_from_state(result, exit_code=10)
        except WaitingForReviewError:
            if self.services.checkpoint is None:
                raise
            result = self.services.checkpoint.load_state()
            return _result_from_state(result, exit_code=10)
        except DocumentEnhancerError:
            raise
        except Exception as exc:
            if self.services.checkpoint is not None:
                state["status"] = "failed"
                state.setdefault("errors", []).append(type(exc).__name__ + ": " + str(exc))
                self.services.checkpoint.save_state(state)
            raise
        if isinstance(result, dict) and result.get("__interrupt__"):
            if self.services.checkpoint is None:
                raise WaitingForReviewError("workflow interrupted without a durable checkpoint")
            durable = self.services.checkpoint.load_state()
            return _result_from_state(durable, exit_code=10)
        if self.services.checkpoint is not None:
            self.services.checkpoint.save_state(result)
        return _result_from_state(result)

    def run(self) -> WorkflowResult:
        return self._invoke(self._initial_state())

    def resume(self) -> WorkflowResult:
        # Locate the durable run from the content-addressed source. If the source moved, the
        # persisted source_path is used after discovering the state file under run_root.
        run_id = self._discover_run_id()
        if run_id is None:
            raise ValidationError("no persisted workflow state found for this source")
        from .checkpoint import WorkflowCheckpoint

        self.services.checkpoint = WorkflowCheckpoint(RunPaths(self.services.run_root, run_id))
        state = self.services.checkpoint.load_state()
        source = Path(str(state["source_path"]))
        if not source.is_file():
            raise ValidationError(f"source is no longer available: {source.name}")
        from document_enhancer.ingest.pipeline import parse_source

        current = parse_source(source, registry=self.services.parser_registry)
        if current.source_digest != state.get("source_digest"):
            raise ValidationError("source changed since the waiting checkpoint; start a new run")
        self.services.source = source
        self.services.attach_run(current, run_id=run_id)
        # --until is a one-shot entry policy. A reviewer resume must validate and continue rather
        # than pausing at the same requested inspection stage forever.
        state["stop_after"] = None
        state["resume_entry"] = str(state.get("current_stage", "raw_ingest"))
        state["status"] = "running"
        return self._invoke(state)

    def _discover_run_id(self) -> str | None:
        if self.services.run_id:
            return self.services.run_id
        candidate = self.services.run_root
        if candidate.name.startswith("run-") and (candidate / "workflow-state.json").exists():
            return candidate.name
        for path in sorted(candidate.glob("run-*/workflow-state.json")):
            try:
                snapshot = WorkflowSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if snapshot.source_path == str(self.services.source.resolve()):
                return snapshot.run_id
        return None


__all__ = ["DocumentWorkflow", "WorkflowResult", "WorkflowServices", "build_graph"]
