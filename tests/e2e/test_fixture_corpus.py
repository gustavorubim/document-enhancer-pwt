from __future__ import annotations

from pathlib import Path

import pytest
from evals.grading import evaluate_corpus, validate_report


@pytest.mark.e2e
def test_offline_fixture_evaluation_produces_report_with_pending_downstream_metrics() -> None:
    report = evaluate_corpus(Path("fixtures/synthetic/corpus"))
    assert report["dataset_id"] == "synthetic-corpus-v1"
    assert report["status"] == "pending_dependencies"
    assert validate_report(report) == []
    assert all(item["status"] == "pending_dependencies" for item in report["reports"])
