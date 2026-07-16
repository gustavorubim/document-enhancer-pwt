from __future__ import annotations

import pytest

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


def test_side_effect_receipts_are_idempotent(tmp_path) -> None:
    ledger = SideEffectLedger(tmp_path / "checkpoint.sqlite3")
    calls: list[str] = []
    assert ledger.run_once("effect", {"value": 1}, lambda: calls.append("called"))
    assert not ledger.run_once("effect", {"value": 1}, lambda: calls.append("called"))
    assert calls == ["called"]
    assert ledger.count() == 1


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
