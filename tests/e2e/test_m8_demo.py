from __future__ import annotations

from pathlib import Path

import pytest
from scripts.run_offline_demo import run_demo


@pytest.mark.e2e
def test_offline_demo_crosses_both_review_gates_and_answers_with_citations(
    tmp_path: Path,
) -> None:
    result = run_demo(tmp_path / "demo")
    assert result["gate1"] == {"status": "waiting", "stage": "gate1"}
    assert result["review_inputs_validated"] is True
    assert result["gate2"] == {"status": "waiting", "stage": "gate2"}
    assert result["completed"] == {"status": "succeeded", "stage": "complete"}
    assert result["audit"]["status"] == "pass"
    assert result["rag_package"]["valid"] is True
    assert result["search"]["hits"]
    assert result["answer"]["status"] in {"answered", "partial"}
    assert result["answer"]["grounding_passed"] is True
    assert result["answer"]["citations"]
