"""DFT-8 machine-readable offline evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.evaluation.draft_first_evaluation import _assert_release_metrics, run_evaluation


@pytest.mark.e2e
def test_dft8_offline_evaluation_emits_verified_metrics(tmp_path: Path) -> None:
    payload = run_evaluation(tmp_path)
    _assert_release_metrics(payload)

    metrics_path = tmp_path / "draft-first-metrics.json"
    assert json.loads(metrics_path.read_text(encoding="utf-8")) == payload
