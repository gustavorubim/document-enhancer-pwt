"""Stable, human-oriented paths for one file-backed run bundle."""

from __future__ import annotations

RUN_RECORD = "json/00-run.json"
RECIPE = "json/01-recipe.json"
SOURCE_METADATA = "json/02-source.json"
STRUCTURE_QUALITY = "json/03-structure-quality.json"
STRUCTURE_ROUTING = "json/04-structure-routing.json"
REVIEW = "json/05-review.json"
DECISIONS_JSON = "json/06-decisions.json"
REWRITE_PLAN = "json/07-rewrite-plan.json"
SEMANTIC = "json/08-semantic.json"
ONTOLOGY = "json/09-ontology.json"
SEMANTIC_DIFF = "json/10-semantic-diff.json"
AUDIT = "json/11-audit.json"
SEAL = "json/12-seal.json"

SOURCE_MARKDOWN = "markdown/01-source-normalized.md"
REVIEW_INDEX_MARKDOWN = "markdown/02-review-overview.md"
MACRO_MARKDOWN = "markdown/03-macro-review.md"
SECTIONS_MARKDOWN = "markdown/04-section-review.md"
FLOW_MARKDOWN = "markdown/05-process-flow-review.md"
QUESTIONS_MARKDOWN = "markdown/06-review-questions.md"
FINAL_MARKDOWN = "markdown/07-final-document.md"
CHANGES_MARKDOWN = "markdown/08-change-explanation.md"
AUDIT_MARKDOWN = "markdown/09-final-audit.md"

DECISIONS_YAML = "review/decisions.yaml"
INFERRED_FLOW = "diagrams/01-inferred-flow.mmd"
PROPOSED_FLOW = "diagrams/02-proposed-flow.mmd"
FINAL_FLOW = "diagrams/03-final-flow.mmd"

GRAPH_JSONL = "data/graph.jsonl"
SOURCE_TO_TARGET_CSV = "data/source-to-target.csv"
ORIGINAL_DOCUMENT_PREFIX = "documents/original"
FINAL_DOCX = "documents/final.docx"
HTML_REPORT = "report.html"
SOURCE_ASSET_PREFIX = "assets/source"
FINAL_ASSET_PREFIX = "assets/final"


__all__ = [
    "AUDIT",
    "AUDIT_MARKDOWN",
    "CHANGES_MARKDOWN",
    "DECISIONS_JSON",
    "DECISIONS_YAML",
    "FINAL_DOCX",
    "FINAL_FLOW",
    "FINAL_MARKDOWN",
    "FLOW_MARKDOWN",
    "FINAL_ASSET_PREFIX",
    "GRAPH_JSONL",
    "HTML_REPORT",
    "INFERRED_FLOW",
    "MACRO_MARKDOWN",
    "ONTOLOGY",
    "ORIGINAL_DOCUMENT_PREFIX",
    "PROPOSED_FLOW",
    "QUESTIONS_MARKDOWN",
    "RECIPE",
    "REVIEW",
    "REVIEW_INDEX_MARKDOWN",
    "REWRITE_PLAN",
    "RUN_RECORD",
    "SEAL",
    "SECTIONS_MARKDOWN",
    "SEMANTIC",
    "SEMANTIC_DIFF",
    "SOURCE_MARKDOWN",
    "SOURCE_METADATA",
    "SOURCE_ASSET_PREFIX",
    "SOURCE_TO_TARGET_CSV",
    "STRUCTURE_QUALITY",
    "STRUCTURE_ROUTING",
]
