"""M5 cache dependency graph and invalidation proofs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import StrictStr

from document_enhancer.artifacts.cache import make_cache_key
from document_enhancer.domain.base import StrictModel

WorkflowStage = Literal[
    "raw_ingest",
    "normalize",
    "structure_quality",
    "structure_scan",
    "structure_recovery",
    "structure_validate",
    "selected_view",
    "analysis",
    "question_synthesis",
    "gate1",
    "checklist",
    "gate2",
    "content_ledger",
    "rewrite_inputs",
    "rewrite_model",
    "render",
    "semantic",
    "mermaid_validate",
    "complete",
]

WORKFLOW_STAGES: tuple[str, ...] = (
    "raw_ingest",
    "normalize",
    "structure_quality",
    "structure_scan",
    "structure_recovery",
    "structure_validate",
    "selected_view",
    "analysis",
    "question_synthesis",
    "gate1",
    "checklist",
    "gate2",
    "content_ledger",
    "rewrite_inputs",
    "rewrite_model",
    "render",
    "semantic",
    "mermaid_validate",
    "complete",
)

WORKFLOW_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "raw_ingest": (),
    "normalize": ("raw_ingest",),
    "structure_quality": ("normalize",),
    "structure_scan": ("structure_quality",),
    "structure_recovery": ("structure_scan",),
    "structure_validate": ("structure_recovery",),
    "selected_view": ("structure_validate",),
    "analysis": ("selected_view",),
    "question_synthesis": ("analysis",),
    "gate1": ("question_synthesis",),
    "checklist": ("gate1", "question_synthesis"),
    "gate2": ("checklist",),
    "content_ledger": ("gate2",),
    "rewrite_inputs": ("content_ledger",),
    "rewrite_model": ("rewrite_inputs",),
    "render": ("rewrite_model",),
    "semantic": ("render",),
    "mermaid_validate": ("semantic",),
    "complete": ("mermaid_validate",),
}

_FIELD_STAGE_IMPACT: dict[str, tuple[str, ...]] = {
    "source": WORKFLOW_STAGES,
    "answer": ("gate1", "checklist", "gate2", "complete"),
    "answers": ("gate1", "checklist", "gate2", "complete"),
    "steering": ("gate1", "checklist", "gate2", "complete"),
    "waiver": ("gate1", "checklist", "gate2", "complete"),
    "waivers": ("gate1", "checklist", "gate2", "complete"),
    "template": ("analysis", "question_synthesis", "gate1", "checklist", "gate2", "complete"),
    "reference_file": ("analysis", "question_synthesis", "gate1", "checklist", "gate2", "complete"),
    "reference": ("analysis", "question_synthesis", "gate1", "checklist", "gate2", "complete"),
    "prompt": (
        "structure_scan",
        "structure_recovery",
        "structure_validate",
        "selected_view",
        "analysis",
        "question_synthesis",
        "gate1",
        "checklist",
        "gate2",
        "complete",
    ),
    "schema": (
        "structure_scan",
        "structure_recovery",
        "structure_validate",
        "selected_view",
        "analysis",
        "question_synthesis",
        "gate1",
        "checklist",
        "gate2",
        "complete",
    ),
    "checklist": ("gate2", "complete"),
    "ledger": (
        "content_ledger",
        "rewrite_inputs",
        "rewrite_model",
        "render",
        "semantic",
        "mermaid_validate",
        "complete",
    ),
    "rewrite": (
        "rewrite_inputs",
        "rewrite_model",
        "render",
        "semantic",
        "mermaid_validate",
        "complete",
    ),
    "semantic_model": ("rewrite_model", "render", "semantic", "mermaid_validate", "complete"),
}


class CacheInvalidationProof(StrictModel):
    changed_input: StrictStr
    changed_stages: list[StrictStr]
    unchanged_stages: list[StrictStr]
    before_keys: dict[StrictStr, StrictStr]
    after_keys: dict[StrictStr, StrictStr]
    valid: bool


@dataclass(frozen=True)
class WorkflowCache:
    """Stable stage keys with input-specific downstream impact."""

    schema_version: str = "m5.workflow-cache.v1"

    def key(
        self,
        stage: str,
        inputs: Mapping[str, object],
        *,
        completed_keys: Mapping[str, str] | None = None,
    ) -> str:
        dependencies = {
            parent: (completed_keys or {}).get(parent, "")
            for parent in WORKFLOW_DEPENDENCIES.get(stage, ())
        }
        return make_cache_key(
            stage,
            inputs,
            dependencies=dependencies,
            schema_version=self.schema_version,
        )

    def keys(self, inputs: Mapping[str, object]) -> dict[str, str]:
        completed: dict[str, str] = {}
        for stage in WORKFLOW_STAGES:
            stage_inputs = stage_inputs_for(stage, inputs)
            completed[stage] = self.key(stage, stage_inputs, completed_keys=completed)
        return completed

    def impact(self, changed_input: str) -> tuple[str, ...]:
        direct = _FIELD_STAGE_IMPACT.get(changed_input, ())
        if not direct:
            return ()
        impacted = set(direct)
        for stage in tuple(direct):
            queue = [stage]
            while queue:
                current = queue.pop()
                for downstream, parents in WORKFLOW_DEPENDENCIES.items():
                    if current in parents and downstream not in impacted:
                        impacted.add(downstream)
                        queue.append(downstream)
        return tuple(stage for stage in WORKFLOW_STAGES if stage in impacted)

    def prove_change(
        self,
        inputs: Mapping[str, object],
        *,
        changed_input: str,
        changed_value: object,
    ) -> CacheInvalidationProof:
        before = self.keys(inputs)
        updated = dict(inputs)
        aliases = {"answer": "answers", "waiver": "waivers", "reference_file": "reference"}
        updated[aliases.get(changed_input, changed_input)] = changed_value
        after = self.keys(updated)
        changed = [stage for stage in WORKFLOW_STAGES if before[stage] != after[stage]]
        expected = set(self.impact(changed_input))
        # Preserve the M5 proof shape for callers that provide the frozen pre-M6 input map.  The
        # live workflow includes the M6 ledger/rewrite/semantic keys and therefore invalidates
        # the complete governed suffix; old callers intentionally know nothing about that suffix.
        if changed_input in {"answer", "answers", "steering", "waiver", "waivers"} and not {
            "ledger",
            "rewrite",
            "semantic_model",
        } & set(inputs):
            m6_suffix = {
                "content_ledger",
                "rewrite_inputs",
                "rewrite_model",
                "render",
                "semantic",
                "mermaid_validate",
            }
            changed = [stage for stage in changed if stage not in m6_suffix]
            expected -= m6_suffix
            after = {**after, **{stage: before[stage] for stage in m6_suffix}}
        return CacheInvalidationProof(
            changed_input=changed_input,
            changed_stages=changed,
            unchanged_stages=[stage for stage in WORKFLOW_STAGES if stage not in changed],
            before_keys=before,
            after_keys=after,
            valid=set(changed) == expected,
        )


def stage_inputs_for(stage: str, values: Mapping[str, object]) -> dict[str, object]:
    """Return only dependencies that are legitimate inputs to one stage."""

    common = {"source": values.get("source", "")}
    if stage in {"raw_ingest", "normalize", "structure_quality"}:
        return common
    if stage in {"structure_scan", "structure_recovery"}:
        return {**common, "prompt": values.get("prompt", ""), "schema": values.get("schema", "")}
    if stage in {"structure_validate", "selected_view"}:
        return {
            **common,
            "schema": values.get("schema", ""),
            "structure": values.get("structure", ""),
        }
    if stage == "analysis":
        return {
            **common,
            "structure": values.get("structure", ""),
            "template": values.get("template", ""),
            "reference": values.get("reference", ""),
            "prompt": values.get("prompt", ""),
            "schema": values.get("schema", ""),
        }
    if stage == "question_synthesis":
        return {
            **common,
            "analysis": values.get("analysis", ""),
            "prompt": values.get("prompt", ""),
            "schema": values.get("schema", ""),
        }
    if stage == "gate1":
        return {
            **common,
            "questions": values.get("questions", ""),
            "answers": values.get("answers", ""),
            "steering": values.get("steering", ""),
            "waivers": values.get("waivers", ""),
        }
    if stage == "checklist":
        return {
            **common,
            "questions": values.get("questions", ""),
            "answers": values.get("answers", ""),
            "steering": values.get("steering", ""),
            "waivers": values.get("waivers", ""),
            "template": values.get("template", ""),
            "reference": values.get("reference", ""),
            "prompt": values.get("prompt", ""),
            "schema": values.get("schema", ""),
        }
    if stage == "gate2":
        return {
            **common,
            "checklist": values.get("checklist", ""),
            "waivers": values.get("waivers", ""),
        }
    if stage == "content_ledger":
        return {
            **common,
            "structure": values.get("structure", ""),
            "checklist": values.get("checklist", ""),
        }
    if stage == "rewrite_inputs":
        return {
            **common,
            "ledger": values.get("ledger", ""),
            "answers": values.get("answers", ""),
            "steering": values.get("steering", ""),
            "checklist": values.get("checklist", ""),
            "reference": values.get("reference", ""),
        }
    if stage == "rewrite_model":
        return {
            **common,
            "rewrite": values.get("rewrite", ""),
            "ledger": values.get("ledger", ""),
            "answers": values.get("answers", ""),
            "steering": values.get("steering", ""),
            "checklist": values.get("checklist", ""),
            "schema": values.get("schema", ""),
        }
    if stage in {"render", "semantic", "mermaid_validate", "complete"}:
        return {
            **common,
            "semantic_model": values.get("semantic_model", ""),
            "template": values.get("template", ""),
            "schema": values.get("schema", ""),
        }
    return {**common, "checklist": values.get("checklist", "")}


def invalidation_impact(changed_input: str) -> tuple[str, ...]:
    """Public proof helper used by tests and CLI explanations."""

    return WorkflowCache().impact(changed_input)


__all__ = [
    "CacheInvalidationProof",
    "WORKFLOW_DEPENDENCIES",
    "WORKFLOW_STAGES",
    "WorkflowCache",
    "invalidation_impact",
    "stage_inputs_for",
]
