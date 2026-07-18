from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from document_enhancer.retrieval.catalog import RagCatalog, RagCatalogBuilder
from document_enhancer.retrieval.corpus import CorpusAnswerer, plan_query
from document_enhancer.retrieval.embeddings import DeterministicEmbeddings
from document_enhancer.retrieval.models import (
    CorpusAttribute,
    CorpusMapEnvelope,
    CorpusMapItem,
)

from .helpers import write_bundle


class _QuestionDrivenMapAgent:
    def invoke(self, state: dict[str, Any], config: object) -> dict[str, object]:
        assert config
        prompt = state["messages"][0]["content"]
        cards = json.loads(prompt.split("Evidence JSON:\n", 1)[1])
        items = []
        for card in cards:
            text = card["text"]
            if "reconcil" not in text.lower():
                continue
            control_id = next(
                (word.strip(".,:;()") for word in text.split() if word.startswith("CTRL-")),
                "",
            )
            items.append(
                CorpusMapItem(
                    item_key=control_id,
                    statement=f"{control_id} contains a reconciliation step.",
                    attributes=(
                        CorpusAttribute(name="control", value=control_id),
                        CorpusAttribute(name="reconciliation_step", value=text),
                    ),
                    citation_ids=(card["evidence_id"],),
                )
            )
        return {"structured_response": CorpusMapEnvelope(items=tuple(items))}


class _CandidateReducer:
    def invoke(self, state: dict[str, Any], config: object) -> dict[str, object]:
        assert config
        prompt = state["messages"][0]["content"]
        candidates = json.loads(prompt.split("Candidate JSON:\n", 1)[1])
        return {"structured_response": CorpusMapEnvelope.model_validate({"items": candidates})}


def _factory(**kwargs: Any) -> _QuestionDrivenMapAgent | _CandidateReducer:
    assert kwargs["tools"] == []
    return (
        _CandidateReducer()
        if kwargs["name"] == "document_enhancer_corpus_reduce"
        else _QuestionDrivenMapAgent()
    )


def _catalog(tmp_path: Path) -> tuple[Path, DeterministicEmbeddings]:
    first = write_bundle(
        tmp_path / "runs",
        "run-a",
        "# Payments\n\n## Controls\n\nCTRL-PAY-001 reconciles settlement totals to the ledger.\n",
    )
    second = write_bundle(
        tmp_path / "runs",
        "run-b",
        "# Access\n\n## Controls\n\nCTRL-IAM-002 reviews privileged access quarterly.\n",
    )
    third = write_bundle(
        tmp_path / "runs",
        "run-c",
        "# Models\n\n## Controls\n\nCTRL-MOD-003 performs a monthly reconciliation of labels and outcomes.\n",
    )
    embeddings = DeterministicEmbeddings()
    path = tmp_path / "catalog"
    RagCatalogBuilder(path, embeddings).build([first, second, third])
    return path, embeddings


@pytest.mark.unit
def test_query_plan_routes_focused_and_arbitrary_corpus_questions() -> None:
    focused = plan_query("What is the payment threshold?")
    corpus = plan_query("List all controls with reconciliation steps from all documents")
    exhaustive = plan_query("What owners are named?", coverage="exhaustive")

    assert focused.scope == "focused"
    assert corpus.scope == "corpus" and corpus.intent == "enumerate"
    assert exhaustive.scope == "corpus" and exhaustive.coverage == "exhaustive"
    with pytest.raises(ValueError, match="scope"):
        plan_query("Question", scope="invalid")  # ty: ignore[invalid-argument-type]


@pytest.mark.unit
def test_exhaustive_corpus_map_scans_every_document_and_compiles_dynamic_items(
    tmp_path: Path,
) -> None:
    path, embeddings = _catalog(tmp_path)
    with RagCatalog.open(path, embeddings) as catalog:
        result = CorpusAnswerer(catalog, object(), agent_factory=_factory).answer(
            "List all controls with reconciliation steps from all documents",
            coverage="exhaustive",
        )

    assert result.status == "answered"
    assert {item.item_key for item in result.items} == {"CTRL-PAY-001", "CTRL-MOD-003"}
    assert {source.run_id for source in result.sources} == {"run-a", "run-c"}
    assert result.coverage.documents_scanned == 3
    assert result.coverage.documents_with_matches == 2
    assert result.coverage.chunks_examined == result.coverage.chunks_available
    assert not result.coverage.failed_run_ids
    assert not result.coverage.truncated


@pytest.mark.unit
def test_corpus_map_applies_run_selection_and_fails_closed_on_invalid_citations(
    tmp_path: Path,
) -> None:
    path, embeddings = _catalog(tmp_path)

    class InvalidAgent:
        def invoke(self, state: object, config: object) -> dict[str, object]:
            return {
                "structured_response": CorpusMapEnvelope(
                    items=(
                        CorpusMapItem(
                            statement="Unsupported",
                            citation_ids=("E999",),
                        ),
                    )
                )
            }

    with RagCatalog.open(path, embeddings) as catalog:
        selected = CorpusAnswerer(catalog, object(), agent_factory=_factory).answer(
            "List controls with reconciliation steps",
            run_ids=["run-a"],
            coverage="retrieval",
        )
        invalid = CorpusAnswerer(
            catalog,
            object(),
            agent_factory=lambda **_: InvalidAgent(),
            reducer_factory=_factory,
        ).answer("List controls", run_ids=["run-a"], coverage="exhaustive")

    assert {source.run_id for source in selected.sources} == {"run-a"}
    assert selected.coverage.documents_requested == 1
    assert invalid.status == "insufficient"
    assert invalid.coverage.failed_run_ids == ("run-a",)
    assert not invalid.items and not invalid.sources


@pytest.mark.unit
def test_corpus_reduction_deduplicates_stable_keys_across_batches() -> None:
    first = CorpusMapItem(
        item_key="CTRL-PAY-001",
        statement="CTRL-PAY-001 reconciles settlement totals.",
        citation_ids=("E1",),
    )
    repeated = CorpusMapItem(
        item_key="ctrl-pay-001",
        statement="The payment reconciliation control is CTRL-PAY-001.",
        citation_ids=("E9",),
    )

    assert CorpusAnswerer._deduplicate((first, repeated)) == [first]


@pytest.mark.unit
def test_corpus_reducer_fails_closed_on_new_citation(tmp_path: Path) -> None:
    path, embeddings = _catalog(tmp_path)

    class InvalidReducer:
        def invoke(self, state: object, config: object) -> dict[str, object]:
            return {
                "structured_response": CorpusMapEnvelope(
                    items=(
                        CorpusMapItem(
                            item_key="CTRL-PAY-001",
                            statement="Unsupported reduced item.",
                            citation_ids=("E999",),
                        ),
                    )
                )
            }

    with RagCatalog.open(path, embeddings) as catalog:
        result = CorpusAnswerer(
            catalog,
            object(),
            agent_factory=_factory,
            reducer_factory=lambda **_: InvalidReducer(),
        ).answer(
            "List controls with reconciliation steps",
            run_ids=["run-a"],
            coverage="exhaustive",
        )

    assert result.status == "insufficient"
    assert result.coverage.reduction_failed
    assert not result.coverage.truncated
    assert result.trace[-1].tool == "corpus_reduce"
    assert result.trace[-1].status == "failed:ValueError"
