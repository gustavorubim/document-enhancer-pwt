"""Deterministic evaluation graders with explicit dependency-gated statuses."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = "0.1"
NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class MetricResult:
    metric_id: str
    status: str
    score: float | None = None
    numerator: int | float | None = None
    denominator: int | float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["dependencies"] = list(self.dependencies)
        return result


def _not_evaluated(metric_id: str, *dependencies: str, reason: str) -> MetricResult:
    return MetricResult(
        metric_id, NOT_EVALUATED, details={"reason": reason}, dependencies=dependencies
    )


def _coverage(expected: Sequence[str], actual: Sequence[str]) -> MetricResult:
    expected_set = set(expected)
    actual_set = set(actual)
    covered = len(expected_set & actual_set)
    score = covered / len(expected_set) if expected_set else 1.0
    order_ok = list(expected) == list(actual)
    return MetricResult(
        "structure_coverage_order",
        "passed" if score == 1.0 and order_ok else "failed",
        score=score,
        numerator=covered,
        denominator=len(expected_set),
        details={
            "missing_span_ids": sorted(expected_set - actual_set),
            "unexpected_span_ids": sorted(actual_set - expected_set),
            "order_match": order_ok,
        },
    )


def _boundary_accuracy(
    expected: Sequence[Mapping[str, Any]], actual: Sequence[Mapping[str, Any]]
) -> MetricResult:
    expected_keys = {
        (item["section_id"], item["start_ordinal"], item["end_ordinal"]) for item in expected
    }
    actual_keys = {
        (item["section_id"], item["start_ordinal"], item["end_ordinal"]) for item in actual
    }
    matched = len(expected_keys & actual_keys)
    score = matched / len(expected_keys) if expected_keys else 1.0
    return MetricResult(
        "boundary_accuracy",
        "passed" if score == 1.0 else "failed",
        score=score,
        numerator=matched,
        denominator=len(expected_keys),
        details={"missing_boundaries": sorted(expected_keys - actual_keys)},
    )


def _set_f1(metric_id: str, expected: Iterable[str], actual: Iterable[str]) -> MetricResult:
    expected_set, actual_set = set(expected), set(actual)
    true_positive = len(expected_set & actual_set)
    precision = true_positive / len(actual_set) if actual_set else 0.0
    recall = true_positive / len(expected_set) if expected_set else 1.0
    score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return MetricResult(
        metric_id,
        "passed" if score == 1.0 else "failed",
        score=score,
        numerator=true_positive,
        denominator=len(expected_set),
        details={
            "precision": precision,
            "recall": recall,
            "missing": sorted(expected_set - actual_set),
            "extra": sorted(actual_set - expected_set),
        },
    )


def _candidate_list(candidate: Mapping[str, Any] | None, key: str) -> Sequence[Any] | None:
    if candidate is None or key not in candidate:
        return None
    value = candidate[key]
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else None


def evaluate_fixture(
    gold: Mapping[str, Any], candidate: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Evaluate one fixture; missing downstream artifacts remain visibly pending."""

    clean = gold["variants"]["clean"]
    metrics: list[MetricResult] = []
    actual_order = _candidate_list(candidate, "raw_order") if candidate else None
    actual_boundaries = _candidate_list(candidate, "section_boundaries") if candidate else None
    if actual_order is None:
        metrics.append(
            _not_evaluated(
                "structure_coverage_order",
                "M3B",
                reason="No selected structural-view artifact was supplied.",
            )
        )
    else:
        metrics.append(_coverage(clean["raw_order"], [str(item) for item in actual_order]))
    if actual_boundaries is None:
        metrics.append(
            _not_evaluated(
                "boundary_accuracy",
                "M3B",
                reason="No selected section-boundary artifact was supplied.",
            )
        )
    else:
        metrics.append(_boundary_accuracy(clean["section_boundaries"], actual_boundaries))

    supported_candidates = {
        "ontology_graph_completeness": (("semantic_objects", "semantic_edges"), ("M6",)),
        "question_quality": (("questions",), ("M4B",)),
        "ledger_rewrite_fidelity": (("content_dispositions",), ("M6",)),
        "sqlite_embedding_completeness": (("sqlite_rows",), ("M7R",)),
        "retrieval_ranking": (("retrieval_hits",), ("M7R",)),
        "groundedness": (("answer_claims",), ("M7R",)),
        "citations": (("citations",), ("M7R",)),
        "abstention": (("abstention",), ("M7R",)),
        "cost": (("cost",), ("live_model",)),
        "latency": (("latency",), ("live_model",)),
    }
    for metric_id, (candidate_keys, dependencies) in supported_candidates.items():
        missing_keys = [key for key in candidate_keys if candidate is None or key not in candidate]
        if missing_keys:
            missing = ", ".join(missing_keys)
            metrics.append(
                _not_evaluated(
                    metric_id,
                    *dependencies,
                    reason=f"Dependency-gated artifact(s) '{missing}' are not available in the WT0 baseline.",
                )
            )
        else:
            value = candidate[candidate_keys[0]]
            if metric_id in {
                "ontology_graph_completeness",
                "question_quality",
                "ledger_rewrite_fidelity",
            } and isinstance(value, Mapping):
                expected_key = {
                    "ontology_graph_completeness": "gold_semantic_objects",
                    "question_quality": "gold_questions",
                    "ledger_rewrite_fidelity": "content_dispositions",
                }[metric_id]
                expected = gold.get(expected_key, [])
                expected_ids = [
                    str(item.get("id", item.get("question_id", item.get("source_span_id", ""))))
                    for item in expected
                    if isinstance(item, Mapping)
                ]
                actual_items = value.get("items", [])
                if metric_id == "ontology_graph_completeness":
                    actual_items = list(actual_items) + list(
                        candidate["semantic_edges"].get("items", [])
                    )
                    expected_ids += [
                        str(item.get("edge_id", "")) for item in gold.get("gold_semantic_edges", [])
                    ]
                actual_ids = [
                    str(
                        item.get(
                            "id",
                            item.get(
                                "edge_id", item.get("question_id", item.get("source_span_id", ""))
                            ),
                        )
                    )
                    for item in actual_items
                    if isinstance(item, Mapping)
                ]
                metrics.append(_set_f1(metric_id, expected_ids, actual_ids))
            else:
                metrics.append(
                    MetricResult(
                        metric_id,
                        "passed",
                        score=float(value) if isinstance(value, (float, int)) else None,
                        details={"candidate_supplied": True},
                    )
                )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "fixture_id": gold["family_id"],
        "document_id": gold["document_id"],
        "status": "pending_dependencies"
        if any(metric.status == NOT_EVALUATED for metric in metrics)
        else "evaluated",
        "metrics": [metric.to_dict() for metric in metrics],
    }


def evaluate_corpus(corpus_dir: Path, *, output_path: Path | None = None) -> dict[str, Any]:
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    reports = []
    for family in manifest["families"]:
        gold = json.loads((corpus_dir / family["gold"]).read_text(encoding="utf-8"))
        reports.append(evaluate_fixture(gold))
    result = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "dataset_id": "synthetic-corpus-v1",
        "status": "pending_dependencies",
        "generator_version": manifest["generator_version"],
        "reports": reports,
        "metric_status_summary": {
            "supported_now": ["structure_coverage_order", "boundary_accuracy"],
            "pending": [
                "ontology_graph_completeness",
                "question_quality",
                "ledger_rewrite_fidelity",
                "sqlite_embedding_completeness",
                "retrieval_ranking",
                "groundedness",
                "citations",
                "abstention",
                "cost",
                "latency",
            ],
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return result


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        errors.append("schema_version must match the evaluator schema version")
    if not isinstance(report.get("reports"), list):
        errors.append("reports must be a list")
    for index, item in enumerate(report.get("reports", [])):
        if not isinstance(item, Mapping):
            errors.append(f"reports[{index}] must be an object")
            continue
        for metric in item.get("metrics", []):
            if metric.get("status") not in {"passed", "failed", NOT_EVALUATED}:
                errors.append(f"reports[{index}] contains an invalid metric status")
            if metric.get("status") == NOT_EVALUATED and not metric.get("details", {}).get(
                "reason"
            ):
                errors.append(f"reports[{index}] has an unexplained not_evaluated metric")
    return errors


def digest_json(value: Any) -> str:
    """Stable digest helper used by reports and tests."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
