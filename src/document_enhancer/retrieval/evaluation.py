"""Compact, provider-neutral evaluation metrics for cited RAG answers."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from .models import AnswerResult


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    question: str
    expected_run_ids: tuple[str, ...] = ()
    answerable: bool
    minimum_retrieval_actions: int = Field(default=1, ge=0, le=8)
    category: str


def evaluate_answers(
    cases: Sequence[EvaluationCase],
    answer: Callable[[EvaluationCase], AnswerResult],
) -> dict[str, object]:
    """Evaluate observable results and traces; hidden reasoning is never required."""

    records: list[dict[str, object]] = []
    latencies: list[float] = []
    for case in cases:
        started = time.perf_counter()
        result = answer(case)
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.append(elapsed_ms)
        source_ids = {source.evidence_id for source in result.sources}
        source_runs = {source.run_id for source in result.sources}
        citations_valid = all(
            citation in source_ids for claim in result.claims for citation in claim.citation_ids
        )
        retrieval_actions = sum(
            event.tool in {"search_evidence", "expand_graph"} for event in result.trace
        )
        expected_runs = set(case.expected_run_ids)
        recall = not expected_runs or expected_runs.issubset(source_runs)
        abstention_correct = (result.status == "answered") == case.answerable
        hop_correct = retrieval_actions >= case.minimum_retrieval_actions
        records.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "status": result.status,
                "expected_run_ids": list(case.expected_run_ids),
                "source_run_ids": sorted(source_runs),
                "recall_at_5": recall,
                "citations_valid": citations_valid,
                "abstention_correct": abstention_correct,
                "retrieval_actions": retrieval_actions,
                "multi_hop_correct": hop_correct,
                "latency_ms": elapsed_ms,
            }
        )
    total = len(records) or 1
    ordered_latencies = sorted(latencies)
    p95_index = max(0, math.ceil(len(ordered_latencies) * 0.95) - 1)
    answerability_accuracy = sum(bool(item["abstention_correct"]) for item in records) / total
    return {
        "schema_version": "document-enhancer.rag.evaluation.v1",
        "cases": len(records),
        "metrics": {
            "recall_at_5": sum(bool(item["recall_at_5"]) for item in records) / total,
            "citation_validity": sum(bool(item["citations_valid"]) for item in records) / total,
            "answerability_accuracy": answerability_accuracy,
            "abstention_accuracy": answerability_accuracy,
            "multi_hop_accuracy": sum(bool(item["multi_hop_correct"]) for item in records) / total,
            "mean_tool_calls": sum(cast(int, item["retrieval_actions"]) for item in records)
            / total,
            "p95_latency_ms": ordered_latencies[p95_index] if ordered_latencies else 0.0,
        },
        "results": records,
    }


__all__ = ["EvaluationCase", "evaluate_answers"]
