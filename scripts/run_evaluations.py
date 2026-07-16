#!/usr/bin/env python3
"""Generate or verify deterministic M8 offline evaluation evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.grading import evaluate_corpus, validate_report  # noqa: E402


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M8 offline evaluation report",
        "",
        f"Release status: **{report['status']}**",
        "",
        "This report is generated from checked-in fictional gold contracts. The default run made "
        "zero provider calls and zero public downloads. It validates deterministic graders, release "
        "contracts, and route configuration; it does not claim live Gemini quality, service latency, "
        "token usage, pricing, or public-source generalization.",
        "",
        "## Section 20 threshold evidence",
        "",
        "| Threshold | Observed | Required | Status | Evidence |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for item in report["thresholds"]:
        lines.append(
            f"| `{item['threshold_id']}` | {_percent(item['observed'])} | "
            f"{_percent(item['required'])} | {item['status']} | {item['evidence_kind']} |"
        )
    lines.extend(
        [
            "",
            "## Per-family enhancement and package results",
            "",
            "| Family | Fixture-format reports | Passed | Failed |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for item in report["family_summaries"]:
        lines.append(
            f"| `{item['family_id']}` | {item['reports']} | {item['passed']} | {item['failed']} |"
        )
    lines.extend(
        [
            "",
            "Each family/format/severity report grades raw-block coverage and order, boundary F1, "
            "hierarchy, schema validity, unique IDs and references, dispositions, provenance, "
            "question/object/defect recall and precision, chunk stability, SQLite/FTS/graph/vector "
            "completeness, embedding smoke ranking, and route coverage.",
            "",
            "## Retrieval channels",
            "",
            "| Channel | Queries | Recall@10 | MRR | nDCG@10 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for channel, item in report["rag"]["channels"].items():
        lines.append(
            f"| {channel} | {item['queries']} | {_percent(item['recall_at_10'])} | "
            f"{item['mrr']:.3f} | {item['ndcg_at_10']:.3f} |"
        )
    lines.extend(
        [
            "",
            f"Graph-path correctness: {_percent(report['rag']['graph_path_correctness'])}. "
            f"Filter correctness: {_percent(report['rag']['filter_correctness'])}. "
            f"Follow-up resolution: {_percent(report['rag']['follow_up_resolution'])}.",
            "",
            "## Answers and citations",
            "",
            f"Groundedness: {_percent(report['rag']['groundedness'])}. Citation precision: "
            f"{_percent(report['rag']['citation_precision'])}. Citation recall: "
            f"{_percent(report['rag']['citation_recall'])}. Abstention accuracy: "
            f"{_percent(report['rag']['abstention_accuracy'])}. Unsupported material claims: "
            f"{report['rag']['unsupported_material_claims']}.",
            "",
            "| Question | Status | Evidence chunks | Citations | Forbidden claims present |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in report["rag"]["answers"]:
        lines.append(
            f"| `{item['question_id']}` | {item['status']} | "
            f"{', '.join(item['evidence_chunks']) or 'none'} | "
            f"{', '.join(item['citations']) or 'none'} | "
            f"{', '.join(item['forbidden_claims_present']) or 'none'} |"
        )
    routes = report["reports"][0]["route_evidence"]
    lines.extend(
        [
            "",
            "## Gemini route, latency, cost, fallback, and lifecycle evidence",
            "",
            "| Route | Offline mode | Coverage/quality | Deterministic latency proxy | Actual provider cost | Fallback/lifecycle |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for route in routes:
        score = route.get("embedding_coverage", route.get("quality_score", 0.0))
        lines.append(
            f"| `{route['model']}` | {route['mode']} | {_percent(score)} | "
            f"{route['deterministic_latency_proxy_ms']:.2f} ms | "
            f"${route['actual_provider_cost_usd']:.2f} | {route['fallback']}; {route['lifecycle']} |"
        )
    lines.extend(
        [
            "",
            "Latency values above are deterministic workload proxies for regression comparison, not "
            "wall-clock service measurements. Actual provider cost is zero because the offline gate "
            "does not call Gemini. Live quality, service latency, token usage, and billed cost are "
            "reported only by the explicit `live_model` evaluation.",
            "",
            "## Fixture-format detail",
            "",
            "| Family | Severity | Format | Status | Lowest metric |",
            "| --- | --- | --- | --- | ---: |",
        ]
    )
    for item in report["reports"]:
        scores = [metric["score"] for metric in item["metrics"] if metric["score"] is not None]
        lines.append(
            f"| `{item['fixture_id']}` | {item['variant']} | {item['input_format']} | "
            f"{item['status']} | {_percent(min(scores))} |"
        )
    lines.extend(["", "## Failures and limitations", ""])
    failed = [item for item in report["thresholds"] if item["status"] == "failed"]
    lines.append(
        "- No deterministic offline threshold failures."
        if not failed
        else "- Failed thresholds: " + ", ".join(item["threshold_id"] for item in failed)
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "- Text PDFs do not cover OCR or scanned-image recovery.",
            "- Messy source structure remains uncertain and requires confidence routing plus human review.",
            "- Gemini exact routes, especially preview models, may change availability or lifecycle state.",
            "- Inferred knowledge remains a separate reviewable graph layer.",
            "- Local SQLite is not an unbounded or multi-tenant enterprise catalog.",
            "- Pre-v1 SQLiteVec behavior is pinned but remains a compatibility risk.",
            "- The MVP has no enterprise identity integration or hosted UI.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("fixtures/synthetic/corpus"))
    parser.add_argument("--json", type=Path, default=Path("evals/reports/m8-offline.json"))
    parser.add_argument("--markdown", type=Path, default=Path("evals/reports/m8-evaluation.md"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = evaluate_corpus(args.corpus)
    errors = validate_report(report)
    if errors:
        parser.error("; ".join(errors))
    expected = {
        args.json: (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(),
        args.markdown: render_markdown(report).encode(),
    }
    for path, content in expected.items():
        if args.check:
            if not path.is_file() or path.read_bytes() != content:
                parser.error(f"evaluation artifact differs: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print(f"{'verified' if args.check else 'generated'} {len(expected)} M8 evaluation artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
