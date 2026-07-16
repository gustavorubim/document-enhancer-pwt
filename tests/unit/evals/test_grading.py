from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.grading import NOT_EVALUATED, evaluate_corpus, evaluate_fixture, validate_report


def _gold() -> dict:
    return json.loads(
        Path("fixtures/synthetic/corpus/monthly_loss_forecasting_methodology/gold.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.unit
def test_structure_grader_scores_supplied_selected_view() -> None:
    gold = _gold()
    clean = gold["variants"]["clean"]
    report = evaluate_fixture(
        gold, {"raw_order": clean["raw_order"], "section_boundaries": clean["section_boundaries"]}
    )
    metrics = {metric["metric_id"]: metric for metric in report["metrics"]}
    assert metrics["structure_coverage_order"]["status"] == "passed"
    assert metrics["boundary_accuracy"]["status"] == "passed"
    assert all(
        metric["status"] == NOT_EVALUATED
        for metric_id, metric in metrics.items()
        if metric_id not in {"structure_coverage_order", "boundary_accuracy"}
    )


@pytest.mark.unit
def test_default_corpus_report_is_honestly_pending() -> None:
    report = evaluate_corpus(Path("fixtures/synthetic/corpus"))
    assert report["status"] == "pending_dependencies"
    assert validate_report(report) == []
    statuses = {metric["status"] for item in report["reports"] for metric in item["metrics"]}
    assert NOT_EVALUATED in statuses


@pytest.mark.unit
def test_structure_grader_detects_reorder_and_missing_span() -> None:
    gold = _gold()
    clean = gold["variants"]["clean"]
    candidate = {"raw_order": clean["raw_order"][::-1], "section_boundaries": []}
    report = evaluate_fixture(gold, candidate)
    metrics = {metric["metric_id"]: metric for metric in report["metrics"]}
    assert metrics["structure_coverage_order"]["status"] == "failed"
    assert metrics["structure_coverage_order"]["details"]["order_match"] is False
    assert metrics["boundary_accuracy"]["status"] == "failed"
