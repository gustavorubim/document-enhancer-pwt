from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.grading import (
    build_offline_candidate,
    evaluate_corpus,
    evaluate_fixture,
    validate_report,
)


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
    candidate = build_offline_candidate(gold, variant="clean", input_format="markdown")
    report = evaluate_fixture(gold, candidate)
    metrics = {metric["metric_id"]: metric for metric in report["metrics"]}
    assert metrics["raw_block_coverage_order"]["status"] == "passed"
    assert metrics["section_boundary_f1"]["status"] == "passed"
    assert clean["format_artifacts"]["markdown"]["sha256"]


@pytest.mark.unit
def test_default_corpus_report_is_honest_offline_release_evidence() -> None:
    report = evaluate_corpus(Path("fixtures/synthetic/corpus"))
    assert report["status"] == "passed_offline"
    assert validate_report(report) == []
    assert report["evidence_policy"]["provider_calls"] == 0
    assert report["evidence_policy"]["live_model"] == "opt_in_not_run"
    assert all(item["status"] == "passed" for item in report["thresholds"])
    assert set(report["rag"]["channels"]) == {"vector", "fts", "graph", "fused"}


@pytest.mark.unit
def test_structure_grader_detects_reorder_and_missing_span() -> None:
    gold = _gold()
    clean = gold["variants"]["clean"]
    candidate = build_offline_candidate(gold, variant="clean", input_format="markdown")
    candidate["raw_order"] = clean["raw_order"][::-1]
    candidate["section_boundaries"] = []
    report = evaluate_fixture(gold, candidate)
    metrics = {metric["metric_id"]: metric for metric in report["metrics"]}
    assert metrics["raw_block_coverage_order"]["status"] == "failed"
    assert metrics["raw_block_coverage_order"]["details"]["order_match"] is False
    assert metrics["section_boundary_f1"]["status"] == "failed"
