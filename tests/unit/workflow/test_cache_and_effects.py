from __future__ import annotations

import json
from pathlib import Path

import pytest

from document_enhancer.analysis.errors import AnalysisIncompleteError
from document_enhancer.analysis.models import AnalysisStageRecord
from document_enhancer.domain.enums import DocumentType
from document_enhancer.workflow import DocumentWorkflow, WorkflowServices
from document_enhancer.workflow.cache import WORKFLOW_STAGES, WorkflowCache
from document_enhancer.workflow.checkpoint import SideEffectLedger


def _inputs() -> dict[str, str]:
    return {
        "source": "source-a",
        "template": "template-a",
        "reference": "reference-a",
        "prompt": "prompt-a",
        "schema": "schema-a",
        "answers": "answers-a",
        "steering": "steering-a",
        "waivers": "waivers-a",
        "structure": "structure-a",
        "analysis": "analysis-a",
        "questions": "questions-a",
        "checklist": "checklist-a",
    }


def test_cache_proofs_change_only_the_dependent_suffix() -> None:
    cache = WorkflowCache()
    answer = cache.prove_change(_inputs(), changed_input="answer", changed_value="answers-b")
    assert answer.valid
    assert set(answer.changed_stages) == {"gate1", "checklist", "gate2", "complete"}
    assert all(
        answer.before_keys[stage] == answer.after_keys[stage]
        for stage in WORKFLOW_STAGES
        if stage not in answer.changed_stages
    )

    source = cache.prove_change(_inputs(), changed_input="source", changed_value="source-b")
    assert source.valid
    assert set(source.changed_stages) == set(WORKFLOW_STAGES)

    prompt = cache.prove_change(_inputs(), changed_input="prompt", changed_value="prompt-b")
    assert prompt.valid
    assert prompt.before_keys["raw_ingest"] == prompt.after_keys["raw_ingest"]
    assert prompt.before_keys["analysis"] != prompt.after_keys["analysis"]

    live = _inputs() | {
        "ledger": "ledger-a",
        "rewrite": "rewrite-a",
        "semantic_model": "semantic-a",
    }
    waiver = cache.prove_change(live, changed_input="waiver", changed_value="waiver-b")
    assert waiver.valid
    assert {"audit", "diff", "chunk", "export", "complete"} <= set(waiver.changed_stages)


def test_side_effect_receipts_are_idempotent(tmp_path) -> None:
    ledger = SideEffectLedger(tmp_path / "checkpoint.sqlite3")
    calls: list[str] = []
    assert ledger.run_once("effect", {"value": 1}, lambda: calls.append("called"))
    assert not ledger.run_once("effect", {"value": 1}, lambda: calls.append("called"))
    assert calls == ["called"]
    assert ledger.count() == 1


class _FailedAnalysisRunner:
    def run(self, request, *, recorder):
        outcome = AnalysisStageRecord(
            document_id=request.document_id,
            source_digest=request.source_digest,
            stage="macro_reviewer",
            status="failed",
            error_type="RecordedProviderFailure",
            error_message="Required analysis stage did not produce a validated artifact.",
            retry_action="Retry the macro_reviewer analysis stage with the same validated inputs.",
        )
        recorder.record(outcome)
        raise AnalysisIncompleteError((outcome,))


def test_workflow_checkpoints_failed_analysis_before_question_and_downstream_gates(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Procedure\n\nThe analyst reviews the monthly report.\n", encoding="utf-8")
    services = WorkflowServices(
        run_root=tmp_path / "runs",
        source=source,
        document_type=DocumentType.PROCESS,
        analysis_runner=_FailedAnalysisRunner(),
        structure_mode="parser",
        offline=True,
    )

    with pytest.raises(AnalysisIncompleteError):
        DocumentWorkflow(services).run()

    assert services.checkpoint is not None
    state = json.loads(services.checkpoint.state_path.read_text(encoding="utf-8"))["state"]
    assert state["status"] == "failed"
    assert state["current_stage"] == "analysis"
    assert state["resume_entry"] == "analysis"
    assert state["next_action"] == (
        "Retry the macro_reviewer analysis stage with the same validated inputs."
    )
    assert "question_synthesis" not in state["completed_stages"]
    assert "gate1" not in state["completed_stages"]
    assert not services.paths.artifact_path("clarification/questions.yaml").exists()
    assert not services.paths.artifact_path("audit/audit.json").exists()
    assert not services.paths.artifact_path("rag/build-manifest.json").exists()
    stage = services.checkpoint.checkpoints.get(services.paths.run_id, "analysis")
    assert stage is not None
    assert stage.status == "failed"
    assert stage.payload["unresolved_stages"] == ["macro_reviewer"]


@pytest.mark.parametrize("changed_input", ["template", "reference_file", "prompt", "schema"])
def test_cache_proves_governed_inputs_invalidate_their_downstream_suffix(
    changed_input: str,
) -> None:
    proof = WorkflowCache().prove_change(
        _inputs(), changed_input=changed_input, changed_value=f"{changed_input}-b"
    )
    assert proof.valid
    assert proof.changed_stages
    assert proof.before_keys["raw_ingest"] == proof.after_keys["raw_ingest"]
