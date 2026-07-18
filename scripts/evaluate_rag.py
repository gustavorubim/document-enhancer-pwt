"""Run the compact cited-answer evaluation against a promoted local RAG catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

from document_enhancer.cli import _load_project_env, _rag_embeddings
from document_enhancer.config import load_config
from document_enhancer.retrieval.agent import RagAnswerer, gemini_chat_model
from document_enhancer.retrieval.catalog import RagCatalog, read_catalog_profile
from document_enhancer.retrieval.evaluation import EvaluationCase, evaluate_answers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path(".document-enhancer/rag/catalog"))
    parser.add_argument("--questions", type=Path, default=Path("fixtures/rag/questions.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.questions.read_text(encoding="utf-8"))
    cases = [EvaluationCase.model_validate(item) for item in raw]
    _load_project_env()
    config = load_config()
    profile = read_catalog_profile(args.catalog)
    embeddings = _rag_embeddings(offline=profile.provider == "offline", profile=profile)
    with RagCatalog.open(args.catalog, embeddings) as catalog:
        answerer = RagAnswerer(catalog, gemini_chat_model(config))
        report = evaluate_answers(
            cases,
            lambda case: answerer.answer(case.question),
        )
    rendered = json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    metrics = cast(dict[str, Any], report["metrics"])
    return (
        0
        if (
            float(metrics["recall_at_5"]) >= 0.85
            and float(metrics["citation_validity"]) == 1.0
            and float(metrics["abstention_accuracy"]) >= 0.90
        )
        else 1
    )


def _json_default(value: Any) -> str:
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
