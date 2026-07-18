from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from document_enhancer.retrieval.agent import RagAnswerer
from document_enhancer.retrieval.catalog import RagCatalog, RagCatalogBuilder
from document_enhancer.retrieval.embeddings import DeterministicEmbeddings
from document_enhancer.retrieval.evaluation import EvaluationCase, evaluate_answers
from document_enhancer.retrieval.models import (
    AnswerClaim,
    AnswerEnvelope,
    AnswerResult,
    SourceCitation,
    TraceEvent,
)

from .helpers import write_bundle

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.unit
def test_compact_evaluation_corpus_has_twenty_varied_cases() -> None:
    raw = json.loads((ROOT / "fixtures/rag/questions.json").read_text(encoding="utf-8"))
    cases = [EvaluationCase.model_validate(item) for item in raw]

    assert len(cases) == 20
    assert len({case.category for case in cases}) >= 7
    assert any(case.minimum_retrieval_actions >= 2 for case in cases)
    assert any(not case.answerable for case in cases)


@pytest.mark.unit
def test_evaluation_reports_recall_citations_abstention_hops_and_latency() -> None:
    cases = [
        EvaluationCase(
            case_id="answer",
            question="Answer?",
            expected_run_ids=("run-a",),
            answerable=True,
            minimum_retrieval_actions=2,
            category="multi-hop",
        ),
        EvaluationCase(
            case_id="abstain",
            question="Unknown?",
            answerable=False,
            minimum_retrieval_actions=1,
            category="insufficient",
        ),
    ]

    def answer(case: EvaluationCase) -> AnswerResult:
        trace = (
            TraceEvent(tool="search_evidence", input={}),
            TraceEvent(tool="expand_graph", input={}),
        )
        if not case.answerable:
            return AnswerResult(status="insufficient", claims=(), sources=(), trace=trace[:1])
        source = SourceCitation(
            evidence_id="E1",
            chunk_id="CHK-1",
            run_id="run-a",
            document_title="A",
            heading_path=("A",),
            bundle_path="/tmp/run-a",
        )
        return AnswerResult(
            status="answered",
            claims=(AnswerClaim(text="Supported", citation_ids=("E1",)),),
            sources=(source,),
            trace=trace,
        )

    report = evaluate_answers(cases, answer)
    metrics = cast(dict[str, Any], report["metrics"])

    assert metrics["recall_at_5"] == 1.0
    assert metrics["citation_validity"] == 1.0
    assert metrics["answerability_accuracy"] == 1.0
    assert metrics["abstention_accuracy"] == 1.0
    assert metrics["multi_hop_accuracy"] == 1.0
    assert metrics["mean_tool_calls"] == 1.5


@pytest.mark.unit
def test_full_evaluation_corpus_meets_declared_thresholds(tmp_path: Path) -> None:
    raw = json.loads((ROOT / "fixtures/rag/questions.json").read_text(encoding="utf-8"))
    cases = [EvaluationCase.model_validate(item) for item in raw]
    nodes = [
        {
            "node_id": "overview",
            "label": "Overview",
            "node_type": "Section",
            "provenance_span_ids": ["span-overview"],
        },
        {
            "node_id": "control",
            "label": "Control",
            "node_type": "Control",
            "provenance_span_ids": ["span-control"],
        },
    ]
    write_bundle(
        tmp_path / "runs",
        "run-a",
        "# Alpha Process\n\n## Overview\n\nAlpha is governed by POL-42.\n\n"
        "## Control\n\nThe Alpha control owner records every completed review.\n",
        nodes=nodes,
        edges=[
            {
                "source": "overview",
                "target": "control",
                "edge_type": "governed_by",
                "provenance_span_ids": ["span-edge"],
            }
        ],
    )
    write_bundle(
        tmp_path / "runs",
        "run-b",
        "# POL-42\n\n## Overview\n\nPOL-42 requires a monthly review by the Risk Committee.\n",
    )
    embeddings = DeterministicEmbeddings()
    catalog_path = tmp_path / "catalog"
    RagCatalogBuilder(catalog_path, embeddings).build(
        [tmp_path / "runs/run-a", tmp_path / "runs/run-b"]
    )

    class EvaluationAgent:
        def __init__(self, tools: list[Any], case: EvaluationCase) -> None:
            self.tools = {tool.name: tool for tool in tools}
            self.case = case

        def invoke(self, _state: object, config: object) -> dict[str, object]:
            if not self.case.answerable:
                self.tools["search_evidence"].invoke({"query": self.case.question, "limit": 5})
                return {"structured_response": AnswerEnvelope(status="insufficient")}
            cards: list[dict[str, Any]] = []
            if self.case.category == "graph-hop":
                first = self.tools["search_evidence"].invoke(
                    {"query": "Alpha Overview", "limit": 5}
                )
                overview = next(
                    card
                    for card in first["evidence"]
                    if card["run_id"] == "run-a" and card["graph_node_ids"]
                )
                expanded = self.tools["expand_graph"].invoke(
                    {"node_ids": overview["graph_node_ids"], "depth": 1}
                )
                cards.extend(expanded["evidence"])
            else:
                query_by_run = {
                    "run-a": "Alpha POL-42 control owner",
                    "run-b": "POL-42 monthly Risk Committee requirement",
                }
                for run_id in self.case.expected_run_ids:
                    found = self.tools["search_evidence"].invoke(
                        {"query": query_by_run[run_id], "limit": 5}
                    )
                    cards.extend(found["evidence"])
            citation_ids = tuple(
                next(card["evidence_id"] for card in cards if card["run_id"] == run_id)
                for run_id in self.case.expected_run_ids
            )
            return {
                "structured_response": AnswerEnvelope(
                    status="answered",
                    claims=(
                        AnswerClaim(text="Supported fixture answer.", citation_ids=citation_ids),
                    ),
                )
            }

    with RagCatalog.open(catalog_path, embeddings) as catalog:

        def answer(case: EvaluationCase) -> AnswerResult:
            return RagAnswerer(
                catalog,
                object(),
                agent_factory=lambda **kwargs: EvaluationAgent(kwargs["tools"], case),
            ).answer(case.question)

        report = evaluate_answers(cases, answer)
    metrics = cast(dict[str, Any], report["metrics"])

    assert metrics["recall_at_5"] >= 0.85
    assert metrics["citation_validity"] == 1.0
    assert metrics["answerability_accuracy"] >= 0.90
    assert metrics["abstention_accuracy"] >= 0.90
    assert metrics["multi_hop_accuracy"] == 1.0
