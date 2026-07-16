from __future__ import annotations

from pathlib import Path

import pytest
from evals.grading import evaluate_corpus, validate_report


@pytest.mark.e2e
def test_offline_fixture_evaluation_produces_release_threshold_evidence() -> None:
    report = evaluate_corpus(Path("fixtures/synthetic/corpus"))
    assert report["dataset_id"] == "synthetic-corpus-v1"
    assert report["status"] == "passed_offline"
    assert validate_report(report) == []
    assert all(item["status"] == "evaluated" for item in report["reports"])
    assert all(item["status"] == "passed" for item in report["thresholds"])
